"""Reserve and settle frozen per-stage research budgets."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.research.workflow.contracts import ResearchBudgetLedger
from core.research.workflow.models import WorkflowStageId

from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .store import WorkflowRunStore

_POLICY_LIMIT_KEYS = {
    "tokens": "tokens",
    "toolCalls": "toolCalls",
    "wallClockSeconds": "wallClockSeconds",
    "experiments": "experiments",
    "computeUnits": "computeUnits",
}


def remaining_budget_policy(
    record: dict[str, Any],
    *,
    stage_additions: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Freeze remaining parent capacity, optionally adding approved stage budget."""
    additions = stage_additions or {}
    stage_budgets: dict[str, dict[str, int]] = {}
    for ledger in record.get("budgetLedgers") or []:
        stage_id = str(ledger.get("stageId") or "")
        limits = dict(ledger.get("limits") or {})
        consumed = dict(ledger.get("consumed") or {})
        reserved = dict(ledger.get("reserved") or {})
        approved = dict(additions.get(stage_id) or {})
        stage_budgets[stage_id] = {
            key: max(
                0,
                int(limits.get(key) or 0)
                - int(consumed.get(key) or 0)
                - int(reserved.get(key) or 0),
            )
            + int(approved.get(key) or 0)
            for key in limits
        }
    original = dict((record.get("inputSnapshot") or {}).get("budgetPolicy") or {})
    return {**original, "stageBudgets": stage_budgets}


class BudgetLifecycleError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_initial_budget_ledgers(
    *,
    run_id: str,
    budget_policy: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    stage_budgets = budget_policy.get("stageBudgets")
    policy_hash = _canonical_hash(budget_policy)
    ledgers: list[dict[str, Any]] = []
    for stage in WorkflowStageId:
        raw_limits = (
            dict(stage_budgets.get(stage.value) or {})
            if isinstance(stage_budgets, dict)
            else budget_policy
        )
        limits = {
            ledger_key: int(raw_limits.get(policy_key) or 0)
            for policy_key, ledger_key in _POLICY_LIMIT_KEYS.items()
        }
        if not any(limits.values()):
            raise BudgetLifecycleError(
                f"budgetPolicy has no limits for stage {stage.value}",
                code="invalid_budget_policy",
            )
        ledger = ResearchBudgetLedger.from_dict(
            {
                "budgetLedgerId": f"budget-{run_id}-{stage.value}",
                "runId": run_id,
                "stageId": stage.value,
                "policySnapshotHash": policy_hash,
                "limits": limits,
                "reserved": {},
                "consumed": {},
                "stopReason": "",
                "updatedAt": created_at,
            }
        )
        ledgers.append(ledger.to_dict())
    return ledgers


def reserve_node_budget(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    stage_id: str,
    request: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    if not request:
        raise BudgetLifecycleError(
            "Agent task requires budgetRequest",
            code="budget_request_required",
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in request.values()
    ):
        raise BudgetLifecycleError(
            "budgetRequest values must be non-negative integers",
            code="invalid_budget_request",
        )
    reservation_id = f"reservation-{node_run['nodeRunId']}"
    existing = next(
        (
            dict(item)
            for item in record.get("budgetReservations") or []
            if item.get("reservationId") == reservation_id
        ),
        None,
    )
    if existing is not None:
        if (
            existing.get("idempotencyKey") == idempotency_key
            and existing.get("requested") == request
        ):
            return existing
        raise BudgetLifecycleError(
            "NodeRun budget reservation conflicts with prior request",
            code="budget_reservation_conflict",
        )
    ledger = next(
        (
            dict(item)
            for item in record.get("budgetLedgers") or []
            if item.get("stageId") == stage_id
        ),
        None,
    )
    if ledger is None:
        raise BudgetLifecycleError(
            f"budget ledger missing for stage {stage_id}",
            code="budget_ledger_missing",
        )
    unknown = set(request) - set(ledger.get("limits") or {})
    if unknown:
        raise BudgetLifecycleError(
            f"budgetRequest contains unknown counters: {', '.join(sorted(unknown))}",
            code="invalid_budget_request",
        )
    remaining = dict(ledger.get("remaining") or {})
    exceeded = [key for key, value in request.items() if value > int(remaining[key])]
    if exceeded:
        now = iso(utc_now())

        def block(current: dict[str, Any]) -> dict[str, Any]:
            ledgers = list(current.get("budgetLedgers") or [])
            blocked_ledger = next(
                dict(item) for item in ledgers if item.get("stageId") == stage_id
            )
            blocked_ledger.update(
                {"stopReason": "budget_exceeded", "updatedAt": now}
            )
            replace_by_id(
                ledgers,
                "budgetLedgerId",
                blocked_ledger["budgetLedgerId"],
                blocked_ledger,
            )
            event = build_event(
                current,
                workflowId=current["workflowId"],
                workflowVersionId=current["workflowVersionId"],
                checkpointId=(current.get("langGraph") or {}).get("checkpointId")
                or "",
                nodeId=node_run["nodeId"],
                nodeRunId=node_run["nodeRunId"],
                attempt=node_run["attempt"],
                type="BudgetExceeded",
                summary={"counters": exceeded},
            )
            return {
                **current,
                "status": "blocked",
                "blockedReason": "budget_exceeded",
                "budgetLedgers": ledgers,
                "events": [*(current.get("events") or []), event],
            }

        store.mutate_run(str(record["runId"]), block)
        raise BudgetLifecycleError(
            f"budget exceeded for {', '.join(exceeded)}",
            code="budget_exceeded",
        )

    now = iso(utc_now())
    reservation = {
        "reservationId": reservation_id,
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "stageId": stage_id,
        "budgetLedgerId": ledger["budgetLedgerId"],
        "requested": dict(request),
        "actual": {},
        "status": "reserved",
        "idempotencyKey": idempotency_key,
        "reservedAt": now,
        "settledAt": "",
    }

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        reservations = list(current.get("budgetReservations") or [])
        prior = next(
            (item for item in reservations if item.get("reservationId") == reservation_id),
            None,
        )
        if prior is not None:
            return current
        ledgers = list(current.get("budgetLedgers") or [])
        current_ledger = next(
            dict(item) for item in ledgers if item.get("stageId") == stage_id
        )
        reserved = dict(current_ledger.get("reserved") or {})
        for key, value in request.items():
            reserved[key] = int(reserved.get(key) or 0) + value
        current_ledger.update(
            {
                "reserved": reserved,
                "remaining": {
                    key: int(limit)
                    - int(reserved.get(key) or 0)
                    - int((current_ledger.get("consumed") or {}).get(key) or 0)
                    for key, limit in current_ledger["limits"].items()
                },
                "updatedAt": now,
            }
        )
        replace_by_id(
            ledgers,
            "budgetLedgerId",
            current_ledger["budgetLedgerId"],
            current_ledger,
        )
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_run["nodeId"],
            nodeRunId=node_run["nodeRunId"],
            attempt=node_run["attempt"],
            type="BudgetReserved",
            summary={"reservationId": reservation_id, "requested": request},
        )
        return {
            **current,
            "budgetLedgers": ledgers,
            "budgetReservations": [*reservations, reservation],
            "events": [*(current.get("events") or []), event],
        }

    persisted = store.mutate_run(str(record["runId"]), mutation)
    return next(
        item
        for item in persisted.get("budgetReservations") or []
        if item["reservationId"] == reservation_id
    )


def settle_budget_records(
    record: dict[str, Any],
    *,
    reservation_id: str,
    actual: dict[str, Any],
    settled_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reservations = list(record.get("budgetReservations") or [])
    reservation = next(
        (
            dict(item)
            for item in reservations
            if item.get("reservationId") == reservation_id
        ),
        None,
    )
    if reservation is None:
        return list(record.get("budgetLedgers") or []), reservations
    if reservation.get("status") == "settled":
        return list(record.get("budgetLedgers") or []), reservations
    requested = dict(reservation.get("requested") or {})
    if any(
        key not in requested
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > int(requested[key])
        for key, value in actual.items()
    ):
        raise BudgetLifecycleError(
            "budgetUsage must fit within the reserved counters",
            code="invalid_budget_settlement",
        )
    ledgers = list(record.get("budgetLedgers") or [])
    ledger = next(
        dict(item)
        for item in ledgers
        if item.get("budgetLedgerId") == reservation["budgetLedgerId"]
    )
    reserved = dict(ledger.get("reserved") or {})
    consumed = dict(ledger.get("consumed") or {})
    for key, value in requested.items():
        reserved[key] = max(0, int(reserved.get(key) or 0) - value)
    for key, value in actual.items():
        consumed[key] = int(consumed.get(key) or 0) + value
    ledger.update(
        {
            "reserved": reserved,
            "consumed": consumed,
            "remaining": {
                key: int(limit)
                - int(reserved.get(key) or 0)
                - int(consumed.get(key) or 0)
                for key, limit in ledger["limits"].items()
            },
            "updatedAt": settled_at,
        }
    )
    replace_by_id(ledgers, "budgetLedgerId", ledger["budgetLedgerId"], ledger)
    reservation.update(
        {"actual": dict(actual), "status": "settled", "settledAt": settled_at}
    )
    replace_by_id(
        reservations,
        "reservationId",
        reservation_id,
        reservation,
    )
    return ledgers, reservations
