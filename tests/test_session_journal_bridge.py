"""Focused tests for session journal_bridge slice."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.chat.conversation_ledger import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    latest_ledger_sequence,
)
from core.chat.session_catalog import (
    set_session_catalog_dirty_observer,
)
from core.web.services.session import journal_bridge


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


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


def test_journal_bridge_notifies_catalog_after_successful_append(tmp_path: Path) -> None:
    observed: list[tuple[Path, str, str]] = []
    set_session_catalog_dirty_observer(
        lambda project_root, session_id, source_revision: observed.append(
            (project_root, session_id, source_revision)
        )
    )
    try:
        journal_bridge.append_session_conversation_event(
            "journal-dirty-session",
            "turn-a",
            EVENT_TURN_STARTED,
            status="running",
            payload={},
            source="test",
            project_root=tmp_path,
        )
    finally:
        set_session_catalog_dirty_observer(None)

    assert observed == [(tmp_path, "journal-dirty-session", "journal:1")]


def test_journal_bridge_logs_only_terminal_commit(tmp_path: Path, monkeypatch) -> None:
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []
    counters = iter((10.0, 20.0, 20.25))
    monkeypatch.setattr(journal_bridge, "_perf_counter", lambda: next(counters))
    monkeypatch.setattr(
        journal_bridge,
        "record_runtime_scene_event",
        lambda *args, **kwargs: observed.append((args, kwargs)),
    )

    journal_bridge.append_session_conversation_event(
        "journal-terminal-session",
        "turn-a",
        EVENT_TURN_STARTED,
        status="running",
        payload={},
        source="test",
        project_root=tmp_path,
    )
    terminal_event = journal_bridge.append_session_conversation_event(
        "journal-terminal-session",
        "turn-a",
        EVENT_TURN_COMPLETED,
        status="completed",
        payload={"content": "must not enter diagnostics"},
        source="test",
        project_root=tmp_path,
    )

    assert len(observed) == 1
    args, kwargs = observed[0]
    assert args == (
        "conversation",
        "conversation_ledger",
        "conversation.ledger.terminal_committed",
    )
    assert kwargs["outcome"] == "completed"
    assert kwargs["fields"] == {
        "sessionId": "journal-terminal-session",
        "turnId": "turn-a",
        "eventType": EVENT_TURN_COMPLETED,
        "status": "completed",
        "sequence": terminal_event.sequence,
        "eventId": terminal_event.event_id,
        "durationMs": 250.0,
        "durability": "fsync",
    }
    assert "must not enter diagnostics" not in repr(observed)


def test_journal_bridge_append_failure_redacts_exception_message(tmp_path: Path, monkeypatch) -> None:
    secret = "secret-token-must-not-be-logged"
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []
    counters = iter((30.0, 30.125))

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(journal_bridge, "_perf_counter", lambda: next(counters))
    monkeypatch.setattr(
        journal_bridge,
        "append_conversation_event",
        fail_append,
    )
    monkeypatch.setattr(
        journal_bridge,
        "record_runtime_scene_event",
        lambda *args, **kwargs: observed.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="secret-token"):
        journal_bridge.append_session_conversation_event(
            "journal-failed-session",
            "turn-f",
            EVENT_TURN_COMPLETED,
            status="failed",
            payload={"content": "also private"},
            source="test",
            project_root=tmp_path,
        )

    assert len(observed) == 1
    args, kwargs = observed[0]
    assert args == (
        "conversation",
        "conversation_ledger",
        "conversation.ledger.append_failed",
    )
    assert kwargs["fields"] == {
        "sessionId": "journal-failed-session",
        "turnId": "turn-f",
        "eventType": EVENT_TURN_COMPLETED,
        "errorType": "RuntimeError",
        "errorMessageLength": len(secret),
        "durationMs": 125.0,
    }
    assert secret not in repr(observed)
    assert "also private" not in repr(observed)


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
