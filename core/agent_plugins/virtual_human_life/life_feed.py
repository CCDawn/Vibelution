"""Read-only local life feed derived from durable life facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .life_provenance import event_provenance


def _sources(value: object) -> list[str]:
    return list(
        dict.fromkeys(
            str(item).strip()[:200]
            for item in list(value or [])
            if str(item).strip()
        )
    )[:16]


def _linked_source_kind(source_ids: Sequence[str], sources: Mapping[str, str]) -> str:
    kinds = {sources.get(item, "unknown") for item in source_ids}
    return next(iter(kinds)) if len(kinds) == 1 else "unknown"


def build_life_feed(
    *,
    events: Sequence[Mapping[str, Any]],
    diary_entries: Sequence[Mapping[str, Any]],
    artifact_receipts: Sequence[Mapping[str, Any]],
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Project supplied experiences with explicit sources, without writing back."""

    rows: list[dict[str, Any]] = []
    lived_event_ids: set[str] = set()
    source_kinds: dict[str, str] = {}
    event_summaries: set[tuple[frozenset[str], str]] = set()
    for event in events:
        outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
        event_id = str(event.get("eventId") or "").strip()[:200]
        if (
            not event_id
            or str(event.get("kind") or "") != "activity_completed"
            or str(outcome.get("status") or "") != "succeeded"
        ):
            continue
        lived_event_ids.add(event_id)
        source_kinds[event_id] = event_provenance(event)
        summary = str(outcome.get("summary") or "").strip()
        event_summaries.add((frozenset([event_id]), summary))
        rows.append(
            {
                "feedId": f"life-event:{event_id}",
                "kind": "life_event",
                "title": str(event.get("title") or "生活片段").strip()[:160],
                "summary": summary[:600],
                "occurredAt": str(event.get("occurredAt") or ""),
                "sourceEventIds": [event_id],
                "sourceKind": source_kinds[event_id],
            }
        )
    for entry in diary_entries:
        all_source_ids = _sources(entry.get("sourceEventIds"))
        source_ids = [item for item in all_source_ids if item in lived_event_ids]
        if not source_ids:
            continue
        diary_id = str(entry.get("diaryEntryId") or "").strip()[:200]
        if not diary_id:
            continue
        content = str(entry.get("content") or "").strip()
        if (frozenset(all_source_ids), content) in event_summaries:
            continue
        rows.append(
            {
                "feedId": f"diary:{diary_id}",
                "kind": "diary",
                "title": str(entry.get("title") or "日记").strip()[:160],
                "summary": content[:600],
                "occurredAt": str(entry.get("writtenAt") or ""),
                "sourceEventIds": source_ids,
                "sourceKind": _linked_source_kind(all_source_ids, source_kinds),
            }
        )
    for receipt in artifact_receipts:
        all_source_ids = _sources(receipt.get("sourceEventIds"))
        source_ids = [item for item in all_source_ids if item in lived_event_ids]
        artifact_id = str(receipt.get("artifactId") or "").strip()[:200]
        if (
            not artifact_id
            or not source_ids
            or str(receipt.get("status") or "") != "succeeded"
        ):
            continue
        rows.append(
            {
                "feedId": f"artifact:{artifact_id}",
                "kind": "artifact",
                "title": str(receipt.get("title") or "生活作品").strip()[:160],
                "summary": str(receipt.get("summary") or "").strip()[:600],
                "occurredAt": str(receipt.get("createdAt") or ""),
                "sourceEventIds": source_ids,
                "sourceKind": _linked_source_kind(all_source_ids, source_kinds),
                "artifactKind": str(receipt.get("kind") or "").strip()[:40],
                "localRef": str(receipt.get("localRef") or "").strip()[:400],
            }
        )
    rows.sort(key=lambda item: (str(item.get("occurredAt") or ""), item["feedId"]), reverse=True)
    return rows[: max(1, min(100, int(limit or 24)))]


__all__ = ["build_life_feed"]
