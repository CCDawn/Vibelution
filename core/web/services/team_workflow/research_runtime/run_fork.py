"""Create child WorkflowRun for revise_protocol (protocol revision fork)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from typing import Any

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.research.workflow.definition_registry import resolve_definition_for_run_record

from .checkpoint_lifecycle import fork_checkpoint_at_node
from .human_gate_artifacts import canonical_sha256
from .node_execution_support import iso, utc_now
from .store import WorkflowRunStore
from .successor_records import build_node_run

_HUMAN_GATE_CORRECTION_ROUTES: dict[str, tuple[str, str]] = {
    "knowledge_handoff": ("knowledge_ingestion", "evidence_relations"),
    "protocol_freeze": ("protocol_design", "hypothesis_design"),
    "smoke_gate": ("protocol_design", "hypothesis_design"),
    "candidate_promotion": ("version_governance", "iteration_decision"),
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
    child_thread_id = f"thread-{child_run_id}"
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


def build_child_run_skeleton(
    *,
    parent: dict[str, Any],
    decision: dict[str, Any],
    fork_checkpoint_id: str,
    utc_now: Callable[[], str],
    child_run_id: str | None = None,
) -> dict[str, Any]:
    """Build the durable record fields for a revision child (not yet started in graph)."""
    parent_id = str(parent.get("runId") or "")
    decision_id = str(decision.get("decisionId") or "")
    artifacts = dict((parent.get("langGraph") or {}).get("artifacts") or {})
    child_id = child_run_id or f"run-{uuid.uuid4().hex[:12]}"
    return {
        "runId": child_id,
        "workflowId": parent.get("workflowId") or CHALLENGE_CUP_WORKFLOW_ID,
        "workflowVersionId": parent.get("workflowVersionId") or "",
        "structureHash": parent.get("structureHash") or "",
        "teamId": parent.get("teamId") or "",
        "projectId": parent.get("projectId") or "",
        "threadId": f"thread-{child_id}",
        "status": "queued",
        "runtimeCurrentNodeIds": ["protocol_design"],
        "parentRunId": parent_id,
        "forkedFromRunId": parent_id,
        "forkedFromNodeId": "iteration_decision",
        "forkedFromCheckpointId": fork_checkpoint_id,
        "forkDecisionId": decision_id,
        "inheritedKnowledgePackageRef": str(artifacts.get("knowledge_package") or ""),
        "inheritedEvaluationReportRef": str(artifacts.get("evaluation_report") or ""),
        "inheritedFrozenProtocolRef": str(artifacts.get("frozen_protocol") or ""),
        "bindingSnapshots": list(parent.get("bindingSnapshots") or []),
        "events": [],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "nodeAttempts": {},
        "officialCandidateRef": "",
        "baselineCandidateRef": str(parent.get("baselineCandidateRef") or parent.get("officialCandidateRef") or ""),
        "completionKind": "",
        "createdAt": utc_now(),
        "langGraph": {
            "engine": "challenge_cup_graph",
            "completedNodeIds": [],
            "startNodeId": "protocol_design",
            "inheritedFromParent": True,
            "artifacts": {
                "knowledge_package": artifacts.get("knowledge_package") or "",
                "evaluation_report": artifacts.get("evaluation_report") or "",
                # Intentionally omit frozen_protocol so child produces a new lineage
            },
        },
    }


def link_parent_after_fork(
    parent: dict[str, Any],
    *,
    child_run_id: str,
    decision_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    """Immutable parent history: succeeded + branched_revision + childRunIds."""
    children = list(parent.get("childRunIds") or [])
    if child_run_id not in children:
        children.append(child_run_id)
    return {
        "status": "succeeded",
        "completionKind": "branched_revision",
        "childRunIds": children,
        "runtimeCurrentNodeIds": [],
        "forkCheckpointId": checkpoint_id,
        "lastForkDecisionId": decision_id,
    }
