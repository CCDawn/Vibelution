from config import Settings
from core.llm.protocol_resolver import resolve_model_protocol
from core.llm.protocols import ModelProtocol


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


def test_explicit_profile_protocol_wins():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-plus",
            "llm.profiles.primary.protocol": "qwen_openai_compat",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.QWEN_OPENAI_COMPAT
    assert route.source == "explicit_model"
    assert route.log_summary()["selectedProtocol"] == "qwen_openai_compat"


def test_provider_api_selects_responses_protocol():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api": "openai-responses",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.RELAY_RESPONSES
    assert route.source == "provider_api"


def test_openai_compatible_tool_chat_contract_allows_tools():
    config = make_config(
        **{
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.compat_mode": "openai",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.OPENAI_CHAT_TOOLS
    assert route.source == "profile_contract"
    assert route.policy.allow_tools is True
    assert "model_protocol.missing_explicit_protocol" in route.warnings


def test_llamacpp_qwen_thinking_inferred_from_local_model():
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
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.LLAMACPP_QWEN_THINKING
    assert route.source == "inferred"
    assert route.compat.allow_assistant_prefill is False
    assert route.compat.thinking_format == "qwen"


def test_deepseek_reasoning_contract_selects_reasoning_protocol():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4",
            "llm.profiles.primary.contract": "reasoning_chat",
            "llm.profiles.primary.reasoning_state_field": "reasoning_content",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.DEEPSEEK_REASONING
    assert route.compat.reasoning_roundtrip is True


def test_profile_contract_wins_over_model_name_inference():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-local-name-but-basic-contract",
            "llm.profiles.primary.contract": "basic_chat",
            "llm.profiles.primary.thinking_type": "adaptive",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.BASIC_CHAT_NO_TOOLS
    assert route.source == "profile_contract"
    assert "model_protocol.missing_explicit_protocol" in route.warnings


def test_inferred_local_qwen_route_reports_diagnostic_warnings():
    config = make_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://127.0.0.1:8081/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-local.gguf",
            "llm.profiles.primary.thinking_type": "adaptive",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.LLAMACPP_QWEN_THINKING
    assert route.source == "inferred"
    assert "model_protocol.missing_explicit_protocol" in route.warnings
    assert "model_protocol.inferred" in route.warnings
    assert "model_protocol.local_advanced_route_warning" in route.warnings
