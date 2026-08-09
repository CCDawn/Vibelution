"""Build the next NodeRun, Handoff and optional HumanTask records."""

from __future__ import annotations

import uuid
from typing import Any

from core.research.workflow.models import WorkflowDefinition

from .human_task_records import build_pending_human_task, human_task_id


def build_node_run(
    *,
    run_id: str,
    node_id: str,
    actor_type: str,
    agent_id: str,
    input_hash: str,
    checkpoint_id: str,
    status: str = "ready",
) -> dict[str, Any]:
    return {
        "nodeRunId": f"nr-{run_id}-{node_id}-a1",
        "runId": run_id,
        "nodeId": node_id,
        "attempt": 1,
        "actorType": actor_type,
        "agentId": agent_id,
        "taskId": "",
        "sessionId": "",
        "status": status,
        "inputSnapshotHash": input_hash,
        "idempotencyKey": f"{run_id}:{node_id}:1",
        "modelRef": "",
        "budgetLedgerRef": "",
        "artifactRefs": [],
        "checkpointId": checkpoint_id,
        "startedAt": "",
        "finishedAt": "",
        "failureCode": "",
        "failureSummary": "",
        "supersedesNodeRunId": "",
    }


def build_successor_records(
    record: dict[str, Any],
    *,
    definition: WorkflowDefinition,
    from_node_id: str,
    from_node_run_id: str,
    next_node_ids: list[str],
    checkpoint_id: str,
    input_hash: str,
    output_artifact_refs: list[dict[str, Any]],
    now: str,
    accepted_by: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    bindings = list(record.get("bindingSnapshots") or [])
    node_runs: list[dict[str, Any]] = []
    specs = {
        node_id: next(item for item in definition.nodes if item.nodeId == node_id)
        for node_id in next_node_ids
    }
    for node_id, spec in specs.items():
        binding = next(
            (item for item in bindings if item.get("nodeId") == node_id),
            {},
        )
        node_runs.append(
            build_node_run(
                run_id=str(record.get("runId") or ""),
                node_id=node_id,
                actor_type=spec.actorKind.value,
                agent_id=str(binding.get("agentId") or ""),
                input_hash=input_hash,
                checkpoint_id=checkpoint_id,
                status=(
                    "waiting_human" if spec.actorKind.value == "human" else "ready"
                ),
            )
        )
    edge = next(
        (
            item
            for item in definition.edges
            if item.fromNodeId == from_node_id and item.toNodeId in next_node_ids
        ),
        None,
    )
    if edge is None:
        return node_runs, None, None
    next_run = next(item for item in node_runs if item["nodeId"] == edge.toNodeId)
    next_is_human = next_run["actorType"] == "human"
    handoff_id = f"ho-{uuid.uuid4().hex[:10]}"
    task_id = human_task_id(next_run["nodeRunId"]) if next_is_human else ""
    handoff = {
        "handoffId": handoff_id,
        "workflowId": record["workflowId"],
        "workflowVersionId": record["workflowVersionId"],
        "runId": record["runId"],
        "fromNodeId": from_node_id,
        "fromNodeRunId": from_node_run_id,
        "toNodeId": edge.toNodeId,
        "toNodeRunId": next_run["nodeRunId"],
        "gateKind": edge.gateKind.value,
        "edgeId": edge.edgeId,
        "outputArtifactRefs": output_artifact_refs,
        "inputSnapshotHash": input_hash,
        "status": "waiting_human" if next_is_human else "accepted",
        "offeredAt": now,
        "acceptedAt": "" if next_is_human else now,
        "acceptedBy": "" if next_is_human else accepted_by,
        "rejectionReason": "",
        "supersedesHandoffId": "",
        "humanTaskId": task_id,
    }
    human_task = (
        build_pending_human_task(
            run_id=record["runId"],
            node_id=edge.toNodeId,
            node_run_id=next_run["nodeRunId"],
            checkpoint_id=checkpoint_id,
            handoff_id=handoff_id,
            created_at=now,
        )
        if next_is_human
        else None
    )
    return node_runs, handoff, human_task
