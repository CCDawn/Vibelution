"""SQLite lifecycle and safety policy for the canonical conversation store."""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import runtime as sqlite3
from .schema import MIGRATIONS, SCHEMA_VERSION

DEFAULT_BUSY_TIMEOUT_MS = 250
_SAFE_BACKPORTS = {(3, 44, 6), (3, 50, 7)}
_FIRST_FULLY_FIXED_VERSION = (3, 51, 3)
class ConversationStoreError(RuntimeError):
    """Base class for bounded canonical conversation-store failures."""


class ConversationStoreUnavailableError(ConversationStoreError):
    """The configured runtime cannot safely host the canonical database."""


class ConversationStoreSchemaError(ConversationStoreError):
    """The database schema is unsupported or has drifted."""


class ConversationStoreMigrationError(ConversationStoreError):
    """A schema migration failed and was rolled back."""


class ConversationStoreLockedError(ConversationStoreError):
    """A second writer or external process held SQLite beyond the short budget."""


@dataclass(frozen=True)
class SqliteWalRuntimeAssessment:
    version: tuple[int, int, int]
    safe: bool
    code: str
    detail: str


class _ThreadReaderLease:
    """A reusable query-only connection owned by one Python thread."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        generation: int,
        slot: threading.BoundedSemaphore,
        database: ConversationDatabase,
    ) -> None:
        self.connection = connection
        self.generation = generation
        self._slot = slot
        self._database_ref = weakref.ref(database)
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.connection.close()
        finally:
            self._slot.release()
            database = self._database_ref()
            if database is not None:
                database._record_thread_reader_retired()

    def __del__(self) -> None:
        try:
            self.close()
        except (sqlite3.Error, ValueError):
            # Thread-local cleanup must not surface during interpreter shutdown.
            return


def assess_sqlite_wal_runtime(
    version: Sequence[int] | str,
) -> SqliteWalRuntimeAssessment:
    """Classify SQLite versions against the upstream WAL-reset race advisory."""

    normalized = _normalize_version(version)
    if normalized in _SAFE_BACKPORTS or normalized >= _FIRST_FULLY_FIXED_VERSION:
        return SqliteWalRuntimeAssessment(
            version=normalized,
            safe=True,
            code="safe",
            detail="SQLite runtime contains the WAL-reset race fix.",
        )
    return SqliteWalRuntimeAssessment(
        version=normalized,
        safe=False,
        code="wal_reset_race",
        detail=(
            "Canonical WAL storage requires SQLite 3.51.3 or a patched "
            "3.44.6/3.50.7 backport."
        ),
    )


class ConversationDatabase:
    """Own database initialization plus writer/read-only connection policy."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        read_pool_capacity: int = 4,
    ) -> None:
        raw_path = str(path)
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ConversationStoreUnavailableError(
                "Canonical conversation storage requires an explicit local file path."
            )
        self.path = Path(path).expanduser().resolve(strict=False)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self.read_pool_capacity = max(1, int(read_pool_capacity))
        self._reader_slots = threading.BoundedSemaphore(self.read_pool_capacity)
        self._reader_local = threading.local()
        self._reader_pool_lock = threading.Lock()
        self._reader_pool_closed = False
        self._reader_generation = 0
        self._reader_metrics_lock = threading.Lock()
        self._active_readers = 0
        self._max_active_readers = 0
        self._active_pooled_readers = 0
        self._max_pooled_readers = 0
        self._overflow_readers = 0
        self._pooled_connection_opens = 0
        self._reused_pooled_reader_leases = 0
        self._cached_pooled_readers = 0
        self._max_cached_pooled_readers = 0
        _ensure_local_path(self.path)

    def initialize(self) -> dict[str, object]:
        self._require_safe_runtime()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._bootstrap_connection()
        migration_active = False
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            self._reject_newer_schema(connection, current_version)
            connection.execute("BEGIN IMMEDIATE")
            migration_active = True
            for migration in MIGRATIONS:
                record = _migration_record(connection, migration.version)
                if record is not None:
                    if str(record[1]) != migration.checksum:
                        raise ConversationStoreSchemaError(
                            "Conversation store migration checksum mismatch at "
                            f"version {migration.version}."
                        )
                    continue
                if migration.version <= current_version:
                    raise ConversationStoreSchemaError(
                        "Conversation store migration record is missing at "
                        f"version {migration.version}."
                    )
                for statement in migration.statements:
                    connection.execute(statement)
                now_ms = _now_ms()
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at_ms, checksum) "
                    "VALUES (?, ?, ?)",
                    (migration.version, now_ms, migration.checksum),
                )
                if migration.version == 1:
                    connection.execute(
                        "INSERT INTO conversation_store_meta("
                        "id, schema_version, created_at_ms, updated_at_ms"
                        ") VALUES (1, 1, ?, ?)",
                        (now_ms, now_ms),
                    )
                connection.execute(f"PRAGMA user_version={migration.version}")
                current_version = migration.version
            connection.commit()
            migration_active = False
            self._validate_schema(connection)
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check != "ok":
                raise ConversationStoreSchemaError(
                    "Conversation store quick_check did not return ok."
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "migrationChecksum": MIGRATIONS[-1].checksum,
                "quickCheck": quick_check,
                "sqliteDriver": sqlite3.DRIVER_NAME,
                "sqliteVersion": sqlite3.sqlite_version,
            }
        except ConversationStoreError:
            if migration_active:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if migration_active:
                connection.rollback()
            _raise_sqlite_error(exc, during_migration=migration_active)
        finally:
            connection.close()

    def metadata(self) -> dict[str, object]:
        with self.reader() as connection:
            self._validate_schema(connection)
            row = connection.execute(
                "SELECT schema_version, created_at_ms, updated_at_ms "
                "FROM conversation_store_meta WHERE id=1"
            ).fetchone()
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if row is None:
            raise ConversationStoreSchemaError("Conversation store metadata row is missing.")
        return {
            "schemaVersion": int(row[0]),
            "createdAtMs": int(row[1]),
            "updatedAtMs": int(row[2]),
            "quickCheck": quick_check,
        }

    def open_writer(self) -> sqlite3.Connection:
        self._require_safe_runtime()
        connection = sqlite3.connect(
            str(self.path),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        try:
            _configure_common(connection, busy_timeout_ms=self.busy_timeout_ms)
            connection.execute("PRAGMA synchronous=FULL")
            self._validate_schema(connection)
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        self._require_safe_runtime()
        connection, pooled = self._lease_current_thread_reader()
        with self._reader_metrics_lock:
            self._active_readers += 1
            self._max_active_readers = max(
                self._max_active_readers,
                self._active_readers,
            )
            if pooled:
                self._active_pooled_readers += 1
                self._max_pooled_readers = max(
                    self._max_pooled_readers,
                    self._active_pooled_readers,
                )
            else:
                self._overflow_readers += 1
        try:
            yield connection
        finally:
            try:
                if not pooled:
                    connection.close()
                elif self._reader_pool_is_retired():
                    self._retire_current_thread_reader()
            finally:
                with self._reader_metrics_lock:
                    self._active_readers -= 1
                    if pooled:
                        self._active_pooled_readers -= 1

    def close_read_pool(self) -> None:
        """Retire the thread-local reader pool without cross-thread closes."""

        with self._reader_pool_lock:
            if self._reader_pool_closed:
                return
            self._reader_pool_closed = True
            self._reader_generation += 1
        # Only this calling thread can safely close its thread-affine lease.
        self._retire_current_thread_reader()

    def reader_metrics(self) -> dict[str, int]:
        with self._reader_metrics_lock:
            return {
                "readerCapacity": self.read_pool_capacity,
                "activeReaders": self._active_readers,
                "maxActiveReaders": self._max_active_readers,
                "activePooledReaders": self._active_pooled_readers,
                "maxPooledReaders": self._max_pooled_readers,
                "idlePooledReaders": max(
                    0,
                    self._cached_pooled_readers - self._active_pooled_readers,
                ),
                "overflowReaders": self._overflow_readers,
                "pooledConnectionOpens": self._pooled_connection_opens,
                "reusedPooledReaderLeases": self._reused_pooled_reader_leases,
                "cachedPooledReaders": self._cached_pooled_readers,
                "maxCachedPooledReaders": self._max_cached_pooled_readers,
            }

    def _lease_current_thread_reader(self) -> tuple[sqlite3.Connection, bool]:
        """Reuse one owning-thread connection or open a short overflow reader."""

        existing = getattr(self._reader_local, "lease", None)
        with self._reader_pool_lock:
            pool_closed = self._reader_pool_closed
            generation = self._reader_generation
        if isinstance(existing, _ThreadReaderLease):
            if not pool_closed and existing.generation == generation:
                with self._reader_metrics_lock:
                    self._reused_pooled_reader_leases += 1
                return existing.connection, True
            self._retire_current_thread_reader(existing)
        if pool_closed:
            raise ConversationStoreUnavailableError(
                "Conversation store reader pool is closed."
            )

        # Do not wait for a hot-slot. A sixth concurrent query must be able to
        # finish with a short read-only connection rather than stall behind a
        # slow reader or borrow a connection owned by another thread.
        if not self._reader_slots.acquire(blocking=False):
            return self._open_reader_connection(), False
        try:
            connection = self._open_reader_connection()
        except Exception:
            self._reader_slots.release()
            raise
        with self._reader_pool_lock:
            if self._reader_pool_closed or generation != self._reader_generation:
                connection.close()
                self._reader_slots.release()
                raise ConversationStoreUnavailableError(
                    "Conversation store reader pool closed while opening a reader."
                )
        self._reader_local.lease = _ThreadReaderLease(
            connection=connection,
            generation=generation,
            slot=self._reader_slots,
            database=self,
        )
        with self._reader_metrics_lock:
            self._pooled_connection_opens += 1
            self._cached_pooled_readers += 1
            self._max_cached_pooled_readers = max(
                self._max_cached_pooled_readers,
                self._cached_pooled_readers,
            )
        return connection, True

    def _retire_current_thread_reader(
        self,
        lease: _ThreadReaderLease | None = None,
    ) -> None:
        current = getattr(self._reader_local, "lease", None)
        if not isinstance(current, _ThreadReaderLease):
            return
        if lease is not None and current is not lease:
            return
        del self._reader_local.lease
        current.close()

    def _reader_pool_is_retired(self) -> bool:
        with self._reader_pool_lock:
            return self._reader_pool_closed

    def _record_thread_reader_retired(self) -> None:
        with self._reader_metrics_lock:
            self._cached_pooled_readers = max(0, self._cached_pooled_readers - 1)

    def _open_reader_connection(self) -> sqlite3.Connection:
        uri = f"{self.path.as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            connection.execute("PRAGMA query_only=ON")
            return connection
        except Exception:
            connection.close()
            raise

    def passive_wal_checkpoint(
        self,
        connection: sqlite3.Connection,
    ) -> dict[str, int | float | str]:
        """Run a non-blocking WAL checkpoint on the writer actor connection."""

        started_at = time.perf_counter()
        try:
            row = connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)
        if row is None:
            raise ConversationStoreError("Conversation store WAL checkpoint returned no result.")
        wal_path = Path(f"{self.path}-wal")
        return {
            "mode": "passive",
            "busy": int(row[0]),
            "logPages": int(row[1]),
            "checkpointedPages": int(row[2]),
            "walBytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "durationMs": round((time.perf_counter() - started_at) * 1000, 3),
        }

    def _bootstrap_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=5,
            isolation_level=None,
        )
        try:
            _configure_common(connection, busy_timeout_ms=5000)
            row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if row is None or str(row[0]).lower() != "wal":
                raise ConversationStoreUnavailableError(
                    "Canonical conversation storage requires SQLite WAL support."
                )
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA wal_autocheckpoint=1000")
            return connection
        except Exception:
            connection.close()
            raise

    def _require_safe_runtime(self) -> None:
        assessment = assess_sqlite_wal_runtime(sqlite3.sqlite_version_info)
        if not assessment.safe:
            raise ConversationStoreUnavailableError(
                f"Unsafe SQLite {'.'.join(map(str, assessment.version))}: "
                f"{assessment.detail}"
            )

    @staticmethod
    def _reject_newer_schema(
        connection: sqlite3.Connection,
        current_version: int,
    ) -> None:
        if current_version > SCHEMA_VERSION:
            raise ConversationStoreSchemaError(
                "Conversation store was created by a newer unsupported schema."
            )
        if _table_exists(connection, "schema_migrations"):
            row = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            if row is not None and row[0] is not None and int(row[0]) > SCHEMA_VERSION:
                raise ConversationStoreSchemaError(
                    "Conversation store contains a newer unsupported migration."
                )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise ConversationStoreSchemaError(
                f"Unsupported conversation store schema version: {version}."
            )
        if not _table_exists(connection, "conversation_store_meta"):
            raise ConversationStoreSchemaError("Conversation store metadata is missing.")
        row = connection.execute(
            "SELECT schema_version FROM conversation_store_meta WHERE id=1"
        ).fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            raise ConversationStoreSchemaError(
                "Conversation store metadata schema version mismatch."
            )
        for migration in MIGRATIONS:
            record = _migration_record(connection, migration.version)
            if record is None or str(record[1]) != migration.checksum:
                raise ConversationStoreSchemaError(
                    "Conversation store migration checksum mismatch at "
                    f"version {migration.version}."
                )


def _configure_common(
    connection: sqlite3.Connection,
    *,
    busy_timeout_ms: int,
) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout={max(1, int(busy_timeout_ms))}")
    connection.execute("PRAGMA foreign_keys=ON")
    if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        raise ConversationStoreUnavailableError(
            "Conversation store could not enable SQLite foreign keys."
        )


def _migration_record(
    connection: sqlite3.Connection,
    version: int,
) -> sqlite3.Row | None:
    if not _table_exists(connection, "schema_migrations"):
        return None
    return connection.execute(
        "SELECT version, checksum FROM schema_migrations WHERE version=?",
        (version,),
    ).fetchone()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _normalize_version(version: Sequence[int] | str) -> tuple[int, int, int]:
    if isinstance(version, str):
        parts = version.split(".")
    else:
        parts = [str(value) for value in version]
    normalized = tuple(int(part) for part in parts[:3])
    if len(normalized) < 3:
        normalized += (0,) * (3 - len(normalized))
    return normalized


def _ensure_local_path(path: Path) -> None:
    raw = str(path)
    if raw.startswith(("\\\\", "//")):
        raise ConversationStoreUnavailableError(
            "Canonical conversation storage requires a local filesystem."
        )
    if os.name == "nt" and not path.anchor:
        raise ConversationStoreUnavailableError(
            "Canonical conversation storage requires an absolute local path."
        )


def _raise_sqlite_error(exc: sqlite3.Error, *, during_migration: bool = False) -> None:
    message = str(exc).lower()
    if "locked" in message or "busy" in message:
        raise ConversationStoreLockedError(
            "Conversation store writer exceeded the bounded lock wait."
        ) from exc
    if during_migration:
        raise ConversationStoreMigrationError(
            "Conversation store migration failed and was rolled back."
        ) from exc
    raise ConversationStoreError("Conversation store operation failed.") from exc


def _now_ms() -> int:
    return int(time.time() * 1000)
