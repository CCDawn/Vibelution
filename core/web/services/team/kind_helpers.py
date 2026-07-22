"""Pure team-kind inference helpers.

Claim scope: map teamKind/source/template ids without registry IO or disk paths.
"""

from __future__ import annotations

from typing import Any

AI_SEARCH_TEAM_ID = "ai-search-team"
KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team"

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
}

DERIVED_TEAM_KINDS = {
    "research",
    "knowledge_expansion",
    "ai_search",
    "self_evolution",
    "supervised_evolution",
}

TEAM_SOURCE_TO_KIND = {
    "manual": "custom",
    "research_organization": "research",
    "knowledge_expansion": "knowledge_expansion",
    "ai_search": "ai_search",
    "self_evolution": "self_evolution",
    "supervised_evolution": "supervised_evolution",
    "team_template": "template_demo",
}

TEAM_ID_TO_KIND = {
    "research-team": "research",
    KNOWLEDGE_EXPANSION_TEAM_ID: "knowledge_expansion",
    AI_SEARCH_TEAM_ID: "ai_search",
    "self-evolution-team": "self_evolution",
    "supervised-evolution-team": "supervised_evolution",
}

TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID = {
    "medical-demo": "medical-consultation-demo",
    "heletech-demo": "heletech-maternal-digital-health-demo",
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
    if kind == "template_demo":
        template_id = str(team.get("teamTemplateId") or infer_team_template_id(team)).strip()
        if template_id == "medical-consultation-demo":
            return "medical_triage"
        if template_id == "heletech-maternal-digital-health-demo":
            return "meeting"
    return str(TEAM_KIND_DEFAULTS.get(kind, TEAM_KIND_DEFAULTS["custom"]).get("chatRoomPurpose") or "discussion")


def team_kind_allows_member_agent_cascade(team: dict[str, Any]) -> bool:
    return str(team.get("teamKind") or infer_team_kind(team)).strip() in {"custom", "template_demo"}


# Historical private aliases used by team_service.
_infer_team_template_id = infer_team_template_id
_infer_team_kind = infer_team_kind
_team_default_chat_room_purpose = team_default_chat_room_purpose
_team_kind_allows_member_agent_cascade = team_kind_allows_member_agent_cascade
