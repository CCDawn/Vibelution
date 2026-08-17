"""Team API projection and agent-reference helpers.

Claim scope: team/list/detail DTO projection and lightweight agent reference maps.
Late-binds ``team_service`` for index load, kind inference, canvas path summary,
and compact chat-room helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service, chat_room_service
from core.web.services.team_conversation_contract import build_team_conversation_projection


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def _team_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    s = _service()
    repaired = dict(team)
    s._repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = s._members_to_api(repaired.get("members"))
    canvas_summary = s._canvas_summary_for_team(repaired, agent_refs=agent_refs)
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    s._sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": canvas_summary,
        **s._ai_search_source_scope_api_fields(repaired),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": s._compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _team_to_compact_reference(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    repaired = dict(team)
    s._apply_team_contract(repaired)
    team_id = s._safe_token(team.get("teamId"), default="", max_length=96)
    members = s._members_to_api(repaired.get("members"))
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    if compact_rooms_by_id is None:
        s._sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id) if linked_room_id else None
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or s.DEFAULT_TEAM_STATUS).strip() or s.DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "sourceScopePath": str(repaired.get("sourceScopePath") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": s._compact_chat_room(linked_room),
        "canvasPath": str(repaired.get("canvasPath") or (s._relative_path(s._team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_to_graph_reference(team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    repaired = dict(team)
    s._apply_team_contract(repaired)
    team_id = s._safe_token(repaired.get("teamId"), default="", max_length=96)
    members = s._members_to_api(repaired.get("members"))
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or s.DEFAULT_TEAM_STATUS).strip() or s.DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": str(repaired.get("linkedChatRoomId") or "").strip(),
        "canvasPath": str(repaired.get("canvasPath") or (s._relative_path(s._team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_detail_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    s = _service()
    agent_refs = agent_refs or s._agent_reference_maps()
    return {
        **s._team_to_api_without_canvas_summary(team, agent_refs=agent_refs),
        "canvas": s._team_canvas_with_validation(
            team,
            agents_by_id=agent_refs["by_id"],
            active_agents_by_id=agent_refs["active_by_id"],
        ),
    }


def _team_to_api_without_canvas_summary(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    s = _service()
    repaired = dict(team)
    s._repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = s._members_to_api(repaired.get("members"))
    team_id = str(repaired.get("teamId") or "").strip()
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    s._sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": s._canvas_path_summary(repaired, team_id=team_id),
        **s._ai_search_source_scope_api_fields(repaired),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": s._compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _members_to_api(members: Any) -> list[dict[str, Any]]:
    s = _service()
    result: list[dict[str, Any]] = []
    for index, member in enumerate(list(members or [])):
        if not isinstance(member, dict) or not str(member.get("agentId") or "").strip():
            continue
        payload = {
            "memberId": s._safe_token(member.get("memberId"), default=f"member-{index + 1}", max_length=96),
            "agentId": str(member.get("agentId") or "").strip(),
            "agentCode": str(member.get("agentCode") or "").strip(),
            "agentName": str(member.get("agentName") or "").strip(),
            "role": trim_lines(member.get("role") or "", max_lines=1).strip(),
            "purpose": trim_lines(member.get("purpose") or "", max_lines=4).strip(),
            "agentStatus": str(member.get("agentStatus") or "active").strip() or "active",
        }
        responsibilities = [
            trim_lines(value, max_lines=2).strip()
            for value in list(member.get("responsibilities") or [])[:8]
            if str(value or "").strip()
        ]
        if responsibilities:
            payload["responsibilities"] = responsibilities
        result.append(payload)
    return result


def _get_team_record(
    team_id: str,
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        if s._repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
        return dict(team)


def _agent_reference_maps() -> dict[str, dict[str, dict[str, Any]]]:
    s = _service()
    agents = s._load_lightweight_agent_references()
    return s._agent_reference_maps_from_agents(agents)


def lookup_agent_display_name_map() -> dict[str, str]:
    """Map agentId → displayName from lightweight Agent identity fields.

    Avoids Agent directory repair and full `_agent_to_api` hydration.
    """
    s = _service()
    names: dict[str, str] = {}
    for agent_id, agent in (s._agent_reference_maps().get("by_id") or {}).items():
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("displayName") or "").strip()
        if agent_id and name:
            names[str(agent_id)] = name
    return names


def _load_lightweight_agent_references() -> list[dict[str, Any]]:
    """Read Agent identity fields without running Agent repair or API hydration."""

    s = _service()
    path = developer_sandbox.seeded_sandbox_workspace_path(s._project_root(), "agents", "agents.json")
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    agents: list[dict[str, Any]] = []
    for item in list(payload.get("agents") or []):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        agents.append(
            {
                "agentId": agent_id,
                "agentCode": str(item.get("agentCode") or "").strip(),
                "displayName": str(item.get("displayName") or "").strip(),
                "directSessionId": str(item.get("directSessionId") or "").strip(),
                "status": str(item.get("status") or "active").strip() or "active",
                "metadata": dict(metadata),
                "createdAt": str(item.get("createdAt") or "").strip(),
                "updatedAt": str(item.get("updatedAt") or "").strip(),
            }
        )
    return agents


def _agent_reference_maps_from_agents(agents: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    s = _service()
    by_id: dict[str, dict[str, Any]] = {}
    active_by_id: dict[str, dict[str, Any]] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        copied = dict(agent)
        by_id[agent_id] = copied
        if str(agent.get("status") or "active").strip() != "archived":
            active_by_id[agent_id] = copied
    return {"by_id": by_id, "active_by_id": active_by_id}


def _merged_agent_reference_maps(*agent_groups: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    s = _service()
    merged: dict[str, dict[str, Any]] = {}
    for agents in agent_groups:
        for agent in list(agents or []):
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("agentId") or "").strip()
            if agent_id:
                merged[agent_id] = dict(agent)
    return s._agent_reference_maps_from_agents(list(merged.values()))


def _agent_reference(
    agent_id: str,
    *,
    include_archived: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return None
    if agent_refs is not None:
        key = "by_id" if include_archived else "active_by_id"
        agent = (agent_refs.get(key) or {}).get(normalized_agent_id)
        return dict(agent) if isinstance(agent, dict) else None
    return agent_directory_service.get_agent(normalized_agent_id, include_archived=include_archived)
