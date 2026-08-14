from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.chat.conversation_store.database as conversation_database
import core.chat.conversation_store.runtime as conversation_sqlite_runtime
import core.chat.conversation_store.schema as conversation_schema
from core.chat.conversation_store import (
    ConversationBackpressureError,
    ConversationStore,
    ConversationStoreLockedError,
    ConversationStoreUnavailableError,
    LAST_PREVIEW_MAX_CHARS,
    LegacyChatStateImporter,
    ChatStateImportError,
    assess_sqlite_wal_runtime,
    parse_directory_cursor,
)


@pytest.fixture
def safe_sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_database.sqlite3,
        "sqlite_version_info",
        (3, 51, 3),
    )


def _open_store(
    tmp_path: Path,
    *,
    queue_capacity: int = 64,
    max_batch_size: int = 16,
    max_batch_delay_ms: int = 5,
    busy_timeout_ms: int = 250,
    read_pool_capacity: int = 4,
) -> ConversationStore:
    store = ConversationStore(
        tmp_path / "workspace" / "chat" / "conversations.sqlite3",
        queue_capacity=queue_capacity,
        max_batch_size=max_batch_size,
        max_batch_delay_ms=max_batch_delay_ms,
        busy_timeout_ms=busy_timeout_ms,
        read_pool_capacity=read_pool_capacity,
    )
    store.open()
    return store


def _create_agent(store: ConversationStore, agent_id: str = "agent-a") -> str:
    result = store.repository.create_agent(
        agent_id=agent_id,
        display_name=f"Agent {agent_id}",
        kind="assistant",
        config={"modelId": "gpt-5.6-luna", "tools": ["read_file"]},
        source="test",
    ).result(timeout=3)
    return str(result["configRevisionId"])


def test_chat_state_roundtrip_preserves_order_and_separates_debug_snapshots(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        result = store.repository.replace_chat_state(
            {
                "version": 1,
                "active_conversation_id": "session-b",
                "updated_at": "2026-08-14T01:02:03Z",
                "custom": {"kept": True},
                "conversations": [
                    {
                        "conversation_id": "session-b",
                        "title": "Second alphabetically, first by position",
                        "experimentBinding": {"teamId": "team-1"},
                        "last_llm_payload_trace": {"large": "trace"},
                    },
                    {
                        "conversation_id": "session-a",
                        "title": "First alphabetically, second by position",
                        "agentPromptSnapshot": {"prompt": "snapshot"},
                    },
                ],
            }
        ).result(timeout=3)

        assert result["stateRevision"] == 1
        restored = store.repository.get_chat_state()
        assert [item["conversation_id"] for item in restored["conversations"]] == [
            "session-b",
            "session-a",
        ]
        assert restored["custom"] == {"kept": True}
        assert restored["conversations"][0]["last_llm_payload_trace"] == {"large": "trace"}
        assert restored["conversations"][1]["agentPromptSnapshot"] == {"prompt": "snapshot"}
        active_id, bindings = store.repository.get_chat_state_directory_overlay()
        assert active_id == "session-b"
        assert bindings == {"session-b": {"teamId": "team-1"}}
    finally:
        store.close()

    connection = sqlite3.connect(tmp_path / "workspace" / "chat" / "conversations.sqlite3")
    try:
        runtime_payloads = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM session_runtime_state ORDER BY position"
            ).fetchall()
        ]
        debug_payloads = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM session_debug_snapshots ORDER BY session_id"
            ).fetchall()
        ]
    finally:
        connection.close()
    assert all("last_llm_payload_trace" not in item for item in runtime_payloads)
    assert all("agentPromptSnapshot" not in item for item in runtime_payloads)
    assert debug_payloads == [
        {"agentPromptSnapshot": {"prompt": "snapshot"}},
        {"last_llm_payload_trace": {"large": "trace"}},
    ]


def test_chat_state_invalid_replace_rolls_back_to_previous_document(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        store.repository.replace_chat_state(
            {"version": 1, "conversations": [{"conversation_id": "kept"}]}
        ).result(timeout=3)
        before = store.repository.get_chat_state()

        with pytest.raises(ValueError, match="duplicate conversation id"):
            store.repository.replace_chat_state(
                {
                    "version": 1,
                    "conversations": [
                        {"conversation_id": "duplicate"},
                        {"conversation_id": "duplicate"},
                    ],
                }
            ).result(timeout=3)

        assert store.repository.get_chat_state() == before
    finally:
        store.close()


def test_legacy_chat_state_import_is_backed_up_and_idempotent(tmp_path: Path):
    store = _open_store(tmp_path)
    source = tmp_path / "chat_state.json"
    source_bytes = json.dumps(
        {
            "version": 1,
            "active_conversation_id": "legacy",
            "conversations": [{"conversation_id": "legacy", "messages": []}],
        }
    ).encode("utf-8")
    source.write_bytes(source_bytes)
    try:
        importer = LegacyChatStateImporter(store.repository)
        first = importer.import_file(source, project_root=tmp_path)
        second = importer.import_file(source, project_root=tmp_path)

        assert first["action"] == "imported"
        assert Path(first["backupPath"]).read_bytes() == source_bytes
        assert second == {"action": "reused", "conversationCount": 1, "backupPath": ""}
        assert source.read_bytes() == source_bytes
        assert len(list(tmp_path.glob("chat_state.json.pre-sqlite.*.bak.json"))) == 1
        assert store.repository.get_chat_state()["conversations"] == [
            {"conversation_id": "legacy"}
        ]
    finally:
        store.close()


def test_invalid_legacy_chat_state_does_not_create_sqlite_root_or_backup(tmp_path: Path):
    store = _open_store(tmp_path)
    source = tmp_path / "chat_state.json"
    source.write_text('{"version": 1,', encoding="utf-8")
    try:
        with pytest.raises(ChatStateImportError, match="valid UTF-8 JSON"):
            LegacyChatStateImporter(store.repository).import_file(source, project_root=tmp_path)
        assert store.repository.get_chat_state() == {}
        assert not list(tmp_path.glob("chat_state.json.pre-sqlite.*.bak.json"))
        assert source.read_text(encoding="utf-8") == '{"version": 1,'
    finally:
        store.close()


def test_existing_schema_v3_store_migrates_to_chat_state_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_path = tmp_path / "conversations.sqlite3"
    with monkeypatch.context() as migration_patch:
        migration_patch.setattr(
            conversation_database,
            "MIGRATIONS",
            conversation_schema.MIGRATIONS[:3],
        )
        migration_patch.setattr(conversation_database, "SCHEMA_VERSION", 3)
        v3_store = ConversationStore(database_path)
        try:
            assert v3_store.open()["schemaVersion"] == 3
        finally:
            v3_store.close()

    migrated = ConversationStore(database_path)
    try:
        metadata = migrated.open()
        assert metadata["schemaVersion"] == 4
        assert migrated.repository.get_chat_state() == {}
        migrated.repository.replace_chat_state(
            {"version": 1, "conversations": [{"conversation_id": "after-upgrade"}]}
        ).result(timeout=3)
        assert migrated.repository.get_chat_state()["conversations"] == [
            {"conversation_id": "after-upgrade"}
        ]
    finally:
        migrated.close()


def test_project_local_sqlite_runtime_is_used_without_version_spoofing(
    tmp_path: Path,
):
    assert conversation_sqlite_runtime.DRIVER_NAME == "apsw"
    assert conversation_sqlite_runtime.sqlite_version_info >= (3, 51, 3)

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    try:
        metadata = store.open()
        assert metadata["sqliteDriver"] == "apsw"
        assert metadata["sqliteVersion"] == conversation_sqlite_runtime.sqlite_version
    finally:
        store.close()


def test_sqlite_runtime_gate_rejects_known_wal_reset_race_versions(tmp_path: Path):
    unsafe = assess_sqlite_wal_runtime((3, 49, 1))
    patched_backport = assess_sqlite_wal_runtime((3, 50, 7))
    fixed = assess_sqlite_wal_runtime((3, 51, 3))

    assert unsafe.safe is False
    assert unsafe.code == "wal_reset_race"
    assert patched_backport.safe is True
    assert fixed.safe is True

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            conversation_database.sqlite3,
            "sqlite_version_info",
            (3, 49, 1),
        )
        with pytest.raises(ConversationStoreUnavailableError, match="3.51.3"):
            store.open()


def test_initialize_creates_canonical_schema_and_query_only_readers(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        metadata = store.database.metadata()
        with sqlite3.connect(store.database.path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()

        assert metadata["schemaVersion"] == 4
        assert metadata["quickCheck"] == "ok"
        assert {
            "agents",
            "agent_config_revisions",
            "sessions",
            "turns",
            "turn_items",
            "turn_item_chunks",
            "checkpoints",
            "session_edges",
            "session_admissions",
            "session_projection_offsets",
            "workspace_chat_state",
            "session_runtime_state",
            "session_debug_snapshots",
        }.issubset(tables)
        assert foreign_keys == []

        with store.database.reader() as reader:
            assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                reader.execute(
                    "INSERT INTO agents(agent_id, display_name, kind, status, created_at_ms, updated_at_ms) "
                    "VALUES ('forbidden', 'Forbidden', 'assistant', 'active', 1, 1)"
                )
    finally:
        store.close()


def test_bounded_reader_admission_preserves_availability_and_reports_pressure(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(
        tmp_path,
        busy_timeout_ms=20,
        read_pool_capacity=1,
    )
    reader_entered = threading.Event()
    release_reader = threading.Event()

    def hold_reader() -> None:
        with store.database.reader() as reader:
            assert reader.execute("SELECT 1").fetchone()[0] == 1
            reader_entered.set()
            assert release_reader.wait(timeout=3)

    thread = threading.Thread(target=hold_reader, name="conversation-test-reader")
    thread.start()
    try:
        assert reader_entered.wait(timeout=1)
        with store.database.reader() as reader:
            assert reader.execute("SELECT 1").fetchone()[0] == 1
        release_reader.set()
        thread.join(timeout=3)
        assert not thread.is_alive()

        with store.database.reader() as reader:
            assert reader.execute("SELECT 1").fetchone()[0] == 1

        metrics = store.database.reader_metrics()
        assert metrics["activeReaders"] == 0
        assert metrics["maxPooledReaders"] == 1
        assert metrics["overflowReaders"] == 1
    finally:
        release_reader.set()
        thread.join(timeout=3)
        store.close()


def test_query_only_reader_pool_reuses_idle_connection(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, read_pool_capacity=1)
    try:
        with store.database.reader() as reader:
            assert reader.execute("SELECT 1").fetchone()[0] == 1
        with store.database.reader() as reader:
            assert reader.execute("SELECT 1").fetchone()[0] == 1

        metrics = store.database.reader_metrics()
        assert metrics["pooledConnectionOpens"] == 1
        assert metrics["reusedPooledReaderLeases"] == 1
        assert metrics["idlePooledReaders"] == 1
    finally:
        store.close()


def test_query_only_reader_pool_never_crosses_thread_connection_ownership(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, read_pool_capacity=2)
    first_released = threading.Event()
    release_first_thread = threading.Event()
    connection_ids: list[int] = []

    def first_thread() -> None:
        with store.database.reader() as reader:
            connection_ids.append(id(reader))
        first_released.set()
        assert release_first_thread.wait(timeout=3)

    def second_thread() -> None:
        assert first_released.wait(timeout=3)
        with store.database.reader() as reader:
            connection_ids.append(id(reader))

    first = threading.Thread(target=first_thread, name="conversation-reader-owner-a")
    second = threading.Thread(target=second_thread, name="conversation-reader-owner-b")
    first.start()
    second.start()
    try:
        assert first_released.wait(timeout=1)
        second.join(timeout=3)
        assert not second.is_alive()
        assert len(connection_ids) == 2
        assert connection_ids[0] != connection_ids[1]
        assert store.database.reader_metrics()["overflowReaders"] == 0
    finally:
        release_first_thread.set()
        first.join(timeout=3)
        second.join(timeout=3)
        store.close()


def test_store_close_retires_the_current_thread_reader_lease(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, read_pool_capacity=1)
    with store.database.reader() as reader:
        assert reader.execute("SELECT 1").fetchone()[0] == 1

    assert store.database.reader_metrics()["cachedPooledReaders"] == 1
    store.close()
    assert store.database.reader_metrics()["cachedPooledReaders"] == 0
    with (
        pytest.raises(ConversationStoreUnavailableError, match="pool is closed"),
        store.database.reader(),
    ):
        pass


def test_agent_revision_and_parent_session_binding_are_enforced(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        revision_a = _create_agent(store, "agent-a")
        revision_b = _create_agent(store, "agent-b")
        store.repository.create_session(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision_a,
            title="Agent A root",
        ).result(timeout=3)
        store.repository.create_session(
            session_id="session-a-child",
            agent_id="agent-a",
            agent_config_revision_id=revision_a,
            parent_session_id="session-a",
            title="Agent A child",
        ).result(timeout=3)

        cross_agent = store.repository.create_session(
            session_id="session-b-child",
            agent_id="agent-b",
            agent_config_revision_id=revision_b,
            parent_session_id="session-a",
            title="Invalid cross-agent child",
        )

        with pytest.raises(sqlite3.IntegrityError):
            cross_agent.result(timeout=3)

        sessions = store.repository.list_sessions(agent_id="agent-a")
        assert [row["sessionId"] for row in sessions] == [
            "session-a-child",
            "session-a",
        ]
        with sqlite3.connect(store.database.path) as connection:
            assert connection.execute(
                "SELECT source_session_id, target_session_id, relation_kind "
                "FROM session_edges"
            ).fetchall() == [("session-a", "session-a-child", "parent")]
    finally:
        store.close()


def test_submission_admission_keeps_one_stable_control_record(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store)
        store.repository.create_session(
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Session A",
        ).result(timeout=3)
        first = store.repository.reserve_submission_admission(
            turn_id="turn-a",
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
        ).result(timeout=3)
        retried = store.repository.reserve_submission_admission(
            turn_id="turn-must-not-replace-a",
            session_id="session-a",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-a",
        ).result(timeout=3)

        assert first["outcome"] == "reserved"
        assert retried["outcome"] == "reused"
        assert retried["turnId"] == "turn-a"
        assert store.repository.get_submission_admission(
            session_id="session-a", client_submission_id="submission-a"
        )["state"] == "reserved"
    finally:
        store.close()


def test_writer_batches_mutations_and_runs_callbacks_only_after_commit(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, max_batch_size=32, max_batch_delay_ms=30)
    observed_after_commit: list[bool] = []
    try:
        futures = []
        for index in range(12):
            agent_id = f"agent-{index:02d}"

            def mutation(unit_of_work, *, agent_id=agent_id):
                result = unit_of_work.agents.create(
                    agent_id=agent_id,
                    display_name=agent_id,
                    kind="assistant",
                    config={"modelId": "test-model"},
                    source="test",
                )
                unit_of_work.after_commit(
                    lambda agent_id=agent_id: observed_after_commit.append(
                        store.repository.get_agent(agent_id) is not None
                    )
                )
                return result

            futures.append(store.writer.submit(mutation))

        for future in futures:
            future.result(timeout=3)

        metrics = store.writer.metrics()
        assert observed_after_commit == [True] * 12
        assert metrics["committedMutations"] == 12
        assert metrics["maxBatchSize"] >= 2
        assert metrics["queueWaitMsP95"] >= 0
    finally:
        store.close()


def test_passive_wal_checkpoint_runs_through_the_writer_actor(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        _create_agent(store)

        checkpoint = store.checkpoint_wal_passive(timeout=3)
        writer_metrics = store.writer.metrics()

        assert checkpoint["mode"] == "passive"
        assert checkpoint["busy"] in {0, 1}
        assert checkpoint["logPages"] >= 0
        assert checkpoint["checkpointedPages"] >= 0
        assert checkpoint["walBytes"] >= 0
        assert checkpoint["durationMs"] >= 0
        assert writer_metrics["maintenanceRuns"] == 1
        assert writer_metrics["failedMaintenanceRuns"] == 0
    finally:
        store.close()


def test_writer_runs_maintenance_between_queued_mutation_batches(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, max_batch_size=1, max_batch_delay_ms=0)
    entered_first = threading.Event()
    release_first = threading.Event()
    order: list[str] = []

    def first_mutation(_unit_of_work):
        entered_first.set()
        assert release_first.wait(timeout=3)
        order.append("first")
        return "first"

    try:
        first = store.writer.submit(first_mutation)
        assert entered_first.wait(timeout=1)
        maintenance = store.writer.submit_maintenance(
            lambda _connection: order.append("maintenance")
        )
        second = store.writer.submit(
            lambda _unit_of_work: order.append("second")
        )

        release_first.set()
        assert first.result(timeout=3) == "first"
        assert maintenance.result(timeout=3) is None
        assert second.result(timeout=3) is None
        assert order == ["first", "maintenance", "second"]
    finally:
        release_first.set()
        store.close()


def test_failed_maintenance_does_not_stop_the_single_writer_actor(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        failed = store.writer.submit_maintenance(
            lambda _connection: (_ for _ in ()).throw(RuntimeError("planned fault"))
        )
        with pytest.raises(RuntimeError, match="planned fault"):
            failed.result(timeout=3)

        revision = _create_agent(store)
        assert revision
        metrics = store.writer.metrics()
        assert metrics["maintenanceRuns"] == 1
        assert metrics["failedMaintenanceRuns"] == 1
        assert metrics["failedMutations"] == 0
    finally:
        store.close()


def test_drained_store_reopens_with_agent_session_and_admission_data(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    database_path = tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    store = ConversationStore(database_path)
    store.open()
    try:
        revision = _create_agent(store)
        store.repository.create_session(
            session_id="session-reopen",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Reopen session",
        ).result(timeout=3)
        store.repository.reserve_submission_admission(
            turn_id="turn-reopen",
            session_id="session-reopen",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            client_submission_id="submission-reopen",
        ).result(timeout=3)
        assert store.checkpoint_wal_passive(timeout=3)["mode"] == "passive"
        store.writer.flush(timeout=3)
    finally:
        store.close()

    reopened = ConversationStore(database_path)
    reopened.open()
    try:
        assert reopened.database.metadata()["quickCheck"] == "ok"
        assert reopened.repository.get_agent("agent-a") is not None
        assert [row["sessionId"] for row in reopened.repository.list_sessions(agent_id="agent-a")] == [
            "session-reopen"
        ]
        admission = reopened.repository.get_submission_admission(
            session_id="session-reopen",
            client_submission_id="submission-reopen",
        )
        assert admission is not None
        assert admission["turnId"] == "turn-reopen"
    finally:
        reopened.close()


def test_committed_wal_data_reopens_after_writer_process_exits_abruptly(
    tmp_path: Path,
):
    database_path = tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    crash_writer = f"""
import os
from pathlib import Path
from core.chat.conversation_store import ConversationStore

store = ConversationStore(Path({str(database_path)!r}))
store.open()
revision = store.repository.create_agent(
    agent_id='agent-crash',
    display_name='Crash Agent',
    kind='assistant',
    config={{'modelId': 'gpt-5.6-luna'}},
    source='crash-test',
).result(timeout=5)['configRevisionId']
store.repository.create_session(
    session_id='session-crash',
    agent_id='agent-crash',
    agent_config_revision_id=revision,
    title='Committed before abrupt exit',
).result(timeout=5)
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", crash_writer],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    reopened = ConversationStore(database_path)
    reopened.open()
    try:
        assert reopened.database.metadata()["quickCheck"] == "ok"
        assert reopened.repository.get_agent("agent-crash") is not None
        assert [row["sessionId"] for row in reopened.repository.list_sessions(agent_id="agent-crash")] == [
            "session-crash"
        ]
    finally:
        reopened.close()


def test_bounded_writer_queue_rejects_excess_work(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(
        tmp_path,
        queue_capacity=1,
        max_batch_size=1,
        max_batch_delay_ms=0,
    )
    entered = threading.Event()
    release = threading.Event()

    def blocking_mutation(_unit_of_work):
        entered.set()
        assert release.wait(timeout=3)
        return "released"

    try:
        first = store.writer.submit(blocking_mutation)
        assert entered.wait(timeout=1)
        second = store.writer.submit(lambda _unit_of_work: "queued")
        with pytest.raises(ConversationBackpressureError):
            store.writer.submit(lambda _unit_of_work: "rejected", timeout=0)
        release.set()
        assert first.result(timeout=3) == "released"
        assert second.result(timeout=3) == "queued"
    finally:
        release.set()
        store.close()


def test_external_write_lock_is_diagnostic_and_writer_recovers(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path, busy_timeout_ms=20)
    external_writer = conversation_sqlite_runtime.connect(
        str(store.database.path),
        timeout=0.02,
        isolation_level=None,
    )
    try:
        external_writer.execute("BEGIN IMMEDIATE")
        blocked = store.repository.create_agent(
            agent_id="agent-locked",
            display_name="Locked Agent",
            kind="assistant",
            config={"modelId": "gpt-5.6-luna"},
            source="lock-test",
        )
        with pytest.raises(ConversationStoreLockedError, match="bounded lock wait"):
            blocked.result(timeout=3)

        external_writer.rollback()
        assert _create_agent(store, "agent-after-lock")
        assert store.writer.metrics()["failedMutations"] == 1
    finally:
        try:
            external_writer.rollback()
        except sqlite3.Error:
            pass
        external_writer.close()
        store.close()


def test_32_sessions_concurrent_admissions_do_not_deadlock_or_lose_records(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(
        tmp_path,
        queue_capacity=512,
        max_batch_size=32,
        max_batch_delay_ms=5,
    )
    try:
        revision = _create_agent(store)
        for session_index in range(32):
            store.repository.create_session(
                session_id=f"session-{session_index:02d}",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                title=f"Session {session_index:02d}",
            ).result(timeout=3)

        def reserve_admission(session_index: int, turn_index: int):
            return store.repository.reserve_submission_admission(
                turn_id=f"turn-{session_index:02d}-{turn_index:02d}",
                session_id=f"session-{session_index:02d}",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                client_submission_id=f"submission-{session_index:02d}-{turn_index:02d}",
            ).result(timeout=5)

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [
                executor.submit(reserve_admission, session_index, turn_index)
                for session_index in range(32)
                for turn_index in range(4)
            ]
            results = [future.result(timeout=10) for future in futures]

        store.writer.flush(timeout=5)
        assert len(results) == 128
        for session_index in range(32):
            for turn_index in range(4):
                admission = store.repository.get_submission_admission(
                    session_id=f"session-{session_index:02d}",
                    client_submission_id=(
                        f"submission-{session_index:02d}-{turn_index:02d}"
                    ),
                )
                assert admission is not None
                assert admission["state"] == "reserved"
        metrics = store.writer.metrics()
        assert metrics["failedMutations"] == 0
        assert metrics["maxQueueDepth"] <= 512
    finally:
        store.close()


def test_readers_and_single_writer_remain_consistent_under_concurrency(
    tmp_path: Path,
):
    store = _open_store(
        tmp_path,
        queue_capacity=512,
        max_batch_size=32,
        max_batch_delay_ms=5,
    )
    stop_readers = threading.Event()
    reader_counts = [0] * 8
    reader_errors: list[Exception] = []
    try:
        revision = _create_agent(store)
        for session_index in range(32):
            store.repository.create_session(
                session_id=f"session-{session_index:02d}",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                title=f"Session {session_index:02d}",
            ).result(timeout=3)

        def read_sessions(reader_index: int) -> None:
            try:
                while not stop_readers.is_set():
                    rows = store.repository.list_sessions(agent_id="agent-a")
                    assert len(rows) == 32
                    reader_counts[reader_index] += 1
            except Exception as exc:  # noqa: BLE001 - retained for the parent assertion.
                reader_errors.append(exc)

        def reserve_admission(index: int) -> dict[str, object]:
            session_index = index % 32
            turn_index = index // 32
            return store.repository.reserve_submission_admission(
                turn_id=f"turn-{session_index:02d}-{turn_index:02d}",
                session_id=f"session-{session_index:02d}",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                client_submission_id=f"submission-{session_index:02d}-{turn_index:02d}",
            ).result(timeout=5)

        with ThreadPoolExecutor(max_workers=24) as executor:
            readers = [executor.submit(read_sessions, index) for index in range(8)]
            writers = [executor.submit(reserve_admission, index) for index in range(128)]
            results = [future.result(timeout=10) for future in writers]
            stop_readers.set()
            for future in readers:
                future.result(timeout=5)

        assert len(results) == 128
        assert reader_errors == []
        assert all(count > 0 for count in reader_counts)
        for session_index in range(32):
            assert all(
                store.repository.get_submission_admission(
                    session_id=f"session-{session_index:02d}",
                    client_submission_id=(
                        f"submission-{session_index:02d}-{turn_index:02d}"
                    ),
                )
                is not None
                for turn_index in range(4)
            )
    finally:
        stop_readers.set()
        store.close()


def test_schema_v4_exposes_directory_columns_and_bounded_preview(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        metadata = store.database.metadata()
        assert metadata["schemaVersion"] == 4
        revision = _create_agent(store)
        long_preview = "x" * (LAST_PREVIEW_MAX_CHARS + 80)
        store.repository.upsert_directory_session(
            session_id="session-dir",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Directory session",
            session_kind="main",
            last_preview=long_preview,
        ).result(timeout=3)
        row = store.repository.get_session("session-dir")
        assert row is not None
        assert row["sessionKind"] == "main"
        assert row["lastPreview"].endswith("…")
        assert len(row["lastPreview"]) == LAST_PREVIEW_MAX_CHARS
        store.repository.touch_directory_session(
            session_id="session-dir",
            status="ready",
            last_preview="later preview",
        ).result(timeout=3)
        touched = store.repository.get_session("session-dir")
        assert touched is not None
        assert touched["lastPreview"] == "later preview"
        assert store.repository.legacy_sessions_discarded_at_ms() is None
        marked = store.repository.mark_legacy_sessions_discarded().result(timeout=3)
        assert marked > 0
        assert store.repository.legacy_sessions_discarded_at_ms() == marked
    finally:
        store.close()


def test_directory_list_uses_keyset_cursor_not_offset(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store)
        for index in range(3):
            store.repository.create_session(
                session_id=f"session-{index}",
                agent_id="agent-a",
                agent_config_revision_id=revision,
                title=f"Session {index}",
            ).result(timeout=3)
        first = store.repository.list_directory_page(agent_id="agent-a", limit=2)
        assert len(first["rows"]) == 2
        assert first["total"] == 3
        assert first["nextCursor"]
        recency, session_id = parse_directory_cursor(first["nextCursor"])
        assert recency > 0
        assert session_id
        second = store.repository.list_directory_page(
            agent_id="agent-a",
            limit=2,
            before=(recency, session_id),
        )
        first_ids = {row["sessionId"] for row in first["rows"]}
        second_ids = {row["sessionId"] for row in second["rows"]}
        assert first_ids.isdisjoint(second_ids)
        assert len(first_ids | second_ids) == 3
        assert second["nextCursor"] == ""
    finally:
        store.close()

# ---------------------------------------------------------------------------
# 会话删除单事务：archive_session_and_replace_chat_state


def test_archive_session_and_replace_chat_state_commits_atomically(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store, agent_id="agent-a")
        store.repository.upsert_directory_session(
            session_id="session-deleted",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Will be deleted",
        ).result(timeout=3)
        store.repository.upsert_directory_session(
            session_id="session-kept",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Kept",
        ).result(timeout=3)
        store.repository.replace_chat_state(
            {
                "version": 1,
                "active_conversation_id": "session-kept",
                "updated_at": "2026-08-14T01:02:03Z",
                "conversations": [
                    {"conversation_id": "session-deleted", "title": "Will be deleted"},
                    {"conversation_id": "session-kept", "title": "Kept"},
                ],
            }
        ).result(timeout=3)

        result = store.repository.archive_session_and_replace_chat_state(
            session_id="session-deleted",
            state={
                "version": 1,
                "active_conversation_id": "session-kept",
                "updated_at": "2026-08-14T01:05:00Z",
                "conversations": [{"conversation_id": "session-kept", "title": "Kept"}],
            },
        ).result(timeout=3)

        assert result["archive"]["sessionId"] == "session-deleted"
        assert result["chatState"]["stateRevision"] >= 2
        restored = store.repository.get_chat_state()
        assert [item["conversation_id"] for item in restored["conversations"]] == [
            "session-kept"
        ]
        page = store.repository.list_directory_page(limit=50)
        assert [item["sessionId"] for item in page["rows"]] == ["session-kept"]
    finally:
        store.close()
    connection = sqlite3.connect(
        tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    )
    try:
        archived = connection.execute(
            "SELECT archived_at_ms FROM sessions WHERE session_id='session-deleted'"
        ).fetchone()
        assert archived is not None
        assert archived[0] is not None
    finally:
        connection.close()


def test_archive_failure_rolls_back_chat_state_in_same_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from core.chat.conversation_store.repository import SessionDao

    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store, agent_id="agent-a")
        store.repository.upsert_directory_session(
            session_id="session-deleted",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Will be deleted",
        ).result(timeout=3)
        store.repository.upsert_directory_session(
            session_id="session-kept",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Kept",
        ).result(timeout=3)
        store.repository.replace_chat_state(
            {
                "version": 1,
                "active_conversation_id": "session-kept",
                "updated_at": "2026-08-14T01:02:03Z",
                "conversations": [
                    {"conversation_id": "session-deleted", "title": "Will be deleted"},
                    {"conversation_id": "session-kept", "title": "Kept"},
                ],
            }
        ).result(timeout=3)
        original = store.repository.get_chat_state()
        original_revision = int(original["state_revision"])

        def fail_archive(self, session_id):
            raise RuntimeError("simulated directory archive failure")

        monkeypatch.setattr(SessionDao, "archive", fail_archive)

        future = store.repository.archive_session_and_replace_chat_state(
            session_id="session-deleted",
            state={
                "version": 1,
                "active_conversation_id": "session-kept",
                "updated_at": "2026-08-14T01:05:00Z",
                "conversations": [{"conversation_id": "session-kept", "title": "Kept"}],
            },
        )
        with pytest.raises(RuntimeError, match="simulated directory archive failure"):
            future.result(timeout=3)

        restored = store.repository.get_chat_state()
        assert {
            item["conversation_id"] for item in restored["conversations"]
        } == {"session-deleted", "session-kept"}
        assert int(restored["state_revision"]) == original_revision
        page = store.repository.list_directory_page(limit=50)
        assert {item["sessionId"] for item in page["rows"]} == {
            "session-deleted",
            "session-kept",
        }
    finally:
        store.close()


def test_archive_session_and_replace_chat_state_uses_one_writer_batch(tmp_path: Path):
    store = _open_store(tmp_path, max_batch_size=32)
    try:
        revision = _create_agent(store, agent_id="agent-a")
        store.repository.upsert_directory_session(
            session_id="session-deleted",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Will be deleted",
        ).result(timeout=3)
        store.writer.flush(timeout=5)
        before = int(store.writer.metrics()["batchCount"])
        store.repository.archive_session_and_replace_chat_state(
            session_id="session-deleted",
            state={
                "version": 1,
                "active_conversation_id": "",
                "updated_at": "2026-08-14T01:05:00Z",
                "conversations": [],
            },
        ).result(timeout=3)
        after = int(store.writer.metrics()["batchCount"])
        assert after == before + 1
    finally:
        store.close()


def test_archive_session_and_replace_chat_state_is_idempotent(tmp_path: Path):
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store, agent_id="agent-a")
        store.repository.upsert_directory_session(
            session_id="session-deleted",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Will be deleted",
        ).result(timeout=3)
        payload = {
            "version": 1,
            "active_conversation_id": "session-kept",
            "updated_at": "2026-08-14T01:05:00Z",
            "conversations": [{"conversation_id": "session-kept", "title": "Kept"}],
        }
        first = store.repository.archive_session_and_replace_chat_state(
            session_id="session-deleted",
            state=payload,
        ).result(timeout=3)
        second = store.repository.archive_session_and_replace_chat_state(
            session_id="session-deleted",
            state=payload,
        ).result(timeout=3)

        assert first["archive"]["action"] == "archived"
        assert second["archive"] is None
        restored = store.repository.get_chat_state()
        assert [item["conversation_id"] for item in restored["conversations"]] == [
            "session-kept"
        ]
    finally:
        store.close()
    connection = sqlite3.connect(
        tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    )
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM session_runtime_state"
        ).fetchone()[0]
        assert rows == 1
    finally:
        connection.close()
