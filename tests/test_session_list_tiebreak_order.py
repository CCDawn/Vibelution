"""Same-second ordering stability for the conversation index and archive list.

Second-level timestamps tie heavily across sessions, so every list endpoint
must tiebreak the same way (id/conversationId DESC) or rows reshuffle between
views. The session list paths are covered in
``tests/test_session_directory_bridge.py``; this file covers the unified
conversation index and the session archive list.
"""

from __future__ import annotations

from core.web.services import conversation_service
from core.web.services import session_archive_service
from core.web.services import session_service


def _fake_direct_session(session_id: str, updated_at: str) -> dict[str, str]:
    return {"id": session_id, "updatedAt": updated_at, "status": "ready"}


def _fake_room(room_id: str, updated_at: str) -> dict[str, str]:
    return {
        "roomId": room_id,
        "teamId": "",
        "title": room_id,
        "status": "ready",
        "summary": "",
        "updatedAt": updated_at,
        "participants": [],
        "mode": "",
    }


def test_list_conversations_orders_same_second_rows_by_conversation_id_desc(
    monkeypatch,
):
    """Direct sessions and group rooms sharing a second tiebreak by id DESC."""

    sessions = [
        _fake_direct_session("session-direct-a", "2026-01-01T00:00:00"),
        _fake_direct_session("session-new", "2026-01-01T00:00:05"),
        _fake_direct_session("session-direct-b", "2026-01-01T00:00:00"),
    ]
    rooms = [
        _fake_room("room-z", "2026-01-01T00:00:00"),
        _fake_room("room-a", "2026-01-01T00:00:00"),
    ]
    monkeypatch.setattr(session_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(
        conversation_service.chat_room_service,
        "list_chat_rooms_for_conversation_index",
        lambda **_kwargs: rooms,
    )
    monkeypatch.setattr(
        conversation_service.team_service,
        "list_archived_team_linked_chat_room_ids",
        set,
    )

    items = conversation_service.list_conversations()

    assert [item["conversationId"] for item in items] == [
        "session-new",
        # Same-second group: session ids sort above room ids, each DESC.
        "session-direct-b",
        "session-direct-a",
        "room-z",
        "room-a",
    ]


def test_list_group_conversations_orders_same_second_rooms_by_room_id_desc(
    monkeypatch,
):
    rooms = [
        _fake_room("room-m", "2026-01-01T00:00:00"),
        _fake_room("room-a", "2026-01-01T00:00:01"),
        _fake_room("room-z", "2026-01-01T00:00:00"),
    ]
    monkeypatch.setattr(
        conversation_service.chat_room_service,
        "list_chat_rooms_for_conversation_index",
        lambda **_kwargs: rooms,
    )
    monkeypatch.setattr(
        conversation_service.team_service,
        "list_archived_team_linked_chat_room_ids",
        set,
    )

    items = conversation_service.list_group_conversations([])

    assert [item["roomId"] for item in items] == ["room-a", "room-z", "room-m"]


def _archived_raw_rows() -> list[dict[str, str]]:
    def raw(session_id: str, updated_at: str) -> dict[str, str]:
        return {
            "conversation_id": session_id,
            "updatedAt": updated_at,
            "archive_state": {"status": "archived", "source": "session_archive"},
        }

    return [
        raw("session-arch-old", "2026-01-01T00:00:00"),
        raw("session-arch-z", "2026-01-01T00:00:01"),
        raw("session-arch-a", "2026-01-01T00:00:01"),
        raw("session-arch-new", "2026-01-01T00:00:02"),
    ]


def _patch_archive_list_paths(monkeypatch, rows):
    monkeypatch.setattr(
        session_service, "load_chat_state", lambda _root: {"conversations": rows}
    )
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(
        session_service,
        "_normalize_conversation",
        lambda raw, **_kwargs: {
            "id": str(raw.get("conversation_id") or ""),
            "updatedAt": str(raw.get("updatedAt") or ""),
        },
    )


def test_list_archived_sessions_orders_same_second_rows_by_session_id_desc(
    monkeypatch,
):
    """Same-second archived rows tiebreak on session id DESC."""

    # Reversed input proves the order comes from the sort, not the source rows.
    _patch_archive_list_paths(monkeypatch, list(reversed(_archived_raw_rows())))

    payload = session_archive_service.list_archived_sessions()

    assert [item["id"] for item in payload["items"]] == [
        "session-arch-new",
        "session-arch-z",
        "session-arch-a",
        "session-arch-old",
    ]
