from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

import pytest

from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    portfolio_engine,
)
from core.web.services.financial_backtest.basket_data import BasketSnapshot
from core.web.services.financial_backtest.corporate_actions import (
    DividendLedger,
    freeze_cash_dividend_artifact,
)
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestSnapshot,
    Candle,
)

_DATES = (
    "2024-04-09",
    "2024-04-10",
    "2024-04-11",
    "2024-04-12",
    "2024-04-15",
    "2024-04-16",
    "2024-04-17",
)


def _event(symbol: str = "sh600036", cash_per_share: str = "0.50") -> dict[str, Any]:
    excerpt = "实施方案：每股派发现金红利0.50元。"
    return {
        "symbol": symbol,
        "actionId": "action-2024-001",
        "noticeId": "1221234567",
        "publishedDate": "2024-03-20",
        "sourceUrl": "https://static.cninfo.com.cn/finalpage/2024-03-20/1221234567.PDF",
        "pdfSha256": "a" * 64,
        "title": "2023年度权益分派实施公告",
        "recordDate": "2024-04-10",
        "exDate": "2024-04-11",
        "paymentDate": "2024-04-15",
        "cashPerShare": cash_per_share,
        "stockDividendRatio": "0",
        "capitalizationRatio": "0",
        "evidencePages": [
            {
                "page": 2,
                "excerpt": excerpt,
                "excerptSha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            }
        ],
    }


def _action_artifact(
    symbol: str = "sh600036",
    cash_per_share: str = "0.50",
    ex_price: str = "9.5",
    one_price_ex: bool = False,
) -> dict[str, Any]:
    raw_previous = {"open": "10.0", "high": "11.0", "low": "9.0", "close": "10.0"}
    raw_current = (
        {field: ex_price for field in ("open", "high", "low", "close")}
        if one_price_ex
        else {
            "open": ex_price,
            "high": str(Decimal(ex_price) + 1),
            "low": str(Decimal(ex_price) - 1),
            "close": ex_price,
        }
    )
    cash = Decimal(cash_per_share)
    qfq_previous = {
        field: str(Decimal(value) - cash) for field, value in raw_previous.items()
    }
    draft = {
        "schemaVersion": 1,
        "ruleVersion": "ashare_cash_dividend_v1",
        "symbol": symbol,
        "coverageStartDate": _DATES[0],
        "coverageEndDate": _DATES[-1],
        "coverageStatus": "complete",
        "coverageEvidence": {
            "source": "cninfo",
            "queryStartDate": "2024-03-01",
            "queryEndDate": _DATES[-1],
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
        "events": [_event(symbol, cash_per_share)],
    }
    return freeze_cash_dividend_artifact(draft)


def _snapshot(
    symbol: str = "sh600036",
    *,
    with_action: bool = True,
    cash_per_share: str = "0.50",
    ex_price: str = "9.5",
    one_price_ex: bool = False,
) -> BacktestSnapshot:
    prices = (
        (10, 10, float(ex_price), *([float(ex_price)] * (len(_DATES) - 3)))
        if with_action
        else (10,) * len(_DATES)
    )
    candles = tuple(
        Candle(
            day,
            price,
            price + 1,
            price - 1,
            price,
            100_000,
        )
        for day, price in zip(_DATES, prices, strict=True)
    )
    if with_action and one_price_ex:
        candles = tuple(
            Candle(day, float(ex_price), float(ex_price), float(ex_price), float(ex_price), 100_000)
            if day == "2024-04-11"
            else candle
            for day, candle in zip(_DATES, candles, strict=True)
        )
    action = (
        _action_artifact(symbol, cash_per_share, ex_price, one_price_ex)
        if with_action
        else None
    )
    return BacktestSnapshot(
        symbol=symbol,
        start_date=_DATES[0],
        end_date=_DATES[-1],
        candles=candles,
        warmup_candles=(),
        source="fixture",
        source_url=f"https://example.invalid/{symbol}",
        fetched_at="2024-04-17T16:00:00+08:00",
        data_hash=data._stable_hash(candles, symbol, _DATES[0], _DATES[-1], action),
        coverage=BacktestCoverage(
            requestedStartDate=_DATES[0],
            requestedEndDate=_DATES[-1],
            actualStartDate=_DATES[0],
            actualEndDate=_DATES[-1],
            availableStartDate=_DATES[0],
            availableEndDate=_DATES[-1],
            tradingDays=len(candles),
            warmupBars=0,
            providerWindows=(),
            tradingCalendarStatus="tencent_index_checked",
            calendarSymbol="sh000001",
            complete=True,
        ),
        actions_status="verified_cash_dividends" if action is not None else "factor_check_passed",
        action_dates=("2024-04-11",) if action is not None else (),
        notice=(),
        corporate_actions=action,
    )


def _params() -> dict[str, Any]:
    return {
        "initialCash": 10_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 0,
        "minimumCommission": 0,
        "slippageBps": 0,
    }


def _single_decisions(snapshot: BacktestSnapshot, sell_date: str) -> list[dict[str, Any]]:
    schedule = engine.build_decision_schedule(snapshot, _params())
    sell_signal_index = _DATES.index(sell_date) - 1
    return [
        {
            "date": day,
            "targetWeight": 1 if _DATES.index(day) < sell_signal_index else 0,
            "reason": "分红账本撮合回归",
        }
        for day in schedule
    ]


@pytest.mark.parametrize("sell_date", ["2024-04-12", "2024-04-16"])
def test_single_strategy_and_benchmark_account_for_dividend_and_deferred_tax(sell_date: str) -> None:
    snapshot = _snapshot()
    decisions = _single_decisions(snapshot, sell_date)

    prefix_date = sell_date
    prefix_schedule = tuple(day for day in engine.build_decision_schedule(snapshot, _params()) if day < prefix_date)
    prefix = engine.portfolio_at(snapshot, _params(), decisions[: len(prefix_schedule)], prefix_date)
    result = engine.simulate(snapshot, _params(), decisions)

    record_row = next(row for row in result["equity"] if row["date"] == "2024-04-10")
    ex_row = next(row for row in result["equity"] if row["date"] == "2024-04-11")
    payment_row = next(row for row in result["equity"] if row["date"] == "2024-04-15")
    assert record_row["dividendReceivable"] == 0
    assert ex_row["cash"] == 0
    assert ex_row["dividendReceivable"] == 500
    assert ex_row["equity"] == pytest.approx(10_000)
    assert ex_row["benchmarkDividendReceivable"] == 500
    assert ex_row["benchmarkEquity"] == pytest.approx(10_000)
    assert prefix["dividendReceivable"] == (500 if sell_date == "2024-04-12" else 0)
    assert prefix["dividendTaxPayable"] == (100 if sell_date == "2024-04-12" else 0)
    assert payment_row["dividendReceivable"] == 0
    assert payment_row["dividendTaxPayable"] == 0
    assert result["equity"][-1]["equity"] == pytest.approx(9_895.25)
    assert result["metrics"]["grossDividends"] == 500
    assert result["metrics"]["dividendTaxPaid"] == 100
    assert result["metrics"]["dividendTaxPayable"] == 0
    assert result["metrics"]["netDividendIncome"] == 400
    assert result["metrics"]["closedTradeCount"] is None
    assert result["metrics"]["winningTradeCount"] is None
    assert result["metrics"]["winRatePct"] is None
    assert Decimal(result["dividendAccounting"]["events"][0]["taxTotal"]) == Decimal(100)
    assert Decimal(result["benchmarkDividendAccounting"]["events"][0]["taxTotal"]) == Decimal(0)


def test_ex_right_limit_check_uses_cash_adjusted_reference_close() -> None:
    snapshot = _snapshot(
        cash_per_share="1.50",
        ex_price="9.0",
        one_price_ex=True,
    )
    ex_index = 2
    ex_candle = snapshot.candles[ex_index]
    reference_close = engine._execution_reference_close(snapshot, ex_index)

    assert Decimal(str(reference_close)) == Decimal("8.5")
    assert engine._is_locked(ex_candle, 10.0, "sell", snapshot.symbol) == (
        "one_price_at_candidate_limit_down"
    )
    assert engine._is_locked(ex_candle, reference_close, "sell", snapshot.symbol) is None

    decisions = _single_decisions(snapshot, "2024-04-11")
    result = engine.simulate(snapshot, _params(), decisions)
    ex_day_sell = next(
        order
        for order in result["orders"]
        if order["date"] == "2024-04-11" and order["side"] == "sell"
    )
    assert ex_day_sell["status"] == "filled"


def _basket_snapshot() -> BasketSnapshot:
    with_action = _snapshot("sh600036")
    without_action = _snapshot("sz000001", with_action=False)
    assets = {with_action.symbol: with_action, without_action.symbol: without_action}
    symbols = tuple(sorted(assets))
    return BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=_DATES,
        start_date=_DATES[0],
        end_date=_DATES[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, _DATES, _DATES[0], _DATES[-1]
        ),
        source="fixture",
        notice=(),
    )


def test_portfolio_and_prefix_replay_keep_symbol_ledgers_separate() -> None:
    snapshot = _basket_snapshot()
    params = _params()
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)
    target_weights = [
        {"sh600036": 1, "sz000001": 0},
        {"sh600036": 1, "sz000001": 0},
        {"sh600036": 0, "sz000001": 0},
        {"sh600036": 0, "sz000001": 0},
        {"sh600036": 0, "sz000001": 0},
        {"sh600036": 0, "sz000001": 0},
    ]
    decisions = [
        {"date": day, "targetWeights": weights, "reason": "组合分红账本回归"}
        for day, weights in zip(schedule, target_weights, strict=True)
    ]

    prefix_schedule = tuple(day for day in schedule if day < "2024-04-12")
    prefix = portfolio_engine.portfolio_at(
        snapshot, params, decisions[: len(prefix_schedule)], "2024-04-12"
    )
    result = portfolio_engine.simulate(snapshot, params, decisions)

    ex_row = next(row for row in result["equity"] if row["date"] == "2024-04-11")
    payment_row = next(row for row in result["equity"] if row["date"] == "2024-04-15")
    assert ex_row["dividendReceivable"] == 500
    assert ex_row["benchmarkDividendReceivable"] == 250
    assert ex_row["benchmarkEquity"] == pytest.approx(10_000)
    assert prefix["dividendReceivable"] == 500
    assert prefix["dividendTaxPayable"] == 100
    assert prefix["equity"] == pytest.approx(9_895.25)
    assert payment_row["dividendReceivable"] == 0
    assert payment_row["dividendTaxPayable"] == 0
    assert result["metrics"]["grossDividends"] == 500
    assert result["metrics"]["benchmarkGrossDividends"] == 250
    assert result["metrics"]["dividendTaxPaid"] == 100
    assert result["metrics"]["benchmarkDividendTaxPaid"] == 0
    assert result["metrics"]["winRatePct"] is None
    assert set(result["dividendAccounting"]) == {"sh600036"}
    assert set(result["benchmarkDividendAccounting"]) == {"sh600036"}


@pytest.mark.parametrize("scope", ["single", "portfolio"])
def test_dividend_sale_tax_cannot_make_cash_negative(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    monkeypatch.setattr(
        DividendLedger,
        "sell",
        lambda _ledger, _day, _shares: Decimal("100000.00"),
    )
    if scope == "single":
        snapshot = _snapshot()
        decisions = _single_decisions(snapshot, "2024-04-12")
    else:
        snapshot = _basket_snapshot()
        params = _params()
        schedule = portfolio_engine.build_decision_schedule(snapshot, params)
        target_weights = [
            {"sh600036": 1, "sz000001": 0},
            {"sh600036": 1, "sz000001": 0},
            {"sh600036": 0, "sz000001": 0},
            {"sh600036": 0, "sz000001": 0},
            {"sh600036": 0, "sz000001": 0},
            {"sh600036": 0, "sz000001": 0},
        ]
        decisions = [
            {
                "date": day,
                "targetWeights": weights,
                "reason": "红利税余额不足回归",
            }
            for day, weights in zip(schedule, target_weights, strict=True)
        ]

    with pytest.raises(engine.BacktestDecisionError, match="现金不足以支付") as error:
        if scope == "single":
            engine.simulate(snapshot, _params(), decisions)
        else:
            portfolio_engine.simulate(snapshot, params, decisions)

    metadata = error.value.metadata
    assert metadata["failure"] == "insufficient_cash_for_dividend_tax"
    assert metadata["symbol"] == "sh600036"
    assert metadata["date"] == "2024-04-12"
    assert Decimal(metadata["availableCash"]) > 0
    assert Decimal(metadata["dividendTaxDue"]) == Decimal("100000.00")
    assert Decimal(metadata["projectedCashAfterTax"]) < 0
    assert metadata["order"]["status"] in {"filled", "partial_fill"}
    if scope == "portfolio":
        assert metadata["order"]["symbol"] == "sh600036"
    assert metadata["trade"]["side"] == "sell"
    assert metadata["trade"]["fee"] == pytest.approx(
        metadata["trade"]["commission"] + metadata["trade"]["stampDuty"]
    )
