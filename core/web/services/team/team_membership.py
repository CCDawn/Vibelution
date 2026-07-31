"""Team membership and contract shared helpers.

Claim scope: active-member agent/session resolution, cross-team agent lookup,
and teamKind/source contract application.
Late-binds ``team_service`` for kind helpers and defaults.
"""

from __future__ import annotations

from typing import Any

from core.chat.chat_task_types import trim_lines


def _service():
    from core.web.services import team_service

    return team_service


def _find_active_team_for_agent(agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    s = _service()
    state = s._load_index()
    return s._find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=excluding_team_id)


def _find_active_team_for_agent_in_state(state: dict[str, Any], agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_excluding_team_id = str(excluding_team_id or "").strip()
    if not normalized_agent_id:
        return None
    for team in list(state.get("teams") or []):
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or "").strip()
        if team_id == normalized_excluding_team_id:
            continue
        if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            continue
        for member in list(team.get("members") or []):
            if isinstance(member, dict) and str(member.get("agentId") or "").strip() == normalized_agent_id:
                return team
    return None


def _unique_active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    agent_ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = s._agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        if not agent or str(agent.get("status") or "active").strip() == "archived":
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if not s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs):
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    return ids


def _active_member_session_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    session_ids: list[str] = []
    seen: set[str] = set()
    for agent_id in s._active_member_agent_ids(team, agent_refs=agent_refs):
        agent = s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    return session_ids


def _apply_team_contract(
    team: dict[str, Any],
    *,
    team_kind: str = "",
    team_category: str = "",
    team_source: str = "",
    team_template_id: str = "",
) -> bool:
    s = _service()
    inferred_kind = s._infer_team_kind(team, fallback=team_kind)
    defaults = s.TEAM_KIND_DEFAULTS.get(inferred_kind, s.TEAM_KIND_DEFAULTS["custom"])
    expected = {
        "teamKind": inferred_kind,
        "teamCategory": trim_lines(team_category or team.get("teamCategory") or defaults["teamCategory"], max_lines=1).strip(),
        "teamSource": str(team_source or team.get("teamSource") or defaults["teamSource"]).strip(),
        "teamTemplateId": str(team_template_id or team.get("teamTemplateId") or "").strip(),
    }
    if expected["teamSource"] in s.TEAM_SOURCE_TO_KIND:
        expected["teamKind"] = s.TEAM_SOURCE_TO_KIND[expected["teamSource"]]
    if expected["teamKind"] != "template_demo":
        expected["teamTemplateId"] = ""
    elif not expected["teamTemplateId"]:
        expected["teamTemplateId"] = s._infer_team_template_id(team)
    changed = False
    for key, value in expected.items():
        if team.get(key) != value:
            team[key] = value
            changed = True
    return changed
