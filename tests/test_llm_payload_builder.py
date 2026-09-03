import copy
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from core.llm.client import LLMClient
from core.llm.reasoning_effort import resolve_reasoning_effort_request
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


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


def make_vllm_qwen_config(**kwargs):
    values = {
        "llm.providers.default.kind": "local",
        "llm.providers.default.requires_api_key": False,
        "llm.providers.default.base_url": "http://192.168.20.63:8011/v1",
        "llm.providers.default.api": "openai-completions",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "qwen3.6-35b-a3b",
        "llm.profiles.primary.protocol": "qwen_thinking_no_prefill",
        "llm.profiles.primary.transport": "chat_completions",
        "llm.profiles.primary.thinking_type": "adaptive",
    }
    values.update(kwargs)
    return make_config(**values)


@pytest.mark.parametrize(
    ("adapter", "mapping", "expected_payload", "expected_effective"),
    [
        ("reasoning_object", {"xhigh": "high"}, {"reasoning": {"effort": "high"}}, "high"),
        ("reasoning_effort", {}, {"reasoning_effort": "xhigh"}, "xhigh"),
        ("thinking_toggle", {"xhigh": "on"}, {"enable_thinking": True}, "on"),
        ("none", {}, {}, ""),
    ],
)
def test_reasoning_effort_request_adapter_mapping(adapter, mapping, expected_payload, expected_effective):
    resolution = resolve_reasoning_effort_request(
        SimpleNamespace(
            reasoning_effort="xhigh",
            reasoning_effort_adapter=adapter,
            reasoning_effort_map=mapping,
        )
    )

    assert resolution.requested == "xhigh"
    assert resolution.effective == expected_effective
    assert resolution.adapter == (adapter if adapter != "none" else "none")
    assert resolution.payload == expected_payload


def test_disabled_prompt_cache_strips_cache_control_without_mutating_messages():
    messages = [{
        "role": "system",
        "content": [
            {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "dynamic"},
        ],
    }]
    original = copy.deepcopy(messages)
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )

    payload = LLMClient(config=config, backend=lambda value: value)._build_payload(messages)

    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "stable"},
        {"type": "text", "text": "dynamic"},
    ]
    assert messages == original


@pytest.mark.parametrize("transport", ["chat_completions", "responses"])
def test_payload_preserves_total_and_connect_timeouts(transport):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.api": "responses" if transport == "responses" else "openai-completions",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": transport,
            "llm.profiles.primary.timeout": 180,
            "llm.profiles.primary.connect_timeout": 20,
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    timeout = payload["timeout"]
    assert timeout.connect == 20
    assert timeout.read == 180
    assert timeout.write == 180
    assert timeout.pool == 180


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


def test_vllm_qwen_thinking_adds_chat_template_kwargs_for_reasoning_parser():
    client = LLMClient(config=make_vllm_qwen_config(), backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["enable_thinking"] is True
    assert payload["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_vllm_qwen_thinking_disabled_updates_chat_template_kwargs():
    client = LLMClient(
        config=make_vllm_qwen_config(**{"llm.profiles.primary.thinking_type": "disabled"}),
        backend=lambda payload: payload,
    )

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["enable_thinking"] is False
    assert payload["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


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
            ),
            ToolMessage(content="file content", tool_call_id="call_1", name="read_file"),
        ]
    )

    assert payload["messages"][0]["reasoning_content"] == "先读文件再决定"


def test_payload_protocol_error_after_duplicate_id_normalization_includes_safe_snapshot():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    with pytest.raises(LLMError) as exc_info:
        client._build_payload(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "dup", "name": "read_file", "args": {"path": "a.py"}},
                        {"id": "dup", "name": "grep_search", "args": {"query": "needle"}},
                    ],
                ),
                ToolMessage(content="result", tool_call_id="dup"),
            ]
        )

    details = exc_info.value.details
    assert exc_info.value.category == "payload_protocol_error"
    # Duplicate ids are normalized deterministically before validation.  The
    # single result can only close one of the two calls, so the remaining
    # fail-closed protocol error is the unresolved call, not the historical
    # duplicate-id classification.
    assert details["payloadValidationErrorType"] == "unresolved_tool_call"
    assert details["payloadMessageAssistantToolCallCount"] == 2
    assert details["payloadMessageToolResultCount"] == 1
    assert details["payloadMessageShapeHash"]
    assert details["payloadMessageShapeTail"][-1]["role"] == "tool"


def test_failed_parallel_tool_results_remain_paired_context():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    same_failure = (
        "[错误] 本地 AutoGLM token 服务不可用\n"
        "依赖: autoglm_token_service\n"
        "阶段: token_fetch\n"
        "状态: unavailable"
    )

    payload = client._build_payload(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_search_a", "name": "web_search_tool", "args": {"query": "predictive coding"}},
                    {"id": "call_search_b", "name": "web_search_tool", "args": {"query": "free energy principle"}},
                ],
            ),
            ToolMessage(content=same_failure, tool_call_id="call_search_a"),
            ToolMessage(content=same_failure, tool_call_id="call_search_b"),
        ]
    )

    messages = payload["messages"]
    assert [item["role"] for item in messages] == ["assistant", "tool", "tool"]
    assert [item["tool_call_id"] for item in messages[1:]] == ["call_search_a", "call_search_b"]
    summary = client._last_payload_protocol_summary
    assert summary["payloadMessageAssistantToolCallCount"] == 2
    assert summary["payloadMessageToolResultCount"] == 2
    assert summary["payloadMessagePairedToolResultCount"] == 2
    assert summary["payloadMessageMissingToolResultCount"] == 0


def test_responses_transport_projects_tool_pairs_as_response_items():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.api": "responses",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload(
        [
            {"role": "user", "content": "查一下资料"},
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_search", "name": "web_search_tool", "args": {"query": "Responses API tool history"}},
                ],
            ),
            ToolMessage(content="找到 1 条来源", tool_call_id="call_search"),
            {"role": "user", "content": "继续"},
        ]
    )

    input_items = payload["input"]
    assert [item.get("type") or item.get("role") for item in input_items] == [
        "user",
        "function_call",
        "function_call_output",
        "user",
    ]
    assert input_items[1] == {
        "type": "function_call",
        "call_id": "call_search",
        "name": "web_search_tool",
        "arguments": '{"query": "Responses API tool history"}',
    }
    assert input_items[2] == {
        "type": "function_call_output",
        "call_id": "call_search",
        "output": "找到 1 条来源",
    }
    summary = client._last_payload_protocol_summary
    assert summary["payloadResponsesFunctionCallCount"] == 1
    assert summary["payloadResponsesFunctionCallOutputCount"] == 1
    assert summary["payloadResponsesMissingFunctionOutputCount"] == 0


def test_responses_transport_projects_assistant_history_as_output_text():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.api": "responses",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload(
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，我在。"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert payload["input"][1] == {
        "role": "assistant",
        "content": [{"type": "output_text", "text": "你好，我在。"}],
    }


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


def test_deepseek_default_streaming_payload_includes_stream_usage_options_without_cache_control():
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

    payload = client._build_payload([{"role": "user", "content": "ping"}], stream=True)

    assert payload["stream_options"] == {"include_usage": True}
    assert "prompt_cache_key" not in payload
    assert "prompt_cache_retention" not in payload
    assert "cache_control" not in str(payload["messages"])
    assert payload["messages"][0]["role"] == "user"


def test_deepseek_compat_override_omits_stream_usage_options_from_payload():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
            "llm.profiles.primary.compat.streamUsageOptions": False,
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "ping"}], stream=True)

    assert "stream_options" not in payload


# ---------------------------------------------------------------------------
# relay_autodl/GLM-5.3-flash prompt cache (mirrors the operator profile) and
# the controlled per-call max_output_tokens override
# ---------------------------------------------------------------------------


def _relay_autodl_glm_config(**overrides):
    values = {
        "llm.providers.default.kind": "autodl",
        "llm.providers.default.api_key": "test-key",
        "llm.providers.default.base_url": "https://www.autodl.art/api/v1",
        "llm.providers.default.api": "chat-completions",
        "llm.providers.default.compat_mode": "openai",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "GLM-5.3-flash",
        "llm.profiles.primary.transport": "chat_completions",
        "llm.profiles.primary.max_output_tokens": 32768,
        "llm.profiles.primary.prompt_cache.mode": "automatic",
    }
    values.update(overrides)
    return make_config(**values)


def test_relay_autodl_automatic_prompt_cache_injects_key_and_retention():
    config = _relay_autodl_glm_config()
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "评审输入"}])

    assert payload["prompt_cache_key"].startswith("vibelution:autodl:primary:")
    assert payload["prompt_cache_retention"] == "in_memory"
    assert payload["max_tokens"] == 32768


def test_relay_autodl_disabled_prompt_cache_keeps_payload_free_of_cache_fields():
    config = _relay_autodl_glm_config(**{"llm.profiles.primary.prompt_cache.mode": "disabled"})
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert "prompt_cache_key" not in payload
    assert "prompt_cache_retention" not in payload


def test_relay_autodl_prompt_cache_partition_scopes_the_cache_key():
    from core.llm.payload_builder import prompt_cache_partition_scope

    config = _relay_autodl_glm_config()
    client = LLMClient(config=config, backend=lambda payload: payload)

    unpartitioned = client._build_payload([{"role": "user", "content": "讲者输入"}])
    with prompt_cache_partition_scope("team-1:meeting_digest"):
        partitioned = client._build_payload([{"role": "user", "content": "讲者输入"}])

    assert ":team-1:meeting_digest:" in partitioned["prompt_cache_key"]
    assert partitioned["prompt_cache_key"] != unpartitioned["prompt_cache_key"]
    assert partitioned["prompt_cache_retention"] == "in_memory"


def test_metadata_override_clamps_max_output_tokens_and_ignores_invalid_values():
    from core.llm.client import MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY

    config = _relay_autodl_glm_config()
    client = LLMClient(config=config, backend=lambda payload: payload)
    messages = [{"role": "user", "content": "评审输入"}]

    clamped = client._build_payload(
        messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 8192}
    )

    assert clamped["max_tokens"] == 8192
    assert clamped["prompt_cache_key"]  # cache wiring is orthogonal to the clamp

    for bogus in ("8192", 0, -5, True, 3.5, None):
        payload = client._build_payload(
            messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: bogus}
        )
        assert payload["max_tokens"] == 32768

    assert client._build_payload(messages)["max_tokens"] == 32768


def test_metadata_override_clamps_responses_transport_payload():
    from core.llm.client import MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY

    config = _relay_autodl_glm_config(
        **{
            "llm.providers.default.api": "responses",
            "llm.profiles.primary.transport": "responses",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    messages = [{"role": "user", "content": "评审输入"}]

    clamped = client._build_payload(
        messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 8192}
    )
    untouched = client._build_payload(messages)

    assert clamped["max_output_tokens"] == 8192
    assert untouched["max_output_tokens"] == 32768


def test_per_call_output_token_cap_scope_clamps_payload_and_yields_to_metadata():
    # Chat-room speaker calls cannot thread metadata through the session
    # agent runtime; the owning service binds the derived generation cap via
    # the scope and the payload build falls back to it.
    from core.llm.client import (
        MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY,
        per_call_output_token_cap_scope,
    )

    config = _relay_autodl_glm_config()
    client = LLMClient(config=config, backend=lambda payload: payload)
    messages = [{"role": "user", "content": "讲者输入"}]

    with per_call_output_token_cap_scope(8400):
        clamped = client._build_payload(messages)
    assert clamped["max_tokens"] == 8400
    # Outside the scope the profile default is authoritative again.
    assert client._build_payload(messages)["max_tokens"] == 32768

    with per_call_output_token_cap_scope(8400):
        explicit = client._build_payload(
            messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 4096}
        )
        # Invalid metadata still falls back to the derived cap.
        invalid_metadata = client._build_payload(
            messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 0}
        )
    assert explicit["max_tokens"] == 4096
    assert invalid_metadata["max_tokens"] == 8400

    with per_call_output_token_cap_scope(None):
        assert client._build_payload(messages)["max_tokens"] == 32768

    for bogus in (0, -5, True, "8400", 3.5):
        with per_call_output_token_cap_scope(bogus):
            assert client._build_payload(messages)["max_tokens"] == 32768
