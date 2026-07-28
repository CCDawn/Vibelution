from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import core.chat.session_catalog as session_catalog
from core.chat.session_catalog import (
    CatalogCorruptError,
    CatalogLeaseConflictError,
    CatalogLockedError,
    CatalogMigrationError,
    CatalogReadOnlyError,
    CatalogSchemaError,
    CatalogUnavailableError,
    Migration,
    SessionCatalogStore,
    compute_workspace_key,
    resolve_session_catalog_path,
)


def _store(tmp_path: Path, *, timeout_ms: int = 5000) -> SessionCatalogStore:
    return SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key="workspace-test",
        busy_timeout_ms=timeout_ms,
    )


def _session(session_id: str, **overrides):
    row = {
        "session_id": session_id,
        "title": f"Title {session_id}",
        "task_title": f"Task {session_id}",
        "task_summary": "bounded metadata",
        "session_kind": "main",
        "visibility": "normal",
        "agent_id": "agent-a",
        "agent_code": "A001",
        "agent_display_name": "Agent A",
        "dialogue_model_id": "model-a",
        "status": "ready",
        "current_phase": "idle",
        "created_at": "2026-07-27T00:00:00Z",
        "updated_at": "2026-07-27T00:00:01Z",
        "last_active_at": "2026-07-27T00:00:01Z",
        "latest_sequence": 1,
        "event_count": 1,
        "message_count": 1,
        "journal_rel_path": f"sessions/{session_id}/turn_journal.jsonl",
        "journal_size": 100,
        "journal_mtime_ns": 200,
        "source_revision": f"revision-{session_id}",
        "indexed_at": "2026-07-27T00:00:02Z",
    }
    row.update(overrides)
    return row


def test_workspace_key_and_runtime_path_isolate_formal_and_developer_modes(tmp_path):
    workspace = tmp_path / "canonical-workspace"
    local_app_data = tmp_path / "local-app-data"

    formal_key = compute_workspace_key(workspace, environment="formal")
    developer_key = compute_workspace_key(workspace, environment="developer")
    formal_path = resolve_session_catalog_path(
        workspace,
        environment="formal",
        local_app_data=local_app_data,
    )
    developer_path = resolve_session_catalog_path(
        workspace,
        environment="developer",
        local_app_data=local_app_data,
    )

    assert formal_key != developer_key
    assert formal_path != developer_path
    assert formal_path == (
        local_app_data
        / "Vibelution"
        / "session-catalogs"
        / formal_key
        / "session_catalog.sqlite3"
    )
    assert not formal_path.is_relative_to(workspace)


def test_formal_path_requires_local_app_data_but_developer_can_use_runtime_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    with pytest.raises(CatalogUnavailableError):
        resolve_session_catalog_path(
            workspace,
            environment="formal",
            local_app_data="",
            project_root=tmp_path / "project",
        )

    developer_path = resolve_session_catalog_path(
        workspace,
        environment="developer",
        local_app_data="",
        project_root=tmp_path / "project",
    )

    assert developer_path.is_relative_to(tmp_path / "project" / ".runtime" / "session-catalogs")


def test_initialize_creates_schema_v2_idempotently_and_records_checksum(tmp_path):
    store = _store(tmp_path)

    first = store.initialize()
    second = store.initialize()

    assert first["schemaVersion"] == 2
    assert second["schemaVersion"] == 2
    assert first["migrationChecksum"] == second["migrationChecksum"]
    assert store.quick_check() == "ok"
    with sqlite3.connect(store.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        migrations = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert {
        "catalog_meta",
        "schema_migrations",
        "sessions",
        "catalog_dirty_sessions",
    }.issubset(tables)
    assert [version for version, _checksum in migrations] == [1, 2]
    assert migrations[-1] == (2, first["migrationChecksum"])


def test_initialize_upgrades_existing_schema_v1_with_ordering_projection(tmp_path, monkeypatch):
    store = _store(tmp_path)
    legacy_migrations = (session_catalog.MIGRATIONS[0],)
    monkeypatch.setattr(session_catalog, "SCHEMA_VERSION", 1)
    monkeypatch.setattr(session_catalog, "PROJECTION_VERSION", 1)
    monkeypatch.setattr(session_catalog, "MIGRATIONS", legacy_migrations)
    store.initialize()
    monkeypatch.undo()

    upgraded = store.initialize()

    assert upgraded["schemaVersion"] == 2
    assert upgraded["projectionVersion"] == 2
    with sqlite3.connect(store.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        metadata = connection.execute(
            "SELECT schema_version, projection_version FROM catalog_meta WHERE id=1"
        ).fetchone()
    assert {"source_order", "updated_at_sort_key", "title_sort_key"}.issubset(columns)
    assert metadata == (2, 2)


def test_unknown_higher_schema_fails_closed_without_downgrade(tmp_path):
    store = _store(tmp_path)
    store.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(CatalogSchemaError, match="newer"):
        store.initialize()

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_unknown_higher_migration_fails_closed_even_if_user_version_was_not_updated(
    tmp_path,
):
    store = _store(tmp_path)
    store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            INSERT INTO schema_migrations(version, applied_at, checksum)
            VALUES (3, '2026-07-27T00:00:00Z', 'future')
            """
        )

    with pytest.raises(CatalogSchemaError, match="newer unsupported migration"):
        store.initialize()


def test_migration_checksum_mismatch_fails_closed(tmp_path):
    store = _store(tmp_path)
    store.initialize()
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=1",
            ("unexpected",),
        )

    with pytest.raises(CatalogSchemaError, match="checksum"):
        store.initialize()


def test_failed_migration_rolls_back_partial_schema(tmp_path, monkeypatch):
    store = _store(tmp_path)
    bad_migration = Migration(
        version=1,
        statements=(
            "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY)",
            "CREATE TABLE malformed (",
        ),
    )
    monkeypatch.setattr(session_catalog, "MIGRATIONS", (bad_migration,))

    with pytest.raises(CatalogMigrationError):
        store.initialize()

    with sqlite3.connect(store.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "should_rollback" not in tables
    assert version == 0


def test_parameterized_upsert_and_query_preserve_schema_under_sql_like_input(tmp_path):
    store = _store(tmp_path)
    store.initialize()
    injected = "needle%' OR 1=1 --"
    store.upsert_session(_session("session-a", title=injected))
    store.upsert_session(
        _session(
            "session-b",
            title="ordinary",
            agent_id="agent-b",
            last_active_at="2026-07-27T00:00:03Z",
        )
    )

    results = store.query_sessions(q=injected, limit=10)
    filtered = store.query_sessions(agent_id="agent-b", sort_order="asc", limit=10)

    assert [row["session_id"] for row in results] == ["session-a"]
    assert [row["session_id"] for row in filtered] == ["session-b"]
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


def test_catalog_never_persists_canonical_workspace_absolute_path(tmp_path):
    workspace = tmp_path / "private" / "canonical-workspace"
    key = compute_workspace_key(workspace, environment="formal")
    store = SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key=key,
    )
    store.initialize()
    store.upsert_session(_session("session-a"))

    database_bytes = store.database_path.read_bytes()
    assert str(workspace).encode() not in database_bytes
    assert store.query_sessions(limit=1)[0]["workspace_key"] == key


def test_lease_rejects_live_competitor_and_allows_stale_takeover(tmp_path):
    store = _store(tmp_path)
    store.initialize()

    assert store.try_acquire_lease(
        "owner-a",
        now="2026-07-27T00:00:00Z",
        expires_at="2026-07-27T00:05:00Z",
    )
    assert not store.try_acquire_lease(
        "owner-b",
        now="2026-07-27T00:01:00Z",
        expires_at="2026-07-27T00:06:00Z",
    )
    with pytest.raises(CatalogLeaseConflictError):
        store.update_watermark("owner-b", "sessions/session-b")

    assert store.try_acquire_lease(
        "owner-b",
        now="2026-07-27T00:05:01Z",
        expires_at="2026-07-27T00:10:00Z",
    )
    store.update_watermark("owner-b", "sessions/session-b")
    store.release_lease("owner-b", status="complete")

    metadata = store.metadata()
    assert metadata["watermark"] == "sessions/session-b"
    assert metadata["backfill_status"] == "complete"
    assert metadata["lease_owner"] == ""


def test_network_or_non_wal_filesystem_fails_closed_before_use(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(session_catalog, "_is_local_filesystem", lambda _path: False)

    with pytest.raises(CatalogUnavailableError, match="local filesystem"):
        store.initialize()
    assert not store.database_path.exists()

    monkeypatch.setattr(session_catalog, "_is_local_filesystem", lambda _path: True)
    monkeypatch.setattr(session_catalog, "_enable_wal", lambda _connection: "delete")
    with pytest.raises(CatalogUnavailableError, match="WAL"):
        store.initialize()


def test_locked_readonly_and_corrupt_failures_have_distinct_types(tmp_path, monkeypatch):
    locked_store = _store(tmp_path / "locked", timeout_ms=25)
    locked_store.initialize()
    blocker = sqlite3.connect(locked_store.database_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(CatalogLockedError):
            locked_store.try_acquire_lease(
                "owner-a",
                now="2026-07-27T00:00:00Z",
                expires_at="2026-07-27T00:05:00Z",
            )
    finally:
        blocker.rollback()
        blocker.close()

    readonly_store = _store(tmp_path / "readonly")

    def readonly_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(session_catalog.sqlite3, "connect", readonly_connect)
    with pytest.raises(CatalogReadOnlyError):
        readonly_store.initialize()
    monkeypatch.undo()

    corrupt_store = _store(tmp_path / "corrupt")
    corrupt_store.database_path.parent.mkdir(parents=True)
    corrupt_store.database_path.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(CatalogCorruptError):
        corrupt_store.initialize()
