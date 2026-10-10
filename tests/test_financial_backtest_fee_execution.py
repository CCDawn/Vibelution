from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    portfolio_engine,
)
from core.web.services.financial_backtest.basket_data import BasketSnapshot
from core.web.services.financial_backtest.corporate_actions import (
    freeze_cash_dividend_artifact,
)
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestInputError,
    BacktestSnapshot,
    Candle,
)
from core.web.services.financial_backtest.fees import (
    LEGACY_FEE_MODEL,
    VERIFIED_FEE_MODEL,
)

_DAYS = ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
_DIVIDEND_DAYS = (
    "2024-04-09",
    "2024-04-10",
    "2024-04-11",
    "2024-04-12",
    "2024-04-15",
    "2024-04-16",
    "2024-04-17",
)


def _asset(
    symbol: str,
    days: tuple[str, ...] = _DAYS,
    price: float = 10,
    prices: tuple[float, ...] | None = None,
) -> BacktestSnapshot:
    marks = prices if prices is not None else (price,) * len(days)
    candles = tuple(
        Candle(day, mark, mark + 1, mark - 1, mark, 100_000)
        for day, mark in zip(days, marks, strict=True)
    )
    return BacktestSnapshot(
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
        notice=(),
    )


def _basket(*, days: tuple[str, ...] = _DAYS) -> BasketSnapshot:
    assets = {
        symbol: _asset(symbol, days)
        for symbol in ("sh600036", "sz000001")
    }
    symbols = tuple(sorted(assets))
    return BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=days,
        start_date=days[0],
        end_date=days[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, days, days[0], days[-1]
        ),
        source="fixture",
        notice=(),
    )


def _dividend_action() -> dict[str, object]:
    excerpt = "实施方案：每股派发现金红利0.50元。"
    raw_previous = {"open": "10.0", "high": "11.0", "low": "9.0", "close": "10.0"}
    raw_current = {"open": "9.5", "high": "10.5", "low": "8.5", "close": "9.5"}
    qfq_previous = {
        field: str(Decimal(value) - Decimal("0.50"))
        for field, value in raw_previous.items()
    }
    return freeze_cash_dividend_artifact(
        {
            "schemaVersion": 1,
            "ruleVersion": "ashare_cash_dividend_v1",
            "symbol": "sh600036",
            "coverageStartDate": _DIVIDEND_DAYS[0],
            "coverageEndDate": _DIVIDEND_DAYS[-1],
            "coverageStatus": "complete",
            "coverageEvidence": {
                "source": "cninfo",
                "queryStartDate": "2024-03-01",
                "queryEndDate": _DIVIDEND_DAYS[-1],
                "pagesRead": 1,
                "terminalPage": True,
                "noticeIds": ["1221234567"],
            },
            "priceValidation": {
                "detectedDates": ["2024-04-11"],
                "pairs": [
                    {
                        "exDate": "2024-04-11",
                        "previousDate": "2024-04-10",
                        "rawPrevious": raw_previous,
                        "rawCurrent": raw_current,
                        "qfqPrevious": qfq_previous,
                        "qfqCurrent": dict(raw_current),
                    }
                ],
            },
            "events": [
                {
                    "symbol": "sh600036",
                    "actionId": "action-2024-001",
                    "noticeId": "1221234567",
                    "publishedDate": "2024-03-20",
                    "sourceUrl": "https://static.cninfo.com.cn/finalpage/2024-03-20/1221234567.PDF",
                    "pdfSha256": "a" * 64,
                    "title": "2023年度权益分派实施公告",
                    "recordDate": "2024-04-10",
                    "exDate": "2024-04-11",
                    "paymentDate": "2024-04-15",
                    "cashPerShare": "0.50",
                    "stockDividendRatio": "0",
                    "capitalizationRatio": "0",
                    "evidencePages": [
                        {
                            "page": 2,
                            "excerpt": excerpt,
                            "excerptSha256": hashlib.sha256(
                                excerpt.encode("utf-8")
                            ).hexdigest(),
                        }
                    ],
                }
            ],
        }
    )


def _dividend_snapshot() -> BacktestSnapshot:
    asset = _asset(
        "sh600036",
        _DIVIDEND_DAYS,
        prices=(10, 10, 9.5, 9.5, 9.5, 10.01, 10.01),
    )
    action = _dividend_action()
    return replace(
        asset,
        data_hash=data._stable_hash(
            asset.candles, asset.symbol, asset.start_date, asset.end_date, action
        ),
        actions_status="verified_cash_dividends",
        action_dates=("2024-04-11",),
        corporate_actions=action,
    )


def _params(**overrides: object) -> dict[str, object]:
    return {
        "initialCash": 100_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 3,
        "minimumCommission": 5,
        "slippageBps": 0,
        "quantityRuleVersion": "ashare_quantity_v2",
        **overrides,
    }


def _single_decisions(
    snapshot: BacktestSnapshot,
    params: dict[str, object],
    weights: tuple[float, ...] = (1, 0, 0),
) -> list[dict[str, object]]:
    schedule = engine.build_decision_schedule(snapshot, params)
    return [
        {"date": day, "targetWeight": weight, "reason": "费用撮合测试"}
        for day, weight in zip(schedule, weights, strict=True)
    ]


def test_legacy_fee_model_keeps_omitted_and_explicit_replays_identical() -> None:
    snapshot = _asset("sh600036")
    params = _params()
    decisions = _single_decisions(snapshot, params)

    omitted = engine.simulate(snapshot, params, decisions)
    explicit = engine.simulate(
        snapshot, {**params, "feeModel": LEGACY_FEE_MODEL}, decisions
    )

    assert omitted == explicit
    assert "feeModel" not in omitted["parameters"]
    assert "transferFee" not in omitted["trades"][0]
    assert omitted["metrics"]["fees"] == pytest.approx(
        sum(trade["commission"] + trade["stampDuty"] for trade in omitted["trades"])
    )


def test_verified_single_backtest_charges_transfer_once_for_strategy_and_benchmark() -> None:
    snapshot = _asset("sh600036")
    params = _params(feeModel=VERIFIED_FEE_MODEL)
    decisions = _single_decisions(snapshot, params)

    result = engine.simulate(snapshot, params, decisions)
    buy, sell = result["trades"]
    benchmark_buy = next(
        order for order in result["benchmarkOrders"] if order["status"] == "filled"
    )

    assert result["parameters"]["feeModel"] == VERIFIED_FEE_MODEL
    assert buy["shares"] == sell["shares"] == 9_900
    assert buy["transferFee"] == pytest.approx(0.99)
    assert sell["transferFee"] == pytest.approx(0.99)
    assert buy["handlingFee"] == pytest.approx(3.38)
    assert buy["regulatoryFee"] == pytest.approx(1.98)
    assert buy["brokerCommission"] == pytest.approx(24.34)
    assert buy["commission"] == pytest.approx(
        buy["handlingFee"] + buy["regulatoryFee"] + buy["brokerCommission"]
    )
    assert buy["fee"] == pytest.approx(
        buy["commission"] + buy["transferFee"] + buy["stampDuty"]
    )
    assert result["metrics"]["fees"] == pytest.approx(
        sum(trade["fee"] for trade in result["trades"])
    )
    assert result["metrics"]["fees"] == pytest.approx(
        result["metrics"]["commissionFees"]
        + result["metrics"]["transferFees"]
        + result["metrics"]["stampDuty"]
    )
    assert result["metrics"]["transferFees"] == pytest.approx(1.98)
    assert result["metrics"]["benchmarkFees"] == pytest.approx(benchmark_buy["fee"])
    assert benchmark_buy["transferFee"] == pytest.approx(0.99)
    assert result["feePolicyAudit"]["feeModel"] == VERIFIED_FEE_MODEL

    prefix = engine.portfolio_at(snapshot, params, decisions[:2], "2024-01-04")
    assert prefix["cash"] == pytest.approx(result["equity"][2]["cash"])
    assert prefix["latestOrders"][-1]["transferFee"] == pytest.approx(0.99)


def test_verified_transfer_fee_is_included_in_roundtrip_cost_basis_and_proceeds() -> None:
    days = ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08")
    snapshot = _asset(
        "sh600036",
        days,
        prices=(10, 10, 10.01, 10.01, 10.01),
    )
    params = _params(
        initialCash=110_000,
        commissionBps=2.49,
        feeModel=VERIFIED_FEE_MODEL,
    )
    decisions = _single_decisions(
        snapshot, params, weights=(100_000 / 110_000, 0, 0, 0)
    )

    result = engine.simulate(snapshot, params, decisions)

    assert [trade["side"] for trade in result["trades"]] == ["buy", "sell"]
    assert result["trades"][0]["shares"] == 10_000
    assert result["trades"][0]["transferFee"] == pytest.approx(1.0)
    assert result["trades"][1]["transferFee"] == pytest.approx(1.0)
    # Before transfer costs, this 0.01-yuan rise would be a 0.13-yuan win.
    # Counting transfer on both the acquisition basis and sale proceeds makes it a loss.
    assert result["metrics"]["closedTradeCount"] == 1
    assert result["metrics"]["winRatePct"] == 0


def test_verified_transfer_fee_flows_through_cash_dividend_lot_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _dividend_snapshot()
    initial_cash = 110_000
    keep_weight = 95_000 / 109_974.1
    params = _params(
        initialCash=initial_cash,
        commissionBps=2.49,
        feeModel=VERIFIED_FEE_MODEL,
    )
    decisions = _single_decisions(
        snapshot,
        params,
        weights=(100_000 / initial_cash, keep_weight, keep_weight, keep_weight, 0, 0),
    )
    # Dividend mode intentionally suppresses price-only win-rate projection. Keep
    # the simulator's internal realized round-trip metric visible for this focused
    # fee-basis assertion.
    monkeypatch.setattr(engine, "_add_dividend_metrics", lambda *_args: None)

    result = engine.simulate(snapshot, params, decisions)

    assert result["trades"][0]["date"] == "2024-04-10"
    assert result["trades"][-1]["date"] == "2024-04-16"
    assert result["trades"][0]["transferFee"] == pytest.approx(1.0)
    assert result["trades"][-1]["transferFee"] == pytest.approx(1.0)
    assert Decimal(result["dividendAccounting"]["dividendsTotal"]) > 0
    # Ignoring the two transfer charges would make this price-only round trip
    # positive; the verified cost basis and sale proceeds correctly keep it a loss.
    assert result["metrics"]["closedTradeCount"] == 1
    assert result["metrics"]["winRatePct"] == 0


def test_verified_shared_cash_basket_and_benchmark_include_transfer_in_affordability() -> None:
    snapshot = _basket()
    params = _params(feeModel=VERIFIED_FEE_MODEL)
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)
    decisions = [
        {
            "date": day,
            "targetWeights": {"sh600036": weight, "sz000001": weight},
            "reason": "组合费用撮合测试",
        }
        for day, weight in zip(schedule, (0.5, 0, 0), strict=True)
    ]

    result = portfolio_engine.simulate(snapshot, params, decisions)
    strategy_fees = sum(Decimal(str(trade["fee"])) for trade in result["trades"])
    benchmark_fees = sum(
        Decimal(str(order["fee"]))
        for order in result["benchmarkOrders"]
        if order["status"] in {"filled", "partial_fill"}
    )

    assert {trade["symbol"] for trade in result["trades"]} == set(snapshot.symbols)
    assert result["metrics"]["fees"] == pytest.approx(float(strategy_fees))
    assert result["metrics"]["fees"] == pytest.approx(
        result["metrics"]["commissionFees"]
        + result["metrics"]["transferFees"]
        + result["metrics"]["stampDuty"]
    )
    assert result["metrics"]["benchmarkFees"] == pytest.approx(float(benchmark_fees))
    assert result["metrics"]["transferFees"] > 0
    assert result["feePolicyAudit"]["symbols"] == list(snapshot.symbols)

    prefix = portfolio_engine.portfolio_at(
        snapshot, params, decisions[:2], "2024-01-04"
    )
    assert prefix["cash"] == pytest.approx(result["equity"][2]["cash"])
    assert all("transferFee" in order for order in prefix["latestOrders"])


def test_verified_portfolio_at_adds_zero_fee_components_before_copying_latest_orders() -> None:
    snapshot = _basket()
    params = _params(feeModel=VERIFIED_FEE_MODEL)
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)

    for target_weight, expected_status in ((0.0, "no_action"), (0.0002, "rejected")):
        decisions = [
            {
                "date": day,
                "targetWeights": {
                    "sh600036": target_weight,
                    "sz000001": target_weight,
                },
                "reason": "零费用分项投影测试",
            }
            for day in schedule
        ]

        prefix = portfolio_engine.portfolio_at(
            snapshot, params, decisions[:2], "2024-01-04"
        )

        matching_orders = [
            order
            for order in prefix["latestOrders"]
            if order["status"] == expected_status
        ]
        assert matching_orders
        for order in matching_orders:
            assert order["transferFee"] == 0
            assert order["handlingFee"] == 0
            assert order["regulatoryFee"] == 0
            assert order["brokerCommission"] == 0


def test_verified_single_sale_rejects_when_fees_would_make_cash_negative() -> None:
    snapshot = _asset(
        "sh600036", prices=(10, 10, 1.01, 1.01)
    )
    params = _params(
        minimumCommission=10_000,
        feeModel=VERIFIED_FEE_MODEL,
    )
    decisions = _single_decisions(snapshot, params, weights=(1, 0, 0))

    result = engine.simulate(snapshot, params, decisions)

    rejected = [
        order
        for order in result["orders"]
        if order["reason"] == "insufficient_cash_for_sale_fees"
    ]
    assert rejected
    assert all(trade["side"] == "buy" for trade in result["trades"])
    assert result["equity"][-1]["cash"] >= 0
    assert result["equity"][-1]["cash"] == pytest.approx(
        result["equity"][-2]["cash"]
    )
    assert result["equity"][-1]["shares"] == result["equity"][-2]["shares"]


def test_verified_portfolio_sale_rejects_when_fees_would_make_shared_cash_negative() -> None:
    base = _basket()
    assets = dict(base.assets)
    assets["sh600036"] = _asset("sh600036", prices=(10, 10, 1.01, 1.01))
    snapshot = replace(
        base,
        assets=assets,
        data_hash=basket_data._stable_basket_hash(
            base.symbols,
            assets,
            base.session_dates,
            base.start_date,
            base.end_date,
        ),
    )
    params = _params(
        minimumCommission=10_000,
        feeModel=VERIFIED_FEE_MODEL,
    )
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)
    decisions = [
        {
            "date": day,
            "targetWeights": {
                "sh600036": 1 if index == 0 else 0,
                "sz000001": 0,
            },
            "reason": "高费率卖出现金保护测试",
        }
        for index, day in enumerate(schedule)
    ]

    result = portfolio_engine.simulate(snapshot, params, decisions)

    rejected = [
        order
        for order in result["orders"]
        if order["symbol"] == "sh600036"
        and order["reason"] == "insufficient_cash_for_sale_fees"
    ]
    assert rejected
    assert all(trade["side"] == "buy" for trade in result["trades"])
    assert result["equity"][-1]["cash"] >= 0
    assert result["equity"][-1]["cash"] == pytest.approx(
        result["equity"][-2]["cash"]
    )
    assert result["equity"][-1]["positions"]["sh600036"] == result["equity"][-2][
        "positions"
    ]["sh600036"]


def test_verified_model_fails_closed_for_unsupported_market_or_fee_window() -> None:
    params = _params(feeModel=VERIFIED_FEE_MODEL)
    with pytest.raises(BacktestInputError):
        engine.build_decision_schedule(_asset("bj430047"), params)

    old_days = ("2015-07-29", "2015-07-30", "2015-07-31", "2015-08-03")
    with pytest.raises(BacktestInputError):
        engine.build_decision_schedule(_asset("sh600036", old_days), params)
