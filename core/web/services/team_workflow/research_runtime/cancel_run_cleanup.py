"""Durable cleanup worker for chat turns owned by a cancelled run.

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
    ) -> None:
        self._store = store
        self._owner = str(owner_id or "cancel-run-cleanup-worker").strip()
        self._lease_ms = max(1, int(lease_ms))
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._retry_delay_ms = max(0, int(retry_delay_ms))

    def run_once(self, limit: int = 4) -> int:
        """Process one resident-tick batch and return leased action count."""
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
        return len(leased)

    def _handle(self, action: Any) -> None:
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
            self._fail(
                action,
                problem={
                    "code": "invalid_cancel_run_cleanup_action",
                    "detail": "cleanup payload must contain kind and runId",
                },
            )
            return

        try:
            complete = self._reconcile_run_turns(run_id)
        except Exception as exc:  # noqa: BLE001 - durable intent must be retried
            logger.exception(
                "cancel_run cleanup attempt failed: runId=%s actionId=%s",
                run_id,
                str(getattr(action, "action_id", "") or ""),
            )
            self._requeue(
                action,
                problem={
                    "code": "cancel_run_cleanup_transient",
                    "detail": str(exc)[:400],
                },
            )
            return

        if complete:
            self._ack(action)
        else:
            # A stop request may only move the live turn to ``stopping``.  Do
            # not acknowledge until the persisted terminal record and its
            # activeRunId cleanup are both observable on the next read.
            self._requeue(
                action,
                problem={
                    "code": "cancel_run_cleanup_pending",
                    "detail": "one or more chat turns are not terminal yet",
                },
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

    def _ack(self, action: Any) -> None:
        now_ms = self._now()

        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _requeue(self, action: Any, *, problem: dict[str, str]) -> None:
        now_ms = self._now()
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + self._retry_delay_ms,
            problem_json=json.dumps(problem, ensure_ascii=False, sort_keys=True),
            # A live turn may legitimately take longer than the generic
            # transient-attempt budget.  The lease itself remains protected
            # by the ledger attempt gate if the worker process dies.
            reset_attempts=True,
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
    "CancelRunCleanupWorker",
    "build_cancel_run_cleanup_record",
    "cancel_run_cleanup_idempotency_key",
]
