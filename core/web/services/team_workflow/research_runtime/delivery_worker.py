"""Delivery orchestration worker — runs the post-run Challenge Cup delivery chain.

Leases ``delivery_orchestration`` outbox actions (enqueued atomically with the
run-succeeded transition), executes the chain outside the writer transaction,
then commits exactly one terminal Ledger event plus the outbox settlement in a
single transaction. The run row itself is never touched: delivery outcomes are
diagnosable from the timeline while the run stays ``succeeded``.

Crash safety: the artifact write is idempotent by content hash and the terminal
event + ack commit atomically, so a crashed attempt simply re-runs the chain
and appends a newer artifact row.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api

from .delivery_orchestration import (
    DELIVERY_OUTBOX_KIND,
    DeliveryOrchestrationError,
    build_delivery_event,
    run_delivery_orchestration,
    run_status_allows_delivery,
)

DEFAULT_DELIVERY_LEASE_MS = 30_000
MAX_DELIVERY_ATTEMPTS = 3


class DeliveryOrchestrationWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        owner_id: str = "delivery-worker",
        lease_ms: int = DEFAULT_DELIVERY_LEASE_MS,
        now_provider: Callable[[], int] | None = None,
        commit_hook: Callable[[], None] | None = None,
        max_attempts: int = MAX_DELIVERY_ATTEMPTS,
    ) -> None:
        self._store = store
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._commit_hook = commit_hook
        self._max_attempts = max(1, int(max_attempts))

    def _submit(self, mutate, *, force_flush: bool = True):
        hook = self._commit_hook

        def wrapped(uow):
            if hook is not None:
                uow.after_commit(hook)
            return mutate(uow)

        return self._store.submit(wrapped, force_flush=force_flush)

    def run_once(self, limit: int = 4) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=(DELIVERY_OUTBOX_KIND,),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action: Any) -> None:
        now_ms = self._now()
        run_id = ""
        try:
            payload = json.loads(action.payload_json)
            if isinstance(payload, dict):
                run_id = str(payload.get("runId") or "").strip()
        except (TypeError, ValueError):
            run_id = ""
        if not run_id:
            self._fail(
                action,
                now_ms=now_ms,
                problem={"code": "invalid_delivery_action", "detail": "missing runId"},
            )
            return
        run = self._store.get_run(run_id)
        if run is None or not run_status_allows_delivery(run.status):
            # Run gone or no longer succeeded (e.g. archived): nothing to deliver.
            self._ack_only(action, now_ms=now_ms)
            return
        try:
            outcome = run_delivery_orchestration(self._store, run_id=run_id, now_ms=now_ms)
        except DeliveryOrchestrationError as exc:
            self._commit_terminal(
                action,
                run=run,
                now_ms=now_ms,
                outcome={
                    "status": "failed",
                    "code": exc.code,
                    "detail": exc.detail,
                    "failedStep": exc.step,
                },
            )
            return
        except Exception as exc:  # noqa: BLE001 - transient failures requeue, never sink the action
            if action.attempt_count < self._max_attempts:
                outbox_api.requeue_action(
                    self._store,
                    action.action_id,
                    self._owner,
                    now_ms,
                    retry_at_ms=now_ms + 5_000,
                    problem_json=json.dumps(
                        {"code": "transient", "detail": str(exc)},
                        ensure_ascii=False,
                    ),
                )
                return
            self._commit_terminal(
                action,
                run=run,
                now_ms=now_ms,
                outcome={
                    "status": "failed",
                    "code": "delivery_orchestration_exception",
                    "detail": str(exc),
                    "failedStep": "orchestration",
                },
            )
            return
        self._commit_terminal(action, run=run, now_ms=now_ms, outcome=outcome)

    def _ack_only(self, action: Any, *, now_ms: int) -> None:
        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _fail(self, action: Any, *, now_ms: int, problem: dict[str, str]) -> None:
        def mutate(uow):
            uow.repository.fail_outbox(
                action.action_id,
                self._owner,
                now_ms,
                problem_json=json.dumps(problem, ensure_ascii=False),
            )

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _commit_terminal(
        self,
        action: Any,
        *,
        run: Any,
        now_ms: int,
        outcome: dict[str, Any],
    ) -> None:
        """One tx: settle the outbox action + append the terminal event."""
        status = str(outcome.get("status") or "failed")

        def mutate(uow):
            if status == "failed":
                settled = uow.repository.fail_outbox(
                    action.action_id,
                    self._owner,
                    now_ms,
                    problem_json=json.dumps(
                        {
                            "code": str(outcome.get("code") or "delivery_failed"),
                            "detail": str(outcome.get("detail") or ""),
                        },
                        ensure_ascii=False,
                    ),
                )
            else:
                settled = uow.repository.ack_outbox(
                    action.action_id, self._owner, now_ms
                )
            if not settled:
                return
            sequence = uow.repository.advance_last_sequence(run.run_id, 1, now_ms)
            if sequence is None:
                return
            uow.repository.insert_event(
                build_delivery_event(
                    run=run,
                    sequence=sequence,
                    outcome=outcome,
                    actor_id=self._owner,
                    correlation_id=str(action.action_id or run.run_id),
                    now_ms=now_ms,
                )
            )

        self._submit(mutate, force_flush=True).result(timeout=30)
