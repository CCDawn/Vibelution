"""Question-scoped conversation cleanup composed into reset and retire.

Resetting or retiring one question must not leave its team communication behind:
the question owns chat rooms (candidate generation/review meetings) and the
agent sessions whose titles carry the question token, plus mirrored room
transcripts inside participant sessions.  This module is the shared owner of
that scope: it composes the chat-room delete and the bulk session delete, and
reports counts for previews and per-step results.
"""

from __future__ import annotations

from typing import Any

_PREVIEW_DETAIL_LIMIT = 20


def _empty_room_result() -> dict[str, Any]:
    return {
        "removedRoomIds": [],
        "removedRoomCount": 0,
        "removedRoundCount": 0,
        "removedMessageCount": 0,
        "cleanedSessionCount": 0,
        "cleanedTranscriptMessageCount": 0,
        "skipped": [],
        "failed": [],
    }


def _empty_session_result() -> dict[str, Any]:
    return {
        "requestedSessionCount": 0,
        "removedSessionCount": 0,
        "skippedSessionCount": 0,
        "failedSessionCount": 0,
        "removedSessionIds": [],
        "skippedSessions": [],
        "failedSessions": [],
        "truncatedDetails": False,
    }


def preview_question_conversations(team_id: str, question_id: str) -> dict[str, Any]:
    """Non-mutating count of one question's rooms and bound sessions."""

    from core.web.services import chat_room_service
    from core.web.services.session import question_sessions

    rooms = chat_room_service.list_chat_rooms_for_question(team_id, question_id)
    sessions = question_sessions.list_question_session_summaries(question_id)
    return {
        "roomCount": len(rooms),
        "roundCount": sum(int(room.get("roundCount") or 0) for room in rooms),
        "messageCount": sum(int(room.get("messageCount") or 0) for room in rooms),
        "sessionCount": len(sessions),
        "visibleSessionCount": sum(
            1 for session in sessions if not session.get("hiddenFromIndex")
        ),
        "hiddenSessionCount": sum(
            1 for session in sessions if session.get("hiddenFromIndex")
        ),
        "rooms": rooms[:_PREVIEW_DETAIL_LIMIT],
        "sessions": sessions[:_PREVIEW_DETAIL_LIMIT],
    }


def remove_question_conversations(team_id: str, question_id: str) -> dict[str, Any]:
    """Delete one question's rooms and bound sessions, reporting per-step errors."""

    from core.web.services import chat_room_service
    from core.web.services.session import question_sessions

    errors: list[str] = []
    try:
        rooms_result = chat_room_service.remove_chat_rooms_for_question(
            team_id, question_id
        )
    except Exception as exc:  # noqa: BLE001 - report per step and continue
        rooms_result = _empty_room_result()
        errors.append(f"chat rooms: {exc}")
    try:
        sessions_result = question_sessions.remove_question_sessions_for_question(
            question_id
        )
    except Exception as exc:  # noqa: BLE001 - report per step and continue
        sessions_result = _empty_session_result()
        errors.append(f"sessions: {exc}")
    return {
        "schemaVersion": 1,
        "questionId": str(question_id or "").strip().upper(),
        "rooms": rooms_result,
        "sessions": sessions_result,
        "errors": errors,
    }


__all__ = [
    "preview_question_conversations",
    "remove_question_conversations",
]
