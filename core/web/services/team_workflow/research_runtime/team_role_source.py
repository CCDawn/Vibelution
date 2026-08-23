"""Team-role binding source for research workflow runs.

Resolves a team's organization canvas / member roles into the workflow's
roleKey -> agentId default map. This is the CURRENT-CONFIGURATION source
only: run creation freezes the resolved result into an immutable
RunAgentBindingSnapshot, so history never re-reads live team config.

Rules enforced here:
- no random fallback to arbitrary agents (a missing role is simply unbound);
- canvas nodes win over team members for the same role (mirrors the frontend
  researchStageAgentBindings projection);
- team lookup failure yields an empty map (all roles unbound), never an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.research.workflow.models import AgentBindingLayers


def normalize_role_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def _agent_id_of(item: dict[str, Any]) -> str:
    return str(item.get("agentId") or "").strip()


def _role_of(item: dict[str, Any]) -> str:
    return normalize_role_key(item.get("role"))


def resolve_team_role_bindings(team_id: str) -> dict[str, str]:
    """Return roleKey -> agentId for a team (canvas nodes, then members).

    Empty result means no usable role mapping — callers treat every role as
    unbound (never fall back to a random agent).
    """
    if not str(team_id or "").strip():
        return {}
    try:
        from core.web.services.team_service import list_team_role_binding_sources

        sources = list_team_role_binding_sources(team_id)
    except Exception:
        return {}

    bindings: dict[str, str] = {}
    for node in list(sources.get("canvas_nodes") or []):
        if not isinstance(node, dict):
            continue
        role = _role_of(node)
        agent_id = _agent_id_of(node)
        if role and agent_id and role not in bindings:
            bindings[role] = agent_id
    for member in list(sources.get("members") or []):
        if not isinstance(member, dict):
            continue
        role = _role_of(member)
        agent_id = _agent_id_of(member)
        if role and agent_id and role not in bindings:
            bindings[role] = agent_id
    return bindings


def heal_agent_binding_for_node(
    team_id: str,
    node_id: str,
) -> dict[str, str] | None:
    """Fill an empty frozen snapshot slot from the team's current role map.

    Canvas overlays live ``effectiveBindings``, so the node can show
    Agent bound while readiness still reads an empty freeze. History
    stays authoritative when the freeze already named an agentId.
    """
    from core.research.workflow.definition import node_by_id
    from core.research.workflow.models import ActorKind

    node = node_by_id().get(str(node_id or "").strip())
    if node is None or node.actorKind != ActorKind.AGENT:
        return None
    roles = resolve_team_role_bindings(team_id)
    if not roles:
        return None
    primary = normalize_role_key(node.primaryRoleKey)
    agent_id = str(roles.get(primary) or roles.get(node.primaryRoleKey) or "").strip()
    if not agent_id:
        try:
            from core.web.services.team.team_constants import RESEARCH_TEAM_MEMBER_ROLE_KEYS
        except Exception:
            RESEARCH_TEAM_MEMBER_ROLE_KEYS = {}
        mapped = RESEARCH_TEAM_MEMBER_ROLE_KEYS.get(node.primaryRoleKey) or RESEARCH_TEAM_MEMBER_ROLE_KEYS.get(primary)
        if mapped:
            agent_id = str(roles.get(normalize_role_key(mapped)) or roles.get(mapped) or "").strip()
    if not agent_id:
        return None
    return {
        "nodeId": node.nodeId,
        "agentId": agent_id,
        "roleKey": node.primaryRoleKey,
        "resolvedFrom": "team_role_heal",
        "snapshotId": f"heal:{team_id}:{node.nodeId}",
    }


def heal_agent_binding_from_sibling_freeze(
    snapshot: Mapping[str, Any] | None,
    node_id: str,
) -> dict[str, str] | None:
    """Reuse another frozen node binding on the same run when this slot is empty.

    Compact restores often freeze earlier Agent nodes only. This stays inside
    the run snapshot; it is not a live-directory random pick.
    """
    from core.research.workflow.definition import node_by_id
    from core.research.workflow.models import ActorKind

    node = node_by_id().get(str(node_id or "").strip())
    if node is None or node.actorKind != ActorKind.AGENT:
        return None
    preferred = normalize_role_key(node.primaryRoleKey)
    for binding in (snapshot or {}).get("agentBindingSnapshot") or []:
        if not isinstance(binding, Mapping):
            continue
        agent_id = str(binding.get("agentId") or "").strip()
        if not agent_id:
            continue
        item = {
            "nodeId": node.nodeId,
            "agentId": agent_id,
            "roleKey": node.primaryRoleKey,
            "resolvedFrom": "sibling_freeze",
            "snapshotId": f"heal-sibling:{node.nodeId}",
        }
        if normalize_role_key(str(binding.get("roleKey") or "")) == preferred:
            return item
    return None


def effective_binding_layers(
    team_id: str,
    config: AgentBindingLayers,
) -> AgentBindingLayers:
    """Merge the persisted (controlled-write) config with team-role defaults.

    Priority order (kept by resolve_effective_agent_id in core/research):
      node override > stage override > workflow default > unbound.
    The controlled config wins over team roles for the same roleKey; team
    roles fill every gap. Team roles only ever populate workflowDefaults.
    """
    team_defaults = resolve_team_role_bindings(team_id) if str(team_id or "").strip() else {}
    merged_defaults = {**team_defaults, **config.workflowDefaults}
    return AgentBindingLayers(
        workflowDefaults=merged_defaults,
        stageOverrides={k: dict(v) for k, v in config.stageOverrides.items()},
        nodeOverrides=dict(config.nodeOverrides),
    )
