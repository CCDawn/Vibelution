"""Settle exact usage from a failed external Agent attempt before retry."""

from __future__ import annotations

from typing import Any

from .agent_task_budget_usage import collect_agent_task_budget_usage
from .budget_lifecycle import BudgetLifecycleError, settle_budget_records
from .external_agent_task_lookup import load_external_agent_task
from .node_execution_support import build_event, iso, utc_now
from .store import WorkflowRunStore


class FailedAgentBudgetError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _reservation_id(record: dict[str, Any], node_run: dict[str, Any]) -> str:
    explicit = str(node_run.get("budgetLedgerRef") or "").strip()
    if explicit:
        return explicit
    node_run_id = str(node_run.get("nodeRunId") or "")
    return next(
        (
            str(item.get("reservationId") or "")
            for item in record.get("budgetReservations") or []
            if item.get("nodeRunId") == node_run_id
        ),
        "",
    )


def settle_failed_agent_task_budget(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any]:
    """Persist consumed budget once; never release a real failed task for free."""
    reservation_id = _reservation_id(record, node_run)
    reservation = next(
        (
            item
            for item in record.get("budgetReservations") or []
            if item.get("reservationId") == reservation_id
        ),
        None,
    )
    if reservation is None or reservation.get("status") == "settled":
        return record
    task_id = str(node_run.get("taskId") or "").strip()
    session_id = str(node_run.get("sessionId") or "").strip()
    if not task_id or not session_id:
        return record
    try:
        task = load_external_agent_task(record, node_run)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FailedAgentBudgetError(
            str(exc),
            code="failed_agent_task_lookup_failed",
        ) from exc
    if task is None or str(task.get("taskId") or "") != task_id:
        raise FailedAgentBudgetError(
            "failed Agent task identity is unavailable",
            code="failed_agent_task_missing",
        )
    if str(task.get("sessionId") or "") != session_id:
        raise FailedAgentBudgetError(
            "failed Agent task session does not match the NodeRun",
            code="failed_agent_session_mismatch",
        )

    from core.web.services.session_service import get_session_detail

    try:
        session_detail = get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
        )
        actual = collect_agent_task_budget_usage(
            record,
            node_run,
            task,
            dict(session_detail),
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FailedAgentBudgetError(
            str(exc),
            code=str(getattr(exc, "code", "failed_agent_usage_invalid")),
        ) from exc
    settled_at = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_reservation = next(
            (
                item
                for item in current.get("budgetReservations") or []
                if item.get("reservationId") == reservation_id
            ),
            None,
        )
        if current_reservation is None or current_reservation.get("status") == "settled":
            return current
        try:
            ledgers, reservations = settle_budget_records(
                current,
                reservation_id=reservation_id,
                actual=actual,
                settled_at=settled_at,
            )
        except BudgetLifecycleError as exc:
            raise FailedAgentBudgetError(str(exc), code=exc.code) from exc
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=str(node_run.get("nodeId") or ""),
            nodeRunId=str(node_run.get("nodeRunId") or ""),
            attempt=int(node_run.get("attempt") or 1),
            type="BudgetSettled",
            summary={
                "reservationId": reservation_id,
                "actual": actual,
                "outcome": "failed",
            },
        )
        return {
            **current,
            "budgetLedgers": ledgers,
            "budgetReservations": reservations,
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(str(record["runId"]), mutation)
