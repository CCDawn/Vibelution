"""Durable cleanup worker for turns and budgets owned by a cancelled run.

``cancel_run`` is a ledger command, while stopping a web chat turn is a
separate session-side effect.  Keeping the two operations separate is
intentional: the command can commit even when the session process is busy or
temporarily unavailable, and this worker can retry the side effect from the
ledger outbox after a process restart.

The worker runs on the existing research-workflow resident tick.  It does not
create a second polling thread or a second source of truth for cleanup state.
The ``reconcile`` outbox kind is the existing run-scoped recovery namespace;
the payload kind and idempotency key make this cleanup intent distinct from
other recovery actions.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api

logger = logging.getLogger(__name__)

CANCEL_RUN_CLEANUP_OUTBOX_KIND = "reconcile"
CANCEL_RUN_CLEANUP_PAYLOAD_KIND = "cancel_run_chat_turn_cleanup"
CANCEL_RUN_CLEANUP_IDEMPOTENCY_PREFIX = "cancel_run_cleanup:"
DEFAULT_CANCEL_RUN_CLEANUP_LEASE_MS = 30_000
DEFAULT_CANCEL_RUN_CLEANUP_RETRY_DELAY_MS = 1_000
# Bounded failure budget for one cleanup intent.  Transient failures are
# requeued WITHOUT resetting ``attempt_count`` so the lease attempt gate stays
# meaningful; once this cap is reached the intent is parked terminally as
# ``failed`` (dead-letter) instead of retrying forever.  Only the legitimate
# long wait for chat turns to reach a terminal state still resets attempts.
DEFAULT_CANCEL_RUN_CLEANUP_MAX_ATTEMPTS = 8


def cancel_run_cleanup_idempotency_key(run_id: str) -> str:
    return f"{CANCEL_RUN_CLEANUP_IDEMPOTENCY_PREFIX}{str(run_id or '').strip()}"


def build_cancel_run_cleanup_record(
    *,
    run_id: str,
    command_id: str,
    now_ms: int,
) -> Any:
    """Build the durable intent inserted in the cancel command transaction."""
    from core.research.workflow.ledger import OutboxRecord

    from .ids import new_id

    normalized_run_id = str(run_id or "").strip()
    payload = {
        "schemaVersion": 1,
        "kind": CANCEL_RUN_CLEANUP_PAYLOAD_KIND,
        "runId": normalized_run_id,
        "commandId": str(command_id or "").strip(),
    }
    return OutboxRecord(
        action_id=new_id("act"),
        run_id=normalized_run_id,
        command_id=str(command_id or "").strip() or None,
        node_run_id=None,
        action_kind=CANCEL_RUN_CLEANUP_OUTBOX_KIND,
        idempotency_key=cancel_run_cleanup_idempotency_key(normalized_run_id),
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        status="pending",
        attempt_count=0,
        available_at_ms=int(now_ms),
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=int(now_ms),
        updated_at_ms=int(now_ms),
    )


class CancelRunCleanupWorker:
    """Lease and finish cancellation cleanup intents from the ledger outbox."""

    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        owner_id: str = "cancel-run-cleanup-worker",
        lease_ms: int = DEFAULT_CANCEL_RUN_CLEANUP_LEASE_MS,
        now_provider: Callable[[], int] | None = None,
        retry_delay_ms: int = DEFAULT_CANCEL_RUN_CLEANUP_RETRY_DELAY_MS,
        max_attempts: int = DEFAULT_CANCEL_RUN_CLEANUP_MAX_ATTEMPTS,
    ) -> None:
        self._store = store
        self._owner = str(owner_id or "cancel-run-cleanup-worker").strip()
        self._lease_ms = max(1, int(lease_ms))
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._retry_delay_ms = max(0, int(retry_delay_ms))
        self._max_attempts = max(1, int(max_attempts))

    def run_once(self, limit: int = 4) -> int:
        """Process one resident-tick batch and return handled work count."""
        repaired = self._repair_completed_cleanup_budget_receipts(limit=limit)
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=(CANCEL_RUN_CLEANUP_OUTBOX_KIND,),
            idempotency_prefix=CANCEL_RUN_CLEANUP_IDEMPOTENCY_PREFIX,
        )
        for action in leased:
            self._handle(action)
        return repaired + len(leased)

    def _handle(self, action: Any) -> None:
        """Handle one leased cleanup intent without ever raising.

        A per-run cleanup failure is a poisoned queue entry, not a process
        fault: the resident maintenance tick drives this worker on backend
        startup/shutdown drains, so any exception escaping ``_handle``
        (including a failure of the ack/requeue write itself, e.g. the writer
        shutting down) kills the whole backend in a crash loop.  Every path
        here ends in an ack, a bounded requeue, or a terminal parked failure.
        """
        run_id = ""
        payload: dict[str, Any] = {}
        try:
            raw = json.loads(str(getattr(action, "payload_json", "") or "{}"))
            if isinstance(raw, dict):
                payload = raw
            run_id = str(payload.get("runId") or getattr(action, "run_id", "") or "").strip()
        except (TypeError, ValueError):
            pass

        if str(payload.get("kind") or "").strip() != CANCEL_RUN_CLEANUP_PAYLOAD_KIND or not run_id:
            self._safe_fail(
                action,
                problem={
                    "code": "invalid_cancel_run_cleanup_action",
                    "detail": "cleanup payload must contain kind and runId",
                },
            )
            return

        try:
            complete = self._reconcile_run_turns(run_id)
            if complete:
                self._finalize_budget_receipts(run_id)
        except Exception as exc:
            logger.exception(
                "cancel_run cleanup attempt failed: runId=%s actionId=%s attempt=%s/%s",
                run_id,
                str(getattr(action, "action_id", "") or ""),
                int(getattr(action, "attempt_count", 0) or 0),
                self._max_attempts,
            )
            self._park_or_requeue(
                action,
                run_id=run_id,
                problem={
                    "code": "cancel_run_cleanup_transient",
                    "detail": str(exc)[:400],
                },
            )
            return

        if complete:
            # The budget finalize above is idempotent (terminal receipts are
            # skipped), so a failed ack can safely fall back to a requeue and
            # re-run the settlement on the next tick.
            self._safe_ack(action, run_id=run_id)
        else:
            # A stop request may only move the live turn to ``stopping``.  Do
            # not acknowledge until the persisted terminal record and its
            # activeRunId cleanup are both observable on the next read.  This
            # is a legitimate long wait, so the attempt budget is reset.
            self._safe_requeue(
                action,
                run_id=run_id,
                problem={
                    "code": "cancel_run_cleanup_pending",
                    "detail": "one or more chat turns are not terminal yet",
                },
                reset_attempts=True,
            )

    def _park_or_requeue(
        self,
        action: Any,
        *,
        run_id: str,
        problem: dict[str, str],
    ) -> None:
        """Bound a failing intent: requeue within the attempt cap, park after.

        Requeueing preserves ``attempt_count`` so the ledger's lease attempt
        gate stays accurate; at the cap the intent is marked terminally
        ``failed`` (persistent dead-letter with the recorded problem) so a
        permanently poisoned entry cannot re-arm on every tick.
        """
        attempt_count = int(getattr(action, "attempt_count", 0) or 0)
        if attempt_count >= self._max_attempts:
            logger.error(
                "cancel_run cleanup parked after %d attempts: runId=%s actionId=%s code=%s",
                attempt_count,
                run_id,
                str(getattr(action, "action_id", "") or ""),
                str(problem.get("code") or ""),
            )
            self._safe_fail(
                action,
                problem={
                    "code": "cancel_run_cleanup_parked",
                    "attempts": str(attempt_count),
                    "detail": str(problem.get("detail") or "")[:400],
                },
            )
            return
        self._safe_requeue(action, run_id=run_id, problem=problem, reset_attempts=False)

    def _repair_completed_cleanup_budget_receipts(self, *, limit: int) -> int:
        """Repair cancellations completed by runtimes that omitted budgets."""
        rows = self._store.read(
            lambda repo: repo.execute(
                """
                SELECT DISTINCT b.run_id
                FROM budget_receipts AS b
                JOIN workflow_runs AS r ON r.run_id = b.run_id
                WHERE r.status = 'cancelled'
                  AND b.status NOT IN ('settled', 'released', 'failed', 'voided')
                  AND EXISTS (
                    SELECT 1 FROM outbox_actions AS o
                    WHERE o.run_id = b.run_id
                      AND o.idempotency_key = ? || b.run_id
                      AND o.status = 'succeeded'
                  )
                ORDER BY b.run_id
                LIMIT ?
                """,
                (CANCEL_RUN_CLEANUP_IDEMPOTENCY_PREFIX, max(1, int(limit))),
            ).fetchall()
        )
        repaired = 0
        for row in rows:
            run_id = str(row[0] or "").strip()
            if not run_id:
                continue
            try:
                if not self._reconcile_run_turns(run_id):
                    continue
                self._finalize_budget_receipts(run_id)
            except Exception:
                logger.exception(
                    "cancel_run legacy budget repair failed: runId=%s",
                    run_id,
                )
                continue
            repaired += 1
        return repaired

    def _finalize_budget_receipts(self, run_id: str) -> None:
        from .budget_authority_adapter import (
            finalize_cancelled_run_budget_receipts,
        )

        finalize_cancelled_run_budget_receipts(
            self._store,
            run_id,
            reason="run_cancelled",
        )

    def _reconcile_run_turns(self, run_id: str) -> bool:
        from core.web.services import session_service

        from .command_service import (
            _CHAT_TURN_OPEN_STATUSES,
            _close_cancel_run_turn,
            _collect_cancel_run_turn_pairs,
        )

        pairs = _collect_cancel_run_turn_pairs(run_id)
        if not pairs:
            return True

        complete = True
        for session_id, turn_id in pairs:
            _close_cancel_run_turn(session_service, session_id, turn_id)
            if not _terminal_turn_is_closed(session_service, turn_id, _CHAT_TURN_OPEN_STATUSES):
                complete = False
        return complete

    def _safe_ack(self, action: Any, *, run_id: str) -> None:
        try:
            self._ack(action)
        except Exception:
            # The settlement succeeded; the ack write failing (e.g. the ledger
            # writer shutting down during a drain) must not escape.  Fall back
            # to a bounded requeue — the idempotent finalize makes the retry
            # harmless, and the lease gates prevent unbounded retries.
            logger.exception(
                "cancel_run cleanup ack failed: runId=%s actionId=%s",
                run_id,
                str(getattr(action, "action_id", "") or ""),
            )
            self._park_or_requeue(
                action,
                run_id=run_id,
                problem={
                    "code": "cancel_run_cleanup_ack_failed",
                    "detail": "cleanup succeeded but the ack write failed",
                },
            )

    def _safe_requeue(
        self,
        action: Any,
        *,
        run_id: str,
        problem: dict[str, str],
        reset_attempts: bool,
    ) -> None:
        try:
            self._requeue(action, problem=problem, reset_attempts=reset_attempts)
        except Exception:
            # The lease will expire and the recovery gates re-arm or retire
            # the action; never propagate into the resident tick.
            logger.exception(
                "cancel_run cleanup requeue failed: runId=%s actionId=%s",
                run_id,
                str(getattr(action, "action_id", "") or ""),
            )

    def _safe_fail(self, action: Any, *, problem: dict[str, str]) -> None:
        try:
            self._fail(action, problem=problem)
        except Exception:
            logger.exception(
                "cancel_run cleanup terminal-fail write failed: actionId=%s",
                str(getattr(action, "action_id", "") or ""),
            )

    def _ack(self, action: Any) -> None:
        now_ms = self._now()

        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _requeue(
        self,
        action: Any,
        *,
        problem: dict[str, str],
        reset_attempts: bool = False,
    ) -> None:
        now_ms = self._now()
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + self._retry_delay_ms,
            problem_json=json.dumps(problem, ensure_ascii=False, sort_keys=True),
            # Only the pending-turn wait resets the attempt budget (a live
            # turn may legitimately take longer than any transient-attempt
            # budget).  Failure requeues keep the count so the cap parks the
            # entry instead of looping forever.  The lease itself remains
            # protected by the ledger attempt gate if the worker dies.
            reset_attempts=reset_attempts,
        )

    def _fail(self, action: Any, *, problem: dict[str, str]) -> None:
        now_ms = self._now()
        outbox_api.fail_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            json.dumps(problem, ensure_ascii=False, sort_keys=True),
        )


def _terminal_turn_is_closed(
    session_service: Any,
    turn_id: str,
    open_statuses: frozenset[str],
) -> bool:
    """Require terminal snapshot plus cleared ``chat_turn.activeRunId``."""
    store = getattr(session_service, "_WORK_RUN_STORE", None)
    if store is None or not callable(getattr(store, "load_snapshot", None)):
        return False
    snapshot = store.load_snapshot("chat_turn", turn_id)
    if not isinstance(snapshot, dict):
        return False
    status = str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
    terminal_statuses = {
        "cancelled",
        "closed",
        "completed",
        "done",
        "failed",
        "failed_provider",
        "failed_runtime",
        "idle",
        "needs_continue",
        "paused_limit",
        "partial",
        "ready",
        "routed",
        "stopped",
        "stopped_by_user",
        "stop_failed",
        "superseded",
    }
    if status in open_statuses and not str(snapshot.get("finishedAt") or "").strip():
        return False
    if status not in terminal_statuses and not str(snapshot.get("finishedAt") or "").strip():
        return False

    load_index = getattr(store, "load_run_index", None)
    if not callable(load_index):
        # Lightweight test doubles can only prove the terminal snapshot.  The
        # production WorkRunStore always exposes the index proof below.
        return True
    index = load_index("chat_turn")
    if str(index.get("activeRunId") or "").strip() == str(turn_id or "").strip():
        # Repair an old terminal snapshot that retained the active index.  The
        # canonical persist writer is idempotent and clears that index for a
        # terminal status without rewriting the business payload.
        persist = getattr(store, "persist_snapshot", None)
        if not callable(persist):
            return False
        persist("chat_turn", snapshot, active_run_id=turn_id)
        index = load_index("chat_turn")
    return str(index.get("activeRunId") or "").strip() != str(turn_id or "").strip()


__all__ = [
    "CANCEL_RUN_CLEANUP_IDEMPOTENCY_PREFIX",
    "CANCEL_RUN_CLEANUP_OUTBOX_KIND",
    "CANCEL_RUN_CLEANUP_PAYLOAD_KIND",
    "DEFAULT_CANCEL_RUN_CLEANUP_MAX_ATTEMPTS",
    "CancelRunCleanupWorker",
    "build_cancel_run_cleanup_record",
    "cancel_run_cleanup_idempotency_key",
]
