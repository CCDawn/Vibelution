"""Preserve validated registry snapshots across narrowly scoped parameter writes."""

from __future__ import annotations

import copy
from typing import Any, Literal

from core.llm.agent_model_parameters import (
    AGENT_MODEL_PARAMETERS_METADATA_KEY,
    LEGACY_REASONING_EFFORT_METADATA_KEY,
)
from core.orchestration.session_budget_resolve import SESSION_BUDGET_PARAMETERS_METADATA_KEY
from .repair_store import _copy_json_value

ParameterKind = Literal["compression", "model", "budget"]
_METADATA_KEYS = {
    "model": {AGENT_MODEL_PARAMETERS_METADATA_KEY, LEGACY_REASONING_EFFORT_METADATA_KEY},
    "budget": {SESSION_BUDGET_PARAMETERS_METADATA_KEY},
}


def get_agent_parameter_snapshot(agent_id: str, *, include_archived: bool = True) -> dict[str, Any] | None:
    """Read canonical parameter fields without hydrating the Agent's UI activity.

    Share get_agent's repaired registry authority, but do not load avatars,
    inboxes or tool-governance activity for a configuration-only operation.
    """
    from core.web.services import agent_directory_service as s

    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    with s._STATE_LOCK:
        state, _ = s._load_repaired_state_for_read()
        agent = s._find_agent(state, normalized)
        if not agent or (not include_archived and str(agent.get("status") or "") == "archived"):
            return None
        return copy.deepcopy(agent)


def list_agent_identity_snapshots(*, include_archived: bool = True) -> list[dict[str, Any]]:
    """Read detached identity/binding fields for internal startup discovery.

    Use the repaired registry owner and list_agents' ordering/filtering. These
    are internal records, not UI DTOs: no avatars, policy derivation, activity
    hydration or per-Agent workspace reads are needed to find bundled assets.
    """
    from core.web.services import agent_directory_service as s

    with s._STATE_LOCK:
        state, _ = s._load_repaired_state_for_read()
        agents = [
            {
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")) or s._fallback_agent_code(agent.get("agentId")),
                "displayName": str(agent.get("displayName") or "").strip(),
                "status": str(agent.get("status") or "active").strip() or "active",
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "roleKey": s._normalize_role_key(agent.get("roleKey")) or s._infer_agent_role_key(agent),
                "createdBy": str(agent.get("createdBy") or "").strip(),
                "metadata": copy.deepcopy(agent.get("metadata") or {}),
                "createdAt": str(agent.get("createdAt") or "").strip(),
                "updatedAt": str(agent.get("updatedAt") or "").strip(),
            }
            for agent in state.get("agents") or []
            if isinstance(agent, dict)
            and (include_archived or str(agent.get("status") or "active") != "archived")
        ]
    agents.sort(key=lambda agent: str(agent.get("updatedAt") or agent.get("createdAt") or ""), reverse=True)
    return agents


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
    s._REPAIRED_STATE_CACHE = _copy_json_value(payload)
    s._REPAIRED_STATE_CACHE_SIGNATURE = signature
    return True
