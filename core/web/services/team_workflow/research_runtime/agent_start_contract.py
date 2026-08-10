"""Durable command contract for starting one workflow Agent NodeRun."""

from __future__ import annotations

from typing import Any

from .node_budget_allocation import (
    NodeBudgetAllocationError,
    build_agent_budget_request,
)
from .node_execution_support import NodeExecutionError, latest_node_run


class AgentStartContractError(ValueError):
    """The runtime cannot publish a safe Agent start command."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def build_agent_start_contract(
    record: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    """Return the immutable command key and exact budget for a ready NodeRun.

    A partial start may already have reserved budget and created a task bundle
    before the external Agent task fails.  Retrying must replay those durable
    values instead of deriving a new request from the mutated run version or
    remaining ledger.
    """

    try:
        node_run = latest_node_run(record, node_id)
    except NodeExecutionError as exc:
        raise AgentStartContractError(str(exc), code=exc.code) from exc
    if str(node_run.get("status") or "") != "ready":
        raise AgentStartContractError(
            f"Agent node must be ready, got {node_run.get('status')}",
            code="invalid_node_state",
        )

    node_run_id = str(node_run.get("nodeRunId") or "").strip()
    reservation_id = f"reservation-{node_run_id}"
    reservation = next(
        (
            item
            for item in record.get("budgetReservations") or []
            if str(item.get("reservationId") or "") == reservation_id
        ),
        None,
    )
    if reservation is not None:
        idempotency_key = str(reservation.get("idempotencyKey") or "").strip()
        requested = reservation.get("requested")
        if not idempotency_key:
            raise AgentStartContractError(
                "已存在的 Agent 预算预留缺少 idempotencyKey",
                code="budget_reservation_contract_invalid",
            )
        if not isinstance(requested, dict) or not requested:
            raise AgentStartContractError(
                "已存在的 Agent 预算预留缺少 requested",
                code="budget_reservation_contract_invalid",
            )
        bundle = next(
            (
                item
                for item in record.get("taskBundles") or []
                if str(item.get("parentNodeRunId") or "") == node_run_id
            ),
            None,
        )
        if bundle is not None and str(bundle.get("idempotencyKey") or "") != idempotency_key:
            raise AgentStartContractError(
                "Agent 预算预留与 TaskBundle 的 idempotencyKey 不一致",
                code="agent_start_contract_conflict",
            )
        return {
            "idempotencyKey": idempotency_key,
            "payload": {"budgetRequest": dict(requested)},
        }

    try:
        requested = build_agent_budget_request(record, node_id)
    except NodeBudgetAllocationError as exc:
        raise AgentStartContractError(str(exc), code=exc.code) from exc
    return {
        "idempotencyKey": f"agent-task:{node_run_id}",
        "payload": {"budgetRequest": requested},
    }
