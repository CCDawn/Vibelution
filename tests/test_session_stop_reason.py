"""Lifecycle stops retain their cause without becoming user feedback."""

from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import (
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    append_conversation_event,
    load_conversation_events,
)
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import runtime_service, session_service
from core.web.services.session import control


@pytest.fixture
def running_control(monkeypatch):
    controller = session_service.SessionTurnControl(session_id="session-stop", turn_id="turn-stop")
    signals, events = [], []
    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "_is_session_running", lambda _: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _: controller)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda *args: False)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda **kwargs: signals.append(kwargs))
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *args, **kwargs: events.append((args, kwargs)))
    return controller, signals, events


@pytest.mark.parametrize("reason", ["electron_user_restart", "electron_user_close", "runtime_shutdown"])
def test_lifecycle_stop_records_runtime_cause_without_user_feedback(running_control, reason):
    controller, signals, events = running_control
    control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False, stop_reason=reason)
    assert controller.snapshot()["stopReason"] == reason
    assert signals == []
    assert events[-1][0] == ("session-stop", "runtime_stop_requested")
    assert events[-1][1]["fields"] == {"source": reason, "stopReason": reason}


def test_manual_stop_keeps_existing_reason_and_user_feedback(running_control):
    controller, signals, events = running_control
    control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False)
    assert controller.snapshot()["stopReason"] == "操作者请求停止当前轮。"
    assert signals[0]["source"] == "user"
    assert signals[0]["kind"] == "user_stops"
    assert events == []


def test_later_manual_stop_cannot_relabel_a_restart(running_control):
    controller, signals, _ = running_control
    controller.request_stop("electron_user_restart")
    control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False)
    assert controller.snapshot()["stopReason"] == "electron_user_restart"
    assert signals == []


def test_restart_cascade_keeps_child_stop_cause(monkeypatch):
    from core.web.services import runtime_task_registry

    calls = []
    monkeypatch.setattr(runtime_task_registry, "default_store", lambda: SimpleNamespace(
        collect_cascade_targets=lambda _: [{"taskId": "child", "kind": "child_session"}],
        seal_and_request_stop=lambda *args, **kwargs: None,
    ))
    monkeypatch.setattr(control, "request_stop_session_turn", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *args, **kwargs: None)
    control._cascade_stop_descendant_runtime_tasks("session-stop", turn_id="turn-stop", stop_reason="electron_user_restart")
    assert calls == [(("child",), {"cascade": False, "stop_reason": "electron_user_restart"})]


@pytest.fixture
def interrupted_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", lambda **kwargs: None)
    monkeypatch.setattr(session_service, "_clear_session_live_output", lambda *args, **kwargs: None)
    save_chat_state(tmp_path, {"version": 1, "conversations": [{
        "conversation_id": "session-stop", "title": "Stop reason", "last_turn_status": "running",
    }]})
    append_conversation_event(tmp_path, "session-stop", "turn-stop", EVENT_TURN_STARTED, status="running")
    return tmp_path


@pytest.mark.parametrize("reason,expected", [
    ("electron_user_restart", "工作台重启中断"),
    ("electron_user_close", "工作台关闭中断"),
    ("操作者请求停止当前轮。", "本轮已按请求停止"),
])
@pytest.mark.parametrize("queued", [False, True])
def test_interrupted_snapshot_persists_reason_and_matching_message(
    interrupted_session, monkeypatch, reason, expected, queued,
):
    monkeypatch.setattr(session_service, "_snapshot_session_live_output", lambda _: SimpleNamespace(
        content="" if queued else "已有进度", stage="queued" if queued else "running",
    ))
    control._persist_session_interrupted_snapshot(
        "session-stop", {"turnId": "turn-stop", "stopReason": reason}, lang="zh",
    )
    events = load_conversation_events(interrupted_session, "session-stop")
    terminal = [event for event in events if event.event_type == EVENT_TURN_INTERRUPTED]
    assert len(terminal) == 1
    assert terminal[0].payload["reason"] == reason
    assert expected in terminal[0].payload["summary"]
    assert ("尚未开始执行" in terminal[0].payload["summary"]) is queued
    row = load_session_chat_state(interrupted_session, "session-stop")
    assert row["last_turn_terminal_reason"] == "stopped_by_user"


@pytest.mark.parametrize("reason,expected", [
    ("electron_user_restart", "工作台重启中断"),
    ("electron_user_close", "工作台关闭中断"),
    ("操作者请求停止当前轮。", "本轮已按请求停止"),
])
def test_worker_settlement_retains_controller_cause(interrupted_session, monkeypatch, reason, expected):
    monkeypatch.setattr(session_service, "_is_session_stop_requested", lambda _: True)
    monkeypatch.setattr(session_service, "_get_session_stop_reason", lambda _: reason)
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *args: True)
    session_service._persist_session_turn_result(
        "session-stop", control._build_stopped_turn_result("stale-worker-reason"),
        turn_id="turn-stop",
    )
    terminal = [event for event in load_conversation_events(interrupted_session, "session-stop")
                if event.event_type == EVENT_TURN_INTERRUPTED]
    assert len(terminal) == 1
    assert terminal[0].payload["reason"] == reason
    assert expected in terminal[0].payload["summary"]


@pytest.mark.parametrize("reason", ["electron_user_restart", "electron_user_close", "runtime_shutdown"])
def test_runtime_snapshot_helper_passes_internal_reason(monkeypatch, reason):
    calls = []
    monkeypatch.setattr(runtime_service, "request_stop_session_turn", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _: None)
    runtime_service._stop_and_persist_chat_turn_for_restart("session-stop", stop_reason=reason)
    assert calls == [(("session-stop",), {"fast_ack": True, "stop_reason": reason})]


def test_runtime_snapshot_helper_default_does_not_invent_a_restart(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime_service, "request_stop_session_turn", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _: None)
    runtime_service._stop_and_persist_chat_turn_for_restart("session-stop")
    assert calls[0]["stop_reason"] == "runtime_shutdown"


def test_close_owner_passes_close_reason(monkeypatch):
    import time
    from core.web.services import runtime_service_user_close

    calls = []
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda **kwargs: [{"sessionId": "session-stop", "runId": "turn-stop"}])
    monkeypatch.setattr(runtime_service, "_stop_and_persist_chat_turn_for_restart", lambda *args, **kwargs: calls.append((args, kwargs)))
    runtime_service_user_close._stop_chat_turns(time.monotonic() + 1)
    assert calls == [(("session-stop",), {"stop_reason": "electron_user_close"})]


def test_restart_harvest_passes_restart_reason(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [{"sessionId": "session-stop", "runId": "turn-stop"}])
    monkeypatch.setattr(runtime_service, "_stop_and_persist_chat_turn_for_restart", lambda *args, **kwargs: calls.append((args, kwargs)))
    runtime_service._stop_active_chat_turns_before_shutdown(persist_partials=True, stop_reason="electron_user_restart")
    assert calls == [(("session-stop",), {"stop_reason": "electron_user_restart"})]


@pytest.mark.parametrize("worker_first", [False, True])
def test_restart_and_worker_settle_once_with_same_cause(
    interrupted_session, running_control, monkeypatch, worker_first,
):
    from core.chat import turn_journal

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *args: True)
    monkeypatch.setattr(session_service, "_set_session_running", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_snapshot_session_live_output", lambda _: None)

    def worker_settle():
        session_service._persist_session_turn_result(
            "session-stop", control._build_stopped_turn_result("electron_user_restart"),
            turn_id="turn-stop",
        )

    def stop(session_id, **kwargs):
        control.request_stop_session_turn(session_id, cascade=False, **kwargs)
        if worker_first:
            worker_settle()

    monkeypatch.setattr(runtime_service, "request_stop_session_turn", stop)
    runtime_service._stop_and_persist_chat_turn_for_restart("session-stop", stop_reason="electron_user_restart")
    if not worker_first:
        worker_settle()
    assert turn_journal.turn_has_terminal_event(interrupted_session, "session-stop", "turn-stop")
    terminal = [event for event in load_conversation_events(interrupted_session, "session-stop")
                if event.event_type == EVENT_TURN_INTERRUPTED]
    assert len(terminal) == 1
    assert terminal[0].payload["reason"] == "electron_user_restart"
    assert "工作台重启中断" in terminal[0].payload["summary"]
    assert running_control[1] == []
