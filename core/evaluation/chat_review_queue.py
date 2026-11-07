# -*- coding: utf-8 -*-
"""Chat 候选审核队列。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


logger = logging.getLogger(__name__)

LEGACY_STATUS_MAP = {
    "approved": "positive",
    "rejected": "discard",
    "discarded": "discard",
}
_REVIEW_ITEMS_CACHE: Dict[Path, Tuple[Tuple[int, int], List[Dict[str, Any]]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_review_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "pending"
    return LEGACY_STATUS_MAP.get(normalized, normalized)


def append_queue_event(queue_path: Path, payload: Dict[str, Any]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _REVIEW_ITEMS_CACHE.pop(queue_path.resolve(), None)


def append_review_queue_candidate(candidate_payload: Dict[str, Any], queue_path: Path) -> None:
    append_queue_event(
        queue_path,
        {
            "event": "candidate",
            "timestamp": _now_iso(),
            **candidate_payload,
        },
    )


def append_review_decision(
    candidate_id: str,
    *,
    status: str,
    reviewer_note: str,
    queue_path: Path,
    extra: Dict[str, Any] | None = None,
) -> None:
    append_queue_event(
        queue_path,
        {
            "event": "decision",
            "timestamp": _now_iso(),
            "candidate_id": candidate_id,
            "status": status,
            "reviewer_note": reviewer_note or "",
            **(extra or {}),
        },
    )


def read_queue_events_with_health(queue_path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """Read queue events, skipping corrupt lines instead of failing the read.

    Returns ``(events, corrupt_line_count)`` where the count covers lines that
    were not valid UTF-8 or not parseable JSON. A single corrupt line must not
    turn queue/stats reads into server errors; it is isolated and reported so
    the remaining records still aggregate.
    """
    if not queue_path.exists():
        return [], 0
    events: List[Dict[str, Any]] = []
    corrupt_lines = 0
    try:
        raw_lines = queue_path.read_bytes().splitlines()
    except OSError:
        return [], 0
    for raw_line in raw_lines:
        try:
            text = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            corrupt_lines += 1
            continue
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            corrupt_lines += 1
            continue
        if isinstance(payload, dict):
            events.append(payload)
    if corrupt_lines:
        logger.warning(
            "chat_review_queue corrupt lines skipped path=%s skippedLines=%d",
            queue_path,
            corrupt_lines,
        )
    return events, corrupt_lines


def iter_queue_events(queue_path: Path) -> Iterable[Dict[str, Any]]:
    events, _ = read_queue_events_with_health(queue_path)
    return events


def queue_corrupt_line_count(queue_path: Path) -> int:
    """Return the number of corrupt lines a fresh queue read would skip."""
    _, corrupt_lines = read_queue_events_with_health(queue_path)
    return corrupt_lines


def load_review_items(queue_path: Path) -> List[Dict[str, Any]]:
    cache_key = queue_path.resolve()
    try:
        stat = cache_key.stat()
    except FileNotFoundError:
        _REVIEW_ITEMS_CACHE.pop(cache_key, None)
        return []
    cache_signature = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _REVIEW_ITEMS_CACHE.get(cache_key)
    if cached and cached[0] == cache_signature:
        return [dict(item) for item in cached[1]]

    state: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for event in iter_queue_events(cache_key):
        candidate_id = str(event.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        if event.get("event") == "candidate":
            candidate = dict(event)
            candidate["status"] = normalize_review_status(candidate.get("status"))
            candidate.setdefault("reviewer_note", "")
            if candidate_id not in state:
                order.append(candidate_id)
            state[candidate_id] = candidate
            continue

        current = state.setdefault(candidate_id, {"candidate_id": candidate_id})
        current["status"] = normalize_review_status(event.get("status") or current.get("status") or "pending")
        current["reviewer_note"] = str(event.get("reviewer_note") or "")
        current["reviewed_at"] = str(event.get("timestamp") or "")
        for key, value in event.items():
            if key not in {"event", "timestamp", "candidate_id", "status", "reviewer_note"}:
                current[key] = value
        if candidate_id not in order:
            order.append(candidate_id)

    items = [state[item_id] for item_id in order if item_id in state]
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    _REVIEW_ITEMS_CACHE[cache_key] = (cache_signature, [dict(item) for item in items])
    return [dict(item) for item in items]


def list_review_items(queue_path: Path, *, status: str | None = None) -> List[Dict[str, Any]]:
    items = load_review_items(queue_path)
    if status is None:
        return items
    normalized = normalize_review_status(status)
    return [item for item in items if str(item.get("status") or "").strip().lower() == normalized]


def get_review_item(candidate_id: str, queue_path: Path) -> Dict[str, Any] | None:
    normalized = str(candidate_id or "").strip()
    if not normalized:
        return None
    for item in load_review_items(queue_path):
        if item.get("candidate_id") == normalized:
            return item
    return None


__all__ = [
    "append_queue_event",
    "append_review_decision",
    "append_review_queue_candidate",
    "get_review_item",
    "iter_queue_events",
    "list_review_items",
    "load_review_items",
    "normalize_review_status",
    "queue_corrupt_line_count",
    "read_queue_events_with_health",
]
