"""Persist a truthful terminal state when an Agent exceeds frozen budget."""

from __future__ import annotations

from typing import Any

from .node_execution_support import (
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .store import WorkflowRunStore


def budget_overrun(reservation: dict[str, Any] | None) -> dict[str, int]:
    """Return validated positive observed-over-reserved counters."""
    raw = (reservation or {}).get("overrun")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }


def budget_overrun_summary(reservation: dict[str, Any] | None) -> str:
    """Give operators an actionable explanation without exposing settlement internals."""
    request = dict((reservation or {}).get("requested") or {})
    actual = dict((reservation or {}).get("actual") or {})
    counters = budget_overrun(reservation)
    details = ", ".join(
        f"{key} {int(actual.get(key) or 0)}/{int(request.get(key) or 0)}"
        for key in sorted(counters)
    )
    return f"Agent 任务已超过本阶段冻结预算（{details}）。请提高预算后创建新运行。"


def budget_overrun_context(reservation: dict[str, Any]) -> dict[str, Any]:
    """Keep observed, charged, and overrun counters together for audit and UI detail."""
    return {
        "kind": "budget_overrun",
        "reservationId": str(reservation.get("reservationId") or ""),
        "requested": dict(reservation.get("requested") or {}),
        "actual": dict(reservation.get("actual") or {}),
        "charged": dict(reservation.get("charged") or {}),
        "allocationOverrun": dict(reservation.get("allocationOverrun") or {}),
        "overrun": budget_overrun(reservation),
    }


def block_completed_node_for_budget_overrun(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_id: str,
    reservation_id: str,
    budget_ledgers: list[dict[str, Any]],
    budget_reservations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Settle the reserved ceiling and block instead of claiming a successful handoff."""
    settled_reservation = next(
        (
            dict(item)
            for item in budget_reservations
            if item.get("reservationId") == reservation_id
        ),
        None,
    )
    if not budget_overrun(settled_reservation):
        return record
    now = iso(utc_now())
    failure_summary = budget_overrun_summary(settled_reservation)
    failure_context = budget_overrun_context(settled_reservation)

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_node_run = dict(latest_node_run(current, node_id))
        if current_node_run.get("status") != "running":
            return current
        current_node_run.update(
            {
                "status": "blocked",
                "finishedAt": now,
                "failureCode": "budget_exceeded",
                "failureSummary": failure_summary,
                "failureContext": failure_context,
            }
        )
        node_runs = [dict(item) for item in current.get("nodeRuns") or []]
        replace_by_id(node_runs, "nodeRunId", current_node_run["nodeRunId"], current_node_run)
        leases = [dict(item) for item in current.get("taskLeases") or []]
        for lease in leases:
            if lease.get("nodeRunId") == current_node_run["nodeRunId"] and lease.get("status") == "running":
                lease["status"] = "failed"
        bundles = [dict(item) for item in current.get("taskBundles") or []]
        for bundle in bundles:
            if bundle.get("parentNodeRunId") != current_node_run["nodeRunId"]:
                continue
            bundle.update(
                {
                    "status": "failed",
                    "failureCode": "budget_exceeded",
                    "failureSummary": failure_summary,
                    "subtasks": [
                        {**item, "status": "failed"}
                        if item.get("status") in {"pending", "running"}
                        else item
                        for item in bundle.get("subtasks") or []
                    ],
                }
            )
        settled_event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_id,
            nodeRunId=current_node_run["nodeRunId"],
            attempt=current_node_run["attempt"],
            type="BudgetSettled",
            summary={
                "reservationId": reservation_id,
                "actual": failure_context["actual"],
                "charged": failure_context["charged"],
                "outcome": "budget_exceeded",
            },
        )
        overrun_event = build_event(
            {**current, "events": [*(current.get("events") or []), settled_event]},
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_id,
            nodeRunId=current_node_run["nodeRunId"],
            attempt=current_node_run["attempt"],
            type="BudgetOverrun",
            summary=failure_context,
        )
        transition_event = build_event(
            {
                **current,
                "events": [*(current.get("events") or []), settled_event, overrun_event],
            },
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_id,
            nodeRunId=current_node_run["nodeRunId"],
            attempt=current_node_run["attempt"],
            type="NodeRunTransitioned",
            summary={"from": "running", "to": "blocked", "reason": "budget_exceeded"},
        )
        return {
            **current,
            "status": "blocked",
            "blockedReason": "budget_exceeded",
            "runtimeCurrentNodeIds": [node_id],
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "taskBundles": bundles,
            "budgetLedgers": budget_ledgers,
            "budgetReservations": budget_reservations,
            "events": [
                *(current.get("events") or []),
                settled_event,
                overrun_event,
                transition_event,
            ],
        }

    return store.mutate_run(str(record["runId"]), mutation)
