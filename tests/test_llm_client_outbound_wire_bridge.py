from dataclasses import replace
import inspect

import pytest

from core.llm.client import LLMClient
from core.llm.protocols import WireProtocol
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


@pytest.fixture(autouse=True)
def _scrub_provider_api_key_env(monkeypatch):
    # relay/openai_compatible 的 canonical env 是 OPENAI_API_KEY；本机真实环境变量
    # 会按设计优先于 config api_key，必须隔离以保证 payload 断言确定。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_ENABLE_USER_ENV_FALLBACK", raising=False)


def _config(*, transport: str = "responses"):
    return isolated_settings_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": transport,
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.tool_calling_mode": "auto",
        }
    )


def _metadata():
    return {
        "sessionId": "session-1",
        "turnId": "turn-1",
        "invocationId": "invocation-1",
        "iteration": 0,
        "promptPurpose": "main_reply",
    }


@pytest.mark.parametrize("streaming", [False, True])
def test_provider_control_only_reply_raises_without_retry_or_visible_text(streaming):
    leaked = "<ds_safety>internal classification</ds_safety>Safe"
    calls = []

    def backend(payload):
        calls.append(payload)
        if streaming:
            return iter([
                {"choices": [{"index": 0, "delta": {"content": leaked}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ])
        return {"choices": [{"index": 0, "message": {"content": leaked}, "finish_reason": "stop"}]}

    client = LLMClient(config=_config(transport="chat_completions"), backend=backend)
    client.protocol_route = replace(client.protocol_route, provider_id="opencode_go",
                                    provider_kind="opencode", effective_model="deepseek-v4.1-flash")
    events = []
    with pytest.raises(LLMError) as caught:
        if streaming:
            for event in client.stream_events([{"role": "user", "content": "inspect"}], metadata=_metadata()):
                events.append(event)  # noqa: PERF402 - retain events emitted before the protocol error
        else:
            client.invoke_outcome([{"role": "user", "content": "inspect"}], metadata=_metadata())
    assert caught.value.category == "provider_protocol_error"
    assert caught.value.retryable is False
    assert len(calls) == 1
    assert "internal classification" not in str(caught.value)
    assert not [event for event in events if event.text]


def test_unavailable_wire_adapter_fails_before_provider_io():
    # 0d6767317 起 anthropic_messages/gemini_generate_content 已注册 compat 适配器；
    # 本测试锁定剩余契约：未注册的 adapter_id 仍在 provider IO 前被拒绝。
    calls = []
    client = LLMClient(config=_config(), backend=lambda payload: calls.append(payload))
    client.protocol_route = replace(
        client.protocol_route,
        wire_protocol=WireProtocol.ANTHROPIC_MESSAGES,
        adapter_id="anthropic_messages_rest_native",
        wire_source="test_native_route",
    )

    with pytest.raises(LLMError) as exc_info:
        client.invoke([{"role": "user", "content": "ping"}], metadata=_metadata())

    assert exc_info.value.category == "unsupported_wire_protocol"
    assert exc_info.value.retryable is False
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"
    assert calls == []
    assert "test-key" not in str(exc_info.value.details)


def test_responses_client_uses_registry_encoder_once_and_preserves_runtime_envelope(monkeypatch):
    client = LLMClient(config=_config(transport="responses"), backend=lambda payload: payload)
    adapter = client._required_wire_adapter()
    calls = []
    original = adapter.encode_request

    def observed(request, *, route):
        calls.append((request, route))
        return original(request, route=route)

    monkeypatch.setattr(adapter, "encode_request", observed)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        stream=True,
        metadata=_metadata(),
    )

    assert len(calls) == 1
    assert calls[0][0].scope.invocation_id == "invocation-1"
    assert "input" in payload and "messages" not in payload
    assert payload["api_key"] == "test-key"
    assert payload["base_url"] == "https://relay.example.test/v1"
    assert payload["timeout"] is not None
    assert payload["stream"] is True
    assert client._last_payload_protocol_summary["wireProtocol"] == "responses"


def test_chat_client_uses_registry_encoder_once_and_preserves_runtime_envelope(monkeypatch):
    client = LLMClient(config=_config(transport="chat_completions"), backend=lambda payload: payload)
    adapter = client._required_wire_adapter()
    calls = []
    original = adapter.encode_request

    def observed(request, *, route):
        calls.append((request, route))
        return original(request, route=route)

    monkeypatch.setattr(adapter, "encode_request", observed)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        stream=True,
        metadata=_metadata(),
    )

    assert len(calls) == 1
    assert calls[0][0].scope.invocation_id == "invocation-1"
    assert "messages" in payload and "input" not in payload
    assert payload["model"] == client.adapter.litellm_model_name()
    assert payload["api_key"] == "test-key"
    assert payload["base_url"] == "https://relay.example.test/v1"


def test_distinct_protocol_clients_reencode_semantic_input_with_fresh_scopes(monkeypatch):
    semantic_messages = [{"role": "user", "content": "ping"}]
    responses_client = LLMClient(
        config=_config(transport="responses"),
        backend=lambda payload: payload,
    )
    chat_client = LLMClient(
        config=_config(transport="chat_completions"),
        backend=lambda payload: payload,
    )
    scopes = []
    for label, client in (("responses", responses_client), ("chat", chat_client)):
        adapter = client._required_wire_adapter()
        original = adapter.encode_request

        def observed(request, *, route, _label=label, _original=original):
            scopes.append((_label, request.scope.invocation_id))
            return _original(request, route=route)

        monkeypatch.setattr(adapter, "encode_request", observed)

    responses_payload = responses_client._build_payload(
        semantic_messages,
        stream=False,
        metadata={**_metadata(), "invocationId": "invocation-primary"},
    )
    chat_payload = chat_client._build_payload(
        semantic_messages,
        stream=False,
        metadata={**_metadata(), "invocationId": "invocation-fallback"},
    )

    assert "input" in responses_payload and "messages" not in responses_payload
    assert "messages" in chat_payload and "input" not in chat_payload
    assert responses_payload is not chat_payload
    assert responses_payload["input"] is not chat_payload["messages"]
    assert scopes == [
        ("responses", "invocation-primary"),
        ("chat", "invocation-fallback"),
    ]


def test_client_has_no_legacy_outbound_or_decode_fallback_ownership():
    payload_source = inspect.getsource(LLMClient._build_payload)
    decode_source = inspect.getsource(LLMClient._decode_canonical_response)
    stream_source = inspect.getsource(LLMClient._stream_attempt)

    assert "build_llm_payload(" not in payload_source
    assert "except LookupError" not in decode_source
    assert "wire_adapter = None" not in stream_source
    assert "ResponsesStreamNormalizer" not in stream_source
