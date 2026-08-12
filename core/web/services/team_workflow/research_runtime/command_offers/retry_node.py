"""retry_node CommandOffers from latest attempt state."""

from __future__ import annotations

from collections.abc import Sequence

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition


def build_retry_node_offers(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
    attempts: Sequence[NodeAttemptRecord],
) -> list[CommandOffer]:
    latest_by_node: dict[str, NodeAttemptRecord] = {}
    for attempt in attempts:
        current = latest_by_node.get(attempt.node_id)
        if current is None or attempt.attempt >= current.attempt:
            latest_by_node[attempt.node_id] = attempt

    offers: list[CommandOffer] = []
    for node in definition.nodes:
        if node.actorKind == ActorKind.HUMAN:
            continue
        latest = latest_by_node.get(node.nodeId)
        available = bool(latest and latest.status in {"failed", "blocked"})
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id=node.nodeId,
                available=available,
                label=f"重试 {node.label}",
                reason_code="retry_available" if available else "retry_not_available",
                blocker_ids=() if available else ("retry_not_available",),
                idempotency_key=(
                    f"offer:{run.run_id}:{node.nodeId}:retry_node:"
                    f"a{(latest.attempt + 1) if latest else 1}:v{run.run_version}"
                ),
                expected_run_version=run.run_version,
                payload={"retryKind": "same_node"},
            )
        )
    return offers
