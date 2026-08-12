"""Pure Snapshot projection builder — no route/request, no writes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.research.workflow.contracts import CommandOffer, ResearchWorkflowSnapshot
from core.research.workflow.contracts.workflow_snapshot import (
    AgentBindingSummary,
    BudgetReceiptRef,
    BudgetSummary,
    HandoffRefSummary,
    HandoffSummary,
    HumanTaskSummary,
    NodeAttemptSummary,
    WorkflowRunSummary,
)
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    run: RunRecord
    definition: WorkflowDefinition
    attempts: tuple[NodeAttemptRecord, ...]
    pending_human_tasks: tuple[HumanTaskSummary | Mapping[str, Any], ...]
    handoffs: tuple[Mapping[str, Any], ...]
    budget_receipts: tuple[Mapping[str, Any], ...]
    command_offers: tuple[CommandOffer, ...]
    latest_event_sequence: int
    generated_at: str


def build_research_workflow_snapshot(inputs: ProjectionInputs) -> ResearchWorkflowSnapshot:
    run = inputs.run
    node_attempts: dict[str, list[NodeAttemptSummary]] = {}
    for attempt in inputs.attempts:
        node_attempts.setdefault(attempt.node_id, []).append(_attempt_summary(attempt))

    active_ids: list[str] = []
    if run.active_node_id:
        active_ids.append(run.active_node_id)
    for attempt in inputs.attempts:
        if attempt.status in {"starting", "dispatching", "running", "waiting_human"}:
            if attempt.node_id not in active_ids:
                active_ids.append(attempt.node_id)

    binding_refs = tuple(
        sorted(
            {
                attempt.binding_snapshot_id
                for attempt in inputs.attempts
                if attempt.binding_snapshot_id
            }
        )
    )

    safety_limits = _loads(run.safety_limits_json)
    return ResearchWorkflowSnapshot(
        run=_run_summary(run),
        definition=inputs.definition.to_dict(),
        node_attempts={
            node_id: tuple(items) for node_id, items in node_attempts.items()
        },
        active_node_ids=tuple(active_ids),
        pending_human_tasks=tuple(
            _coerce_human_task(item) for item in inputs.pending_human_tasks
        ),
        command_offers=inputs.command_offers,
        handoff_summary=_handoff_summary(inputs.handoffs),
        agent_binding_summary=AgentBindingSummary(
            binding_snapshot_set_id=run.binding_snapshot_set_id,
            binding_snapshot_ids=binding_refs,
            count=len(binding_refs),
        ),
        budget_summary=BudgetSummary(
            safety_limits=safety_limits,
            receipt_refs=tuple(
                BudgetReceiptRef(
                    receipt_id=_as_optional_str(item.get("receiptId")),
                    node_run_id=_as_optional_str(item.get("nodeRunId")),
                    status=_as_optional_str(item.get("status")),
                    policy_hash=_as_optional_str(item.get("policyHash")),
                )
                for item in inputs.budget_receipts
            ),
            receipt_count=len(inputs.budget_receipts),
        ),
        latest_event_sequence=int(inputs.latest_event_sequence),
        generated_at=inputs.generated_at,
    )


def _run_summary(run: RunRecord) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        run_id=run.run_id,
        team_id=run.team_id,
        workflow_id=run.workflow_id,
        workflow_version_id=run.workflow_version_id,
        thread_id=run.thread_id,
        project_id=run.project_id,
        question_id=run.question_id,
        status=run.status,
        run_version=run.run_version,
        input_snapshot_hash=run.input_snapshot_hash,
        binding_snapshot_set_id=run.binding_snapshot_set_id,
        active_node_id=run.active_node_id,
        parent_run_id=run.parent_run_id,
        forked_from_checkpoint_id=run.forked_from_checkpoint_id,
        completion_kind=run.completion_kind,
        terminal_reason=run.terminal_reason,
        created_at_ms=run.created_at_ms,
        updated_at_ms=run.updated_at_ms,
        completed_at_ms=run.completed_at_ms,
    )


def _attempt_summary(attempt: NodeAttemptRecord) -> NodeAttemptSummary:
    return NodeAttemptSummary(
        node_run_id=attempt.node_run_id,
        node_id=attempt.node_id,
        attempt=attempt.attempt,
        actor_kind=attempt.actor_kind,
        status=attempt.status,
        command_id=attempt.command_id,
        binding_snapshot_id=attempt.binding_snapshot_id,
        input_snapshot_hash=attempt.input_snapshot_hash,
        execution_anchor_id=attempt.execution_anchor_id,
        started_at_ms=attempt.started_at_ms,
        updated_at_ms=attempt.updated_at_ms,
        finished_at_ms=attempt.finished_at_ms,
    )


def _coerce_human_task(item: HumanTaskSummary | Mapping[str, Any]) -> HumanTaskSummary:
    if isinstance(item, HumanTaskSummary):
        return item
    return HumanTaskSummary(
        task_id=str(item.get("taskId") or ""),
        run_id=str(item.get("runId") or ""),
        node_run_id=str(item.get("nodeRunId") or ""),
        node_id=_as_optional_str(item.get("nodeId")),
        handoff_id=_as_optional_str(item.get("handoffId")),
        task_kind=str(item.get("taskKind") or ""),
        status=str(item.get("status") or ""),
        created_at_ms=int(item.get("createdAtMs") or 0),
        resolved_at_ms=(
            None
            if item.get("resolvedAtMs") is None
            else int(item.get("resolvedAtMs") or 0)
        ),
    )


def _handoff_summary(handoffs: Sequence[Mapping[str, Any]]) -> HandoffSummary:
    by_status: dict[str, int] = {}
    refs: list[HandoffRefSummary] = []
    for item in handoffs:
        status = str(item.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        refs.append(
            HandoffRefSummary(
                handoff_id=_as_optional_str(item.get("handoffId")),
                to_node_id=_as_optional_str(item.get("toNodeId")),
                status=status,
                input_snapshot_hash=_as_optional_str(item.get("inputSnapshotHash")),
            )
        )
    return HandoffSummary(
        counts_by_status=by_status,
        refs=tuple(refs),
        count=len(refs),
    )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
