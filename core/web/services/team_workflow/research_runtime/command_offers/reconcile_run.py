"""reconcile_run CommandOffer."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord


def build_reconcile_run_offer(*, run: RunRecord) -> CommandOffer:
    available = run.status in {"blocked", "reconciliation_required"}
    return CommandOffer(
        command=WorkflowCommandKind.RECONCILE_RUN,
        node_id=None,
        available=available,
        label="对账运行",
        reason_code="ready" if available else "reconcile_not_needed",
        blocker_ids=() if available else ("reconcile_not_needed",),
        idempotency_key=f"offer:{run.run_id}:reconcile_run:v{run.run_version}",
        expected_run_version=run.run_version,
        payload={},
    )
