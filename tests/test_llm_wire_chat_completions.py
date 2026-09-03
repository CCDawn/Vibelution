from types import SimpleNamespace

import pytest

from core.llm.protocols import WireProtocol
from core.llm.provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
from core.llm.semantic_messages import (
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    ReasoningTextPart,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticOutputSchema,
    SemanticToolDefinition,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult
from core.llm.wire.chat_completions import (
    OUTPUT_LENGTH_TRUNCATED,
    ChatCompletionsWireAdapter,
)


def route():
    return SimpleNamespace(
        adapter_id="chat_completions",
        wire_protocol=WireProtocol.CHAT_COMPLETIONS,
        provider_id="openai_compatible",
        model_id="chat-model",
        effective_model="chat-model-runtime",
        runtime_endpoint="https://chat.example.test/v1",
        policy=SimpleNamespace(allow_tools=True),
    )


def scope() -> InvocationScope:
    return InvocationScope(session_id="session-1", turn_id="turn-1", invocation_id="invocation-1", iteration=0)


def identity(item_id: str) -> CanonicalItemIdentity:
    current = scope()
    return CanonicalItemIdentity(
        session_id=current.session_id,
        turn_id=current.turn_id,
        invocation_id=current.invocation_id,
        iteration=current.iteration,
        item_id=item_id,
    )


def test_chat_encodes_strict_structured_output_schema():
    schema = {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}},
        "required": ["reasoning"],
        "additionalProperties": False,
    }
    output_schema = SemanticOutputSchema(
        name="research_protocol_review_v1",
        schema=schema,
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="user", parts=(TextPart("review"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=64),
        output_schema=output_schema,
    )

    payload = ChatCompletionsWireAdapter().encode_request(request, route=route()).body

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "research_protocol_review_v1",
            "strict": True,
            "schema": schema,
        },
    }


def test_chat_encoder_owns_openai_messages_and_tool_result_shape():
    call = CanonicalToolCall(
        identity=identity("call-item"),
        call_id="call-1",
        name="lookup",
        arguments={"query": "moon"},
    )
    result = CanonicalToolResult(
        identity=identity("result-item"),
        call_id="call-1",
        tool_name="lookup",
        output={"value": 42},
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(
            SemanticMessage(role="user", parts=(TextPart("look"), ImagePart("memory://image", "image/png"))),
            SemanticMessage(role="assistant", parts=(ToolCallPart(call),)),
            SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
            SemanticMessage(role="assistant", parts=(TextPart("done"),)),
            SemanticMessage(role="user", parts=(TextPart("continue"),)),
        ),
        tools=(
            SemanticToolDefinition(name="lookup", input_schema={"type": "object"}, description="Lookup"),
        ),
        settings=SemanticGenerationSettings(max_output_tokens=64, stream=True),
    )

    payload = ChatCompletionsWireAdapter().encode_request(request, route=route()).body

    assert payload["model"] == "chat-model-runtime"
    assert "input" not in payload
    assert payload["max_tokens"] == 64
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "memory://image"}},
    ]
    assert payload["messages"][1]["tool_calls"][0]["id"] == "call-1"
    assert payload["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"value":42}',
    }
    assert payload["messages"][3:] == [
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "continue"},
    ]
    assert "input" not in payload


def test_chat_reasoning_only_message_is_not_silently_dropped():
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="assistant", parts=(ReasoningTextPart("reasoning only"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
    )

    payload = ChatCompletionsWireAdapter().encode_request(request, route=route()).body

    assert payload["messages"] == [
        {"role": "assistant", "content": "", "reasoning_content": "reasoning only"}
    ]


def test_chat_rejects_opaque_responses_replay():
    current_route = route()
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=WireProtocol.RESPONSES,
        opaque_items=(OpaqueReplayItem(item_id="reasoning-1", payload=b'{"type":"reasoning"}'),),
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reasoning-1"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="does not accept provider replay state"):
        ChatCompletionsWireAdapter().encode_request(request, route=current_route)


def test_chat_non_stream_and_stream_have_same_final_outcome():
    adapter = ChatCompletionsWireAdapter()
    response = {
        "id": "chatcmpl-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Done."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }
    non_stream = adapter.decode_response(response, route=route(), scope=scope())
    stream = adapter.decode_stream(
        [
            {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"content": "Done."}, "finish_reason": None}]},
            {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ],
        route=route(),
        scope=scope(),
    )
    tuple(stream)

    assert non_stream.kind == stream.outcome.kind == "final_answer"
    assert non_stream.final_text == stream.outcome.final_text == "Done."
    assert non_stream.events[0].kind == stream.outcome.events[0].kind == "turn_started"


def test_chat_parallel_tool_calls_preserve_provider_ids_and_order():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "call-a", "function": {"name": "first", "arguments": "{}"}},
                                {"index": 1, "id": "call-b", "function": {"name": "second", "arguments": "{}"}},
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

    tuple(decoded)

    assert [call.call_id for call in decoded.outcome.tool_calls] == ["call-a", "call-b"]
    assert [call.name for call in decoded.outcome.tool_calls] == ["first", "second"]


def test_chat_malformed_tool_arguments_are_intercepted_as_incomplete():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-bad-json",
                                    "function": {"name": "lookup", "arguments": "{bad"},
                                }
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

    tuple(decoded)

    # Truncated arguments must never surface as an executable tool call.
    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == "chat.finish.tool_arguments_unparsable"
    assert decoded.outcome.tool_calls == ()
    assert decoded.outcome.pending_tool_call_ids == ()
    terminal_events = [event for event in decoded.outcome.events if event.terminal]
    assert terminal_events[-1].provider_event_type == "chat.finish.tool_arguments_unparsable"


def test_chat_finish_length_with_truncated_call_stays_incomplete():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-truncated",
                                    "function": {
                                        "name": "writeback",
                                        "arguments": '{"teamId": "research-team", "result_json": "{\"items"',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == "chat.finish.tool_arguments_unparsable"
    assert decoded.outcome.tool_calls == ()


def test_chat_finish_length_truncation_is_marked_output_length_truncated():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {"index": 0, "delta": {"content": "partial ans"}, "finish_reason": None}
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == OUTPUT_LENGTH_TRUNCATED
    terminal_events = [event for event in decoded.outcome.events if event.terminal]
    assert terminal_events[-1].provider_event_type == "chat.finish.length"


def test_chat_decode_response_finish_length_marks_output_length_truncated():
    outcome = ChatCompletionsWireAdapter().decode_response(
        {
            "id": "chatcmpl-1",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "partial"},
                    "finish_reason": "length",
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        },
        route=route(),
        scope=scope(),
    )

    assert outcome.kind == "incomplete"
    assert outcome.error == OUTPUT_LENGTH_TRUNCATED


def test_chat_late_argument_chunk_after_finish_does_not_escape_interception():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-late",
                                    "function": {"name": "lookup", "arguments": '{"query": "va'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            # Relay reorders: a trailing argument fragment arrives after the
            # finish chunk completed the choice. It must be accumulated (not
            # dropped) and the outcome must stay intercepted.
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "lid"}}]},
                        "finish_reason": None,
                    }
                ]
            },
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == "chat.finish.tool_arguments_unparsable"
    assert decoded.outcome.tool_calls == ()


def test_chat_late_argument_chunk_completing_call_keeps_interception_for_resend():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-late-recovered",
                                    "function": {"name": "lookup", "arguments": '{"query": "va'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            # The late fragment completes the JSON object. The terminal event
            # was already emitted as incomplete, so the canonical outcome stays
            # incomplete and the client layer resends the same request instead
            # of executing a call whose arguments were partially delivered.
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'lid"}'}}]},
                        "finish_reason": None,
                    }
                ]
            },
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == "chat.finish.tool_arguments_unparsable"
    assert decoded.outcome.tool_calls == ()


def test_chat_tool_result_encoder_preserves_call_id():
    result = CanonicalToolResult(
        identity=identity("result-item"),
        call_id="call-1",
        tool_name="lookup",
        output="ok",
    )

    assert ChatCompletionsWireAdapter().encode_tool_results([result]) == [
        {"role": "tool", "tool_call_id": "call-1", "content": "ok"}
    ]


def test_chat_cumulative_reasoning_emits_prefix_deltas_with_bounded_source():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"reasoning": "先看"}}]},
            {"choices": [{"index": 0, "delta": {"reasoning": "先看日志"}}]},
            {"choices": [{"index": 0, "delta": {"reasoning": "先看日志再回答"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ],
        route=route(),
        scope=scope(),
    )

    events = [event for event in decoded if event.kind == "reasoning_delta"]

    assert [event.text for event in events] == ["先看", "日志", "再回答"]
    assert [dict(event.diagnostic_summary) for event in events] == [
        {"reasoningSource": "reasoning"},
        {"reasoningSource": "reasoning"},
        {"reasoningSource": "reasoning"},
    ]


def test_chat_explicit_reasoning_delta_fields_remain_direct_deltas():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"reasoning_delta": "A"}}]},
            {"choices": [{"index": 0, "delta": {"reasoning_delta": "B"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ],
        route=route(),
        scope=scope(),
    )

    events = [event for event in decoded if event.kind == "reasoning_delta"]

    assert [event.text for event in events] == ["A", "B"]
    assert [event.diagnostic_summary["reasoningSource"] for event in events] == [
        "reasoning_delta",
        "reasoning_delta",
    ]


def test_chat_non_prefix_reasoning_replacement_is_emitted_whole():
    decoded = ChatCompletionsWireAdapter().decode_stream(
        [
            {"choices": [{"index": 0, "delta": {"reasoning": "先看日志"}}]},
            {"choices": [{"index": 0, "delta": {"reasoning": "改查配置"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ],
        route=route(),
        scope=scope(),
    )

    events = [event for event in decoded if event.kind == "reasoning_delta"]

    assert [event.text for event in events] == ["先看日志", "改查配置"]
