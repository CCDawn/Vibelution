"""T8 apply/verify: migratable JSON Runs land in Ledger with matching counts/hash."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.migration.importer import apply_migration
from core.research.workflow.migration.manifest import ManifestStatus, load_manifest
from core.research.workflow.migration.verifier import verify_migration
from tests._support.workflow_migration_fixtures import (
    build_legacy_run_record,
    write_checkpoint,
    write_legacy_run,
)


def test_apply_and_verify_match_counts_hash_and_lineage(tmp_path: Path) -> None:
    data_root = tmp_path / "research_workflows"
    write_checkpoint(data_root)
    write_legacy_run(data_root, build_legacy_run_record(runId="run-ok", threadId="thread-audittest"))
    apply_report = apply_migration(
        data_root,
        project_root=tmp_path,
        backup_root=tmp_path / "backup",
        workspace_root=tmp_path / "workspace",
    )
    assert apply_report["importedCount"] == 1
    assert apply_report["lineageHash"]
    assert (tmp_path / "backup" / "runs" / "run-ok.json").exists()

    verify_report = verify_migration(data_root)
    assert verify_report["ok"] is True
    assert verify_report["importedCount"] == 1
    assert verify_report["lineageHash"] == apply_report["lineageHash"]
    assert load_manifest(data_root)["status"] == ManifestStatus.ACTIVATED.value

    store = WorkflowLedgerStore(data_root / "workflow-ledger.sqlite")
    store.open()
    try:
        run = store.get_run("run-ok")
        assert run is not None
        assert run.team_id == "research-team"
        assert run.question_id == "SCI-096"
        assert store.latest_event_sequence("run-ok") == 1
    finally:
        store.close()
