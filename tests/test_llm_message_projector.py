import pytest

from config import Settings
from core.llm.client import LLMClient
from core.llm.message_projector import normalize_messages_for_provider
from core.llm.types import LLMError


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", True)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


def test_projector_demotes_legacy_tool_calls_with_results_to_semantic_history():
    full_result = "line\n" * 300

    projected = normalize_messages_for_provider(
        [
            {"role": "user", "content": "运行测试"},
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "toolName": "cli_tool",
                        "toolCallId": "call_1",
                        "arguments": {"command": "pytest -q"},
                        "status": "failed",
                        "result": full_result,
                        "resultPreview": "short preview must not win",
                    }
                ],
            },
        ]
    )

    assert [message["role"] for message in projected] == ["user", "assistant"]
    assert not any(message.get("role") == "tool" for message in projected)
    assert "历史工具结果: cli_tool" in projected[1]["content"]
    assert full_result.strip() in projected[1]["content"]
    assert "short preview must not win" not in projected[1]["content"]


def test_llm_client_payload_demotes_history_tool_results_after_projection():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "name": "history_search_tool",
                        "toolCallId": "call_history",
                        "arguments": {"query": "失败日志"},
                        "result": "完整历史证据",
                    }
                ],
            },
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "user"]
    assert "tool_calls" not in payload["messages"][0]
    assert "完整历史证据" in payload["messages"][0]["content"]


def test_llm_client_payload_repairs_orphan_tool_result_before_provider():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "tool",
                "tool_call_id": "call_orphan",
                "content": "payload_protocol_error: Tool result has no pending assistant tool call.",
            },
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "user"]
    assert "历史工具结果: unknown_tool" in payload["messages"][0]["content"]
    assert "pending assistant tool call" in payload["messages"][0]["content"]
    assert client._last_payload_protocol_summary["payloadValidationResult"] == "passed"


def test_llm_client_payload_repairs_unresolved_tool_call_before_provider():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "assistant",
                "content": "准备读取文件",
                "tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "read_file_tool", "arguments": "{\"file_path\":\"demo.py\"}"},
                    }
                ],
            },
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "user"]
    assert "tool_calls" not in payload["messages"][0]
    assert "历史工具调用未返回结果: read_file_tool" in payload["messages"][0]["content"]
    assert client._last_payload_protocol_summary["payloadValidationResult"] == "passed"


def test_responses_payload_converts_images_after_canonical_projection():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.api": "openai-responses",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.supports_image_input": True,
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]
    )

    assert payload["messages"][0]["content"] == [
        {"type": "input_text", "text": "看图"},
        {"type": "input_image", "image_url": "data:image/png;base64,abc"},
    ]


def test_payload_rejects_images_when_profile_disables_image_input():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.api": "openai-responses",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.supports_image_input": False,
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    with pytest.raises(LLMError) as exc_info:
        client._build_payload(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "看图"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    ],
                }
            ]
        )

    assert exc_info.value.category == "capability_error"
    assert exc_info.value.details["capability"] == "image_input"
