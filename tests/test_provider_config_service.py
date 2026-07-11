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
                        }
                    },
                }
            },
        },
    )
    summary = config_service._provider_workspace_fields(config)["modelCatalog"]
    assert summary["providers"]["relay_a"]["status"] == "protocol_mismatch"
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
                    "credential_state": "configured",
                    "credential_ref": "env:SECRET",
                }
            ],
            "modelCatalog": {
                "schemaVersion": 2,
                "providerCount": 1,
                "modelCount": 0,
                "providers": {
                    "relay_a": {
                        "providerId": "relay_a",
                        "status": "reachable",
                        "modelCount": 0,
                        "models": {},
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
    serialized = json.dumps(projected)
    assert "credential_ref" not in serialized
    assert "rawPayload" not in serialized
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
