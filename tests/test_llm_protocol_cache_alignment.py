"""Protocol wire registration + vendor cache strategy alignment."""

from __future__ import annotations

from core.llm.payload_builder import (
    PayloadBuildInput,
    PayloadPolicyActions,
    _apply_anthropic_explicit_prompt_cache_markers,
    _apply_explicit_prompt_cache_markers,
    _prompt_cache_provider_strategy,
)
from core.llm.protocols import WireProtocol
from core.llm.wire.registry import build_default_wire_adapter_registry
from tests.helpers.isolated_config import isolated_settings_config


def test_wire_registry_covers_all_declared_wire_protocols():
    registry = build_default_wire_adapter_registry()
    for wire in WireProtocol:
        adapter = registry.resolve(
            type(
                "R",
                (),
                {
                    "adapter_id": wire.value,
                    "wire_protocol": wire,
                    "provider_id": "p",
                    "runtime_endpoint": "https://example.test",
                    "model_id": "m",
                },
            )()
        )
        assert adapter.wire_protocol == wire
        assert adapter.adapter_id == wire.value


def test_anthropic_automatic_strategy_is_top_level_cache_control():
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "anthropic",
            "llm.providers.default.base_url": "https://api.anthropic.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "claude-sonnet-4",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    from core.llm.adapters import get_provider_adapter
    from core.llm.protocol_resolver import resolve_model_protocol
    from core.llm.types import LLMCapabilities

    route = resolve_model_protocol(profile, provider)
    adapter = get_provider_adapter(provider, profile)
    build_input = PayloadBuildInput(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        profile=profile,
        provider=provider,
        adapter=adapter,
        route=route,
        capabilities=LLMCapabilities(supports_prompt_cache=True),
        stream=False,
        api_key="test",
        profile_id="primary",
        config=config,
    )
    strategy = _prompt_cache_provider_strategy(build_input, "automatic")
    assert strategy == "anthropic_automatic_top_level"


def test_anthropic_explicit_markers_land_on_system_block():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="anthropic_explicit_cache_control")
    messages = [
        {"role": "system", "content": "You are a careful assistant."},
        {"role": "user", "content": "hello"},
    ]
    out = _apply_anthropic_explicit_prompt_cache_markers(messages, actions)
    assert actions.anthropic_prompt_cache_markers_added >= 1
    system = out[0]
    assert isinstance(system["content"], list)
    assert any(
        isinstance(block, dict) and block.get("cache_control", {}).get("type") == "ephemeral"
        for block in system["content"]
    )


def test_explicit_dispatcher_routes_qwen_and_anthropic():
    qwen_actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    anthropic_actions = PayloadPolicyActions(prompt_cache_provider_strategy="anthropic_explicit_cache_control")
    messages = [
        {"role": "user", "content": "history"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "now"},
    ]
    qwen_out = _apply_explicit_prompt_cache_markers(messages, qwen_actions)
    anthropic_out = _apply_explicit_prompt_cache_markers(messages, anthropic_actions)
    assert qwen_actions.qwen_prompt_cache_markers_added >= 0
    assert anthropic_actions.anthropic_prompt_cache_markers_added >= 0
    assert isinstance(qwen_out, list)
    assert isinstance(anthropic_out, list)


def test_deepseek_automatic_strategy_unchanged():
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-flash",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    from core.llm.adapters import get_provider_adapter
    from core.llm.protocol_resolver import resolve_model_protocol
    from core.llm.types import LLMCapabilities

    route = resolve_model_protocol(profile, provider)
    adapter = get_provider_adapter(provider, profile)
    build_input = PayloadBuildInput(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        profile=profile,
        provider=provider,
        adapter=adapter,
        route=route,
        capabilities=LLMCapabilities(),
        stream=False,
        api_key="test",
        profile_id="primary",
        config=config,
    )
    assert _prompt_cache_provider_strategy(build_input, "automatic") == "deepseek_automatic"
