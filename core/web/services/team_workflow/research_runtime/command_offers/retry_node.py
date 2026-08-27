"""retry_node CommandOffers from latest attempt state."""

from __future__ import annotations

import json
from collections.abc import Sequence

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition


_RETRYABLE_ATTEMPT_STATUSES = frozenset({"failed", "blocked", "cancelled"})

# Idempotent collection nodes may be re-run after a "succeeded" attempt whose
# artifacts never materialized (e.g. a restart killed the agent turn after the
# node had been marked succeeded, leaving the candidate store empty and the
# successor wedged on source_candidates_missing; or the relation mapper wrote
# dangling-endpoint edges that the merger fail-closed into missingLinks and the
# successor wedged on evidence_graph_incomplete).  Their stores are
# append-only and deduplicated, so a re-run is safe; every other node keeps
# the strict non-retryable contract for succeeded attempts.  This mapping is
# the single authority for "which upstream node heals this blocker detail";
# offers, the command handler and the current-task projection all read it.
_RERUN_BLOCKER_TARGET_NODES = {
    "source_candidates_missing": "source_finding",
    "evidence_graph_incomplete": "evidence_relations",
}


def succeeded_node_rerun_target(run: RunRecord) -> str | None:
    """Node that owns recovery when the run is blocked by a hollow success."""

    if str(run.status or "").strip() != "blocked":
        return None
    try:
        problem = json.loads(str(run.blocked_problem_json or "") or "{}")
    except (TypeError, ValueError):
        return None
    if str(problem.get("code") or "") != "auto_advance_not_ready":
        return None
    return _RERUN_BLOCKER_TARGET_NODES.get(str(problem.get("detail") or "")) or None


def succeeded_node_rerun_available(
    *,
    node_id: str,
    latest: NodeAttemptRecord | None,
    run: RunRecord,
) -> bool:
    """True when an idempotent collection node may re-run despite success.

    Requires the run to be blocked on the successor readiness gap that the
    missing artifacts cause, so a healthy succeeded node never offers a retry.
    """

    if succeeded_node_rerun_target(run) != str(node_id):
        return False
    return latest is not None and str(latest.status or "").strip() == "succeeded"


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
        latest = latest_by_node.get(node.nodeId)
        rerun_available = succeeded_node_rerun_available(
            node_id=node.nodeId, latest=latest, run=run
        )
        available = bool(
            latest and latest.status in _RETRYABLE_ATTEMPT_STATUSES
        ) or rerun_available
        if node.actorKind == ActorKind.HUMAN and not available:
            # A healthy human gate is operated through resolve_human_task.
            # Only surface retry when readiness previously blocked or the
            # attempt otherwise ended before a pending human task existed.
            continue
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id=node.nodeId,
                available=available,
                label=f"{'重跑' if rerun_available else '重试'} {node.label}",
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
