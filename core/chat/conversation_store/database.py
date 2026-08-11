"""SQLite lifecycle and safety policy for the canonical conversation store."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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
    ) -> None:
        raw_path = str(path)
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ConversationStoreUnavailableError(
                "Canonical conversation storage requires an explicit local file path."
            )
        self.path = Path(path).expanduser().resolve(strict=False)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
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
            yield connection
        finally:
            connection.close()

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
