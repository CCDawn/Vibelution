"""Team linked chat-room sync and repair helpers.

Claim scope: team <-> chat_room linking, historical room reuse, compact metadata
sync, and archived-room repair. Late-binds ``team_service`` for index locks and
team record helpers.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.web.services import chat_room_service


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def list_archived_team_linked_chat_room_ids() -> set[str]:
    """Return room IDs linked to archived teams without loading chat-room catalog data."""

    s = _service()
    team_lock_acquired = s._try_acquire_team_lock()
    try:
        state = s._load_index()
    finally:
        s._release_team_lock_if_acquired(team_lock_acquired)
    return {
        str(item.get("linkedChatRoomId") or "").strip()
        for item in list(state.get("teams") or [])
        if isinstance(item, dict)
        and str(item.get("status") or s.DEFAULT_TEAM_STATUS).strip().lower() == "archived"
        and str(item.get("linkedChatRoomId") or "").strip()
    }


def sync_team_chat_room(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    agent_refs = s._agent_reference_maps()
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        if s._repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = s.utc_now_iso()
        s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
        state["updatedAt"] = team["updatedAt"]
        s._save_index(state)
    return s.get_team(normalized_team_id)


def _remove_team_member_agents_from_chat_rooms(team: dict[str, Any], agent_ids: list[str]) -> dict[str, Any]:
    s = _service()
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
        s._record_team_archive_rejected(team, reason="chat_room_busy", error=exc)
        raise s.TeamServiceError(str(exc)) from exc
    except chat_room_service.ChatRoomValidationError as exc:
        s._record_team_archive_rejected(team, reason="chat_room_cleanup_rejected", error=exc)
        raise s.TeamServiceError(str(exc)) from exc


def _team_chat_room_title(team: dict[str, Any]) -> str:
    s = _service()
    name = str(team.get("name") or team.get("teamId") or "Team").strip()
    return f"{name} 团队群聊"


def _team_participant_contexts_by_agent_id(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    s = _service()
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
        agent = s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) or {}
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
    s = _service()
    if chat_room_service.PROJECT_ROOT != s.PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = s.PROJECT_ROOT


def _team_chat_room_purpose_for_update(team: dict[str, Any], current_purpose: Any) -> str:
    s = _service()
    normalized_current = str(current_purpose or "").strip()
    expected = s._team_default_chat_room_purpose(team)
    if not normalized_current:
        return expected
    if normalized_current == "discussion" and s._infer_team_kind(team) != "custom":
        return expected
    return normalized_current


def _ensure_team_chat_room_link(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
        return str(team.get("linkedChatRoomId") or "").strip()
    session_ids = s._active_member_session_ids(team, agent_refs=agent_refs)
    s._sync_chat_room_root()
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    title = s._team_chat_room_title(team)
    config = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or s.TEAM_KIND_DEFAULTS["custom"]["teamCategory"]).strip(),
        "teamSource": str(team.get("teamSource") or s.TEAM_KIND_DEFAULTS["custom"]["teamSource"]).strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    participant_contexts = s._team_participant_contexts_by_agent_id(team, agent_refs=agent_refs)
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
                purpose=s._team_chat_room_purpose_for_update(team, linked_room.get("purpose")),
                config=room_config,
            )
    else:
        reusable_room_id = s._find_existing_team_chat_room_id(str(team.get("teamId") or "").strip())
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
                purpose=s._team_chat_room_purpose_for_update(team, reusable_room.get("purpose")),
                config=room_config,
            )
        else:
            historical_room_id = s._find_historical_team_chat_room_id(str(team.get("teamId") or "").strip(), preferred_room_id=linked_room_id)
            room = chat_room_service.create_chat_room(
                room_id=historical_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode="round_robin",
                purpose=s._team_default_chat_room_purpose(team),
                config=config,
            )
    team["linkedChatRoomId"] = str(room.get("roomId") or "").strip()
    s._archive_duplicate_team_chat_rooms(team["linkedChatRoomId"], str(team.get("teamId") or "").strip())
    s._ensure_historical_team_chat_room_links(
        team,
        title=title,
        session_ids=session_ids,
        participant_contexts=participant_contexts,
        config=config,
    )
    team["updatedAt"] = s.utc_now_iso()
    s._record_team_event(
        "team.chat_room.synced",
        team,
        fields={
            "linkedChatRoomId": team["linkedChatRoomId"],
            "memberSessionCount": len(session_ids),
        },
    )
    return team["linkedChatRoomId"]


def _find_existing_team_chat_room_id(team_id: str) -> str:
    s = _service()
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


def _find_historical_team_chat_room_id(team_id: str, *, preferred_room_id: str = "") -> str:
    s = _service()
    candidates = s._historical_team_chat_room_ids(team_id)
    preferred = str(preferred_room_id or "").strip()
    if preferred and preferred in candidates:
        return preferred
    return candidates[-1] if candidates else ""


def _historical_team_chat_room_ids(team_id: str) -> list[str]:
    s = _service()
    normalized_team_id = s._safe_token(team_id, default="", max_length=96)
    if not normalized_team_id:
        return []
    rounds_path = s._teams_root() / normalized_team_id / "research_stage_rounds" / "index.json"
    if not rounds_path.exists():
        return []
    try:
        payload = json.loads(rounds_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("linkedChatRoomId", "coordinationRoomId", "roomId"):
                room_id = str(value.get(key) or "").strip()
                if room_id.startswith("room-") and room_id not in candidates:
                    candidates.append(room_id)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    return candidates


def _ensure_historical_team_chat_room_links(
    team: dict[str, Any],
    *,
    title: str,
    session_ids: list[str],
    participant_contexts: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[str]:
    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    current_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not team_id or not current_room_id:
        return []
    created_room_ids: list[str] = []
    updated_room_ids: list[str] = []
    for room_id in s._historical_team_chat_room_ids(team_id):
        if not room_id or room_id == current_room_id:
            continue
        room_config = {
            **config,
            "historicalTeamRoom": True,
            "teamRoomRole": "historical",
            "currentLinkedChatRoomId": current_room_id,
        }
        existing_room = chat_room_service.get_chat_room_detail(room_id)
        if existing_room:
            try:
                chat_room_service.update_chat_room(
                    room_id,
                    title=f"{title}（历史）",
                    participant_session_ids=session_ids,
                    participant_contexts_by_agent_id=participant_contexts,
                    allow_empty_participants=True,
                    mode=str(existing_room.get("mode") or "round_robin"),
                    purpose=s._team_chat_room_purpose_for_update(team, existing_room.get("purpose")),
                    config={
                        **dict(existing_room.get("config") or {}),
                        **room_config,
                    },
                )
            except Exception:
                continue
            updated_room_ids.append(room_id)
            continue
        try:
            chat_room_service.create_chat_room(
                room_id=room_id,
                title=f"{title}（历史）",
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode="round_robin",
                purpose=s._team_default_chat_room_purpose(team),
                config=room_config,
            )
        except Exception:
            continue
        created_room_ids.append(room_id)
    if created_room_ids or updated_room_ids:
        s._record_team_event(
            "team.chat_room.history_synced",
            team,
            fields={
                "linkedChatRoomId": current_room_id,
                "historicalRoomIds": created_room_ids,
                "historicalRoomCount": len(created_room_ids),
                "historicalUpdatedRoomIds": updated_room_ids,
                "historicalUpdatedRoomCount": len(updated_room_ids),
            },
        )
    return created_room_ids


def _archive_duplicate_team_chat_rooms(keep_room_id: str, team_id: str) -> None:
    s = _service()
    normalized_keep_room_id = str(keep_room_id or "").strip()
    normalized_team_id = str(team_id or "").strip()
    if not normalized_keep_room_id or not normalized_team_id:
        return
    historical_room_ids = set(s._historical_team_chat_room_ids(normalized_team_id))
    historical_room_ids.discard(normalized_keep_room_id)
    duplicates = [
        room for room in chat_room_service.list_chat_rooms()
        if str(room.get("roomId") or "").strip() != normalized_keep_room_id
        and str(room.get("roomId") or "").strip() not in historical_room_ids
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
        s._record_team_event(
            "team.chat_room.duplicates_archived",
            {"teamId": normalized_team_id, "linkedChatRoomId": normalized_keep_room_id},
            fields={
                "linkedChatRoomId": normalized_keep_room_id,
                "duplicateRoomCount": len(duplicates),
            },
        )


def repair_archived_team_chat_rooms() -> dict[str, Any]:
    """Delete linked team chat rooms for Teams that are already archived."""

    s = _service()
    s._sync_chat_room_root()
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = False
        deleted_room_ids: list[str] = []
        for team in list(state.get("teams") or []):
            if not isinstance(team, dict):
                continue
            if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() != "archived":
                continue
            before = str(team.get("linkedChatRoomId") or "").strip()
            deleted = s._delete_team_linked_chat_rooms(team, reason="archived_team_repair")
            if deleted:
                deleted_room_ids.extend(deleted)
            if deleted or before != str(team.get("linkedChatRoomId") or "").strip():
                changed = True
        if changed:
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
    return {
        "deleted": bool(deleted_room_ids),
        "deletedRoomIds": deleted_room_ids,
        "deletedRoomCount": len(deleted_room_ids),
    }


def _repair_archived_team_linked_chat_room(team: dict[str, Any], *, reason: str) -> bool:
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() != "archived":
        return False
    before = str(team.get("linkedChatRoomId") or "").strip()
    deleted = s._delete_team_linked_chat_rooms(team, reason=reason)
    after = str(team.get("linkedChatRoomId") or "").strip()
    return bool(deleted) or before != after


def _delete_team_linked_chat_rooms(team: dict[str, Any], *, reason: str, strict_busy: bool = False) -> list[str]:
    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return []
    s._sync_chat_room_root()
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
            s._record_team_event(
                "team.chat_room.archive_delete_rejected",
                team,
                fields={"linkedChatRoomId": room_id, "reason": reason, "errorType": type(exc).__name__},
            )
            if strict_busy:
                raise s.TeamServiceError("Team chat room has an active round and cannot be deleted while archiving.") from exc
            continue
        deleted_room_ids.append(room_id)

    if linked_room_id and linked_room_id in {*deleted_room_ids, *missing_room_ids}:
        team["linkedChatRoomId"] = ""
    if deleted_room_ids or missing_room_ids:
        s._record_team_event(
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
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    active_member_agent_ids = s._active_member_agent_ids(team, agent_refs=agent_refs)
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return True
    s._sync_chat_room_root()
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
    if s._team_chat_room_participant_contexts_need_sync(team, linked_room, agent_refs=agent_refs):
        return True
    historical_room_ids = [
        room_id
        for room_id in s._historical_team_chat_room_ids(str(team.get("teamId") or "").strip())
        if room_id and room_id != linked_room_id
    ]
    if any(
        s._historical_team_chat_room_needs_sync(
            team,
            room_id=room_id,
            current_room_id=linked_room_id,
            active_member_agent_ids=active_member_agent_ids,
        )
        for room_id in historical_room_ids
    ):
        return True
    team_kind = s._infer_team_kind(team)
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
    return str(linked_room.get("purpose") or "").strip() != s._team_chat_room_purpose_for_update(team, linked_room.get("purpose"))


def _team_chat_room_participant_contexts_need_sync(
    team: dict[str, Any],
    linked_room: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    s = _service()
    expected_contexts = s._team_participant_contexts_by_agent_id(team, agent_refs=agent_refs)
    for participant in list(linked_room.get("participants") or []):
        if not isinstance(participant, dict):
            continue
        agent_id = str(participant.get("agentId") or "").strip()
        expected = expected_contexts.get(agent_id)
        if not isinstance(expected, dict):
            continue
        for field, expected_value in expected.items():
            if s._normalized_participant_context_value(participant.get(field)) != s._normalized_participant_context_value(expected_value):
                return True
    return False


def _normalized_participant_context_value(value: Any) -> Any:
    s = _service()
    if isinstance(value, list):
        return [
            trim_lines(str(item or ""), max_lines=1).strip()
            for item in value[:8]
            if trim_lines(str(item or ""), max_lines=1).strip()
        ]
    return trim_lines(str(value or ""), max_lines=4).strip()


def _historical_team_chat_room_needs_sync(
    team: dict[str, Any],
    *,
    room_id: str,
    current_room_id: str,
    active_member_agent_ids: list[str],
) -> bool:
    s = _service()
    room = chat_room_service.get_chat_room_compact(room_id)
    if not room:
        return True
    participant_agent_ids = [
        str(participant.get("agentId") or "").strip()
        for participant in list(room.get("participants") or [])
        if isinstance(participant, dict) and str(participant.get("agentId") or "").strip()
    ]
    if participant_agent_ids != active_member_agent_ids:
        return True
    if str(room.get("title") or "").strip() != f"{s._team_chat_room_title(team)}（历史）":
        return True
    if str(room.get("purpose") or "").strip() != s._team_chat_room_purpose_for_update(team, room.get("purpose")):
        return True
    config = room.get("config") if isinstance(room.get("config"), dict) else {}
    expected_pairs = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
        "teamRoomRole": "historical",
        "currentLinkedChatRoomId": current_room_id,
    }
    if any(str(config.get(key) or "").strip() != value for key, value in expected_pairs.items() if value):
        return True
    return config.get("historicalTeamRoom") is not True


def _sync_compact_team_chat_room_metadata(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    s = _service()
    if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    if s._infer_team_kind(team) == "custom":
        return False
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return False
    if compact_rooms_by_id is None:
        s._sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id)
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id)
    if not linked_room:
        return False
    next_purpose = s._team_chat_room_purpose_for_update(team, linked_room.get("purpose"))
    current_purpose = str(linked_room.get("purpose") or "").strip()
    config = {
        **dict(linked_room.get("config") or {}),
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
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
        s._record_compact_chat_room_sync_skipped_busy(team, linked_room_id, exc)
        return False
    return True


def _compact_chat_room(room: dict[str, Any] | None) -> dict[str, Any] | None:
    s = _service()
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


def _record_compact_chat_room_sync_skipped_busy(team: dict[str, Any], linked_room_id: str, exc: Exception) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team_compact_repair",
            "team.compact_chat_room_sync_skipped_busy",
            message="Team compact repair skipped linked chat room metadata sync because the room has an active round.",
            level="warning",
            outcome="skipped",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "linkedChatRoomId": str(linked_room_id or "").strip(),
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"Failed to record compact chat room sync skipped busy for team={team.get('teamId')}, linked_room_id={linked_room_id}. error={exc}"
        )
