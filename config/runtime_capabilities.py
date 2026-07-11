"""Compatibility adapter for runtime capability observations.

Runtime observations are persisted only in the provider-scoped model catalog.
The legacy cache filename and environment override remain readable compatibility
surfaces for callers and the one-time import path.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm_identity import make_model_key, split_model_ref
from .model_catalog import (
    import_legacy_capability_cache,
    load_model_catalog_state,
    merge_capability_observations,
    save_model_catalog_state,
)
from .paths import resolve_config_path, resolve_model_catalog_state_path


MODEL_CAPABILITY_CACHE_ENV = "VIBELUTION_MODEL_CAPABILITY_CACHE"
MODEL_CAPABILITY_CACHE_FILENAME = "model-capabilities.json"
RUNTIME_CAPABILITY_SOURCE = "runtime_probe"
RUNTIME_MODEL_CAPABILITY_FIELDS = (
    "supports_image_input",
    "capability_status",
    "capability_source",
    "capability_checked_at",
    "capability_error",
)
OPERATOR_CAPABILITY_SOURCES = {"manual", "manual_config", "operator", "operator_config"}
_LEGACY_PROVIDER_ID = "legacy"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_model_capability_cache_path() -> Path:
    """Return the legacy cache location for compatibility and one-time import."""

    override = os.environ.get(MODEL_CAPABILITY_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return resolve_config_path().parent / MODEL_CAPABILITY_CACHE_FILENAME


def _catalog_path(cache_path: Path | None = None) -> Path:
    if cache_path is not None:
        return resolve_model_catalog_state_path(cache_path)
    if os.environ.get(MODEL_CAPABILITY_CACHE_ENV, "").strip():
        return resolve_model_catalog_state_path(get_model_capability_cache_path())
    return resolve_model_catalog_state_path()


def load_model_capability_cache(cache_path: Path | None = None) -> dict[str, Any]:
    """Compatibility alias that now loads the canonical catalog envelope."""

    return load_model_catalog_state(_catalog_path(cache_path))


def save_model_capability_cache(payload: dict[str, Any], cache_path: Path | None = None) -> None:
    """Compatibility alias that writes only the canonical catalog envelope."""

    save_model_catalog_state(payload, _catalog_path(cache_path))


def _load_legacy_capability_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": 1, "models": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": 1, "models": {}}
    if not isinstance(payload, dict) or payload.get("schemaVersion", 1) != 1:
        return {"schemaVersion": 1, "models": {}}
    models = payload.get("models")
    if not isinstance(models, dict):
        payload["models"] = {}
    return payload


def _normalized_image_input_capability(details: dict[str, Any]) -> dict[str, Any]:
    supports = details.get("supports_image_input")
    status = str(details.get("capability_status") or "").strip().lower()
    if status not in {"supported", "unsupported", "unknown"}:
        status = "supported" if supports is True else "unsupported" if supports is False else "unknown"
    normalized: dict[str, Any] = {
        "capability_status": status,
        "capability_source": RUNTIME_CAPABILITY_SOURCE,
        "capability_checked_at": str(details.get("capability_checked_at") or "").strip() or _utcnow_iso(),
    }
    if supports is not None:
        normalized["supports_image_input"] = bool(supports)
    error = str(details.get("capability_error") or "").strip()
    if error:
        normalized["capability_error"] = error[:240]
    return normalized


def _catalog_location(model_ref: str) -> tuple[str, str]:
    value = str(model_ref or "").strip()
    if not value:
        raise ValueError("model_ref is required")
    if "/" in value:
        return split_model_ref(value)
    return _LEGACY_PROVIDER_ID, make_model_key(value)


def _catalog_capability(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": "image_input",
        "value": normalized["capability_status"],
        "source": RUNTIME_CAPABILITY_SOURCE,
        "checked_at": normalized["capability_checked_at"],
        "error": str(normalized.get("capability_error") or ""),
    }


def record_model_image_input_capability(
    model_id: str,
    details: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return {}
    provider_id, model_key = _catalog_location(normalized_model_id)
    normalized = _normalized_image_input_capability(details)
    path = _catalog_path(cache_path)
    state = load_model_catalog_state(path)
    provider = state.setdefault("providers", {}).setdefault(provider_id, {"models": {}})
    models = provider.setdefault("models", {})
    model = models.setdefault(
        model_key,
        {
            "upstreamId": model_key if provider_id != _LEGACY_PROVIDER_ID else normalized_model_id,
            "availability": "unknown",
        },
    )
    existing = model.get("capabilities", {})
    observations = []
    if isinstance(existing, dict):
        for field, raw in existing.items():
            if isinstance(raw, dict):
                observations.append(
                    {
                        "field": field,
                        "value": raw.get("value", "unknown"),
                        "source": raw.get("source", "driver_default"),
                        "confidence": raw.get("confidence", ""),
                        "checked_at": raw.get("checked_at", ""),
                        "error": raw.get("error", ""),
                    }
                )
    model["capabilities"] = merge_capability_observations([*observations, _catalog_capability(normalized)])
    model["updatedAt"] = normalized["capability_checked_at"]
    state["updatedAt"] = normalized["capability_checked_at"]
    save_model_catalog_state(state, path)
    return copy.deepcopy(normalized)


def _legacy_details(record: dict[str, Any]) -> dict[str, Any]:
    value = str(record.get("value") or "unknown")
    details: dict[str, Any] = {
        "capability_status": value,
        "capability_source": str(record.get("source") or ""),
        "capability_checked_at": str(record.get("checked_at") or ""),
    }
    if value in {"supported", "unsupported"}:
        details["supports_image_input"] = value == "supported"
    error = str(record.get("error") or "")
    if error:
        details["capability_error"] = error
    return details


def _capability_record(state: dict[str, Any], model_ref: str) -> dict[str, Any]:
    try:
        provider_id, model_key = _catalog_location(model_ref)
    except ValueError:
        return {}
    providers = state.get("providers", {}) if isinstance(state, dict) else {}
    provider = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    models = provider.get("models", {}) if isinstance(provider, dict) else {}
    model = models.get(model_key, {}) if isinstance(models, dict) else {}
    capabilities = model.get("capabilities", {}) if isinstance(model, dict) else {}
    record = capabilities.get("image_input", {}) if isinstance(capabilities, dict) else {}
    return record if isinstance(record, dict) else {}


def get_model_image_input_capability(model_id: str, *, cache_path: Path | None = None) -> dict[str, Any]:
    state = load_model_catalog_state(_catalog_path(cache_path))
    record = _capability_record(state, str(model_id or "").strip())
    return _legacy_details(record) if record else {}


def _has_operator_image_input_capability(entry: dict[str, Any]) -> bool:
    if "supports_image_input" not in entry:
        return False
    source = str(entry.get("capability_source") or "").strip().lower()
    if not source:
        return True
    return source in OPERATOR_CAPABILITY_SOURCES


def _legacy_to_canonical_refs(public_config: dict[str, Any]) -> dict[str, str]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    aliases = llm.get("model_aliases", {}) if isinstance(llm, dict) else {}
    mapping: dict[str, str] = {}
    if not isinstance(model_library, dict):
        return mapping
    for model_ref in model_library:
        value = str(model_ref)
        if "/" in value:
            try:
                split_model_ref(value)
            except ValueError:
                continue
            mapping[value] = value
    if not isinstance(aliases, dict):
        return mapping
    for legacy_id in aliases:
        current = str(legacy_id)
        visited: set[str] = set()
        while current in aliases and current not in visited:
            visited.add(current)
            current = str(aliases[current] or "").strip()
        if current in mapping:
            mapping[str(legacy_id)] = current
    return mapping


def _load_catalog_with_legacy_import(public_config: dict[str, Any], *, cache_path: Path | None) -> dict[str, Any]:
    path = _catalog_path(cache_path)
    state = load_model_catalog_state(path)
    metadata = state.get("metadata", {})
    if cache_path is not None:
        return state
    if isinstance(metadata, dict) and metadata.get("legacyCapabilityImportCompleted") is True:
        return state
    legacy = _load_legacy_capability_cache(get_model_capability_cache_path())
    imported = import_legacy_capability_cache(state, legacy, _legacy_to_canonical_refs(public_config))
    save_model_catalog_state(imported, path)
    return imported


def apply_model_capability_overrides(
    public_config: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    llm = updated.get("llm", {}) if isinstance(updated, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    if not isinstance(model_library, dict):
        return updated
    state = _load_catalog_with_legacy_import(updated, cache_path=cache_path)
    for model_id, entry in model_library.items():
        if not isinstance(entry, dict) or _has_operator_image_input_capability(entry):
            continue
        record = _capability_record(state, str(model_id))
        if not record:
            continue
        details = _legacy_details(record)
        for field in RUNTIME_MODEL_CAPABILITY_FIELDS:
            if field in details:
                entry[field] = copy.deepcopy(details[field])
    return updated


def strip_runtime_model_capability_fields(public_config: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    llm = updated.get("llm", {}) if isinstance(updated, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    if not isinstance(model_library, dict):
        return updated
    for entry in model_library.values():
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("capability_source") or "").strip().lower()
        if source == RUNTIME_CAPABILITY_SOURCE:
            for field in RUNTIME_MODEL_CAPABILITY_FIELDS:
                entry.pop(field, None)
            continue
        entry.pop("capability_checked_at", None)
        entry.pop("capability_error", None)
    return updated


__all__ = [
    "MODEL_CAPABILITY_CACHE_ENV",
    "MODEL_CAPABILITY_CACHE_FILENAME",
    "OPERATOR_CAPABILITY_SOURCES",
    "RUNTIME_CAPABILITY_SOURCE",
    "RUNTIME_MODEL_CAPABILITY_FIELDS",
    "apply_model_capability_overrides",
    "get_model_capability_cache_path",
    "get_model_image_input_capability",
    "load_model_capability_cache",
    "record_model_image_input_capability",
    "save_model_capability_cache",
    "strip_runtime_model_capability_fields",
]
