"""Source-addressed emotion episodes and deterministic afterglow recovery."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION

BASELINE_MOOD = {"label": "calm", "valence": 12, "arousal": 28, "stability": 72}


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


def _bounded_int(value: object, minimum: int, maximum: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def episode_from_life_event(
    event: Mapping[str, Any], *, now: datetime
) -> dict[str, Any] | None:
    event_id = str(event.get("eventId") or "").strip()
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    if (
        not event_id
        or str(event.get("kind") or "") != "activity_completed"
        or str(outcome.get("status") or "") != "succeeded"
    ):
        return None
    kind = str(event.get("activityKind") or "").strip().lower()
    default_delta = 8 if kind in {"social", "creative", "learning", "exercise"} else 4
    valence_delta = _bounded_int(outcome.get("moodDelta"), -40, 40, default_delta)
    intensity = max(8, min(100, abs(valence_delta) * 2 + 12))
    duration_hours = max(2, min(16, 2 + intensity // 8))
    occurred = _parse(event.get("occurredAt")) or now.astimezone(timezone.utc)
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:20]
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "episodeId": f"affect-{digest}",
        "sourceEventId": event_id,
        "targetId": str(event.get("targetId") or "self")[:160],
        "valenceDelta": valence_delta,
        "arousalDelta": min(20, max(-12, abs(valence_delta) // 3)),
        "intensity": intensity,
        "confidence": 100,
        "status": "active",
        "occurredAt": _iso(occurred),
        "recoverBy": _iso(occurred + timedelta(hours=duration_hours)),
    }


def episode_from_relationship_event(
    event: Mapping[str, Any], *, now: datetime
) -> dict[str, Any] | None:
    event_id = str(event.get("eventId") or "").strip()
    occurred = _parse(event.get("occurredAt")) or now.astimezone(timezone.utc)
    if not event_id:
        return None
    kind = str(event.get("kind") or "interaction").lower()
    combined = _bounded_int(event.get("intimacyDelta"), -8, 8) + _bounded_int(
        event.get("trustDelta"), -8, 8
    )
    if any(token in kind for token in ("conflict", "争执", "拒绝")):
        combined = min(combined, -10)
    elif any(token in kind for token in ("apology", "repair", "道歉", "修复")):
        combined = max(combined, 6)
    valence_delta = _bounded_int(round(combined / 2), -20, 20)
    intensity = max(8, min(60, abs(combined) * 3))
    duration_hours = max(2, min(12, 2 + intensity // 8))
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:20]
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "episodeId": f"affect-{digest}",
        "sourceEventId": event_id,
        "targetId": str(event.get("targetId") or "user")[:160],
        "valenceDelta": valence_delta,
        "arousalDelta": min(16, abs(combined) // 2),
        "intensity": intensity,
        "confidence": 100,
        "status": "active",
        "occurredAt": _iso(occurred),
        "recoverBy": _iso(occurred + timedelta(hours=duration_hours)),
    }


def project_affect(
    episodes: list[Mapping[str, Any]],
    *,
    now: datetime,
    baseline_mood: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc)
    source_baseline = baseline_mood if isinstance(baseline_mood, Mapping) else BASELINE_MOOD
    normalized_baseline = {
        "label": str(source_baseline.get("label") or BASELINE_MOOD["label"])[:40],
        "valence": _bounded_int(
            source_baseline.get("valence"), -100, 100, int(BASELINE_MOOD["valence"])
        ),
        "arousal": _bounded_int(
            source_baseline.get("arousal"), 0, 100, int(BASELINE_MOOD["arousal"])
        ),
        "stability": _bounded_int(
            source_baseline.get("stability"), 0, 100, int(BASELINE_MOOD["stability"])
        ),
    }
    valence = float(normalized_baseline["valence"])
    arousal = float(normalized_baseline["arousal"])
    stability = float(normalized_baseline["stability"])
    active_ids: list[str] = []
    recovered_ids: list[str] = []
    source_ids: list[str] = []
    seen: set[str] = set()
    for episode in sorted(episodes, key=lambda item: str(item.get("occurredAt") or "")):
        episode_id = str(episode.get("episodeId") or "").strip()
        if not episode_id or episode_id in seen:
            continue
        seen.add(episode_id)
        occurred = _parse(episode.get("occurredAt"))
        recover_by = _parse(episode.get("recoverBy"))
        if occurred is None or recover_by is None or recover_by <= occurred:
            continue
        if current >= recover_by:
            recovered_ids.append(episode_id)
            continue
        if current < occurred:
            continue
        remaining = max(0.0, min(1.0, (recover_by - current) / (recover_by - occurred)))
        valence += _bounded_int(episode.get("valenceDelta"), -40, 40) * remaining
        arousal += _bounded_int(episode.get("arousalDelta"), -20, 20) * remaining
        stability -= _bounded_int(episode.get("intensity"), 0, 100) * remaining / 8
        active_ids.append(episode_id)
        source_id = str(episode.get("sourceEventId") or "").strip()
        if source_id:
            source_ids.append(source_id)
    mood_valence = max(-100, min(100, round(valence)))
    mood_arousal = max(0, min(100, round(arousal)))
    mood_stability = max(0, min(100, round(stability)))
    if not active_ids:
        label = str(normalized_baseline["label"])
        if mood_valence <= -15:
            expression_tier = "contained"
        elif mood_valence >= 30:
            expression_tier = "warm"
        else:
            expression_tier = "natural"
    elif mood_valence <= -15:
        label, expression_tier = "low", "contained"
    elif mood_valence >= 30:
        label, expression_tier = "bright", "warm"
    else:
        label, expression_tier = "calm", "natural"
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "baselineMood": normalized_baseline,
        "mood": {
            "label": label,
            "valence": mood_valence,
            "arousal": mood_arousal,
            "stability": mood_stability,
            "causeEventIds": list(dict.fromkeys(source_ids))[-8:],
            "updatedAt": _iso(current),
        },
        "expressionTier": expression_tier,
        "activeEpisodeIds": active_ids,
        "recoveredEpisodeIds": recovered_ids,
        "updatedAt": _iso(current),
    }


__all__ = [
    "BASELINE_MOOD",
    "episode_from_life_event",
    "episode_from_relationship_event",
    "project_affect",
]
