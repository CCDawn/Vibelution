"""Replayable relationship-event ledger with bounded stages and repair."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamp(value: object, minimum: int, maximum: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def make_relationship_event(
    *,
    event_id: str,
    target_id: str,
    kind: str,
    intimacy_delta: int,
    trust_delta: int,
    occurred_at: datetime,
    source_turn_id: str = "",
) -> dict[str, Any]:
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "eventId": str(event_id or "").strip()[:200],
        "targetId": str(target_id or "").strip()[:160],
        "kind": str(kind or "interaction").strip()[:120],
        "intimacyDelta": _clamp(intimacy_delta, -8, 8),
        "trustDelta": _clamp(trust_delta, -8, 8),
        "occurredAt": _iso(occurred_at),
        "localDate": occurred_at.date().isoformat(),
        "sourceTurnId": str(source_turn_id or "").strip()[:200],
    }


def _relationship_stage(intimacy: int, trust: int, interactions: int) -> str:
    score = min(intimacy, trust)
    if interactions >= 12 and score >= 82:
        return "close"
    if interactions >= 5 and score >= 65:
        return "friend"
    return "getting_to_know"


def project_relationships(
    base_rows: list[Mapping[str, Any]],
    events: list[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Rebuild projections with per-event and per-local-day caps."""

    by_target: dict[str, dict[str, Any]] = {
        str(item.get("targetId") or ""): deepcopy(dict(item))
        for item in base_rows
        if str(item.get("targetId") or "").strip()
    }
    seen: set[str] = set()
    daily: dict[tuple[str, str], dict[str, int]] = {}
    last_event_at: dict[str, datetime] = {}
    for event in sorted(events, key=lambda item: str(item.get("occurredAt") or "")):
        event_id = str(event.get("eventId") or "").strip()
        target_id = str(event.get("targetId") or "").strip()
        occurred = _parse(event.get("occurredAt"))
        if not event_id or event_id in seen or not target_id or occurred is None:
            continue
        seen.add(event_id)
        row = by_target.setdefault(
            target_id,
            {
                "targetId": target_id,
                "kind": "user" if target_id == "user" else "person",
                "intimacy": 50,
                "trust": 50,
                "interactionCount": 0,
                "relationshipStage": "getting_to_know",
            },
        )
        local_date = str(event.get("localDate") or occurred.date().isoformat())
        budget = daily.setdefault((target_id, local_date), {"intimacy": 0, "trust": 0})
        raw_intimacy = _clamp(event.get("intimacyDelta"), -8, 8)
        raw_trust = _clamp(event.get("trustDelta"), -8, 8)
        allowed_intimacy = _clamp(raw_intimacy, -12 - budget["intimacy"], 12 - budget["intimacy"])
        allowed_trust = _clamp(raw_trust, -12 - budget["trust"], 12 - budget["trust"])
        budget["intimacy"] += allowed_intimacy
        budget["trust"] += allowed_trust
        row["intimacy"] = _clamp(int(row.get("intimacy") or 50) + allowed_intimacy, 0, 100, 50)
        row["trust"] = _clamp(int(row.get("trust") or 50) + allowed_trust, 0, 100, 50)
        row["interactionCount"] = max(0, int(row.get("interactionCount") or 0)) + 1
        row["lastInteractionKind"] = str(event.get("kind") or "interaction")[:120]
        row["lastInteractionAt"] = _iso(occurred)
        row["lastSourceEventId"] = event_id
        last_event_at[target_id] = occurred

    current = now.astimezone(timezone.utc)
    stage_rank = {"getting_to_know": 0, "friend": 1, "close": 2}
    for target_id, row in by_target.items():
        last_at = last_event_at.get(target_id) or _parse(row.get("lastInteractionAt"))
        if last_at is not None:
            quiet_days = max(0, (current - last_at).days - 14)
            decay = min(12, quiet_days // 14)
            if decay:
                row["intimacy"] = max(50, int(row.get("intimacy") or 50) - decay)
                row["trust"] = max(50, int(row.get("trust") or 50) - decay // 2)
        proposed = _relationship_stage(
            int(row.get("intimacy") or 50),
            int(row.get("trust") or 50),
            int(row.get("interactionCount") or 0),
        )
        previous = str(row.get("relationshipStage") or "getting_to_know")
        # Promotion is evidence based. Demotion requires a 15-point margin so
        # a single poor interaction cannot flip the relationship label.
        if stage_rank.get(proposed, 0) >= stage_rank.get(previous, 0):
            stage = proposed
        else:
            threshold = 82 if previous == "close" else 65
            stage = proposed if min(int(row["intimacy"]), int(row["trust"])) < threshold - 15 else previous
        row["relationshipStage"] = stage
        row["updatedAt"] = _iso(current)
    return sorted(by_target.values(), key=lambda item: str(item.get("targetId") or ""))


__all__ = ["make_relationship_event", "project_relationships"]
