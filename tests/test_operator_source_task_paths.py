"""Operator task ledgers fit the Windows path budget without moving evidence."""
from pathlib import Path
import json

from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.source_collection import residual, stage_reconcile


def configure(monkeypatch, tmp_path, kind="operator_knowledge"):
    run = "dprun-20260913114019913820-4e0fdb64"
    old = tmp_path / "teams" / "research-team" / "research_projects" / "research-one" / "workspace"
    dp = tmp_path / "data_processing" / "runs"
    monkeypatch.setattr(service, "_source_collection_run_workflow_root", lambda *a: old)
    monkeypatch.setattr(service, "_team_workflow_root", lambda *a: old)
    monkeypatch.setattr(service, "_candidate_store_path", lambda *a: old / "candidate_store" / "index.json")
    monkeypatch.setattr(service.developer_sandbox, "seeded_sandbox_workspace_path", lambda project, *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(service.data_processing_service, "get_processing_run_scope", lambda *a: {"scope": {"teamId": "research-team", "modelAccountingKind": kind}})
    monkeypatch.setattr(service, "_source_collection_storage_artifact_paths", residual._source_collection_storage_artifact_paths)
    return run, old, dp


def test_operator_task_ledger_reuses_short_native_processing_directory(tmp_path, monkeypatch):
    run, old, dp = configure(monkeypatch, tmp_path / "runtime-depth" / ("d" * 30))
    paths = residual._source_collection_storage_artifact_paths("research-team", run)
    task = stage_reconcile._source_collection_stage_session_task_store_path("research-team", run)
    assert task == dp / run / "stage_session_tasks.json"
    assert paths["runDirectory"] == old / "source_collection_runs" / run
    assert len((str(task) + ".lock").encode("utf-16-le")) // 2 <= 240
    service._write_json(task, {"teamId": "research-team", "runId": run, "tasks": [{"taskId": "task-one"}]})
    service._write_json(task, {"teamId": "research-team", "runId": run, "tasks": [{"taskId": "task-two"}]})
    assert json.loads(task.read_text(encoding="utf8"))["tasks"][0]["taskId"] == "task-two"
    assert stage_reconcile._find_source_collection_stage_session_task_by_id("research-team", "task-two")[1] == run
    assert stage_reconcile._find_source_collection_stage_session_task_by_id("other-team", "task-two") == (None, "")
    task.unlink()
    assert not task.exists()


def test_ordinary_source_task_paths_stay_project_scoped(tmp_path, monkeypatch):
    run, old, _ = configure(monkeypatch, tmp_path, kind="")
    assert stage_reconcile._source_collection_stage_session_task_store_path("research-team", run) == old / "source_collection_runs" / run / "stage_session_tasks.json"
