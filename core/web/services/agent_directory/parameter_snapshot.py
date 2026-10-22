"""Preserve validated registry snapshots across narrowly scoped parameter writes."""

from __future__ import annotations

import copy
from typing import Any, Literal

from core.llm.agent_model_parameters import (
    AGENT_MODEL_PARAMETERS_METADATA_KEY,
    LEGACY_REASONING_EFFORT_METADATA_KEY,
)
from core.orchestration.session_budget_resolve import SESSION_BUDGET_PARAMETERS_METADATA_KEY

ParameterKind = Literal["compression", "model", "budget"]
_METADATA_KEYS = {
    "model": {AGENT_MODEL_PARAMETERS_METADATA_KEY, LEGACY_REASONING_EFFORT_METADATA_KEY},
    "budget": {SESSION_BUDGET_PARAMETERS_METADATA_KEY},
}


def save_parameter_update(
    state: dict[str, Any], agent: dict[str, Any], previous_agent: dict[str, Any], *, kind: ParameterKind,
) -> bool:
    """Carry repair invariants through a parameter-only canonical write.

    The caller owns _STATE_LOCK throughout CAS, write and cache handoff.
    Generic, cold and repair-sensitive writes retain normal invalidation.
    """
    from core.web.services import agent_directory_service as s

    warm = (
        s._REPAIRED_STATE_CACHE is not None
        and s._REPAIRED_STATE_CACHE_SIGNATURE == s._registry_state_signature()
    )
    payload = s.save_state(state)
    changed_keys = {
        key for key in previous_agent.keys() | agent.keys()
        if previous_agent.get(key) != agent.get(key)
    }
    allowed = {"configRevision", "configHash", "configSchemaVersion", "updatedAt"}
    if kind == "compression":
        allowed.add("contextCompressionPolicy")
        parameter_only = changed_keys <= allowed
    elif kind in _METADATA_KEYS:
        allowed.add("metadata")
        previous = previous_agent.get("metadata")
        current = agent.get("metadata")
        metadata_valid = isinstance(previous, dict) and isinstance(current, dict)
        changed_metadata = {
            key for key in previous.keys() | current.keys()
            if previous.get(key) != current.get(key)
        } if metadata_valid else set()
        parameter_only = metadata_valid and changed_keys <= allowed and changed_metadata <= _METADATA_KEYS[kind]
    else:
        parameter_only = False
    if not warm or not parameter_only:
        return False
    # A later external write must never inherit this payload's validation.
    try:
        signature = s._registry_state_signature()
        persisted = s._load_existing_registry_payload_or_raise(s.registry_path())
        if signature != s._registry_state_signature() or persisted != payload:
            return False
    except (OSError, s.AgentDirectoryError):
        return False
    s._REPAIRED_STATE_CACHE = copy.deepcopy(payload)
    s._REPAIRED_STATE_CACHE_SIGNATURE = signature
    return True
