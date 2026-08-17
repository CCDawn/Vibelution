"""Pure Snapshot projection builder — no route/request, no writes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from core.research.workflow.contracts import CommandOffer, ResearchWorkflowSnapshot
from core.research.workflow.contracts.workflow_snapshot import (
    AgentBindingRef,
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

from .blocked_reason import format_blocked_reason, parse_problem_json


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

    active_ids = _active_node_ids(run, inputs.attempts)
    canonical_active_node_id = active_ids[0] if active_ids else None
    run_summary = _run_summary_with_active_block(
        run,
        inputs.attempts,
        active_node_id=canonical_active_node_id,
    )
    if run_summary.active_node_id != canonical_active_node_id:
        run_summary = replace(
            run_summary,
            active_node_id=canonical_active_node_id,
        )

    binding_refs = tuple(
        sorted(
            {
                attempt.binding_snapshot_id
                for attempt in inputs.attempts
                if attempt.binding_snapshot_id
            }
        )
    )
    frozen_bindings = frozen_agent_bindings(run.input_snapshot_json)
    binding_ids = tuple(
        dict.fromkeys(
            [
                *binding_refs,
                *(item.snapshot_id for item in frozen_bindings if item.snapshot_id),
            ]
        )
    )

    safety_limits = _loads(run.safety_limits_json)
    return ResearchWorkflowSnapshot(
        run=run_summary,
        definition=inputs.definition.to_dict(),
        node_attempts={
            node_id: tuple(items) for node_id, items in node_attempts.items()
        },
        active_node_ids=active_ids,
        pending_human_tasks=tuple(
            _coerce_human_task(item) for item in inputs.pending_human_tasks
        ),
        command_offers=inputs.command_offers,
        handoff_summary=_handoff_summary(inputs.handoffs),
        agent_binding_summary=AgentBindingSummary(
            binding_snapshot_set_id=run.binding_snapshot_set_id,
            binding_snapshot_ids=binding_ids,
            count=len(binding_ids),
            bindings=frozen_bindings,
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


_LIVE_ATTEMPT_STATUS = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)


def _active_node_ids(
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
) -> tuple[str, ...]:
    """Project one canonical active-node set from durable attempt state.

    A successor can become live before the run row's convenience pointer is
    updated.  Live attempts are the stronger fact; the pointer is used only
    while no live attempt exists (for example, a newly created or failed run).
    """
    live_ids = tuple(
        dict.fromkeys(
            attempt.node_id
            for attempt in attempts
            if attempt.status in _LIVE_ATTEMPT_STATUS
        )
    )
    if live_ids:
        active = str(run.active_node_id or "").strip()
        if active in live_ids:
            return (active, *(node_id for node_id in live_ids if node_id != active))
        return live_ids
    active = str(run.active_node_id or "").strip()
    return (active,) if active else ()


_TERMINAL_RUN_STATUS = frozenset(
    {"succeeded", "failed", "cancelled", "archived"}
)


def _run_summary_with_active_block(
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
    *,
    active_node_id: str | None = None,
) -> WorkflowRunSummary:
    """Surface active-node blocks even when ledger run.status is still running."""
    summary = _run_summary(run)
    if run.status in _TERMINAL_RUN_STATUS:
        return summary
    active = str(active_node_id or run.active_node_id or "")
    if not active:
        return summary
    latest: NodeAttemptRecord | None = None
    for attempt in attempts:
        if attempt.node_id != active:
            continue
        if latest is None or int(attempt.attempt) >= int(latest.attempt):
            latest = attempt
    if latest is None or latest.status != "blocked":
        return summary
    reason = format_blocked_reason(
        parse_problem_json(latest.problem_json),
        fallback=summary.blocked_reason,
    ) or summary.blocked_reason
    return replace(summary, status="blocked", blocked_reason=reason)


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
        blocked_reason=format_blocked_reason(
            parse_problem_json(run.blocked_problem_json),
            fallback=run.terminal_reason,
        )
        or None,
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
        problem=parse_problem_json(attempt.problem_json),
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
                from_node_id=_as_optional_str(item.get("fromNodeId")),
                from_node_run_id=_as_optional_str(item.get("fromNodeRunId")),
                status=status,
                input_snapshot_hash=_as_optional_str(item.get("inputSnapshotHash")),
                output_artifact_refs=tuple(
                    ref
                    for ref in (item.get("outputArtifactRefs") or ())
                    if isinstance(ref, Mapping)
                ),
                offered_at_ms=_as_optional_int(item.get("offeredAtMs")),
                accepted_at_ms=_as_optional_int(item.get("acceptedAtMs")),
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


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def frozen_agent_bindings(input_snapshot_json: str | None) -> tuple[AgentBindingRef, ...]:
    payload = _loads(input_snapshot_json or "")
    if not isinstance(payload, dict):
        return ()
    refs: list[AgentBindingRef] = []
    seen: set[str] = set()
    for item in payload.get("agentBindingSnapshot") or []:
        if not isinstance(item, Mapping):
            continue
        node_id = str(item.get("nodeId") or "").strip()
        agent_id = str(item.get("agentId") or "").strip()
        if not node_id or not agent_id or node_id in seen:
            continue
        seen.add(node_id)
        resolved = str(item.get("resolvedFrom") or "").strip() or "workflow_default"
        refs.append(
            AgentBindingRef(
                node_id=node_id,
                agent_id=agent_id,
                role_key=str(item.get("roleKey") or "").strip(),
                resolved_from=resolved,
                snapshot_id=str(item.get("snapshotId") or "").strip(),
            )
        )
    return tuple(refs)


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
