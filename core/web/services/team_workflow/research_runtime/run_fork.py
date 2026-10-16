"""Child WorkflowRun creation for human-gate reject/revise correction forks."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from core.research.workflow.definition_registry import resolve_definition_for_run_record

from .checkpoint_lifecycle import fork_checkpoint_at_node
from .human_gate_artifacts import canonical_sha256
from .node_execution_support import iso, utc_now
from .store import WorkflowRunStore
from .successor_records import build_node_run

# Human-gate reject/revise correction routes.  ``knowledge_handoff`` is the
# only human gate on the live knowledge sideflow; the 3.0.0-only gates
# (protocol_freeze/smoke_gate/candidate_promotion) were removed with the dead
# experiment-definition flow, so an unknown node fails closed below.
_HUMAN_GATE_CORRECTION_ROUTES: dict[str, tuple[str, str]] = {
    "knowledge_handoff": ("knowledge_ingestion", "evidence_relations"),
}


def human_gate_correction_route(node_id: str) -> tuple[str, str]:
    try:
        return _HUMAN_GATE_CORRECTION_ROUTES[node_id]
    except KeyError as exc:
        raise ValueError(f"human gate has no correction route: {node_id}") from exc


def human_gate_child_run_id(
    *,
    parent_run_id: str,
    task_id: str,
    decision: str,
    idempotency_key: str,
) -> str:
    identity = f"{parent_run_id}:{task_id}:{decision}:{idempotency_key}".encode()
    return f"run-{hashlib.sha256(identity).hexdigest()[:12]}"


def create_human_gate_child_run(
    store: WorkflowRunStore,
    checkpoint_path: str,
    *,
    parent: dict[str, Any],
    task: dict[str, Any],
    decision: str,
    idempotency_key: str,
    resolved_by: str,
) -> dict[str, Any]:
    parent_run_id = str(parent["runId"])
    task_id = str(task["taskId"])
    child_run_id = human_gate_child_run_id(
        parent_run_id=parent_run_id,
        task_id=task_id,
        decision=decision,
        idempotency_key=idempotency_key,
    )
    existing = store.get_run(child_run_id)
    if existing is not None:
        if (
            existing.get("parentRunId") == parent_run_id
            and existing.get("forkHumanTaskId") == task_id
            and existing.get("forkIdempotencyKey") == idempotency_key
        ):
            return existing
        raise ValueError("deterministic child run identity collision")

    correction_node_id, predecessor_node_id = human_gate_correction_route(
        str(task.get("nodeId") or "")
    )
    # Fail-closed: fork on the parent's pinned graph; the child record copies
    # the parent's workflowVersionId/structureHash below.
    definition = resolve_definition_for_run_record(parent)
    correction_spec = next(
        item for item in definition.nodes if item.nodeId == correction_node_id
    )
    child_thread_id = child_run_id
    source_checkpoint_id = str(task.get("checkpointId") or "")
    child_checkpoint_id = fork_checkpoint_at_node(
        checkpoint_path,
        source_thread_id=str(parent["threadId"]),
        source_checkpoint_id=source_checkpoint_id,
        child_thread_id=child_thread_id,
        predecessor_node_id=predecessor_node_id,
        resume_node_id=correction_node_id,
        state_patch={"current_node_id": predecessor_node_id},
        definition=definition,
    )
    bindings = list(parent.get("bindingSnapshots") or [])
    binding = next(
        (item for item in bindings if item.get("nodeId") == correction_node_id),
        {},
    )
    inherited_artifact_refs = [
        str(item.get("artifactId") or "")
        for item in parent.get("artifactManifests") or []
        if str(item.get("artifactId") or "")
    ]
    input_hash = canonical_sha256(
        {
            "parentRunId": parent_run_id,
            "sourceCheckpointId": source_checkpoint_id,
            "decision": decision,
            "inheritedArtifactRefs": inherited_artifact_refs,
        }
    )
    correction_run = build_node_run(
        run_id=child_run_id,
        node_id=correction_node_id,
        actor_type=correction_spec.actorKind.value,
        agent_id=str(binding.get("agentId") or ""),
        input_hash=input_hash,
        checkpoint_id=child_checkpoint_id,
    )
    parent_correction_runs = [
        item
        for item in parent.get("nodeRuns") or []
        if item.get("nodeId") == correction_node_id
    ]
    if parent_correction_runs:
        prior = max(
            parent_correction_runs,
            key=lambda item: int(item.get("attempt") or 0),
        )
        correction_run["supersedesNodeRunId"] = str(prior.get("nodeRunId") or "")

    node_order = [item.nodeId for item in definition.nodes]
    correction_index = node_order.index(correction_node_id)
    inherited_completed = [
        node_id
        for node_id in parent.get("completedNodeIds") or []
        if node_id in node_order[:correction_index]
    ]
    created_at = iso(utc_now())
    record = {
        "runId": child_run_id,
        "workflowId": parent["workflowId"],
        "workflowVersionId": parent["workflowVersionId"],
        "structureHash": parent["structureHash"],
        "teamId": parent["teamId"],
        "projectId": parent["projectId"],
        "questionId": parent.get("questionId") or "",
        "threadId": child_thread_id,
        "status": "queued",
        "inputSnapshot": dict(parent.get("inputSnapshot") or {}),
        "bindingSnapshots": bindings,
        "runtimeCurrentNodeIds": [correction_node_id],
        "completedNodeIds": inherited_completed,
        "nodeRuns": [correction_run],
        "artifactManifests": [],
        "inheritedArtifactRefs": inherited_artifact_refs,
        "events": [
            {
                "eventId": f"evt-{uuid.uuid4().hex[:10]}",
                "sequence": 1,
                "occurredAt": created_at,
                "workflowId": parent["workflowId"],
                "workflowVersionId": parent["workflowVersionId"],
                "runId": child_run_id,
                "threadId": child_thread_id,
                "checkpointId": child_checkpoint_id,
                "nodeId": correction_node_id,
                "nodeRunId": correction_run["nodeRunId"],
                "attempt": 1,
                "type": "RunForked",
                "summary": {
                    "parentRunId": parent_run_id,
                    "humanTaskId": task_id,
                    "decision": decision,
                },
            }
        ],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "taskLeases": [],
        "commandReceipts": [],
        "outbox": [],
        "officialCandidateRef": str(parent.get("officialCandidateRef") or ""),
        "baselineCandidateRef": str(parent.get("baselineCandidateRef") or ""),
        "childRunIds": [],
        "parentRunId": parent_run_id,
        "supersedesRunId": parent_run_id,
        "forkedFromRunId": parent_run_id,
        "forkedFromNodeId": str(task.get("nodeId") or ""),
        "forkedFromCheckpointId": source_checkpoint_id,
        "forkHumanTaskId": task_id,
        "forkDecision": decision,
        "forkIdempotencyKey": idempotency_key,
        "forkedBy": resolved_by,
        "completionKind": "",
        "terminalReason": "",
        "createdAt": created_at,
        "langGraph": {
            "engine": "challenge_cup_graph",
            "checkpointId": child_checkpoint_id,
            "completedNodeIds": inherited_completed,
            "startNodeId": correction_node_id,
            "inheritedFromParent": True,
            "sourceCheckpointId": source_checkpoint_id,
        },
        "forkInputHash": canonical_sha256(
            {
                "parentRunId": parent_run_id,
                "taskId": task_id,
                "decision": decision,
                "idempotencyKey": idempotency_key,
            }
        ),
    }
    return store.create_run(record)
