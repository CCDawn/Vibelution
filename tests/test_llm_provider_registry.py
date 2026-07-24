from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

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


def test_protocol_resolver_imports_in_fresh_process() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from core.llm.protocol_resolver import resolve_model_protocol",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


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


def test_pin_openai_responses_model_gets_reasoning_effort_protocol_defaults() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    updated = pin_llm_model(config, "relay_a", upstream_id="gpt-5.6-sol", label="Sol")
    pinned = updated["llm"]["providers"]["relay_a"]["models"]["gpt-5.6-sol"]
    assert pinned["defaults"]["reasoning_effort_values"] == ["low", "medium", "high"]
    assert pinned["defaults"]["default_reasoning_effort"] == "medium"
    assert pinned["defaults"]["reasoning_effort_adapter"] == "reasoning_object"
    # Idempotent re-pin heals older entries missing the contract.
    bare = add_llm_provider(_empty_v2(), "relay_a", _provider())
    bare["llm"]["providers"]["relay_a"]["models"] = {
        "gpt-5.6-sol": {"upstream_id": "gpt-5.6-sol", "label": "Sol", "enabled": True}
    }
    healed = pin_llm_model(bare, "relay_a", upstream_id="gpt-5.6-sol")
    assert healed["llm"]["providers"]["relay_a"]["models"]["gpt-5.6-sol"]["defaults"][
        "reasoning_effort_values"
    ] == ["low", "medium", "high"]


@pytest.mark.parametrize(
    "reserved_field",
    [
        "upstream_id",
        "label",
        "enabled",
        "model_key",
        "provider_id",
        "model_ref",
        "api_key",
        "api_key_env",
        "credential_ref",
    ],
)
def test_pin_rejects_reserved_identity_and_ownership_overrides(
    reserved_field: str,
) -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    original = copy.deepcopy(config)
    sentinel = "must-not-appear"

    with pytest.raises(
        ValueError, match="^pinned model overrides contain reserved fields$"
    ) as exc_info:
        pin_llm_model(
            config,
            "relay_a",
            upstream_id="anthropic/claude-sonnet-4.6",
            overrides={reserved_field: sentinel},
        )

    assert str(exc_info.value) == "pinned model overrides contain reserved fields"
    assert sentinel not in str(exc_info.value)
    assert config == original


@pytest.mark.parametrize(
    "overrides",
    [
        {"compatibility": {"api_key": "must-not-appear"}},
        {"compatibility": {"payload": [{"api_key_env": "must-not-appear"}]}},
        {"metadata": [{"nested": {"credential_ref": "must-not-appear"}}]},
    ],
)
def test_pin_rejects_nested_credential_fields_without_mutating_input(
    overrides: dict,
) -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    original = copy.deepcopy(config)
    sentinel = "must-not-appear"

    with pytest.raises(
        ValueError, match="^pinned model overrides contain reserved fields$"
    ) as exc_info:
        pin_llm_model(
            config,
            "relay_a",
            upstream_id="gpt-a",
            overrides=overrides,
        )

    assert str(exc_info.value) == "pinned model overrides contain reserved fields"
    assert sentinel not in str(exc_info.value)
    assert config == original


def test_pin_preserves_nested_noncredential_metadata() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    overrides = {
        "compatibility": {
            "payload": [{"supports_tools": True}],
            "tags": ["relay", "stable"],
        }
    }

    updated = pin_llm_model(
        config,
        "relay_a",
        upstream_id="gpt-a",
        overrides=overrides,
    )

    assert (
        updated["llm"]["providers"]["relay_a"]["models"]["gpt-a"]["compatibility"]
        == overrides["compatibility"]
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


def test_unpin_rejects_unknown_pinned_model_without_mutating_input() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    original = copy.deepcopy(config)

    with pytest.raises(ValueError, match="^unknown pinned model$"):
        unpin_llm_model(config, "relay_a/missing-model")

    assert config == original


@pytest.mark.parametrize("invalid_models", [None, [], "not-a-model-registry"])
def test_unpin_rejects_invalid_model_registry_without_mutating_input(
    invalid_models: object,
) -> None:
    provider = {**_provider(), "models": invalid_models}
    config = add_llm_provider(_empty_v2(), "relay_a", provider)
    original = copy.deepcopy(config)

    with pytest.raises(ValueError, match="^provider models must be an object$"):
        unpin_llm_model(config, "relay_a/gpt-a")

    assert config == original


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
