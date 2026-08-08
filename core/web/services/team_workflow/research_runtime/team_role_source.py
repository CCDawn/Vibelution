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
        from core.web.services.team_service import get_team, get_team_canvas
    except Exception:  # pragma: no cover - defensive import boundary
        return {}

    bindings: dict[str, str] = {}
    try:
        canvas = get_team_canvas(team_id)
        for node in (canvas or {}).get("nodes") or []:
            role = _role_of(node)
            agent_id = _agent_id_of(node)
            if role and agent_id and role not in bindings:
                bindings[role] = agent_id
    except Exception:
        # Team or canvas unavailable: keep going with members; if both fail
        # the result stays empty and every role is unbound.
        pass

    try:
        team = get_team(team_id)
        for member in (team or {}).get("members") or []:
            role = _role_of(member)
            agent_id = _agent_id_of(member)
            if role and agent_id and role not in bindings:
                bindings[role] = agent_id
    except Exception:
        pass

    return bindings


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
