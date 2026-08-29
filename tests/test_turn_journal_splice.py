"""Regression tests: turn journal replay must not splice duplicated tool chains.

Persist writes the turn's full tool list into the journaled assistant message
payload (``persist_session_turn_result``), while stream capture already
journaled ``tool_call_started`` / ``tool_result`` lifecycle events for the same
calls. The model replay must merge those two representations instead of
emitting the same tool call twice (second copy renamed ``-dedup-N``), which
polluted provider history with phantom duplicate tool chains.
"""

from __future__ import annotations

import pytest

from core.chat.conversation_ledger import (
    append_conversation_event,
    conversation_model_messages_from_events,
    load_conversation_events,
)
from core.chat.context_assembler import assemble_conversation_context
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    model_visible_messages_from_events,
)


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    return data_home


def _event(
    sequence: int,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict | None = None,
    tool_call_id: str = "",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=2,
        event_id=f"event-{sequence:03d}",
        session_id="session-splice",
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status=status,
        timestamp="2026-08-28T00:00:00+00:00",
        source="test",
        payload=dict(payload or {}),
        tool_call_id=tool_call_id,
        correlation_id=tool_call_id,
    )


def _tool_started(sequence: int, turn_id: str, call_id: str, name: str = "search_tool") -> TurnJournalEvent:
    return _event(
        sequence,
        turn_id,
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"id": call_id, "name": name, "arguments": {"query": "X"}}},
        tool_call_id=call_id,
    )


def _tool_result(
    sequence: int,
    turn_id: str,
    call_id: str,
    result: str,
    name: str = "search_tool",
) -> TurnJournalEvent:
    return _event(
        sequence,
        turn_id,
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": call_id, "name": name, "arguments": {"query": "X"}, "result": result}},
        tool_call_id=call_id,
    )


def _assistant_with_embedded_tools(
    sequence: int,
    turn_id: str,
    content: str,
    call_id: str,
    result: str,
    name: str = "search_tool",
    *,
    status: str = "completed",
) -> TurnJournalEvent:
    return _event(
        sequence,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status=status,
        payload={
            "content": content,
            "toolCalls": [
                {"id": call_id, "name": name, "status": "done", "result": result},
            ],
        },
    )


def _chain_tool_call_ids(messages: list[dict]) -> list[str]:
    return [
        str(call.get("id") or "")
        for message in messages
        if isinstance(message, dict)
        for call in (
            message.get("tool_calls")
            or message.get("toolCalls")
            or []
        )
        if isinstance(call, dict)
    ]


def test_replay_dedupes_embedded_tool_call_already_projected_from_lifecycle_events():
    events = [
        _event(1, "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "检索X"}),
        _tool_started(2, "turn-1", "call-1"),
        _tool_result(3, "turn-1", "call-1", "X 的检索结果"),
        _assistant_with_embedded_tools(4, "turn-1", "已完成检索", "call-1", "X 的检索结果"),
        _event(5, "turn-1", EVENT_TURN_COMPLETED, status="completed", payload={}),
    ]

    messages = conversation_model_messages_from_events(events)

    assert _chain_tool_call_ids(messages) == ["call-1"]
    result_bodies = [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call-1"
    ]
    assert result_bodies == ["X 的检索结果"]
    # The assistant text survives without carrying a duplicate toolCalls bundle.
    final_texts = [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "assistant" and "已完成检索" in str(message.get("content") or "")
    ]
    assert final_texts == ["已完成检索"]


def test_replay_dedupes_embedded_tool_call_on_failed_partial_message():
    events = [
        _event(1, "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "检索X"}),
        _tool_started(2, "turn-1", "call-1"),
        _tool_result(3, "turn-1", "call-1", "X 的检索结果"),
        _assistant_with_embedded_tools(
            4,
            "turn-1",
            "已拿到检索结果，正在整理",
            "call-1",
            "X 的检索结果",
            status="failed_provider",
        ),
    ]

    messages = conversation_model_messages_from_events(events)

    assert _chain_tool_call_ids(messages) == ["call-1"]
    assert any(
        message.get("role") == "assistant" and "正在整理" in str(message.get("content") or "")
        for message in messages
    )


def test_visible_projection_keeps_embedded_tool_bundle_for_ui():
    """The dedupe is model-projection scoped: the UI visible projection keeps
    the persisted assistant bundle so transcript cells stay unchanged."""

    events = [
        _event(1, "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "检索X"}),
        _tool_result(2, "turn-1", "call-1", "X 的检索结果"),
        _assistant_with_embedded_tools(3, "turn-1", "已完成检索", "call-1", "X 的检索结果"),
    ]

    messages = model_visible_messages_from_events(events)

    embedded_bundles = [
        message
        for message in messages
        if isinstance(message, dict)
        and str((message.get("metadata") or {}).get("kind") or "") == "journal_assistant_message"
        and any(
            str(call.get("id") or "") == "call-1"
            for call in (message.get("toolCalls") or [])
            if isinstance(call, dict)
        )
    ]
    assert len(embedded_bundles) == 1


def test_replay_keeps_embedded_tool_call_without_lifecycle_events():
    events = [
        _event(1, "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "检索X"}),
        _assistant_with_embedded_tools(2, "turn-1", "已完成检索", "call-legacy", "X 的检索结果"),
    ]

    messages = conversation_model_messages_from_events(events)

    # The embedded bundle is the only record of this call: it must survive.
    assert _chain_tool_call_ids(messages) == ["call-legacy"]


def test_context_pipeline_seed_replays_single_tool_chain_for_persisted_turn(tmp_path):
    """End to end: the assembled history seed carries the tool chain once."""

    session_id = "session-splice-pipeline"
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "检索X"},
        source="test",
    )
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"id": "call-1", "name": "search_tool", "arguments": {"query": "X"}}},
        tool_call_id="call-1",
        source="test",
    )
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "call-1", "name": "search_tool", "arguments": {"query": "X"}, "result": "X 的检索结果"}},
        tool_call_id="call-1",
        source="test",
    )
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "已完成检索",
            "toolCalls": [{"id": "call-1", "name": "search_tool", "status": "done", "result": "X 的检索结果"}],
        },
        source="test",
    )

    assembled = assemble_conversation_context(
        [],
        session_id=session_id,
        current_turn_id="turn-current",
        ledger_events=load_conversation_events(tmp_path, session_id),
        recent_message_limit=12,
    )

    assert _chain_tool_call_ids(assembled.history_messages) == ["call-1"]
    tool_messages = [
        str(message.get("content") or "")
        for message in assembled.history_messages
        if message.get("role") == "tool"
    ]
    assert tool_messages == ["X 的检索结果"]
