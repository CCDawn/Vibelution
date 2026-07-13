"""Atomic promotion of one observed Provider model into one Agent binding."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.llm_identity import provider_discovery_fingerprint, split_model_ref
from config.model_catalog import load_model_catalog_state
from config.operator_config_transaction import (
    OperatorConfigTransactionError,
    TransactionParticipant,
    append_toml_table,
    apply_operator_config_transaction,
    prepare_operator_config_transaction,
)
from config.paths import resolve_model_catalog_state_path
from config.public_config import CONFIG_PATH, load_public_config, public_config_hash
from core.llm.agent_runtime import AGENT_LLM_SLOTS, normalize_agent_llm_bindings
from core.llm.reasoning_effort import normalize_reasoning_effort

from .agent_config_workspace_service import invalidate_agent_config_workspace_cache
from .agent_directory_service import (
    AgentNotFoundError,
    AgentStateConflictError,
    get_agent,
    record_agent_llm_binding_updated_event,
    replace_agent_llm_bindings_if_current,
)
from .agent_model_candidate_service import project_agent_model_candidates
from .runtime_scene_service import record_runtime_scene_event


_UNAVAILABLE_CANDIDATE_STATES = {
    "missing",
    "missing_remote",
    "stale",
    "unavailable",
    "unknown",
}
_REASONING_EFFORT_ADAPTERS = {
    "reasoning_effort",
    "reasoning_object",
    "thinking_toggle",
}
_CAPABILITY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CAPABILITY_VALUES = {"supported", "unsupported", "unknown"}
_CAPABILITY_SOURCES = {"operator_override", "runtime_probe"}
_CAPABILITY_PROJECTION_SOURCES = {
    "driver_default",
    "curated_snapshot",
    "provider_endpoint",
    *_CAPABILITY_SOURCES,
}
_CAPABILITY_CONFIDENCE_VALUES = {"low", "medium", "high"}


class AgentModelPromotionError(RuntimeError):
    """Base error for bounded model-promotion failures."""


class AgentModelPromotionConflict(AgentModelPromotionError):
    """Raised when promotion inputs no longer match canonical state."""


@dataclass(frozen=True)
class _PromotionPreflight:
    agent: dict[str, Any]
    public_config: dict[str, Any]
    candidate: dict[str, Any]
    catalog_model: dict[str, Any]
    config_path: Path
    base_hash: str
    model_ref: str
    provider_id: str
    model_key: str
    already_pinned: bool


def _promotion_preflight(
    agent_id: str,
    *,
    slot: str,
    model_ref: str,
    expected_base_hash: str,
    expected_agent_updated_at: str,
    confirmed: bool,
    config_path: Path | str,
) -> _PromotionPreflight:
    if not confirmed:
        raise AgentModelPromotionConflict("Model promotion confirmation is required.")
    normalized_agent_id = str(agent_id or "").strip()
    normalized_slot = str(slot or "").strip()
    if normalized_slot not in AGENT_LLM_SLOTS:
        raise AgentModelPromotionConflict("Agent model slot is not supported.")
    try:
        provider_id, model_key = split_model_ref(model_ref)
    except ValueError:
        raise AgentModelPromotionConflict("Model reference is invalid.") from None
    canonical_model_ref = f"{provider_id}/{model_key}"

    agent = get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise AgentNotFoundError("Agent not found.")
    if (
        str(agent.get("updatedAt") or "").strip()
        != str(expected_agent_updated_at or "").strip()
    ):
        raise AgentModelPromotionConflict(
            "Agent changed after the model selection was opened."
        )

    resolved_config_path = Path(config_path).expanduser().resolve()
    public_config = load_public_config(resolved_config_path)
    base_hash = public_config_hash(public_config)
    if base_hash != str(expected_base_hash or "").strip():
        raise AgentModelPromotionConflict(
            "Operator config changed after the model selection was opened."
        )
    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        raise AgentModelPromotionConflict("Model Provider is no longer configured.")
    models = provider.get("models") if isinstance(provider.get("models"), dict) else {}
    pinned_model = models.get(model_key)
    has_pinned_record = isinstance(pinned_model, dict)
    already_pinned = has_pinned_record and pinned_model.get("enabled", True) is not False
    if has_pinned_record and not already_pinned:
        raise AgentModelPromotionConflict("Pinned model is disabled.")

    if already_pinned:
        # Operator config is authoritative for an enabled pinned model. A
        # derived catalog cannot block a pure Agent-binding update.
        catalog_state: dict[str, Any] = {}
    else:
        try:
            catalog_state = load_model_catalog_state(
                resolve_model_catalog_state_path(resolved_config_path)
            )
        except (OSError, ValueError):
            raise AgentModelPromotionConflict("Model catalog is unavailable.") from None
    candidate = next(
        (
            item
            for item in project_agent_model_candidates(
                public_config,
                _catalog_state_for_candidate_projection(catalog_state),
            )
            if str(item.get("modelRef") or "") == canonical_model_ref
        ),
        None,
    )
    if not candidate:
        raise AgentModelPromotionConflict("Model candidate is no longer available.")

    if not already_pinned:
        if candidate.get("catalogStale") is True:
            raise AgentModelPromotionConflict("Model candidate catalog is stale.")
        availability = str(candidate.get("availability") or "unknown").strip().lower()
        if availability in _UNAVAILABLE_CANDIDATE_STATES:
            raise AgentModelPromotionConflict("Model candidate is unavailable.")
        if str(candidate.get("verificationStatus") or "").strip().lower() == "stale":
            raise AgentModelPromotionConflict("Model candidate verification is stale.")

    source = str(candidate.get("source") or "").strip().lower()
    catalog_providers = (
        catalog_state.get("providers")
        if isinstance(catalog_state.get("providers"), dict)
        else {}
    )
    provider_catalog = catalog_providers.get(provider_id)
    catalog_models = (
        provider_catalog.get("models")
        if isinstance(provider_catalog, dict)
        and isinstance(provider_catalog.get("models"), dict)
        else {}
    )
    catalog_model = catalog_models.get(model_key)
    if not isinstance(catalog_model, dict):
        catalog_model = {}
    if not already_pinned and source in {"discovered", "both"}:
        catalog_fingerprint = (
            str(provider_catalog.get("providerFingerprint") or "").strip()
            if isinstance(provider_catalog, dict)
            else ""
        )
        if (
            not catalog_fingerprint
            or catalog_fingerprint != provider_discovery_fingerprint(provider)
        ):
            raise AgentModelPromotionConflict(
                "Model candidate Provider fingerprint changed."
            )

    compatibility = candidate.get("slotCompatibility")
    slot_compatibility = (
        compatibility.get(normalized_slot) if isinstance(compatibility, dict) else None
    )
    if (
        not isinstance(slot_compatibility, dict)
        or slot_compatibility.get("allowed") is not True
    ):
        raise AgentModelPromotionConflict(
            "Model candidate is incompatible with this Agent slot."
        )
    return _PromotionPreflight(
        agent=agent,
        public_config=public_config,
        candidate=candidate,
        catalog_model=catalog_model,
        config_path=resolved_config_path,
        base_hash=base_hash,
        model_ref=canonical_model_ref,
        provider_id=provider_id,
        model_key=model_key,
        already_pinned=already_pinned,
    )


def _pinned_model_from_candidate(
    candidate: dict[str, Any],
    catalog_model: dict[str, Any],
) -> dict[str, Any]:
    upstream_id = str(candidate.get("upstreamId") or "").strip()
    if not upstream_id:
        raise AgentModelPromotionConflict("Model candidate identity is incomplete.")
    model: dict[str, Any] = {
        "upstream_id": upstream_id,
        "label": str(candidate.get("label") or upstream_id).strip()[:160]
        or upstream_id,
        "enabled": True,
    }
    verification_status = str(candidate.get("verificationStatus") or "").strip().lower()
    if verification_status == "verified":
        raw_capabilities = catalog_model.get("capabilities")
        confirmed: dict[str, dict[str, Any]] = {}
        if isinstance(raw_capabilities, dict):
            for key, raw_value in raw_capabilities.items():
                normalized = _verified_capability_record(key, raw_value)
                if normalized is not None:
                    normalized_key, value = normalized
                    confirmed[normalized_key] = value
        if confirmed:
            model["capabilities"] = confirmed
        reasoning_defaults = _verified_reasoning_defaults(candidate, catalog_model)
        if reasoning_defaults:
            model["defaults"] = reasoning_defaults
    return model


def _valid_capability_timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        return None
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return normalized


def _valid_capability_confidence(value: Any) -> str | float | None:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized if normalized in _CAPABILITY_CONFIDENCE_VALUES else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and 0.0 <= numeric <= 1.0 else None


def _verified_capability_record(
    key: Any,
    raw_value: Any,
    *,
    allowed_sources: set[str] = _CAPABILITY_SOURCES,
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(key, str):
        return None
    normalized_key = key.strip()
    if normalized_key != key or not _CAPABILITY_KEY_PATTERN.fullmatch(normalized_key):
        return None
    if not isinstance(raw_value, dict):
        return None
    raw_capability_value = raw_value.get("value")
    if not isinstance(raw_capability_value, str):
        return None
    capability_value = raw_capability_value.strip().lower()
    source = raw_value.get("source")
    if not isinstance(source, str):
        return None
    source = source.strip()
    if capability_value not in _CAPABILITY_VALUES or source not in allowed_sources:
        return None
    confidence = _valid_capability_confidence(raw_value.get("confidence"))
    checked_at = _valid_capability_timestamp(raw_value.get("checked_at"))
    if confidence is None or checked_at is None:
        return None
    normalized: dict[str, Any] = {
        "value": capability_value,
        "source": source,
    }
    if confidence != "":
        normalized["confidence"] = confidence
    if checked_at:
        normalized["checked_at"] = checked_at
    return normalized_key, normalized


def _catalog_state_for_candidate_projection(
    catalog_state: dict[str, Any],
) -> dict[str, Any]:
    """Drop malformed capability records before read-only candidate projection."""

    projected = copy.deepcopy(catalog_state)
    providers = projected.get("providers")
    if not isinstance(providers, dict):
        return projected
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model in models.values():
            if not isinstance(model, dict):
                continue
            raw_capabilities = model.get("capabilities")
            if not isinstance(raw_capabilities, dict):
                model.pop("capabilities", None)
                continue
            normalized_capabilities: dict[str, dict[str, Any]] = {}
            for key, raw_value in raw_capabilities.items():
                normalized = _verified_capability_record(
                    key,
                    raw_value,
                    allowed_sources=_CAPABILITY_PROJECTION_SOURCES,
                )
                if normalized is not None:
                    normalized_key, value = normalized
                    normalized_capabilities[normalized_key] = value
            model["capabilities"] = normalized_capabilities
    return projected


def _verified_reasoning_defaults(
    candidate: dict[str, Any],
    catalog_model: dict[str, Any],
) -> dict[str, Any]:
    capability_status = str(candidate.get("capabilityStatus") or "").strip().lower()
    if capability_status not in {"confirmed", "verified"}:
        return {}
    raw_contract = catalog_model.get("reasoningContract")
    if not isinstance(raw_contract, dict):
        return {}
    if str(raw_contract.get("verificationStatus") or "").strip().lower() != "verified":
        return {}
    if str(raw_contract.get("source") or "").strip() not in _CAPABILITY_SOURCES:
        return {}
    raw_effort_values = raw_contract.get("effortValues")
    if not isinstance(raw_effort_values, list):
        return {}
    effort_values: list[str] = []
    for raw_value in raw_effort_values:
        if not isinstance(raw_value, str):
            return {}
        normalized = normalize_reasoning_effort(raw_value)
        if not normalized or normalized in effort_values:
            return {}
        effort_values.append(normalized)
    if not effort_values:
        return {}

    default_effort = normalize_reasoning_effort(raw_contract.get("default"))
    if default_effort not in effort_values:
        return {}
    adapter = str(raw_contract.get("adapter") or "").strip().lower()
    if adapter not in _REASONING_EFFORT_ADAPTERS:
        return {}

    raw_mapping = raw_contract.get("map")
    if not isinstance(raw_mapping, dict):
        return {}
    mapping: dict[str, str] = {}
    for raw_key, raw_target in raw_mapping.items():
        if not isinstance(raw_key, str) or not isinstance(raw_target, str):
            return {}
        key = normalize_reasoning_effort(raw_key)
        if not key or key not in effort_values or key in mapping:
            return {}
        target = raw_target.strip().lower()
        if adapter == "thinking_toggle":
            if target not in {"on", "off"}:
                return {}
        else:
            target = normalize_reasoning_effort(target)
            if not target:
                return {}
        mapping[key] = target
    return {
        "reasoning_effort_values": effort_values,
        "default_reasoning_effort": default_effort,
        "reasoning_effort_adapter": adapter,
        "reasoning_effort_map": mapping,
    }


def _assert_agent_binding(agent_id: str, slot: str, model_ref: str) -> None:
    current = get_agent(agent_id, include_archived=False)
    if not current:
        raise AgentNotFoundError("Agent not found.")
    bindings = normalize_agent_llm_bindings(current.get("llmBindings"))
    if str(bindings.get(slot, {}).get("modelId") or "") != model_ref:
        raise RuntimeError("Agent binding verification failed.")


def _record_promotion_event(
    event_code: str,
    *,
    agent_id: str,
    slot: str,
    model_ref: str,
    outcome: str,
    status: str,
    source: str = "",
    reason_code: str = "",
    operation_id: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "agent_model_promotion",
            "promotion",
            event_code,
            message="Agent model promotion state changed.",
            level="info" if outcome == "completed" else "error",
            outcome=outcome,
            fields={
                "agentId": str(agent_id or "").strip(),
                "slot": str(slot or "").strip(),
                "modelRef": str(model_ref or "").strip(),
                "status": str(status or "").strip(),
                "source": str(source or "").strip(),
                "reasonCode": str(reason_code or "").strip(),
                "operationId": str(operation_id or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _failure_reason_code(exc: Exception) -> str:
    if isinstance(exc, AgentNotFoundError):
        return "agent_not_found"
    if isinstance(exc, AgentStateConflictError):
        return "agent_state_conflict"
    if isinstance(exc, OperatorConfigTransactionError):
        return (
            "transaction_rollback_failed"
            if exc.status == "rollback_failed"
            else "transaction_rolled_back"
        )
    if isinstance(exc, AgentModelPromotionConflict):
        return "promotion_conflict"
    return "promotion_failed"


def promote_agent_model(
    agent_id: str,
    *,
    slot: str,
    model_ref: str,
    expected_base_hash: str,
    expected_agent_updated_at: str,
    confirmed: bool,
    config_path: Path | str = CONFIG_PATH,
) -> dict[str, Any]:
    """Promote one candidate and bind it without leaving partial state."""

    source = ""
    operation_id = ""
    event_agent_id = ""
    event_slot = ""
    event_model_ref = ""
    try:
        preflight = _promotion_preflight(
            agent_id,
            slot=slot,
            model_ref=model_ref,
            expected_base_hash=expected_base_hash,
            expected_agent_updated_at=expected_agent_updated_at,
            confirmed=confirmed,
            config_path=config_path,
        )
        event_agent_id = str(preflight.agent.get("agentId") or "").strip()
        event_slot = str(slot).strip()
        event_model_ref = preflight.model_ref
        old_bindings = normalize_agent_llm_bindings(preflight.agent.get("llmBindings"))
        new_bindings = copy.deepcopy(old_bindings)
        new_bindings[str(slot).strip()] = {"modelId": preflight.model_ref}
        source = "pinned" if preflight.already_pinned else "discovered"

        if preflight.already_pinned:
            updated_agent = replace_agent_llm_bindings_if_current(
                agent_id,
                expected_updated_at=expected_agent_updated_at,
                llm_bindings=new_bindings,
            )
            invalidate_agent_config_workspace_cache()
            result = {
                "status": "completed",
                "modelRef": preflight.model_ref,
                "source": source,
                "agent": updated_agent,
                "operatorConfigHash": preflight.base_hash,
                "manifestPath": "",
            }
            _record_promotion_event(
                "config.model.promotion_completed",
                agent_id=event_agent_id,
                slot=event_slot,
                model_ref=event_model_ref,
                outcome="completed",
                status="completed",
                source=source,
            )
            return result

        binding_write: dict[str, Any] = {}

        def apply_binding() -> None:
            updated = replace_agent_llm_bindings_if_current(
                agent_id,
                expected_updated_at=expected_agent_updated_at,
                llm_bindings=new_bindings,
                emit_event=False,
            )
            binding_write["updatedAt"] = str(updated.get("updatedAt") or "")
            binding_write["agent"] = updated

        def rollback_binding() -> None:
            applied_revision = str(binding_write.get("updatedAt") or "")
            if not applied_revision:
                return
            replace_agent_llm_bindings_if_current(
                agent_id,
                expected_updated_at=applied_revision,
                llm_bindings=old_bindings,
                emit_event=False,
            )

        participant = TransactionParticipant(
            name="agent_binding",
            apply=apply_binding,
            verify=lambda: _assert_agent_binding(
                agent_id,
                str(slot).strip(),
                preflight.model_ref,
            ),
            rollback=rollback_binding,
        )
        prepared = prepare_operator_config_transaction(
            operation_kind="model_promotion",
            expected_base_hash=preflight.base_hash,
            config_path=preflight.config_path,
            mutate_text=lambda text: append_toml_table(
                text,
                (
                    "llm",
                    "providers",
                    preflight.provider_id,
                    "models",
                    preflight.model_key,
                ),
                _pinned_model_from_candidate(
                    preflight.candidate,
                    preflight.catalog_model,
                ),
            ),
        )
        operation_id = prepared.operation_id
        transaction_result = apply_operator_config_transaction(
            prepared,
            participants=[participant],
        )
        updated_agent = binding_write.get("agent")
        if not isinstance(updated_agent, dict):
            raise RuntimeError("Agent binding participant returned no result.")
        record_agent_llm_binding_updated_event(updated_agent)
        invalidate_agent_config_workspace_cache()
        result = {
            "status": "completed",
            "modelRef": preflight.model_ref,
            "source": source,
            "agent": updated_agent,
            "operatorConfigHash": str(transaction_result.get("hash") or ""),
            "manifestPath": str(transaction_result.get("manifestPath") or ""),
        }
        _record_promotion_event(
            "config.model.promotion_completed",
            agent_id=event_agent_id,
            slot=event_slot,
            model_ref=event_model_ref,
            outcome="completed",
            status="completed",
            source=source,
            operation_id=operation_id,
        )
        return result
    except Exception as exc:
        status = (
            exc.status
            if isinstance(exc, OperatorConfigTransactionError)
            else "rejected"
        )
        _record_promotion_event(
            "config.model.promotion_failed",
            agent_id=event_agent_id,
            slot=event_slot,
            model_ref=event_model_ref,
            outcome="failed",
            status=status,
            source=source,
            reason_code=_failure_reason_code(exc),
            operation_id=(
                exc.operation_id
                if isinstance(exc, OperatorConfigTransactionError)
                else operation_id
            ),
        )
        raise


__all__ = [
    "AgentModelPromotionConflict",
    "AgentModelPromotionError",
    "promote_agent_model",
]
