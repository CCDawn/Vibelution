"""Guide and queue follow-ups share one session journal fact."""

from __future__ import annotations

from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_TURN_STEER,
    EVENT_USER_MESSAGE,
    load_conversation_events,
)
from core.chat.turn_journal import EVENT_TURN_STEER as JOURNAL_TURN_STEER
from core.chat.turn_journal import (
    MODEL_VISIBLE_EVENT_TYPES,
    TURN_PHASE_OUT_OF_BAND,
    model_visible_messages_from_events,
    turn_event_phase,
)
from core.web.services import session_service
from core.web.services.session import queued_turns, submit
from tests.test_session_submit import _seed_submittable_sessions


def test_turn_steer_is_out_of_band_and_not_model_visible() -> None:
    assert turn_event_phase(JOURNAL_TURN_STEER) == TURN_PHASE_OUT_OF_BAND
    assert JOURNAL_TURN_STEER not in MODEL_VISIBLE_EVENT_TYPES


def test_open_turn_guide_stays_one_model_visible_message(tmp_path: Path, monkeypatch) -> None:
    from core.chat.conversation_ledger import EVENT_TURN_STARTED, append_conversation_event

    session_id = "session-guidance-open"
    turn_id = "turn-open"
    guidance = "check the queue contract"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    _seed_submittable_sessions(tmp_path, [session_id])
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        visible_in_model=False,
    )

    class _OpenTurnControl:
        turn_id = "turn-open"

        def snapshot(self) -> dict:
            return {
                "turnId": turn_id,
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

        turn_id = "turn-open"

    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: _OpenTurnControl())
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)

    submit.submit_session_guidance(session_id, guidance, mode="safe")

    events = load_conversation_events(tmp_path, session_id)
    steer_events = [event for event in events if event.event_type == EVENT_TURN_STEER]
    assert [(event.payload.get("delivery"), event.payload.get("disposition")) for event in steer_events] == [
        ("guide", "admitted"),
    ]
    user_copies = [
        event
        for event in events
        if event.event_type == EVENT_USER_MESSAGE and event.payload.get("content") == guidance
    ]
    assert len(user_copies) == 1
    assert user_copies[0].payload["metadata"]["steerId"] == steer_events[0].payload["steerId"]
    assert user_copies[0].payload["metadata"]["clientSubmissionId"] == (
        f"steer:{steer_events[0].payload['steerId']}"
    )
    assert session_service.list_session_queued_turns(session_id) == []
    visible = [
        item
        for item in model_visible_messages_from_events(events)
        if str(item.get("content") or "") == guidance
    ]
    assert len(visible) == 1


def test_busy_queue_admission_and_promotion_share_one_steer_id(tmp_path: Path, monkeypatch) -> None:
    session_id = "session-queue-steer"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    _seed_submittable_sessions(tmp_path, [session_id])

    class _BusyTurn:
        turn_id = "turn-busy"

        def snapshot(self) -> dict:
            return {
                "turnId": "turn-busy",
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: _BusyTurn())

    row = queued_turns.enqueue_session_queued_turn(
        session_id,
        content="send this next",
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=None,
        client_submission_id="client-queue-1",
    )
    admitted = [
        event
        for event in load_conversation_events(tmp_path, session_id)
        if event.event_type == EVENT_TURN_STEER
    ]
    assert len(admitted) == 1
    assert admitted[0].payload["steerId"] == row["id"]
    assert admitted[0].payload["delivery"] == "queue"
    assert admitted[0].payload["disposition"] == "admitted"
    assert admitted[0].payload["targetTurnId"] == "turn-busy"
    assert admitted[0].visible_in_model is False

    receipt = submit._append_initial_session_journal_markers(
        session_id=session_id,
        turn_id="turn-next",
        client_submission_id="client-queue-1",
        agent={"agentId": "agent-a"},
        conversation={"title": session_id},
        source="queued_turn",
        leases=["readonly_chat"],
        user_payload={
            "content": "send this next",
            "metadata": {"clientSubmissionId": "client-queue-1"},
        },
        turn_steer_promotion={"steerId": row["id"], "delivery": "queue"},
    )

    events = load_conversation_events(tmp_path, session_id)
    promotions = [
        event
        for event in events
        if event.event_type == EVENT_TURN_STEER and event.payload.get("disposition") == "promoted"
    ]
    assert len(promotions) == 1
    assert promotions[0].turn_id == "turn-next"
    assert promotions[0].payload["steerId"] == row["id"]
    assert "content" not in promotions[0].payload
    assert promotions[0].correlation_id == "client-queue-1"
    assert receipt["journalEventId"]
    visible = model_visible_messages_from_events(events)
    assert [item.get("content") for item in visible if item.get("content") == "send this next"] == [
        "send this next",
    ]

    submit._append_initial_session_journal_markers(
        session_id=session_id,
        turn_id="turn-next",
        client_submission_id="client-queue-1",
        agent={"agentId": "agent-a"},
        conversation={"title": session_id},
        source="queued_turn",
        leases=["readonly_chat"],
        user_payload={
            "content": "send this next",
            "metadata": {"clientSubmissionId": "client-queue-1"},
        },
        turn_steer_promotion={"steerId": row["id"], "delivery": "queue"},
    )
    repeated = [
        event
        for event in load_conversation_events(tmp_path, session_id)
        if event.event_type == EVENT_TURN_STEER and event.payload.get("disposition") == "promoted"
    ]
    assert len(repeated) == 1

def test_guide_message_carries_delivery_metadata_and_model_preamble(tmp_path: Path, monkeypatch) -> None:
    from core.chat.conversation_ledger import EVENT_TURN_STARTED, append_conversation_event
    from core.web.services.session import turn_steer

    session_id = "session-guidance-delivery"
    turn_id = "turn-delivery"
    guidance = "carry the delivery marker"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    _seed_submittable_sessions(tmp_path, [session_id])
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        visible_in_model=False,
    )

    class _OpenTurnControl:
        turn_id = "turn-delivery"

        def snapshot(self) -> dict:
            return {
                "turnId": turn_id,
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: _OpenTurnControl())
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    submit.submit_session_guidance(session_id, guidance, mode="safe")

    events = load_conversation_events(tmp_path, session_id)
    user_copies = [
        event
        for event in events
        if event.event_type == EVENT_USER_MESSAGE and event.payload.get("content") == guidance
    ]
    assert len(user_copies) == 1
    assert user_copies[0].payload["metadata"]["turnSteerDelivery"] == "guide"

    drained = turn_steer.drain_guidance_events(session_id, turn_id, events, set())
    assert len(drained) == 1
    assert drained[0].startswith("[User steer during the running turn]")
    assert guidance in drained[0]


def test_settled_turn_falls_back_undrained_guide_to_queue(tmp_path: Path, monkeypatch) -> None:
    from core.chat.conversation_ledger import (
        EVENT_TURN_COMPLETED,
        EVENT_TURN_STARTED,
        append_conversation_event,
    )
    from core.web.services.session import turn_steer

    session_id = "session-guidance-fallback"
    turn_id = "turn-fallback"
    guidance = "do not lose this steer"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    _seed_submittable_sessions(tmp_path, [session_id])
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        visible_in_model=False,
    )

    class _OpenTurnControl:
        turn_id = "turn-fallback"

        def snapshot(self) -> dict:
            return {
                "turnId": turn_id,
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: _OpenTurnControl())
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    submit.submit_session_guidance(session_id, guidance, mode="safe")
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_COMPLETED,
        status="completed",
        visible_in_model=False,
    )

    moved = turn_steer.fallback_pending_guides_to_queue(
        session_id,
        turn_id,
        load_conversation_events(tmp_path, session_id),
    )
    assert moved == 1
    rows = session_service.list_session_queued_turns(session_id)
    assert [row.get("content") for row in rows] == [guidance]
    events = load_conversation_events(tmp_path, session_id)
    changed = [
        event
        for event in events
        if event.event_type == EVENT_TURN_STEER
        and event.payload.get("disposition") == "delivery_changed"
    ]
    assert len(changed) == 1
    assert changed[0].payload["delivery"] == "queue"
    assert changed[0].payload["fromDelivery"] == "guide"

def test_promoted_guide_reports_promoted_state(tmp_path: Path, monkeypatch) -> None:
    from core.chat.conversation_ledger import EVENT_TURN_STARTED, append_conversation_event
    from core.web.services.session import turn_steer

    session_id = "session-guidance-promoted"
    turn_id = "turn-promoted"
    guidance = "promote this guide"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    _seed_submittable_sessions(tmp_path, [session_id])
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        visible_in_model=False,
    )

    class _OpenTurnControl:
        turn_id = "turn-promoted"

        def snapshot(self) -> dict:
            return {
                "turnId": turn_id,
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda _session_id: _OpenTurnControl())
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    submit.submit_session_guidance(session_id, guidance, mode="safe")
    events = load_conversation_events(tmp_path, session_id)
    steer_id = next(event.payload["steerId"] for event in events if event.event_type == EVENT_TURN_STEER)
    turn_steer.record_promoted(
        session_id,
        steer_id=steer_id,
        turn_id=turn_id,
        delivery="queue",
    )
    events = load_conversation_events(tmp_path, session_id)
    metadata = turn_steer.guidance_metadata_from_events(events)
    guide_ids = [
        event.event_id
        for event in events
        if event.event_type == EVENT_USER_MESSAGE and event.payload.get("content") == guidance
    ]
    assert len(guide_ids) == 1
    row = metadata[guide_ids[0]]
    assert row["guidanceState"] == "promoted"
    assert row["guidanceDelivery"] == "queue"
