from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow.research_runtime import question_launch
from core.web.services.team_workflow.research_runtime import (
    service as runtime_service_module,
)
from core.web.services.team_workflow.research_runtime.service import (
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _approved_detail(question_id: str = "SCI-096") -> dict:
    return {
        "teamId": "research-team",
        "questionId": question_id,
        "selectedRunId": "stage1-sci-096-v3",
        "record": {
            "questionId": question_id,
            "runId": "stage1-sci-096-v3",
            "status": "approved",
            "humanGates": {"allApproved": True},
        },
        "output": {
            "schema_version": 1,
            "catalog_id": "science-125-questions-2021",
            "question_id": question_id,
            "question_en": "How does the brain retrieve memories?",
            "problem_understanding": {"scope": "只讨论可证伪的记忆提取机制。"},
            "research_plan": {"failure_criteria": "无法区分"},
            "final_summary": {"next_validation_step": "执行对照。"},
        },
        "artifact": {"sha256": "a" * 64, "immutable": True},
    }


def _safety_limits() -> dict:
    return {
        "stageTokens": {
            "knowledge_collection": 250000,
            "experiment_design": 250000,
            "execution_iteration": 250000,
        },
        "toolCalls": 300,
        "wallClockSeconds": 21600,
        "maxRetries": 2,
    }


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": ["SCI-096"]},
    )
    monkeypatch.setattr(
        question_launch,
        "get_challenge_question_run_detail",
        lambda _team_id, question_id: _approved_detail(question_id),
    )
    monkeypatch.setattr(
        question_launch,
        "ensure_challenge_question_project",
        lambda _team_id, **_kwargs: {"project": {"projectId": "challenge-sci-096"}},
    )


def test_launch_options_and_frozen_input_derive_from_one_approved_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_approved_question(monkeypatch)

    options = question_launch.list_question_launch_options("research-team")
    run_input = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-096",
        safety_limits=_safety_limits(),
    )

    assert options["questions"] == [
        {
            "questionId": "SCI-096",
            "title": "How does the brain retrieve memories?",
            "scope": "只讨论可证伪的记忆提取机制。",
            "catalogId": "science-125-questions-2021",
            "reviewRunId": "stage1-sci-096-v3",
            "artifactSha256": "a" * 64,
        }
    ]
    assert run_input["projectId"] == "challenge-sci-096"
    assert run_input["researchBriefHash"] == "a" * 64
    assert run_input["datasetRefs"] == [
        "challenge-question-artifact://science-125-questions-2021/SCI-096/stage1-sci-096-v3/" + "a" * 64
    ]
    assert run_input["researchObjectiveContract"]["question"] == "How does the brain retrieve memories?"
    assert run_input["budgetPolicy"]["stageBudgets"]["execution_iteration"]["tokens"] == 250000
    assert set(run_input["modelRoutingPolicy"].values()) == {"relay_openai/gpt-5.6-luna"}
    assert "projectId" not in options["questions"][0]


def test_question_launch_rejects_unapproved_questions_and_invalid_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_approved_question(monkeypatch)

    with pytest.raises(question_launch.QuestionLaunchError) as missing_question:
        question_launch.build_question_run_input(
            "research-team",
            question_id="SCI-097",
            safety_limits=_safety_limits(),
        )
    with pytest.raises(question_launch.QuestionLaunchError) as unsafe_budget:
        question_launch.build_safety_budget_policy(
            {**_safety_limits(), "toolCalls": 601}
        )

    assert missing_question.value.code == "challenge_question_not_launchable"
    assert unsafe_budget.value.code == "invalid_safety_limits"


def test_canonical_question_project_collision_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_projects.team_service, "get_team", lambda _team_id: {})
    monkeypatch.setattr(
        research_projects,
        "_load_store",
        lambda _team_id: {
            "projects": [
                {
                    "projectId": "challenge-sci-096",
                    "challengeQuestionId": "SCI-097",
                }
            ],
            "activeProjectId": "legacy-default",
        },
    )

    with pytest.raises(research_projects.ResearchProjectQuestionMismatchError):
        research_projects.ensure_challenge_question_project(
            "research-team",
            question_id="SCI-096",
            title="How does the brain retrieve memories?",
            topic="只讨论可证伪的记忆提取机制。",
        )


def test_create_endpoint_forbids_client_authored_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    canonical_input = question_launch.build_question_run_input
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(
        runtime_service_module,
        "build_question_run_input",
        lambda team_id, **kwargs: canonical_input(
            team_id,
            question_id=str(kwargs["question_id"]),
            safety_limits=kwargs["safety_limits"],
        ),
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    options = client.get(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/launch-options",
        params={"teamId": "research-team"},
    )

    rejected = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={
            "teamId": "research-team",
            "projectId": "operator-chosen-project",
            "questionId": "SCI-096",
            "researchBriefHash": "operator-authored",
            "safetyLimits": _safety_limits(),
            "idempotencyKey": "question-authority-1",
        },
    )
    accepted = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={
            "teamId": "research-team",
            "questionId": "SCI-096",
            "safetyLimits": _safety_limits(),
            "idempotencyKey": "question-authority-1",
        },
    )

    assert options.status_code == 200
    assert options.json()["questions"][0]["questionId"] == "SCI-096"
    assert rejected.status_code == 422
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["projectId"] == "challenge-sci-096"
    assert body["inputSnapshot"]["researchBriefHash"] == "a" * 64
    assert body["inputSnapshot"]["createdBy"] == "operator"
