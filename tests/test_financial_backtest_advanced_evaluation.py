from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    portfolio_engine,
)
from core.web.services.financial_backtest.advanced_evaluation import (
    evaluate_cost_stress,
    evaluate_return_uncertainty,
)
from core.web.services.financial_backtest.basket_data import BasketSnapshot
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestInputError,
    BacktestSnapshot,
    Candle,
)


def _weekdays(start: str, count: int) -> list[str]:
    current = date.fromisoformat(start)
    result: list[str] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _asset(symbol: str, dates: list[str], *, base: float) -> BacktestSnapshot:
    candles = tuple(
        Candle(
            day,
            base + index * 0.02,
            base + index * 0.02 + 0.1,
            base + index * 0.02 - 0.1,
            base + index * 0.02,
            1_000_000,
        )
        for index, day in enumerate(dates)
    )
    return BacktestSnapshot(
        symbol=symbol,
        start_date=dates[0],
        end_date=dates[-1],
        candles=candles,
        warmup_candles=(),
        source="fixture",
        source_url=f"https://example.invalid/{symbol}",
        fetched_at="2026-10-10T15:00:00+08:00",
        data_hash=data._stable_hash(candles, symbol, dates[0], dates[-1]),
        coverage=BacktestCoverage(
            requestedStartDate=dates[0],
            requestedEndDate=dates[-1],
            actualStartDate=dates[0],
            actualEndDate=dates[-1],
            availableStartDate=dates[0],
            availableEndDate=dates[-1],
            tradingDays=len(dates),
            warmupBars=0,
            providerWindows=(),
            tradingCalendarStatus="tencent_index_checked",
            calendarSymbol="sh000001",
            complete=True,
        ),
        actions_status="factor_check_passed",
        action_dates=(),
        notice=(),
    )


def _single_snapshot(count: int = 6) -> BacktestSnapshot:
    dates = _weekdays("2026-01-05", count)
    return _asset("sh600000", dates, base=10)


def _basket_snapshot(count: int = 6) -> BasketSnapshot:
    dates = _weekdays("2026-01-05", count)
    symbols = ("sh600000", "sz000001")
    assets = {
        "sh600000": _asset("sh600000", dates, base=10),
        "sz000001": _asset("sz000001", dates, base=12),
    }
    return BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=tuple(dates),
        start_date=dates[0],
        end_date=dates[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, tuple(dates), dates[0], dates[-1]
        ),
        source="fixture",
        notice=(),
    )


def _params() -> dict[str, float | int]:
    return {
        "initialCash": 100_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 3,
        "minimumCommission": 5,
        "slippageBps": 5,
    }


def _public_single_decisions(snapshot: BacktestSnapshot) -> list[dict[str, object]]:
    return [
        {"date": day, "targetWeight": 100, "reason": "固定测试信号"}
        for day in engine.build_decision_schedule(snapshot, _params())
    ]


def _curve(count: int) -> list[dict[str, float | str]]:
    dates = _weekdays("2023-01-02", count)
    strategy = 100_000.0
    benchmark = 100_000.0
    rows: list[dict[str, float | str]] = []
    for index, day in enumerate(dates):
        strategy *= 1.0012 + (0.0002 if index % 3 == 0 else -0.0001)
        benchmark *= 1.0007 + (0.0001 if index % 4 == 0 else -0.00005)
        rows.append({"date": day, "equity": strategy, "benchmarkEquity": benchmark})
    return rows


def test_cost_stress_replays_identical_single_stock_decisions_and_scales_costs():
    snapshot = _single_snapshot()
    params = _params()
    decisions = _public_single_decisions(snapshot)
    before = [dict(item) for item in decisions]
    result = evaluate_cost_stress(
        snapshot,
        params,
        decisions,
        out_of_sample_start_date=None,
    )

    assert result["status"] == "available"
    assert [item["id"] for item in result["scenarios"]] == [
        "baseline",
        "cost_1_5x",
        "cost_2x",
    ]
    assert [item["commissionBps"] for item in result["scenarios"]] == [3, 4.5, 6]
    assert [item["minimumCommission"] for item in result["scenarios"]] == [5, 7.5, 10]
    assert [item["slippageBps"] for item in result["scenarios"]] == [5, 7.5, 10]
    assert (
        result["scenarios"][0]["metrics"]["fees"]
        < result["scenarios"][2]["metrics"]["fees"]
    )
    assert (
        result["scenarios"][0]["metrics"]["slippageCost"]
        < result["scenarios"][2]["metrics"]["slippageCost"]
    )
    assert decisions == before


def test_cost_stress_supports_shared_cash_portfolios():
    snapshot = _basket_snapshot()
    params = _params()
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)
    decisions = [
        {
            "date": day,
            "targetWeights": {"sh600000": 50, "sz000001": 50},
            "reason": "固定组合信号",
        }
        for day in schedule
    ]

    result = evaluate_cost_stress(
        snapshot, params, decisions, out_of_sample_start_date=None
    )

    assert result["status"] == "available"
    assert all(item["status"] == "available" for item in result["scenarios"])
    assert result["scenarios"][0]["metrics"]["tradeCount"] >= 1


def test_uncertainty_uses_only_frozen_oos_sessions_and_is_reproducible():
    rows = _curve(340)
    boundary = str(rows[20]["date"])
    result = evaluate_return_uncertainty(
        rows,
        initial_cash=100_000,
        out_of_sample_start_date=boundary,
    )

    assert result["status"] == "available"
    assert result["method"] == "newey_west_hac"
    assert result["observations"] == len(rows) - 20
    assert result["lowerPct"] <= result["pointEstimatePct"] <= result["upperPct"]
    assert result == evaluate_return_uncertainty(
        rows,
        initial_cash=100_000,
        out_of_sample_start_date=boundary,
    )


def test_uncertainty_withholds_interval_without_oos_or_with_short_sample():
    short = _curve(130)
    boundary = str(short[10]["date"])

    no_holdout = evaluate_return_uncertainty(
        short,
        initial_cash=100_000,
        out_of_sample_start_date=None,
    )
    too_short = evaluate_return_uncertainty(
        short,
        initial_cash=100_000,
        out_of_sample_start_date=boundary,
    )

    assert no_holdout["status"] == "unavailable"
    assert too_short["status"] == "insufficient_sample"
    assert too_short["observations"] == len(short) - 10
    assert too_short["lowerPct"] is None
    assert too_short["upperPct"] is None


def test_uncertainty_rejects_bad_boundary_and_nonpositive_equity():
    rows = _curve(300)
    with pytest.raises(BacktestInputError):
        evaluate_return_uncertainty(
            rows,
            initial_cash=100_000,
            out_of_sample_start_date=str(rows[0]["date"]),
        )
    invalid = [dict(row) for row in rows]
    invalid[150]["equity"] = 0
    with pytest.raises(BacktestInputError):
        evaluate_return_uncertainty(
            invalid,
            initial_cash=100_000,
            out_of_sample_start_date=str(rows[10]["date"]),
        )
