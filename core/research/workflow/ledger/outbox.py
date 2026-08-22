"""Outbox primitives: atomic lease / ack / requeue / fail.

Leasing must happen inside one BEGIN IMMEDIATE transaction via the single
writer; expired leases may be re-leased and adapters still need stable
idempotency keys to prevent duplicated external side effects (spec 6.7).
"""

from __future__ import annotations

from typing import Any

from .records import OutboxRecord


def lease_ready_actions(
    store: Any,
    *,
    owner: str,
    now_ms: int,
    limit: int = 8,
    lease_ms: int = 30_000,
    action_kinds: tuple[str, ...] | None = None,
) -> list[OutboxRecord]:
    future = store.submit(
        lambda uow: uow.repository.lease_outbox_actions(
            owner=owner,
            now_ms=now_ms,
            limit=limit,
            lease_ms=lease_ms,
            action_kinds=action_kinds,
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
) -> bool:
    future = store.submit(
        lambda uow: uow.repository.requeue_outbox(
            action_id, owner, now_ms, retry_at_ms=retry_at_ms, problem_json=problem_json
        ),
        force_flush=True,
    )
    return bool(future.result(timeout=30))
