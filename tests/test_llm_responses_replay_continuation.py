import pytest

from core.llm.client import LLMClient
from core.llm.protocol_resolver import ProtocolResolutionError, resolve_model_protocol
from tests.helpers.isolated_config import isolated_settings_config


def _config():
    return isolated_settings_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.tool_calling_mode": "auto",
        }
    )


def _metadata(*, iteration: int):
    return {
        "sessionId": "session-replay",
        "turnId": "turn-replay",
        "invocationId": "invocation-replay",
        "iteration": iteration,
        "promptPurpose": "main_reply",
    }


def test_responses_tool_continuation_uses_latest_canonical_replay_bookmark():
    sent_payloads = []

    def backend(payload):
        sent_payloads.append(payload)
        return {
            "id": "resp_replay_1",
            "status": "completed",
            "output": [
                {
                    "id": "reasoning_replay_1",
                    "type": "reasoning",
                    "encrypted_content": "opaque-reasoning-state",
                    "summary": [],
                },
                {
                    "id": "function_replay_1",
                    "type": "function_call",
                    "call_id": "call_replay_1",
                    "name": "lookup",
                    "arguments": '{"query":"moon"}',
                },
            ],
        }

    client = LLMClient(config=_config(), backend=backend)
    assistant = client.invoke(
        [{"role": "user", "content": "look up the moon"}],
        metadata=_metadata(iteration=0),
    )

    outcome = assistant.additional_kwargs["turn_outcome"]
    assert outcome.replay_state is not None
    assert outcome.replay_state.response_id == "resp_replay_1"
    assert outcome.replay_state.safe_summary()["hasResponseId"] is True
    assert "resp_replay_1" not in str(outcome.replay_state.safe_summary())

    continuation = client._build_payload(
        [
            assistant,
            {
                "role": "tool",
                "tool_call_id": "call_replay_1",
                "content": "The moon is Earth's natural satellite.",
            },
        ],
        metadata=_metadata(iteration=1),
    )

    assert continuation["previous_response_id"] == "resp_replay_1"
    assert all(item.get("role") != "assistant" for item in continuation["input"] if isinstance(item, dict))
    assert any(item.get("type") == "reasoning" for item in continuation["input"] if isinstance(item, dict))
    assert any(item.get("type") == "function_call_output" for item in continuation["input"] if isinstance(item, dict))
    assert len(sent_payloads) == 1


def test_invalid_explicit_model_protocol_fails_closed():
    client = LLMClient(config=_config())

    with pytest.raises(ProtocolResolutionError, match="unknown explicit model protocol") as exc_info:
        resolve_model_protocol(
            client.profile,
            client.provider,
            model_entry={"model": "gpt-5.6-luna", "protocol": "responses-ish"},
        )

    assert exc_info.value.code == "protocol_mismatch"
