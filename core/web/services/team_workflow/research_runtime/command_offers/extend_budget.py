"""extend_budget CommandOffers — only when a concrete limit delta is known."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.transitions import RunStatus, is_terminal_run


def build_extend_budget_offers(*, run: RunRecord) -> list[CommandOffer]:
    try:
        terminal = is_terminal_run(RunStatus(run.status))
    except ValueError:
        terminal = True
    # Empty limits are not an executable operator action. Keep the Offer visible
    # but unavailable until a concrete extension payload is projected.
    available = False
    if terminal:
        reason_code = "run_terminal"
        blocker_ids = ("run_terminal",)
    else:
        reason_code = "budget_extension_required"
        blocker_ids = ("budget_extension_required",)
    return [
        CommandOffer(
            command=WorkflowCommandKind.EXTEND_BUDGET,
            node_id=None,
            available=available,
            label="扩展预算",
            reason_code=reason_code,
            blocker_ids=blocker_ids,
            idempotency_key=f"offer:{run.run_id}:extend_budget:v{run.run_version}",
            expected_run_version=run.run_version,
            payload={"limits": {}},
        )
    ]
