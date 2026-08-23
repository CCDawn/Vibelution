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
from .schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    V5_CATALOG_COLUMNS,
    V5_CATALOG_LOOKUP_INDEX_COLUMNS,
    V5_CATALOG_LOOKUP_INDEX_NAME,
    V5_CATALOG_LOOKUP_INDEX_STATEMENT,
    V5_CATALOG_TABLE_NAME,
    V5_CATALOG_TABLE_STATEMENT,
    V5_CATALOG_UNIQUE_COLUMNS,
    V5_LEGACY_CHECKSUM,
)

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
        self._reader_connections: dict[int, Any] = {}
        self._reader_lock = threading.Lock()
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
        self.close_all_readers()

    def open_reader(self) -> Any:
        if self._closed:
            raise WorkflowLedgerSchemaError("ledger database is closed")
        connection = sqlite_runtime.open_ledger_connection(str(self.path), read_only=True)
        return connection

    def acquire_read_connection(self) -> Any:
        """Thread-local pooled read-only connection (overflow allowed, no wait)."""
        thread_id = threading.get_ident()
        with self._reader_lock:
            cached = self._reader_connections.get(thread_id)
            if cached is not None:
                return cached
        if not self._reader_slots.acquire(blocking=False):
            return self.open_reader()
        try:
            connection = self.open_reader()
        except Exception:
            self._reader_slots.release()
            raise
        with self._reader_lock:
            self._reader_connections[thread_id] = connection
        return connection

    def release_read_connection(self, connection: Any) -> None:
        thread_id = threading.get_ident()
        with self._reader_lock:
            if self._reader_connections.get(thread_id) is connection:
                return
        try:
            connection.close()
        except Exception:
            return
        self._reader_slots.release()

    def close_all_readers(self) -> None:
        """Close every pooled reader connection (fixes WinError 32 on close)."""
        with self._reader_lock:
            connections = list(self._reader_connections.values())
            self._reader_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                continue

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
                    checksum = str(record[0])
                    is_legacy_v5 = (
                        migration.version == 5 and checksum == V5_LEGACY_CHECKSUM
                    )
                    if checksum != migration.checksum and not is_legacy_v5:
                        raise WorkflowLedgerSchemaError(
                            "Workflow Ledger migration checksum mismatch at "
                            f"version {migration.version}"
                        )
                    if migration.version == 5:
                        self._validate_v5_catalog_schema(connection)
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                if migration.version == 5:
                    self._validate_v5_catalog_schema(connection)
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

    def _validate_v5_catalog_schema(self, connection: Any) -> None:
        """Fail closed unless the v5 authorization DDL is exactly supported.

        The legacy checksum is not enough evidence: a copied or partially
        rebuilt database may retain ``schema_migrations`` while its table or
        indexes drift.  Validate both the stored DDL and SQLite's structural
        introspection before allowing the runtime to open it.
        """

        table_row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
            (V5_CATALOG_TABLE_NAME,),
        ).fetchone()
        if table_row is None or _normalize_sql(table_row[0]) != _normalize_sql(
            V5_CATALOG_TABLE_STATEMENT
        ):
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization table DDL mismatch"
            )

        columns = tuple(
            (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(V5_CATALOG_TABLE_NAME)})"
            )
        )
        if columns != V5_CATALOG_COLUMNS:
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization columns mismatch"
            )

        index_rows = tuple(
            connection.execute(
                f"PRAGMA index_list({_quote_identifier(V5_CATALOG_TABLE_NAME)})"
            )
        )
        lookup = next(
            (row for row in index_rows if str(row[1]) == V5_CATALOG_LOOKUP_INDEX_NAME),
            None,
        )
        if lookup is None or int(lookup[2]) != 0 or str(lookup[3]) != "c":
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization lookup index mismatch"
            )
        lookup_index_sql = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'index' AND name = ?",
            (V5_CATALOG_LOOKUP_INDEX_NAME,),
        ).fetchone()
        if lookup_index_sql is None or _normalize_sql(lookup_index_sql[0]) != _normalize_sql(
            V5_CATALOG_LOOKUP_INDEX_STATEMENT
        ):
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization lookup DDL mismatch"
            )
        lookup_columns = tuple(
            (str(row[2]), bool(int(row[3])))
            for row in connection.execute(
                f"PRAGMA index_xinfo({_quote_identifier(V5_CATALOG_LOOKUP_INDEX_NAME)})"
            )
            if int(row[5]) == 1
        )
        if lookup_columns != V5_CATALOG_LOOKUP_INDEX_COLUMNS:
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization lookup columns mismatch"
            )

        unique_constraint_found = False
        for row in index_rows:
            if int(row[2]) != 1 or str(row[3]) != "u":
                continue
            index_name = str(row[1])
            unique_columns = tuple(
                str(info[2])
                for info in connection.execute(
                    f"PRAGMA index_info({_quote_identifier(index_name)})"
                )
            )
            if unique_columns == V5_CATALOG_UNIQUE_COLUMNS:
                unique_constraint_found = True
                break
        if not unique_constraint_found:
            raise WorkflowLedgerSchemaError(
                "Workflow Ledger v5 catalog authorization unique constraint mismatch"
            )


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _normalize_sql(value: Any) -> str:
    raw_sql = str(value or "")
    normalized: list[str] = []
    pending_space = False
    index = 0

    while index < len(raw_sql):
        char = raw_sql[index]
        quote_closer = {"'": "'", '"': '"', "`": "`", "[": "]"}.get(char)
        if quote_closer is not None:
            if pending_space and normalized and normalized[-1] not in "(),":
                normalized.append(" ")
            pending_space = False
            quote_end = _quoted_sql_end(raw_sql, index, quote_closer)
            normalized.append(raw_sql[index:quote_end])
            index = quote_end
            continue
        if char.isspace():
            pending_space = True
            index += 1
            continue
        if char in "(),":
            if normalized and normalized[-1] == " ":
                normalized.pop()
            normalized.append(char)
            pending_space = False
            index += 1
            continue
        if pending_space and normalized and normalized[-1] not in "(),":
            normalized.append(" ")
        pending_space = False
        normalized.append(char.lower())
        index += 1

    return "".join(normalized).strip().rstrip(";").strip()


def _quoted_sql_end(value: str, start: int, closer: str) -> int:
    index = start + 1
    while index < len(value):
        if value[index] != closer:
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == closer:
            index += 2
            continue
        return index + 1
    return len(value)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
