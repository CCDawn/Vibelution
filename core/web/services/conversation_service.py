"""Unified conversation index for direct agents and group rooms."""

from __future__ import annotations

from typing import Any

from . import chat_room_service, session_service


def list_conversations() -> list[dict[str, Any]]:
    """Return direct agent conversations and group rooms in one index."""

    items: list[dict[str, Any]] = []
    sessions = session_service.list_sessions()
    session_summaries = {
        str(session.get("id") or "").strip(): session
        for session in sessions
        if isinstance(session, dict) and str(session.get("id") or "").strip()
    }
    for session in sessions:
        items.append(
            {
                "conversationId": str(session.get("id") or "").strip(),
                "type": "direct_agent",
                "title": str(session.get("agentDisplayName") or session.get("title") or "").strip(),
                "agentId": str(session.get("agentId") or "").strip(),
                "agentCode": str(session.get("agentCode") or "").strip(),
                "directSessionId": str(session.get("id") or "").strip(),
                "roomId": "",
                "status": str(session.get("status") or "").strip(),
                "summary": str(session.get("taskSummary") or "").strip(),
                "updatedAt": str(session.get("updatedAt") or session.get("lastActive") or "").strip(),
                "workspacePath": str(session.get("agentWorkspacePath") or session.get("workspacePath") or "").strip(),
                "agentProfileId": str(session.get("agentProfileId") or "").strip(),
                "agentTemplateLabel": str(session.get("agentTemplateLabel") or "").strip(),
            }
        )
    for room in chat_room_service.list_chat_rooms(session_summaries=session_summaries):
        latest_round = _latest_round(room)
        items.append(
            {
                "conversationId": str(room.get("roomId") or "").strip(),
                "type": "group_room",
                "title": str(room.get("title") or room.get("roomId") or "").strip(),
                "agentId": "",
                "directSessionId": "",
                "roomId": str(room.get("roomId") or "").strip(),
                "status": str(room.get("status") or "").strip(),
                "summary": str((latest_round or {}).get("summary") or "").strip(),
                "updatedAt": str(room.get("updatedAt") or "").strip(),
                "workspacePath": f"workspace/chat_rooms/{room.get('roomId') or ''}",
                "participantCount": len(list(room.get("participants") or [])),
                "mode": str(room.get("mode") or "").strip(),
            }
        )
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return items


def _latest_round(room: dict[str, Any]) -> dict[str, Any] | None:
    rounds = [item for item in list(room.get("rounds") or []) if isinstance(item, dict)]
    return rounds[-1] if rounds else None
