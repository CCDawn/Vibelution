from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.schema import MIGRATIONS
from core.web.services.session.admission import SessionSubmissionAdmissionService


def _open_store(tmp_path: Path) -> ConversationStore:
    store = ConversationStore(tmp_path / "workspace" / "chat" / "conversations.sqlite3")
    store.open()
    return store


def _create_bound_session(store: ConversationStore) -> str:
    revision = store.repository.create_agent(
        agent_id="agent-a",
        display_name="Agent A",
        kind="assistant",
        config={"modelId": "gpt-5.6-luna"},
        source="test",
    ).result(timeout=3)["configRevisionId"]
    store.repository.create_session(
        session_id="session-a",
        agent_id="agent-a",
        agent_config_revision_id=revision,
        title="Session A",
    ).result(timeout=3)
    return str(revision)


def test_submission_reservation_is_idempotent_and_does_not_write_transcript_rows(
    tmp_path: Path,
):
    store = _open_store(tmp_path)
    try:
        revision = _create_bound_session(store)
        admission = SessionSubmissionAdmissionService(store.repository)

        first = admission.reserve(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
            turn_id="turn-a",
        )
        retried = admission.reserve(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
            turn_id="turn-retry-must-not-replace-a",
        )

        assert first["outcome"] == "reserved"
        assert retried["outcome"] == "reused"
        assert retried["turnId"] == "turn-a"
        assert store.repository.get_submission_admission(
            session_id="session-a", client_submission_id="submission-a"
        )["state"] == "reserved"
        with sqlite3.connect(store.database.path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 0
    finally:
        store.close()


def test_only_journaled_admission_can_advance_to_projection_offset(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        revision = _create_bound_session(store)
        admission = SessionSubmissionAdmissionService(store.repository)
        admission.reserve(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
            turn_id="turn-a",
        )

        with pytest.raises(ValueError, match="journaled"):
            admission.mark_projected(
                session_id="session-a",
                client_submission_id="submission-a",
                journal_sequence=2,
            )

        journaled = admission.mark_journaled(
            session_id="session-a",
            client_submission_id="submission-a",
            journal_sequence=1,
            journal_event_id="event-user-a",
        )
        projected = admission.mark_projected(
            session_id="session-a",
            client_submission_id="submission-a",
            journal_sequence=2,
        )

        assert journaled["state"] == "journaled"
        assert projected["state"] == "projected"
        assert store.repository.get_session_projection_offset("session-a") == 2
    finally:
        store.close()


def test_repository_has_no_transcript_write_or_read_facade(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        for forbidden_name in (
            "begin_turn",
            "upsert_turn_item",
            "list_turns",
            "list_turn_items",
        ):
            assert not hasattr(store.repository, forbidden_name)
    finally:
        store.close()


def test_v1_store_upgrades_to_control_plane_v2_without_creating_transcript_rows(
    tmp_path: Path,
):
    database_path = tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    database_path.parent.mkdir(parents=True)
    v1 = MIGRATIONS[0]
    with sqlite3.connect(database_path) as connection:
        for statement in v1.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at_ms, checksum) VALUES (1, 1, ?)",
            (v1.checksum,),
        )
        connection.execute(
            "INSERT INTO conversation_store_meta(id, schema_version, created_at_ms, updated_at_ms) "
            "VALUES (1, 1, 1, 1)"
        )
        connection.execute("PRAGMA user_version=1")

    store = ConversationStore(database_path)
    try:
        assert store.open()["schemaVersion"] == 2
        assert store.database.metadata()["schemaVersion"] == 2
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {
                "session_edges",
                "session_admissions",
                "session_projection_offsets",
            }.issubset(tables)
            assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 0
    finally:
        store.close()
