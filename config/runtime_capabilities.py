from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_config_path

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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_model_capability_cache_path() -> Path:
    override = os.environ.get(MODEL_CAPABILITY_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return resolve_config_path().parent / MODEL_CAPABILITY_CACHE_FILENAME


def load_model_capability_cache(cache_path: Path | None = None) -> dict[str, Any]:
    path = cache_path or get_model_capability_cache_path()
    if not path.exists():
        return {"schemaVersion": 1, "models": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schemaVersion": 1, "models": {}}
    if not isinstance(payload, dict):
        return {"schemaVersion": 1, "models": {}}
    models = payload.get("models")
    if not isinstance(models, dict):
        payload["models"] = {}
    payload.setdefault("schemaVersion", 1)
    return payload


def save_model_capability_cache(payload: dict[str, Any], cache_path: Path | None = None) -> None:
    path = cache_path or get_model_capability_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


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
        normalized["capability_error"] = error
    return normalized


def record_model_image_input_capability(
    model_id: str,
    details: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return {}
    normalized = _normalized_image_input_capability(details)
    payload = load_model_capability_cache(cache_path)
    models = payload.setdefault("models", {})
    if not isinstance(models, dict):
        models = {}
        payload["models"] = models
    model_payload = models.setdefault(normalized_model_id, {})
    if not isinstance(model_payload, dict):
        model_payload = {}
        models[normalized_model_id] = model_payload
    capabilities = model_payload.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
        model_payload["capabilities"] = capabilities
    capabilities["image_input"] = normalized
    now = _utcnow_iso()
    model_payload["updatedAt"] = now
    payload["updatedAt"] = now
    save_model_capability_cache(payload, cache_path)
    return copy.deepcopy(normalized)


def get_model_image_input_capability(model_id: str, *, cache_path: Path | None = None) -> dict[str, Any]:
    payload = load_model_capability_cache(cache_path)
    models = payload.get("models") if isinstance(payload, dict) else {}
    model_payload = models.get(str(model_id or "").strip(), {}) if isinstance(models, dict) else {}
    capabilities = model_payload.get("capabilities", {}) if isinstance(model_payload, dict) else {}
    details = capabilities.get("image_input", {}) if isinstance(capabilities, dict) else {}
    return copy.deepcopy(details) if isinstance(details, dict) else {}


def _has_operator_image_input_capability(entry: dict[str, Any]) -> bool:
    if "supports_image_input" not in entry:
        return False
    source = str(entry.get("capability_source") or "").strip().lower()
    if not source:
        return True
    return source in OPERATOR_CAPABILITY_SOURCES


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
    payload = load_model_capability_cache(cache_path)
    models = payload.get("models") if isinstance(payload, dict) else {}
    if not isinstance(models, dict):
        return updated
    for model_id, entry in model_library.items():
        if not isinstance(entry, dict):
            continue
        if _has_operator_image_input_capability(entry):
            continue
        model_payload = models.get(str(model_id), {})
        capabilities = model_payload.get("capabilities", {}) if isinstance(model_payload, dict) else {}
        details = capabilities.get("image_input", {}) if isinstance(capabilities, dict) else {}
        if not isinstance(details, dict):
            continue
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
