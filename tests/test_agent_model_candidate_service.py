from __future__ import annotations

import copy
import json

from config.llm_identity import provider_discovery_fingerprint
from core.web.services import agent_model_candidate_service


def _public_config() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "ai-pixel": {
                    "label": "Ai-Pixel",
                    "driver": "openai",
                    "service_class": "relay",
                    "base_url": "https://relay.example/v1",
                    "credential_ref": "env:AI_PIXEL_API_KEY",
                    "auth_kind": "api_key",
                    "requires_credential": True,
                    "protocols": {"default": "responses"},
                    "discovery": {"adapter": "openai_compatible"},
                    "models": {
                        "image2": {
                            "upstream_id": "gpt-image-1",
                            "label": "Image 2",
                            "enabled": True,
                        }
                    },
                }
            },
            "profiles": {"primary": {"model_ref": "ai-pixel/image2"}},
        }
    }


def _catalog_state() -> dict:
    provider = _public_config()["llm"]["providers"]["ai-pixel"]
    fingerprint = provider_discovery_fingerprint(provider)
    return {
        "schemaVersion": 2,
        "metadata": {"legacyCapabilityImportCompleted": True},
        "providers": {
            "ai-pixel": {
                "providerFingerprint": fingerprint,
                "catalogStale": False,
                "models": {
                    "gpt-5.6-luna": {
                        "upstreamId": "gpt-5.6-luna",
                        "label": "Luna",
                        "availability": "observed",
                        "capabilities": {},
                    },
                    "gpt-5.6-sol": {
                        "upstreamId": "gpt-5.6-sol",
                        "label": "Sol",
                        "availability": "observed",
                        "capabilities": {},
                    },
                    "gpt-5.6-terra": {
                        "upstreamId": "gpt-5.6-terra",
                        "label": "Terra",
                        "availability": "observed",
                        "capabilities": {},
                    },
                    "image2": {
                        "upstreamId": "gpt-image-1",
                        "label": "Observed image label",
                        "availability": "pinned",
                        "capabilities": {},
                    },
                },
            },
            "catalog-only": {
                "providerFingerprint": "ignored",
                "catalogStale": False,
                "models": {
                    "ghost": {
                        "upstreamId": "ghost-model",
                        "label": "Ghost",
                        "availability": "observed",
                    }
                },
            },
        },
    }


def test_projection_unions_pinned_and_observed_without_duplicate_model_refs():
    payload = agent_model_candidate_service.project_agent_model_candidates(
        _public_config(),
        _catalog_state(),
    )
    by_ref = {item["modelRef"]: item for item in payload}

    assert sorted(by_ref) == [
        "ai-pixel/gpt-5.6-luna",
        "ai-pixel/gpt-5.6-sol",
        "ai-pixel/gpt-5.6-terra",
        "ai-pixel/image2",
    ]
    assert by_ref["ai-pixel/image2"]["source"] == "both"
    assert by_ref["ai-pixel/image2"]["label"] == "Image 2"
    assert by_ref["ai-pixel/gpt-5.6-luna"]["source"] == "discovered"
    assert by_ref["ai-pixel/gpt-5.6-luna"]["runtimeSelectable"] is False
    assert by_ref["ai-pixel/gpt-5.6-luna"]["slotCompatibility"]["dialogue"]["allowed"] is True


def test_image_and_audio_candidates_remain_visible_with_disabled_reason():
    catalog = _catalog_state()
    models = catalog["providers"]["ai-pixel"]["models"]
    models["gpt-image-1"] = {
        "upstreamId": "gpt-image-1",
        "label": "Image generator",
        "availability": "observed",
    }
    models["gpt-4o-mini-tts"] = {
        "upstreamId": "gpt-4o-mini-tts",
        "label": "Audio generator",
        "availability": "observed",
    }

    payload = agent_model_candidate_service.project_agent_model_candidates(_public_config(), catalog)
    by_upstream = {item["upstreamId"]: item for item in payload}

    for upstream_id in ("gpt-image-1", "gpt-4o-mini-tts"):
        assert by_upstream[upstream_id]["slotCompatibility"]["dialogue"] == {
            "allowed": False,
            "reasonCode": "non_dialogue_model",
        }
        assert by_upstream[upstream_id]["capabilityStatus"] == "confirmed"
        assert by_upstream[upstream_id]["capabilitySource"] == "operator_override"


def _single_model_public_config(upstream_id: str) -> dict:
    public_config = _public_config()
    public_config["llm"]["providers"]["ai-pixel"]["models"] = {
        "primary": {"upstream_id": upstream_id, "label": upstream_id, "enabled": True}
    }
    return public_config


def test_curated_preset_image_capability_reaches_slot_projection() -> None:
    # ``deepseek-v4-flash`` is a built-in preset that declares image input as
    # unsupported, so the curated snapshot layer must surface that verdict
    # instead of leaving the vision slot at "unknown".
    payload = agent_model_candidate_service.project_agent_model_candidates(
        _single_model_public_config("deepseek-v4-flash"),
        _catalog_state(),
    )
    candidate = next(item for item in payload if item["upstreamId"] == "deepseek-v4-flash")

    assert candidate["supportsImageInput"] is False
    assert candidate["slotCompatibility"]["vision"] == {
        "allowed": False,
        "reasonCode": "image_input_unsupported",
    }
    assert candidate["capabilities"]["image_input"]["source"] == "curated_snapshot"


def test_unlisted_gateway_model_keeps_image_capability_unknown() -> None:
    payload = agent_model_candidate_service.project_agent_model_candidates(
        _single_model_public_config("mystery-gateway-model-9000"),
        _catalog_state(),
    )
    candidate = next(
        item for item in payload if item["upstreamId"] == "mystery-gateway-model-9000"
    )

    assert candidate["supportsImageInput"] is None
    assert candidate["slotCompatibility"]["vision"] == {
        "allowed": False,
        "reasonCode": "image_input_unknown",
    }


def test_provider_endpoint_declaration_outranks_curated_preset() -> None:
    catalog = _catalog_state()
    catalog["providers"]["ai-pixel"]["models"] = {
        "primary": {
            "upstreamId": "deepseek-v4-flash",
            "label": "DeepSeek V4 Flash",
            "availability": "observed",
            "capabilities": {
                "image_input": {"value": "supported", "source": "provider_endpoint"}
            },
        }
    }

    payload = agent_model_candidate_service.project_agent_model_candidates(
        _single_model_public_config("deepseek-v4-flash"),
        catalog,
    )
    candidate = next(item for item in payload if item["upstreamId"] == "deepseek-v4-flash")

    assert candidate["supportsImageInput"] is True
    assert candidate["slotCompatibility"]["vision"]["allowed"] is True
    assert candidate["capabilities"]["image_input"]["source"] == "provider_endpoint"


def test_numbered_image_alias_is_disabled_without_matching_image_understanding_models():
    public_config = _public_config()
    public_config["llm"]["providers"]["ai-pixel"]["models"]["image2"]["upstream_id"] = "image2"
    catalog = _catalog_state()
    models = catalog["providers"]["ai-pixel"]["models"]
    models["image2"]["upstreamId"] = "image2"
    models["image-understanding"] = {
        "upstreamId": "image-understanding",
        "label": "Image Understanding",
        "availability": "observed",
    }

    by_ref = {
        item["modelRef"]: item
        for item in agent_model_candidate_service.project_agent_model_candidates(public_config, catalog)
    }

    image_alias = by_ref["ai-pixel/image2"]
    assert image_alias["upstreamId"] == "image2"
    assert image_alias["slotCompatibility"]
    assert all(
        compatibility == {"allowed": False, "reasonCode": "non_dialogue_model"}
        for compatibility in image_alias["slotCompatibility"].values()
    )
    assert by_ref["ai-pixel/image-understanding"]["slotCompatibility"]["dialogue"] == {
        "allowed": True,
        "reasonCode": "",
    }


def test_reasoning_contract_accepts_only_operator_or_current_verified_evidence():
    public_config = _public_config()
    provider = public_config["llm"]["providers"]["ai-pixel"]
    provider["models"]["gpt-5.6-sol"] = {
        "upstream_id": "gpt-5.6-sol",
        "defaults": {
            "reasoning_effort_values": ["low", "xhigh", "low"],
            "default_reasoning_effort": "xhigh",
            "reasoning_effort_adapter": "reasoning.effort",
            "reasoning_effort_map": {"xhigh": "high"},
        },
    }
    fingerprint = provider_discovery_fingerprint(provider)
    catalog = _catalog_state()
    provider_catalog = catalog["providers"]["ai-pixel"]
    provider_catalog["providerFingerprint"] = fingerprint
    provider_catalog["models"]["gpt-5.6-luna"]["reasoningContract"] = {
        "verificationStatus": "verified",
        "providerFingerprint": fingerprint,
        "source": "runtime_probe",
        "effortValues": ["minimal", "xhigh"],
        "default": "xhigh",
        "adapter": "reasoning.effort",
        "map": {"xhigh": "high"},
    }
    provider_catalog["models"]["gpt-5.6-terra"]["reasoningContract"] = {
        "verificationStatus": "verified",
        "providerFingerprint": "stale-fingerprint",
        "source": "runtime_probe",
        "effortValues": ["high"],
        "default": "high",
        "adapter": "reasoning_effort",
    }

    by_ref = {
        item["modelRef"]: item
        for item in agent_model_candidate_service.project_agent_model_candidates(public_config, catalog)
    }

    assert by_ref["ai-pixel/gpt-5.6-sol"]["reasoningEffortValues"] == ["low", "xhigh"]
    assert by_ref["ai-pixel/gpt-5.6-sol"]["reasoningDefaultSource"] == "operator_override"
    assert by_ref["ai-pixel/gpt-5.6-sol"]["capabilityStatus"] == "confirmed"
    assert by_ref["ai-pixel/gpt-5.6-luna"]["reasoningEffortValues"] == ["low", "medium", "high"]
    assert by_ref["ai-pixel/gpt-5.6-luna"]["capabilityStatus"] == "confirmed"
    assert by_ref["ai-pixel/gpt-5.6-terra"]["supportsReasoningEffort"] is True
    assert by_ref["ai-pixel/gpt-5.6-terra"]["reasoningEffortValues"] == ["low", "medium", "high"]
    assert by_ref["ai-pixel/gpt-5.6-terra"]["capabilityStatus"] == "confirmed"


def _with_provider_status(catalog_status: str | None) -> tuple[dict, dict]:
    """Fixture pair with an explicit provider catalog status for health tests."""

    public_config = _public_config()
    catalog = _catalog_state()
    provider_catalog = catalog["providers"]["ai-pixel"]
    if catalog_status is None:
        catalog["providers"].pop("ai-pixel")
    else:
        provider_catalog["status"] = catalog_status
    return public_config, catalog


def test_provider_channel_health_mirrors_registry_status_set(monkeypatch):
    monkeypatch.setenv("AI_PIXEL_API_KEY", "candidate-health-key")

    def candidates_with(status: str | None):
        public_config, catalog = _with_provider_status(status)
        return {
            item["modelRef"]: item
            for item in agent_model_candidate_service.project_agent_model_candidates(
                public_config, catalog
            )
        }

    # Registry-healthy channel: reachable plus a configured key.
    reachable = candidates_with("reachable")["ai-pixel/gpt-5.6-luna"]
    assert reachable["providerStatus"] == "reachable"
    assert reachable["providerHealthy"] is True

    # Mild staleness stays usable (same tolerance as the registry rail).
    stale = candidates_with("stale")["ai-pixel/gpt-5.6-luna"]
    assert stale["providerHealthy"] is True

    # Broken auth/discovery/protocol channels are unhealthy.
    for broken_status in ("auth_failed", "discovery_failed", "blocked", "protocol_mismatch", "not_discovered"):
        candidate_item = candidates_with(broken_status)["ai-pixel/gpt-5.6-luna"]
        assert candidate_item["providerStatus"] == broken_status
        assert candidate_item["providerHealthy"] is False

    # Provider without a catalog entry defaults to healthy with an empty status.
    # Only pinned models remain candidates in that case.
    undiscovered = candidates_with(None)["ai-pixel/image2"]
    assert undiscovered["providerStatus"] == ""
    assert undiscovered["providerHealthy"] is True


def test_provider_channel_health_requires_configured_credential(monkeypatch):
    monkeypatch.delenv("AI_PIXEL_API_KEY", raising=False)

    public_config, catalog = _with_provider_status("reachable")
    by_ref = {
        item["modelRef"]: item
        for item in agent_model_candidate_service.project_agent_model_candidates(
            public_config, catalog
        )
    }

    candidate_item = by_ref["ai-pixel/gpt-5.6-luna"]
    assert candidate_item["missingApiKey"] is True
    assert candidate_item["providerHealthy"] is False


def test_disabled_provider_projects_unhealthy_channel_even_when_reachable(monkeypatch):
    """Wave 2 row switch: enabled=False hides the provider's models from the picker
    via the same providerHealthy=False path as broken channels. Selection-surface
    semantics only — candidate generation and ordering stay untouched."""
    monkeypatch.setenv("AI_PIXEL_API_KEY", "candidate-health-key")

    public_config, catalog = _with_provider_status("reachable")
    public_config["llm"]["providers"]["ai-pixel"]["enabled"] = False
    by_ref = {
        item["modelRef"]: item
        for item in agent_model_candidate_service.project_agent_model_candidates(
            public_config, catalog
        )
    }

    # Every candidate of the disabled provider shares the unhealthy channel.
    assert by_ref["ai-pixel/gpt-5.6-luna"]["providerHealthy"] is False
    assert by_ref["ai-pixel/image2"]["providerHealthy"] is False
    assert by_ref["ai-pixel/gpt-5.6-luna"]["providerStatus"] == "reachable"
    # Candidates are still generated (hidden by filter, not deleted).
    assert len(by_ref) == 4


def test_enabled_defaults_to_true_for_legacy_provider_without_key(monkeypatch):
    monkeypatch.setenv("AI_PIXEL_API_KEY", "candidate-health-key")

    public_config, catalog = _with_provider_status("reachable")
    assert "enabled" not in public_config["llm"]["providers"]["ai-pixel"]
    by_ref = {
        item["modelRef"]: item
        for item in agent_model_candidate_service.project_agent_model_candidates(
            public_config, catalog
        )
    }
    assert by_ref["ai-pixel/gpt-5.6-luna"]["providerHealthy"] is True


def test_list_candidates_reads_each_snapshot_once_and_never_exposes_secret(monkeypatch):
    public_config = _public_config()
    catalog = _catalog_state()
    original_public = copy.deepcopy(public_config)
    original_catalog = copy.deepcopy(catalog)
    calls = {"config": 0, "catalog": 0, "hash": 0, "credential": 0, "fingerprint": 0}
    secret = "candidate-secret-must-not-leak"
    monkeypatch.setenv("AI_PIXEL_API_KEY", secret)
    original_credential_projection = agent_model_candidate_service._provider_credential_compatibility
    original_fingerprint = agent_model_candidate_service.provider_discovery_fingerprint

    def load_config():
        calls["config"] += 1
        return public_config

    def load_catalog():
        calls["catalog"] += 1
        return catalog

    def hash_snapshot(snapshot):
        calls["hash"] += 1
        assert snapshot is public_config
        return "operator-snapshot-hash"

    def credential_projection(provider):
        calls["credential"] += 1
        return original_credential_projection(provider)

    def fingerprint(provider):
        calls["fingerprint"] += 1
        return original_fingerprint(provider)

    monkeypatch.setattr(agent_model_candidate_service, "load_public_config", load_config)
    monkeypatch.setattr(agent_model_candidate_service, "load_model_catalog_state", load_catalog)
    monkeypatch.setattr(agent_model_candidate_service, "public_config_hash", hash_snapshot)
    monkeypatch.setattr(
        agent_model_candidate_service,
        "_provider_credential_compatibility",
        credential_projection,
    )
    monkeypatch.setattr(agent_model_candidate_service, "provider_discovery_fingerprint", fingerprint)

    payload = agent_model_candidate_service.list_agent_model_candidates()

    assert calls == {"config": 1, "catalog": 1, "hash": 1, "credential": 1, "fingerprint": 1}
    assert payload["operatorConfigHash"] == "operator-snapshot-hash"
    assert public_config == original_public
    assert catalog == original_catalog
    assert secret not in json.dumps(payload, ensure_ascii=False)
    assert secret not in repr(payload)
    assert {item["apiKeyEnv"] for item in payload["candidates"]} == {"AI_PIXEL_API_KEY"}
    assert all(item["apiKeyConfigured"] is True for item in payload["candidates"])


def _install_counting_candidate_loaders(monkeypatch, catalog_state):
    """Bind per-test loaders so the cache signature is unique to this test."""
    calls = {"config": 0, "catalog": 0, "hash": 0}
    original_hash = agent_model_candidate_service.public_config_hash

    def load_config():
        calls["config"] += 1
        return _public_config()

    def load_catalog():
        calls["catalog"] += 1
        return copy.deepcopy(catalog_state)

    def hash_snapshot(snapshot):
        calls["hash"] += 1
        return original_hash(snapshot)

    monkeypatch.setattr(agent_model_candidate_service, "load_public_config", load_config)
    monkeypatch.setattr(agent_model_candidate_service, "load_model_catalog_state", load_catalog)
    monkeypatch.setattr(agent_model_candidate_service, "public_config_hash", hash_snapshot)
    return calls


def test_list_candidates_cache_hit_skips_rebuild_and_isolates_mutation(monkeypatch):
    calls = _install_counting_candidate_loaders(monkeypatch, _catalog_state())

    first = agent_model_candidate_service.list_agent_model_candidates()
    assert calls == {"config": 1, "catalog": 1, "hash": 1}
    assert first["candidates"]

    pristine = copy.deepcopy(first)
    first["candidates"].clear()
    first["modelOptions"].clear()
    first["operatorConfigHash"] = "mutated-by-caller"

    second = agent_model_candidate_service.list_agent_model_candidates()
    assert calls == {"config": 1, "catalog": 1, "hash": 1}
    assert second == pristine
    assert second["operatorConfigHash"] != "mutated-by-caller"

    second["candidates"].pop()
    third = agent_model_candidate_service.list_agent_model_candidates()
    assert calls == {"config": 1, "catalog": 1, "hash": 1}
    assert third == pristine


def test_list_candidates_cache_invalidates_when_catalog_signature_changes(monkeypatch):
    catalog_a = _catalog_state()
    calls = _install_counting_candidate_loaders(monkeypatch, catalog_a)

    first = agent_model_candidate_service.list_agent_model_candidates()
    assert calls == {"config": 1, "catalog": 1, "hash": 1}
    assert "ai-pixel/gpt-5.6-sol" in {item["modelRef"] for item in first["candidates"]}

    catalog_b = _catalog_state()
    del catalog_b["providers"]["ai-pixel"]["models"]["gpt-5.6-sol"]
    # Rebind the catalog loader: the bound callable is part of the cache signature,
    # so the next read must rebuild from the new snapshot.
    monkeypatch.setattr(
        agent_model_candidate_service,
        "load_model_catalog_state",
        lambda: copy.deepcopy(catalog_b),
    )

    second = agent_model_candidate_service.list_agent_model_candidates()
    assert calls["config"] == 2
    model_refs = {item["modelRef"] for item in second["candidates"]}
    assert "ai-pixel/gpt-5.6-sol" not in model_refs
    assert "ai-pixel/gpt-5.6-luna" in model_refs


def test_candidates_cache_signature_tracks_config_path(monkeypatch, tmp_path):
    from config import public_config as public_config_module

    before = agent_model_candidate_service._agent_model_candidates_cache_signature()
    monkeypatch.setattr(public_config_module, "CONFIG_PATH", str(tmp_path / "config.toml"))
    after = agent_model_candidate_service._agent_model_candidates_cache_signature()

    assert before != after
