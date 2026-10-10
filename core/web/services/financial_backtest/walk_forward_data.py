"""Offline slicing of owner-frozen A-share single and basket snapshots."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.web.services.financial_backtest import basket_data, data

_MAX_WARMUP_BARS = 252


def session_dates(snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot) -> tuple[str, ...]:
    if isinstance(snapshot, basket_data.BasketSnapshot):
        return snapshot.session_dates
    return tuple(candle.date for candle in snapshot.candles)


def slice_snapshot(
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    start_index: int,
    end_index: int,
) -> data.BacktestSnapshot | basket_data.BasketSnapshot:
    """Create a validated immutable window without fetching or changing prices."""
    dates = session_dates(snapshot)
    if (
        isinstance(start_index, bool)
        or isinstance(end_index, bool)
        or not isinstance(start_index, int)
        or not isinstance(end_index, int)
        or start_index < 0
        or end_index < start_index
        or end_index >= len(dates)
        or end_index - start_index + 1 < 2
    ):
        raise data.BacktestInputError("滚动验证窗口边界无效，至少需要两个完整交易日")

    if isinstance(snapshot, basket_data.BasketSnapshot):
        assets = {
            symbol: _slice_single_snapshot(snapshot.assets[symbol], start_index, end_index)
            for symbol in snapshot.symbols
        }
        window_dates = snapshot.session_dates[start_index : end_index + 1]
        sliced = basket_data.BasketSnapshot(
            symbols=snapshot.symbols,
            assets=assets,
            session_dates=window_dates,
            start_date=window_dates[0],
            end_date=window_dates[-1],
            data_hash=basket_data._stable_basket_hash(
                snapshot.symbols,
                assets,
                window_dates,
                window_dates[0],
                window_dates[-1],
            ),
            source=snapshot.source,
            notice=snapshot.notice,
        )
        basket_data.validate_basket_snapshot(sliced)
        return sliced

    return _slice_single_snapshot(snapshot, start_index, end_index)


def _slice_single_snapshot(
    snapshot: data.BacktestSnapshot, start_index: int, end_index: int
) -> data.BacktestSnapshot:
    rows = snapshot.candles[start_index : end_index + 1]
    if len(rows) < 2:
        raise data.BacktestInputError("滚动验证窗口至少需要两个完整交易日")
    earlier = snapshot.warmup_candles + snapshot.candles[:start_index]
    warmup = earlier[-_MAX_WARMUP_BARS:]
    start_date = rows[0].date
    end_date = rows[-1].date
    all_rows = tuple(warmup) + tuple(rows)
    coverage = replace(
        snapshot.coverage,
        requestedStartDate=start_date,
        requestedEndDate=end_date,
        actualStartDate=start_date,
        actualEndDate=end_date,
        availableStartDate=all_rows[0].date,
        availableEndDate=end_date,
        tradingDays=len(rows),
        warmupBars=len(warmup),
    )
    sliced = replace(
        snapshot,
        start_date=start_date,
        end_date=end_date,
        candles=tuple(rows),
        warmup_candles=tuple(warmup),
        data_hash=data._stable_hash(all_rows, snapshot.symbol, start_date, end_date),
        coverage=coverage,
    )
    data.validate_snapshot(sliced)
    return sliced


__all__ = ["session_dates", "slice_snapshot"]
