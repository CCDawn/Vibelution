from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.models import ProviderConfig


def test_subscription_credential_metadata_never_requests_a_token(monkeypatch):
    from core.llm import chatgpt_subscription as auth

    manager = SimpleNamespace(
        status=lambda: {"state": "connected", "connected": True},
        get_access_token=lambda: pytest.fail("configuration projection must not refresh credentials"),
    )
    monkeypatch.setattr(auth, "get_chatgpt_subscription_auth", lambda: manager)
    assert canonicalize_credential_ref("oauth:chatgpt") == "oauth:chatgpt"
    result = resolve_credential_ref("oauth:chatgpt")
    assert result.state == "configured"
    assert result.secret == ""


def test_subscription_credential_resolves_only_on_explicit_runtime_request(monkeypatch):
    from core.llm import chatgpt_subscription as auth

    manager = SimpleNamespace(status=lambda: {"connected": True}, get_access_token=lambda: "synthetic-token")
    monkeypatch.setattr(auth, "get_chatgpt_subscription_auth", lambda: manager)
    assert resolve_credential_ref("oauth:chatgpt", resolve_secret=True).secret == "synthetic-token"
    assert "synthetic-token" not in repr(resolve_credential_ref("oauth:chatgpt", resolve_secret=True))


def test_subscription_provider_is_pinned_to_official_origin_and_responses():
    from config.chatgpt_subscription import build_subscription_provider

    provider = build_subscription_provider()
    assert ProviderConfig(**provider).auth_kind == "oauth"
    for changed in (
        {"base_url": "https://example.com/v1"},
        {"auth_kind": "api_key"},
        {"driver": "anthropic"},
        {"discovery": {"adapter": "gemini"}},
        {"discovery": {"adapter": "anthropic"}},
        {"protocols": {"default": "chat_completions", "allowed": ["chat_completions"]}},
        {"discovery": {"adapter": "openai", "models_url_override": "https://example.com/models"}},
    ):
        with pytest.raises(ValueError):
            ProviderConfig(**{**provider, **changed})


@pytest.mark.parametrize("reference", ["oauth:other", "oauth:chatgpt/extra", "oauth:https://example.com"])
def test_unknown_oauth_credential_references_are_rejected(reference):
    with pytest.raises(ValueError):
        canonicalize_credential_ref(reference)


def test_environment_credentials_keep_existing_behavior():
    result = resolve_credential_ref("env:SYNTHETIC_KEY", env_reader=lambda _: "synthetic-env")
    assert result.secret == "synthetic-env"
    assert result.state == "configured"


@pytest.mark.parametrize("reference", ["OAUTH:chatgpt", "oauth: chatgpt", " oauth:chatgpt "])
def test_oauth_aliases_cannot_escape_the_subscription_destination_guard(reference):
    from config.chatgpt_subscription import (
        build_subscription_provider,
        is_subscription_provider,
    )
    from config.llm_security import validate_llm_provider_target

    unsafe = {**build_subscription_provider(), "credential_ref": reference,
              "service_class": "relay", "kind": "relay", "base_url": "https://example.com/v1",
              "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]}}
    assert is_subscription_provider(unsafe)
    with pytest.raises(ValueError):
        ProviderConfig(**unsafe)
    with pytest.raises(ValueError):
        validate_llm_provider_target(unsafe, context="test", resolve_dns=False)
    safe = ProviderConfig(**{**build_subscription_provider(), "credential_ref": reference})
    assert safe.credential_ref == "oauth:chatgpt"


def test_legacy_profile_and_model_keys_cannot_change_subscription_billing(monkeypatch):
    from config import models
    from config.chatgpt_subscription import build_subscription_provider
    from core.llm import chatgpt_subscription as auth

    manager = SimpleNamespace(get_access_token=lambda: "synthetic-subscription")
    monkeypatch.setattr(auth, "get_chatgpt_subscription_auth", lambda: manager)
    monkeypatch.setattr(models, "_read_env_var", lambda _: "synthetic-paid-api-key")
    provider = models.ProviderConfig(**{**build_subscription_provider(), "provider_id": "subscription"})
    profile = models.LLMProfile(profile_id="primary", provider_id="subscription", model="test-model", api_key_env="PAID_TEST_KEY")
    config = models.LLMConfig(providers={"subscription": provider}, profiles={"primary": profile})
    monkeypatch.setattr(models.LLMConfig, "get_model_library_entry_for_profile", lambda *_: ("test", {"api_key_env": "PAID_MODEL_KEY"}))
    assert config.resolve_api_key_for_profile("primary") == "synthetic-subscription"
    assert config.get_api_key_source_label_for_profile("primary") == "oauth:chatgpt"


def test_subscription_is_excluded_from_automatic_paid_warmup(monkeypatch):
    from config.chatgpt_subscription import build_subscription_provider
    from core.llm.warmup import _provider_credentials_ready

    provider = ProviderConfig(**build_subscription_provider())
    monkeypatch.setattr(ProviderConfig, "resolve_api_key", lambda _: pytest.fail("warmup must not resolve OAuth credentials"))
    assert not _provider_credentials_ready(provider)


@pytest.mark.parametrize("levels", [[], ["high"], ["low", "medium", "high"]])
def test_subscription_pins_are_selectable_through_real_agent_model_gate(monkeypatch, levels):
    from config.chatgpt_subscription import build_subscription_provider
    from config.llm_provider_registry import pin_llm_model
    from config.public_config import build_effective_config
    from core.llm import chatgpt_subscription as auth
    from core.llm.agent_runtime import config_for_agent_llm_model
    from core.llm.protocol_resolver import resolve_model_protocol

    monkeypatch.setattr(auth, "get_chatgpt_subscription_auth", lambda: SimpleNamespace(status=lambda: {"connected": False}))
    public = {"llm": {"schema_version": 2, "providers": {"subscription": build_subscription_provider()},
                      "profiles": {"primary": {"model_ref": "subscription/plan-test"}}}}
    public = pin_llm_model(public, "subscription", upstream_id="plan-test", model_key="plan-test", overrides={
        "wire_protocol": "responses", "model_protocol": "openai_responses" if levels else "", "interaction_contract": "tool_chat",
        "context_window": 65536,
        "defaults": {"reasoning_effort_values": levels, "reasoning_effort_adapter": "reasoning_object" if levels else "none",
                     "default_reasoning_effort": "medium" if "medium" in levels else levels[0] if levels else ""},
    })
    config = build_effective_config(public)
    runtime = config_for_agent_llm_model(config, model_id="subscription/plan-test")
    profile = runtime.llm.get_profile(role="primary")
    assert profile.contract == "tool_chat"
    assert profile.reasoning_effort_values == levels
    assert profile.default_reasoning_effort == ("medium" if "medium" in levels else levels[0] if levels else "")
    route = resolve_model_protocol(profile, runtime.llm.providers["subscription"])
    assert route.adapter_id == "chatgpt_subscription_responses"


def _subscription_model_options_fixture():
    from config.chatgpt_subscription import build_subscription_provider
    from config.llm_provider_registry import pin_llm_model

    public = {"llm": {"schema_version": 2, "providers": {"subscription": build_subscription_provider()},
                      "profiles": {"primary": {"model_ref": "subscription/plan-test"}}}}
    return pin_llm_model(public, "subscription", upstream_id="plan-test", model_key="plan-test", overrides={
        "wire_protocol": "responses", "model_protocol": "openai_responses", "interaction_contract": "tool_chat",
        "context_window": 65536,
        "defaults": {"reasoning_effort_values": ["low"], "reasoning_effort_adapter": "reasoning_object",
                     "default_reasoning_effort": "low"},
    })


def test_subscription_model_options_preserve_provider_contract_without_secret_fields():
    import json

    from config.public_config import list_llm_model_options

    public = _subscription_model_options_fixture()
    source = public["llm"]["providers"]["subscription"]
    source.update(api_key="synthetic-inline-secret", access_token="synthetic-bearer", refresh_token="synthetic-refresh")
    source["protocols"]["extra_headers"] = {"Authorization": "Bearer synthetic-protocol-header"}
    source["discovery"].update(access_token="synthetic-discovery-token", extra_headers={"Authorization": "Bearer synthetic-discovery-header"})
    source["deployment"] = {"runtime_framework": "", "access_token": "synthetic-deployment-token"}
    option = list_llm_model_options(public)[0]
    provider = option["provider"]
    for field in ("auth_kind", "credential_ref", "driver", "vendor", "service_class"):
        assert provider[field] == source[field]
    assert provider["protocols"] == {"default": "responses", "allowed": ["responses"], "routes": {"responses": "responses"}}
    assert provider["discovery"] == {"adapter": "openai"}
    assert provider["deployment"] == {"runtime_framework": ""}
    assert ProviderConfig.model_validate(provider).auth_kind == "oauth"
    payload = json.dumps(option)
    for secret in ("synthetic-inline-secret", "synthetic-bearer", "synthetic-refresh", "synthetic-protocol-header",
                   "synthetic-discovery-token", "synthetic-discovery-header", "synthetic-deployment-token"):
        assert secret not in payload


@pytest.mark.parametrize("connected", [False, True])
def test_subscription_model_option_decoration_uses_only_oauth_status(monkeypatch, connected):
    from config.public_config import list_llm_model_options
    from core.llm import chatgpt_subscription as auth
    from core.web.services import config_service

    public = _subscription_model_options_fixture()
    option = list_llm_model_options(public)[0]
    # Preserve the complete identity here so this regression isolates credential
    # decoration from the separate public-provider projection regression.
    source = public["llm"]["providers"]["subscription"]
    option["provider"].update({field: source[field] for field in ("auth_kind", "driver", "vendor", "protocols", "discovery")})
    monkeypatch.setattr(config_service, "list_llm_model_options", lambda _: [option])
    monkeypatch.setattr(config_service, "_read_env_var", lambda _: pytest.fail("subscription metadata must not read API keys"))
    monkeypatch.setattr(config_service, "invoke_llm", lambda *_args, **_kwargs: pytest.fail("metadata must not run inference"))
    monkeypatch.setattr(auth, "get_chatgpt_subscription_auth", lambda: SimpleNamespace(
        status=lambda: {"connected": connected},
        get_access_token=lambda: pytest.fail("metadata must not refresh or resolve a bearer"),
    ))

    decorated = config_service._decorate_model_options(public, {})[0]
    assert decorated["api_key_source"] == "oauth:chatgpt"
    assert decorated["api_key_state"] == ("configured" if connected else "missing")
    assert decorated["api_key_configured"] is connected


def test_api_key_model_option_decoration_keeps_legacy_credential_metadata(monkeypatch):
    import json

    from core.web.services import config_service

    public = {"llm": {"schema_version": 1, "model_library": {"api-test": {
        "model": "synthetic-model", "provider": {
            "kind": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "SYNTHETIC_API_KEY",
        },
    }}}}
    monkeypatch.setattr(config_service, "_read_env_var", lambda name: "synthetic-paid-key" if name == "SYNTHETIC_API_KEY" else None)
    decorated = config_service._decorate_model_options(public, {})[0]
    assert decorated["api_key_source"] == "provider-env:SYNTHETIC_API_KEY"
    assert decorated["api_key_state"] == "configured"
    assert decorated["api_key_configured"] is True
    assert "synthetic-paid-key" not in json.dumps(decorated)
