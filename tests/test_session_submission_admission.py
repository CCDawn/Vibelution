from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.chat.conversation_ledger import (
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.schema import MIGRATIONS, SCHEMA_VERSION
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


def test_v1_store_upgrades_to_directory_control_plane_without_creating_transcript_rows(
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
        assert store.open()["schemaVersion"] == SCHEMA_VERSION
        assert store.database.metadata()["schemaVersion"] == SCHEMA_VERSION
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
                "workspace_chat_state",
            }.issubset(tables)
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(sessions)")
            }
            assert {"last_preview", "session_kind", "hidden_from_index"}.issubset(columns)
            assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 0
    finally:
        store.close()


def test_journal_admission_retry_writes_one_turn_start_and_one_user_message(
    tmp_path: Path,
):
    store = _open_store(tmp_path)
    try:
        revision = _create_bound_session(store)
        admission = SessionSubmissionAdmissionService(store.repository)

        def lookup(record: dict[str, object]) -> dict[str, object] | None:
            matching = [
                event
                for event in load_conversation_events(tmp_path, "session-a")
                if event.correlation_id == record["clientSubmissionId"]
                and event.event_type == EVENT_USER_MESSAGE
            ]
            if not matching:
                return None
            final_event = matching[-1]
            return {
                "journalSequence": final_event.sequence,
                "journalEventId": final_event.event_id,
            }

        def append_initial_events(record: dict[str, object]) -> dict[str, object]:
            correlation_id = str(record["clientSubmissionId"])
            turn_id = str(record["turnId"])
            append_conversation_event(
                tmp_path,
                "session-a",
                turn_id,
                EVENT_TURN_STARTED,
                status="running",
                correlation_id=correlation_id,
                visible_in_model=False,
            )
            user_event = append_conversation_event(
                tmp_path,
                "session-a",
                turn_id,
                EVENT_USER_MESSAGE,
                status="recorded",
                correlation_id=correlation_id,
                payload={"content": "hello"},
            )
            return {
                "journalSequence": user_event.sequence,
                "journalEventId": user_event.event_id,
            }

        first = admission.admit_to_journal(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
            turn_id="turn-a",
            journal_lookup=lookup,
            journal_append=append_initial_events,
        )
        retried = admission.admit_to_journal(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
            turn_id="turn-retry-must-not-replace-a",
            journal_lookup=lookup,
            journal_append=append_initial_events,
        )

        events = load_conversation_events(tmp_path, "session-a")
        assert first["journalDisposition"] == "appended"
        assert retried["journalDisposition"] == "already_journaled"
        assert [event.event_type for event in events] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
        assert first["turnId"] == retried["turnId"] == "turn-a"
        assert retried["state"] == "journaled"
    finally:
        store.close()


def test_concurrent_journal_admission_uses_one_append_callback(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        revision = _create_bound_session(store)
        admission = SessionSubmissionAdmissionService(store.repository)
        append_calls = 0

        def lookup(_record: dict[str, object]) -> dict[str, object] | None:
            return None

        def append(_record: dict[str, object]) -> dict[str, object]:
            nonlocal append_calls
            append_calls += 1
            return {"journalSequence": 1, "journalEventId": "event-a"}

        def admit(index: int) -> dict[str, object]:
            return admission.admit_to_journal(
                session_id="session-a",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                client_submission_id="submission-a",
                turn_id=f"turn-{index}",
                journal_lookup=lookup,
                journal_append=append,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(admit, range(16)))

        assert append_calls == 1
        assert {str(result["turnId"]) for result in results} == {"turn-0"}
        assert {str(result["state"]) for result in results} == {"journaled"}
    finally:
        store.close()


def test_journal_success_before_sqlite_ack_recovers_without_second_user_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = _open_store(tmp_path)
    try:
        revision = _create_bound_session(store)
        admission = SessionSubmissionAdmissionService(store.repository)
        append_calls = 0

        def lookup(record: dict[str, object]) -> dict[str, object] | None:
            matching = [
                event
                for event in load_conversation_events(tmp_path, "session-a")
                if event.correlation_id == record["clientSubmissionId"]
                and event.event_type == EVENT_USER_MESSAGE
            ]
            if not matching:
                return None
            event = matching[-1]
            return {
                "journalSequence": event.sequence,
                "journalEventId": event.event_id,
            }

        def append(record: dict[str, object]) -> dict[str, object]:
            nonlocal append_calls
            append_calls += 1
            correlation_id = str(record["clientSubmissionId"])
            turn_id = str(record["turnId"])
            append_conversation_event(
                tmp_path,
                "session-a",
                turn_id,
                EVENT_TURN_STARTED,
                status="running",
                correlation_id=correlation_id,
                visible_in_model=False,
            )
            event = append_conversation_event(
                tmp_path,
                "session-a",
                turn_id,
                EVENT_USER_MESSAGE,
                status="recorded",
                correlation_id=correlation_id,
                payload={"content": "recover me"},
            )
            return {
                "journalSequence": event.sequence,
                "journalEventId": event.event_id,
            }

        real_mark_journaled = admission.mark_journaled
        monkeypatch.setattr(
            admission,
            "mark_journaled",
            lambda **_values: (_ for _ in ()).throw(RuntimeError("simulated crash")),
        )
        with pytest.raises(RuntimeError, match="simulated crash"):
            admission.admit_to_journal(
                session_id="session-a",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                client_submission_id="submission-recover",
                turn_id="turn-recover",
                journal_lookup=lookup,
                journal_append=append,
            )

        monkeypatch.setattr(admission, "mark_journaled", real_mark_journaled)
        recovered = admission.admit_to_journal(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-recover",
            turn_id="turn-retry-must-not-replace-recover",
            journal_lookup=lookup,
            journal_append=append,
        )

        assert append_calls == 1
        assert recovered["journalDisposition"] == "recovered"
        assert recovered["state"] == "journaled"
        assert [event.event_type for event in load_conversation_events(tmp_path, "session-a")] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
    finally:
        store.close()


def test_development_runtime_refuses_the_formal_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from core.web.services.session import admission

    project_root = tmp_path / "project"
    monkeypatch.setenv("VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT", str(project_root))

    with pytest.raises(admission.DevelopmentSubmissionAdmissionConfigurationError):
        admission.get_development_submission_admission_runtime(project_root)


def test_development_runtime_admits_one_journal_backed_submission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from core.web.services.session import admission

    project_root = tmp_path / "project"
    development_root = tmp_path / "development-data"
    monkeypatch.setenv("VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT", str(development_root))
    runtime = admission.get_development_submission_admission_runtime(project_root)
    assert runtime is not None

    def journal_lookup(record: dict[str, object]) -> dict[str, object] | None:
        for event in load_conversation_events(project_root, str(record["sessionId"])):
            if event.event_type != EVENT_USER_MESSAGE:
                continue
            metadata = dict((event.payload or {}).get("metadata") or {})
            if metadata.get("clientSubmissionId") == record["clientSubmissionId"]:
                return {
                    "journalSequence": event.sequence,
                    "journalEventId": event.event_id,
                }
        return None

    def journal_append(record: dict[str, object]) -> dict[str, object]:
        append_conversation_event(
            project_root,
            str(record["sessionId"]),
            str(record["turnId"]),
            EVENT_TURN_STARTED,
            status="running",
            correlation_id=str(record["clientSubmissionId"]),
            visible_in_model=False,
        )
        event = append_conversation_event(
            project_root,
            str(record["sessionId"]),
            str(record["turnId"]),
            EVENT_USER_MESSAGE,
            status="recorded",
            correlation_id=str(record["clientSubmissionId"]),
            payload={
                "content": "development submission",
                "metadata": {"clientSubmissionId": record["clientSubmissionId"]},
            },
        )
        return {"journalSequence": event.sequence, "journalEventId": event.event_id}

    try:
        first = runtime.admit(
            session_id="session-development",
            agent={"agentId": "agent-development", "displayName": "Development Agent"},
            conversation={"title": "Development conversation"},
            client_submission_id="submission-development",
            turn_id="turn-development",
            journal_lookup=journal_lookup,
            journal_append=journal_append,
        )
        second = runtime.admit(
            session_id="session-development",
            agent={"agentId": "agent-development", "displayName": "Development Agent"},
            conversation={"title": "Development conversation"},
            client_submission_id="submission-development",
            turn_id="turn-new-must-not-replace",
            journal_lookup=journal_lookup,
            journal_append=journal_append,
        )

        assert first["journalDisposition"] == "appended"
        assert second["journalDisposition"] == "already_journaled"
        assert second["turnId"] == "turn-development"
        assert [event.event_type for event in load_conversation_events(project_root, "session-development")] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
        assert (development_root / "conversation-control" / "session_admission.sqlite3").is_file()
    finally:
        admission.close_development_submission_admission_runtimes()
