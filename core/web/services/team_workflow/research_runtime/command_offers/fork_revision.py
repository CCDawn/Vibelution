"""fork_revision CommandOffers."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.models import WorkflowDefinition


def build_fork_revision_offers(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
) -> list[CommandOffer]:
    checkpoint_id = str(run.forked_from_checkpoint_id or "").strip()
    # Prefer explicit active node; otherwise first definition node as fromNodeId.
    from_node_id = str(run.active_node_id or "").strip()
    if not from_node_id and definition.nodes:
        from_node_id = definition.nodes[0].nodeId
    available = bool(checkpoint_id and from_node_id)
    return [
        CommandOffer(
            command=WorkflowCommandKind.FORK_REVISION,
            node_id=from_node_id or None,
            available=available,
            label="分叉修订",
            reason_code="ready" if available else "fork_checkpoint_unavailable",
            blocker_ids=() if available else ("fork_checkpoint_unavailable",),
            idempotency_key=f"offer:{run.run_id}:fork_revision:v{run.run_version}",
            expected_run_version=run.run_version,
            payload={
                "fromNodeId": from_node_id,
                "reason": "operator fork",
                "checkpointId": checkpoint_id,
            },
            destructive=True,
        )
    ]
