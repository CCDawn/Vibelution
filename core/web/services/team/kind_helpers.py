"""Pure team-kind inference helpers.

Claim scope: map teamKind/source/template ids without registry IO or disk paths.
"""

from __future__ import annotations

from typing import Any

AI_SEARCH_TEAM_ID = "ai-search-team"
KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team"
EVOLUTION_SYSTEM_TEAM_IDS = {"self-evolution-team", "supervised-evolution-team"}

TEAM_KIND_DEFAULTS = {
    "custom": {"teamCategory": "自定义团队", "teamSource": "manual", "chatRoomPurpose": "discussion"},
    "research": {
        "teamCategory": "科研组织团队",
        "teamSource": "research_organization",
        "chatRoomPurpose": "research_coordination",
    },
    "knowledge_expansion": {
        "teamCategory": "知识库扩充团队",
        "teamSource": "knowledge_expansion",
        "chatRoomPurpose": "knowledge_expansion",
    },
    "ai_search": {"teamCategory": "AI 搜索系统团队", "teamSource": "ai_search", "chatRoomPurpose": "ai_search"},
    "self_evolution": {
        "teamCategory": "自进化系统团队",
        "teamSource": "self_evolution",
        "chatRoomPurpose": "self_evolution",
    },
    "supervised_evolution": {
        "teamCategory": "监督进化系统团队",
        "teamSource": "supervised_evolution",
        "chatRoomPurpose": "supervised_evolution",
    },
    "template_demo": {"teamCategory": "演示业务团队", "teamSource": "team_template", "chatRoomPurpose": "meeting"},
    # Financial analyst teams are provisioned and repaired by the
    # financial-team workflow (purpose prefix ``financial-stock-agent-team-v1``);
    # chatRoomPurpose stays "discussion" so pre-migration linked rooms keep
    # their purpose without a rename churn.
    "financial": {"teamCategory": "股票研究团队", "teamSource": "financial", "chatRoomPurpose": "discussion"},
}

DERIVED_TEAM_KINDS = {
    "research",
    "knowledge_expansion",
    "ai_search",
    "self_evolution",
    "supervised_evolution",
    "financial",
}

TEAM_SOURCE_TO_KIND = {
    "manual": "custom",
    "research_organization": "research",
    "knowledge_expansion": "knowledge_expansion",
    "ai_search": "ai_search",
    "self_evolution": "self_evolution",
    "supervised_evolution": "supervised_evolution",
    "team_template": "template_demo",
    "financial": "financial",
}

TEAM_ID_TO_KIND = {
    "research-team": "research",
    KNOWLEDGE_EXPANSION_TEAM_ID: "knowledge_expansion",
    AI_SEARCH_TEAM_ID: "ai_search",
    "self-evolution-team": "self_evolution",
    "supervised-evolution-team": "supervised_evolution",
}

TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID = {
    "dev-team": "dev-team",
}


def infer_team_template_id(team: dict[str, Any]) -> str:
    template_id = str(team.get("teamTemplateId") or "").strip()
    if template_id:
        return template_id
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        member_id = str(member.get("memberId") or "").strip()
        for prefix, candidate in TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID.items():
            if member_id.startswith(f"{prefix}-"):
                return candidate
    return ""


def infer_team_kind(team: dict[str, Any], *, fallback: str = "") -> str:
    explicit = str(fallback or team.get("teamKind") or "").strip()
    if explicit in TEAM_KIND_DEFAULTS:
        return explicit
    source = str(team.get("teamSource") or team.get("systemTeamKind") or "").strip()
    if source in TEAM_SOURCE_TO_KIND:
        return TEAM_SOURCE_TO_KIND[source]
    team_id = str(team.get("teamId") or "").strip()
    if team_id in TEAM_ID_TO_KIND:
        return TEAM_ID_TO_KIND[team_id]
    if infer_team_template_id(team):
        return "template_demo"
    return "custom"


def team_default_chat_room_purpose(team: dict[str, Any]) -> str:
    kind = infer_team_kind(team)
    return str(TEAM_KIND_DEFAULTS.get(kind, TEAM_KIND_DEFAULTS["custom"]).get("chatRoomPurpose") or "discussion")


# Single behavior key for workflow-managed system teams. Behavior branches
# (PATCH lock, archive refusal, derived prune, route hiding, conversation
# index exclusion) must read ``team_is_system_managed`` instead of kind
# enumerations; ``teamKind`` itself stays a display value derived from the
# team category contract.
SYSTEM_MANAGED_TEAM_IDS = {
    "research-team",
    KNOWLEDGE_EXPANSION_TEAM_ID,
    AI_SEARCH_TEAM_ID,
    *EVOLUTION_SYSTEM_TEAM_IDS,
}
SYSTEM_MANAGED_TEAM_SOURCES = {
    source
    for source, kind in TEAM_SOURCE_TO_KIND.items()
    if kind in DERIVED_TEAM_KINDS
}


def team_is_system_managed(team: dict[str, Any] | None) -> bool:
    """Return whether a workflow maintains this team's lifecycle and roster.

    Primary judgment: the team matches a managed spec id or carries a managed
    ``teamSource``. Legacy fallback: stored kind representations (``teamKind``
    or the retired ``systemTeamKind``) that still infer to a derived workflow
    kind remain managed, so pre-flag records keep their protection.
    """

    if not isinstance(team, dict):
        return False
    if str(team.get("teamId") or "").strip() in SYSTEM_MANAGED_TEAM_IDS:
        return True
    if str(team.get("teamSource") or "").strip() in SYSTEM_MANAGED_TEAM_SOURCES:
        return True
    return infer_team_kind(team) in DERIVED_TEAM_KINDS


def team_kind_allows_member_agent_cascade(team: dict[str, Any]) -> bool:
    return str(team.get("teamKind") or infer_team_kind(team)).strip() in {"custom", "template_demo"}


# Historical private aliases used by team_service.
_infer_team_template_id = infer_team_template_id
_infer_team_kind = infer_team_kind
_team_default_chat_room_purpose = team_default_chat_room_purpose
_team_kind_allows_member_agent_cascade = team_kind_allows_member_agent_cascade
