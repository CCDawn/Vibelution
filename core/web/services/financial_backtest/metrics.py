"""Pure return, benchmark, drawdown and risk metrics for a backtest."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

_TRADING_DAYS_PER_YEAR = 252
_CALENDAR_DAYS_PER_YEAR = 365.2425


def _series_stats(
    equity: Sequence[Mapping[str, Any]], key: str, initial_cash: float
) -> dict[str, float | int | None]:
    values = [float(row[key]) for row in equity]
    final_value = values[-1] if values else initial_cash
    total_return = (final_value / initial_cash - 1.0) * 100.0
    calendar_days = 0
    if len(equity) > 1:
        from datetime import date

        calendar_days = (date.fromisoformat(str(equity[-1]["date"])) - date.fromisoformat(str(equity[0]["date"]))).days
    annualized_return = None
    if calendar_days > 0 and final_value > 0:
        annualized_return = ((final_value / initial_cash) ** (_CALENDAR_DAYS_PER_YEAR / calendar_days) - 1.0) * 100.0

    returns = [
        current / previous - 1.0
        for previous, current in pairwise(values)
        if previous > 0
    ]
    volatility_pct = None
    sharpe = None
    if len(returns) > 1:
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / (len(returns) - 1)
        standard_deviation = math.sqrt(variance)
        if standard_deviation > 0:
            volatility_pct = standard_deviation * math.sqrt(_TRADING_DAYS_PER_YEAR) * 100.0
            sharpe = mean_return / standard_deviation * math.sqrt(_TRADING_DAYS_PER_YEAR)

    peak = initial_cash
    max_drawdown = 0.0
    max_drawdown_sessions = 0
    current_peak_index = -1
    max_peak_index = -1
    max_trough_index = -1
    for index, value in enumerate(values):
        if value >= peak:
            peak = value
            current_peak_index = index
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_peak_index = current_peak_index
                max_trough_index = index
    if max_peak_index >= 0 and max_trough_index >= max_peak_index:
        recovery = next(
            (index for index in range(max_trough_index + 1, len(values)) if values[index] >= values[max_peak_index]),
            len(values) - 1,
        )
        max_drawdown_sessions = max(0, recovery - max_peak_index)

    return {
        "totalReturnPct": total_return,
        "annualizedReturnPct": annualized_return,
        "maxDrawdownPct": max_drawdown * 100.0,
        "maxDrawdownSessions": max_drawdown_sessions,
        "volatilityAnnualizedPct": volatility_pct,
        "sharpeRatio": sharpe,
        "finalEquity": final_value,
    }


def calculate_metrics(
    equity: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    trade_count: int,
    closed_trade_count: int,
    winning_trade_count: int,
    gross_turnover: float,
    total_fees: float,
    commission_fees: float,
    stamp_duty: float,
) -> dict[str, float | int | None]:
    """Calculate strategy and same-cost benchmark metrics from marked equity."""
    strategy = _series_stats(equity, "equity", initial_cash)
    benchmark = _series_stats(equity, "benchmarkEquity", initial_cash)
    strategy_return = float(strategy["totalReturnPct"])
    benchmark_return = float(benchmark["totalReturnPct"])
    win_rate = (
        winning_trade_count / closed_trade_count * 100.0 if closed_trade_count else None
    )
    return {
        "totalReturnPct": strategy_return,
        "benchmarkReturnPct": benchmark_return,
        "excessReturnPct": strategy_return - benchmark_return,
        "annualizedReturnPct": strategy["annualizedReturnPct"],
        "benchmarkAnnualizedReturnPct": benchmark["annualizedReturnPct"],
        "maxDrawdownPct": strategy["maxDrawdownPct"],
        "maxDrawdownSessions": strategy["maxDrawdownSessions"],
        "volatilityAnnualizedPct": strategy["volatilityAnnualizedPct"],
        "sharpeRatio": strategy["sharpeRatio"],
        "benchmarkMaxDrawdownPct": benchmark["maxDrawdownPct"],
        "tradeCount": trade_count,
        "closedTradeCount": closed_trade_count,
        "winningTradeCount": winning_trade_count,
        "winRatePct": win_rate,
        "grossTurnover": gross_turnover,
        "fees": total_fees,
        "commissionFees": commission_fees,
        "stampDuty": stamp_duty,
        "finalEquity": strategy["finalEquity"],
        "benchmarkFinalEquity": benchmark["finalEquity"],
    }


__all__ = ["calculate_metrics"]
