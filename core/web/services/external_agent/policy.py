"""Single external exposure policy for non-team project Agents."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from core.web.services.tool_catalog import TOOL_CATALOG

ActiveTeamLookup = Callable[[str], dict[str, Any] | None]
OperatorEnabled = Callable[[str], bool]

_TEAM_INDEX_KIND = "team_agent"
_PERSONAL_INDEX_KIND = "personal_agent"
_TEAM_CREATED_BY = frozenset(
    {
        "ai_search_team",
        "challenge_cup_team",
        "knowledge_expansion_team",
    }
)
_TEAM_ROLE_PREFIXES = ("challenge_cup_", "knowledge_expansion_", "research_team_")
_EXTERNAL_PERMISSION_PROFILES = frozenset(
    {"read_only", "workspace_write", "full_access"}
)
DEFAULT_EXTERNAL_AGENT_PERMISSION_CEILING = "workspace_write"
_EXTERNAL_WORKSPACE_CATEGORIES = frozenset({"workspace_write", "code_quality"})
_EXTERNAL_DESTRUCTIVE_RISK_TAGS = frozenset({"delete_or_cleanup", "project_rollback"})
_EXTERNAL_FORBIDDEN_CATEGORIES = frozenset(
    {"agent_collaboration", "conversation_history"}
)
_EXTERNAL_FORBIDDEN_RISK_TAGS = frozenset(
    {
        "research_database_access",
        "session_data_access",
        "team_knowledge_access",
        "team_workflow_access",
    }
)


@dataclass(frozen=True)
class ExternalAgentEligibility:
    eligible: bool
    reason: str


def external_runtime_tool_grants(permission_profile: str) -> tuple[str, ...]:
    """Return the fail-closed tool ceiling for one external task profile."""

    profile = str(permission_profile or "").strip().lower()
    if profile not in _EXTERNAL_PERMISSION_PROFILES:
        raise ValueError(
            f"unsupported external permission profile: {profile or '<empty>'}"
        )
    allowed: list[str] = []
    for tool_name, raw_metadata in TOOL_CATALOG.items():
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        capabilities = set(metadata.get("capabilityTags") or [])
        category = str(metadata.get("category") or "")
        risk_tags = set(metadata.get("riskTags") or [])
        if category in _EXTERNAL_FORBIDDEN_CATEGORIES or risk_tags.intersection(
            _EXTERNAL_FORBIDDEN_RISK_TAGS
        ):
            continue
        if profile == "read_only" and "read_only" not in capabilities:
            continue
        if profile == "workspace_write":
            workspace_allowed = (
                "read_only" in capabilities
                or category in _EXTERNAL_WORKSPACE_CATEGORIES
            )
            if not workspace_allowed or risk_tags.intersection(
                _EXTERNAL_DESTRUCTIVE_RISK_TAGS
            ):
                continue
        allowed.append(tool_name)
    return tuple(allowed)


def _default_active_team_lookup(agent_id: str) -> dict[str, Any] | None:
    from core.web.services.team import team_membership

    return team_membership._find_active_team_for_agent(agent_id)


def _agent_id(agent: dict[str, Any]) -> str:
    return str(agent.get("agentId") or agent.get("id") or "").strip()


def _agent_metadata(agent: dict[str, Any]) -> dict[str, Any]:
    return agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}


def _team_dedicated(agent: dict[str, Any]) -> bool:
    metadata = _agent_metadata(agent)
    creation_spec = (
        metadata.get("creationSpec")
        if isinstance(metadata.get("creationSpec"), dict)
        else {}
    )
    index_kind = str(
        agent.get("conversationIndexKind")
        or metadata.get("conversationIndexKind")
        or ""
    ).strip()
    created_by = str(
        agent.get("createdBy") or creation_spec.get("source") or ""
    ).strip()
    role_key = (
        str(agent.get("roleKey") or metadata.get("roleKey") or "").strip().lower()
    )
    has_team_marker = any(
        str(metadata.get(key) or agent.get(key) or "").strip()
        for key in ("teamId", "challengeCupTeamId", "knowledgeExpansionTeamId")
    )
    return bool(
        index_kind == _TEAM_INDEX_KIND
        or has_team_marker
        or created_by in _TEAM_CREATED_BY
        or any(role_key.startswith(prefix) for prefix in _TEAM_ROLE_PREFIXES)
    )


def external_mcp_eligibility(
    agent: dict[str, Any] | None,
    *,
    active_team_lookup: ActiveTeamLookup | None = None,
    operator_enabled: OperatorEnabled | None = None,
) -> ExternalAgentEligibility:
    if not isinstance(agent, dict):
        return ExternalAgentEligibility(False, "agent_not_found")
    agent_id = _agent_id(agent)
    if not agent_id:
        return ExternalAgentEligibility(False, "agent_not_found")
    if str(agent.get("status") or "active").strip().lower() != "active":
        return ExternalAgentEligibility(False, "agent_inactive")
    if _team_dedicated(agent):
        return ExternalAgentEligibility(False, "team_dedicated_agent")
    lookup = active_team_lookup or _default_active_team_lookup
    if lookup(agent_id):
        return ExternalAgentEligibility(False, "active_team_member")
    if operator_enabled is not None and not operator_enabled(agent_id):
        return ExternalAgentEligibility(False, "operator_disabled")

    metadata = _agent_metadata(agent)
    index_kind = str(
        agent.get("conversationIndexKind")
        or metadata.get("conversationIndexKind")
        or ""
    ).strip()
    if index_kind and index_kind != _PERSONAL_INDEX_KIND:
        return ExternalAgentEligibility(False, "unsupported_agent_class")
    return ExternalAgentEligibility(True, "eligible")


def _public_agent_projection(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = _agent_id(agent)
    return {
        "agentId": agent_id,
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "displayName": str(
            agent.get("displayName") or agent.get("name") or agent_id
        ).strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "role": str(agent.get("role") or agent.get("roleKey") or "").strip(),
        "maximumPermissionProfile": str(
            agent.get("externalMaximumPermissionProfile")
            or DEFAULT_EXTERNAL_AGENT_PERMISSION_CEILING
        ).strip()
        or DEFAULT_EXTERNAL_AGENT_PERMISSION_CEILING,
        "approvalCapabilities": ["approval.resolve"],
    }


def list_externally_callable_agents(
    agents: Iterable[dict[str, Any]],
    *,
    active_team_lookup: ActiveTeamLookup | None = None,
    operator_enabled: OperatorEnabled | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent in agents:
        decision = external_mcp_eligibility(
            agent,
            active_team_lookup=active_team_lookup,
            operator_enabled=operator_enabled,
        )
        if decision.eligible:
            result.append(_public_agent_projection(agent))
    result.sort(
        key=lambda item: (
            str(item.get("displayName") or "").casefold(),
            item["agentId"],
        )
    )
    return result
