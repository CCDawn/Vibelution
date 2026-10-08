from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from core.web.services.financial_backtest import data as backtest_data
from core.web.services.financial_backtest import engine
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestDataError,
    BacktestInputError,
    BacktestSnapshot,
    Candle,
    CorporateActionUnsupported,
)
from core.web.services.financial_backtest.engine import BacktestDecisionError


def _weekdays(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    result: list[str] = []
    while current <= last:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _wire_row(
    day: str,
    opening: float,
    *,
    close: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: int = 100_000,
) -> list[str]:
    close = opening if close is None else close
    high = max(opening, close) + 0.5 if high is None else high
    low = min(opening, close) - 0.5 if low is None else low
    return [day, f"{opening:.2f}", f"{close:.2f}", f"{high:.2f}", f"{low:.2f}", str(volume)]


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stock_rows: list[list[str]],
    calendar_rows: list[list[str]] | None = None,
    qfq_rows: list[list[str]] | None = None,
) -> list[tuple[str, str, str, str]]:
    requests: list[tuple[str, str, str, str]] = []
    qfq_rows = stock_rows if qfq_rows is None else qfq_rows
    calendar_rows = stock_rows if calendar_rows is None else calendar_rows

    def fetch(symbol: str, start: date, end: date, adjustment: str) -> list[list[str]]:
        requests.append((symbol, start.isoformat(), end.isoformat(), adjustment))
        rows = calendar_rows if symbol == "sh000001" else (qfq_rows if adjustment == "qfq" else stock_rows)
        return [row[:] for row in rows if start.isoformat() <= row[0] <= end.isoformat()]

    monkeypatch.setattr(backtest_data, "_fetch_window", fetch)
    return requests


def _prepared_rows(days: list[str]) -> tuple[list[list[str]], list[list[str]]]:
    stock = [_wire_row(day, 10 + index / 100) for index, day in enumerate(days)]
    calendar = [_wire_row(day, 3_000 + index) for index, day in enumerate(days)]
    return stock, calendar


def _candle(
    day: str,
    opening: float,
    *,
    close: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100_000,
) -> Candle:
    close = opening if close is None else close
    high = max(opening, close) + 1.0 if high is None else high
    low = min(opening, close) - 1.0 if low is None else low
    return Candle(day, opening, high, low, close, volume)


def _snapshot(
    candles: list[Candle] | tuple[Candle, ...],
    *,
    actions_status: str = "factor_check_passed",
    warmup: tuple[Candle, ...] = (),
) -> BacktestSnapshot:
    rows = tuple(candles)
    return BacktestSnapshot(
        symbol="sh600000",
        start_date=rows[0].date,
        end_date=rows[-1].date,
        candles=rows,
        warmup_candles=warmup,
        source="fixture",
        source_url="https://example.invalid/quote/sh600000",
        fetched_at="2024-01-10T16:00:00+08:00",
        data_hash=backtest_data._stable_hash(
            tuple(warmup) + rows, "sh600000", rows[0].date, rows[-1].date
        ),
        coverage=BacktestCoverage(
            requestedStartDate=rows[0].date,
            requestedEndDate=rows[-1].date,
            actualStartDate=rows[0].date,
            actualEndDate=rows[-1].date,
            availableStartDate=warmup[0].date if warmup else rows[0].date,
            availableEndDate=rows[-1].date,
            tradingDays=len(rows),
            warmupBars=len(warmup),
            providerWindows=(),
            tradingCalendarStatus="tencent_index_checked",
            calendarSymbol="sh000001",
            complete=True,
        ),
        actions_status=actions_status,
        action_dates=(),
        notice=(),
    )


def _trading_snapshot(
    prices: list[float], *, volumes: list[float] | None = None, days: list[str] | None = None
) -> BacktestSnapshot:
    if days is None:
        days = _weekdays("2024-01-02", "2024-01-31")[: len(prices)]
    volumes = [100_000] * len(prices) if volumes is None else volumes
    return _snapshot(
        [_candle(day, price, volume=volume) for day, price, volume in zip(days, prices, volumes, strict=True)]
    )


def _decisions(snapshot: BacktestSnapshot, weights: list[float]) -> list[dict[str, Any]]:
    schedule = engine.build_decision_schedule(snapshot, {"decisionInterval": 1})
    return [
        {"date": day, "targetWeight": weight, "reason": "测试决策"}
        for day, weight in zip(schedule, weights, strict=True)
    ]


def test_prepare_data_fetches_year_windows_and_keeps_complete_calendar_coverage(monkeypatch):
    days = ["2023-12-27", "2023-12-28", "2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04"]
    stock, calendar = _prepared_rows(days)
    requests = _install_provider(monkeypatch, stock_rows=stock, calendar_rows=calendar)

    snapshot = backtest_data.prepare_data(
        {
            "symbol": "600000",
            "startDate": "2023-12-29",
            "endDate": "2024-01-04",
            "warmupBars": 2,
        },
        today="2024-01-05",
    )

    assert snapshot.start_date == "2023-12-29"
    assert snapshot.end_date == "2024-01-04"
    assert [row.date for row in snapshot.warmup_candles] == ["2023-12-27", "2023-12-28"]
    assert snapshot.coverage.complete is True
    assert snapshot.coverage.tradingDays == 4
    assert snapshot.coverage.calendarSymbol == "sh000001"
    assert [window["calendarBars"] for window in snapshot.coverage.providerWindows] == [0, 0, 3, 3]
    assert {request[0] for request in requests} == {"sh600000", "sh000001"}
    assert snapshot.actions_status == "factor_check_passed"


def test_prepare_data_blocks_a_missing_stock_bar_in_the_middle(monkeypatch):
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    stock, _ = _prepared_rows([day for day in days if day != "2024-01-04"])
    _, calendar = _prepared_rows(days)
    _install_provider(monkeypatch, stock_rows=stock, calendar_rows=calendar)

    with pytest.raises(BacktestDataError, match="交易日历不一致") as captured:
        backtest_data.prepare_data(
            {"symbol": "600000", "startDate": days[0], "endDate": days[-1], "warmupBars": 0},
            today="2024-01-08",
        )

    assert captured.value.metadata["missingStockBarDates"] == ["2024-01-04"]
    assert captured.value.metadata["tradingCalendarStatus"] == "mismatch"


def test_prepare_data_blocks_qfq_transform_change_inside_selected_range(monkeypatch):
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    raw, calendar = _prepared_rows(days)
    qfq = []
    for index, row in enumerate(raw):
        offset = 1.0 if index < 2 else 2.0
        qfq.append([row[0], *(f"{float(value) + offset:.2f}" for value in row[1:5]), row[5]])
    _install_provider(monkeypatch, stock_rows=raw, calendar_rows=calendar, qfq_rows=qfq)

    with pytest.raises(CorporateActionUnsupported) as captured:
        backtest_data.prepare_data(
            {"symbol": "600000", "startDate": days[1], "endDate": days[-1], "warmupBars": 0},
            today="2024-01-08",
        )

    assert captured.value.action_dates == ("2024-01-04",)
    assert captured.value.metadata["actionsStatus"] == "blocked"


def test_snapshot_json_projection_round_trips_for_job_storage():
    candles = [_candle(day, 10.0) for day in _weekdays("2024-01-02", "2024-01-05")]
    original = _snapshot(candles, warmup=(_candle("2023-12-29", 9.9),))
    stored = json.loads(json.dumps(original.to_dict(), ensure_ascii=False))
    coverage_data = dict(stored["coverage"])
    coverage_data["providerWindows"] = tuple(coverage_data["providerWindows"])
    restored = BacktestSnapshot(
        symbol=stored["symbol"],
        start_date=stored["startDate"],
        end_date=stored["endDate"],
        candles=tuple(Candle(**row) for row in stored["candles"]),
        warmup_candles=tuple(Candle(**row) for row in stored["warmupCandles"]),
        source=stored["source"],
        source_url=stored["sourceUrl"],
        fetched_at=stored["fetchedAt"],
        data_hash=stored["dataHash"],
        coverage=BacktestCoverage(**coverage_data),
        actions_status=stored["actionsStatus"],
        action_dates=tuple(stored["actionDates"]),
        notice=tuple(stored["notice"]),
    )

    assert restored.to_dict() == stored
    assert engine.build_decision_schedule(restored, {"decisionInterval": 2}) == (
        "2024-01-02",
        "2024-01-04",
    )


def test_schedule_requires_verified_snapshot_and_excludes_last_unexecutable_close():
    snapshot = _trading_snapshot([10, 10.1, 10.2, 10.3])

    assert engine.build_decision_schedule(snapshot, {"decisionInterval": 2}) == (
        snapshot.candles[0].date,
        snapshot.candles[2].date,
    )
    with pytest.raises(BacktestDataError, match="公司行动状态未通过"):
        engine.build_decision_schedule(_snapshot(snapshot.candles, actions_status="unknown"))


def test_schedule_rejects_incomplete_coverage_tampered_bars_and_invalid_ohlc():
    snapshot = _trading_snapshot([10, 10.1, 10.2])
    incomplete = replace(
        snapshot,
        coverage=replace(snapshot.coverage, complete=False),
    )
    changed_candle = replace(snapshot.candles[0], close=10.01)
    tampered = replace(snapshot, candles=(changed_candle, *snapshot.candles[1:]))
    invalid_ohlc = replace(
        snapshot,
        candles=(replace(snapshot.candles[0], low=10.5), *snapshot.candles[1:]),
    )
    bad_coverage_count = replace(
        snapshot,
        coverage=replace(snapshot.coverage, tradingDays=99),
    )

    with pytest.raises(BacktestDataError, match="覆盖不完整"):
        engine.build_decision_schedule(incomplete)
    with pytest.raises(BacktestDataError, match="摘要校验失败"):
        engine.build_decision_schedule(tampered)
    with pytest.raises(BacktestDataError, match="OHLCV关系无效"):
        engine.build_decision_schedule(invalid_ohlc)
    with pytest.raises(BacktestDataError, match="覆盖边界与K线不一致"):
        engine.build_decision_schedule(bad_coverage_count)


def test_snapshot_rejects_warmup_candles_that_include_future_sessions():
    candle = _candle("2024-01-02", 10)
    snapshot = _snapshot([candle, _candle("2024-01-03", 10.1)], warmup=(candle,))

    with pytest.raises(BacktestDataError, match="日期重复或乱序"):
        engine.build_decision_schedule(snapshot)


def test_simulation_rejects_missing_decisions_instead_of_silently_holding():
    snapshot = _trading_snapshot([10, 10.2, 10.1])

    with pytest.raises(BacktestDecisionError, match="AI决策计划不完整"):
        engine.simulate(snapshot, {"decisionInterval": 1}, [])


def test_execution_uses_next_open_fees_slippage_lots_and_realized_trade_win_rate():
    snapshot = _trading_snapshot([10, 10, 11, 11])
    decisions = _decisions(snapshot, [1, 0, 0])

    result = engine.simulate(
        snapshot,
        {
            "decisionInterval": 1,
            "initialCash": 100_000,
            "commissionBps": 3,
            "minimumCommission": 5,
            "slippageBps": 5,
        },
        decisions,
    )

    assert [(trade["side"], trade["date"]) for trade in result["trades"]] == [
        ("buy", snapshot.candles[1].date),
        ("sell", snapshot.candles[2].date),
    ]
    assert all(trade["shares"] % 100 == 0 for trade in result["trades"])
    assert result["trades"][0]["price"] == 10.01
    assert result["trades"][1]["price"] == 10.99
    assert result["metrics"]["tradeCount"] == 2
    assert result["metrics"]["closedTradeCount"] == 1
    assert result["metrics"]["winningTradeCount"] == 1
    assert result["metrics"]["winRatePct"] == 100
    assert result["metrics"]["commissionFees"] == pytest.approx(62.37)
    assert result["metrics"]["stampDuty"] == pytest.approx(54.4)
    assert result["metrics"]["slippageCost"] == pytest.approx(198.0)


def test_minimum_commission_and_cash_limit_reduce_fill_by_whole_lots():
    snapshot = _trading_snapshot([20, 20, 20])
    decisions = _decisions(snapshot, [1, 1])

    result = engine.simulate(
        snapshot,
        {
            "decisionInterval": 1,
            "initialCash": 10_000,
            "commissionBps": 1,
            "minimumCommission": 5,
            "slippageBps": 0,
        },
        decisions,
    )

    assert result["trades"][0]["shares"] == 400
    assert result["trades"][0]["commission"] == 5


@pytest.mark.parametrize(
    ("execution_date", "side", "expected"),
    [
        ("2023-08-27", "sell", 0.001),
        ("2023-08-28", "sell", 0.0005),
        ("2023-08-28", "buy", 0.0),
        ("2008-04-23", "sell", 0.003),
        ("2008-04-24", "sell", 0.001),
        ("2008-09-19", "sell", 0.001),
        ("2008-09-19", "buy", 0.0),
    ],
)
def test_historical_stamp_duty_rate_is_applied_by_execution_date(execution_date, side, expected):
    assert float(engine._stamp_duty_rate(execution_date, side)) == expected


def test_slippage_is_bounded_by_daily_ohlc():
    candle = _candle("2024-01-03", 10, high=10.02, low=9.98)

    buy_price, buy_slippage = engine._execution_price(candle, "buy", engine.Decimal("0.01"))
    sell_price, sell_slippage = engine._execution_price(candle, "sell", engine.Decimal("0.01"))

    assert buy_price == engine.Decimal("10.02")
    assert buy_slippage == engine.Decimal("0.02")
    assert sell_price == engine.Decimal("9.98")
    assert sell_slippage == engine.Decimal("0.02")


@pytest.mark.parametrize(
    ("execution_candle", "expected_reason"),
    [
        (_candle("2024-01-03", 10, volume=0), "zero_volume_or_suspended"),
        (_candle("2024-01-03", 11, close=11, high=11, low=11), "one_price_at_candidate_limit_up"),
    ],
)
def test_unexecutable_zero_volume_and_candidate_locked_limit_are_rejected(
    execution_candle: Candle, expected_reason: str
):
    first = _candle("2024-01-02", 10)
    last = _candle("2024-01-04", 11)
    snapshot = _snapshot([first, execution_candle, last])
    result = engine.simulate(
        snapshot,
        {"decisionInterval": 1, "slippageBps": 0},
        _decisions(snapshot, [1, 1]),
    )

    assert result["orders"][0]["status"] == "rejected"
    assert result["orders"][0]["reason"] == expected_reason
    if expected_reason.startswith("one_price"):
        assert result["orders"][0]["limitStatus"] == "candidate_only_unverified"


def test_benchmark_retries_after_first_session_is_locked_then_holds_after_fill():
    snapshot = _snapshot(
        [
            _candle("2024-01-02", 10),
            _candle("2024-01-03", 11, close=11, high=11, low=11),
            _candle("2024-01-04", 10.8),
            _candle("2024-01-05", 10.9),
        ]
    )

    result = engine.simulate(
        snapshot,
        {"decisionInterval": 1, "slippageBps": 0},
        _decisions(snapshot, [0, 0, 0]),
    )

    assert [order["status"] for order in result["benchmarkOrders"]] == ["rejected", "filled"]
    assert [order["date"] for order in result["benchmarkOrders"]] == [
        "2024-01-03",
        "2024-01-04",
    ]
    assert result["equity"][2]["benchmarkShares"] > 0
    assert result["equity"][3]["benchmarkShares"] == result["equity"][2]["benchmarkShares"]
    assert engine.validate_benchmark(snapshot, {"decisionInterval": 1, "slippageBps": 0}) is None


def test_backtest_blocks_when_benchmark_never_finds_an_executable_open():
    snapshot = _snapshot(
        [
            _candle("2024-01-02", 10),
            _candle("2024-01-03", 11, close=11, high=11, low=11),
            _candle("2024-01-04", 12.1, close=12.1, high=12.1, low=12.1),
        ]
    )

    with pytest.raises(BacktestDataError, match="基准在所有后续开盘均无法成交") as captured:
        engine.simulate(
            snapshot,
            {"decisionInterval": 1, "slippageBps": 0},
            _decisions(snapshot, [0, 0]),
        )

    assert captured.value.metadata["benchmarkStatus"] == "unavailable"
    assert captured.value.metadata["benchmarkAttemptCount"] == 2
    assert captured.value.metadata["lastBenchmarkOrder"]["status"] == "rejected"
    assert captured.value.metadata["lastBenchmarkOrder"]["reason"] == "one_price_at_candidate_limit_up"


def test_benchmark_precheck_blocks_when_cash_cannot_buy_one_board_lot():
    snapshot = _trading_snapshot([2_000, 2_000, 2_000])

    with pytest.raises(BacktestDataError, match="基准在所有后续开盘均无法成交") as captured:
        engine.validate_benchmark(snapshot, {"decisionInterval": 1, "initialCash": 100_000})

    assert captured.value.metadata["benchmarkStatus"] == "unavailable"
    assert captured.value.metadata["lastBenchmarkOrder"]["reason"] == "insufficient_cash_for_one_lot"


def test_portfolio_at_is_invariant_to_future_candles():
    days = _weekdays("2024-01-02", "2024-01-10")[:6]
    common = [_candle(day, price) for day, price in zip(days[:5], [10, 10.2, 10.1, 10.5, 10.4], strict=True)]
    original = _snapshot([*common, _candle(days[5], 10.3)])
    changed_future = _snapshot([*common, _candle(days[5], 90, high=100, low=80)])
    decisions = [
        {"date": candle.date, "targetWeight": 0.5 if index % 2 == 0 else 0.25, "reason": "测试决策"}
        for index, candle in enumerate(common[:-1])
    ]

    original_portfolio = engine.portfolio_at(original, {"decisionInterval": 1}, decisions, common[-1].date)
    future_portfolio = engine.portfolio_at(changed_future, {"decisionInterval": 1}, decisions, common[-1].date)

    assert original_portfolio == future_portfolio


def test_metrics_win_rate_uses_closed_round_trips_not_one_sided_orders():
    snapshot = _trading_snapshot([10, 10, 11])
    result = engine.simulate(
        snapshot,
        {"decisionInterval": 2, "slippageBps": 0},
        [{"date": snapshot.candles[0].date, "targetWeight": 1, "reason": "买入后持有"}],
    )

    assert result["metrics"]["tradeCount"] == 1
    assert result["metrics"]["closedTradeCount"] == 0
    assert result["metrics"]["winRatePct"] is None


def test_invalid_dates_and_parameter_ranges_fail_closed():
    snapshot = _trading_snapshot([10, 10.1, 10.2])

    with pytest.raises(BacktestInputError):
        engine.build_decision_schedule(snapshot, {"decisionInterval": 0})
    with pytest.raises(BacktestInputError):
        engine.build_decision_schedule(snapshot, [])
    with pytest.raises(BacktestInputError):
        backtest_data.prepare_data(
            {"symbol": "600000", "startDate": "2024-01-05", "endDate": "2024-01-04", "warmupBars": 0},
            today="2024-01-08",
        )
