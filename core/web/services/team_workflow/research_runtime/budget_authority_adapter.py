"""Ledger-backed budget authority adapter (T5.1-5).

Reuses the frozen Run budgetPolicy and budget_receipts table as the single
budget fact source for the formal Workflow Ledger runtime. Does not create a
second budget store.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import WorkflowLedgerStore

from .ids import new_id

DEFAULT_STAGE_TOKENS = 250_000
DEFAULT_TOOL_CALLS = 300
DEFAULT_WALL_CLOCK_SECONDS = 21_600
DEFAULT_AUTO_RETRIES = 2

_STAGE_BY_NODE: dict[str, str] = {
    "source_finding": "knowledge_collection",
    "source_extraction": "knowledge_collection",
    "evidence_relations": "knowledge_collection",
    "knowledge_ingestion": "knowledge_collection",
    "knowledge_handoff": "knowledge_collection",
    "hypothesis_design": "experiment_design",
    "protocol_design": "experiment_design",
    "protocol_review": "experiment_design",
    "protocol_freeze": "experiment_design",
    "smoke_gate": "experiment_design",
    "controlled_run": "execution_iteration",
    "result_evaluation": "execution_iteration",
    "iteration_decision": "execution_iteration",
    "version_governance": "execution_iteration",
    "candidate_promotion": "execution_iteration",
    "result_package": "execution_iteration",
}


class BudgetAuthorityError(RuntimeError):
    def __init__(self, message: str, *, code: str = "budget_error") -> None:
        super().__init__(message)
        self.code = code


def stage_for_node(node_id: str) -> str:
    return _STAGE_BY_NODE.get(node_id, "execution_iteration")


def _policy_limits(snapshot: dict[str, Any], stage_id: str) -> dict[str, int]:
    policy = snapshot.get("budgetPolicy") or {}
    stage_budgets = policy.get("stageBudgets") or {}
    stage = stage_budgets.get(stage_id) if isinstance(stage_budgets, dict) else {}
    if not isinstance(stage, dict):
        stage = {}
    tokens = int(stage.get("tokens") or policy.get("tokens") or DEFAULT_STAGE_TOKENS)
    tool_calls = int(
        stage.get("toolCalls") or policy.get("toolCalls") or DEFAULT_TOOL_CALLS
    )
    seconds = int(
        stage.get("wallClockSeconds")
        or policy.get("wallClockSeconds")
        or DEFAULT_WALL_CLOCK_SECONDS
    )
    retries = int(policy.get("autoRetries") or DEFAULT_AUTO_RETRIES)
    return {
        "tokens": tokens,
        "toolCalls": tool_calls,
        "seconds": seconds,
        "retries": retries,
    }


def _consumed_tokens(store: WorkflowLedgerStore, run_id: str, stage_id: str) -> int:
    rows = store.submit(
        lambda uow: uow.repository.execute(
            "SELECT reserved_json, status, stage_id FROM budget_receipts WHERE run_id = ?",
            (run_id,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    total = 0
    for reserved_json, status, row_stage in rows:
        if str(row_stage or "") and str(row_stage) != stage_id:
            continue
        if str(status or "") not in {"reserved", "settled", "consumed"}:
            continue
        try:
            reserved = json.loads(reserved_json or "{}")
        except (TypeError, ValueError):
            reserved = {}
        inner = (
            reserved.get("reserved")
            if isinstance(reserved.get("reserved"), dict)
            else reserved
        )
        if not isinstance(inner, dict):
            inner = {}
        total += int(inner.get("estimatedTokens") or inner.get("tokens") or 0)
    return total


def reserve_budget_authority(
    store: WorkflowLedgerStore,
    *,
    action: PendingAction,
    estimate_tokens: int,
    input_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(input_snapshot or {})
    stage_id = stage_for_node(action.node_id)
    limits = _policy_limits(snapshot, stage_id)
    reservation_id = f"reservation-{action.node_run_id}"
    estimate = max(0, int(estimate_tokens))

    # Idempotent: existing reserved/settled receipt for this reservation wins.
    existing = store.submit(
        lambda uow: uow.repository.execute(
            "SELECT receipt_id, status, reserved_json FROM budget_receipts "
            "WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone(),
        force_flush=True,
    ).result(timeout=10)
    if existing is not None:
        try:
            reserved = json.loads(existing[2] or "{}")
        except (TypeError, ValueError):
            reserved = {}
        return {
            "reservationId": reservation_id,
            "receiptId": str(existing[0]),
            "actionId": action.action_id,
            "nodeRunId": action.node_run_id,
            "stageId": stage_id,
            "policyHash": action.budget_policy_hash or "",
            "reserved": dict(reserved.get("reserved") or reserved or {}),
            "status": str(existing[1] or "reserved"),
            "limits": limits,
        }

    consumed = _consumed_tokens(store, action.run_id, stage_id)
    if consumed + estimate > limits["tokens"]:
        raise BudgetAuthorityError(
            f"stage token limit exceeded for {stage_id}: "
            f"consumed={consumed} estimate={estimate} limit={limits['tokens']}",
            code="budget_safety_limit_reached",
        )

    now_ms = int(time.time() * 1000)
    receipt_id = new_id("br")
    reserved_payload = {
        "estimatedTokens": estimate,
        "tokens": estimate,
        "toolCalls": 1,
        "seconds": 60,
        "retries": 0,
    }

    def mutate(uow):
        uow.repository.insert_budget_receipt(
            receipt_id=receipt_id,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=reservation_id,
            stage_id=stage_id,
            policy_hash=action.budget_policy_hash or "",
            reserved_json=json.dumps(
                {"reserved": reserved_payload, "limits": limits},
                ensure_ascii=False,
            ),
            created_at_ms=now_ms,
        )

    store.submit(mutate, force_flush=True).result(timeout=30)

    return {
        "reservationId": reservation_id,
        "receiptId": receipt_id,
        "actionId": action.action_id,
        "nodeRunId": action.node_run_id,
        "stageId": stage_id,
        "policyHash": action.budget_policy_hash or "",
        "reserved": reserved_payload,
        "status": "reserved",
        "limits": limits,
    }


def settle_budget_authority(
    store: WorkflowLedgerStore,
    *,
    reservation: dict[str, Any],
    usage: dict[str, Any],
) -> None:
    reservation_id = str(reservation.get("reservationId") or "").strip()
    if not reservation_id:
        raise BudgetAuthorityError(
            "settle requires reservationId", code="budget_settle_missing"
        )
    now_ms = int(time.time() * 1000)
    settled_json = json.dumps(
        {"usage": usage, "source": "budget-authority-adapter"},
        ensure_ascii=False,
    )

    def mutate(uow):
        row = uow.repository.execute(
            "SELECT receipt_id, status FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise BudgetAuthorityError(
                f"budget receipt missing for {reservation_id}",
                code="budget_settle_missing",
            )
        if str(row[1] or "") == "settled":
            return
        uow.repository.update_budget_receipt(
            str(row[0]),
            status="settled",
            now_ms=now_ms,
            settled_json=settled_json,
        )

    store.submit(mutate, force_flush=True).result(timeout=30)


def release_budget_reservation(
    store: WorkflowLedgerStore,
    reservation: dict[str, Any],
) -> None:
    reservation_id = str(reservation.get("reservationId") or "").strip()
    if not reservation_id:
        return
    now_ms = int(time.time() * 1000)

    def mutate(uow):
        row = uow.repository.execute(
            "SELECT receipt_id, status FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            return
        if str(row[1] or "") in {"settled", "released", "failed"}:
            return
        uow.repository.update_budget_receipt(
            str(row[0]),
            status="released",
            now_ms=now_ms,
            settled_json=json.dumps(
                {"reason": "unused_release", "source": "budget-authority-adapter"},
                ensure_ascii=False,
            ),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
