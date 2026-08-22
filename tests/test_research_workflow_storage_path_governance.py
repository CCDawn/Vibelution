from __future__ import annotations

import json
from pathlib import Path

from core.web.services.team_workflow.research_runtime import paths, store
from scripts import audit_research_workflow_runtime as audit
from vibelution_storage import (
    PROJECTS_HOME_ENV,
    resolve_project_storage_paths,
    storage_migration_state_path,
)


def _write_completed_storage_marker(project_root: Path, projects_home: Path) -> Path:
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    marker = storage_migration_state_path(target)
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": target.project_id,
                "instanceId": target.instance_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return target.data


def _write_project_identity(project_root: Path, project_id: str = "custom-audit-project") -> None:
    identity = project_root / ".vibelution" / "project.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(
        json.dumps({"schemaVersion": 1, "projectId": project_id}) + "\n",
        encoding="utf-8",
    )


def test_research_workflow_defaults_use_completed_canonical_project_storage(monkeypatch, tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    projects_home = tmp_path / "local-app-data" / "projects"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "missing-config.toml"))
    monkeypatch.delenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("VIBELUTION_RESEARCH_WORKFLOW_LEDGER_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", raising=False)

    canonical_data = _write_completed_storage_marker(project_root, projects_home)

    assert paths.research_workflow_data_root() == canonical_data / "research_workflows"
    assert paths.workflow_ledger_path() == canonical_data / "research_workflows" / "workflow-ledger.sqlite"
    assert store.default_run_store_dir() == canonical_data / "research_workflows" / "runs"
    assert audit.default_data_root(project_root) == canonical_data / "research_workflows"
    assert "Documents" not in str(paths.research_workflow_data_root())


def test_research_workflow_explicit_environment_overrides_remain_authoritative(monkeypatch, tmp_path):
    data_root = tmp_path / "workflow-data"
    ledger_path = tmp_path / "custom-ledger.sqlite"
    run_store = tmp_path / "custom-runs"
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(data_root))
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(run_store))

    assert paths.research_workflow_data_root() == data_root
    assert paths.workflow_ledger_path() == ledger_path
    assert store.default_run_store_dir() == run_store


def test_audit_default_data_root_follows_custom_project_root_after_parse(monkeypatch, tmp_path):
    project_root = tmp_path / "other-checkout"
    project_root.mkdir()
    _write_project_identity(project_root)
    projects_home = tmp_path / "local-app-data" / "projects"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "missing-config.toml"))

    canonical_data = _write_completed_storage_marker(project_root, projects_home)
    runs_root = canonical_data / "research_workflows" / "runs"
    runs_root.mkdir(parents=True)
    output = tmp_path / "audit.json"

    assert audit.main(["--project-root", str(project_root), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert Path(report["dataRoot"]) == canonical_data / "research_workflows"
