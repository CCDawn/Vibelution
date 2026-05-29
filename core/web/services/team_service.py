"""Team registry and organization canvas service."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, project_agent_bus_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
CANVAS_KIND = "team_organization_canvas"
DEFAULT_TEAM_STATUS = "active"
TEAM_STATUSES = {"active", "archived"}
NODE_TYPES = {"role", "agent", "group", "user", "external"}
EDGE_TYPES = {"reports_to", "collaborates_with", "delegates_to", "observes", "supports"}
_TEAM_LOCK = threading.RLock()
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


class TeamServiceError(ValueError):
    """Raised when a team request is invalid."""


class TeamNotFoundError(TeamServiceError):
    """Raised when a team does not exist."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def list_teams(*, include_archived: bool = False) -> dict[str, Any]:
    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_state(state):
            _save_index(state)
    teams = [
        _team_to_api(item)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": teams,
        "summary": _summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": _relative_path(_teams_index_path()), "teamRoot": _relative_path(_teams_root())},
    }


def create_team(
    *,
    name: str,
    description: str = "",
    purpose: str = "",
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamServiceError("Team name is required.")
    now = utc_now_iso()
    with _TEAM_LOCK:
        state = _load_index()
        existing_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
        }
        team_id = _new_team_id(normalized_name, existing_ids)
        normalized_members = _normalize_members(members or [], require_active=True)
        team = {
            "teamId": team_id,
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=8).strip(),
            "purpose": trim_lines(purpose or "", max_lines=4).strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": normalized_members,
            "linkedChatRoomId": "",
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "createdAt": now,
            "updatedAt": now,
        }
        state.setdefault("teams", []).append(team)
        state["updatedAt"] = now
        _save_index(state)
        canvas = _default_canvas_for_team(team)
        _write_json(_team_canvas_path(team_id), canvas)
        _ensure_team_chat_room_link(team)
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    _record_team_event("team.created", team, fields={"memberCount": len(normalized_members)})
    return get_team(team_id)


def get_team(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team):
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    return _team_detail_to_api(team)


def update_team(
    team_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    purpose: str | None = None,
    status: str | None = None,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if name is not None:
            normalized_name = trim_lines(name or "", max_lines=1).strip()
            if not normalized_name:
                raise TeamServiceError("Team name is required.")
            team["name"] = normalized_name
        if description is not None:
            team["description"] = trim_lines(description or "", max_lines=8).strip()
        if purpose is not None:
            team["purpose"] = trim_lines(purpose or "", max_lines=4).strip()
        if status is not None:
            normalized_status = str(status or "").strip().lower() or DEFAULT_TEAM_STATUS
            if normalized_status not in TEAM_STATUSES:
                raise TeamServiceError(f"Unsupported team status: {status}")
            team["status"] = normalized_status
        if members is not None:
            team["members"] = _normalize_members(members, require_active=True)
        team["updatedAt"] = utc_now_iso()
        team["canvasPath"] = _relative_path(_team_canvas_path(normalized_team_id))
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    _record_team_event("team.updated", team, fields={"memberCount": len(team.get("members") or [])})
    return get_team(normalized_team_id)


def archive_team(team_id: str) -> dict[str, Any]:
    return update_team(team_id, status="archived")


def send_team_message(
    team_id: str,
    *,
    content: str,
    interrupt_mode: str = "none",
    wake_target: bool = True,
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    team = _get_team_record(team_id)
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        raise TeamServiceError("Archived teams cannot receive new messages.")
    normalized_content = trim_lines(content or "", max_lines=40).strip()
    if not normalized_content:
        raise TeamServiceError("Team message content is required.")
    target_agent_ids = _active_member_agent_ids(team)
    if not target_agent_ids:
        raise TeamServiceError("Team has no active Agent members.")
    _sync_project_bus_root()
    event = project_agent_bus_service.send_project_agent_bus_message(
        content=normalized_content,
        target_scope="agents",
        target_agent_ids=target_agent_ids,
        interrupt_mode=interrupt_mode,
        wake_target=wake_target,
        created_by=created_by,
        metadata={
            **(metadata or {}),
            "teamId": team["teamId"],
            "teamName": str(team.get("name") or ""),
            "source": "team",
        },
    )
    _record_team_event(
        "team.message.sent",
        team,
        fields={
            "projectBusEventId": event.get("eventId"),
            "targetAgentIds": event.get("targetAgentIds") or [],
            "deliveryCount": len(event.get("deliveries") or []),
            "interruptMode": interrupt_mode,
            "wakeTarget": bool(wake_target),
        },
    )
    return event


def sync_team_chat_room(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team):
            state["updatedAt"] = utc_now_iso()
        _ensure_team_chat_room_link(team)
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    return get_team(normalized_team_id)


def get_team_canvas(team_id: str) -> dict[str, Any]:
    team = _get_team_record(team_id)
    canvas_path = _team_canvas_path(team["teamId"])
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    canvas = _normalize_canvas(raw or _default_canvas_for_team(team), team)
    validation = _validate_canvas(canvas)
    if raw != canvas:
        _write_json(canvas_path, canvas)
    return {**canvas, "validation": validation}


def save_team_canvas(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = get_team(team_id)
    canvas = _normalize_canvas(payload, team)
    validation = _validate_canvas(canvas)
    if not validation["valid"]:
        raise TeamServiceError(_format_validation_error(validation))
    canvas["updatedAt"] = utc_now_iso()
    with _TEAM_LOCK:
        _write_json(_team_canvas_path(team["teamId"]), canvas)
        state = _load_index()
        stored = _find_team(state, team["teamId"])
        if stored is not None:
            stored["updatedAt"] = canvas["updatedAt"]
            stored["canvasPath"] = _relative_path(_team_canvas_path(team["teamId"]))
            stored["members"] = _sync_members_from_canvas(stored.get("members") or [], canvas)
            _ensure_team_chat_room_link(stored)
            state["updatedAt"] = canvas["updatedAt"]
            _save_index(state)
    _record_team_event(
        "team.canvas.updated",
        team,
        fields={"nodeCount": len(canvas["nodes"]), "edgeCount": len(canvas["edges"]), "valid": validation["valid"]},
    )
    return {**canvas, "validation": validation}


def list_agent_team_references() -> dict[str, list[dict[str, Any]]]:
    references: dict[str, list[dict[str, Any]]] = {}
    for team in list_teams(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        status = str(team.get("status") or DEFAULT_TEAM_STATUS).strip()
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if not agent_id:
                continue
            references.setdefault(agent_id, []).append(
                {
                    "kind": "team",
                    "sourceId": team_id,
                    "sourceLabel": str(team.get("name") or team_id),
                    "field": str(member.get("memberId") or ""),
                    "route": "/agents/teams",
                    "status": "stale" if str(member.get("agentStatus") or "") != "active" or status == "archived" else "active",
                }
            )
    return references


def _normalize_canvas(raw: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TeamServiceError("Team canvas payload must be an object.")
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if not nodes:
        nodes = _default_nodes_for_members(team.get("members") or [])
    normalized_nodes = [_normalize_node(item, index) for index, item in enumerate(nodes[:120])]
    node_ids = [node["id"] for node in normalized_nodes]
    if len(node_ids) != len(set(node_ids)):
        raise TeamServiceError("Team canvas node ids must be unique.")
    node_id_set = set(node_ids)
    normalized_edges = [_normalize_edge(item, index, node_id_set) for index, item in enumerate(edges[:240])]
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(raw.get("updatedAt") or team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(team["teamId"])),
        "viewport": {
            "x": _safe_float(viewport.get("x"), 0.0),
            "y": _safe_float(viewport.get("y"), 0.0),
            "zoom": min(2.0, max(0.45, _safe_float(viewport.get("zoom"), 1.0))),
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def _normalize_node(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamServiceError("Team canvas node must be an object.")
    node_id = _safe_token(item.get("id"), default=f"node-{index + 1}", max_length=96)
    agent_id = _safe_token(item.get("agentId"), default="", max_length=128)
    agent = agent_directory_service.get_agent(agent_id, include_archived=True) if agent_id else None
    active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
    node_type = _safe_token(item.get("type"), default="role", max_length=40)
    status = "bound" if active_agent else "stale" if agent_id else "unbound"
    return {
        "id": node_id,
        "label": trim_lines(item.get("label") or (agent or {}).get("displayName") or f"角色 {index + 1}", max_lines=1).strip(),
        "type": node_type if node_type in NODE_TYPES else "role",
        "status": status,
        "x": _safe_float(item.get("x"), 120.0 + index * 220.0),
        "y": _safe_float(item.get("y"), 120.0),
        "agentId": agent_id,
        "agentCode": str((agent or {}).get("agentCode") or "").strip(),
        "agentName": str((agent or {}).get("displayName") or "").strip(),
        "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
        "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
    }


def _normalize_edge(item: Any, index: int, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamServiceError("Team canvas edge must be an object.")
    source = _safe_token(item.get("source"), default="", max_length=96)
    target = _safe_token(item.get("target"), default="", max_length=96)
    if source not in node_ids or target not in node_ids:
        raise TeamServiceError("Team canvas edge must reference existing nodes.")
    edge_type = _safe_token(item.get("type"), default="collaborates_with", max_length=40)
    return {
        "id": _safe_token(item.get("id"), default=f"edge-{index + 1}", max_length=96),
        "source": source,
        "target": target,
        "label": trim_lines(item.get("label") or "", max_lines=1).strip(),
        "type": edge_type if edge_type in EDGE_TYPES else "collaborates_with",
    }


def _validate_canvas(canvas: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    node_ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            issues.append(_issue("error", "missing_node_id", "画布节点缺少 id。"))
            continue
        if node_id in node_ids:
            issues.append(_issue("error", "duplicate_node_id", f"节点 id 重复：{node_id}", node_id=node_id))
        node_ids.add(node_id)
        agent_id = str(node.get("agentId") or "").strip()
        if agent_id and not agent_directory_service.get_agent(agent_id, include_archived=False):
            issues.append(_issue("warning", "stale_agent_ref", f"节点绑定的 Agent 不可用：{agent_id}", node_id=node_id))
    for edge in edges:
        edge_id = str(edge.get("id") or "").strip()
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            issues.append(_issue("error", "missing_edge_endpoint", "组织关系线引用了不存在的节点。", edge_id=edge_id, source=source, target=target))
    errors = [item for item in issues if item.get("severity") == "error"]
    warnings = [item for item in issues if item.get("severity") == "warning"]
    return {
        "valid": not errors,
        "summary": {"errorCount": len(errors), "warningCount": len(warnings), "issueCount": len(issues)},
        "issues": issues,
    }


def _normalize_members(items: list[dict[str, Any]], *, require_active: bool) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=not require_active)
        if not agent:
            if require_active:
                raise TeamServiceError(f"Team member Agent is not active: {agent_id}")
            continue
        seen.add(agent_id)
        members.append(
            {
                "memberId": _safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "agentStatus": "active",
            }
        )
    return members


def _sync_members_from_canvas(current_members: list[dict[str, Any]], canvas: dict[str, Any]) -> list[dict[str, Any]]:
    by_agent = {
        str(member.get("agentId") or "").strip(): dict(member)
        for member in current_members
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    for index, node in enumerate(canvas.get("nodes") or []):
        agent_id = str(node.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        if not agent:
            continue
        member = by_agent.get(agent_id) or {"memberId": f"member-{index + 1}", "agentId": agent_id}
        member.update(
            {
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or "").strip(),
                "role": str(node.get("role") or member.get("role") or "").strip(),
                "purpose": str(node.get("purpose") or member.get("purpose") or "").strip(),
                "agentStatus": "active" if str(agent.get("status") or "active") != "archived" else "stale",
            }
        )
        by_agent[agent_id] = member
    return list(by_agent.values())


def _active_member_agent_ids(team: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if not agent_directory_service.get_agent(agent_id, include_archived=False):
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    return ids


def _active_member_session_ids(team: dict[str, Any]) -> list[str]:
    session_ids: list[str] = []
    seen: set[str] = set()
    for agent_id in _active_member_agent_ids(team):
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    return session_ids


def _team_chat_room_title(team: dict[str, Any]) -> str:
    name = str(team.get("name") or team.get("teamId") or "Team").strip()
    return f"{name} 团队群聊"


def _sync_chat_room_root() -> None:
    if chat_room_service.PROJECT_ROOT != PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = PROJECT_ROOT


def _ensure_team_chat_room_link(team: dict[str, Any]) -> str:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return str(team.get("linkedChatRoomId") or "").strip()
    session_ids = _active_member_session_ids(team)
    if not session_ids:
        team["linkedChatRoomId"] = ""
        return ""
    _sync_chat_room_root()
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    title = _team_chat_room_title(team)
    config = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
    }
    if linked_room_id and chat_room_service.get_chat_room_detail(linked_room_id):
        room = chat_room_service.update_chat_room(
            linked_room_id,
            title=title,
            participant_session_ids=session_ids,
            purpose="discussion",
            config=config,
        )
    else:
        room = chat_room_service.create_chat_room(
            title=title,
            participant_session_ids=session_ids,
            mode="round_robin",
            purpose="discussion",
            config=config,
        )
    team["linkedChatRoomId"] = str(room.get("roomId") or "").strip()
    team["updatedAt"] = utc_now_iso()
    _record_team_event(
        "team.chat_room.synced",
        team,
        fields={
            "linkedChatRoomId": team["linkedChatRoomId"],
            "memberSessionCount": len(session_ids),
        },
    )
    return team["linkedChatRoomId"]


def _team_to_api(team: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(team)
    _repair_team(repaired)
    canvas_summary = _canvas_summary_for_team(repaired)
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_detail(linked_room_id) if linked_room_id else None
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": canvas_summary,
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
    }


def _team_detail_to_api(team: dict[str, Any]) -> dict[str, Any]:
    return {**_team_to_api(team), "canvas": get_team_canvas(str(team.get("teamId") or ""))}


def _get_team_record(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team):
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
        return dict(team)


def _canvas_summary_for_team(team: dict[str, Any]) -> dict[str, Any]:
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return {"path": "", "nodeCount": 0, "edgeCount": 0, "validation": _validate_canvas({"nodes": [], "edges": []})}
    canvas_path = _team_canvas_path(team_id)
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    try:
        canvas = _normalize_canvas(raw or _default_canvas_for_team(team), team)
        validation = _validate_canvas(canvas)
    except TeamServiceError as exc:
        canvas = {"nodes": [], "edges": []}
        validation = {
            "valid": False,
            "summary": {"errorCount": 1, "warningCount": 0, "issueCount": 1},
            "issues": [_issue("error", "invalid_canvas", str(exc))],
        }
    return {
        "path": str(team.get("canvasPath") or _relative_path(canvas_path)),
        "nodeCount": len(canvas.get("nodes") or []),
        "edgeCount": len(canvas.get("edges") or []),
        "validation": validation,
    }


def _repair_index_state(state: dict[str, Any]) -> bool:
    changed = False
    if state.get("schemaVersion") != SCHEMA_VERSION:
        state["schemaVersion"] = SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    for team in state.get("teams") or []:
        if isinstance(team, dict):
            changed = _repair_team(team) or changed
    return changed


def _repair_team(team: dict[str, Any]) -> bool:
    changed = False
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    if not str(team.get("name") or "").strip():
        team["name"] = team_id or "Team"
        changed = True
    if str(team.get("status") or DEFAULT_TEAM_STATUS) not in TEAM_STATUSES:
        team["status"] = DEFAULT_TEAM_STATUS
        changed = True
    expected_path = _relative_path(_team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    members = team.get("members") if isinstance(team.get("members"), list) else []
    repaired_members = _repair_members(members)
    if repaired_members != members:
        team["members"] = repaired_members
        changed = True
    return changed


def _repair_members(members: list[Any]) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(members):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        active = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
        repaired.append(
            {
                "memberId": _safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or item.get("agentName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "agentStatus": "active" if active else "stale",
            }
        )
    return repaired


def _default_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(team["teamId"])),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": _default_nodes_for_members(team.get("members") or []),
        "edges": [],
    }


def _default_nodes_for_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        nodes.append(
            {
                "id": f"node-{index + 1}",
                "label": str(member.get("agentName") or agent_id),
                "type": "agent",
                "status": str(member.get("agentStatus") or "active"),
                "x": 120 + index * 220,
                "y": 120,
                "agentId": agent_id,
                "agentCode": str(member.get("agentCode") or ""),
                "agentName": str(member.get("agentName") or ""),
                "role": str(member.get("role") or ""),
                "purpose": str(member.get("purpose") or ""),
            }
        )
    if nodes:
        return nodes
    return [
        {
            "id": "team-lead",
            "label": "团队负责人",
            "type": "role",
            "status": "unbound",
            "x": 220,
            "y": 120,
            "agentId": "",
            "agentCode": "",
            "agentName": "",
            "role": "lead",
            "purpose": "",
        }
    ]


def _load_index() -> dict[str, Any]:
    path = _teams_index_path()
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}
    return data if isinstance(data, dict) else {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}


def _save_index(state: dict[str, Any]) -> None:
    _write_json(_teams_index_path(), state)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _teams_root() -> Path:
    return _project_root() / "workspace" / "teams"


def _teams_index_path() -> Path:
    return _teams_root() / "teams.json"


def _team_canvas_path(team_id: str) -> Path:
    return _teams_root() / _safe_token(team_id, default="team", max_length=96) / "canvas.json"


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_project_bus_root() -> None:
    if project_agent_bus_service.PROJECT_ROOT != PROJECT_ROOT:
        project_agent_bus_service.PROJECT_ROOT = PROJECT_ROOT


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _find_team(state: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    for item in list(state.get("teams") or []):
        if isinstance(item, dict) and str(item.get("teamId") or "").strip() == team_id:
            return item
    return None


def _new_team_id(name: str, existing_ids: set[str]) -> str:
    base = _safe_token(name, default="team", max_length=48).lower()
    candidate = base
    index = 2
    while candidate in existing_ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _normalize_required_id(value: str, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=96)
    if not normalized:
        raise TeamServiceError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: str = "",
    edge_id: str = "",
    source: str = "",
    target: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "nodeId": node_id,
        "edgeId": edge_id,
        "source": source,
        "target": target,
    }


def _format_validation_error(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    details = "; ".join(str(item.get("message") or item.get("code") or "") for item in issues[:3] if isinstance(item, dict))
    return f"Team canvas contract invalid: {details or 'unknown validation error'}"


def _summary(teams: list[dict[str, Any]]) -> dict[str, Any]:
    active = [team for team in teams if str(team.get("status") or DEFAULT_TEAM_STATUS) != "archived"]
    return {
        "teamCount": len(teams),
        "activeTeamCount": len(active),
        "memberCount": sum(len(team.get("members") or []) for team in active),
        "staleMemberCount": sum(
            1
            for team in active
            for member in list(team.get("members") or [])
            if isinstance(member, dict) and str(member.get("agentStatus") or "") != "active"
        ),
    }


def _compact_chat_room(room: dict[str, Any] | None) -> dict[str, Any] | None:
    if not room:
        return None
    return {
        "roomId": str(room.get("roomId") or "").strip(),
        "title": str(room.get("title") or "").strip(),
        "status": str(room.get("status") or "").strip(),
        "mode": str(room.get("mode") or "").strip(),
        "purpose": str(room.get("purpose") or "").strip(),
        "participantCount": len(list(room.get("participants") or [])),
        "updatedAt": str(room.get("updatedAt") or "").strip(),
    }


def _record_team_event(event_code: str, team: dict[str, Any], *, fields: dict[str, Any] | None = None) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            event_code,
            message=f"Team {team.get('teamId')} {event_code}",
            outcome="succeeded",
            fields={
                "teamId": team.get("teamId"),
                "teamName": team.get("name"),
                "status": team.get("status"),
                **(fields or {}),
            },
        )
    except Exception:
        pass
