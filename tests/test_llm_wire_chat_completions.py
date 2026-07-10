from types import SimpleNamespace

from core.llm.protocols import WireProtocol
from core.llm.semantic_messages import (
    ImagePart,
    InvocationScope,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticToolDefinition,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult
from core.llm.wire.chat_completions import ChatCompletionsWireAdapter


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


def test_chat_malformed_tool_arguments_remain_non_executable_mapping():
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

    assert decoded.outcome.kind == "tool_calls"
    assert decoded.outcome.tool_calls[0].arguments == {}


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
