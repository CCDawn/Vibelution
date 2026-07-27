from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    data_processing_service,
    project_agent_bus_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.research_project_agent_sessions import (
    ResearchProjectAgentSessionError,
    resolve_research_project_agent_session,
)


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        data_processing_service,
        project_agent_bus_service,
        session_service,
        team_knowledge_service,
        team_service,
        team_workflow_orchestration_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)


def _project_and_agent(tmp_path, monkeypatch, *, project_name: str = "层级反馈实验"):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        role_key="source_finder",
    )
    legacy_direct_session = session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"],
        title="旧直连会话",
    )
    team = team_service.create_team(
        name="科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": "资料寻找",
                "role": "source_finder",
            }
        ],
    )
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": project_name},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(
        team["teamId"],
        project["projectId"],
    )
    return team, project, agent, legacy_direct_session


def _fake_local_research_public_config() -> dict:
    return {
        "llm": {
            "profiles": {},
            "model_library": {
                "local_research_model": {
                    "model": "qwen-local",
                    "provider": "local",
                    "prompt_cache": {"mode": "explicit_cache_control"},
                }
            },
        }
    }


def test_same_project_agent_reuses_flat_session_without_touching_direct_session(
    tmp_path, monkeypatch
):
    team, project, agent, legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )

    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        created_from_task_id="task-1",
    )
    second = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="task-2",
    )

    assert first["sessionCreated"] is True
    assert first["sessionAttempt"] == 1
    assert first["sessionTitle"] == "层级反馈实验｜资料寻找"
    assert first["chatRoute"] == f"/chat?session={first['sessionId']}"
    assert second["sessionCreated"] is False
    assert second["sessionId"] == first["sessionId"]
    session_detail = session_service.get_session_detail(first["sessionId"])
    experiment_binding = session_detail["experimentBinding"]
    assert experiment_binding == {
        "teamId": team["teamId"],
        "researchProjectId": project["projectId"],
        "experimentName": "层级反馈实验",
        "agentId": agent["agentId"],
        "roleKey": "source_finder",
        "roleLabel": "资料寻找",
        "attempt": 1,
        "retryOfSessionId": "",
        "createdFromTaskId": "task-1",
        "createdAt": experiment_binding["createdAt"],
    }
    assert session_detail["agentDirectSessionMismatch"] is False
    assert (
        agent_directory_service.get_agent(agent["agentId"])["directSessionId"]
        == legacy_direct_session["id"]
    )
    assert session_service.get_session_detail(legacy_direct_session["id"]) is not None


def test_project_or_agent_change_creates_a_different_flat_session(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    other_agent = agent_directory_service.create_agent_instance(
        display_name="资料提炼",
        role_key="source_extractor",
    )
    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
    )
    other_agent_session = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=other_agent["agentId"],
        role_key="source_extractor",
        role_label="资料提炼",
    )
    other_project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "另一个实验"},
    )["project"]
    other_project_session = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=other_project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
    )

    assert (
        len(
            {
                first["sessionId"],
                other_agent_session["sessionId"],
                other_project_session["sessionId"],
            }
        )
        == 3
    )


def test_formal_retry_requires_terminal_task_and_keeps_attempts_flat(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="task-1",
    )

    with pytest.raises(ResearchProjectAgentSessionError, match="still active"):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            role_label="资料寻找",
            created_from_task_id="task-2",
            formal_retry=True,
            previous_task={
                "taskId": "task-1",
                "sessionId": first["sessionId"],
                "status": "running",
            },
        )

    with pytest.raises(ResearchProjectAgentSessionError, match="terminal"):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            role_label="璧勬枡瀵绘壘",
            created_from_task_id="task-2",
            formal_retry=True,
            previous_task={
                "taskId": "task-1",
                "sessionId": first["sessionId"],
                "status": "needs_review",
            },
        )

    session_service.update_chat_session_title(
        first["sessionId"], "用户自定义的会话名称"
    )
    retry = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="task-2",
        formal_retry=True,
        previous_task={
            "taskId": "task-1",
            "sessionId": first["sessionId"],
            "status": "failed",
        },
    )

    assert retry["sessionCreated"] is True
    assert retry["sessionAttempt"] == 2
    assert retry["retryOfSessionId"] == first["sessionId"]
    assert retry["sessionTitle"] == "层级反馈实验｜资料寻找｜重试 2"
    assert (
        session_service.get_session_detail(first["sessionId"])["title"]
        == "用户自定义的会话名称"
    )
    assert session_service.get_session_detail(retry["sessionId"]) is not None


def test_session_binding_recovers_registry_without_creating_a_duplicate(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
    )
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"],
            project["projectId"],
        )
        / "research_project_agent_sessions.json"
    )
    registry_path.unlink()

    recovered = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
    )

    assert recovered["sessionId"] == first["sessionId"]
    assert recovered["sessionCreated"] is False
    assert registry_path.exists()


def test_retry_title_keeps_role_and_attempt_suffix_within_limit(tmp_path, monkeypatch):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path,
        monkeypatch,
        project_name="实验" * 80,
    )
    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="task-1",
    )
    retry = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="task-2",
        formal_retry=True,
        previous_task={
            "taskId": "task-1",
            "sessionId": first["sessionId"],
            "status": "failed",
        },
    )

    assert len(retry["sessionTitle"]) == 120
    assert retry["sessionTitle"].endswith("｜资料寻找｜重试 2")


def test_source_stage_tasks_use_project_session_without_direct_session_and_retry_idempotently(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        _fake_local_research_public_config,
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        role_key="source_finder",
    )
    assert not agent_directory_service.get_agent(agent["agentId"]).get(
        "directSessionId"
    )
    team = team_service.create_team(
        name="科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": "资料寻找",
                "role": "source_finder",
            }
        ],
    )
    project = team_workflow_orchestration_service.update_research_project(
        team["teamId"],
        team_workflow_orchestration_service.LEGACY_PROJECT_ID,
        {"name": "可塑性规则实验"},
    )["project"]
    run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "plasticity rules",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["plasticity rules"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]
    submitted_sessions: list[str] = []

    def fake_submit(session_id, _content, **_kwargs):
        submitted_sessions.append(session_id)
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-{len(submitted_sessions)}",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    first = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "ordinary-1",
            },
        )
    )
    second = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "ordinary-2",
            },
        )
    )

    assert first["sessionCreated"] is True
    assert second["sessionCreated"] is False
    assert second["sessionId"] == first["sessionId"]
    assert second["researchProjectId"] == project["projectId"]
    assert second["sessionTitle"] == "可塑性规则实验｜资料寻找"
    assert not agent_directory_service.get_agent(agent["agentId"]).get(
        "directSessionId"
    )

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="still active",
    ):
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "retry-active",
                "formalRetry": True,
            },
        )

    latest = dict(second["task"])
    latest["status"] = "failed"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        latest,
    )
    retry_request = {
        "stageId": "finding",
        "agentId": agent["agentId"],
        "agentRole": "source_finder",
        "idempotencyKey": "retry-terminal",
        "formalRetry": True,
    }
    retry = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            retry_request,
        )
    )
    duplicate = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            retry_request,
        )
    )

    assert retry["sessionAttempt"] == 2
    assert retry["sessionId"] != first["sessionId"]
    assert retry["retryOfSessionId"] == first["sessionId"]
    assert duplicate["alreadyPresent"] is True
    assert duplicate["taskId"] == retry["taskId"]
    assert duplicate["sessionId"] == retry["sessionId"]
    assert submitted_sessions == [
        first["sessionId"],
        first["sessionId"],
        retry["sessionId"],
    ]


def test_formal_retry_selects_the_same_agent_previous_task_when_roles_match(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        _fake_local_research_public_config,
    )
    first_agent = agent_directory_service.create_agent_instance(
        display_name="璧勬枡瀵绘壘 A",
        role_key="source_finder",
    )
    second_agent = agent_directory_service.create_agent_instance(
        display_name="璧勬枡瀵绘壘 B",
        role_key="source_finder",
    )
    team = team_service.create_team(
        name="绉戠爺鍥㈤槦",
        members=[
            {
                "agentId": first_agent["agentId"],
                "agentName": "璧勬枡瀵绘壘 A",
                "role": "source_finder",
            },
            {
                "agentId": second_agent["agentId"],
                "agentName": "璧勬枡瀵绘壘 B",
                "role": "source_finder",
            },
        ],
    )
    run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "agent-scoped retry",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": first_agent["agentId"]},
            "querySeeds": ["agent-scoped retry"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]
    submitted_count = 0

    def fake_submit(session_id, _content, **_kwargs):
        nonlocal submitted_count
        submitted_count += 1
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-{submitted_count}",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)

    def start(agent_id: str, idempotency_key: str, *, formal_retry: bool = False):
        return team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent_id,
                "agentRole": "source_finder",
                "idempotencyKey": idempotency_key,
                "formalRetry": formal_retry,
            },
        )

    first = start(first_agent["agentId"], "agent-a-first")
    first["task"]["status"] = "failed"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        first["task"],
    )
    second = start(second_agent["agentId"], "agent-b-first")
    second["task"]["status"] = "failed"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        second["task"],
    )

    retry = start(first_agent["agentId"], "agent-a-retry", formal_retry=True)

    assert retry["sessionAttempt"] == 2
    assert retry["retryOfSessionId"] == first["sessionId"]
    assert retry["sessionId"] != second["sessionId"]
