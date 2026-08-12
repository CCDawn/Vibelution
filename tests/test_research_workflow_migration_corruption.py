"""T8: corrupt JSON is classified and never imported as an empty successful Run."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.migration.importer import apply_migration
from core.research.workflow.migration.inventory import build_inventory
from tests._support.workflow_migration_fixtures import (
    build_legacy_run_record,
    write_checkpoint,
    write_legacy_run,
)


def test_corrupt_json_is_not_imported(tmp_path: Path) -> None:
    data_root = tmp_path / "research_workflows"
    write_checkpoint(data_root)
    write_legacy_run(data_root, build_legacy_run_record(runId="run-ok", threadId="thread-audittest"))
    bad = data_root / "runs" / "run-corrupt.json"
    bad.write_text("{not valid json", encoding="utf-8")

    inventory = build_inventory(data_root, project_root=tmp_path, workspace_root=tmp_path / "workspace")
    labels = {entry["runId"]: entry["classification"] for entry in inventory["runs"]}
    assert labels["run-corrupt"] == "corrupt"
    assert labels["run-ok"] == "migratable"

    apply_report = apply_migration(
        data_root,
        project_root=tmp_path,
        backup_root=tmp_path / "backup",
        workspace_root=tmp_path / "workspace",
    )
    imported_ids = {item["runId"] for item in apply_report["imported"]}
    skipped = {item["runId"]: item["classification"] for item in apply_report["skipped"]}
    assert "run-ok" in imported_ids
    assert "run-corrupt" not in imported_ids
    assert skipped["run-corrupt"] == "corrupt"

    store = WorkflowLedgerStore(data_root / "workflow-ledger.sqlite")
    store.open()
    try:
        assert store.get_run("run-ok") is not None
        assert store.get_run("run-corrupt") is None
    finally:
        store.close()
