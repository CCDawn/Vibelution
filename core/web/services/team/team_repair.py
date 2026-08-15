"""Team index and membership repair helpers.

Claim scope: index shape/contract repair, derived-member prune, archived-member
cascade repair, and member agent archive prechecks.
Late-binds ``team_service`` for contracts, logging, and chat-room repair helpers.
"""

from __future__ import annotations

from typing import Any

from core.chat.chat_task_types import trim_lines
from core.web.services import agent_directory_service


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def _ensure_team_member_agents_can_archive(team: dict[str, Any], agent_ids: list[str]) -> None:
    s = _service()
    for agent_id in agent_ids:
        try:
            agent_directory_service.ensure_agent_archive_allowed(agent_id)
        except agent_directory_service.AgentDirectoryError as exc:
            s._record_team_archive_rejected(team, reason="agent_archive_rejected", agent_id=agent_id, error=exc)
            raise s.TeamServiceError(str(exc)) from exc


def _cascade_archive_member_agents_unlocked(agent_ids: list[str], *, reason: str) -> dict[str, Any]:
    """Archive member Agents and seal their sessions. Caller must not hold ``_TEAM_LOCK``."""

    s = _service()
    from core.web.services.agent_bulk_delete_service import MAX_BULK_AGENT_IDS, bulk_archive_agents

    requested = [str(item or "").strip() for item in agent_ids if str(item or "").strip()]
    if not requested:
        return {"archivedAgentIds": [], "removedFromRoomIds": [], "roomCleanupByAgentId": {}, "failed": []}

    archived_agent_ids: list[str] = []
    room_cleanup_by_agent_id: dict[str, list[str]] = {}
    removed_from_room_ids: list[str] = []
    failed: list[dict[str, Any]] = []
    last_result: dict[str, Any] = {}
    for offset in range(0, len(requested), MAX_BULK_AGENT_IDS):
        chunk = requested[offset : offset + MAX_BULK_AGENT_IDS]
        try:
            result = bulk_archive_agents(chunk, allow_empty_rooms=True)
        except agent_directory_service.AgentDirectoryError as exc:
            raise s.TeamServiceError(str(exc)) from exc
        last_result = result
        for item in list(result.get("success") or []):
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agentId") or "").strip()
            if not agent_id:
                continue
            archived_agent_ids.append(agent_id)
            archive_summary = item.get("archiveSummary") if isinstance(item.get("archiveSummary"), dict) else {}
            room_ids = [
                str(room_id or "").strip()
                for room_id in list(archive_summary.get("removedFromRoomIds") or [])
                if str(room_id or "").strip()
            ]
            if room_ids:
                room_cleanup_by_agent_id[agent_id] = room_ids
                for room_id in room_ids:
                    if room_id not in removed_from_room_ids:
                        removed_from_room_ids.append(room_id)
        failed.extend(item for item in list(result.get("failed") or []) if isinstance(item, dict))
        if failed and reason == "team_archive":
            messages = [str(item.get("message") or item.get("reason") or "archive failed") for item in failed]
            raise s.TeamServiceError("Team member Agents could not be archived: " + "; ".join(messages[:4]))
    return {
        "archivedAgentIds": archived_agent_ids,
        "removedFromRoomIds": removed_from_room_ids,
        "roomCleanupByAgentId": room_cleanup_by_agent_id,
        "failed": failed,
        "bulkResult": last_result,
    }


def _archive_team_member_agents(team: dict[str, Any], agent_ids: list[str], *, reason: str) -> list[str]:
    s = _service()
    cascade = s._cascade_archive_member_agents_unlocked(agent_ids, reason=reason)
    archived_agent_ids = list(cascade.get("archivedAgentIds") or [])
    if archived_agent_ids and reason != "team_archive":
        s._record_archived_team_member_cascade_repaired(team, archived_agent_ids, reason=reason)
    return archived_agent_ids


def _repair_archived_team_member_agents(
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[bool, list[str]]:
    s = _service()
    changed = False
    pending_agent_ids: list[str] = []
    seen_agent_ids: set[str] = set()
    for team in list(state.get("teams") or []):
        if not isinstance(team, dict):
            continue
        team_changed, agent_ids = s._repair_archived_team_member_agents_for_team(
            team,
            state,
            reason=reason,
            strict=strict,
            agent_refs=agent_refs,
        )
        changed = team_changed or changed
        for agent_id in agent_ids:
            if agent_id in seen_agent_ids:
                continue
            seen_agent_ids.add(agent_id)
            pending_agent_ids.append(agent_id)
    return changed, pending_agent_ids


def _repair_archived_team_member_agents_for_team(
    team: dict[str, Any],
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[bool, list[str]]:
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() != "archived":
        return False, []
    if not s._team_kind_allows_member_agent_cascade(team):
        return False, []
    changed = s._prune_missing_archived_team_members(team, agent_refs=agent_refs)
    agent_ids = s._unique_active_member_agent_ids(team, agent_refs=agent_refs)
    if not agent_ids:
        if changed:
            team["updatedAt"] = s.utc_now_iso()
            state["updatedAt"] = team["updatedAt"]
        return changed, []
    try:
        s._ensure_team_member_agents_can_archive(team, agent_ids)
    except s.TeamServiceError:
        if strict:
            raise
        return changed, []
    return changed, agent_ids


def _prune_missing_archived_team_members(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    s = _service()
    kept_members: list[dict[str, Any]] = []
    removed_agent_ids: list[str] = []
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        if s._agent_reference(agent_id, include_archived=True, agent_refs=agent_refs):
            kept_members.append(member)
            continue
        removed_agent_ids.append(agent_id)
    if not removed_agent_ids:
        return False
    team["members"] = kept_members
    s._record_team_event(
        "team.archived_missing_members_pruned",
        team,
        fields={
            "removedAgentIds": removed_agent_ids,
            "removedAgentCount": len(removed_agent_ids),
        },
    )
    return True


def _repair_index_state(
    state: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    s = _service()
    changed = False
    if state.get("schemaVersion") != s.SCHEMA_VERSION:
        state["schemaVersion"] = s.SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    for team in state.get("teams") or []:
        if isinstance(team, dict):
            changed = s._repair_team(team, agent_refs=agent_refs) or changed
    return changed


def _repair_index_shape(state: dict[str, Any]) -> bool:
    s = _service()
    changed = False
    if state.get("schemaVersion") != s.SCHEMA_VERSION:
        state["schemaVersion"] = s.SCHEMA_VERSION
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
    s = _service()
    changed = s._repair_index_shape(state)
    for team in state.get("teams") or []:
        if not isinstance(team, dict):
            continue
        if s._repair_team_contract_only(team, compact_rooms_by_id=compact_rooms_by_id):
            changed = True
    return changed


def _repair_team_contract_only(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    s = _service()
    changed = False
    team_id = s._safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    expected_path = s._relative_path(s._team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if s._infer_team_kind(team) == "ai_search":
        expected_source_scope_path = s._relative_path(s._ai_search_source_scope_path())
        if team.get("sourceScopePath") != expected_source_scope_path:
            team["sourceScopePath"] = expected_source_scope_path
            changed = True
        if s._ensure_ai_search_source_scope_file():
            changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    if s._apply_team_contract(team):
        changed = True
    if s._sync_compact_team_chat_room_metadata(team, compact_rooms_by_id=compact_rooms_by_id):
        changed = True
    return changed


def _repair_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    s = _service()
    changed = False
    team_id = s._safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    if not str(team.get("name") or "").strip():
        team["name"] = team_id or "Team"
        changed = True
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS) not in s.TEAM_STATUSES:
        team["status"] = s.DEFAULT_TEAM_STATUS
        changed = True
    expected_path = s._relative_path(s._team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if s._infer_team_kind(team) == "ai_search":
        expected_source_scope_path = s._relative_path(s._ai_search_source_scope_path())
        if team.get("sourceScopePath") != expected_source_scope_path:
            team["sourceScopePath"] = expected_source_scope_path
            changed = True
        if s._ensure_ai_search_source_scope_file():
            changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    if s._apply_team_contract(team):
        changed = True
    members = team.get("members") if isinstance(team.get("members"), list) else []
    stale_member_agent_ids = s._stale_member_agent_ids(members)
    repaired_members = s._repair_members(members, agent_refs=agent_refs)
    if repaired_members != members:
        team["members"] = repaired_members
        changed = True
    removed_agent_ids = s._prune_unavailable_derived_team_members(
        team,
        agent_refs=agent_refs,
        stale_member_agent_ids=stale_member_agent_ids,
    )
    if removed_agent_ids:
        changed = True
        for removed_agent_id in removed_agent_ids:
            s._remove_agent_from_team_canvas(team, removed_agent_id)
    if s._infer_team_kind(team) == "research":
        s._sync_research_team_member_agent_roles(team.get("members") or [])
    if removed_agent_ids or s._team_chat_room_needs_sync(team, agent_refs=agent_refs):
        s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    if removed_agent_ids:
        s._record_team_event(
            "team.derived_unavailable_members_pruned",
            team,
            fields={
                "removedAgentIds": removed_agent_ids,
                "removedAgentCount": len(removed_agent_ids),
                "teamKind": s._infer_team_kind(team),
            },
        )
    return changed


def _prune_unavailable_derived_team_members(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
    stale_member_agent_ids: set[str] | None = None,
) -> list[str]:
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
        return []
    if s._infer_team_kind(team) not in s.DERIVED_TEAM_KINDS:
        return []
    stale_member_agent_ids = {
        str(agent_id or "").strip()
        for agent_id in set(stale_member_agent_ids or set())
        if str(agent_id or "").strip()
    }
    if not stale_member_agent_ids:
        return []
    kept_members: list[dict[str, Any]] = []
    removed_agent_ids: list[str] = []
    seen_removed: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        if agent_id not in stale_member_agent_ids:
            kept_members.append(member)
            continue
        if s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs):
            kept_members.append(member)
            continue
        if agent_id not in seen_removed:
            seen_removed.add(agent_id)
            removed_agent_ids.append(agent_id)
    if removed_agent_ids:
        team["members"] = kept_members
        team["updatedAt"] = s.utc_now_iso()
    return removed_agent_ids


def _stale_member_agent_ids(members: list[Any]) -> set[str]:
    s = _service()
    return {
        str(member.get("agentId") or "").strip()
        for member in list(members or [])
        if isinstance(member, dict)
        and str(member.get("agentId") or "").strip()
        and str(member.get("agentStatus") or "").strip().lower() == "stale"
    }


def _repair_members(
    members: list[Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    repaired: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(members):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agent = s._agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        active = s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) if agent_id else None
        repaired.append(
            {
                "memberId": s._safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
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
