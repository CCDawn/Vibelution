"""Guidance drain receipts locate display boundaries without changing replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.chat.conversation_ledger import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_TURN_STEER,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.chat.turn_journal import model_visible_messages_from_events
from core.chat.turn_journal import EVENT_BRANCH_REBASE
from core.web.services import session_service
from core.web.services.session import projection, turn_steer


def _guide(root: Path, *, turn_id: str = "turn-a", steer_id: str = "steer-a", content: str = "same guidance"):
    return append_conversation_event(
        root,
        "session-a",
        turn_id,
        EVENT_USER_MESSAGE,
        payload={
            "content": content,
            "metadata": {"kind": "user_guidance", "steerId": steer_id},
        },
    )


def _start(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root)
    append_conversation_event(root, "session-a", "turn-a", EVENT_TURN_STARTED)


def _drain(root: Path, consumed: set[str] | None = None) -> list[str]:
    return turn_steer.drain_guidance_events(
        "session-a",
        "turn-a",
        load_conversation_events(root, "session-a"),
        consumed if consumed is not None else set(),
    )


def test_drain_receipts_follow_intervening_work_and_keep_identical_submissions(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    first = _guide(tmp_path)
    work = append_conversation_event(
        tmp_path,
        "session-a",
        "turn-a",
        "assistant_item_committed",
        payload={"itemId": "tool-a", "kind": "tool_call", "callId": "call-a"},
        visible_in_model=False,
    )
    second = _guide(tmp_path, steer_id="steer-b")
    consumed: set[str] = set()
    visible_before = model_visible_messages_from_events(load_conversation_events(tmp_path, "session-a"))

    assert _drain(tmp_path, consumed) == ["same guidance", "same guidance"]
    assert _drain(tmp_path, consumed) == []

    events = load_conversation_events(tmp_path, "session-a")
    receipts = [event for event in events if event.event_type == EVENT_TURN_STEER]
    assert len(receipts) == 2
    assert [event.payload["userMessageEventId"] for event in receipts] == [first.event_id, second.event_id]
    assert all(event.sequence > work.sequence for event in receipts)
    assert all(event.payload["disposition"] == "drained" for event in receipts)
    assert all(event.visible_in_model is False and "content" not in event.payload for event in receipts)
    assert model_visible_messages_from_events(events) == visible_before


def test_new_worker_can_reinject_without_moving_the_first_drain_boundary(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    guide = _guide(tmp_path)
    assert _drain(tmp_path) == ["same guidance"]
    before = load_conversation_events(tmp_path, "session-a")
    first = turn_steer.guidance_metadata_from_events(before)[guide.event_id]

    assert _drain(tmp_path) == ["same guidance"]
    after = load_conversation_events(tmp_path, "session-a")
    assert len(after) == len(before)
    assert turn_steer.guidance_metadata_from_events(after)[guide.event_id] == first


def test_receipt_failure_does_not_drop_guidance_or_repeat_it_in_the_same_worker(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    _guide(tmp_path)
    def fail(*_args, **_kwargs):
        raise OSError("receipt unavailable")
    monkeypatch.setattr(turn_steer, "append_turn_steer_event", fail)
    consumed: set[str] = set()

    assert _drain(tmp_path, consumed) == ["same guidance"]
    assert _drain(tmp_path, consumed) == []


def test_detail_projects_each_exact_guide_once_and_terminal_without_receipt_is_unconfirmed(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    ordinary = append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_USER_MESSAGE, payload={"content": "ordinary"},
    )
    first = _guide(tmp_path)
    assert _drain(tmp_path) == ["same guidance"]
    second = _guide(tmp_path, steer_id="steer-b", content="late guidance")
    append_conversation_event(tmp_path, "session-a", "turn-a", EVENT_TURN_COMPLETED)
    events = load_conversation_events(tmp_path, "session-a")
    loads: list[str] = []
    monkeypatch.setattr(
        session_service, "_load_session_conversation_events_cached",
        lambda session_id: loads.append(session_id) or events,
    )
    raw = model_visible_messages_from_events(events)
    result = projection._normalize_messages("session-a", raw, include_timeline=False, transcript_scope="none")
    by_id = {item["metadata"]["eventId"]: item for item in result}

    assert by_id[first.event_id]["metadata"]["guidanceState"] == "drained"
    assert by_id[first.event_id]["metadata"]["guidanceSequence"] == first.sequence
    assert by_id[first.event_id]["metadata"]["guidanceConsumedSequence"] > first.sequence
    assert by_id[second.event_id]["metadata"]["guidanceState"] == "unconfirmed"
    assert by_id[second.event_id]["metadata"]["guidanceEventId"] == second.event_id
    assert "guidanceConsumedSequence" not in by_id[second.event_id]["metadata"]
    assert by_id[ordinary.event_id]["metadata"] == raw[0]["metadata"]
    assert loads == ["session-a"]
    assert projection._normalize_messages("session-a", raw, include_timeline=False, transcript_scope="none") == result


def test_pending_and_invalid_receipts_do_not_invent_a_consumption_boundary(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    guide = _guide(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-a",
        "other-turn",
        EVENT_TURN_STEER,
        payload={
            "schema": "turn_steer.v1", "steerId": "steer-a", "delivery": "guide",
            "disposition": "drained", "targetTurnId": "turn-a",
            "userMessageEventId": guide.event_id, "userMessageSequence": guide.sequence,
        },
        visible_in_model=False,
    )
    metadata = turn_steer.guidance_metadata_from_events(load_conversation_events(tmp_path, "session-a"))
    assert metadata[guide.event_id] == {
        "guidanceEventId": guide.event_id, "guidanceSequence": guide.sequence, "guidanceState": "pending",
    }


def test_ordinary_message_projection_does_not_load_guidance_events(monkeypatch):
    def unexpected_load(*_args, **_kwargs):
        raise AssertionError("ordinary messages do not need guidance enrichment")
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", unexpected_load)
    raw = [{"role": "user", "content": "ordinary", "metadata": {"kind": "journal_user_message", "turnId": "turn-a"}}]
    result = projection._normalize_messages("session-a", raw, include_timeline=False, transcript_scope="none")
    assert result[0]["metadata"] == raw[0]["metadata"]


@pytest.mark.parametrize("invalid", [
    {"targetTurnId": "another-turn"},
    {"userMessageSequence": 9999},
    {"userMessageEventId": "unknown-guide"},
])
def test_first_valid_receipt_is_the_boundary_even_when_events_are_reordered(tmp_path, monkeypatch, invalid):
    _start(tmp_path, monkeypatch)
    guide = _guide(tmp_path)
    payload = {
        "schema": "turn_steer.v1", "steerId": "steer-a", "delivery": "guide", "disposition": "drained",
        "targetTurnId": "turn-a", "userMessageEventId": guide.event_id, "userMessageSequence": guide.sequence,
    }
    append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_TURN_STEER, payload={**payload, **invalid}, visible_in_model=False,
    )
    first = append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_TURN_STEER, payload=payload, visible_in_model=False,
    )
    append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_TURN_STEER, payload=payload, visible_in_model=False,
    )
    metadata = turn_steer.guidance_metadata_from_events(reversed(load_conversation_events(tmp_path, "session-a")))
    assert metadata[guide.event_id]["guidanceConsumedSequence"] == first.sequence


def test_live_synthetic_item_is_identifiable_when_its_local_sequence_precedes_the_drain(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    _guide(tmp_path)
    tool = append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "tool-a", "kind": "tool_call", "callId": "call-a"}, visible_in_model=False,
    )
    assert _drain(tmp_path) == ["same guidance"]
    events = load_conversation_events(tmp_path, "session-a")
    boundary = next(event.sequence for event in events if event.event_type == EVENT_TURN_STEER)
    loads: list[str] = []
    monkeypatch.setattr(
        session_service, "_load_session_conversation_events_cached",
        lambda session_id: loads.append(session_id) or events,
    )

    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", content="live response", done=False,
    )
    by_id = {item["itemId"]: item for item in items}
    assert by_id["tool-a"]["sequence"] == tool.sequence
    assert by_id["tool-a"]["metadata"]["orderSequence"] == tool.sequence
    answer = next(item for item in items if item["type"] == "agent_message")
    assert answer["sequence"] <= boundary
    assert "orderSequence" not in (answer.get("metadata") or {})
    assert loads == ["session-a"]


def test_nonjournal_fallback_items_do_not_invent_a_creation_position():
    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="", message_id="message-a", content="legacy answer", done=True,
    )
    assert "orderSequence" not in (items[0].get("metadata") or {})


def test_detail_source_restores_repeated_guides_but_preserves_ordinary_user_dedup(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    original = append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_USER_MESSAGE, payload={"content": "ordinary"},
    )
    first = _guide(tmp_path)
    append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_USER_MESSAGE, payload={"content": "ordinary"},
    )
    second = _guide(tmp_path, steer_id="steer-b")
    events = load_conversation_events(tmp_path, "session-a")
    replay_before = model_visible_messages_from_events(events)

    displayed = projection._ledger_visible_messages_for_session("session-a")
    assert [message["metadata"]["eventId"] for message in displayed] == [
        original.event_id, first.event_id, second.event_id,
    ]
    assert model_visible_messages_from_events(events) == replay_before
    assert len(replay_before) == 2
    assert projection._ledger_visible_messages_for_session("session-a") == displayed


def test_pagination_counts_and_windows_include_repeated_guidance_submissions(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_USER_MESSAGE, payload={"content": "ordinary"},
    )
    first = _guide(tmp_path)
    second = _guide(tmp_path, steer_id="steer-b")
    monkeypatch.setattr(session_service, "_build_live_output_message", lambda *_args: None)

    messages, window, stats = projection._session_detail_messages_with_window(
        "session-a", message_limit=2, transcript_scope="none",
    )
    assert window["totalMessages"] == 3
    assert window["returnedMessages"] == 2
    assert [message["metadata"]["eventId"] for message in messages] == [first.event_id, second.event_id]
    assert len(stats) == 3
    earlier, previous_window, _stats = projection._session_detail_messages_with_window(
        "session-a", message_limit=1, before_message_index=3, transcript_scope="none",
    )
    assert earlier[0]["metadata"]["eventId"] == first.event_id
    assert previous_window["newestMessageIndex"] == 2


def test_display_recovery_does_not_revive_guidance_from_an_inactive_branch(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    anchor = append_conversation_event(
        tmp_path, "session-a", "turn-a", EVENT_USER_MESSAGE, payload={"content": "original"},
    )
    abandoned = [_guide(tmp_path), _guide(tmp_path, steer_id="steer-old")]
    append_conversation_event(tmp_path, "session-a", "turn-a", EVENT_TURN_COMPLETED)
    append_conversation_event(
        tmp_path, "session-a", "turn-b", EVENT_BRANCH_REBASE,
        payload={"operation": "edit", "fromEventId": anchor.event_id, "branchId": "branch-new"},
        visible_in_model=False,
    )
    append_conversation_event(tmp_path, "session-a", "turn-b", EVENT_TURN_STARTED)
    new_guides = [
        _guide(tmp_path, turn_id="turn-b", steer_id="steer-new-1"),
        _guide(tmp_path, turn_id="turn-b", steer_id="steer-new-2"),
    ]

    displayed = projection._ledger_visible_messages_for_session("session-a")
    ids = [message["metadata"]["eventId"] for message in displayed]
    assert ids == [anchor.event_id, *(event.event_id for event in new_guides)]
    assert not set(ids).intersection(event.event_id for event in abandoned)


def test_burst_of_nine_identical_guides_drains_every_submission_in_journal_order(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    _guide(tmp_path, turn_id="other-turn", steer_id="other-steer", content="unrelated guidance")
    guides = [_guide(tmp_path, steer_id=f"steer-{index}") for index in range(9)]
    consumed: set[str] = set()

    assert _drain(tmp_path, consumed) == ["same guidance"] * 9
    assert _drain(tmp_path, consumed) == []
    receipts = [
        event for event in load_conversation_events(tmp_path, "session-a")
        if event.event_type == EVENT_TURN_STEER
    ]
    assert [event.payload["userMessageEventId"] for event in receipts] == [event.event_id for event in guides]
    _guide(tmp_path, steer_id="steer-later", content="later guidance")
    assert _drain(tmp_path, consumed) == ["later guidance"]


def test_display_only_guide_restoration_does_not_change_the_next_turn_model_seed(tmp_path, monkeypatch):
    from core.chat.context_assembler import assemble_conversation_context

    _start(tmp_path, monkeypatch)
    _guide(tmp_path)
    _guide(tmp_path, steer_id="steer-b")
    append_conversation_event(tmp_path, "session-a", "turn-a", EVENT_TURN_COMPLETED)
    events = load_conversation_events(tmp_path, "session-a")
    model_source = model_visible_messages_from_events(events)
    display_source = projection._ledger_visible_messages_for_session("session-a")
    assert len(display_source) == len(model_source) + 1
    kwargs = {"session_id": "session-a", "current_turn_id": "next-turn", "ledger_events": events, "recent_message_limit": None}
    assert assemble_conversation_context(display_source, **kwargs).history_messages == assemble_conversation_context(
        model_source, **kwargs,
    ).history_messages


def test_later_canonical_revision_does_not_move_work_across_a_guidance_boundary(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    initial = append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "reasoning-a", "kind": "reasoning", "text": "first", "revision": 0},
        visible_in_model=False,
    )
    _guide(tmp_path)
    _drain(tmp_path)
    later = append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "reasoning-a", "kind": "reasoning", "text": "first extended", "revision": 1},
        visible_in_model=False,
    )
    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", done=True,
    )
    assert max(item["sequence"] for item in items) == later.sequence
    assert {item["metadata"]["orderSequence"] for item in items} == {initial.sequence}


def test_native_stream_creation_order_survives_multiple_guides_and_canonical_commit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.web.services.session import stream_capture

    _start(tmp_path, monkeypatch)
    capture = stream_capture.SessionTurnCapture(session_id="session-a", turn_id="turn-a")
    def event(item_id: str, text: str = "chunk"):
        return SimpleNamespace(
            session_id="session-a", turn_id="turn-a", item_id=item_id,
            kind="answer_delta", text=text, channel="answer", call_id="",
        )
    capture.note_protocol_item(event("native-first"))
    capture.content = "first response"
    first = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", content=capture.content,
    )[0]
    first_order = first["metadata"]["orderSequence"]
    assert first["itemId"] == "native-first"
    _guide(tmp_path)
    pending = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", content=capture.content,
    )[0]
    assert pending["metadata"]["orderSequence"] == first_order
    _drain(tmp_path)
    capture.note_protocol_item(event("native-first", "extension"))
    anchors = [event for event in load_conversation_events(tmp_path, "session-a")
               if event.payload.get("disposition") == "display_item_started"]
    assert len(anchors) == 1
    append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "native-first", "kind": "commentary", "text": "first response", "revision": 1},
        visible_in_model=False,
    )
    capture.note_protocol_item(event("native-second"))
    capture.content += "second response"
    live = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", content=capture.content,
    )
    second = next(item for item in live if item["itemId"] == "native-second")
    assert second["text"] == "second response"
    second_order = second["metadata"]["orderSequence"]
    assert second_order > first_order
    _guide(tmp_path, steer_id="steer-second", content="second guidance")
    _drain(tmp_path)
    append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "native-second", "kind": "assistant_message", "phase": "final_answer",
                 "text": "second response", "terminal": True}, visible_in_model=False,
    )
    append_conversation_event(tmp_path, "session-a", "turn-a", EVENT_TURN_COMPLETED)
    refreshed = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", done=True,
    )
    assert {item["itemId"]: item["metadata"]["orderSequence"] for item in refreshed} == {
        "native-first": first_order, "native-second": second_order,
    }


def test_native_reasoning_anchor_reuses_live_identity_after_later_canonical_commit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.web.services.session import stream_capture

    _start(tmp_path, monkeypatch)
    capture = stream_capture.SessionTurnCapture(session_id="session-a", turn_id="turn-a")
    event = SimpleNamespace(session_id="session-a", turn_id="turn-a", item_id="native-thought",
                            kind="reasoning_delta", text="thinking", call_id="")
    capture.note_protocol_item(event)
    capture.note_thought("thinking")
    transcript = session_service._build_codex_transcript_projection(
        message_id="message-a", feedback_events=capture.feedback_events, streaming=True,
    )
    def projected():
        return projection._build_session_turn_items_projection(
            session_id="session-a", turn_id="turn-a", message_id="message-a", thought=capture.thought,
            codex_transcript=transcript,
        )
    live = projected()
    assert [item["itemId"] for item in live] == ["native-thought"]
    order = live[0]["metadata"]["orderSequence"]
    _guide(tmp_path)
    _drain(tmp_path)
    append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "native-thought", "kind": "reasoning", "text": "thinking", "revision": 1},
        visible_in_model=False,
    )
    refreshed = projected()
    assert [item["itemId"] for item in refreshed] == ["native-thought"]
    assert refreshed[0]["metadata"]["orderSequence"] == order


@pytest.mark.parametrize("observer_fails", [False, True])
def test_real_adapter_notifies_capture_before_text_and_observer_failure_keeps_streaming(tmp_path, monkeypatch, observer_fails):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from core.llm.types import CanonicalItemIdentity, LLMProtocolEvent, TurnOutcome
    from core.orchestration.turn_llm_adapter import invoke_agent_llm_turn
    from core.web.services.session import stream_capture
    from tests.test_turn_llm_adapter import _adapter_hooks, _route_llm, _DummyContext

    _start(tmp_path, monkeypatch)
    streamed: list[str] = []
    def fail(_event):
        raise OSError("observer unavailable")
    ui = SimpleNamespace(
        thinking=lambda *_args: _DummyContext(), add_log=lambda *_args, **_kwargs: None,
        stream_thought=lambda *_args, **_kwargs: None, clear_thought_stream=lambda: None,
        stream_response=lambda text, **_kwargs: streamed.append(text), clear_response_stream=lambda: None,
        set_pet_mental_state=lambda **_kwargs: None,
    )
    if observer_fails:
        ui.note_protocol_item = fail
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)
    capture = stream_capture.SessionTurnCapture(session_id="session-a", turn_id="turn-a")
    identity = CanonicalItemIdentity("session-a", "turn-a", "invocation-a", 0, "native-answer")
    def run_stream(_client, _messages, *, on_event=None, **_kwargs):
        on_event(LLMProtocolEvent(
            kind="answer_delta", sequence=1, session_id="session-a", turn_id="turn-a",
            invocation_id="invocation-a", iteration=0, item_id="native-answer", text="answer",
        ))
        return TurnOutcome.final_answer(identity=identity, text="answer")
    llm = _route_llm("primary")
    llm.stream = True
    with stream_capture._capture_session_ui_stream("session-a", capture):
        result = invoke_agent_llm_turn(
            messages=[AIMessage(content="hello")],
            hooks=_adapter_hooks(get_ui=lambda: ui, get_llm_for_mode=lambda **_kwargs: llm,
                                 should_stream=lambda *_args: True, run_streaming_outcome=run_stream),
        )
    assert result.payload is not None
    assert streamed == ["answer"]
    anchors = [event for event in load_conversation_events(tmp_path, "session-a")
               if event.payload.get("disposition") == "display_item_started"]
    assert len(anchors) == (0 if observer_fails else 1)
    if anchors:
        assert anchors[0].payload["itemId"] == "native-answer"
        assert "text" not in anchors[0].payload and "content" not in anchors[0].payload


def test_tool_first_start_is_its_order_when_the_canonical_item_is_committed_later(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    started = append_conversation_event(
        tmp_path, "session-a", "turn-a", "tool_call_started",
        payload={"toolCall": {"callId": "call-a", "name": "tool-a"}}, visible_in_model=False,
    )
    _guide(tmp_path)
    _drain(tmp_path)
    append_conversation_event(
        tmp_path, "session-a", "turn-a", "assistant_item_committed",
        payload={"itemId": "tool-native", "kind": "tool_call", "callId": "call-a"}, visible_in_model=False,
    )
    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", done=True,
    )
    assert items[0]["metadata"]["orderSequence"] == started.sequence


@pytest.mark.parametrize("clear_between_requests", [False, True])
def test_real_response_done_and_clear_do_not_truncate_a_later_native_item(tmp_path, monkeypatch, clear_between_requests):
    from types import SimpleNamespace
    from core.web.services.session import stream_capture

    _start(tmp_path, monkeypatch)
    ui = SimpleNamespace(
        stream_thought=lambda *_args, **_kwargs: None, clear_thought_stream=lambda: None,
        stream_response=lambda *_args, **_kwargs: None, clear_response_stream=lambda: None,
        set_pet_mental_state=lambda **_kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)
    capture = stream_capture.SessionTurnCapture(session_id="session-a", turn_id="turn-a")
    def protocol(item_id: str):
        return SimpleNamespace(session_id="session-a", turn_id="turn-a", item_id=item_id,
                               kind="answer_delta", text="chunk", call_id="")
    with stream_capture._capture_session_ui_stream("session-a", capture):
        ui.note_protocol_item(protocol("native-one"))
        ui.stream_response("first")
        ui.stream_response("first", done=True)
        append_conversation_event(
            tmp_path, "session-a", "turn-a", "assistant_item_committed",
            payload={"itemId": "native-one", "kind": "commentary", "text": "first"}, visible_in_model=False,
        )
        if clear_between_requests:
            ui.clear_response_stream()
        _guide(tmp_path)
        _drain(tmp_path)
        ui.note_protocol_item(protocol("native-two"))
        ui.stream_response("second")
        before_done = projection._build_session_turn_items_projection(
            session_id="session-a", turn_id="turn-a", message_id="message-a",
            content=capture.content, source="assistant_delta", done=False,
        )
        before_order = next(item["metadata"]["orderSequence"] for item in before_done if item["itemId"] == "native-two")
        ui.stream_response("second authoritative response", done=True)
        live = projection._build_session_turn_items_projection(
            session_id="session-a", turn_id="turn-a", message_id="message-a",
            content=capture.content, source="session_live_overlay", done=False,
        )
        second = next(item for item in live if item["itemId"] == "native-two")
        assert second["text"] == "second authoritative response"
        assert second["metadata"]["orderSequence"] == before_order
        assert projection._build_session_turn_items_projection(
            session_id="session-a", turn_id="turn-a", message_id="message-a",
            content=capture.content, source="session_live_overlay", done=False,
        ) == live


def test_session_detail_never_applies_a_cumulative_live_content_offset(tmp_path, monkeypatch):
    _start(tmp_path, monkeypatch)
    turn_steer.record_display_item_started(
        "session-a", "turn-a", item_id="native-answer", kind="agent_message", content_offset=5,
    )
    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a",
        content="authoritative standalone response", source="session_detail", done=False,
    )
    assert items[0]["text"] == "authoritative standalone response"


@pytest.mark.parametrize("clear_method", ["reset_stream_restart_boundary", "clear_content"])
def test_same_native_item_retry_rebases_cleared_content_without_moving_creation_order(tmp_path, monkeypatch, clear_method):
    from types import SimpleNamespace
    from core.web.services.session import stream_capture

    _start(tmp_path, monkeypatch)
    capture = stream_capture.SessionTurnCapture(session_id="session-a", turn_id="turn-a", content="older prefix")
    event = SimpleNamespace(session_id="session-a", turn_id="turn-a", item_id="same-native-retry",
                            kind="answer_delta", text="chunk", call_id="")
    capture.note_protocol_item(event)
    capture.content += "failed partial"
    initial_order = turn_steer.display_item_order_provenance(
        load_conversation_events(tmp_path, "session-a"), "turn-a",
    )["same-native-retry"]["orderSequence"]
    getattr(capture, clear_method)()
    capture.note_protocol_item(event)
    capture.note_content("recovered authoritative response")

    items = projection._build_session_turn_items_projection(
        session_id="session-a", turn_id="turn-a", message_id="message-a", content=capture.content,
        source="session_live_overlay", done=False,
    )
    assert items[0]["text"] == "recovered authoritative response"
    assert items[0]["metadata"]["orderSequence"] == initial_order
    events = load_conversation_events(tmp_path, "session-a")
    assert sum(event.payload.get("disposition") == "display_item_started" for event in events) == 1
    assert sum(event.payload.get("disposition") == "display_content_rebased" for event in events) == 1
