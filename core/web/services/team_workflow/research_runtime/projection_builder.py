"""Pure Snapshot projection builder — no route/request, no writes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.research.workflow.contracts import CommandOffer, ResearchWorkflowSnapshot
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    run: RunRecord
    definition: WorkflowDefinition
    attempts: tuple[NodeAttemptRecord, ...]
    pending_human_tasks: tuple[Mapping[str, Any], ...]
    handoffs: tuple[Mapping[str, Any], ...]
    budget_receipts: tuple[Mapping[str, Any], ...]
    command_offers: tuple[CommandOffer, ...]
    latest_event_sequence: int
    generated_at: str


def build_research_workflow_snapshot(inputs: ProjectionInputs) -> ResearchWorkflowSnapshot:
    run = inputs.run
    node_attempts: dict[str, list[dict[str, Any]]] = {}
    for attempt in inputs.attempts:
        node_attempts.setdefault(attempt.node_id, []).append(_attempt_summary(attempt))

    active_ids: list[str] = []
    if run.active_node_id:
        active_ids.append(run.active_node_id)
    for attempt in inputs.attempts:
        if attempt.status in {"starting", "dispatching", "running", "waiting_human"}:
            if attempt.node_id not in active_ids:
                active_ids.append(attempt.node_id)

    binding_refs = sorted(
        {
            attempt.binding_snapshot_id
            for attempt in inputs.attempts
            if attempt.binding_snapshot_id
        }
    )

    safety_limits = _loads(run.safety_limits_json)
    return ResearchWorkflowSnapshot(
        run=_run_summary(run),
        definition=inputs.definition.to_dict(),
        node_attempts={
            node_id: tuple(items) for node_id, items in node_attempts.items()
        },
        active_node_ids=tuple(active_ids),
        pending_human_tasks=tuple(dict(item) for item in inputs.pending_human_tasks),
        command_offers=inputs.command_offers,
        handoff_summary=_handoff_summary(inputs.handoffs),
        agent_binding_summary={
            "bindingSnapshotSetId": run.binding_snapshot_set_id,
            "bindingSnapshotIds": binding_refs,
            "count": len(binding_refs),
        },
        budget_summary={
            "safetyLimits": safety_limits,
            "receiptRefs": [
                {
                    "receiptId": item.get("receiptId"),
                    "nodeRunId": item.get("nodeRunId"),
                    "status": item.get("status"),
                    "policyHash": item.get("policyHash"),
                }
                for item in inputs.budget_receipts
            ],
            "receiptCount": len(inputs.budget_receipts),
        },
        latest_event_sequence=int(inputs.latest_event_sequence),
        generated_at=inputs.generated_at,
    )


def _run_summary(run: RunRecord) -> dict[str, Any]:
    return {
        "runId": run.run_id,
        "teamId": run.team_id,
        "workflowId": run.workflow_id,
        "workflowVersionId": run.workflow_version_id,
        "threadId": run.thread_id,
        "projectId": run.project_id,
        "questionId": run.question_id,
        "status": run.status,
        "runVersion": run.run_version,
        "inputSnapshotHash": run.input_snapshot_hash,
        "bindingSnapshotSetId": run.binding_snapshot_set_id,
        "activeNodeId": run.active_node_id,
        "parentRunId": run.parent_run_id,
        "forkedFromCheckpointId": run.forked_from_checkpoint_id,
        "completionKind": run.completion_kind,
        "terminalReason": run.terminal_reason,
        "createdAtMs": run.created_at_ms,
        "updatedAtMs": run.updated_at_ms,
        "completedAtMs": run.completed_at_ms,
    }


def _attempt_summary(attempt: NodeAttemptRecord) -> dict[str, Any]:
    return {
        "nodeRunId": attempt.node_run_id,
        "nodeId": attempt.node_id,
        "attempt": attempt.attempt,
        "actorKind": attempt.actor_kind,
        "status": attempt.status,
        "commandId": attempt.command_id,
        "bindingSnapshotId": attempt.binding_snapshot_id,
        "inputSnapshotHash": attempt.input_snapshot_hash,
        "executionAnchorId": attempt.execution_anchor_id,
        "startedAtMs": attempt.started_at_ms,
        "updatedAtMs": attempt.updated_at_ms,
        "finishedAtMs": attempt.finished_at_ms,
    }


def _handoff_summary(handoffs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    refs: list[dict[str, Any]] = []
    for item in handoffs:
        status = str(item.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        refs.append(
            {
                "handoffId": item.get("handoffId"),
                "toNodeId": item.get("toNodeId"),
                "status": status,
                "inputSnapshotHash": item.get("inputSnapshotHash"),
            }
        )
    return {"countsByStatus": by_status, "refs": refs, "count": len(refs)}


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
