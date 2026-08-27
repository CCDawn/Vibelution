from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.chat.conversation_ledger import EVENT_USER_MESSAGE, load_conversation_events
from core.web.services import agent_directory_service, session_service
from core.web.services.session import submit as session_submit
from core.web.services.session import worker as session_worker
from core.web.services.session.proactive import (
    INTERNAL_TURN_TRIGGER_EVENT,
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


def test_user_and_proactive_turns_share_one_session_admission_lane(
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
    scheduled: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )

    admit_lock = session_submit._session_submit_admit_lock(session_id)
    admit_lock.acquire()
    start_barrier = threading.Barrier(3)
    accepted: dict[str, dict] = {}
    rejected: dict[str, Exception] = {}

    def submit(name: str, operation) -> None:
        start_barrier.wait()
        try:
            accepted[name] = operation()
        except Exception as exc:  # noqa: BLE001 - the losing lane is the assertion
            rejected[name] = exc

    user_thread = threading.Thread(
        target=submit,
        args=("user", lambda: session_service.submit_session_message(session_id, "你好")),
    )
    proactive_thread = threading.Thread(
        target=submit,
        args=(
            "proactive",
            lambda: session_service.submit_session_proactive_turn(
                session_id=session_id,
                agent_id=agent_id,
                origin="proactive_plugin",
                source_kind="virtual-human-life",
                plugin_id="virtual-human-life",
                trigger_id=str(attempt["triggerId"]),
                delivery_token=str(attempt["deliveryToken"]),
                binding_revision=int(attempt["bindingRevision"]),
                trigger={"reason": attempt["reason"]},
            ),
        ),
    )
    user_thread.start()
    proactive_thread.start()
    start_barrier.wait()
    admit_lock.release()

    try:
        user_thread.join(timeout=5)
        proactive_thread.join(timeout=5)
        assert not user_thread.is_alive()
        assert not proactive_thread.is_alive()
        assert len(accepted) == 1
        assert len(rejected) == 1
        assert isinstance(next(iter(rejected.values())), session_service.SessionBusyError)
        assert len(scheduled) == 1

        accepted_turn_id = str(scheduled[0]["turn_id"])
        accepted_events = [
            event
            for event in load_conversation_events(tmp_path, session_id)
            if event.turn_id == accepted_turn_id
        ]
        user_event_count = sum(
            event.event_type == EVENT_USER_MESSAGE for event in accepted_events
        )
        assert user_event_count == (1 if "user" in accepted else 0)
    finally:
        if admit_lock.locked():
            admit_lock.release()
        if scheduled and scheduled[0].get("origin") == "proactive_plugin":
            cancel_proactive_turn_context(scheduled[0], reason="test_cleanup")
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
