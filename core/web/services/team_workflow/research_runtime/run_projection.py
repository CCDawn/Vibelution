"""Read-only canvas projection from canonical WorkflowRun records."""

from __future__ import annotations

from typing import Any

from core.research.workflow.iteration_decisions import DEFAULT_ITERATION_BUDGET
from core.research.workflow.models import WorkflowRunStatus
from core.research.workflow.projection import build_canvas_projection


def build_run_canvas_projection(record: dict[str, Any]) -> dict[str, Any]:
    try:
        status = WorkflowRunStatus(str(record.get("status") or ""))
    except ValueError:
        status = None
    latest: dict[str, dict[str, Any]] = {}
    for node_run in record.get("nodeRuns") or []:
        node_id = str(node_run.get("nodeId") or "")
        if not node_id:
            continue
        existing = latest.get(node_id)
        if existing is None or int(node_run.get("attempt") or 0) >= int(
            existing.get("attempt") or 0
        ):
            latest[node_id] = dict(node_run)
    pending = [
        task
        for task in record.get("humanTasks") or []
        if task.get("status") == "pending"
    ]
    return build_canvas_projection(
        run_id=str(record.get("runId") or ""),
        run_status=status,
        runtime_current_node_ids=list(record.get("runtimeCurrentNodeIds") or []),
        node_runs=latest,
        pending_human_tasks=pending,
        parent_run_id=str(record.get("parentRunId") or "") or None,
        child_run_ids=list(record.get("childRunIds") or []),
        completion_kind=str(record.get("completionKind") or "") or None,
        official_candidate_ref=str(record.get("officialCandidateRef") or "") or None,
        blocked_reason=str(record.get("blockedReason") or "") or None,
        iteration_budget_max=int(
            ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
                "experiments", DEFAULT_ITERATION_BUDGET
            )
        ),
    )
