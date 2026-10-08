from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from random import Random
from typing import Any

import pytest

from core.web.services.financial_backtest import basket_data, data, portfolio_engine
from core.web.services.financial_backtest.basket_data import BasketSnapshot
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestSnapshot,
    Candle,
)
from core.web.services.financial_backtest.engine import BacktestDecisionError
from core.web.services.financial_backtest.evaluation import evaluate_windows


def _weekdays(start: str, count: int) -> list[str]:
    current = date.fromisoformat(start)
    days: list[str] = []
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _basket(
    prices: dict[str, list[float]],
    *,
    days: list[str] | None = None,
    volumes: dict[str, list[float]] | None = None,
) -> BasketSnapshot:
    if days is None:
        days = _weekdays("2024-01-02", len(next(iter(prices.values()))))
    symbols = tuple(sorted(prices))
    assets: dict[str, BacktestSnapshot] = {}
    for symbol in symbols:
        values = prices[symbol]
        asset_volumes = (
            [100_000.0] * len(values) if volumes is None else volumes[symbol]
        )
        candles = tuple(
            Candle(day, value, value + 1, value - 1, value, volume)
            for day, value, volume in zip(days, values, asset_volumes, strict=True)
        )
        assets[symbol] = BacktestSnapshot(
            symbol=symbol,
            start_date=days[0],
            end_date=days[-1],
            candles=candles,
            warmup_candles=(),
            source="fixture",
            source_url=f"https://example.invalid/{symbol}",
            fetched_at="2024-01-08T16:00:00+08:00",
            data_hash=data._stable_hash(candles, symbol, days[0], days[-1]),
            coverage=BacktestCoverage(
                requestedStartDate=days[0],
                requestedEndDate=days[-1],
                actualStartDate=days[0],
                actualEndDate=days[-1],
                availableStartDate=days[0],
                availableEndDate=days[-1],
                tradingDays=len(candles),
                warmupBars=0,
                providerWindows=(),
                tradingCalendarStatus="tencent_index_checked",
                calendarSymbol="sh000001",
                complete=True,
            ),
            actions_status="factor_check_passed",
            action_dates=(),
            notice=("fixture notice",),
        )
    return BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=tuple(days),
        start_date=days[0],
        end_date=days[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, tuple(days), days[0], days[-1]
        ),
        source="fixture",
        notice=(),
    )


def _params(**overrides: Any) -> dict[str, Any]:
    return {
        "initialCash": 10_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 0,
        "minimumCommission": 5,
        "slippageBps": 0,
        **overrides,
    }


def _decisions(
    snapshot: BasketSnapshot,
    weight_rows: list[dict[str, float]],
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    schedule = portfolio_engine.build_decision_schedule(snapshot, params or _params())
    return [
        {"date": day, "targetWeights": weights, "reason": "测试组合决策"}
        for day, weights in zip(schedule, weight_rows, strict=True)
    ]


def test_shared_cash_competition_applies_fees_and_orders_buys_canonically():
    snapshot = _basket({"sh600001": [5, 5, 5], "sh600000": [5, 5, 5]})
    weights = {"sh600000": 0.5, "sh600001": 0.5}
    decisions = _decisions(snapshot, [weights, weights])

    result = portfolio_engine.simulate(
        snapshot,
        _params(commissionBps=1),
        decisions,
    )

    first_open_orders = [
        order
        for order in result["orders"]
        if order["date"] == snapshot.session_dates[1]
    ]
    assert [
        (order["symbol"], order["side"], order["status"]) for order in first_open_orders
    ] == [
        ("sh600000", "buy", "filled"),
        ("sh600001", "buy", "filled"),
    ]
    assert [
        (order["requestedShares"], order["filledShares"]) for order in first_open_orders
    ] == [
        (1_000, 1_000),
        (1_000, 900),
    ]
    assert first_open_orders[0]["commission"] == 5
    assert first_open_orders[1]["fee"] == 5
    assert first_open_orders[1]["notional"] == 4_500
    assert result["equity"][1]["cash"] == 490
    assert result["equity"][1]["equity"] == 9_990
    assert all(row["cash"] >= 0 for row in result["equity"])
    assert all(trade["symbol"] in snapshot.symbols for trade in result["trades"])


def test_benchmark_starts_at_same_next_open_and_holdout_baseline_as_strategy():
    snapshot = _basket({"sh600000": [10, 10, 10], "sh600001": [10, 10, 10]})
    assets = dict(snapshot.assets)
    for symbol, asset in assets.items():
        candles = (replace(asset.candles[0], open=9), *asset.candles[1:])
        assets[symbol] = replace(
            asset,
            candles=candles,
            data_hash=data._stable_hash(
                candles,
                symbol,
                asset.start_date,
                asset.end_date,
            ),
        )
    snapshot = replace(
        snapshot,
        assets=assets,
        data_hash=basket_data._stable_basket_hash(
            snapshot.symbols,
            assets,
            snapshot.session_dates,
            snapshot.start_date,
            snapshot.end_date,
        ),
    )
    weights = {symbol: 0.5 for symbol in snapshot.symbols}
    result = portfolio_engine.simulate(
        snapshot, _params(), _decisions(snapshot, [weights, weights])
    )
    assert result["equity"][0]["benchmarkEquity"] == 10_000
    assert result["equity"][0]["equity"] == 10_000
    assert result["benchmarkOrders"][0]["date"] == snapshot.session_dates[1]
    windows = evaluate_windows(
        result["equity"],
        result["orders"],
        initial_cash=10_000,
        out_of_sample_start_date=snapshot.session_dates[1],
    )
    assert windows["outOfSample"]["startingBenchmarkEquity"] == 10_000
    assert windows["outOfSample"]["metrics"]["excessReturnPct"] == 0


def test_rebalance_sells_before_buying_and_reuses_only_realized_shared_cash():
    snapshot = _basket({"sh600000": [10, 10, 10, 10], "sh600001": [10, 10, 10, 10]})
    decisions = _decisions(
        snapshot,
        [
            {"sh600000": 0.5, "sh600001": 0.5},
            {"sh600000": 0, "sh600001": 1},
            {"sh600000": 0, "sh600001": 1},
        ],
    )

    result = portfolio_engine.simulate(snapshot, _params(), decisions)

    rebalance_orders = [
        order
        for order in result["orders"]
        if order["date"] == snapshot.session_dates[2]
    ]
    assert [(order["symbol"], order["side"]) for order in rebalance_orders] == [
        ("sh600000", "sell"),
        ("sh600001", "buy"),
    ]
    assert rebalance_orders[0]["stampDuty"] == 2.5
    assert rebalance_orders[0]["notional"] == 5_000
    assert rebalance_orders[1]["requestedShares"] == 500
    assert rebalance_orders[1]["filledShares"] == 400
    assert result["equity"][2]["cash"] == 997.5
    assert result["equity"][2]["positions"] == {"sh600000": 0, "sh600001": 900}
    assert all(row["cash"] >= 0 for row in result["equity"])


def test_portfolio_at_is_invariant_to_future_prices_and_returns_position_details():
    days = _weekdays("2024-01-02", 4)
    prices = {"sh600000": [10, 10, 11, 12], "sh600001": [20, 20, 22, 30]}
    original = _basket(prices, days=days)
    changed = _basket(
        {"sh600000": [10, 10, 11, 120], "sh600001": [20, 20, 22, 300]}, days=days
    )
    weights = {"sh600000": 0.4, "sh600001": 0.4}
    decisions = _decisions(original, [weights, weights, weights])
    original_at = portfolio_engine.portfolio_at(
        original, _params(), decisions[:1], days[1]
    )
    changed_at = portfolio_engine.portfolio_at(
        changed, _params(), decisions[:1], days[1]
    )

    assert original_at == changed_at
    assert original_at["date"] == days[1]
    assert set(original_at) >= {"cash", "equity", "positions"}
    assert [row["symbol"] for row in original_at["positions"]] == list(original.symbols)
    assert all(
        {"symbol", "shares", "sellableShares", "marketValue", "weightPct", "close"}
        <= set(row)
        for row in original_at["positions"]
    )
    assert all(
        row["shares"] > 0 and row["sellableShares"] == 0
        for row in original_at["positions"]
    )


def test_unfilled_benchmark_ticker_keeps_cash_sleeve_without_blocking_result():
    snapshot = _basket(
        {"sh600000": [10, 10, 10], "sh600001": [10, 10, 10]},
        volumes={"sh600000": [0, 0, 0], "sh600001": [100_000, 100_000, 100_000]},
    )
    zero_weights = {"sh600000": 0, "sh600001": 0}
    decisions = _decisions(snapshot, [zero_weights, zero_weights])

    result = portfolio_engine.simulate(snapshot, _params(), decisions)

    assert result["benchmarkStatus"] == "partial_cash_sleeves"
    assert result["unfilledBenchmarkSymbols"] == ["sh600000"]
    assert [
        (order["symbol"], order["status"], order["reason"])
        for order in result["benchmarkOrders"][:2]
    ] == [
        ("sh600000", "rejected", "zero_volume_or_suspended"),
        ("sh600001", "filled", "same_cost_buy_and_hold_benchmark"),
    ]
    assert result["equity"][-1]["benchmarkPositions"]["sh600001"] > 0
    assert result["equity"][-1]["benchmarkCash"] >= 5_000


def test_benchmark_buy_reserves_historical_stamp_duty_inside_its_cash_sleeve():
    days = ["2007-06-01", "2007-06-04", "2007-06-05"]
    snapshot = _basket({"sh600000": [10, 10, 10]}, days=days)
    zero_weights = {"sh600000": 0}
    decisions = _decisions(snapshot, [zero_weights, zero_weights])

    result = portfolio_engine.simulate(snapshot, _params(), decisions)

    first_order = result["benchmarkOrders"][0]
    assert first_order["status"] == "filled"
    assert first_order["requestedShares"] == 1_000
    assert first_order["filledShares"] == 900
    assert first_order["stampDuty"] == 27
    assert result["equity"][1]["benchmarkCash"] == 973
    assert all(row["benchmarkCash"] >= 0 for row in result["equity"])


def test_varied_rebalances_conserve_cash_shares_and_marked_equity():
    random = Random(19)
    symbols = ("sh600000", "sh600001", "sz000001")
    for _ in range(20):
        prices = {
            symbol: [round(random.uniform(8, 16), 2) for _ in range(8)]
            for symbol in symbols
        }
        snapshot = _basket(prices)
        weights = []
        for _ in range(7):
            # Retain cash while varying concentration and the direction of trades.
            scores = [random.randint(0, 5) for _ in symbols]
            denominator = sum(scores) + 1
            weights.append(
                {
                    symbol: score / denominator
                    for symbol, score in zip(symbols, scores, strict=True)
                }
            )
        result = portfolio_engine.simulate(
            snapshot,
            _params(commissionBps=3, slippageBps=5),
            _decisions(snapshot, weights),
        )
        expected_cash = 10_000.0
        expected_shares = dict.fromkeys(symbols, 0)
        total_fees = 0.0
        for index, row in enumerate(result["equity"]):
            for order in result["orders"]:
                if order["date"] != row["date"] or order["status"] != "filled":
                    continue
                sign = 1 if order["side"] == "buy" else -1
                expected_shares[order["symbol"]] += sign * order["filledShares"]
                expected_cash -= sign * order["notional"] + order["fee"]
                total_fees += order["fee"]
            assert row["cash"] >= 0
            assert row["cash"] == pytest.approx(expected_cash, abs=0.011)
            assert row["positions"] == expected_shares
            assert all(
                shares >= 0 and shares % 100 == 0 for shares in expected_shares.values()
            )
            value = expected_cash + sum(
                expected_shares[symbol] * prices[symbol][index] for symbol in symbols
            )
            assert row["equity"] == pytest.approx(value, abs=0.011)
        assert result["metrics"]["fees"] == pytest.approx(total_fees)


def test_decision_weights_must_cover_every_symbol_and_respect_limits():
    snapshot = _basket({"sh600000": [10, 10, 10], "sh600001": [10, 10, 10]})
    schedule = portfolio_engine.build_decision_schedule(snapshot, _params())
    incomplete = [
        {"date": day, "targetWeights": {"sh600000": 0.5}, "reason": "不完整"}
        for day in schedule
    ]
    over_budget = [
        {
            "date": day,
            "targetWeights": {"sh600000": 0.6, "sh600001": 0.5},
            "reason": "权重超限",
        }
        for day in schedule
    ]
    over_position_cap = [
        {
            "date": day,
            "targetWeights": {"sh600000": 0.6, "sh600001": 0},
            "reason": "单票超限",
        }
        for day in schedule
    ]

    with pytest.raises(BacktestDecisionError, match="完整覆盖"):
        portfolio_engine.simulate(snapshot, _params(), incomplete)
    with pytest.raises(BacktestDecisionError, match="权重之和"):
        portfolio_engine.simulate(snapshot, _params(), over_budget)
    with pytest.raises(BacktestDecisionError, match="最大仓位上限"):
        portfolio_engine.simulate(
            snapshot, _params(maxPositionPct=50), over_position_cap
        )
