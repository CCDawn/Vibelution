"""Unit tests for turn message serialization carryover helpers.

Covers core.orchestration.turn_carryover — extracted from agent.py during
orchestration split (R03). Pure roundtrip and edge-case guards prevent
silent data loss across turn boundaries.
"""

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from core.orchestration.turn_carryover import (
    deserialize_turn_messages,
    serialize_turn_message,
    serialize_turn_messages,
)


def test_serialize_ai_message_preserves_tool_calls_and_metadata():
    message = AIMessage(
        content="done",
        tool_calls=[{"id": "call-1", "name": "read_file_tool", "args": {"path": "a.py"}}],
        additional_kwargs={"refusal": None},
        response_metadata={"model": "test-model", "token_usage": {"total_tokens": 42}},
    )

    payload = serialize_turn_message(message)

    assert payload["kind"] == "ai"
    assert payload["content"] == "done"
    assert payload["tool_calls"][0]["id"] == "call-1"
    assert payload["tool_calls"][0]["name"] == "read_file_tool"
    assert payload["tool_calls"][0]["args"] == {"path": "a.py"}
    assert payload["additional_kwargs"] == {"refusal": None}
    assert payload["response_metadata"] == {
        "model": "test-model",
        "token_usage": {"total_tokens": 42},
    }


def test_serialize_ai_message_omits_empty_metadata_keys():
    message = AIMessage(content="plain")

    payload = serialize_turn_message(message)

    assert payload == {"kind": "ai", "content": "plain", "tool_calls": []}
    assert "additional_kwargs" not in payload
    assert "response_metadata" not in payload


def test_serialize_tool_and_system_messages():
    tool = ToolMessage(content='{"ok": true}', tool_call_id="call-9")
    system = SystemMessage(content="system prefix")

    assert serialize_turn_message(tool) == {
        "kind": "tool",
        "content": '{"ok": true}',
        "tool_call_id": "call-9",
    }
    assert serialize_turn_message(system) == {"kind": "system", "content": "system prefix"}


def test_serialize_dict_and_fallback_content_shapes():
    raw_dict = {"role": "user", "content": "hello"}
    assert serialize_turn_message(raw_dict) == {
        "kind": "dict",
        "role": "user",
        "content": "hello",
    }

    class ContentOnly:
        content = "fallback system text"

    assert serialize_turn_message(ContentOnly()) == {
        "kind": "system",
        "content": "fallback system text",
    }


def test_serialize_unknown_empty_object_returns_empty_dict():
    class Empty:
        pass

    assert serialize_turn_message(Empty()) == {}


def test_serialize_turn_messages_skips_empty_entries():
    class _Empty:
        pass

    messages = [AIMessage(content="keep"), _Empty()]
    serialized = serialize_turn_messages(messages)

    assert len(serialized) == 1
    assert serialized[0]["kind"] == "ai"


def test_deserialize_roundtrip_restores_langchain_messages():
    original = [
        AIMessage(
            content="assistant",
            tool_calls=[{"id": "c1", "name": "cli_tool", "args": {"command": "pytest"}}],
            additional_kwargs={"cache_control": {"type": "ephemeral"}},
            response_metadata={"finish_reason": "stop"},
        ),
        ToolMessage(content="tool output", tool_call_id="c1"),
        SystemMessage(content="system"),
        {"role": "user", "content": "dict payload"},
    ]

    restored = deserialize_turn_messages(serialize_turn_messages(original))

    assert len(restored) == 4
    ai = restored[0]
    assert isinstance(ai, AIMessage)
    assert ai.content == "assistant"
    assert ai.tool_calls[0]["id"] == "c1"
    assert ai.tool_calls[0]["name"] == "cli_tool"
    assert ai.tool_calls[0]["args"] == {"command": "pytest"}
    assert ai.additional_kwargs == {"cache_control": {"type": "ephemeral"}}
    assert ai.response_metadata == {"finish_reason": "stop"}

    tool = restored[1]
    assert isinstance(tool, ToolMessage)
    assert tool.content == "tool output"
    assert tool.tool_call_id == "c1"

    system = restored[2]
    assert isinstance(system, SystemMessage)
    assert system.content == "system"

    assert restored[3] == {"role": "user", "content": "dict payload"}


def test_deserialize_skips_non_dict_and_unknown_kind():
    restored = deserialize_turn_messages(
        [
            "skip-string",
            {"kind": "unknown", "content": "ignored"},
            {"kind": "system", "content": "kept"},
        ]
    )

    assert len(restored) == 1
    assert isinstance(restored[0], SystemMessage)
    assert restored[0].content == "kept"


def test_deserialize_dict_kind_strips_kind_field():
    restored = deserialize_turn_messages([{"kind": "dict", "content": "x", "extra": 1}])

    assert restored == [{"content": "x", "extra": 1}]
