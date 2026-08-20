"""start_node CommandOffers from NodeReadiness."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition

from ..readiness import NodeReadinessService
from ..readiness.common import DomainReadinessContext

_START_HELD = frozenset(
    {
        "starting",
        "dispatching",
        "running",
        "waiting_human",
        "blocked",
        "failed",
        "succeeded",
    }
)
_RETRY_OWNED = frozenset({"blocked", "failed"})
_IN_FLIGHT = frozenset({"starting", "dispatching", "running", "waiting_human"})


def build_start_node_offers(
    *,
    readiness_service: NodeReadinessService,
    context: DomainReadinessContext,
    team_id: str,
    run: RunRecord,
    definition: WorkflowDefinition,
    attempts: Sequence[NodeAttemptRecord] = (),
    evaluated_at_ms: int | None = None,
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
        held_reason = ""
        if latest is not None and latest.status in _START_HELD:
            if latest.status in _RETRY_OWNED:
                held_reason = "retry_owns_recovery"
            elif latest.status in _IN_FLIGHT:
                held_reason = "node_in_flight"
            else:
                held_reason = "node_already_succeeded"
        readiness = readiness_service.evaluate(
            team_id=team_id,
            run_id=run.run_id,
            node_id=node.nodeId,
            context=context,
            use_cache=True,
            evaluated_at_ms=evaluated_at_ms,
        )
        payload: dict[str, Any] = {}
        if held_reason:
            available = False
            blocker_ids = (held_reason,)
            reason_code = held_reason
        else:
            blocker_ids = tuple(blocker.code for blocker in readiness.blockers)
            reason_code = blocker_ids[0] if blocker_ids else (
                "ready" if readiness.ready else "not_ready"
            )
            available = bool(readiness.ready)
            # Carry the blocker's own wording to the UI: the offer is the only
            # channel the node inspector has, and a bare reason code forces the
            # frontend to guess a remediation that may not match the sub-case.
            if not available and readiness.blockers:
                first = readiness.blockers[0]
                payload = {
                    "blocker_title": str(first.title or ""),
                    "blocker_detail": str(first.detail or ""),
                }
                if first.remediation is not None and first.remediation.label:
                    payload["remediation_label"] = str(first.remediation.label)
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.START_NODE,
                node_id=node.nodeId,
                available=available,
                label=f"启动 {node.label}",
                reason_code=reason_code,
                blocker_ids=blocker_ids,
                idempotency_key=(
                    f"offer:{run.run_id}:{node.nodeId}:start_node:v{run.run_version}"
                ),
                expected_run_version=run.run_version,
                payload=payload,
            )
        )
    return offers
