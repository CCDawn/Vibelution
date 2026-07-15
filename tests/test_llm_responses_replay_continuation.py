import pytest
from langchain_core.messages import SystemMessage

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


def test_responses_http_tool_continuation_replays_complete_semantic_input_without_previous_response_id():
    sent_payloads = []

    def backend(payload):
        sent_payloads.append(payload)
        if len(sent_payloads) > 1:
            return {
                "id": "resp_replay_2",
                "status": "completed",
                "output": [
                    {
                        "id": "message_replay_2",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "The moon is Earth's natural satellite."}],
                    }
                ],
            }
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
    outcome = client.invoke_outcome(
        [{"role": "user", "content": "look up the moon"}],
        metadata=_metadata(iteration=0),
    )
    assistant = client.project_outcome_message(outcome)

    assert "turn_outcome" not in assistant.additional_kwargs
    assert outcome.replay_state is not None
    assert outcome.replay_state.response_id == "resp_replay_1"
    assert outcome.replay_state.safe_summary()["hasResponseId"] is True
    assert "resp_replay_1" not in str(outcome.replay_state.safe_summary())

    continuation_outcome = client.invoke_outcome(
        [
            {"role": "user", "content": "look up the moon"},
            assistant,
            {
                "role": "tool",
                "tool_call_id": "call_replay_1",
                "content": "The moon is Earth's natural satellite.",
            },
        ],
        metadata=_metadata(iteration=1),
        replay_state=outcome.replay_state,
    )
    continuation = sent_payloads[1]

    assert "previous_response_id" not in continuation
    assert continuation["input"][0] == {
        "role": "user",
        "content": [{"type": "input_text", "text": "look up the moon"}],
    }
    item_kinds = [item.get("type") or item.get("role") for item in continuation["input"] if isinstance(item, dict)]
    assert item_kinds == ["user", "reasoning", "function_call", "function_call_output"]
    assert continuation_outcome.final_text == "The moon is Earth's natural satellite."
    assert len(sent_payloads) == 2


def test_responses_projection_anchors_opaque_reasoning_before_runtime_notice():
    replay_item = {
        "id": "reasoning_replay_notice",
        "type": "reasoning",
        "encrypted_content": "opaque-reasoning-state",
        "summary": [],
    }

    def backend(_payload):
        return {
            "id": "resp_replay_notice",
            "status": "completed",
            "output": [
                replay_item,
                {
                    "id": "function_replay_notice",
                    "type": "function_call",
                    "call_id": "call_replay_notice",
                    "name": "lookup",
                    "arguments": '{"query":"moon"}',
                },
            ],
        }

    client = LLMClient(config=_config(), backend=backend)
    outcome = client.invoke_outcome(
        [{"role": "user", "content": "look up the moon"}],
        metadata=_metadata(iteration=0),
    )
    assistant = client.project_outcome_message(outcome)

    assert assistant.additional_kwargs["reasoning_replay_item_id"] == "reasoning_replay_notice"

    continuation = client._build_payload(
        [
            {"role": "user", "content": "look up the moon"},
            assistant,
            {
                "role": "tool",
                "tool_call_id": "call_replay_notice",
                "content": "The moon is Earth's natural satellite.",
            },
            SystemMessage(content="Runtime context refreshed after the tool result."),
        ],
        metadata=_metadata(iteration=1),
        replay_state=outcome.replay_state,
    )

    assert "previous_response_id" not in continuation
    assert replay_item in continuation["input"]
    assert any(
        item.get("type") == "function_call_output"
        and item.get("call_id") == "call_replay_notice"
        for item in continuation["input"]
        if isinstance(item, dict)
    )


def test_invalid_explicit_model_protocol_fails_closed():
    client = LLMClient(config=_config())

    with pytest.raises(ProtocolResolutionError, match="unknown explicit model protocol") as exc_info:
        resolve_model_protocol(
            client.profile,
            client.provider,
            model_entry={"model": "gpt-5.6-luna", "protocol": "responses-ish"},
        )

    assert exc_info.value.code == "protocol_mismatch"
