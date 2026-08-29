"""Deterministic, Agent-scoped calendar projections for virtual-human-life.

The calendar is intentionally a small append-only ledger adapter.  A row in the
ledger is a change (``upsert``, ``cancel`` or ``exception``); the effective
event is reconstructed from the rows and expanded only for the requested local
date.  Daily schedules may reference an occurrence with ``calendarEventId``,
but they continue to own execution state and outcomes.

This module does not know about the host Agent, sessions, tools, or an LLM.  It
is therefore safe to use from both a heartbeat and a UI read projection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "yearly"})
_TERMINAL_OPERATIONS = frozenset({"cancel", "delete"})


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _parse_datetime(value: object, *, default_zone: tzinfo = UTC) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_zone)
    return parsed


def _zone(timezone_name: str | tzinfo | None) -> tzinfo:
    if isinstance(timezone_name, tzinfo):
        return timezone_name
    normalized = str(timezone_name or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        if normalized == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise ValueError(f"Unknown timezone: {normalized}") from None


def _date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value or "").strip())


def _bounded_text(value: object, limit: int, default: str = "") -> str:
    return str(value or default).strip()[:limit]


def _normal_recurrence(value: object, *, event_start: datetime) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    frequency = _bounded_text(value.get("frequency"), 20).lower()
    if frequency not in _FREQUENCIES:
        return None
    interval = max(1, min(365, int(value.get("interval") or 1)))
    result: dict[str, Any] = {"frequency": frequency, "interval": interval}
    if frequency == "weekly":
        raw_weekdays = value.get("byWeekday")
        weekdays: list[int] = []
        if isinstance(raw_weekdays, (list, tuple, set)):
            for item in raw_weekdays:
                try:
                    weekday = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= weekday <= 6 and weekday not in weekdays:
                    weekdays.append(weekday)
        if not weekdays:
            weekdays = [event_start.weekday()]
        result["byWeekday"] = sorted(weekdays)
    elif frequency == "monthly":
        result["day"] = max(1, min(31, int(value.get("day") or event_start.day)))
    elif frequency == "yearly":
        result["month"] = max(1, min(12, int(value.get("month") or event_start.month)))
        result["day"] = max(1, min(31, int(value.get("day") or event_start.day)))
    for key in ("until", "count"):
        if value.get(key) is not None and str(value.get(key)).strip() != "":
            if key == "count":
                try:
                    result[key] = max(1, min(10_000, int(value.get(key))))
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    result[key] = _date(value.get(key)).isoformat()
                except (TypeError, ValueError):
                    pass
    return result


def _event_id(value: object) -> str:
    normalized = _bounded_text(value, 160)
    if not normalized:
        raise ValueError("calendar eventId is required")
    return normalized


def normalize_calendar_change(
    change: Mapping[str, Any],
    *,
    agent_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize one calendar-ledger change.

    ``upsert`` is the default operation, which makes the function convenient
    for imported operator configuration while still recording an explicit
    operation in the ledger.  Calendar input is untrusted: titles, reasons and
    source references are bounded and malformed windows fail closed.
    """

    if not isinstance(change, Mapping):
        raise TypeError("calendar change must be an object")
    operation = _bounded_text(change.get("operation") or change.get("op") or "upsert", 20).lower()
    if operation not in {"upsert", "cancel", "delete", "exception"}:
        raise ValueError("unsupported calendar operation")
    event_id = _event_id(change.get("eventId") or change.get("id"))
    timestamp = now or datetime.now(UTC)
    row: dict[str, Any] = {
        "operation": operation,
        "eventId": event_id,
        "agentId": _bounded_text(agent_id or change.get("agentId"), 160),
        "changedAt": _iso(timestamp),
    }
    if operation in _TERMINAL_OPERATIONS:
        row.update({"reason": _bounded_text(change.get("reason"), 300)})
        return row
    if operation == "exception":
        occurrence_date = change.get("occurrenceDate") or change.get("date")
        try:
            row["occurrenceDate"] = _date(occurrence_date).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("calendar exception occurrenceDate is required") from exc
        replacement = change.get("replacement")
        if isinstance(replacement, Mapping):
            row["replacement"] = {
                "title": _bounded_text(replacement.get("title"), 160),
                "startAt": _bounded_text(replacement.get("startAt"), 80),
                "endAt": _bounded_text(replacement.get("endAt"), 80),
            }
        row["reason"] = _bounded_text(change.get("reason"), 300)
        return row

    timezone_name = _bounded_text(change.get("timezone") or "Asia/Shanghai", 80)
    event_zone = _zone(timezone_name)
    start = _parse_datetime(change.get("startAt"), default_zone=event_zone)
    end = _parse_datetime(change.get("endAt"), default_zone=event_zone)
    if start is None or end is None or end <= start:
        raise ValueError("calendar event requires a valid startAt/endAt window")
    if end - start > timedelta(days=31):
        raise ValueError("calendar event window must not exceed 31 days")
    recurrence = _normal_recurrence(change.get("recurrence"), event_start=start.astimezone(event_zone))
    kind = _bounded_text(change.get("kind") or "one_off", 40).lower()
    if kind not in {"one_off", "recurring", "anniversary", "reminder", "commitment"}:
        kind = "one_off"
    if kind in {"recurring", "anniversary"} and recurrence is None:
        recurrence = {
            "frequency": "yearly" if kind == "anniversary" else "daily",
            "interval": 1,
            **(
                {"month": start.astimezone(event_zone).month, "day": start.astimezone(event_zone).day}
                if kind == "anniversary"
                else {}
            ),
        }
    row.update(
        {
            "title": _bounded_text(change.get("title") or "日历安排", 160),
            "kind": kind,
            "startAt": _iso(start),
            "endAt": _iso(end),
            "timezone": timezone_name,
            "recurrence": recurrence,
            "source": {
                "kind": _bounded_text(
                    (change.get("source") or {}).get("kind")
                    if isinstance(change.get("source"), Mapping)
                    else change.get("sourceKind"),
                    60,
                    "operator",
                ),
                "ref": _bounded_text(
                    (change.get("source") or {}).get("ref")
                    if isinstance(change.get("source"), Mapping)
                    else change.get("sourceRef"),
                    300,
                ),
            },
        }
    )
    return row


def append_calendar_change(
    ledger: list[dict[str, Any]],
    change: Mapping[str, Any],
    *,
    agent_id: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Append a normalized immutable calendar change to a bounded ledger."""

    normalized = normalize_calendar_change(change, agent_id=agent_id, now=now)
    rows = [deepcopy(item) for item in ledger if isinstance(item, Mapping)]
    rows.append(normalized)
    return rows[-2048:]


def effective_calendar_events(ledger: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold ledger changes into currently active event definitions."""

    events: dict[str, dict[str, Any]] = {}
    cancellations: dict[str, dict[str, Any]] = {}
    exceptions: dict[str, list[dict[str, Any]]] = {}
    for raw in ledger:
        if not isinstance(raw, Mapping):
            continue
        operation = _bounded_text(raw.get("operation") or "upsert", 20).lower()
        try:
            event_id = _event_id(raw.get("eventId"))
        except ValueError:
            continue
        if operation == "upsert":
            events[event_id] = deepcopy(dict(raw))
            events[event_id]["operation"] = "upsert"
            cancellations.pop(event_id, None)
        elif operation in _TERMINAL_OPERATIONS:
            cancellations[event_id] = deepcopy(dict(raw))
        elif operation == "exception":
            occurrence = _bounded_text(raw.get("occurrenceDate"), 20)
            if occurrence:
                exceptions.setdefault(event_id, []).append(deepcopy(dict(raw)))
    effective: list[dict[str, Any]] = []
    for event_id, event in events.items():
        if event_id in cancellations:
            continue
        event["exceptions"] = exceptions.get(event_id, [])
        effective.append(event)
    effective.sort(key=lambda item: (str(item.get("startAt") or ""), str(item.get("eventId") or "")))
    return effective


def _candidate_start_dates(
    event: Mapping[str, Any],
    target_date: date,
    *,
    zone: tzinfo,
) -> list[date]:
    start = _parse_datetime(event.get("startAt"), default_zone=zone)
    if start is None:
        return []
    local_start = start.astimezone(zone)
    recurrence = event.get("recurrence") if isinstance(event.get("recurrence"), Mapping) else None
    if not recurrence:
        return [local_start.date()] if local_start.date() == target_date else []
    frequency = _bounded_text(recurrence.get("frequency"), 20).lower()
    interval = max(1, min(365, int(recurrence.get("interval") or 1)))
    origin = local_start.date()
    if target_date < origin:
        return []
    until = None
    try:
        until = _date(recurrence.get("until")) if recurrence.get("until") else None
    except (TypeError, ValueError):
        until = None
    if until is not None and target_date > until:
        return []
    count = recurrence.get("count")
    try:
        count_int = int(count) if count is not None else None
    except (TypeError, ValueError):
        count_int = None
    if frequency == "daily":
        delta_days = (target_date - origin).days
        if delta_days % interval:
            return []
        occurrence_index = delta_days // interval
        if count_int is not None and occurrence_index >= count_int:
            return []
        return [target_date]
    if frequency == "weekly":
        weekdays = recurrence.get("byWeekday")
        if not isinstance(weekdays, (list, tuple, set)):
            weekdays = [origin.weekday()]
        if target_date.weekday() not in {int(item) for item in weekdays if str(item).lstrip("-").isdigit()}:
            return []
        weeks = (target_date - origin).days // 7
        if weeks < 0 or weeks % interval:
            return []
        # ``count`` counts occurrences, not calendar weeks.  This is enough to
        # stay deterministic for the small number of projections requested by
        # the plugin, while preserving the intuitive weekly semantics.
        if count_int is not None:
            prior = 0
            cursor = origin
            while cursor <= target_date:
                if cursor.weekday() in {int(item) for item in weekdays if str(item).lstrip("-").isdigit()} and ((cursor - origin).days // 7) % interval == 0:
                    prior += 1
                cursor += timedelta(days=1)
            if prior > count_int:
                return []
        return [target_date]
    if frequency == "monthly":
        requested_day = max(1, min(31, int(recurrence.get("day") or origin.day)))
        if target_date.day != requested_day:
            return []
        months = (target_date.year - origin.year) * 12 + target_date.month - origin.month
        if months < 0 or months % interval:
            return []
        if count_int is not None and months // interval >= count_int:
            return []
        return [target_date]
    if frequency == "yearly":
        month = max(1, min(12, int(recurrence.get("month") or origin.month)))
        day = max(1, min(31, int(recurrence.get("day") or origin.day)))
        if target_date.month != month or target_date.day != day:
            return []
        years = target_date.year - origin.year
        if years < 0 or years % interval:
            return []
        if count_int is not None and years // interval >= count_int:
            return []
        return [target_date]
    return []


def _replacement_occurrence(
    event: Mapping[str, Any],
    exception: Mapping[str, Any],
    *,
    occurrence_date: date,
    zone: tzinfo,
) -> dict[str, Any] | None:
    replacement = exception.get("replacement")
    if not isinstance(replacement, Mapping):
        return None
    start = _parse_datetime(replacement.get("startAt"), default_zone=zone)
    end = _parse_datetime(replacement.get("endAt"), default_zone=zone)
    if start is None or end is None or end <= start:
        return None
    return _make_occurrence(event, occurrence_date, start=start, end=end, zone=zone, exception=exception)


def _make_occurrence(
    event: Mapping[str, Any],
    occurrence_date: date,
    *,
    start: datetime,
    end: datetime,
    zone: tzinfo,
    exception: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = _event_id(event.get("eventId"))
    local_start = start.astimezone(zone)
    local_end = end.astimezone(zone)
    occurrence_key = f"{event_id}:{occurrence_date.isoformat()}:{_iso(start)}"
    occurrence_id = "calendar-occurrence-" + hashlib.sha256(occurrence_key.encode("utf-8")).hexdigest()[:16]
    return {
        "calendarEventId": event_id,
        "calendarOccurrenceId": occurrence_id,
        "occurrenceDate": occurrence_date.isoformat(),
        "title": _bounded_text(event.get("title") or "日历安排", 160),
        "kind": _bounded_text(event.get("kind") or "one_off", 40),
        "startAt": _iso(start),
        "endAt": _iso(end),
        "localStartAt": local_start.isoformat(),
        "localEndAt": local_end.isoformat(),
        "timezone": str(event.get("timezone") or "Asia/Shanghai"),
        "source": deepcopy(event.get("source") or {}),
        **({"exception": deepcopy(dict(exception))} if exception else {}),
    }


def occurrences_for_date(
    ledger: list[Mapping[str, Any]],
    local_date: str | date,
    *,
    timezone_name: str | tzinfo = "Asia/Shanghai",
) -> list[dict[str, Any]]:
    """Expand effective events intersecting one local calendar day."""

    target = _date(local_date)
    projection_zone = _zone(timezone_name)
    day_start = datetime.combine(target, time.min, tzinfo=projection_zone)
    day_end = day_start + timedelta(days=1)
    occurrences: list[dict[str, Any]] = []
    for event in effective_calendar_events(ledger):
        event_zone = _zone(event.get("timezone") or projection_zone)
        # A calendar item may cross midnight.  Check the target date and the
        # immediately preceding local date so the continuation is visible in
        # both daily projections; recurring events use the same rule.
        candidate_dates = (target - timedelta(days=1), target)
        for candidate_date in candidate_dates:
            for occurrence_date in _candidate_start_dates(event, candidate_date, zone=event_zone):
                start = _parse_datetime(event.get("startAt"), default_zone=event_zone)
                end = _parse_datetime(event.get("endAt"), default_zone=event_zone)
                if start is None or end is None:
                    continue
                base_start_local = start.astimezone(event_zone)
                base_end_local = end.astimezone(event_zone)
                duration = base_end_local - base_start_local
                occurrence_start = datetime.combine(
                    occurrence_date,
                    time(
                        base_start_local.hour,
                        base_start_local.minute,
                        base_start_local.second,
                        base_start_local.microsecond,
                    ),
                    tzinfo=event_zone,
                )
                occurrence_end = occurrence_start + duration
                exception = next(
                    (
                        item
                        for item in list(event.get("exceptions") or [])
                        if isinstance(item, Mapping)
                        and str(item.get("occurrenceDate") or "") == occurrence_date.isoformat()
                    ),
                    None,
                )
                if exception is not None:
                    replacement = _replacement_occurrence(
                        event,
                        exception,
                        occurrence_date=occurrence_date,
                        zone=event_zone,
                    )
                    if replacement is None:
                        continue
                    occurrence = replacement
                else:
                    occurrence = _make_occurrence(
                        event,
                        occurrence_date,
                        start=occurrence_start,
                        end=occurrence_end,
                        zone=event_zone,
                    )
                occurrence_start_utc = _parse_datetime(occurrence["startAt"]) or occurrence_start.astimezone(UTC)
                occurrence_end_utc = _parse_datetime(occurrence["endAt"]) or occurrence_end.astimezone(UTC)
                if occurrence_start_utc < day_end.astimezone(UTC) and occurrence_end_utc > day_start.astimezone(UTC):
                    occurrences.append(occurrence)
    occurrences.sort(key=lambda item: (str(item.get("startAt") or ""), str(item.get("calendarEventId") or "")))
    return occurrences


def detect_calendar_conflicts(occurrences: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact, explainable overlap ledger projection."""

    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(occurrences):
        left_start = _parse_datetime(left.get("startAt"))
        left_end = _parse_datetime(left.get("endAt"))
        if left_start is None or left_end is None:
            continue
        for right in occurrences[index + 1 :]:
            right_start = _parse_datetime(right.get("startAt"))
            right_end = _parse_datetime(right.get("endAt"))
            if right_start is None or right_end is None:
                continue
            if left_start >= right_end or right_start >= left_end:
                continue
            event_ids = sorted(
                {
                    _bounded_text(left.get("calendarEventId"), 160),
                    _bounded_text(right.get("calendarEventId"), 160),
                }
            )
            occurrence_ids = sorted(
                {
                    _bounded_text(left.get("calendarOccurrenceId"), 160),
                    _bounded_text(right.get("calendarOccurrenceId"), 160),
                }
            )
            conflict_key = ":".join([*event_ids, *occurrence_ids])
            conflicts.append(
                {
                    "conflictId": "calendar-conflict-" + hashlib.sha256(conflict_key.encode("utf-8")).hexdigest()[:16],
                    "eventIds": event_ids,
                    "occurrenceIds": occurrence_ids,
                    "startAt": max(left_start, right_start).isoformat(),
                    "endAt": min(left_end, right_end).isoformat(),
                    "status": "unresolved",
                }
            )
    return conflicts


def project_calendar_for_date(
    ledger: list[Mapping[str, Any]],
    local_date: str | date,
    *,
    timezone_name: str | tzinfo = "Asia/Shanghai",
) -> dict[str, Any]:
    """Build the read-only calendar projection for one local date."""

    target = _date(local_date)
    occurrences = occurrences_for_date(ledger, target, timezone_name=timezone_name)
    conflicts = detect_calendar_conflicts(occurrences)
    for conflict in conflicts:
        conflict["localDate"] = target.isoformat()
    return {
        "localDate": target.isoformat(),
        "timezone": str(timezone_name),
        "occurrences": occurrences,
        "conflicts": conflicts,
        "eventCount": len(occurrences),
        "conflictCount": len(conflicts),
    }


def merge_calendar_into_schedule(
    schedule: Mapping[str, Any],
    projection: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Reference calendar occurrences from a daily schedule.

    The function never changes an activity's execution outcome.  If an
    occurrence disappears because of a cancellation/exception, a still-planned
    reference is marked ``cancelled`` so the schedule remains an audit trail.
    """

    result = deepcopy(dict(schedule))
    activities = [deepcopy(item) for item in list(result.get("activities") or []) if isinstance(item, Mapping)]
    by_occurrence = {
        str(item.get("calendarOccurrenceId") or ""): item
        for item in activities
        if str(item.get("calendarOccurrenceId") or "")
    }
    changed = False
    projected_ids = set()
    for occurrence in list(projection.get("occurrences") or []):
        if not isinstance(occurrence, Mapping):
            continue
        occurrence_id = _bounded_text(occurrence.get("calendarOccurrenceId"), 160)
        event_id = _bounded_text(occurrence.get("calendarEventId"), 160)
        if not occurrence_id or not event_id:
            continue
        projected_ids.add(occurrence_id)
        existing = by_occurrence.get(occurrence_id)
        if existing is not None:
            # Calendar text/times are projections; keep schedule status and
            # outcome fields untouched while refreshing source metadata.
            for key in ("calendarEventId", "title", "startAt", "endAt", "timezone", "calendarOccurrenceId"):
                value = deepcopy(occurrence.get(key) or existing.get(key) or "")
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True
            continue
        activity = {
            "activityId": occurrence_id,
            "calendarEventId": event_id,
            "calendarOccurrenceId": occurrence_id,
            "title": _bounded_text(occurrence.get("title") or "日历安排", 160),
            "kind": "simulated",
            "activityKind": "calendar",
            "startAt": _bounded_text(occurrence.get("startAt"), 80),
            "endAt": _bounded_text(occurrence.get("endAt"), 80),
            "status": "planned",
            "origin": "calendar_projection",
            "timezone": _bounded_text(occurrence.get("timezone") or "Asia/Shanghai", 80),
        }
        activities.append(activity)
        by_occurrence[occurrence_id] = activity
        changed = True
    for activity in activities:
        occurrence_id = str(activity.get("calendarOccurrenceId") or "")
        if (
            occurrence_id
            and occurrence_id not in projected_ids
            and str(activity.get("status") or "planned") == "planned"
        ):
            activity["status"] = "cancelled"
            activity["finishedAt"] = _iso(now or datetime.now(UTC))
            activity["reason"] = "calendar_occurrence_cancelled_or_excepted"
            changed = True
    activities.sort(key=lambda item: (str(item.get("startAt") or ""), str(item.get("activityId") or "")))
    if changed:
        result["activities"] = activities
        result["calendarProjection"] = {
            "eventCount": int(projection.get("eventCount") or 0),
            "conflictCount": int(projection.get("conflictCount") or 0),
            "conflicts": deepcopy(list(projection.get("conflicts") or [])),
            "projectedAt": _iso(now or datetime.now(UTC)),
        }
        result["scheduleVersion"] = int(result.get("scheduleVersion") or 1) + 1
        result["updatedAt"] = _iso(now or datetime.now(UTC))
    return result, changed


__all__ = [
    "append_calendar_change",
    "detect_calendar_conflicts",
    "effective_calendar_events",
    "merge_calendar_into_schedule",
    "normalize_calendar_change",
    "occurrences_for_date",
    "project_calendar_for_date",
]
