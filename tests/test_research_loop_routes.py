from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import research_loop_service, team_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_loop_service, "PROJECT_ROOT", tmp_path)


def test_research_loop_routes_create_record_and_decide(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    team_id = team["teamId"]

    templates_response = client.get(f"/api/teams/{team_id}/workflow-orchestration/research-loop/templates")
    create_response = client.post(
        f"/api/teams/{team_id}/workflow-orchestration/research-loop/loops",
        json={
            "templateId": "algorithm_model_experiment",
            "researchQuestion": "Does the candidate routing layer improve benchmark accuracy?",
            "planId": "plan-42",
            "candidateIds": ["hypothesis-1"],
            "createdByAgent": "Experiment Planning Agent",
        },
    )
    loop = create_response.json()["loop"]

    blocked_decision = client.post(
        f"/api/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop['loopId']}/decision",
        json={
            "decision": "promote_to_iteration",
            "rationale": "Should be blocked until required evidence is present.",
        },
    )

    for evidence_type in ("baseline_artifact", "dataset_benchmark", "metric_report"):
        evidence_response = client.post(
            f"/api/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop['loopId']}/evidence",
            json={
                "evidenceType": evidence_type,
                "status": "passed",
                "summary": f"{evidence_type} registered manually.",
                "metricName": "accuracy",
                "metricValue": "0.84",
                "artifactRefs": [{"path": f"workspace/artifacts/{evidence_type}.json"}],
                "commandPreview": "python evaluate.py --config config.yaml",
                "recordedByAgent": "Experiment Planning Agent",
            },
        )
        assert evidence_response.status_code == 201, evidence_response.text

    decision_response = client.post(
        f"/api/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop['loopId']}/decision",
        json={
            "decision": "promote_to_iteration",
            "rationale": "All required manual evidence records are present.",
            "nextTemplateId": "dataset_benchmark",
            "nextActions": ["record full-run result in experiment ledger"],
            "decidedByAgent": "Research Coordination Agent",
        },
    )
    status_response = client.get(f"/api/teams/{team_id}/workflow-orchestration/research-loop/status")

    assert templates_response.status_code == 200, templates_response.text
    assert templates_response.json()["boundaries"]["sandboxRunner"] is False
    assert create_response.status_code == 201, create_response.text
    assert loop["executionPolicy"]["autoExecution"] is False
    assert blocked_decision.status_code == 422, blocked_decision.text
    assert decision_response.status_code == 201, decision_response.text
    assert decision_response.json()["loop"]["status"] == "ready_for_iteration"
    assert decision_response.json()["iterationProposal"]["nextTemplateId"] == "dataset_benchmark"
    assert status_response.json()["summary"]["readyForIterationCount"] == 1


def test_research_loop_routes_report_missing_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()

    response = client.get("/api/teams/missing-team/workflow-orchestration/research-loop/status")

    assert response.status_code == 404
