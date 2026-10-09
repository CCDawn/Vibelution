from datetime import date, timedelta

import pytest

from core.web.services.financial_market.trading_calendar import (
    OFFICIAL_CALENDAR_SOURCES,
    TradingCalendarUnavailable,
    is_a_share_trading_day,
    next_a_share_trading_day,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2024, 2, 8), True),
        (date(2024, 2, 9), False),
        (date(2025, 1, 1), False),
        (date(2025, 2, 5), True),
        (date(2025, 10, 8), False),
        (date(2025, 10, 9), True),
        (date(2026, 10, 7), False),
        (date(2026, 10, 8), True),
        (date(2026, 10, 10), False),
    ],
)
def test_official_exchange_notices_cover_2024_through_2026(value, expected):
    assert is_a_share_trading_day(value) is expected
    assert "sse.com.cn" in OFFICIAL_CALENDAR_SOURCES[value.year]


def test_next_trading_day_does_not_cross_unverified_year():
    with pytest.raises(TradingCalendarUnavailable, match="2027 年"):
        next_a_share_trading_day(date(2026, 12, 31) + timedelta(days=1))
