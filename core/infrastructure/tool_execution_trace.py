"""Content-free phase diagnostics for synchronous tool lifecycle waits.

The observer never cancels a callback, changes a tool result, or publishes an
EventBus event. In particular, its warning threshold is not a tool deadline.
"""

from __future__ import annotations

import sys
import queue
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from pathlib import Path
from typing import Any, Iterator


_STALL_SECONDS = 5.0
_OBSERVER_SLOTS = threading.BoundedSemaphore(4)
_CURRENT_TRACE: ContextVar["ToolExecutionTrace | None"] = ContextVar("tool_execution_trace", default=None)


def _emit(event_code: str, fields: dict[str, Any], *, warning: bool = False) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool_executor", "execution_phase", event_code,
            level="warning" if warning else "info",
            outcome="waiting" if warning else "observed",
            message="Tool execution phase diagnostic.", fields=fields,
        )
    except Exception:
        # Diagnostics must never alter an authoritative tool result.
        pass


def _thread_stack(thread_id: int) -> list[dict[str, Any]]:
    frame = sys._current_frames().get(thread_id)
    frames: list[dict[str, Any]] = []
    try:
        while frame is not None and len(frames) < 12:
            frames.append({
                "file": Path(frame.f_code.co_filename).name,
                "function": frame.f_code.co_name,
                "line": frame.f_lineno,
            })
            frame = frame.f_back
    finally:
        del frame
    return frames


class ToolExecutionTrace:
    def __init__(self, tool_name: str, tool_call_id: str) -> None:
        self.identity = {"toolName": str(tool_name)[:120], "toolCallId": str(tool_call_id)[:160]}
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._phase: dict[str, Any] | None = None
        self._serial = 0
        self._watcher: threading.Thread | None = None
        self._events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(maxsize=64)
        self._disabled = False

    def bind(self, **identity: str) -> None:
        with self._lock:
            self.identity.update({key: str(value)[:160] for key, value in identity.items()})

    def record(self, event_code: str, **facts: Any) -> None:
        if self._disabled:
            return
        with self._lock:
            fields = {**self.identity, **facts}
        try:
            self._events.put_nowait((event_code, fields))
        except queue.Full:
            # This is lossy diagnostic telemetry, never authoritative history.
            pass

    def _start_observer(self) -> None:
        if self._watcher is not None or self._disabled:
            return
        slots = _OBSERVER_SLOTS
        if not slots.acquire(blocking=False):
            self._disabled = True
            return
        try:
            context = copy_context()

            def observe() -> None:
                try:
                    context.run(self._observe)
                finally:
                    slots.release()

            watcher = threading.Thread(
                target=observe, name="tool-phase-observer", daemon=True,
            )
            watcher.start()
            self._watcher = watcher
        except (RuntimeError, OSError):
            # Resource exhaustion in diagnostics must not reject a real tool.
            self._disabled = True
            slots.release()

    @contextmanager
    def phase(self, name: str, **facts: Any) -> Iterator[None]:
        started = time.monotonic()
        with self._lock:
            self._serial += 1
            serial = self._serial
            self._phase = {"phase": name, "started": started, "serial": serial,
                           "threadId": threading.get_ident(), **facts}
        self.record("tool.execution.phase_started", phase=name, **facts)
        self._start_observer()
        try:
            yield
        finally:
            self.record("tool.execution.phase_finished", phase=name,
                        durationMs=max(0, int((time.monotonic() - started) * 1000)), **facts)
            with self._lock:
                if self._phase is not None and self._phase["serial"] == serial:
                    self._phase = None

    def _observe(self) -> None:
        warned_serial = 0
        interval = min(0.25, max(0.01, _STALL_SECONDS / 4))
        while not self._finished.is_set() or not self._events.empty():
            try:
                item = self._events.get(timeout=interval)
            except queue.Empty:
                item = None
            if item is not None:
                try:
                    _emit(*item)
                except Exception:
                    pass
            if self._finished.is_set():
                continue
            with self._lock:
                phase = dict(self._phase or {})
                identity = dict(self.identity)
            if not phase or phase["serial"] == warned_serial:
                continue
            elapsed = time.monotonic() - phase["started"]
            if elapsed < _STALL_SECONDS:
                continue
            warned_serial = phase["serial"]
            _emit("tool.execution.phase_waiting", {
                **identity,
                **{key: value for key, value in phase.items() if key not in {"serial", "started"}},
                "durationMs": max(0, int(elapsed * 1000)),
                "diagnosticThresholdSeconds": _STALL_SECONDS,
                "stack": _thread_stack(phase["threadId"]),
            }, warning=phase["phase"].startswith("notify."))

    def close(self) -> None:
        self._finished.set()
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        if self._watcher is not None:
            self._watcher.join(timeout=0.1)


@contextmanager
def trace_tool_execution(tool_name: str, tool_call_id: str) -> Iterator[ToolExecutionTrace]:
    trace = ToolExecutionTrace(tool_name, tool_call_id)
    token = _CURRENT_TRACE.set(trace)
    try:
        yield trace
    finally:
        trace.close()
        _CURRENT_TRACE.reset(token)


def record_tool_process_event(event_code: str, **facts: Any) -> None:
    trace = _CURRENT_TRACE.get()
    if trace is not None:
        trace.record(event_code, **facts)
