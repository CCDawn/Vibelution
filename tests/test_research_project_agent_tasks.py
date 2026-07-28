from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.research_project_agent_tasks import (
    ResearchProjectAgentTaskError,
    get_research_project_agent_task_context,
    get_research_project_agent_task_status,
    start_research_project_agent_task,
    update_research_project_agent_task_status,
)
from core.web.services.team_workflow.experiment_kernel import (
    _select_experiment_stage_round,
)


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        project_agent_bus_service,
        session_service,
        team_service,
        team_workflow_orchestration_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)


def _team_project_and_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    role_specs = (
        ("experiment_planner", "challenge_cup_experiment_planner", "实验规划"),
        ("experiment_ledger", "challenge_cup_experiment_ledger", "实验证据"),
        ("iteration_planner", "challenge_cup_iteration_planner", "迭代决策"),
        ("iteration_versioning", "challenge_cup_versioning", "版本治理"),
    )
    members = []
    agents = {}
    for team_role, role_key, label in role_specs:
        agent = agent_directory_service.create_agent_instance(
            display_name=label,
            role_key=role_key,
        )
        agents[team_role] = agent
        members.append(
            {
                "agentId": agent["agentId"],
                "agentName": label,
                "role": team_role,
            }
        )
    team = team_service.create_team(name="科研团队", members=members)
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "层级反馈实验"},
    )["project"]
    return team, project, agents


def _accepted_submitter(monkeypatch):
    calls: list[dict] = []

    def fake_submit(session_id: str, content: str, **kwargs):
        calls.append(
            {
                "sessionId": session_id,
                "content": content,
                "kwargs": kwargs,
            }
        )
        return {
            "accepted": True,
            "turnId": f"turn-{len(calls)}",
            "status": "running",
            "acceptedAt": "2026-07-28T00:00:00+00:00",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    return calls


def _client() -> TestClient:
    return TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )


def test_task_start_resolves_fixed_role_and_replays_idempotently(
    tmp_path, monkeypatch
):
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)

    first = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "design-stage-round-1",
            "returnTo": "/teams?team=research",
            "returnLabel": "返回科研工作台",
        },
    )
    replay = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "design-stage-round-1",
        },
    )

    assert first["task"]["agentId"] == agents["experiment_planner"]["agentId"]
    assert first["task"]["roleKey"] == "challenge_cup_experiment_planner"
    assert first["task"]["roleLabel"] == "实验规划"
    assert first["task"]["status"] == "running"
    assert first["task"]["sessionTitle"] == "层级反馈实验｜实验规划"
    assert first["task"]["turn"]["turnId"] == "turn-1"
    assert first["chatRoute"] == first["task"]["chatRoute"]
    assert replay["idempotentReplay"] is True
    assert replay["task"]["taskId"] == first["task"]["taskId"]
    assert replay["task"]["sessionId"] == first["task"]["sessionId"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["turn_mode"] == "task"
    assert calls[0]["kwargs"]["message_metadata"]["researchProjectId"] == project["projectId"]


def test_different_project_roles_use_distinct_flat_sessions(tmp_path, monkeypatch):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)

    planner = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "planner-1",
        },
    )
    ledger = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_evidence_review",
            "targetRef": "plan-1",
            "idempotencyKey": "ledger-1",
        },
    )

    assert planner["task"]["sessionId"] != ledger["task"]["sessionId"]
    assert planner["task"]["sessionAttempt"] == 1
    assert ledger["task"]["sessionAttempt"] == 1
    assert ledger["task"]["sessionTitle"] == "层级反馈实验｜实验证据"


def test_active_task_blocks_formal_retry_then_terminal_retry_creates_attempt_two(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    first = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "iteration_decision",
            "targetRef": "loop-1",
            "idempotencyKey": "iteration-1",
        },
    )

    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="still active",
    ):
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "iteration_decision",
                "targetRef": "loop-1",
                "formalRetry": True,
                "retryTaskId": first["task"]["taskId"],
                "idempotencyKey": "iteration-retry-active",
            },
        )

    update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        first["task"]["taskId"],
        status="failed",
        result_refs=["loop-1"],
    )
    retry = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "iteration_decision",
            "targetRef": "loop-1",
            "formalRetry": True,
            "retryTaskId": first["task"]["taskId"],
            "idempotencyKey": "iteration-retry-1",
        },
    )

    assert retry["task"]["sessionAttempt"] == 2
    assert retry["task"]["sessionId"] != first["task"]["sessionId"]
    assert retry["task"]["retryOfSessionId"] == first["task"]["sessionId"]
    assert retry["task"]["retrySourceTaskId"] == first["task"]["taskId"]
    assert retry["task"]["sessionTitle"] == "层级反馈实验｜迭代决策｜重试 2"


def test_public_task_status_is_project_scoped_and_path_prompt_secret_free(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "version_governance",
            "targetRef": "candidate-1",
            "idempotencyKey": "version-1",
        },
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    encoded = json.dumps(status, ensure_ascii=False).lower()

    assert status["researchProjectId"] == project["projectId"]
    assert status["tasks"][0]["roleKey"] == "challenge_cup_versioning"
    assert "storagepath" not in encoded
    assert "prompt" not in encoded
    assert "secret" not in encoded
    assert str(tmp_path).lower() not in encoded


def test_task_start_rejects_missing_fixed_role_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="无实验职责团队", members=[])
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "无绑定实验"},
    )["project"]

    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="is not bound",
    ) as exc_info:
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "experiment_design",
                "idempotencyKey": "missing-role",
            },
        )

    assert exc_info.value.code == "agent_role_unbound"


def test_agent_task_routes_expose_typed_start_and_status_payloads(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    client = _client()
    base = (
        f"/api/teams/{team['teamId']}/workflow-orchestration/"
        f"research-projects/{project['projectId']}/agent-tasks"
    )

    started = client.post(
        f"{base}/start",
        json={
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "route-design-1",
        },
    )
    status_response = client.get(f"{base}/status")

    assert started.status_code == 201
    assert started.json()["task"]["taskKind"] == "experiment_design"
    assert started.json()["task"]["turn"]["turnId"] == "turn-1"
    assert status_response.status_code == 200
    assert status_response.json()["tasks"][0]["taskId"] == started.json()["task"]["taskId"]


def test_experiment_task_context_is_project_scoped_and_bounded(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-project-a",
            "idempotencyKey": "design-context-project-a",
        },
    )
    other_project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "另一个项目"},
    )["project"]
    plan_store = {
        "plans": [
            {
                "planId": "plan-project-a",
                "researchProjectId": project["projectId"],
                "experimentName": project["name"],
                "title": "本项目计划",
                "status": "draft",
                "revision": 2,
                "stageRoundId": "stage-round-project-a",
                "experimentContract": {
                    "researchQuestion": "Does A improve?",
                    "dataset": "dataset-a",
                    "baseline": "baseline-a",
                    "metrics": ["metric-a"],
                },
                "readiness": {"readyForPlanReview": True},
                "activeFullRunResult": {
                    "fullRunResultId": "full-result-a",
                    "status": "passed",
                    "metricName": "accuracy",
                    "metricValue": "0.91",
                    "delta": "+0.02",
                    "resultPath": str(tmp_path / "must-not-leak.json"),
                    "logRef": str(tmp_path / "must-not-leak.log"),
                },
                "updatedAt": "2026-07-28T01:00:00+00:00",
            },
            {
                "planId": "plan-project-b",
                "researchProjectId": other_project["projectId"],
                "experimentName": other_project["name"],
                "title": "其他项目计划",
                "status": "draft",
            },
        ]
    }
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda _team_id: plan_store,
    )

    context = get_research_project_agent_task_context(
        team["teamId"],
        project["projectId"],
        started["task"]["taskId"],
    )
    encoded = json.dumps(context, ensure_ascii=False).lower()

    assert context["task"]["taskKind"] == "experiment_design"
    assert context["experiment"]["planCount"] == 1
    assert context["experiment"]["plans"][0]["planId"] == "plan-project-a"
    assert context["experiment"]["plans"][0]["fullRunResult"] == {
        "resultId": "full-result-a",
        "status": "passed",
        "metricName": "accuracy",
        "metricValue": "0.91",
        "delta": "+0.02",
    }
    assert "plan-project-b" not in encoded
    assert "storagepath" not in encoded
    assert str(tmp_path).lower() not in encoded


def test_experiment_stage_round_selection_is_project_scoped():
    rounds = [
        {
            "stageRoundId": "round-project-a",
            "stageType": "experiment",
            "researchProjectId": "project-a",
            "status": "planning",
            "createdAt": "2026-07-28T01:00:00+00:00",
        },
        {
            "stageRoundId": "round-project-b",
            "stageType": "experiment",
            "researchProjectId": "project-b",
            "status": "planning",
            "createdAt": "2026-07-28T02:00:00+00:00",
        },
    ]

    selected = _select_experiment_stage_round(
        {"researchProjectId": "project-a"},
        rounds,
    )

    assert selected["stageRoundId"] == "round-project-a"
