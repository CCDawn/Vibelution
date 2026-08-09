"""SSE projection over the canonical durable WorkflowRun event list."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any


def _cursor(record: dict[str, Any]) -> int:
    return max(
        (int(item.get("sequence") or 0) for item in record.get("events") or []),
        default=0,
    )


def _frame(*, frame_id: int, event: str, data: dict[str, Any]) -> str:
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"id: {frame_id}\nevent: {event}\ndata: {encoded}\n\n"


def _bounded_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": record.get("status"),
        "runVersion": record.get("runVersion"),
        "runtimeCurrentNodeIds": list(record.get("runtimeCurrentNodeIds") or []),
        "bindingSnapshotIds": [
            str(item.get("snapshotId") or "")
            for item in record.get("bindingSnapshots") or []
        ],
        "handoffStates": [
            {
                "handoffId": item.get("handoffId"),
                "status": item.get("status"),
            }
            for item in (record.get("handoffs") or [])[-100:]
        ],
        "pendingHumanTaskIds": [
            str(item.get("taskId") or "")
            for item in record.get("humanTasks") or []
            if item.get("status") == "pending"
        ],
        "checkpointId": (record.get("langGraph") or {}).get("checkpointId"),
    }


def initial_sse_frames(record: dict[str, Any]) -> list[str]:
    cursor = _cursor(record)
    return [
        _frame(
            frame_id=cursor,
            event="snapshot",
            data={
                "runId": record["runId"],
                "cursor": cursor,
                "snapshot": _bounded_snapshot(record),
            },
        )
    ]


def replay_sse_frames(
    record: dict[str, Any],
    *,
    after_sequence: int,
) -> list[str]:
    seen_event_ids: set[str] = set()
    seen_sequences: set[int] = set()
    frames: list[str] = []
    events = sorted(
        (dict(item) for item in record.get("events") or []),
        key=lambda item: int(item.get("sequence") or 0),
    )
    for event in events:
        sequence = int(event.get("sequence") or 0)
        event_id = str(event.get("eventId") or "")
        if sequence <= after_sequence:
            continue
        if sequence in seen_sequences or (event_id and event_id in seen_event_ids):
            continue
        seen_sequences.add(sequence)
        if event_id:
            seen_event_ids.add(event_id)
        frames.append(
            _frame(
                frame_id=sequence,
                event=str(event.get("type") or "WorkflowEvent"),
                data=event,
            )
        )
    return frames


def parse_last_event_id(value: str | None) -> int:
    if value is None or not value.strip():
        return 0
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError("Last-Event-ID must be a non-negative sequence") from exc
    if parsed < 0:
        raise ValueError("Last-Event-ID must be a non-negative sequence")
    return parsed


def iter_workflow_sse(
    get_record: Callable[[], dict[str, Any]],
    *,
    last_event_id: str | None,
    poll_interval_seconds: float = 0.5,
    heartbeat_seconds: float = 15.0,
) -> Iterator[str]:
    """Yield initial snapshot or replay, then live deltas from the same event source."""
    cursor = parse_last_event_id(last_event_id)
    record = get_record()
    if cursor == 0:
        frames = initial_sse_frames(record)
        cursor = _cursor(record)
    else:
        frames = replay_sse_frames(record, after_sequence=cursor)
    for frame in frames:
        yield frame
        first_line = frame.splitlines()[0]
        cursor = max(cursor, int(first_line.removeprefix("id: ")))

    last_heartbeat = time.monotonic()
    while True:
        record = get_record()
        deltas = replay_sse_frames(record, after_sequence=cursor)
        for frame in deltas:
            yield frame
            first_line = frame.splitlines()[0]
            cursor = max(cursor, int(first_line.removeprefix("id: ")))
        now = time.monotonic()
        if not deltas and now - last_heartbeat >= heartbeat_seconds:
            yield f": heartbeat {cursor}\n\n"
            last_heartbeat = now
        time.sleep(max(0.05, poll_interval_seconds))
