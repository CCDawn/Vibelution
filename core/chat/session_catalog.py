"""Rebuildable SQLite metadata catalog for chat sessions.

Canonical chat state and turn journals remain the source of truth. This module
only owns a local, disposable query projection and never writes canonical data.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
DEFAULT_BUSY_TIMEOUT_MS = 5000
CATALOG_FILENAME = "session_catalog.sqlite3"


class CatalogError(RuntimeError):
    """Base class for bounded catalog failures."""


class CatalogUnavailableError(CatalogError):
    """The configured runtime location cannot safely host the catalog."""


class CatalogSchemaError(CatalogError):
    """The database schema is unsupported or has drifted."""


class CatalogMigrationError(CatalogError):
    """A schema migration failed and was rolled back."""


class CatalogLockedError(CatalogError):
    """Another SQLite writer held the catalog beyond the configured timeout."""


class CatalogReadOnlyError(CatalogError):
    """The catalog location cannot be written."""


class CatalogCorruptError(CatalogError):
    """SQLite reported an invalid or corrupt database."""


class CatalogLeaseConflictError(CatalogError):
    """A lease-bound mutation was attempted by a non-owner."""


@dataclass(frozen=True)
class Migration:
    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n;\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE schema_migrations (
      version INTEGER PRIMARY KEY,
      applied_at TEXT NOT NULL,
      checksum TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE catalog_meta (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      schema_version INTEGER NOT NULL,
      projection_version INTEGER NOT NULL,
      source_revision TEXT NOT NULL DEFAULT '',
      backfill_status TEXT NOT NULL DEFAULT 'pending',
      lease_owner TEXT,
      lease_expires_at TEXT,
      watermark TEXT NOT NULL DEFAULT '',
      last_reconciled_at TEXT NOT NULL DEFAULT '',
      last_quick_check_at TEXT NOT NULL DEFAULT '',
      last_error_type TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    INSERT INTO catalog_meta (
      id, schema_version, projection_version, source_revision, backfill_status
    ) VALUES (1, 1, 1, '', 'pending')
    """,
    """
    CREATE TABLE sessions (
      session_id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT '',
      task_title TEXT NOT NULL DEFAULT '',
      task_summary TEXT NOT NULL DEFAULT '',
      session_kind TEXT NOT NULL,
      visibility TEXT NOT NULL,
      agent_id TEXT NOT NULL DEFAULT '',
      agent_code TEXT NOT NULL DEFAULT '',
      agent_display_name TEXT NOT NULL DEFAULT '',
      team_id TEXT NOT NULL DEFAULT '',
      parent_session_id TEXT NOT NULL DEFAULT '',
      source_session_id TEXT NOT NULL DEFAULT '',
      workspace_key TEXT NOT NULL,
      dialogue_model_id TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT '',
      current_phase TEXT NOT NULL DEFAULT '',
      child_status TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL DEFAULT '',
      last_active_at TEXT NOT NULL DEFAULT '',
      last_turn_status TEXT NOT NULL DEFAULT '',
      open_turn_id TEXT NOT NULL DEFAULT '',
      latest_sequence INTEGER NOT NULL DEFAULT 0 CHECK (latest_sequence >= 0),
      event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
      message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
      journal_rel_path TEXT NOT NULL DEFAULT '',
      journal_size INTEGER NOT NULL DEFAULT 0 CHECK (journal_size >= 0),
      journal_mtime_ns INTEGER NOT NULL DEFAULT 0 CHECK (journal_mtime_ns >= 0),
      source_revision TEXT NOT NULL,
      indexed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE catalog_dirty_sessions (
      session_id TEXT PRIMARY KEY,
      reason TEXT NOT NULL,
      source_revision TEXT NOT NULL,
      observed_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX idx_sessions_last_active
    ON sessions(last_active_at DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_visibility_last_active
    ON sessions(visibility, last_active_at DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_kind_last_active
    ON sessions(session_kind, last_active_at DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_agent_last_active
    ON sessions(agent_id, last_active_at DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_team_last_active
    ON sessions(team_id, last_active_at DESC, session_id DESC)
    """,
    "CREATE INDEX idx_sessions_parent ON sessions(parent_session_id)",
    """
    CREATE INDEX idx_sessions_title
    ON sessions(title COLLATE NOCASE, session_id)
    """,
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, statements=_SCHEMA_V1_STATEMENTS),
)

_SESSION_COLUMNS = (
    "session_id",
    "title",
    "task_title",
    "task_summary",
    "session_kind",
    "visibility",
    "agent_id",
    "agent_code",
    "agent_display_name",
    "team_id",
    "parent_session_id",
    "source_session_id",
    "workspace_key",
    "dialogue_model_id",
    "status",
    "current_phase",
    "child_status",
    "created_at",
    "updated_at",
    "last_active_at",
    "last_turn_status",
    "open_turn_id",
    "latest_sequence",
    "event_count",
    "message_count",
    "journal_rel_path",
    "journal_size",
    "journal_mtime_ns",
    "source_revision",
    "indexed_at",
)

_INTEGER_SESSION_COLUMNS = {
    "latest_sequence",
    "event_count",
    "message_count",
    "journal_size",
    "journal_mtime_ns",
}

_QUERY_SEARCH_COLUMNS = (
    "session_id",
    "title",
    "task_title",
    "task_summary",
    "agent_id",
    "agent_code",
    "agent_display_name",
    "dialogue_model_id",
    "session_kind",
    "status",
    "current_phase",
)

_SORT_COLUMNS = {
    "last_active_at": "last_active_at",
    "updated_at": "updated_at",
    "created_at": "created_at",
    "title": "title COLLATE NOCASE",
    "session_id": "session_id",
}


def compute_workspace_key(workspace_root: Path, *, environment: str) -> str:
    normalized_environment = _normalize_environment(environment)
    canonical = Path(workspace_root).expanduser().resolve(strict=False)
    path_token = os.path.normcase(str(canonical)).replace("\\", "/")
    digest = hashlib.sha256(
        f"{normalized_environment}\n{path_token}".encode("utf-8")
    ).hexdigest()
    return digest[:20]


def resolve_session_catalog_path(
    workspace_root: Path,
    *,
    environment: str,
    local_app_data: str | os.PathLike[str] | None = None,
    project_root: Path | None = None,
) -> Path:
    normalized_environment = _normalize_environment(environment)
    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    workspace_key = compute_workspace_key(workspace, environment=normalized_environment)
    raw_local_root = (
        os.environ.get("LOCALAPPDATA", "")
        if local_app_data is None
        else str(local_app_data)
    )
    if str(raw_local_root or "").strip():
        catalog_root = (
            Path(raw_local_root).expanduser().resolve(strict=False)
            / "Vibelution"
            / "session-catalogs"
        )
    elif normalized_environment == "developer" and project_root is not None:
        catalog_root = (
            Path(project_root).expanduser().resolve(strict=False)
            / ".runtime"
            / "session-catalogs"
        )
    else:
        raise CatalogUnavailableError(
            "Session catalog requires an explicit local runtime cache root."
        )
    target = (catalog_root / workspace_key / CATALOG_FILENAME).resolve(strict=False)
    if _paths_overlap(target, workspace):
        raise CatalogUnavailableError(
            "Session catalog runtime cache must be isolated from canonical workspace data."
        )
    return target


class SessionCatalogStore:
    """Small, connection-per-operation store for a rebuildable catalog."""

    def __init__(
        self,
        database_path: Path,
        *,
        workspace_key: str,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve(strict=False)
        self.workspace_key = str(workspace_key or "").strip()
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        if not self.workspace_key:
            raise ValueError("workspace_key is required")

    def initialize(self) -> dict[str, Any]:
        self._ensure_local_target()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        migration_active = False
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            self._reject_unsupported_schema(connection, current_version)
            connection.execute("BEGIN IMMEDIATE")
            migration_active = True
            for migration in MIGRATIONS:
                if migration.version > SCHEMA_VERSION:
                    continue
                record = _migration_record(connection, migration.version)
                if record is not None:
                    if str(record["checksum"]) != migration.checksum:
                        raise CatalogSchemaError(
                            f"Session catalog migration checksum mismatch at version {migration.version}."
                        )
                    continue
                if migration.version <= current_version:
                    raise CatalogSchemaError(
                        f"Session catalog migration record missing at version {migration.version}."
                    )
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO schema_migrations(version, applied_at, checksum)
                    VALUES (?, ?, ?)
                    """,
                    (migration.version, _utcnow(), migration.checksum),
                )
                connection.execute(f"PRAGMA user_version={migration.version}")
                current_version = migration.version
            connection.commit()
            migration_active = False
            self._validate_schema(connection)
            quick_check = _quick_check(connection)
            if quick_check != "ok":
                raise CatalogCorruptError("Session catalog quick_check did not return ok.")
            checked_at = _utcnow()
            connection.execute(
                """
                UPDATE catalog_meta
                SET last_quick_check_at=?, last_error_type=''
                WHERE id=1
                """,
                (checked_at,),
            )
            metadata = _metadata_row(connection)
            connection.commit()
            return {
                "schemaVersion": int(metadata["schema_version"]),
                "projectionVersion": int(metadata["projection_version"]),
                "migrationChecksum": MIGRATIONS[-1].checksum,
                "quickCheck": quick_check,
            }
        except CatalogError:
            if migration_active:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if migration_active:
                connection.rollback()
            _raise_sqlite_error(exc, during_migration=migration_active)
        finally:
            connection.close()

    def metadata(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            self._validate_schema(connection)
            row = dict(_metadata_row(connection))
        for key in ("lease_owner", "lease_expires_at"):
            row[key] = str(row.get(key) or "")
        return row

    def quick_check(self) -> str:
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                result = _quick_check(connection)
                if result != "ok":
                    raise CatalogCorruptError(
                        "Session catalog quick_check did not return ok."
                    )
                connection.execute(
                    """
                    UPDATE catalog_meta
                    SET last_quick_check_at=?, last_error_type=''
                    WHERE id=1
                    """,
                    (_utcnow(),),
                )
                connection.commit()
                return result
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def upsert_session(self, row: Mapping[str, Any]) -> None:
        normalized = self._normalize_session_row(row)
        columns = ", ".join(_SESSION_COLUMNS)
        placeholders = ", ".join("?" for _ in _SESSION_COLUMNS)
        updates = ", ".join(
            f"{column}=excluded.{column}"
            for column in _SESSION_COLUMNS
            if column != "session_id"
        )
        values = tuple(normalized[column] for column in _SESSION_COLUMNS)
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                connection.execute(
                    f"""
                    INSERT INTO sessions ({columns})
                    VALUES ({placeholders})
                    ON CONFLICT(session_id) DO UPDATE SET {updates}
                    """,
                    values,
                )
                connection.commit()
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def query_sessions(
        self,
        *,
        q: str = "",
        agent_id: str = "",
        team_id: str = "",
        visibility: str = "",
        session_kind: str = "",
        status: str = "",
        sort_by: str = "last_active_at",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["workspace_key=?"]
        parameters: list[Any] = [self.workspace_key]
        filters = {
            "agent_id": agent_id,
            "team_id": team_id,
            "visibility": visibility,
            "session_kind": session_kind,
            "status": status,
        }
        for column, raw_value in filters.items():
            value = str(raw_value or "").strip()
            if value:
                clauses.append(f"{column}=?")
                parameters.append(value)
        query = str(q or "").strip()
        if query:
            escaped = f"%{_escape_like(query)}%"
            clauses.append(
                "("
                + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in _QUERY_SEARCH_COLUMNS)
                + ")"
            )
            parameters.extend(escaped for _ in _QUERY_SEARCH_COLUMNS)
        sort_column = _SORT_COLUMNS.get(str(sort_by or "").strip().lower())
        if sort_column is None:
            raise ValueError(f"Unsupported session catalog sort: {sort_by}")
        direction = str(sort_order or "desc").strip().lower()
        if direction not in {"asc", "desc"}:
            raise ValueError(f"Unsupported session catalog sort order: {sort_order}")
        bounded_limit = min(1000, max(1, int(limit)))
        bounded_offset = max(0, int(offset))
        parameters.extend((bounded_limit, bounded_offset))
        sql = f"""
            SELECT {", ".join(_SESSION_COLUMNS)}
            FROM sessions
            WHERE {" AND ".join(clauses)}
            ORDER BY {sort_column} {direction.upper()}, session_id {direction.upper()}
            LIMIT ? OFFSET ?
        """
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                rows = connection.execute(sql, tuple(parameters)).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def replace_sessions(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        owner: str,
        source_revision: str,
        watermark: str,
        source_revision_reader: Callable[[], str],
    ) -> bool:
        """Atomically publish a fully validated candidate projection."""

        normalized_rows = [self._normalize_session_row(row) for row in rows]
        session_ids = [row["session_id"] for row in normalized_rows]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("candidate session catalog contains duplicate session_id values")
        normalized_owner = str(owner or "").strip()
        normalized_revision = str(source_revision or "").strip()
        if not normalized_owner or not normalized_revision:
            raise ValueError("owner and source_revision are required")
        columns = ", ".join(_SESSION_COLUMNS)
        placeholders = ", ".join("?" for _ in _SESSION_COLUMNS)
        values = [
            tuple(row[column] for column in _SESSION_COLUMNS)
            for row in normalized_rows
        ]
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                connection.execute("DROP TABLE IF EXISTS temp.sessions_next")
                connection.execute(
                    "CREATE TEMP TABLE sessions_next AS SELECT * FROM sessions WHERE 0"
                )
                if values:
                    connection.executemany(
                        f"INSERT INTO sessions_next ({columns}) VALUES ({placeholders})",
                        values,
                    )
                connection.execute("BEGIN IMMEDIATE")
                current_owner = str(_metadata_row(connection)["lease_owner"] or "")
                if current_owner != normalized_owner:
                    connection.rollback()
                    raise CatalogLeaseConflictError(
                        "Session catalog lease is owned by another worker."
                    )
                if str(source_revision_reader() or "").strip() != normalized_revision:
                    connection.rollback()
                    return False
                connection.execute("DELETE FROM sessions")
                connection.execute(
                    f"INSERT INTO sessions ({columns}) SELECT {columns} FROM sessions_next"
                )
                connection.execute(
                    """
                    UPDATE catalog_meta
                    SET source_revision=?,
                        backfill_status='complete',
                        lease_owner=NULL,
                        lease_expires_at=NULL,
                        watermark=?,
                        last_reconciled_at=?,
                        last_error_type=''
                    WHERE id=1
                    """,
                    (normalized_revision, str(watermark or ""), _utcnow()),
                )
                connection.commit()
                return True
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def try_acquire_lease(
        self,
        owner: str,
        *,
        now: str,
        expires_at: str,
    ) -> bool:
        normalized_owner = str(owner or "").strip()
        if not normalized_owner:
            raise ValueError("lease owner is required")
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                row = _metadata_row(connection)
                current_owner = str(row["lease_owner"] or "")
                current_expiry = str(row["lease_expires_at"] or "")
                if (
                    current_owner
                    and current_owner != normalized_owner
                    and current_expiry > str(now)
                ):
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    UPDATE catalog_meta
                    SET lease_owner=?, lease_expires_at=?, backfill_status='running'
                    WHERE id=1
                    """,
                    (normalized_owner, str(expires_at)),
                )
                connection.commit()
                return True
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def update_watermark(self, owner: str, watermark: str) -> None:
        self._lease_owner_update(
            owner,
            "UPDATE catalog_meta SET watermark=? WHERE id=1",
            (str(watermark or ""),),
        )

    def release_lease(self, owner: str, *, status: str) -> None:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"pending", "complete", "failed"}:
            raise ValueError(f"Unsupported backfill status: {status}")
        self._lease_owner_update(
            owner,
            """
            UPDATE catalog_meta
            SET lease_owner=NULL, lease_expires_at=NULL, backfill_status=?
            WHERE id=1
            """,
            (normalized_status,),
        )

    def _lease_owner_update(
        self,
        owner: str,
        statement: str,
        parameters: Sequence[Any],
    ) -> None:
        normalized_owner = str(owner or "").strip()
        try:
            with closing(self._connect()) as connection:
                self._validate_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                current_owner = str(_metadata_row(connection)["lease_owner"] or "")
                if not current_owner or current_owner != normalized_owner:
                    connection.rollback()
                    raise CatalogLeaseConflictError(
                        "Session catalog lease is owned by another worker."
                    )
                connection.execute(statement, tuple(parameters))
                connection.commit()
        except sqlite3.Error as exc:
            _raise_sqlite_error(exc)

    def _normalize_session_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        normalized: dict[str, Any] = {}
        for column in _SESSION_COLUMNS:
            if column == "workspace_key":
                normalized[column] = self.workspace_key
            elif column in _INTEGER_SESSION_COLUMNS:
                normalized[column] = max(0, int(row.get(column) or 0))
            else:
                normalized[column] = str(row.get(column) or "")
        for required in ("session_kind", "visibility", "source_revision", "indexed_at"):
            if not normalized[required]:
                raise ValueError(f"{required} is required")
        return normalized

    def _connect(self) -> sqlite3.Connection:
        self._ensure_local_target()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                str(self.database_path),
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            actual_journal_mode = _enable_wal(connection)
            if actual_journal_mode.lower() != "wal":
                connection.close()
                connection = None
                raise CatalogUnavailableError(
                    "Session catalog requires SQLite WAL support on the runtime filesystem."
                )
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                connection.close()
                connection = None
                raise CatalogUnavailableError(
                    "Session catalog could not enable SQLite foreign keys."
                )
            return connection
        except CatalogError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            _raise_sqlite_error(exc)

    def _ensure_local_target(self) -> None:
        if not _is_local_filesystem(self.database_path):
            raise CatalogUnavailableError(
                "Session catalog requires a local filesystem runtime cache."
            )

    @staticmethod
    def _reject_unsupported_schema(
        connection: sqlite3.Connection,
        current_version: int,
    ) -> None:
        if current_version > SCHEMA_VERSION:
            raise CatalogSchemaError(
                "Session catalog was created by a newer unsupported schema."
            )
        if _table_exists(connection, "catalog_meta"):
            row = connection.execute(
                "SELECT schema_version FROM catalog_meta WHERE id=1"
            ).fetchone()
            if row is not None and int(row[0]) > SCHEMA_VERSION:
                raise CatalogSchemaError(
                    "Session catalog was created by a newer unsupported schema."
                )
        if _table_exists(connection, "schema_migrations"):
            row = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            if row is not None and row[0] is not None and int(row[0]) > SCHEMA_VERSION:
                raise CatalogSchemaError(
                    "Session catalog contains a newer unsupported migration."
                )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version != SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"Unsupported session catalog schema version: {current_version}."
            )
        row = _metadata_row(connection)
        if int(row["schema_version"]) != SCHEMA_VERSION:
            raise CatalogSchemaError("Session catalog metadata schema version mismatch.")
        if int(row["projection_version"]) != PROJECTION_VERSION:
            raise CatalogSchemaError(
                "Session catalog projection version is unsupported."
            )
        for migration in MIGRATIONS:
            record = _migration_record(connection, migration.version)
            if record is None or str(record["checksum"]) != migration.checksum:
                raise CatalogSchemaError(
                    f"Session catalog migration checksum mismatch at version {migration.version}."
                )


def _normalize_environment(environment: str) -> str:
    normalized = str(environment or "").strip().lower()
    if normalized not in {"formal", "developer"}:
        raise ValueError(f"Unsupported session catalog environment: {environment}")
    return normalized


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _is_local_filesystem(path: Path) -> bool:
    resolved = Path(path).expanduser().resolve(strict=False)
    raw = str(resolved)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return False
    if os.name != "nt":
        return True
    anchor = resolved.anchor
    if not anchor:
        return False
    drive_type = int(ctypes.windll.kernel32.GetDriveTypeW(str(anchor)))
    return drive_type in {3, 6}


def _enable_wal(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
    return str(row[0] if row is not None else "")


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


def _metadata_row(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM catalog_meta WHERE id=1").fetchone()
    if row is None:
        raise CatalogSchemaError("Session catalog metadata row is missing.")
    return row


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _quick_check(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA quick_check").fetchone()
    return str(row[0] if row is not None else "")


def _escape_like(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_sqlite_error(
    error: sqlite3.Error,
    *,
    during_migration: bool = False,
) -> None:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        raise CatalogLockedError("Session catalog is locked.") from error
    if "readonly" in message or "read-only" in message:
        raise CatalogReadOnlyError("Session catalog is read-only.") from error
    if (
        "malformed" in message
        or "not a database" in message
        or "file is encrypted" in message
    ):
        raise CatalogCorruptError("Session catalog is corrupt.") from error
    if during_migration:
        raise CatalogMigrationError(
            "Session catalog migration failed and was rolled back."
        ) from error
    if isinstance(error, sqlite3.DatabaseError):
        raise CatalogCorruptError("Session catalog database operation failed.") from error
    raise CatalogUnavailableError("Session catalog database is unavailable.") from error
