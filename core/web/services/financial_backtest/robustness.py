"""Descriptive robustness slices for a completed historical backtest."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from .data import BacktestInputError
from .evaluation import _finite, _window

_WINDOW_SIZE = 63
_MIN_COMPLETE_WINDOWS = 4
_METRIC_KEYS = (
    "totalReturnPct",
    "benchmarkReturnPct",
    "excessReturnPct",
    "maxDrawdownPct",
    "fees",
    "tradeCount",
)


def evaluate_robustness(
    equity: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    out_of_sample_start_date: str | None = None,
) -> dict[str, Any]:
    """Summarize calendar-year and fixed 63-session slices of a frozen run.

    A frozen holdout limits the summary to its out-of-sample sessions. Without
    one, the function labels the full-period result as retrospective. Every
    slice uses the prior close as a valuation baseline while keeping the
    account continuous; these slices are descriptive, not independent runs.
    """
    initial_cash = _finite(initial_cash, "initialCash", positive=True)
    rows = _validate_equity(equity)
    dates = [str(row["date"]) for row in rows]
    order_rows = _validate_orders(orders, set(dates))

    if out_of_sample_start_date is None:
        scope = "full_period"
        first_index = 0
    else:
        if not isinstance(out_of_sample_start_date, str):
            raise BacktestInputError("样本外起点必须是有效交易日")
        try:
            parsed_start = date.fromisoformat(out_of_sample_start_date)
        except ValueError as exc:
            raise BacktestInputError("样本外起点必须是有效交易日") from exc
        if parsed_start.isoformat() != out_of_sample_start_date:
            raise BacktestInputError("样本外起点必须是有效交易日")
        if out_of_sample_start_date not in dates:
            raise BacktestInputError("样本外起点必须是区间内的交易日")
        first_index = dates.index(out_of_sample_start_date)
        if first_index == 0:
            raise BacktestInputError("样本外起点前必须至少保留一个交易日")
        scope = "out_of_sample"

    evaluated_rows = rows[first_index:]
    if not evaluated_rows:
        raise BacktestInputError("稳健性评估区间不能为空")

    fixed_windows: list[dict[str, Any]] = []
    for offset in range(0, len(evaluated_rows), _WINDOW_SIZE):
        global_start = first_index + offset
        window_rows = evaluated_rows[offset : offset + _WINDOW_SIZE]
        complete = len(window_rows) == _WINDOW_SIZE
        fixed_windows.append(
            _window_record(
                f"63交易日窗 {len(fixed_windows) + 1}",
                window_rows,
                global_start=global_start,
                all_rows=rows,
                orders=order_rows,
                initial_cash=initial_cash,
                complete=complete,
            )
        )

    annual_windows: list[dict[str, Any]] = []
    group_start = first_index
    while group_start < len(rows):
        year = dates[group_start][:4]
        group_end = group_start + 1
        while group_end < len(rows) and dates[group_end][:4] == year:
            group_end += 1
        annual_windows.append(
            _window_record(
                year,
                rows[group_start:group_end],
                global_start=group_start,
                all_rows=rows,
                orders=order_rows,
                initial_cash=initial_cash,
                # The available run data cannot certify full calendar-year
                # coverage without an authoritative exchange calendar and
                # requested coverage endpoints.
                complete=None,
            )
        )
        group_start = group_end

    complete_windows = [window for window in fixed_windows if window["complete"]]
    partial_window_count = len(fixed_windows) - len(complete_windows)
    sufficient = len(complete_windows) >= _MIN_COMPLETE_WINDOWS
    outperforming_rate = (
        sum(window["metrics"]["excessReturnPct"] > 0 for window in complete_windows)
        / len(complete_windows)
        * 100.0
        if sufficient
        else None
    )
    if scope == "out_of_sample":
        notice = (
            "仅统计预先冻结的样本外区间。各切片以前一交易日收盘净值为基准，"
            "账户与跨窗持仓连续；年度按自然年分组，首尾可能不足全年。"
            "超越基准比例只在至少四个完整63交易日窗口时提供；切片不是独立重复实验，"
            "也不构成前瞻收益证明。"
        )
    else:
        notice = (
            "未配置冻结的样本外起点，结果按全区间回顾。各切片以前一交易日收盘净值为基准，"
            "账户与跨窗持仓连续；年度按自然年分组，首尾可能不足全年。"
            "超越基准比例只在至少四个完整63交易日窗口时提供；切片不是独立重复实验，"
            "也不构成前瞻收益证明。"
        )

    return {
        "schemaVersion": 1,
        "status": "available" if sufficient else "insufficient_sample",
        "scope": scope,
        "windowSize": _WINDOW_SIZE,
        "minCompleteWindows": _MIN_COMPLETE_WINDOWS,
        "completeWindowCount": len(complete_windows),
        "partialWindowCount": partial_window_count,
        "outperformingWindowRatePct": outperforming_rate,
        "evaluatedStartDate": dates[first_index],
        "evaluatedEndDate": dates[-1],
        "tradingDays": len(evaluated_rows),
        "error": None,
        "annualWindows": annual_windows,
        "fixedWindows": fixed_windows,
        "notice": notice,
    }


def _validate_equity(
    equity: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if not isinstance(equity, Sequence) or isinstance(equity, (str, bytes)):
        raise BacktestInputError("评估净值必须是交易日行列表")
    rows = list(equity)
    if not rows:
        raise BacktestInputError("评估净值不能为空")
    previous_date = ""
    for row in rows:
        if not isinstance(row, Mapping):
            raise BacktestInputError("评估净值行必须是对象")
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            raise BacktestInputError("评估净值日期无效")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise BacktestInputError("评估净值日期无效") from exc
        if parsed.isoformat() != raw_date or (previous_date and raw_date <= previous_date):
            raise BacktestInputError("评估净值日期必须严格递增且不重复")
        previous_date = raw_date
        _finite(row.get("equity"), "equity")
        _finite(row.get("benchmarkEquity"), "benchmarkEquity")
    return rows


def _validate_orders(
    orders: Sequence[Mapping[str, Any]],
    equity_dates: set[str],
) -> list[Mapping[str, Any]]:
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
        raise BacktestInputError("评估委托必须是列表")
    rows = list(orders)
    for order in rows:
        if not isinstance(order, Mapping):
            raise BacktestInputError("评估委托行必须是对象")
        if order.get("status") != "filled":
            continue
        raw_shares = order.get("filledShares", 0)
        if isinstance(raw_shares, bool):
            raise BacktestInputError("成交股数必须是非负整数")
        try:
            shares = int(raw_shares)
        except (ValueError, TypeError, OverflowError) as exc:
            raise BacktestInputError("成交股数必须是非负整数") from exc
        if shares != raw_shares or shares < 0:
            raise BacktestInputError("成交股数必须是非负整数")
        if shares == 0:
            continue
        raw_date = order.get("date")
        if not isinstance(raw_date, str):
            raise BacktestInputError("成交日期无效")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise BacktestInputError("成交日期无效") from exc
        if parsed.isoformat() != raw_date or raw_date not in equity_dates:
            raise BacktestInputError("成交日期必须与回测净值交易日一致")
        for key in ("notional", "fee", "commission", "stampDuty"):
            _finite(order.get(key, 0), key)
    return rows


def _window_record(
    label: str,
    rows: list[Mapping[str, Any]],
    *,
    global_start: int,
    all_rows: list[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    initial_cash: float,
    complete: bool | None,
) -> dict[str, Any]:
    baseline = all_rows[global_start - 1] if global_start > 0 else None
    initial_equity = (
        _finite(baseline.get("equity"), "窗口起始净值", positive=True)
        if baseline is not None
        else initial_cash
    )
    initial_benchmark = (
        _finite(baseline.get("benchmarkEquity"), "窗口基准起始净值", positive=True)
        if baseline is not None
        else initial_cash
    )
    try:
        raw = _window(
            rows,
            orders,
            initial_equity=initial_equity,
            initial_benchmark=initial_benchmark,
            baseline=baseline,
        )
    except BacktestInputError:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise BacktestInputError("稳健性窗口指标无法计算") from exc
    metrics: dict[str, float | int | None] = {}
    for key in _METRIC_KEYS:
        value = raw["metrics"].get(key)
        if value is None:
            metrics[key] = None
        elif key == "tradeCount":
            if isinstance(value, bool):
                raise BacktestInputError("稳健性窗口成交次数无效")
            try:
                count = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise BacktestInputError("稳健性窗口成交次数无效") from exc
            if count != value or count < 0:
                raise BacktestInputError("稳健性窗口成交次数无效")
            metrics[key] = count
        else:
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise BacktestInputError("稳健性窗口指标必须是有限数值") from exc
            if not math.isfinite(number):
                raise BacktestInputError("稳健性窗口指标必须是有限数值")
            metrics[key] = number
    return {
        "label": label,
        "startDate": raw["startDate"],
        "endDate": raw["endDate"],
        "baselineDate": raw["baselineDate"],
        "tradingDays": raw["tradingDays"],
        "complete": complete,
        "metrics": metrics,
    }


__all__ = ["evaluate_robustness"]
