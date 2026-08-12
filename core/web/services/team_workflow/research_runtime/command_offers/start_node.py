"""start_node CommandOffers from NodeReadiness."""

from __future__ import annotations

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition

from ..readiness import NodeReadinessService
from ..readiness.common import DomainReadinessContext


def build_start_node_offers(
    *,
    readiness_service: NodeReadinessService,
    context: DomainReadinessContext,
    team_id: str,
    run: RunRecord,
    definition: WorkflowDefinition,
    evaluated_at_ms: int | None = None,
) -> list[CommandOffer]:
    offers: list[CommandOffer] = []
    for node in definition.nodes:
        if node.actorKind == ActorKind.HUMAN:
            continue
        readiness = readiness_service.evaluate(
            team_id=team_id,
            run_id=run.run_id,
            node_id=node.nodeId,
            context=context,
            use_cache=True,
            evaluated_at_ms=evaluated_at_ms,
        )
        blocker_ids = tuple(blocker.code for blocker in readiness.blockers)
        reason_code = blocker_ids[0] if blocker_ids else (
            "ready" if readiness.ready else "not_ready"
        )
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.START_NODE,
                node_id=node.nodeId,
                available=bool(readiness.ready),
                label=f"启动 {node.label}",
                reason_code=reason_code,
                blocker_ids=blocker_ids,
                idempotency_key=(
                    f"offer:{run.run_id}:{node.nodeId}:start_node:v{run.run_version}"
                ),
                expected_run_version=run.run_version,
                payload={},
            )
        )
    return offers
