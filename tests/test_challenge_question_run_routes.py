from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import experiment as team_workflows_experiment


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
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": "SCI-096",
                "question_en": "How are neural signals encoded?",
            },
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

    monkeypatch.setattr(team_workflows_experiment, "get_challenge_question_run_detail", fake_detail)

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

    monkeypatch.setattr(team_workflows_experiment, "get_challenge_question_run_detail", fake_detail)

    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/questions/SCI-999"
    )

    assert response.status_code == 404
    assert "challenge_question_run_not_found" in response.json()["detail"]


def test_get_challenge_submission_readiness_returns_single_typed_artifact_list(monkeypatch):
    monkeypatch.setattr(
        team_workflows_experiment,
        "get_challenge_submission_readiness",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "blocked",
            "readyCount": 0,
            "requiredCount": 5,
            "blockerCount": 5,
            "artifacts": [
                {
                    "key": "full_catalog_results",
                    "label": "125 题结果包",
                    "required": True,
                    "status": "blocked",
                    "detail": "0/125 题已通过提交门。",
                    "blocker": "full_catalog_results_incomplete",
                    "primaryAction": {
                        "kind": "repair",
                        "target": "full-catalog-results",
                        "label": "修复缺失结果",
                        "questionId": "SCI-042",
                    },
                }
            ],
            "blockers": [{"code": "full_catalog_results_incomplete", "label": "ignored", "action": {"kind": "repair", "target": "full-catalog-results", "label": "ignored"}}],
            "programSummary": {"title": "ignored", "questionCount": 125, "approvedQuestionCount": 0, "deepExperimentCount": 2, "approvedDeepExperimentCount": 0},
            "unexpected": "ignored by bounded response model",
        },
    )

    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/submission-readiness"
    )

    assert response.status_code == 200
    assert response.json()["artifacts"][0]["primaryAction"]["kind"] == "repair"
    assert response.json()["artifacts"][0]["primaryAction"]["questionId"] == "SCI-042"
    assert response.json()["blockers"][0]["code"] == "full_catalog_results_incomplete"
    assert "unexpected" not in response.json()
