"""Durable workflow event replay — Ledger workflow_events is the only history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.contracts import WorkflowEventEnvelope, WorkflowEventType
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger.errors import (
    WorkflowLedgerClosedError,
    WorkflowLedgerUnavailableError,
)
from core.research.workflow.ledger.records import EventRecord

from .query_service import (
    RunNotFoundError,
    TeamScopeMismatchError,
    WorkflowLedgerUnavailable,
)


@dataclass(frozen=True, slots=True)
class EventPage:
    run_id: str
    team_id: str
    run_version: int
    latest_event_sequence: int
    events: tuple[WorkflowEventEnvelope, ...]
    after_sequence: int = 0
    last_returned_sequence: int = 0
    has_more: bool = False
    next_after_sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "teamId": self.team_id,
            "runVersion": self.run_version,
            "latestEventSequence": self.latest_event_sequence,
            "afterSequence": self.after_sequence,
            "lastReturnedSequence": self.last_returned_sequence,
            "hasMore": self.has_more,
            "nextAfterSequence": self.next_after_sequence,
            "events": [envelope_api_dict(event) for event in self.events],
        }


class WorkflowEventReplayService:
    def __init__(self, *, store: WorkflowLedgerStore) -> None:
        self._store = store

    def list_events(
        self,
        *,
        team_id: str,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> EventPage:
        scoped = _require_team_id(team_id)
        if after_sequence < 0:
            raise ValueError("afterSequence must be >= 0")
        try:

            def load(repo):
                run = repo.get_run(run_id)
                if run is None:
                    return None
                if run.team_id != scoped:
                    raise TeamScopeMismatchError()
                records = repo.list_events(
                    run_id, after_sequence=after_sequence, limit=limit
                )
                latest = repo.latest_event_sequence(run_id)
                return run, records, latest

            bundle = self._store.read(load)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        except TeamScopeMismatchError:
            raise

        if bundle is None:
            raise RunNotFoundError(run_id)
        run, records, latest = bundle

        events = tuple(
            _envelope_from_record(
                record,
                team_id=scoped,
                workflow_id=run.workflow_id,
                workflow_version_id=run.workflow_version_id,
            )
            for record in records
        )
        # Defensive: never emit duplicates or out-of-order sequences.
        seen: set[int] = set()
        ordered: list[WorkflowEventEnvelope] = []
        for event in sorted(events, key=lambda item: item.sequence):
            if event.sequence in seen:
                continue
            if event.sequence <= after_sequence:
                continue
            seen.add(event.sequence)
            ordered.append(event)
        last_returned = ordered[-1].sequence if ordered else after_sequence
        has_more = last_returned < int(latest)
        return EventPage(
            run_id=run_id,
            team_id=scoped,
            run_version=run.run_version,
            latest_event_sequence=latest,
            events=tuple(ordered),
            after_sequence=after_sequence,
            last_returned_sequence=last_returned,
            has_more=has_more,
            next_after_sequence=last_returned if has_more else None,
        )


def _require_team_id(team_id: str) -> str:
    normalized = str(team_id or "").strip()
    if not normalized:
        raise TeamScopeMismatchError("teamId is required")
    return normalized


def _envelope_from_record(
    record: EventRecord,
    *,
    team_id: str,
    workflow_id: str,
    workflow_version_id: str,
) -> WorkflowEventEnvelope:
    event_type: WorkflowEventType | str
    try:
        event_type = WorkflowEventType(record.event_type)
    except ValueError:
        # The ledger is append-only history: replay must keep serving the whole
        # stream even when a record was written with an event type this build
        # does not know yet. Keep the raw value instead of failing the request.
        event_type = str(record.event_type)
    actor = json.loads(record.actor_json or "{}")
    payload = json.loads(record.payload_json or "{}")
    return WorkflowEventEnvelope(
        event_id=record.event_id,
        sequence=record.sequence,
        team_id=team_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=record.run_id,
        run_version=record.run_version,
        event_type=event_type,
        actor=actor if isinstance(actor, dict) else {},
        correlation_id=record.correlation_id,
        causation_id=record.causation_id,
        payload=payload if isinstance(payload, dict) else {"value": payload},
        occurred_at_ms=record.occurred_at_ms,
    )


def envelope_api_dict(event: WorkflowEventEnvelope) -> dict[str, Any]:
    """Frozen HTTP/SSE surface: occurredAt string + typed fields."""
    payload = event.to_dict()
    occurred_at = (
        datetime.fromtimestamp(event.occurred_at_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    api = {
        "eventId": payload["eventId"],
        "sequence": payload["sequence"],
        "runId": payload["runId"],
        "teamId": payload["teamId"],
        "runVersion": payload["runVersion"],
        "type": payload["type"],
        "correlationId": payload["correlationId"],
        "occurredAt": occurred_at,
        "payload": payload["payload"],
    }
    if payload.get("causationId"):
        api["causationId"] = payload["causationId"]
    return api
