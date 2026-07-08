from core.llm.payload_validator import validate_payload_against_protocol
from core.llm.protocol_resolver import resolve_model_protocol
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


def qwen_route():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://192.168.20.30:8081/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "HiModel_xh2_qwen3.5_9b.gguf",
            "llm.profiles.primary.thinking_type": "adaptive",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    return resolve_model_protocol(profile, provider)


def responses_route():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api": "responses",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "responses",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    return resolve_model_protocol(profile, provider)


def test_responses_transport_accepts_paired_function_items():
    payload = {
        "model": "openai/gpt-5.5",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "查资料"}]},
            {"type": "function_call", "call_id": "call_search", "name": "web_search_tool", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_search", "output": "找到 1 条"},
            {"role": "user", "content": [{"type": "input_text", "text": "继续"}]},
        ],
    }

    result = validate_payload_against_protocol(payload, responses_route())

    assert result.ok is True
    assert result.details["payloadValidationResult"] == "passed"
    assert result.details["responsesItemTypeTail"] == ["user", "function_call", "function_call_output", "user"]


def test_responses_transport_rejects_missing_function_output():
    payload = {
        "model": "openai/gpt-5.5",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "查资料"}]},
            {"type": "function_call", "call_id": "call_search", "name": "web_search_tool", "arguments": "{}"},
            {"role": "user", "content": [{"type": "input_text", "text": "继续"}]},
        ],
    }

    result = validate_payload_against_protocol(payload, responses_route())

    assert result.ok is False
    assert result.error_type == "missing_function_call_output"
    assert result.details["pendingCallIds"] == ["call_search"]


def test_responses_transport_rejects_orphan_function_output():
    payload = {
        "model": "openai/gpt-5.5",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "查资料"}]},
            {"type": "function_call_output", "call_id": "call_search", "output": "找到 1 条"},
        ],
    }

    result = validate_payload_against_protocol(payload, responses_route())

    assert result.ok is False
    assert result.error_type == "orphan_function_call_output"
    assert result.details["callId"] == "call_search"


def test_qwen_thinking_rejects_assistant_prefill():
    route = qwen_route()
    payload = {
        "model": "openai/HiModel_xh2_qwen3.5_9b.gguf",
        "messages": [
            {"role": "user", "content": "今天是星期几"},
            {"role": "assistant", "content": "今天是"},
        ],
        "thinking": {"type": "adaptive"},
    }

    result = validate_payload_against_protocol(payload, route)

    assert result.ok is False
    assert result.error_type in {"assistant_prefill_not_allowed", "assistant_final_message_not_allowed"}
    assert result.details["payloadValidationResult"] == "blocked_before_provider"


def test_qwen_thinking_allows_user_final_message():
    route = qwen_route()
    payload = {
        "model": "openai/HiModel_xh2_qwen3.5_9b.gguf",
        "messages": [{"role": "user", "content": "今天是星期几"}],
        "thinking": {"type": "adaptive"},
    }

    result = validate_payload_against_protocol(payload, route)

    assert result.ok is True
    assert result.details["payloadValidationResult"] == "passed"


def test_qwen_thinking_rejects_reasoning_roundtrip():
    route = qwen_route()
    payload = {
        "model": "openai/HiModel_xh2_qwen3.5_9b.gguf",
        "messages": [
            {"role": "assistant", "content": "旧回复", "reasoning_content": "hidden"},
            {"role": "user", "content": "继续"},
        ],
        "thinking": {"type": "adaptive"},
    }

    result = validate_payload_against_protocol(payload, route)

    assert result.ok is False
    assert result.error_type == "reasoning_roundtrip_not_allowed"
