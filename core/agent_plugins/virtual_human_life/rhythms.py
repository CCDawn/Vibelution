"""Independent circadian rhythm and non-medical life-need projections.

Rhythms are a plugin projection, not a medical model and not a replacement for
the Agent's Persona or conversation runtime.  Needs are bounded unmet-drive
signals used as planning hints.  Chronotype adaptation is deliberately
conservative: only successful completed sleep/rest experiences on distinct days
count, and at least three consistent observations are required before the
long-term profile changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
NEED_NAMES = ("sleep", "rest", "nourishment", "social", "movement", "focus")
_DEFAULT_NEEDS = {
    "sleep": {"level": 24, "ratePerHour": 4, "recoveryPerActivity": 42},
    "rest": {"level": 18, "ratePerHour": 2, "recoveryPerActivity": 28},
    "nourishment": {"level": 30, "ratePerHour": 1, "recoveryPerActivity": 34},
    "social": {"level": 34, "ratePerHour": 1, "recoveryPerActivity": 30},
    "movement": {"level": 22, "ratePerHour": 1, "recoveryPerActivity": 26},
    "focus": {"level": 16, "ratePerHour": 1, "recoveryPerActivity": 22},
}


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _parse(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _zone(name: str | tzinfo | None) -> tzinfo:
    if isinstance(name, tzinfo):
        return name
    normalized = str(name or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        if normalized == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise ValueError(f"Unknown timezone: {normalized}") from None


def _bounded(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _chronotype_label(value: object) -> str:
    normalized = str(value or "balanced").strip().lower()
    return normalized if normalized in {"morning", "balanced", "evening"} else "balanced"


def _classify_sleep_hour(local_hour: float) -> str:
    # A completed sleep starting between 04:00 and 10:00 is a late/after-dawn
    # signal.  20:00–02:00 is ordinary night sleep; everything else is treated
    # as a nap/ambiguous observation and does not adapt chronotype.
    if 4 <= local_hour < 10:
        return "late"
    if local_hour >= 20 or local_hour < 2:
        return "night"
    if 10 <= local_hour < 18:
        return "nap"
    return "early"


def _activity_kind(event: Mapping[str, Any]) -> str:
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    return str(
        event.get("activityKind")
        or outcome.get("activityKind")
        or outcome.get("kind")
        or event.get("title")
        or ""
    ).strip().lower()


def _is_kind(kind: str, words: tuple[str, ...]) -> bool:
    return any(word in kind for word in words)


def default_rhythm_projection(
    *,
    now: datetime,
    timezone_name: str = "Asia/Shanghai",
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an explicit baseline rhythm projection."""

    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    config_map = config if isinstance(config, Mapping) else {}
    configured_label = _chronotype_label(
        config_map.get("chronotype") if not isinstance(config_map.get("chronotype"), Mapping) else (config_map.get("chronotype") or {}).get("label")
    )
    has_explicit_chronotype = bool(
        str(config_map.get("chronotype") or "").strip()
        or isinstance(config_map.get("chronotype"), Mapping)
    )
    needs = deepcopy(_DEFAULT_NEEDS)
    raw_needs = config_map.get("needs") if isinstance(config_map.get("needs"), Mapping) else {}
    for name in NEED_NAMES:
        raw = raw_needs.get(name) if isinstance(raw_needs, Mapping) else {}
        if isinstance(raw, Mapping):
            needs[name]["level"] = _bounded(raw.get("level"), 0, 100, needs[name]["level"])
            needs[name]["ratePerHour"] = _bounded(raw.get("ratePerHour"), 0, 12, needs[name]["ratePerHour"])
            needs[name]["recoveryPerActivity"] = _bounded(raw.get("recoveryPerActivity"), 1, 100, needs[name]["recoveryPerActivity"])
    return {
        "schemaVersion": 1,
        "timezone": str(timezone_name or "Asia/Shanghai"),
        "chronotype": {
            "label": configured_label,
            "evidenceCount": 0,
            "confidence": 100 if has_explicit_chronotype else 0,
            "adaptationStatus": "configured" if has_explicit_chronotype else "stable",
            "patternCounts": {"early": 0, "late": 0, "night": 0, "nap": 0},
            "observations": [],
            "lastEvidenceAt": "",
        },
        "circadian": {
            "localHour": 0,
            "phase": "night",
            "energyFactor": 0.55,
            "preferredSleepStart": "23:00",
            "preferredWakeTime": "07:00",
            "updatedAt": _iso(current),
        },
        "needs": needs,
        "processedEventIds": [],
        "updatedAt": _iso(current),
    }


def _project_circadian(
    projection: dict[str, Any],
    *,
    now: datetime,
    timezone_name: str | tzinfo,
) -> None:
    local = now.astimezone(_zone(timezone_name))
    hour = local.hour + local.minute / 60.0
    label = _chronotype_label(
        (projection.get("chronotype") or {}).get("label") if isinstance(projection.get("chronotype"), Mapping) else "balanced"
    )
    if label == "morning":
        wake, sleep = 6.5, 22.0
    elif label == "evening":
        wake, sleep = 9.0, 0.5
    else:
        wake, sleep = 7.5, 23.0
    distance_from_peak = min(abs(hour - wake), abs(hour - (wake + 24)))
    if distance_from_peak <= 3:
        phase = "morning"
        factor = 0.78 + (3 - distance_from_peak) * 0.07
    elif hour >= 22 or hour < 5:
        phase = "sleep_window"
        factor = 0.38
    elif hour >= 18:
        phase = "evening"
        factor = 0.70
    else:
        phase = "day"
        factor = 0.92
    circadian = projection.setdefault("circadian", {})
    circadian.update(
        {
            "localHour": round(hour, 2),
            "phase": phase,
            "energyFactor": round(max(0.25, min(1.0, factor)), 2),
            "preferredSleepStart": f"{int(sleep) % 24:02d}:{int((sleep % 1) * 60):02d}",
            "preferredWakeTime": f"{int(wake) % 24:02d}:{int((wake % 1) * 60):02d}",
            "updatedAt": _iso(now),
        }
    )


def project_rhythm_state(
    projection: Mapping[str, Any],
    *,
    now: datetime,
    timezone_name: str | tzinfo | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance needs by elapsed time and refresh the independent circadian view."""

    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    result = deepcopy(dict(projection))
    zone_name = timezone_name or result.get("timezone") or "Asia/Shanghai"
    result["timezone"] = str(zone_name)
    anchor = _parse(result.get("updatedAt"))
    if anchor is not None and current > anchor:
        elapsed_hours = min(72.0, max(0.0, (current - anchor).total_seconds() / 3600.0))
        whole_hours = int(elapsed_hours)
        if whole_hours:
            needs = result.setdefault("needs", {})
            for name in NEED_NAMES:
                item = needs.setdefault(name, deepcopy(_DEFAULT_NEEDS[name]))
                rate = _bounded(item.get("ratePerHour"), 0, 12, _DEFAULT_NEEDS[name]["ratePerHour"])
                item["level"] = _bounded(item.get("level"), 0, 100, 0) + whole_hours * rate
                item["level"] = max(0, min(100, item["level"]))
            result["updatedAt"] = _iso(anchor + timedelta(hours=whole_hours))
    if anchor is None or current >= (anchor or current):
        result["updatedAt"] = _iso(current)
    if isinstance(config, Mapping):
        explicit = config.get("chronotype")
        if explicit is not None:
            label = explicit.get("label") if isinstance(explicit, Mapping) else explicit
            normalized = _chronotype_label(label)
            chronotype = result.setdefault("chronotype", {})
            chronotype.update({"label": normalized, "adaptationStatus": "configured", "confidence": 100})
    _project_circadian(result, now=current, timezone_name=_zone(zone_name))
    return result


def apply_completed_activity_to_rhythm(
    projection: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply one successful completed activity to needs and rhythm evidence."""

    event_time = _parse(event.get("occurredAt"))
    effective_now = now or event_time or datetime.now(UTC)
    result = project_rhythm_state(projection, now=effective_now)
    event_id = str(event.get("eventId") or "").strip()
    processed = [str(item).strip() for item in list(result.get("processedEventIds") or []) if str(item).strip()]
    if event_id and event_id in processed:
        return result
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    if str(event.get("kind") or "") != "activity_completed" or str(outcome.get("status") or "") != "succeeded":
        return result
    kind = _activity_kind(event)
    recovery: dict[str, int] = {}
    if _is_kind(kind, ("sleep", "睡")):
        recovery = {"sleep": 48, "rest": 36, "focus": 8}
    elif _is_kind(kind, ("rest", "recovery", "休息", "午觉")):
        recovery = {"sleep": 20, "rest": 35, "focus": 6}
    elif _is_kind(kind, ("meal", "food", "cooking", "早餐", "午饭", "晚饭")):
        recovery = {"nourishment": 42}
    elif _is_kind(kind, ("social", "conversation", "relationship", "聊天", "朋友", "聚会")):
        recovery = {"social": 38}
    elif _is_kind(kind, ("exercise", "walk", "movement", "运动", "散步", "伸展")):
        recovery = {"movement": 36, "rest": -4}
    elif _is_kind(kind, ("creative", "learning", "focus", "study", "创作", "学习", "阅读")):
        recovery = {"focus": 30}
    needs = result.setdefault("needs", {})
    for name, amount in recovery.items():
        item = needs.setdefault(name, deepcopy(_DEFAULT_NEEDS[name]))
        item["level"] = max(0, min(100, _bounded(item.get("level"), 0, 100, 0) - amount))
    if event_id:
        result["processedEventIds"] = [*processed, event_id][-512:]

    # Only completed sleep/rest events produce chronotype observations.  The
    # event timestamp is authoritative; an injected ``now`` merely controls
    # projection time and does not turn an unfinished activity into evidence.
    if _is_kind(kind, ("sleep", "rest", "recovery", "睡", "休息")):
        observed = event_time or effective_now
        local = observed.astimezone(_zone(result.get("timezone") or "Asia/Shanghai"))
        classification = _classify_sleep_hour(local.hour + local.minute / 60.0)
        chronotype = result.setdefault("chronotype", {})
        observations = [item for item in list(chronotype.get("observations") or []) if isinstance(item, Mapping)]
        observed_date = local.date().isoformat()
        if not any(str(item.get("date") or "") == observed_date for item in observations):
            observations.append(
                {
                    "date": observed_date,
                    "classification": classification,
                    "eventId": event_id,
                    "observedAt": _iso(observed),
                }
            )
        pattern_counts = {str(key): int(value or 0) for key, value in dict(chronotype.get("patternCounts") or {}).items()}
        pattern_counts.setdefault(classification, 0)
        # Recompute counts from distinct-day evidence rather than incrementing
        # on retries, which keeps the projection replay-safe.
        for key in ("early", "late", "night", "nap"):
            pattern_counts[key] = sum(1 for item in observations if str(item.get("classification") or "") == key)
        observations = observations[-64:]
        chronotype["observations"] = observations
        chronotype["patternCounts"] = pattern_counts
        chronotype["evidenceCount"] = len(observations)
        chronotype["lastEvidenceAt"] = _iso(observed)
        late_count = pattern_counts.get("late", 0)
        early_count = pattern_counts.get("early", 0)
        if late_count >= 3 and late_count > early_count:
            chronotype.update({"label": "evening", "adaptationStatus": "adapted", "confidence": min(95, 50 + late_count * 10)})
        elif early_count >= 3 and early_count > late_count:
            chronotype.update({"label": "morning", "adaptationStatus": "adapted", "confidence": min(95, 50 + early_count * 10)})
        elif str(chronotype.get("adaptationStatus") or "stable") != "configured":
            chronotype["adaptationStatus"] = "stable"
    _project_circadian(
        result,
        now=effective_now.astimezone(UTC),
        timezone_name=_zone(result.get("timezone") or "Asia/Shanghai"),
    )
    # A replayed historical event must never move the projection clock
    # backwards; the needs update is still applied exactly once.
    previous_updated = _parse(projection.get("updatedAt"))
    result["updatedAt"] = _iso(max(previous_updated, effective_now) if previous_updated else effective_now)
    return result


def rhythm_constraints(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded planning hints without creating a second schedule owner."""

    needs = projection.get("needs") if isinstance(projection.get("needs"), Mapping) else {}
    levels = {
        name: _bounded((needs.get(name) or {}).get("level") if isinstance(needs.get(name), Mapping) else 0, 0, 100, 0)
        for name in NEED_NAMES
    }
    return {
        "chronotype": _chronotype_label((projection.get("chronotype") or {}).get("label") if isinstance(projection.get("chronotype"), Mapping) else "balanced"),
        "circadianPhase": str((projection.get("circadian") or {}).get("phase") or "day"),
        "needs": levels,
        "highPriorityNeeds": [name for name, level in sorted(levels.items(), key=lambda item: item[1], reverse=True) if level >= 60][:3],
    }


__all__ = [
    "NEED_NAMES",
    "apply_completed_activity_to_rhythm",
    "default_rhythm_projection",
    "project_rhythm_state",
    "rhythm_constraints",
]
