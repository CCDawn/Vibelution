"""Lifecycle stops retain their cause without becoming user feedback."""

import threading
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


@pytest.fixture(autouse=True)
def _clean_harvest_context():
    """收割上下文是模块级状态：测试前后都必须清空，防止跨测试污染。"""
    control._ACTIVE_RUNTIME_STOP_REASONS.clear()
    yield
    control._ACTIVE_RUNTIME_STOP_REASONS.clear()


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


@pytest.mark.parametrize("controller_reason", ["操作者请求停止当前轮。", "electron_user_restart"])
@pytest.mark.parametrize("reason_field", ["stop_reason", "stopReason"])
def test_challenge_deadline_result_survives_later_operator_stop(
    interrupted_session, monkeypatch, controller_reason, reason_field,
):
    deadline_reason = "challenge_logical_task_deadline_exhausted"
    monkeypatch.setattr(session_service, "_is_session_stop_requested", lambda _: True)
    monkeypatch.setattr(session_service, "_get_session_stop_reason", lambda _: controller_reason)
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *args: True)
    session_service._persist_session_turn_result(
        "session-stop", {
            "status": "stopped", "summary": "Challenge 已达到逻辑任务截止时间。",
            "raw_output": "Challenge 已达到逻辑任务截止时间。", "stop_requested": True,
            reason_field: deadline_reason,
        }, turn_id="turn-stop",
    )

    stored = load_session_chat_state(interrupted_session, "session-stop")
    assert stored["last_turn_status"] == "cancelled"
    assert stored["last_turn_terminal_problem_code"] == deadline_reason
    assert stored["last_turn_terminal_reason"] == deadline_reason
    snapshot = session_service.get_session_turn_completion_snapshot("session-stop", "turn-stop")
    assert snapshot["terminal"] is True
    assert snapshot["terminalStatus"] == "cancelled"
    assert snapshot["terminalProblemCode"] == deadline_reason
    assert snapshot["terminalReason"] == deadline_reason
    terminal = [event for event in load_conversation_events(interrupted_session, "session-stop")
                if event.event_type == EVENT_TURN_INTERRUPTED]
    assert len(terminal) == 1
    assert terminal[0].payload["reason"] == deadline_reason
    assert terminal[0].payload["finalStatus"] == "cancelled"
    assert terminal[0].payload["summary"] == "Challenge 已达到逻辑任务截止时间。"


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


# --------------------------------------------------------------------------
# 收割窗口上下文：进程级运行时停止原因（2026-10 重启收割误标事故）
#
# 退休收割窗口内，域内组件对会话回合发起的进程内停止请求可能不带
# stop_reason；旧逻辑按操作者默认文案处理，被杀回合被永久误标为用户停止，
# 已合入的证据门对这种签名 fail-closed。修复后窗口内无显式原因的停止继承
# 收割原因（机器可识别），走 runtime_stop_requested 生命周期事件路径。
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["electron_user_restart", "electron_user_close", "runtime_shutdown"])
def test_harvest_context_drives_reasonless_stop(running_control, reason):
    """收割上下文激活 + 空 stop_reason → 继承收割原因，记 runtime 生命周期事件。"""
    controller, signals, events = running_control
    with control.runtime_stop_reason_context(reason):
        control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False)
    assert controller.snapshot()["stopReason"] == reason
    # 不产生 user_stops chat 信号（与操作者停止互斥）。
    assert signals == []
    assert events[-1][0] == ("session-stop", "runtime_stop_requested")
    assert events[-1][1]["fields"] == {"source": reason, "stopReason": reason}


def test_explicit_runtime_reason_beats_harvest_context(running_control):
    """显式 stop_reason 永远优先于收割上下文（runtime_shutdown vs 上下文 electron_user_restart）。"""
    controller, signals, events = running_control
    with control.runtime_stop_reason_context("electron_user_restart"):
        control.request_stop_session_turn(
            "session-stop", fast_ack=True, cascade=False, stop_reason="runtime_shutdown",
        )
    assert controller.snapshot()["stopReason"] == "runtime_shutdown"
    assert signals == []
    assert events[-1][1]["fields"] == {"source": "runtime_shutdown", "stopReason": "runtime_shutdown"}


def test_explicit_operator_reason_beats_harvest_context(running_control):
    """显式非运行时原因同样优先：收割窗口内不吞掉显式的操作者/系统原因。"""
    controller, signals, events = running_control
    with control.runtime_stop_reason_context("electron_user_restart"):
        control.request_stop_session_turn(
            "session-stop", fast_ack=True, cascade=False,
            stop_reason="challenge_logical_task_deadline_exhausted",
        )
    assert controller.snapshot()["stopReason"] == "challenge_logical_task_deadline_exhausted"
    assert len(signals) == 1
    assert signals[0]["source"] == "user"
    assert signals[0]["kind"] == "user_stops"
    assert events == []


def test_no_harvest_context_keeps_byte_identical_operator_default(running_control):
    """回归守卫：无收割上下文 + 空 stop_reason 时与历史现状逐字节一致。"""
    controller, signals, events = running_control
    assert control.active_runtime_stop_reason() == ""
    control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False)
    assert controller.snapshot()["stopReason"] == "操作者请求停止当前轮。"
    assert len(signals) == 1
    assert signals[0]["source"] == "user"
    assert signals[0]["kind"] == "user_stops"
    assert signals[0]["polarity"] == "negative"
    assert signals[0]["mode"] == "directive"
    assert signals[0]["related_event_code"] == "conversation.user_stop_requested"
    assert signals[0]["summary"] == "用户请求停止当前对话轮次。"
    assert events == []


def test_harvest_context_nesting_restores_outer_value():
    """嵌套窗口：内层退出恢复外层值，最外层退出回到空。"""
    assert control.active_runtime_stop_reason() == ""
    with control.runtime_stop_reason_context("electron_user_restart"):
        assert control.active_runtime_stop_reason() == "electron_user_restart"
        with control.runtime_stop_reason_context("runtime_shutdown"):
            assert control.active_runtime_stop_reason() == "runtime_shutdown"
        assert control.active_runtime_stop_reason() == "electron_user_restart"
    assert control.active_runtime_stop_reason() == ""


def test_harvest_context_survives_context_manager_exception():
    """收割函数体抛异常时上下文仍必须释放（try/finally 语义）。"""
    with pytest.raises(RuntimeError):
        with control.runtime_stop_reason_context("electron_user_close"):
            raise RuntimeError("harvest failed")
    assert control.active_runtime_stop_reason() == ""


def test_harvest_context_is_visible_across_threads():
    """跨线程可见：模块状态而非线程本地（user_close 并行收割依赖此）。"""
    observed = {}
    started = threading.Event()
    release = threading.Event()

    def probe():
        observed["reason"] = control.active_runtime_stop_reason()
        started.set()
        release.wait(5)

    with control.runtime_stop_reason_context("electron_user_close"):
        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        assert started.wait(5)
        # 主线程持有窗口期间，另一线程读取到同一原因。
        assert observed["reason"] == "electron_user_close"
        release.set()
        thread.join(5)
    assert control.active_runtime_stop_reason() == ""


def _stub_harvest_owners(monkeypatch, observed):
    """把各 _stop_* 子收割器换成记录当前收割原因的记录器（最小 seam）。"""
    lock = threading.Lock()

    def recorder(name):
        def _run(*args, **kwargs):
            reason = control.active_runtime_stop_reason()
            with lock:
                observed.append((name, reason))
            return []
        return _run

    monkeypatch.setattr(runtime_service, "_stop_additional_work_for_restart", recorder("additional"))
    monkeypatch.setattr(runtime_service, "_stop_active_evolution_runs_before_shutdown", recorder("evolution"))
    monkeypatch.setattr(runtime_service, "_stop_active_source_collection_runs_before_shutdown", recorder("sources"))
    monkeypatch.setattr(runtime_service, "_stop_active_chat_room_rounds_before_shutdown", recorder("rooms"))
    monkeypatch.setattr(runtime_service, "_stop_active_chat_turns_before_shutdown", recorder("turns"))
    monkeypatch.setattr(runtime_service, "_restart_guard_active_work_runs", recorder("readback"))
    monkeypatch.setattr(runtime_service, "_record_shutdown_event", lambda *args, **kwargs: None)


def test_restart_retire_wraps_harvest_in_runtime_reason_context(monkeypatch):
    """_retire_for_user_restart 执行期间收割原因全程可见，退出后清空。"""
    observed = []
    _stub_harvest_owners(monkeypatch, observed)
    monkeypatch.setattr(runtime_service, "_electron_retire_local_shutdown", lambda lang, **kwargs: {"accepted": True})
    runtime_service._retire_for_user_restart("zh")
    assert observed
    assert {reason for _, reason in observed} == {"electron_user_restart"}
    assert control.active_runtime_stop_reason() == ""


def test_electron_retire_inherits_runtime_source(monkeypatch):
    """带运行时 source 的 retire：内部收割在同名原因窗口内执行。"""
    observed = []
    _stub_harvest_owners(monkeypatch, observed)
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda: None)
    runtime_service._electron_retire_local_shutdown("zh", source="electron_user_restart")
    assert observed
    assert {reason for _, reason in observed} == {"electron_user_restart"}
    assert control.active_runtime_stop_reason() == ""


def test_electron_retire_maps_non_runtime_source_to_runtime_shutdown(monkeypatch):
    """无 body 退休的默认 source（electron_retire）映射为 runtime_shutdown。"""
    observed = []
    _stub_harvest_owners(monkeypatch, observed)
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda: None)
    runtime_service._electron_retire_local_shutdown("zh")
    assert observed
    assert {reason for _, reason in observed} == {"runtime_shutdown"}
    assert control.active_runtime_stop_reason() == ""


def test_user_close_parallel_harvest_threads_see_runtime_reason_context(monkeypatch):
    """user_close 并行收割：新线程里的 owner 停止器都能读到收割窗口原因。"""
    from core.web.services import runtime_service_user_close

    observed = []
    lock = threading.Lock()

    def recorder(name):
        def _run(*args, **kwargs):
            reason = control.active_runtime_stop_reason()
            with lock:
                observed.append((name, reason))
            return []
        return _run

    monkeypatch.setattr(runtime_service_user_close, "_stop_autonomous", recorder("autonomous"))
    monkeypatch.setattr(runtime_service_user_close, "_stop_formal_review", recorder("formal_review"))
    monkeypatch.setattr(
        runtime_service_user_close, "_stopped_evolution",
        lambda kind, stopper: recorder(kind)(),
    )
    monkeypatch.setattr(runtime_service_user_close, "_stop_sources", recorder("sources"))
    monkeypatch.setattr(runtime_service_user_close, "_stop_rooms", recorder("rooms"))
    monkeypatch.setattr(runtime_service_user_close, "_stop_chat_turns", recorder("turns"))
    monkeypatch.setattr(runtime_service_user_close, "_remaining_work", recorder("readback"))
    monkeypatch.setattr(runtime_service, "_record_shutdown_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_service, "_electron_retire_local_shutdown", lambda lang, **kwargs: {"accepted": True})

    runtime_service_user_close.retire_for_user_close("zh")

    names = {name for name, _ in observed}
    assert {"autonomous", "formal_review", "self_evolution_run", "sources", "rooms", "turns", "readback"} <= names
    assert {reason for _, reason in observed} == {"electron_user_close"}
    assert control.active_runtime_stop_reason() == ""


def test_harvest_context_stop_yields_recoverable_dead_turn_evidence(
    interrupted_session, running_control,
):
    """端到端：收割窗口内无原因停止 → journal 保留运行时原因，证据门通过。

    事故形态：收割级联在窗口内对资料搜集会话回合发起无 stop_reason 的停止，
    journal 若落操作者默认文案 + user_stops 信号，已合入的
    runtime_stop_evidence_confirmed 对这种签名 fail-closed，blocked 节点永不
    自动重驱。修复后同一停止写出 reason=electron_user_close 且无 user_stops
    信号的证据，stopped 死回合可被证据门放行。
    """
    from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
        runtime_stop_evidence_confirmed,
    )

    controller, signals, _ = running_control
    with control.runtime_stop_reason_context("electron_user_close"):
        control.request_stop_session_turn("session-stop", fast_ack=True, cascade=False)
        snapshot = controller.snapshot()
        control._persist_session_interrupted_snapshot("session-stop", snapshot, lang="zh")

    terminal = [event for event in load_conversation_events(interrupted_session, "session-stop")
                if event.event_type == EVENT_TURN_INTERRUPTED]
    assert len(terminal) == 1
    assert terminal[0].payload["reason"] == "electron_user_close"
    assert signals == []
    assert runtime_stop_evidence_confirmed({
        "sessionId": "session-stop",
        "turnId": "turn-stop",
        "terminalStatus": "stopped",
        "terminalReason": "stopped_by_user",
    })
