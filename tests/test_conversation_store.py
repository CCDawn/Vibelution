from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.chat.conversation_store.database as conversation_database
import core.chat.conversation_store.runtime as conversation_sqlite_runtime
from core.chat.conversation_store import (
    ConversationBackpressureError,
    ConversationStore,
    ConversationStoreUnavailableError,
    assess_sqlite_wal_runtime,
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

        assert metadata["schemaVersion"] == 1
        assert metadata["quickCheck"] == "ok"
        assert {
            "agents",
            "agent_config_revisions",
            "sessions",
            "turns",
            "turn_items",
            "turn_item_chunks",
            "checkpoints",
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
    finally:
        store.close()


def test_turn_item_revision_is_monotonic_and_keeps_one_stable_row(
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
        turn = store.repository.begin_turn(
            turn_id="turn-a",
            session_id="session-a",
            client_submission_id="submission-a",
        ).result(timeout=3)

        first = store.repository.upsert_turn_item(
            item_id="tool-a",
            turn_id="turn-a",
            call_id="call-a",
            revision=1,
            kind="tool_call",
            status="running",
            payload={"toolName": "read_file"},
        ).result(timeout=3)
        terminal = store.repository.upsert_turn_item(
            item_id="tool-a",
            turn_id="turn-a",
            call_id="call-a",
            revision=2,
            kind="tool_call",
            status="completed",
            payload={"toolName": "read_file", "summary": "ok"},
        ).result(timeout=3)
        stale = store.repository.upsert_turn_item(
            item_id="tool-a",
            turn_id="turn-a",
            call_id="call-a",
            revision=1,
            kind="tool_call",
            status="running",
            payload={"toolName": "read_file"},
        ).result(timeout=3)
        terminal_guard = store.repository.upsert_turn_item(
            item_id="tool-a",
            turn_id="turn-a",
            call_id="call-a",
            revision=3,
            kind="tool_call",
            status="running",
            payload={"toolName": "read_file"},
        ).result(timeout=3)

        items = store.repository.list_turn_items("turn-a")
        assert turn["sequence"] == 1
        assert first == {"outcome": "inserted", "sequence": 1, "revision": 1}
        assert terminal == {"outcome": "updated", "sequence": 1, "revision": 2}
        assert stale == {"outcome": "stale", "sequence": 1, "revision": 2}
        assert terminal_guard == {"outcome": "terminal", "sequence": 1, "revision": 2}
        assert len(items) == 1
        assert items[0]["itemId"] == "tool-a"
        assert items[0]["status"] == "completed"
        assert items[0]["revision"] == 2
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


def test_drained_store_reopens_with_canonical_agent_session_and_turn_data(
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
        store.repository.begin_turn(
            turn_id="turn-reopen",
            session_id="session-reopen",
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
        assert [row["turnId"] for row in reopened.repository.list_turns("session-reopen")] == [
            "turn-reopen"
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


def test_32_sessions_concurrent_turn_writes_do_not_deadlock_or_lose_rows(
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

        def submit_turn(session_index: int, turn_index: int):
            return store.repository.begin_turn(
                turn_id=f"turn-{session_index:02d}-{turn_index:02d}",
                session_id=f"session-{session_index:02d}",
                client_submission_id=f"submission-{session_index:02d}-{turn_index:02d}",
            ).result(timeout=5)

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [
                executor.submit(submit_turn, session_index, turn_index)
                for session_index in range(32)
                for turn_index in range(4)
            ]
            results = [future.result(timeout=10) for future in futures]

        store.writer.flush(timeout=5)
        assert len(results) == 128
        for session_index in range(32):
            turns = store.repository.list_turns(f"session-{session_index:02d}")
            assert len(turns) == 4
            assert sorted(turn["sequence"] for turn in turns) == [1, 2, 3, 4]
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

        def write_turn(index: int) -> dict[str, object]:
            session_index = index % 32
            turn_index = index // 32
            return store.repository.begin_turn(
                turn_id=f"turn-{session_index:02d}-{turn_index:02d}",
                session_id=f"session-{session_index:02d}",
                client_submission_id=f"submission-{session_index:02d}-{turn_index:02d}",
            ).result(timeout=5)

        with ThreadPoolExecutor(max_workers=24) as executor:
            readers = [executor.submit(read_sessions, index) for index in range(8)]
            writers = [executor.submit(write_turn, index) for index in range(128)]
            results = [future.result(timeout=10) for future in writers]
            stop_readers.set()
            for future in readers:
                future.result(timeout=5)

        assert len(results) == 128
        assert reader_errors == []
        assert all(count > 0 for count in reader_counts)
        for session_index in range(32):
            assert len(
                store.repository.list_turns(f"session-{session_index:02d}")
            ) == 4
    finally:
        stop_readers.set()
        store.close()
