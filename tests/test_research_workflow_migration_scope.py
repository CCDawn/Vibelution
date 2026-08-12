"""T8: scope-mismatched Runs stay in the report and are not imported."""

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


def test_scope_mismatch_is_not_imported(tmp_path: Path) -> None:
    data_root = tmp_path / "research_workflows"
    write_checkpoint(data_root)
    write_legacy_run(data_root, build_legacy_run_record(runId="run-ok", threadId="thread-audittest"))
    mismatched = build_legacy_run_record(runId="run-scope", threadId="thread-audittest")
    mismatched["inputSnapshot"]["teamId"] = "other-team"
    write_legacy_run(data_root, mismatched)

    inventory = build_inventory(data_root, project_root=tmp_path, workspace_root=tmp_path / "workspace")
    labels = {entry["runId"]: entry["classification"] for entry in inventory["runs"]}
    assert labels["run-scope"] == "scope_mismatch"

    apply_report = apply_migration(
        data_root,
        project_root=tmp_path,
        backup_root=tmp_path / "backup",
        workspace_root=tmp_path / "workspace",
    )
    imported_ids = {item["runId"] for item in apply_report["imported"]}
    assert "run-ok" in imported_ids
    assert "run-scope" not in imported_ids

    store = WorkflowLedgerStore(data_root / "workflow-ledger.sqlite")
    store.open()
    try:
        assert store.get_run("run-scope") is None
        assert store.get_run("run-ok") is not None
    finally:
        store.close()
