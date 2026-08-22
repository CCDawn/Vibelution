from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.checkpoint_store import default_checkpoint_path
from core.web.services.team_workflow.research_runtime import paths, store
from core.web.services.team_workflow.research_runtime.binding_config import (
    WorkflowBindingConfigStore,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
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
    checkpoint_path = tmp_path / "custom-checkpoint.sqlite"
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH", str(checkpoint_path))

    assert paths.research_workflow_data_root() == data_root
    assert paths.workflow_ledger_path() == ledger_path
    assert store.default_run_store_dir() == run_store
    assert WorkflowBindingConfigStore().root == run_store / "binding_config"
    assert default_checkpoint_path() == checkpoint_path
    assert ResearchWorkflowRuntimeService()._checkpoint_path == str(checkpoint_path)


def test_direct_backend_defaults_use_canonical_project_storage(monkeypatch, tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    projects_home = tmp_path / "local-app-data" / "projects"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "missing-config.toml"))
    for name in (
        "VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT",
        "VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE",
        "VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    canonical_data = _write_completed_storage_marker(project_root, projects_home)
    expected_data = canonical_data / "research_workflows"

    assert default_checkpoint_path() == expected_data / "checkpoints.sqlite"
    assert WorkflowBindingConfigStore().root == expected_data / "runs" / "binding_config"
    runtime = ResearchWorkflowRuntimeService()
    assert Path(runtime._checkpoint_path) == expected_data / "checkpoints.sqlite"
    assert Path(runtime._store.root) == expected_data / "runs"


def test_data_root_override_controls_checkpoint_defaults(monkeypatch, tmp_path):
    data_root = tmp_path / "workflow-data"
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(data_root))
    monkeypatch.delenv("VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH", raising=False)

    expected = data_root / "checkpoints.sqlite"
    assert default_checkpoint_path() == expected
    runtime = ResearchWorkflowRuntimeService(run_store=store.WorkflowRunStore(tmp_path / "runs"))
    assert Path(runtime._checkpoint_path) == expected


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
