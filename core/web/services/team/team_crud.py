"""Team CRUD and membership public API.

Claim scope: list/create/get/update/archive teams, agent membership remove/restore,
and team message send entrypoints. Late-binds ``team_service`` for index locks,
repair, projection, canvas defaults, and chat-room helpers.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.chat.chat_task_types import trim_lines
from core.web.services import agent_directory_service, chat_room_service, project_agent_bus_service


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def list_teams(*, include_archived: bool = False) -> dict[str, Any]:
    s = _service()
    agent_refs = s._agent_reference_maps()
    pending_agent_ids: list[str] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = s._repair_index_state(state, agent_refs=agent_refs)
        member_changed, pending_agent_ids = s._repair_archived_team_member_agents(
            state, reason="s.list_teams", strict=False, agent_refs=agent_refs
        )
        changed = member_changed or changed
        if changed:
            s._save_index(state)
    if pending_agent_ids:
        s._cascade_archive_member_agents_unlocked(pending_agent_ids, reason="s.list_teams")
    teams = [
        s._team_to_api(item, agent_refs=agent_refs)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or s.DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teams": teams,
        "summary": s._summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": s._relative_path(s._teams_index_path()), "teamRoot": s._relative_path(s._teams_root())},
    }


def list_teams_compact(*, include_archived: bool = False) -> dict[str, Any]:
    """Return Team references without canvas reads or linked room hydration."""

    s = _service()
    s._sync_chat_room_root()
    compact_rooms_by_id = {
        str(room.get("roomId") or "").strip(): room
        for room in chat_room_service.list_chat_rooms_compact()
        if isinstance(room, dict) and str(room.get("roomId") or "").strip()
    }
    team_lock_acquired = s._try_acquire_team_lock()
    try:
        state = s._load_index()
        changed = False
        if team_lock_acquired:
            changed = s._repair_index_compact_contracts(state, compact_rooms_by_id=compact_rooms_by_id)
        if changed:
            s._save_index(state)
    finally:
        s._release_team_lock_if_acquired(team_lock_acquired)
    teams = [
        s._team_to_compact_reference(item, compact_rooms_by_id=compact_rooms_by_id)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or s.DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teams": teams,
        "summary": s._summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": s._relative_path(s._teams_index_path()), "teamRoot": s._relative_path(s._teams_root())},
    }


def list_team_graph_references(*, include_archived: bool = False) -> dict[str, Any]:
    """Return lightweight Team references for read-only graph surfaces."""

    s = _service()
    state = s._load_index()
    teams = [
        s._team_to_graph_reference(item)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or s.DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teams": teams,
        "summary": s._summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": s._relative_path(s._teams_index_path()), "teamRoot": s._relative_path(s._teams_root())},
    }


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
    s = _service()
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise s.TeamServiceError("Team name is required.")
    now = s.utc_now_iso()
    with s._TEAM_LOCK:
        state = s._load_index()
        normalized_members = s._normalize_members(members or [], require_active=True)
        reusable_team = s._find_reusable_empty_team(
            state,
            normalized_name=normalized_name,
            team_kind=team_kind,
            team_source=team_source,
            team_template_id=team_template_id,
            requested_member_count=len(normalized_members),
        )
        if reusable_team is not None:
            reused_team_id = str(reusable_team.get("teamId") or "").strip()
            s._record_team_event(
                "team.create.reused_empty_team",
                reusable_team,
                fields={"name": normalized_name, "memberCount": 0},
            )
            return s.get_team(reused_team_id)
        existing_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
        }
        team_id = s._new_team_id(normalized_name, existing_ids)
        s._ensure_members_can_join_team(normalized_members, state, team_id)
        team = {
            "teamId": team_id,
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=8).strip(),
            "purpose": trim_lines(purpose or "", max_lines=4).strip(),
            "status": s.DEFAULT_TEAM_STATUS,
            "members": normalized_members,
            "linkedChatRoomId": "",
            "canvasPath": s._relative_path(s._team_canvas_path(team_id)),
            "createdAt": now,
            "updatedAt": now,
        }
        s._apply_team_contract(
            team,
            team_kind=team_kind,
            team_category=team_category,
            team_source=team_source,
            team_template_id=team_template_id,
        )
        state.setdefault("teams", []).append(team)
        state["updatedAt"] = now
        s._save_index(state)
        canvas = s._default_canvas_for_team(team)
        s._write_json(s._team_canvas_path(team_id), canvas)
        state["updatedAt"] = team["updatedAt"]
        s._save_index(state)
    s._ensure_active_member_direct_sessions(team)
    s._ensure_team_chat_room_link(team)
    with s._TEAM_LOCK:
        state = s._load_index()
        stored = s._find_team(state, team_id)
        if stored is not None:
            stored["linkedChatRoomId"] = str(team.get("linkedChatRoomId") or "").strip()
            stored["updatedAt"] = s.utc_now_iso()
            state["updatedAt"] = stored["updatedAt"]
            s._save_index(state)
            team = stored
    s._record_team_event("team.created", team, fields={"memberCount": len(normalized_members)})
    return s.get_team(team_id)


def get_team(team_id: str) -> dict[str, Any]:
    s = _service()
    started_at = s._perf_counter()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    agent_refs = s._agent_reference_maps()
    pending_agent_ids: list[str] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        changed = s._repair_team(team, agent_refs=agent_refs)
        member_changed, pending_agent_ids = s._repair_archived_team_member_agents_for_team(
            team,
            state,
            reason="s.get_team",
            strict=False,
            agent_refs=agent_refs,
        )
        changed = member_changed or changed
        if changed:
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
    if pending_agent_ids:
        s._cascade_archive_member_agents_unlocked(pending_agent_ids, reason="s.get_team")
    detail = s._team_detail_to_api(team, agent_refs=agent_refs)
    s._record_team_detail_loaded(detail, started_at)
    return detail


def get_team_light(team_id: str) -> dict[str, Any]:
    """Return Team detail for first paint without hydrating the full canvas."""

    s = _service()
    started_at = s._perf_counter()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s._sync_chat_room_root()
    compact_rooms_by_id = {
        str(room.get("roomId") or "").strip(): room
        for room in chat_room_service.list_chat_rooms_compact()
        if isinstance(room, dict) and str(room.get("roomId") or "").strip()
    }
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
    detail = {
        **s._team_to_compact_reference(team, compact_rooms_by_id=compact_rooms_by_id),
        "canvas": s._canvas_path_summary(team, team_id=normalized_team_id),
    }
    s._record_team_detail_loaded(detail, started_at)
    return detail


def assert_team_exists(team_id: str) -> str:
    """Validate that a Team exists without hydrating or repairing its full detail."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
    return normalized_team_id


def update_team(
    team_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    purpose: str | None = None,
    status: str | None = None,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    should_archive = False
    members_changed = False
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        if name is not None:
            normalized_name = trim_lines(name or "", max_lines=1).strip()
            if not normalized_name:
                raise s.TeamServiceError("Team name is required.")
            team["name"] = normalized_name
        if description is not None:
            team["description"] = trim_lines(description or "", max_lines=8).strip()
        if purpose is not None:
            team["purpose"] = trim_lines(purpose or "", max_lines=4).strip()
        if status is not None:
            normalized_status = str(status or "").strip().lower() or s.DEFAULT_TEAM_STATUS
            if normalized_status not in s.TEAM_STATUSES:
                raise s.TeamServiceError(f"Unsupported team status: {status}")
            if normalized_status == "archived" and str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() != "archived":
                should_archive = True
            else:
                team["status"] = normalized_status
        if members is not None:
            normalized_members = s._normalize_members(members, require_active=True)
            s._ensure_members_can_join_team(normalized_members, state, normalized_team_id)
            team["members"] = normalized_members
            members_changed = True
        team["updatedAt"] = s.utc_now_iso()
        team["canvasPath"] = s._relative_path(s._team_canvas_path(normalized_team_id))
        state["updatedAt"] = team["updatedAt"]
        s._save_index(state)
    if should_archive:
        return s.archive_team(normalized_team_id)
    if members_changed:
        s._ensure_active_member_direct_sessions(team)
        s._ensure_team_chat_room_link(team)
        with s._TEAM_LOCK:
            state = s._load_index()
            stored = s._find_team(state, normalized_team_id)
            if stored is not None:
                stored["linkedChatRoomId"] = str(team.get("linkedChatRoomId") or "").strip()
                stored["updatedAt"] = s.utc_now_iso()
                state["updatedAt"] = stored["updatedAt"]
                s._save_index(state)
                team = stored
    s._record_team_event("team.updated", team, fields={"memberCount": len(team.get("members") or [])})
    return s.get_team(normalized_team_id)


def remove_agent_from_teams(agent_id: str, *, include_restore_token: bool = False) -> dict[str, Any]:
    """Remove one unavailable Agent from active Team membership and linked rooms."""

    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.TeamServiceError("Agent id is required.")
    cleanup = s.remove_agents_from_teams([normalized_agent_id], include_restore_token=include_restore_token)
    result = {
        "agentId": normalized_agent_id,
        "changedTeamIds": list(cleanup.get("changedTeamIds") or []),
    }
    if include_restore_token:
        result["restoreToken"] = cleanup.get("restoreToken")
    return result


def remove_agents_from_teams(agent_ids: list[str] | None, *, include_restore_token: bool = False) -> dict[str, Any]:
    """Remove multiple unavailable Agents from active Team membership in one index update."""

    s = _service()
    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    normalized_agent_ids: list[str] = []
    seen_agent_ids: set[str] = set()
    for agent_id in requested:
        if agent_id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent_id)
        normalized_agent_ids.append(agent_id)
    if not normalized_agent_ids:
        return {"agentIds": [], "changedTeamIds": [], "removedByAgentId": {}}
    changed_team_ids: list[str] = []
    restore_teams: list[dict[str, Any]] = []
    restore_canvases: dict[str, dict[str, Any] | None] = {}
    removed_by_agent_id: dict[str, list[str]] = {agent_id: [] for agent_id in normalized_agent_ids}
    agent_id_set = set(normalized_agent_ids)
    with s._TEAM_LOCK:
        state = s._load_index()
        teams = [item for item in list(state.get("teams") or []) if isinstance(item, dict)]
        now = s.utc_now_iso()
        for team in teams:
            if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
                continue
            members = [dict(item) for item in list(team.get("members") or []) if isinstance(item, dict)]
            removed_agent_ids_for_team = {
                str(member.get("agentId") or "").strip()
                for member in members
                if str(member.get("agentId") or "").strip() in agent_id_set
            }
            next_members = [
                member
                for member in members
                if str(member.get("agentId") or "").strip() not in agent_id_set
            ]
            if next_members == members:
                continue
            team_id = str(team.get("teamId") or "").strip()
            if include_restore_token:
                restore_teams.append(copy.deepcopy(team))
                canvas_path = s._team_canvas_path(team_id)
                restore_canvases[team_id] = copy.deepcopy(s._read_json(canvas_path)) if canvas_path.exists() else None
            team["members"] = next_members
            team["updatedAt"] = now
            team["canvasPath"] = s._relative_path(s._team_canvas_path(team_id))
            for removed_agent_id in sorted(removed_agent_ids_for_team):
                s._remove_agent_from_team_canvas(team, removed_agent_id)
                removed_by_agent_id.setdefault(removed_agent_id, []).append(team_id)
            s._sync_chat_room_root()
            s._ensure_team_chat_room_link(team)
            changed_team_ids.append(team_id)
        if changed_team_ids:
            state["updatedAt"] = now
            s._save_index(state)
    for team_id in changed_team_ids:
        removed_agent_ids = [
            agent_id
            for agent_id, team_ids in removed_by_agent_id.items()
            if team_id in set(team_ids)
        ]
        s._record_team_event(
            "team.agent_membership.removed",
            {"teamId": team_id, "status": s.DEFAULT_TEAM_STATUS},
            fields={"agentIds": removed_agent_ids, "agentCount": len(removed_agent_ids)},
        )
    result = {
        "agentIds": normalized_agent_ids,
        "changedTeamIds": changed_team_ids,
        "removedByAgentId": {
            agent_id: list(team_ids)
            for agent_id, team_ids in removed_by_agent_id.items()
            if team_ids
        },
    }
    if include_restore_token:
        result["restoreToken"] = {"teams": restore_teams, "canvases": restore_canvases}
    return result


def restore_removed_agents_to_teams(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    """Restore exact Team membership and canvas snapshots after a failed archive."""

    s = _service()
    token = dict(restore_token or {})
    snapshots = [copy.deepcopy(item) for item in list(token.get("teams") or []) if isinstance(item, dict)]
    if not snapshots:
        return {"restoredTeamIds": []}
    restored_ids: list[str] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        teams = [item for item in list(state.get("teams") or []) if isinstance(item, dict)]
        by_id = {str(item.get("teamId") or "").strip(): index for index, item in enumerate(teams)}
        for snapshot in snapshots:
            team_id = str(snapshot.get("teamId") or "").strip()
            if not team_id or team_id not in by_id:
                continue
            teams[by_id[team_id]] = snapshot
            restored_ids.append(team_id)
        state["teams"] = teams
        if restored_ids:
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
            canvases = token.get("canvases") if isinstance(token.get("canvases"), dict) else {}
            for team_id in restored_ids:
                canvas = canvases.get(team_id)
                if isinstance(canvas, dict):
                    s._write_json(s._team_canvas_path(team_id), canvas)
    return {"restoredTeamIds": restored_ids}


def archive_team(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    already_archived = False
    agent_ids: list[str] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            already_archived = True
            member_changed, agent_ids = s._repair_archived_team_member_agents_for_team(
                team,
                state,
                reason="archive_team_already_archived",
                strict=True,
            )
            room_changed = s._repair_archived_team_linked_chat_room(team, reason="archive_team_already_archived")
            if member_changed or room_changed:
                state["updatedAt"] = s.utc_now_iso()
                s._save_index(state)
        else:
            s._reject_system_or_unsupported_team_archive(team)
            agent_ids = s._unique_active_member_agent_ids(team)
            s._ensure_team_member_agents_can_archive(team, agent_ids)

    cascade = {"archivedAgentIds": [], "removedFromRoomIds": [], "roomCleanupByAgentId": {}}
    if agent_ids:
        cascade = s._cascade_archive_member_agents_unlocked(
            agent_ids,
            reason="team_archive" if not already_archived else "archive_team_already_archived",
        )
        if already_archived and cascade.get("archivedAgentIds"):
            s._record_archived_team_member_cascade_repaired(
                {"teamId": normalized_team_id},
                list(cascade.get("archivedAgentIds") or []),
                reason="archive_team_already_archived",
            )

    if already_archived:
        return s.get_team(normalized_team_id)

    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            return s.get_team(normalized_team_id)
        return s._finalize_archived_team_in_state(state, team, cascade=cascade)


def _reject_system_or_unsupported_team_archive(team: dict[str, Any]) -> None:
    s = _service()
    team_kind = str(team.get("teamKind") or s._infer_team_kind(team)).strip() or "custom"
    if team_kind in {"research", "ai_search", "self_evolution", "supervised_evolution"}:
        s._record_team_archive_rejected(team, reason="system_team")
        raise s.TeamServiceError("System Team cannot be archived with cascade Agent deletion.")
    if team_kind not in {"custom", "template_demo"}:
        s._record_team_archive_rejected(team, reason="unsupported_team_kind")
        raise s.TeamServiceError(f"Team kind cannot be archived with cascade Agent deletion: {team_kind}")


def _archive_team_in_state(state: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper. Member Agent/session writes happen in archive_team without _TEAM_LOCK."""

    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        raise s.TeamServiceError("Team id is required.")
    return s.archive_team(team_id)


def _finalize_archived_team_in_state(
    state: dict[str, Any],
    team: dict[str, Any],
    *,
    cascade: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    s._reject_system_or_unsupported_team_archive(team)
    deleted_room_ids = s._delete_team_linked_chat_rooms(team, reason="team_archive", strict_busy=True)
    now = s.utc_now_iso()
    team["status"] = "archived"
    team["updatedAt"] = now
    team["canvasPath"] = s._relative_path(s._team_canvas_path(team_id))
    state["updatedAt"] = now
    s._save_index(state)
    archived_agent_ids = list(cascade.get("archivedAgentIds") or [])
    s._record_team_event(
        "team.archived_with_agents",
        team,
        fields={
            "archivedAgentIds": archived_agent_ids,
            "archivedAgentCount": len(archived_agent_ids),
            "deletedLinkedChatRoomIds": deleted_room_ids,
            "deletedLinkedChatRoomCount": len(deleted_room_ids),
            "removedFromRoomIds": list(cascade.get("removedFromRoomIds") or []),
            "removedFromRoomCount": len(list(cascade.get("removedFromRoomIds") or [])),
            "roomCleanupByAgentId": dict(cascade.get("roomCleanupByAgentId") or {}),
        },
    )
    return s.get_team(team_id)


def send_team_message(
    team_id: str,
    *,
    content: str,
    interrupt_mode: str = "none",
    wake_target: bool = True,
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    team = s._get_team_record(team_id)
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
        raise s.TeamServiceError("Archived teams cannot receive new messages.")
    normalized_content = trim_lines(content or "", max_lines=40).strip()
    if not normalized_content:
        raise s.TeamServiceError("Team message content is required.")
    target_agent_ids = s._active_member_agent_ids(team)
    if not target_agent_ids:
        raise s.TeamServiceError("Team has no active Agent members.")
    s._sync_project_bus_root()
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
    s._record_team_event(
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


def list_agent_team_references() -> dict[str, list[dict[str, Any]]]:
    s = _service()
    references: dict[str, list[dict[str, Any]]] = {}
    for team in s.list_teams(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        status = str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip()
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


def _find_reusable_empty_team(
    state: dict[str, Any],
    *,
    normalized_name: str,
    team_kind: str,
    team_source: str,
    team_template_id: str,
    requested_member_count: int,
) -> dict[str, Any] | None:
    s = _service()
    if requested_member_count:
        return None
    requested_key = s._normalized_team_dedupe_key(
        name=normalized_name,
        team_kind=team_kind,
        team_source=team_source,
        team_template_id=team_template_id,
    )
    candidates: list[dict[str, Any]] = []
    for item in list(state.get("teams") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            continue
        if len(list(item.get("members") or [])):
            continue
        item_key = s._normalized_team_dedupe_key(
            name=str(item.get("name") or "").strip(),
            team_kind=str(item.get("teamKind") or ""),
            team_source=str(item.get("teamSource") or ""),
            team_template_id=str(item.get("teamTemplateId") or ""),
        )
        if item_key == requested_key:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""))
    return candidates[0]


def _new_team_id(name: str, existing_ids: set[str]) -> str:
    s = _service()
    base = s._safe_token(name, default="team", max_length=48).lower()
    candidate = base
    index = 2
    while candidate in existing_ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _normalized_team_dedupe_key(
    *,
    name: str,
    team_kind: str,
    team_source: str,
    team_template_id: str,
) -> tuple[str, str, str, str]:
    s = _service()
    probe = {
        "name": name,
        "teamKind": team_kind,
        "teamSource": team_source,
        "teamTemplateId": team_template_id,
    }
    s._apply_team_contract(
        probe,
        team_kind=team_kind,
        team_source=team_source,
        team_template_id=team_template_id,
    )
    return (
        str(probe.get("teamSource") or s.TEAM_KIND_DEFAULTS["custom"]["teamSource"]).strip().lower(),
        str(probe.get("teamKind") or "custom").strip().lower(),
        str(probe.get("teamTemplateId") or "").strip().lower(),
        str(name or "").strip().lower(),
    )


def _summary(teams: list[dict[str, Any]]) -> dict[str, Any]:
    s = _service()
    active = [team for team in teams if str(team.get("status") or s.DEFAULT_TEAM_STATUS) != "archived"]
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
