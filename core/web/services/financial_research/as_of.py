"""Keep research news and market snapshots from outrunning the chosen analysis date.

The stored user message stays as written. Tools and the model-facing copy of
that message use the latest 分析日期, 分析截至, or 研究日期 in the turn.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

_ANALYSIS_DATE = re.compile(
    r"(?:分析日期|分析截至|研究日期)\s*[:：]?\s*(?P<day>\d{4}-\d{2}-\d{2})"
)
_QUOTE_SENTENCE = re.compile(
    r"行情快照（[^，\n]{1,40}，可能延迟）：(?P<timestamp>[^，\n]{8,64})，价格 [^。\n]{1,120}。这是带时点的报价，不是已审核财报证据。"
)
_AS_OF: ContextVar[date | None] = ContextVar(
    "vibelution_research_analysis_date",
    default=None,
)


def analysis_date_in_text(text: object) -> date | None:
    found: date | None = None
    for match in _ANALYSIS_DATE.finditer(str(text or "")):
        try:
            found = date.fromisoformat(match.group("day"))
        except ValueError:
            continue
    return found


def explicit_iso_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def published_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    return parsed.date()


def on_or_before(value: object, cutoff: date | None) -> bool:
    if cutoff is None:
        return True
    published = published_date(value)
    return published is not None and published <= cutoff


def resolve_analysis_date(user_message: object = None, history: object = None) -> date | None:
    if isinstance(user_message, str):
        found = analysis_date_in_text(user_message)
        if found is not None:
            return found
    if isinstance(history, list):
        for message in reversed(history):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                found = analysis_date_in_text(content)
                if found is not None:
                    return found
    return None


def active_cutoff(explicit: object = None) -> date | None:
    dates: list[date] = []
    current = _AS_OF.get()
    if current is not None:
        dates.append(current)
    explicit_day = explicit_iso_date(explicit)
    if explicit_day is not None:
        dates.append(explicit_day)
    return min(dates) if dates else None


def screen_snapshot_usable(data_date: object, cutoff: date) -> bool:
    """A screen without a trade date is only usable on that same analysis day."""
    parsed = published_date(data_date)
    if parsed is not None:
        return parsed <= cutoff
    return cutoff >= datetime.now(ZoneInfo("Asia/Shanghai")).date()


def redact_research_prompt(text: object) -> object:
    if not isinstance(text, str) or "行情快照" not in text:
        return text
    analysis = analysis_date_in_text(text)
    if analysis is None:
        return text

    def replace(match: re.Match[str]) -> str:
        published = published_date(match.group("timestamp"))
        if published is not None and published <= analysis:
            return match.group(0)
        return f"行情快照晚于分析日期 {analysis.isoformat()}，未作为本次研究依据。"

    return _QUOTE_SENTENCE.sub(replace, text)


def redact_research_history(messages: object) -> object:
    if not isinstance(messages, list):
        return messages
    changed = False
    redacted: list[object] = []
    for message in messages:
        if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
            content = message.get("content")
            updated = redact_research_prompt(content)
            if updated != content:
                redacted.append({**message, "content": updated})
                changed = True
                continue
        redacted.append(message)
    return redacted if changed else messages


@contextmanager
def research_analysis_date_context(user_message: object = None, history: object = None):
    token: Token[date | None] = _AS_OF.set(resolve_analysis_date(user_message, history))
    try:
        yield
    finally:
        _AS_OF.reset(token)
