"""Focused tests for session journal_bridge slice."""

from __future__ import annotations

from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    latest_ledger_sequence,
)
from core.web.services.session import journal_bridge


def test_journal_bridge_cache_hit_invalidate_and_project_root(tmp_path: Path) -> None:
    session_id = "journal-cache-session"
    journal_bridge.invalidate_session_conversation_events_cache(session_id)

    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_TURN_STARTED,
        status="running",
        payload={},
        source="test",
    )
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_USER_MESSAGE,
        status="ok",
        payload={"content": "hello"},
        source="test",
    )

    first = journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=tmp_path,
    )
    assert len(first) == 2
    second = journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=tmp_path,
    )
    assert len(second) == 2
    # defensive list copies
    second.append("mutated")
    third = journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=tmp_path,
    )
    assert len(third) == 2

    journal_bridge.invalidate_session_conversation_events_cache(session_id)
    # After invalidate, re-load still works against the same tmp root.
    reloaded = journal_bridge.load_session_conversation_events_snapshot(
        session_id,
        project_root=tmp_path,
    )
    assert len(reloaded) == 2
    assert journal_bridge.session_ledger_sequence(session_id, project_root=tmp_path) == latest_ledger_sequence(
        tmp_path, session_id
    )


def test_journal_bridge_append_invalidates_cache(tmp_path: Path) -> None:
    session_id = "journal-append-session"
    journal_bridge.invalidate_session_conversation_events_cache(session_id)

    journal_bridge.append_session_conversation_event(
        session_id,
        "turn-a",
        EVENT_TURN_STARTED,
        status="running",
        payload={},
        source="test",
        project_root=tmp_path,
    )
    events = journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=tmp_path,
    )
    assert len(events) == 1

    journal_bridge.append_session_conversation_event(
        session_id,
        "turn-a",
        EVENT_USER_MESSAGE,
        status="ok",
        payload={"content": "next"},
        source="test",
        project_root=tmp_path,
    )
    events_after = journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=tmp_path,
    )
    assert len(events_after) == 2


def test_facade_forwards_monkeypatched_project_root(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import session_service

    session_id = "facade-root-session"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._invalidate_session_conversation_events_cache(session_id)

    session_service._append_session_conversation_event(
        session_id,
        "turn-f",
        EVENT_TURN_STARTED,
        status="running",
        payload={},
        source="test",
    )
    events = session_service._load_session_conversation_events_cached(session_id)
    assert len(events) == 1
    assert session_service._session_ledger_sequence(session_id) >= 1
    snapshot = session_service.load_session_conversation_events_snapshot(session_id)
    assert len(snapshot) == 1
