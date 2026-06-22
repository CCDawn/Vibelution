import pytest
from langchain_core.messages import AIMessage, ToolMessage

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


def test_llm_client_payload_rejects_ui_tool_calls_before_provider_projection():
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
    with pytest.raises(LLMError) as exc_info:
        client._build_payload([
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
        ])

    assert exc_info.value.error_type == "payload_protocol_error"
    assert exc_info.value.details["forbiddenField"] == "toolCalls"


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
    assert client._last_payload_protocol_summary["payloadMessageRoleSequence"] == ["assistant", "user"]
    assert client._last_payload_protocol_summary["payloadMessageOrphanToolResultCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageMissingToolResultCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageShapeHash"]


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
    assert client._last_payload_protocol_summary["payloadMessageAssistantToolCallCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageToolResultCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageMissingToolResultCount"] == 0


def test_llm_client_payload_demotes_partial_live_tool_chain_before_provider():
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
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_ok", "name": "cli_tool", "args": {"command": "echo ok"}},
                    {"id": "call_timeout", "name": "cli_tool", "args": {"command": "bash -c find ."}},
                ],
            ),
            ToolMessage(content="ok", tool_call_id="call_ok"),
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "assistant", "user"]
    assert "tool_calls" not in payload["messages"][0]
    assert "历史工具调用未返回结果: cli_tool" in payload["messages"][0]["content"]
    assert "历史工具结果: cli_tool" in payload["messages"][1]["content"]
    assert client._last_payload_protocol_summary["payloadValidationResult"] == "passed"
    assert client._last_payload_protocol_summary["payloadMessageAssistantToolCallCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageToolResultCount"] == 0
    assert client._last_payload_protocol_summary["payloadMessageMissingToolResultCount"] == 0
    assert client._last_payload_protocol_summary["payloadPolicyProviderToolChainRepaired"] >= 1


def test_llm_client_payload_preserves_complete_live_timeout_tool_pair():
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
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_timeout", "name": "cli_tool", "args": {"command": "bash -c find ."}},
                ],
            ),
            ToolMessage(
                content="[超时] 命令执行超过 30 秒被强制终止。",
                tool_call_id="call_timeout",
            ),
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "tool", "user"]
    assert payload["messages"][0]["tool_calls"][0]["id"] == "call_timeout"
    assert payload["messages"][1]["tool_call_id"] == "call_timeout"
    assert client._last_payload_protocol_summary["payloadValidationResult"] == "passed"
    assert client._last_payload_protocol_summary["payloadMessageAssistantToolCallCount"] == 1
    assert client._last_payload_protocol_summary["payloadMessageToolResultCount"] == 1
    assert client._last_payload_protocol_summary["payloadMessagePairedToolResultCount"] == 1
    assert client._last_payload_protocol_summary["payloadMessageMissingToolResultCount"] == 0


def test_llm_client_payload_preserves_repeated_failed_tool_results_by_call_id():
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
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_search_a", "name": "web_search_tool", "args": {"query": "predictive coding"}},
                    {"id": "call_search_b", "name": "web_search_tool", "args": {"query": "free energy principle"}},
                ],
            ),
            ToolMessage(content="[错误] 本地 AutoGLM token 服务不可用", tool_call_id="call_search_a"),
            ToolMessage(content="[错误] 本地 AutoGLM token 服务不可用", tool_call_id="call_search_b"),
        ]
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "tool", "tool"]
    assert [message["tool_call_id"] for message in payload["messages"][1:]] == ["call_search_a", "call_search_b"]
    assert client._last_payload_protocol_summary["payloadValidationResult"] == "passed"
    assert client._last_payload_protocol_summary["payloadMessageAssistantToolCallCount"] == 2
    assert client._last_payload_protocol_summary["payloadMessageToolResultCount"] == 2
    assert client._last_payload_protocol_summary["payloadMessagePairedToolResultCount"] == 2
    assert client._last_payload_protocol_summary["payloadMessageMissingToolResultCount"] == 0


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
