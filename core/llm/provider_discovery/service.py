from __future__ import annotations

import copy
import dataclasses
import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config.llm_credentials import resolve_credential_ref
from config.llm_identity import provider_discovery_fingerprint, validate_provider_id
from config.llm_security import validate_llm_provider_target
from config.model_catalog import (
    load_model_catalog_state,
    record_discovery_failure,
    record_discovery_success,
    save_model_catalog_state,
)
from config.paths import resolve_model_catalog_state_path

from .adapters import get_provider_discovery_adapter
from .types import ProviderDiscoveryRequest, ProviderDiscoveryResult, assert_no_credential_taint


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filter_models(result: ProviderDiscoveryResult, discovery: dict[str, Any]) -> ProviderDiscoveryResult:
    include = [str(item) for item in discovery.get("include", []) if str(item)]
    exclude = [str(item) for item in discovery.get("exclude", []) if str(item)]
    models = tuple(
        model
        for model in result.models
        if (not include or any(fnmatch.fnmatchcase(model.upstream_id, pattern) for pattern in include))
        and not any(fnmatch.fnmatchcase(model.upstream_id, pattern) for pattern in exclude)
    )
    return dataclasses.replace(result, models=models)


def discover_provider_models(
    public_config: dict[str, Any],
    provider_id: str,
    *,
    credential_override: str = "",
    catalog_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderDiscoveryResult:
    canonical_provider_id = validate_provider_id(provider_id)
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    provider = providers.get(canonical_provider_id) if isinstance(providers, dict) else None
    if int(llm.get("schema_version") or 1) != 2 or not isinstance(provider, dict):
        raise ValueError(f"unknown schema v2 provider: {canonical_provider_id}")
    validate_llm_provider_target(provider, context="llm.provider.discovery", resolve_dns=True)
    resolution = resolve_credential_ref(str(provider.get("credential_ref") or "none"))
    credential = str(credential_override or resolution.secret)
    if provider.get("requires_credential", True) and not credential:
        raise ValueError("provider credential is missing")
    discovery = provider.get("discovery", {}) if isinstance(provider.get("discovery"), dict) else {}
    adapter_id = str(discovery.get("adapter") or "manual").strip().lower()
    models_url_override = str(discovery.get("models_url_override") or "").strip()
    if models_url_override:
        override_provider = copy.deepcopy(provider)
        override_provider["base_url"] = models_url_override
        validate_llm_provider_target(
            override_provider,
            context="llm.provider.discovery.models_url_override",
            resolve_dns=True,
        )
    adapter = get_provider_discovery_adapter(adapter_id)
    request = ProviderDiscoveryRequest(
        provider_id=canonical_provider_id,
        provider=copy.deepcopy(provider),
        credential=credential,
        timeout_seconds=15.0,
        transport=transport,
    )
    path = catalog_path or resolve_model_catalog_state_path()
    state = load_model_catalog_state(path)
    attempted_at = _utcnow_iso()
    try:
        result = _filter_models(adapter.discover(request), discovery)
        assert_no_credential_taint(dataclasses.asdict(result), credential)
        if adapter_id == "manual":
            return result
        if not result.models:
            raise ValueError("model discovery returned no usable models")
        updated = record_discovery_success(
            state,
            provider_id=canonical_provider_id,
            provider_fingerprint=provider_discovery_fingerprint(provider),
            discovered_at=result.discovered_at,
            observed=[dataclasses.asdict(model) for model in result.models],
            pinned=copy.deepcopy(provider.get("models", {})),
        )
        save_model_catalog_state(updated, path)
        return result
    except Exception as exc:
        status = (
            "auth_failed"
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}
            else ""
        )
        failed = record_discovery_failure(
            state,
            provider_id=canonical_provider_id,
            attempted_at=attempted_at,
            error_type=(
                "timeout"
                if isinstance(exc, httpx.TimeoutException)
                else "network"
                if isinstance(exc, httpx.RequestError)
                else type(exc).__name__
            ),
            status=status,
        )
        save_model_catalog_state(failed, path)
        raise


__all__ = ["discover_provider_models"]
