"""Focused fan-out/fan-in coverage for ResearchTaskBundle lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.research.workflow.contracts import ContractValidationError, ResearchTaskBundle
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.models import ActorKind, WorkflowNodeSpec, WorkflowStageId
from core.web.services.team_workflow.research_runtime.agent_node_execution import (
    AgentNodeExecutionError,
    start_agent_node_execution,
)
from core.web.services.team_workflow.research_runtime.external_agent_task_reconciliation import (
    reconcile_external_agent_tasks,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from core.web.services.team_workflow.research_runtime.task_bundle_lifecycle import (
    TaskBundleError,
    bind_agent_task_bundle,
    cancel_task_bundle,
    complete_agent_task_bundle_subtask,
    complete_task_bundle_records,
    create_agent_task_bundle,
    fail_agent_task_bundle_subtask,
    reconcile_expired_task_bundles,
    replace_agent_task_bundle_subtask,
)


def _node_spec() -> WorkflowNodeSpec:
    return WorkflowNodeSpec(
        nodeId="hypothesis_design",
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label="假说设计",
        actorKind=ActorKind.AGENT,
        primaryRoleKey="hypothesis_designer",
        producesArtifactKinds=("hypothesis_fragment",),
    )


def _registered_run_identity() -> dict:
    """Pin the fixture run like production run creation does.

    The definition registry resolves fail-closed, so the fixture must carry
    the workflow identity of the current built definition.
    """

    identity = register_or_resolve(build_challenge_cup_workflow_definition())
    return {
        "workflowId": identity.workflowId,
        "workflowVersionId": identity.workflowVersionId,
    }


def _record() -> dict:
    return {
        "runId": "run-1",
        **_registered_run_identity(),
        "threadId": "thread-1",
        "inputSnapshot": {
            "budgetPolicy": {"maxParallelTasks": 4},
            "researchObjectiveContract": {
                "question": "验证三个假说",
                "hypothesisFirst": True,
            },
            "workflowSessionScopeV3": {"hypothesis_design": "on"},
        },
        "taskBundles": [],
        "modelRoutingDecisions": [],
        "commandReceipts": [],
        "nodeRuns": [
            {
                "nodeRunId": "node-run-1",
                "nodeId": "hypothesis_design",
                "attempt": 1,
                "status": "running",
            }
        ],
        "events": [],
        "status": "running",
    }


def _node_run() -> dict:
    return {
        "nodeRunId": "node-run-1",
        "nodeId": "hypothesis_design",
        "inputSnapshotHash": "a" * 64,
        "artifactRefs": ["artifact-question"],
    }


def _route() -> dict:
    return {
        "decisionId": "route-1",
        "nodeRunId": "node-run-1",
        "modelRef": "model-1",
    }


def _create_bundle(store: WorkflowRunStore) -> dict:
    return create_agent_task_bundle(
        store,
        record=_record(),
        node_run=_node_run(),
        node_spec=_node_spec(),
        model_route=_route(),
        budget_reservation_ref="budget-1",
        idempotency_key="dispatch-1",
        deadline_seconds=300,
        subtask_specs=[
            {
                "selectionId": "selection-1",
                "candidateId": "H1",
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-1",
                    "candidateId": "H1",
                },
            },
            {
                "selectionId": "selection-1",
                "candidateId": "H2",
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-1",
                    "candidateId": "H2",
                },
            },
        ],
        max_concurrency=2,
    )


def _create_three_candidate_bundle(store: WorkflowRunStore) -> dict:
    return create_agent_task_bundle(
        store,
        record=_record(),
        node_run=_node_run(),
        node_spec=_node_spec(),
        model_route=_route(),
        budget_reservation_ref="budget-1",
        idempotency_key="dispatch-three",
        deadline_seconds=300,
        subtask_specs=[
            {
                "selectionId": "selection-1",
                "candidateId": candidate_id,
            }
            for candidate_id in ("H1", "H2", "H3")
        ],
        max_concurrency=3,
    )


def _candidate_ready_record() -> dict:
    record = _record()
    record.update({"teamId": "team-1", "projectId": "project-1"})
    record["bindingSnapshots"] = [
        {
            "nodeId": "hypothesis_design",
            "agentId": "agent-hypothesis",
            "roleKey": "hypothesis_designer",
        }
    ]
    record["nodeRuns"][0].update(
        {
            "actorType": "agent",
            "agentId": "agent-hypothesis",
            "status": "ready",
            "inputSnapshotHash": "a" * 64,
        }
    )
    return record


def _candidate_fan_out_input() -> dict:
    return {
        "selectionId": "selection-1",
        "selectedCandidateIds": ["H1", "H2", "H3"],
        "candidateSnapshots": [
            {"candidateId": candidate} for candidate in ("H1", "H2", "H3")
        ],
        "selection": {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2", "H3"],
        },
    }


def _candidate_started(candidate_id: str, *, attempt: int = 1) -> dict:
    return {
        "taskId": f"task-{candidate_id.lower()}",
        "agentId": "agent-hypothesis",
        "sessionId": f"session-{candidate_id.lower()}",
        "sessionAttempt": attempt,
        "turn": {"turnId": f"turn-{candidate_id.lower()}"},
        "task": {
            "taskId": f"task-{candidate_id.lower()}",
            "agentId": "agent-hypothesis",
            "sessionId": f"session-{candidate_id.lower()}",
            "sessionAttempt": attempt,
            "turn": {"turnId": f"turn-{candidate_id.lower()}"},
        },
        "chatRoute": f"/chat?session=session-{candidate_id.lower()}",
    }


def _patch_candidate_start_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.load_hypothesis_fan_out_input",
        lambda _record: _candidate_fan_out_input(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.select_model_route",
        lambda *_args, **_kwargs: {
            "decisionId": "route-1",
            "nodeRunId": "node-run-1",
            "modelRef": "model-1",
            "purpose": "hypothesis",
            "estimatedCost": 1.0,
            "escalationReason": "",
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.reserve_node_budget",
        lambda *_args, **_kwargs: {"reservationId": "budget-1"},
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._require_canonical_task_session",
        lambda **_kwargs: None,
    )


def test_contract_round_trips_scope_attempt_turn_and_rejects_oversized_concurrency() -> None:
    payload = {
        "bundleId": "bundle-1",
        "runId": "run-1",
        "parentNodeRunId": "node-run-1",
        "objective": "验证三个假说",
        "inputArtifactRefs": [],
        "subtasks": [
            {
                "subtaskId": "subtask-1",
                "role": "researcher",
                "scope": {"kind": "workflow_candidate", "candidateId": "H1"},
                "attempt": 2,
                "acceptanceContract": {"artifactKinds": ["hypothesis_fragment"]},
                "budgetReservationRef": "budget-1",
                "deadlineAt": "2026-08-22T00:00:00Z",
                "status": "running",
                "taskId": "task-1",
                "sessionId": "session-1",
                "turnId": "turn-1",
                "outputArtifactRefs": [],
            }
        ],
        "maxConcurrency": 1,
        "aggregationContract": {"mode": "all_required_ordered"},
        "status": "running",
    }

    bundle = ResearchTaskBundle.from_dict(payload)

    assert bundle.subtasks[0].scope["candidateId"] == "H1"
    assert bundle.subtasks[0].attempt == 2
    assert bundle.subtasks[0].turnId == "turn-1"
    assert bundle.to_dict()["subtasks"][0]["scope"]["kind"] == "workflow_candidate"

    with pytest.raises(ContractValidationError, match="maxConcurrency"):
        ResearchTaskBundle.from_dict({**payload, "maxConcurrency": 2})


def test_create_fans_out_in_order_and_replays_without_duplicates(tmp_path) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_record())

    first = _create_bundle(store)
    replay = _create_bundle(store)
    persisted = store.get_run("run-1")

    assert [item["scope"]["candidateId"] for item in first["subtasks"]] == ["H1", "H2"]
    assert [item["attempt"] for item in first["subtasks"]] == [1, 1]
    assert [item["subtaskId"] for item in first["subtasks"]] == [
        "node-run-1:selection-1:H1",
        "node-run-1:selection-1:H2",
    ]
    assert replay == first
    assert len(persisted["taskBundles"]) == 1
    assert len(persisted["taskBundles"][0]["subtasks"]) == 2

    with pytest.raises(TaskBundleError, match="candidateId values must be unique"):
        create_agent_task_bundle(
            store,
            record={**_record(), "runId": "run-duplicate"},
            node_run={**_node_run(), "nodeRunId": "node-run-duplicate"},
            node_spec=_node_spec(),
            model_route=_route(),
            budget_reservation_ref="budget-duplicate",
            idempotency_key="dispatch-duplicate",
            deadline_seconds=300,
            selected_candidate_ids=["H1", "H1"],
            selection_id="selection-duplicate",
        )


def test_multi_subtask_binding_requires_id_and_updates_selected_subtask(tmp_path) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_record())
    bundle = _create_bundle(store)

    with pytest.raises(TaskBundleError, match="subtaskId"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            task_id="task-h1",
            session_id="session-h1",
            turn_id="turn-h1",
        )

    bound = bind_agent_task_bundle(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H2",
        task_id="task-h2",
        session_id="session-h2",
        turn_id="turn-h2",
    )
    assert bound["status"] == "running"
    assert bound["subtasks"][0]["taskId"] == ""
    assert bound["subtasks"][1]["taskId"] == "task-h2"

    replay = bind_agent_task_bundle(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H2",
        task_id="task-h2",
        session_id="session-h2",
        turn_id="turn-h2",
    )
    assert replay == bound


def test_completion_derives_bundle_status_from_all_subtasks(tmp_path) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_record())
    bundle = _create_bundle(store)

    bind_agent_task_bundle(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H1",
        task_id="task-h1",
        session_id="session-h1",
        turn_id="turn-h1",
    )
    bind_agent_task_bundle(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H2",
        task_id="task-h2",
        session_id="session-h2",
        turn_id="turn-h2",
    )

    running = store.get_run("run-1")
    after_h1 = complete_task_bundle_records(
        running,
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        output_artifact_refs=["artifact-h1"],
        completed_at="2026-08-22T00:01:00Z",
    )
    assert after_h1[0]["status"] == "running"
    assert after_h1[0]["subtasks"][0]["outputArtifactRefs"] == ["artifact-h1"]
    assert after_h1[0]["subtasks"][1]["status"] == "running"

    after_h2 = complete_task_bundle_records(
        {**running, "taskBundles": after_h1},
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H2",
        output_artifact_refs=["artifact-h2"],
        completed_at="2026-08-22T00:02:00Z",
    )
    assert after_h2[0]["status"] == "succeeded"
    assert [item["status"] for item in after_h2[0]["subtasks"]] == [
        "succeeded",
        "succeeded",
    ]
    aggregated = complete_task_bundle_records(
        {**running, "taskBundles": after_h2},
        node_run_id="node-run-1",
        output_artifact_refs=["hypothesis_set:portfolio-1"],
        completed_at="2026-08-22T00:03:00Z",
    )
    assert aggregated[0]["aggregationArtifactRefs"] == [
        "hypothesis_set:portfolio-1"
    ]


def test_candidate_failure_and_exact_retry_preserve_succeeded_siblings(tmp_path) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_record())
    bundle = _create_three_candidate_bundle(store)
    for candidate in ("H1", "H2", "H3"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate}",
            task_id=f"task-{candidate.lower()}",
            session_id=f"session-{candidate.lower()}",
            turn_id=f"turn-{candidate.lower()}",
        )

    running = store.get_run("run-1")
    after_h1 = complete_task_bundle_records(
        running,
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        output_artifact_refs=["fragment-h1"],
        completed_at="2026-08-22T00:01:00Z",
        attempt=1,
    )
    after_h3 = complete_task_bundle_records(
        {**running, "taskBundles": after_h1},
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H3",
        output_artifact_refs=["fragment-h3"],
        completed_at="2026-08-22T00:02:00Z",
        attempt=1,
    )
    store.update_run("run-1", {"taskBundles": after_h3})

    failed = fail_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H2",
        failure_code="external_task_failed",
        failure_summary="H2 failed",
        attempt=1,
    )
    assert failed["status"] == "failed"
    assert [item["status"] for item in failed["subtasks"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert failed["subtasks"][0]["taskId"] == "task-h1"
    assert failed["subtasks"][2]["taskId"] == "task-h3"

    retried = replace_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H2",
        retry_task_id="task-h2",
        task_id="task-h2-retry",
        session_id="session-h2-retry",
        turn_id="turn-h2-retry",
        attempt=2,
        idempotency_key="retry-h2-1",
    )
    assert retried["status"] == "running"
    assert [item["status"] for item in retried["subtasks"]] == [
        "succeeded",
        "running",
        "succeeded",
    ]
    assert retried["subtasks"][1]["taskId"] == "task-h2-retry"
    assert retried["subtasks"][1]["attempt"] == 2
    assert retried["subtasks"][1]["outputArtifactRefs"] == []
    assert retried["subtasks"][0]["taskId"] == "task-h1"
    assert retried["subtasks"][2]["taskId"] == "task-h3"

    replay = replace_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        subtask_id="node-run-1:selection-1:H2",
        retry_task_id="task-h2",
        task_id="task-h2-retry",
        session_id="session-h2-retry",
        turn_id="turn-h2-retry",
        attempt=2,
        idempotency_key="retry-h2-1",
    )
    assert replay == retried


def test_candidate_reconciliation_reads_each_task_and_only_fails_h2(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    record = _record()
    record["nodeRuns"][0].update(
        {
            "actorType": "agent",
            "agentId": "agent-hypothesis",
            "taskId": "task-h1",
            "sessionId": "session-h1",
        }
    )
    record["taskLeases"] = [
        {
            "nodeRunId": "node-run-1",
            "status": "running",
            "leaseExpiresAt": "2099-01-01T00:00:00Z",
        }
    ]
    store.create_run(record)
    bundle = _create_three_candidate_bundle(store)
    for candidate in ("H1", "H2", "H3"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate}",
            task_id=f"task-{candidate.lower()}",
            session_id=f"session-{candidate.lower()}",
            turn_id=f"turn-{candidate.lower()}",
        )
    tasks = {
        "task-h1": {
            "taskId": "task-h1",
            "sessionId": "session-h1",
            "status": "completed",
            "resultRefs": ["fragment-h1"],
        },
        "task-h2": {
            "taskId": "task-h2",
            "sessionId": "session-h2",
            "status": "failed",
            "failureCode": "model_failed",
            "failureSummary": "H2 failed",
        },
        "task-h3": {
            "taskId": "task-h3",
            "sessionId": "session-h3",
            "status": "completed",
            "resultRefs": ["fragment-h3"],
        },
    }
    looked_up: list[str] = []

    def load_task(_record: dict, node_run: dict) -> dict:
        looked_up.append(str(node_run["taskId"]))
        return tasks[str(node_run["taskId"])]

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.external_agent_task_reconciliation.load_external_agent_task",
        load_task,
    )

    reconciled = reconcile_external_agent_tasks(
        store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
        record=store.get_run("run-1"),
    )
    persisted_bundle = reconciled["taskBundles"][0]
    assert looked_up == ["task-h1", "task-h2", "task-h3"]
    assert [item["status"] for item in persisted_bundle["subtasks"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert persisted_bundle["subtasks"][0]["outputArtifactRefs"] == ["fragment-h1"]
    assert persisted_bundle["subtasks"][2]["outputArtifactRefs"] == ["fragment-h3"]
    assert persisted_bundle["subtasks"][1]["failureCode"] == "model_failed"
    assert reconciled["nodeRuns"][0]["status"] == "running"

    replay = reconcile_external_agent_tasks(
        store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
        record=reconciled,
    )
    assert replay["taskBundles"] == reconciled["taskBundles"]


def test_start_agent_task_retry_candidate_replaces_only_h2_and_replays(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    record = _record()
    record["nodeRuns"][0].update(
        {
            "actorType": "agent",
            "agentId": "agent-hypothesis",
            "taskId": "task-h1",
            "sessionId": "session-h1",
        }
    )
    store.create_run(record)
    bundle = _create_three_candidate_bundle(store)
    for candidate in ("H1", "H2", "H3"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate}",
            task_id=f"task-{candidate.lower()}",
            session_id=f"session-{candidate.lower()}",
            turn_id=f"turn-{candidate.lower()}",
        )
    running = store.get_run("run-1")
    after_h1 = complete_task_bundle_records(
        running,
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        output_artifact_refs=["fragment-h1"],
        completed_at="2026-08-22T00:01:00Z",
        attempt=1,
    )
    after_h3 = complete_task_bundle_records(
        {**running, "taskBundles": after_h1},
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H3",
        output_artifact_refs=["fragment-h3"],
        completed_at="2026-08-22T00:02:00Z",
        attempt=1,
    )
    store.update_run("run-1", {"taskBundles": after_h3})
    fail_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H2",
        failure_code="model_failed",
        failure_summary="H2 failed",
        attempt=1,
    )
    calls: list[dict] = []

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.load_hypothesis_fan_out_input",
        lambda _record: {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2", "H3"],
            "candidateSnapshots": [
                {"candidateId": candidate} for candidate in ("H1", "H2", "H3")
            ],
            "selection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2", "H3"],
            },
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._require_canonical_task_session",
        lambda **_kwargs: None,
    )

    def start_retry(_store, _record, **kwargs):
        calls.append(dict(kwargs["payload"]))
        return _record, {
            "taskId": "task-h2-retry",
            "agentId": "agent-hypothesis",
            "sessionId": "session-h2-retry",
            "sessionAttempt": 2,
            "turn": {"turnId": "turn-h2-retry"},
            "task": {
                "taskId": "task-h2-retry",
                "agentId": "agent-hypothesis",
                "sessionId": "session-h2-retry",
                "sessionAttempt": 2,
                "turn": {"turnId": "turn-h2-retry"},
            },
            "chatRoute": "/chat?session=session-h2-retry",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        start_retry,
    )

    first = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={
            "retryCandidateId": "H2",
            "idempotencyKey": "retry-h2-1",
        },
    )
    assert calls[0]["formalRetry"] is True
    assert calls[0]["retryTaskId"] == "task-h2"
    assert first["taskId"] == "task-h2-retry"
    assert first["taskBundle"]["subtasks"][1]["attempt"] == 2
    assert first["taskBundle"]["subtasks"][1]["taskId"] == "task-h2-retry"
    assert first["taskBundle"]["subtasks"][0]["taskId"] == "task-h1"
    assert first["taskBundle"]["subtasks"][2]["taskId"] == "task-h3"
    assert store.get_run("run-1")["nodeRuns"][0]["taskId"] == "task-h1"

    replay = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={
            "retryCandidateId": "H2",
            "idempotencyKey": "retry-h2-1",
        },
    )
    assert replay["idempotentReplay"] is True
    assert len(calls) == 1


def test_candidate_fan_out_queues_excess_candidate_until_slot_frees(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_candidate_ready_record())
    _patch_candidate_start_dependencies(monkeypatch)
    started: list[str] = []

    def recording_start(_store, current, **kwargs):
        candidate_id = str(kwargs["payload"]["candidateId"])
        started.append(candidate_id)
        return current, _candidate_started(candidate_id)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        recording_start,
    )

    result = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={"idempotencyKey": "dispatch-queued", "maxConcurrency": 2},
    )

    # Only the first maxConcurrency candidates start; the excess candidate
    # stays pending in the bundle instead of failing the dispatch.
    assert started == ["H1", "H2"]
    assert result["taskBundle"]["maxConcurrency"] == 2
    assert result["taskIds"] == ["task-h1", "task-h2"]
    assert [item["candidateId"] for item in result["scopedSessions"]] == [
        "H1",
        "H2",
    ]
    persisted = store.get_run("run-1")
    subtasks = persisted["taskBundles"][0]["subtasks"]
    assert [item["status"] for item in subtasks] == [
        "running",
        "running",
        "pending",
    ]
    assert subtasks[2]["taskId"] == ""

    completed = complete_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        output_artifact_refs=["fragment-h1"],
        attempt=1,
    )

    # The terminal candidate hands its slot to the queued candidate.  The
    # dispatch runs after the terminal mutation, so read the persisted bundle.
    assert started == ["H1", "H2", "H3"]
    completed = store.get_run("run-1")["taskBundles"][0]
    assert [item["status"] for item in completed["subtasks"]] == [
        "succeeded",
        "running",
        "running",
    ]
    assert completed["subtasks"][2]["taskId"] == "task-h3"


def test_running_candidate_failure_starts_pending_candidate_and_keeps_siblings(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_candidate_ready_record())
    _patch_candidate_start_dependencies(monkeypatch)
    started: list[str] = []

    def recording_start(_store, current, **kwargs):
        candidate_id = str(kwargs["payload"]["candidateId"])
        started.append(candidate_id)
        return current, _candidate_started(candidate_id)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        recording_start,
    )

    bundle = create_agent_task_bundle(
        store,
        record=_candidate_ready_record(),
        node_run=_node_run(),
        node_spec=_node_spec(),
        model_route=_route(),
        budget_reservation_ref="budget-1",
        idempotency_key="dispatch-fail-queue",
        deadline_seconds=300,
        subtask_specs=[
            {"selectionId": "selection-1", "candidateId": candidate_id}
            for candidate_id in ("H1", "H2", "H3")
        ],
        max_concurrency=2,
    )
    for candidate_id in ("H1", "H2"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate_id}",
            task_id=f"task-{candidate_id.lower()}",
            session_id=f"session-{candidate_id.lower()}",
            turn_id=f"turn-{candidate_id.lower()}",
        )

    failed = fail_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        failure_code="external_task_failed",
        failure_summary="H1 failed",
        attempt=1,
    )

    # The failed running candidate preserves its siblings and the freed slot
    # starts the pending candidate normally.  The dispatch runs after the
    # terminal mutation, so read the persisted bundle.
    assert started == ["H3"]
    failed = store.get_run("run-1")["taskBundles"][0]
    assert [item["status"] for item in failed["subtasks"]] == [
        "failed",
        "running",
        "running",
    ]
    assert failed["subtasks"][1]["taskId"] == "task-h2"
    assert not failed["subtasks"][1].get("failureCode")
    assert failed["subtasks"][2]["taskId"] == "task-h3"
    assert not failed["subtasks"][2].get("failureCode")


def test_shadow_candidate_scope_keeps_legacy_single_session_execution(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    record = _candidate_ready_record()
    record["inputSnapshot"]["workflowSessionScopeV3"] = {
        "hypothesis_design": "shadow"
    }
    store.create_run(record)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.load_hypothesis_fan_out_input",
        lambda _record: _candidate_fan_out_input(),
    )

    _patch_candidate_start_dependencies(monkeypatch)
    starts: list[dict] = []

    def start_legacy(_store, current, **kwargs):
        starts.append(dict(kwargs["payload"]))
        return current, _candidate_started("H1")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        start_legacy,
    )

    before = store.get_run("run-1")
    result = start_agent_node_execution(
        store,
        record=before,
        node_id="hypothesis_design",
        payload={"idempotencyKey": "shadow-dispatch"},
    )

    assert result["taskId"] == "task-h1"
    assert result["chatRoute"] == "/chat?session=session-h1"
    assert result["sessionBinding"]["sessionId"] == "session-h1"
    assert len(result["taskBundle"]["subtasks"]) == 1
    assert starts == [{"idempotencyKey": "shadow-dispatch"}]
    assert result["sessionScopeShadow"]["candidateCount"] == 3
    assert len(result["sessionScopeShadow"]["scopeHash"]) == 64
    assert result["idempotentReplay"] is False
    after_start = store.get_run("run-1")
    assert after_start["nodeRuns"][0]["status"] == "running"

    with pytest.raises(
        AgentNodeExecutionError,
        match="retryCandidateId is only valid for candidate fan-out nodes",
    ) as exc_info:
        start_agent_node_execution(
            store,
            record=store.get_run("run-1"),
            node_id="hypothesis_design",
            payload={
                "idempotencyKey": "shadow-retry",
                "retryCandidateId": "H1",
            },
        )
    assert exc_info.value.code == "candidate_retry_not_supported"
    assert store.get_run("run-1") == after_start


def test_start_agent_task_retry_first_candidate_syncs_node_run_and_binding(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    record = _record()
    record["bindingSnapshots"] = [
        {
            "nodeId": "hypothesis_design",
            "agentId": "agent-hypothesis",
            "roleKey": "hypothesis_designer",
        }
    ]
    record["nodeRuns"][0].update(
        {
            "actorType": "agent",
            "agentId": "agent-hypothesis",
            "taskId": "task-h1",
            "sessionId": "session-h1",
            "turnId": "turn-h1",
        }
    )
    store.create_run(record)
    bundle = _create_three_candidate_bundle(store)
    for candidate in ("H1", "H2", "H3"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate}",
            task_id=f"task-{candidate.lower()}",
            session_id=f"session-{candidate.lower()}",
            turn_id=f"turn-{candidate.lower()}",
        )
    fail_agent_task_bundle_subtask(
        store,
        run_id="run-1",
        node_run_id="node-run-1",
        subtask_id="node-run-1:selection-1:H1",
        failure_code="model_failed",
        failure_summary="H1 failed",
        attempt=1,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution.load_hypothesis_fan_out_input",
        lambda _record: {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2", "H3"],
            "candidateSnapshots": [
                {"candidateId": candidate} for candidate in ("H1", "H2", "H3")
            ],
            "selection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2", "H3"],
            },
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._require_canonical_task_session",
        lambda **_kwargs: None,
    )
    calls: list[dict] = []

    def start_retry(_store, _record, **kwargs):
        calls.append(dict(kwargs["payload"]))
        return _record, {
            "taskId": "task-h1-retry",
            "agentId": "agent-hypothesis",
            "sessionId": "session-h1-retry",
            "sessionAttempt": 2,
            "turn": {"turnId": "turn-h1-retry"},
            "task": {
                "taskId": "task-h1-retry",
                "agentId": "agent-hypothesis",
                "sessionId": "session-h1-retry",
                "sessionAttempt": 2,
                "turn": {"turnId": "turn-h1-retry"},
            },
            "chatRoute": "/chat?session=session-h1-retry",
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        start_retry,
    )

    result = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={
            "retryCandidateId": "H1",
            "idempotencyKey": "retry-h1-1",
        },
    )

    assert calls[0]["formalRetry"] is True
    assert calls[0]["retryTaskId"] == "task-h1"
    assert result["taskId"] == "task-h1-retry"
    persisted = store.get_run("run-1")
    node_run = persisted["nodeRuns"][0]
    assert {
        key: node_run[key] for key in ("taskId", "sessionId", "turnId")
    } == {
        "taskId": "task-h1-retry",
        "sessionId": "session-h1-retry",
        "turnId": "turn-h1-retry",
    }
    binding = store.get_session_binding("run-1", "hypothesis_design")
    assert {
        key: binding[key] for key in ("taskId", "sessionId", "turnId", "sessionAttempt")
    } == {
        "taskId": "task-h1-retry",
        "sessionId": "session-h1-retry",
        "turnId": "turn-h1-retry",
        "sessionAttempt": 2,
    }
    # The retry binding echoes the attempt-start checkpoint as an audit
    # reference under the renamed key, never as a recovery pointer.
    assert binding["anchoredAtCheckpointId"] == ""
    assert "checkpointId" not in binding


def test_session_binding_anchor_checkpoint_is_audit_reference(tmp_path) -> None:
    """anchoredAtCheckpointId is attempt-start provenance, not a resume pointer."""

    from core.web.services.team_workflow.research_runtime.session_binding_bridge import (
        SessionBindingBridge,
    )

    store = WorkflowRunStore(tmp_path / "runs")
    store.create_run(
        {
            "runId": "run-anchor-1",
            **_registered_run_identity(),
            "threadId": "thread-anchor-1",
            "bindingSnapshots": [
                {
                    "nodeId": "hypothesis_design",
                    "agentId": "agent-hypothesis",
                    "roleKey": "hypothesis_designer",
                }
            ],
            "nodeRuns": [
                {
                    "nodeRunId": "node-run-anchor-1",
                    "nodeId": "hypothesis_design",
                    "attempt": 1,
                    "status": "running",
                    "checkpointId": "ckpt-at-attempt-start",
                }
            ],
            "events": [],
            "status": "running",
        }
    )
    binding = SessionBindingBridge(store).put(
        store.get_run("run-anchor-1"),
        "hypothesis_design",
        {
            "agentId": "agent-hypothesis",
            "nodeRunId": "node-run-anchor-1",
            "nodeAttempt": 1,
            "sessionId": "session-anchor-1",
            "sessionAttempt": 1,
            "taskId": "task-anchor-1",
            "turnId": "turn-anchor-1",
            "anchoredAtCheckpointId": "ckpt-at-attempt-start",
        },
    )
    assert binding["anchoredAtCheckpointId"] == "ckpt-at-attempt-start"
    assert "checkpointId" not in binding


def test_partial_candidate_start_binds_and_reconciles_started_siblings(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_candidate_ready_record())
    _patch_candidate_start_dependencies(monkeypatch)
    attempted: list[str] = []

    def flaky_start(_store, current, **kwargs):
        candidate_id = str(kwargs["payload"]["candidateId"])
        attempted.append(candidate_id)
        if candidate_id == "H2":
            raise AgentNodeExecutionError(
                "H2 start failed", code="h2_start_failed"
            )
        return current, _candidate_started(candidate_id)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        flaky_start,
    )

    result = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={"idempotencyKey": "dispatch-partial"},
    )

    assert attempted == ["H1", "H2", "H3"]
    assert result["taskIds"] == ["task-h1", "task-h3"]
    assert [item["candidateId"] for item in result["scopedSessions"]] == [
        "H1",
        "H3",
    ]
    persisted = store.get_run("run-1")
    subtasks = persisted["taskBundles"][0]["subtasks"]
    assert [item["status"] for item in subtasks] == [
        "running",
        "failed",
        "running",
    ]
    assert subtasks[1]["failureCode"] == "h2_start_failed"
    assert persisted["nodeRuns"][0]["status"] == "running"
    assert persisted["nodeRuns"][0]["taskId"] == "task-h1"
    assert [item["status"] for item in persisted["taskLeases"]] == ["running"]

    lookups: list[str] = []

    def load_completed(_record, candidate_node_run):
        task_id = str(candidate_node_run["taskId"])
        lookups.append(task_id)
        return {
            "taskId": task_id,
            "sessionId": str(candidate_node_run["sessionId"]),
            "status": "completed",
            "resultRefs": [f"fragment-{task_id}"],
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.external_agent_task_reconciliation.load_external_agent_task",
        load_completed,
    )
    reconciled = reconcile_external_agent_tasks(
        store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
        record=persisted,
    )
    assert lookups == ["task-h1", "task-h3"]
    assert [
        item["status"] for item in reconciled["taskBundles"][0]["subtasks"]
    ] == ["succeeded", "failed", "succeeded"]
    assert reconciled["nodeRuns"][0]["status"] == "running"


def test_first_candidate_start_failure_allows_fresh_retry_without_formal_retry(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_candidate_ready_record())
    _patch_candidate_start_dependencies(monkeypatch)

    def fail_first_then_start(_store, current, **kwargs):
        candidate_id = str(kwargs["payload"]["candidateId"])
        if candidate_id == "H1":
            raise AgentNodeExecutionError(
                "H1 start failed", code="h1_start_failed"
            )
        return current, _candidate_started(candidate_id)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        fail_first_then_start,
    )
    initial = start_agent_node_execution(
        store,
        record=store.get_run("run-1"),
        node_id="hypothesis_design",
        payload={"idempotencyKey": "dispatch-first-failure"},
    )
    assert initial["taskIds"] == ["task-h2", "task-h3"]
    persisted = store.get_run("run-1")
    assert persisted["taskBundles"][0]["subtasks"][0]["taskId"] == ""
    assert persisted["taskBundles"][0]["subtasks"][0]["attempt"] == 1
    assert persisted["nodeRuns"][0]["taskId"] == "task-h2"
    assert store.get_session_binding("run-1", "hypothesis_design")["taskId"] == "task-h2"

    retry_payloads: list[dict] = []

    def fresh_retry(_store, current, **kwargs):
        retry_payloads.append(dict(kwargs["payload"]))
        return current, _candidate_started("H1-retry", attempt=1)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        fresh_retry,
    )
    retried = start_agent_node_execution(
        store,
        record=persisted,
        node_id="hypothesis_design",
        payload={
            "retryCandidateId": "H1",
            "idempotencyKey": "retry-h1-fresh",
        },
    )

    assert retry_payloads[0].get("formalRetry") is not True
    assert retry_payloads[0].get("retryTaskId", "") == ""
    assert retried["taskId"] == "task-h1-retry"
    after_retry = store.get_run("run-1")
    h1 = after_retry["taskBundles"][0]["subtasks"][0]
    assert h1["taskId"] == "task-h1-retry"
    assert h1["attempt"] == 1
    assert after_retry["nodeRuns"][0]["taskId"] == "task-h1-retry"
    assert after_retry["nodeRuns"][0]["status"] == "running"
    assert store.get_session_binding("run-1", "hypothesis_design")["taskId"] == "task-h1-retry"


def test_all_candidate_start_failures_leave_no_active_anchor_and_fresh_retry_can_start(
    monkeypatch, tmp_path
) -> None:
    store = WorkflowRunStore(tmp_path)
    store.create_run(_candidate_ready_record())
    _patch_candidate_start_dependencies(monkeypatch)

    def always_fail(_store, current, **_kwargs):
        raise AgentNodeExecutionError(
            "candidate start failed", code="candidate_start_failed"
        )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        always_fail,
    )
    with pytest.raises(
        AgentNodeExecutionError,
        match="all candidate tasks failed to start",
    ) as exc_info:
        start_agent_node_execution(
            store,
            record=store.get_run("run-1"),
            node_id="hypothesis_design",
            payload={"idempotencyKey": "dispatch-all-failed"},
        )
    assert exc_info.value.code == "candidate_fan_out_start_failed"
    failed = store.get_run("run-1")
    assert failed["nodeRuns"][0]["status"] == "ready"
    assert failed["nodeRuns"][0].get("taskId", "") == ""
    assert failed.get("taskLeases", []) == []
    assert store.get_session_binding("run-1", "hypothesis_design") is None
    assert [
        item["status"] for item in failed["taskBundles"][0]["subtasks"]
    ] == ["failed", "failed", "failed"]
    assert all(
        not item.get("taskId") for item in failed["taskBundles"][0]["subtasks"]
    )

    retry_payloads: list[dict] = []

    def fresh_retry(_store, current, **kwargs):
        retry_payloads.append(dict(kwargs["payload"]))
        return current, _candidate_started("H1-retry", attempt=1)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_node_execution._start_external_task",
        fresh_retry,
    )
    retried = start_agent_node_execution(
        store,
        record=failed,
        node_id="hypothesis_design",
        payload={
            "retryCandidateId": "H1",
            "idempotencyKey": "retry-h1-after-all-failed",
        },
    )
    assert retry_payloads[0].get("formalRetry") is not True
    assert retry_payloads[0].get("retryTaskId", "") == ""
    assert retried["taskId"] == "task-h1-retry"
    recovered = store.get_run("run-1")
    assert recovered["nodeRuns"][0]["status"] == "running"
    assert recovered["nodeRuns"][0]["taskId"] == "task-h1-retry"
    assert len(recovered["taskLeases"]) == 1


def test_cancel_and_expire_cover_every_active_subtask(monkeypatch, tmp_path) -> None:
    stopped: list[tuple[str, str]] = []

    def stop(session_id: str, *, expected_turn_id: str) -> dict:
        stopped.append((session_id, expected_turn_id))
        return {"sessionId": session_id, "turnId": expected_turn_id, "status": "stopped"}

    monkeypatch.setattr(
        "core.web.services.session_service.request_stop_session_turn", stop
    )
    store = WorkflowRunStore(tmp_path)
    store.create_run(_record())
    bundle = _create_bundle(store)
    for candidate in ("H1", "H2"):
        bind_agent_task_bundle(
            store,
            run_id="run-1",
            bundle_id=bundle["bundleId"],
            subtask_id=f"node-run-1:selection-1:{candidate}",
            task_id=f"task-{candidate.lower()}",
            session_id=f"session-{candidate.lower()}",
            turn_id=f"turn-{candidate.lower()}",
        )

    cancelled = cancel_task_bundle(
        store,
        run_id="run-1",
        bundle_id=bundle["bundleId"],
        reason="operator requested stop",
        idempotency_key="cancel-1",
    )
    assert stopped == [("session-h1", "turn-h1"), ("session-h2", "turn-h2")]
    assert [item["status"] for item in cancelled["taskBundles"][0]["subtasks"]] == [
        "cancelled",
        "cancelled",
    ]

    store.create_run({**_record(), "runId": "run-2"})
    create_agent_task_bundle(
        store,
        record={**_record(), "runId": "run-2"},
        node_run={**_node_run(), "nodeRunId": "node-run-2"},
        node_spec=_node_spec(),
        model_route={**_route(), "decisionId": "route-2"},
        budget_reservation_ref="budget-2",
        idempotency_key="dispatch-2",
        deadline_seconds=300,
        subtask_specs=[
            {
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-2",
                    "candidateId": "H1",
                }
            },
            {
                "scope": {
                    "kind": "workflow_candidate",
                    "selectionId": "selection-2",
                    "candidateId": "H2",
                }
            },
        ],
        max_concurrency=2,
    )
    record = store.get_run("run-2")
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    record["taskBundles"][0]["subtasks"][0]["deadlineAt"] = expired_at
    record["taskBundles"][0]["subtasks"][1]["deadlineAt"] = expired_at
    store.update_run("run-2", {"taskBundles": record["taskBundles"]})
    reconciled = reconcile_expired_task_bundles(store, run_id="run-2")
    assert reconciled["taskBundles"][0]["status"] == "cancelled"
    assert reconciled["commandReceipts"][0]["idempotencyKey"].startswith("expire:bundle-")
