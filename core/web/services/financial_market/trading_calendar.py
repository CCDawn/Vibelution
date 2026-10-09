"""Verified A-share trading dates from published exchange closure notices.

The calendar deliberately covers only years for which the official SSE annual
closure notice has been checked. It does not infer holidays for other years.
The SSE notices state that days outside the listed closures open as usual;
ordinary Saturdays and Sundays remain closed.
"""

from __future__ import annotations

from datetime import date, timedelta


class TradingCalendarUnavailable(ValueError):
    """Raised when a requested date is outside verified exchange coverage."""

    def __init__(self, year: int) -> None:
        self.year = year
        super().__init__(f"A股交易日历尚未覆盖 {year} 年")


OFFICIAL_CALENDAR_SOURCES: dict[int, str] = {
    2024: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml",
    2025: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml",
    2026: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
}


def _dates(*ranges: tuple[str, str] | str) -> frozenset[date]:
    result: set[date] = set()
    for value in ranges:
        if isinstance(value, str):
            result.add(date.fromisoformat(value))
            continue
        start, end = (date.fromisoformat(item) for item in value)
        while start <= end:
            result.add(start)
            start += timedelta(days=1)
    return frozenset(result)


# Dates transcribed from the linked official annual notices. Ranges include
# weekend dates where the notice defines a full closure period; weekends are
# independently excluded by is_a_share_trading_day.
_CLOSED_DATES: dict[int, frozenset[date]] = {
    2024: _dates(
        ("2024-01-01", "2024-01-01"),
        ("2024-02-09", "2024-02-18"),
        ("2024-04-04", "2024-04-07"),
        ("2024-04-28", "2024-04-28"),
        ("2024-05-01", "2024-05-05"),
        ("2024-05-11", "2024-05-11"),
        ("2024-06-10", "2024-06-10"),
        ("2024-09-14", "2024-09-17"),
        ("2024-09-29", "2024-09-29"),
        ("2024-10-01", "2024-10-07"),
        ("2024-10-12", "2024-10-12"),
    ),
    2025: _dates(
        ("2025-01-01", "2025-01-01"),
        ("2025-01-26", "2025-01-26"),
        ("2025-01-28", "2025-02-04"),
        ("2025-02-08", "2025-02-08"),
        ("2025-04-04", "2025-04-06"),
        ("2025-04-27", "2025-04-27"),
        ("2025-05-01", "2025-05-05"),
        ("2025-05-31", "2025-06-02"),
        ("2025-09-28", "2025-09-28"),
        ("2025-10-01", "2025-10-08"),
        ("2025-10-11", "2025-10-11"),
    ),
    2026: _dates(
        ("2026-01-01", "2026-01-04"),
        ("2026-02-14", "2026-02-23"),
        ("2026-04-04", "2026-04-06"),
        ("2026-05-01", "2026-05-05"),
        ("2026-05-09", "2026-05-09"),
        ("2026-06-19", "2026-06-21"),
        ("2026-09-20", "2026-09-20"),
        ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    ),
}


def is_a_share_trading_day(value: date) -> bool:
    """Return the verified trading status; raise when the year is not covered."""

    closed_dates = _CLOSED_DATES.get(value.year)
    if closed_dates is None:
        raise TradingCalendarUnavailable(value.year)
    return value.weekday() < 5 and value not in closed_dates


def next_a_share_trading_day(value: date, *, max_days: int = 370) -> date:
    """Find the next covered trading day, refusing to cross an unknown year."""

    candidate = value
    for _ in range(max(1, max_days)):
        if is_a_share_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise TradingCalendarUnavailable(candidate.year)


__all__ = [
    "OFFICIAL_CALENDAR_SOURCES",
    "TradingCalendarUnavailable",
    "is_a_share_trading_day",
    "next_a_share_trading_day",
]
