"""Ledger-authority recompute for reconcile_run (recovery closeout).

A run can sit on ``reconciliation_required`` while its ledger already says
something different: an operator-misassigned attempt (e.g. retrying
``source_finding`` after the chain authoritative progress moved past it)
terminal-fails with ``checkpoint_node_mismatch`` and pins the run's
``active_node_id`` to that stale node. Reconciling then keeps re-deriving
dispatch decisions from the polluted projection, hitting the same thread
interrupt forever — the run-d02722658d8b death loop.

This module is the pure decision core that repairs the projection FROM the
ledger, never the other way around:

- blocked attempts whose problem was written by the auto-advance readiness
  evaluator (``auto_advance_not_ready``) are real forward-edge blockers;
  the deepest one beyond every success supplies the run's landing verdict;
- incident blocked attempts (any other problem code) are superseded when a
  succeeded attempt covers equal-or-deeper ground than the blocked attempt's
  own position: the same chain already advanced past it, so this attempt can
  never become the advancing edge again. Such attempts flip to ``stale``
  (the same status the retry flow uses for superseded attempts) and their
  failed dispatch rows stop being revived. An uncovered incident block never
  authors the landing verdict by itself: some of those problems (e.g.
  ``frozen_protocol_missing``) describe gaps the reconcile command itself
  repairs, so their recovery stays owned by the pre-existing
  backfill/resume/heal contracts.

Thread rebuild is intentionally deferred: with no revived dispatch pointing at
a covered node left behind, the existing worker heal paths (lag-walk,
identity-addressed resume, restart_attempt) drive the LangGraph thread back
onto the ledger authority at the next legitimate rerun/resume, instead of
reconcile performing risky checkpoint surgery.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Problem code written by the readiness pipeline (graph_dispatch_worker
# _commit_successor_dispatch) when auto-advance is gated by domain facts.
EVALUATOR_BLOCK_CODE = "auto_advance_not_ready"


@dataclass(frozen=True)
class LedgerAuthorityPlan:
    """What reconcile should do to restore ledger-authoritative projection.

    ``superseded_node_run_ids`` — dirty blocked attempts to mark ``stale``.
    ``active_node_id`` / ``landing_problem`` — present only when the ledger
    holds a surviving blocker deeper than every success; ``landing_problem``
    is the evaluator-authored dict copied verbatim from that attempt.
    """

    superseded_node_run_ids: tuple[str, ...] = ()
    active_node_id: str | None = None
    landing_node_id: str | None = None
    landing_problem: Mapping[str, Any] | None = None

    @property
    def lands_blocked(self) -> bool:
        return self.active_node_id is not None and self.landing_problem is not None


def _problem_code(problem_json: str | None) -> str:
    if not problem_json:
        return ""
    try:
        loaded = json.loads(problem_json)
    except (TypeError, ValueError):
        return ""
    if isinstance(loaded, Mapping):
        return str(loaded.get("code") or "")
    return ""


def _attempt_order_key(attempt: Any) -> int:
    return (
        attempt.finished_at_ms
        if getattr(attempt, "finished_at_ms", None)
        else attempt.updated_at_ms
    )


def _covered_by_success(attempt: Any, succeeded: Sequence[Any], depth_of) -> bool:
    """Ledger test for “superseded by an earlier successful advance”.

    A succeeded attempt strictly deeper in the canonical chain, or one that
    finished at the same position before this attempt started, proves the
    chain authoritative progress had already covered this attempt's ground.
    """
    own_depth = depth_of(attempt.node_id)
    started_at = int(getattr(attempt, "started_at_ms", 0) or 0)
    for other in succeeded:
        if other.node_run_id == attempt.node_run_id:
            continue
        other_depth = depth_of(other.node_id)
        if other_depth > own_depth:
            return True
        if other_depth == own_depth and _attempt_order_key(other) <= started_at:
            return True
    return False


def plan_ledger_authority(
    attempts: Iterable[Any],
    *,
    node_order: Sequence[str],
) -> LedgerAuthorityPlan:
    """Decide which blocked attempts reconcile must retire and where the run lands.

    Fail-safe for foreign ledgers: any unknown node id disables the whole
    plan (no supersessions, no landing) so legacy/non-formal ledgers keep the
    plain revive-and-heal behavior.
    """
    records = [attempt for attempt in attempts]
    if not records or any(node not in set(node_order) for node in
                          {str(record.node_id) for record in records}):
        return LedgerAuthorityPlan()
    depth_of = {node: index for index, node in enumerate(node_order)}
    depth = lambda node_id: depth_of[str(node_id)]

    succeeded = [record for record in records if record.status == "succeeded"]
    blocked = [record for record in records if record.status == "blocked"]

    # Evaluator-authored blockers are the pipeline's own truth: always kept.
    kept_blocked = [
        record
        for record in blocked
        if _problem_code(record.problem_json) == EVALUATOR_BLOCK_CODE
    ]
    dirty = [
        record
        for record in blocked
        if _problem_code(record.problem_json) != EVALUATOR_BLOCK_CODE
        and _covered_by_success(record, succeeded, depth)
    ]
    dirty_ids = {record.node_run_id for record in dirty}

    frontier_success_depth = max(
        (depth(record.node_id) for record in succeeded), default=-1
    )
    # Only the readiness pipeline's own verdict may author the landing.
    leading = [
        record
        for record in blocked
        if _problem_code(record.problem_json) == EVALUATOR_BLOCK_CODE
        and depth(record.node_id) > frontier_success_depth
    ]
    if not leading:
        # No evaluator verdict owns the frontier: a terminal-failed attempt
        # beyond every success is the run's real state (its only recovery is
        # the ordinary retry offer). Landing blocked there keeps
        # reconciliation_required for genuinely inconsistent dispatch tables
        # instead of wedging a retryable frontier behind a reconcile loop
        # (retry is refused with run_reconciliation_required while reconcile
        # keeps re-deriving "no active work" forever).
        failed_leading = [
            record
            for record in records
            if record.status == "failed"
            and depth(record.node_id) > frontier_success_depth
        ]
        if failed_leading:
            failed_keeper = sorted(
                failed_leading,
                key=lambda record: (
                    -depth(record.node_id),
                    int(getattr(record, "started_at_ms", 0) or 0),
                    str(record.node_run_id),
                ),
            )[0]
            failed_problem: Mapping[str, Any] = {}
            try:
                loaded = json.loads(str(failed_keeper.problem_json or "") or "{}")
            except (TypeError, ValueError):
                loaded = {}
            if isinstance(loaded, Mapping) and loaded:
                failed_problem = loaded
            else:
                failed_problem = {
                    "code": "node_failed_awaiting_retry",
                    "detail": str(failed_keeper.node_id),
                }
            return LedgerAuthorityPlan(
                superseded_node_run_ids=tuple(sorted(dirty_ids)),
                active_node_id=str(failed_keeper.node_id),
                landing_node_id=str(failed_keeper.node_id),
                landing_problem=dict(failed_problem),
            )
        return LedgerAuthorityPlan(superseded_node_run_ids=tuple(sorted(dirty_ids)))

    # Deepest evaluator blocker wins; ties prefer the earliest evidence.
    keeper = sorted(
        leading,
        key=lambda record: (
            -depth(record.node_id),
            int(getattr(record, "started_at_ms", 0) or 0),
            str(record.node_run_id),
        ),
    )[0]
    try:
        problem = json.loads(str(keeper.problem_json or "") or "{}")
    except (TypeError, ValueError):
        problem = {}
    if not isinstance(problem, Mapping) or not problem:
        return LedgerAuthorityPlan(superseded_node_run_ids=tuple(sorted(dirty_ids)))
    return LedgerAuthorityPlan(
        superseded_node_run_ids=tuple(sorted(dirty_ids)),
        active_node_id=str(keeper.node_id),
        landing_node_id=str(keeper.node_id),
        landing_problem=dict(problem),
    )
