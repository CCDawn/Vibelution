"""Durable ``event_publish`` outbox worker (knowledge cross-run handoff).

The knowledge sideflow child's terminal commit inserts a pending
``event_publish`` row in the SAME ledger transaction as its terminal facts;
this worker leases it, delivers the typed payload to the parent-side
consumer, and only then ACKs.  Delivery is at-least-once: the consumer is
idempotent (deterministic event id per
``knowledge-result:<invocationId>:<packageContentHash>``), so a crash
between consumer write and ACK converges on replay without duplicate
writes.  Retries past the lease-attempt gate dead-letter the action and mark
the producing child run ``reconciliation_required`` with diagnostics.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.ledger.repository import MAX_OUTBOX_LEASE_ATTEMPTS

from .block_projection import mark_run_reconciliation_required


class EventPublishWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        owner_id: str = "event-publish-worker",
        lease_ms: int = 30_000,
        now_provider: Callable[[], int] | None = None,
        commit_hook: Callable[[], None] | None = None,
        deliver: Callable[[dict], dict] | None = None,
        notify_readiness: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._commit_hook = commit_hook
        self._notify_readiness = notify_readiness
        self._deliver = deliver

    def _deliver_payload(self, payload: dict) -> dict:
        if self._deliver is not None:
            return self._deliver(payload)
        from .knowledge_sideflow_service import absorb_knowledge_result

        return absorb_knowledge_result(
            self._store,
            payload,
            now_provider=self._now,
            notify_readiness=self._notify_readiness,
        )

    def _submit(self, mutate, *, force_flush: bool = True):
        hook = self._commit_hook

        def wrapped(uow):
            if hook is not None:
                uow.after_commit(hook)
            return mutate(uow)

        return self._store.submit(wrapped, force_flush=force_flush)

    def run_once(self, limit: int = 8) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=("event_publish",),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action) -> None:
        try:
            payload = json.loads(action.payload_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            # Undecodable payload is deterministic, never transient.
            self._dead_letter(action, exc, deterministic=True)
            return
        try:
            self._deliver_payload(payload)
        except Exception as exc:  # noqa: BLE001 - delivery failure is data
            self._requeue_or_dead_letter(action, exc)
            return

        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, self._now())

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _requeue_or_dead_letter(self, action, exc: BaseException) -> None:
        now_ms = self._now()
        attempts = int(getattr(action, "attempt_count", 0) or 0) + 1
        problem = json.dumps(
            {
                "code": "event_publish_delivery_failed",
                "errorType": type(exc).__name__,
                "detail": str(exc)[:500],
                "attempt": attempts,
            },
            ensure_ascii=False,
        )
        if attempts >= MAX_OUTBOX_LEASE_ATTEMPTS:
            self._dead_letter(action, exc)
            return
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=problem,
        )

    def _dead_letter(
        self, action, exc: BaseException, *, deterministic: bool = False
    ) -> None:
        now_ms = self._now()
        problem = json.dumps(
            {
                "code": (
                    "event_publish_payload_invalid"
                    if deterministic
                    else "event_publish_dead_lettered"
                ),
                "errorType": type(exc).__name__,
                "detail": str(exc)[:500],
            },
            ensure_ascii=False,
        )

        def mutate(uow):
            uow.repository.fail_outbox(
                action.action_id, self._owner, now_ms, problem_json=problem
            )
            reconciliation_problem = {
                "code": "event_publish_dead_lettered",
                "detail": (
                    "knowledge_result_available could not be delivered to "
                    f"the parent run: {type(exc).__name__}: {exc}"
                )[:500],
            }
            transitioned = mark_run_reconciliation_required(
                uow,
                run_id=str(action.run_id or ""),
                problem=reconciliation_problem,
                now_ms=now_ms,
                actor_id=self._owner,
                correlation_id=str(getattr(action, "action_id", "") or ""),
                node_run_id=str(getattr(action, "node_run_id", "") or "") or None,
                action_id=str(getattr(action, "action_id", "") or ""),
                extra_payload={"worker": "event-publish-worker"},
            )
            if not transitioned:
                # The producing child already reached a terminal run status
                # (normally ``succeeded``): its terminal facts must not be
                # overwritten, so the operator-visible reconciliation surface
                # is the cross-run invocation record instead.
                invocation = uow.repository.find_knowledge_invocation_by_child_run(
                    str(action.run_id or "")
                )
                if invocation is not None:
                    uow.repository.update_knowledge_invocation(
                        invocation.invocation_id,
                        now_ms,
                        status=invocation.status,
                        error_json=json.dumps(
                            {
                                **reconciliation_problem,
                                "actionId": str(action.action_id or ""),
                                "worker": "event-publish-worker",
                            },
                            ensure_ascii=False,
                        ),
                    )

        self._submit(mutate, force_flush=True).result(timeout=30)
