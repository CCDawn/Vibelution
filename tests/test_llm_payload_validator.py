from config import Settings
from core.llm.payload_validator import validate_payload_against_protocol
from core.llm.protocol_resolver import resolve_model_protocol


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


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
