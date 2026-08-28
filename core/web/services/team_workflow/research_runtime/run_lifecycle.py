"""Pure builders for a frozen WorkflowRun and its first ready NodeRun."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import WorkflowRunInputSnapshot
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import RunAgentBindingSnapshot, WorkflowDefinition

from .budget_lifecycle import build_initial_budget_ledgers


def create_request_fingerprint(request: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(request),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def run_id_for_create(workflow_id: str, idempotency_key: str) -> str:
    if not idempotency_key:
        return f"run-{uuid.uuid4().hex[:12]}"
    identity = f"{workflow_id}:{idempotency_key}".encode()
    return f"run-{hashlib.sha256(identity).hexdigest()[:12]}"


def binding_snapshot_payload(snapshot: RunAgentBindingSnapshot) -> dict[str, Any]:
    return {
        "snapshotId": snapshot.snapshotId,
        "nodeId": snapshot.nodeId,
        "agentId": snapshot.agentId,
        "roleKey": snapshot.roleKey,
        "actorKind": snapshot.actorKind.value,
        "resolvedFrom": snapshot.resolvedFrom,
        "capturedAt": snapshot.capturedAt,
    }


def freeze_run_input(
    request: Mapping[str, Any],
    *,
    workflow_version_id: str,
    binding_snapshots: list[dict[str, Any]],
    created_at: str,
) -> WorkflowRunInputSnapshot:
    from config.settings import get_config

    configured_mode = str(
        get_config().workflow_session_scope_v3.hypothesis_design
    ).strip().lower()
    payload = {
        **dict(request),
        # Effective server-owned mode; request input cannot override it and
        # replay always reads the frozen run snapshot.
        "workflowSessionScopeV3": {
            "hypothesis_design": configured_mode,
        },
        "workflowVersionId": workflow_version_id,
        "agentBindingSnapshot": binding_snapshots,
        "createdAt": created_at,
    }
    return WorkflowRunInputSnapshot.from_dict(payload)


def build_initial_node_run(
    *,
    run_id: str,
    input_snapshot: WorkflowRunInputSnapshot,
    checkpoint_id: str,
    binding_snapshots: list[dict[str, Any]],
    definition: WorkflowDefinition | None = None,
) -> dict[str, Any]:
    pinned = definition or build_challenge_cup_workflow_definition()
    first_node = pinned.nodes[0]
    binding = next(
        (item for item in binding_snapshots if item["nodeId"] == first_node.nodeId),
        None,
    )
    return {
        "nodeRunId": f"nr-{run_id}-{first_node.nodeId}-a1",
        "runId": run_id,
        "nodeId": first_node.nodeId,
        "attempt": 1,
        "actorType": first_node.actorKind.value,
        "agentId": str((binding or {}).get("agentId") or ""),
        "taskId": "",
        "sessionId": "",
        "status": "ready",
        "inputSnapshotHash": input_snapshot.snapshotHash,
        "idempotencyKey": f"{run_id}:{first_node.nodeId}:1",
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


def build_initial_run_record(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    structure_hash: str,
    thread_id: str,
    checkpoint_id: str,
    input_snapshot: WorkflowRunInputSnapshot,
    binding_snapshots: list[dict[str, Any]],
    idempotency_key: str,
    create_input_fingerprint: str,
    created_at: str,
    definition: WorkflowDefinition | None = None,
) -> dict[str, Any]:
    first_node_run = build_initial_node_run(
        run_id=run_id,
        input_snapshot=input_snapshot,
        checkpoint_id=checkpoint_id,
        binding_snapshots=binding_snapshots,
        definition=definition,
    )
    budget_ledgers = build_initial_budget_ledgers(
        run_id=run_id,
        budget_policy=input_snapshot.budgetPolicy,
        created_at=created_at,
    )
    return {
        "runId": run_id,
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version_id,
        "structureHash": structure_hash,
        "teamId": input_snapshot.teamId,
        "projectId": input_snapshot.projectId,
        "questionId": input_snapshot.questionId,
        "threadId": thread_id,
        "status": "queued",
        "inputSnapshot": input_snapshot.to_dict(),
        "bindingSnapshots": binding_snapshots,
        "runtimeCurrentNodeIds": [first_node_run["nodeId"]],
        "completedNodeIds": [],
        "nodeRuns": [first_node_run],
        "artifactManifests": [],
        "events": [
            {
                "eventId": f"evt-{uuid.uuid4().hex[:10]}",
                "sequence": 1,
                "occurredAt": created_at,
                "workflowId": workflow_id,
                "workflowVersionId": workflow_version_id,
                "runId": run_id,
                "threadId": thread_id,
                "checkpointId": checkpoint_id,
                "nodeId": first_node_run["nodeId"],
                "nodeRunId": first_node_run["nodeRunId"],
                "attempt": 1,
                "type": "run.queued",
                "summary": {"inputSnapshotHash": input_snapshot.snapshotHash},
            }
        ],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "taskLeases": [],
        "commandReceipts": [],
        "outbox": [],
        "budgetLedgers": budget_ledgers,
        "budgetReservations": [],
        "iterationBudgetMax": min(
            3,
            max(1, int(input_snapshot.budgetPolicy.get("experiments") or 1)),
        ),
        "officialCandidateRef": "",
        "baselineCandidateRef": "",
        "childRunIds": [],
        "completionKind": "",
        "terminalReason": "",
        "createIdempotencyKey": idempotency_key,
        "createInputFingerprint": create_input_fingerprint,
        "langGraph": {
            "engine": "challenge_cup_graph",
            "checkpointId": checkpoint_id,
            "completedNodeIds": [],
        },
    }
