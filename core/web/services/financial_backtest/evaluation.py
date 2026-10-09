"""Evaluate a predeclared holdout without resetting either simulated account."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from .data import BacktestInputError
from .metrics import calculate_metrics


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是有限数值")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是有限数值") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise BacktestInputError(f"{label}必须是有效的非负数值")
    return number


def _window(
    rows: list[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    *,
    initial_equity: float,
    initial_benchmark: float,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    first, last = str(rows[0]["date"]), str(rows[-1]["date"])
    fills = [
        order
        for order in orders
        if first <= str(order.get("date", "")) <= last
        and order.get("status") in {"filled", "partial_fill"}
        and int(order.get("filledShares", 0)) > 0
    ]

    def total(key: str) -> float:
        return sum(_finite(order.get(key, 0), key) for order in fills)

    metrics = calculate_metrics(
        ([baseline] if baseline is not None else []) + rows,
        initial_cash=initial_equity,
        benchmark_initial_cash=initial_benchmark,
        trade_count=len(fills),
        closed_trade_count=0,
        winning_trade_count=0,
        gross_turnover=total("notional"),
        total_fees=total("fee"),
        commission_fees=total("commission"),
        stamp_duty=total("stampDuty"),
    )
    # Window return includes carried positions. A sold lot can have been bought
    # before this window, so do not invent a window-local realized win rate.
    for key in ("closedTradeCount", "winningTradeCount", "winRatePct"):
        metrics.pop(key)
    return {
        "startDate": first,
        "endDate": last,
        "baselineDate": str(baseline["date"]) if baseline is not None else None,
        "startingEquity": initial_equity,
        "startingBenchmarkEquity": initial_benchmark,
        "tradingDays": len(rows),
        "metrics": metrics,
    }


def evaluate_windows(
    equity: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    out_of_sample_start_date: str,
) -> dict[str, Any]:
    """The split must be frozen in preview/run parameters by the caller.

    The boundary is included only in the out-of-sample period. Its previous
    close is a valuation baseline, not a second counted trade/session.
    """
    initial_cash = _finite(initial_cash, "initialCash", positive=True)
    rows = list(equity)
    dates: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise BacktestInputError("评估净值行必须是对象")
        raw_date = row.get("date")
        try:
            parsed = date.fromisoformat(raw_date)
        except (ValueError, TypeError) as exc:
            raise BacktestInputError("评估净值日期无效") from exc
        if parsed.isoformat() != raw_date or (dates and raw_date <= dates[-1]):
            raise BacktestInputError("评估净值日期必须严格递增且不重复")
        dates.append(raw_date)
        _finite(row.get("equity"), "equity")
        _finite(row.get("benchmarkEquity"), "benchmarkEquity")
    if (
        out_of_sample_start_date not in dates
        or dates.index(out_of_sample_start_date) == 0
    ):
        raise BacktestInputError(
            "样本外起点必须是区间内的交易日，且前面至少保留一个交易日"
        )
    boundary = dates.index(out_of_sample_start_date)
    baseline = rows[boundary - 1]
    starting_equity = _finite(baseline["equity"], "样本外起始净值", positive=True)
    starting_benchmark = _finite(
        baseline["benchmarkEquity"], "样本外基准起始净值", positive=True
    )
    return {
        "outOfSampleStartDate": out_of_sample_start_date,
        "inSample": _window(
            rows[:boundary],
            orders,
            initial_equity=initial_cash,
            initial_benchmark=initial_cash,
        ),
        "outOfSample": _window(
            rows[boundary:],
            orders,
            initial_equity=starting_equity,
            initial_benchmark=starting_benchmark,
            baseline=baseline,
        ),
        "notice": "连续账户按预先冻结日期分段；样本外以前一交易日收盘净值为基准，不重置现金。分段结果不构成前瞻收益证明。",
    }
