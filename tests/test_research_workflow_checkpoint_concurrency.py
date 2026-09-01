"""B4 hardening: checkpoint SQLite concurrent writers plus factory pragma policy.

After pump-worker parallelization the checkpoint store is read and written by
concurrent threads through short-lived connections.  Every connection must
come from the single factory with WAL + busy timeout, and 10-way concurrent
writers must complete with zero ``database is locked`` failures and zero data
loss.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from core.research.workflow.checkpoint_store import (
    CHECKPOINT_BUSY_TIMEOUT_MS,
    CHECKPOINT_WAL_JOURNAL_SIZE_LIMIT_BYTES,
    _checkpoint_open_connection,
    _connect_checkpoint_sqlite,
    list_checkpoint_thread_ids,
    list_team_scoped_checkpoints,
    open_sqlite_checkpointer,
)

WRITER_COUNT = 10
WRITES_PER_WRITER = 4
READER_COUNT = 4


def _make_checkpoint(team_id: str) -> dict:
    return {
        "v": 1,
        "id": str(uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel_values": {"team_id": team_id},
        "channel_versions": {"__root__": 1},
        "versions_seen": {},
    }


def _assert_factory_pragmas(connection: sqlite3.Connection) -> None:
    """Assert the fixed pragma policy on any open checkpoint connection."""

    assert int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000
    assert CHECKPOINT_BUSY_TIMEOUT_MS == 5000
    assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(connection.execute("PRAGMA synchronous").fetchone()[0]) == 1  # NORMAL
    assert int(connection.execute("PRAGMA journal_size_limit").fetchone()[0]) == (
        CHECKPOINT_WAL_JOURNAL_SIZE_LIMIT_BYTES
    )


def test_connection_factory_applies_fixed_pragmas(tmp_path: Path) -> None:
    db = tmp_path / "checkpoints.sqlite"
    with open_sqlite_checkpointer(db):
        pass  # create the store through the factory-backed saver

    writer = _connect_checkpoint_sqlite(db, read_only=False)
    try:
        _assert_factory_pragmas(writer)
    finally:
        writer.close()

    # The read-only reset-port lane goes through the same factory and keeps
    # the busy timeout, WAL recognition, and its fail-closed query_only lock.
    reader = _checkpoint_open_connection(db, read_only=True)
    try:
        _assert_factory_pragmas(reader)
        assert int(reader.execute("PRAGMA query_only").fetchone()[0]) == 1
    finally:
        reader.close()


def test_open_sqlite_checkpointer_uses_factory_connection(tmp_path: Path) -> None:
    db = tmp_path / "checkpoints.sqlite"
    with open_sqlite_checkpointer(db) as saver:
        assert isinstance(saver, SqliteSaver)
        _assert_factory_pragmas(saver.conn)


def test_ten_concurrent_writers_and_readers_have_no_lock_failures(tmp_path: Path) -> None:
    db = tmp_path / "checkpoints.sqlite"
    with open_sqlite_checkpointer(db):
        pass  # create schema before the barrier so setup races stay out of scope

    barrier = threading.Barrier(WRITER_COUNT + READER_COUNT)
    errors: list[str] = []
    stop = threading.Event()

    def writer(index: int) -> None:
        thread_id = f"conc-thread-{index}"
        team_id = f"team-{index}"
        try:
            barrier.wait(timeout=60)
            with open_sqlite_checkpointer(db) as saver:
                config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                for step in range(WRITES_PER_WRITER):
                    saved = saver.put(
                        config,
                        _make_checkpoint(team_id),
                        {"source": "b4-stress", "step": step},
                        {"__root__": step + 1},
                    )
                    assert saved["configurable"]["checkpoint_id"]
        except Exception as exc:  # noqa: BLE001 - collect every failure for assertion
            errors.append(f"writer-{index}: {exc!r}")

    def reader(index: int) -> None:
        try:
            barrier.wait(timeout=60)
            while not stop.is_set():
                # Read-only reset-port lane racing the writers: WAL must let
                # both sides proceed and the busy timeout must absorb any
                # transient contention instead of raising "database is locked".
                list_checkpoint_thread_ids(db)
                time.sleep(0.001)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader-{index}: {exc!r}")

    writer_threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITER_COUNT)]
    reader_threads = [threading.Thread(target=reader, args=(i,)) for i in range(READER_COUNT)]
    for thread in reader_threads + writer_threads:
        thread.start()
    for thread in writer_threads:
        thread.join(timeout=120)
    stop.set()
    for thread in reader_threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in writer_threads + reader_threads)
    # Zero failures overall, which subsumes the zero "database is locked"
    # acceptance rule: any lock escalation that survived busy_timeout would
    # surface here as a collected sqlite3.OperationalError.
    assert errors == []

    # Data completeness: every writer's thread is present, every write landed,
    # and each team can still read its own rows back through the scoped port.
    expected_threads = sorted(f"conc-thread-{i}" for i in range(WRITER_COUNT))
    assert list_checkpoint_thread_ids(db) == expected_threads
    authority = [
        {
            "threadId": f"conc-thread-{i}",
            "teamId": f"team-{i}",
            "runId": f"conc-thread-{i}",
        }
        for i in range(WRITER_COUNT)
    ]
    for index in range(WRITER_COUNT):
        rows = list_team_scoped_checkpoints(
            f"team-{index}",
            checkpoint_path=db,
            scope_authority=authority,
        )
        assert len(rows) == WRITES_PER_WRITER
        assert all(row["teamId"] == f"team-{index}" for row in rows)

    # Read-back through a fresh saver: last checkpoint per thread decodes with
    # the writer's own team binding intact.
    with open_sqlite_checkpointer(db) as verifier:
        for index in range(WRITER_COUNT):
            tuple_ = verifier.get_tuple({"configurable": {"thread_id": f"conc-thread-{index}"}})
            assert tuple_ is not None
            assert tuple_.checkpoint["channel_values"]["team_id"] == f"team-{index}"
