"""Shared invariants for NodeRun execution transition modules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class NodeExecutionError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_event(record: dict[str, Any], **payload: Any) -> dict[str, Any]:
    events = list(record.get("events") or [])
    return {
        "eventId": f"evt-{uuid.uuid4().hex[:10]}",
        "sequence": int(events[-1].get("sequence") or 0) + 1 if events else 1,
        "occurredAt": iso(utc_now()),
        "runId": record["runId"],
        "threadId": record["threadId"],
        **payload,
    }


def latest_node_run(record: dict[str, Any], node_id: str) -> dict[str, Any]:
    matches = [
        item for item in record.get("nodeRuns") or [] if item.get("nodeId") == node_id
    ]
    if not matches:
        raise NodeExecutionError(
            f"node is not scheduled: {node_id}",
            code="node_not_scheduled",
        )
    return max(matches, key=lambda item: int(item.get("attempt") or 0))


def replace_by_id(
    items: list[dict[str, Any]],
    key: str,
    value: str,
    replacement: dict[str, Any],
) -> None:
    for index, item in enumerate(items):
        if str(item.get(key) or "") == value:
            items[index] = replacement
            return
    raise NodeExecutionError(
        f"record not found: {key}={value}",
        code="record_not_found",
    )
