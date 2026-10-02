from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows import research_projects as research_project_routes
from core.web.services import team_service, team_workflow_orchestration_service
from core.web.services.team_workflow import research_projects as research_project_service
from core.web.services.team_workflow.source_collection import runs as source_collection_runs


def test_research_project_progress_reads_persisted_facts_without_reconciling_bad_task(
    monkeypatch,
):
    team_id = "team-progress"
    project_id = "project-active"
    invalid_task_result = {
        "candidateGraph": {
            "nodes": {"count": 1},
            "edges": [],
        },
    }
    rounds = [
        {"stageRoundId": "target-experiment", "stageType": "experiment", "researchProjectId": project_id},
        {"stageRoundId": "foreign-experiment", "stageType": "experiment", "researchProjectId": "project-foreign"},
        {"stageRoundId": "target-iteration", "stageType": "iteration", "researchProjectId": project_id},
        {"stageRoundId": "foreign-knowledge", "stageType": "knowledge_collection", "researchProjectId": "project-foreign"},
    ]
    candidates = [
        {"candidateId": "source-target", "candidateType": "source_manifest", "researchProjectId": project_id},
        {
            "candidateId": "malformed-graph-target",
            "candidateType": "candidate_graph",
            "researchProjectId": project_id,
            "metadata": {"graph": {"nodes": {"count": 1}, "edges": []}},
        },
        {"candidateId": "source-foreign", "candidateType": "source_manifest", "researchProjectId": "project-foreign"},
    ]
    plans = [
        {"planId": "target-plan", "researchProjectId": project_id, "designFrozen": True},
        {"planId": "foreign-plan", "researchProjectId": "project-foreign", "designFrozen": True},
    ]
    active_project = {
        "projectId": project_id,
        "name": "Active project",
        "updatedAt": "project-updated-at",
    }
    reconciliation_calls: list[str] = []

    def reconcile_bad_fixture(requested_team_id: str) -> None:
        reconciliation_calls.append(requested_team_id)
        team_workflow_orchestration_service._source_collection_stage_writeback_agent_graph_payload(
            invalid_task_result
        )

    monkeypatch.setattr(team_service, "get_team", lambda requested_team_id: {"teamId": requested_team_id})
    monkeypatch.setattr(
        research_project_service,
        "get_active_research_project",
        lambda requested_team_id: active_project,
    )
    monkeypatch.setattr(
        source_collection_runs,
        "_project_source_collection_run_ids",
        lambda requested_team_id, requested_project_id: {"run-target"},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_reconcile_source_collection_stage_session_tasks",
        reconcile_bad_fixture,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_stage_round_store",
        lambda requested_team_id: {"updatedAt": "stage-store-updated-at", "rounds": rounds},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_candidate_store",
        lambda requested_team_id: {"candidates": candidates},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda requested_team_id: {"plans": plans},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_or_create_workflow",
        lambda requested_team_id: {"workflowId": "workflow-target"},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_team_identity_snapshot",
        lambda requested_team_id: {"teamId": requested_team_id},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_stage_phase_status",
        lambda requested_team_id, stage_type, project_rounds, **kwargs: {
            "stageType": stage_type,
            "roundCount": sum(1 for item in project_rounds if item.get("stageType") == stage_type),
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_current_research_stage",
        lambda phases, workflow: "experiment",
    )

    app = FastAPI()
    app.include_router(research_project_routes.router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/api/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/progress"
        )

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
    assert reconciliation_calls == []
