"""T3 contracts for exact Agent task and session execution."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.session_binding_bridge import (
    chat_deep_link,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

SOURCE_AGENTS = {
    "source_finder": "agent-source-finder",
    "source_extractor": "agent-source-extractor",
    "source_relation_mapper": "agent-source-relation-mapper",
    "source_ingestor": "agent-source-ingestor",
}


def test_chat_deep_link_preserves_exact_team_run_node_return_context() -> None:
    href = chat_deep_link(
        session_id="session-1",
        task_id="task-1",
        turn_id="turn-1",
        team_id="team-1",
        run_id="run-1",
        node_id="source_finding",
    )
    assert href is not None
    chat_query = parse_qs(urlparse(href).query)
    return_query = parse_qs(urlparse(chat_query["returnTo"][0]).query)
    assert chat_query["session"] == ["session-1"]
    assert chat_query["focusTask"] == ["task-1"]
    assert chat_query["focusTurn"] == ["turn-1"]
    assert return_query == {
        "teamId": ["team-1"],
        "researchView": ["workflow"],
        "runId": ["run-1"],
        "node": ["source_finding"],
        "panel": ["node"],
    }


def _run_input(team_id: str = "team-agent-execution") -> dict:
    return {
        "teamId": team_id,
        "projectId": "project-agent-execution",
        "questionId": "question-agent-execution",
        "researchBriefHash": "b" * 64,
        "datasetRefs": ["fixture://dataset/agent-execution"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {"formalWrites": False},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "如何提升科研闭环效率？"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
            "experiments": 4,
            "computeUnits": 20,
            "maxParallelTasks": 2,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "fixture://environment/agent-execution",
        "modelRoutingPolicy": {"reasoning": "reasoning-model"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _make_node_ready(
    service: ResearchWorkflowRuntimeService,
    run: dict,
    *,
    node_id: str,
    agent_id: str,
) -> dict:
    source = dict(run["nodeRuns"][0])
    source.update(
        {
            "nodeRunId": f"nr-{run['runId']}-{node_id}-a1",
            "nodeId": node_id,
            "agentId": agent_id,
            "status": "ready",
            "taskId": "",
            "sessionId": "",
        }
    )
    service._store.update_run(
        run["runId"],
        {"runtimeCurrentNodeIds": [node_id], "nodeRuns": [source]},
    )
    return service.get_run(run["runId"])


@pytest.mark.parametrize(
    ("node_id", "stage_id", "role_key"),
    (
        ("source_finding", "finding", "source_finder"),
        ("source_extraction", "extraction", "source_extractor"),
        ("evidence_relations", "relations", "source_relation_mapper"),
        ("knowledge_ingestion", "ingestion", "source_ingestor"),
    ),
)
def test_each_source_agent_starts_exact_task_and_persists_node_session(
    tmp_path: Path,
    monkeypatch,
    node_id: str,
    stage_id: str,
    role_key: str,
) -> None:
    service = _service(tmp_path / node_id)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(workflowDefaults=SOURCE_AGENTS),
        idempotency_key=f"create-{node_id}",
    )
    run = _make_node_ready(
        service,
        run,
        node_id=node_id,
        agent_id=SOURCE_AGENTS[role_key],
    )
    if node_id != "source_finding":
        service._store.update_run(
            run["runId"], {"sourceCollectionRunId": "source-run-1"}
        )

    source_run_calls: list[dict] = []
    task_calls: list[dict] = []

    def fake_start_source_run(team_id: str, payload: dict) -> dict:
        source_run_calls.append({"teamId": team_id, "payload": payload})
        return {"run": {"runId": "source-run-1"}}

    def fake_start_stage_task(team_id: str, source_run_id: str, payload: dict) -> dict:
        task_calls.append(
            {"teamId": team_id, "sourceRunId": source_run_id, "payload": payload}
        )
        assert payload["stageId"] == stage_id
        assert payload["agentRole"] == role_key
        assert payload["agentId"] == SOURCE_AGENTS[role_key]
        return {
            "taskId": f"task-{node_id}",
            "agentId": SOURCE_AGENTS[role_key],
            "agentRole": role_key,
            "sessionId": f"session-{node_id}",
            "sessionAttempt": 1,
            "turn": {"turnId": f"turn-{node_id}"},
            "task": {
                "taskId": f"task-{node_id}",
                "agentId": SOURCE_AGENTS[role_key],
                "sessionId": f"session-{node_id}",
                "turn": {"turnId": f"turn-{node_id}"},
            },
            "chatRoute": f"/chat?session=session-{node_id}",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.runs.start_source_collection_run",
        fake_start_source_run,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        fake_start_stage_task,
    )

    first = service.apply_node_command(
        run["runId"],
        node_id,
        "start_agent_task",
        payload={"idempotencyKey": f"start-{node_id}"},
    )
    replay = service.apply_node_command(
        run["runId"],
        node_id,
        "start_agent_task",
        payload={"idempotencyKey": f"start-{node_id}"},
    )

    persisted = service.get_run(run["runId"])
    node_run = persisted["nodeRuns"][0]
    assert first["taskId"] == f"task-{node_id}"
    assert replay["taskId"] == first["taskId"]
    assert node_run["status"] == "running"
    assert node_run["agentId"] == SOURCE_AGENTS[role_key]
    assert node_run["taskId"] == f"task-{node_id}"
    assert node_run["sessionId"] == f"session-{node_id}"
    assert len(task_calls) == 1
    assert len(source_run_calls) == (1 if node_id == "source_finding" else 0)
    assert "teamId=team-agent-execution" in task_calls[0]["payload"]["returnTo"]


def test_project_agent_task_uses_frozen_agent_and_rejects_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    planner_id = "agent-experiment-planner"
    service = _service(tmp_path / "project-agent")
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"experiment_planner": planner_id}
        ),
        idempotency_key="create-project-agent",
    )
    run = _make_node_ready(
        service,
        run,
        node_id="hypothesis_design",
        agent_id=planner_id,
    )
    calls: list[dict] = []

    def fake_start_project_task(team_id: str, project_id: str, payload: dict) -> dict:
        calls.append({"teamId": team_id, "projectId": project_id, "payload": payload})
        assert payload["taskKind"] == "experiment_design"
        assert payload["agentId"] == planner_id
        assert "teamId=team-agent-execution" in payload["returnTo"]
        return {
            "task": {
                "taskId": "task-hypothesis",
                "agentId": planner_id,
                "sessionId": "session-hypothesis",
                "sessionAttempt": 1,
                "turn": {"turnId": "turn-hypothesis"},
            },
            "sessionId": "session-hypothesis",
            "sessionAttempt": 1,
            "chatRoute": "/chat?session=session-hypothesis",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.start_research_project_agent_task",
        fake_start_project_task,
    )

    started = service.apply_node_command(
        run["runId"],
        "hypothesis_design",
        "start_agent_task",
        payload={"idempotencyKey": "start-hypothesis", "agentId": planner_id},
    )
    assert started["taskId"] == "task-hypothesis"
    assert len(calls) == 1

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "hypothesis_design",
            "start_agent_task",
            payload={
                "idempotencyKey": "start-hypothesis",
                "agentId": "agent-wrong",
            },
        )
    assert getattr(exc.value, "code", "") == "binding_agent_mismatch"
    assert len(calls) == 1
