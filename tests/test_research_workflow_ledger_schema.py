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

    connection = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY)
    assert MIGRATIONS[-1].checksum != V5_LEGACY_CHECKSUM
    assert connection.execute(
        "SELECT checksum FROM schema_migrations WHERE version = 5"
    ).fetchone()[0] == MIGRATIONS[-1].checksum
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
