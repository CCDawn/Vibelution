"""A lifecycle start is not proof of a submitted or physically started tool."""

import json
import threading
import sys
from pathlib import Path

import pytest

from core.infrastructure import tool_execution_trace as diagnostics
from core.infrastructure.event_bus import EventBus, EventNames
from core.infrastructure.tool_executor import ToolExecutor


@pytest.fixture
def probe(monkeypatch):
    events = []
    waiting = threading.Event()

    def record(code, fields, *, warning=False):
        events.append((code, fields, warning))
        if warning:
            waiting.set()

    monkeypatch.setattr(diagnostics, "_STALL_SECONDS", 0.03)
    monkeypatch.setattr(diagnostics, "_emit", record)
    executor = ToolExecutor()
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", lambda *a, **kw: None)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *a, **kw: None)
    return executor, events, waiting


@pytest.mark.parametrize("phase", ["started", "arguments_ready"])
@pytest.mark.parametrize("cancel", [False, True])
def test_waiting_start_is_diagnosed_before_tool_runs(probe, phase, cancel):
    executor, events, waiting = probe
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    calls, result = [], []
    secret = "private command and result must not enter diagnostics"
    executor.register_tool("phase_probe_tool", lambda command: calls.append(command) or secret, timeout=1)
    bus = EventBus()

    def hold_start(event):
        if event.data.get("name") == "phase_probe_tool" and event.data.get("lifecyclePhase") == phase:
            entered.set()
            assert release.wait(3)

    callback = bus.subscribe(EventNames.TOOL_START, hold_start)

    def run():
        executor.set_cancel_checker(lambda: "user stop" if stopped.is_set() else "")
        try:
            result.append(executor.execute("phase_probe_tool", {"command": secret}, tool_call_id="trace-start-call"))
        finally:
            executor.set_cancel_checker(None)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(2)
        assert waiting.wait(2)
        assert calls == []
        warning = next(fields for code, fields, _ in events if code.endswith("phase_waiting"))
        assert warning["phase"] == "notify." + phase
        assert warning["toolCallId"] == "trace-start-call"
        assert warning["timeoutSeconds"] == 1
        assert 0 < len(warning["stack"]) <= 12
        assert set(warning["stack"][0]) == {"file", "function", "line"}
        assert not any(code.endswith("future_submitted") for code, _, _ in events)
        if cancel:
            stopped.set()
    finally:
        release.set()
        thread.join(3)
        bus.unsubscribe_by_id(callback)
    assert not thread.is_alive()
    assert calls == ([] if cancel else [secret])
    assert ("[取消]" in str(result[0][0])) if cancel else result[0][0] == secret
    assert secret not in json.dumps(events)


@pytest.mark.parametrize("tool_result,event_name", [
    ("real result kept", EventNames.TOOL_SUCCESS),
    ("[错误] real failed result kept", EventNames.TOOL_ERROR),
])
def test_finished_function_is_distinct_from_blocked_result_notification(probe, tool_result, event_name):
    executor, events, waiting = probe
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []
    executor.register_tool("phase_probe_tool", lambda: calls.append(1) or tool_result, timeout=1)
    bus = EventBus()

    def hold_result(event):
        if event.data.get("name") == "phase_probe_tool":
            entered.set()
            assert release.wait(3)

    callback = bus.subscribe(event_name, hold_result)
    thread = threading.Thread(target=lambda: results.append(executor.execute("phase_probe_tool", {})))
    thread.start()
    try:
        assert entered.wait(2)
        assert waiting.wait(2)
        assert calls == [1]
        assert any(code.endswith("function_returned") for code, _, _ in events)
        warning = next(fields for code, fields, _ in events if code.endswith("phase_waiting"))
        assert warning["phase"] == "notify." + event_name
        assert tool_result not in json.dumps(events)
    finally:
        release.set()
        thread.join(3)
        bus.unsubscribe_by_id(callback)
    assert not thread.is_alive()
    assert results == [(tool_result, None)]
    assert calls == [1]


def test_observer_closes_and_preserves_nested_context_and_process_identity(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostics, "_emit", lambda code, fields, **kw: events.append((code, fields)))
    with diagnostics.trace_tool_execution("probe", "call-one") as trace:
        trace.bind(sessionId="session-one", turnId="turn-one")
        with trace.phase("notify.started"):
            pass
        diagnostics.record_tool_process_event("process.started", processId=123, commandHash="abcd")
        with diagnostics.trace_tool_execution("nested", "call-two"):
            pass
        assert diagnostics._CURRENT_TRACE.get() is trace
    assert diagnostics._CURRENT_TRACE.get() is None
    assert trace._watcher is not None and not trace._watcher.is_alive()
    assert any(fields.get("processId") == 123 and fields["sessionId"] == "session-one"
               for _, fields in events)


def test_blocked_diagnostic_recorder_does_not_change_real_tool_result(probe, monkeypatch):
    executor, _, _ = probe
    recording, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls, results = [], []

    def blocked_recorder(*args, **kwargs):
        recording.set()
        assert release.wait(3)

    monkeypatch.setattr(diagnostics, "_emit", blocked_recorder)
    executor.register_tool("phase_probe_tool", lambda: calls.append(1) or "physical result", timeout=1)

    def run():
        results.append(executor.execute("phase_probe_tool", {}))
        finished.set()

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert recording.wait(2)
        assert finished.wait(1), "diagnostic I/O blocked the tool's authoritative return"
        assert results == [("physical result", None)]
        assert calls == [1]
    finally:
        release.set()
        worker.join(3)


def test_observer_start_failure_keeps_body_and_original_exception(monkeypatch):
    class CannotStart:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("cannot start new thread")

    monkeypatch.setattr(diagnostics.threading, "Thread", CannotStart)
    entered = []
    with pytest.raises(ValueError, match="original failure"):
        with diagnostics.trace_tool_execution("probe", "call") as trace:
            with trace.phase("notify.started"):
                entered.append(1)
                raise ValueError("original failure")
    assert entered == [1]
    assert trace._disabled
    assert trace._watcher is None


def test_diagnostic_queue_is_bounded_when_recorder_stalls(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked_recorder(*args, **kwargs):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(diagnostics, "_emit", blocked_recorder)
    try:
        with diagnostics.trace_tool_execution("probe", "call") as trace:
            with trace.phase("notify.started"):
                assert entered.wait(2)
                for index in range(1000):
                    trace.record("diagnostic.probe", index=index)
                assert trace._events.qsize() == 64
    finally:
        release.set()
        trace.close()


def test_real_sandbox_process_has_physical_start_exit_receipts(monkeypatch, tmp_path):
    from core.infrastructure import codex_cli_sandbox as sandbox

    events = []
    monkeypatch.setattr(diagnostics, "_emit", lambda code, fields, **kw: events.append((code, fields)))
    monkeypatch.setattr(sandbox, "_current_agent_sandbox_mode", lambda: "danger_full_access")
    monkeypatch.setattr(sandbox, "_resolve_cwd", lambda cwd: Path(tmp_path))
    command = f'"{sys.executable}" -c "print(12345)"'
    with diagnostics.trace_tool_execution("cli_tool", "physical-probe") as trace:
        trace.bind(sessionId="isolated-probe", turnId="isolated-turn")
        with trace.phase("tool_function", timeoutSeconds=5):
            result = sandbox.execute_codex_sandbox_command(command, timeout=5, cwd=str(tmp_path))
    assert "12345" in result
    started = next(fields for code, fields in events if code.endswith("process_started"))
    exited = next(fields for code, fields in events if code.endswith("process_exit_observed"))
    assert started["processId"] > 0
    assert started["toolCallId"] == "physical-probe"
    assert exited["processId"] == started["processId"]
    assert exited["exitCode"] == 0
    assert command not in json.dumps(events)


def test_blocked_recorders_cannot_accumulate_unbounded_observers(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(diagnostics, "_OBSERVER_SLOTS", slots)

    def blocked_recorder(*args, **kwargs):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(diagnostics, "_emit", blocked_recorder)
    try:
        with diagnostics.trace_tool_execution("probe", "first") as first:
            with first.phase("notify.started"):
                assert entered.wait(2)
        with diagnostics.trace_tool_execution("probe", "second") as second:
            with second.phase("notify.started"):
                assert second._disabled
                assert second._watcher is None
    finally:
        release.set()
        first.close()
    assert slots.acquire(blocking=False)
    slots.release()
