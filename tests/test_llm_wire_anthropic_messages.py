from __future__ import annotations

from types import SimpleNamespace

from config.models import (
    AppConfig,
    LLMConfig,
    LLMProfile,
    PinnedModelConfig,
    ProviderConfig,
    ProviderProtocolsConfig,
)
from core.llm.client import LLMClient
from core.llm.protocols import WireProtocol
from core.llm.semantic_messages import (
    InvocationScope,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticToolDefinition,
    TextPart,
)
from core.llm.wire.anthropic_messages import AnthropicMessagesNativeWireAdapter
from core.llm.wire.chat_completions import OUTPUT_LENGTH_TRUNCATED
from core.llm.wire.compat_native import AnthropicMessagesLiteLLMCompatWireAdapter


def _scope() -> InvocationScope:
    return InvocationScope(
        session_id="session-1", turn_id="turn-1", invocation_id="invoke-1", iteration=0
    )


def _request(*, stream: bool = False) -> SemanticModelRequest:
    return SemanticModelRequest(
        scope=_scope(),
        messages=(
            SemanticMessage("system", (TextPart("Be precise."),)),
            SemanticMessage("user", (TextPart("hello"),)),
        ),
        tools=(
            SemanticToolDefinition(
                name="lookup", description="Lookup", input_schema={"type": "object"}
            ),
        ),
        settings=SemanticGenerationSettings(
            max_output_tokens=256, stream=stream, tool_choice="auto"
        ),
    )


def _route(adapter_id: str = "anthropic_messages_native"):
    return SimpleNamespace(
        adapter_id=adapter_id,
        wire_protocol=WireProtocol.ANTHROPIC_MESSAGES,
        effective_model="claude-test",
        runtime_endpoint="https://api.anthropic.com/v1/messages",
    )


def test_native_adapter_encodes_real_messages_shape_not_openai_chat_shape() -> None:
    payload = AnthropicMessagesNativeWireAdapter().encode_request(
        _request(), route=_route()
    ).body

    assert payload["system"] == [{"type": "text", "text": "Be precise."}]
    assert payload["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]}
    ]
    assert payload["tools"] == [
        {"name": "lookup", "description": "Lookup", "input_schema": {"type": "object"}}
    ]
    assert "tool_choice" in payload
    assert "functions" not in payload


def test_native_adapter_decodes_text_tool_and_cache_usage() -> None:
    outcome = AnthropicMessagesNativeWireAdapter().decode_response(
        {
            "id": "msg-1",
            "content": [
                {"type": "thinking", "thinking": "reason"},
                {"type": "text", "text": "answer"},
                {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {"q": "x"}},
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
            },
        },
        route=_route(),
        scope=_scope(),
    )

    assert outcome.kind == "tool_calls"
    assert any(event.text == "answer" for event in outcome.events)
    assert outcome.tool_calls[0].name == "lookup"
    usage_events = [event for event in outcome.events if event.kind == "usage_updated"]
    assert usage_events
    assert usage_events[-1].diagnostic_summary["cachedInputTokens"] == 3
    assert usage_events[-1].diagnostic_summary["cacheCreationInputTokens"] == 2


def test_native_max_tokens_stop_reason_marks_output_length_truncated() -> None:
    outcome = AnthropicMessagesNativeWireAdapter().decode_response(
        {
            "id": "msg-1",
            "content": [{"type": "text", "text": "partial answer"}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 10, "output_tokens": 8},
        },
        route=_route(),
        scope=_scope(),
    )

    # stop_reason "max_tokens" maps to finish_reason "length" and then to the
    # shared explicit truncation marker the client converts into
    # LLMOutputTruncatedError.
    assert outcome.kind == "incomplete"
    assert outcome.error == OUTPUT_LENGTH_TRUNCATED


def test_native_stream_max_tokens_stop_reason_marks_output_length_truncated() -> None:
    streamed = AnthropicMessagesNativeWireAdapter().decode_stream(
        [
            {"type": "message_start", "message": {"id": "msg-3", "usage": {"input_tokens": 2}}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "partial"},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "max_tokens"},
                "usage": {"output_tokens": 9},
            },
            {"type": "message_stop"},
        ],
        route=_route(),
        scope=_scope(),
    )
    tuple(streamed)

    assert streamed.outcome.kind == "incomplete"
    assert streamed.outcome.error == OUTPUT_LENGTH_TRUNCATED


def test_native_sse_and_nonstream_produce_equivalent_final_text() -> None:
    adapter = AnthropicMessagesNativeWireAdapter()
    streamed = adapter.decode_stream(
        [
            {"type": "message_start", "message": {"id": "msg-2", "usage": {"input_tokens": 2}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
            {"type": "message_stop"},
        ],
        route=_route(),
        scope=_scope(),
    )
    tuple(streamed)
    direct = adapter.decode_response(
        {"id": "msg-2", "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"},
        route=_route(),
        scope=_scope(),
    )
    assert streamed.outcome.final_text == direct.final_text == "hi"
    assert streamed.outcome.kind == direct.kind == "final_answer"


def test_native_and_litellm_compat_have_distinct_adapter_identity() -> None:
    native = AnthropicMessagesNativeWireAdapter()
    compat = AnthropicMessagesLiteLLMCompatWireAdapter()
    assert native.adapter_id == "anthropic_messages_native"
    assert compat.adapter_id == "anthropic_messages_litellm_compat"
    assert native.wire_protocol is compat.wire_protocol is WireProtocol.ANTHROPIC_MESSAGES


def test_official_anthropic_native_route_uses_native_payload_and_injected_backend(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    provider = ProviderConfig(
        provider_id="anthropic",
        kind="anthropic",
        api="anthropic-messages",
        service_class="official_api",
        driver="anthropic",
        compat_mode="native",
        base_url="https://api.anthropic.com",
        credential_ref="env:ANTHROPIC_API_KEY",
        protocols=ProviderProtocolsConfig(
            default="anthropic_messages", allowed=["anthropic_messages"]
        ),
        models={
            "claude": PinnedModelConfig(
                upstream_id="claude-test",
                wire_protocol="anthropic_messages",
                model_protocol="anthropic_chat",
            )
        },
        legacy_inference_allowed=False,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="anthropic",
        model_ref="anthropic/claude",
        model="claude-test",
        transport="chat_completions",
        contract="tool_chat",
    )
    config = AppConfig(
        llm=LLMConfig(
            schema_version=2,
            providers={"anthropic": provider},
            profiles={"primary": profile},
        )
    )
    backend = lambda payload: payload
    client = LLMClient(config=config, backend=backend)

    payload = client._build_payload(
        [{"role": "system", "content": "Be precise."}, {"role": "user", "content": "ping"}],
        stream=False,
        metadata={
            "sessionId": "session-1",
            "turnId": "turn-1",
            "invocationId": "invoke-1",
            "iteration": 0,
        },
    )

    assert client.protocol_route.adapter_id == "anthropic_messages_native"
    assert payload["model"] == "claude-test"
    assert payload["system"] == [{"type": "text", "text": "Be precise."}]
    assert client._backend_for_payload(payload) is backend
