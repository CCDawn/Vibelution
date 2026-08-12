"""rebind_node CommandOffers (formal, default unavailable without binding target)."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition


def build_rebind_node_offers(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
) -> list[CommandOffer]:
    offers: list[CommandOffer] = []
    for node in definition.nodes:
        if node.actorKind != ActorKind.AGENT:
            continue
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.REBIND_NODE,
                node_id=node.nodeId,
                available=False,
                label=f"重绑 {node.label}",
                reason_code="rebind_target_required",
                blocker_ids=("rebind_target_required",),
                idempotency_key=(
                    f"offer:{run.run_id}:{node.nodeId}:rebind_node:v{run.run_version}"
                ),
                expected_run_version=run.run_version,
                payload={},
            )
        )
    return offers
