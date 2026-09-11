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


def test_question_run_status_exposes_registration_without_requiring_validation(monkeypatch):
    monkeypatch.setattr(team_workflows_experiment, "get_challenge_question_run_status", lambda team_id: {
        "teamId": team_id,
        "summary": {"registeredQuestionIds": ["SCI-004"], "validatedQuestionIds": []},
    })
    response = _client().get(
        "/api/teams/research-team/workflow-orchestration/challenge-program/question-runs/status"
    )
    assert response.status_code == 200
    assert response.json()["summary"]["registeredQuestionIds"] == ["SCI-004"]


def test_reverify_citations_post_passes_ids_through_and_returns_service_report(monkeypatch):
    calls: list[tuple[str, str, str]] = []
    report = {
        "status": "reverified",
        "record": {"recordId": "SCI-096:stage1-sci-096-v3", "citationValidation": "passed"},
        "citation": {"status": "passed"},
        "verification": {"verifiedSourceUrls": {"https://doi.org/10.1/x": True}, "attemptedCount": 1, "verifiedCount": 1},
    }

    def fake_reverify(team_id: str, question_id: str, run_id: str) -> dict:
        calls.append((team_id, question_id, run_id))
        return report

    monkeypatch.setattr(team_workflows_experiment, "reverify_citation_receipts", fake_reverify)

    response = _client().post(
        "/api/teams/research-team/workflow-orchestration/challenge-program"
        "/questions/SCI-096/runs/stage1-sci-096-v3/reverify-citations"
    )

    assert response.status_code == 200
    assert calls == [("research-team", "SCI-096", "stage1-sci-096-v3")]
    assert response.json() == report


def test_repair_registration_post_passes_ids_through_and_returns_service_report(monkeypatch):
    calls: list[tuple[str, str, str]] = []
    report = {
        "teamId": "research-team",
        "questionId": "SCI-096",
        "runId": "stage1-sci-096-v3",
        "repaired": False,
        "reason": "canonical_result_package_already_bound",
        "officialModelCall": True,
        "record": {"recordId": "SCI-096:stage1-sci-096-v3"},
    }

    def fake_repair(team_id: str, question_id: str, run_id: str) -> dict:
        calls.append((team_id, question_id, run_id))
        return report

    monkeypatch.setattr(
        team_workflows_experiment,
        "repair_challenge_question_output_registration",
        fake_repair,
    )

    response = _client().post(
        "/api/teams/research-team/workflow-orchestration/challenge-program"
        "/questions/SCI-096/runs/stage1-sci-096-v3/repair-registration"
    )

    assert response.status_code == 200
    assert calls == [("research-team", "SCI-096", "stage1-sci-096-v3")]
    assert response.json()["repaired"] is False
    assert response.json()["reason"] == "canonical_result_package_already_bound"


def test_challenge_question_run_repair_routes_map_errors_like_neighbors(monkeypatch):
    def missing_record(team_id: str, question_id: str, run_id: str) -> dict:
        raise ValueError("Challenge question run record was not found.")

    def missing_team(team_id: str, question_id: str, run_id: str) -> dict:
        from core.web.services.team_service import TeamNotFoundError

        raise TeamNotFoundError("team not found: research-team")

    monkeypatch.setattr(team_workflows_experiment, "reverify_citation_receipts", missing_team)
    missing_team_response = _client().post(
        "/api/teams/research-team/workflow-orchestration/challenge-program"
        "/questions/SCI-096/runs/stage1-sci-096-v3/reverify-citations"
    )
    assert missing_team_response.status_code == 404

    monkeypatch.setattr(team_workflows_experiment, "reverify_citation_receipts", missing_record)
    value_error_response = _client().post(
        "/api/teams/research-team/workflow-orchestration/challenge-program"
        "/questions/SCI-096/runs/stage1-sci-096-v3/reverify-citations"
    )
    assert value_error_response.status_code == 422
    assert "Challenge question run record was not found." in value_error_response.json()["detail"]

    monkeypatch.setattr(
        team_workflows_experiment,
        "repair_challenge_question_output_registration",
        missing_record,
    )
    repair_error_response = _client().post(
        "/api/teams/research-team/workflow-orchestration/challenge-program"
        "/questions/SCI-096/runs/stage1-sci-096-v3/repair-registration"
    )
    assert repair_error_response.status_code == 422
