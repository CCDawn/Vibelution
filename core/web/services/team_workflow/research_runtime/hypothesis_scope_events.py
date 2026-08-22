"""Idempotent, bounded Workflow Ledger events for hypothesis candidate scopes."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import EventRecord, WorkflowLedgerStore

HYPOTHESIS_SCOPE_EVENT_TYPES = frozenset(
    {
        "workflow.session_scope.resolved",
        "workflow.child_session.created",
        "workflow.child_session.resumed",
        "workflow.scope_attempt.retried",
        "workflow.hypothesis_fragment.recorded",
        "workflow.hypothesis_aggregation.blocked",
        "workflow.hypothesis_aggregation.completed",
    }
)
_ALLOWED_FIELDS = frozenset(
    {
        "mode",
        "selectionId",
        "candidateId",
        "candidateCount",
        "sessionId",
        "sessionAttempt",
        "taskId",
        "status",
        "durationMs",
        "errorCode",
        "scopeHash",
        "fragmentRef",
        "fragmentCount",
        "aggregationHash",
        "created",
        "fallbackReason",
    }
)


class HypothesisScopeEventConflict(RuntimeError):
    """Raised when a stable event ID is reused for different event content."""


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [str(item or "")[:200] for item in value[:16]]
    return str(value or "")[:240]


def _safe_payload(action: PendingAction, fields: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "nodeId": action.node_id,
        "nodeRunId": action.node_run_id,
        "attempt": action.attempt,
    }
    payload.update(
        {
            key: _bounded_value(value)
            for key, value in fields.items()
            if key in _ALLOWED_FIELDS
        }
    )
    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_json_text(value: str) -> str:
    try:
        return _canonical_json(json.loads(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _canonical_event_content(event: EventRecord) -> tuple[str, ...]:
    """Compare semantic event content while ignoring ledger placement/time."""

    return (
        event.run_id,
        event.event_id,
        event.event_type,
        _canonical_json_text(event.actor_json),
        event.correlation_id,
        event.causation_id or "",
        _canonical_json_text(event.payload_json),
    )


def record_hypothesis_scope_event(
    store: WorkflowLedgerStore,
    *,
    action: PendingAction,
    event_type: str,
    fields: Mapping[str, Any],
    discriminator: str = "",
) -> str:
    """Append once; event identity is stable across outbox replay."""

    if event_type not in HYPOTHESIS_SCOPE_EVENT_TYPES:
        raise ValueError(f"unsupported hypothesis scope event: {event_type}")
    identity = "|".join(
        (
            action.run_id,
            action.node_run_id,
            event_type,
            str(discriminator or ""),
        )
    )
    event_id = "evt-hyp-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    payload = _safe_payload(action, fields)
    now_ms = int(time.time() * 1000)
    actor_json = _canonical_json(
        {
            "actorType": action.actor_kind.value,
            "actorId": "hypothesis-scope-runtime",
        }
    )
    candidate = EventRecord(
        run_id=action.run_id,
        sequence=0,
        event_id=event_id,
        run_version=0,
        event_type=event_type,
        actor_json=actor_json,
        correlation_id=action.action_id,
        causation_id=None,
        payload_json=_canonical_json(payload),
        occurred_at_ms=0,
    )

    def mutate(uow: Any) -> None:
        existing = uow.repository.get_event_by_id(event_id)
        if existing is not None:
            if _canonical_event_content(existing) == _canonical_event_content(
                candidate
            ):
                return
            raise HypothesisScopeEventConflict(
                f"hypothesis scope event ID conflict: {event_id}"
            )
        run = uow.repository.get_run(action.run_id)
        if run is None:
            return
        sequence = uow.repository.advance_last_sequence(action.run_id, 1, now_ms)
        if sequence is None:
            return
        uow.repository.insert_event(
            EventRecord(
                run_id=action.run_id,
                sequence=sequence,
                event_id=event_id,
                run_version=run.run_version,
                event_type=event_type,
                actor_json=actor_json,
                correlation_id=action.action_id,
                causation_id=None,
                payload_json=candidate.payload_json,
                occurred_at_ms=now_ms,
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
    return event_id


__all__ = [
    "HYPOTHESIS_SCOPE_EVENT_TYPES",
    "HypothesisScopeEventConflict",
    "record_hypothesis_scope_event",
]
