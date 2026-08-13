"""T3 contracts for exact Agent task and session execution."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    node_command_capabilities,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.session_binding_bridge import (
    chat_deep_link,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from core.web.services.team_workflow_orchestration_service import (
    TeamWorkflowOrchestrationError,
)

SOURCE_AGENTS = {
    "source_finder": "agent-source-finder",
    "source_extractor": "agent-source-extractor",
    "source_relation_mapper": "agent-source-relation-mapper",
    "source_ingestor": "agent-source-ingestor",
}

BUDGET_REQUEST = {"tokens": 100, "toolCalls": 2, "wallClockSeconds": 30}


@pytest.fixture(autouse=True)
def _canonical_session_detail_for_external_adapter_fixtures(monkeypatch):
    """External-adapter fixtures return synthetic task anchors, not real Chat rows."""

    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **_kwargs: {"id": str(session_id or ""), "agentId": ""},
    )


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
        "modelRoutingPolicy": {
            "source_discovery": "source-model",
            "extraction": "extraction-model",
            "reasoning": "reasoning-model",
            "review": "review-model",
            "governance": "governance-model",
        },
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
        assert "questionId" not in payload
        assert payload["scope"] == {
            "workflowRunId": run["runId"],
            "researchProjectId": "project-agent-execution",
        }
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
        payload={
            "idempotencyKey": f"start-{node_id}",
            "budgetRequest": BUDGET_REQUEST,
        },
    )
    replay = service.apply_node_command(
        run["runId"],
        node_id,
        "start_agent_task",
        payload={
            "idempotencyKey": f"start-{node_id}",
            "budgetRequest": BUDGET_REQUEST,
        },
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
    assert first["modelRoute"]["purpose"] in {
        "source_discovery",
        "extraction",
    }
    assert first["taskBundle"]["status"] == "running"
    assert first["taskBundle"]["subtasks"][0]["taskId"] == f"task-{node_id}"
    assert len(persisted["modelRoutingDecisions"]) == 1
    assert len(persisted["taskBundles"]) == 1


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
        assert payload["taskKind"] == "hypothesis_design"
        assert payload["agentId"] == planner_id
        assert payload["workflowRunId"] == run["runId"]
        assert payload["workflowNodeId"] == "hypothesis_design"
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

    with pytest.raises(ResearchWorkflowError) as model_exc:
        service.apply_node_command(
            run["runId"],
            "hypothesis_design",
            "start_agent_task",
            payload={
                "idempotencyKey": "start-hypothesis",
                "agentId": planner_id,
                "modelRef": "unapproved-model",
            },
        )
    assert getattr(model_exc.value, "code", "") == "model_route_mismatch"
    assert calls == []

    started = service.apply_node_command(
        run["runId"],
        "hypothesis_design",
        "start_agent_task",
        payload={
            "idempotencyKey": "start-hypothesis",
            "agentId": planner_id,
            "budgetRequest": BUDGET_REQUEST,
        },
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


    stop_calls: list[dict] = []

    def fake_stop(session_id: str, *, expected_turn_id: str = "") -> dict:
        stop_calls.append(
            {"sessionId": session_id, "expectedTurnId": expected_turn_id}
        )
        return {"ok": True, "sessionId": session_id, "turnId": expected_turn_id}

    monkeypatch.setattr(
        "core.web.services.session_service.request_stop_session_turn",
        fake_stop,
    )
    expired_bundle = {
        **started["taskBundle"],
        "subtasks": [
            {
                **started["taskBundle"]["subtasks"][0],
                "deadlineAt": "2000-01-01T00:00:00Z",
            }
        ],
    }
    service._store.update_run(run["runId"], {"taskBundles": [expired_bundle]})
    cancelled = service.reconcile_task_bundles(run["runId"])
    replay = service.reconcile_task_bundles(run["runId"])
    assert cancelled["status"] == "blocked"
    assert cancelled["taskBundles"][0]["status"] == "cancelled"
    assert cancelled["taskBundles"][0]["subtasks"][0]["status"] == "cancelled"
    assert cancelled["taskBundles"][0]["cancelReason"] == (
        "task bundle deadline exceeded"
    )
    assert cancelled["nodeRuns"][0]["status"] == "cancelled"
    assert replay == cancelled
    assert stop_calls == [
        {"sessionId": "session-hypothesis", "expectedTurnId": "turn-hypothesis"}
    ]


def test_source_stage_preflight_is_a_recoverable_workflow_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "source-stage-preflight")
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(workflowDefaults=SOURCE_AGENTS),
        idempotency_key="create-source-stage-preflight",
    )
    run = _make_node_ready(
        service,
        run,
        node_id="knowledge_ingestion",
        agent_id=SOURCE_AGENTS["source_ingestor"],
    )
    service._store.update_run(
        run["runId"], {"sourceCollectionRunId": "source-run-preflight"}
    )

    def reject_stage_start(_team_id: str, _source_run_id: str, _payload: dict) -> dict:
        raise TeamWorkflowOrchestrationError(
            "推进失败（不合格）：关系图有 5 个节点但 0 条边，入库会被系统拦截。请先完成整理关系。"
        )

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        reject_stage_start,
    )

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "knowledge_ingestion",
            "start_agent_task",
            payload={
                "idempotencyKey": "start-source-stage-preflight",
                "budgetRequest": BUDGET_REQUEST,
            },
        )

    assert getattr(exc.value, "code", "") == "source_stage_preflight_failed"
    assert "关系图有 5 个节点但 0 条边" in str(exc.value)
    persisted = service.get_run(run["runId"])
    assert persisted["nodeRuns"][0]["status"] == "ready"


def test_partial_agent_start_replays_persisted_key_and_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "partial-replay")
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(workflowDefaults=SOURCE_AGENTS),
        idempotency_key="create-partial-replay",
    )
    run = _make_node_ready(
        service,
        run,
        node_id="source_finding",
        agent_id=SOURCE_AGENTS["source_finder"],
    )
    service._store.update_run(
        run["runId"],
        {"sourceCollectionRunId": "source-run-partial-replay"},
    )
    task_keys: list[str] = []

    def flaky_start_stage_task(
        team_id: str,
        source_run_id: str,
        payload: dict,
    ) -> dict:
        task_keys.append(str(payload["idempotencyKey"]))
        if len(task_keys) == 1:
            raise RuntimeError("simulated external start failure")
        return {
            "taskId": "task-partial-replay",
            "agentId": SOURCE_AGENTS["source_finder"],
            "sessionId": "session-partial-replay",
            "sessionAttempt": 1,
            "turn": {"turnId": "turn-partial-replay"},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        flaky_start_stage_task,
    )

    initial_capability = next(
        item
        for item in node_command_capabilities(
            service.get_run(run["runId"]),
            "source_finding",
        )
        if item["command"] == "start_agent_task"
    )
    initial_payload = {
        **initial_capability["payload"],
        "idempotencyKey": initial_capability["idempotencyKey"],
    }
    with pytest.raises(RuntimeError, match="simulated external start failure"):
        service.apply_node_command(
            run["runId"],
            "source_finding",
            "start_agent_task",
            payload=initial_payload,
        )

    partial = service.get_run(run["runId"])
    retry_capability = next(
        item
        for item in node_command_capabilities(partial, "source_finding")
        if item["command"] == "start_agent_task"
    )
    assert retry_capability["idempotencyKey"] == initial_capability["idempotencyKey"]
    assert retry_capability["payload"] == initial_capability["payload"]
    assert len(partial["budgetReservations"]) == 1
    assert len(partial["taskBundles"]) == 1

    started = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_agent_task",
        payload={
            **retry_capability["payload"],
            "idempotencyKey": retry_capability["idempotencyKey"],
        },
    )

    assert started["taskId"] == "task-partial-replay"
    assert task_keys == [
        initial_capability["idempotencyKey"],
        initial_capability["idempotencyKey"],
    ]
    persisted = service.get_run(run["runId"])
    assert len(persisted["budgetReservations"]) == 1
    assert len(persisted["taskBundles"]) == 1


@pytest.mark.parametrize(
    ("node_id", "role_key", "task_kind"),
    (
        ("protocol_design", "experiment_planner", "experiment_design"),
        ("protocol_review", "experiment_ledger", "experiment_evidence_review"),
        ("result_evaluation", "experiment_ledger", "experiment_evidence_review"),
        ("iteration_decision", "iteration_planner", "iteration_decision"),
        ("version_governance", "iteration_versioning", "version_governance"),
    ),
)
def test_each_project_agent_node_persists_exact_task_and_session(
    tmp_path: Path,
    monkeypatch,
    node_id: str,
    role_key: str,
    task_kind: str,
) -> None:
    agent_id = f"agent-{role_key}"
    service = _service(tmp_path / node_id)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={role_key: agent_id}
        ),
        idempotency_key=f"create-{node_id}",
    )
    run = _make_node_ready(
        service,
        run,
        node_id=node_id,
        agent_id=agent_id,
    )
    calls: list[dict] = []

    def fake_start_project_task(team_id: str, project_id: str, payload: dict) -> dict:
        calls.append(payload)
        assert payload["taskKind"] == task_kind
        assert payload["agentId"] == agent_id
        return {
            "task": {
                "taskId": f"task-{node_id}",
                "agentId": agent_id,
                "sessionId": f"session-{node_id}",
                "turn": {"turnId": f"turn-{node_id}"},
            },
            "sessionId": f"session-{node_id}",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.start_research_project_agent_task",
        fake_start_project_task,
    )
    started = service.apply_node_command(
        run["runId"],
        node_id,
        "start_agent_task",
        payload={
            "idempotencyKey": f"start-{node_id}",
            "budgetRequest": BUDGET_REQUEST,
        },
    )
    persisted = service.get_run(run["runId"])
    assert started["taskId"] == f"task-{node_id}"
    assert persisted["nodeRuns"][0]["agentId"] == agent_id
    assert persisted["nodeRuns"][0]["sessionId"] == f"session-{node_id}"
    assert persisted["taskBundles"][0]["status"] == "running"
    assert len(calls) == 1


def test_parallel_task_limit_blocks_second_bundle_before_external_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_input = _run_input()
    run_input["budgetPolicy"] = {
        **run_input["budgetPolicy"],
        "maxParallelTasks": 1,
    }
    service = _service(tmp_path / "parallel-limit")
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input,
        binding_layers=AgentBindingLayers(workflowDefaults=SOURCE_AGENTS),
        idempotency_key="create-parallel-limit",
    )
    run = _make_node_ready(
        service,
        run,
        node_id="source_finding",
        agent_id=SOURCE_AGENTS["source_finder"],
    )
    service._store.update_run(
        run["runId"],
        {"sourceCollectionRunId": "source-run-parallel"},
    )
    calls: list[dict] = []

    def fake_start_stage_task(team_id: str, source_run_id: str, payload: dict) -> dict:
        calls.append(payload)
        node_label = str(payload["stageId"])
        return {
            "taskId": f"task-{node_label}",
            "agentId": payload["agentId"],
            "sessionId": f"session-{node_label}",
            "turn": {"turnId": f"turn-{node_label}"},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        fake_start_stage_task,
    )
    service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_agent_task",
        payload={
            "idempotencyKey": "start-first-bundle",
            "budgetRequest": BUDGET_REQUEST,
        },
    )
    persisted = service.get_run(run["runId"])
    second = {
        **persisted["nodeRuns"][0],
        "nodeRunId": f"nr-{run['runId']}-source_extraction-a1",
        "nodeId": "source_extraction",
        "agentId": SOURCE_AGENTS["source_extractor"],
        "status": "ready",
        "taskId": "",
        "sessionId": "",
    }
    service._store.update_run(
        run["runId"],
        {
            "runtimeCurrentNodeIds": ["source_extraction"],
            "nodeRuns": [*persisted["nodeRuns"], second],
        },
    )

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "source_extraction",
            "start_agent_task",
            payload={
                "idempotencyKey": "start-second-bundle",
                "budgetRequest": BUDGET_REQUEST,
            },
        )
    assert getattr(exc.value, "code", "") == "parallel_budget_exhausted"
    assert len(calls) == 1


def test_agent_task_does_not_bind_a_session_missing_from_chat_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path / "missing-canonical-session")
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(workflowDefaults=SOURCE_AGENTS),
        idempotency_key="create-missing-canonical-session",
    )
    run = _make_node_ready(
        service,
        run,
        node_id="source_finding",
        agent_id=SOURCE_AGENTS["source_finder"],
    )
    service._store.update_run(
        run["runId"], {"sourceCollectionRunId": "source-run-missing-session"}
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        lambda _team_id, _source_run_id, _payload: {
            "taskId": "task-missing-session",
            "agentId": SOURCE_AGENTS["source_finder"],
            "sessionId": "session-missing-session",
            "sessionAttempt": 1,
            "turn": {"turnId": "turn-missing-session"},
        },
    )
    monkeypatch.setattr(session_service, "get_session_detail", lambda *_args, **_kwargs: None)

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "source_finding",
            "start_agent_task",
            payload={
                "idempotencyKey": "start-missing-session",
                "budgetRequest": BUDGET_REQUEST,
            },
        )

    assert getattr(exc.value, "code", "") == "task_session_not_canonical"
    persisted = service.get_run(run["runId"])
    assert service._store.get_session_binding(run["runId"], "source_finding") is None
    assert persisted["nodeRuns"][0]["status"] == "ready"
