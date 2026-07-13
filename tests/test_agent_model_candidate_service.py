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
        assert by_upstream[upstream_id]["capabilityStatus"] == "unknown"
        assert by_upstream[upstream_id]["capabilitySource"] == "unknown"


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
    assert by_ref["ai-pixel/gpt-5.6-luna"]["reasoningEffortValues"] == ["minimal", "xhigh"]
    assert by_ref["ai-pixel/gpt-5.6-luna"]["capabilityStatus"] == "verified"
    assert by_ref["ai-pixel/gpt-5.6-terra"]["supportsReasoningEffort"] is False
    assert by_ref["ai-pixel/gpt-5.6-terra"]["reasoningEffortValues"] == []
    assert by_ref["ai-pixel/gpt-5.6-terra"]["capabilityStatus"] == "unknown"


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
