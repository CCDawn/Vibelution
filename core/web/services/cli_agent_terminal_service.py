"""Persistent terminal sessions for configured CLI Agent adapters."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import cli_agent_service
from . import cli_agent_task_kernel
from .terminal_screen_buffer import TerminalScreenBuffer, TerminalScreenSnapshot
from core.logging import debug as _debug_logger

try:  # pragma: no cover - availability is platform/package dependent
    from winpty import PtyProcess
except Exception:  # pragma: no cover - fallback is covered by unit tests
    PtyProcess = None  # type: ignore[assignment]


PROJECT_ROOT = cli_agent_service.PROJECT_ROOT
RUNTIME_ROOT = PROJECT_ROOT / ".runtime" / "cli_agents"
SESSION_STATE_DIR = RUNTIME_ROOT / "sessions"
TRANSCRIPT_DIR = RUNTIME_ROOT / "transcripts"
DEFAULT_ROWS = 28
DEFAULT_COLS = 100
MAX_TRANSCRIPT_TAIL_CHARS = 120000
MAX_TRANSCRIPT_BYTES = 1_500_000
TRANSCRIPT_TRIM_TARGET_BYTES = 900_000
STREAM_HEARTBEAT_SECONDS = 15
STREAM_QUEUE_SIZE = 200
DEFAULT_DISCOVERY_POLL_ATTEMPTS = 8
DEFAULT_DISCOVERY_POLL_INTERVAL_SECONDS = 0.75
DEFAULT_DISCOVERY_CREATED_GRACE_MS = 5000
DEFAULT_DISCOVERY_MAX_ROWS = 80
SCREEN_BUFFER_PARSER_VERSION = 2
SCREEN_STATE_FIELD_KEYS = (
    "screenText",
    "screenReplay",
    "screenQuality",
    "screenRows",
    "screenCols",
    "screenParserVersion",
)


class CliAgentTerminalError(Exception):
    """Raised when a CLI Agent terminal session cannot be created or used."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class _TerminalRuntime:
    def __init__(
        self,
        *,
        state: dict[str, Any],
        process: Any,
        transport: str,
        transcript_path: Path,
        session_id_regex: str,
    ) -> None:
        self.state = state
        self.process = process
        self.transport = transport
        self.transcript_path = transcript_path
        self.session_id_regex = session_id_regex
        self.screen = TerminalScreenBuffer(
            rows=_clamp_int(state.get("rows"), DEFAULT_ROWS, 4, 120),
            cols=_clamp_int(state.get("cols"), DEFAULT_COLS, 20, 240),
            initial_text=_screen_initial_text(state),
        )
        self.subscribers: list[queue.Queue[dict[str, Any]]] = []
        self.stop_requested = threading.Event()
        self.lock = threading.RLock()
        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"cli-agent-terminal-{state.get('terminalSessionId')}",
            daemon=True,
        )

    def start(self) -> None:
        self.reader_thread.start()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=STREAM_QUEUE_SIZE)
        with self.lock:
            self.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            self.subscribers = [item for item in self.subscribers if item is not subscriber]

    def send_input(self, data: str) -> None:
        if not data:
            return
        if self.transport == "conpty":
            self.process.write(data)
            return
        stdin = getattr(self.process, "stdin", None)
        if stdin is None:
            raise CliAgentTerminalError("TERMINAL_STDIN_UNAVAILABLE", "Terminal input is not available.")
        stdin.write(data)
        stdin.flush()

    def resize(self, rows: int, cols: int) -> None:
        rows = _clamp_int(rows, DEFAULT_ROWS, 4, 120)
        cols = _clamp_int(cols, DEFAULT_COLS, 20, 240)
        with self.lock:
            self.state["rows"] = rows
            self.state["cols"] = cols
            self.screen.resize(rows=rows, cols=cols)
            self.state.update(_terminal_screen_state_fields(self.screen.snapshot()))
            self.state["updatedAt"] = _now_iso()
            _write_state(self.state)
        if self.transport == "conpty":
            try:
                self.process.setwinsize(rows, cols)
            except Exception:
                return

    def stop(self) -> None:
        self.stop_requested.set()
        try:
            if self.transport == "conpty":
                try:
                    self.process.terminate(force=True)
                except TypeError:
                    self.process.terminate()
            else:
                self.process.terminate()
        except Exception as exc:
            _debug_logger.warning(
                f"Failed to terminate terminal process (transport={self.transport}): {exc}",
                tag="cli_terminal_process_stop",
            )

    def is_alive(self) -> bool:
        try:
            if self.transport == "conpty":
                return bool(self.process.isalive())
            return self.process.poll() is None
        except Exception:
            return False

    def snapshot(self, *, include_transcript_tail: bool = False) -> dict[str, Any]:
        with self.lock:
            self.state.update(_terminal_screen_state_fields(self.screen.snapshot()))
            payload = dict(self.state)
        payload["alive"] = self.is_alive()
        payload["transport"] = self.transport
        snapshot = (
            _read_transcript_snapshot_for_state(
                self.transcript_path,
                payload,
                include_transcript_tail=True,
            )
            if include_transcript_tail
            else _live_runtime_transcript_snapshot(payload)
        )
        payload = _merge_transcript_snapshot(payload, snapshot)
        return _public_state(payload)

    def _reader_loop(self) -> None:
        try:
            while not self.stop_requested.is_set():
                chunk = self._read_chunk()
                if not chunk:
                    if not self.is_alive():
                        break
                    time.sleep(0.05)
                    continue
                self._record_output(chunk)
        finally:
            with self.lock:
                self.state["status"] = "stopped" if self.stop_requested.is_set() else "exited"
                self.state["alive"] = False
                self.state["updatedAt"] = _now_iso()
                _write_state(self.state)
                final_state = _public_state(dict(self.state))
            self._publish({"type": "terminal_status", "session": final_state})
            cli_agent_service._record_event(
                "cli_agent.terminal.exited",
                outcome="stopped" if self.stop_requested.is_set() else "completed",
                fields={
                    "terminalSessionId": str(self.state.get("terminalSessionId") or ""),
                    "adapterId": str(self.state.get("adapterId") or ""),
                    "transport": self.transport,
                },
            )
            cli_agent_task_kernel.mark_terminal_closed(final_state, status=str(final_state.get("status") or "exited"))

    def _read_chunk(self) -> str:
        try:
            if self.transport == "conpty":
                return str(self.process.read() or "")
            stdout = getattr(self.process, "stdout", None)
            if stdout is None:
                return ""
            return str(stdout.read(1) or "")
        except Exception:
            return ""

    def _record_output(self, chunk: str) -> None:
        _append_transcript_chunk(self.transcript_path, chunk)
        next_cli_session_id = _extract_cli_session_id(chunk, self.session_id_regex)
        linked_session_id = ""
        with self.lock:
            if next_cli_session_id and not str(self.state.get("cliSessionId") or "").strip():
                self.state["cliSessionId"] = next_cli_session_id
                self.state["cliSessionIdSource"] = "stdout_regex"
                self.state["sessionDiscoveryStatus"] = "found"
                linked_session_id = next_cli_session_id
            self.state["status"] = "running"
            self.state["alive"] = True
            self.state.update(_terminal_screen_state_fields(self.screen.feed(chunk)))
            self.state["updatedAt"] = _now_iso()
            _write_state(self.state)
            public_state = _public_state(dict(self.state))
        if linked_session_id:
            _record_cli_agent_lifecycle_link(public_state, source="stdout_regex")
            self._publish({"type": "terminal_status", "session": public_state})
        cli_agent_task_kernel.ingest_terminal_output(public_state, chunk)
        self._publish({"type": "terminal_output", "chunk": chunk})

    def _publish(self, event: dict[str, Any]) -> None:
        with self.lock:
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except Exception:
                    continue


_RUNTIMES: dict[str, _TerminalRuntime] = {}
_RUNTIMES_LOCK = threading.RLock()


def ensure_cli_agent_terminal_session(
    *,
    agent_type: str,
    task: str = "",
    cwd: str = "",
    mode: str = "readonly",
    model: str = "",
    agent: str = "",
    source_session_id: str = "",
    source_message_id: str = "",
    source_run_id: str = "",
    cli_session_id: str = "",
    rows: int = DEFAULT_ROWS,
    cols: int = DEFAULT_COLS,
    send_initial_task: bool = False,
    allow_unsafe_permissions: bool = False,
    intent: str = "task",
) -> dict[str, Any]:
    """Return an attached or newly started terminal session for a configured CLI Agent."""

    normalized_intent = _normalize_terminal_intent(intent)
    normalized_type = cli_agent_service._normalize_id(agent_type)
    if not normalized_type:
        raise CliAgentTerminalError("MISSING_CLI_AGENT", "CLI Agent type is required.")
    normalized_source_session_id = str(source_session_id or "").strip()
    normalized_source_message_id = str(source_message_id or "").strip()
    normalized_source_run_id = str(source_run_id or "").strip()
    scope_cwd = _scope_cwd(cwd, mode=mode)
    terminal_session_id = _stable_terminal_session_id(
        adapter_id=normalized_type,
        source_session_id=normalized_source_session_id,
        source_message_id=normalized_source_message_id,
        source_run_id=normalized_source_run_id,
        cwd=scope_cwd or cwd,
        mode=mode,
        task=task,
    )
    lock_key = _stable_cli_lock_key(
        adapter_id=normalized_type,
        source_session_id=normalized_source_session_id,
        source_message_id=normalized_source_message_id,
        source_run_id=normalized_source_run_id,
        cwd=scope_cwd or cwd,
        mode=mode,
        task=task,
    )
    cli_run_id = _stable_cli_run_id(
        adapter_id=normalized_type,
        source_session_id=normalized_source_session_id,
        source_message_id=normalized_source_message_id,
        source_run_id=normalized_source_run_id,
        cwd=scope_cwd or cwd,
        mode=mode,
        task=task,
    )

    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(terminal_session_id)
        if runtime and runtime.is_alive():
            _link_runtime_source(
                runtime,
                source_message_id=normalized_source_message_id,
                source_run_id=normalized_source_run_id,
            )
            _supersede_related_terminal_states(runtime.state, keep_terminal_session_id=terminal_session_id)
            snapshot = runtime.snapshot()
            snapshot["reusedActiveLock"] = True
            return snapshot

        existing_state = _read_state(terminal_session_id)
        if not existing_state:
            existing_state = _find_related_terminal_state(
                cli_run_id=cli_run_id,
                lock_key=lock_key,
                adapter_id=normalized_type,
                source_session_id=normalized_source_session_id,
                cwd=scope_cwd or cwd,
                mode=mode,
                exclude_terminal_session_id=terminal_session_id,
            )
        related_live_runtime = _find_active_related_runtime(
            existing_state,
            cli_run_id=cli_run_id,
            lock_key=lock_key,
            adapter_id=normalized_type,
            source_session_id=normalized_source_session_id,
            cwd=scope_cwd or cwd,
            mode=mode,
            exclude_terminal_session_id=terminal_session_id,
        )
        if related_live_runtime is not None:
            _link_runtime_source(
                related_live_runtime,
                source_message_id=normalized_source_message_id,
                source_run_id=normalized_source_run_id,
            )
            keep_terminal_session_id = str(related_live_runtime.state.get("terminalSessionId") or "")
            _supersede_related_terminal_states(
                related_live_runtime.state,
                keep_terminal_session_id=keep_terminal_session_id,
            )
            snapshot = related_live_runtime.snapshot()
            snapshot["reusedActiveLock"] = True
            snapshot["reboundFromTerminalSessionId"] = str(
                (existing_state or {}).get("terminalSessionId") or terminal_session_id
            )
            return snapshot
        if normalized_intent == "view":
            if existing_state:
                return _public_state(
                    _merge_transcript_snapshot(
                        existing_state,
                        _read_transcript_snapshot(
                            _transcript_path(str(existing_state.get("terminalSessionId") or terminal_session_id))
                        ),
                    )
                )
            raise CliAgentTerminalError(
                "TERMINAL_SESSION_NOT_FOUND",
                "Terminal session history was not found.",
                details={
                    "terminalSessionId": terminal_session_id,
                    "interactionState": "closed",
                    "canInput": False,
                    "canResume": False,
                    "resumeAction": "none",
                    "displayMode": "readonly_replay",
                    "stateReason": "not_found",
                },
            )
        if _source_bound_attach_should_not_resume_stale_state(
            existing_state,
            source_session_id=normalized_source_session_id,
        ) and normalized_intent not in {"resume", "start"}:
            public_state = _public_state(
                _merge_transcript_snapshot(
                    existing_state,
                    _read_transcript_snapshot(
                        _transcript_path(str(existing_state.get("terminalSessionId") or terminal_session_id))
                    ),
                )
            )
            cli_agent_service._record_event(
                "cli_agent.terminal.stale_attach_skipped",
                outcome="skipped",
                fields={
                    "terminalSessionId": str(existing_state.get("terminalSessionId") or terminal_session_id),
                    "adapterId": normalized_type,
                    "sourceSessionId": normalized_source_session_id,
                    "status": str(existing_state.get("status") or ""),
                    "staleReason": str(existing_state.get("staleReason") or ""),
                },
            )
            return public_state
        if normalized_intent == "resume" and existing_state:
            status = str(existing_state.get("status") or "").strip().lower()
            if bool(existing_state.get("userClosed")) or status == "closed":
                raise CliAgentTerminalError(
                    "TERMINAL_SESSION_CLOSED",
                    "Terminal session was closed by the user and cannot be resumed automatically.",
                    details=_terminal_not_running_details(str(existing_state.get("terminalSessionId") or terminal_session_id)),
                )
        normalized_source_session_id = normalized_source_session_id or str(existing_state.get("sourceSessionId") or "").strip()
        normalized_source_message_id = normalized_source_message_id or str(existing_state.get("sourceMessageId") or "").strip()
        normalized_source_run_id = normalized_source_run_id or str(existing_state.get("sourceRunId") or "").strip()
        requested_task = task or str(existing_state.get("task") or "")
        requested_cwd = cwd or str(existing_state.get("cwd") or "")
        requested_mode = mode or str(existing_state.get("mode") or "readonly")
        requested_model = model or str(existing_state.get("model") or "")
        requested_agent = agent or str(existing_state.get("agent") or "")
        existing_cli_session_id = str(cli_session_id or "").strip()
        if normalized_intent != "start":
            existing_cli_session_id = existing_cli_session_id or str(existing_state.get("cliSessionId") or "")
        if not existing_cli_session_id and existing_state:
            existing_cli_session_id = _discover_existing_cli_session_id(
                agent_type=normalized_type,
                state={
                    **existing_state,
                    "cwd": requested_cwd or existing_state.get("cwd") or "",
                },
            )
            if existing_cli_session_id:
                existing_state = {
                    **existing_state,
                    "cliSessionId": existing_cli_session_id,
                    "cliSessionIdSource": "session_discovery_existing",
                }
        command = _build_terminal_command(
            agent_type=normalized_type,
            task=requested_task,
            cwd=requested_cwd,
            mode=requested_mode,
            model=requested_model,
            agent=requested_agent,
            cli_session_id=existing_cli_session_id,
            allow_unsafe_permissions=allow_unsafe_permissions,
        )
        lock_key = _stable_cli_lock_key(
            adapter_id=normalized_type,
            source_session_id=normalized_source_session_id,
            source_message_id=normalized_source_message_id,
            source_run_id=normalized_source_run_id,
            cwd=str(command.get("cwd") or cwd or ""),
            mode=str(command.get("mode") or requested_mode or "readonly"),
            task=requested_task,
        )
        cli_run_id = _stable_cli_run_id(
            adapter_id=normalized_type,
            source_session_id=normalized_source_session_id,
            source_message_id=normalized_source_message_id,
            source_run_id=normalized_source_run_id,
            cwd=str(command.get("cwd") or cwd or ""),
            mode=str(command.get("mode") or requested_mode or "readonly"),
            task=requested_task,
        )
        locked_runtime = _find_active_locked_runtime(lock_key, exclude_terminal_session_id=terminal_session_id)
        if locked_runtime is not None:
            _link_runtime_source(
                locked_runtime,
                source_message_id=normalized_source_message_id,
                source_run_id=normalized_source_run_id,
            )
            _supersede_related_terminal_states(
                locked_runtime.state,
                keep_terminal_session_id=str(locked_runtime.state.get("terminalSessionId") or ""),
            )
            snapshot = locked_runtime.snapshot()
            snapshot["reusedActiveLock"] = True
            return snapshot
        state = _initial_state(
            terminal_session_id=terminal_session_id,
            command=command,
            task=requested_task,
            source_session_id=normalized_source_session_id,
            source_message_id=normalized_source_message_id,
            source_run_id=normalized_source_run_id,
            cli_run_id=cli_run_id,
            lock_key=lock_key,
            rows=rows,
            cols=cols,
            previous_state=existing_state,
        )
        process, transport = _spawn_terminal_process(command["args"], cwd=command["cwd"], rows=rows, cols=cols)
        state["transport"] = transport
        state["alive"] = True
        state["status"] = "running"
        transcript_path = _transcript_path(terminal_session_id)
        state["transcriptPath"] = _relative_to_project(transcript_path)
        _write_state(state)
        _supersede_related_terminal_states(state, keep_terminal_session_id=terminal_session_id)
        runtime = _TerminalRuntime(
            state=state,
            process=process,
            transport=transport,
            transcript_path=transcript_path,
            session_id_regex=str(command.get("sessionIdRegex") or ""),
        )
        _RUNTIMES[terminal_session_id] = runtime
        runtime.start()
        if send_initial_task:
            _send_initial_task(runtime, str(command.get("initialInput") or ""))
        _schedule_session_id_discovery(runtime, command.get("sessionDiscovery"))
        cli_agent_service._record_event(
            "cli_agent.terminal.started",
            outcome="started",
            fields={
                "terminalSessionId": terminal_session_id,
                "cliRunId": cli_run_id,
                "lockKey": lock_key,
                "adapterId": normalized_type,
                "cwd": str(command.get("cwd") or ""),
                "mode": str(command.get("mode") or ""),
                "transport": transport,
                "resumed": bool(command.get("resumed")),
                "commandPreview": list(command.get("preview") or []),
            },
        )
        return runtime.snapshot()


def get_cli_agent_terminal_session(terminal_session_id: str, *, include_transcript_tail: bool = False) -> dict[str, Any]:
    session_id = _normalize_terminal_session_id(terminal_session_id)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
        if runtime:
            return runtime.snapshot(include_transcript_tail=include_transcript_tail)
        state = _read_state(session_id)
        if not state:
            raise CliAgentTerminalError("TERMINAL_SESSION_NOT_FOUND", "Terminal session not found.")
        related_live_runtime = _find_active_related_runtime(
            state,
            exclude_terminal_session_id=session_id,
        )
        if related_live_runtime is not None:
            snapshot = related_live_runtime.snapshot(include_transcript_tail=include_transcript_tail)
            snapshot["reusedActiveLock"] = True
            snapshot["reboundFromTerminalSessionId"] = session_id
            return snapshot
    state["alive"] = False
    return _public_state(
        _merge_transcript_snapshot(
            state,
            _read_transcript_snapshot_for_state(
                _transcript_path(session_id),
                state,
                include_transcript_tail=include_transcript_tail,
            ),
        )
    )


def _source_bound_attach_should_not_resume_stale_state(state: dict[str, Any], *, source_session_id: str) -> bool:
    if not state or not str(source_session_id or "").strip():
        return False
    status = str(state.get("status") or "").strip().lower()
    if status != "stale":
        return False
    return bool(str(state.get("terminalSessionId") or "").strip())


def _normalize_terminal_intent(intent: str) -> str:
    normalized = str(intent or "task").strip().lower()
    if normalized in {"task", "view", "resume", "start"}:
        return normalized
    return "task"


def _terminal_action_ack(runtime: _TerminalRuntime, *, action: str) -> dict[str, Any]:
    with runtime.lock:
        state = dict(runtime.state)
    rows = _clamp_int(state.get("rows"), DEFAULT_ROWS, 4, 120)
    cols = _clamp_int(state.get("cols"), DEFAULT_COLS, 20, 240)
    payload = {
        "status": "accepted",
        "semanticStatus": "accepted",
        "code": "CLI_AGENT_TERMINAL_INPUT_ACCEPTED" if action == "input" else "CLI_AGENT_TERMINAL_RESIZE_ACCEPTED",
        "action": action,
        "terminalSessionId": str(state.get("terminalSessionId") or "").strip(),
        "alive": runtime.is_alive(),
        "rows": rows,
        "cols": cols,
        "updatedAt": str(state.get("updatedAt") or "").strip(),
    }
    payload.update(_terminal_interaction_fields({**state, "alive": runtime.is_alive()}))
    return payload


def stream_cli_agent_terminal_events(terminal_session_id: str):
    session_id = _normalize_terminal_session_id(terminal_session_id)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
        if runtime is None:
            state = _read_state(session_id)
            runtime = _find_active_related_runtime(state, exclude_terminal_session_id=session_id)
    if runtime is None:
        yield _encode_sse_event(
            "terminal_snapshot",
            {
                "type": "terminal_snapshot",
                "session": get_cli_agent_terminal_session(session_id),
            },
        )
        return

    subscriber = runtime.subscribe()
    try:
        yield _encode_sse_event(
            "terminal_snapshot",
            {
                "type": "terminal_snapshot",
                "session": runtime.snapshot(),
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_sse_event(str(event.get("type") or "terminal_event"), event)
            if str(event.get("type") or "") == "terminal_status":
                session = event.get("session") if isinstance(event.get("session"), dict) else {}
                if not bool(session.get("alive")):
                    break
    finally:
        runtime.unsubscribe(subscriber)


def write_cli_agent_terminal_input(terminal_session_id: str, data: str) -> dict[str, Any]:
    runtime = _require_runtime(terminal_session_id)
    runtime.send_input(str(data or ""))
    return _terminal_action_ack(runtime, action="input")


def resize_cli_agent_terminal_session(terminal_session_id: str, rows: int, cols: int) -> dict[str, Any]:
    runtime = _require_runtime(terminal_session_id)
    runtime.resize(rows, cols)
    return _terminal_action_ack(runtime, action="resize")


def stop_cli_agent_terminal_session(terminal_session_id: str) -> dict[str, Any]:
    session_id = _normalize_terminal_session_id(terminal_session_id)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
        runtime_state = dict(runtime.state) if runtime is not None else {}
    state = runtime_state or _read_state(session_id)
    if not state:
        raise CliAgentTerminalError("TERMINAL_SESSION_NOT_FOUND", "Terminal session not found.")

    related_ids = _related_terminal_session_ids(state)
    if session_id not in related_ids:
        related_ids.insert(0, session_id)
    closed_ids: list[str] = []
    now = _now_iso()
    with _RUNTIMES_LOCK:
        for related_id in related_ids:
            related_runtime = _RUNTIMES.get(related_id)
            if related_runtime is not None and related_runtime.is_alive():
                related_runtime.stop()
            related_state = dict(related_runtime.state) if related_runtime is not None else _read_state(related_id)
            if not related_state:
                continue
            _mark_terminal_state_closed(related_state, closed_at=now, closed_ids=related_ids)
            if related_runtime is not None:
                with related_runtime.lock:
                    related_runtime.state.update(related_state)
                    _write_state(related_runtime.state)
            else:
                _write_state(related_state)
            closed_ids.append(related_id)
    final_state = _read_state(session_id) or state
    final_state["closedTerminalSessionIds"] = closed_ids
    return _public_state(
        _merge_transcript_snapshot(
            final_state,
            _read_transcript_snapshot(_transcript_path(session_id)),
        )
    )


def shutdown_cli_agent_terminal_sessions() -> None:
    with _RUNTIMES_LOCK:
        runtimes = list(_RUNTIMES.values())
        _RUNTIMES.clear()
    for runtime in runtimes:
        runtime.stop()


def reconcile_cli_agent_terminal_states_on_startup(*, reason: str = "backend_startup") -> dict[str, Any]:
    """Mark persisted running terminal states stale when no in-memory runtime owns them."""

    now = _now_iso()
    stale_ids: list[str] = []
    with _RUNTIMES_LOCK:
        live_ids = {
            terminal_session_id
            for terminal_session_id, runtime in list(_RUNTIMES.items())
            if runtime.is_alive()
        }
        for state in _iter_terminal_states():
            terminal_session_id = str(state.get("terminalSessionId") or "").strip()
            if not terminal_session_id or terminal_session_id in live_ids:
                continue
            status = str(state.get("status") or "").strip().lower()
            if bool(state.get("userClosed")) or status in {"closed", "stopped", "exited", "stale"}:
                continue
            if not bool(state.get("alive")) and status not in {"running", "starting", "stopping"}:
                continue
            state["status"] = "stale"
            state["alive"] = False
            state["staleAt"] = now
            state["staleReason"] = str(reason or "backend_startup")
            state["updatedAt"] = now
            _write_state(state)
            stale_ids.append(terminal_session_id)
    if stale_ids:
        cli_agent_service._record_event(
            "cli_agent.terminal.startup_reconciled",
            outcome="stale_states_marked",
            fields={
                "staleCount": len(stale_ids),
                "staleTerminalSessionIds": stale_ids[:20],
                "reason": str(reason or "backend_startup"),
            },
        )
    return {"staleCount": len(stale_ids), "staleTerminalSessionIds": stale_ids}


def _require_runtime(terminal_session_id: str) -> _TerminalRuntime:
    session_id = _normalize_terminal_session_id(terminal_session_id)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
    if runtime is None or not runtime.is_alive():
        raise CliAgentTerminalError(
            "TERMINAL_SESSION_NOT_RUNNING",
            "Terminal session is not running.",
            details=_terminal_not_running_details(session_id),
        )
    return runtime


def _build_terminal_command(
    *,
    agent_type: str,
    task: str,
    cwd: str,
    mode: str,
    model: str,
    agent: str,
    cli_session_id: str,
    allow_unsafe_permissions: bool = False,
) -> dict[str, Any]:
    adapters = cli_agent_service._load_adapter_definitions()
    adapter = adapters.get(agent_type)
    if not adapter:
        raise CliAgentTerminalError("UNSUPPORTED_CLI_AGENT", f"Unsupported CLI agent type: {agent_type}")
    terminal = adapter.get("terminal") if isinstance(adapter.get("terminal"), dict) else {}
    if not terminal.get("enabled"):
        raise CliAgentTerminalError("TERMINAL_NOT_SUPPORTED", f"{adapter.get('label') or agent_type} does not support terminal sessions.")
    executable = cli_agent_service._resolve_executable(adapter)
    if not executable:
        raise CliAgentTerminalError("CLI_AGENT_NOT_FOUND", f"{adapter.get('label') or agent_type} executable was not found.")
    normalized_mode = str(mode or "readonly").strip().lower()
    if normalized_mode not in cli_agent_service.SUPPORTED_MODES:
        raise CliAgentTerminalError("UNSUPPORTED_MODE", f"Unsupported CLI agent mode: {normalized_mode}")
    cwd_result = cli_agent_service._resolve_run_cwd(cwd, mode=normalized_mode)
    if not cwd_result.get("ok"):
        raise CliAgentTerminalError(
            str(cwd_result.get("code") or "INVALID_CWD"),
            str(cwd_result.get("message") or "Invalid CLI agent working directory."),
        )
    run_cwd = str(cwd_result["cwd"])
    resume_spec = terminal.get("resume") if isinstance(terminal.get("resume"), dict) else {}
    launch_spec = terminal.get("launch") if isinstance(terminal.get("launch"), dict) else {}
    use_resume = bool(str(cli_session_id or "").strip()) and bool(resume_spec.get("argv"))
    spec = resume_spec if use_resume else launch_spec
    argv_template = spec.get("argv")
    if not isinstance(argv_template, list) or not argv_template:
        raise CliAgentTerminalError("TERMINAL_PROTOCOL_INVALID", "CLI Agent terminal argv template is missing.")

    context = {
        "exe": executable,
        "cwd": run_cwd,
        "task": task,
        "mode": normalized_mode,
        "model": str(model or adapter.get("defaultModel") or ""),
        "agent": str(agent or adapter.get("defaultAgent") or ""),
        "cliSessionId": str(cli_session_id or ""),
        "permissionMode": _terminal_permission_mode(agent_type, normalized_mode),
    }
    executable_args = _terminal_executable_args(executable)
    args = _render_terminal_argv_template(argv_template, context, executable_args)
    initial_input = "" if use_resume else _render_template_arg(str(terminal.get("initialInput") or ""), context)
    session_id_spec = terminal.get("sessionId") if isinstance(terminal.get("sessionId"), dict) else {}
    session_discovery_spec = terminal.get("sessionDiscovery") if isinstance(terminal.get("sessionDiscovery"), dict) else {}
    if (
        str(mode or "").strip().lower() == "worktree"
        and bool(allow_unsafe_permissions)
        and cli_agent_service._normalize_id(agent_type) == "claude_code"
    ):
        args.append("--dangerously-skip-permissions")
    return {
        "adapterId": agent_type,
        "label": str(adapter.get("label") or agent_type),
        "args": args,
        "preview": _redacted_preview(args, task=task),
        "cwd": run_cwd,
        "mode": normalized_mode,
        "task": task,
        "model": context["model"],
        "agent": context["agent"],
        "cliSessionId": context["cliSessionId"],
        "initialInput": initial_input,
        "sessionIdRegex": str(session_id_spec.get("regex") or ""),
        "sessionDiscovery": dict(session_discovery_spec),
        "resumed": use_resume,
    }


def _render_terminal_argv_template(
    argv_template: list[Any],
    context: dict[str, str],
    executable_args: list[str],
) -> list[str]:
    args: list[str] = []
    for item in argv_template:
        raw = str(item)
        if raw == "{exe}":
            args.extend(executable_args)
            continue
        rendered = _render_template_arg(raw, context)
        if rendered:
            args.append(rendered)
    return args


def _terminal_executable_args(executable: str) -> list[str]:
    expanded = _resolve_windows_npm_cmd_shim(executable)
    if expanded:
        return expanded
    return [executable]


def _resolve_windows_npm_cmd_shim(executable: str) -> list[str]:
    if not _is_windows_platform():
        return []
    path = Path(str(executable or "")).expanduser()
    if path.suffix.lower() != ".cmd" or not path.exists():
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    match = re.search(r"%dp0%[\\/](node_modules[\\/][^\"]+)", source, flags=re.IGNORECASE)
    if not match:
        return []
    relative_parts = [part for part in re.split(r"[\\/]+", match.group(1)) if part]
    if not relative_parts:
        return []
    script_path = path.parent.joinpath(*relative_parts)
    if not script_path.exists():
        return []
    if script_path.suffix.lower() == ".exe":
        return [str(script_path)]
    local_node = path.parent / "node.exe"
    node_path = str(local_node) if local_node.exists() else (
        cli_agent_service.shutil.which("node.exe") or cli_agent_service.shutil.which("node") or ""
    )
    if not node_path:
        return []
    return [node_path, str(script_path)]


def _spawn_terminal_process(args: list[str], *, cwd: str, rows: int, cols: int) -> tuple[Any, str]:
    env = cli_agent_service._run_environment()
    env.pop("CI", None)
    env.pop("NO_COLOR", None)
    rows = _clamp_int(rows, DEFAULT_ROWS, 4, 120)
    cols = _clamp_int(cols, DEFAULT_COLS, 20, 240)
    if _is_windows_platform() and PtyProcess is not None:
        return PtyProcess.spawn(args, cwd=cwd, env=env, dimensions=(rows, cols)), "conpty"
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=0,
        env=env,
        **cli_agent_service._subprocess_no_window_kwargs(),
    )
    return process, "pipe"


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _send_initial_task(runtime: _TerminalRuntime, initial_input: str) -> None:
    if not initial_input.strip():
        return

    def write_later() -> None:
        time.sleep(0.35)
        if runtime.is_alive():
            try:
                runtime.send_input(initial_input)
            except Exception:
                return

    threading.Thread(target=write_later, name="cli-agent-terminal-initial-input", daemon=True).start()


def _initial_state(
    *,
    terminal_session_id: str,
    command: dict[str, Any],
    task: str,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    cli_run_id: str,
    lock_key: str,
    rows: int,
    cols: int,
    previous_state: dict[str, Any],
) -> dict[str, Any]:
    now = _now_iso()
    process_started_at_ms = _now_epoch_ms()
    cli_session_id = str(command.get("cliSessionId") or previous_state.get("cliSessionId") or "")
    previous_screen_current = _screen_state_is_current(previous_state)
    return {
        "schemaVersion": 1,
        "terminalSessionId": terminal_session_id,
        "adapterId": str(command.get("adapterId") or ""),
        "agentType": str(command.get("adapterId") or ""),
        "label": str(command.get("label") or command.get("adapterId") or ""),
        "sourceSessionId": source_session_id,
        "sourceMessageId": source_message_id,
        "sourceRunId": source_run_id,
        "linkedSourceMessageIds": _append_unique(previous_state.get("linkedSourceMessageIds") or [], source_message_id),
        "linkedSourceRunIds": _append_unique(previous_state.get("linkedSourceRunIds") or [], source_run_id),
        "cliRunId": cli_run_id,
        "lockKey": lock_key,
        "cwd": str(command.get("cwd") or ""),
        "mode": str(command.get("mode") or "readonly"),
        "model": str(command.get("model") or ""),
        "agent": str(command.get("agent") or ""),
        "task": task,
        "taskHash": cli_agent_service._task_hash(task),
        "taskPreview": cli_agent_service._clip(task, 500),
        "cliSessionId": cli_session_id,
        "cliSessionIdSource": str(previous_state.get("cliSessionIdSource") or ("resume_state" if cli_session_id else "")),
        "sessionDiscoveryStatus": "skipped" if cli_session_id else "",
        "commandPreview": list(command.get("preview") or []),
        "resumed": bool(command.get("resumed")),
        "status": "starting",
        "alive": False,
        "transport": "",
        "rows": _clamp_int(rows, DEFAULT_ROWS, 4, 120),
        "cols": _clamp_int(cols, DEFAULT_COLS, 20, 240),
        "transcriptPath": str(previous_state.get("transcriptPath") or ""),
        "screenText": str(previous_state.get("screenText") or "") if previous_screen_current else "",
        "screenReplay": str(previous_state.get("screenReplay") or "") if previous_screen_current else "",
        "screenQuality": str(previous_state.get("screenQuality") or "") if previous_screen_current else "",
        "screenRows": previous_state.get("screenRows") if previous_screen_current else None,
        "screenCols": previous_state.get("screenCols") if previous_screen_current else None,
        "screenParserVersion": SCREEN_BUFFER_PARSER_VERSION,
        "processStartedAt": now,
        "processStartedAtMs": process_started_at_ms,
        "createdAt": str(previous_state.get("createdAt") or now),
        "updatedAt": now,
    }


def _find_active_locked_runtime(lock_key: str, *, exclude_terminal_session_id: str = "") -> _TerminalRuntime | None:
    normalized_lock_key = str(lock_key or "").strip()
    if not normalized_lock_key:
        return None
    excluded = str(exclude_terminal_session_id or "").strip()
    for terminal_session_id, runtime in list(_RUNTIMES.items()):
        if excluded and terminal_session_id == excluded:
            continue
        if not runtime.is_alive():
            continue
        with runtime.lock:
            runtime_lock_key = str(runtime.state.get("lockKey") or "").strip()
        if runtime_lock_key == normalized_lock_key:
            return runtime
    return None


def _find_active_related_runtime(
    state: dict[str, Any] | None,
    *,
    cli_run_id: str = "",
    lock_key: str = "",
    adapter_id: str = "",
    source_session_id: str = "",
    cwd: str = "",
    mode: str = "",
    exclude_terminal_session_id: str = "",
) -> _TerminalRuntime | None:
    state = state or {}
    normalized_lock_key = str(lock_key or state.get("lockKey") or "").strip()
    locked_runtime = _find_active_locked_runtime(
        normalized_lock_key,
        exclude_terminal_session_id=exclude_terminal_session_id,
    )
    if locked_runtime is not None:
        return locked_runtime

    excluded = str(exclude_terminal_session_id or "").strip()
    scope = {
        "cli_run_id": str(cli_run_id or state.get("cliRunId") or "").strip(),
        "lock_key": normalized_lock_key,
        "adapter_id": str(adapter_id or state.get("adapterId") or state.get("agentType") or "").strip(),
        "source_session_id": str(source_session_id or state.get("sourceSessionId") or "").strip(),
        "cwd": str(cwd or state.get("cwd") or "").strip(),
        "mode": str(mode or state.get("mode") or "").strip(),
    }
    if not scope["adapter_id"] or not scope["cwd"]:
        return None

    for terminal_session_id, runtime in list(_RUNTIMES.items()):
        if excluded and terminal_session_id == excluded:
            continue
        if not runtime.is_alive():
            continue
        with runtime.lock:
            runtime_state = dict(runtime.state)
        if _terminal_state_matches_scope(runtime_state, **scope):
            return runtime
    return None


def _find_related_terminal_state(
    *,
    cli_run_id: str,
    lock_key: str,
    adapter_id: str,
    source_session_id: str,
    cwd: str,
    mode: str,
    exclude_terminal_session_id: str = "",
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    excluded = str(exclude_terminal_session_id or "").strip()
    for state in _iter_terminal_states():
        terminal_session_id = str(state.get("terminalSessionId") or "").strip()
        if excluded and terminal_session_id == excluded:
            continue
        if not _terminal_state_matches_scope(
            state,
            cli_run_id=cli_run_id,
            lock_key=lock_key,
            adapter_id=adapter_id,
            source_session_id=source_session_id,
            cwd=cwd,
            mode=mode,
        ):
            continue
        candidates.append(state)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: (
            not bool(item.get("userClosed")) and str(item.get("status") or "").strip().lower() != "closed",
            bool(item.get("alive")) or str(item.get("status") or "").strip().lower() == "running",
            bool(str(item.get("cliSessionId") or "").strip()),
            _timestamp_sort_key(str(item.get("updatedAt") or item.get("createdAt") or "")),
        ),
        reverse=True,
    )
    return dict(candidates[0])


def _related_terminal_session_ids(state: dict[str, Any]) -> list[str]:
    cli_run_id = str(state.get("cliRunId") or "").strip()
    lock_key = str(state.get("lockKey") or "").strip()
    adapter_id = str(state.get("adapterId") or state.get("agentType") or "").strip()
    source_session_id = str(state.get("sourceSessionId") or "").strip()
    cwd = str(state.get("cwd") or "").strip()
    mode = str(state.get("mode") or "").strip()
    result: list[str] = []
    for candidate in _iter_terminal_states():
        terminal_session_id = str(candidate.get("terminalSessionId") or "").strip()
        if not terminal_session_id:
            continue
        if _terminal_state_matches_scope(
            candidate,
            cli_run_id=cli_run_id,
            lock_key=lock_key,
            adapter_id=adapter_id,
            source_session_id=source_session_id,
            cwd=cwd,
            mode=mode,
        ):
            result = _append_unique(result, terminal_session_id)
    return result


def _terminal_state_matches_scope(
    state: dict[str, Any],
    *,
    cli_run_id: str,
    lock_key: str,
    adapter_id: str,
    source_session_id: str,
    cwd: str,
    mode: str,
) -> bool:
    if cli_run_id and str(state.get("cliRunId") or "").strip() == cli_run_id:
        return True
    if lock_key and str(state.get("lockKey") or "").strip() == lock_key:
        return True
    state_adapter = str(state.get("adapterId") or state.get("agentType") or "").strip()
    if not adapter_id or state_adapter != adapter_id:
        return False
    if _normalize_path_for_match(str(state.get("cwd") or "")) != _normalize_path_for_match(cwd):
        return False
    state_mode = _normalize_mode_for_scope(str(state.get("mode") or ""))
    requested_mode = _normalize_mode_for_scope(mode)
    return not state_mode or not requested_mode or state_mode == requested_mode


def _iter_terminal_states() -> list[dict[str, Any]]:
    if not SESSION_STATE_DIR.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in SESSION_STATE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def _mark_terminal_state_closed(state: dict[str, Any], *, closed_at: str, closed_ids: list[str]) -> None:
    state["status"] = "closed"
    state["alive"] = False
    state["userClosed"] = True
    state["closedAt"] = closed_at
    state["updatedAt"] = closed_at
    state["closedTerminalSessionIds"] = list(closed_ids)


def _supersede_related_terminal_states(state: dict[str, Any], *, keep_terminal_session_id: str) -> None:
    keep_id = str(keep_terminal_session_id or "").strip()
    if not keep_id:
        return
    related_ids = [item for item in _related_terminal_session_ids(state) if item and item != keep_id]
    if not related_ids:
        return
    now = _now_iso()
    for related_id in related_ids:
        related_runtime = _RUNTIMES.get(related_id)
        if related_runtime is not None and related_runtime.is_alive():
            related_runtime.stop()
        related_state = dict(related_runtime.state) if related_runtime is not None else _read_state(related_id)
        if not related_state:
            continue
        related_state["status"] = "closed"
        related_state["alive"] = False
        related_state["closedAt"] = now
        related_state["updatedAt"] = now
        related_state["closeReason"] = "superseded_by_idempotent_terminal"
        related_state["supersededByTerminalSessionId"] = keep_id
        if related_runtime is not None:
            with related_runtime.lock:
                related_runtime.state.update(related_state)
                _write_state(related_runtime.state)
        else:
            _write_state(related_state)


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _link_runtime_source(runtime: _TerminalRuntime, *, source_message_id: str, source_run_id: str) -> None:
    with runtime.lock:
        runtime.state["linkedSourceMessageIds"] = _append_unique(
            runtime.state.get("linkedSourceMessageIds") or [],
            source_message_id,
        )
        runtime.state["linkedSourceRunIds"] = _append_unique(
            runtime.state.get("linkedSourceRunIds") or [],
            source_run_id,
        )
        runtime.state["updatedAt"] = _now_iso()
        _write_state(runtime.state)


def _discover_existing_cli_session_id(*, agent_type: str, state: dict[str, Any]) -> str:
    if bool(state.get("userClosed")) or str(state.get("status") or "").strip().lower() == "closed":
        return ""
    spec = _terminal_session_discovery_spec(agent_type)
    if not spec:
        return ""
    discovered = _discover_cli_session_id_for_state(state, spec, existing=True)
    if discovered:
        _touch_cli_session_id_in_state(
            str(state.get("terminalSessionId") or ""),
            discovered,
            source="session_discovery_existing",
            status="found",
        )
    return discovered


def _terminal_session_discovery_spec(agent_type: str) -> dict[str, Any]:
    adapters = cli_agent_service._load_adapter_definitions()
    adapter = adapters.get(agent_type)
    terminal = adapter.get("terminal") if isinstance(adapter, dict) and isinstance(adapter.get("terminal"), dict) else {}
    spec = terminal.get("sessionDiscovery") if isinstance(terminal.get("sessionDiscovery"), dict) else {}
    source = str(spec.get("source") or "").strip()
    if not source or source.lower() in {"none", "disabled", "false"}:
        return {}
    return dict(spec)


def _schedule_session_id_discovery(runtime: _TerminalRuntime, raw_spec: Any) -> None:
    spec = dict(raw_spec) if isinstance(raw_spec, dict) else {}
    if not spec or str(spec.get("source") or "").strip().lower() in {"", "none", "disabled", "false"}:
        return
    with runtime.lock:
        if str(runtime.state.get("cliSessionId") or "").strip():
            return
        runtime.state["sessionDiscoveryStatus"] = "pending"
        runtime.state["updatedAt"] = _now_iso()
        _write_state(runtime.state)

    def discover_later() -> None:
        attempts = _clamp_int(spec.get("pollAttempts"), DEFAULT_DISCOVERY_POLL_ATTEMPTS, 1, 60)
        interval = _clamp_float(
            spec.get("pollIntervalSeconds"),
            DEFAULT_DISCOVERY_POLL_INTERVAL_SECONDS,
            0.1,
            10.0,
        )
        for _attempt in range(attempts):
            with runtime.lock:
                state = dict(runtime.state)
                if str(state.get("cliSessionId") or "").strip():
                    return
            discovered = _discover_cli_session_id_for_state(state, spec, existing=False)
            if discovered:
                _apply_discovered_cli_session_id(runtime, discovered, source="session_discovery")
                return
            if not runtime.is_alive():
                break
            time.sleep(interval)
        with runtime.lock:
            if not str(runtime.state.get("cliSessionId") or "").strip():
                runtime.state["sessionDiscoveryStatus"] = "not_found"
                runtime.state["updatedAt"] = _now_iso()
                _write_state(runtime.state)

    threading.Thread(
        target=discover_later,
        name=f"cli-agent-session-discovery-{runtime.state.get('terminalSessionId')}",
        daemon=True,
    ).start()


def _apply_discovered_cli_session_id(runtime: _TerminalRuntime, cli_session_id: str, *, source: str) -> None:
    normalized = str(cli_session_id or "").strip()
    if not normalized:
        return
    with runtime.lock:
        if str(runtime.state.get("cliSessionId") or "").strip():
            return
        runtime.state["cliSessionId"] = normalized
        runtime.state["cliSessionIdSource"] = source
        runtime.state["sessionDiscoveryStatus"] = "found"
        runtime.state["updatedAt"] = _now_iso()
        _write_state(runtime.state)
        public_state = _public_state(dict(runtime.state))
    _record_cli_agent_lifecycle_link(public_state, source=source)
    runtime._publish({"type": "terminal_status", "session": public_state})


def _touch_cli_session_id_in_state(
    terminal_session_id: str,
    cli_session_id: str,
    *,
    source: str,
    status: str,
) -> None:
    normalized_terminal_session_id = str(terminal_session_id or "").strip()
    normalized_cli_session_id = str(cli_session_id or "").strip()
    if not normalized_terminal_session_id or not normalized_cli_session_id:
        return
    state = _read_state(normalized_terminal_session_id)
    if not state or str(state.get("cliSessionId") or "").strip():
        return
    state["cliSessionId"] = normalized_cli_session_id
    state["cliSessionIdSource"] = source
    state["sessionDiscoveryStatus"] = status
    state["updatedAt"] = _now_iso()
    _write_state(state)
    _record_cli_agent_lifecycle_link(_public_state(dict(state)), source=source)


def _record_cli_agent_lifecycle_link(state: dict[str, Any], *, source: str) -> None:
    source_session_id = str(state.get("sourceSessionId") or "").strip()
    cli_session_id = str(state.get("cliSessionId") or "").strip()
    if not source_session_id or not cli_session_id:
        return
    try:
        from . import session_service

        session_service.append_cli_agent_lifecycle_event(
            source_session_id,
            event="linked",
            terminal_session={**state, "cliSessionIdSource": source},
        )
    except Exception as exc:
        cli_agent_service._record_event(
            "cli_agent.terminal.lifecycle_link_failed",
            outcome="failed",
            fields={
                "terminalSessionId": str(state.get("terminalSessionId") or ""),
                "cliRunId": str(state.get("cliRunId") or ""),
                "adapterId": str(state.get("adapterId") or state.get("agentType") or ""),
                "errorType": type(exc).__name__,
            },
        )


def _discover_cli_session_id_for_state(state: dict[str, Any], spec: dict[str, Any], *, existing: bool) -> str:
    source = str(spec.get("source") or "").strip().lower()
    if source in {"mimocode_sqlite", "sqlite_latest_by_cwd"}:
        return _discover_mimocode_sqlite_session_id(state, spec, existing=existing)
    if source in {"claude_code_project_jsonl", "claude_project_jsonl"}:
        return _discover_claude_project_jsonl_session_id(state, spec, existing=existing)
    return ""


def _discover_mimocode_sqlite_session_id(state: dict[str, Any], spec: dict[str, Any], *, existing: bool) -> str:
    cwd = str(state.get("cwd") or "").strip()
    if not cwd:
        return ""
    database_path = _render_discovery_path(str(spec.get("databasePath") or ""))
    if not database_path.exists():
        return ""
    normalized_cwd = _normalize_path_for_match(cwd)
    if not normalized_cwd:
        return ""
    started_at_ms = _state_started_at_ms(state)
    created_grace_ms = _clamp_int(spec.get("createdGraceMs"), DEFAULT_DISCOVERY_CREATED_GRACE_MS, 0, 86_400_000)
    min_timestamp_ms = max(0, started_at_ms - created_grace_ms) if started_at_ms else 0
    max_rows = _clamp_int(spec.get("maxRows"), DEFAULT_DISCOVERY_MAX_ROWS, 1, 500)
    try:
        uri = f"{database_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "select id, directory, title, time_created, time_updated from session "
                "order by time_updated desc limit ?",
                (max_rows,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return ""
    for row in rows:
        row_cwd = _normalize_path_for_match(str(row["directory"] or ""))
        if row_cwd != normalized_cwd:
            continue
        created_at = _safe_int(row["time_created"])
        updated_at = _safe_int(row["time_updated"])
        latest_at = max(created_at, updated_at)
        if min_timestamp_ms and latest_at < min_timestamp_ms:
            if existing:
                continue
            return ""
        session_id = str(row["id"] or "").strip()
        if _valid_discovered_session_id(session_id, spec):
            return session_id
    return ""


def _discover_claude_project_jsonl_session_id(state: dict[str, Any], spec: dict[str, Any], *, existing: bool) -> str:
    cwd = str(state.get("cwd") or "").strip()
    if not cwd:
        return ""
    project_dir = _render_discovery_path(
        str(spec.get("projectDir") or "{home}/.claude/projects/{encodedCwd}"),
        cwd=cwd,
    )
    if not project_dir.exists() or not project_dir.is_dir():
        return ""
    started_at_ms = _state_started_at_ms(state)
    created_grace_ms = _clamp_int(spec.get("createdGraceMs"), DEFAULT_DISCOVERY_CREATED_GRACE_MS, 0, 86_400_000)
    min_timestamp_ms = max(0, started_at_ms - created_grace_ms) if started_at_ms else 0
    max_rows = _clamp_int(spec.get("maxRows"), DEFAULT_DISCOVERY_MAX_ROWS, 1, 500)
    try:
        candidates = sorted(project_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:max_rows]
    except OSError:
        return ""
    for path in candidates:
        try:
            latest_at_ms = int(path.stat().st_mtime * 1000)
        except OSError:
            continue
        if min_timestamp_ms and latest_at_ms < min_timestamp_ms:
            if existing:
                continue
            return ""
        session_id = _claude_session_id_from_jsonl(path, spec)
        if session_id:
            return session_id
    return ""


def _claude_session_id_from_jsonl(path: Path, spec: dict[str, Any]) -> str:
    stem = path.stem.strip()
    if _valid_discovered_session_id(stem, spec):
        return stem
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    sample = lines[:8] + lines[-8:]
    for line in sample:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
        if _valid_discovered_session_id(session_id, spec):
            return session_id
    return ""


def _render_discovery_path(template: str, *, cwd: str = "") -> Path:
    raw = template or "{home}/.local/share/mimocode/mimocode.db"
    rendered = (
        raw.replace("{home}", str(Path.home()))
        .replace("{projectRoot}", str(Path(PROJECT_ROOT)))
        .replace("{encodedCwd}", _claude_project_dir_name(cwd))
    )
    return Path(rendered).expanduser()


def _claude_project_dir_name(cwd: str) -> str:
    text = str(cwd or "").strip()
    if not text:
        return ""
    try:
        text = str(Path(text).resolve())
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to resolve Claude project directory name for '{text}': {exc}",
            tag="cli_terminal_path_resolve",
        )
    text = text.replace("\\", "/").rstrip("/")
    return re.sub(r"[^A-Za-z0-9._-]", "-", text).strip("-")


def _terminal_permission_mode(agent_type: str, mode: str) -> str:
    if cli_agent_service._normalize_id(agent_type) != "claude_code":
        return ""
    return "plan" if str(mode or "").strip().lower() == "readonly" else "auto"


def _normalize_path_for_match(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        text = str(Path(text).resolve())
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to normalize path for matching for '{text}': {exc}",
            tag="cli_terminal_path_normalize",
        )
    return text.replace("\\", "/").rstrip("/").lower()


def _state_started_at_ms(state: dict[str, Any]) -> int:
    explicit = _safe_int(state.get("processStartedAtMs"))
    if explicit:
        return explicit
    created_at = str(state.get("createdAt") or "").strip()
    if not created_at:
        return 0
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return 0


def _valid_discovered_session_id(session_id: str, spec: dict[str, Any]) -> bool:
    if not session_id:
        return False
    regex = str(spec.get("idRegex") or r"^[A-Za-z0-9_.:-]+$").strip()
    if not regex:
        return True
    try:
        return bool(re.match(regex, session_id))
    except re.error:
        return True


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _stable_cli_lock_key(
    *,
    adapter_id: str,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    cwd: str,
    mode: str,
    task: str,
) -> str:
    return f"cli-lock-{_fnv1a_hex(_cli_scope_basis(adapter_id=adapter_id, source_session_id=source_session_id, source_message_id=source_message_id, source_run_id=source_run_id, cwd=cwd, mode=mode, task=task))}"


def _stable_cli_run_id(
    *,
    adapter_id: str,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    cwd: str,
    mode: str,
    task: str,
) -> str:
    return f"cli-run-{_fnv1a_hex(_cli_scope_basis(adapter_id=adapter_id, source_session_id=source_session_id, source_message_id=source_message_id, source_run_id=source_run_id, cwd=cwd, mode=mode, task=task))}"


def _cli_scope_basis(
    *,
    adapter_id: str,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    cwd: str,
    mode: str,
    task: str,
) -> str:
    normalized_cwd = str(cwd or "").strip().replace("\\", "/").lower()
    normalized_mode = _normalize_mode_for_scope(mode) or "readonly"
    return "\n".join(["cli-run-v3", str(adapter_id or "").strip(), normalized_cwd, normalized_mode])


def _fnv1a_hex(value: str) -> str:
    hash_value = 0x811C9DC5
    for char in str(value or ""):
        hash_value ^= ord(char)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return f"{hash_value:08x}"


def _append_unique(items: Any, value: str) -> list[str]:
    result: list[str] = []
    for item in list(items or []):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    text = str(value or "").strip()
    if text and text not in result:
        result.append(text)
    return result


def _stable_terminal_session_id(
    *,
    adapter_id: str,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    cwd: str,
    mode: str,
    task: str,
) -> str:
    basis = _cli_scope_basis(
        adapter_id=adapter_id,
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        cwd=cwd,
        mode=mode,
        task=task,
    )
    return f"cli-term-{hashlib.sha256(basis.encode('utf-8', errors='replace')).hexdigest()[:16]}"


def _normalize_mode_for_scope(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if not normalized:
        return ""
    return normalized if normalized in cli_agent_service.SUPPORTED_MODES else "readonly"


def _scope_cwd(cwd: str, *, mode: str) -> str:
    normalized_mode = str(mode or "readonly").strip().lower()
    if normalized_mode not in cli_agent_service.SUPPORTED_MODES:
        normalized_mode = "readonly"
    try:
        result = cli_agent_service._resolve_run_cwd(cwd, mode=normalized_mode)
    except Exception:
        return str(cwd or "").strip()
    return str(result.get("cwd") or cwd or "").strip()


def _read_state(terminal_session_id: str) -> dict[str, Any]:
    path = _state_path(terminal_session_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    terminal_session_id = _normalize_terminal_session_id(str(state.get("terminalSessionId") or ""))
    path = _state_path(terminal_session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch_state(terminal_session_id: str, *, status: str, alive: bool) -> None:
    state = _read_state(terminal_session_id)
    if not state:
        return
    state["status"] = status
    state["alive"] = alive
    state["updatedAt"] = _now_iso()
    _write_state(state)


def _state_path(terminal_session_id: str) -> Path:
    return SESSION_STATE_DIR / f"{_normalize_terminal_session_id(terminal_session_id)}.json"


def _transcript_path(terminal_session_id: str) -> Path:
    return TRANSCRIPT_DIR / f"{_normalize_terminal_session_id(terminal_session_id)}.log"


def _normalize_terminal_session_id(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value or "").strip())
    if not normalized:
        raise CliAgentTerminalError("MISSING_TERMINAL_SESSION", "Terminal session id is required.")
    return normalized[:120]


def _render_template_arg(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", str(value or ""))
    return rendered


def _redacted_preview(args: list[str], *, task: str) -> list[str]:
    task_hash = cli_agent_service._task_hash(task)
    return [f"<task:{task_hash}>" if task and item == task else item for item in args]


def _extract_cli_session_id(chunk: str, regex: str) -> str:
    if not regex:
        return ""
    try:
        match = re.search(regex, chunk)
    except re.error:
        return ""
    if not match:
        return ""
    return str(match.group(1) if match.groups() else match.group(0)).strip()


def _read_transcript_tail(path: Path, limit: int = MAX_TRANSCRIPT_TAIL_CHARS) -> str:
    if not path.exists():
        return ""
    try:
        byte_limit = max(8192, limit * 4)
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - byte_limit), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= limit:
        return text
    return text[-limit:]


LEADING_CSI_FRAGMENT_RE = re.compile(r"^[0-?]+(?:[@-~]|\r?\n)")


def _strip_leading_ansi_fragment(text: str) -> str:
    result = str(text or "")
    for _ in range(8):
        match = LEADING_CSI_FRAGMENT_RE.match(result)
        if not match:
            break
        result = result[match.end() :]
    return result


def _screen_state_is_current(state: dict[str, Any]) -> bool:
    try:
        version = int(state.get("screenParserVersion") or 0)
    except (TypeError, ValueError):
        version = 0
    return version >= SCREEN_BUFFER_PARSER_VERSION


def _screen_initial_text(state: dict[str, Any]) -> str:
    return str(state.get("screenText") or "") if _screen_state_is_current(state) else ""


def _merge_transcript_snapshot(state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    merged = {**state, **snapshot}
    if str(snapshot.get("screenText") or "").strip():
        return merged
    if not str(state.get("screenText") or "").strip() or not _screen_state_is_current(state):
        if str(state.get("screenText") or "").strip() and not _screen_state_is_current(state):
            for key in SCREEN_STATE_FIELD_KEYS:
                if key in merged:
                    merged[key] = "" if key in {"screenText", "screenReplay", "screenQuality"} else None
        return merged
    for key in SCREEN_STATE_FIELD_KEYS:
        if key in state:
            merged[key] = state.get(key)
    return merged


def _read_transcript_snapshot(
    path: Path,
    limit: int = MAX_TRANSCRIPT_TAIL_CHARS,
    *,
    rows: int = DEFAULT_ROWS,
    cols: int = DEFAULT_COLS,
) -> dict[str, Any]:
    tail = _read_transcript_tail(path, limit=limit)
    replay_tail = _strip_leading_ansi_fragment(tail)
    replayable, reason = _classify_transcript_tail_replay(replay_tail)
    if not replayable:
        return {
            "transcriptTail": "",
            "transcriptTailReplayable": False,
            "transcriptTailRenderReason": reason,
        }
    return {
        "transcriptTail": replay_tail,
        "transcriptTailReplayable": True,
        "transcriptTailRenderReason": "raw_transcript_tail_boundary_aligned" if replay_tail != tail else ("raw_transcript_tail" if tail else "empty"),
    }


def _read_transcript_snapshot_for_state(
    path: Path,
    state: dict[str, Any],
    *,
    include_transcript_tail: bool,
) -> dict[str, Any]:
    if (
        not include_transcript_tail
        and _screen_state_is_current(state)
        and str(state.get("screenText") or "").strip()
    ):
        return {
            "transcriptTail": "",
            "transcriptTailReplayable": False,
            "transcriptTailRenderReason": "screen_snapshot_preferred",
        }
    return _read_transcript_snapshot(
        path,
        rows=_clamp_int(state.get("rows"), DEFAULT_ROWS, 4, 120),
        cols=_clamp_int(state.get("cols"), DEFAULT_COLS, 20, 240),
    )


def _live_runtime_transcript_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    if _screen_state_is_current(state) and str(state.get("screenText") or "").strip():
        return {
            "transcriptTail": "",
            "transcriptTailReplayable": False,
            "transcriptTailRenderReason": "live_screen_snapshot",
        }
    return {
        "transcriptTail": "",
        "transcriptTailReplayable": False,
        "transcriptTailRenderReason": "live_runtime_no_history_replay",
    }


def _classify_transcript_tail_replay(text: str) -> tuple[bool, str]:
    if not text:
        return True, "empty"
    escape_count = text.count("\x1b")
    cursor_move_count = len(re.findall(r"\x1b\[[0-9;]*[Hf]", text))
    tui_mode_count = len(re.findall(r"\x1b\[\?[0-9;]*(?:h|l)", text))
    without_ansi = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    visible = "".join(ch for ch in without_ansi if ch.isprintable() and not ch.isspace())
    visible_ratio = len(visible) / max(len(text), 1)
    control_heavy = escape_count >= 20 and visible_ratio < 0.08
    tui_repaint_tail = (cursor_move_count >= 10 or tui_mode_count >= 10) and visible_ratio < 0.15
    if control_heavy or tui_repaint_tail:
        return False, "unsafe_tui_control_tail"
    return True, "replayable"


def _append_transcript_chunk(path: Path, chunk: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = str(chunk or "").encode("utf-8", errors="replace")
    with path.open("ab") as handle:
        handle.write(data)
    try:
        if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
            _trim_transcript_file(path)
    except Exception:
        return


def _trim_transcript_file(path: Path) -> None:
    try:
        size = path.stat().st_size
    except Exception:
        return
    if size <= MAX_TRANSCRIPT_BYTES:
        return
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - TRANSCRIPT_TRIM_TARGET_BYTES), os.SEEK_SET)
            tail = handle.read()
        text = tail.decode("utf-8", errors="replace")
        path.write_bytes(text.encode("utf-8", errors="replace"))
    except Exception:
        return


def _terminal_screen_state_fields(snapshot: TerminalScreenSnapshot) -> dict[str, Any]:
    return {
        "screenText": snapshot.text,
        "screenReplay": snapshot.replay,
        "screenQuality": snapshot.quality,
        "screenRows": snapshot.rows,
        "screenCols": snapshot.cols,
        "screenParserVersion": SCREEN_BUFFER_PARSER_VERSION,
    }


def _terminal_interaction_fields(state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status") or "").strip().lower()
    alive = bool(state.get("alive"))
    cli_session_id = str(state.get("cliSessionId") or "").strip()
    user_closed = bool(state.get("userClosed"))
    tui_state = _infer_terminal_tui_state(state)
    state_reason = (
        str(state.get("staleReason") or "").strip()
        or str(state.get("closeReason") or "").strip()
        or status
        or "unknown"
    )
    if alive and status not in {"closed", "stale", "stopped", "exited"}:
        return {
            "interactionState": "live",
            "canInput": True,
            "canResume": False,
            "canStart": False,
            "resumeAction": "none",
            "displayMode": "live_terminal",
            "stateReason": "runtime_alive",
            "tuiState": tui_state,
        }
    if user_closed or status == "closed":
        return {
            "interactionState": "closed",
            "canInput": False,
            "canResume": False,
            "canStart": False,
            "resumeAction": "none",
            "displayMode": "readonly_replay",
            "stateReason": state_reason,
            "tuiState": tui_state,
        }
    if status in {"stale", "stopped", "exited"} and cli_session_id:
        return {
            "interactionState": "resumable",
            "canInput": False,
            "canResume": True,
            "canStart": False,
            "resumeAction": "resume_session",
            "displayMode": "readonly_replay",
            "stateReason": state_reason,
            "tuiState": tui_state,
        }
    return {
        "interactionState": "history",
        "canInput": False,
        "canResume": False,
        "canStart": True,
        "resumeAction": "start_new",
        "displayMode": "readonly_replay",
        "stateReason": state_reason,
        "tuiState": tui_state,
    }


def _infer_terminal_tui_state(state: dict[str, Any]) -> str:
    text = str(state.get("screenText") or state.get("transcriptTail") or "").strip()
    lowered = text.lower()
    status = str(state.get("status") or "").strip().lower()
    if bool(state.get("userClosed")) or status == "closed":
        return "closed"
    if "interrupted" in lowered or "已中断" in text or "中断" in text:
        return "interrupted"
    if "vibelution_cli_done:" in lowered or "已完成" in text or status in {"completed", "done"}:
        return "task_done"
    if bool(state.get("alive")) and status not in {"closed", "stale", "stopped", "exited"}:
        return "live"
    if status in {"stale", "stopped", "exited"}:
        return "history"
    return status or "unknown"


def _terminal_not_running_details(terminal_session_id: str) -> dict[str, Any]:
    session_id = _normalize_terminal_session_id(terminal_session_id)
    state = _read_state(session_id)
    if not state:
        details: dict[str, Any] = {
            "terminalSessionId": session_id,
            "status": "missing",
            "alive": False,
            "interactionState": "closed",
            "canInput": False,
            "canResume": False,
            "canStart": False,
            "resumeAction": "none",
            "displayMode": "readonly_replay",
            "stateReason": "not_found",
            "tuiState": "missing",
        }
        return details
    public_state = _public_state({**state, "alive": False})
    keys = {
        "terminalSessionId",
        "status",
        "alive",
        "cliSessionId",
        "interactionState",
        "canInput",
        "canResume",
        "canStart",
        "resumeAction",
        "displayMode",
        "stateReason",
        "tuiState",
    }
    return {key: public_state.get(key) for key in keys if key in public_state}


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "terminalSessionId",
        "adapterId",
        "agentType",
        "label",
        "sourceSessionId",
        "sourceMessageId",
        "sourceRunId",
        "linkedSourceMessageIds",
        "linkedSourceRunIds",
        "cliRunId",
        "lockKey",
        "cwd",
        "mode",
        "taskHash",
        "taskPreview",
        "cliSessionId",
        "cliSessionIdSource",
        "sessionDiscoveryStatus",
        "commandPreview",
        "resumed",
        "status",
        "alive",
        "transport",
        "rows",
        "cols",
        "transcriptPath",
        "transcriptTail",
        "transcriptTailReplayable",
        "transcriptTailRenderReason",
        "screenText",
        "screenReplay",
        "screenQuality",
        "screenRows",
        "screenCols",
        "screenParserVersion",
        "processStartedAt",
        "processStartedAtMs",
        "userClosed",
        "closedAt",
        "closedTerminalSessionIds",
        "closeReason",
        "supersededByTerminalSessionId",
        "semanticStatus",
        "interactionState",
        "canInput",
        "canResume",
        "canStart",
        "resumeAction",
        "displayMode",
        "stateReason",
        "tuiState",
        "createdAt",
        "updatedAt",
    }
    payload = {key: state.get(key) for key in keys if key in state}
    payload.update(_terminal_interaction_fields(payload))
    if "semanticStatus" not in payload and str(payload.get("terminalSessionId") or "").strip():
        status = str(payload.get("status") or "").strip().lower()
        payload["semanticStatus"] = status if status in {"closed", "stopped", "exited", "stale"} else "attached"
    return payload


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch_ms() -> int:
    return int(time.time() * 1000)


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
