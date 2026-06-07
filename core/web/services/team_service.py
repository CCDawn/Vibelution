"""Team registry and organization canvas service."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, project_agent_bus_service
from .runtime_scene_service import record_runtime_scene_event
from .team_conversation_contract import build_team_conversation_projection


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
CANVAS_KIND = "team_organization_canvas"
DEFAULT_TEAM_STATUS = "active"
TEAM_STATUSES = {"active", "archived"}
NODE_TYPES = {"role", "agent", "group", "user", "external"}
EDGE_TYPES = {"reports_to", "communication", "collaborates_with", "delegates_to", "observes", "supports"}
_TEAM_LOCK = threading.RLock()
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
EVOLUTION_SYSTEM_TEAM_IDS = {"self-evolution-team", "supervised-evolution-team"}
EVOLUTION_SYSTEM_TEAM_SPECS = (
    {
        "teamId": "self-evolution-team",
        "name": "自进化团队",
        "description": "由自进化固定角色自动同步的系统团队。",
        "purpose": "承接自进化执行、评审与总结角色的团队通讯。",
        "source": "self_evolution",
        "teamKind": "self_evolution",
        "teamCategory": "自进化系统团队",
        "teamSource": "self_evolution",
        "chatRoomPurpose": "self_evolution",
    },
    {
        "teamId": "supervised-evolution-team",
        "name": "监督进化团队",
        "description": "由监督进化固定角色自动同步的系统团队。",
        "purpose": "承接监督进化基线、候选、评审、审计与裁决角色的团队通讯。",
        "source": "supervised_evolution",
        "teamKind": "supervised_evolution",
        "teamCategory": "监督进化系统团队",
        "teamSource": "supervised_evolution",
        "chatRoomPurpose": "supervised_evolution",
    },
)
TEAM_KIND_DEFAULTS = {
    "custom": {"teamCategory": "自定义团队", "teamSource": "manual", "chatRoomPurpose": "discussion"},
    "research": {"teamCategory": "科研组织团队", "teamSource": "research_organization", "chatRoomPurpose": "research_coordination"},
    "self_evolution": {"teamCategory": "自进化系统团队", "teamSource": "self_evolution", "chatRoomPurpose": "self_evolution"},
    "supervised_evolution": {"teamCategory": "监督进化系统团队", "teamSource": "supervised_evolution", "chatRoomPurpose": "supervised_evolution"},
    "template_demo": {"teamCategory": "演示业务团队", "teamSource": "team_template", "chatRoomPurpose": "meeting"},
}
TEAM_SOURCE_TO_KIND = {
    "manual": "custom",
    "research_organization": "research",
    "self_evolution": "self_evolution",
    "supervised_evolution": "supervised_evolution",
    "team_template": "template_demo",
}
TEAM_ID_TO_KIND = {
    "research-team": "research",
    "self-evolution-team": "self_evolution",
    "supervised-evolution-team": "supervised_evolution",
}
TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID = {
    "medical-demo": "medical-consultation-demo",
    "heletech-demo": "heletech-maternal-digital-health-demo",
}


class TeamServiceError(ValueError):
    """Raised when a team request is invalid."""


class TeamNotFoundError(TeamServiceError):
    """Raised when a team does not exist."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _perf_counter() -> float:
    return perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def list_teams(*, include_archived: bool = False) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_state(state, agent_refs=agent_refs)
        changed = _repair_archived_team_member_agents(state, reason="list_teams", strict=False, agent_refs=agent_refs) or changed
        if changed:
            _save_index(state)
    teams = [
        _team_to_api(item, agent_refs=agent_refs)
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


def list_teams_compact(*, include_archived: bool = False) -> dict[str, Any]:
    """Return Team references without canvas reads or linked room hydration."""

    _sync_chat_room_root()
    compact_rooms_by_id = {
        str(room.get("roomId") or "").strip(): room
        for room in chat_room_service.list_chat_rooms_compact()
        if isinstance(room, dict) and str(room.get("roomId") or "").strip()
    }
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_compact_contracts(state, compact_rooms_by_id=compact_rooms_by_id)
        if changed:
            _save_index(state)
    teams = [
        _team_to_compact_reference(item, compact_rooms_by_id=compact_rooms_by_id)
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


def list_team_graph_references(*, include_archived: bool = False) -> dict[str, Any]:
    """Return lightweight Team references for read-only graph surfaces."""

    state = _load_index()
    teams = [
        _team_to_graph_reference(item)
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


def evolution_system_teams_missing() -> bool:
    """Return whether the system Team bootstrap is required for the list surface."""

    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_shape(state):
            _save_index(state)
        active_team_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
            and str(item.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived"
        }
    return not EVOLUTION_SYSTEM_TEAM_IDS.issubset(active_team_ids)


def create_team(
    *,
    name: str,
    description: str = "",
    purpose: str = "",
    members: list[dict[str, Any]] | None = None,
    team_kind: str = "custom",
    team_category: str = "",
    team_source: str = "manual",
    team_template_id: str = "",
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
        _ensure_members_can_join_team(normalized_members, state, team_id)
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
        _apply_team_contract(
            team,
            team_kind=team_kind,
            team_category=team_category,
            team_source=team_source,
            team_template_id=team_template_id,
        )
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


def ensure_research_team_from_organization(organization: dict[str, Any]) -> dict[str, Any]:
    """Ensure the locked research organization has a stable Team reference."""

    team_id = "research-team"
    now = utc_now_iso()
    members = _members_from_research_organization(organization)
    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_state(state):
            state["updatedAt"] = now
        _ensure_members_can_join_team(members, state, team_id)
        team = _find_team(state, team_id)
        created = team is None
        if team is None:
            team = {
                "teamId": team_id,
                "name": "科研团队",
                "description": "由科研组织架构自动同步的系统团队。",
                "purpose": "实时展示科研团队成员、职能与组织通信关系。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": _relative_path(_team_canvas_path(team_id)),
                "createdAt": now,
                "updatedAt": now,
            }
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
            state.setdefault("teams", []).append(team)
        else:
            team["name"] = "科研团队"
            team["description"] = "由科研组织架构自动同步的系统团队。"
            team["purpose"] = "实时展示科研团队成员、职能与组织通信关系。"
            team["status"] = DEFAULT_TEAM_STATUS
            team["members"] = members
            team["canvasPath"] = _relative_path(_team_canvas_path(team_id))
            team["updatedAt"] = now
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
        state["updatedAt"] = str(team.get("updatedAt") or now)
        _save_index(state)
        canvas = _canvas_from_research_organization(organization, team)
        _write_json(_team_canvas_path(team_id), canvas)
        _ensure_team_chat_room_link(team)
        state["updatedAt"] = str(team.get("updatedAt") or now)
        _save_index(state)
    _record_team_event(
        "team.research_organization_synced",
        team,
        fields={
            "created": created,
            "memberCount": len(members),
            "nodeCount": len(canvas.get("nodes") or []),
            "edgeCount": len(canvas.get("edges") or []),
            "source": "research_organization",
        },
    )
    return get_team(team_id)


def ensure_evolution_system_teams() -> dict[str, Any]:
    """Ensure self-evolution and supervised-evolution roles are visible as Teams."""

    ensured_agents = _ensure_evolution_system_agents()
    agent_refs = _merged_agent_reference_maps(
        _load_lightweight_agent_references(),
        [agent for agents in ensured_agents.values() for agent in list(agents or []) if isinstance(agent, dict)],
    )
    teams: list[dict[str, Any]] = []
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_state(state, agent_refs=agent_refs)
        for spec in EVOLUTION_SYSTEM_TEAM_SPECS:
            team, team_changed = _ensure_evolution_system_team_in_state(
                state,
                spec,
                ensured_agents,
                agent_refs=agent_refs,
            )
            changed = changed or team_changed
            if team:
                teams.append(dict(team))
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": [get_team(str(team.get("teamId") or "")) for team in teams],
        "updatedAt": utc_now_iso(),
    }


def get_team(team_id: str) -> dict[str, Any]:
    started_at = _perf_counter()
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        changed = _repair_team(team, agent_refs=agent_refs)
        changed = _repair_archived_team_member_agents_for_team(
            team,
            state,
            reason="get_team",
            strict=False,
            agent_refs=agent_refs,
        ) or changed
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    detail = _team_detail_to_api(team, agent_refs=agent_refs)
    _record_team_detail_loaded(detail, started_at)
    return detail


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
            if normalized_status == "archived" and str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
                return _archive_team_in_state(state, team)
            team["status"] = normalized_status
        if members is not None:
            normalized_members = _normalize_members(members, require_active=True)
            _ensure_members_can_join_team(normalized_members, state, normalized_team_id)
            team["members"] = normalized_members
        team["updatedAt"] = utc_now_iso()
        team["canvasPath"] = _relative_path(_team_canvas_path(normalized_team_id))
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    _record_team_event("team.updated", team, fields={"memberCount": len(team.get("members") or [])})
    return get_team(normalized_team_id)


def remove_agent_from_teams(agent_id: str) -> dict[str, Any]:
    """Remove one unavailable Agent from active Team membership and linked rooms."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise TeamServiceError("Agent id is required.")
    changed_team_ids: list[str] = []
    with _TEAM_LOCK:
        state = _load_index()
        teams = [item for item in list(state.get("teams") or []) if isinstance(item, dict)]
        now = utc_now_iso()
        for team in teams:
            if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
                continue
            members = [dict(item) for item in list(team.get("members") or []) if isinstance(item, dict)]
            next_members = [
                member
                for member in members
                if str(member.get("agentId") or "").strip() != normalized_agent_id
            ]
            if next_members == members:
                continue
            team["members"] = next_members
            team["updatedAt"] = now
            team["canvasPath"] = _relative_path(_team_canvas_path(str(team.get("teamId") or "").strip()))
            _remove_agent_from_team_canvas(team, normalized_agent_id)
            _sync_chat_room_root()
            _ensure_team_chat_room_link(team)
            changed_team_ids.append(str(team.get("teamId") or "").strip())
        if changed_team_ids:
            state["updatedAt"] = now
            _save_index(state)
    for team_id in changed_team_ids:
        _record_team_event(
            "team.agent_membership.removed",
            {"teamId": team_id, "status": DEFAULT_TEAM_STATUS},
            fields={"agentId": normalized_agent_id},
        )
    return {
        "agentId": normalized_agent_id,
        "changedTeamIds": changed_team_ids,
    }


def _remove_agent_from_team_canvas(team: dict[str, Any], agent_id: str) -> None:
    team_id = str(team.get("teamId") or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not team_id or not normalized_agent_id:
        return
    canvas_path = _team_canvas_path(team_id)
    raw = _read_json(canvas_path) if canvas_path.exists() else _default_canvas_for_team(team)
    if not isinstance(raw, dict):
        raw = _default_canvas_for_team(team)
    removed_node_ids = {
        str(node.get("id") or "").strip()
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() == normalized_agent_id
    }
    nodes = [
        dict(node)
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() != normalized_agent_id
    ]
    if not nodes:
        nodes = _default_nodes_for_members(team.get("members") or [])
    edges = [
        dict(edge)
        for edge in list(raw.get("edges") or [])
        if isinstance(edge, dict)
        and str(edge.get("source") or "").strip() not in removed_node_ids
        and str(edge.get("target") or "").strip() not in removed_node_ids
    ]
    canvas = {
        **raw,
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team_id,
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(canvas_path),
        "nodes": nodes,
        "edges": edges,
    }
    _write_json(canvas_path, canvas)


def archive_team(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
            member_changed = _repair_archived_team_member_agents_for_team(
                team,
                state,
                reason="archive_team_already_archived",
                strict=True,
            )
            room_changed = _repair_archived_team_linked_chat_room(team, reason="archive_team_already_archived")
            if member_changed or room_changed:
                state["updatedAt"] = utc_now_iso()
                _save_index(state)
            return get_team(normalized_team_id)
        return _archive_team_in_state(state, team)


def _archive_team_in_state(state: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    team_id = str(team.get("teamId") or "").strip()
    team_kind = str(team.get("teamKind") or _infer_team_kind(team)).strip() or "custom"
    if team_kind in {"research", "self_evolution", "supervised_evolution"}:
        _record_team_archive_rejected(team, reason="system_team")
        raise TeamServiceError("System Team cannot be archived with cascade Agent deletion.")
    if team_kind not in {"custom", "template_demo"}:
        _record_team_archive_rejected(team, reason="unsupported_team_kind")
        raise TeamServiceError(f"Team kind cannot be archived with cascade Agent deletion: {team_kind}")

    agent_ids = _unique_active_member_agent_ids(team)
    _ensure_team_member_agents_can_archive(team, agent_ids)
    deleted_room_ids = _delete_team_linked_chat_rooms(team, reason="team_archive", strict_busy=True)
    room_cleanup = _remove_team_member_agents_from_chat_rooms(team, agent_ids)

    now = utc_now_iso()
    team["status"] = "archived"
    team["updatedAt"] = now
    team["canvasPath"] = _relative_path(_team_canvas_path(team_id))
    state["updatedAt"] = now
    _save_index(state)

    archived_agent_ids = _archive_team_member_agents(team, agent_ids, reason="team_archive")

    _record_team_event(
        "team.archived_with_agents",
        team,
        fields={
            "archivedAgentIds": archived_agent_ids,
            "archivedAgentCount": len(archived_agent_ids),
            "deletedLinkedChatRoomIds": deleted_room_ids,
            "deletedLinkedChatRoomCount": len(deleted_room_ids),
            "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
            "removedFromRoomCount": len(list(room_cleanup.get("changedRoomIds") or [])),
            "roomCleanupByAgentId": dict(room_cleanup.get("removedByAgentId") or {}),
        },
    )
    return get_team(team_id)


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
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = utc_now_iso()
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    return get_team(normalized_team_id)


def get_team_canvas(team_id: str) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    team = _get_team_record(team_id, agent_refs=agent_refs)
    return _team_canvas_with_validation(
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )


def _team_canvas_with_validation(
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    canvas_path = _team_canvas_path(team["teamId"])
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    canvas = _normalize_canvas(
        raw or _default_canvas_for_team(team),
        team,
        agents_by_id=agents_by_id,
        active_agents_by_id=active_agents_by_id,
    )
    validation = _validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=active_agents_by_id)
    if raw != canvas:
        _write_json(canvas_path, canvas)
    return {**canvas, "validation": validation}


def save_team_canvas(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    team = get_team(team_id)
    canvas = _normalize_canvas(
        payload,
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )
    validation = _validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=agent_refs["active_by_id"])
    if not validation["valid"]:
        raise TeamServiceError(_format_validation_error(validation))
    canvas["updatedAt"] = utc_now_iso()
    with _TEAM_LOCK:
        state = _load_index()
        stored = _find_team(state, team["teamId"])
        current_members = stored.get("members") if isinstance(stored, dict) and isinstance(stored.get("members"), list) else team.get("members") or []
        next_members = _sync_members_from_canvas(current_members, canvas)
        _ensure_members_can_join_team(next_members, state, team["teamId"])
        _write_json(_team_canvas_path(team["teamId"]), canvas)
        if stored is not None:
            stored["updatedAt"] = canvas["updatedAt"]
            stored["canvasPath"] = _relative_path(_team_canvas_path(team["teamId"]))
            stored["members"] = next_members
            _ensure_team_chat_room_link(stored, agent_refs=agent_refs)
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
                    "route": "/teams",
                    "status": "stale" if str(member.get("agentStatus") or "") != "active" or status == "archived" else "active",
                }
            )
    return references


def _normalize_canvas(
    raw: dict[str, Any],
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TeamServiceError("Team canvas payload must be an object.")
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if not nodes:
        nodes = _default_nodes_for_members(team.get("members") or [])
    normalized_nodes = [
        _normalize_node(
            item,
            index,
            agents_by_id=agents_by_id,
            active_agents_by_id=active_agents_by_id,
        )
        for index, item in enumerate(nodes[:120])
    ]
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


def _normalize_node(
    item: Any,
    index: int,
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamServiceError("Team canvas node must be an object.")
    agent_id = _safe_token(item.get("agentId"), default="", max_length=128)
    node_id = _safe_token(item.get("id") or agent_id, default=f"node-{index + 1}", max_length=128)
    if agent_id and agents_by_id is not None:
        agent = agents_by_id.get(agent_id)
    else:
        agent = agent_directory_service.get_agent(agent_id, include_archived=True) if agent_id else None
    if agent_id and active_agents_by_id is not None:
        active_agent = active_agents_by_id.get(agent_id)
    else:
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
        "responsibilities": [
            trim_lines(value, max_lines=2).strip()
            for value in list(item.get("responsibilities") or [])[:8]
            if str(value or "").strip()
        ],
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


def _validate_canvas(
    canvas: dict[str, Any],
    *,
    team_id: str = "",
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        if agent_id and active_agents_by_id is not None:
            active_agent = active_agents_by_id.get(agent_id)
        else:
            active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
        if agent_id and not active_agent:
            issues.append(_issue("warning", "stale_agent_ref", f"节点绑定的 Agent 不可用：{agent_id}", node_id=node_id))
        if agent_id:
            conflict = _find_active_team_for_agent(agent_id, excluding_team_id=team_id)
            if conflict:
                issues.append(
                    _issue(
                        "error",
                        "agent_team_conflict",
                        f"Agent 已属于团队 {conflict.get('name') or conflict.get('teamId')}，不能同时加入当前团队。",
                        node_id=node_id,
                    )
                )
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
                "responsibilities": [
                    trim_lines(value, max_lines=2).strip()
                    for value in list(item.get("responsibilities") or [])[:8]
                    if str(value or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _ensure_members_can_join_team(members: list[dict[str, Any]], state: dict[str, Any], team_id: str) -> None:
    for member in members:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        conflict = _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            conflict_label = str(conflict.get("name") or conflict.get("teamId") or "").strip()
            _record_team_membership_conflict(team_id, agent_id, conflict)
            raise TeamServiceError(f"Agent already belongs to Team {conflict_label}: {agent_id}")


def _ensure_evolution_system_agents() -> dict[str, list[dict[str, Any]]]:
    project_root = Path(PROJECT_ROOT).resolve()
    ensured: dict[str, list[dict[str, Any]]] = {"self_evolution": [], "supervised_evolution": []}
    try:
        from . import self_evolution_control_service

        previous_root = self_evolution_control_service.PROJECT_ROOT
        self_evolution_control_service.PROJECT_ROOT = project_root
        try:
            ensured["self_evolution"] = list(self_evolution_control_service.ensure_self_evolution_agent_instances())
        finally:
            self_evolution_control_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("self_evolution", exc)
    try:
        from . import supervised_agent_service

        previous_root = supervised_agent_service.PROJECT_ROOT
        supervised_agent_service.PROJECT_ROOT = project_root
        try:
            ensured["supervised_evolution"] = list(supervised_agent_service.ensure_supervised_agent_instances())
        finally:
            supervised_agent_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("supervised_evolution", exc)
    return ensured


def _ensure_evolution_system_team_in_state(
    state: dict[str, Any],
    spec: dict[str, str],
    ensured_agents: dict[str, list[dict[str, Any]]],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    team_id = str(spec.get("teamId") or "").strip()
    source = str(spec.get("source") or "").strip()
    if not team_id or not source:
        return None, False
    members = _system_members_from_agents(ensured_agents.get(source) or [], source=source)
    members = _members_without_cross_team_conflicts(members, state, team_id, source=source)
    now = utc_now_iso()
    team = _find_team(state, team_id)
    created = team is None
    changed = created
    if team is None:
        team = {
            "teamId": team_id,
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": members,
            "linkedChatRoomId": "",
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        _apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        )
        state.setdefault("teams", []).append(team)
    else:
        expected = {
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": members,
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
        }
        for key, value in expected.items():
            if team.get(key) != value:
                team[key] = value
                changed = True
        if _apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        ):
            changed = True
        if changed:
            team["updatedAt"] = now
    canvas_path = _team_canvas_path(team_id)
    if changed or not canvas_path.exists() or _default_canvas_edges_missing_for_team(team, canvas_path):
        _write_json(canvas_path, _default_canvas_for_team(team))
    if _team_chat_room_needs_sync(team, agent_refs=agent_refs):
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    if changed:
        _record_team_event(
            "team.system_evolution_synced",
            team,
            fields={"created": created, "source": source, "memberCount": len(members)},
        )
    return team, changed


def _system_members_from_agents(agents: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, agent in enumerate(agents[:120]):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if str(agent.get("status") or "active").strip() == "archived":
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(agent.get("roleKey") or "").strip()
        role_label = ""
        if source == "self_evolution":
            role = str(metadata.get("selfEvolutionRole") or role).strip()
            role_label = str(metadata.get("selfEvolutionRoleLabel") or "").strip()
        elif source == "supervised_evolution":
            role = str(metadata.get("supervisedRole") or role).strip()
            role_label = str(metadata.get("supervisedRoleLabel") or "").strip()
        seen.add(agent_id)
        members.append(
            {
                "memberId": _safe_token(f"{source}-{role or index + 1}", default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or role_label or agent_id).strip(),
                "role": role,
                "purpose": role_label,
                "agentStatus": "active",
            }
        )
    return members


def _members_without_cross_team_conflicts(
    members: list[dict[str, Any]],
    state: dict[str, Any],
    team_id: str,
    *,
    source: str,
) -> list[dict[str, Any]]:
    available: list[dict[str, Any]] = []
    for member in members:
        agent_id = str(member.get("agentId") or "").strip()
        conflict = _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            _record_system_team_membership_conflict(team_id, agent_id, conflict, source=source)
            continue
        available.append(member)
    return available


def _find_active_team_for_agent(agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    state = _load_index()
    return _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=excluding_team_id)


def _find_active_team_for_agent_in_state(state: dict[str, Any], agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
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
        if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
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
    agent_ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = _agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        if not agent or str(agent.get("status") or "active").strip() == "archived":
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _team_kind_allows_member_agent_cascade(team: dict[str, Any]) -> bool:
    return str(team.get("teamKind") or _infer_team_kind(team)).strip() in {"custom", "template_demo"}


def _ensure_team_member_agents_can_archive(team: dict[str, Any], agent_ids: list[str]) -> None:
    for agent_id in agent_ids:
        try:
            agent_directory_service.ensure_agent_archive_allowed(agent_id)
        except agent_directory_service.AgentDirectoryError as exc:
            _record_team_archive_rejected(team, reason="agent_archive_rejected", agent_id=agent_id, error=exc)
            raise TeamServiceError(str(exc)) from exc


def _archive_team_member_agents(team: dict[str, Any], agent_ids: list[str], *, reason: str) -> list[str]:
    archived_agent_ids: list[str] = []
    for agent_id in agent_ids:
        archived_agent = agent_directory_service.archive_agent_instance(agent_id)
        archived_agent_ids.append(str(archived_agent.get("agentId") or agent_id).strip())
    if archived_agent_ids and reason != "team_archive":
        _record_archived_team_member_cascade_repaired(team, archived_agent_ids, reason=reason)
    return archived_agent_ids


def _remove_team_member_agents_from_chat_rooms(team: dict[str, Any], agent_ids: list[str]) -> dict[str, Any]:
    if not agent_ids:
        return {"agentIds": [], "changedRoomIds": [], "removedByAgentId": {}}
    try:
        return chat_room_service.remove_agents_from_chat_rooms(
            agent_ids,
            allow_empty_rooms=True,
            include_chat_rooms=False,
            repair_participants=False,
        )
    except chat_room_service.ChatRoomBusyError as exc:
        _record_team_archive_rejected(team, reason="chat_room_busy", error=exc)
        raise TeamServiceError(str(exc)) from exc
    except chat_room_service.ChatRoomValidationError as exc:
        _record_team_archive_rejected(team, reason="chat_room_cleanup_rejected", error=exc)
        raise TeamServiceError(str(exc)) from exc


def _repair_archived_team_member_agents(
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    changed = False
    for team in list(state.get("teams") or []):
        if isinstance(team, dict):
            changed = _repair_archived_team_member_agents_for_team(
                team,
                state,
                reason=reason,
                strict=strict,
                agent_refs=agent_refs,
            ) or changed
    return changed


def _repair_archived_team_member_agents_for_team(
    team: dict[str, Any],
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
        return False
    if not _team_kind_allows_member_agent_cascade(team):
        return False
    agent_ids = _unique_active_member_agent_ids(team, agent_refs=agent_refs)
    if not agent_ids:
        return False
    try:
        _ensure_team_member_agents_can_archive(team, agent_ids)
    except TeamServiceError:
        if strict:
            raise
        return False
    try:
        _remove_team_member_agents_from_chat_rooms(team, agent_ids)
    except TeamServiceError:
        if strict:
            raise
        return False
    _archive_team_member_agents(team, agent_ids, reason=reason)
    team["updatedAt"] = utc_now_iso()
    state["updatedAt"] = team["updatedAt"]
    return True


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
        if isinstance(node.get("responsibilities"), list):
            member["responsibilities"] = [
                trim_lines(value, max_lines=2).strip()
                for value in list(node.get("responsibilities") or [])[:8]
                if str(value or "").strip()
            ]
        by_agent[agent_id] = member
    return list(by_agent.values())


def _members_from_research_organization(organization: dict[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen or str(item.get("status") or "active").strip() == "archived":
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            continue
        seen.add(agent_id)
        function_label = _research_member_function_label(item, agent)
        members.append(
            {
                "memberId": _safe_token(item.get("nodeId") or agent_id, default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or item.get("displayName") or "").strip(),
                "role": str(item.get("role") or ((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("researchOrgRole") or "").strip(),
                "purpose": function_label,
                "agentStatus": "active",
            }
        )
    return members


def _canvas_from_research_organization(organization: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    members_by_agent_id = {
        str(member.get("agentId") or "").strip(): member
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        member = members_by_agent_id.get(agent_id)
        if not member:
            continue
        nodes.append(
            {
                "id": _safe_token(agent_id, default=f"node-{index + 1}", max_length=96),
                "label": str(item.get("displayName") or member.get("agentName") or agent_id).strip(),
                "type": "agent",
                "status": "bound",
                "x": _safe_float(item.get("x"), 120.0 + index * 220.0),
                "y": _safe_float(item.get("y"), 120.0),
                "agentId": agent_id,
                "agentCode": str(item.get("agentCode") or member.get("agentCode") or "").strip(),
                "agentName": str(member.get("agentName") or item.get("displayName") or "").strip(),
                "role": str(member.get("role") or "").strip(),
                "purpose": str(member.get("purpose") or "").strip(),
            }
        )
    node_ids = {str(node.get("id") or "") for node in nodes}
    edges: list[dict[str, Any]] = _organization_reporting_edges(organization, nodes)
    for index, item in enumerate(list(organization.get("edges") or [])[:240]):
        if not isinstance(item, dict) or str(item.get("status") or "active").strip() == "archived":
            continue
        source = _safe_token(item.get("fromAgentId") or item.get("source"), default="", max_length=96)
        target = _safe_token(item.get("toAgentId") or item.get("target"), default="", max_length=96)
        if source not in node_ids or target not in node_ids:
            continue
        edges.append(
            {
                "id": _safe_token(item.get("edgeId") or item.get("id"), default=f"edge-{index + 1}", max_length=96),
                "source": source,
                "target": target,
                "label": trim_lines(item.get("label") or "组织通信", max_lines=1).strip(),
                "type": "communication",
            }
        )
    return _normalize_canvas(
        {
            "schemaVersion": SCHEMA_VERSION,
            "canvasKind": CANVAS_KIND,
            "teamId": team["teamId"],
            "updatedAt": str(organization.get("updatedAt") or team.get("updatedAt") or utc_now_iso()),
            "path": _relative_path(_team_canvas_path(team["teamId"])),
            "viewport": {"x": 40, "y": 80, "zoom": 1},
            "nodes": nodes,
            "edges": edges,
        },
        team,
    )


def _organization_reporting_edges(organization: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = {str(node.get("id") or "").strip() for node in nodes if str(node.get("id") or "").strip()}
    if len(node_ids) < 2:
        return []
    source_items = [
        item for item in list(organization.get("agents") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip() != "archived"
        and str(item.get("agentId") or "").strip() in node_ids
    ]
    nodes_by_agent_id = {str(node.get("agentId") or "").strip(): node for node in nodes}
    items_by_agent_id = {str(item.get("agentId") or "").strip(): item for item in source_items}
    role_index: dict[str, str] = {}
    label_index: dict[str, str] = {}
    for item in source_items:
        agent_id = str(item.get("agentId") or "").strip()
        role = _research_org_role(item)
        if role and role not in role_index:
            role_index[role] = agent_id
        for value in (
            item.get("agentCode"),
            item.get("displayName"),
            item.get("role"),
            _research_member_function_label(item, item.get("agent") if isinstance(item.get("agent"), dict) else {}),
        ):
            normalized = _normalize_report_to_reference(value)
            if normalized and normalized not in label_index:
                label_index[normalized] = agent_id
    ceo_agent_id = role_index.get("ceo") or role_index.get("research_ceo") or label_index.get("ceo")
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in source_items:
        target_agent_id = str(item.get("agentId") or "").strip()
        if not target_agent_id:
            continue
        role = _research_org_role(item)
        if role in {"ceo", "research_ceo"}:
            continue
        source_agent_id = _resolve_report_to_agent_id(item, role_index=role_index, label_index=label_index, fallback_agent_id=ceo_agent_id or "")
        if not source_agent_id or source_agent_id == target_agent_id or source_agent_id not in node_ids:
            continue
        pair = (source_agent_id, target_agent_id)
        if pair in seen:
            continue
        seen.add(pair)
        source_node = nodes_by_agent_id.get(source_agent_id) or {}
        target_node = nodes_by_agent_id.get(target_agent_id) or {}
        edges.append(
            {
                "id": _safe_token(f"reports-{source_agent_id}-{target_agent_id}", default=f"reports-{len(edges) + 1}", max_length=96),
                "source": source_agent_id,
                "target": target_agent_id,
                "label": trim_lines(
                    f"{source_node.get('label') or source_agent_id} 管理 {target_node.get('label') or target_agent_id}",
                    max_lines=1,
                ).strip(),
                "type": "reports_to",
            }
        )
    return edges


def _resolve_report_to_agent_id(
    item: dict[str, Any],
    *,
    role_index: dict[str, str],
    label_index: dict[str, str],
    fallback_agent_id: str,
) -> str:
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role_contract = metadata.get("roleContract") if isinstance(metadata.get("roleContract"), dict) else {}
    candidates = [
        item.get("reportToAgentId"),
        item.get("reportsToAgentId"),
        role_contract.get("reportToAgentId"),
        role_contract.get("reportsToAgentId"),
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    report_to = _normalize_report_to_reference(item.get("reportTo") or role_contract.get("reportTo") or "CEO")
    if report_to in role_index:
        return role_index[report_to]
    if report_to in label_index:
        return label_index[report_to]
    aliases = {
        "chiefexecutiveofficer": "ceo",
        "ceoagent": "ceo",
        "organizationadvisor": "organization_advisor",
        "organizationadvisoragent": "organization_advisor",
        "capabilitysteward": "capability_steward",
        "capabilitystewardagent": "capability_steward",
    }
    alias = aliases.get(report_to)
    if alias and alias in role_index:
        return role_index[alias]
    return fallback_agent_id


def _research_org_role(item: dict[str, Any]) -> str:
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return str(item.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole") or "").strip()


def _normalize_report_to_reference(value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "", str(value or "").strip().lower())
    return normalized


def _research_member_function_label(item: dict[str, Any], agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    label = str(metadata.get("functionalDisplayName") or "").strip()
    if label:
        return trim_lines(label, max_lines=1).strip()
    responsibilities = metadata.get("responsibilities")
    if isinstance(responsibilities, list):
        joined = "；".join(str(value).strip() for value in responsibilities[:2] if str(value).strip())
        if joined:
            return trim_lines(joined, max_lines=1).strip()
    return trim_lines(item.get("role") or "科研协作", max_lines=1).strip()


def _active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if not _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs):
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    return ids


def _active_member_session_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    session_ids: list[str] = []
    seen: set[str] = set()
    for agent_id in _active_member_agent_ids(team, agent_refs=agent_refs):
        agent = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    return session_ids


def _team_chat_room_title(team: dict[str, Any]) -> str:
    name = str(team.get("name") or team.get("teamId") or "Team").strip()
    return f"{name} 团队群聊"


def _team_participant_contexts_by_agent_id(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    team_id = str(team.get("teamId") or "").strip()
    team_name = str(team.get("name") or "").strip()
    team_purpose = trim_lines(team.get("purpose") or "", max_lines=4).strip()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) or {}
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        responsibilities = []
        if isinstance(member.get("responsibilities"), list):
            responsibilities.extend(str(item).strip() for item in member.get("responsibilities") if str(item).strip())
        if isinstance(metadata.get("responsibilities"), list):
            responsibilities.extend(str(item).strip() for item in metadata.get("responsibilities") if str(item).strip())
        contexts[agent_id] = {
            "teamId": team_id,
            "teamName": team_name,
            "teamPurpose": team_purpose,
            "teamRole": trim_lines(member.get("role") or "", max_lines=1).strip(),
            "teamMemberPurpose": trim_lines(member.get("purpose") or "", max_lines=4).strip(),
            "teamResponsibilities": responsibilities[:8],
        }
    return contexts


def _sync_chat_room_root() -> None:
    if chat_room_service.PROJECT_ROOT != PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = PROJECT_ROOT


def _apply_team_contract(
    team: dict[str, Any],
    *,
    team_kind: str = "",
    team_category: str = "",
    team_source: str = "",
    team_template_id: str = "",
) -> bool:
    inferred_kind = _infer_team_kind(team, fallback=team_kind)
    defaults = TEAM_KIND_DEFAULTS.get(inferred_kind, TEAM_KIND_DEFAULTS["custom"])
    expected = {
        "teamKind": inferred_kind,
        "teamCategory": trim_lines(team_category or team.get("teamCategory") or defaults["teamCategory"], max_lines=1).strip(),
        "teamSource": str(team_source or team.get("teamSource") or defaults["teamSource"]).strip(),
        "teamTemplateId": str(team_template_id or team.get("teamTemplateId") or "").strip(),
    }
    if expected["teamSource"] in TEAM_SOURCE_TO_KIND:
        expected["teamKind"] = TEAM_SOURCE_TO_KIND[expected["teamSource"]]
    if expected["teamKind"] != "template_demo":
        expected["teamTemplateId"] = ""
    elif not expected["teamTemplateId"]:
        expected["teamTemplateId"] = _infer_team_template_id(team)
    changed = False
    for key, value in expected.items():
        if team.get(key) != value:
            team[key] = value
            changed = True
    return changed


def _infer_team_kind(team: dict[str, Any], *, fallback: str = "") -> str:
    explicit = str(fallback or team.get("teamKind") or "").strip()
    if explicit in TEAM_KIND_DEFAULTS:
        return explicit
    source = str(team.get("teamSource") or team.get("systemTeamKind") or "").strip()
    if source in TEAM_SOURCE_TO_KIND:
        return TEAM_SOURCE_TO_KIND[source]
    team_id = str(team.get("teamId") or "").strip()
    if team_id in TEAM_ID_TO_KIND:
        return TEAM_ID_TO_KIND[team_id]
    if _infer_team_template_id(team):
        return "template_demo"
    return "custom"


def _infer_team_template_id(team: dict[str, Any]) -> str:
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


def _team_default_chat_room_purpose(team: dict[str, Any]) -> str:
    kind = _infer_team_kind(team)
    if kind == "template_demo":
        template_id = str(team.get("teamTemplateId") or _infer_team_template_id(team)).strip()
        if template_id == "medical-consultation-demo":
            return "medical_triage"
        if template_id == "heletech-maternal-digital-health-demo":
            return "meeting"
    return str(TEAM_KIND_DEFAULTS.get(kind, TEAM_KIND_DEFAULTS["custom"]).get("chatRoomPurpose") or "discussion")


def _team_chat_room_purpose_for_update(team: dict[str, Any], current_purpose: Any) -> str:
    normalized_current = str(current_purpose or "").strip()
    expected = _team_default_chat_room_purpose(team)
    if not normalized_current:
        return expected
    if normalized_current == "discussion" and _infer_team_kind(team) != "custom":
        return expected
    return normalized_current


def _ensure_team_chat_room_link(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return str(team.get("linkedChatRoomId") or "").strip()
    session_ids = _active_member_session_ids(team, agent_refs=agent_refs)
    _sync_chat_room_root()
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    title = _team_chat_room_title(team)
    config = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or TEAM_KIND_DEFAULTS["custom"]["teamCategory"]).strip(),
        "teamSource": str(team.get("teamSource") or TEAM_KIND_DEFAULTS["custom"]["teamSource"]).strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    participant_contexts = _team_participant_contexts_by_agent_id(team, agent_refs=agent_refs)
    linked_room = chat_room_service.get_chat_room_detail(linked_room_id) if linked_room_id else None
    if linked_room:
        room_config = {
            **dict(linked_room.get("config") or {}),
            **config,
        }
        room = chat_room_service.update_chat_room(
                linked_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode=str(linked_room.get("mode") or "round_robin"),
                purpose=_team_chat_room_purpose_for_update(team, linked_room.get("purpose")),
                config=room_config,
            )
    else:
        reusable_room_id = _find_existing_team_chat_room_id(str(team.get("teamId") or "").strip())
        if reusable_room_id:
            reusable_room = chat_room_service.get_chat_room_detail(reusable_room_id) or {}
            room_config = {
                **dict(reusable_room.get("config") or {}),
                **config,
            }
            room = chat_room_service.update_chat_room(
                reusable_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode=str(reusable_room.get("mode") or "round_robin"),
                purpose=_team_chat_room_purpose_for_update(team, reusable_room.get("purpose")),
                config=room_config,
            )
        else:
            room = chat_room_service.create_chat_room(
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode="round_robin",
                purpose=_team_default_chat_room_purpose(team),
                config=config,
            )
    team["linkedChatRoomId"] = str(room.get("roomId") or "").strip()
    _archive_duplicate_team_chat_rooms(team["linkedChatRoomId"], str(team.get("teamId") or "").strip())
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


def _find_existing_team_chat_room_id(team_id: str) -> str:
    normalized_team_id = str(team_id or "").strip()
    if not normalized_team_id:
        return ""
    rooms = [
        room for room in chat_room_service.list_chat_rooms()
        if str((room.get("config") or {}).get("source") or "").strip() == "team"
        and str((room.get("config") or {}).get("teamId") or "").strip() == normalized_team_id
    ]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return str((rooms[0] if rooms else {}).get("roomId") or "").strip()


def _archive_duplicate_team_chat_rooms(keep_room_id: str, team_id: str) -> None:
    normalized_keep_room_id = str(keep_room_id or "").strip()
    normalized_team_id = str(team_id or "").strip()
    if not normalized_keep_room_id or not normalized_team_id:
        return
    duplicates = [
        room for room in chat_room_service.list_chat_rooms()
        if str(room.get("roomId") or "").strip() != normalized_keep_room_id
        and str((room.get("config") or {}).get("source") or "").strip() == "team"
        and str((room.get("config") or {}).get("teamId") or "").strip() == normalized_team_id
        and str(room.get("status") or "").strip() not in {"running", "stopping"}
    ]
    for room in duplicates:
        try:
            chat_room_service.delete_chat_room(str(room.get("roomId") or ""))
        except Exception:
            continue
    if duplicates:
        _record_team_event(
            "team.chat_room.duplicates_archived",
            {"teamId": normalized_team_id, "linkedChatRoomId": normalized_keep_room_id},
            fields={
                "linkedChatRoomId": normalized_keep_room_id,
                "duplicateRoomCount": len(duplicates),
            },
        )


def repair_archived_team_chat_rooms() -> dict[str, Any]:
    """Delete linked team chat rooms for Teams that are already archived."""

    _sync_chat_room_root()
    with _TEAM_LOCK:
        state = _load_index()
        changed = False
        deleted_room_ids: list[str] = []
        for team in list(state.get("teams") or []):
            if not isinstance(team, dict):
                continue
            if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
                continue
            before = str(team.get("linkedChatRoomId") or "").strip()
            deleted = _delete_team_linked_chat_rooms(team, reason="archived_team_repair")
            if deleted:
                deleted_room_ids.extend(deleted)
            if deleted or before != str(team.get("linkedChatRoomId") or "").strip():
                changed = True
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    return {
        "deleted": bool(deleted_room_ids),
        "deletedRoomIds": deleted_room_ids,
        "deletedRoomCount": len(deleted_room_ids),
    }


def _repair_archived_team_linked_chat_room(team: dict[str, Any], *, reason: str) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
        return False
    before = str(team.get("linkedChatRoomId") or "").strip()
    deleted = _delete_team_linked_chat_rooms(team, reason=reason)
    after = str(team.get("linkedChatRoomId") or "").strip()
    return bool(deleted) or before != after


def _delete_team_linked_chat_rooms(team: dict[str, Any], *, reason: str, strict_busy: bool = False) -> list[str]:
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return []
    _sync_chat_room_root()
    room_ids: list[str] = []
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if linked_room_id:
        room_ids.append(linked_room_id)
    for room in chat_room_service.list_chat_rooms_compact():
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("roomId") or "").strip()
        room_config = dict(room.get("config") or {})
        if (
            room_id
            and room_id not in room_ids
            and str(room_config.get("source") or "").strip() == "team"
            and str(room_config.get("teamId") or "").strip() == team_id
        ):
            room_ids.append(room_id)

    deleted_room_ids: list[str] = []
    missing_room_ids: list[str] = []
    for room_id in room_ids:
        try:
            chat_room_service.delete_chat_room(room_id)
        except chat_room_service.ChatRoomNotFoundError:
            missing_room_ids.append(room_id)
            continue
        except chat_room_service.ChatRoomBusyError as exc:
            _record_team_event(
                "team.chat_room.archive_delete_rejected",
                team,
                fields={"linkedChatRoomId": room_id, "reason": reason, "errorType": type(exc).__name__},
            )
            if strict_busy:
                raise TeamServiceError("Team chat room has an active round and cannot be deleted while archiving.") from exc
            continue
        deleted_room_ids.append(room_id)

    if linked_room_id and linked_room_id in {*deleted_room_ids, *missing_room_ids}:
        team["linkedChatRoomId"] = ""
    if deleted_room_ids or missing_room_ids:
        _record_team_event(
            "team.chat_room.deleted_for_archive",
            team,
            fields={
                "deletedLinkedChatRoomIds": deleted_room_ids,
                "deletedLinkedChatRoomCount": len(deleted_room_ids),
                "clearedMissingLinkedChatRoomIds": missing_room_ids,
                "clearedMissingLinkedChatRoomCount": len(missing_room_ids),
                "reason": reason,
            },
        )
    return deleted_room_ids


def _team_chat_room_needs_sync(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    active_member_agent_ids = _active_member_agent_ids(team, agent_refs=agent_refs)
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return True
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id)
    if not linked_room:
        return True
    participant_agent_ids = [
        str(participant.get("agentId") or "").strip()
        for participant in list(linked_room.get("participants") or [])
        if isinstance(participant, dict) and str(participant.get("agentId") or "").strip()
    ]
    if participant_agent_ids != active_member_agent_ids:
        return True
    team_kind = _infer_team_kind(team)
    if team_kind == "custom":
        return False
    config = linked_room.get("config") if isinstance(linked_room.get("config"), dict) else {}
    expected_pairs = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamKind": str(team.get("teamKind") or team_kind).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    if any(str(config.get(key) or "").strip() != value for key, value in expected_pairs.items() if value):
        return True
    return str(linked_room.get("purpose") or "").strip() != _team_chat_room_purpose_for_update(team, linked_room.get("purpose"))


def _sync_compact_team_chat_room_metadata(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    if _infer_team_kind(team) == "custom":
        return False
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return False
    if compact_rooms_by_id is None:
        _sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id)
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id)
    if not linked_room:
        return False
    next_purpose = _team_chat_room_purpose_for_update(team, linked_room.get("purpose"))
    current_purpose = str(linked_room.get("purpose") or "").strip()
    config = {
        **dict(linked_room.get("config") or {}),
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    needs_config = any(str((linked_room.get("config") or {}).get(key) or "").strip() != value for key, value in config.items() if value)
    if current_purpose == next_purpose and not needs_config:
        return False
    try:
        chat_room_service.update_chat_room(
            linked_room_id,
            purpose=next_purpose,
            config=config,
        )
    except chat_room_service.ChatRoomBusyError as exc:
        _record_compact_chat_room_sync_skipped_busy(team, linked_room_id, exc)
        return False
    return True


def _team_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    repaired = dict(team)
    _repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = _members_to_api(repaired.get("members"))
    canvas_summary = _canvas_summary_for_team(repaired, agent_refs=agent_refs)
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": canvas_summary,
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _team_to_compact_reference(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repaired = dict(team)
    _apply_team_contract(repaired)
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    members = _members_to_api(repaired.get("members"))
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    if compact_rooms_by_id is None:
        _sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id) if linked_room_id else None
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or DEFAULT_TEAM_STATUS).strip() or DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "canvasPath": str(repaired.get("canvasPath") or (_relative_path(_team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_to_graph_reference(team: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(team)
    _apply_team_contract(repaired)
    team_id = _safe_token(repaired.get("teamId"), default="", max_length=96)
    members = _members_to_api(repaired.get("members"))
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or DEFAULT_TEAM_STATUS).strip() or DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": str(repaired.get("linkedChatRoomId") or "").strip(),
        "canvasPath": str(repaired.get("canvasPath") or (_relative_path(_team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_detail_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    agent_refs = agent_refs or _agent_reference_maps()
    return {
        **_team_to_api_without_canvas_summary(team, agent_refs=agent_refs),
        "canvas": _team_canvas_with_validation(
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
    repaired = dict(team)
    _repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = _members_to_api(repaired.get("members"))
    team_id = str(repaired.get("teamId") or "").strip()
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": _canvas_path_summary(repaired, team_id=team_id),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _members_to_api(members: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, member in enumerate(list(members or [])):
        if not isinstance(member, dict) or not str(member.get("agentId") or "").strip():
            continue
        payload = {
            "memberId": _safe_token(member.get("memberId"), default=f"member-{index + 1}", max_length=96),
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
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
        return dict(team)


def _canvas_summary_for_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return {"path": "", "nodeCount": 0, "edgeCount": 0, "validation": _validate_canvas({"nodes": [], "edges": []}, team_id=team_id)}
    canvas_path = _team_canvas_path(team_id)
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    agent_refs = agent_refs or _agent_reference_maps()
    try:
        canvas = _normalize_canvas(
            raw or _default_canvas_for_team(team),
            team,
            agents_by_id=agent_refs["by_id"],
            active_agents_by_id=agent_refs["active_by_id"],
        )
        validation = _validate_canvas(canvas, team_id=team_id, active_agents_by_id=agent_refs["active_by_id"])
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


def _canvas_path_summary(team: dict[str, Any], *, team_id: str = "") -> dict[str, Any]:
    normalized_team_id = str(team_id or team.get("teamId") or "").strip()
    canvas_path = _team_canvas_path(normalized_team_id) if normalized_team_id else Path("")
    return {
        "path": str(team.get("canvasPath") or (_relative_path(canvas_path) if normalized_team_id else "")),
        "nodeCount": 0,
        "edgeCount": 0,
        "validation": {"valid": True, "summary": {"errorCount": 0, "warningCount": 0, "issueCount": 0}, "issues": []},
    }


def _agent_reference_maps() -> dict[str, dict[str, dict[str, Any]]]:
    agents = _load_lightweight_agent_references()
    return _agent_reference_maps_from_agents(agents)


def _load_lightweight_agent_references() -> list[dict[str, Any]]:
    """Read Agent identity fields without running Agent repair or API hydration."""

    path = _project_root() / "workspace" / "agents" / "agents.json"
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
    merged: dict[str, dict[str, Any]] = {}
    for agents in agent_groups:
        for agent in list(agents or []):
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("agentId") or "").strip()
            if agent_id:
                merged[agent_id] = dict(agent)
    return _agent_reference_maps_from_agents(list(merged.values()))


def _agent_reference(
    agent_id: str,
    *,
    include_archived: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return None
    if agent_refs is not None:
        key = "by_id" if include_archived else "active_by_id"
        agent = (agent_refs.get(key) or {}).get(normalized_agent_id)
        return dict(agent) if isinstance(agent, dict) else None
    return agent_directory_service.get_agent(normalized_agent_id, include_archived=include_archived)


def _repair_index_state(
    state: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    changed = False
    if state.get("schemaVersion") != SCHEMA_VERSION:
        state["schemaVersion"] = SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    for team in state.get("teams") or []:
        if isinstance(team, dict):
            changed = _repair_team(team, agent_refs=agent_refs) or changed
    return changed


def _repair_index_shape(state: dict[str, Any]) -> bool:
    changed = False
    if state.get("schemaVersion") != SCHEMA_VERSION:
        state["schemaVersion"] = SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    return changed


def _repair_index_compact_contracts(
    state: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = _repair_index_shape(state)
    for team in state.get("teams") or []:
        if not isinstance(team, dict):
            continue
        if _repair_team_contract_only(team, compact_rooms_by_id=compact_rooms_by_id):
            changed = True
    return changed


def _repair_team_contract_only(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = False
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    expected_path = _relative_path(_team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    if _apply_team_contract(team):
        changed = True
    if _sync_compact_team_chat_room_metadata(team, compact_rooms_by_id=compact_rooms_by_id):
        changed = True
    return changed


def _repair_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
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
    if _apply_team_contract(team):
        changed = True
    members = team.get("members") if isinstance(team.get("members"), list) else []
    repaired_members = _repair_members(members, agent_refs=agent_refs)
    if repaired_members != members:
        team["members"] = repaired_members
        changed = True
    if _team_chat_room_needs_sync(team, agent_refs=agent_refs):
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    return changed


def _repair_members(
    members: list[Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(members):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agent = _agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        active = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) if agent_id else None
        repaired.append(
            {
                "memberId": _safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or item.get("agentName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "responsibilities": [
                    trim_lines(value, max_lines=2).strip()
                    for value in list(item.get("responsibilities") or [])[:8]
                    if str(value or "").strip()
                ],
                "agentStatus": "active" if active else "stale",
            }
        )
    return repaired


def _default_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    nodes = _default_nodes_for_members(team.get("members") or [])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(team["teamId"])),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": _default_edges_for_team(team, nodes),
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


def _default_edges_for_team(team: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_by_role: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = str(node.get("role") or "").strip()
        if role and role not in nodes_by_role:
            nodes_by_role[role] = node
    if _infer_team_kind(team) == "self_evolution":
        return _edges_from_role_chain(
            nodes_by_role,
            [
                ("executor", "reviewer", "执行交付评审"),
                ("reviewer", "summarizer", "评审结果总结"),
            ],
        )
    if _infer_team_kind(team) == "supervised_evolution":
        return _edges_from_role_chain(
            nodes_by_role,
            [
                ("baseline", "reviewer", "基线方案评审"),
                ("candidate", "reviewer", "候选方案评审"),
                ("reviewer", "auditor", "评审进入审计"),
                ("auditor", "judge", "审计进入裁决"),
            ],
        )
    return []


def _edges_from_role_chain(
    nodes_by_role: dict[str, dict[str, Any]],
    links: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, (source_role, target_role, label) in enumerate(links, start=1):
        source = nodes_by_role.get(source_role)
        target = nodes_by_role.get(target_role)
        if not source or not target:
            continue
        source_id = str(source.get("id") or "").strip()
        target_id = str(target.get("id") or "").strip()
        if not source_id or not target_id:
            continue
        edges.append(
            {
                "id": _safe_token(f"{source_role}-{target_role}", default=f"edge-{index}", max_length=96),
                "source": source_id,
                "target": target_id,
                "label": label,
                "type": "communication",
            }
        )
    return edges


def _default_canvas_edges_missing_for_team(team: dict[str, Any], canvas_path: Path) -> bool:
    if _infer_team_kind(team) not in {"self_evolution", "supervised_evolution"}:
        return False
    if not canvas_path.exists():
        return True
    try:
        canvas = _read_json(canvas_path)
    except Exception:
        return True
    return not list(canvas.get("edges") or [])


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
                "teamKind": team.get("teamKind"),
                "teamCategory": team.get("teamCategory"),
                "teamSource": team.get("teamSource"),
                "teamTemplateId": team.get("teamTemplateId"),
                **(fields or {}),
            },
        )
    except Exception:
        pass


def _record_team_detail_loaded(team: dict[str, Any], started_at: float) -> None:
    try:
        canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
        record_runtime_scene_event(
            "team_service",
            "team_detail",
            "team.detail.loaded",
            message="Team detail loaded.",
            outcome="observed",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or "").strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "linkedChatRoomId": str(team.get("linkedChatRoomId") or "").strip(),
                "memberCount": len(list(team.get("members") or [])),
                "canvasNodeCount": len(list(canvas.get("nodes") or [])),
                "canvasEdgeCount": len(list(canvas.get("edges") or [])),
                "elapsedMs": _elapsed_ms(started_at),
            },
        )
    except Exception:
        pass


def _record_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.membership_conflict_rejected",
            message="Team member assignment rejected because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception:
        pass


def _record_team_archive_rejected(
    team: dict[str, Any],
    *,
    reason: str,
    agent_id: str = "",
    error: Exception | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.archive_rejected",
            message="Team archive rejected before cascading Agent archive.",
            outcome="blocked",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "reason": str(reason or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "errorType": type(error).__name__ if error else "",
                "message": str(error) if error else "",
            },
        )
    except Exception:
        pass


def _record_archived_team_member_cascade_repaired(
    team: dict[str, Any],
    archived_agent_ids: list[str],
    *,
    reason: str,
) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team_repair",
            "team.archived_agent_cascade_repaired",
            message="Archived Team had active member Agents; cascading archive repair applied.",
            outcome="repaired",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "archivedAgentIds": archived_agent_ids,
                "archivedAgentCount": len(archived_agent_ids),
                "reason": str(reason or "").strip(),
            },
        )
    except Exception:
        pass


def _record_compact_chat_room_sync_skipped_busy(team: dict[str, Any], linked_room_id: str, exc: Exception) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team_compact_repair",
            "team.compact_chat_room_sync_skipped_busy",
            message="Team compact repair skipped linked chat room metadata sync because the room has an active round.",
            level="warning",
            outcome="skipped",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "linkedChatRoomId": str(linked_room_id or "").strip(),
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception:
        pass


def _record_system_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any], *, source: str) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.system_membership_conflict",
            message="System Team member was not synced because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "source": source,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception:
        pass


def _record_system_team_sync_failed(source: str, exc: Exception) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.system_evolution_sync_failed",
            message="System evolution Team sync failed",
            level="warning",
            outcome="failed",
            fields={
                "source": str(source or "").strip(),
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception:
        pass
