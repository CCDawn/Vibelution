from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from .llm_identity import (
    make_model_key,
    make_model_ref,
    provider_identity_fingerprint,
    split_model_ref,
    validate_provider_id,
)


_PINNED_MODEL_RESERVED_OVERRIDE_FIELDS = frozenset(
    {
        "api_key",
        "api_key_env",
        "credential_ref",
        "enabled",
        "label",
        "model_key",
        "model_ref",
        "provider_id",
        "upstream_id",
    }
)
_CREDENTIAL_FIELDS = frozenset({"api_key", "api_key_env", "credential_ref"})


def _contains_credential_field(value: Any) -> bool:
    pending = [value]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        if isinstance(current, dict):
            if _CREDENTIAL_FIELDS.intersection(current):
                return True
            pending.extend(current.values())
        else:
            pending.extend(current)
    return False


def _providers(public_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    if int(llm.get("schema_version") or 1) != 2:
        raise ValueError("Provider registry mutations require llm.schema_version = 2")
    providers = llm.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("llm.providers must be an object")
    return providers


def _fingerprint(provider: dict[str, Any]) -> str:
    return provider_identity_fingerprint(
        str(provider.get("base_url") or ""),
        str(provider.get("credential_ref") or "none"),
        auth_kind=str(provider.get("auth_kind") or "api_key"),
    )


def suggest_provider_id(provider: dict[str, Any], existing_ids: Iterable[str]) -> str:
    label = str(provider.get("label") or "").strip().lower()
    host = urlsplit(str(provider.get("base_url") or "")).hostname or ""
    service_class = str(provider.get("service_class") or "provider").strip().lower()
    source = label or host.split(".")[0] or service_class
    base = re.sub(r"[^a-z0-9_-]+", "_", source).strip("_") or "provider"
    if not base[0].isalpha():
        base = f"provider_{base}"
    existing = {str(item) for item in existing_ids}
    if base not in existing:
        return validate_provider_id(base[:64])
    return validate_provider_id(f"{base[:55]}_{_fingerprint(provider)[:8]}")


def validate_provider_registry(public_config: dict[str, Any]) -> None:
    fingerprints: dict[str, str] = {}
    for provider_id, provider in _providers(public_config).items():
        validate_provider_id(str(provider_id))
        if not isinstance(provider, dict):
            raise ValueError(f"provider {provider_id} must be an object")
        fingerprint = _fingerprint(provider)
        duplicate = fingerprints.get(fingerprint)
        if duplicate:
            raise ValueError(
                f"provider {provider_id} duplicates active provider {duplicate}"
            )
        fingerprints[fingerprint] = str(provider_id)


def add_llm_provider(
    public_config: dict[str, Any],
    provider_id: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    canonical_id = validate_provider_id(provider_id)
    if canonical_id in providers:
        raise ValueError(f"LLM provider already exists: {canonical_id}")
    providers[canonical_id] = copy.deepcopy(provider)
    providers[canonical_id].setdefault("models", {})
    validate_provider_registry(updated)
    return updated


def update_llm_provider(
    public_config: dict[str, Any],
    provider_id: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    if provider_id not in providers:
        raise ValueError(f"unknown LLM provider: {provider_id}")
    existing_models = copy.deepcopy(providers[provider_id].get("models", {}))
    providers[provider_id] = copy.deepcopy(provider)
    providers[provider_id]["models"] = copy.deepcopy(
        provider.get("models", existing_models)
    )
    validate_provider_registry(updated)
    return updated


def preview_provider_route_replacement(
    public_config: dict[str, Any],
    provider_id: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    existing = _providers(public_config).get(provider_id)
    if not isinstance(existing, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    old_fingerprint = _fingerprint(existing)
    new_fingerprint = _fingerprint(provider)
    model_refs = sorted(
        make_model_ref(provider_id, key) for key in existing.get("models", {})
    )
    return {
        "providerId": provider_id,
        "routeChanged": old_fingerprint != new_fingerprint,
        "oldFingerprint": old_fingerprint,
        "newFingerprint": new_fingerprint,
        "modelRefs": model_refs,
    }


def pin_llm_model(
    public_config: dict[str, Any],
    provider_id: str,
    *,
    upstream_id: str,
    label: str = "",
    model_key: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    resolved_overrides = copy.deepcopy(overrides or {})
    if _PINNED_MODEL_RESERVED_OVERRIDE_FIELDS.intersection(
        resolved_overrides
    ) or _contains_credential_field(resolved_overrides):
        raise ValueError("pinned model overrides contain reserved fields")
    provider = _providers(updated).get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    key = str(model_key or make_model_key(upstream_id)).strip()
    make_model_ref(provider_id, key)
    models = provider.setdefault("models", {})
    if key in models:
        # Idempotent pin: already-fixed models are a no-op success so bulk pin can continue.
        existing = models.get(key)
        if isinstance(existing, dict):
            if label and not str(existing.get("label") or "").strip():
                existing["label"] = str(label or upstream_id)
            if resolved_overrides:
                for override_key, override_value in resolved_overrides.items():
                    if override_key not in existing:
                        existing[override_key] = override_value
            models[key] = existing
        return updated
    models[key] = {
        "upstream_id": str(upstream_id),
        "label": str(label or upstream_id),
        "enabled": True,
        **resolved_overrides,
    }
    return updated


def unpin_llm_model(public_config: dict[str, Any], model_ref: str) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    provider_id, model_key = split_model_ref(model_ref)
    provider = _providers(updated).get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    models = provider.get("models")
    if not isinstance(models, dict):
        raise ValueError("provider models must be an object")
    if model_key not in models:
        raise ValueError("unknown pinned model")
    models.pop(model_key)
    return updated


def delete_llm_provider(
    public_config: dict[str, Any], provider_id: str
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    if provider.get("models"):
        raise ValueError("provider must have no pinned models before deletion")
    providers.pop(provider_id)
    return updated


__all__ = [
    "add_llm_provider",
    "delete_llm_provider",
    "pin_llm_model",
    "preview_provider_route_replacement",
    "suggest_provider_id",
    "unpin_llm_model",
    "update_llm_provider",
    "validate_provider_registry",
]
