"""Outcome-backed long-term goals, projects, habits, and skills."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _clamp(value: object, minimum: int, maximum: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def default_drive_projection(*, now: datetime) -> dict[str, Any]:
    """Create neutral drives for an independent fictional person.

    These defaults express the approved product contract, not a user-authored
    Persona.  They may progress, but never rewrite the Agent's core identity.
    """

    stamp = _iso(now)
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "goals": [
            {
                "driveId": "goal-independent-life",
                "title": "经营稳定而充实的独立生活",
                "status": "active",
                "progress": 0,
                "origin": "independent_person_contract",
                "updatedAt": stamp,
            }
        ],
        "projects": [
            {
                "driveId": "project-personal-craft",
                "title": "推进自己的长期创作项目",
                "status": "active",
                "progress": 0,
                "origin": "independent_person_contract",
                "updatedAt": stamp,
            }
        ],
        "habits": [
            {
                "driveId": "habit-evening-reflection",
                "title": "回顾并整理当天经历",
                "status": "active",
                "completionCount": 0,
                "streak": 0,
                "lastCompletedLocalDate": "",
                "origin": "independent_person_contract",
                "updatedAt": stamp,
            }
        ],
        "skills": [
            {
                "driveId": "skill-creative-expression",
                "title": "创作与表达",
                "status": "active",
                "level": 1,
                "experience": 0,
                "practiceCount": 0,
                "origin": "independent_person_contract",
                "updatedAt": stamp,
            }
        ],
        "processedEventIds": [],
        "updatedAt": stamp,
    }


def _event_kind(event: Mapping[str, Any]) -> str:
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    return str(
        event.get("activityKind")
        or outcome.get("activityKind")
        or event.get("kind")
        or ""
    ).strip().lower()


def _selected_drive_ids(projection: Mapping[str, Any], kind: str, title: str) -> list[str]:
    selected: list[str] = []
    normalized_title = str(title or "").lower()
    if kind in {"creative", "learning", "focus", "study"} or any(
        token in normalized_title for token in ("创作", "项目", "学习", "练习", "阅读")
    ):
        selected.extend(["goal-independent-life", "project-personal-craft", "skill-creative-expression"])
    if kind in {"reflection", "journal"} or any(
        token in normalized_title for token in ("回顾", "日记", "整理明天")
    ):
        selected.extend(["goal-independent-life", "habit-evening-reflection"])
    if kind in {"exercise", "walk", "movement", "wellness", "rest", "recovery"}:
        selected.append("goal-independent-life")
    if not selected:
        selected.append("goal-independent-life")
    available = {
        str(item.get("driveId") or "")
        for bucket in ("goals", "projects", "habits", "skills")
        for item in list(projection.get(bucket) or [])
        if isinstance(item, Mapping)
    }
    return list(dict.fromkeys(item for item in selected if item in available))


def apply_completed_event_to_drives(
    projection: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Advance drives only from a unique, successful completed-life event."""

    current = deepcopy(dict(projection))
    event_id = str(event.get("eventId") or "").strip()
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    processed = [str(item) for item in list(current.get("processedEventIds") or []) if str(item)]
    if (
        not event_id
        or event_id in processed
        or str(event.get("kind") or "") != "activity_completed"
        or str(outcome.get("status") or "") != "succeeded"
    ):
        return {"projection": current, "change": None}

    stamp = _iso(now)
    kind = _event_kind(event)
    drive_ids = _selected_drive_ids(current, kind, str(event.get("title") or ""))
    local_date = str(event.get("localDate") or str(event.get("occurredAt") or "")[:10])
    deltas: list[dict[str, Any]] = []
    for bucket in ("goals", "projects", "habits", "skills"):
        rows = current.get(bucket) if isinstance(current.get(bucket), list) else []
        for item in rows:
            if not isinstance(item, dict) or str(item.get("driveId") or "") not in drive_ids:
                continue
            drive_id = str(item["driveId"])
            if bucket == "goals":
                before = _clamp(item.get("progress"), 0, 100)
                item["progress"] = min(100, before + 2)
                deltas.append({"driveId": drive_id, "field": "progress", "delta": item["progress"] - before})
            elif bucket == "projects":
                before = _clamp(item.get("progress"), 0, 100)
                item["progress"] = min(100, before + 5)
                deltas.append({"driveId": drive_id, "field": "progress", "delta": item["progress"] - before})
            elif bucket == "habits":
                if local_date and str(item.get("lastCompletedLocalDate") or "") != local_date:
                    item["completionCount"] = max(0, int(item.get("completionCount") or 0)) + 1
                    item["streak"] = max(0, int(item.get("streak") or 0)) + 1
                    item["lastCompletedLocalDate"] = local_date
                    deltas.append({"driveId": drive_id, "field": "completionCount", "delta": 1})
            else:
                before = max(0, int(item.get("experience") or 0))
                item["experience"] = before + 8
                item["practiceCount"] = max(0, int(item.get("practiceCount") or 0)) + 1
                item["level"] = min(10, 1 + item["experience"] // 100)
                deltas.append({"driveId": drive_id, "field": "experience", "delta": 8})
            item["lastSourceEventId"] = event_id
            item["updatedAt"] = stamp
    current["processedEventIds"] = [*processed, event_id][-512:]
    current["updatedAt"] = stamp
    change = {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "driveEventId": f"drive:{event_id}",
        "sourceEventId": event_id,
        "occurredAt": str(event.get("occurredAt") or stamp),
        "driveIds": drive_ids,
        "deltas": deltas,
    }
    return {"projection": current, "change": change}


def link_schedule_to_drives(
    schedule: Mapping[str, Any], projection: Mapping[str, Any]
) -> dict[str, Any]:
    """Annotate plan rows with explainable drive links; no progress is awarded."""

    linked = deepcopy(dict(schedule))
    activities = linked.get("activities") if isinstance(linked.get("activities"), list) else []
    titles = {
        str(item.get("driveId") or ""): str(item.get("title") or "")
        for bucket in ("goals", "projects", "habits", "skills")
        for item in list(projection.get(bucket) or [])
        if isinstance(item, Mapping)
    }
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        drive_ids = _selected_drive_ids(
            projection,
            str(activity.get("activityKind") or activity.get("kind") or "").lower(),
            str(activity.get("title") or ""),
        )
        activity["driveLinks"] = drive_ids
        activity["driveReason"] = "；".join(titles[item] for item in drive_ids if titles.get(item))[:300]
    return linked


def prompt_drive_summary(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded derived context for planning and dialogue prompts."""

    return {
        bucket: [
            {
                "driveId": str(item.get("driveId") or ""),
                "title": str(item.get("title") or "")[:80],
                **({"progress": _clamp(item.get("progress"), 0, 100)} if bucket in {"goals", "projects"} else {}),
                **({"streak": max(0, int(item.get("streak") or 0))} if bucket == "habits" else {}),
                **({"level": _clamp(item.get("level"), 1, 10, 1)} if bucket == "skills" else {}),
            }
            for item in list(projection.get(bucket) or [])[:4]
            if isinstance(item, Mapping) and str(item.get("status") or "active") == "active"
        ]
        for bucket in ("goals", "projects", "habits", "skills")
    }


__all__ = [
    "apply_completed_event_to_drives",
    "default_drive_projection",
    "link_schedule_to_drives",
    "prompt_drive_summary",
]
