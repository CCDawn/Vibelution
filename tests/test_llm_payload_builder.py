import copy
import logging
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from config.llm_security import validate_llm_provider_target
from core.llm.client import LLMClient
from core.llm.invocation import (
    invoke_llm,
    invoke_llm_outcome,
    run_streaming_llm_outcome,
    stream_llm,
)
from core.llm.payload_builder import (
    invocation_header_identity_scope,
    resolve_extra_header_identity_templates,
)
from core.llm.reasoning_effort import resolve_reasoning_effort_request
from core.llm.types import CanonicalItemIdentity, LLMError, TurnOutcome
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


def make_dashscope_openai_compat_config(**kwargs):
    values = {
        "llm.providers.default.kind": "official_api",
        "llm.providers.default.requires_api_key": False,
        "llm.providers.default.base_url": "https://dashscope.example/compatible-mode/v1",
        "llm.providers.default.api": "openai-completions",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "qwen3.8-max-0902",
    }
    values.update(kwargs)
    return make_config(**values)


def test_openai_compat_wire_passes_declared_thinking_via_extra_body():
    """SCI-007 regression: on chat_completions (thinking_param_shape !=
    "qwen") a declared thinking contract used to be silently dropped, so
    the digest drafter ran on the provider default thinking pass and its
    deep-reasoning call outran the 600s per-call fence.  The declared
    toggle now travels via litellm extra_body instead."""

    client = LLMClient(
        config=make_dashscope_openai_compat_config(
            **{"llm.profiles.primary.thinking_type": "disabled"}
        ),
        backend=lambda payload: payload,
    )

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["extra_body"]["enable_thinking"] is False
    assert "enable_thinking" not in payload
    assert client._last_payload_protocol_summary["payloadPolicyQwenThinkingParameter"] == "disabled"


def test_openai_compat_wire_undeclared_thinking_stays_byte_identical():
    """No declared thinking contract: no thinking parameters at all."""

    client = LLMClient(
        config=make_dashscope_openai_compat_config(
            **{"llm.profiles.primary.thinking_type": ""}
        ),
        backend=lambda payload: payload,
    )

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert "extra_body" not in payload
    assert "enable_thinking" not in payload


def test_openai_compat_enabled_thinking_switches_to_qwen_shape_protocol():
    """A declared non-disabled contract makes the resolver pick the qwen
    thinking protocol, which keeps the historical top-level parameter."""

    client = LLMClient(
        config=make_dashscope_openai_compat_config(
            **{"llm.profiles.primary.thinking_type": "adaptive"}
        ),
        backend=lambda payload: payload,
    )

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["enable_thinking"] is True
    assert "extra_body" not in payload

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


def test_deepseek_reasoning_protocol_last_mile_guard_repairs_wire_payload(monkeypatch):
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

    def drop_semantic_backstop(messages, *, route):
        return list(messages)

    monkeypatch.setattr(
        "core.llm.wire.chat_completions._ensure_reasoning_roundtrip_messages",
        drop_semantic_backstop,
    )

    payload = client._build_payload(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "agent.py"}}],
            ),
            ToolMessage(content="file content", tool_call_id="call_1", name="read_file"),
        ]
    )

    assert str(payload["messages"][0].get("reasoning_content") or "").strip()


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


def test_speaker_payload_keeps_profile_default_without_cap_injection():
    """Regression: the fenced speaker request must not lose output budget.

    The removed per-call token-cap channel (fence-derived ContextVar) used to
    clamp the speaker's ``max_tokens`` below the profile default.  Speakers
    must generate exactly as before: without an explicit
    ``llmMaxOutputTokensOverride`` metadata entry, the payload keeps the
    profile default even inside the scopes a fenced speaker turn binds.
    """

    from core.llm import client as llm_client_module
    from core.llm.client import (
        MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY,
        llm_status_context,
        model_invocation_receipt_context_scope,
    )

    # The derived cap channel itself is gone; only the pre-existing explicit
    # metadata override remains.
    assert not hasattr(llm_client_module, "per_call_output_token_cap_scope")
    assert not hasattr(llm_client_module, "_PER_CALL_OUTPUT_TOKEN_CAP")

    config = _relay_autodl_glm_config()
    client = LLMClient(config=config, backend=lambda payload: payload)
    messages = [{"role": "user", "content": "讲者输入"}]

    with model_invocation_receipt_context_scope(None), llm_status_context(
        session_id="session-speaker",
        turn_id="chat-room:round-1:speaker-1",
    ):
        payload = client._build_payload(messages)
        assert payload["max_tokens"] == 32768

        # The pre-existing explicit metadata clamp keeps working.
        clamped = client._build_payload(
            messages, metadata={MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 4096}
        )
    assert clamped["max_tokens"] == 4096


# ---------------------------------------------------------------------------
# extra_headers 身份占位符：{session_id} / {agent_id} 在请求构建时解析
# ---------------------------------------------------------------------------


def _header_template_config(extra_headers):
    return make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-test",
            "llm.providers.default.extra_headers": extra_headers,
        }
    )


def test_extra_headers_without_placeholders_pass_through_unchanged():
    # 未闭合/非占位符形式的花括号不属于模板语法，按存量值原样透传。
    headers = {"X-Static": "keep-me", "X-Brace-Literal": "not-a-{token-pattern"}

    assert resolve_extra_header_identity_templates(headers) == headers


def test_extra_header_templates_resolve_session_and_agent_identity():
    headers = {
        "x-opencode-session": "{session_id}",
        "x-opencode-agent": "agent:{agent_id}",
        "X-Static": "keep-me",
    }

    with invocation_header_identity_scope(session_id="sess-42", agent_id="reviewer"):
        resolved = resolve_extra_header_identity_templates(headers)
        again = resolve_extra_header_identity_templates(headers)

    assert resolved == {
        "x-opencode-session": "sess-42",
        "x-opencode-agent": "agent:reviewer",
        "X-Static": "keep-me",
    }
    # 同一会话多次调用必须得到同一值（路由/缓存亲和的前提）。
    assert again == resolved


def test_extra_header_templates_dropped_without_session_identity():
    headers = {"x-opencode-session": "{session_id}", "X-Static": "keep-me"}

    # 无身份上下文（如 compression 等辅助调用）：含占位符 header 整体丢弃，
    # 静态 header 保持原样，绝不外发字面量 `{session_id}`。
    assert resolve_extra_header_identity_templates(headers) == {"X-Static": "keep-me"}


def test_extra_header_templates_dropped_for_unknown_placeholder():
    headers = {"x-custom": "{session_id}/{conversation_id}"}

    with invocation_header_identity_scope(session_id="sess-42", agent_id="reviewer"):
        assert resolve_extra_header_identity_templates(headers) == {}


def test_extra_header_template_dropped_when_identity_value_is_not_header_safe():
    headers = {"x-opencode-session": "{session_id}"}

    with invocation_header_identity_scope(session_id="bad\nsession"):
        assert resolve_extra_header_identity_templates(headers) == {}


def test_llm_client_resolves_header_templates_at_request_build_time():
    config = _header_template_config(
        {
            "x-opencode-session": "{session_id}",
            "X-Static": "keep-me",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)
    messages = [{"role": "user", "content": "ping"}]

    with invocation_header_identity_scope(session_id="sess-e2e"):
        payload = client._build_payload(messages)

    assert payload["extra_headers"] == {
        "x-opencode-session": "sess-e2e",
        "X-Static": "keep-me",
    }


def test_llm_client_drops_template_headers_without_identity_context():
    config = _header_template_config({"x-opencode-session": "{session_id}"})
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert "extra_headers" not in payload


class _HeaderIdentityCaptureClient:
    """Fake LLM client that records header-template resolution per wrapper."""

    def __init__(self):
        self.captured = []

    def _capture(self):
        self.captured.append(
            resolve_extra_header_identity_templates({"x-opencode-session": "{session_id}"})
        )

    def invoke(self, messages, **kwargs):
        self._capture()
        return {"id": "compat"}

    def invoke_outcome(self, messages, **kwargs):
        self._capture()
        return TurnOutcome.final_answer(identity=_capture_identity(), text="ok")

    def stream(self, messages, **kwargs):
        self._capture()
        yield "chunk"

    def stream_events(self, messages, **kwargs):
        self._capture()
        outcome = TurnOutcome.final_answer(identity=_capture_identity(), text="ok")
        yield "chunk"
        return outcome


def _capture_identity():
    return CanonicalItemIdentity(
        session_id="sess-wrapper",
        turn_id="turn-wrapper",
        invocation_id="invocation-wrapper",
        iteration=0,
        item_id="item-wrapper",
    )


@pytest.mark.parametrize("wrapper", ["invoke", "invoke_outcome", "stream", "stream_events"])
def test_invocation_wrappers_bind_session_identity_for_header_templates(wrapper):
    from core.llm.invocation import LLMInvocationContext

    fake = _HeaderIdentityCaptureClient()
    context = LLMInvocationContext(
        surface="test",
        session_id="sess-wrapper",
        agent_id="agent-wrapper",
    )
    runner = {
        "invoke": lambda: invoke_llm(fake, [], context=context),
        "invoke_outcome": lambda: invoke_llm_outcome(fake, [], context=context),
        "stream": lambda: list(stream_llm(fake, [], context=context)),
        "stream_events": lambda: run_streaming_llm_outcome(
            fake, [], context=context, on_event=lambda event: None
        ),
    }[wrapper]

    runner()

    assert fake.captured == [{"x-opencode-session": "sess-wrapper"}]


def test_extra_header_template_tolerates_whitespace_around_placeholder():
    # config 层（llm_security）对占位符提取后 strip 归一，运行时必须同语义：
    # 花括号内的空白不得导致字面量外发或静默差异。
    headers = {"x-a": "{session_id }", "x-b": "{ session_id}", "x-c": "agent:{ agent_id }"}

    with invocation_header_identity_scope(session_id="sess-ws", agent_id="ag-ws"):
        resolved = resolve_extra_header_identity_templates(headers)

    assert resolved == {"x-a": "sess-ws", "x-b": "sess-ws", "x-c": "agent:ag-ws"}


@pytest.mark.parametrize("value", ["{{session_id}}", "{session_id}}", "{{session_id}"])
def test_extra_header_template_dropped_for_residual_braces_after_resolution(value):
    # 解析完成后仍残留花括号的值绝不外发（含字面量 {session_id} 形态）。
    with invocation_header_identity_scope(session_id="sess-brace"):
        resolved = resolve_extra_header_identity_templates({"x-opencode-session": value})

    assert resolved == {}


_TWO_LAYER_TEMPLATE_CASES = [
    # (value, config_accepts, runtime_resolved_or_None)
    ("{session_id }", True, "sess-2l"),
    ("{ session_id}", True, "sess-2l"),
    ("{{session_id}}", True, None),
    ("{session_id}}", True, None),
    ("{{session_id}", True, None),
    ("{sessionId}", False, None),
]


@pytest.mark.parametrize(
    ("value", "config_accepts", "runtime_resolved"),
    _TWO_LAYER_TEMPLATE_CASES,
)
def test_header_template_two_layer_contract(value, config_accepts, runtime_resolved):
    # config 层（llm_security）与运行时（payload_builder）必须对同一值给出
    # 对应行为：要么都拒，要么 config 收 + 运行时正确解析/fail-safe 丢弃；
    # 绝不允许 config 收下后运行时把字面量模板原样外发。
    provider = {
        "service_class": "self_hosted",
        "vendor": "custom",
        "base_url": "https://models.example/v1",
        "credential_ref": "env:VIBELUTION_LLM_PROVIDER_LAB_API_KEY",
        "extra_headers": {"x-opencode-session": value},
    }
    if config_accepts:
        validate_llm_provider_target(provider)
    else:
        with pytest.raises(ValueError):
            validate_llm_provider_target(provider)

    with invocation_header_identity_scope(session_id="sess-2l"):
        resolved_headers = resolve_extra_header_identity_templates({"x-opencode-session": value})

    if runtime_resolved is None:
        assert resolved_headers == {}
    else:
        assert resolved_headers == {"x-opencode-session": runtime_resolved}
    assert resolved_headers.get("x-opencode-session") != value


def test_header_template_drop_logs_once_without_header_value(caplog):
    from core.llm import payload_builder as payload_builder_module

    payload_builder_module._HEADER_TEMPLATE_DROP_LOGGED.clear()
    headers = {"x-opencode-session": "{session_id}", "x-static": "keep"}

    with caplog.at_level(logging.WARNING, logger="core.llm.payload_builder"):
        with invocation_header_identity_scope(session_id=""):
            first = resolve_extra_header_identity_templates(headers)
            second = resolve_extra_header_identity_templates(headers)

    assert first == {"x-static": "keep"}
    assert second == {"x-static": "keep"}
    drop_records = [
        record
        for record in caplog.records
        if "identity template header dropped" in record.getMessage()
    ]
    assert len(drop_records) == 1
    message = drop_records[0].getMessage()
    assert "x-opencode-session" in message
    assert "identity_missing" in message
    # 绝不记录 header 值（extra_headers 可能包含敏感头内容）。
    assert "{session_id}" not in message
