from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import data_processing_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)


def test_data_processing_route_runs_collection_slice(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()

    profiles_response = client.get("/api/data-processing/profiles")
    run_response = client.post(
        "/api/data-processing/runs",
        json={
            "profileId": "generic_document_processing",
            "title": "Generic intake",
            "scope": {"domain": "research"},
        },
    )
    run_id = run_response.json()["runId"]
    assignment_response = client.post(
        f"/api/data-processing/runs/{run_id}/collection-assignments",
        json={
            "agentRole": "data_discovery",
            "agentId": "agent-data-discovery",
            "scope": {"query": "collect sources"},
        },
    )
    assignment_id = assignment_response.json()["assignmentId"]
    output_response = client.post(
        f"/api/data-processing/runs/{run_id}/collection-assignments/{assignment_id}/outputs",
        json={
            "status": "completed",
            "records": [
                {
                    "sourceType": "url",
                    "sourceRef": "https://example.test/a",
                    "title": "Source A",
                }
            ],
        },
    )
    runs_response = client.get("/api/data-processing/runs")
    status_response = client.get(f"/api/data-processing/runs/{run_id}/status")

    assert profiles_response.status_code == 200, profiles_response.text
    assert run_response.status_code == 201, run_response.text
    assert assignment_response.status_code == 201, assignment_response.text
    assert output_response.status_code == 201, output_response.text
    assert output_response.json()["createdRecords"][0]["collectionTrace"]["agentRole"] == "data_discovery"
    assert runs_response.status_code == 200, runs_response.text
    assert runs_response.json()["runs"][0]["runId"] == run_id
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["summary"]["recordCount"] == 1
    assert status_response.json()["boundaries"]["writesKnowledgeGraph"] is False


def test_data_processing_route_reports_unknown_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()

    response = client.get("/api/data-processing/runs/missing/status")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_data_processing_route_rejects_unknown_collection_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    run_id = client.post("/api/data-processing/runs", json={}).json()["runId"]

    response = client.post(
        f"/api/data-processing/runs/{run_id}/collection-assignments",
        json={"agentRole": "neuro_specific_collector"},
    )

    assert response.status_code == 422
    assert "Unsupported collection agent role" in response.json()["detail"]
