from types import SimpleNamespace

import pytest

from core.llm.protocols import WireProtocol
from core.llm.semantic_messages import InvocationScope
from core.llm.wire.chat_completions import ChatCompletionsWireAdapter


def route(*, allow_tools: bool = True):
    return SimpleNamespace(
        adapter_id="chat_completions",
        wire_protocol=WireProtocol.CHAT_COMPLETIONS,
        provider_id="openai_compatible",
        model_id="chat-model",
        effective_model="chat-model-runtime",
        runtime_endpoint="https://chat.example.test/v1",
        policy=SimpleNamespace(allow_tools=allow_tools),
    )


def scope(iteration: int = 0) -> InvocationScope:
    return InvocationScope(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id=f"invocation-{iteration + 1}",
        iteration=iteration,
    )


def test_chat_pre_tool_text_is_reclassified_to_commentary_under_same_item():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"content": "Let me check."}, "finish_reason": None}]},
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"query":'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"moon"}'}}]},
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ],
        route=route(),
        scope=scope(),
    )
    events = tuple(decoded)

    interim = next(event for event in events if event.kind == "interim_text_delta")
    committed = next(event for event in events if event.kind == "item_completed" and event.channel == "commentary")
    assert committed.item_id == interim.item_id
    assert interim.item_revision == 0
    assert interim.provisional is True
    assert committed.item_revision == 1
    assert committed.text == "Let me check."
    assert decoded.outcome.kind == "tool_calls"
    assert decoded.outcome.final_text == ""
    assert decoded.outcome.tool_calls[0].call_id == "call-1"
    assert decoded.outcome.tool_calls[0].arguments == {"query": "moon"}
    assert not any(event.kind == "answer_delta" for event in events)


def test_chat_successful_no_tool_terminal_promotes_interim_text_once():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"content": "Final "}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": "answer."}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ],
        route=route(),
        scope=scope(),
    )
    events = tuple(decoded)

    interim = [event for event in events if event.kind == "interim_text_delta"]
    promoted = [event for event in events if event.kind == "item_completed" and event.channel == "answer"]
    assert len(interim) == 2
    assert len(promoted) == 1
    assert promoted[0].item_id == interim[0].item_id
    assert promoted[0].item_revision == 1
    assert promoted[0].text == "Final answer."
    assert decoded.outcome.kind == "final_answer"
    assert decoded.outcome.final_text == "Final answer."
    assert sum(event.kind == "turn_completed" for event in events) == 1


@pytest.mark.parametrize(
    ("terminal_chunk", "expected_kind"),
    [
        ({"type": "chat.cancelled", "reason": "operator stop"}, "cancelled"),
        ({"type": "chat.failed", "error": {"message": "provider failed"}}, "failed"),
        ({"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]}, "incomplete"),
    ],
)
def test_chat_cancel_failure_or_length_never_promotes_interim_text(terminal_chunk, expected_kind):
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"content": "Draft"}, "finish_reason": None}]},
            terminal_chunk,
        ],
        route=route(),
        scope=scope(),
    )
    events = tuple(decoded)

    assert decoded.outcome.kind == expected_kind
    assert decoded.outcome.final_text == ""
    assert not any(event.kind == "item_completed" and event.channel == "answer" for event in events)


def test_chat_stream_exhaustion_without_finish_reason_is_incomplete():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [{"choices": [{"index": 0, "delta": {"content": "Draft"}, "finish_reason": None}]}],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.final_text == ""


def test_chat_tool_started_waits_for_provider_call_id_and_matches_ready_identity():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "lookup", "arguments": '{"query":'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "call-real", "function": {"arguments": '"moon"}'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ],
        route=route(),
        scope=scope(),
    )
    events = tuple(decoded)

    started = [event for event in events if event.kind == "tool_call_started"]
    ready = [event for event in events if event.kind == "tool_call_ready"]
    assert [event.call_id for event in started] == ["call-real"]
    assert [event.call_id for event in ready] == ["call-real"]


def test_chat_tool_finish_without_valid_call_is_incomplete_not_empty_tool_success():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, "id": "call-empty", "function": {"arguments": "{}"}}]},
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.tool_calls == ()


def test_chat_missing_provider_call_id_uses_invocation_scoped_fallback_everywhere():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "lookup", "arguments": "{}"}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ],
        route=route(),
        scope=scope(),
    )
    events = tuple(decoded)

    expected = "chat:invocation-1:tool:0"
    assert [event.call_id for event in events if event.kind == "tool_call_started"] == [expected]
    assert [event.call_id for event in events if event.kind == "tool_call_ready"] == [expected]
    assert decoded.outcome.tool_calls[0].call_id == expected
