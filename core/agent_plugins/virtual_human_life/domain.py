"""Pure deterministic rules for the virtual-human-life domain.

The plugin owns persistence and orchestration, while this module keeps the
small, repeatable parts of the life simulation easy to test.  It deliberately
does not call an LLM, read files, or emit events.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def _clamp(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _event_text(event: Mapping[str, Any]) -> str:
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    return " ".join(
        part
        for part in (
            str(event.get("title") or "").strip(),
            str(outcome.get("summary") or "").strip(),
        )
        if part
    )


def compute_event_salience(event: Mapping[str, Any]) -> int:
    """Compute a bounded, explainable importance score for a completed event.

    Existing events may predate ``salienceScore``.  An explicit score remains
    authoritative (and is normalized); otherwise the score is derived from
    activity meaning, outcome detail, and whether the event was only simulated
    during restart recovery.  The rule is intentionally conservative so a
    routine heartbeat cannot flood long-term memory.
    """

    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    if str(event.get("kind") or "") != "activity_completed":
        return 0
    if str(outcome.get("status") or "") != "succeeded":
        return 0
    explicit = outcome.get("salienceScore")
    if explicit is not None and str(explicit).strip() != "":
        return _clamp(explicit, 0, 100, 0)

    text = _event_text(event)
    score = 28
    high_signal = (
        "创作",
        "项目",
        "学习",
        "技能",
        "阅读",
        "回顾",
        "想法",
        "突破",
        "第一次",
        "重要",
        "朋友",
        "聊天",
        "庆祝",
    )
    medium_signal = ("散步", "运动", "音乐", "日记", "整理", "早餐", "晚饭")
    if any(keyword in text for keyword in high_signal):
        score += 42
    elif any(keyword in text for keyword in medium_signal):
        score += 24
    if len(str(outcome.get("summary") or "").strip()) >= 18:
        score += 8
    if str(outcome.get("kind") or "") not in {"", "deterministic_simulation"}:
        score += 8
    if bool(event.get("simulatedAfterRestart")):
        score -= 8
    return _clamp(score, 0, 100, 0)


def has_normalized_salience(event: Mapping[str, Any], score: int) -> bool:
    """Return whether the event already carries the normalized derived score."""

    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    try:
        return int(outcome.get("salienceScore")) == int(score)
    except (TypeError, ValueError):
        return False


def _delta_from_outcome(outcome: Mapping[str, Any], key: str) -> int:
    # Model/tool supplied deltas are suggestions, never an unbounded state write.
    return _clamp(outcome.get(key), -20, 20, 0)


def _set_mood_label(state: dict[str, Any]) -> None:
    mood = state.get("mood") if isinstance(state.get("mood"), dict) else {}
    valence = _clamp(mood.get("valence"), -100, 100, 0)
    energy = _clamp(state.get("energy"), 0, 100, 70)
    if valence <= -25:
        label = "low"
    elif energy <= 22:
        label = "tired"
    elif valence >= 35:
        label = "happy"
    else:
        label = "calm"
    mood["label"] = label
    state["mood"] = mood


def evolve_state_for_time(
    state: Mapping[str, Any],
    *,
    now: datetime,
    baseline_valence: int = 12,
) -> dict[str, Any]:
    """Recover energy/social need and gently normalize mood since last evolution."""

    next_state = deepcopy(dict(state))
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    anchor = _parse_datetime(
        next_state.get("lastStateEvolutionAt")
        or next_state.get("lastHeartbeatAt")
        or next_state.get("updatedAt")
    )
    if anchor is None:
        # An empty/malformed anchor is initialized explicitly.  ``setdefault``
        # would preserve a present-but-empty legacy value and make every later
        # heartbeat lose its elapsed-time reference.
        next_state["lastStateEvolutionAt"] = _iso(current)
        return next_state
    if current <= anchor:
        return next_state
    elapsed_hours = min(24.0, max(0.0, (current - anchor).total_seconds() / 3600.0))
    recovery_units = int(elapsed_hours)
    if recovery_units <= 0:
        # Keep the original anchor so repeated minute-level heartbeats retain
        # the sub-hour remainder instead of accumulating artificial drift.
        return next_state
    energy = _clamp(next_state.get("energy"), 0, 100, 70)
    social_need = _clamp(next_state.get("socialNeed"), 0, 100, 42)
    mood = next_state.get("mood") if isinstance(next_state.get("mood"), dict) else {}
    valence = _clamp(mood.get("valence"), -100, 100, baseline_valence)
    direction = 1 if valence < baseline_valence else -1 if valence > baseline_valence else 0
    sleep_state = str(next_state.get("sleepState") or "").strip().lower()
    energy_delta = recovery_units * (6 if sleep_state in {"sleeping", "resting"} else -1)
    next_state["energy"] = _clamp(energy + energy_delta, 0, 100, 70)
    # socialNeed is the strength of the unmet social drive: time alone makes it
    # rise; an interaction or social activity is what lowers it.
    next_state["socialNeed"] = _clamp(social_need + recovery_units * 2, 0, 100, 42)
    mood["valence"] = _clamp(valence + direction * min(recovery_units * 2, abs(valence - baseline_valence)), -100, 100, baseline_valence)
    mood["updatedAt"] = _iso(current)
    next_state["mood"] = mood
    if str(next_state.get("sleepState") or "").strip() in {"sleeping", "resting"} and current.hour >= 7:
        next_state["sleepState"] = "awake"
    _set_mood_label(next_state)
    # Advance by the applied whole hours only.  Any remaining minutes are
    # intentionally carried into the next heartbeat.
    next_state["lastStateEvolutionAt"] = _iso(anchor + timedelta(hours=recovery_units))
    return next_state


def apply_completed_event_to_state(
    state: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Apply one activity result exactly once and return a bounded new state."""

    next_state = deepcopy(dict(state))
    event_id = str(event.get("eventId") or "").strip()
    processed = [
        str(item).strip()
        for item in list(next_state.get("processedEventIds") or [])
        if str(item).strip()
    ]
    if event_id and event_id in processed:
        return next_state
    next_state = evolve_state_for_time(next_state, now=now)
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    succeeded = str(outcome.get("status") or "") == "succeeded"
    text = _event_text(event)
    activity_kind = str(
        event.get("activityKind")
        or outcome.get("activityKind")
        or outcome.get("kind")
        or ""
    ).strip().lower()
    if succeeded:
        if activity_kind in {"social", "conversation", "relationship"} or any(
            keyword in text for keyword in ("聊天", "朋友", "社交", "聚会")
        ):
            mood_delta, energy_delta, social_delta = 9, -4, -18
        elif activity_kind in {"creative", "learning", "focus", "study"} or any(
            keyword in text for keyword in ("创作", "项目", "学习", "技能", "阅读")
        ):
            mood_delta, energy_delta, social_delta = 7, -8, 2
        elif activity_kind in {"sleep", "rest", "recovery"} or any(
            keyword in text for keyword in ("睡", "休息", "午觉")
        ):
            mood_delta, energy_delta, social_delta = 4, 12, -5
            next_state["sleepState"] = "resting"
        elif activity_kind in {"exercise", "walk", "movement"} or any(
            keyword in text for keyword in ("散步", "运动", "伸展")
        ):
            mood_delta, energy_delta, social_delta = 6, -5, -4
        else:
            mood_delta, energy_delta, social_delta = 4, -3, -3
    else:
        mood_delta, energy_delta, social_delta = -8, -6, 5
    mood_delta += _delta_from_outcome(outcome, "moodDelta")
    energy_delta += _delta_from_outcome(outcome, "energyDelta")
    social_delta += _delta_from_outcome(outcome, "socialNeedDelta")
    mood = next_state.get("mood") if isinstance(next_state.get("mood"), dict) else {}
    mood["valence"] = _clamp(_clamp(mood.get("valence"), -100, 100, 0) + mood_delta, -100, 100, 0)
    mood["arousal"] = _clamp(
        _clamp(mood.get("arousal"), 0, 100, 30) + (3 if succeeded else -4),
        0,
        100,
        30,
    )
    mood["stability"] = _clamp(
        _clamp(mood.get("stability"), 0, 100, 70) + (1 if succeeded else -3),
        0,
        100,
        70,
    )
    if event_id:
        mood["causeEventIds"] = [*list(mood.get("causeEventIds") or []), event_id][-8:]
        processed = [*processed, event_id][-128:]
    mood["updatedAt"] = _iso(now)
    next_state["mood"] = mood
    next_state["energy"] = _clamp(
        _clamp(next_state.get("energy"), 0, 100, 70) + energy_delta,
        0,
        100,
        70,
    )
    next_state["socialNeed"] = _clamp(
        _clamp(next_state.get("socialNeed"), 0, 100, 42) + social_delta,
        0,
        100,
        42,
    )
    if event_id:
        next_state["processedEventIds"] = processed
    current_activity_id = str(next_state.get("currentActivityId") or "").strip()
    if current_activity_id and current_activity_id == str(event.get("activityId") or "").strip():
        next_state["currentActivityId"] = ""
    _set_mood_label(next_state)
    next_state["lastStateEvolutionAt"] = _iso(now)
    return next_state


def apply_relationship_interaction_to_state(
    state: Mapping[str, Any],
    *,
    interaction_id: str,
    intimacy_delta: int,
    trust_delta: int,
    kind: str,
    now: datetime,
) -> dict[str, Any]:
    """Reflect one relationship interaction without allowing duplicate drift."""

    next_state = deepcopy(dict(state))
    normalized_id = str(interaction_id or "").strip()
    processed = [
        str(item).strip()
        for item in list(next_state.get("processedInteractionIds") or [])
        if str(item).strip()
    ]
    if normalized_id and normalized_id in processed:
        return next_state
    next_state = evolve_state_for_time(next_state, now=now)
    kind_text = str(kind or "").strip()
    positive = _clamp(intimacy_delta, -20, 20, 0) + _clamp(trust_delta, -20, 20, 0)
    social_delta = -max(0, min(20, 5 + positive // 3))
    if any(keyword in kind_text for keyword in ("冲突", "争执", "拒绝")):
        social_delta = min(20, social_delta + 12)
    mood_delta = _clamp(positive // 2, -12, 12, 0)
    mood = next_state.get("mood") if isinstance(next_state.get("mood"), dict) else {}
    mood["valence"] = _clamp(_clamp(mood.get("valence"), -100, 100, 0) + mood_delta, -100, 100, 0)
    mood["arousal"] = _clamp(_clamp(mood.get("arousal"), 0, 100, 30) + (2 if positive >= 0 else -3), 0, 100, 30)
    mood["updatedAt"] = _iso(now)
    next_state["mood"] = mood
    next_state["socialNeed"] = _clamp(
        _clamp(next_state.get("socialNeed"), 0, 100, 42) + social_delta,
        0,
        100,
        42,
    )
    if normalized_id:
        next_state["processedInteractionIds"] = [
            *[item for item in processed if item != normalized_id],
            normalized_id,
        ][-128:]
    _set_mood_label(next_state)
    next_state["lastStateEvolutionAt"] = _iso(now)
    return next_state


__all__ = [
    "apply_completed_event_to_state",
    "apply_relationship_interaction_to_state",
    "compute_event_salience",
    "evolve_state_for_time",
    "has_normalized_salience",
]
