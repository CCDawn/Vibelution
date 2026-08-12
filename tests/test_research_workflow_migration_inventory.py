"""T8 dry-run inventory: every legacy Run is classified; unknown count is zero."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.migration.inventory import build_inventory
from core.research.workflow.migration.validator import CLASSIFICATIONS, unknown_entries
from tests._support.workflow_migration_fixtures import (
    build_legacy_run_record,
    write_checkpoint,
    write_legacy_run,
)


def test_dry_run_classifies_known_categories_with_zero_unknown(tmp_path: Path) -> None:
    data_root = tmp_path / "research_workflows"
    write_checkpoint(data_root)
    write_legacy_run(data_root, build_legacy_run_record(runId="run-ok", threadId="thread-audittest"))
    write_legacy_run(
        data_root,
        build_legacy_run_record(runId="run-scope", teamId="", threadId="thread-audittest"),
    )
    report = build_inventory(data_root, project_root=tmp_path, workspace_root=tmp_path / "workspace")
    assert report["unknownCount"] == 0
    assert unknown_entries(report["runs"]) == []
    labels = {entry["classification"] for entry in report["runs"]}
    assert labels <= set(CLASSIFICATIONS)
    assert "migratable" in labels
    assert "scope_mismatch" in labels
