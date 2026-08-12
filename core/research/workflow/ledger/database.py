"""Connection policy and initialization for the Workflow Ledger database."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from . import runtime as sqlite_runtime
from .errors import (
    WorkflowLedgerCorruptionError,
    WorkflowLedgerMigrationError,
    WorkflowLedgerSchemaError,
    WorkflowLedgerUnavailableError,
)
from .schema import MIGRATIONS, SCHEMA_VERSION

DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_READ_POOL_CAPACITY = 4


class WorkflowLedgerDatabase:
    """Owns the writer connection and the read-only connection pool."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        read_pool_capacity: int = DEFAULT_READ_POOL_CAPACITY,
    ) -> None:
        raw_path = str(path)
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            raise WorkflowLedgerUnavailableError(
                "Workflow Ledger requires an explicit local file path."
            )
        self.path = Path(path).expanduser().resolve(strict=False)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self.read_pool_capacity = max(1, int(read_pool_capacity))
        self._reader_slots = threading.BoundedSemaphore(self.read_pool_capacity)
        self._reader_local = threading.local()
        self._closed = False
        self._writer: Any = None

    def initialize(self) -> dict[str, object]:
        sqlite_runtime.require_safe_sqlite_runtime()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite_runtime.open_ledger_connection(str(self.path))
        try:
            self._require_runtime_capabilities(connection)
            self._apply_migrations(connection)
            return {
                "schemaVersion": SCHEMA_VERSION,
                "sqliteVersion": sqlite_runtime.apsw.sqlitelibversion(),
                "wal": self._journal_mode(connection),
            }
        finally:
            connection.close()

    def open_writer(self) -> Any:
        if self._closed:
            raise WorkflowLedgerSchemaError("ledger database is closed")
        sqlite_runtime.require_safe_sqlite_runtime()
        connection = sqlite_runtime.open_ledger_connection(str(self.path))
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def close(self) -> None:
        self._closed = True
        writer = self._writer
        if writer is not None:
            writer.close()

    def open_reader(self) -> Any:
        if self._closed:
            raise WorkflowLedgerSchemaError("ledger database is closed")
        connection = sqlite_runtime.open_ledger_connection(str(self.path), read_only=True)
        return connection

    def acquire_read_connection(self) -> Any:
        """Thread-local pooled read-only connection (overflow allowed, no wait)."""
        cached = getattr(self._reader_local, "connection", None)
        if cached is not None:
            return cached
        if not self._reader_slots.acquire(blocking=False):
            return self.open_reader()
        try:
            connection = self.open_reader()
        except Exception:
            self._reader_slots.release()
            raise
        self._reader_local.connection = connection
        return connection

    def release_read_connection(self, connection: Any) -> None:
        if getattr(self._reader_local, "connection", None) is connection:
            return
        try:
            connection.close()
        except Exception:
            return
        self._reader_slots.release()

    def _require_runtime_capabilities(self, connection: Any) -> None:
        try:
            has_json = connection.execute(
                "SELECT json_valid('{}')"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite_runtime.apsw.Error as exc:
            raise WorkflowLedgerCorruptionError(f"ledger unreadable: {exc}") from exc
        if has_json != 1:
            raise WorkflowLedgerSchemaError("SQLite json_valid unavailable")
        if integrity != "ok":
            raise WorkflowLedgerCorruptionError(
                f"ledger integrity_check failed: {integrity}"
            )

    def _journal_mode(self, connection: Any) -> str:
        row = connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row else "unknown"

    def _apply_migrations(self, connection: Any) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  checksum TEXT NOT NULL,
                  applied_at_ms INTEGER NOT NULL
                )
                """
            )
            for migration in MIGRATIONS:
                record = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?",
                    (migration.version,),
                ).fetchone()
                if record is not None:
                    if str(record[0]) != migration.checksum:
                        raise WorkflowLedgerSchemaError(
                            "Workflow Ledger migration checksum mismatch at "
                            f"version {migration.version}"
                        )
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, checksum, applied_at_ms) "
                    "VALUES (?, ?, ?)",
                    (migration.version, migration.checksum, _utc_now_ms()),
                )
            connection.execute("COMMIT")
        except WorkflowLedgerSchemaError:
            connection.execute("ROLLBACK")
            raise
        except Exception as exc:
            connection.execute("ROLLBACK")
            raise WorkflowLedgerMigrationError(f"ledger migration failed: {exc}") from exc


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)
