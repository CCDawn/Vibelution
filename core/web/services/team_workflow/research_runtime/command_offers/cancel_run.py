"""cancel_run CommandOffer — availability from transitions authority only."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.transitions import RunStatus, can_transition_run


def build_cancel_run_offer(*, run: RunRecord) -> CommandOffer:
    try:
        current = RunStatus(run.status)
    except ValueError:
        current = None
    available = bool(
        current is not None
        and current != RunStatus.CANCELLED
        and can_transition_run(current, RunStatus.CANCELLED)
    )
    return CommandOffer(
        command=WorkflowCommandKind.CANCEL_RUN,
        node_id=None,
        available=available,
        label="取消运行",
        reason_code="cancel_available" if available else "cancel_not_allowed",
        blocker_ids=() if available else ("cancel_not_allowed",),
        idempotency_key=f"offer:{run.run_id}:cancel_run:v{run.run_version}",
        expected_run_version=run.run_version,
        payload={"reason": "operator cancelled"},
        destructive=True,
    )
