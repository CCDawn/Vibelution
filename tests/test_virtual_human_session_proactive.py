from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.chat.conversation_ledger import EVENT_USER_MESSAGE, load_conversation_events
from core.web.services import agent_directory_service, session_service
from core.web.services.session import worker as session_worker
from core.web.services.session.proactive import (
    INTERNAL_TURN_TRIGGER_EVENT,
    admit_session_proactive_turn,
    cancel_proactive_turn_context,
)
from core.web.services.virtual_human_life_service import (
    set_virtual_human_life_service_for_tests,
)
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)


def test_proactive_turn_records_internal_trigger_without_user_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    agent_id = str(agent["agentId"])
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda target_id, include_archived=False: (
            agent if target_id == agent_id else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda target_id: (
            tmp_path / "agents" / target_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    service.set_binding(agent_id, enabled=True, expected_version=0)
    attempt = service.request_proactive_message(
        agent_id,
        reason="刚完成一项生活活动，想自然地分享近况",
    )
    set_virtual_human_life_service_for_tests(service)
    scheduled: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )

    try:
        accepted = session_service.submit_session_proactive_turn(
            session_id=session_id,
            agent_id=agent_id,
            origin="proactive_plugin",
            source_kind="virtual-human-life",
            plugin_id="virtual-human-life",
            trigger_id=str(attempt["triggerId"]),
            delivery_token=str(attempt["deliveryToken"]),
            binding_revision=int(attempt["bindingRevision"]),
            trigger={
                "reason": attempt["reason"],
                "validUntil": attempt["validUntil"],
            },
        )
        assert admit_session_proactive_turn(scheduled[0]) == "admitted"

        events = load_conversation_events(tmp_path, session_id)
        assert accepted["accepted"] is True
        proactive_turn_events = [
            event for event in events if event.turn_id == accepted["turnId"]
        ]
        assert EVENT_USER_MESSAGE not in [event.event_type for event in proactive_turn_events]
        trigger_event = next(
            event for event in events if event.event_type == INTERNAL_TURN_TRIGGER_EVENT
        )
        assert trigger_event.visible_in_model is False
        assert trigger_event.payload["triggerId"] == attempt["triggerId"]
        assert scheduled[0]["origin"] == "proactive_plugin"
        assert scheduled[0]["user_message"] == ""
        assert scheduled[0]["raw_user_message"] == ""
        assert scheduled[0]["proactive_plugin"]["deliveryToken"] == attempt["deliveryToken"]
        cancel_proactive_turn_context(scheduled[0], reason="binding_disabled_during_turn")
        assert service.proactive_attempt(
            agent_id, attempt["deliveryToken"]
        )["status"] == "cancelled"
    finally:
        set_virtual_human_life_service_for_tests(None)
        _reset_seeded_session_runtime(session_id)


def test_proactive_receipt_failure_does_not_fail_persisted_session_turn(monkeypatch) -> None:
    def fail_receipt(_context: dict) -> None:
        raise OSError("receipt storage unavailable")

    monkeypatch.setattr(
        "core.web.services.virtual_human_life_service.finalize_proactive_delivery",
        fail_receipt,
    )

    session_worker._finalize_proactive_delivery_after_persist(
        {
            "origin": "proactive_plugin",
            "agent_id": "agent-a",
            "session_id": "session-a",
            "turn_id": "turn-a",
        }
    )


def test_proactive_turn_waits_for_user_turn_then_captures_latest_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    agent_id = str(agent["agentId"])
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda target_id, include_archived=False: (
            agent if target_id == agent_id else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda target_id: (
            tmp_path / "agents" / target_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    service.set_binding(agent_id, enabled=True, expected_version=0)
    attempt = service.request_proactive_message(agent_id, reason="并发入场测试")
    set_virtual_human_life_service_for_tests(service)
    class CapturingExecutor:
        def __init__(self) -> None:
            self.contexts: list[dict] = []

        def submit(self, _operation, context):
            self.contexts.append(context)

    executor = CapturingExecutor()
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    session_service._SESSION_TURN_SCHEDULER.clear()
    user_control = session_service._create_session_turn_control(
        session_id,
        turn_id="turn-user-active",
    )
    session_service._set_session_running(
        session_id,
        True,
        turn_id=user_control.turn_id,
        leases=[],
    )
    user_context = {
        "session_id": session_id,
        "turn_id": user_control.turn_id,
        "turn_control": user_control,
        "agent_id": agent_id,
        "user_message": "用户当前轮",
        "raw_user_message": "用户当前轮",
    }
    scheduled_user: list[dict] = []
    session_service._SESSION_TURN_SCHEDULER.schedule(
        user_context,
        submit=scheduled_user.append,
        release=lambda _context: None,
    )

    try:
        accepted = session_service.submit_session_proactive_turn(
            session_id=session_id,
            agent_id=agent_id,
            origin="proactive_plugin",
            source_kind="virtual-human-life",
            plugin_id="virtual-human-life",
            trigger_id=str(attempt["triggerId"]),
            delivery_token=str(attempt["deliveryToken"]),
            binding_revision=int(attempt["bindingRevision"]),
            trigger={"reason": attempt["reason"]},
        )
        assert accepted["status"] == "queued"
        assert session_service._current_session_turn_id(session_id) == user_control.turn_id
        assert not any(
            event.turn_id == accepted["turnId"]
            for event in load_conversation_events(tmp_path, session_id)
        )

        session_service._append_session_conversation_event(
            session_id,
            user_control.turn_id,
            EVENT_USER_MESSAGE,
            status="recorded",
            payload={"content": "这是刚刚完成的用户轮次"},
            source="test",
            visible_in_model=True,
        )
        session_service._set_session_running(
            session_id,
            False,
            turn_id=user_control.turn_id,
        )
        session_service._clear_session_turn_control(
            session_id,
            turn_id=user_control.turn_id,
        )
        session_service._release_scheduled_session_turn(scheduled_user[0])

        assert len(executor.contexts) == 1
        proactive_context = executor.contexts[0]
        assert proactive_context["turn_id"] == accepted["turnId"]
        assert proactive_context["_proactive_admitted"] is True
        assert any(
            item.get("role") == "user"
            and "这是刚刚完成的用户轮次" in str(item.get("content") or "")
            for item in proactive_context["history_messages"]
        )
        assert session_service._current_session_turn_id(session_id) == accepted["turnId"]
    finally:
        if executor.contexts:
            proactive_context = executor.contexts[0]
            cancel_proactive_turn_context(proactive_context, reason="test_cleanup")
            session_service._set_session_running(
                session_id,
                False,
                turn_id=str(proactive_context.get("turn_id") or ""),
            )
            session_service._clear_session_turn_control(
                session_id,
                turn_id=str(proactive_context.get("turn_id") or ""),
            )
            session_service._SESSION_TURN_SCHEDULER.release(proactive_context)
        session_service._SESSION_TURN_SCHEDULER.clear()
        set_virtual_human_life_service_for_tests(None)
        _reset_seeded_session_runtime(session_id)


def test_proactive_executor_submit_failure_closes_the_admitted_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    agent_id = str(agent["agentId"])
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda target_id, include_archived=False: (
            agent if target_id == agent_id else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda target_id: (
            tmp_path / "agents" / target_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    service.set_binding(agent_id, enabled=True, expected_version=0)
    attempt = service.request_proactive_message(agent_id, reason="提交失败收口测试")

    class FailingExecutor:
        @staticmethod
        def submit(_operation, _context):
            raise RuntimeError("executor unavailable")

    set_virtual_human_life_service_for_tests(service)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", FailingExecutor())
    session_service._SESSION_TURN_SCHEDULER.clear()
    try:
        with pytest.raises(RuntimeError, match="executor unavailable"):
            session_service.submit_session_proactive_turn(
                session_id=session_id,
                agent_id=agent_id,
                origin="proactive_plugin",
                source_kind="virtual-human-life",
                plugin_id="virtual-human-life",
                trigger_id=str(attempt["triggerId"]),
                delivery_token=str(attempt["deliveryToken"]),
                binding_revision=int(attempt["bindingRevision"]),
                trigger={"reason": attempt["reason"]},
            )

        assert session_service._is_session_running(session_id) is False
        assert session_service._get_session_turn_control(session_id) is None
        assert service.proactive_attempt(
            agent_id,
            str(attempt["deliveryToken"]),
        )["status"] == "cancelled"
    finally:
        session_service._SESSION_TURN_SCHEDULER.clear()
        set_virtual_human_life_service_for_tests(None)
        _reset_seeded_session_runtime(session_id)


def test_stale_proactive_turn_is_cancelled_before_prepare(monkeypatch) -> None:
    cancelled: list[tuple[dict, str]] = []
    finished: list[tuple[str, str, object]] = []

    monkeypatch.setattr(session_worker, "_proactive_turn_is_current", lambda _context: False)
    monkeypatch.setattr(
        session_worker,
        "_cancel_stale_proactive_turn",
        lambda context, *, reason: cancelled.append((context, reason)),
    )
    monkeypatch.setattr(
        session_worker,
        "_finish_session_turn_worker",
        lambda session_id, turn_id, turn_control: finished.append(
            (session_id, turn_id, turn_control)
        ),
    )

    def fail_if_prepared(_context: dict) -> None:
        raise AssertionError("stale proactive turns must not enter turn preparation")

    monkeypatch.setattr(session_worker, "_run_session_turn_impl", fail_if_prepared)
    turn_control = session_service.SessionTurnControl("session-stale", "turn-stale")
    context = {
        "origin": "proactive_plugin",
        "session_id": "session-stale",
        "turn_id": "turn-stale",
        "turn_control": turn_control,
    }

    session_worker._run_session_turn(context)

    assert cancelled == [(context, "binding_revision_fence_before_prepare")]
    assert finished == [("session-stale", "turn-stale", turn_control)]
