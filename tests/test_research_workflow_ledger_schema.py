"""T1 RED: Ledger schema — migrations, checksum, FK, corruption fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import (
    CatalogRunAuthorization,
    WorkflowLedgerCorruptionError,
    WorkflowLedgerSchemaError,
    WorkflowLedgerStore,
)
from core.research.workflow.ledger.database import _normalize_sql
from core.research.workflow.ledger.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    V5_CATALOG_LOOKUP_INDEX_NAME,
    V5_CATALOG_LOOKUP_INDEX_STATEMENT,
    V5_CATALOG_TABLE_NAME,
    V5_CATALOG_TABLE_STATEMENT,
    V5_LEGACY_CHECKSUM,
)
from tests._support.workflow_ledger_helpers import (
    build_command_record,
    build_run_record,
    open_ledger_store,
)


def test_migrations_apply_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    try:
        info = store.initialize()
        assert info["schemaVersion"] == SCHEMA_VERSION
        assert info["wal"] == "wal"
    finally:
        store.close()

    store = open_ledger_store(path)
    try:
        info = store.initialize()
        assert info["schemaVersion"] == SCHEMA_VERSION
    finally:
        store.close()


def test_migration_checksum_mismatch_fails_startup(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()
    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = 'deadbeef' WHERE version = 1"
    )
    connection.close()
    store = WorkflowLedgerStore(path)
    with pytest.raises(WorkflowLedgerSchemaError):
        store.initialize()


def test_legacy_v5_checksum_requires_expected_catalog_schema(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
        (V5_LEGACY_CHECKSUM,),
    )
    connection.execute("DROP TABLE catalog_run_authorizations")
    connection.close()

    store = WorkflowLedgerStore(path)
    with pytest.raises(WorkflowLedgerSchemaError, match="v5"):
        store.initialize()


def test_legacy_v5_checksum_opens_without_rewriting_and_supports_catalog_io(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
        (V5_LEGACY_CHECKSUM,),
    )
    connection.close()

    store = WorkflowLedgerStore(path)
    store.open()
    try:
        authorization = CatalogRunAuthorization(
            authorization_id="auth-legacy-v5",
            team_id="research-team",
            plan_id="real-1",
            batch_scope_json='{"questionIds":["SCI-096"]}',
            scope_hash="s" * 64,
            approved_by="operator-1",
            approved_at_ms=1_750_000_000_001,
            readiness_report_sha256="r" * 64,
            record_hash="h" * 64,
            created_at_ms=1_750_000_000_001,
        )
        store.submit(
            lambda uow: uow.repository.insert_catalog_run_authorization(authorization),
            force_flush=True,
        ).result(timeout=10)
        assert store.get_catalog_run_authorization(authorization.authorization_id) == authorization
    finally:
        store.close()

    connection = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY)
    assert connection.execute(
        "SELECT checksum FROM schema_migrations WHERE version = 5"
    ).fetchone()[0] == V5_LEGACY_CHECKSUM
    connection.close()


def test_legacy_v5_accepts_equivalent_catalog_ddl_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
        (V5_LEGACY_CHECKSUM,),
    )
    connection.execute("PRAGMA writable_schema = ON")
    connection.execute(
        "UPDATE sqlite_schema SET sql = ? WHERE type = 'table' AND name = ?",
        (_space_sql_punctuation(V5_CATALOG_TABLE_STATEMENT), V5_CATALOG_TABLE_NAME),
    )
    connection.execute(
        "UPDATE sqlite_schema SET sql = ? WHERE type = 'index' AND name = ?",
        (
            _space_sql_punctuation(V5_CATALOG_LOOKUP_INDEX_STATEMENT),
            V5_CATALOG_LOOKUP_INDEX_NAME,
        ),
    )
    connection.execute("PRAGMA writable_schema = OFF")
    connection.close()

    store = WorkflowLedgerStore(path)
    try:
        assert store.initialize()["schemaVersion"] == SCHEMA_VERSION
    finally:
        store.close()


def _space_sql_punctuation(statement: str) -> str:
    for punctuation in "(),":
        statement = statement.replace(punctuation, f" {punctuation} ")
    return statement


@pytest.mark.parametrize(
    ("sql", "expected"),
    (
        (
            "CHECK ( value = 'a,  b (x)' )",
            "check(value = 'a,  b (x)')",
        ),
        (
            'CREATE TABLE "Mixed (Name)" ( "Value,  (Text)" TEXT )',
            'create table "Mixed (Name)"("Value,  (Text)" text)',
        ),
        (
            "CHECK ( value = 'It''s,  Fine (X)' )",
            "check(value = 'It''s,  Fine (X)')",
        ),
        (
            'CREATE TABLE "Mixed ""(Name)""" ( "Value" TEXT )',
            'create table "Mixed ""(Name)"""("Value" text)',
        ),
        (
            "CREATE TABLE [Mixed (Name),  Value] ( [Column (X)] TEXT )",
            "create table [Mixed (Name),  Value]([Column (X)] text)",
        ),
        (
            "CREATE TABLE `Mixed ``(Name)``` ( `Value,  (Text)` TEXT )",
            "create table `Mixed ``(Name)```(`Value,  (Text)` text)",
        ),
    ),
)
def test_v5_sql_normalization_preserves_quoted_content(
    sql: str,
    expected: str,
) -> None:
    assert _normalize_sql(sql) == expected


def test_fresh_v5_uses_current_checksum(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    v5_migration = next(m for m in MIGRATIONS if m.version == 5)
    assert v5_migration.checksum != V5_LEGACY_CHECKSUM
    connection = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY)
    assert connection.execute(
        "SELECT checksum FROM schema_migrations WHERE version = 5"
    ).fetchone()[0] == v5_migration.checksum
    connection.close()


def test_legacy_v5_checksum_rejects_lookup_index_drift(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
        (V5_LEGACY_CHECKSUM,),
    )
    connection.execute("DROP INDEX idx_catalog_run_authorizations_lookup")
    connection.close()

    store = WorkflowLedgerStore(path)
    with pytest.raises(WorkflowLedgerSchemaError, match="v5"):
        store.initialize()


def test_legacy_v5_checksum_rejects_wrong_catalog_columns(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    _prepare_legacy_v5(path)

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute("DROP INDEX idx_catalog_run_authorizations_lookup")
    connection.execute("DROP TABLE catalog_run_authorizations")
    connection.execute(
        V5_CATALOG_TABLE_STATEMENT.replace(
            "team_id TEXT NOT NULL", "team_code TEXT NOT NULL"
        ).replace(
            "UNIQUE (team_id, plan_id, scope_hash, readiness_report_sha256)",
            "UNIQUE (team_code, plan_id, scope_hash, readiness_report_sha256)",
        )
    )
    connection.execute(
        V5_CATALOG_LOOKUP_INDEX_STATEMENT.replace(
            "team_id, plan_id", "team_code, plan_id"
        )
    )
    connection.close()

    with pytest.raises(WorkflowLedgerSchemaError, match="v5"):
        WorkflowLedgerStore(path).initialize()


def test_legacy_v5_checksum_rejects_wrong_unique_constraint(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    _prepare_legacy_v5(path)

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute("DROP INDEX idx_catalog_run_authorizations_lookup")
    connection.execute("DROP TABLE catalog_run_authorizations")
    connection.execute(
        V5_CATALOG_TABLE_STATEMENT.replace(
            "UNIQUE (team_id, plan_id, scope_hash, readiness_report_sha256)",
            "UNIQUE (team_id, plan_id, scope_hash, record_hash)",
        )
    )
    connection.execute(V5_CATALOG_LOOKUP_INDEX_STATEMENT)
    connection.close()

    with pytest.raises(WorkflowLedgerSchemaError, match="v5"):
        WorkflowLedgerStore(path).initialize()


def test_legacy_v5_checksum_rejects_lookup_index_order_drift(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    _prepare_legacy_v5(path)

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute("DROP INDEX idx_catalog_run_authorizations_lookup")
    connection.execute(
        V5_CATALOG_LOOKUP_INDEX_STATEMENT.replace(
            "approved_at_ms DESC, authorization_id",
            "authorization_id, approved_at_ms DESC",
        )
    )
    connection.close()

    with pytest.raises(WorkflowLedgerSchemaError, match="v5"):
        WorkflowLedgerStore(path).initialize()


def test_legacy_v5_checksum_drift_still_rejects_startup(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = 'deadbeef' WHERE version = 5"
    )
    connection.close()

    with pytest.raises(WorkflowLedgerSchemaError, match="checksum"):
        WorkflowLedgerStore(path).initialize()


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    import apsw

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        with pytest.raises(apsw.ConstraintError):
            store.submit(
                lambda uow: uow.repository.insert_run(
                    build_run_record(run_id="run-orphan", parent_run_id="run-missing")
                ),
                force_flush=True,
            ).result(timeout=10)

        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record()),
            force_flush=True,
        ).result(timeout=10)
        with pytest.raises(apsw.ConstraintError):
            store.submit(
                lambda uow: uow.repository.insert_command(
                    build_command_record(command_id="cmd-orphan", run_id="run-missing")
                ),
                force_flush=True,
            ).result(timeout=10)
    finally:
        store.close()


def test_integrity_check_on_startup(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.close()
    # 截断文件使 b-tree 结构损坏；startup 必须 fail closed。
    for suffix in (".sqlite3-wal", ".sqlite3-shm"):
        sidecar = tmp_path / f"ledger{suffix}"
        if sidecar.exists():
            sidecar.unlink()
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    store = WorkflowLedgerStore(path)
    with pytest.raises(WorkflowLedgerCorruptionError):
        store.initialize()


def test_corruption_fails_closed_after_open(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record()),
            force_flush=True,
        ).result(timeout=10)
        # 破坏底层文件后，读路径必须报错而不是返回空状态。
        path = Path(store.path)
        store.close()
        for suffix in (".sqlite3-wal", ".sqlite3-shm"):
            sidecar = tmp_path / f"ledger{suffix}"
            if sidecar.exists():
                sidecar.unlink()
        raw = path.read_bytes()
        path.write_bytes(raw[: len(raw) // 2])
        with pytest.raises(WorkflowLedgerCorruptionError):
            store = open_ledger_store(path)
            store.get_run("run-test")
    finally:
        store.close()


def test_schema_migration_versions_are_deterministic() -> None:
    checksums = {migration.version: migration.checksum for migration in MIGRATIONS}
    assert len(checksums) == len(MIGRATIONS)
    assert all(len(checksum) == 64 for checksum in checksums.values())


def _prepare_legacy_v5(path: Path) -> None:
    store = open_ledger_store(path)
    store.close()

    import apsw

    connection = apsw.Connection(str(path))
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
        (V5_LEGACY_CHECKSUM,),
    )
    connection.close()


def test_v10_rebuild_adds_paused_status_and_preserves_data(tmp_path: Path) -> None:
    """P2-e: the workflow_runs rebuild exposes the recoverable 'paused' status.

    A ledger that already carries rows (the upgrade path) is rebuilt without
    losing them, and every other table's foreign keys still resolve.
    """
    import apsw

    from core.research.workflow.ledger.database import _utc_now_ms
    from core.research.workflow.ledger.schema import MIGRATIONS

    path = tmp_path / "ledger-v9.sqlite3"
    # Build a v9-shaped ledger by hand: apply migrations 1..9 only, then put
    # rows in workflow_runs and its children.
    connection = apsw.Connection(str(path))
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("BEGIN IMMEDIATE")
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
        if migration.version > 9:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, checksum, applied_at_ms) "
            "VALUES (?, ?, ?)",
            (migration.version, migration.checksum, _utc_now_ms()),
        )
    connection.execute(
        """
        INSERT INTO workflow_runs (
          run_id, team_id, workflow_id, workflow_version_id, thread_id,
          project_id, question_id, status, run_version, last_event_sequence,
          input_snapshot_json, input_snapshot_hash, safety_limits_json,
          binding_snapshot_set_id, active_node_id, parent_run_id,
          forked_from_checkpoint_id, completion_kind, terminal_reason,
          blocked_problem_json, created_at_ms, updated_at_ms, completed_at_ms,
          structure_hash
        ) VALUES ('run-v9', 'research-team', 'challenge-cup-research', 'wv-x',
                  'run-v9', 'proj', 'q', 'running', 1, 0, '{}', 'h', '{}',
                  'b', NULL, NULL, NULL, NULL, NULL, NULL, 1, 1, NULL, '')
        """
    )
    connection.execute(
        """
        INSERT INTO workflow_commands (
          command_id, run_id, team_id, node_id, command_kind,
          expected_run_version, accepted_run_version, idempotency_key,
          request_hash, request_json, requested_by_json, status,
          created_at_ms
        ) VALUES ('cmd-v9', 'run-v9', 'research-team', NULL, 'start_node',
                  1, 1, 'key-v9', 'rh', '{}', '{}', 'accepted', 1)
        """
    )
    connection.execute("COMMIT")
    connection.close()

    store = open_ledger_store(path)
    try:
        assert store.initialize()["schemaVersion"] == 10
        run = store.get_run("run-v9")
        assert run is not None and run.status == "running"

        # The rebuild did not strand child rows: FK enforcement is back on
        # and the ledger accepts the new recoverable status.
        def pause(uow):
            ok = uow.repository.update_run_status(
                "run-v9", "research-team", "paused", 1234
            )
            sequence = uow.repository.advance_last_sequence("run-v9", 1, 1234)
            return ok, sequence

        assert store.submit(pause, force_flush=True).result(timeout=10) == (True, 1)
        assert store.get_run("run-v9").status == "paused"
    finally:
        store.close()
