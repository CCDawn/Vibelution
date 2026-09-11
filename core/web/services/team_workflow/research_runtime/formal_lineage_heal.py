"""Formal lineage auto-heal: archive stale CANCELLED leaves (maintenance).

A question whose formal runs carry more than one leaf (no child run, not
archived) projects the ``formal_run_lineage_conflict`` problem with
actionability=blocked and the whole program projection suppressed, and the
only manual escape is an 「归档分支」 click the frontend often never
surfaces.  The stale side of the conflict is almost always a CANCELLED leaf
left behind by a superseded attempt, so the resident maintenance sweep
archives exactly those through the same command SSOT the operator button
uses — never SUCCEEDED/FAILED/RECONCILIATION_REQUIRED leaves, which may
need operator review.
"""

from __future__ import annotations

import time
from typing import Any

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID

STALE_LEAF_ARCHIVE_ACTOR_ID = "system:formal-lineage-heal"
STALE_LEAF_ARCHIVE_REASON = "auto-heal formal run lineage conflict"
DEFAULT_STALE_LEAF_ARCHIVE_SWEEP_LIMIT = 3


def _record_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Best-effort observability event; diagnostics never break the sweep."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "formal_lineage_heal",
        event_code,
        level=level,
        outcome=outcome,
        fields=fields or {},
    )


def sweep_archive_stale_formal_leaves(
    *, limit: int = DEFAULT_STALE_LEAF_ARCHIVE_SWEEP_LIMIT
) -> dict[str, Any]:
    """Maintenance sweep: archive stale CANCELLED formal-run leaves.

    For every team with a hypothesis-first chain ledger, groups the question's
    formal runs exactly like the v2 projection computes leaves (runs excluding
    ``archived`` with no child run among them).  When more than one leaf
    exists, the newest leaf (by ``updatedAt``/``createdAt``, then runId) is
    the current revision and every OTHER leaf whose ledger status is
    CANCELLED gets an ARCHIVE_RUN submitted under a server-bound system
    operator scope with one deterministic idempotency key per run — the same
    command channel and submit shape as the question-reset cancel path, so a
    replayed command converges instead of duplicating.  Non-cancelled stale
    leaves are left untouched for operator review.  Bounded per pass
    (``limit``, default 3, attempts included) and never raises: one broken
    team/question/submit is isolated, counted, and reported as a scene event.
    """
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )

    from .hypothesis_first_chain import _team_ids_with_chain_storage
    from .ids import new_id
    from .operator_authorization import server_operator_scope
    from .runtime_factory import production_workflow_runtime

    summary: dict[str, Any] = {
        "teams": 0,
        "conflicts": 0,
        "archived": 0,
        "skipped": 0,
        "failed": 0,
    }
    runtime = production_workflow_runtime()
    if runtime is None:
        return summary
    try:
        team_ids = _team_ids_with_chain_storage()
    except Exception:  # noqa: BLE001 - enumeration must never break the sweep
        _record_scene_event(
            "hypothesis_first.stale_leaf_auto_archive",
            outcome="failed",
            level="warning",
            fields={"reason": "team_enumeration_failed"},
        )
        return summary
    remaining = max(0, int(limit))
    for team_id in team_ids:
        summary["teams"] += 1
        try:
            runs = runtime.store.list_runs_for_team(
                team_id, CHALLENGE_CUP_WORKFLOW_ID
            )
        except Exception:  # noqa: BLE001 - isolate one unreadable team
            summary["failed"] += 1
            continue
        by_question: dict[str, list[Any]] = {}
        for run in runs:
            if str(run.team_id or "") != team_id:
                continue
            question_id = str(run.question_id or "").strip().upper()
            if question_id:
                by_question.setdefault(question_id, []).append(run)
        for question_id in sorted(by_question):
            live = [
                run
                for run in by_question[question_id]
                if str(run.status or "").strip().lower() != "archived"
            ]
            if len(live) < 2:
                continue
            children_by_parent: dict[str, list[str]] = {}
            for run in live:
                parent_id = str(run.parent_run_id or "").strip()
                if parent_id:
                    children_by_parent.setdefault(parent_id, []).append(
                        str(run.run_id or "")
                    )
            live_ids = {str(run.run_id or "") for run in live}
            leaves = [
                run
                for run in live
                if not [
                    child
                    for child in children_by_parent.get(str(run.run_id or ""), [])
                    if child in live_ids
                ]
            ]
            if len(leaves) < 2:
                continue
            summary["conflicts"] += 1
            # Same ordering as the v2 projection: updatedAt (createdAt
            # fallback), then runId; the newest leaf is the current revision.
            def _leaf_order(run: Any) -> tuple[int, str]:
                updated_ms = int(getattr(run, "updated_at_ms", 0) or 0)
                created_ms = int(getattr(run, "created_at_ms", 0) or 0)
                return (updated_ms or created_ms, str(run.run_id or ""))

            leaves.sort(key=_leaf_order)
            current = leaves[-1]
            for leaf in leaves[:-1]:  # oldest stale leaf first
                if remaining <= 0:
                    summary["skipped"] += 1
                    continue
                if str(leaf.status or "").strip().lower() != "cancelled":
                    # Only CANCELLED leaves are safe to auto-archive;
                    # SUCCEEDED/FAILED/RECONCILIATION_REQUIRED leaves may
                    # carry evidence an operator still needs to review.
                    summary["skipped"] += 1
                    continue
                try:
                    fresh = runtime.store.get_run(str(leaf.run_id or ""))
                except Exception:  # noqa: BLE001 - re-read failure is skippable
                    fresh = None
                if (
                    fresh is None
                    or str(getattr(fresh, "team_id", "") or "") != team_id
                    or str(getattr(fresh, "status", "") or "").strip().lower()
                    != "cancelled"
                ):
                    summary["skipped"] += 1
                    continue
                # The per-pass bound counts attempts, not just successes: a
                # flapping submit failure must not let one tick exceed it.
                remaining -= 1
                try:
                    with server_operator_scope(
                        STALE_LEAF_ARCHIVE_ACTOR_ID,
                        display_name="Formal lineage auto-heal",
                        roles=("operator",),
                    ):
                        receipt = runtime.command_service.submit(
                            CommandRequest(
                                command_id=new_id("cmd"),
                                run_id=fresh.run_id,
                                team_id=team_id,
                                command=WorkflowCommandKind.ARCHIVE_RUN,
                                node_id=None,
                                expected_run_version=int(fresh.run_version),
                                idempotency_key=(
                                    f"hf2:sweep-archive-stale-leaf:{fresh.run_id}"
                                ),
                                payload={"reason": STALE_LEAF_ARCHIVE_REASON},
                                requested_by=ActorRef(
                                    "system", STALE_LEAF_ARCHIVE_ACTOR_ID
                                ),
                                requested_at_ms=int(time.time() * 1000),
                            )
                        )
                except Exception as exc:  # noqa: BLE001 - isolate one leaf
                    summary["failed"] += 1
                    _record_scene_event(
                        "hypothesis_first.stale_leaf_auto_archive",
                        outcome="failed",
                        level="warning",
                        fields={
                            "runId": str(fresh.run_id or ""),
                            "questionId": question_id,
                            "currentRunId": str(current.run_id or ""),
                            "error": type(exc).__name__,
                        },
                    )
                    continue
                summary["archived"] += 1
                _record_scene_event(
                    "hypothesis_first.stale_leaf_auto_archive",
                    outcome=str(getattr(receipt, "status", "") or "submitted"),
                    fields={
                        "runId": str(fresh.run_id or ""),
                        "questionId": question_id,
                        "currentRunId": str(current.run_id or ""),
                    },
                )
    return summary
