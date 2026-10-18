"""Agent-scoped model parameter mutation helpers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.llm.agent_model_parameters import (
    AgentModelParametersError,
    merge_agent_model_parameter_entry,
    validate_agent_model_parameters,
)
from core.orchestration.session_budget_resolve import (
    SESSION_BUDGET_PARAMETERS_METADATA_KEY,
    normalize_session_budget_parameters,
)
from ..agent_config_authority import materialize_agent_config_identity


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _bound_dialogue_model_ref(agent: dict[str, Any], config: Any) -> str:
    s = _service()
    model_id = s.agent_dialogue_model_id(agent)
    if not model_id:
        return ""
    try:
        canonical_id = config.llm.resolve_model_ref(model_id)
    except Exception:
        canonical_id = model_id
    try:
        entry = config.llm.model_library.get(canonical_id)
    except Exception:
        entry = None
    return str((entry or {}).get("model_ref") or canonical_id).strip()


def _declared_context_window(config: Any, model_ref: str) -> int:
    try:
        model_id = config.llm.resolve_model_ref(model_ref)
        entry = config.llm.model_library.get(model_id)
    except Exception:
        entry = None
    if not isinstance(entry, dict):
        return 0
    for key in ("context_window", "contextWindow", "max_model_len", "context_length"):
        value = entry.get(key)
        if isinstance(value, bool):
            continue
        try:
            normalized = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if normalized > 0:
            return normalized
    provider_id = str(entry.get("provider_id") or "").strip()
    if not provider_id:
        return 0
    try:
        value = getattr(config.llm.get_provider(provider_id), "context_window", None)
        if isinstance(value, bool):
            return 0
        normalized = int(value or 0)
        return normalized if normalized > 0 else 0
    except Exception:
        return 0


def update_agent_model_parameters_if_current(
    agent_id: str,
    *,
    expected_model_ref: str,
    expected_config_revision: int,
    context_window: int,
    reasoning_effort: str,
    supported_reasoning_efforts: Sequence[str] = (),
) -> dict[str, Any]:
    """Atomically update one Agent/model entry if its binding and revision match."""
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_model_ref = str(expected_model_ref or "").strip()
    if not normalized_agent_id or not normalized_model_ref:
        raise AgentModelParametersError("Agent id and modelRef are required.")
    if isinstance(expected_config_revision, bool) or not isinstance(expected_config_revision, int):
        raise AgentModelParametersError("expectedConfigRevision must be an integer.")
    if expected_config_revision < 0:
        raise AgentModelParametersError("expectedConfigRevision must be non-negative.")

    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        current_revision = max(0, int(agent.get("configRevision") or 0))
        if current_revision != expected_config_revision:
            raise s.AgentStateConflictError("Agent configuration changed. Refresh and retry.")
        if str(agent.get("status") or "active").strip().lower() == "archived":
            raise s.AgentArchivedError("Archived Agent model parameters cannot be changed.")

        from config.settings import get_config

        config = get_config()
        current_model_ref = _bound_dialogue_model_ref(agent, config)
        if current_model_ref != normalized_model_ref:
            raise s.AgentStateConflictError("Agent model binding changed. Refresh and retry.")
        max_context_window = _declared_context_window(config, current_model_ref)
        normalized_values = validate_agent_model_parameters(
            context_window=context_window,
            reasoning_effort=reasoning_effort,
            max_context_window=max_context_window,
            supported_reasoning_efforts=supported_reasoning_efforts,
        )

        materialize_agent_config_identity(agent)
        previous_hash = str(agent.get("configHash") or "").strip()
        metadata = merge_agent_model_parameter_entry(
            agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {},
            normalized_model_ref,
            normalized_values,
        )
        agent["metadata"] = metadata
        # Keep the older Agent settings control aligned with the model it now
        # represents; the model-keyed entry remains the runtime authority.
        effort_by_slot = metadata.get("llmReasoningEffort")
        effort_by_slot = dict(effort_by_slot) if isinstance(effort_by_slot, dict) else {}
        if normalized_values["reasoningEffort"]:
            effort_by_slot["dialogue"] = normalized_values["reasoningEffort"]
        else:
            effort_by_slot.pop("dialogue", None)
        if effort_by_slot:
            metadata["llmReasoningEffort"] = effort_by_slot
        else:
            metadata.pop("llmReasoningEffort", None)
        agent["metadata"] = metadata
        materialize_agent_config_identity(
            agent,
            increment_if_changed=True,
            previous_hash=previous_hash,
        )
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)

    s._record_agent_event("agent.model_parameters.updated", agent)
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_model_parameters",
            "agent.model_parameters.updated",
            level="info",
            outcome="updated",
            message="Agent model parameters were updated.",
            fields={
                "agentId": normalized_agent_id,
                "modelRef": normalized_model_ref,
                "configRevision": int(agent.get("configRevision") or 0),
                "contextWindow": normalized_values["contextWindow"],
                "reasoningEffort": normalized_values["reasoningEffort"],
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return dict(agent)


def update_agent_budget_parameters_if_current(
    agent_id: str,
    *,
    expected_config_revision: int,
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Atomically replace one Agent's session budget override block.

    ``values`` is the fully merged override mapping (an empty/``None`` mapping
    clears the override back to defaults). Mirrors the model-parameters CAS:
    stale revisions raise ``AgentStateConflictError``; the caller validates
    ranges before calling. Budget overrides are not part of the canonical
    config hash, so the revision is incremented explicitly to keep
    compare-and-swap collisions between two budget edits detectable.
    """
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentModelParametersError("Agent id is required.")
    if isinstance(expected_config_revision, bool) or not isinstance(expected_config_revision, int):
        raise AgentModelParametersError("expectedConfigRevision must be an integer.")
    if expected_config_revision < 0:
        raise AgentModelParametersError("expectedConfigRevision must be non-negative.")

    normalized_parameters = normalize_session_budget_parameters(values)
    payload = (
        {}
        if normalized_parameters is None
        else normalized_parameters.as_storage_payload()
    )
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        current_revision = max(0, int(agent.get("configRevision") or 0))
        if current_revision != expected_config_revision:
            raise s.AgentStateConflictError("Agent configuration changed. Refresh and retry.")
        if str(agent.get("status") or "active").strip().lower() == "archived":
            raise s.AgentArchivedError("Archived Agent budget parameters cannot be changed.")

        metadata = dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}
        if payload:
            metadata[SESSION_BUDGET_PARAMETERS_METADATA_KEY] = dict(payload)
        else:
            metadata.pop(SESSION_BUDGET_PARAMETERS_METADATA_KEY, None)
        agent["metadata"] = metadata
        materialize_agent_config_identity(agent)
        # Explicit bump: the canonical config hash does not cover this metadata
        # key, so without it concurrent budget edits would never collide.
        agent["configRevision"] = max(1, int(agent.get("configRevision") or 0)) + 1
        materialize_agent_config_identity(agent)
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)

    s._record_agent_event("agent.budget_parameters.updated", agent)
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_budget_parameters",
            "agent.budget_parameters.updated",
            level="info",
            outcome="updated",
            message="Agent session budget parameters were updated.",
            fields={
                "agentId": normalized_agent_id,
                "configRevision": int(agent.get("configRevision") or 0),
                "maxCallsPerTurn": payload.get("maxCallsPerTurn"),
                "thinkingBudgetChars": payload.get("thinkingBudgetChars"),
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return dict(agent)


__all__ = [
    "update_agent_budget_parameters_if_current",
    "update_agent_model_parameters_if_current",
]
