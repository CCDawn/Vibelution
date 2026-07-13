from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from config.public_config import public_config_hash
from core.web.services import config_service, provider_config_service
from core.web.services.model_reference_service import ModelReferenceConflictError


def _provider(credential_ref: str) -> dict:
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


def test_provider_merge_preview_is_projected_without_credentials(monkeypatch) -> None:
    preview = SimpleNamespace(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=("ai-pixel-copy",),
        model_ref_map={"ai-pixel-copy/luna": "ai-pixel/luna"},
        status="READY",
        to_dict=lambda: {
            "previewId": "preview-1",
            "baseHash": "hash-1",
            "status": "READY",
            "canonicalProviderId": "ai-pixel",
            "duplicateProviderIds": ["ai-pixel-copy"],
            "modelRefMap": {"ai-pixel-copy/luna": "ai-pixel/luna"},
            "modelsToAdd": [],
            "liveReferences": [],
            "historicalReferences": [],
            "liveReferenceCount": 0,
            "historicalReferenceCount": 0,
            "conflicts": [],
            "requiredProbeModelRef": "ai-pixel/luna",
        },
    )
    monkeypatch.setattr(provider_config_service, "preview_provider_merge", lambda **_kwargs: preview)

    payload = provider_config_service.preview_duplicate_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel-copy"],
        credential_decisions={"ai-pixel-copy": "use_canonical"},
    )

    assert payload["status"] == "READY"
    assert "credential_ref" not in json.dumps(payload)


def test_provider_merge_apply_requires_explicit_confirmation(monkeypatch) -> None:
    captured = {}

    def fake_apply(preview_id, **kwargs):
        captured.update(preview_id=preview_id, **kwargs)
        return {"migrationId": "merge-1", "status": "applied", "hash": "hash-2"}

    monkeypatch.setattr(provider_config_service, "apply_provider_merge", fake_apply)

    result = provider_config_service.apply_duplicate_provider_merge(
        preview_id="preview-1", base_hash="hash-1", confirmed=True
    )

    assert result["migrationId"] == "merge-1"
    assert captured["confirmed"] is True


def _v2_config() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {},
            "profiles": {},
            "model_aliases": {},
        }
    }


def _v2_with_provider() -> dict:
    config = _v2_config()
    config["llm"]["providers"]["relay_a"] = _provider(
        "env:VIBELUTION_LLM_PROVIDER_RELAY_A_API_KEY"
    )
    config["llm"]["providers"]["relay_a"]["models"]["base-model"] = {
        "upstream_id": "base-model",
        "label": "Base Model",
        "enabled": True,
    }
    config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_a/base-model",
        "overrides": {},
    }
    return config


def _v2_with_provider_and_model() -> dict:
    config = _v2_with_provider()
    config["llm"]["providers"]["relay_a"]["models"]["gpt-a"] = {
        "upstream_id": "gpt-a",
        "label": "GPT A",
        "enabled": True,
    }
    return config


def _patch_saved(monkeypatch: pytest.MonkeyPatch, config: dict) -> None:
    monkeypatch.setattr(
        provider_config_service,
        "load_public_config",
        lambda: copy.deepcopy(config),
    )


def _v1_artifact_config() -> dict:
    return {
        "llm": {
            "schema_version": 1,
            "model_library": {
                "local-model": {
                    "model": "C:/models/local-model.gguf",
                    "provider": {"kind": "local"},
                },
                "remote-model": {
                    "model": "C:/models/remote-model.gguf",
                    "provider": {"kind": "openai"},
                },
            },
        }
    }


def test_migration_preview_passes_resolutions_and_projects_provider_kind_choices(monkeypatch) -> None:
    public_config = _v1_artifact_config()
    resolutions = [
        {"modelId": "local-model", "decision": "preserve_upstream_id"},
        {
            "modelId": "remote-model",
            "decision": "split_deployment_artifact",
            "upstreamId": "remote-upstream",
        },
    ]
    captured: dict[str, object] = {}
    events: list[tuple[str, str, dict]] = []

    def fake_preview(config, *, project_root, artifact_resolutions=None):
        captured["config"] = config
        captured["project_root"] = project_root
        captured["artifact_resolutions"] = artifact_resolutions
        return SimpleNamespace(
            preview_id="preview-a",
            base_hash="hash-a",
            status="CONFLICT",
            providers=(),
            model_ref_map={},
            reference_impact={"liveReferenceCount": 3},
            conflicts=(
                {"code": "artifact_path_suspected", "modelId": "local-model"},
                {"code": "artifact_path_suspected", "modelId": "remote-model"},
            ),
        )

    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(provider_config_service, "preview_v1_to_v2", fake_preview)
    monkeypatch.setattr(
        provider_config_service,
        "_record_migration_event",
        lambda event_code, *, outcome, fields: events.append((event_code, outcome, fields)),
    )

    raw = provider_config_service.preview_llm_v2_migration(
        artifact_resolutions=resolutions
    )
    projected = provider_config_service.project_llm_v2_migration_preview(raw)

    assert captured["config"] == public_config
    assert captured["artifact_resolutions"] == resolutions
    assert projected["conflicts"] == [
        {
            "code": "artifact_path_suspected",
            "modelId": "local-model",
            "requiresExplicitResolution": True,
            "allowedResolutions": [
                "preserve_upstream_id",
                "split_deployment_artifact",
            ],
            "verificationState": "unverified_offline",
        },
        {
            "code": "artifact_path_suspected",
            "modelId": "remote-model",
            "requiresExplicitResolution": True,
            "allowedResolutions": ["split_deployment_artifact"],
            "verificationState": "unverified_offline",
        },
    ]
    assert events == [
        (
            "config.schema.migration_previewed",
            "previewed",
            {
                "status": "CONFLICT",
                "resolutionCount": 2,
                "preserveResolutionCount": 1,
                "splitResolutionCount": 1,
                "providerCount": 0,
                "modelCount": 0,
                "referenceCount": 3,
                "elapsedMs": events[0][2]["elapsedMs"],
            },
        )
    ]


def test_migration_preview_projection_keeps_conflict_model_ids_without_artifact_paths() -> None:
    projected = provider_config_service.project_llm_v2_migration_preview(
        {
            "previewId": "preview-a",
            "baseHash": "hash-a",
            "status": "NEEDS_REVIEW",
            "providers": [],
            "modelRefMap": {},
            "referenceImpact": {},
            "conflicts": [
                {
                    "code": "provider_artifact_path_conflict",
                    "modelIds": ["model-a", "model-b"],
                    "artifactPath": "C:/private/sentinel-model.gguf",
                }
            ],
        }
    )

    assert projected["conflicts"] == [
        {
            "code": "provider_artifact_path_conflict",
            "modelIds": ["model-a", "model-b"],
        }
    ]
    assert "sentinel-model.gguf" not in json.dumps(projected)


def test_migration_preview_failure_event_is_bounded_and_redacted(monkeypatch) -> None:
    events: list[tuple[str, str, dict]] = []
    secret_resolution = {
        "modelId": "private-model",
        "decision": "split_deployment_artifact",
        "upstreamId": "private-upstream-secret",
    }
    monkeypatch.setattr(provider_config_service, "load_public_config", _v1_artifact_config)
    monkeypatch.setattr(
        provider_config_service,
        "preview_v1_to_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("C:/private/artifact.gguf Authorization credential-ref-secret")
        ),
    )
    monkeypatch.setattr(
        provider_config_service,
        "_record_migration_event",
        lambda event_code, *, outcome, fields: events.append((event_code, outcome, fields)),
    )

    with pytest.raises(ValueError):
        provider_config_service.preview_llm_v2_migration(
            artifact_resolutions=[secret_resolution]
        )

    assert len(events) == 1
    assert set(events[0][2]) == {
        "resolutionCount",
        "preserveResolutionCount",
        "splitResolutionCount",
        "elapsedMs",
        "errorType",
    }
    serialized = json.dumps(events)
    for forbidden in (
        "private-model",
        "private-upstream-secret",
        "C:/private/artifact.gguf",
        "Authorization",
        "credential-ref-secret",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("provider_kind", ["local", "local_runtime", "ollama"])
def test_artifact_conflict_preserve_is_available_only_for_local_provider_kinds(
    provider_kind: str,
) -> None:
    public_config = _v1_artifact_config()
    public_config["llm"]["model_library"]["local-model"]["provider"]["kind"] = provider_kind

    assert provider_config_service._artifact_conflict_allowed_resolutions(
        public_config, "local-model"
    ) == ["preserve_upstream_id", "split_deployment_artifact"]


def test_artifact_conflict_non_local_provider_only_allows_split() -> None:
    assert provider_config_service._artifact_conflict_allowed_resolutions(
        _v1_artifact_config(), "remote-model"
    ) == ["split_deployment_artifact"]


def test_provider_draft_add_returns_stable_provider_without_secret(monkeypatch) -> None:
    config = _v2_with_provider()
    _patch_saved(monkeypatch, config)
    workspace = provider_config_service.draft_add_provider(
        config,
        draft_meta={},
        base_hash=public_config_hash(config),
        provider_id="relay_b",
        provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY"),
        credential_value="secret-value",
    )
    assert {
        "publicConfig",
        "draftMeta",
        "editorSections",
        "hash",
        "providerOptions",
        "modelCatalog",
    } <= set(workspace)
    assert workspace["providerOptions"][-1]["provider_id"] == "relay_b"
    assert "credential_ref" not in workspace["providerOptions"][-1]
    assert "secret-value" not in json.dumps(workspace)
    assert workspace["draftMeta"]["pending_api_keys"]


def test_provider_draft_mutations_require_nonempty_current_base_hash(monkeypatch) -> None:
    config = _v2_config()
    _patch_saved(monkeypatch, config)
    with pytest.raises(ValueError, match="baseHash is required"):
        provider_config_service.draft_add_provider(
            config,
            draft_meta={},
            base_hash="",
            provider_id="relay_b",
            provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY"),
        )


def test_provider_route_update_requires_single_use_preview_token(monkeypatch) -> None:
    config = _v2_with_provider()
    _patch_saved(monkeypatch, config)
    replacement = _provider("env:VIBELUTION_LLM_PROVIDER_OTHER_ACCOUNT_API_KEY")
    with pytest.raises(ValueError, match="route replacement preview"):
        provider_config_service.draft_update_provider(
            config,
            draft_meta={},
            base_hash=public_config_hash(config),
            provider_id="relay_a",
            provider=replacement,
            route_preview_token="",
        )

    preview = provider_config_service.preview_draft_provider_route(
        config,
        base_hash=public_config_hash(config),
        provider_id="relay_a",
        provider=replacement,
    )
    assert preview["routeChanged"] is True
    assert preview["routePreviewToken"]
    assert "Fingerprint" not in json.dumps(preview)

    workspace = provider_config_service.draft_update_provider(
        config,
        draft_meta={},
        base_hash=public_config_hash(config),
        provider_id="relay_a",
        provider=replacement,
        route_preview_token=preview["routePreviewToken"],
    )
    assert workspace["providerOptions"][0]["provider_id"] == "relay_a"
    with pytest.raises(ValueError, match="route replacement preview"):
        provider_config_service.draft_update_provider(
            config,
            draft_meta={},
            base_hash=public_config_hash(config),
            provider_id="relay_a",
            provider=replacement,
            route_preview_token=preview["routePreviewToken"],
        )


def test_provider_delete_blocks_pinned_models_and_live_refs(monkeypatch) -> None:
    config = _v2_with_provider_and_model()
    _patch_saved(monkeypatch, config)
    with pytest.raises(ValueError, match="pinned models"):
        provider_config_service.draft_delete_provider(
            config,
            draft_meta={},
            base_hash=public_config_hash(config),
            provider_id="relay_a",
        )

    saved = copy.deepcopy(config)
    base_hash = public_config_hash(saved)
    config["llm"]["providers"]["relay_a"]["models"] = {}
    config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_a/observed-a",
        "overrides": {},
    }
    _patch_saved(monkeypatch, saved)
    monkeypatch.setattr(
        provider_config_service,
        "scan_model_references",
        lambda model_ref, **_kwargs: {
            "modelId": model_ref,
            "liveReferences": [{"source": "public_config", "path": "llm.profiles.primary.model_ref"}],
            "historicalReferences": [],
            "liveReferenceCount": 1,
            "historicalReferenceCount": 0,
            "blocking": True,
        },
    )
    with pytest.raises(ModelReferenceConflictError):
        provider_config_service.draft_delete_provider(
            config,
            draft_meta={},
            base_hash=base_hash,
            provider_id="relay_a",
        )


def test_unpin_checks_live_references_before_mutating(monkeypatch) -> None:
    config = _v2_with_provider_and_model()
    _patch_saved(monkeypatch, config)
    monkeypatch.setattr(
        provider_config_service,
        "scan_model_references",
        lambda model_ref, **_kwargs: {
            "modelId": model_ref,
            "liveReferences": [{"source": "agent_registry"}],
            "historicalReferences": [],
            "liveReferenceCount": 1,
            "historicalReferenceCount": 0,
            "blocking": True,
        },
    )
    with pytest.raises(ModelReferenceConflictError):
        provider_config_service.draft_unpin_provider_model(
            config,
            draft_meta={},
            base_hash=public_config_hash(config),
            provider_id="relay_a",
            model_key="gpt-a",
        )


def test_profile_binding_to_observed_model_pins_only_that_model(monkeypatch) -> None:
    config = _v2_with_provider()
    config["llm"]["providers"]["relay_a"]["models"] = {}
    config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_a/observed-a",
        "overrides": {},
    }
    monkeypatch.setattr(
        config_service,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "providers": {
                "relay_a": {
                    "models": {
                        "observed-a": {
                            "upstreamId": "observed-a",
                            "label": "Observed A",
                            "availability": "observed",
                        },
                        "observed-b": {
                            "upstreamId": "observed-b",
                            "label": "Observed B",
                            "availability": "observed",
                        },
                    }
                }
            },
        },
    )
    materialized = config_service.materialize_observed_binding_pins(config)
    models = materialized["llm"]["providers"]["relay_a"]["models"]
    assert set(models) == {"observed-a"}
    assert models["observed-a"]["upstream_id"] == "observed-a"


def test_discovery_delegates_and_records_bounded_redacted_events(monkeypatch) -> None:
    config = _v2_with_provider()
    _patch_saved(monkeypatch, config)
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        provider_config_service,
        "discover_provider_models",
        lambda public_config, provider_id, **kwargs: SimpleNamespace(
            provider_id=provider_id,
            adapter_id="openai_compatible",
            attempted_endpoints=("models",),
            discovered_at="2026-07-11T00:00:00+00:00",
            models=(SimpleNamespace(upstream_id="gpt-a"),),
        ),
    )
    monkeypatch.setattr(
        provider_config_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    workspace = provider_config_service.discover_draft_provider(
        config,
        draft_meta={},
        base_hash=public_config_hash(config),
        provider_id="relay_a",
        credential_value="secret-value",
    )
    assert workspace["providerOptions"][0]["provider_id"] == "relay_a"
    assert events[-1][0][2] == "config.provider.discovery_succeeded"
    serialized = json.dumps(events)
    for forbidden in (
        "secret-value",
        "credentialValue",
        "Authorization",
        "api_key",
        "relay.example",
        "artifact_path",
    ):
        assert forbidden not in serialized


def test_catalog_summary_omits_sensitive_details_and_derives_protocol_status(monkeypatch) -> None:
    config = _v2_with_provider_and_model()
    config["llm"]["providers"]["relay_a"]["models"]["gpt-a"]["wire_protocol"] = "gemini_generate_content"
    monkeypatch.setattr(
        config_service,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "providers": {
                "relay_a": {
                    "providerFingerprint": "must-not-appear",
                    "status": "reachable",
                    "lastAttemptAt": "2026-07-11T00:00:00+00:00",
                    "lastSuccessAt": "2026-07-11T00:00:00+00:00",
                    "lastErrorType": "",
                    "models": {
                        "gpt-a": {
                            "upstreamId": "gpt-a",
                            "label": "GPT A",
                            "availability": "pinned",
                            "metadata": {"response": "must-not-appear"},
                            "verification": {
                                "status": "failed",
                                "checkedAt": "2026-07-12T09:30:00Z",
                                "errorType": "service_unavailable",
                                "httpStatus": 503,
                                "rawMessage": "Bearer must-not-appear",
                            },
                        }
                    },
                }
            },
        },
    )
    summary = config_service._provider_workspace_fields(config)["modelCatalog"]
    assert summary["providers"]["relay_a"]["status"] == "protocol_mismatch"
    model = summary["providers"]["relay_a"]["models"]["gpt-a"]
    assert model["verificationStatus"] == "failed"
    assert model["verificationErrorType"] == "service_unavailable"
    assert model["verificationHttpStatus"] == 503
    serialized = json.dumps(summary)
    assert "providerFingerprint" not in serialized
    assert "credential_ref" not in serialized
    assert "must-not-appear" not in serialized


def test_provider_draft_events_cover_mutations_and_failed_discovery(monkeypatch) -> None:
    saved = _v2_with_provider()
    base_hash = public_config_hash(saved)
    _patch_saved(monkeypatch, saved)
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        provider_config_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        provider_config_service,
        "scan_model_references",
        lambda model_ref, **_kwargs: {
            "modelId": model_ref,
            "liveReferences": [],
            "historicalReferences": [],
            "liveReferenceCount": 0,
            "historicalReferenceCount": 0,
            "blocking": False,
        },
    )

    added = provider_config_service.draft_add_provider(
        saved,
        draft_meta={},
        base_hash=base_hash,
        provider_id="relay_b",
        provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY"),
        credential_value="secret-value",
    )
    replacement = _provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_OTHER_API_KEY")
    preview = provider_config_service.preview_draft_provider_route(
        added["publicConfig"],
        base_hash=base_hash,
        provider_id="relay_b",
        provider=replacement,
    )
    updated = provider_config_service.draft_update_provider(
        added["publicConfig"],
        draft_meta=added["draftMeta"],
        base_hash=base_hash,
        provider_id="relay_b",
        provider=replacement,
        route_preview_token=preview["routePreviewToken"],
    )
    assert set(updated["draftMeta"]["pending_api_keys"]) == {
        "VIBELUTION_LLM_PROVIDER_RELAY_B_OTHER_API_KEY"
    }
    pinned = provider_config_service.draft_pin_provider_model(
        updated["publicConfig"],
        draft_meta=updated["draftMeta"],
        base_hash=base_hash,
        provider_id="relay_b",
        upstream_id="gpt-b",
    )
    provider_config_service.draft_unpin_provider_model(
        pinned["publicConfig"],
        draft_meta=pinned["draftMeta"],
        base_hash=base_hash,
        provider_id="relay_b",
        model_key="gpt-b",
    )
    monkeypatch.setattr(
        provider_config_service,
        "discover_provider_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError(
                "secret-value https://relay.example/models?api_key=secret-value raw payload"
            )
        ),
    )
    with pytest.raises(ValueError, match="^provider discovery failed$") as exc_info:
        provider_config_service.discover_draft_provider(
            updated["publicConfig"],
            draft_meta=updated["draftMeta"],
            base_hash=base_hash,
            provider_id="relay_b",
            credential_value="secret-value",
        )
    assert "secret-value" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert "relay.example" not in repr(exc_info.value)
    assert "raw payload" not in repr(exc_info.value)

    event_codes = {str(args[2]) for args, _kwargs in events}
    assert {
        "config.provider.created",
        "config.provider.updated",
        "config.provider.route_replacement_previewed",
        "config.provider.discovery_failed",
        "config.model.pinned",
        "config.model.unpinned",
    } <= event_codes
    serialized = json.dumps(events)
    for forbidden in (
        "secret-value",
        "credentialValue",
        "Authorization",
        "api_key",
        "relay.example",
        "artifact_path",
    ):
        assert forbidden not in serialized


def test_delete_drops_only_its_pending_secret_before_apply(monkeypatch) -> None:
    saved = _v2_with_provider()
    base_hash = public_config_hash(saved)
    _patch_saved(monkeypatch, saved)
    other = provider_config_service.draft_add_provider(
        saved,
        draft_meta={},
        base_hash=base_hash,
        provider_id="relay_c",
        provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_C_API_KEY"),
        credential_value="secret-c",
    )
    target = provider_config_service.draft_add_provider(
        other["publicConfig"],
        draft_meta=other["draftMeta"],
        base_hash=base_hash,
        provider_id="relay_b",
        provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY"),
        credential_value="secret-b",
    )
    deleted = provider_config_service.draft_delete_provider(
        target["publicConfig"],
        draft_meta=target["draftMeta"],
        base_hash=base_hash,
        provider_id="relay_b",
    )
    assert set(deleted["draftMeta"]["pending_api_keys"]) == {
        "VIBELUTION_LLM_PROVIDER_RELAY_C_API_KEY"
    }

    persisted = {"value": copy.deepcopy(saved)}
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        config_service,
        "load_public_config",
        lambda: copy.deepcopy(persisted["value"]),
    )
    monkeypatch.setattr(
        config_service,
        "save_public_config",
        lambda value: persisted.update(value=copy.deepcopy(value)),
    )
    monkeypatch.setattr(config_service, "reload_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        config_service,
        "_set_user_env_var",
        lambda env, value: writes.append((env, value)),
    )
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda _env: None)
    config_service.apply_config_workspace(
        deleted["publicConfig"],
        base_config=saved,
        draft_meta=deleted["draftMeta"],
        base_hash=public_config_hash(
            config_service._with_config_workspace_defaults(saved)
        ),
    )
    assert writes == [("VIBELUTION_LLM_PROVIDER_RELAY_C_API_KEY", "secret-c")]


def test_apply_materializes_observed_binding_in_same_save_and_event(monkeypatch) -> None:
    saved = _v2_with_provider()
    submitted = copy.deepcopy(saved)
    submitted["llm"]["profiles"]["primary"]["model_ref"] = "relay_a/observed-a"
    persisted = {"value": copy.deepcopy(saved)}
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        config_service,
        "load_public_config",
        lambda: copy.deepcopy(persisted["value"]),
    )
    monkeypatch.setattr(
        config_service,
        "save_public_config",
        lambda value: persisted.update(value=copy.deepcopy(value)),
    )
    monkeypatch.setattr(config_service, "reload_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        config_service,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "providers": {
                "relay_a": {
                    "models": {
                        "observed-a": {
                            "upstreamId": "observed-a",
                            "label": "Observed A",
                            "availability": "observed",
                        }
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    workspace = config_service.apply_config_workspace(
        submitted,
        base_config=saved,
        base_hash=public_config_hash(
            config_service._with_config_workspace_defaults(saved)
        ),
    )

    models = persisted["value"]["llm"]["providers"]["relay_a"]["models"]
    assert set(models) == {"base-model", "observed-a"}
    assert workspace["publicConfig"]["llm"]["profiles"]["primary"]["model_ref"] == "relay_a/observed-a"
    applied = next(
        kwargs["fields"]
        for args, kwargs in events
        if args[1] == "config.workspace.applied"
    )
    assert applied["observedPinCount"] == 1
    assert applied["observedPinnedModelRefs"] == ["relay_a/observed-a"]


def test_catalog_summary_ignores_invalid_derived_provider_keys(monkeypatch) -> None:
    config = _v2_with_provider()
    monkeypatch.setattr(
        config_service,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "providers": {
                "INVALID/DERIVED": {
                    "status": "reachable",
                    "models": {"bad/key": {"availability": "observed"}},
                }
            },
        },
    )
    summary = config_service._provider_workspace_fields(config)["modelCatalog"]
    assert "INVALID/DERIVED" not in summary["providers"]
    assert "relay_a" in summary["providers"]


def test_provider_http_projection_recursively_allowlists_nested_data() -> None:
    projected = provider_config_service.project_provider_draft_response(
        {
            "hash": "draft-hash",
            "baseHash": "base-hash",
            "schemaVersion": 2,
            "rawToml": "credential_ref = 'env:SECRET'",
            "draftMeta": {"pending_api_keys": {"SECRET": "pending-secret:token"}},
            "providerOptions": [
                {
                    "provider_id": "relay_a",
                    "label": "Relay A",
                    "service_class": "relay",
                    "vendor": "example",
                    "driver": "openai",
                    "runtime_framework": "vllm",
                    "artifact_path": "C:/models/relay-a",
                    "base_url": "https://relay.example/v1",
                    "credential_state": "configured",
                    "default_protocol": "openai_chat_completions",
                    "pinned_count": 1,
                    "credential_ref": "env:SECRET",
                    "query": {"api_key": "secret-value"},
                    "unknownNested": {"rawPayload": "secret-value"},
                },
                {
                    "provider_id": {"nested": "relay_secret"},
                    "label": "pending-secret:token",
                    "runtime_framework": ["vllm", "secret-value"],
                    "artifact_path": "x" * 1200,
                    "base_url": "https://relay.example/v1?api_key=secret-value",
                    "pinned_count": True,
                },
            ],
            "modelCatalog": {
                "schemaVersion": 2,
                "providerCount": 1,
                "modelCount": 0,
                "providers": {
                    "relay_a": {
                        "providerId": "relay_a",
                        "status": "reachable",
                        "modelCount": 1,
                        "models": {
                            "model": {
                                "modelKey": "model",
                                "modelRef": "relay_a/model",
                                "upstreamId": "model",
                                "label": "Model",
                                "availability": "observed",
                                "status": "observed",
                                "capabilities": {
                                    "image_input": {
                                        "value": "supported",
                                        "source": "runtime_probe",
                                        "confidence": "high",
                                        "checked_at": "2026-07-11T10:00:00Z",
                                        "error": "Bearer secret-value",
                                        "rawMetadata": {"token": "secret-value"},
                                        "unknownNested": ["secret-value"],
                                    },
                                    "tool_calling": {
                                        "value": "unsupported",
                                        "source": "provider_endpoint",
                                        "confidence": "medium",
                                        "checked_at": "2026-07-11T09:00:00Z",
                                    },
                                    "reasoning": {
                                        "value": "yes",
                                        "source": "provider_endpoint",
                                    },
                                    "credential_ref": {
                                        "value": "supported",
                                        "source": "operator_override",
                                    },
                                    "raw_payload": {
                                        "value": "unknown",
                                        "source": "runtime_probe",
                                    },
                                },
                                "metadata": {"api_key": "secret-value"},
                                "rawPayload": "pending-secret:token",
                            }
                        },
                        "credential_ref": "env:SECRET",
                        "rawPayload": "pending-secret:token",
                    }
                },
            },
            "impactedRefs": [
                {
                    "modelId": "relay_a/model",
                    "liveReferences": [],
                    "historicalReferences": [],
                    "liveReferenceCount": 0,
                    "historicalReferenceCount": 0,
                    "blocking": False,
                    "rawPayload": "pending-secret:token",
                }
            ],
        }
    )
    option = projected["providerOptions"][0]
    assert option["base_url"] == "https://relay.example/v1"
    assert option["runtime_framework"] == "vllm"
    assert option["artifact_path"] == "C:/models/relay-a"
    assert projected["providerOptions"][1] == {"artifact_path": "x" * 1024}
    model = projected["modelCatalog"]["providers"]["relay_a"]["models"]["model"]
    assert model["capabilities"] == {
        "image_input": {
            "value": "supported",
            "source": "runtime_probe",
            "confidence": "high",
            "checked_at": "2026-07-11T10:00:00Z",
        },
        "tool_calling": {
            "value": "unsupported",
            "source": "provider_endpoint",
            "confidence": "medium",
            "checked_at": "2026-07-11T09:00:00Z",
        },
    }
    serialized = json.dumps(projected)
    assert "credential_ref" not in serialized
    assert "rawPayload" not in serialized
    assert "rawMetadata" not in serialized
    assert "unknownNested" not in serialized
    assert "secret-value" not in serialized
    assert '"query"' not in serialized
    assert '"error"' not in serialized
    assert "pending-secret:" not in serialized


def test_apply_reports_full_observed_pin_count_with_bounded_refs(monkeypatch) -> None:
    saved = _v2_with_provider()
    submitted = copy.deepcopy(saved)
    model_refs = [f"relay_a/observed-{index:02d}" for index in range(55)]
    submitted["llm"]["profiles"] = {
        "primary": {"model_ref": model_refs[0], "overrides": {}},
        **{
            f"profile_{index:02d}": {"model_ref": model_ref, "overrides": {}}
            for index, model_ref in enumerate(model_refs[1:], start=1)
        },
    }
    persisted = {"value": copy.deepcopy(saved)}
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        config_service,
        "load_public_config",
        lambda: copy.deepcopy(persisted["value"]),
    )
    monkeypatch.setattr(
        config_service,
        "save_public_config",
        lambda value: persisted.update(value=copy.deepcopy(value)),
    )
    monkeypatch.setattr(config_service, "reload_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        config_service,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "providers": {
                "relay_a": {
                    "models": {
                        f"observed-{index:02d}": {
                            "upstreamId": f"observed-{index:02d}",
                            "label": f"Observed {index:02d}",
                            "availability": "observed",
                        }
                        for index in range(55)
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    config_service.apply_config_workspace(
        submitted,
        base_config=saved,
        base_hash=public_config_hash(
            config_service._with_config_workspace_defaults(saved)
        ),
    )
    applied = next(
        kwargs["fields"]
        for args, kwargs in events
        if args[1] == "config.workspace.applied"
    )
    assert applied["observedPinCount"] == 55
    assert len(applied["observedPinnedModelRefs"]) == 50
