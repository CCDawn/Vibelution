"""Source-collection run research-project binding tests.

The hypothesis-first chain creates collection runs scoped to one question's
formal workflow run.  Those runs must bind the question's canonical research
project (resolved from the question binding) even when the operator's
active-project pointer still sits on an older project; every non-workflow
caller keeps the strict active-project rule.
"""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    data_processing_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import research_projects
from tests._support.team_workflow.helpers import (
    _capture_workflow_events,
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


def test_default_project_run_writeback_survives_active_project_switch(tmp_path, monkeypatch) -> None:
    """ISS-039 回归：默认(legacy)项目的 run 在切换到隔离活跃项目后写回仍成功。

    Run 落盘固定在 run owner 项目的 workspace（legacy → formal team 根），
    任务查找的搜索根必须显式覆盖该位置，不能只靠随活跃项目漂移的 glob。
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _capture_workflow_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-default-project-writeback",
            "status": "running",
        },
    )
    team = team_service.create_team(name="挑战杯科研团队")
    team_id = team["teamId"]

    response = team_workflow_orchestration_service.start_source_collection_run(
        team_id,
        _start_payload(scope={"workflowRunId": "run-default-project-writeback"}),
    )
    run_id = response["run"]["runId"]
    assert response["run"]["scope"]["researchProjectId"] == research_projects.LEGACY_PROJECT_ID
    data_processing_service.add_record(run_id, {
        "sourceType": "url",
        "sourceRef": "https://example.test/default-project-source",
        "title": "Default project source",
        "summary": "A raw record so the extraction stage advance gate opens.",
    })

    extractor = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=extractor["agentId"], title="资料提炼")
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team_id,
        run_id,
        {"stageId": "extraction", "agentId": extractor["agentId"], "agentRole": "source_extractor"},
    )
    task_id = task["taskId"]

    isolated = team_workflow_orchestration_service.create_research_project(
        team_id,
        {"name": "Isolated experiment", "topic": "isolated experiment"},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(team_id, isolated["projectId"])

    found, found_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team_id, task_id,
    )
    assert found is not None
    assert found_run_id == run_id

    writeback = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team_id,
        task_id,
        {"status": "needs_review", "summary": "Persist default-project finding batch"},
    )
    assert writeback["task"]["taskId"] == task_id
