"""Unified ISO-8601 timestamp parsing for session-side time bases.

Session-layer writers historically used ``_now_timestamp()`` (naive
machine-local wall time) while workflow/journal writers emit tz-aware UTC.
Readers that sort, diff, or cross-compare those values must normalize both
generations onto one time base. Naive strings are therefore interpreted as
machine-local time (the legacy writer semantics) via ``datetime.astimezone()``
and converted to UTC; aware strings keep their own offset. Never hard-code a
UTC offset here: the machine's local offset comes from the platform.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_timestamp_utc(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp into a tz-aware UTC ``datetime``.

    Returns ``None`` for empty/unparseable input. Naive timestamps are treated
    as machine-local wall time; aware timestamps are converted from their own
    offset. The result is always ``timezone.utc``-aware so mixed legacy/new
    data compares and sorts correctly.
    """

    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)
