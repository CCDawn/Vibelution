"""停止收尾总上界 watchdog 与停止阶段登记的行为锁定。

覆盖三类契约：
1. stopRequested 后未 settle、fake 时钟推进超阈值 → 强制收尾发生、
   interrupted 快照路径被复用、stopForced 原因标记随行；
2. 正常 settle 早于阈值 → watchdog 静默退出，无任何副作用；
3. fast_ack 返回形状不变（完整语义回归由
   test_launcher_assistant_runtime_operations.py::test_real_session_stop_retains_turn_identity_and_only_acknowledges_request
   锁定，本文件只锁定返回形状与 bookkeeping 不越界）。
"""

import time

import pytest

from core.web.services import session_service
from core.web.services.session import control


@pytest.fixture(autouse=True)
def _clean_stop_watchdog_state(monkeypatch):
    """watchdog/阶段登记是模块级状态：测试前后清空，防跨测试污染。

    同时清掉可能存在的外部阈值覆盖，保证用例内的量级断言确定。
    """
    monkeypatch.delenv("VIBELUTION_STOP_SETTLEMENT_WATCHDOG_SECONDS", raising=False)
    with control._ARMED_STOP_WATCHDOGS_LOCK:
        control._ARMED_STOP_WATCHDOGS.clear()
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES.clear()
    yield
    with control._ARMED_STOP_WATCHDOGS_LOCK:
        control._ARMED_STOP_WATCHDOGS.clear()
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES.clear()


class _FakeClock:
    """watchdog 的时间源缝隙（control._MONOTONIC）的可控替身。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def stop_env(monkeypatch):
    controller = session_service.SessionTurnControl(
        session_id="session-watch", turn_id="turn-watch"
    )
    events: list[tuple[tuple, dict]] = []
    snapshot_calls: list[tuple[str, dict, dict]] = []
    running_calls: list[tuple[str, bool, dict]] = []
    published: list[tuple] = []
    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _sid: controller)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda *args: False)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda **kwargs: None)
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_interrupted_snapshot",
        lambda sid, snap, **kwargs: snapshot_calls.append((sid, snap, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda sid, running, **kwargs: running_calls.append((sid, running, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda *args, **kwargs: published.append(args),
    )
    monkeypatch.setattr(session_service, "_clear_session_turn_control", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "get_session_detail", lambda *args, **kwargs: None)
    return controller, events, snapshot_calls, running_calls, published


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_watchdog_waits_below_threshold_then_forces_settle_with_forced_snapshot(stop_env, monkeypatch):
    """超阈值才强制收尾：复用 interrupted 快照路径并带 stopForced 标记。"""
    controller, events, snapshot_calls, running_calls, published = stop_env
    clock = _FakeClock()
    monkeypatch.setattr(control, "_MONOTONIC", clock)

    control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    assert controller.snapshot()["stopRequested"] is True
    assert ("session-watch", "turn-watch") in control._ARMED_STOP_WATCHDOGS

    # 阈值内（还差 5s）：真实等待 1.2s（≥3 个 watchdog tick）不得出现任何
    # 强制收尾副作用。
    clock.now += control.STOP_SETTLEMENT_WATCHDOG_SECONDS - 5
    escalated_below_threshold = _wait_until(
        lambda: bool(snapshot_calls)
        or any(args[1] == "stop_watchdog_forced" for args, _kwargs in events),
        timeout=1.2,
    )
    assert escalated_below_threshold is False
    assert controller.snapshot()["releasedToUser"] is False

    # 推进超阈值 → watchdog 升级强制收尾。
    clock.now += 30
    assert _wait_until(lambda: bool(snapshot_calls), timeout=5.0)
    session_id, forced_snapshot, kwargs = snapshot_calls[0]
    assert session_id == "session-watch"
    assert kwargs.get("lang") == "zh"
    assert forced_snapshot.get("stopRequested") is True
    assert forced_snapshot.get("stopForced") is True
    assert controller.snapshot()["releasedToUser"] is True
    assert any(args[1] == "stop_watchdog_forced" for args, _kwargs in events)
    assert any(
        sid == "session-watch" and running is False and call_kwargs.get("turn_id") == "turn-watch"
        for sid, running, call_kwargs in running_calls
    )
    assert published  # 强制收尾后 detail 必须被重新发布

    # 阶段登记：requested → forced；watchdog 退出后武装集合清理。
    stages = control._session_stop_stages_for_projection("session-watch", "turn-watch")
    assert [entry["stage"] for entry in stages] == ["requested", "forced"]
    assert stages[1]["watchdogSeconds"] == pytest.approx(control.STOP_SETTLEMENT_WATCHDOG_SECONDS)
    assert ("session-watch", "turn-watch") not in control._ARMED_STOP_WATCHDOGS


def test_watchdog_stays_silent_when_turn_settles_before_threshold(stop_env, monkeypatch):
    """正常 settle（控制登记清除 + 运行标记清除）早于阈值 → 无副作用退出。"""
    controller, events, snapshot_calls, running_calls, published = stop_env
    clock = _FakeClock()
    monkeypatch.setattr(control, "_MONOTONIC", clock)

    control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    assert ("session-watch", "turn-watch") in control._ARMED_STOP_WATCHDOGS

    # 模拟 worker 正常收尾：turn control 被清理、运行标记清除。
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _sid: None)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: False)

    assert _wait_until(
        lambda: ("session-watch", "turn-watch") not in control._ARMED_STOP_WATCHDOGS,
        timeout=3.0,
    )
    assert snapshot_calls == []
    assert not any(args[1] == "stop_watchdog_forced" for args, _kwargs in events)
    assert running_calls == []
    assert published == []
    assert controller.snapshot()["releasedToUser"] is False


def test_fast_ack_reply_shape_and_bookkeeping_are_unchanged(stop_env):
    """fast_ack 返回形状锁定；bookkeeping（快照/运行标记）不越界。"""
    controller, _events, snapshot_calls, running_calls, _published = stop_env
    result = control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    assert result == {
        "id": "session-watch",
        "currentPhase": "stopping",
        "stopRequested": True,
        "stopRequestedAt": controller.snapshot()["stopRequestedAt"],
        "activeTurnId": "turn-watch",
    }
    assert snapshot_calls == []
    assert running_calls == []
    # 停止阶段已登记（requested），停止未 settle，投影可读。
    stages = control._session_stop_stages_for_projection("session-watch", "turn-watch")
    assert [entry["stage"] for entry in stages] == ["requested"]


def test_queued_stop_settles_synchronously_without_watchdog(stop_env, monkeypatch):
    """排队取消路径同步 settle：快照落盘、released、无 watchdog 残留。"""
    controller, _events, snapshot_calls, running_calls, _published = stop_env
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda *args: True)
    result = control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    assert snapshot_calls and snapshot_calls[0][0] == "session-watch"
    assert running_calls and running_calls[0][1] is False
    assert controller.snapshot()["releasedToUser"] is True
    assert result.get("stopRequested") is True
    assert ("session-watch", "turn-watch") not in control._ARMED_STOP_WATCHDOGS
    # 同步 settle 后阶段登记已释放，不再留给投影。
    assert control._session_stop_stages_for_projection("session-watch", "turn-watch") == []


def test_worker_finish_clears_stop_stage_registry(monkeypatch):
    """worker 终局清理阶段登记：无论正常结束还是停止收尾都不留残余。"""
    from core.web.services.session import worker

    control._record_session_stop_stage(
        "session-finish", "turn-finish", control.SESSION_STOP_STAGE_REQUESTED
    )
    assert control._session_stop_stages_for_projection("session-finish", "turn-finish")
    monkeypatch.setattr(session_service, "_ensure_session_turn_terminal_fallback", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "_record_session_execution_registry_event", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *a, **k: True)
    monkeypatch.setattr(session_service, "_clear_session_turn_control", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "_set_session_running", lambda *a, **k: None)
    worker._finish_session_turn_worker("session-finish", "turn-finish", None)
    assert control._session_stop_stages_for_projection("session-finish", "turn-finish") == []


def test_detail_projection_exposes_stop_stages_while_stopping(monkeypatch):
    """detail 投影在停止窗口内透出 stopStages；settle 后不再透出。"""
    from core.web.services.session import projection as session_projection

    controller = session_service.SessionTurnControl(
        session_id="session-stage", turn_id="turn-stage"
    )
    controller.request_stop("操作者请求停止当前轮。")
    control._record_session_stop_stage(
        "session-stage", "turn-stage", control.SESSION_STOP_STAGE_REQUESTED
    )
    control._record_session_stop_stage(
        "session-stage",
        "turn-stage",
        control.SESSION_STOP_STAGE_TOOLS_CANCELLED,
        outcome="quiescent",
    )

    conversation = {
        "id": "session-stage",
        "conversation_id": "session-stage",
        "title": "stage",
        "status": "ready",
        "messages": [],
        "last_turn_status": "ready",
        "agent_id": "agent-stage",
    }
    summary = {
        "id": "session-stage",
        "title": "stage",
        "status": "ready",
        "taskSummary": "",
        "lastActive": "",
        "updatedAt": "",
        "currentPhase": "stopping",
        "agentId": "agent-stage",
    }

    def boom(*_args, **_kwargs):
        raise AssertionError("secondary hydrate should be skipped")

    monkeypatch.setattr(session_service, "_recent_chat_next_state_signal_summaries", boom)
    monkeypatch.setattr(session_service, "list_group_context_events_for_agent", boom)
    monkeypatch.setattr(session_service, "list_agent_inbox_messages_for_agent", boom)
    monkeypatch.setattr(session_service, "_pending_tool_governance_requests_for_session", boom)
    monkeypatch.setattr(session_service, "_session_agent_is_available", lambda _summary: True)
    monkeypatch.setattr(
        session_service,
        "_session_detail_agent_snapshot",
        lambda *_args, **_kwargs: {"toolPolicy": {}, "memoryPolicy": {}},
    )
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda *_args, **_kwargs: controller)
    monkeypatch.setattr(session_service, "_active_chat_turn_work_run_for_session", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_normalize_session_active_task", lambda value: value if isinstance(value, dict) else None)
    monkeypatch.setattr(session_service, "_is_task_tool_backed_active_task", lambda _task: False)
    monkeypatch.setattr(session_service, "_session_detail_window_requested", lambda **_kwargs: False)
    monkeypatch.setattr(session_service, "_messages_with_live_output", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "_normalize_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "_build_session_context_usage", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_session_last_llm_usage", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_build_session_cache_usage", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_current_session_live_context_composition", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_normalize_session_context_composition", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_current_session_live_llm_payload_trace", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_normalize_session_llm_payload_trace", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_session_last_cache_composition", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda *_a, **_k: 0)
    monkeypatch.setattr(session_service, "_active_task_to_api", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_visible_session_runtime_notices", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "_normalize_session_runtime_notices", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "normalize_active_skill_contract", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_normalize_child_handoff_context", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_session_turn_error_to_api", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_current_session_turn_id", lambda *_a, **_k: "")
    monkeypatch.setattr(session_service, "_session_branch_metadata", lambda *_a, **_k: ("", ""))

    detail = session_projection._build_session_detail_from_summary(
        conversation,
        summary,
        hydrate_agent=True,
        include_secondary=False,
    )
    assert detail["stopRequested"] is True
    assert detail["stopReason"] == "操作者请求停止当前轮。"
    stages = detail["stopStages"]
    assert [entry["stage"] for entry in stages] == ["requested", "tools_cancelled"]
    assert stages[1]["outcome"] == "quiescent"
    assert all(entry.get("at") for entry in stages)

    # settle（releasedToUser）后不再透出阶段列表。
    controller.mark_released_to_user()
    detail_after = session_projection._build_session_detail_from_summary(
        conversation,
        summary,
        hydrate_agent=True,
        include_secondary=False,
    )
    assert detail_after["stopStages"] == []


def test_repeat_stop_request_does_not_stack_watchdogs(stop_env, monkeypatch):
    """同一 (session, turn) 的重复停止请求只保留一个 watchdog。"""
    controller, _events, _snapshot_calls, _running_calls, _published = stop_env
    clock = _FakeClock()
    monkeypatch.setattr(control, "_MONOTONIC", clock)
    control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    armed = [
        key
        for key in tuple(control._ARMED_STOP_WATCHDOGS)
        if key == ("session-watch", "turn-watch")
    ]
    assert armed == [("session-watch", "turn-watch")]
    assert controller.snapshot()["stopRequested"] is True


def test_disabled_threshold_arms_no_watchdog(stop_env, monkeypatch):
    """阈值置 0 显式禁用：不武装 watchdog，停止登记语义不变。"""
    controller, _events, snapshot_calls, _running_calls, _published = stop_env
    monkeypatch.setenv("VIBELUTION_STOP_SETTLEMENT_WATCHDOG_SECONDS", "0")
    result = control.request_stop_session_turn("session-watch", fast_ack=True, cascade=False)
    assert result["stopRequested"] is True
    assert control._ARMED_STOP_WATCHDOGS == set()
    assert controller.snapshot()["stopRequested"] is True
    assert snapshot_calls == []
