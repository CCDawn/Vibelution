from dataclasses import replace

import pytest

from core.llm.client import LLMClient
from core.llm.protocols import WireProtocol
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


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


def test_unsupported_native_adapter_fails_before_provider_io():
    calls = []
    client = LLMClient(config=_config(), backend=lambda payload: calls.append(payload))
    client.protocol_route = replace(
        client.protocol_route,
        wire_protocol=WireProtocol.ANTHROPIC_MESSAGES,
        adapter_id=WireProtocol.ANTHROPIC_MESSAGES.value,
        wire_source="test_native_route",
    )

    with pytest.raises(LLMError) as exc_info:
        client.invoke([{"role": "user", "content": "ping"}], metadata=_metadata())

    assert exc_info.value.category == "unsupported_wire_protocol"
    assert exc_info.value.retryable is False
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"
    assert calls == []
    assert "test-key" not in str(exc_info.value.details)
