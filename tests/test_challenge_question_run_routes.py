from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import team_workflows


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _detail() -> dict:
    return {
        "teamId": "research-team",
        "questionId": "SCI-096",
        "selectedRunId": "stage1-sci-096-v3",
        "record": {
            "recordId": "SCI-096:stage1-sci-096-v3",
            "questionId": "SCI-096",
            "runId": "stage1-sci-096-v3",
            "status": "approved",
        },
        "output": {
            "question_id": "SCI-096",
            "question_en": "How are neural signals encoded?",
            "run": {"run_id": "stage1-sci-096-v3"},
            "evidence": [],
            "hypotheses": [],
            "dimension_reviews": [],
            "feedback_iterations": [],
        },
        "runs": [
            {
                "recordId": "SCI-096:stage1-sci-096-v3",
                "questionId": "SCI-096",
                "runId": "stage1-sci-096-v3",
                "status": "approved",
            }
        ],
        "artifact": {
            "path": "C:\\data\\SCI-096\\stage1-sci-096-v3.json",
            "sha256": "a" * 64,
            "immutable": True,
        },
    }


def test_get_challenge_question_detail_exposes_explicit_read_only_contract(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def fake_detail(team_id: str, question_id: str, *, run_id: str = "") -> dict:
        calls.append((team_id, question_id, run_id))
        return _detail()

    monkeypatch.setattr(team_workflows, "get_challenge_question_run_detail", fake_detail)

    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/questions/SCI-096",
        params={"runId": "stage1-sci-096-v3"},
    )

    assert response.status_code == 200
    assert calls == [("research-team", "SCI-096", "stage1-sci-096-v3")]
    assert response.json()["questionId"] == "SCI-096"
    assert response.json()["artifact"]["immutable"] is True


def test_get_challenge_question_detail_fails_closed_instead_of_loading_active_project(monkeypatch):
    def fake_detail(team_id: str, question_id: str, *, run_id: str = "") -> dict:
        raise ValueError("challenge_question_run_not_found: no registered output exists for this question.")

    monkeypatch.setattr(team_workflows, "get_challenge_question_run_detail", fake_detail)

    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/questions/SCI-999"
    )

    assert response.status_code == 404
    assert "challenge_question_run_not_found" in response.json()["detail"]
