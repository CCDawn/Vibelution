"""Team knowledge permission and ACL helpers.

Claim scope: can_* checks, steward detection, ACL normalize, permission
explain, and require_* permission gates.
Late-binds ``team_knowledge_service`` for owner context, store helpers, and errors.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def _permissions_for_actor(owner_value: Any, base: dict[str, Any], agent_id: str, *, internal: bool = False) -> dict[str, bool]:
    s = _service()
    return {
        "canRead": s._can_access(owner_value, base, agent_id, "read", internal=internal),
        "canPropose": s._can_access(owner_value, base, agent_id, "propose", internal=internal),
        "canReview": s._can_access(owner_value, base, agent_id, "review", internal=internal),
        "canRate": s._can_access(owner_value, base, agent_id, "rate", internal=internal),
    }


def _require_permission(owner_value: Any, base: dict[str, Any], agent_id: str, action: str) -> None:
    s = _service()
    if not s._can_access(owner_value, base, agent_id, action):
        raise s.TeamKnowledgePermissionError(f"Agent is not allowed to {action} this knowledge base.")


def _require_rating_suggestion_permission(owner_value: Any, base: dict[str, Any], agent_id: str) -> None:
    s = _service()
    if s._can_access(owner_value, base, agent_id, "rate") or s._is_global_knowledge_steward(agent_id):
        return
    raise s.TeamKnowledgePermissionError("Agent is not allowed to suggest ratings for this knowledge base.")


def _can_access(owner_value: Any, base: dict[str, Any], agent_id: str, action: str, *, internal: bool = False) -> bool:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if internal:
        return True
    if not normalized_agent_id:
        return False
    if s._is_global_knowledge_steward(normalized_agent_id) and action in {"read", "propose"}:
        return True
    acl = s._normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {})
    grants = acl.get("grants") if isinstance(acl.get("grants"), dict) else {}
    agent_grants = s._unique_strings((grants.get(action) or []) + (grants.get("*") or [])) if isinstance(grants, dict) else []
    if normalized_agent_id in agent_grants:
        return True
    owner_type = str(owner.get("ownerType") or "team").strip()
    owner_id = str(owner.get("ownerId") or "").strip()
    if owner_type == "agent":
        return normalized_agent_id == owner_id
    team = owner.get("team") if isinstance(owner.get("team"), dict) else owner
    role = s._member_role(team, normalized_agent_id)
    if action == "read":
        return bool(role)
    if action == "propose":
        return bool(role)
    if action == "review":
        return role in s.REVIEW_ROLES
    if action == "rate":
        return role in s.REVIEW_ROLES
    return False


def _can_collect_owner_source(owner_value: Any, agent_id: str) -> bool:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if s._is_global_knowledge_steward(normalized_agent_id):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    return bool(s._member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id))


def _can_read_owner_source_inbox(owner_value: Any, agent_id: str) -> bool:
    s = _service()
    return s._can_collect_owner_source(owner_value, agent_id) or s._can_review_owner_source(owner_value, agent_id)


def _can_review_owner_source(owner_value: Any, agent_id: str) -> bool:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if s._is_global_knowledge_steward(normalized_agent_id):
        return True
    if normalized_agent_id in s._source_governance_for_owner(owner).get("localStewardAgentIds", []):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    role = s._member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id)
    return role in s.REVIEW_ROLES


def _can_configure_owner_source_governance(owner_value: Any, agent_id: str) -> bool:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if s._is_global_knowledge_steward(normalized_agent_id):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    role = s._member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id)
    return role in s.REVIEW_ROLES


def _is_global_knowledge_steward(agent_id: str) -> bool:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if normalized_agent_id == getattr(s.agent_directory_service, "KNOWLEDGE_STEWARD_AGENT_ID", ""):
        return True
    try:
        agent = s.agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    except Exception:
        agent = {}
    metadata = agent.get("metadata") if isinstance(agent, dict) and isinstance(agent.get("metadata"), dict) else {}
    return str(metadata.get("governanceRole") or metadata.get("systemRole") or "").strip() == "knowledge_steward"


def _permission_explain(
    team: dict[str, Any],
    base: dict[str, Any],
    agent_id: str,
    action: str,
    policy_ids: set[str],
    internal: bool = False,
) -> dict[str, Any]:
    s = _service()
    owner = s._coerce_owner_context(team)
    base_id = str(base.get("knowledgeBaseId") or "")
    team_allowed = s._can_access(owner, base, agent_id, action, internal=internal)
    policy_allowed = s.knowledge_base_policy_allows(s._owner_scoped_knowledge_base_id(owner, base_id), policy_ids)
    allowed = team_allowed and policy_allowed
    reason = "allowed"
    if not team_allowed:
        reason = "agent_owner_blocked" if str(owner.get("ownerType") or "") == "agent" else "team_acl_blocked"
    elif not policy_allowed:
        reason = "memory_policy_blocked"
    return {
        "allowed": allowed,
        "reason": reason,
        "teamAclAllowed": team_allowed if str(owner.get("ownerType") or "") == "team" else False,
        "agentOwnerAllowed": team_allowed if str(owner.get("ownerType") or "") == "agent" else False,
        "memoryPolicyAllowed": policy_allowed,
        "memoryPolicyExplicit": bool(policy_ids),
    }


def _member_role(team: dict[str, Any], agent_id: str) -> str:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    for member in list(team.get("members") or []):
        if isinstance(member, dict) and str(member.get("agentId") or "").strip() == normalized_agent_id:
            return str(member.get("role") or "member").strip().lower() or "member"
    return ""


def _normalize_acl(raw: Any) -> dict[str, Any]:
    s = _service()
    payload = raw if isinstance(raw, dict) else {}
    return {
        "read": str(payload.get("read") or "team").strip() or "team",
        "propose": str(payload.get("propose") or "team").strip() or "team",
        "review": str(payload.get("review") or "review_roles").strip() or "review_roles",
        "grants": {
            "read": s._unique_strings((payload.get("grants") or {}).get("read") if isinstance(payload.get("grants"), dict) else []),
            "propose": s._unique_strings((payload.get("grants") or {}).get("propose") if isinstance(payload.get("grants"), dict) else []),
            "review": s._unique_strings((payload.get("grants") or {}).get("review") if isinstance(payload.get("grants"), dict) else []),
            "*": s._unique_strings((payload.get("grants") or {}).get("*") if isinstance(payload.get("grants"), dict) else []),
        },
    }
