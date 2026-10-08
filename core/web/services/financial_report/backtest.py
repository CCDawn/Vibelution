"""Reproducible, read-only moving-average backtests over public A-share candles."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from numbers import Real
from typing import Any, Mapping

from core.web.services import financial_market_service, financial_preferences_service
from core.web.services.financial_preferences_service import FinancialPreferenceError

_INITIAL_CASH = 100_000.0
_DEFAULT_WINDOW = 20
_DEFAULT_COMMISSION_BPS = 3.0
_DEFAULT_SLIPPAGE_BPS = 5.0
_MAX_BOUNDARY_ADJUSTMENT_DAYS = 3
_BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
_NOTICE = (
    "前复权历史数据可能因未来公司行为回溯变化；未建模税费、最低佣金、涨跌停、分红及停牌；"
    "为便于计量允许小数股，不代表A股实盘撮合；这是均线指标策略回测，不是原生AI策略回测；"
    "期末持仓仅按收盘价估值，不虚构平仓。"
)


def _finite_number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise FinancialPreferenceError(f"{label}必须是有限数值")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise FinancialPreferenceError(f"{label}必须是有限正数" if positive else f"{label}必须是有限数值")
    return number


def _request_parameters(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FinancialPreferenceError("回测参数格式无效")
    raw_symbol = payload.get("symbol")
    try:
        symbol = financial_market_service.normalize_a_share_symbol(raw_symbol)
    except financial_market_service.MarketDataError as exc:
        raise FinancialPreferenceError(str(exc), 422) from exc

    window = payload.get("window", _DEFAULT_WINDOW)
    if isinstance(window, bool) or not isinstance(window, int) or not 5 <= window <= 60:
        raise FinancialPreferenceError("window必须是5至60之间的整数")

    commission_bps = _finite_number(
        payload.get("commissionBps", _DEFAULT_COMMISSION_BPS), "commissionBps"
    )
    slippage_bps = _finite_number(
        payload.get("slippageBps", _DEFAULT_SLIPPAGE_BPS), "slippageBps"
    )
    if not 0 <= commission_bps <= 100:
        raise FinancialPreferenceError("commissionBps必须在0至100之间")
    if not 0 <= slippage_bps <= 100:
        raise FinancialPreferenceError("slippageBps必须在0至100之间")

    start_date = _parse_date(payload.get("startDate"), "startDate")
    end_date = _parse_date(payload.get("endDate"), "endDate")
    if start_date > end_date:
        raise FinancialPreferenceError("startDate不能晚于endDate")

    return {
        "symbol": symbol,
        "requestedStartDate": start_date,
        "requestedEndDate": end_date,
        "window": window,
        "commissionBps": commission_bps,
        "slippageBps": slippage_bps,
    }


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise FinancialPreferenceError(f"{label}必须使用YYYY-MM-DD格式")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FinancialPreferenceError(f"{label}必须使用YYYY-MM-DD格式") from exc
    if parsed.isoformat() != value:
        raise FinancialPreferenceError(f"{label}必须使用YYYY-MM-DD格式")
    return parsed


def _beijing_today(today: date | datetime | str | None) -> date:
    if today is None:
        return datetime.now(_BEIJING_TZ).date()
    if isinstance(today, datetime):
        if today.tzinfo is None:
            return today.date()
        return today.astimezone(_BEIJING_TZ).date()
    if isinstance(today, date):
        return today
    return _parse_date(today, "today")


def _validated_candles(snapshot: Mapping[str, Any], symbol: str, today: date) -> list[dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        raise FinancialPreferenceError("历史行情快照无效")
    stock = snapshot.get("stock")
    if not isinstance(stock, Mapping):
        raise FinancialPreferenceError("历史行情快照缺少股票身份")
    try:
        snapshot_symbol = financial_market_service.normalize_a_share_symbol(stock.get("symbol"))
    except financial_market_service.MarketDataError as exc:
        raise FinancialPreferenceError("历史行情快照股票代码无效", 422) from exc
    if snapshot_symbol != symbol:
        raise FinancialPreferenceError("历史行情快照股票代码与请求不一致")
    if snapshot.get("period") != "day":
        raise FinancialPreferenceError("回测仅接受日K历史行情")
    if snapshot.get("adjustment") != "qfq":
        raise FinancialPreferenceError("A股回测仅接受前复权日K")
    for field in ("source", "sourceUrl", "fetchedAt"):
        value = snapshot.get(field)
        if not isinstance(value, str) or not value.strip():
            raise FinancialPreferenceError(f"历史行情快照缺少{field}来源信息")

    rows = snapshot.get("candles")
    if not isinstance(rows, list) or not rows:
        detail = str(snapshot.get("candleError") or "")
        suffix = f"：{detail}" if detail else ""
        raise FinancialPreferenceError(f"历史日K数据不可用{suffix}", 422)

    validated: list[dict[str, Any]] = []
    previous_date = ""
    for row in rows:
        if not isinstance(row, Mapping):
            raise FinancialPreferenceError("历史日K数据格式无效")
        candle_date = row.get("date")
        if not isinstance(candle_date, str):
            raise FinancialPreferenceError("历史日K日期无效")
        parsed_date = _parse_date(candle_date, "历史日K日期")
        if candle_date <= previous_date:
            raise FinancialPreferenceError("历史日K日期必须严格递增且不能重复")
        previous_date = candle_date

        opening = _finite_number(row.get("open"), "open", positive=True)
        closing = _finite_number(row.get("close"), "close", positive=True)
        high = _finite_number(row.get("high"), "high", positive=True)
        low = _finite_number(row.get("low"), "low", positive=True)
        if low > min(opening, closing) or high < max(opening, closing) or low > high:
            raise FinancialPreferenceError("历史日K的OHLC关系无效")
        validated.append(
            {
                "date": candle_date,
                "open": opening,
                "close": closing,
                "high": high,
                "low": low,
                "parsedDate": parsed_date,
            }
        )

    # A candle dated today may still be forming in Beijing. Exclude it and any
    # future rows before resolving the requested range or calculating signals.
    completed = [row for row in validated if row["parsedDate"] < today]
    if not completed:
        raise FinancialPreferenceError("没有可用于回测的已完成日K数据")
    return completed


def _resolve_boundary(
    requested: date,
    candles: list[dict[str, Any]],
    label: str,
    *,
    side: str,
) -> int:
    if side == "start":
        candidates = [
            (index, (row["parsedDate"] - requested).days)
            for index, row in enumerate(candles)
            if row["parsedDate"] >= requested
        ]
        index, distance = min(candidates, key=lambda item: item[1]) if candidates else (-1, -1)
    elif side == "end":
        candidates = [
            (index, (requested - row["parsedDate"]).days)
            for index, row in enumerate(candles)
            if row["parsedDate"] <= requested
        ]
        index, distance = min(candidates, key=lambda item: item[1]) if candidates else (-1, -1)
    else:
        raise ValueError(f"unsupported boundary side: {side}")
    if index < 0 or distance > _MAX_BOUNDARY_ADJUSTMENT_DAYS:
        raise FinancialPreferenceError(f"{label}附近缺少日K覆盖，请调整日期；不能截断回测区间")
    return index


def _adjusted_fill_price(opening: float, side: str, slippage_rate: float) -> float:
    return opening * (1.0 + slippage_rate if side == "buy" else 1.0 - slippage_rate)


def _buy_units(cash: float, price: float, commission_rate: float) -> tuple[float, float]:
    units = cash / (price * (1.0 + commission_rate))
    fee = units * price * commission_rate
    return units, fee


def _max_drawdown_pct(equity_rows: list[dict[str, Any]]) -> float:
    peak = _INITIAL_CASH
    maximum = 0.0
    for row in equity_rows:
        equity = row["equity"]
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100.0)
    return maximum


def calculate_backtest(
    snapshot: Mapping[str, Any],
    payload: Mapping[str, Any],
    today: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Calculate a deterministic long/cash MA backtest from a supplied snapshot."""
    parameters = _request_parameters(payload)
    cutoff = _beijing_today(today)
    if parameters["requestedStartDate"] >= cutoff:
        raise FinancialPreferenceError("startDate必须早于北京时间今天")
    if parameters["requestedEndDate"] > cutoff:
        raise FinancialPreferenceError("endDate不能晚于北京时间今天")

    candles = _validated_candles(snapshot, parameters["symbol"], cutoff)
    first_index = _resolve_boundary(
        parameters["requestedStartDate"], candles, "startDate", side="start"
    )
    last_index = _resolve_boundary(
        parameters["requestedEndDate"], candles, "endDate", side="end"
    )
    if first_index > last_index:
        raise FinancialPreferenceError("对齐后的startDate不能晚于endDate")
    window = parameters["window"]
    if first_index < window:
        raise FinancialPreferenceError("所选起始日之前不足window根完整日K预热数据")

    selected = candles[first_index : last_index + 1]
    commission_rate = parameters["commissionBps"] / 10_000.0
    slippage_rate = parameters["slippageBps"] / 10_000.0

    # Buy-and-hold enters at the same first in-range session open and pays the
    # same per-side execution costs as the strategy.
    benchmark_fill = _adjusted_fill_price(selected[0]["open"], "buy", slippage_rate)
    benchmark_units, benchmark_fee = _buy_units(_INITIAL_CASH, benchmark_fill, commission_rate)

    cash = _INITIAL_CASH
    units = 0.0
    pending_target: bool | None = None
    pending_signal_date = ""
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    total_fees = 0.0

    for offset, candle in enumerate(selected):
        if pending_target is not None and pending_target != (units > 0):
            if pending_target:
                price = _adjusted_fill_price(candle["open"], "buy", slippage_rate)
                units, fee = _buy_units(cash, price, commission_rate)
                cash = 0.0
                side = "buy"
            else:
                price = _adjusted_fill_price(candle["open"], "sell", slippage_rate)
                gross = units * price
                fee = gross * commission_rate
                cash = gross - fee
                units = 0.0
                side = "sell"
            total_fees += fee
            trades.append(
                {
                    "signalDate": pending_signal_date,
                    "date": candle["date"],
                    "side": side,
                    "price": price,
                    "units": units if side == "buy" else gross / price,
                    "fee": fee,
                }
            )
        pending_target = None

        equity_rows.append(
            {
                "date": candle["date"],
                "equity": cash + units * candle["close"],
                "benchmarkEquity": benchmark_units * candle["close"],
            }
        )

        # Only closes in the requested range create signals. A signal on the
        # final bar has no in-range next-open execution and is therefore ignored.
        absolute_index = first_index + offset
        if offset < len(selected) - 1 and absolute_index >= window - 1:
            window_rows = candles[absolute_index - window + 1 : absolute_index + 1]
            moving_average = sum(row["close"] for row in window_rows) / window
            pending_target = candle["close"] > moving_average
            pending_signal_date = candle["date"]

    final_equity = equity_rows[-1]["equity"]
    final_benchmark_equity = equity_rows[-1]["benchmarkEquity"]
    total_return = (final_equity / _INITIAL_CASH - 1.0) * 100.0
    benchmark_return = (final_benchmark_equity / _INITIAL_CASH - 1.0) * 100.0

    hash_rows = [
        {key: row[key] for key in ("date", "open", "close", "high", "low")}
        for row in candles[first_index - window + 1 : last_index + 1]
    ]
    data_hash = hashlib.sha256(
        json.dumps(hash_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()

    start_date = selected[0]["date"]
    end_date = selected[-1]["date"]
    notices = [_NOTICE]
    if start_date != parameters["requestedStartDate"].isoformat():
        notices.append(f"startDate已按邻近交易日对齐为{start_date}。")
    if end_date != parameters["requestedEndDate"].isoformat():
        notices.append(f"endDate已按邻近交易日对齐为{end_date}。")

    return {
        "symbol": parameters["symbol"],
        "metrics": {
            "totalReturnPct": total_return,
            "benchmarkReturnPct": benchmark_return,
            "excessReturnPct": total_return - benchmark_return,
            "maxDrawdownPct": _max_drawdown_pct(equity_rows),
            "tradeCount": len(trades),
            "fees": total_fees,
            "benchmarkFees": benchmark_fee,
        },
        "equity": equity_rows,
        "trades": trades,
        "source": snapshot["source"],
        "sourceUrl": snapshot["sourceUrl"],
        "fetchedAt": snapshot["fetchedAt"],
        "adjustment": "qfq",
        "dataHash": data_hash,
        "startDate": start_date,
        "endDate": end_date,
        "requestedStartDate": parameters["requestedStartDate"].isoformat(),
        "requestedEndDate": parameters["requestedEndDate"].isoformat(),
        "window": window,
        "notice": "".join(notices),
    }


def run_backtest(agent_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Authorize a financial Agent, fetch its bounded daily snapshot, and calculate."""
    financial_preferences_service._agent(agent_id)
    parameters = _request_parameters(payload)
    try:
        snapshot = financial_market_service.get_stock_snapshot(parameters["symbol"], period="day")
    except financial_market_service.MarketDataError as exc:
        raise FinancialPreferenceError(str(exc), 422) from exc
    return calculate_backtest(snapshot, payload)


__all__ = ["calculate_backtest", "run_backtest"]
