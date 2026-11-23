from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from core.web.services import cli_agent_task_kernel as kernel
from core.web.services import runtime_task_registry as registry
from core.web.services import session_service


@pytest.fixture
def completed_task(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kernel, "TASK_STATE_DIR", tmp_path / "cli-tasks")
    monkeypatch.setattr(kernel, "_PENDING_FINALIZATIONS", {})
    monkeypatch.setattr(kernel, "_STORE_CACHE", {})
    monkeypatch.setattr(kernel, "_WATCH_MTIME_CACHE", {})
    monkeypatch.setattr(kernel.cli_agent_service, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(registry.RuntimeTaskStore, "_ensure_auto_background_sweeper", lambda self: None)
    store = kernel._task_store()
    store._branch_generation_reader = lambda _: 0
    task = store.register_task(registry.new_snapshot(
        kind=registry.KIND_CLI_AGENT, task_id="cli-receipt", status="running",
        source_session_id="parent-session",
    ))
    task.update({"terminalSessionId": "terminal-one", "adapterId": "codex_code", "output": "answer"})
    kernel._complete_task_state(task, status="completed", code="CLI_AGENT_TASK_COMPLETED", reason="protocol_pattern")
    with kernel._TASK_LOCK:
        kernel._persist_task_for_finalization(task)
    return task


def _restart(monkeypatch):
    monkeypatch.setattr(kernel, "_PENDING_FINALIZATIONS", {})
    monkeypatch.setattr(kernel, "_STORE_CACHE", {})
    monkeypatch.setattr(kernel, "_WATCH_MTIME_CACHE", {})
    kernel._task_store()._branch_generation_reader = lambda _: 0


def _watch_once(monkeypatch):
    class EndWatch(Exception):
        pass

    def end_watch(_seconds):
        raise EndWatch()

    monkeypatch.setattr(kernel.time, "sleep", end_watch)
    with pytest.raises(EndWatch):
        kernel._watch_active_tasks()


def test_failed_parent_delivery_survives_restart_and_does_not_restart_child(monkeypatch, completed_task):
    from core.web.services import cli_agent_terminal_service

    calls = []

    def unavailable(*args, **kwargs):
        calls.append("failed")
        raise OSError("parent temporarily unavailable")

    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", unavailable)
    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda *args: pytest.fail("child dispatched again"))
    kernel._finalize_task_result(completed_task, reason="protocol_pattern")
    failed = kernel._task_store().load_state(completed_task["taskId"])
    assert failed["resultDeliveryState"] == "pending"
    assert failed["resultDeliveryAttempts"] == 1
    assert completed_task["taskId"] in kernel._PENDING_FINALIZATIONS
    assert kernel._task_store().active_task_ids() == []

    _restart(monkeypatch)
    # A restart before the retry deadline must honor the persisted backoff.
    _watch_once(monkeypatch)
    assert calls == ["failed"]
    due = datetime.fromisoformat(failed["resultDeliveryNextAttemptAt"]).timestamp()
    monkeypatch.setattr(kernel.time, "time", lambda: due + 1)
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: calls.append("delivered") or {"id": "receipt"})
    _watch_once(monkeypatch)
    _watch_once(monkeypatch)
    settled = kernel._task_store().load_state(completed_task["taskId"])
    assert calls == ["failed", "delivered"]
    assert settled["status"] == "completed"
    assert settled["resultDeliveryState"] == "delivered"
    assert settled["resultDeliveryAcknowledgedAt"]
    assert kernel._PENDING_FINALIZATIONS == {}


def test_crash_after_terminal_persist_is_recovered_without_new_submission(monkeypatch, completed_task):
    _restart(monkeypatch)
    started = []
    monkeypatch.setattr(kernel, "_ensure_watcher_started", lambda: started.append(True))
    report = kernel.recover_pending_cli_agent_task_results_on_startup()
    assert report["pendingResultCount"] == 1
    assert started == [True]
    receipts = []
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: receipts.append(kwargs["task_result"]) or {"id": "receipt"})
    _watch_once(monkeypatch)
    assert [row["taskId"] for row in receipts] == [completed_task["taskId"]]


@pytest.mark.parametrize("fence", ["sealed", "rewound"])
def test_recovered_pending_result_obeys_current_notification_fences(monkeypatch, completed_task, fence):
    _restart(monkeypatch)
    store = kernel._task_store()
    if fence == "sealed":
        store.seal_and_request_stop(completed_task["taskId"], reason="parent_turn_cancelled")
    else:
        store._branch_generation_reader = lambda _: 1
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: pytest.fail("fenced result delivered"))
    _watch_once(monkeypatch)
    state = store.load_state(completed_task["taskId"])
    assert state["resultDeliveryState"] == "dropped"
    assert kernel._PENDING_FINALIZATIONS == {}


def test_journal_acknowledged_before_callback_error_does_not_duplicate_wake(monkeypatch, completed_task, tmp_path):
    from core.chat.turn_journal import EVENT_CLI_TASK_RESULT, load_turn_events
    from core.ui.chat_state import build_chat_state, save_chat_state

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_cli_agent_task_result_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda *args, **kwargs: {"signalId": "signal-one"})
    wakes = []
    monkeypatch.setattr(session_service, "_wake_agent_for_cli_agent_task_result", lambda *args, **kwargs: wakes.append(True) or "wake_scheduled")
    save_chat_state(tmp_path, build_chat_state([], conversation_id="parent-session", title="parent"))
    # Simulate a failure after Journal append and wake, before the caller's ack.
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("publish interrupted")))
    kernel._finalize_task_result(completed_task, reason="protocol_pattern")
    failed = kernel._task_store().load_state(completed_task["taskId"])
    assert failed["resultDeliveryState"] == "pending"
    _restart(monkeypatch)
    due = datetime.fromisoformat(failed["resultDeliveryNextAttemptAt"]).timestamp()
    monkeypatch.setattr(kernel.time, "time", lambda: due + 1)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *args, **kwargs: None)
    _watch_once(monkeypatch)
    _watch_once(monkeypatch)
    events = [event for event in load_turn_events(tmp_path, "parent-session") if event.event_type == EVENT_CLI_TASK_RESULT]
    assert len(events) == 1
    assert events[0].correlation_id == "cli_agent_task_result:cli-receipt:completed"
    assert wakes == [True]
    assert kernel._task_store().load_state(completed_task["taskId"])["resultDeliveryState"] == "delivered"


def test_missing_parent_ack_remains_retryable(monkeypatch, completed_task):
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: None)
    kernel._finalize_task_result(completed_task, reason="protocol_pattern")
    state = kernel._task_store().load_state(completed_task["taskId"])
    assert state["resultDeliveryState"] == "pending"
    assert state["resultDeliveryLastErrorType"] == "RuntimeError"


def test_startup_does_not_replay_unmarked_historical_terminal_results(monkeypatch, completed_task):
    store = kernel._task_store()
    old = {key: value for key, value in completed_task.items() if not key.startswith("resultDelivery")}
    store.save_state(old)
    _restart(monkeypatch)
    monkeypatch.setattr(kernel, "_ensure_watcher_started", lambda: pytest.fail("historical terminal result replayed"))
    assert kernel.recover_pending_cli_agent_task_results_on_startup()["pendingResultCount"] == 0


def test_cli_startup_reconcile_starts_receipt_recovery_after_terminal_reconcile(monkeypatch):
    from core.web import lifecycle
    from core.web.services import cli_agent_terminal_service

    calls = []
    monkeypatch.setattr(cli_agent_terminal_service, "reconcile_cli_agent_terminal_states_on_startup", lambda **kwargs: calls.append("terminals") or {"staleCount": 0})
    monkeypatch.setattr(kernel, "recover_pending_cli_agent_task_results_on_startup", lambda: calls.append("receipts") or {"pendingResultCount": 1})
    report = lifecycle._reconcile_cli_agent_terminal_states_on_startup()
    assert calls == ["terminals", "receipts"]
    assert report["taskResultRecovery"] == {"pendingResultCount": 1}


def test_concurrent_finalizers_deliver_only_once(monkeypatch, completed_task):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    entered, release = threading.Event(), threading.Event()
    calls = []

    def deliver(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        return {"id": "receipt"}

    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", deliver)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(kernel._finalize_task_result, dict(completed_task), reason="first")
        assert entered.wait(10)
        try:
            workers.submit(kernel._finalize_task_result, dict(completed_task), reason="concurrent").result(timeout=10)
        finally:
            release.set()
        first.result(timeout=10)
    kernel._finalize_task_result(dict(completed_task), reason="stale_copy")
    assert calls == [True]
    assert kernel._task_store().load_state(completed_task["taskId"])["resultDeliveryState"] == "delivered"


def test_snapshot_write_failure_does_not_kill_receipt_recovery(monkeypatch, completed_task):
    store = kernel._task_store()
    update = store.update_task
    calls = []

    def fail_once(*args, **kwargs):
        monkeypatch.setattr(store, "update_task", update)
        raise OSError("snapshot unavailable")

    monkeypatch.setattr(store, "update_task", fail_once)
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda *args, **kwargs: calls.append(True) or {"id": "receipt"})
    _watch_once(monkeypatch)
    assert calls == []
    assert store.load_state(completed_task["taskId"])["resultDeliveryState"] == "pending"
    _watch_once(monkeypatch)
    assert calls == [True]


def test_pending_receipt_recovers_once_in_fresh_processes(completed_task, tmp_path):
    # Use real interpreter boundaries: no in-memory pending map or store cache
    # from the submitting process can make this receipt recoverable.
    script = r'''
import json
from pathlib import Path
import sys
from core.web.services import cli_agent_task_kernel as kernel, runtime_task_registry as registry, session_service
root = Path(sys.argv[1])
kernel.TASK_STATE_DIR = root / "cli-tasks"
registry.RuntimeTaskStore._ensure_auto_background_sweeper = lambda self: None
kernel._task_store()._branch_generation_reader = lambda _: 0
kernel.cli_agent_service._record_event = lambda *args, **kwargs: None
kernel._ensure_watcher_started = lambda: None
calls = []
def deliver(*args, **kwargs):
    calls.append(kwargs["task_result"]["taskId"])
    return {"id": "receipt"}
session_service.append_cli_agent_task_result_event = deliver
class EndWatch(Exception):
    pass
def end_watch(_):
    raise EndWatch()
kernel.time.sleep = end_watch
report = kernel.recover_pending_cli_agent_task_results_on_startup()
try:
    kernel._watch_active_tasks()
except EndWatch:
    pass
print(json.dumps({"recovered": report["pendingResultCount"], "calls": calls}))
'''
    results = []
    for _ in range(2):
        child = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        assert child.returncode == 0, child.stderr
        results.append(json.loads(child.stdout.strip().splitlines()[-1]))
    assert results == [
        {"recovered": 1, "calls": [completed_task["taskId"]]},
        {"recovered": 0, "calls": []},
    ]
