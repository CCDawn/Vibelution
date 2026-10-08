"""Deterministic contract tests for the read-only A-share MA backtest."""

from datetime import date, timedelta

import pytest

from core.web.services import financial_preferences_service
from core.web.services.financial_preferences_service import FinancialPreferenceError
from core.web.services.financial_report import backtest


TODAY = date(2026, 10, 8)


def _weekdays(start: date, count: int) -> list[str]:
    rows = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current.isoformat())
        current += timedelta(days=1)
    return rows


def _snapshot(
    closes: list[float],
    *,
    opens: list[float] | None = None,
    dates: list[str] | None = None,
    symbol: str = "sh600519",
    period: str = "day",
    adjustment: str = "qfq",
) -> dict:
    opens = opens or list(closes)
    dates = dates or _weekdays(date(2026, 9, 1), len(closes))
    candles = []
    for candle_date, opening, closing in zip(dates, opens, closes, strict=True):
        candles.append(
            {
                "date": candle_date,
                "open": opening,
                "close": closing,
                "high": max(opening, closing) + 1,
                "low": max(0.01, min(opening, closing) - 1),
            }
        )
    return {
        "stock": {"symbol": symbol},
        "candles": candles,
        "period": period,
        "adjustment": adjustment,
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/sh600519/gp",
        "fetchedAt": "2026-10-07T12:00:00+00:00",
        "candleError": "",
    }


def _payload(start: str, end: str, **overrides) -> dict:
    return {
        "symbol": "600519",
        "startDate": start,
        "endDate": end,
        "window": 5,
        **overrides,
    }


def test_signal_on_close_fills_at_next_session_open_and_marks_without_synthetic_close():
    dates = _weekdays(date(2026, 9, 1), 8)
    snapshot = _snapshot(
        [10, 10, 10, 10, 10, 20, 5, 5],
        opens=[10, 10, 10, 10, 10, 11, 20, 7],
        dates=dates,
    )

    result = backtest.calculate_backtest(
        snapshot, _payload(dates[5], dates[7]), today=TODAY
    )

    assert [(trade["signalDate"], trade["date"], trade["side"]) for trade in result["trades"]] == [
        (dates[5], dates[6], "buy"),
        (dates[6], dates[7], "sell"),
    ]
    assert result["trades"][0]["price"] == pytest.approx(20 * 1.0005)
    assert result["trades"][1]["price"] == pytest.approx(7 * 0.9995)
    assert result["trades"][0]["units"] > 0
    assert result["trades"][1]["units"] == pytest.approx(result["trades"][0]["units"])
    assert result["trades"][0]["fee"] > 0 and result["trades"][1]["fee"] > 0
    assert result["equity"][0]["equity"] == pytest.approx(100_000)
    assert len(result["equity"]) == 3
    assert result["metrics"]["tradeCount"] == 2
    assert result["metrics"]["fees"] == pytest.approx(sum(trade["fee"] for trade in result["trades"]))


def test_buy_and_hold_benchmark_pays_the_same_entry_costs():
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    payload = _payload(dates[5], dates[6])

    with_costs = backtest.calculate_backtest(snapshot, payload, today=TODAY)
    without_costs = backtest.calculate_backtest(
        snapshot,
        {**payload, "commissionBps": 0, "slippageBps": 0},
        today=TODAY,
    )

    assert with_costs["metrics"]["benchmarkFees"] > 0
    assert with_costs["metrics"]["benchmarkReturnPct"] < 0
    assert without_costs["metrics"]["benchmarkFees"] == 0
    assert without_costs["metrics"]["benchmarkReturnPct"] == pytest.approx(0)


def test_later_candles_do_not_change_results_through_requested_end():
    dates = _weekdays(date(2026, 9, 1), 15)
    closes = [10, 12, 9, 13, 11, 15, 8, 16, 10, 18, 7, 30, 2, 40, 1]
    snapshot = _snapshot(closes, dates=dates)
    payload = _payload(dates[5], dates[10])

    prefix = backtest.calculate_backtest(
        {**snapshot, "candles": snapshot["candles"][:11]}, payload, today=TODAY
    )
    full = backtest.calculate_backtest(snapshot, payload, today=TODAY)

    assert prefix == full


def test_today_candle_is_excluded_and_end_date_is_reported_as_aligned():
    dates = _weekdays(date(2026, 9, 29), 8)
    snapshot = _snapshot([10, 10, 10, 10, 10, 10, 10, 99_999], dates=dates)

    result = backtest.calculate_backtest(
        snapshot, _payload(dates[6], dates[7]), today=TODAY
    )

    assert result["endDate"] == "2026-10-07"
    assert all(row["date"] < TODAY.isoformat() for row in result["equity"])
    assert "endDate已按邻近交易日对齐" in result["notice"]


def test_weekend_end_date_aligns_to_nearest_available_session():
    dates = _weekdays(date(2026, 10, 1), 8)
    snapshot = _snapshot([10] * len(dates), dates=dates)

    result = backtest.calculate_backtest(
        snapshot,
        _payload(dates[5], "2026-10-10"),
        today=date(2026, 10, 13),
    )

    assert result["endDate"] == "2026-10-09"
    assert "endDate已按邻近交易日对齐为2026-10-09" in result["notice"]


def test_weekend_start_date_uses_following_session_and_never_prior_friday():
    dates = _weekdays(date(2026, 9, 21), 15)
    snapshot = _snapshot([10] * len(dates), dates=dates)

    result = backtest.calculate_backtest(
        snapshot,
        _payload("2026-10-04", dates[11]),
        today=TODAY,
    )

    assert dates[10] == "2026-10-05"
    assert result["startDate"] == "2026-10-05"
    assert result["startDate"] >= "2026-10-04"


def test_start_date_fails_when_only_a_pre_request_friday_is_available():
    dates = _weekdays(date(2026, 9, 21), 10)
    assert dates[-1] == "2026-10-02"
    snapshot = _snapshot([10] * len(dates), dates=dates)

    with pytest.raises(FinancialPreferenceError, match="startDate附近缺少日K覆盖"):
        backtest.calculate_backtest(
            snapshot,
            _payload("2026-10-04", "2026-10-05"),
            today=date(2026, 10, 8),
        )


def test_missing_data_or_old_range_is_rejected_without_truncating():
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    empty = {**snapshot, "candles": [], "candleError": "provider offline"}

    with pytest.raises(FinancialPreferenceError, match="数据不可用"):
        backtest.calculate_backtest(empty, _payload(dates[5], dates[6]), today=TODAY)
    with pytest.raises(FinancialPreferenceError, match="缺少日K覆盖"):
        backtest.calculate_backtest(
            snapshot,
            _payload("2026-01-01", dates[6]),
            today=TODAY,
        )
    with pytest.raises(FinancialPreferenceError, match="预热数据"):
        backtest.calculate_backtest(
            snapshot,
            _payload(dates[4], dates[6]),
            today=TODAY,
        )


def test_stale_source_after_long_holiday_rejects_uncovered_requested_end():
    dates = _weekdays(date(2026, 9, 21), 10)
    snapshot = _snapshot([10] * len(dates), dates=dates)

    with pytest.raises(FinancialPreferenceError, match="endDate附近缺少日K覆盖"):
        backtest.calculate_backtest(
            snapshot,
            _payload(dates[5], "2026-10-08"),
            today=date(2026, 10, 9),
        )


def test_wrong_symbol_period_and_adjustment_are_rejected():
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    payload = _payload(dates[5], dates[6])

    for invalid in (
        {**snapshot, "stock": {"symbol": "sz000001"}},
        {**snapshot, "period": "week"},
        {**snapshot, "adjustment": "raw"},
    ):
        with pytest.raises(FinancialPreferenceError):
            backtest.calculate_backtest(invalid, payload, today=TODAY)

    with pytest.raises(FinancialPreferenceError, match="仅支持 A 股"):
        backtest.calculate_backtest(
            snapshot,
            {**payload, "symbol": "hk00700"},
            today=TODAY,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(open=float("nan")),
        lambda row: row.update(close=float("inf")),
        lambda row: row.update(high=True),
        lambda row: row.update(low=0),
        lambda row: row.update(high=row["close"] - 1),
    ],
)
def test_nonfinite_boolean_nonpositive_or_inconsistent_ohlc_is_rejected(mutation):
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    mutation(snapshot["candles"][0])

    with pytest.raises(FinancialPreferenceError):
        backtest.calculate_backtest(
            snapshot, _payload(dates[5], dates[6]), today=TODAY
        )


def test_unsorted_or_duplicate_candle_dates_are_rejected():
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    snapshot["candles"][1]["date"] = snapshot["candles"][0]["date"]

    with pytest.raises(FinancialPreferenceError, match="严格递增且不能重复"):
        backtest.calculate_backtest(
            snapshot, _payload(dates[5], dates[6]), today=TODAY
        )


def test_run_backtest_checks_financial_agent_and_fetches_only_daily_snapshot(monkeypatch):
    dates = _weekdays(date(2026, 9, 1), 7)
    snapshot = _snapshot([10] * len(dates), dates=dates)
    agent_calls = []
    market_calls = []

    monkeypatch.setattr(
        financial_preferences_service,
        "_agent",
        lambda agent_id: agent_calls.append(agent_id) or {"agentId": agent_id},
    )
    monkeypatch.setattr(
        backtest.financial_market_service,
        "get_stock_snapshot",
        lambda symbol, period: market_calls.append((symbol, period)) or snapshot,
    )

    result = backtest.run_backtest(
        "finance-agent", _payload(dates[5], dates[6])
    )

    assert agent_calls == ["finance-agent"]
    assert market_calls == [("sh600519", "day")]
    assert result["adjustment"] == "qfq"
    assert result["source"] == "腾讯财经"
    assert result["sourceUrl"].startswith("https://")
    assert len(result["dataHash"]) == 64

    def reject_agent(agent_id):
        raise FinancialPreferenceError("当前金融助手不存在", 404)

    monkeypatch.setattr(financial_preferences_service, "_agent", reject_agent)
    with pytest.raises(FinancialPreferenceError) as error:
        backtest.run_backtest("missing-agent", _payload(dates[5], dates[6]))
    assert error.value.status_code == 404
    assert market_calls == [("sh600519", "day")]
