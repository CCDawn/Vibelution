"""Companion-only reunion and shared-experience projections.

The functions in this module are deliberately pure.  Arrival timestamps and
open-loop/event rows are supplied by the Companion adapter, while the native
Session, Journal, Memory, and Drive authorities remain untouched.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UNKNOWN = "unknown"
_MAX_EVENT_ID_LENGTH = 200
_MAX_TITLE_LENGTH = 160
_MAX_SUMMARY_LENGTH = 240
_MAX_OCCURRED_AT_LENGTH = 80
_MAX_TOPIC_KEY_LENGTH = 120
_MAX_LOOP_ID_LENGTH = 200


def _parse_timestamp(value: object) -> tuple[datetime, str] | None:
    """Parse an offset-bearing timestamp and retain its evidence text.

    A naive timestamp has no reliable UTC meaning here, so it is treated as
    missing evidence rather than silently assuming a timezone.
    """

    raw = str(value or "").strip()
    if not raw or raw.lower() == _UNKNOWN:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC), raw


def _utc_now(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)


def _text(value: object, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _intent(value: object) -> str:
    # Intent is a classified receipt, not user-authored prompt content.  Keep
    # it short and single-line before it can appear in a derived projection.
    return (
        " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:80]
        .strip()
        .lower()
    )


def _resume_topic(value: object) -> str:
    intent = _intent(value)
    # These are the actual resumable values emitted by
    # ``classify_companion_user_intent``.  The field is a continuation hint,
    # not a place to invent a topic from arbitrary text.
    return intent if intent in {"acknowledgement", "small_talk"} else ""


def project_reunion_context(
    *,
    previous_user_arrived_at: str,
    current_user_arrived_at: str,
    local_now: datetime,
    timezone_name: str,
    user_intent: str,
    proactive: bool = False,
) -> dict[str, Any]:
    """Project evidence-backed time continuity for one Companion turn.

    ``elapsedSeconds`` is measured on the UTC timeline.  ``localDayGap`` is
    measured after converting both arrivals into the character's timezone;
    these intentionally differ around local midnight.  Invalid or backwards
    timestamps fail closed to ``"unknown"``.  A proactive turn is explicitly
    marked as such and never counts as the user returning.
    """

    previous = _parse_timestamp(previous_user_arrived_at)
    current = _parse_timestamp(current_user_arrived_at)
    previous_value = previous[1] if previous is not None else _UNKNOWN
    current_value = current[1] if current is not None else _UNKNOWN
    proactive_value = bool(proactive)

    elapsed: int | str = _UNKNOWN
    local_day_gap: int | str = _UNKNOWN
    if previous is not None and current is not None and current[0] >= previous[0]:
        elapsed = int((current[0] - previous[0]).total_seconds())
        try:
            character_zone = ZoneInfo(str(timezone_name or "").strip())
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            character_zone = None
        if character_zone is not None:
            local_day_gap = (
                current[0].astimezone(character_zone).date()
                - previous[0].astimezone(character_zone).date()
            ).days

    result: dict[str, Any] = {
        "previousUserArrivedAt": previous_value,
        "currentUserArrivedAt": current_value,
        "elapsedSeconds": elapsed,
        "localDayGap": local_day_gap,
        "proactive": proactive_value,
        "userReturned": bool(
            not proactive_value
            and previous is not None
            and current is not None
            and current[0] >= previous[0]
        ),
    }
    topic = _resume_topic(user_intent)
    if topic and not proactive_value and elapsed != _UNKNOWN:
        result["resumeTopic"] = topic
    # ``local_now`` is an injected clock owned by the caller.  Touching it
    # here validates the contract without using it as a replacement for the
    # receipt's current arrival evidence (or inventing a first meeting).
    _utc_now(local_now)
    return result


def _string_ids(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _shared_loop_links(
    open_loops: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    now: datetime,
) -> dict[str, list[dict[str, str]]]:
    links: dict[str, list[dict[str, str]]] = defaultdict(list)
    normalized_session = str(session_id or "").strip()
    if not normalized_session:
        return links

    for raw_loop in open_loops:
        if not isinstance(raw_loop, Mapping):
            continue
        if str(raw_loop.get("sourceSessionId") or "").strip() != normalized_session:
            continue
        status = str(raw_loop.get("status") or "open").strip().lower()
        if status not in {"open", "resolved"}:
            continue
        if status == "open":
            expires_at = _parse_timestamp(raw_loop.get("expiresAt"))
            if expires_at is not None and _utc_now(now) > expires_at[0]:
                continue
        if not _string_ids(raw_loop.get("sourceTurnIds")):
            continue
        loop_id = _text(
            raw_loop.get("loopId") or raw_loop.get("openLoopId") or raw_loop.get("id"),
            limit=_MAX_LOOP_ID_LENGTH,
        )
        if not loop_id:
            continue
        topic_key = _text(raw_loop.get("topicKey"), limit=_MAX_TOPIC_KEY_LENGTH)
        for event_id in _string_ids(raw_loop.get("sourceEventIds")):
            links[event_id].append(
                {
                    "loopId": loop_id,
                    "topicKey": topic_key,
                    "status": status,
                }
            )
    return links


def _completed_event_candidate(
    raw_event: Mapping[str, Any],
    *,
    links: Mapping[str, list[dict[str, str]]],
    now: datetime,
) -> tuple[str, datetime, dict[str, str]] | None:
    event_id = _text(raw_event.get("eventId"), limit=_MAX_EVENT_ID_LENGTH)
    if not event_id or event_id not in links:
        return None
    if str(raw_event.get("kind") or "").strip().lower() != "activity_completed":
        return None
    outcome = raw_event.get("outcome")
    if not isinstance(outcome, Mapping):
        return None
    if str(outcome.get("status") or "").strip().lower() != "succeeded":
        return None
    # An inconsistent terminal event is not a trustworthy shared completion.
    top_level_status = str(raw_event.get("status") or "").strip().lower()
    if top_level_status in {"cancelled", "canceled", "failed", "skipped"}:
        return None
    occurred = _parse_timestamp(raw_event.get("occurredAt"))
    if occurred is None or occurred[0] > now:
        return None

    eligible_links = links[event_id]
    # Prefer a still-open loop if malformed duplicate rows point at both an
    # open and a resolved record; preserve input order within each state.
    link = next(
        (item for item in eligible_links if item.get("status") == "open"),
        eligible_links[0],
    )
    topic_key = _text(
        raw_event.get("topicKey") or link.get("topicKey"),
        limit=_MAX_TOPIC_KEY_LENGTH,
    )
    projected = {
        "eventId": event_id,
        "title": _text(raw_event.get("title") or "生活片段", limit=_MAX_TITLE_LENGTH),
        "outcomeSummary": _text(
            outcome.get("summary"),
            limit=_MAX_SUMMARY_LENGTH,
        ),
        "occurredAt": _text(occurred[1], limit=_MAX_OCCURRED_AT_LENGTH),
        "topicKey": topic_key,
        "loopId": _text(link.get("loopId"), limit=_MAX_LOOP_ID_LENGTH),
        "sourceKey": f"life-event:{event_id}",
        "factStatus": "completed",
    }
    return event_id, occurred[0], projected


def project_shared_experiences(
    *,
    open_loops: list,
    completed_events: list,
    session_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return recent successful events explicitly linked to this Companion session.

    An event is shared only when an eligible open/resolved loop from the same
    ``session_id`` references its exact ``sourceEventIds`` value.  The
    projection is bounded and read-only; it never turns a private life event,
    an expired loop, a plan, or an unsuccessful outcome into a shared fact.
    """

    links = _shared_loop_links(open_loops, session_id=session_id, now=now)
    if not links:
        return []
    current = _utc_now(now)
    by_event: dict[str, tuple[datetime, dict[str, str]]] = {}
    for raw_event in completed_events:
        if not isinstance(raw_event, Mapping):
            continue
        candidate = _completed_event_candidate(raw_event, links=links, now=current)
        if candidate is None:
            continue
        event_id, occurred, projected = candidate
        previous = by_event.get(event_id)
        if previous is None or occurred > previous[0]:
            by_event[event_id] = (occurred, projected)

    recent = sorted(
        by_event.values(),
        key=lambda item: (item[0], item[1]["eventId"]),
        reverse=True,
    )[:6]
    return [item[1] for item in recent]


__all__ = ["project_reunion_context", "project_shared_experiences"]
