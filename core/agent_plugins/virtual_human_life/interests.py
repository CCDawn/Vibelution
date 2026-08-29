"""Outcome-backed interests and practice projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION

_LABELS = {
    "reading": "阅读",
    "news": "新闻探索",
    "news_exploration": "新闻探索",
    "creative": "创作",
    "skill_practice": "技能练习",
    "learning": "学习",
    "study": "学习",
}
_VERIFIED_OUTCOME_KINDS = {
    "verified_tool_outcome",
    "artifact_created",
    "reading_completed",
    "news_explored",
    "skill_practiced",
    "verified",
}


def _bounded_int(value: object, minimum: int, maximum: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def project_interests(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Project interests only from idempotent, verified completed outcomes."""

    processed: list[str] = []
    items: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("eventId") or "").strip()
        outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
        interest_key = str(
            event.get("activityKind") or event.get("interestKey") or ""
        ).strip().lower()[:80]
        if (
            not event_id
            or event_id in processed
            or interest_key not in _LABELS
            or str(event.get("kind") or "") != "activity_completed"
            or str(outcome.get("status") or "") != "succeeded"
            or str(outcome.get("kind") or "") not in _VERIFIED_OUTCOME_KINDS
        ):
            continue
        processed.append(event_id)
        item = items.setdefault(
            interest_key,
            {
                "interestKey": interest_key,
                "label": _LABELS[interest_key],
                "experience": 0,
                "level": 1,
                "completedCount": 0,
                "lastOutcomeSummary": "",
                "lastPracticedAt": "",
                "sourceEventIds": [],
            },
        )
        salience = _bounded_int(outcome.get("salienceScore"), 0, 100, 50)
        item["experience"] += 6 + salience // 30
        item["level"] = 1 + item["experience"] // 25
        item["completedCount"] += 1
        item["lastOutcomeSummary"] = str(outcome.get("summary") or "").strip()[:300]
        item["lastPracticedAt"] = str(event.get("occurredAt") or "")
        item["sourceEventIds"].append(event_id)
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "items": sorted(items.values(), key=lambda item: item["interestKey"]),
        "processedEventIds": processed,
    }


__all__ = ["project_interests"]
