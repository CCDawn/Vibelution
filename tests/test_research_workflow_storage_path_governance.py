from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.checkpoint_store import default_checkpoint_path
from core.research import formal_runner
from core.infrastructure import developer_sandbox
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow.experiment_api import full_run as full_run_api
from core.web.services.team_workflow import experiment_kernel
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


def test_formal_product_execution_config_binds_output_to_current_canonical_root(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    _write_project_identity(project_root, "canonical-writer-test")
    canonical_data = tmp_path / "canonical-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(canonical_data))
    fake_service = SimpleNamespace(
        formal_runner=formal_runner,
        TeamWorkflowOrchestrationError=RuntimeError,
    )
    monkeypatch.setattr(full_run_api, "_service", lambda: fake_service)

    output_root = canonical_data / "challenge-cup" / "formal-runs"
    bound = full_run_api._bind_formal_execution_config(
        {"outputRoot": str(output_root), "timeoutSeconds": 120},
        project_root=project_root,
    )

    assert Path(bound["outputRoot"]) == output_root.resolve()
    assert bound["timeoutSeconds"] == 120
    assert not output_root.exists()


@pytest.mark.parametrize(
    "output_root",
    [
        "checkout/artifacts",
        "other-instance/data/formal-runs",
        ".runtime/developer-mode/sandboxes/sandbox-1/workspace/teams/team-a",
    ],
)
def test_formal_product_execution_config_rejects_noncanonical_output_roots(
    monkeypatch, tmp_path, output_root
):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    _write_project_identity(project_root, "canonical-writer-test")
    canonical_data = tmp_path / "canonical-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(canonical_data))
    fake_service = SimpleNamespace(
        formal_runner=formal_runner,
        TeamWorkflowOrchestrationError=RuntimeError,
    )
    monkeypatch.setattr(full_run_api, "_service", lambda: fake_service)

    candidate = tmp_path / output_root
    with pytest.raises(RuntimeError, match="current project canonical data root"):
        full_run_api._bind_formal_execution_config(
            {"outputRoot": str(candidate)},
            project_root=project_root,
        )

    assert not candidate.exists()


def test_formal_product_execution_config_rejects_relative_output_root(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    _write_project_identity(project_root, "canonical-writer-test")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "canonical-data"))
    fake_service = SimpleNamespace(
        formal_runner=formal_runner,
        TeamWorkflowOrchestrationError=RuntimeError,
    )
    monkeypatch.setattr(full_run_api, "_service", lambda: fake_service)

    with pytest.raises(RuntimeError, match="absolute path"):
        full_run_api._bind_formal_execution_config(
            {"outputRoot": "canonical-data/formal-runs"},
            project_root=project_root,
        )


def test_formal_team_workspace_root_does_not_follow_developer_sandbox(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    _write_project_identity(project_root, "canonical-writer-test")
    canonical_data = tmp_path / "canonical-data"
    sandbox_root = tmp_path / "sandbox" / "workspace"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(canonical_data))
    monkeypatch.setattr(research_projects, "_project_root", lambda: project_root)
    monkeypatch.setattr(
        developer_sandbox,
        "seeded_sandbox_workspace_path",
        lambda _root, *parts: sandbox_root.joinpath(*parts),
    )

    formal_root = research_projects.formal_team_workspace_root("team-alpha")

    assert formal_root == canonical_data / "workspace" / "teams" / "team-alpha"
    assert not formal_root.is_relative_to(sandbox_root)


def test_formal_receipt_locators_use_the_same_canonical_root_guard(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    _write_project_identity(project_root, "canonical-writer-test")
    canonical_data = tmp_path / "canonical-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(canonical_data))

    def trim(value, *, max_length):
        return str(value or "").strip()[:max_length]

    fake_service = SimpleNamespace(
        _trim_text=trim,
        formal_runner=formal_runner,
        PROJECT_ROOT=project_root,
        TeamWorkflowOrchestrationError=RuntimeError,
    )
    monkeypatch.setattr(experiment_kernel, "_service", lambda: fake_service)

    accepted = canonical_data / "challenge-cup" / "formal-runs" / "result.json"
    accepted.parent.mkdir(parents=True)
    accepted.write_text("{}", encoding="utf-8")
    assert experiment_kernel._canonical_formal_path(accepted, label="resultPath") == str(
        accepted.resolve()
    )
    assert experiment_kernel._canonical_formal_path(
        "", label="configPath", required=False
    ) == ""

    for rejected in (
        project_root / "artifacts" / "result.json",
        tmp_path / "other-instance" / "data" / "result.json",
        tmp_path / ".runtime" / "developer-mode" / "sandboxes" / "result.json",
    ):
        with pytest.raises(RuntimeError, match="current project canonical data root"):
            experiment_kernel._canonical_formal_path(rejected, label="resultPath")
