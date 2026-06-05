from langchain_core.messages import AIMessage
import pytest

from config import Settings
from core.llm.client import LLMClient
from core.llm.types import LLMError


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


def make_llamacpp_qwen_config(**kwargs):
    values = {
        "llm.providers.default.kind": "llamacpp",
        "llm.providers.default.requires_api_key": False,
        "llm.providers.default.base_url": "http://192.168.20.30:8081/v1",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "HiModel_xh2_qwen3.5_9b.gguf",
        "llm.profiles.primary.thinking_type": "adaptive",
    }
    values.update(kwargs)
    return make_config(**values)


def test_llamacpp_qwen_thinking_shapes_system_messages_and_thinking_flag():
    client = LLMClient(config=make_llamacpp_qwen_config(), backend=lambda payload: payload)

    payload = client._build_payload(
        [
            {"role": "system", "content": "base rules"},
            {"role": "system", "content": "runtime notice"},
            {"role": "user", "content": "ping"},
        ]
    )

    assert payload["enable_thinking"] is True
    assert [item["role"] for item in payload["messages"]] == ["system", "user", "user"]
    assert client._last_payload_protocol_summary["payloadPolicySystemMessagesConverted"] == 1
    assert client._last_payload_protocol_summary["payloadPolicyQwenThinkingParameter"] == "enabled"


def test_llamacpp_qwen_thinking_strips_empty_assistant_prefill_and_reasoning():
    client = LLMClient(config=make_llamacpp_qwen_config(), backend=lambda payload: payload)

    payload = client._build_payload(
        [
            {"role": "assistant", "content": "", "reasoning_content": "上一轮思考"},
        ]
    )

    assert payload["messages"] == []
    assert client._last_payload_protocol_summary["payloadPolicyReasoningContentStripped"] == 1
    assert client._last_payload_protocol_summary["payloadPolicyEmptyAssistantPrefillRemoved"] == 1


def test_llamacpp_qwen_thinking_keeps_blocking_non_empty_assistant_prefill():
    client = LLMClient(config=make_llamacpp_qwen_config(), backend=lambda payload: payload)

    with pytest.raises(LLMError) as exc_info:
        client.invoke(
            [
                {"role": "user", "content": "今天是星期几"},
                {"role": "assistant", "content": "今天是"},
            ]
        )

    assert exc_info.value.category == "payload_protocol_error"
    assert exc_info.value.details["protocol"] == "llamacpp_qwen_thinking"
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"


def test_llamacpp_qwen_thinking_omits_explicit_tool_choice():
    client = LLMClient(config=make_llamacpp_qwen_config(), backend=lambda payload: payload)

    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read file",
                    "description": "Read one file",
                    "parameters": {
                        "type": "object",
                        "title": "Noisy",
                        "properties": {
                            "path": {
                                "type": "string",
                                "title": "Path",
                                "examples": ["agent.py"],
                            }
                        },
                    },
                },
            }
        ],
    )

    assert "tool_choice" not in payload
    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert "title" not in payload["tools"][0]["function"]["parameters"]
    assert "examples" not in payload["tools"][0]["function"]["parameters"]["properties"]["path"]
    assert client._last_payload_protocol_summary["payloadPolicyMinimalToolSchema"] is True


def test_deepseek_reasoning_protocol_preserves_assistant_reasoning_roundtrip():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "agent.py"}}],
                additional_kwargs={"reasoning_content": "先读文件再决定"},
            )
        ]
    )

    assert payload["messages"][0]["reasoning_content"] == "先读文件再决定"


def test_basic_chat_no_tools_blocks_tool_payload_before_provider():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "plain-chat",
            "llm.profiles.primary.contract": "basic_chat",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    with pytest.raises(LLMError) as exc_info:
        client.invoke(
            [{"role": "user", "content": "ping"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read one file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    assert exc_info.value.category == "capability_error"
