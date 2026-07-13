from __future__ import annotations

import pytest

from config.model_catalog import (
    empty_model_catalog_state,
    import_legacy_capability_cache,
    load_model_catalog_state,
    merge_capability_observations,
    provider_catalog_refresh_due,
    record_model_verification,
    record_discovery_failure,
    record_discovery_success,
    resolve_model_capabilities,
    save_model_catalog_state,
)
from config.paths import resolve_model_catalog_state_path
from config.runtime_capabilities import (
    apply_model_capability_overrides,
    record_model_image_input_capability,
)


def test_discovery_success_reconciles_observed_and_missing_pinned(tmp_path) -> None:
    state = empty_model_catalog_state()
    state = record_discovery_success(
        state,
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={"gpt-a": {"upstream_id": "gpt-a"}, "gpt-b": {"upstream_id": "gpt-b"}},
    )
    models = state["providers"]["relay"]["models"]
    assert models["gpt-a"]["availability"] == "pinned"
    assert models["gpt-b"]["availability"] == "missing_remote"
    save_model_catalog_state(state, tmp_path / "model-catalog-state.json")
    assert load_model_catalog_state(tmp_path / "model-catalog-state.json") == state


def test_model_verification_records_callability_without_overwriting_discovery() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={"gpt-a": {"upstream_id": "gpt-a"}},
    )

    verified = record_model_verification(
        state,
        model_ref="relay/gpt-a",
        provider_fingerprint="fp",
        checked_at="2026-07-12T09:30:00Z",
        ok=False,
        error_type="service_unavailable",
        http_status=503,
    )

    provider = verified["providers"]["relay"]
    model = provider["models"]["gpt-a"]
    assert provider["status"] == "reachable"
    assert model["availability"] == "pinned"
    assert model["verification"] == {
        "status": "failed",
        "checkedAt": "2026-07-12T09:30:00Z",
        "errorType": "service_unavailable",
        "httpStatus": 503,
        "providerFingerprint": "fp",
    }
    rediscovered = record_discovery_success(
        verified,
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-12T10:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={"gpt-a": {"upstream_id": "gpt-a"}},
    )
    assert rediscovered["providers"]["relay"]["models"]["gpt-a"]["verification"] == model["verification"]


def test_discovery_fingerprint_change_marks_prior_evidence_stale_without_deleting_diagnostics() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp-old",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={
            "gpt-a": {"upstream_id": "gpt-a"},
            "gpt-b": {"upstream_id": "gpt-b"},
        },
    )
    for model_key in ("gpt-a", "gpt-b"):
        state = record_model_verification(
            state,
            model_ref=f"relay/{model_key}",
            provider_fingerprint="fp-old",
            checked_at="2026-07-12T09:30:00Z",
            ok=True,
        )
        state["providers"]["relay"]["models"][model_key]["reasoningContract"] = {
            "verificationStatus": "verified",
            "providerFingerprint": "fp-old",
            "checkedAt": "2026-07-12T09:31:00Z",
        }

    rediscovered = record_discovery_success(
        state,
        provider_id="relay",
        provider_fingerprint="fp-new",
        discovered_at="2026-07-12T10:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={
            "gpt-a": {"upstream_id": "gpt-a"},
            "gpt-b": {"upstream_id": "gpt-b"},
        },
    )

    for model_key in ("gpt-a", "gpt-b"):
        model = rediscovered["providers"]["relay"]["models"][model_key]
        assert model["verification"] == {
            "status": "stale",
            "checkedAt": "2026-07-12T09:30:00Z",
            "errorType": "",
            "httpStatus": None,
            "providerFingerprint": "fp-old",
        }
        assert model["reasoningContract"] == {
            "verificationStatus": "stale",
            "providerFingerprint": "fp-old",
            "checkedAt": "2026-07-12T09:31:00Z",
        }


def test_failure_keeps_last_success_and_marks_provider_stale() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={},
    )
    failed = record_discovery_failure(
        state,
        provider_id="relay",
        attempted_at="2026-07-11T13:00:00Z",
        error_type="timeout",
    )
    assert failed["providers"]["relay"]["status"] == "stale"
    assert failed["providers"]["relay"]["lastSuccessAt"] == "2026-07-11T12:00:00Z"
    assert "gpt-a" in failed["providers"]["relay"]["models"]


def test_auth_failure_keeps_models_but_reports_auth_state() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={},
    )
    failed = record_discovery_failure(
        state,
        provider_id="relay",
        attempted_at="2026-07-11T13:00:00Z",
        error_type="HTTPStatusError",
        status="auth_failed",
    )
    assert failed["providers"]["relay"]["status"] == "auth_failed"
    assert failed["providers"]["relay"]["catalogStale"] is True
    assert "gpt-a" in failed["providers"]["relay"]["models"]


def test_capabilities_merge_per_field_by_source_priority() -> None:
    merged = merge_capability_observations(
        [
            {"field": "image_input", "value": "unsupported", "source": "provider_endpoint", "checked_at": "a"},
            {"field": "image_input", "value": "supported", "source": "operator_override", "checked_at": "b"},
            {"field": "tool_calling", "value": "supported", "source": "runtime_probe", "checked_at": "c"},
        ]
    )
    assert merged["image_input"]["value"] == "supported"
    assert merged["image_input"]["source"] == "operator_override"
    assert merged["tool_calling"]["value"] == "supported"


def test_discovery_payload_cannot_spoof_operator_capability_or_metadata_source() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[
            {
                "upstream_id": "gpt-a",
                "metadata_source": "operator_override",
                "capabilities": {
                    "image_input": {
                        "value": "supported",
                        "source": "operator_override",
                        "capability_source": "operator_override",
                    }
                },
            }
        ],
        pinned={
            "gpt-a": {
                "upstream_id": "gpt-a",
                "capabilities": {
                    "image_input": {
                        "value": "unsupported",
                        "source": "provider_endpoint",
                    }
                },
            }
        },
    )
    model = state["providers"]["relay"]["models"]["gpt-a"]
    assert model["capabilities"]["image_input"]["value"] == "unsupported"
    assert model["capabilities"]["image_input"]["source"] == "operator_override"
    assert model["metadataSource"] == "provider_endpoint"


def test_resolve_capabilities_uses_independent_field_precedence() -> None:
    resolved = resolve_model_capabilities(
        operator={"image_input": "unsupported"},
        runtime_probe={"tool_calling": "supported"},
        provider_metadata={"image_input": "supported", "tool_calling": "unsupported"},
        curated_snapshot={"reasoning": "supported"},
        driver_default={"image_input": "unknown", "reasoning": "unsupported"},
    )
    assert resolved["image_input"]["value"] == "unsupported"
    assert resolved["image_input"]["source"] == "operator_override"
    assert resolved["tool_calling"]["source"] == "runtime_probe"
    assert resolved["reasoning"]["source"] == "curated_snapshot"


def test_resolve_capabilities_labels_inputs_instead_of_trusting_embedded_source() -> None:
    resolved = resolve_model_capabilities(
        operator={"image_input": {"value": "unsupported", "source": "driver_default"}},
        runtime_probe={},
        provider_metadata={"image_input": "supported"},
        curated_snapshot={},
        driver_default={},
    )
    assert resolved["image_input"]["value"] == "unsupported"
    assert resolved["image_input"]["source"] == "operator_override"


def test_invalid_capability_value_is_rejected_without_coercion() -> None:
    with pytest.raises(ValueError, match="invalid capability observation"):
        merge_capability_observations(
            [{"field": "image_input", "value": "yes", "source": "operator_override"}]
        )


@pytest.mark.parametrize(
    "secret_shaped_error",
    [
        "sk_liveABC123XYZ",
        "Bearer dummyTokenABC123",
        "https://relay.example/error?api_key=dummyTokenABC123",
    ],
)
def test_capability_errors_are_persisted_only_as_controlled_categories(secret_shaped_error) -> None:
    merged = merge_capability_observations(
        [
            {
                "field": "image_input",
                "value": "unknown",
                "source": "runtime_probe",
                "error": secret_shaped_error,
            }
        ]
    )
    assert merged["image_input"]["error"] == "other"
    assert secret_shaped_error not in repr(merged)


@pytest.mark.parametrize(
    "secret_shaped_error",
    [
        "sk_liveABC123XYZ",
        "BearerDummyTokenABC123",
        "httpsrelayexampleerrorapi_keydummyTokenABC123",
    ],
)
def test_discovery_error_type_is_reduced_to_controlled_category(secret_shaped_error) -> None:
    failed = record_discovery_failure(
        empty_model_catalog_state(),
        provider_id="relay",
        attempted_at="2026-07-11T13:00:00Z",
        error_type=secret_shaped_error,
    )
    assert failed["providers"]["relay"]["lastErrorType"] == "other"
    assert secret_shaped_error not in repr(failed)


def test_catalog_refresh_due_uses_last_attempt_and_ttl() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[],
        pinned={},
    )
    assert provider_catalog_refresh_due(state, "relay", ttl_seconds=3600, now="2026-07-11T13:00:01Z") is True
    assert provider_catalog_refresh_due(state, "relay", ttl_seconds=3600, now="2026-07-11T12:59:59Z") is False
    assert provider_catalog_refresh_due(state, "relay", ttl_seconds=0, now="2026-07-12T12:00:00Z") is False


def test_case_distinct_upstream_ids_remain_distinct_and_emit_warning() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[
            {"upstream_id": "Model-A", "label": "Model A upper", "capabilities": {}},
            {"upstream_id": "model-a", "label": "Model A lower", "capabilities": {}},
        ],
        pinned={},
    )
    provider = state["providers"]["relay"]
    assert len(provider["models"]) == 2
    assert provider["warnings"][0]["code"] == "upstream_id_case_collision"


def test_legacy_capability_import_runs_once_and_is_auditable() -> None:
    legacy = {
        "schemaVersion": 1,
        "models": {
            "old_model": {
                "capabilities": {
                    "image_input": {
                        "supports_image_input": True,
                        "capability_status": "supported",
                        "capability_source": "runtime_probe",
                        "capability_checked_at": "2026-07-10",
                    }
                }
            }
        },
    }
    imported = import_legacy_capability_cache(empty_model_catalog_state(), legacy, {"old_model": "relay/gpt-a"})
    assert imported["providers"]["relay"]["models"]["gpt-a"]["capabilities"]["image_input"]["value"] == "supported"
    assert imported["metadata"]["legacyCapabilityImportCompleted"] is True
    assert imported["metadata"]["legacyCapabilityImport"]["mappedModels"] == 1
    changed_legacy = {
        "schemaVersion": 1,
        "models": {
            "old_model": {
                "capabilities": {
                    "image_input": {"supports_image_input": False, "capability_status": "unsupported"}
                }
            }
        },
    }
    second = import_legacy_capability_cache(imported, changed_legacy, {"old_model": "relay/gpt-a"})
    assert second == imported


def test_empty_legacy_import_still_completes_once() -> None:
    imported = import_legacy_capability_cache(empty_model_catalog_state(), {"schemaVersion": 1}, {})
    assert imported["metadata"]["legacyCapabilityImportCompleted"] is True


def test_catalog_path_is_sibling_of_selected_operator_config(tmp_path) -> None:
    operator_config = tmp_path / "operator" / "custom.toml"
    assert resolve_model_catalog_state_path(operator_config) == operator_config.with_name("model-catalog-state.json")


def test_load_rejects_non_v2_catalog(tmp_path) -> None:
    path = tmp_path / "model-catalog-state.json"
    path.write_text('{"schemaVersion": 1, "models": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported model catalog schema"):
        load_model_catalog_state(path)


def test_runtime_capability_adapter_writes_provider_scoped_catalog(tmp_path) -> None:
    catalog_path = tmp_path / "model-catalog-state.json"
    record_model_image_input_capability(
        "relay/gpt-a",
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_checked_at": "2026-07-11T12:00:00Z",
        },
        cache_path=catalog_path,
    )
    state = load_model_catalog_state(catalog_path)
    capability = state["providers"]["relay"]["models"]["gpt-a"]["capabilities"]["image_input"]
    assert capability["value"] == "supported"
    assert capability["source"] == "runtime_probe"

    public_config = {
        "llm": {
            "model_library": {
                "relay/gpt-a": {
                    "label": "GPT A",
                    "model": "gpt-a",
                }
            }
        }
    }
    updated = apply_model_capability_overrides(public_config, cache_path=catalog_path)
    model = updated["llm"]["model_library"]["relay/gpt-a"]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "runtime_probe"


def test_runtime_adapter_never_dual_writes_legacy_cache_filename(tmp_path) -> None:
    legacy_path = tmp_path / "model-capabilities.json"
    record_model_image_input_capability(
        "relay/gpt-a",
        {"capability_status": "supported"},
        cache_path=legacy_path,
    )
    assert not legacy_path.exists()
    state = load_model_catalog_state(tmp_path / "model-catalog-state.json")
    assert state["providers"]["relay"]["models"]["gpt-a"]["capabilities"]["image_input"]["value"] == "supported"


def test_runtime_adapter_imports_legacy_cache_via_canonical_alias_once(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "operator" / "config.toml"
    legacy_path = config_path.with_name("model-capabilities.json")
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        """{
  "schemaVersion": 1,
  "models": {
    "old_model": {
      "capabilities": {
        "image_input": {
          "capability_status": "supported",
          "capability_source": "runtime_probe"
        }
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("VIBELUTION_MODEL_CAPABILITY_CACHE", raising=False)
    public_config = {
        "llm": {
            "model_aliases": {"old_model": "relay/gpt-a"},
            "model_library": {"relay/gpt-a": {"model": "gpt-a"}},
        }
    }

    updated = apply_model_capability_overrides(public_config)

    model = updated["llm"]["model_library"]["relay/gpt-a"]
    assert model["supports_image_input"] is True
    catalog = load_model_catalog_state(config_path.with_name("model-catalog-state.json"))
    assert catalog["metadata"]["legacyCapabilityImportCompleted"] is True
