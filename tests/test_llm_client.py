from langchain_core.messages import AIMessage
import pytest
from types import SimpleNamespace
import json

from config import Settings
from core.orchestration.response_processor import ResponseProcessor
from core.llm.client import LLMClient
from core.llm.errors import classify_exception
from core.llm.types import LLMError
from core.llm.recovery import plan_recovery
from core.llm.routing import attach_recovery_fallback, select_recovery_profile


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


def test_litellm_payload_prefixes_minimax_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_minimax_payload_converts_runtime_system_messages_after_first_to_user():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "## 外部任务输入\n开始自主进化"},
        ]
    )

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_litellm_payload_prefixes_openai_compatible_local_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/qwen-32b-awq"


def test_litellm_payload_prefixes_relay_openai_compatible_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/gpt-5.5"


def test_openai_compatible_payload_converts_runtime_system_messages_after_first_to_user():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "## 运行时提示\n请输出 state"},
        ]
    )

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_openai_gpt5_payload_sanitizes_temperature_and_tool_choice():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.temperature": 0.7,
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
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

    assert payload["model"] == "openai/gpt-5.5"
    assert payload["temperature"] == 1.0
    assert "tools" in payload
    assert "tool_choice" not in payload


def test_responses_transport_routes_openai_compatible_model_through_responses_bridge():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/responses/gpt-5.5"
    assert payload["messages"][0]["content"] == "ping"


def test_responses_transport_preserves_existing_provider_prefix():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "openai/gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/responses/gpt-5.5"


def test_openai_compatible_payload_prefixes_model_names_that_contain_slash():
    config = make_config(
        **{
            "llm.providers.default.kind": "siliconflow",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.siliconflow.cn/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-ai/DeepSeek-V3",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/deepseek-ai/DeepSeek-V3"


def test_payload_does_not_double_prefix_litellm_qualified_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "minimax/MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_deepseek_payload_preserves_reasoning_content_for_assistant_history():
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

    assert payload["messages"][0]["role"] == "assistant"
    assert payload["messages"][0]["reasoning_content"] == "先读文件再决定"
    assert payload["messages"][0]["tool_calls"][0]["id"] == "call_1"


def test_deepseek_payload_omits_explicit_tool_choice_in_thinking_mode():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-pro",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
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

    assert "tools" in payload
    assert "tool_choice" not in payload


def test_invoke_preserves_reasoning_content_in_ai_message():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "已完成",
                        "reasoning_content": "先分析再作答",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "已完成"
    assert message.additional_kwargs["reasoning_content"] == "先分析再作答"


def test_invoke_extracts_reasoning_alias_and_strips_think_tags():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<think>先看日志</think>结论",
                        "reasoning": "先看日志",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "结论"
    assert message.additional_kwargs["reasoning_content"] == "先看日志"


def test_invoke_extracts_think_tags_when_provider_has_no_reasoning_field():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<thinking>先判断工具是否可用</thinking>\n可以继续。",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "\n可以继续。"
    assert message.additional_kwargs["reasoning_content"] == "先判断工具是否可用"


def test_invoke_records_cached_input_token_observation(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 8,
                "total_tokens": 108,
                "prompt_tokens_details": {"cached_tokens": 64},
            },
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "ping"}])

    assert message.response_metadata["usage_observation"]["cached_input_tokens"] == 64
    assert message.response_metadata["usage_observation"]["cache_hit_rate"] == pytest.approx(0.64)
    success_event = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")
    assert success_event[1]["fields"]["cachedInputTokens"] == 64
    assert success_event[1]["fields"]["cacheHitRate"] == pytest.approx(0.64)


def test_invoke_records_safe_payload_shape_without_prompt_text(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "anthropic",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.anthropic.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "claude-3-5-sonnet-20241022",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )
    recorded = []

    def backend(_payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    client.invoke(
        [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "stable-secret-prefix", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "dynamic-current-goal"},
                ],
            },
            {"role": "user", "content": "user-secret-message"},
        ]
    )

    fields = next(item for item in recorded if item[0][1] == "llm.invoke.succeeded")[1]["fields"]
    shape = fields["payloadShape"]
    assert shape["firstSystemBlockCount"] == 2
    assert shape["firstSystemCacheControlBlockCount"] == 1
    assert shape["firstSystemCacheableTextChars"] == len("stable-secret-prefix")
    assert shape["firstSystemDynamicTextChars"] == len("dynamic-current-goal")
    serialized = json.dumps(fields, ensure_ascii=False)
    assert "stable-secret-prefix" not in serialized
    assert "dynamic-current-goal" not in serialized
    assert "user-secret-message" not in serialized


def test_llm_error_exposes_legacy_error_type_alias():
    error = LLMError("provider_protocol_error", "bad request", retryable=False)

    assert error.error_type == "provider_protocol_error"


def test_invoke_failure_records_category_without_masking_provider_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        raise Exception('400: One of "input" or "previous_response_id" must be provided.')

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "user", "content": "ping"}])

    assert raised.value.category == "provider_protocol_error"
    assert 'One of "input"' in str(raised.value)
    assert recorded[-1][1]["message"] == "LLM invoke failed: provider_protocol_error"
    assert recorded[-1][1]["fields"]["errorType"] == "provider_protocol_error"
    assert 'One of "input"' in recorded[-1][1]["fields"]["error"]


def test_invoke_retries_retryable_timeout_up_to_profile_limit(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    attempts = {"count": 0}

    def backend(_payload):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("provider timeout")
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "ping"}])

    assert message.content == "ok"
    assert attempts["count"] == 3
    retry_events = [item for item in recorded if item[0][1] == "llm.invoke.failed.retrying"]
    assert [event[1]["fields"]["attempt"] for event in retry_events] == [1, 2]
    assert [event[1]["fields"]["nextAttempt"] for event in retry_events] == [2, 3]


def test_stream_retries_retryable_failure_before_first_event(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    attempts = {"count": 0}

    def failing_before_first_chunk():
        raise TimeoutError("stream timeout")
        yield {"choices": [{"delta": {"content": "unreachable"}}]}

    def backend(_payload):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return failing_before_first_chunk()
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert attempts["count"] == 3
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "ok"
    retry_events = [item for item in recorded if item[0][1] == "llm.stream.failed.retrying"]
    assert [event[1]["fields"]["attempt"] for event in retry_events] == [1, 2]
    assert [item[0] for item in statuses] == ["retrying", "retrying"]
    assert [item[1]["attempt"] for item in statuses] == [1, 2]


def test_stream_falls_back_to_non_streaming_after_retryable_pre_chunk_failures(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 2,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
        }
    )
    recorded = []
    statuses = []
    payloads = []

    def failing_before_first_chunk():
        raise Exception(
            "litellm.MidStreamFallbackError: peer closed connection without sending complete message body "
            "(incomplete chunked read)"
        )
        yield {"choices": [{"delta": {"content": "unreachable"}}]}

    def backend(payload):
        payloads.append(dict(payload))
        if payload.get("stream"):
            return failing_before_first_chunk()
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "fallback ok"}}
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr("core.llm.client._publish_llm_status_event", lambda status, **fields: statuses.append((status, fields)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [payload["stream"] for payload in payloads] == [True, True, False]
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "fallback ok"
    event_codes = [item[0][1] for item in recorded]
    assert "llm.stream.fallback.invoke_started" in event_codes
    assert "llm.stream.fallback.invoke_succeeded" in event_codes
    assert [item[0] for item in statuses] == ["retrying", "failed", "fallback_invoke_started", "fallback_invoke_succeeded"]


def test_stream_records_success_event_with_safe_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "read_file", "arguments": "{}"},
                                    }
                                ]
                            }
                        }
                    ]
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}], tools=[{"name": "read_file"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    success_events = [item for item in recorded if item[0][1] == "llm.stream.succeeded"]
    assert success_events
    fields = success_events[-1][1]["fields"]
    assert fields["messageCount"] == 1
    assert fields["toolCount"] == 1
    assert fields["chunkCount"] == 3
    assert fields["textDeltaCount"] == 1
    assert fields["toolCallCount"] == 1
    assert "latencyMs" in fields


def test_stream_records_usage_and_cache_hit_rate(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        return iter(
            [
                {"choices": [{"delta": {"content": "ok"}}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                        "prompt_tokens_details": {"cached_tokens": 64},
                    },
                },
            ]
        )

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert payloads[0]["stream_options"] == {"include_usage": True}
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 100
    assert events[-1].usage.cached_input_tokens == 64
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    fields = success_event[1]["fields"]
    assert fields["inputTokens"] == 100
    assert fields["outputTokens"] == 20
    assert fields["cachedInputTokens"] == 64
    assert fields["cacheHitRate"] == pytest.approx(0.64)
    assert fields["usageObserved"] is True
    assert fields["payloadShape"]["messageTextCharsByRole"] == {"user": len("ping")}
    assert fields["payloadShape"]["toolSchemaHash"] == ""


def test_stream_retries_without_usage_options_when_provider_rejects_them(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []
    payloads = []

    def backend(payload):
        payloads.append(dict(payload))
        if payload.get("stream_options"):
            raise Exception("400 bad_request unknown parameter: stream_options.include_usage")
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [payload.get("stream_options") for payload in payloads] == [
        {"include_usage": True},
        None,
    ]
    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].text == "ok"
    event_codes = [item[0][1] for item in recorded]
    assert "llm.stream.usage_options_downgraded" in event_codes
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    assert success_event[1]["fields"]["usageObserved"] is False


def test_stream_final_chunk_exposes_usage_observation_for_ui():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "ok"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 10,
                "total_tokens": 90,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        },
    ]

    client = LLMClient(config=config, backend=lambda _payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "ping"}]))

    assert [chunk.content for chunk in streamed] == ["ok", ""]
    usage_observation = streamed[-1].response_metadata["usage_observation"]
    assert usage_observation["input_tokens"] == 80
    assert usage_observation["cached_input_tokens"] == 40
    assert usage_observation["cache_hit_rate"] == pytest.approx(0.5)


def test_stream_records_started_event_before_first_provider_chunk(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        def chunks():
            event_codes = [item[0][1] for item in recorded]
            assert "llm.stream.started" in event_codes
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return chunks()

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    started_events = [item for item in recorded if item[0][1] == "llm.stream.started"]
    assert len(started_events) == 1
    fields = started_events[0][1]["fields"]
    assert fields["messageCount"] == 1
    assert fields["toolCount"] == 0
    assert fields["runtimeRoute"] == "openai/qwen-32b-awq"
    assert fields["transport"] == "chat_completions"
    assert fields["baseUrlHost"] == "localhost"
    assert fields["stream"] is True
    assert fields["maxTokens"] == config.llm.get_profile("primary").max_output_tokens


def test_stream_records_safe_message_role_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return iter([{"choices": [{"delta": {"content": "ok"}}]}])

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)
    events = list(
        client.stream_events(
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "## 对话用户输入\nping"},
            ]
        )
    )

    assert [event.type for event in events] == ["text_delta", "done"]
    started = next(item for item in recorded if item[0][1] == "llm.stream.started")
    succeeded = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    for event in (started, succeeded):
        fields = event[1]["fields"]
        assert fields["messageRoles"] == ["system", "user"]
        assert fields["messageRoleCounts"] == {"system": 1, "user": 1}


def test_stream_does_not_replay_after_partial_output(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    attempts = {"count": 0}

    def partial_then_failure():
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise TimeoutError("stream timeout")

    def backend(_payload):
        attempts["count"] += 1
        return partial_then_failure()

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "timeout"
    assert attempts["count"] == 1


def test_invoke_does_not_retry_non_retryable_protocol_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.retry_policy.max_attempts": 5,
        }
    )
    attempts = {"count": 0}

    def backend(_payload):
        attempts["count"] += 1
        raise Exception("400 bad_request invalid params")

    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "user", "content": "ping"}])

    assert raised.value.category == "provider_protocol_error"
    assert attempts["count"] == 1


def test_stream_failure_records_category_without_masking_provider_error(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        raise Exception('400: One of "input" or "previous_response_id" must be provided.')

    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=backend)

    with pytest.raises(LLMError) as raised:
        list(client.stream_events([{"role": "user", "content": "ping"}]))

    assert raised.value.category == "provider_protocol_error"
    assert 'One of "input"' in str(raised.value)
    assert recorded[-1][1]["message"] == "LLM stream failed before iterator: provider_protocol_error"
    assert recorded[-1][1]["fields"]["errorType"] == "provider_protocol_error"
    assert recorded[-1][1]["fields"]["messageRoles"] == ["user"]
    assert 'One of "input"' in recorded[-1][1]["fields"]["error"]


def test_native_anthropic_payload_preserves_structured_content_blocks_by_default():
    config = make_config(
        **{
            "llm.providers.default.kind": "anthropic",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.anthropic.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "claude-3-5-sonnet-20241022",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )

    content = [{"type": "text", "text": "cached", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "anthropic/claude-3-5-sonnet-20241022"
    assert payload["messages"][0]["content"] == content


def test_prompt_cache_disabled_strips_cache_control_and_allows_request():
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

    content = [{"type": "text", "text": "plain", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["messages"][0]["content"] == [{"type": "text", "text": "plain"}]


def test_prompt_cache_unsupported_rejects_cache_control_without_backend_call():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.primary.prompt_cache.mode": "unsupported",
        }
    )

    content = [{"type": "text", "text": "plain", "cache_control": {"type": "ephemeral"}}]
    backend_called = False

    def backend(_payload):
        nonlocal backend_called
        backend_called = True
        return {"choices": [{"message": {"role": "assistant", "content": "should-not-run"}}]}

    client = LLMClient(config=config, backend=backend)
    with pytest.raises(LLMError) as raised:
        client.invoke([{"role": "system", "content": content}])

    assert backend_called is False
    assert raised.value.category == "prompt_cache_unsupported"
    assert raised.value.retryable is False
    assert raised.value.details["provider_kind"] == "local"
    assert raised.value.details["prompt_cache_mode"] == "unsupported"


def test_openai_compatible_automatic_prompt_cache_strips_cache_control_and_keeps_payload_valid():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
            "llm.profiles.primary.prompt_cache.key": "vibelution-primary",
            "llm.profiles.primary.prompt_cache.retention": "24h",
        }
    )

    content = [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "openai/responses/gpt-5.5"
    assert payload["prompt_cache_key"] == "vibelution-primary"
    assert payload["prompt_cache_retention"] == "24h"
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "stable"},
        {"type": "text", "text": "dynamic"},
    ]


def test_openai_compatible_payload_preserves_image_blocks_for_chat_completions():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )

    content = [
        {"type": "text", "text": "看看这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": content}])

    assert payload["messages"][0]["content"] == content


def test_responses_transport_converts_image_blocks_to_input_image():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://ai-pixel.online",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看这张图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    )

    assert payload["model"] == "openai/responses/gpt-5.5"
    assert payload["messages"][0]["content"] == [
        {"type": "input_text", "text": "看看这张图"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    ]


def test_openai_codex_model_uses_known_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.3-codex",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 400000


def test_openai_gpt_5_5_uses_known_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 1050000


def test_tool_schema_is_sanitized_before_payload():
    class ArgsSchema:
        @staticmethod
        def model_json_schema():
            return {
                "title": "Args",
                "type": "object",
                "$defs": {"Ignored": {"type": "string"}},
                "properties": {
                    "file path": {
                        "title": "Path",
                        "type": "string",
                        "description": "target",
                        "examples": ["a.py"],
                    }
                },
                "required": ["file path"],
            }

    class Tool:
        name = "read file!*"
        description = "x" * 2000
        args_schema = ArgsSchema

    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "read"}], tools=[Tool()])
    function = payload["tools"][0]["function"]

    assert function["name"] == "read_file"
    assert len(function["description"]) == 1024
    assert "title" not in function["parameters"]
    assert "$defs" not in function["parameters"]
    assert "examples" not in function["parameters"]["properties"]["file path"]


def test_stream_merges_tool_call_argument_deltas():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[-1].tool_calls[0]["id"] == "call_1"
    assert streamed[-1].tool_calls[0]["name"] == "read_file"
    assert streamed[-1].tool_calls[0]["args"] == {"path": "agent.py"}
    assert all(not chunk.tool_calls for chunk in streamed[:-1])


def test_stream_chunks_merge_without_duplicate_tool_calls():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "read"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_1"
    assert full_chunk.tool_calls[0]["name"] == "read_file"


def test_stream_events_expose_tool_calls_only_after_finalization():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "读"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    assert events[0].text == "读"
    assert events[1].tool_calls[0].id == "call_1"
    assert events[1].tool_calls[0].arguments == {"path": "agent.py"}


def test_stream_exposes_reasoning_deltas_without_polluting_content():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "先看"}}]},
        {"choices": [{"delta": {"reasoning_content": "日志"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[0].content == ""
    assert streamed[0].additional_kwargs["reasoning_content_delta"] == "先看"
    assert streamed[1].additional_kwargs["reasoning_content_delta"] == "日志"
    assert streamed[2].content == "结论"


def test_stream_exposes_reasoning_aliases_and_strips_think_tags_from_content():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning": "先看"}}]},
        {"choices": [{"delta": {"thinking": "日志"}}]},
        {"choices": [{"delta": {"content": "<think>不要进回答</think>结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[0].additional_kwargs["reasoning_content_delta"] == "先看"
    assert streamed[1].additional_kwargs["reasoning_content_delta"] == "日志"
    assert streamed[2].additional_kwargs["reasoning_content_delta"] == "不要进回答"
    assert streamed[3].content == "结论"


def test_stream_splits_reasoning_when_think_tags_span_chunks():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "<think>"}}]},
        {"choices": [{"delta": {"content": "先看"}}]},
        {"choices": [{"delta": {"content": "日志"}}]},
        {"choices": [{"delta": {"content": "</think>"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert [chunk.additional_kwargs.get("reasoning_content_delta") for chunk in streamed[:2]] == ["先看", "日志"]
    assert streamed[2].content == "结论"


def test_stream_events_record_reasoning_source_summary(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning": "先看"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]
    recorded = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["reasoning_delta", "text_delta", "done"]
    success_event = next(item for item in recorded if item[0][1] == "llm.stream.succeeded")
    assert success_event[1]["fields"]["reasoningDeltaCount"] == 1
    assert success_event[1]["fields"]["reasoningChars"] == 2
    assert success_event[1]["fields"]["reasoningSources"] == ["reasoning"]


def test_stream_events_drop_incomplete_tool_calls_with_empty_name():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_empty",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    }
                }
            ]
        }
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["done"]
    assert list(client.stream([{"role": "user", "content": "read"}])) == []


def test_transcript_replay_duplicate_tool_call_id_regression():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_function_8euvktt1r7y4_1",
                                "function": {"name": "get_git_status_summary_tool", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call_function_8euvktt1r7y4_2",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "开始自主进化"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_function_8euvktt1r7y4_1"
    assert full_chunk.tool_calls[0]["name"] == "get_git_status_summary_tool"


def test_bad_request_wrapped_as_connection_error_is_protocol_error():
    error = Exception("APIConnectionError: MinimaxException - bad_request_error invalid params, chat content is empty (2013)")

    normalized = classify_exception(error)

    assert normalized.category == "empty_content_error"
    assert normalized.retryable is False


def test_duplicate_tool_call_error_classified_as_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    normalized = classify_exception(error)

    assert normalized.category == "tool_protocol_error"
    assert normalized.retryable is False


def test_recovery_policy_disables_tools_for_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "tool_protocol_error"
    assert decision.action == "disable_tools_and_retry_without_streaming"
    assert decision.disable_tools is True
    assert decision.disable_streaming is True
    assert decision.stop_current_turn is False


def test_recovery_policy_uses_longer_backoff_for_rate_limit():
    error = Exception("429 rate limit exceeded")

    decision = plan_recovery(error, attempt=2, max_attempts=5)

    assert decision.category == "rate_limit"
    assert decision.action == "retry_after_backoff"
    assert decision.wait_seconds == 20
    assert decision.stop_current_turn is False


def test_recovery_policy_requests_context_compression():
    error = Exception("maximum context length exceeded")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "context_length_error"
    assert decision.action == "compress_context"
    assert decision.request_context_compression is True
    assert decision.stop_current_turn is False


def test_recovery_routing_prefers_no_tool_non_streaming_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.plain.kind": "local",
            "llm.providers.plain.requires_api_key": False,
            "llm.providers.plain.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_plain.provider_id": "plain",
            "llm.profiles.fallback_plain.model": "qwen-32b-awq",
            "llm.profiles.fallback_plain.streaming": False,
            "llm.profiles.fallback_plain.tool_calling_mode": "disabled",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="disable_tools_and_retry_without_streaming",
    )

    assert fallback == "fallback_plain"


def test_recovery_decision_attaches_fallback_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.streaming": False,
            "llm.profiles.fallback_backup.tool_calling_mode": "disabled",
        }
    )
    decision = plan_recovery(
        Exception("invalid params, duplicate tool_call id: call_1"),
        attempt=1,
        max_attempts=5,
    )

    enriched = attach_recovery_fallback(
        decision,
        config=config,
        current_profile_id="primary",
    )

    assert enriched.fallback_profile_id == "fallback_backup"


def test_provider_retry_does_not_use_compression_profile_as_fallback():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.remote_main.kind": "relay",
            "llm.providers.remote_main.api_key": "test-key",
            "llm.providers.remote_main.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.compression.provider_id": "remote_main",
            "llm.profiles.compression.model": "gpt-5.5",
            "llm.profiles.compression.streaming": False,
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="retry_with_backoff",
    )

    assert fallback is None


def test_usage_observation_accepts_provider_usage_objects():
    class UsageObject:
        prompt_tokens = 100
        completion_tokens = 20
        total_tokens = 120
        prompt_tokens_details = {"cached_tokens": 32}

    response = SimpleNamespace(usage=UsageObject())
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )
    client = LLMClient(config=config, backend=lambda _payload: response)

    usage = client._usage_from_response(response, latency_ms=7)

    assert usage.input_tokens == 100
    assert usage.output_tokens == 20
    assert usage.cached_input_tokens == 32
    assert usage.provider_raw_usage["prompt_tokens_details"] == {"cached_tokens": 32}


def test_context_recovery_uses_larger_context_profile_only():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.context_window": 32768,
            "llm.providers.large.kind": "local",
            "llm.providers.large.requires_api_key": False,
            "llm.providers.large.context_window": 131072,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.long_context.provider_id": "large",
            "llm.profiles.long_context.model": "qwen-plus",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="compress_context",
    )

    current_window = config.llm.get_provider(config.llm.get_profile("primary").provider_id).context_window
    selected_window = config.llm.get_provider(config.llm.get_profile(fallback).provider_id).context_window
    assert fallback is not None
    assert selected_window > current_window
