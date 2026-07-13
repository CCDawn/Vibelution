"""Provider-scoped derived model catalog state and capability provenance."""

from __future__ import annotations

import copy
import json
import unicodedata
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Any

from .llm_identity import make_model_key, split_model_ref, validate_provider_id
from .paths import resolve_model_catalog_state_path


MODEL_CATALOG_SCHEMA_VERSION = 2
CAPABILITY_SOURCE_PRIORITY = {
    "driver_default": 10,
    "curated_snapshot": 20,
    "provider_endpoint": 30,
    "runtime_probe": 40,
    "operator_override": 50,
}
CAPABILITY_VALUES = {"supported", "unsupported", "unknown"}
CAPABILITY_ERROR_CATEGORIES = {
    "",
    "auth_failed",
    "blocked",
    "other",
    "protocol_mismatch",
    "timeout",
    "unsupported",
}
_PROVIDER_FAILURE_STATUSES = {
    "auth_failed",
    "discovery_failed",
    "stale",
    "protocol_mismatch",
    "blocked",
}
_DISCOVERY_ERROR_CATEGORIES = {
    "auth_failed",
    "blocked",
    "network",
    "other",
    "protocol_mismatch",
    "rate_limited",
    "service_unavailable",
    "timeout",
    "upstream_unavailable",
}
_MAX_WARNINGS = 20
_MAX_WARNING_KEYS = 20
_REASONING_EFFORT_VALUES = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_REASONING_ADAPTERS = {"reasoning_object", "reasoning_effort", "thinking_toggle"}
_REASONING_SOURCES = {"runtime_probe", "operator_override"}


def empty_model_catalog_state() -> dict[str, Any]:
    return {
        "schemaVersion": MODEL_CATALOG_SCHEMA_VERSION,
        "providers": {},
        "metadata": {"legacyCapabilityImportCompleted": False},
    }


def load_model_catalog_state(
    path: str | PathLike[str] | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else resolve_model_catalog_state_path()
    if not target.exists():
        return empty_model_catalog_state()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid model catalog state") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != MODEL_CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported model catalog schema")
    if not isinstance(payload.get("providers"), dict) or not isinstance(payload.get("metadata"), dict):
        raise ValueError("invalid model catalog state")
    return payload


def save_model_catalog_state(
    state: dict[str, Any],
    path: str | PathLike[str] | None = None,
) -> None:
    if not isinstance(state, dict) or state.get("schemaVersion") != MODEL_CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported model catalog schema")
    from core.infrastructure.atomic_io import atomic_write_json

    target = Path(path) if path is not None else resolve_model_catalog_state_path()
    atomic_write_json(target, state, indent=2, sort_keys=True, ensure_ascii=False)


def merge_capability_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for observation in observations:
        field = str(observation.get("field") or "").strip()
        value = str(observation.get("value") or "unknown").strip().lower()
        source = str(observation.get("source") or "driver_default").strip()
        if not field or value not in CAPABILITY_VALUES or source not in CAPABILITY_SOURCE_PRIORITY:
            raise ValueError("invalid capability observation")
        current = merged.get(field)
        if current is None or CAPABILITY_SOURCE_PRIORITY[source] >= CAPABILITY_SOURCE_PRIORITY[current["source"]]:
            merged[field] = {
                "value": value,
                "source": source,
                "confidence": str(observation.get("confidence") or ""),
                "checked_at": str(observation.get("checked_at") or ""),
                "error": classify_capability_error(observation.get("error")),
            }
    return merged


def classify_capability_error(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in CAPABILITY_ERROR_CATEGORIES:
        return raw
    if not raw:
        return ""
    if "not support" in raw or "unsupported" in raw or "no endpoints found" in raw:
        return "unsupported"
    if "unauthor" in raw or "forbidden" in raw or "auth" in raw or "401" in raw or "403" in raw:
        return "auth_failed"
    if "timeout" in raw or "timed out" in raw:
        return "timeout"
    if "protocol" in raw or "schema" in raw or "decode" in raw:
        return "protocol_mismatch"
    if "blocked" in raw or "permission" in raw:
        return "blocked"
    return "other"


def _capability_observations(capabilities: Any, *, default_source: str) -> list[dict[str, Any]]:
    if not isinstance(capabilities, dict):
        return []
    observations: list[dict[str, Any]] = []
    for field, raw in capabilities.items():
        if isinstance(raw, dict):
            supports = raw.get("supports_image_input")
            fallback_value = "supported" if supports is True else "unsupported" if supports is False else "unknown"
            observations.append(
                {
                    "field": str(field),
                    "value": str(raw.get("value") or raw.get("capability_status") or fallback_value),
                    "source": str(raw.get("source") or raw.get("capability_source") or default_source),
                    "confidence": str(raw.get("confidence") or ""),
                    "checked_at": str(raw.get("checked_at") or raw.get("capability_checked_at") or ""),
                    "error": str(raw.get("error") or raw.get("capability_error") or ""),
                }
            )
        elif isinstance(raw, bool):
            observations.append(
                {
                    "field": str(field),
                    "value": "supported" if raw else "unsupported",
                    "source": default_source,
                }
            )
        elif isinstance(raw, str):
            observations.append({"field": str(field), "value": raw, "source": default_source})
    return observations


def _labeled_capability_observations(capabilities: Any, *, source: str) -> list[dict[str, Any]]:
    observations = _capability_observations(capabilities, default_source=source)
    for observation in observations:
        observation["source"] = source
    return observations


def resolve_model_capabilities(
    *,
    operator: dict[str, Any],
    runtime_probe: dict[str, Any],
    provider_metadata: dict[str, Any],
    curated_snapshot: dict[str, Any],
    driver_default: dict[str, Any],
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for capabilities, source in (
        (driver_default, "driver_default"),
        (curated_snapshot, "curated_snapshot"),
        (provider_metadata, "provider_endpoint"),
        (runtime_probe, "runtime_probe"),
        (operator, "operator_override"),
    ):
        observations.extend(_labeled_capability_observations(capabilities, source=source))
    return merge_capability_observations(observations)


def record_discovery_success(
    state: dict[str, Any],
    *,
    provider_id: str,
    provider_fingerprint: str,
    discovered_at: str,
    observed: list[dict[str, Any]],
    pinned: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    provider_key = validate_provider_id(provider_id)
    updated = copy.deepcopy(state)
    providers = updated.setdefault("providers", {})
    previous = providers.get(provider_key, {})
    previous_models = previous.get("models", {}) if isinstance(previous, dict) else {}
    if not isinstance(previous_models, dict):
        previous_models = {}

    models: dict[str, dict[str, Any]] = {}
    observed_upstream_ids: set[str] = set()
    diagnostic_groups: dict[str, dict[str, str]] = {}
    for raw in observed:
        if not isinstance(raw, dict):
            continue
        upstream_id = str(raw.get("upstream_id") or "").strip()
        if not upstream_id:
            continue
        observed_upstream_ids.add(upstream_id)
        model_key = make_model_key(upstream_id)
        diagnostic_key = unicodedata.normalize("NFKC", upstream_id).casefold()
        diagnostic_groups.setdefault(diagnostic_key, {})[upstream_id] = model_key
        pinned_model = pinned.get(model_key, {})
        is_pinned = isinstance(pinned_model, dict) and str(pinned_model.get("upstream_id")) == upstream_id
        prior = previous_models.get(model_key, {})
        if not isinstance(prior, dict):
            prior = {}
        operator_capabilities = pinned_model.get("capabilities", {}) if is_pinned else {}
        capability_observations = [
            *_capability_observations(prior.get("capabilities", {}), default_source="driver_default"),
            *_labeled_capability_observations(raw.get("capabilities", {}), source="provider_endpoint"),
            *_labeled_capability_observations(operator_capabilities, source="operator_override"),
        ]
        verification = (
            copy.deepcopy(prior.get("verification", {}))
            if isinstance(prior.get("verification"), dict)
            else {}
        )
        if verification and verification.get("providerFingerprint") != provider_fingerprint:
            verification["status"] = "stale"
        reasoning_contract = (
            copy.deepcopy(prior.get("reasoningContract", {}))
            if isinstance(prior.get("reasoningContract"), dict)
            else {}
        )
        if reasoning_contract and reasoning_contract.get("providerFingerprint") != provider_fingerprint:
            reasoning_contract["verificationStatus"] = "stale"
        models[model_key] = {
            "upstreamId": upstream_id,
            "label": str(raw.get("label") or upstream_id),
            "availability": "pinned" if is_pinned else "observed",
            "capabilities": merge_capability_observations(capability_observations),
            "limits": copy.deepcopy(raw.get("limits", {})) if isinstance(raw.get("limits", {}), dict) else {},
            "metadataSource": "provider_endpoint",
            "verification": verification,
            "reasoningContract": reasoning_contract,
        }

    for model_key, pinned_model in pinned.items():
        if not isinstance(pinned_model, dict):
            continue
        upstream_id = str(pinned_model.get("upstream_id") or "").strip()
        if not upstream_id or upstream_id in observed_upstream_ids:
            continue
        prior = copy.deepcopy(previous_models.get(model_key, {}))
        if not isinstance(prior, dict):
            prior = {}
        capabilities = merge_capability_observations(
            [
                *_capability_observations(prior.get("capabilities", {}), default_source="driver_default"),
                *_labeled_capability_observations(pinned_model.get("capabilities", {}), source="operator_override"),
            ]
        )
        verification = (
            copy.deepcopy(prior.get("verification", {}))
            if isinstance(prior.get("verification"), dict)
            else {}
        )
        if verification and verification.get("providerFingerprint") != provider_fingerprint:
            verification["status"] = "stale"
        reasoning_contract = (
            copy.deepcopy(prior.get("reasoningContract", {}))
            if isinstance(prior.get("reasoningContract"), dict)
            else {}
        )
        if reasoning_contract and reasoning_contract.get("providerFingerprint") != provider_fingerprint:
            reasoning_contract["verificationStatus"] = "stale"
        models[model_key] = {
            **prior,
            "upstreamId": upstream_id,
            "label": str(pinned_model.get("label") or prior.get("label") or upstream_id),
            "availability": "missing_remote",
            "capabilities": capabilities,
            "verification": verification,
            "reasoningContract": reasoning_contract,
        }

    warnings = []
    for group in diagnostic_groups.values():
        if len(group) < 2:
            continue
        warnings.append(
            {
                "code": "upstream_id_case_collision",
                "modelKeys": sorted(set(group.values()))[:_MAX_WARNING_KEYS],
            }
        )
        if len(warnings) >= _MAX_WARNINGS:
            break
    providers[provider_key] = {
        "providerFingerprint": str(provider_fingerprint),
        "status": "reachable",
        "catalogStale": False,
        "lastAttemptAt": str(discovered_at),
        "lastSuccessAt": str(discovered_at),
        "lastErrorType": "",
        "models": models,
        "warnings": warnings,
    }
    return updated


def record_discovery_failure(
    state: dict[str, Any],
    *,
    provider_id: str,
    attempted_at: str,
    error_type: str,
    status: str | None = None,
) -> dict[str, Any]:
    provider_key = validate_provider_id(provider_id)
    updated = copy.deepcopy(state)
    providers = updated.setdefault("providers", {})
    previous = providers.get(provider_key, {})
    provider = copy.deepcopy(previous) if isinstance(previous, dict) else {}
    previous_success = bool(str(provider.get("lastSuccessAt") or "").strip())
    resolved_status = str(status or ("stale" if previous_success else "discovery_failed")).strip()
    if resolved_status not in _PROVIDER_FAILURE_STATUSES:
        raise ValueError("invalid provider discovery status")
    provider.setdefault("models", {})
    provider.setdefault("warnings", [])
    provider["status"] = resolved_status
    provider["catalogStale"] = previous_success
    provider["lastAttemptAt"] = str(attempted_at)
    provider["lastErrorType"] = _classify_discovery_error_type(error_type, status=resolved_status)
    providers[provider_key] = provider
    return updated


def record_model_verification(
    state: dict[str, Any],
    *,
    model_ref: str,
    provider_fingerprint: str,
    checked_at: str,
    ok: bool,
    error_type: str = "",
    http_status: int | None = None,
) -> dict[str, Any]:
    provider_id, model_key = split_model_ref(model_ref)
    _parse_utc(checked_at)
    normalized_error = "" if ok else str(error_type or "failed").strip().lower()[:64]
    normalized_status = None
    if http_status is not None:
        try:
            candidate = int(http_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid model verification HTTP status") from exc
        if candidate < 100 or candidate > 599:
            raise ValueError("invalid model verification HTTP status")
        normalized_status = candidate

    updated = copy.deepcopy(state)
    providers = updated.setdefault("providers", {})
    provider = providers.setdefault(
        provider_id,
        {
            "status": "not_discovered",
            "catalogStale": False,
            "lastAttemptAt": "",
            "lastSuccessAt": "",
            "lastErrorType": "",
            "models": {},
            "warnings": [],
        },
    )
    models = provider.setdefault("models", {})
    model = models.setdefault(
        model_key,
        {
            "upstreamId": model_key,
            "label": model_key,
            "availability": "pinned",
            "capabilities": {},
        },
    )
    verification = {
        "status": "verified" if ok else "failed",
        "checkedAt": str(checked_at),
        "errorType": normalized_error,
        "httpStatus": normalized_status,
        "providerFingerprint": str(provider_fingerprint),
    }
    model["verification"] = verification
    return updated


def record_model_reasoning_contract(
    state: dict[str, Any],
    *,
    model_ref: str,
    provider_fingerprint: str,
    checked_at: str,
    effort_values: list[str] | tuple[str, ...],
    default_effort: str,
    adapter: str,
    mapping: dict[str, str],
    source: str,
    ok: bool = True,
    error_type: str = "",
) -> dict[str, Any]:
    provider_id, model_key = split_model_ref(model_ref)
    _parse_utc(checked_at)
    normalized_source = str(source or "").strip().lower()
    if normalized_source not in _REASONING_SOURCES:
        raise ValueError("invalid reasoning contract source")
    normalized_values: list[str] = []
    for raw_value in effort_values:
        value = str(raw_value or "").strip().lower()
        if value not in _REASONING_EFFORT_VALUES:
            raise ValueError("invalid reasoning effort value")
        if value not in normalized_values:
            normalized_values.append(value)
    normalized_default = str(default_effort or "").strip().lower()
    normalized_adapter = str(adapter or "").strip().lower()
    normalized_mapping = {
        str(key or "").strip().lower(): str(value or "").strip().lower()
        for key, value in dict(mapping or {}).items()
    }
    if ok:
        if not normalized_values or normalized_default not in normalized_values:
            raise ValueError("reasoning contract requires a valid default")
        if normalized_adapter not in _REASONING_ADAPTERS:
            raise ValueError("invalid reasoning contract adapter")
        if set(normalized_mapping) != set(normalized_values):
            raise ValueError("reasoning contract mapping must cover every effort value")
        allowed_targets = {"on", "off"} if normalized_adapter == "thinking_toggle" else _REASONING_EFFORT_VALUES
        if any(target not in allowed_targets for target in normalized_mapping.values()):
            raise ValueError("invalid reasoning contract mapping target")

    updated = copy.deepcopy(state)
    providers = updated.setdefault("providers", {})
    provider = providers.setdefault(
        provider_id,
        {
            "status": "not_discovered",
            "catalogStale": False,
            "lastAttemptAt": "",
            "lastSuccessAt": "",
            "lastErrorType": "",
            "models": {},
            "warnings": [],
        },
    )
    model = provider.setdefault("models", {}).setdefault(
        model_key,
        {
            "upstreamId": model_key,
            "label": model_key,
            "availability": "pinned",
            "capabilities": {},
        },
    )
    contract = {
        "verificationStatus": "verified" if ok else "failed",
        "providerFingerprint": str(provider_fingerprint),
        "checkedAt": str(checked_at),
        "source": normalized_source,
    }
    if ok:
        contract.update(
            {
                "effortValues": normalized_values,
                "default": normalized_default,
                "adapter": normalized_adapter,
                "map": normalized_mapping,
            }
        )
    else:
        contract["errorType"] = str(error_type or "failed").strip().lower()[:64]
    model["reasoningContract"] = contract
    return updated


def provider_catalog_refresh_due(
    state: dict[str, Any],
    provider_id: str,
    *,
    ttl_seconds: int,
    now: str,
) -> bool:
    if ttl_seconds == 0:
        return False
    providers = state.get("providers", {}) if isinstance(state, dict) else {}
    provider = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    last_attempt = provider.get("lastAttemptAt") if isinstance(provider, dict) else None
    if not str(last_attempt or "").strip():
        return True
    try:
        elapsed = _parse_utc(now) - _parse_utc(str(last_attempt))
    except ValueError:
        return True
    return elapsed.total_seconds() >= ttl_seconds


def import_legacy_capability_cache(
    state: dict[str, Any],
    legacy_payload: dict[str, Any],
    legacy_to_ref: dict[str, str],
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    metadata = updated.setdefault("metadata", {})
    if metadata.get("legacyCapabilityImportCompleted") is True:
        return updated
    providers = updated.setdefault("providers", {})
    legacy_models = legacy_payload.get("models", {}) if isinstance(legacy_payload, dict) else {}
    mapped_models = 0
    imported_fields = 0
    if isinstance(legacy_models, dict):
        for legacy_id, model_ref in legacy_to_ref.items():
            legacy_model = legacy_models.get(legacy_id, {})
            if not isinstance(legacy_model, dict):
                continue
            try:
                provider_id, model_key = split_model_ref(model_ref)
            except ValueError:
                continue
            observations = _labeled_capability_observations(
                legacy_model.get("capabilities", {}),
                source="runtime_probe",
            )
            if not observations:
                continue
            provider = providers.setdefault(provider_id, {"models": {}})
            models = provider.setdefault("models", {})
            model = models.setdefault(model_key, {"upstreamId": model_key, "availability": "unknown"})
            existing = _capability_observations(model.get("capabilities", {}), default_source="driver_default")
            model["capabilities"] = merge_capability_observations([*existing, *observations])
            mapped_models += 1
            imported_fields += len(observations)
    metadata["legacyCapabilityImportCompleted"] = True
    metadata["legacyCapabilityImport"] = {
        "sourceSchemaVersion": legacy_payload.get("schemaVersion") if isinstance(legacy_payload, dict) else None,
        "mappedModels": mapped_models,
        "importedFields": imported_fields,
    }
    return updated


def _parse_utc(value: str) -> datetime:
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _classify_discovery_error_type(value: Any, *, status: str) -> str:
    if status == "auth_failed":
        return "auth_failed"
    raw = str(value or "").strip().lower()
    if raw in _DISCOVERY_ERROR_CATEGORIES:
        return raw
    if "timeout" in raw or "timedout" in raw or "timed out" in raw:
        return "timeout"
    if "connection" in raw or "network" in raw or "dns" in raw:
        return "network"
    if "protocol" in raw or "schema" in raw or "decode" in raw:
        return "protocol_mismatch"
    if "blocked" in raw or "permission" in raw:
        return "blocked"
    return "other"


__all__ = [
    "CAPABILITY_SOURCE_PRIORITY",
    "CAPABILITY_VALUES",
    "CAPABILITY_ERROR_CATEGORIES",
    "MODEL_CATALOG_SCHEMA_VERSION",
    "empty_model_catalog_state",
    "classify_capability_error",
    "import_legacy_capability_cache",
    "load_model_catalog_state",
    "merge_capability_observations",
    "provider_catalog_refresh_due",
    "record_discovery_failure",
    "record_discovery_success",
    "record_model_reasoning_contract",
    "record_model_verification",
    "resolve_model_capabilities",
    "save_model_catalog_state",
]
