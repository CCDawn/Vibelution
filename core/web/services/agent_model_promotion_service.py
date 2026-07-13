"""Atomic promotion of one observed Provider model into one Agent binding."""

from __future__ import annotations

import copy
from dataclasses import dataclass
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
_VERIFIED_CAPABILITY_FIELDS = {
    "value",
    "source",
    "confidence",
    "checked_at",
}
_REASONING_EFFORT_ADAPTERS = {
    "reasoning_effort",
    "reasoning_object",
    "thinking_toggle",
}


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
    try:
        catalog_state = load_model_catalog_state(
            resolve_model_catalog_state_path(resolved_config_path)
        )
    except (OSError, ValueError):
        raise AgentModelPromotionConflict("Model catalog is unavailable.") from None
    candidate = next(
        (
            item
            for item in project_agent_model_candidates(public_config, catalog_state)
            if str(item.get("modelRef") or "") == canonical_model_ref
        ),
        None,
    )
    if not candidate:
        raise AgentModelPromotionConflict("Model candidate is no longer available.")

    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        raise AgentModelPromotionConflict("Model Provider is no longer configured.")
    models = provider.get("models") if isinstance(provider.get("models"), dict) else {}
    pinned_model = models.get(model_key)
    already_pinned = (
        isinstance(pinned_model, dict)
        and pinned_model.get("enabled", True) is not False
    )

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
    if source in {"discovered", "both"}:
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
    if str(candidate.get("verificationStatus") or "").strip().lower() == "verified":
        raw_capabilities = catalog_model.get("capabilities")
        confirmed: dict[str, dict[str, Any]] = {}
        if isinstance(raw_capabilities, dict):
            for key, raw_value in raw_capabilities.items():
                if not isinstance(raw_value, dict):
                    continue
                if str(raw_value.get("source") or "") not in {
                    "operator_override",
                    "runtime_probe",
                }:
                    continue
                value = {
                    field: raw_value[field]
                    for field in _VERIFIED_CAPABILITY_FIELDS
                    if field in raw_value
                }
                if value:
                    confirmed[str(key)] = value
        if confirmed:
            model["capabilities"] = confirmed

    reasoning_defaults = _verified_reasoning_defaults(candidate)
    if reasoning_defaults:
        model["defaults"] = reasoning_defaults
    return model


def _verified_reasoning_defaults(candidate: dict[str, Any]) -> dict[str, Any]:
    capability_status = str(candidate.get("capabilityStatus") or "").strip().lower()
    if capability_status not in {"confirmed", "verified"}:
        return {}
    raw_effort_values = candidate.get("reasoningEffortValues")
    if not isinstance(raw_effort_values, list):
        return {}
    effort_values: list[str] = []
    for raw_value in raw_effort_values:
        normalized = normalize_reasoning_effort(raw_value)
        if not normalized:
            return {}
        if normalized not in effort_values:
            effort_values.append(normalized)
    if not effort_values:
        return {}

    default_effort = normalize_reasoning_effort(candidate.get("defaultReasoningEffort"))
    if default_effort not in effort_values:
        return {}
    adapter = str(candidate.get("reasoningAdapter") or "").strip().lower()
    if adapter not in _REASONING_EFFORT_ADAPTERS:
        return {}

    raw_mapping = candidate.get("reasoningEffortMap")
    if not isinstance(raw_mapping, dict):
        return {}
    mapping: dict[str, str] = {}
    for raw_key, raw_target in raw_mapping.items():
        key = normalize_reasoning_effort(raw_key)
        target = str(raw_target or "").strip().lower()
        if not key or key not in effort_values:
            return {}
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
