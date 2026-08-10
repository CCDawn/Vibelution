"""Reconcile canonical external Agent task terminal state into WorkflowRun state."""

from __future__ import annotations

from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind

from .agent_node_execution import SOURCE_NODE_TASKS
from .agent_task_artifact_builder import build_agent_task_artifacts
from .agent_task_budget_usage import collect_agent_task_budget_usage, parse_task_time
from .external_agent_task_failure import (
    block_external_agent_node_run,
    is_recoverable_external_reconciliation_failure,
    reopen_external_agent_reconciliation_failure,
)
from .external_agent_task_lookup import load_external_agent_task
from .failed_agent_budget import (
    FailedAgentBudgetError,
    settle_failed_agent_task_budget,
)
from .node_completion import complete_node_execution
from .node_execution_support import NodeExecutionError, iso, utc_now
from .store import WorkflowRunStore

_ACTIVE_TASK_STATUSES = frozenset({"accepted", "queued", "running", "starting"})
_BLOCKED_TASK_STATUSES = frozenset({"blocked", "incomplete"})
_FAILED_TASK_STATUSES = frozenset(
    {"cancelled", "canceled", "failed", "interrupted", "stopped"}
)


def _evidence_failure_context(task: dict[str, Any]) -> dict[str, Any]:
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    closure = (
        result.get("closureSummary")
        if isinstance(result.get("closureSummary"), dict)
        else {}
    )
    coverage = (
        writeback.get("coverageSummary")
        if isinstance(writeback.get("coverageSummary"), dict)
        else closure.get("coverageSummary")
        if isinstance(closure.get("coverageSummary"), dict)
        else {}
    )
    candidate_ids = sorted(
        {
            str(item).strip()
            for item in list(coverage.get("blockedCandidateIds") or [])
            if str(item).strip()
        }
    )
    if not candidate_ids:
        return {}
    return {
        "kind": "evidence_quality_gap",
        "sourceTaskId": str(task.get("taskId") or ""),
        "evidenceGapCandidateIds": candidate_ids,
    }


def _settle_then_block(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    failure_code: str,
    failure_summary: str,
    failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist consumed Agent usage before making its terminal failure visible."""
    try:
        settled = settle_failed_agent_task_budget(
            store,
            record=record,
            node_run=node_run,
        )
    except FailedAgentBudgetError as exc:
        return block_external_agent_node_run(
            store,
            record=record,
            node_run=node_run,
            failure_code=exc.code,
            failure_summary=(
                f"{failure_code}: {failure_summary} "
                f"Budget settlement failed: {exc}"
            ),
            failure_context=failure_context,
        )
    return block_external_agent_node_run(
        store,
        record=settled,
        node_run=node_run,
        failure_code=failure_code,
        failure_summary=failure_summary,
        failure_context=failure_context,
    )


def _reconcile_one(
    store: WorkflowRunStore,
    *,
    checkpoint_path: str,
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any]:
    lease = next(
        (
            item
            for item in reversed(record.get("taskLeases") or [])
            if item.get("nodeRunId") == node_run.get("nodeRunId")
            and item.get("status") == "running"
        ),
        None,
    )
    expires_at = parse_task_time((lease or {}).get("leaseExpiresAt"))
    lease_is_live = expires_at is not None and utc_now() <= expires_at
    try:
        task = load_external_agent_task(record, node_run)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        if lease_is_live:
            return record
        return block_external_agent_node_run(
            store,
            record=record,
            node_run=node_run,
            failure_code="external_agent_task_lookup_failed",
            failure_summary=str(exc),
        )
    if task is None:
        if lease_is_live:
            return record
        return block_external_agent_node_run(
            store,
            record=record,
            node_run=node_run,
            failure_code="external_agent_task_missing",
            failure_summary="The exact persisted Agent task no longer exists.",
        )
    if str(task.get("taskId") or "") != str(node_run.get("taskId") or ""):
        return block_external_agent_node_run(
            store,
            record=record,
            node_run=node_run,
            failure_code="external_agent_task_mismatch",
            failure_summary="The Agent task identity does not match the NodeRun.",
        )
    status = str(task.get("status") or "").strip().lower()
    if status in _ACTIVE_TASK_STATUSES:
        return record
    source_completion_gate = (
        task.get("completionGate")
        if node_run.get("nodeId") in SOURCE_NODE_TASKS
        else None
    )
    review_artifact_ready = (
        status == "needs_review"
        and isinstance(source_completion_gate, dict)
        and bool(source_completion_gate.get("passed"))
    )
    if status in _BLOCKED_TASK_STATUSES | _FAILED_TASK_STATUSES or (
        status == "needs_review" and not review_artifact_ready
    ):
        return _settle_then_block(
            store,
            record=record,
            node_run=node_run,
            failure_code=str(task.get("failureCode") or f"external_task_{status}"),
            failure_summary=str(
                task.get("failureSummary")
                or task.get("summary")
                or f"External Agent task reached {status}."
            ),
            failure_context=_evidence_failure_context(task),
        )
    if status != "completed" and not review_artifact_ready:
        return record

    if node_run.get("nodeId") in SOURCE_NODE_TASKS and (
        not isinstance(source_completion_gate, dict)
        or not source_completion_gate.get("passed")
    ):
        return _settle_then_block(
            store,
            record=record,
            node_run=node_run,
            failure_code="external_task_completion_gate_failed",
            failure_summary="Source Agent task completed without passing its artifact gate.",
        )
    session_id = str(node_run.get("sessionId") or "")
    if not session_id or session_id != str(task.get("sessionId") or ""):
        return block_external_agent_node_run(
            store,
            record=record,
            node_run=node_run,
            failure_code="external_agent_session_mismatch",
            failure_summary="The terminal task is not anchored to the NodeRun session.",
        )
    from core.web.services.session_service import get_session_detail

    try:
        session_detail = get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
        )
        node_spec = next(
            item
            for item in build_challenge_cup_workflow_definition().nodes
            if item.nodeId == node_run["nodeId"]
        )
        manifests, payloads = build_agent_task_artifacts(
            record=record,
            node_spec=node_spec,
            node_run=node_run,
            task=task,
            created_at=str(task.get("updatedAt") or iso(utc_now())),
        )
        lease = next(
            item
            for item in reversed(record.get("taskLeases") or [])
            if item.get("nodeRunId") == node_run["nodeRunId"]
            and item.get("status") == "running"
        )
        return complete_node_execution(
            store,
            checkpoint_path=checkpoint_path,
            run_id=str(record["runId"]),
            node_id=str(node_run["nodeId"]),
            payload={
                "idempotencyKey": (
                    f"external-agent-complete:{node_run['nodeRunId']}:{task['taskId']}"
                ),
                "leaseOwner": str(lease["leaseOwner"]),
                "artifactManifests": [item.to_dict() for item in manifests],
                "artifactPayloads": payloads,
                "budgetUsage": collect_agent_task_budget_usage(
                    record,
                    node_run,
                    task,
                    dict(session_detail),
                ),
            },
        )
    except (KeyError, StopIteration, TypeError, ValueError, NodeExecutionError) as exc:
        return _settle_then_block(
            store,
            record=record,
            node_run=node_run,
            failure_code=str(getattr(exc, "code", "external_task_completion_invalid")),
            failure_summary=str(exc),
        )


def reconcile_external_agent_tasks(
    store: WorkflowRunStore,
    *,
    checkpoint_path: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Apply terminal external task state exactly once for reconcilable Agent nodes."""
    current = record
    definition = build_challenge_cup_workflow_definition()
    actor_by_node = {item.nodeId: item.actorKind for item in definition.nodes}
    candidates = [
        dict(item)
        for item in current.get("nodeRuns") or []
        if (
            item.get("status") == "running"
            or is_recoverable_external_reconciliation_failure(dict(item))
        )
        and item.get("taskId")
        and actor_by_node.get(str(item.get("nodeId") or "")) is ActorKind.AGENT
    ]
    for node_run in candidates:
        if is_recoverable_external_reconciliation_failure(node_run):
            try:
                task = load_external_agent_task(current, node_run)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                continue
            if task is None or str(task.get("status") or "").lower() != "completed":
                continue
            current = reopen_external_agent_reconciliation_failure(
                store,
                record=current,
                node_run=node_run,
            )
            node_run = next(
                (
                    dict(item)
                    for item in current.get("nodeRuns") or []
                    if item.get("nodeRunId") == node_run.get("nodeRunId")
                ),
                node_run,
            )
            if node_run.get("status") != "running":
                continue
        current = _reconcile_one(
            store,
            checkpoint_path=checkpoint_path,
            record=current,
            node_run=node_run,
        )
    return current


def has_reconcilable_external_agent_tasks(record: dict[str, Any]) -> bool:
    return any(
        item.get("taskId")
        and (
            item.get("status") == "running"
            or is_recoverable_external_reconciliation_failure(dict(item))
        )
        for item in record.get("nodeRuns") or []
    )
