"""Pure cursor and notification logic for bounded knowledge snapshots.

The runtime owns ACL-filtered snapshot loading and the AgentPerceptionStore
write boundary. This module only transforms the supplied snapshot and state.
"""
from __future__ import annotations

import hashlib
from typing import Any


MAX_KNOWLEDGE_BASES = 64
MAX_KNOWLEDGE_ITEMS_PER_BASE = 1_000
MAX_KNOWLEDGE_SNAPSHOT_ITEMS = 16_000
MAX_KNOWLEDGE_FILE_BYTES = 5 * 1024 * 1024
MAX_NOTIFICATIONS = 500
MAX_KNOWLEDGE_CANDIDATES = 100
MAX_RELEVANCE_CHARS = 4_000
_ALLOWED_NOTIFICATION_SOURCES = {"personal", "team", "knowledge", "projects"}


def apply_knowledge_snapshot(
    state: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: str,
    notification_mode: str,
    topics: list[Any],
) -> dict[str, int]:
    """Apply one complete snapshot to the caller's existing state object."""
    counters = {"basesScanned": 0, "changed": 0, "notified": 0, "suppressed": 0}
    cursors = dict(state.get("knowledgeCursors") or {})
    notifications = [row for row in state.get("notifications", []) if isinstance(row, dict)]
    first_baseline = not cursors
    by_base: dict[str, list[dict[str, Any]]] = {}
    for row in rows[:MAX_KNOWLEDGE_SNAPSHOT_ITEMS]:
        base_id = str(row.get("knowledgeBaseId") or "").strip()
        item_id = str(row.get("knowledgeItemId") or "").strip()
        if not base_id:
            continue
        base_rows = by_base.setdefault(base_id, [])
        if item_id:
            base_rows.append(row)

    next_cursors: dict[str, Any] = {}
    for base_id in sorted(by_base)[:MAX_KNOWLEDGE_BASES]:
        base_rows = sorted(
            by_base[base_id], key=lambda row: str(row.get("knowledgeItemId") or "")
        )[:MAX_KNOWLEDGE_ITEMS_PER_BASE]
        counters["basesScanned"] += 1
        old_cursor = cursors.get(base_id) if isinstance(cursors.get(base_id), dict) else {}
        old_items = old_cursor.get("items") if isinstance(old_cursor.get("items"), dict) else {}
        base_baseline = not isinstance(old_cursor.get("items"), dict)
        current_items: dict[str, dict[str, str]] = {}
        for row in base_rows:
            item_id = str(row.get("knowledgeItemId") or "")
            revision = str(row.get("revision") or "1")[:64]
            content_hash = str(row.get("contentHash") or row.get("contentSha256") or "")[:128]
            if not content_hash:
                content_hash = hashlib.sha256(str(row.get("content") or "").encode("utf-8")).hexdigest()
            current_items[item_id] = {"revision": revision, "contentHash": content_hash}
            previous = old_items.get(item_id) if isinstance(old_items.get(item_id), dict) else None
            changed = previous is None or (
                str(previous.get("revision") or "") != revision
                or str(previous.get("contentHash") or "") != content_hash
            )
            if first_baseline or base_baseline or not changed:
                continue
            counters["changed"] += 1
            notify = notification_mode == "all" or (
                notification_mode == "important" and _item_matches_topics(row, topics)
            )
            if not notify or notification_mode == "quiet":
                counters["suppressed"] += 1
                continue
            notification = {
                "notificationId": hashlib.sha256(f"{base_id}:{item_id}".encode("utf-8")).hexdigest()[:32],
                "knowledgeBaseId": base_id,
                "knowledgeItemId": item_id,
                "revision": revision,
                "contentHash": content_hash,
                "observedAt": now,
                "sessionId": "",
                "turnId": "",
                "delivered": False,
            }
            notification_source = _notification_source(row)
            if notification_source:
                notification["source"] = notification_source
            existing_index = next(
                (
                    index for index, old in enumerate(notifications)
                    if old.get("notificationId") == notification["notificationId"]
                    and not bool(old.get("delivered"))
                ),
                None,
            )
            if existing_index is None:
                notifications.append(notification)
            else:
                notifications[existing_index] = notification
            counters["notified"] += 1
        next_cursors[base_id] = {"items": current_items, "scannedAt": now}

    state["knowledgeCursors"] = next_cursors
    state["notifications"] = notifications[-MAX_NOTIFICATIONS:]
    state["suppressedNotificationCount"] = (
        int(state.get("suppressedNotificationCount") or 0) + counters["suppressed"]
    )
    scan = dict(state.get("knowledgeScan") or {})
    scan.update({
        "basesScanned": counters["basesScanned"],
        "pendingCount": sum(1 for row in state["notifications"] if not bool(row.get("delivered"))),
        "scannedAt": now,
    })
    state["knowledgeScan"] = scan
    candidates = []
    for row in notifications[-MAX_KNOWLEDGE_CANDIDATES:]:
        if bool(row.get("delivered")):
            continue
        candidate = {
            key: row[key]
            for key in ("knowledgeBaseId", "knowledgeItemId", "revision", "contentHash")
            if key in row
        }
        source = row.get("source")
        if isinstance(source, str) and source in _ALLOWED_NOTIFICATION_SOURCES:
            candidate["source"] = source
        candidates.append(candidate)
    state["pendingKnowledgeCandidates"] = candidates
    state["updatedAt"] = now
    return counters


def _item_matches_topics(item: dict[str, Any], topics: list[Any]) -> bool:
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("name") or ""),
            str(item.get("subject") or ""),
            str(item.get("content") or ""),
            " ".join(str(tag) for tag in list(item.get("tags") or [])[:32]),
        ]
    ).casefold()
    if not haystack:
        return False
    for topic in topics:
        normalized = " ".join(str(topic or "").casefold().split())
        if len(normalized) >= 2 and normalized in haystack:
            return True
        # Preserve a small deterministic Chinese-friendly token match without
        # sending knowledge bodies to a model or persisting them in runtime state.
        tokens = [
            part for part in normalized.replace("，", " ").replace("、", " ").replace("/", " ").split()
            if len(part) >= 2
        ]
        if tokens and any(token in haystack for token in tokens):
            return True
    return False


def _notification_source(row: dict[str, Any]) -> str:
    raw_sources = row.get("sources")
    if isinstance(raw_sources, list):
        sources = {str(value) for value in raw_sources if isinstance(value, str) and value in _ALLOWED_NOTIFICATION_SOURCES}
    elif isinstance(raw_sources, str) and raw_sources in _ALLOWED_NOTIFICATION_SOURCES:
        sources = {raw_sources}
    else:
        source = row.get("source")
        sources = {source} if isinstance(source, str) and source in _ALLOWED_NOTIFICATION_SOURCES else set()
    if "knowledge" in sources:
        # A knowledge item may be visible through overlapping team and
        # knowledge subscriptions; keep one stable public source label.
        return "knowledge"
    return next(iter(sources)) if len(sources) == 1 else ""


__all__ = [
    "MAX_KNOWLEDGE_BASES",
    "MAX_KNOWLEDGE_CANDIDATES",
    "MAX_KNOWLEDGE_FILE_BYTES",
    "MAX_KNOWLEDGE_ITEMS_PER_BASE",
    "MAX_KNOWLEDGE_SNAPSHOT_ITEMS",
    "MAX_NOTIFICATIONS",
    "MAX_RELEVANCE_CHARS",
    "apply_knowledge_snapshot",
]
