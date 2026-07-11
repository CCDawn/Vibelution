"""Draft-only Provider registry orchestration for the config workbench."""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from config.llm_credentials import canonicalize_credential_ref
from config.llm_identity import (
    make_model_ref,
    split_model_ref,
    validate_provider_id,
)
from config.llm_provider_registry import (
    add_llm_provider,
    delete_llm_provider,
    pin_llm_model,
    preview_provider_route_replacement,
    suggest_provider_id,
    unpin_llm_model,
    update_llm_provider,
)
from config.model_catalog import load_model_catalog_state
from config.model_config_migration import apply_v1_to_v2, preview_v1_to_v2, rollback_v1_to_v2
from config.public_config import (
    CONFIG_PATH,
    build_effective_config,
    load_public_config,
    validate_llm_public_config,
)
from core.chat.chat_task_types import trim_lines
from core.llm.provider_discovery.service import discover_provider_models

from .config_service import (
    _assert_base_hash_matches,
    _build_workspace,
    _drop_api_key_state,
    _move_pending_api_key_token,
    _normalize_draft_meta,
    _resolve_workspace_language,
    _with_pending_api_key,
)
from .model_reference_service import ModelReferenceConflictError, scan_model_references
from .runtime_scene_service import record_runtime_scene_event


_ROUTE_PREVIEW_SECRET = secrets.token_bytes(32)
_ROUTE_PREVIEW_TTL_SECONDS = 300.0
_ROUTE_PREVIEW_EXPIRY: dict[str, float] = {}
_ROUTE_PREVIEW_LOCK = threading.Lock()
_MAX_IMPACT_REFS = 50
_MAX_REFERENCE_SCAN_MODELS = 1000
_PROVIDER_OPTION_STRING_LIMITS = {
    "artifact_path": 1024,
    "base_url": 1024,
    "credential_state": 64,
    "default_protocol": 128,
    "driver": 64,
    "label": 256,
    "provider_id": 64,
    "runtime_framework": 128,
    "service_class": 64,
    "vendor": 128,
}
_CATALOG_PROVIDER_RESPONSE_FIELDS = (
    "catalogStale",
    "lastAttemptAt",
    "lastErrorType",
    "lastSuccessAt",
    "modelCount",
    "observedCount",
    "pinnedCount",
    "providerId",
    "refreshDue",
    "status",
)
_CATALOG_MODEL_RESPONSE_FIELDS = (
    "availability",
    "label",
    "modelKey",
    "modelRef",
    "status",
    "upstreamId",
)
_CAPABILITY_VALUES = {"supported", "unsupported", "unknown"}
_CAPABILITY_SOURCES = {
    "curated_snapshot",
    "driver_default",
    "operator_override",
    "provider_endpoint",
    "runtime_probe",
}
_MAX_CAPABILITY_FIELDS = 50
_SENSITIVE_CAPABILITY_FIELD_PARTS = (
    "authorization",
    "credential",
    "error",
    "key",
    "metadata",
    "password",
    "query",
    "raw",
    "secret",
    "token",
)
_IMPACT_RESPONSE_FIELDS = (
    "blocking",
    "historicalReferenceCount",
    "liveReferenceCount",
    "modelId",
)
_REFERENCE_RESPONSE_FIELDS = (
    "field",
    "historical",
    "label",
    "ownerId",
    "ownerType",
    "path",
    "source",
    "sourcePath",
)


def _compute_route_preview_token(
    *,
    base_hash: str,
    provider_id: str,
    old_fingerprint: str,
    new_fingerprint: str,
) -> str:
    message = "\0".join(
        (base_hash, provider_id, old_fingerprint, new_fingerprint)
    ).encode("utf-8")
    return hmac.new(_ROUTE_PREVIEW_SECRET, message, hashlib.sha256).hexdigest()


def _issue_route_preview_token(
    *,
    base_hash: str,
    provider_id: str,
    old_fingerprint: str,
    new_fingerprint: str,
) -> str:
    digest = _compute_route_preview_token(
        base_hash=base_hash,
        provider_id=provider_id,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
    )
    with _ROUTE_PREVIEW_LOCK:
        now = time.monotonic()
        for token, expires_at in list(_ROUTE_PREVIEW_EXPIRY.items()):
            if expires_at < now:
                _ROUTE_PREVIEW_EXPIRY.pop(token, None)
        _ROUTE_PREVIEW_EXPIRY[digest] = (
            now + _ROUTE_PREVIEW_TTL_SECONDS
        )
    return digest


def _consume_route_preview_token(token: str, *, expected: str) -> None:
    submitted = str(token or "")
    with _ROUTE_PREVIEW_LOCK:
        expires_at = _ROUTE_PREVIEW_EXPIRY.pop(submitted, 0.0)
    if (
        not hmac.compare_digest(submitted, expected)
        or expires_at < time.monotonic()
    ):
        raise ValueError("route replacement preview is required or expired")


def _record_provider_event(
    event_code: str,
    *,
    provider_id: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    bounded: dict[str, Any] = {
        "providerId": str(provider_id or "")[:64],
    }
    allowed_fields = {
        "adapterId",
        "elapsedMs",
        "errorType",
        "impactedRefCount",
        "modelCount",
        "modelKey",
        "repairSummary",
        "routeChanged",
        "serviceClass",
        "status",
    }
    for key, value in (fields or {}).items():
        if key not in allowed_fields:
            continue
        if key == "repairSummary":
            bounded[key] = trim_lines(str(value or ""), max_lines=2)[:400]
        elif isinstance(value, str):
            bounded[key] = value[:128]
        elif isinstance(value, (bool, int, float)):
            bounded[key] = value
    try:
        record_runtime_scene_event(
            "config",
            "provider_config",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=bounded,
            lifecycle=True,
        )
    except Exception:
        return


def _current_draft(
    public_config: dict[str, Any],
    *,
    base_hash: str,
) -> tuple[dict[str, Any], str]:
    if not str(base_hash or "").strip():
        raise ValueError("baseHash is required")
    saved = load_public_config()
    current_hash = _assert_base_hash_matches(
        base_hash,
        saved,
        _resolve_workspace_language(saved),
    )
    if not isinstance(public_config, dict):
        raise ValueError("publicConfig must be an object")
    return copy.deepcopy(public_config), current_hash


def _validate_draft(public_config: dict[str, Any]) -> None:
    validate_llm_public_config(public_config)
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    has_pinned_models = any(
        isinstance(provider, dict) and bool(provider.get("models"))
        for provider in providers.values()
    ) if isinstance(providers, dict) else False
    if profiles or has_pinned_models:
        build_effective_config(public_config)


def _credential_meta(
    draft_meta: dict[str, Any] | None,
    provider: dict[str, Any],
    credential_value: str,
) -> dict[str, object]:
    meta = _normalize_draft_meta(draft_meta)
    credential_ref = canonicalize_credential_ref(
        str(provider.get("credential_ref") or "none")
    )
    if credential_value and credential_ref.startswith("env:"):
        meta = _with_pending_api_key(
            meta,
            credential_ref.removeprefix("env:"),
            credential_value,
        )
    return meta


def _updated_credential_meta(
    draft_meta: dict[str, Any] | None,
    old_provider: dict[str, Any],
    new_provider: dict[str, Any],
    credential_value: str,
) -> dict[str, object]:
    old_ref = canonicalize_credential_ref(
        str(old_provider.get("credential_ref") or "none")
    )
    new_ref = canonicalize_credential_ref(
        str(new_provider.get("credential_ref") or "none")
    )
    if old_ref == new_ref:
        return _credential_meta(draft_meta, new_provider, credential_value)

    meta = _normalize_draft_meta(draft_meta)
    old_env = old_ref.removeprefix("env:") if old_ref.startswith("env:") else ""
    new_env = new_ref.removeprefix("env:") if new_ref.startswith("env:") else ""
    if credential_value:
        if old_env:
            meta = _drop_api_key_state(meta, old_env)
        return _credential_meta(meta, new_provider, credential_value)

    pending = meta.get("pending_api_keys", {})
    old_token = pending.get(old_env) if isinstance(pending, dict) and old_env else None
    if old_token and new_env:
        meta = _drop_api_key_state(meta, new_env)
        pending = meta.get("pending_api_keys", {})
        if isinstance(pending, dict):
            pending.pop(old_env, None)
            _move_pending_api_key_token(old_token, old_env, new_env)
            pending[new_env] = str(old_token)
        return meta
    if old_env:
        meta = _drop_api_key_state(meta, old_env)
    return meta


def _provider(public_config: dict[str, Any], provider_id: str) -> dict[str, Any]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    return provider


def _owned_provider_model_refs(
    public_config: dict[str, Any], provider_id: str
) -> list[str]:
    refs: set[str] = set()
    provider = _provider(public_config, provider_id)
    models = provider.get("models", {})
    if isinstance(models, dict):
        for model_key in models:
            refs.add(make_model_ref(provider_id, str(model_key)))

    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            model_ref = str(profile.get("model_ref") or "").strip()
            if model_ref.startswith(f"{provider_id}/"):
                refs.add(model_ref)
    tools = public_config.get("tools", {})
    image2 = tools.get("image2", {}) if isinstance(tools, dict) else {}
    image_ref = str(image2.get("default_model_ref") or "").strip() if isinstance(image2, dict) else ""
    if image_ref.startswith(f"{provider_id}/"):
        refs.add(image_ref)
    git = public_config.get("git", {})
    git_ref = str(git.get("commit_message_model_ref") or "").strip() if isinstance(git, dict) else ""
    if git_ref.startswith(f"{provider_id}/"):
        refs.add(git_ref)

    try:
        state = load_model_catalog_state()
    except ValueError:
        state = {}
    catalog_providers = state.get("providers", {}) if isinstance(state, dict) else {}
    catalog_provider = catalog_providers.get(provider_id, {}) if isinstance(catalog_providers, dict) else {}
    catalog_models = catalog_provider.get("models", {}) if isinstance(catalog_provider, dict) else {}
    if isinstance(catalog_models, dict):
        for model_key in catalog_models:
            refs.add(make_model_ref(provider_id, str(model_key)))
    return sorted(refs)


def _bounded_impact(impact: dict[str, Any]) -> dict[str, Any]:
    projected = project_model_reference_impacts([impact])
    return projected[0] if projected else {}


def _scan_impacts(
    public_config: dict[str, Any], model_refs: list[str]
) -> list[dict[str, Any]]:
    if len(model_refs) > _MAX_REFERENCE_SCAN_MODELS:
        raise ValueError("provider reference scan exceeds safety limit")
    impacts: list[dict[str, Any]] = []
    for model_ref in model_refs:
        impact = _bounded_impact(
            scan_model_references(model_ref, public_config=public_config)
        )
        impacts.append(impact)
        if int(impact.get("liveReferenceCount") or 0):
            raise ModelReferenceConflictError(impact)
    return impacts[:_MAX_IMPACT_REFS]


def _workspace_with_impacts(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | dict[str, object] | None,
    base_hash: str,
    impacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workspace = _build_workspace(
        public_config,
        draft_meta=draft_meta,
        base_hash=base_hash,
    )
    workspace["impactedRefs"] = copy.deepcopy((impacts or [])[:_MAX_IMPACT_REFS])
    return workspace


def _allowlisted_fields(
    payload: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in fields:
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, (str, bool, int, float)) and value is not None:
            continue
        if isinstance(value, str) and "pending-secret:" in value:
            projected[key] = "[redacted]"
        else:
            projected[key] = value
    return projected


def _bounded_string(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str) or "pending-secret:" in value:
        return None
    return value[:max_length]


def _project_provider_option(value: Any) -> dict[str, Any]:
    option = value if isinstance(value, dict) else {}
    projected: dict[str, Any] = {}
    for key, max_length in _PROVIDER_OPTION_STRING_LIMITS.items():
        bounded = _bounded_string(option.get(key), max_length=max_length)
        if bounded is None:
            continue
        if key == "base_url" and ("?" in bounded or "#" in bounded):
            continue
        projected[key] = bounded
    pinned_count = option.get("pinned_count")
    if (
        isinstance(pinned_count, int)
        and not isinstance(pinned_count, bool)
        and 0 <= pinned_count <= 1_000_000
    ):
        projected["pinned_count"] = pinned_count
    return projected


def _project_capabilities(value: Any) -> dict[str, Any]:
    capabilities = value if isinstance(value, dict) else {}
    projected: dict[str, Any] = {}
    for raw_field, raw_observation in list(capabilities.items())[
        :_MAX_CAPABILITY_FIELDS
    ]:
        if not isinstance(raw_field, str) or not isinstance(raw_observation, dict):
            continue
        field = raw_field.strip()
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field)
            or any(part in field for part in _SENSITIVE_CAPABILITY_FIELD_PARTS)
        ):
            continue
        observation_value = raw_observation.get("value")
        source = raw_observation.get("source")
        if (
            not isinstance(observation_value, str)
            or observation_value not in _CAPABILITY_VALUES
            or not isinstance(source, str)
            or source not in _CAPABILITY_SOURCES
        ):
            continue
        confidence = _bounded_string(
            raw_observation.get("confidence"),
            max_length=64,
        )
        checked_at = _bounded_string(
            raw_observation.get("checked_at"),
            max_length=64,
        )
        projected[field] = {
            "value": observation_value,
            "source": source,
            "confidence": confidence or "",
            "checked_at": checked_at or "",
        }
    return projected


def _project_model_catalog(value: Any) -> dict[str, Any]:
    catalog = value if isinstance(value, dict) else {}
    raw_providers = catalog.get("providers", {})
    providers: dict[str, Any] = {}
    if isinstance(raw_providers, dict):
        for raw_provider_id, raw_provider in list(raw_providers.items())[:100]:
            if not isinstance(raw_provider, dict):
                continue
            provider_id = _project_provider_id(raw_provider_id)
            if not provider_id:
                continue
            provider = _allowlisted_fields(
                raw_provider,
                _CATALOG_PROVIDER_RESPONSE_FIELDS,
            )
            raw_models = raw_provider.get("models", {})
            provider["models"] = {}
            if isinstance(raw_models, dict):
                for model_key, raw_model in list(raw_models.items())[:500]:
                    if not isinstance(model_key, str) or not isinstance(raw_model, dict):
                        continue
                    try:
                        make_model_ref(provider_id, model_key)
                    except ValueError:
                        continue
                    model = _allowlisted_fields(
                        raw_model,
                        _CATALOG_MODEL_RESPONSE_FIELDS,
                    )
                    model["capabilities"] = _project_capabilities(
                        raw_model.get("capabilities")
                    )
                    provider["models"][model_key[:128]] = model
            raw_warnings = raw_provider.get("warnings", [])
            provider["warnings"] = [
                {
                    "code": str(warning.get("code") or "")[:64],
                    "modelKeys": [
                        str(item)[:128]
                        for item in warning.get("modelKeys", [])[:20]
                    ]
                    if isinstance(warning.get("modelKeys"), list)
                    else [],
                }
                for warning in raw_warnings[:20]
                if isinstance(warning, dict)
            ] if isinstance(raw_warnings, list) else []
            providers[provider_id] = provider
    return {
        "modelCount": int(catalog.get("modelCount") or 0),
        "providerCount": int(catalog.get("providerCount") or 0),
        "providers": providers,
        "schemaVersion": int(catalog.get("schemaVersion") or 2),
    }


def project_model_reference_impacts(value: Any) -> list[dict[str, Any]]:
    impacts = value if isinstance(value, list) else []
    projected: list[dict[str, Any]] = []
    for raw_impact in impacts[:_MAX_IMPACT_REFS]:
        if not isinstance(raw_impact, dict):
            continue
        impact = _allowlisted_fields(raw_impact, _IMPACT_RESPONSE_FIELDS)
        for key in ("liveReferences", "historicalReferences"):
            raw_refs = raw_impact.get(key, [])
            impact[key] = [
                _allowlisted_fields(ref, _REFERENCE_RESPONSE_FIELDS)
                for ref in raw_refs[:_MAX_IMPACT_REFS]
                if isinstance(ref, dict)
            ] if isinstance(raw_refs, list) else []
        projected.append(impact)
    return projected


def project_model_reference_impact(value: Any) -> dict[str, Any]:
    projected = project_model_reference_impacts([value])
    return projected[0] if projected else {}


def _project_provider_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return validate_provider_id(value)
    except ValueError:
        return ""


def _project_model_refs(value: Any, *, provider_id: str) -> list[str]:
    if not isinstance(value, list):
        return []
    projected: list[str] = []
    for raw_ref in value:
        if not isinstance(raw_ref, str) or "pending-secret:" in raw_ref:
            continue
        try:
            ref_provider_id, model_key = split_model_ref(raw_ref)
            canonical = make_model_ref(ref_provider_id, model_key)
        except ValueError:
            continue
        if provider_id and ref_provider_id != provider_id:
            continue
        projected.append(canonical)
        if len(projected) >= _MAX_IMPACT_REFS:
            break
    return projected


def _project_route_preview_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    token = value.strip()
    if not token:
        return ""
    return token if re.fullmatch(r"[0-9a-f]{64}", token) else ""


def project_provider_route_preview_response(
    preview: dict[str, Any],
) -> dict[str, Any]:
    provider_id = _project_provider_id(preview.get("providerId"))
    route_changed = preview.get("routeChanged")
    return {
        "impactedRefs": project_model_reference_impacts(
            preview.get("impactedRefs")
        ),
        "modelRefs": _project_model_refs(
            preview.get("modelRefs"),
            provider_id=provider_id,
        ),
        "providerId": provider_id,
        "routeChanged": route_changed if isinstance(route_changed, bool) else False,
        "routePreviewToken": _project_route_preview_token(
            preview.get("routePreviewToken")
        ),
    }


def project_provider_draft_response(workspace: dict[str, Any]) -> dict[str, Any]:
    """Return the explicit, credential-free HTTP projection for Provider drafts."""

    raw_options = workspace.get("providerOptions", [])
    provider_options = [
        _project_provider_option(option)
        for option in raw_options
        if isinstance(option, dict)
    ] if isinstance(raw_options, list) else []
    return {
        "baseHash": str(workspace.get("baseHash") or ""),
        "hash": str(workspace.get("hash") or ""),
        "impactedRefs": project_model_reference_impacts(
            workspace.get("impactedRefs")
        ),
        "modelCatalog": _project_model_catalog(workspace.get("modelCatalog")),
        "providerOptions": provider_options,
        "schemaVersion": int(workspace.get("schemaVersion") or 1),
    }


def suggest_draft_provider_id(
    public_config: dict[str, Any],
    *,
    base_hash: str,
    provider: dict[str, Any],
) -> dict[str, str]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    llm = current.get("llm", {})
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    existing_ids = providers.keys() if isinstance(providers, dict) else ()
    return {"suggestedProviderId": suggest_provider_id(provider, existing_ids)}


def draft_add_provider(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    provider: dict[str, Any],
    credential_value: str = "",
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    updated = add_llm_provider(current, provider_id, provider)
    _validate_draft(updated)
    meta = _credential_meta(draft_meta, provider, credential_value)
    _record_provider_event(
        "config.provider.created",
        provider_id=provider_id,
        outcome="drafted",
        fields={
            "serviceClass": str(provider.get("service_class") or ""),
            "modelCount": len(provider.get("models", {}))
            if isinstance(provider.get("models"), dict)
            else 0,
        },
    )
    return _workspace_with_impacts(
        updated,
        draft_meta=meta,
        base_hash=base_hash,
    )


def preview_draft_provider_route(
    public_config: dict[str, Any],
    *,
    base_hash: str,
    provider_id: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    preview = preview_provider_route_replacement(current, provider_id, provider)
    model_refs = [str(item) for item in preview.get("modelRefs", [])]
    if len(model_refs) > _MAX_REFERENCE_SCAN_MODELS:
        raise ValueError("provider reference scan exceeds safety limit")
    impacts = [
        _bounded_impact(scan_model_references(model_ref, public_config=current))
        for model_ref in model_refs
    ]
    token = ""
    if preview.get("routeChanged"):
        token = _issue_route_preview_token(
            base_hash=base_hash,
            provider_id=provider_id,
            old_fingerprint=str(preview.get("oldFingerprint") or ""),
            new_fingerprint=str(preview.get("newFingerprint") or ""),
        )
    _record_provider_event(
        "config.provider.route_replacement_previewed",
        provider_id=provider_id,
        outcome="previewed",
        fields={
            "routeChanged": bool(preview.get("routeChanged")),
            "impactedRefCount": sum(
                int(impact.get("liveReferenceCount") or 0) for impact in impacts
            ),
        },
    )
    return {
        "providerId": provider_id,
        "routeChanged": bool(preview.get("routeChanged")),
        "routePreviewToken": token,
        "modelRefs": model_refs[:_MAX_IMPACT_REFS],
        "impactedRefs": project_model_reference_impacts(impacts),
    }


def draft_update_provider(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    provider: dict[str, Any],
    credential_value: str = "",
    route_preview_token: str = "",
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    current_provider = _provider(current, provider_id)
    provider_payload = copy.deepcopy(provider)
    provider_payload["models"] = copy.deepcopy(current_provider.get("models", {}))
    preview = preview_provider_route_replacement(
        current,
        provider_id,
        provider_payload,
    )
    updated = update_llm_provider(current, provider_id, provider_payload)
    _validate_draft(updated)
    if preview.get("routeChanged"):
        expected = _compute_route_preview_token(
            base_hash=base_hash,
            provider_id=provider_id,
            old_fingerprint=str(preview.get("oldFingerprint") or ""),
            new_fingerprint=str(preview.get("newFingerprint") or ""),
        )
        _consume_route_preview_token(route_preview_token, expected=expected)
    meta = _updated_credential_meta(
        draft_meta,
        current_provider,
        provider_payload,
        credential_value,
    )
    _record_provider_event(
        "config.provider.updated",
        provider_id=provider_id,
        outcome="drafted",
        fields={
            "routeChanged": bool(preview.get("routeChanged")),
            "modelCount": len(_provider(updated, provider_id).get("models", {})),
        },
    )
    return _workspace_with_impacts(
        updated,
        draft_meta=meta,
        base_hash=base_hash,
    )


def draft_delete_provider(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    provider = _provider(current, provider_id)
    if provider.get("models"):
        raise ValueError("provider must have no pinned models before deletion")
    impacts = _scan_impacts(
        current,
        _owned_provider_model_refs(current, provider_id),
    )
    updated = delete_llm_provider(current, provider_id)
    _validate_draft(updated)
    meta = _normalize_draft_meta(draft_meta)
    credential_ref = canonicalize_credential_ref(
        str(provider.get("credential_ref") or "none")
    )
    if credential_ref.startswith("env:"):
        meta = _drop_api_key_state(
            meta,
            credential_ref.removeprefix("env:"),
        )
    _record_provider_event(
        "config.provider.deleted",
        provider_id=provider_id,
        outcome="drafted",
        fields={"impactedRefCount": 0},
    )
    return _workspace_with_impacts(
        updated,
        draft_meta=meta,
        base_hash=base_hash,
        impacts=impacts,
    )


def draft_pin_provider_model(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    upstream_id: str,
    model_key: str = "",
    label: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    updated = pin_llm_model(
        current,
        provider_id,
        upstream_id=upstream_id,
        model_key=model_key,
        label=label,
        overrides=overrides,
    )
    _validate_draft(updated)
    resolved_models = _provider(updated, provider_id).get("models", {})
    resolved_key = next(
        (
            str(key)
            for key, model in resolved_models.items()
            if isinstance(model, dict)
            and str(model.get("upstream_id") or "") == str(upstream_id)
        ),
        str(model_key or ""),
    )
    _record_provider_event(
        "config.model.pinned",
        provider_id=provider_id,
        outcome="drafted",
        fields={"modelKey": resolved_key, "modelCount": 1},
    )
    return _workspace_with_impacts(
        updated,
        draft_meta=draft_meta,
        base_hash=base_hash,
    )


def draft_unpin_provider_model(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    model_key: str,
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    model_ref = make_model_ref(provider_id, model_key)
    impact = _bounded_impact(
        scan_model_references(model_ref, public_config=current)
    )
    if int(impact.get("liveReferenceCount") or 0):
        raise ModelReferenceConflictError(impact)
    updated = unpin_llm_model(current, model_ref)
    _validate_draft(updated)
    _record_provider_event(
        "config.model.unpinned",
        provider_id=provider_id,
        outcome="drafted",
        fields={"modelKey": model_key, "impactedRefCount": 0},
    )
    return _workspace_with_impacts(
        updated,
        draft_meta=draft_meta,
        base_hash=base_hash,
        impacts=[impact],
    )


def discover_draft_provider(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    credential_value: str = "",
) -> dict[str, Any]:
    current, _ = _current_draft(public_config, base_hash=base_hash)
    _provider(current, provider_id)
    started_at = time.monotonic()
    try:
        result = discover_provider_models(
            current,
            provider_id,
            credential_override=str(credential_value or ""),
        )
    except Exception as exc:
        _record_provider_event(
            "config.provider.discovery_failed",
            provider_id=provider_id,
            outcome="failed",
            level="warning",
            fields={
                "elapsedMs": int((time.monotonic() - started_at) * 1000),
                "errorType": type(exc).__name__,
                "status": "failed",
            },
        )
        raise ValueError("provider discovery failed") from None
    _record_provider_event(
        "config.provider.discovery_succeeded",
        provider_id=provider_id,
        outcome="succeeded",
        fields={
            "adapterId": str(result.adapter_id or ""),
            "elapsedMs": int((time.monotonic() - started_at) * 1000),
            "modelCount": len(result.models),
            "status": "succeeded",
        },
    )
    return _workspace_with_impacts(
        current,
        draft_meta=draft_meta,
        base_hash=base_hash,
    )


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SAFE_MIGRATION_ROLLBACK_ERRORS = frozenset(
    {
        "unknown migration id",
        "migration is not rollback eligible",
        "stale config hash",
        "invalid migration manifest",
        "migration backup hash mismatch",
        "migration target hash drift",
    }
)


def _record_migration_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "config",
            "model_config_migration",
            event_code,
            message=event_code,
            outcome=outcome,
            level="warning" if outcome == "failed" else "info",
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return


def preview_llm_v2_migration() -> dict[str, Any]:
    started = time.monotonic()
    preview = preview_v1_to_v2(load_public_config(), project_root=_PROJECT_ROOT)
    payload = {
        "previewId": preview.preview_id,
        "baseHash": preview.base_hash,
        "status": preview.status,
        "providers": list(preview.providers),
        "modelRefMap": dict(preview.model_ref_map),
        "referenceImpact": copy.deepcopy(preview.reference_impact),
        "conflicts": list(preview.conflicts),
    }
    _record_migration_event(
        "config.schema.migration_previewed",
        outcome="previewed",
        fields={
            "migrationId": preview.preview_id,
            "providerCount": len(preview.providers),
            "modelCount": len(preview.model_ref_map),
            "referenceCount": int(preview.reference_impact.get("liveReferenceCount") or 0),
            "phase": "preview",
            "elapsedMs": int((time.monotonic() - started) * 1000),
        },
    )
    return payload


def project_llm_v2_migration_preview(payload: dict[str, Any]) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for raw in payload.get("providers", []):
        if not isinstance(raw, dict):
            continue
        models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
        provider_id = str(raw.get("provider_id") or "")
        providers.append(
            {
                "providerId": provider_id,
                "label": str(raw.get("label") or ""),
                "serviceClass": str(raw.get("service_class") or ""),
                "vendor": str(raw.get("vendor") or ""),
                "driver": str(raw.get("driver") or ""),
                "baseUrl": str(raw.get("base_url") or ""),
                "credentialState": str(raw.get("credential_state") or "unknown"),
                "modelRefs": [make_model_ref(provider_id, str(key)) for key in sorted(models)] if provider_id else [],
            }
        )
    conflicts: list[dict[str, Any]] = []
    for raw in payload.get("conflicts", []):
        if not isinstance(raw, dict):
            continue
        projected = {
            key: copy.deepcopy(raw[key])
            for key in ("code", "severity", "modelId", "fields", "proposedProviderId")
            if key in raw
        }
        conflicts.append(projected)
    impact = payload.get("referenceImpact") if isinstance(payload.get("referenceImpact"), dict) else {}
    return {
        "previewId": str(payload.get("previewId") or ""),
        "baseHash": str(payload.get("baseHash") or ""),
        "status": str(payload.get("status") or ""),
        "providers": providers,
        "modelRefMap": {
            str(key): str(value)
            for key, value in (payload.get("modelRefMap") or {}).items()
        }
        if isinstance(payload.get("modelRefMap"), dict)
        else {},
        "referenceImpact": {
            "liveReferenceCount": int(impact.get("liveReferenceCount") or 0),
            "historicalReferenceCount": int(impact.get("historicalReferenceCount") or 0),
        },
        "conflicts": conflicts,
    }


def apply_llm_v2_migration(*, preview_id: str, base_hash: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = apply_v1_to_v2(
            preview_id,
            expected_base_hash=base_hash,
            config_path=CONFIG_PATH,
            project_root=_PROJECT_ROOT,
        )
    except Exception as exc:
        _record_migration_event(
            "config.schema.migration_applied",
            outcome="failed",
            fields={
                "migrationId": str(preview_id),
                "phase": "apply",
                "elapsedMs": int((time.monotonic() - started) * 1000),
                "errorType": type(exc).__name__,
            },
        )
        raise
    _record_migration_event(
        "config.schema.migration_applied",
        outcome="applied",
        fields={
            "migrationId": result["migrationId"],
            "referenceCount": int(result.get("updatedReferenceCount") or 0),
            "phase": "apply",
            "elapsedMs": int((time.monotonic() - started) * 1000),
        },
    )
    if int(result.get("updatedReferenceCount") or 0):
        _record_migration_event(
            "config.model_reference.migrated",
            outcome="applied",
            fields={
                "migrationId": result["migrationId"],
                "referenceCount": int(result["updatedReferenceCount"]),
                "phase": "apply",
                "elapsedMs": int((time.monotonic() - started) * 1000),
            },
        )
    return result


def rollback_llm_v2_migration(*, migration_id: str, base_hash: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = rollback_v1_to_v2(
            migration_id,
            config_path=CONFIG_PATH,
            project_root=_PROJECT_ROOT,
            expected_current_hash=base_hash,
        )
    except Exception as exc:
        _record_migration_event(
            "config.schema.migration_rolled_back",
            outcome="failed",
            fields={
                "migrationId": migration_id,
                "phase": "rollback",
                "errorType": type(exc).__name__,
                "elapsedMs": int((time.monotonic() - started) * 1000),
            },
        )
        if isinstance(exc, ValueError) and str(exc) in _SAFE_MIGRATION_ROLLBACK_ERRORS:
            raise
        raise RuntimeError("migration rollback failed") from None
    _record_migration_event(
        "config.schema.migration_rolled_back",
        outcome="rolled_back",
        fields={
            "migrationId": migration_id,
            "phase": "rollback",
            "elapsedMs": int((time.monotonic() - started) * 1000),
        },
    )
    return result


__all__ = [
    "discover_draft_provider",
    "draft_add_provider",
    "draft_delete_provider",
    "draft_pin_provider_model",
    "draft_unpin_provider_model",
    "draft_update_provider",
    "preview_draft_provider_route",
    "apply_llm_v2_migration",
    "preview_llm_v2_migration",
    "project_llm_v2_migration_preview",
    "project_model_reference_impact",
    "project_model_reference_impacts",
    "project_provider_draft_response",
    "project_provider_route_preview_response",
    "suggest_draft_provider_id",
    "rollback_llm_v2_migration",
]
