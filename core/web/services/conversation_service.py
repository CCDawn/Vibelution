"""Unified conversation index for direct agents and group rooms."""

from __future__ import annotations

from typing import Any

from . import chat_room_service, session_service, team_service
from .runtime_scene_service import record_runtime_scene_event


def list_conversations() -> list[dict[str, Any]]:
    """Return direct agent conversations and group rooms in one index."""

    items: list[dict[str, Any]] = []
    sessions = session_service.list_sessions()
    session_summaries = {
        str(session.get("id") or "").strip(): session
        for session in sessions
        if isinstance(session, dict) and str(session.get("id") or "").strip()
    }
    archived_team_room_ids = _archived_team_room_ids()
    for session in sessions:
        items.append(
            {
                "conversationId": str(session.get("id") or "").strip(),
                "type": "direct_agent",
                "title": str(session.get("title") or session.get("agentDisplayName") or "").strip(),
                "agentId": str(session.get("agentId") or "").strip(),
                "agentCode": str(session.get("agentCode") or "").strip(),
                "agentDisplayName": str(session.get("agentDisplayName") or "").strip(),
                "agentAvatarImagePath": str(session.get("agentAvatarImagePath") or "").strip(),
                "agentAvatarImageUrl": str(session.get("agentAvatarImageUrl") or "").strip(),
                "directSessionId": str(session.get("id") or "").strip(),
                "roomId": "",
                "status": str(session.get("status") or "").strip(),
                "summary": str(session.get("taskSummary") or "").strip(),
                "updatedAt": str(session.get("updatedAt") or session.get("lastActive") or "").strip(),
                "workspacePath": str(session.get("agentWorkspacePath") or session.get("workspacePath") or "").strip(),
                "agentPrimaryMode": str(session.get("agentPrimaryMode") or "").strip(),
                "agentRoleKey": str(session.get("agentRoleKey") or "").strip(),
                "agentPromptTemplateId": str(session.get("agentPromptTemplateId") or "").strip(),
                "agentInboxPendingCount": int(session.get("agentInboxPendingCount") or 0),
            }
        )
    filtered_archived_team_room_count = 0
    for room in chat_room_service.list_chat_rooms_for_conversation_index(session_summaries=session_summaries):
        room_id = str(room.get("roomId") or "").strip()
        if room_id in archived_team_room_ids:
            filtered_archived_team_room_count += 1
            continue
        items.append(
            {
                "conversationId": room_id,
                "type": "group_room",
                "title": str(room.get("title") or room.get("roomId") or "").strip(),
                "agentId": "",
                "directSessionId": "",
                "roomId": room_id,
                "status": str(room.get("status") or "").strip(),
                "summary": str(room.get("summary") or "").strip(),
                "updatedAt": str(room.get("updatedAt") or "").strip(),
                "workspacePath": f"workspace/chat_rooms/{room.get('roomId') or ''}",
                "participantCount": len(list(room.get("participants") or [])),
                "mode": str(room.get("mode") or "").strip(),
            }
        )
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    _record_conversation_index_loaded(
        item_count=len(items),
        session_count=len(sessions),
        filtered_archived_team_room_count=filtered_archived_team_room_count,
    )
    return items


def _archived_team_room_ids() -> set[str]:
    return team_service.list_archived_team_linked_chat_room_ids()


def _record_conversation_index_loaded(
    *,
    item_count: int,
    session_count: int,
    filtered_archived_team_room_count: int,
) -> None:
    if filtered_archived_team_room_count <= 0:
        return
    try:
        record_runtime_scene_event(
            "conversation_service",
            "conversation_index",
            "conversation.index.filtered_archived_team_rooms",
            message="Conversation index filtered archived Team linked rooms.",
            outcome="observed",
            fields={
                "itemCount": item_count,
                "sessionCount": session_count,
                "filteredArchivedTeamRoomCount": filtered_archived_team_room_count,
            },
        )
    except Exception:
        pass
