"""Source-collection run research-project binding tests.

The hypothesis-first chain creates collection runs scoped to one question's
formal workflow run.  Those runs must bind the question's canonical research
project (resolved from the question binding) even when the operator's
active-project pointer still sits on an older project; every non-workflow
caller keeps the strict active-project rule.
"""

from __future__ import annotations

import pytest

from core.web.services import team_service, team_workflow_orchestration_service
from core.web.services.team_workflow import research_projects
from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)


def _start_payload(**overrides) -> dict:
    payload = {
        "topic": "predictive coding",
        "agentRoles": ["source_finder"],
        "querySeeds": ["predictive coding"],
        "promptCachePolicy": {"requirement": "disabled"},
    }
    payload.update(overrides)
    return payload


def _team_with_stale_active_project(team_id: str) -> dict:
    """Active pointer on the legacy project while the question owns its own."""
    question_project = research_projects.ensure_challenge_question_project(
        team_id,
        question_id="SCI-096",
        title="How does the brain retrieve memories?",
        topic="只讨论可证伪的记忆提取机制。",
    )["project"]
    research_projects.activate_research_project(team_id, research_projects.LEGACY_PROJECT_ID)
    return question_project


def test_workflow_scoped_run_honors_question_canonical_project(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    question_project = _team_with_stale_active_project(team["teamId"])
    assert question_project["projectId"] != research_projects.LEGACY_PROJECT_ID

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        _start_payload(
            researchProjectId=question_project["projectId"],
            scope={"workflowRunId": "run-question-owned"},
        ),
    )

    run = response["run"]
    assert run["scope"]["researchProjectId"] == question_project["projectId"]
    assert run["scope"]["workflowRunId"] == "run-question-owned"
    assert run["metadata"]["researchProjectId"] == question_project["projectId"]
    assert response["researchProjectId"] == question_project["projectId"]


def test_non_workflow_scoped_run_still_rejects_project_mismatch(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    question_project = _team_with_stale_active_project(team["teamId"])

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.start_source_collection_run(
            team["teamId"],
            _start_payload(researchProjectId=question_project["projectId"]),
        )


def test_workflow_scoped_run_rejects_unknown_project(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.start_source_collection_run(
            team["teamId"],
            _start_payload(
                researchProjectId="challenge-does-not-exist",
                scope={"workflowRunId": "run-unknown-project"},
            ),
        )


def test_active_project_match_keeps_legacy_behavior(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    question_project = _team_with_stale_active_project(team["teamId"])
    active_id = research_projects.get_active_research_project(team["teamId"])["projectId"]

    # A payload whose project matches the active pointer (the workflow-run
    # adapter shape) keeps working and carries the workflow scope untouched.
    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        _start_payload(
            researchProjectId=active_id,
            scope={"workflowRunId": "run-active-project"},
        ),
    )
    assert response["run"]["scope"]["researchProjectId"] == active_id
    assert response["run"]["scope"]["researchProjectId"] != question_project["projectId"]
