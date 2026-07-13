"""Read-only projection of configured and observed Provider models for Agents."""

from __future__ import annotations

import re
from typing import Any

from config.llm_credentials import resolve_credential_ref
from config.llm_identity import make_model_ref, provider_discovery_fingerprint
from config.model_catalog import load_model_catalog_state, resolve_model_capabilities
from config.public_config import load_public_config, public_config_hash
from core.llm.reasoning_effort import normalize_reasoning_effort


_AGENT_LLM_SLOTS = (
    "dialogue",
    "mentalModel",
    "summary",
    "subagentPlanning",
    "subagentExecution",
    "vision",
)
_NON_DIALOGUE_CONTRACTS = {
    "audio",
    "audio_generation",
    "embedding",
    "image_generation",
    "moderation",
    "realtime",
    "rerank",
    "speech",
    "transcription",
    "video_generation",
}
_NON_DIALOGUE_CAPABILITIES = (
    "audio_generation",
    "embedding",
    "image_generation",
    "moderation",
    "realtime",
    "rerank",
    "speech",
    "transcription",
    "video_generation",
)
_NON_DIALOGUE_MODEL_PATTERN = re.compile(
    r"(?:^|[-_/.])(?:audio|dall-e|embedding|gpt-image|imagen|moderation|realtime|rerank|"
    r"sora|speech|stable-diffusion|tts|video|whisper)(?:$|[-_/.])",
    re.IGNORECASE,
)
_REASONING_EFFORT_LABELS = {
    "none": "无",
    "minimal": "最小",
    "low": "低",
    "medium": "中",
    "high": "高",
    "xhigh": "超高",
    "max": "最大",
    "ultra": "极高",
}
_REASONING_EFFORT_DESCRIPTIONS = {
    "minimal": "最快响应",
    "low": "更快响应，适合直接问题",
    "medium": "平衡速度与推理深度",
    "high": "更深推理，适合复杂任务",
    "xhigh": "最大推理深度",
}


def reasoning_effort_options(values: list[str]) -> list[dict[str, str]]:
    """Return stable display metadata for a confirmed reasoning contract."""

    return [
        {
            "value": value,
            "label": _REASONING_EFFORT_LABELS.get(value, value),
            "description": _REASONING_EFFORT_DESCRIPTIONS.get(value, ""),
        }
        for value in values
    ]


def project_reasoning_contract(
    pinned: dict[str, Any],
    observed: dict[str, Any],
    *,
    current_provider_fingerprint: str,
) -> dict[str, Any]:
    """Project only operator-confirmed or current verified reasoning evidence."""

    defaults = pinned.get("defaults") if isinstance(pinned.get("defaults"), dict) else {}
    capabilities = pinned.get("capabilities") if isinstance(pinned.get("capabilities"), dict) else {}
    observed_contract = (
        observed.get("reasoningContract")
        if isinstance(observed.get("reasoningContract"), dict)
        else {}
    )
    observed_verified = (
        str(observed_contract.get("verificationStatus") or "").strip().lower() == "verified"
        and str(observed_contract.get("providerFingerprint") or "") == current_provider_fingerprint
    )
    operator_values = defaults.get("reasoning_effort_values") or capabilities.get(
        "reasoning_effort_values"
    )
    raw_values = operator_values or (
        observed_contract.get("effortValues") if observed_verified else []
    )
    values: list[str] = []
    for raw_value in raw_values if isinstance(raw_values, (list, tuple)) else []:
        normalized = normalize_reasoning_effort(raw_value)
        if normalized and normalized not in values:
            values.append(normalized)

    if operator_values:
        source = "operator_override"
    elif observed_verified:
        source = str(observed_contract.get("source") or "unknown").strip() or "unknown"
    else:
        source = "unknown"
    requested_default = normalize_reasoning_effort(
        defaults.get("default_reasoning_effort")
        or (observed_contract.get("default") if observed_verified else "")
    )
    adapter = str(
        defaults.get("reasoning_effort_adapter")
        or (observed_contract.get("adapter") if observed_verified else "")
        or "none"
    ).strip()
    raw_mapping = defaults.get("reasoning_effort_map") or (
        observed_contract.get("map") if observed_verified else {}
    )
    mapping = (
        {
            str(key): str(value)
            for key, value in raw_mapping.items()
            if str(key).strip() and str(value).strip()
        }
        if isinstance(raw_mapping, dict)
        else {}
    )
    return {
        "supportsReasoningEffort": bool(values),
        "reasoningEffortValues": values,
        "reasoningEffortOptions": reasoning_effort_options(values),
        "defaultReasoningEffort": (
            requested_default if requested_default in values else (values[0] if values else "")
        ),
        "reasoningAdapter": adapter if values else "none",
        "reasoningEffortMap": mapping if values else {},
        "reasoningDefaultSource": source,
        "capabilityStatus": (
            "confirmed"
            if source == "operator_override" and values
            else "verified"
            if observed_verified and values
            else "unknown"
        ),
        "capabilitySource": source,
    }


def _capability_value(capabilities: Any, field: str) -> str:
    if not isinstance(capabilities, dict):
        return "unknown"
    raw = capabilities.get(field)
    if isinstance(raw, dict):
        raw = raw.get("value") or raw.get("capability_status")
    if isinstance(raw, bool):
        return "supported" if raw else "unsupported"
    value = str(raw or "unknown").strip().lower()
    return value if value in {"supported", "unsupported", "unknown"} else "unknown"


def _resolved_slot_capability(
    pinned: dict[str, Any],
    observed: dict[str, Any],
    field: str,
) -> str:
    pinned_capabilities = pinned.get("capabilities") if isinstance(pinned.get("capabilities"), dict) else {}
    if field in pinned_capabilities:
        return _capability_value(pinned_capabilities, field)
    observed_capabilities = (
        observed.get("capabilities") if isinstance(observed.get("capabilities"), dict) else {}
    )
    return _capability_value(observed_capabilities, field)


def _is_non_dialogue_model(
    upstream_id: str,
    pinned: dict[str, Any],
    observed: dict[str, Any],
) -> bool:
    contract = str(
        pinned.get("interaction_contract")
        or pinned.get("model_type")
        or observed.get("interactionContract")
        or observed.get("modelType")
        or ""
    ).strip().lower()
    if contract in _NON_DIALOGUE_CONTRACTS:
        return True
    if _resolved_slot_capability(pinned, observed, "text_output") == "unsupported":
        return True
    if any(
        _resolved_slot_capability(pinned, observed, capability) == "supported"
        for capability in _NON_DIALOGUE_CAPABILITIES
    ):
        return True
    # This is a conservative slot-safety classification only. It never writes a
    # confirmed capability or reasoning contract into the candidate DTO.
    return bool(_NON_DIALOGUE_MODEL_PATTERN.search(str(upstream_id or "").strip()))


def project_slot_compatibility(
    upstream_id: str,
    pinned: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Project stable slot decisions without promoting catalog observations."""

    non_dialogue = _is_non_dialogue_model(upstream_id, pinned, observed)
    image_input = _resolved_slot_capability(pinned, observed, "image_input")
    result: dict[str, dict[str, Any]] = {}
    for slot in _AGENT_LLM_SLOTS:
        if non_dialogue:
            result[slot] = {"allowed": False, "reasonCode": "non_dialogue_model"}
        elif slot == "vision" and image_input != "supported":
            result[slot] = {
                "allowed": False,
                "reasonCode": (
                    "image_input_unsupported"
                    if image_input == "unsupported"
                    else "image_input_unknown"
                ),
            }
        else:
            result[slot] = {"allowed": True, "reasonCode": ""}
    return result


def _provider_credential_compatibility(provider: dict[str, Any]) -> dict[str, Any]:
    credential_ref = str(provider.get("credential_ref") or "none").strip()
    resolution = resolve_credential_ref(credential_ref)
    requires = bool(provider.get("requires_credential", True)) and str(
        provider.get("auth_kind") or "api_key"
    ).strip().lower() != "none"
    configured = not requires or bool(resolution.secret)
    canonical_ref = str(resolution.reference or "none")
    return {
        "apiKeyEnv": canonical_ref.removeprefix("env:") if canonical_ref.startswith("env:") else "",
        "apiKeyConfigured": configured,
        "apiKeyState": str(resolution.state or "unknown"),
        "requiresApiKey": requires,
        "missingApiKey": requires and not configured,
    }


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _candidate(
    *,
    provider_id: str,
    provider: dict[str, Any],
    model_key: str,
    pinned: dict[str, Any],
    observed: dict[str, Any],
    provider_catalog: dict[str, Any],
    credential_compatibility: dict[str, Any],
    current_provider_fingerprint: str,
) -> dict[str, Any]:
    model_ref = make_model_ref(provider_id, model_key)
    has_pinned = bool(pinned)
    has_observed = bool(observed)
    upstream_id = str(pinned.get("upstream_id") or observed.get("upstreamId") or model_key).strip()
    capabilities = resolve_model_capabilities(
        operator=pinned.get("capabilities", {}),
        runtime_probe={},
        provider_metadata=observed.get("capabilities", {}),
        curated_snapshot={},
        driver_default={},
    )
    image_input = capabilities.get("image_input") if isinstance(capabilities.get("image_input"), dict) else {}
    verification = observed.get("verification") if isinstance(observed.get("verification"), dict) else {}
    fingerprint_stale = bool(
        verification
        and str(verification.get("providerFingerprint") or "") != current_provider_fingerprint
    )
    catalog_fingerprint = str(provider_catalog.get("providerFingerprint") or "")
    catalog_stale = bool(
        provider_catalog.get("catalogStale")
        or (catalog_fingerprint and catalog_fingerprint != current_provider_fingerprint)
    )
    defaults = pinned.get("defaults") if isinstance(pinned.get("defaults"), dict) else {}
    limits = observed.get("limits") if isinstance(observed.get("limits"), dict) else {}
    protocols = provider.get("protocols") if isinstance(provider.get("protocols"), dict) else {}
    reasoning = project_reasoning_contract(
        pinned,
        observed,
        current_provider_fingerprint=current_provider_fingerprint,
    )
    return {
        "modelId": model_ref,
        "modelRef": model_ref,
        "modelKey": model_key,
        "upstreamId": upstream_id,
        "label": str(pinned.get("label") or observed.get("label") or upstream_id).strip(),
        "model": upstream_id,
        "contextWindow": _safe_int(
            pinned.get("context_window")
            or defaults.get("context_window")
            or observed.get("contextWindow")
            or limits.get("context_window")
            or provider.get("context_window")
        ),
        "providerId": provider_id,
        "providerLabel": str(provider.get("label") or provider_id).strip(),
        "providerKind": str(provider.get("driver") or "").strip(),
        "providerBaseUrl": str(provider.get("base_url") or "").strip(),
        "transport": str(pinned.get("wire_protocol") or protocols.get("default") or "").strip(),
        "source": "both" if has_pinned and has_observed else "pinned" if has_pinned else "discovered",
        "runtimeSelectable": has_pinned and pinned.get("enabled", True) is not False,
        "availability": str(observed.get("availability") or ("pinned" if has_pinned else "unknown")),
        "catalogStale": catalog_stale,
        "verificationStatus": (
            "stale" if fingerprint_stale else str(verification.get("status") or "unverified")
        ),
        "capabilities": capabilities,
        "supportsImageInput": (
            True
            if image_input.get("value") == "supported"
            else False
            if image_input.get("value") == "unsupported"
            else None
        ),
        "slotCompatibility": project_slot_compatibility(upstream_id, pinned, observed),
        **credential_compatibility,
        **reasoning,
    }


def project_agent_model_candidates(
    public_config: dict[str, Any],
    catalog_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Union pinned and observed models for configured Providers only."""

    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    catalog_providers = (
        catalog_state.get("providers") if isinstance(catalog_state.get("providers"), dict) else {}
    )
    candidates: dict[str, dict[str, Any]] = {}
    for raw_provider_id, raw_provider in providers.items():
        provider_id = str(raw_provider_id)
        if not isinstance(raw_provider, dict):
            continue
        provider = raw_provider
        provider_catalog = catalog_providers.get(provider_id, {})
        if not isinstance(provider_catalog, dict):
            provider_catalog = {}
        pinned_models = provider.get("models") if isinstance(provider.get("models"), dict) else {}
        observed_models = (
            provider_catalog.get("models")
            if isinstance(provider_catalog.get("models"), dict)
            else {}
        )
        credential_compatibility = _provider_credential_compatibility(provider)
        current_provider_fingerprint = provider_discovery_fingerprint(provider)
        for raw_model_key in sorted(set(pinned_models) | set(observed_models), key=str):
            model_key = str(raw_model_key)
            pinned = pinned_models.get(raw_model_key, {})
            observed = observed_models.get(raw_model_key, {})
            if not isinstance(pinned, dict):
                pinned = {}
            if not isinstance(observed, dict):
                observed = {}
            try:
                make_model_ref(provider_id, model_key)
            except ValueError:
                continue
            candidate = _candidate(
                provider_id=provider_id,
                provider=provider,
                model_key=model_key,
                pinned=pinned,
                observed=observed,
                provider_catalog=provider_catalog,
                credential_compatibility=credential_compatibility,
                current_provider_fingerprint=current_provider_fingerprint,
            )
            candidates[candidate["modelRef"]] = candidate
    return sorted(
        candidates.values(),
        key=lambda item: (
            str(item.get("providerLabel") or "").casefold(),
            str(item.get("label") or "").casefold(),
            str(item.get("modelRef") or "").casefold(),
        ),
    )


def _legacy_model_options(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the old pinned-only workspace field derived from the same snapshot."""

    options: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("runtimeSelectable") is not True:
            continue
        provider = {
            "id": candidate["providerId"],
            "provider_id": candidate["providerId"],
            "label": candidate["providerLabel"],
            "kind": candidate["providerKind"],
            "driver": candidate["providerKind"],
            "base_url": candidate["providerBaseUrl"],
            "requires_api_key": candidate["requiresApiKey"],
        }
        details = {
            "capabilities": candidate["capabilities"],
            "reasoning_effort_values": list(candidate.get("reasoningEffortValues") or []),
            "default_reasoning_effort": str(candidate.get("defaultReasoningEffort") or ""),
            "reasoning_effort_adapter": str(candidate.get("reasoningAdapter") or "none"),
            "reasoning_effort_map": dict(candidate.get("reasoningEffortMap") or {}),
        }
        options.append(
            {
                "model_ref": candidate["modelRef"],
                "provider_id": candidate["providerId"],
                "upstream_id": candidate["upstreamId"],
                "model_id": candidate["modelRef"],
                "source": "provider_model",
                "provider": provider,
                "contextWindow": candidate["contextWindow"],
                "provider_kind": candidate["providerKind"],
                "model": candidate["upstreamId"],
                "label": candidate["label"],
                "details": details,
                "transport": candidate["transport"],
                "api_key_env": candidate["apiKeyEnv"],
                "api_key_configured": candidate["apiKeyConfigured"],
                "api_key_state": candidate["apiKeyState"],
                "supports_image_input": candidate["supportsImageInput"],
                "capability_status": candidate["capabilityStatus"],
                "capability_source": candidate["capabilitySource"],
            }
        )
    return options


def list_agent_model_candidates() -> dict[str, Any]:
    """Load each canonical source once and project one consistent workspace payload."""

    public_config = load_public_config()
    catalog_state = load_model_catalog_state()
    candidates = project_agent_model_candidates(public_config, catalog_state)
    return {
        "operatorConfigHash": public_config_hash(public_config),
        "candidates": candidates,
        "modelOptions": _legacy_model_options(candidates),
    }


__all__ = [
    "list_agent_model_candidates",
    "project_agent_model_candidates",
    "project_reasoning_contract",
    "project_slot_compatibility",
    "reasoning_effort_options",
]
