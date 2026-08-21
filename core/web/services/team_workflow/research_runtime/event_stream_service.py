"""SSE encoding and wait loop over committed Ledger events.

Notification only wakes waiters. Ledger tail is the source of truth.
Keepalive comments must never change the cursor. No silent polling fallback
for the UI — callers may still wait on Ledger between wakeups.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from typing import Any, Protocol

from .event_replay_service import WorkflowEventReplayService, envelope_api_dict
from .query_service import WorkflowQueryError


class StreamNotifier(Protocol):
    def notify(self) -> None: ...

    def wait(self, timeout: float) -> bool: ...


class InvalidLastEventIdError(WorkflowQueryError):
    code = "invalid_event_cursor"

    def __init__(self, detail: str) -> None:
        super().__init__(detail, code="invalid_event_cursor")


class LocalStreamNotifier:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._generation = 0

    def notify(self) -> None:
        with self._cond:
            self._generation += 1
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        """Wait until notify() advances generation, or timeout.

        Generation counters avoid lost wakeups when notify races ahead of wait.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            start = self._generation
            while self._generation == start:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)
            return True


def parse_stream_cursor(
    last_event_id: str | None,
    *,
    route_run_id: str,
    after_sequence: int | None = None,
) -> int:
    if after_sequence is not None and last_event_id:
        # Prefer Last-Event-ID on reconnect; afterSequence is for first connect.
        pass
    if last_event_id is not None and str(last_event_id).strip():
        raw = str(last_event_id).strip()
        if ":" not in raw:
            raise InvalidLastEventIdError(
                "Last-Event-ID must be '{runId}:{sequence}'"
            )
        run_id, seq_text = raw.rsplit(":", 1)
        if run_id != route_run_id:
            raise InvalidLastEventIdError(
                "Last-Event-ID runId does not match route runId"
            )
        try:
            sequence = int(seq_text)
        except ValueError as exc:
            raise InvalidLastEventIdError(
                "Last-Event-ID sequence must be an integer"
            ) from exc
        if sequence < 0:
            raise InvalidLastEventIdError(
                "Last-Event-ID sequence must be non-negative"
            )
        return sequence
    if after_sequence is None:
        return 0
    if after_sequence < 0:
        raise InvalidLastEventIdError("afterSequence must be >= 0")
    return int(after_sequence)


def encode_sse_event(
    *,
    run_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    frame_id = f"{run_id}:{sequence}"
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"id: {frame_id}\nevent: {event_type}\ndata: {encoded}\n\n"


def encode_keepalive() -> str:
    return ": keepalive\n\n"


class WorkflowEventStreamService:
    def __init__(
        self,
        *,
        store: Any,
        notifier: StreamNotifier | None = None,
        replay_service: WorkflowEventReplayService | None = None,
    ) -> None:
        self._store = store
        self._notifier = notifier or LocalStreamNotifier()
        self._replay = replay_service or WorkflowEventReplayService(store=store)

    @property
    def notifier(self) -> StreamNotifier:
        return self._notifier

    def validate_stream_request(
        self,
        *,
        team_id: str,
        run_id: str,
        after_sequence: int | None = None,
        last_event_id: str | None = None,
    ) -> int:
        """Parse cursor and confirm run scope without materializing replay frames."""
        cursor = parse_stream_cursor(
            last_event_id,
            route_run_id=run_id,
            after_sequence=after_sequence,
        )
        # limit=1 is enough to enforce team/run existence and cursor validity.
        self._replay.list_events(
            team_id=team_id,
            run_id=run_id,
            after_sequence=cursor,
            limit=1,
        )
        return cursor

    def replay_frames(
        self,
        *,
        team_id: str,
        run_id: str,
        after_sequence: int | None = None,
        last_event_id: str | None = None,
    ) -> Iterator[str]:
        cursor = parse_stream_cursor(
            last_event_id,
            route_run_id=run_id,
            after_sequence=after_sequence,
        )
        page = self._replay.list_events(
            team_id=team_id,
            run_id=run_id,
            after_sequence=cursor,
        )
        for event in page.events:
            payload = envelope_api_dict(event)
            yield encode_sse_event(
                run_id=run_id,
                sequence=event.sequence,
                event_type=str(payload["type"]),
                payload=payload,
            )

    def iter_sse(
        self,
        *,
        team_id: str,
        run_id: str,
        after_sequence: int | None = None,
        last_event_id: str | None = None,
        heartbeat_seconds: float = 15.0,
        wait_timeout_seconds: float = 1.0,
    ) -> Iterator[str]:
        cursor = parse_stream_cursor(
            last_event_id,
            route_run_id=run_id,
            after_sequence=after_sequence,
        )
        last_heartbeat = time.monotonic()
        while True:
            page = self._replay.list_events(
                team_id=team_id,
                run_id=run_id,
                after_sequence=cursor,
            )
            emitted = False
            for event in page.events:
                payload = envelope_api_dict(event)
                yield encode_sse_event(
                    run_id=run_id,
                    sequence=event.sequence,
                    event_type=str(payload["type"]),
                    payload=payload,
                )
                cursor = event.sequence
                emitted = True
            now = time.monotonic()
            if not emitted and now - last_heartbeat >= heartbeat_seconds:
                yield encode_keepalive()
                last_heartbeat = now
                # keepalive must not change cursor
            self._notifier.wait(timeout=wait_timeout_seconds)
