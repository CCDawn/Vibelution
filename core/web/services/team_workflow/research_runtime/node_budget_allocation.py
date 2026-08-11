"""Deterministic per-Agent-node allocation from the frozen stage ledger."""

from __future__ import annotations

from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind


class NodeBudgetAllocationError(ValueError):
    """The runtime cannot publish a safe Agent start budget."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def build_agent_budget_request(
    record: dict[str, Any],
    node_id: str,
) -> dict[str, int]:
    """Reserve current stage capacity across concurrently ready Agent nodes.

    The backend owns this allocation because the frozen stage ledger and node
    completion facts are runtime state.  The frontend receives the resulting
    request through the command capability and must not invent a budget.

    A future node is not a competing reservation: each completed node settles
    its actual usage and releases the unused balance before its successor is
    scheduled.  Splitting against every unfinished node therefore makes a
    serial pipeline fail even when the stage still has enough total budget.
    """

    definition = build_challenge_cup_workflow_definition()
    node = next((item for item in definition.nodes if item.nodeId == node_id), None)
    if node is None or node.actorKind is not ActorKind.AGENT:
        raise NodeBudgetAllocationError(
            f"节点 {node_id} 不是可分配预算的 Agent 节点",
            code="agent_budget_node_invalid",
        )

    ledger = next(
        (
            item
            for item in record.get("budgetLedgers") or []
            if str(item.get("stageId") or "") == node.stageId.value
        ),
        None,
    )
    if not isinstance(ledger, dict):
        raise NodeBudgetAllocationError(
            "当前阶段预算台账缺失",
            code="budget_ledger_missing",
        )
    if str(ledger.get("stopReason") or "").strip():
        raise NodeBudgetAllocationError(
            "当前阶段预算已停止",
            code="budget_stage_stopped",
        )

    stage_agent_node_ids = {
        item.nodeId
        for item in definition.nodes
        if item.stageId == node.stageId and item.actorKind == ActorKind.AGENT
    }
    ready_agent_node_ids = {
        str(item.get("nodeId") or "")
        for item in record.get("nodeRuns") or []
        if str(item.get("status") or "") == "ready"
        and str(item.get("nodeId") or "") in stage_agent_node_ids
    }
    if node_id not in ready_agent_node_ids:
        raise NodeBudgetAllocationError(
            "当前 Agent 节点尚未就绪，不可申请预算",
            code="agent_node_not_ready",
        )

    remaining = ledger.get("remaining")
    if not isinstance(remaining, dict) or not remaining:
        raise NodeBudgetAllocationError(
            "当前阶段预算台账缺少 remaining",
            code="budget_remaining_missing",
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in remaining.values()
    ):
        raise NodeBudgetAllocationError(
            "当前阶段剩余预算无效",
            code="budget_remaining_invalid",
        )

    divisor = len(ready_agent_node_ids)
    request = {
        str(counter): int(value) // divisor
        for counter, value in remaining.items()
    }
    if not any(request.values()):
        raise NodeBudgetAllocationError(
            "当前阶段预算已耗尽",
            code="budget_exhausted",
        )
    return request
