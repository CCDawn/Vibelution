"""T1 RED: Ledger schema — migrations, checksum, FK, corruption fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import (
    WorkflowLedgerCorruptionError,
    WorkflowLedgerSchemaError,
    WorkflowLedgerStore,
)
from core.research.workflow.ledger.schema import MIGRATIONS, SCHEMA_VERSION
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
