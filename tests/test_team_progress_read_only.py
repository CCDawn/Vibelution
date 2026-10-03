import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows import research_projects as research_project_routes
from core.web.services import (
    data_processing_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import research_projects as research_project_service
from core.web.services.team_workflow.research_project_agent_tasks import (
    research_project_iteration_readiness,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _progress_paths(monkeypatch, tmp_path, team_id):
    project_store_path = tmp_path / "team-state" / "research_projects" / "index.json"
    workflow_root = tmp_path / "team-state" / "active-project"
    runs_root = tmp_path / "data-processing" / "runs"
    paths = {
        "project_store": project_store_path,
        "stage_store": workflow_root / "research_stage_rounds" / "index.json",
        "candidate_store": workflow_root / "candidate_store" / "index.json",
        "plan_store": workflow_root / "experiment_plans" / "index.json",
        "workflow": workflow_root / "workflow_orchestration.json",
        "runs_root": runs_root,
    }

    monkeypatch.setattr(
        research_project_service,
        "_store_path",
        lambda _team_id: paths["project_store"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_stage_round_store_path",
        lambda _team_id, _project_id="": paths["stage_store"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_candidate_store_path",
        lambda _team_id, _run_id="", research_project_id="": paths["candidate_store"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_experiment_plan_store_path",
        lambda _team_id, _project_id="": paths["plan_store"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_workflow_path",
        lambda _team_id, _project_id="": paths["workflow"],
    )
    monkeypatch.setattr(data_processing_service, "_runs_root", lambda: runs_root)
    monkeypatch.setattr(
        team_service,
        "_load_index",
        lambda: {
            "teams": [
                {
                    "teamId": team_id,
                    "name": "Progress test team",
                    "linkedChatRoomId": "room-progress",
                }
            ]
        },
    )
    monkeypatch.setattr(
        team_service,
        "get_team",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("progress must not call the repairing Team detail loader")
        ),
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_relative_path",
        lambda path: str(path),
    )
    return paths


def _reject_writes(monkeypatch):
    writes = []
    events = []

    def reject_write(*args, **kwargs):
        writes.append((args, kwargs))
        raise AssertionError("progress must not write persisted state")

    def reject_event(*args, **kwargs):
        events.append((args, kwargs))
        raise AssertionError("progress must not record workflow events")

    for owner in (
        research_project_service,
        team_service,
        team_workflow_orchestration_service,
        data_processing_service,
    ):
        if hasattr(owner, "_write_json"):
            monkeypatch.setattr(owner, "_write_json", reject_write)
    monkeypatch.setattr(team_service, "_save_index", reject_write)
    monkeypatch.setattr(
        research_project_service,
        "_record_project_event",
        reject_event,
    )
    monkeypatch.setattr(team_service, "_record_team_event", reject_event)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_record_workflow_event",
        reject_event,
    )
    monkeypatch.setattr(
        data_processing_service,
        "_record_data_processing_event",
        reject_event,
    )
    for loader_name in (
        "_load_stage_round_store",
        "_load_candidate_store",
        "_load_experiment_plan_store",
        "_load_or_create_workflow",
    ):
        monkeypatch.setattr(
            team_workflow_orchestration_service,
            loader_name,
            reject_write,
        )
    return writes, events


def _get_progress(team_id, project_id):
    app = FastAPI()
    app.include_router(research_project_routes.router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get(
            f"/api/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/progress"
        )


def test_research_project_progress_reads_persisted_facts_without_reconciling_bad_task(
    tmp_path,
    monkeypatch,
):
    team_id = "team-progress"
    project_id = "project-active"
    paths = _progress_paths(monkeypatch, tmp_path, team_id)
    run_id = "run-target"

    _write_json(
        paths["project_store"],
        {
            "schemaVersion": 1,
            "teamId": team_id,
            "activeProjectId": project_id,
            "projects": [
                {
                    "projectId": project_id,
                    "name": "Active project",
                    "createdAt": "project-created-at",
                    "updatedAt": "project-updated-at",
                }
            ],
        },
    )
    _write_json(
        paths["stage_store"],
        {
            "updatedAt": "stage-store-updated-at",
            "rounds": [
                {"stageRoundId": "target-experiment", "stageType": "experiment", "researchProjectId": project_id},
                {"stageRoundId": "foreign-experiment", "stageType": "experiment", "researchProjectId": "project-foreign"},
                {"stageRoundId": "target-iteration", "stageType": "iteration", "researchProjectId": project_id},
                {"stageRoundId": "foreign-knowledge", "stageType": "knowledge_collection", "researchProjectId": "project-foreign"},
            ],
        },
    )
    _write_json(
        paths["candidate_store"],
        {
            "candidates": [
                {"candidateId": "source-target", "candidateType": "source_manifest", "researchProjectId": project_id},
                {
                    "candidateId": "malformed-graph-target",
                    "candidateType": "candidate_graph",
                    "researchProjectId": project_id,
                    "metadata": {"graph": {"nodes": {"count": 1}, "edges": []}},
                },
                {"candidateId": "source-foreign", "candidateType": "source_manifest", "researchProjectId": "project-foreign"},
            ],
        },
    )
    _write_json(
        paths["plan_store"],
        {
            "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
            "teamId": team_id,
            "plans": [
                {
                    "planId": "target-plan",
                    "teamId": team_id,
                    "researchProjectId": project_id,
                    "designFrozen": True,
                    "experimentContract": {"schemaVersion": 2, "revision": 1},
                    "contractValidation": {"valid": True},
                    "readiness": {"readyForPlanReview": True},
                    "designGate": {"status": "frozen"},
                    "activeSmokeRun": {"smokeRunId": "smoke-needs-review", "status": "needs_review"},
                },
                {
                    "planId": "foreign-plan",
                    "teamId": team_id,
                    "researchProjectId": "project-foreign",
                    "designFrozen": True,
                    "experimentContract": {"schemaVersion": 2, "revision": 1},
                    "contractValidation": {"valid": True},
                    "readiness": {"readyForPlanReview": True},
                    "designGate": {"status": "frozen"},
                },
            ],
        },
    )
    # An empty workflow is repairable in memory, but the GET must leave its
    # persisted bytes untouched and emit no created/repair event.
    _write_json(paths["workflow"], {})
    workflow_before = paths["workflow"].read_bytes()
    _write_json(
        paths["runs_root"] / run_id / "run.json",
        {
            "runId": run_id,
            "status": "completed",
            "metadata": {
                "startedFrom": "team_workflow_source_collection",
                "teamId": team_id,
                "researchProjectId": project_id,
            },
        },
    )

    invalid_task_result = {"candidateGraph": {"nodes": {"count": 1}, "edges": []}}
    reconciliation_calls = []

    def reconcile_bad_fixture(requested_team_id):
        reconciliation_calls.append(requested_team_id)
        team_workflow_orchestration_service._source_collection_stage_writeback_agent_graph_payload(
            invalid_task_result
        )

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_reconcile_source_collection_stage_session_tasks",
        reconcile_bad_fixture,
    )
    expected_readiness = research_project_iteration_readiness(team_id, project_id)
    writes, events = _reject_writes(monkeypatch)

    response = _get_progress(team_id, project_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["researchProjectId"] == project_id
    assert payload["sourceRunCount"] == 1
    assert payload["sourceCandidateCount"] == 1
    assert payload["downstreamCandidateCount"] == 1
    assert payload["stageRoundCounts"] == {
        "knowledge_collection": 0,
        "experiment": 1,
        "iteration": 1,
    }
    assert payload["experimentPlanCount"] == 1
    assert payload["frozenExperimentPlanCount"] == 1
    assert payload["updatedAt"] == "stage-store-updated-at"
    assert payload["phases"][-1]["readiness"] == {
        **expected_readiness,
        "reason": expected_readiness["reasonZh"],
    }
    assert paths["workflow"].read_bytes() == workflow_before
    assert reconciliation_calls == []
    assert writes == []
    assert events == []


def test_research_project_progress_does_not_create_missing_stores(tmp_path, monkeypatch):
    team_id = "team-progress-missing"
    project_id = research_project_service.LEGACY_PROJECT_ID
    paths = _progress_paths(monkeypatch, tmp_path, team_id)
    writes, events = _reject_writes(monkeypatch)

    response = _get_progress(team_id, project_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["researchProjectId"] == project_id
    assert payload["sourceRunCount"] == 0
    assert payload["sourceCandidateCount"] == 0
    assert payload["downstreamCandidateCount"] == 0
    assert payload["stageRoundCounts"] == {
        "knowledge_collection": 0,
        "experiment": 0,
        "iteration": 0,
    }
    assert payload["experimentPlanCount"] == 0
    assert not paths["project_store"].exists()
    assert not paths["stage_store"].exists()
    assert not paths["candidate_store"].exists()
    assert not paths["plan_store"].exists()
    assert not paths["workflow"].exists()
    assert writes == []
    assert events == []

    _write_json(
        paths["project_store"],
        {
            "schemaVersion": 1,
            "teamId": team_id,
            "activeProjectId": project_id,
            "projects": [
                {
                    "projectId": project_id,
                    "name": "Legacy project",
                    "createdAt": "project-created-at",
                    "updatedAt": "project-updated-at-stable",
                }
            ],
        },
    )
    first_missing_stage = _get_progress(team_id, project_id)
    second_missing_stage = _get_progress(team_id, project_id)

    assert first_missing_stage.status_code == 200, first_missing_stage.text
    assert second_missing_stage.status_code == 200, second_missing_stage.text
    assert first_missing_stage.json()["updatedAt"] == "project-updated-at-stable"
    assert second_missing_stage.json()["updatedAt"] == "project-updated-at-stable"
    assert not paths["stage_store"].exists()
    assert writes == []
    assert events == []

    _write_json(
        paths["stage_store"],
        {
            "updatedAt": "stage-store-with-iteration",
            "rounds": [
                {"stageRoundId": "experiment", "stageType": "experiment", "researchProjectId": project_id},
                {"stageRoundId": "iteration", "stageType": "iteration", "researchProjectId": project_id},
            ],
        },
    )
    stage_before = paths["stage_store"].read_bytes()

    response_with_iteration = _get_progress(team_id, project_id)

    assert response_with_iteration.status_code == 200, response_with_iteration.text
    iteration_payload = response_with_iteration.json()
    assert iteration_payload["phases"][-1]["readiness"]["code"] == "missing_frozen_experiment_design"
    assert iteration_payload["phases"][-1]["readiness"]["reason"] == "需要先冻结一份可执行的实验设计。"
    assert paths["stage_store"].read_bytes() == stage_before
    assert not paths["plan_store"].exists()
    assert not paths["workflow"].exists()
    assert writes == []
    assert events == []
