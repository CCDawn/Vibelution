from __future__ import annotations

import copy

import pytest

from config.public_config import LLM_MODEL_PRESETS, list_llm_provider_preset_options
from config.models import ProviderConfig


@pytest.mark.parametrize("preset_id", list(LLM_MODEL_PRESETS))
def test_every_model_preset_has_a_v2_provider_connection(preset_id: str) -> None:
    from config.provider_preset_contract import normalize_provider_preset

    preset = LLM_MODEL_PRESETS[preset_id]
    before = copy.deepcopy(preset)
    provider = normalize_provider_preset(preset["provider"], preset["model"])
    assert provider["driver"] in {"openai", "anthropic"}
    assert provider["protocols"]["default"] in provider["protocols"]["allowed"]
    requires = preset["provider"].get("requires_api_key", True)
    assert provider["auth_kind"] == ("api_key" if requires else "none")
    assert provider["credential_ref"] == (
        f"env:{preset['provider']['api_key_env']}" if requires else "none"
    )
    assert provider["requires_credential"] is requires
    assert provider["discovery"]["adapter"] != "manual"
    ProviderConfig(**provider)
    assert preset == before


@pytest.mark.parametrize("option", list_llm_provider_preset_options(), ids=lambda x: x["provider_id"])
def test_every_public_provider_template_has_complete_contract(option: dict) -> None:
    provider = option["provider"]
    raw_provider = LLM_MODEL_PRESETS[option["source_preset_id"]]["provider"]
    assert provider["driver"] in {"openai", "anthropic"}
    assert provider["protocols"]["default"] in provider["protocols"]["allowed"]
    assert provider["credential_ref"] == (
        f"env:{raw_provider['api_key_env']}" if raw_provider["requires_api_key"] else "none"
    )
    assert "api_key_env" not in provider
    assert provider["discovery"]["mode"] == "auto"


def test_anthropic_and_gemini_connections_have_distinct_chat_and_catalog_contracts() -> None:
    options = {option["provider_id"]: option["provider"] for option in list_llm_provider_preset_options()}
    for provider_id in ("anthropic_main", "anthropic_atpify"):
        provider = options[provider_id]
        assert provider["driver"] == "anthropic"
        assert provider["protocols"] == {"default": "anthropic_messages", "allowed": ["anthropic_messages"]}
        assert provider["discovery"]["adapter"] == "anthropic"
    gemini = options["google_main"]
    assert gemini["driver"] == "openai"
    assert gemini["protocols"]["default"] == "chat_completions"
    assert gemini["discovery"]["adapter"] == "gemini"
    assert gemini["discovery"]["models_url_override"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert options["local_main"]["discovery"]["adapter"] == "ollama"


def test_explicit_wire_and_protocols_do_not_depend_on_model_name() -> None:
    from config.provider_preset_contract import normalize_provider_preset

    raw = {
        "kind": "anthropic", "driver": "openai", "base_url": "https://relay.example/v1",
        "api_key_env": "LAB_KEY", "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
        "discovery": {"adapter": "openai_compatible", "cache_ttl_seconds": 77},
    }
    provider = normalize_provider_preset(raw, {"model": "claude-gemini", "wire_protocol": "chat_completions"})
    assert provider["driver"] == "openai"
    assert provider["protocols"] == raw["protocols"]
    assert provider["discovery"]["adapter"] == "openai_compatible"
    assert provider["discovery"]["cache_ttl_seconds"] == 77


def test_explicit_model_wire_is_preserved_without_provider_protocols() -> None:
    from config.provider_preset_contract import normalize_provider_preset

    provider = normalize_provider_preset(
        {"kind": "anthropic", "base_url": "https://relay.example", "api_key_env": "LAB_KEY"},
        {"model": "any-model", "wire_protocol": "responses"},
    )
    assert provider["protocols"] == {"default": "responses", "allowed": ["responses"]}


def test_gemini_catalog_derivation_preserves_custom_host_and_path_prefix() -> None:
    from config.provider_preset_contract import normalize_provider_preset

    provider = normalize_provider_preset(
        {"kind": "google", "base_url": "https://relay.example/google/v1beta/openai/", "api_key_env": "LAB_KEY"},
        {"model": "any-model", "transport": "chat_completions"},
    )
    assert provider["base_url"] == "https://relay.example/google/v1beta/openai"
    assert provider["discovery"]["models_url_override"] == "https://relay.example/google/v1beta/models"


def test_preset_listing_never_resolves_credentials(monkeypatch) -> None:
    monkeypatch.setattr("config.public_config.resolve_credential_ref", lambda *_args, **_kwargs: pytest.fail("preset listing read credentials"))
    assert len(list_llm_provider_preset_options()) == 21


def test_explicit_credential_reference_and_override_are_preserved() -> None:
    from config.provider_preset_contract import normalize_provider_preset

    raw = {"kind": "openai", "base_url": "https://relay.example/v1", "credential_ref": "env:EXPLICIT_KEY"}
    assert normalize_provider_preset(raw, {})["credential_ref"] == "env:EXPLICIT_KEY"
    assert normalize_provider_preset(raw, {})["auth_kind"] == "api_key"
    assert normalize_provider_preset(raw, {}, credential_env="OVERRIDE_KEY")["credential_ref"] == "env:OVERRIDE_KEY"
