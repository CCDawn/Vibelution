from __future__ import annotations

import copy

import pytest

from config.llm_provider_registry import (
    add_llm_provider,
    delete_llm_provider,
    pin_llm_model,
    preview_provider_route_replacement,
    suggest_provider_id,
    unpin_llm_model,
    update_llm_provider,
    validate_provider_registry,
)
from config.public_config import list_llm_provider_options


def _empty_v2() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {},
            "profiles": {},
            "model_aliases": {},
        }
    }


def _provider(credential_ref: str = "env:RELAY_KEY") -> dict:
    return {
        "label": "Relay",
        "service_class": "relay",
        "vendor": "multi_model",
        "driver": "openai",
        "base_url": "https://relay.example/v1",
        "auth_kind": "api_key",
        "credential_ref": credential_ref,
        "requires_credential": True,
        "protocols": {
            "default": "responses",
            "allowed": ["responses", "chat_completions"],
        },
        "discovery": {
            "mode": "auto",
            "adapter": "openai_compatible",
            "cache_ttl_seconds": 3600,
        },
        "models": {},
    }


def test_duplicate_endpoint_and_credential_is_rejected() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    with pytest.raises(ValueError, match="duplicates active provider relay_a"):
        add_llm_provider(config, "relay_b", _provider())


def test_same_endpoint_with_different_credential_is_distinct() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider("env:RELAY_A_KEY"))
    config = add_llm_provider(config, "relay_b", _provider("env:RELAY_B_KEY"))
    validate_provider_registry(config)
    assert set(config["llm"]["providers"]) == {"relay_a", "relay_b"}


def test_duplicate_business_identity_uses_normalized_endpoint_and_credential_ref() -> (
    None
):
    config = add_llm_provider(_empty_v2(), "relay_a", _provider("env:relay_key"))
    duplicate = {
        **_provider("env:RELAY_KEY"),
        "base_url": "HTTPS://RELAY.EXAMPLE:443/v1/",
    }

    with pytest.raises(ValueError, match="duplicates active provider relay_a"):
        add_llm_provider(config, "relay_b", duplicate)


def test_provider_mutations_are_immutable_and_do_not_rewrite_provider_id() -> None:
    original = _empty_v2()
    provider = _provider()

    added = add_llm_provider(original, "relay_a", provider)
    provider["label"] = "Changed outside"

    assert original == _empty_v2()
    assert set(added["llm"]["providers"]) == {"relay_a"}
    assert added["llm"]["providers"]["relay_a"]["label"] == "Relay"


def test_pin_uses_upstream_id_and_stable_provider_scoped_key() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    updated = pin_llm_model(
        config, "relay_a", upstream_id="anthropic/claude-sonnet-4.6", label="Claude"
    )
    models = updated["llm"]["providers"]["relay_a"]["models"]
    assert set(models) == {"anthropic_claude-sonnet-4.6~3e041007"}
    assert models["anthropic_claude-sonnet-4.6~3e041007"]["upstream_id"] == (
        "anthropic/claude-sonnet-4.6"
    )
    assert config["llm"]["providers"]["relay_a"]["models"] == {}


def test_update_preserves_models_without_implicit_ref_migration() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    config = pin_llm_model(config, "relay_a", upstream_id="gpt-a")
    original = copy.deepcopy(config)
    replacement = {**_provider(), "label": "Renamed"}
    replacement.pop("models")

    updated = update_llm_provider(config, "relay_a", replacement)

    assert updated["llm"]["providers"]["relay_a"]["label"] == "Renamed"
    assert set(updated["llm"]["providers"]["relay_a"]["models"]) == {"gpt-a"}
    assert updated["llm"]["profiles"] == {}
    assert config == original


def test_unpin_and_delete_require_explicit_order_and_are_immutable() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    config = pin_llm_model(config, "relay_a", upstream_id="gpt-a")

    with pytest.raises(ValueError, match="no pinned models"):
        delete_llm_provider(config, "relay_a")

    unpinned = unpin_llm_model(config, "relay_a/gpt-a")
    deleted = delete_llm_provider(unpinned, "relay_a")

    assert set(config["llm"]["providers"]["relay_a"]["models"]) == {"gpt-a"}
    assert deleted["llm"]["providers"] == {}


def test_route_replacement_preview_reports_all_provider_models() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    config = pin_llm_model(config, "relay_a", upstream_id="gpt-5.6-luna", label="GPT")
    preview = preview_provider_route_replacement(
        config,
        "relay_a",
        {
            **_provider("env:NEW_ACCOUNT_KEY"),
            "models": config["llm"]["providers"]["relay_a"]["models"],
        },
    )
    assert preview["routeChanged"] is True
    assert preview["modelRefs"] == ["relay_a/gpt-5.6-luna"]
    assert preview["oldFingerprint"] != preview["newFingerprint"]


def test_provider_id_suggestion_is_readable_and_collision_deterministic() -> None:
    provider = _provider("env:VIBELUTION_LLM_PROVIDER_RELAY_A_API_KEY")
    assert suggest_provider_id(provider, []) == "relay"
    suggested = suggest_provider_id(provider, ["relay"])
    assert suggested.startswith("relay_")
    assert len(suggested.rsplit("_", 1)[1]) == 8


def test_provider_options_expose_credential_state_without_reference_or_secret() -> None:
    provider = {**_provider("none"), "auth_kind": "none", "requires_credential": False}
    provider["deployment"] = {
        "runtime_framework": "vllm",
        "artifact_path": "models/relay",
    }
    config = add_llm_provider(_empty_v2(), "relay_a", provider)

    options = list_llm_provider_options(config)

    assert options == [
        {
            "provider_id": "relay_a",
            "label": "Relay",
            "service_class": "relay",
            "vendor": "multi_model",
            "driver": "openai",
            "runtime_framework": "vllm",
            "artifact_path": "models/relay",
            "base_url": "https://relay.example/v1",
            "credential_state": "not_required",
            "default_protocol": "responses",
            "pinned_count": 0,
        }
    ]
    assert "credential_ref" not in options[0]
    assert "secret" not in options[0]
