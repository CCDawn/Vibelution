import pytest

from core.llm.protocol_resolver import resolve_model_protocol
from core.llm.protocols import ModelProtocol, WireProtocol
from tests.helpers.isolated_config import isolated_settings_config

def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


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
            "llm.providers.default.base_url": "https://api.xiaomimimo.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.XIAOMI_MIMO_MULTIMODAL_OPENAI_COMPAT
    assert route.source == "profile_contract"
    assert route.policy.allow_tools is True
    assert "model_protocol.missing_explicit_protocol" in route.warnings


def test_xiaomi_token_plan_uses_dedicated_mimo_protocol():
    config = make_config(
        **{
            "llm.providers.default.kind": "xiaomi",
            "llm.providers.default.compat_mode": "openai",
            "llm.providers.default.base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "mimo-v2.5-pro",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.XIAOMI_MIMO_TOKEN_PLAN_OPENAI_COMPAT
    assert route.policy.allow_tools is True


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


def test_reasoning_chat_contract_does_not_force_non_deepseek_to_deepseek():
    config = make_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.compat_mode": "openai",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.contract": "reasoning_chat",
            "llm.profiles.primary.thinking_type": "adaptive",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.QWEN_THINKING_NO_PREFILL
    assert route.protocol != ModelProtocol.DEEPSEEK_REASONING


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


def test_opencode_zen_effective_model_rule_beats_profile_default_transport():
    config = make_config(
        **{
            "llm.providers.default.kind": "opencode",
            "llm.providers.default.base_url": "https://opencode.ai/zen/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "fallback-model",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    gpt_route = resolve_model_protocol(
        profile,
        provider,
        model_entry={"modelId": "zen-gpt", "model": "gpt-5.5-codex"},
    )
    qwen_route = resolve_model_protocol(
        profile,
        provider,
        model_entry={"modelId": "zen-qwen", "model": "qwen3-coder"},
    )
    opus_route = resolve_model_protocol(
        profile,
        provider,
        model_entry={"modelId": "zen-opus", "model": "opus-4"},
    )

    assert gpt_route.effective_model == "gpt-5.5-codex"
    assert gpt_route.wire_protocol == WireProtocol.RESPONSES
    assert gpt_route.source_scope == "provider_model"
    assert gpt_route.runtime_endpoint == "https://opencode.ai/zen/v1"
    assert qwen_route.effective_model == "qwen3-coder"
    assert qwen_route.wire_protocol == WireProtocol.ANTHROPIC_MESSAGES
    assert qwen_route.source_scope == "provider_model"
    assert qwen_route.configured_endpoint == "https://opencode.ai/zen/v1"
    assert qwen_route.runtime_endpoint == "https://opencode.ai/zen"
    assert opus_route.wire_protocol == WireProtocol.ANTHROPIC_MESSAGES
    assert opus_route.runtime_endpoint == "https://opencode.ai/zen"
    assert provider.base_url == "https://opencode.ai/zen/v1"


def test_explicit_model_wire_protocol_beats_opencode_provider_model_rule():
    config = make_config(
        **{
            "llm.providers.default.kind": "opencode",
            "llm.providers.default.base_url": "https://opencode.ai/zen/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3-coder",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(
        profile,
        provider,
        model_entry={
            "modelId": "zen-qwen-chat",
            "model": "qwen3-coder",
            "wireProtocol": "chat_completions",
        },
    )

    assert route.wire_protocol == WireProtocol.CHAT_COMPLETIONS
    assert route.source_scope == "model"
    assert route.runtime_endpoint == "https://opencode.ai/zen/v1"


def test_provider_api_wire_contract_beats_profile_default_transport():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api": "openai-responses",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.wire_protocol == WireProtocol.RESPONSES
    assert route.source_scope == "provider"


@pytest.mark.parametrize(
    ("provider_kind", "expected_wire"),
    [
        ("anthropic", WireProtocol.ANTHROPIC_MESSAGES),
        ("gemini", WireProtocol.GEMINI_GENERATE_CONTENT),
    ],
)
def test_native_provider_kind_beats_profile_default_transport(provider_kind, expected_wire):
    config = make_config(
        **{
            "llm.providers.default.kind": provider_kind,
            "llm.providers.default.base_url": "https://native.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "native-model",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.wire_protocol == expected_wire
    assert route.source_scope == "provider"


def test_wire_shaped_model_protocol_alias_migrates_at_route_boundary():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
            "llm.profiles.primary.protocol": "openai_responses",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    route = resolve_model_protocol(profile, provider)

    assert route.protocol == ModelProtocol.OPENAI_RESPONSES
    assert route.wire_protocol == WireProtocol.RESPONSES
    assert route.source_scope == "model"
    assert "wire_protocol.migrated_model_protocol_alias" in route.warnings


def test_unknown_native_provider_rejects_silent_chat_fallback():
    config = make_config(
        **{
            "llm.providers.default.kind": "custom_native",
            "llm.providers.default.base_url": "https://native.example.test/api",
            "llm.providers.default.compat_mode": "native",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "native-model",
        }
    )

    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)

    with pytest.raises(ValueError, match="wire protocol"):
        resolve_model_protocol(
            profile,
            provider,
            model_entry={
                "modelId": "custom-native-model",
                "model": "native-model",
                "wireProtocol": "custom_native",
            },
        )
