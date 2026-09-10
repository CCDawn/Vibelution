"""DeepSeek thinking-mode reasoning roundtrip on journal replay.

Contract under test (probed directly against the Command Code DeepSeek V4.1
Flash thinking endpoint): the upstream *returns* reasoning in
``reasoning``/``reasoning_details`` but *requires* every historical assistant
message carrying ``tool_calls`` to pass a non-empty ``reasoning_content`` back,
otherwise the next chat/completions call fails with 400 "The
`reasoning_content` in the thinking mode must be passed back to the API".

The journal stores thinking as ``assistant_item_committed`` events with
``payload.kind == "reasoning"`` (``visible_in_model=False``, double-written by
``session_ui_capture_llm_response`` and ``persist_session_turn_result``). The
replay must re-attach that reasoning to tool-call assistant messages without
touching fingerprints, invariants, or messages without tool calls.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.chat.conversation_invariant import (
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
    live_conversation_messages_from_events,
)
from core.chat.model_messages import normalize_model_messages
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_RESULT,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    model_messages_from_events,
    model_visible_messages_from_events,
)
from core.llm.message_projector import message_to_openai_dict
from core.orchestration.turn_message_assembly import (
    langchain_messages_from_conversation_layer,
    splice_current_turn_conversation,
)

REASONING_ROUND1 = "思考A：需要先检索资料再回答"
REASONING_ROUND2 = "思考B：汇总检索结果给出结论"

_FOUR_TOOL_CALLS = [
    {"id": f"call-{index}", "name": "web_search", "arguments": {"query": f"q{index}"}}
    for index in range(1, 5)
]


def _event(
    sequence: int,
    event_type: str,
    payload: dict,
    *,
    turn_id: str = "turn-reasoning",
    visible: bool = True,
    status: str = "completed",
    source: str = "test",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=1,
        event_id=f"event-{sequence:03d}",
        session_id="session-reasoning",
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status=status,
        timestamp="2026-09-10T19:55:00+00:00",
        source=source,
        payload=dict(payload),
        visible_in_model=visible,
    )


def _reasoning_pair(sequence: int, text: str, turn_id: str = "turn-reasoning") -> list[TurnJournalEvent]:
    """Double-written reasoning entries as journaled by the two persist paths."""

    return [
        _event(
            sequence,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            {"kind": "reasoning", "text": text},
            turn_id=turn_id,
            visible=False,
            source="session_ui_capture_llm_response",
        ),
        _event(
            sequence + 1,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            {"kind": "reasoning", "text": text},
            turn_id=turn_id,
            visible=False,
            source="persist_session_turn_result",
        ),
    ]


def _fault_time_turn_events(
    *,
    turn_id: str = "turn-reasoning",
    tool_calls: list[dict] | None = None,
    reasoning_text: str = REASONING_ROUND1,
    with_reasoning: bool = True,
) -> list[TurnJournalEvent]:
    """Journal shape at the failing second model call (no final answer yet)."""

    calls = tool_calls if tool_calls is not None else _FOUR_TOOL_CALLS
    events: list[TurnJournalEvent] = [
        _event(1, EVENT_USER_MESSAGE, {"content": "帮我查一下这四个问题"}, turn_id=turn_id)
    ]
    sequence = 2
    if with_reasoning and reasoning_text:
        events.extend(_reasoning_pair(sequence, reasoning_text, turn_id=turn_id))
        sequence += 2
    events.append(
        _event(sequence, EVENT_ASSISTANT_MESSAGE, {"content": "", "toolCalls": calls}, turn_id=turn_id)
    )
    sequence += 1
    for call in calls:
        events.append(
            _event(
                sequence,
                EVENT_TOOL_RESULT,
                {"toolCall": {"id": call["id"], "name": call["name"], "result": f"{call['name']} 结果"}},
                turn_id=turn_id,
            )
        )
        sequence += 1
    return events


def _tool_call_assistant(messages: list[dict]) -> dict | None:
    for message in messages:
        if message.get("role") == "assistant" and (message.get("tool_calls") or message.get("toolCalls")):
            return message
    return None


def test_reasoning_roundtrip_attaches_to_tool_call_assistant_on_replay():
    events = _fault_time_turn_events()

    model_messages = model_messages_from_events(events)
    assistant = _tool_call_assistant(model_messages)
    assert assistant is not None
    assert assistant.get("reasoning_content") == REASONING_ROUND1

    visible = model_visible_messages_from_events(events)
    visible_assistant = _tool_call_assistant(visible)
    assert visible_assistant is not None
    assert visible_assistant.get("reasoning_content") == REASONING_ROUND1


def test_reasoning_roundtrip_keeps_invariant_and_fingerprint_unchanged():
    events = _fault_time_turn_events()

    layer = live_conversation_messages_from_events(events, turn_id="turn-reasoning")
    invariant = check_conversation_payload_invariant(layer)
    assert invariant.ok, invariant.message

    def _strip(messages: list) -> list[dict]:
        stripped = []
        for message in messages:
            item = dict(message) if isinstance(message, dict) else message
            if isinstance(item, dict):
                item.pop("reasoning_content", None)
            stripped.append(item)
        return stripped

    assert conversation_layer_fingerprint(layer) == conversation_layer_fingerprint(_strip(layer))


def test_reasoning_not_attached_to_assistant_without_tool_calls():
    # Final-answer branch (assistant_item_committed) carries no tool_calls.
    events = _fault_time_turn_events()
    events.extend(_reasoning_pair(20, REASONING_ROUND2))
    events.append(
        _event(
            22,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            {
                "kind": "assistant_message",
                "channel": "answer",
                "phase": "final_answer",
                "text": "这是最终答案",
                "revision": 1,
            },
        )
    )

    for message in model_messages_from_events(events):
        if not (message.get("tool_calls") or message.get("toolCalls")):
            assert "reasoning_content" not in message, message

    # Plain-text assistant envelope (assistant_message without toolCalls).
    plain_events = [
        _event(1, EVENT_USER_MESSAGE, {"content": "你好"}),
        *_reasoning_pair(2, REASONING_ROUND1),
        _event(4, EVENT_ASSISTANT_MESSAGE, {"content": "直接回答，不用工具。"}),
    ]
    for message in model_messages_from_events(plain_events):
        assert "reasoning_content" not in message, message


def test_no_reasoning_fabricated_without_journal_entries():
    events = _fault_time_turn_events(with_reasoning=False)

    model_messages = model_messages_from_events(events)
    assistant = _tool_call_assistant(model_messages)
    assert assistant is not None
    assert "reasoning_content" not in assistant

    layer = live_conversation_messages_from_events(events, turn_id="turn-reasoning")
    for message in layer:
        assert "reasoning_content" not in message, message


def test_same_turn_reasoning_segments_attach_by_position():
    calls_round1 = [{"id": "call-r1", "name": "web_search", "arguments": {"query": "q"}}]
    calls_round2 = [{"id": "call-r2", "name": "web_search", "arguments": {"query": "q2"}}]
    events = [
        _event(1, EVENT_USER_MESSAGE, {"content": "连续查两次"}),
        *_reasoning_pair(2, REASONING_ROUND1),
        _event(4, EVENT_ASSISTANT_MESSAGE, {"content": "", "toolCalls": calls_round1}),
        _event(5, EVENT_TOOL_RESULT, {"toolCall": {"id": "call-r1", "name": "web_search", "result": "r1"}}),
        *_reasoning_pair(6, REASONING_ROUND2),
        _event(8, EVENT_ASSISTANT_MESSAGE, {"content": "", "toolCalls": calls_round2}),
        _event(9, EVENT_TOOL_RESULT, {"toolCall": {"id": "call-r2", "name": "web_search", "result": "r2"}}),
    ]

    model_messages = model_messages_from_events(events)
    assistants = [
        message
        for message in model_messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert [message.get("reasoning_content") for message in assistants] == [
        REASONING_ROUND1,
        REASONING_ROUND2,
    ]


def test_reasoning_does_not_leak_across_turns():
    # Turn A journals reasoning but produces no assistant message that could
    # consume it (interrupted before the envelope); turn B must not inherit it.
    events = [
        _event(1, EVENT_USER_MESSAGE, {"content": "第一轮"}, turn_id="turn-a"),
        *_reasoning_pair(2, REASONING_ROUND1, turn_id="turn-a"),
        _event(4, EVENT_USER_MESSAGE, {"content": "第二轮"}, turn_id="turn-b"),
        _event(5, EVENT_ASSISTANT_MESSAGE, {"content": "第二轮直接回答。"}, turn_id="turn-b"),
    ]

    for message in model_messages_from_events(events):
        assert "reasoning_content" not in message, message


def test_langchain_replay_restores_reasoning_into_additional_kwargs():
    events = _fault_time_turn_events()
    layer = live_conversation_messages_from_events(events, turn_id="turn-reasoning")

    restored = langchain_messages_from_conversation_layer(layer)
    assistant_messages = [message for message in restored if isinstance(message, AIMessage)]
    assert len(assistant_messages) == 1
    assistant = assistant_messages[0]
    assert assistant.tool_calls
    assert assistant.additional_kwargs.get("reasoning_content") == REASONING_ROUND1

    # Without journal reasoning the projection stays exactly as before.
    plain = langchain_messages_from_conversation_layer(
        live_conversation_messages_from_events(
            _fault_time_turn_events(with_reasoning=False),
            turn_id="turn-reasoning",
        )
    )
    for message in plain:
        if isinstance(message, AIMessage):
            assert "reasoning_content" not in (message.additional_kwargs or {})


def test_splice_replaces_in_memory_run_with_reasoning_bearing_replay():
    """The real failure path: intra-turn continuation splices the ledger layer."""

    events = _fault_time_turn_events()
    layer = live_conversation_messages_from_events(events, turn_id="turn-reasoning")

    in_memory = [
        SystemMessage(content="system"),
        HumanMessage(content="帮我查一下这四个问题"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": call["id"], "name": call["name"], "args": call["arguments"]}
                for call in _FOUR_TOOL_CALLS
            ],
        ),
        *[
            ToolMessage(content=f"{call['name']} 结果", tool_call_id=call["id"])
            for call in _FOUR_TOOL_CALLS
        ],
    ]

    spliced = splice_current_turn_conversation(in_memory, langchain_messages_from_conversation_layer(layer))
    assistants = [message for message in spliced if isinstance(message, AIMessage)]
    assert len(assistants) == 1
    assert assistants[0].additional_kwargs.get("reasoning_content") == REASONING_ROUND1
    assert sum(1 for message in spliced if isinstance(message, ToolMessage)) == 4


def test_fault_session_1955_turn_shape_roundtrip():
    """Synthetic replay of session-20260910-184759-935222's 19:55 turn shape."""

    events = _fault_time_turn_events()
    assert len(_FOUR_TOOL_CALLS) == 4

    layer = live_conversation_messages_from_events(events, turn_id="turn-reasoning")
    assistant = _tool_call_assistant([m for m in layer if isinstance(m, dict)])
    assert assistant is not None
    assert assistant.get("reasoning_content") == REASONING_ROUND1
    assert len(assistant.get("tool_calls") or []) == 4
    tool_messages = [message for message in layer if message.get("role") == "tool"]
    assert len(tool_messages) == 4
    assert check_conversation_payload_invariant(layer).ok


def test_model_messages_provider_chain_copies_top_level_reasoning_content():
    """Verification-only guard: the downstream chain passes reasoning through."""

    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call-1", "name": "web_search", "args": {"query": "q"}},
        ],
        "reasoning_content": REASONING_ROUND1,
        "metadata": {"turnId": "turn-reasoning"},
    }
    tool_result = {
        "role": "tool",
        "content": "web_search 结果",
        "tool_call_id": "call-1",
        "metadata": {"turnId": "turn-reasoning"},
    }
    normalized = normalize_model_messages([message, tool_result])
    assistant = _tool_call_assistant(normalized)
    assert assistant is not None
    assert assistant.get("reasoning_content") == REASONING_ROUND1

    # LangChain shape: projector restores additional_kwargs reasoning into the
    # provider payload (DeepSeek adapter sets preserves_reasoning_content=True).
    ai_message = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "web_search", "args": {"query": "q"}}],
        additional_kwargs={"reasoning_content": REASONING_ROUND1},
    )
    payload = message_to_openai_dict(ai_message, preserve_reasoning_content=True)
    assert payload.get("reasoning_content") == REASONING_ROUND1
    assert payload.get("tool_calls")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
