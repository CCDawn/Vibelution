"""Pure schedule construction and planner-proposal validation.

The life service owns Agent state, persistence, and planner invocation.  This
module owns the deterministic planning rules so they can evolve and be tested
without coupling time-window validation to the heartbeat or memory stores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from .manifest import STORAGE_SCHEMA_VERSION


PLANNER_ACTIVITY_KINDS = (
    "creative",
    "learning",
    "focus",
    "study",
    "social",
    "conversation",
    "relationship",
    "sleep",
    "rest",
    "recovery",
    "exercise",
    "walk",
    "movement",
    "wellness",
    "meal",
    "cooking",
    "chores",
    "housework",
    "journal",
    "reflection",
    "personal",
    "simulated",
)
PLANNER_ACTIVITY_KIND_SET = frozenset(PLANNER_ACTIVITY_KINDS)


def _utc_iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def build_deterministic_schedule(
    agent_id: str,
    local_date: date,
    *,
    timezone_name: str,
    zone: tzinfo,
    now: datetime,
    life_world: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the bounded provisional schedule used before a planner runs."""

    identity_schedule = _identity_constrained_schedule(
        agent_id,
        local_date,
        timezone_name=timezone_name,
        zone=zone,
        now=now,
        life_world=life_world,
    )
    if identity_schedule is not None:
        return identity_schedule

    seed = int(
        hashlib.sha256(f"{agent_id}:{local_date.isoformat()}".encode()).hexdigest()[:8],
        16,
    )
    variants = [
        ("整理房间和做早餐", "专注处理自己的学习与创作", "傍晚散步", "写私人日记并放松"),
        ("慢慢醒来并准备早餐", "阅读和推进个人项目", "做一顿晚饭", "听音乐并回顾一天"),
        ("晨间伸展和早餐", "练习一项长期技能", "去附近走走", "整理明天的想法"),
    ]
    titles = variants[seed % len(variants)]
    slots = ((8, 0, 9, 0), (10, 0, 12, 0), (18, 0, 19, 0), (21, 30, 22, 15))
    activities: list[dict[str, Any]] = []
    for index, (title, slot) in enumerate(zip(titles, slots), start=1):
        start_hour, start_minute, end_hour, end_minute = slot
        start_at = datetime.combine(
            local_date, time(start_hour, start_minute), tzinfo=zone
        )
        end_at = datetime.combine(
            local_date, time(end_hour, end_minute), tzinfo=zone
        )
        activities.append(
            {
                "activityId": f"life-{local_date.isoformat()}-{index}",
                "title": title,
                "kind": "simulated",
                "startAt": _utc_iso(start_at),
                "endAt": _utc_iso(end_at),
                "status": "planned",
                "origin": "deterministic_daily_plan",
            }
        )
    return {
        "schemaVersion": STORAGE_SCHEMA_VERSION,
        "agentId": str(agent_id).strip(),
        "localDate": local_date.isoformat(),
        "timezone": str(timezone_name or "Asia/Shanghai"),
        "scheduleVersion": 1,
        "planningMode": "deterministic_mvp",
        "activities": activities,
        "createdAt": _utc_iso(now),
        "updatedAt": _utc_iso(now),
    }


def _identity_constrained_schedule(
    agent_id: str,
    local_date: date,
    *,
    timezone_name: str,
    zone: tzinfo,
    now: datetime,
    life_world: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(life_world, dict) or str(life_world.get("setupState") or "") != "ready":
        return None
    facts = life_world.get("facts") if isinstance(life_world.get("facts"), dict) else {}
    identities = [row for row in list(facts.get("identities") or []) if isinstance(row, dict)]
    if not identities:
        return None
    identity = identities[0]
    identity_kind = str(identity.get("kind") or "").strip().lower()
    day_type = "weekday" if local_date.weekday() < 5 else "weekend"
    routines = [
        row
        for row in list(facts.get("routines") or [])
        if isinstance(row, dict) and str(row.get("dayType") or "") == day_type
    ]
    if not routines:
        routines = [
            row
            for row in list(facts.get("routines") or [])
            if isinstance(row, dict) and str(row.get("dayType") or "") == "holiday"
        ]
    routines.sort(key=lambda row: str(row.get("startTime") or ""))
    if not routines:
        return None

    activities: list[dict[str, Any]] = []
    if str(routines[0].get("startTime") or "") >= "07:30":
        routines = [
            {
                "routineId": "morning-meal",
                "startTime": "07:00",
                "endTime": "07:30",
                "title": "起床、整理和吃早餐",
                "activityKind": "meal",
            },
            *routines,
        ]
    for index, row in enumerate(routines, start=1):
        try:
            start_value = time.fromisoformat(str(row.get("startTime") or ""))
            end_value = time.fromisoformat(str(row.get("endTime") or ""))
        except ValueError:
            continue
        start_at = datetime.combine(local_date, start_value, tzinfo=zone)
        end_at = datetime.combine(local_date, end_value, tzinfo=zone)
        if end_at <= start_at:
            continue
        stable_id = hashlib.sha256(
            f"{agent_id}:{local_date.isoformat()}:{row.get('routineId')}:{index}".encode("utf-8")
        ).hexdigest()[:16]
        activities.append(
            {
                "activityId": f"life-identity-{local_date.isoformat()}-{stable_id}",
                "title": str(row.get("title") or "生活安排").strip()[:160],
                "kind": "simulated",
                "activityKind": str(row.get("activityKind") or "personal").strip() or "personal",
                "startAt": _utc_iso(start_at),
                "endAt": _utc_iso(end_at),
                "status": "planned",
                "origin": "life_world_identity_routine",
                "lifeWorldRoutineId": str(row.get("routineId") or ""),
            }
        )
    return {
        "schemaVersion": STORAGE_SCHEMA_VERSION,
        "agentId": str(agent_id).strip(),
        "localDate": local_date.isoformat(),
        "timezone": str(timezone_name or "Asia/Shanghai"),
        "scheduleVersion": 1,
        "planningMode": "identity_constrained_deterministic",
        "identityConstraint": {
            "kind": identity_kind,
            "identityId": str(identity.get("identityId") or ""),
            "roleTitle": str(identity.get("roleTitle") or ""),
            "lifeWorldRevision": int(life_world.get("revision") or 0),
        },
        "activities": activities,
        "createdAt": _utc_iso(now),
        "updatedAt": _utc_iso(now),
    }


def parse_datetime_in_zone(
    value: object,
    zone: tzinfo,
    *,
    local_date: date | None = None,
) -> datetime | None:
    """Parse a full ISO timestamp or a planner-local ``HH:MM`` value."""

    raw = str(value or "").strip()
    if not raw:
        return None
    if local_date is not None:
        try:
            parsed_time = time.fromisoformat(raw)
        except ValueError:
            parsed_time = None
        if parsed_time is not None:
            return datetime.combine(local_date, parsed_time, tzinfo=zone)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def validate_schedule_proposal(
    proposal: Any,
    *,
    agent_id: str,
    local_date: date,
    zone: tzinfo,
) -> tuple[list[dict[str, Any]], str]:
    """Normalize and validate one untrusted planner proposal."""

    if isinstance(proposal, str):
        raw = proposal.strip()
        if not raw or len(raw) > 12_000:
            return [], "invalid_proposal"
        try:
            proposal = json.loads(raw)
        except json.JSONDecodeError:
            return [], "invalid_proposal"
    if not isinstance(proposal, dict):
        return [], "invalid_proposal"
    if isinstance(proposal.get("schedule"), dict):
        proposal = proposal["schedule"]
    raw_activities = proposal.get("activities")
    if not isinstance(raw_activities, list) or not raw_activities:
        return [], "empty_proposal"
    if len(raw_activities) > 8:
        return [], "too_many_activities"

    normalized: list[dict[str, Any]] = []
    windows: list[tuple[datetime, datetime]] = []
    for index, raw_activity in enumerate(raw_activities, start=1):
        if not isinstance(raw_activity, dict):
            return [], "invalid_activity"
        title = str(raw_activity.get("title") or "").strip()[:160]
        if not title:
            return [], "missing_title"
        start_at = parse_datetime_in_zone(
            raw_activity.get("startAt"), zone, local_date=local_date
        )
        end_at = parse_datetime_in_zone(
            raw_activity.get("endAt"), zone, local_date=local_date
        )
        if start_at is None or end_at is None or end_at <= start_at:
            return [], "invalid_time_window"
        if (
            start_at.astimezone(zone).date() != local_date
            or end_at.astimezone(zone).date() != local_date
        ):
            return [], "crosses_local_date"
        duration = end_at - start_at
        if duration < timedelta(minutes=5) or duration > timedelta(hours=8):
            return [], "invalid_duration"
        if any(
            start_at < existing_end and end_at > existing_start
            for existing_start, existing_end in windows
        ):
            return [], "overlap"
        windows.append((start_at, end_at))

        raw_kind = str(raw_activity.get("kind") or "").strip().lower()
        raw_activity_kind = str(raw_activity.get("activityKind") or "").strip().lower()
        if (
            raw_kind not in {"", "simulated", "tool"}
            and raw_kind not in PLANNER_ACTIVITY_KIND_SET
        ):
            return [], "invalid_kind"
        if raw_activity_kind and raw_activity_kind not in PLANNER_ACTIVITY_KIND_SET:
            return [], "invalid_activity_kind"
        # ``kind`` is the execution classification.  Semantic shorthand such
        # as ``creative`` is safe only as a simulated activity.
        kind = "tool" if raw_kind == "tool" else "simulated"
        activity_kind = raw_activity_kind or (
            raw_kind if raw_kind in PLANNER_ACTIVITY_KIND_SET else ""
        )
        required_tools: list[str] = []
        if kind == "tool":
            raw_tools = raw_activity.get("requiredToolNames")
            if not isinstance(raw_tools, list):
                return [], "tool_names_required"
            for item in raw_tools:
                tool_name = str(item or "").strip()[:160]
                if tool_name and tool_name not in required_tools:
                    required_tools.append(tool_name)
                if len(required_tools) >= 8:
                    break
            if not required_tools:
                return [], "tool_names_required"
        stable_id = hashlib.sha256(
            f"{agent_id}:{local_date.isoformat()}:{index}:{title}:{_utc_iso(start_at)}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        normalized.append(
            {
                "activityId": f"life-plan-{local_date.isoformat()}-{stable_id}",
                "title": title,
                "kind": kind,
                "startAt": _utc_iso(start_at),
                "endAt": _utc_iso(end_at),
                "status": "planned",
                "origin": "agent_planner_proposal",
                **(
                    {"activityKind": activity_kind}
                    if activity_kind and activity_kind != "simulated"
                    else {}
                ),
                **({"requiredToolNames": required_tools} if required_tools else {}),
            }
        )
    normalized.sort(key=lambda item: str(item.get("startAt") or ""))
    return normalized, ""


__all__ = [
    "PLANNER_ACTIVITY_KINDS",
    "PLANNER_ACTIVITY_KIND_SET",
    "build_deterministic_schedule",
    "parse_datetime_in_zone",
    "validate_schedule_proposal",
]
