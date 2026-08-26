from __future__ import annotations

import json

import pytest

from core.chat.turn_journal import (
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
)
from core.research.workflow.contracts.session_scope import (
    ContractValidationError,
    WorkflowSessionScopeV3,
)
from core.research.workflow.contracts.discussion_scope import (
    WorkflowDiscussionScopeV1,
)
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
from tests._support.team_workflow.helpers import (
    _start_source_collection_run_with_problem_understanding,
)
from core.web.services.team_workflow.research_project_agent_sessions import (
    ResearchProjectAgentSessionError,
    resolve_research_project_agent_session,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store


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
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)


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


def test_formal_workflow_nodes_use_exact_scoped_sessions_without_reusing_flat_history(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )

    flat = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="manual-task",
    )
    hypothesis = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="假设设计",
        created_from_task_id="workflow-task-hypothesis",
        workflow_run_id="run-sci-096",
        workflow_node_id="hypothesis_design",
    )
    hypothesis_replay = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="假设设计",
        created_from_task_id="workflow-task-hypothesis-replay",
        workflow_run_id="run-sci-096",
        workflow_node_id="hypothesis_design",
    )
    protocol = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="协议设计",
        created_from_task_id="workflow-task-protocol",
        workflow_run_id="run-sci-096",
        workflow_node_id="protocol_design",
    )
    next_run_hypothesis = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="假设设计",
        created_from_task_id="workflow-task-next-run",
        workflow_run_id="run-sci-097",
        workflow_node_id="hypothesis_design",
    )

    assert hypothesis["sessionCreated"] is True
    assert hypothesis["sessionAttempt"] == 1
    assert hypothesis["sessionId"] != flat["sessionId"]
    assert hypothesis["sessionTitle"] == "层级反馈实验｜假设设计"
    assert hypothesis_replay["sessionCreated"] is False
    assert hypothesis_replay["sessionId"] == hypothesis["sessionId"]
    assert protocol["sessionAttempt"] == 1
    assert protocol["sessionId"] not in {flat["sessionId"], hypothesis["sessionId"]}
    assert next_run_hypothesis["sessionAttempt"] == 1
    assert next_run_hypothesis["sessionId"] not in {
        flat["sessionId"],
        hypothesis["sessionId"],
        protocol["sessionId"],
    }
    scoped_binding = session_service.get_session_detail(hypothesis["sessionId"])[
        "experimentBinding"
    ]
    assert scoped_binding["workflowRunId"] == "run-sci-096"
    assert scoped_binding["workflowNodeId"] == "hypothesis_design"
    assert scoped_binding["scope"]["kind"] == "workflow_node_root"


def test_v2_root_registry_fixture_recovers_the_existing_canonical_session(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    workflow_run_id = "run-sci-096"
    workflow_node_id = "hypothesis_design"
    created_at = "2026-08-22T00:00:00Z"
    legacy_binding = {
        "teamId": team["teamId"],
        "researchProjectId": project["projectId"],
        "experimentName": project["name"],
        "agentId": agent["agentId"],
        "roleKey": "source_finder",
        "roleLabel": "假设设计",
        "attempt": 1,
        "retryOfSessionId": "",
        "createdFromTaskId": "v2-root-task",
        "createdAt": created_at,
        "workflowRunId": workflow_run_id,
        "workflowNodeId": workflow_node_id,
    }
    legacy_session = session_service.create_chat_session(
        title="层级反馈实验｜假设设计",
        agent_id=agent["agentId"],
        created_by="test.v2_root_fixture",
        conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        experiment_binding=legacy_binding,
    )
    legacy_session_id = legacy_session["id"]
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "teamId": team["teamId"],
                "researchProjectId": project["projectId"],
                "agents": {},
                "workflowNodes": {
                    f"{agent['agentId']}::{workflow_run_id}::{workflow_node_id}": {
                        "agentId": agent["agentId"],
                        "roleKey": "source_finder",
                        "workflowRunId": workflow_run_id,
                        "workflowNodeId": workflow_node_id,
                        "currentAttempt": 1,
                        "attempts": [
                            {
                                "sessionId": legacy_session_id,
                                "agentId": agent["agentId"],
                                "roleKey": "source_finder",
                                "attempt": 1,
                                "retryOfSessionId": "",
                                "createdFromTaskId": "v2-root-task",
                                "createdAt": created_at,
                                "workflowRunId": workflow_run_id,
                                "workflowNodeId": workflow_node_id,
                            }
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    recovered = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="假设设计",
        created_from_task_id="v2-root-replay",
        workflow_run_id=workflow_run_id,
        workflow_node_id=workflow_node_id,
    )

    assert recovered["sessionCreated"] is False
    assert recovered["sessionId"] == legacy_session_id
    assert recovered["scope"]["kind"] == "workflow_node_root"
    assert recovered["scopeKey"] == (
        "v3|node|"
        f"{agent['agentId']}|{workflow_run_id}|{workflow_node_id}"
    )
    assert session_service.get_session_detail(legacy_session_id)["id"] == legacy_session_id


def test_workflow_session_scope_v3_is_stable_and_attempt_is_not_identity():
    root = WorkflowSessionScopeV3.root(
        teamId="team-1",
        researchProjectId="project-1",
        agentId="agent-1",
        workflowRunId="run-sci-096",
        workflowNodeId="hypothesis_design",
    )
    candidate = WorkflowSessionScopeV3.candidate(
        teamId="team-1",
        researchProjectId="project-1",
        agentId="agent-1",
        workflowRunId="run-sci-096",
        workflowNodeId="hypothesis_design",
        selectionId="selection-1",
        candidateId="H2",
    )

    assert root.kind == "workflow_node_root"
    assert root.key == "v3|node|agent-1|run-sci-096|hypothesis_design"
    assert candidate.kind == "workflow_candidate"
    assert candidate.key == (
        "v3|candidate|agent-1|run-sci-096|hypothesis_design|selection-1|H2"
    )
    assert candidate.to_dict()["version"] == 3
    assert "attempt" not in candidate.to_dict()
    assert WorkflowSessionScopeV3.from_mapping(
        {**candidate.to_dict(), "attempt": 2}
    ).key == candidate.key

    with pytest.raises(ContractValidationError, match="both selectionId and candidateId"):
        WorkflowSessionScopeV3.from_mapping(
            {**root.to_dict(), "kind": "workflow_candidate", "selectionId": "selection-1"}
        )
    with pytest.raises(ContractValidationError, match="must not carry candidate"):
        WorkflowSessionScopeV3.from_mapping(
            {**root.to_dict(), "selectionId": "selection-1", "candidateId": "H1"}
        )


def test_candidate_scope_creates_hidden_child_and_resumes_exact_candidate_scope(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
    }
    h1 = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-task"
    )
    h2 = resolve_research_project_agent_session(
        **common, candidate_id="H2", created_from_task_id="h2-task"
    )
    h1_replay = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-replay"
    )

    assert h1["sessionCreated"] is True
    assert h1["sessionKind"] == "child"
    assert h1["hiddenFromIndex"] is True
    assert h1["sessionId"] != h2["sessionId"]
    assert h1_replay["sessionCreated"] is False
    assert h1_replay["sessionId"] == h1["sessionId"]
    assert h1["parentSessionId"] == h2["parentSessionId"]
    assert h1["rootSessionId"] == h1["parentSessionId"]

    h1_detail = session_service.get_session_detail(h1["sessionId"])
    h2_detail = session_service.get_session_detail(h2["sessionId"])
    assert h1_detail["sessionKind"] == "child"
    assert h1_detail["hiddenFromIndex"] is True
    assert h1_detail["parentSessionId"] == h1["parentSessionId"]
    assert h1_detail["rootSessionId"] == h1["parentSessionId"]
    assert h1_detail["experimentBinding"]["scope"] == {
        "version": 3,
        "kind": "workflow_candidate",
        "teamId": team["teamId"],
        "researchProjectId": project["projectId"],
        "agentId": agent["agentId"],
        "workflowRunId": "run-sci-096",
        "workflowNodeId": "hypothesis_design",
        "selectionId": "selection-1",
        "candidateId": "H1",
    }
    assert h2_detail["experimentBinding"]["scope"]["candidateId"] == "H2"
    assert h1["sessionId"] not in {
        item["id"] for item in session_service.list_sessions()
    }


def test_candidate_formal_retry_only_advances_that_candidate_scope(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
    }
    h1 = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-task"
    )
    h2 = resolve_research_project_agent_session(
        **common, candidate_id="H2", created_from_task_id="h2-task"
    )
    h2_retry = resolve_research_project_agent_session(
        **common,
        candidate_id="H2",
        created_from_task_id="h2-retry",
        formal_retry=True,
        previous_task={
            "taskId": "h2-task",
            "sessionId": h2["sessionId"],
            "status": "failed",
        },
    )
    h1_replay = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-replay"
    )

    assert h2_retry["sessionCreated"] is True
    assert h2_retry["sessionAttempt"] == 2
    assert h2_retry["retryOfSessionId"] == h2["sessionId"]
    assert h2_retry["sessionId"] != h2["sessionId"]
    assert h1_replay["sessionId"] == h1["sessionId"]
    assert h1_replay["sessionAttempt"] == 1
    assert h2_retry["parentSessionId"] == h2["parentSessionId"]
    assert session_service.get_session_detail(h2_retry["sessionId"])[
        "experimentBinding"
    ]["scope"]["candidateId"] == "H2"


def test_candidate_scope_recovers_registry_and_never_falls_back_to_node_root(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
    }
    first = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-task"
    )
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry_path.unlink()

    recovered = resolve_research_project_agent_session(
        **common, candidate_id="H1", created_from_task_id="h1-replay"
    )
    assert recovered["sessionId"] == first["sessionId"]
    assert recovered["sessionCreated"] is False
    assert recovered["sessionKind"] == "child"

    session_service.delete_chat_session(first["sessionId"])
    with pytest.raises(ResearchProjectAgentSessionError, match="candidate session"):
        resolve_research_project_agent_session(
            **common, candidate_id="H1", created_from_task_id="h1-missing"
        )


def test_candidate_registry_pointing_to_root_fails_closed_without_creating_child(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
    }
    root = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="假设设计",
        created_from_task_id="root-task",
        workflow_run_id="run-sci-096",
        workflow_node_id="hypothesis_design",
    )
    candidate_scope = WorkflowSessionScopeV3.candidate(
        teamId=team["teamId"],
        researchProjectId=project["projectId"],
        agentId=agent["agentId"],
        workflowRunId="run-sci-096",
        workflowNodeId="hypothesis_design",
        selectionId="selection-1",
        candidateId="H1",
    )
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry.setdefault("workflowCandidates", {})[candidate_scope.key] = {
        "agentId": agent["agentId"],
        "roleKey": "source_finder",
        "workflowRunId": "run-sci-096",
        "workflowNodeId": "hypothesis_design",
        "selectionId": "selection-1",
        "candidateId": "H1",
        "currentAttempt": 1,
        "attempts": [
            {
                "sessionId": root["sessionId"],
                "agentId": agent["agentId"],
                "roleKey": "source_finder",
                "attempt": 1,
                "retryOfSessionId": "",
                "createdFromTaskId": "candidate-task",
                "createdAt": "2026-08-22T00:00:00Z",
                "workflowRunId": "run-sci-096",
                "workflowNodeId": "hypothesis_design",
                "selectionId": "selection-1",
                "candidateId": "H1",
                "scope": candidate_scope.to_dict(),
            }
        ],
    }
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False),
        encoding="utf-8",
    )
    session_ids_before = {item["id"] for item in session_service.list_sessions()}
    child_calls: list[dict] = []

    def forbidden_child_creation(*_args, **kwargs):
        child_calls.append(dict(kwargs))
        raise AssertionError("candidate scope must not create a child for a root registry entry")

    monkeypatch.setattr(session_service, "create_child_session", forbidden_child_creation)

    with pytest.raises(
        ResearchProjectAgentSessionError,
        match="missing or mismatched canonical session",
    ):
        resolve_research_project_agent_session(
            **common,
            candidate_id="H1",
            created_from_task_id="candidate-replay",
        )

    assert child_calls == []
    assert {item["id"] for item in session_service.list_sessions()} == session_ids_before
    persisted_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert (
        persisted_registry["workflowCandidates"][candidate_scope.key]["attempts"][0][
            "sessionId"
        ]
        == root["sessionId"]
    )


def test_project_agent_session_recovers_exact_identity_from_real_stage_turn_journal(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    created = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="stage-task-recovery",
    )
    session_id = created["sessionId"]
    turn_id = "turn-stage-recovery"
    timestamp = "2026-08-11T01:02:03Z"
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        payload={"agentId": agent["agentId"]},
        source="test.stage_task",
        timestamp=timestamp,
    )
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        status="completed",
        payload={
            "content": "stage task",
            "metadata": {
                "kind": "source_collection_stage_session_task",
                "sourceSurface": "team_workflow_stage_task",
                "teamId": team["teamId"],
                "researchProjectId": project["projectId"],
                "experimentName": project["name"],
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "sessionAttempt": 1,
                "retryOfSessionId": "",
                "sourceCollectionStageTaskId": "stage-task-recovery",
            },
        },
        source="test.stage_task",
        timestamp=timestamp,
    )
    with session_service._CHAT_STATE_LOCK:
        state = session_service.load_chat_state(tmp_path)
        state["conversations"] = [
            item
            for item in state.get("conversations", [])
            if item.get("conversation_id") != session_id
        ]
        session_service.save_chat_state(tmp_path, state)

    recovered = session_service.get_session_detail(session_id)

    assert recovered is not None
    assert recovered["id"] == session_id
    assert recovered["title"] == "层级反馈实验｜资料寻找"
    assert recovered["agentId"] == agent["agentId"]
    assert recovered["experimentBinding"] == {
        "teamId": team["teamId"],
        "researchProjectId": project["projectId"],
        "experimentName": project["name"],
        "agentId": agent["agentId"],
        "roleKey": "source_finder",
        "roleLabel": "资料寻找",
        "attempt": 1,
        "retryOfSessionId": "",
        "createdFromTaskId": "stage-task-recovery",
        "createdAt": timestamp,
    }


def test_project_agent_session_does_not_register_created_session_without_canonical_detail(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        session_service,
        "create_chat_session",
        lambda **_kwargs: {"id": "session-orphaned"},
    )
    monkeypatch.setattr(session_service, "get_session_detail", lambda *_args, **_kwargs: None)

    with pytest.raises(
        ResearchProjectAgentSessionError,
        match="canonical session",
    ):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            role_label="资料寻找",
            created_from_task_id="stage-task-orphan",
        )

    with pytest.raises(
        ResearchProjectAgentSessionError,
        match="canonical session",
    ):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            role_label="资料寻找",
            created_from_task_id="stage-task-orphan",
        )


def test_missing_canonical_project_agent_session_fails_closed_and_requires_formal_retry(
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
    session_service.delete_chat_session(first["sessionId"])

    with pytest.raises(
        ResearchProjectAgentSessionError,
        match="missing canonical session",
    ):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            role_label="资料寻找",
            created_from_task_id="task-2",
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
    assert retry["sessionId"] != first["sessionId"]
    assert session_service.get_session_detail(retry["sessionId"]) is not None


def test_managed_new_task_recovers_missing_session_with_explicit_lineage(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    first = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_extractor",
        role_label="资料提炼",
        created_from_task_id="task-old",
    )
    session_service.delete_chat_session(first["sessionId"])

    recovered = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_extractor",
        role_label="资料提炼",
        created_from_task_id="task-new",
        recover_missing_session=True,
    )

    assert recovered["sessionCreated"] is True
    assert recovered["sessionAttempt"] == 2
    assert recovered["retryOfSessionId"] == first["sessionId"]
    assert recovered["recoveryReason"] == "missing_canonical_session"
    assert recovered["sessionId"] != first["sessionId"]
    assert session_service.get_session_detail(recovered["sessionId"]) is not None


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


def test_scoped_session_binding_recovers_only_the_exact_workflow_node(
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
        role_label="假设设计",
        workflow_run_id="run-sci-096",
        workflow_node_id="hypothesis_design",
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
        role_label="假设设计",
        workflow_run_id="run-sci-096",
        workflow_node_id="hypothesis_design",
    )
    different_node = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="协议设计",
        workflow_run_id="run-sci-096",
        workflow_node_id="protocol_design",
    )

    assert recovered["sessionId"] == first["sessionId"]
    assert recovered["sessionCreated"] is False
    assert different_node["sessionId"] != first["sessionId"]
    assert different_node["sessionAttempt"] == 1


def test_formal_workflow_session_rejects_partial_scope(tmp_path, monkeypatch):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )

    with pytest.raises(
        ResearchProjectAgentSessionError,
        match="both workflowRunId and workflowNodeId",
    ):
        resolve_research_project_agent_session(
            team["teamId"],
            research_project_id=project["projectId"],
            agent_id=agent["agentId"],
            role_key="source_finder",
            workflow_run_id="run-sci-096",
        )


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


def test_source_stage_exact_replay_recovers_pre_submit_missing_session_without_duplicate_task(
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
        {"name": "会话恢复实验"},
    )["project"]
    run = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "session recovery",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["session recovery"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]
    first_session = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="stagetask-pre-submit",
    )
    session_service.delete_chat_session(first_session["sessionId"])

    requested_key = "agent-task:node-run-source-finding"
    task_id = "stagetask-pre-submit"
    canonical_key = (
        team_workflow_orchestration_service._source_collection_stage_task_idempotency_key(
            team_id=team["teamId"],
            run_id=run["runId"],
            stage_id="finding",
            agent_id=agent["agentId"],
            agent_role="source_finder",
            task_id=task_id,
            requested_key=requested_key,
        )
    )
    now = team_workflow_orchestration_service.utc_now_iso()
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        {
            "schemaVersion": 1,
            "taskKind": "source_collection_stage_session_task",
            "taskId": task_id,
            "idempotencyKey": canonical_key,
            "teamId": team["teamId"],
            "runId": run["runId"],
            "stageId": "finding",
            "agentId": agent["agentId"],
            "agentRole": "source_finder",
            "sessionId": first_session["sessionId"],
            "researchProjectId": project["projectId"],
            "experimentName": project["name"],
            "sessionTitle": first_session["sessionTitle"],
            "sessionAttempt": 1,
            "sessionCreated": False,
            "retryOfSessionId": "",
            "status": "queued",
            "turn": {},
            "createdAt": now,
            "updatedAt": now,
        },
    )

    submitted_sessions: list[str] = []

    def fake_submit(session_id, _content, **_kwargs):
        submitted_sessions.append(session_id)
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-recovered",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    recovered = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": requested_key,
            },
        )
    )

    tasks = team_workflow_orchestration_service._source_collection_stage_session_tasks(
        team["teamId"], run["runId"]
    )
    assert recovered["alreadyPresent"] is False
    assert recovered["taskId"] == task_id
    assert recovered["sessionAttempt"] == 2
    assert recovered["retryOfSessionId"] == first_session["sessionId"]
    assert recovered["sessionId"] != first_session["sessionId"]
    assert submitted_sessions == [recovered["sessionId"]]
    assert len(tasks) == 1
    assert tasks[0]["taskId"] == task_id
    assert tasks[0]["status"] == "running"
    assert tasks[0]["turn"]["turnId"] == "turn-recovered"


def test_source_stage_new_task_records_missing_project_session_recovery(
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
        {"name": "新任务会话恢复实验"},
    )["project"]
    run = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "new task session recovery",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["new task session recovery"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]
    first_session = resolve_research_project_agent_session(
        team["teamId"],
        research_project_id=project["projectId"],
        agent_id=agent["agentId"],
        role_key="source_finder",
        role_label="资料寻找",
        created_from_task_id="old-project-task",
    )
    session_service.delete_chat_session(first_session["sessionId"])
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, _content, **_kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-new-task-recovery",
            "status": "running",
        },
    )

    recovered = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "new-task-missing-session-recovery",
            },
        )
    )

    assert recovered["sessionAttempt"] == 2
    assert recovered["retryOfSessionId"] == first_session["sessionId"]
    assert recovered["task"]["formalRetry"] is True
    assert recovered["task"]["formalRetryReason"] == "missing_canonical_session"
    assert recovered["task"]["turn"]["turnId"] == "turn-new-task-recovery"


def test_source_stage_tasks_use_project_session_without_reusing_direct_session_and_retry_idempotently(
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
    run = _start_source_collection_run_with_problem_understanding(
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
    direct_session_id = agent_directory_service.get_agent(agent["agentId"])[
        "directSessionId"
    ]
    assert direct_session_id
    assert first["sessionId"] != direct_session_id

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

    needs_review = dict(second["task"])
    needs_review["status"] = "needs_review"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        needs_review,
    )
    supplement = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "ordinary-supplement",
            },
        )
    )
    assert supplement["sessionCreated"] is False
    assert supplement["sessionId"] == first["sessionId"]
    assert supplement["task"]["formalRetry"] is False

    latest = dict(supplement["task"])
    latest["status"] = "running"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        latest,
    )
    reconciliation_calls: list[str] = []

    def reconcile_stale_running_task(team_id, run_id, task):
        assert team_id == team["teamId"]
        assert run_id == run["runId"]
        reconciliation_calls.append(task["taskId"])
        return {**task, "status": "failed"}

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_reconcile_source_collection_stage_session_task",
        reconcile_stale_running_task,
    )
    retry_request = {
        "stageId": "finding",
        "agentId": agent["agentId"],
        "agentRole": "source_finder",
        "idempotencyKey": "retry-terminal",
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
    assert retry["task"]["formalRetry"] is True
    assert retry["task"]["formalRetryReason"] == "previous_stage_task_failed"
    assert reconciliation_calls == [latest["taskId"]]
    assert duplicate["alreadyPresent"] is True
    assert duplicate["taskId"] == retry["taskId"]
    assert duplicate["sessionId"] == retry["sessionId"]
    assert submitted_sessions == [
        first["sessionId"],
        first["sessionId"],
        first["sessionId"],
        retry["sessionId"],
    ]

    reviewable = dict(retry["task"])
    reviewable["status"] = "needs_review"
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        reviewable,
    )
    session_service.delete_chat_session(retry["sessionId"])
    recovered = (
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run["runId"],
            {
                "stageId": "finding",
                "agentId": agent["agentId"],
                "agentRole": "source_finder",
                "idempotencyKey": "missing-session-after-review",
            },
        )
    )

    assert recovered["sessionAttempt"] == 3
    assert recovered["sessionId"] != retry["sessionId"]
    assert recovered["retryOfSessionId"] == retry["sessionId"]
    assert recovered["task"]["formalRetry"] is True
    assert recovered["task"]["formalRetryReason"] == "missing_canonical_session"
    assert submitted_sessions[-1] == recovered["sessionId"]


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
    run = _start_source_collection_run_with_problem_understanding(
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


def test_root_resolver_rejects_registry_entry_pointing_to_child(tmp_path, monkeypatch):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
    }
    root = resolve_research_project_agent_session(
        **common,
        created_from_task_id="root-task",
    )
    child = resolve_research_project_agent_session(
        **common,
        selection_id="selection-1",
        candidate_id="H1",
        created_from_task_id="candidate-task",
    )
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    record_key = (
        f"{agent['agentId']}::run-sci-096::hypothesis_design"
    )
    registry["workflowNodes"][record_key]["attempts"][-1]["sessionId"] = child[
        "sessionId"
    ]
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ResearchProjectAgentSessionError, match="non-canonical root"):
        resolve_research_project_agent_session(
            **common,
            created_from_task_id="root-replay",
        )
    assert root["sessionId"] != child["sessionId"]


def test_root_recovery_skips_durable_child_even_with_root_binding(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
    }
    root = resolve_research_project_agent_session(
        **common,
        created_from_task_id="root-task",
    )
    session_service.create_child_session(
        root["sessionId"],
        user_request="durable child should not become root",
        auto_start=False,
        switch_to_child=False,
        experiment_binding={
            "teamId": team["teamId"],
            "researchProjectId": project["projectId"],
            "experimentName": project["name"],
            "agentId": agent["agentId"],
            "roleKey": "source_finder",
            "roleLabel": "假设设计",
            "attempt": 1,
            "retryOfSessionId": "",
            "createdFromTaskId": "child-task",
            "createdAt": "2026-08-22T00:00:00Z",
            "workflowRunId": common["workflow_run_id"],
            "workflowNodeId": common["workflow_node_id"],
        },
    )
    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry_path.unlink()

    recovered = resolve_research_project_agent_session(
        **common,
        created_from_task_id="root-replay",
    )

    assert recovered["sessionId"] == root["sessionId"]
    assert recovered["sessionCreated"] is False


def test_candidate_resolver_rejects_child_not_hidden_from_index(tmp_path, monkeypatch):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
        "selection_id": "selection-1",
        "candidate_id": "H1",
    }
    first = resolve_research_project_agent_session(
        **common,
        created_from_task_id="candidate-task",
    )
    original_get_detail = session_service.get_session_detail

    def get_detail(session_id, **kwargs):
        detail = original_get_detail(session_id, **kwargs)
        if session_id == first["sessionId"] and isinstance(detail, dict):
            detail = dict(detail)
            detail["hiddenFromIndex"] = False
        return detail

    monkeypatch.setattr(session_service, "get_session_detail", get_detail)
    with pytest.raises(ResearchProjectAgentSessionError, match="candidate session"):
        resolve_research_project_agent_session(
            **common,
            created_from_task_id="candidate-replay",
        )


def test_discussion_generation_and_candidate_are_sibling_children_of_node_root(
    tmp_path, monkeypatch
):
    team, project, agent, _legacy_direct_session = _project_and_agent(
        tmp_path, monkeypatch
    )
    common = {
        "team_id": team["teamId"],
        "research_project_id": project["projectId"],
        "agent_id": agent["agentId"],
        "role_key": "source_finder",
        "role_label": "假设设计",
        "workflow_run_id": "run-sci-096",
        "workflow_node_id": "hypothesis_design",
    }
    root = resolve_research_project_agent_session(
        **common,
        created_from_task_id="node-root",
    )
    generation_scope = WorkflowDiscussionScopeV1.generation(
        teamId=team["teamId"],
        researchProjectId=project["projectId"],
        workflowRunId=common["workflow_run_id"],
        workflowNodeId=common["workflow_node_id"],
        questionId="SCI-096",
    )
    generation = resolve_research_project_agent_session(
        **common,
        created_from_task_id="question-generation",
        discussion_scope=generation_scope,
    )
    review_scope = WorkflowDiscussionScopeV1.review(
        teamId=team["teamId"],
        researchProjectId=project["projectId"],
        workflowRunId=common["workflow_run_id"],
        workflowNodeId=common["workflow_node_id"],
        questionId="SCI-096",
        selectionId="selection-1",
        candidateId="H1",
    )
    review = resolve_research_project_agent_session(
        **common,
        selection_id="selection-1",
        candidate_id="H1",
        selected_candidate_ids=["H1", "H2"],
        created_from_task_id="candidate-review",
        discussion_scope=review_scope,
    )

    assert generation["sessionKind"] == "child"
    assert review["sessionKind"] == "child"
    assert generation["sessionId"] != review["sessionId"]
    assert generation["parentSessionId"] == root["sessionId"]
    assert review["parentSessionId"] == root["sessionId"]
    assert generation["rootSessionId"] == root["sessionId"]
    assert review["rootSessionId"] == root["sessionId"]

    registry_path = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"], project["projectId"]
        )
        / "research_project_agent_sessions.json"
    )
    registry_path.unlink()
    recovered_generation = resolve_research_project_agent_session(
        **common,
        created_from_task_id="question-generation-replay",
        discussion_scope=generation_scope,
    )

    assert recovered_generation["sessionId"] == generation["sessionId"]
    assert recovered_generation["sessionCreated"] is False
    assert recovered_generation["sessionKind"] == "child"
