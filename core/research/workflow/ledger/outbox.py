"""Outbox primitives: atomic lease / ack / requeue / fail.

Leasing must happen inside one BEGIN IMMEDIATE transaction via the single
writer; expired leases may be re-leased and adapters still need stable
idempotency keys to prevent duplicated external side effects (spec 6.7).
"""

from __future__ import annotations

from typing import Any

from .records import OutboxRecord
from .repository import (
    DEFAULT_OUTBOX_LEASE_MS,
    MAX_OUTBOX_LEASE_ATTEMPTS,
    MAX_OUTBOX_LEASE_RECOVERIES,
)


def lease_ready_actions(
    store: Any,
    *,
    owner: str,
    now_ms: int,
    limit: int = 8,
    lease_ms: int = DEFAULT_OUTBOX_LEASE_MS,
    action_kinds: tuple[str, ...] | None = None,
    idempotency_prefix: str | None = None,
    background_workflow_ids: tuple[str, ...] | None = None,
    background_limit: int | None = None,
    max_attempts: int = MAX_OUTBOX_LEASE_ATTEMPTS,
    max_lease_recoveries: int = MAX_OUTBOX_LEASE_RECOVERIES,
) -> list[OutboxRecord]:
    future = store.submit(
        lambda uow: uow.repository.lease_outbox_actions(
            owner=owner,
            now_ms=now_ms,
            limit=limit,
            lease_ms=lease_ms,
            action_kinds=action_kinds,
            idempotency_prefix=idempotency_prefix,
            background_workflow_ids=background_workflow_ids,
            background_limit=background_limit,
            max_attempts=max_attempts,
            max_lease_recoveries=max_lease_recoveries,
        ),
        force_flush=True,
    )
    return list(future.result(timeout=30))


def ack_action(store: Any, action_id: str, owner: str, now_ms: int) -> bool:
    future = store.submit(
        lambda uow: uow.repository.ack_outbox(
            action_id, owner, now_ms, status="succeeded"
        ),
        force_flush=True,
    )
    return bool(future.result(timeout=30))


def renew_lease(
    store: Any,
    action_id: str,
    owner: str,
    *,
    now_ms: int,
    lease_ms: int,
) -> bool:
    future = store.submit(
        lambda uow: uow.repository.renew_outbox_lease(
            action_id,
            owner,
            now_ms,
            lease_ms,
        ),
        force_flush=True,
    )
    return bool(future.result(timeout=30))


def renew_lease_direct(
    store: Any,
    action_id: str,
    owner: str,
    *,
    now_ms: int,
    lease_ms: int,
) -> bool | None:
    """Renew a lease on a dedicated short-lived connection, bypassing the
    single-writer queue.

    Tri-state: ``True`` renewed; ``False`` definitive loss (rows_affected ==
    0 — lease reclaimed or expired); ``None`` transient miss (queue/busy
    contention, store closed) — the lease state is unknown and the window
    outlives several misses. The renewal is one atomic UPDATE, so running it
    on its own WAL connection is safe. Stores that do not implement the
    direct path (test fakes) fall back to the queued renewal, which only
    reports the binary renewed/not-renewed result.
    """
    direct = getattr(store, "renew_outbox_lease_direct", None)
    if direct is None:
        return renew_lease(
            store,
            action_id,
            owner,
            now_ms=now_ms,
            lease_ms=lease_ms,
        )
    return direct(action_id, owner, now_ms=now_ms, lease_ms=lease_ms)


def fail_action(
    store: Any, action_id: str, owner: str, now_ms: int, problem_json: str
) -> bool:
    future = store.submit(
        lambda uow: uow.repository.fail_outbox(action_id, owner, now_ms, problem_json),
        force_flush=True,
    )
    return bool(future.result(timeout=30))


def requeue_action(
    store: Any,
    action_id: str,
    owner: str,
    now_ms: int,
    *,
    retry_at_ms: int,
    problem_json: str,
    reset_attempts: bool = False,
) -> bool:
    future = store.submit(
        lambda uow: uow.repository.requeue_outbox(
            action_id,
            owner,
            now_ms,
            retry_at_ms=retry_at_ms,
            problem_json=problem_json,
            reset_attempts=reset_attempts,
        ),
        force_flush=True,
    )
    return bool(future.result(timeout=30))
