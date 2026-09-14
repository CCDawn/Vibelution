"""fork_revision CommandOffers."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.models import WorkflowDefinition, WorkflowStageId


def build_fork_revision_offers(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
    revise_checkpoint_id: str | None = None,
) -> list[CommandOffer]:
    # Root runs never carry forked_from_checkpoint_id; the caller resolves
    # the thread's latest durable checkpoint so fork stays available.
    checkpoint_id = str(
        run.forked_from_checkpoint_id or revise_checkpoint_id or ""
    ).strip()
    # The command service only accepts a source in knowledge collection or
    # experiment design.  Never advertise a first graph node from another
    # stage as executable; operator iteration has its own decision-driven
    # next-round path.
    eligible_stages = {
        WorkflowStageId.KNOWLEDGE_COLLECTION,
        WorkflowStageId.EXPERIMENT_DESIGN,
    }
    nodes_by_id = {node.nodeId: node for node in definition.nodes}
    active_node_id = str(run.active_node_id or "").strip()
    active_node = nodes_by_id.get(active_node_id)
    from_node_id = (
        active_node_id
        if active_node is not None and active_node.stageId in eligible_stages
        else next(
            (
                node.nodeId
                for node in definition.nodes
                if node.stageId in eligible_stages
            ),
            "",
        )
    )
    available = bool(checkpoint_id and from_node_id)
    reason_code = (
        "ready"
        if available
        else "fork_checkpoint_unavailable"
        if not checkpoint_id
        else "fork_source_unavailable"
    )
    blocker_ids = () if available else (reason_code,)
    return [
        CommandOffer(
            command=WorkflowCommandKind.FORK_REVISION,
            node_id=from_node_id or None,
            available=available,
            label="分叉修订",
            reason_code=reason_code,
            blocker_ids=blocker_ids,
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
