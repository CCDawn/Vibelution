from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.web.services.financial_backtest import data as backtest_data
from core.web.services.financial_backtest import engine
from core.web.services.financial_backtest import quantity_rules
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestDataError,
    BacktestInputError,
    BacktestSnapshot,
    Candle,
    CorporateActionUnsupported,
)
from core.web.services.financial_backtest.engine import BacktestDecisionError


def test_benchmark_reserves_historical_buy_stamp_duty() -> None:
    cash, shares, order = engine._execute_benchmark(
        execution=Candle("2007-06-01", 10, 11, 9, 10, 100_000),
        previous_close=10,
        initial_cash=Decimal(10000),
        commission_rate=Decimal(0),
        minimum_commission=Decimal(5),
        slippage_rate=Decimal(0),
        symbol="sh600000",
    )
    assert shares == 900
    assert cash == Decimal(973)
    assert order["stampDuty"] == 27


def _snapshot_for_symbol(symbol: str, days: list[str]) -> BacktestSnapshot:
    candles = tuple(_candle(day, 10) for day in days)
    snapshot = _snapshot(candles)
    return replace(
        snapshot,
        symbol=symbol,
        source_url=f"https://example.invalid/quote/{symbol}",
        data_hash=backtest_data._stable_hash(candles, symbol, days[0], days[-1]),
    )


def _simulate_quantity_rule(
    symbol: str,
    weights: list[float],
    *,
    quantity_rule_version: str | None = "ashare_quantity_v2",
    days: list[str] | None = None,
    initial_cash: int = 100_000,
) -> dict[str, Any]:
    days = days or ["2024-01-02", "2024-01-03", "2024-01-04"]
    snapshot = _snapshot_for_symbol(symbol, days)
    params: dict[str, Any] = {
        "initialCash": initial_cash,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 0,
        "minimumCommission": 0,
        "slippageBps": 0,
    }
    if quantity_rule_version is not None:
        params["quantityRuleVersion"] = quantity_rule_version
    return engine.simulate(snapshot, params, _decisions(snapshot, weights))


@pytest.mark.parametrize(
    ("symbol", "weight", "expected_shares"),
    [
        ("sh600000", 0.0125, 100),
        ("sz300001", 0.0125, 100),
        ("sh688001", 0.0205, 205),
        ("bj430047", 0.0125, 125),
    ],
)
def test_ashare_quantity_rules_size_board_specific_buy_steps(
    symbol: str, weight: float, expected_shares: int
) -> None:
    result = _simulate_quantity_rule(symbol, [weight, weight])

    assert result["trades"][0]["shares"] == expected_shares


def test_star_market_sells_in_single_share_steps_and_closes_subminimum_target() -> None:
    partial = _simulate_quantity_rule("sh688001", [0.05, 0.0299])
    liquidation = _simulate_quantity_rule("sh688001", [0.025, 0.0199])

    assert [(trade["side"], trade["shares"]) for trade in partial["trades"]] == [
        ("buy", 500),
        ("sell", 201),
    ]
    assert [(trade["side"], trade["shares"]) for trade in liquidation["trades"]] == [
        ("buy", 250),
        ("sell", 250),
    ]


def test_missing_quantity_rule_version_preserves_legacy_100_share_replay() -> None:
    legacy = _simulate_quantity_rule(
        "sh688001", [0.0125, 0.0125], quantity_rule_version=None
    )
    current = _simulate_quantity_rule("sh688001", [0.0125, 0.0125])

    assert legacy["trades"][0]["shares"] == 100
    assert current["trades"] == []
    assert current["orders"][0]["status"] == "rejected"
    assert current["orders"][0]["reason"] == "below_board_minimum_buy"
    assert current["orders"][0]["requestedShares"] == 125


def test_current_quantity_contract_excludes_todays_buys_from_sellable_input() -> None:
    snapshot = _snapshot_for_symbol("sh600000", ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    params = {"initialCash": 100000, "maxPositionPct": 100, "decisionInterval": 1,
              "commissionBps": 0, "minimumCommission": 0, "slippageBps": 0,
              "quantityRuleVersion": "ashare_quantity_v2"}
    decisions = _decisions(snapshot, [0.4, 0.6, 0.6])
    first_purchase = engine.portfolio_at(snapshot, params, decisions[:1], "2024-01-03")
    assert first_purchase["shares"] == 4000
    assert first_purchase["sellableShares"] == 0
    added = engine.portfolio_at(snapshot, params, decisions[:2], "2024-01-04")
    assert added["shares"] == 6000
    assert added["sellableShares"] == 4000
    legacy = engine.portfolio_at(snapshot, {**params, "quantityRuleVersion": "legacy_100_v1"},
                                 decisions[:1], "2024-01-03")
    assert legacy["sellableShares"] == legacy["shares"]


@pytest.mark.parametrize(
    ("symbol", "held", "requested", "cap", "expected"),
    [
        ("sh600000", 250, 150, 150, 100),
        ("sh600000", 250, 250, 250, 250),
        ("sh688001", 250, 50, 50, 0),
        ("sh688001", 250, 250, 250, 250),
        ("bj430047", 150, 50, 50, 0),
        ("bj430047", 50, 50, 50, 50),
        ("sh688001", 250, 250, 199, 0),
    ],
)
def test_sell_residual_exception_requires_a_complete_sell_order(
    symbol: str, held: int, requested: int, cap: int, expected: int
) -> None:
    rule = quantity_rules.resolve_quantity_rule(
        symbol, "2024-01-03", "ashare_quantity_v2"
    )

    assert quantity_rules.floor_sell_quantity(requested, held, cap, rule) == expected


@pytest.mark.parametrize(
    ("execution_day", "expected_filled", "expected_reason"),
    [
        ("2020-08-21", 1_000_000, "next_session_open"),
        ("2020-08-24", 300_000, "order_quantity_limit"),
    ],
)
def test_chinext_limit_order_quantity_cap_uses_effective_date(
    execution_day: str, expected_filled: int, expected_reason: str
) -> None:
    signal_day = "2020-08-20" if execution_day == "2020-08-21" else "2020-08-21"
    next_day = "2020-08-24" if execution_day == "2020-08-21" else "2020-08-25"
    result = _simulate_quantity_rule(
        "sz300001",
        [1, 1],
        days=[signal_day, execution_day, next_day],
        initial_cash=10_000_000,
    )

    assert result["orders"][0]["filledShares"] == expected_filled
    assert result["orders"][0]["reason"] == expected_reason


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
    assert [window["calendarBars"] for window in snapshot.coverage.providerWindows] == [3, 3]
    assert len(requests) == 6
    assert [window["startDate"] for window in snapshot.coverage.providerWindows] == [
        "2023-01-01",
        "2024-01-01",
    ]
    assert {request[0] for request in requests} == {"sh600000", "sh000001"}
    assert snapshot.actions_status == "factor_check_passed"


def test_prepare_data_fetches_range_years_first_and_skips_unused_older_warmup_years(
    monkeypatch,
):
    days = _weekdays("2023-01-02", "2026-10-08")
    stock, calendar = _prepared_rows(days)
    requests = _install_provider(monkeypatch, stock_rows=stock, calendar_rows=calendar)

    snapshot = backtest_data.prepare_data(
        {
            "symbol": "600000",
            "startDate": "2024-10-09",
            "endDate": "2026-10-08",
            "warmupBars": 252,
        },
        today="2026-10-09",
    )

    assert len(snapshot.warmup_candles) == 252
    assert len(requests) == 12
    assert [request[1][:4] for request in requests] == [
        "2024",
        "2024",
        "2024",
        "2025",
        "2025",
        "2025",
        "2026",
        "2026",
        "2026",
        "2023",
        "2023",
        "2023",
    ]
    assert [
        (symbol, adjustment) for symbol, _start, _end, adjustment in requests
    ] == [(symbol, adjustment) for _ in range(4) for symbol, adjustment in (
        ("sh600000", "none"),
        ("sh600000", "qfq"),
        ("sh000001", "none"),
    )]
    assert [window["startDate"] for window in snapshot.coverage.providerWindows] == [
        "2023-01-01",
        "2024-01-01",
        "2025-01-01",
        "2026-01-01",
    ]


def test_prepare_data_still_blocks_missing_qfq_in_requested_year(monkeypatch):
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    stock, calendar = _prepared_rows(days)
    _install_provider(
        monkeypatch, stock_rows=stock, calendar_rows=calendar, qfq_rows=[]
    )

    with pytest.raises(BacktestDataError, match="raw/qfq 历史日期覆盖不一致"):
        backtest_data.prepare_data(
            {
                "symbol": "600000",
                "startDate": "2024-01-03",
                "endDate": "2024-01-05",
                "warmupBars": 1,
            },
            today="2024-01-08",
        )


def test_prepare_data_still_blocks_missing_qfq_in_required_warmup_year(monkeypatch):
    days = _weekdays("2023-01-02", "2024-10-11")
    stock, calendar = _prepared_rows(days)
    qfq = [row for row in stock if row[0].startswith("2024-")]
    _install_provider(
        monkeypatch, stock_rows=stock, calendar_rows=calendar, qfq_rows=qfq
    )

    with pytest.raises(BacktestDataError, match="raw/qfq 历史日期覆盖不一致"):
        backtest_data.prepare_data(
            {
                "symbol": "600000",
                "startDate": "2024-10-09",
                "endDate": "2024-10-11",
                "warmupBars": 252,
            },
            today="2024-10-14",
        )


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
    assert "maxParticipationPct" not in result["parameters"]


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


@pytest.mark.parametrize("value", [0, 0.09, 100.01, True, "not-a-number"])
def test_max_participation_pct_requires_a_number_between_point_one_and_one_hundred(value):
    with pytest.raises(BacktestInputError, match="maxParticipationPct"):
        engine._normalize_params({"maxParticipationPct": value})


@pytest.mark.parametrize("value", [0.1, 1, 100])
def test_max_participation_pct_accepts_inclusive_bounds(value):
    assert engine._normalize_params({"maxParticipationPct": value})[
        "maxParticipationPct"
    ] == Decimal(str(value))


def test_daily_volume_cap_partially_fills_one_strategy_and_benchmark_order():
    snapshot = _trading_snapshot(
        [10, 10, 10],
        volumes=[100_000, 100_000, 100_000],
    )
    result = engine.simulate(
        snapshot,
        {
            "decisionInterval": 1,
            "initialCash": 100_000,
            "commissionBps": 0,
            "minimumCommission": 0,
            "slippageBps": 0,
            "maxParticipationPct": 1,
        },
        _decisions(snapshot, [1, 0.1]),
    )

    strategy_order = result["orders"][0]
    assert strategy_order["status"] == "partial_fill"
    assert strategy_order["reason"] == "daily_volume_participation_limit"
    assert strategy_order["requestedShares"] == 10_000
    assert strategy_order["filledShares"] == 1_000
    assert result["trades"][0]["shares"] == 1_000
    assert result["parameters"]["maxParticipationPct"] == 1
    assert result["orders"][1]["status"] == "no_action"
    assert len(result["trades"]) == 1

    benchmark_order = result["benchmarkOrders"][0]
    assert benchmark_order["status"] == "partial_fill"
    assert benchmark_order["requestedShares"] == 10_000
    assert benchmark_order["filledShares"] == 1_000
    assert result["equity"][1]["benchmarkShares"] == 1_000
    assert "日线容量仅为近似" in " ".join(result["notice"])
    assert "开盘真实可成交" in " ".join(result["notice"])


def test_volume_cap_below_one_board_lot_rejects_without_losing_requested_shares():
    snapshot = _trading_snapshot(
        [10, 10, 10],
        volumes=[100_000, 9_999, 100_000],
    )
    result = engine.simulate(
        snapshot,
        {
            "decisionInterval": 1,
            "initialCash": 100_000,
            "commissionBps": 0,
            "minimumCommission": 0,
            "slippageBps": 0,
            "maxParticipationPct": 1,
        },
        _decisions(snapshot, [1, 0.1]),
    )

    order = result["orders"][0]
    assert order["status"] == "rejected"
    assert order["reason"] == "volume_participation_below_one_lot"
    assert order["requestedShares"] == 10_000
    assert order["filledShares"] == 0


def test_volume_limited_sell_is_partial_and_not_carried_as_a_pending_order():
    snapshot = _trading_snapshot(
        [10, 10, 10, 10],
        volumes=[100_000, 100_000, 50_000, 100_000],
    )
    result = engine.simulate(
        snapshot,
        {
            "decisionInterval": 1,
            "initialCash": 10_000,
            "commissionBps": 0,
            "minimumCommission": 0,
            "slippageBps": 0,
            "maxParticipationPct": 1,
        },
        _decisions(snapshot, [1, 0, 0.51]),
    )

    sell_order = next(order for order in result["orders"] if order["side"] == "sell")
    assert sell_order["status"] == "partial_fill"
    assert sell_order["reason"] == "daily_volume_participation_limit"
    assert sell_order["requestedShares"] == 1_000
    assert sell_order["filledShares"] == 500
    assert result["orders"][-1]["status"] == "no_action"
    assert sum(trade["shares"] for trade in result["trades"] if trade["side"] == "sell") == 500


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
