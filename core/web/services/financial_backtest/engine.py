"""Deterministic CN single-stock, long-only next-open execution simulator."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from core.web.services.financial_backtest.data import (
    BacktestDataError,
    BacktestInputError,
    BacktestSnapshot,
    Candle,
    validate_snapshot,
)
from core.web.services.financial_backtest.metrics import calculate_metrics

_MAX_TRADING_DAYS = 5_000
_MAX_DECISIONS = 500
_LOT_SIZE = 100
_PRICE_TICK = Decimal("0.01")
_MONEY_QUANTUM = Decimal("0.01")
_BPS = Decimal(10000)
_STAMP_DUTY_CHANGES = (
    (date(2023, 8, 28), Decimal("0.0005"), Decimal(0)),
    (date(2008, 9, 19), Decimal("0.001"), Decimal(0)),
    (date(2008, 4, 24), Decimal("0.001"), Decimal("0.001")),
    (date(2007, 5, 30), Decimal("0.003"), Decimal("0.003")),
    (date(2005, 1, 24), Decimal("0.001"), Decimal("0.001")),
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class BacktestDecisionError(BacktestDataError):
    """AI output is missing, duplicated, malformed, or outside its date schedule."""

    code = "invalid_backtest_decisions"


def _decimal(value: Any, label: str, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是有效数值")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestInputError(f"{label}必须是有效数值") from exc
    if not result.is_finite() or result < minimum or result > maximum:
        raise BacktestInputError(f"{label}超出允许范围")
    return result


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数") from exc
    if result != value or not minimum <= result <= maximum:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    return result


def _param(params: Mapping[str, Any], camel: str, snake: str, default: Any) -> Any:
    return params[camel] if camel in params else params.get(snake, default)


def _normalize_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        raise BacktestInputError("回测参数必须是对象")
    initial_cash = _decimal(
        _param(params, "initialCash", "initial_cash", 100_000),
        "initialCash",
        minimum=Decimal(1000),
        maximum=Decimal(100000000),
    )
    max_position_pct = _decimal(
        _param(params, "maxPositionPct", "max_position_pct", 100),
        "maxPositionPct",
        minimum=Decimal(0),
        maximum=Decimal(100),
    )
    decision_interval = _integer(
        _param(params, "decisionInterval", "decision_interval", 5),
        "decisionInterval",
        minimum=1,
        maximum=252,
    )
    commission_bps = _decimal(
        _param(params, "commissionBps", "commission_bps", 3),
        "commissionBps",
        minimum=Decimal(0),
        maximum=Decimal(100),
    )
    minimum_commission = _decimal(
        _param(params, "minimumCommission", "minimum_commission", 5),
        "minimumCommission",
        minimum=Decimal(0),
        maximum=Decimal(10000),
    )
    slippage_bps = _decimal(
        _param(params, "slippageBps", "slippage_bps", 5),
        "slippageBps",
        minimum=Decimal(0),
        maximum=Decimal(100),
    )
    raw_participation_pct = _param(
        params, "maxParticipationPct", "max_participation_pct", None
    )
    max_participation_pct = (
        None
        if raw_participation_pct is None
        else _decimal(
            raw_participation_pct,
            "maxParticipationPct",
            minimum=Decimal("0.1"),
            maximum=Decimal(100),
        )
    )
    max_decisions = _integer(
        _param(params, "maxDecisions", "max_decisions", _MAX_DECISIONS),
        "maxDecisions",
        minimum=1,
        maximum=_MAX_DECISIONS,
    )
    if params.get("stampDutyBps") is not None or params.get("stamp_duty_bps") is not None:
        raise BacktestInputError("印花税按历史成交日期自动计取，不接受固定税率覆盖")
    normalized = {
        "initialCash": initial_cash,
        "maxPositionPct": max_position_pct,
        "decisionInterval": decision_interval,
        "commissionBps": commission_bps,
        "minimumCommission": minimum_commission,
        "slippageBps": slippage_bps,
        "maxDecisions": max_decisions,
    }
    if max_participation_pct is not None:
        normalized["maxParticipationPct"] = max_participation_pct
    return normalized


def build_decision_schedule(
    snapshot: BacktestSnapshot, params: Mapping[str, Any] | None = None
) -> tuple[str, ...]:
    """Return exact close-time decision dates whose next open exists in-range."""
    validate_snapshot(snapshot)
    if not snapshot.candles or len(snapshot.candles) > _MAX_TRADING_DAYS:
        raise BacktestInputError("回测区间需要1到5000根完整交易日K线")
    normalized = _normalize_params({} if params is None else params)
    interval = normalized["decisionInterval"]
    schedule = tuple(
        snapshot.candles[index].date
        for index in range(0, max(0, len(snapshot.candles) - 1), interval)
    )
    allowed = min(_MAX_DECISIONS, normalized["maxDecisions"])
    if len(schedule) > allowed:
        raise BacktestInputError(
            f"决策点共{len(schedule)}次，超过本次上限{allowed}次；增大决策间隔或缩短区间"
        )
    if not schedule:
        raise BacktestInputError("区间内没有可撮合的决策日；至少需要两根交易日日K")
    return schedule


def _validate_decisions(
    decisions: Sequence[Mapping[str, Any]], expected_dates: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        raise BacktestDecisionError("AI决策必须是列表")
    by_date: dict[str, dict[str, Any]] = {}
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise BacktestDecisionError("AI决策行必须是对象")
        decision_date = raw.get("date")
        if not isinstance(decision_date, str) or decision_date not in expected_dates:
            raise BacktestDecisionError("AI决策日期不在完整交易日决策计划内")
        if decision_date in by_date:
            raise BacktestDecisionError(f"AI决策日期重复：{decision_date}")
        weight = _decimal(
            raw.get("targetWeight"),
            "targetWeight",
            minimum=Decimal(0),
            maximum=Decimal(1),
        )
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2_000:
            raise BacktestDecisionError("每个AI决策都必须有不超过2000字的理由")
        confidence = raw.get("confidence")
        row: dict[str, Any] = {
            "date": decision_date,
            "targetWeight": float(weight),
            "reason": reason.strip(),
        }
        if confidence is not None:
            row["confidence"] = float(
                _decimal(
                    confidence,
                    "confidence",
                    minimum=Decimal(0),
                    maximum=Decimal(1),
                )
            )
        for key in ("inputHash", "outputHash"):
            value = raw.get(key)
            if value is not None:
                if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
                    raise BacktestDecisionError(f"{key}必须是SHA-256十六进制摘要")
                row[key] = value
        by_date[decision_date] = row
    if set(by_date) != set(expected_dates):
        missing = [value for value in expected_dates if value not in by_date]
        extra = [value for value in by_date if value not in expected_dates]
        raise BacktestDecisionError(
            "AI决策计划不完整；缺少=" + ",".join(missing[:8]) + "; 多余=" + ",".join(extra[:8])
        )
    return by_date


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _price(value: Decimal, side: str) -> Decimal:
    rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
    return value.quantize(_PRICE_TICK, rounding=rounding)


def _fee(notional: Decimal, commission_rate: Decimal, minimum_commission: Decimal) -> Decimal:
    if commission_rate == 0 or notional <= 0:
        return Decimal(0)
    return _money(max(minimum_commission, notional * commission_rate))


def _stamp_duty_rate(execution_date: str, side: str) -> Decimal:
    day = date.fromisoformat(execution_date)
    for effective, seller_rate, buyer_rate in _STAMP_DUTY_CHANGES:
        if day >= effective:
            return seller_rate if side == "sell" else buyer_rate
    # The configured 20-year maximum makes earlier effective rates unreachable
    # for supported current-date runs; retain the rate in force from 2005.
    return Decimal("0.001")


def _stamp_duty(notional: Decimal, execution_date: str, side: str) -> Decimal:
    return _money(notional * _stamp_duty_rate(execution_date, side))


def _limit_rates(symbol: str) -> tuple[Decimal, ...]:
    # Historical ST, listing and board limit regimes are not supplied by the
    # quote source. Check common candidate bands as a conservative heuristic.
    return (Decimal("0.10"), Decimal("0.05"), Decimal("0.20"), Decimal("0.30"))


def _is_locked(candle: Candle, previous_close: float | None, side: str, symbol: str) -> str | None:
    if candle.volume <= 0:
        return "zero_volume_or_suspended"
    if previous_close is None or previous_close <= 0:
        return None
    flat = max(candle.open, candle.high, candle.low, candle.close) - min(
        candle.open, candle.high, candle.low, candle.close
    ) <= 0.010001
    if not flat:
        return None
    direction = 1 if side == "buy" else -1
    for rate in _limit_rates(symbol):
        limit = float(
            _price(Decimal(str(previous_close)) * (Decimal(1) + direction * rate), "buy" if direction > 0 else "sell")
        )
        if abs(candle.open - limit) <= 0.010001:
            return "one_price_at_candidate_limit_up" if direction > 0 else "one_price_at_candidate_limit_down"
    return None


def _execution_price(candle: Candle, side: str, slippage_rate: Decimal) -> tuple[Decimal, Decimal]:
    opening = Decimal(str(candle.open))
    high = Decimal(str(candle.high))
    low = Decimal(str(candle.low))
    raw = opening * (Decimal(1) + slippage_rate if side == "buy" else Decimal(1) - slippage_rate)
    bounded = min(raw, high) if side == "buy" else max(raw, low)
    final = _price(bounded, side)
    if side == "buy" and final > high:
        final = high.quantize(_PRICE_TICK, rounding=ROUND_FLOOR)
    elif side == "sell" and final < low:
        final = low.quantize(_PRICE_TICK, rounding=ROUND_CEILING)
    return final, abs(final - opening)


def _account_equity(cash: Decimal, shares: int, price: Decimal) -> Decimal:
    return cash + Decimal(shares) * price


def _shares_for_target(value: Decimal, price: Decimal) -> int:
    if value <= 0 or price <= 0:
        return 0
    lots = int((value / price / _LOT_SIZE).to_integral_value(rounding=ROUND_FLOOR))
    return max(0, lots * _LOT_SIZE)


def _max_participation_shares(
    execution: Candle, max_participation_pct: Decimal | None
) -> int | None:
    """Return the per-symbol daily share cap rounded down to board lots.

    Missing participation limits preserve the legacy unlimited-volume behavior.
    Candle volume is already normalized to shares by the frozen-data layer.
    """
    if max_participation_pct is None:
        return None
    allowed = Decimal(str(execution.volume)) * max_participation_pct / Decimal(100)
    whole_shares = int(allowed.to_integral_value(rounding=ROUND_FLOOR))
    return (whole_shares // _LOT_SIZE) * _LOT_SIZE


def _make_order(
    *,
    signal_date: str,
    candle: Candle,
    side: str,
    status: str,
    reason: str,
    requested_shares: int,
    filled_shares: int = 0,
    fill_price: Decimal | None = None,
    commission: Decimal = Decimal(0),
    stamp: Decimal = Decimal(0),
    slippage_cost: Decimal = Decimal(0),
) -> dict[str, Any]:
    notional = Decimal(filled_shares) * fill_price if fill_price is not None else Decimal(0)
    return {
        "signalDate": signal_date,
        "date": candle.date,
        "side": side,
        "status": status,
        "reason": reason,
        "requestedShares": requested_shares,
        "filledShares": filled_shares,
        "units": filled_shares,
        "price": float(fill_price) if fill_price is not None else None,
        "notional": float(_money(notional)),
        "commission": float(commission),
        "stampDuty": float(stamp),
        "fee": float(commission + stamp),
        "slippageCost": float(_money(Decimal(filled_shares) * slippage_cost)),
        "tPlusOne": True,
        "limitStatus": (
            "candidate_only_unverified"
            if reason.startswith("one_price_at_candidate_limit_")
            else "unverified"
        ),
    }


def _execute_target(
    *,
    signal_date: str,
    execution: Candle,
    previous_close: float | None,
    target_weight: Decimal,
    cash: Decimal,
    shares: int,
    max_position_pct: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    symbol: str,
    max_participation_pct: Decimal | None = None,
) -> tuple[Decimal, int, dict[str, Any], dict[str, Any] | None, Decimal, Decimal, Decimal]:
    if target_weight > max_position_pct / Decimal(100):
        raise BacktestDecisionError("AI目标仓位超过本次最大仓位上限")
    open_price = Decimal(str(execution.open))
    pre_equity = _account_equity(cash, shares, open_price)
    target_value = pre_equity * target_weight
    # Position sizing uses the observable next open. Slippage affects the fill
    # and cash constraint only, never the target percentage calculation.
    desired = _shares_for_target(target_value, open_price)
    delta = desired - shares
    if delta == 0:
        order = _make_order(
            signal_date=signal_date,
            candle=execution,
            side="hold",
            status="no_action",
            reason="目标仓位与开盘市值对应的持仓一致",
            requested_shares=0,
        )
        return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    side = "buy" if delta > 0 else "sell"
    fill_price, per_share_slippage = _execution_price(execution, side, slippage_rate)
    rejection = _is_locked(execution, previous_close, side, symbol)
    requested = abs(delta)
    if rejection:
        order = _make_order(
            signal_date=signal_date,
            candle=execution,
            side=side,
            status="rejected",
            reason=rejection,
            requested_shares=requested,
        )
        return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    if side == "buy":
        requested = max(0, (requested // _LOT_SIZE) * _LOT_SIZE)
        executable_requested = requested
    else:
        executable_requested = (min(shares, requested) // _LOT_SIZE) * _LOT_SIZE
        if not executable_requested:
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="no_sellable_board_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    participation_cap = _max_participation_shares(
        execution, max_participation_pct
    )
    volume_limited = (
        participation_cap is not None
        and participation_cap < executable_requested
    )
    fill_limit = (
        executable_requested
        if participation_cap is None
        else min(executable_requested, participation_cap)
    )
    if executable_requested and fill_limit == 0:
        order = _make_order(
            signal_date=signal_date,
            candle=execution,
            side=side,
            status="rejected",
            reason="volume_participation_below_one_lot",
            requested_shares=requested,
        )
        return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    if side == "buy":
        filled = fill_limit
        while filled:
            notional = Decimal(filled) * fill_price
            commission = _fee(notional, commission_rate, minimum_commission)
            stamp = _stamp_duty(notional, execution.date, side)
            if notional + commission + stamp <= cash:
                break
            filled -= _LOT_SIZE
        if not filled:
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="insufficient_cash_for_one_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)
        notional = Decimal(filled) * fill_price
        commission = _fee(notional, commission_rate, minimum_commission)
        stamp = _stamp_duty(notional, execution.date, side)
        fee = commission + stamp
        cash -= notional + fee
        shares += filled
        trade = {
            "signalDate": signal_date,
            "date": execution.date,
            "side": side,
            "price": float(fill_price),
            "units": filled,
            "shares": filled,
            "fee": float(fee),
            "commission": float(commission),
            "stampDuty": float(stamp),
            "slippageCost": float(_money(Decimal(filled) * per_share_slippage)),
            "notional": float(_money(notional)),
            "tPlusOne": True,
        }
    else:
        filled = min(shares, fill_limit)
        filled = (filled // _LOT_SIZE) * _LOT_SIZE
        if not filled:
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="no_sellable_board_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)
        notional = Decimal(filled) * fill_price
        commission = _fee(notional, commission_rate, minimum_commission)
        stamp = _stamp_duty(notional, execution.date, side)
        fee = commission + stamp
        cash += notional - fee
        shares -= filled
        trade = {
            "signalDate": signal_date,
            "date": execution.date,
            "side": side,
            "price": float(fill_price),
            "units": filled,
            "shares": filled,
            "fee": float(fee),
            "commission": float(commission),
            "stampDuty": float(stamp),
            "slippageCost": float(_money(Decimal(filled) * per_share_slippage)),
            "notional": float(_money(notional)),
            "tPlusOne": True,
        }
    order = _make_order(
        signal_date=signal_date,
        candle=execution,
        side=side,
        status="partial_fill" if volume_limited else "filled",
        reason=(
            "daily_volume_participation_limit"
            if volume_limited
            else "next_session_open"
        ),
        requested_shares=requested,
        filled_shares=filled,
        fill_price=fill_price,
        commission=commission,
        stamp=stamp,
        slippage_cost=per_share_slippage,
    )
    slippage_cost = Decimal(filled) * per_share_slippage
    return cash, shares, order, trade, commission, stamp, slippage_cost


def _execute_benchmark(
    *,
    execution: Candle,
    previous_close: float | None,
    initial_cash: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    symbol: str,
    max_participation_pct: Decimal | None = None,
) -> tuple[Decimal, int, dict[str, Any]]:
    fill_price, per_share_slippage = _execution_price(execution, "buy", slippage_rate)
    rejection = _is_locked(execution, previous_close, "buy", symbol)
    if rejection:
        return initial_cash, 0, _make_order(
            signal_date=execution.date, candle=execution, side="buy",
            status="rejected", reason=rejection, requested_shares=0,
        )
    requested = _shares_for_target(Decimal(initial_cash), fill_price)
    participation_cap = _max_participation_shares(
        execution, max_participation_pct
    )
    volume_limited = (
        participation_cap is not None and participation_cap < requested
    )
    fill_limit = (
        requested
        if participation_cap is None
        else min(requested, participation_cap)
    )
    if requested and fill_limit == 0:
        return initial_cash, 0, _make_order(
            signal_date=execution.date,
            candle=execution,
            side="buy",
            status="rejected",
            reason="volume_participation_below_one_lot",
            requested_shares=requested,
        )
    filled = fill_limit
    while filled:
        notional = Decimal(filled) * fill_price
        fee = _fee(notional, commission_rate, minimum_commission)
        stamp = _stamp_duty(notional, execution.date, "buy")
        if notional + fee + stamp <= initial_cash:
            break
        filled -= _LOT_SIZE
    if not filled:
        return initial_cash, 0, _make_order(
            signal_date=execution.date, candle=execution, side="buy",
            status="rejected", reason="insufficient_cash_for_one_lot", requested_shares=requested,
        )
    notional = Decimal(filled) * fill_price
    commission = _fee(notional, commission_rate, minimum_commission)
    stamp = _stamp_duty(notional, execution.date, "buy")
    fee = commission + stamp
    remaining_cash = initial_cash - notional - fee
    order = _make_order(
        signal_date=execution.date,
        candle=execution,
        side="buy",
        status="partial_fill" if volume_limited else "filled",
        reason=(
            "daily_volume_participation_limit"
            if volume_limited
            else "same_cost_buy_and_hold_benchmark"
        ),
        requested_shares=requested,
        filled_shares=filled,
        fill_price=fill_price,
        commission=commission,
        stamp=stamp,
        slippage_cost=per_share_slippage,
    )
    order["slippageCost"] = float(_money(Decimal(filled) * per_share_slippage))
    return remaining_cash, filled, order


def _equity_row(
    candle: Candle,
    *,
    cash: Decimal,
    shares: int,
    benchmark_cash: Decimal,
    benchmark_shares: int,
) -> dict[str, Any]:
    close = Decimal(str(candle.close))
    equity = _account_equity(cash, shares, close)
    benchmark_equity = _account_equity(benchmark_cash, benchmark_shares, close)
    return {
        "date": candle.date,
        "equity": float(_money(equity)),
        "benchmarkEquity": float(_money(benchmark_equity)),
        "cash": float(_money(cash)),
        "shares": shares,
        "units": shares,
        "marketValue": float(_money(Decimal(shares) * close)),
        "benchmarkCash": float(_money(benchmark_cash)),
        "benchmarkShares": benchmark_shares,
    }


def _benchmark_unavailable_error(attempts: Sequence[Mapping[str, Any]]) -> BacktestDataError:
    metadata: dict[str, Any] = {
        "benchmarkStatus": "unavailable",
        "benchmarkAttemptCount": len(attempts),
    }
    if attempts:
        metadata["lastBenchmarkOrder"] = dict(attempts[-1])
    return BacktestDataError(
        "所选区间内基准在所有后续开盘均无法成交，不能计算可靠的基准和超额收益。",
        metadata=metadata,
    )


def _prepare_schedule(snapshot: BacktestSnapshot, params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_decision_schedule(snapshot, params)


def _simulate_prefix(
    snapshot: BacktestSnapshot,
    normalized: Mapping[str, Any],
    decision_rows: Mapping[str, Mapping[str, Any]],
    *,
    through_date: str,
    expected_schedule: tuple[str, ...],
    complete: bool,
) -> dict[str, Any]:
    candles = snapshot.candles
    dates = [row.date for row in candles]
    if through_date not in dates:
        raise BacktestInputError("asOfDate必须是所选区间内的完整交易日")
    end_index = dates.index(through_date)
    initial_cash: Decimal = normalized["initialCash"]
    max_position_pct: Decimal = normalized["maxPositionPct"]
    commission_rate: Decimal = normalized["commissionBps"] / _BPS
    minimum_commission: Decimal = normalized["minimumCommission"]
    slippage_rate: Decimal = normalized["slippageBps"] / _BPS
    max_participation_pct: Decimal | None = normalized.get("maxParticipationPct")
    cash = initial_cash
    shares = 0
    benchmark_cash = initial_cash
    benchmark_shares = 0
    benchmark_order: dict[str, Any] | None = None
    benchmark_orders: list[dict[str, Any]] = []
    pending: Mapping[str, Any] | None = None
    orders: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    total_commission = Decimal(0)
    total_stamp = Decimal(0)
    total_slippage = Decimal(0)
    turnover = Decimal(0)
    cost_basis = Decimal(0)
    realized_roundtrips: list[Decimal] = []

    for index, candle in enumerate(candles[: end_index + 1]):
        previous_close = candles[index - 1].close if index > 0 else None
        if index > 0 and benchmark_order is None:
            candidate_cash, candidate_shares, candidate_order = _execute_benchmark(
                execution=candle,
                previous_close=previous_close,
                initial_cash=initial_cash,
                commission_rate=commission_rate,
                minimum_commission=minimum_commission,
                slippage_rate=slippage_rate,
                symbol=snapshot.symbol,
                max_participation_pct=max_participation_pct,
            )
            benchmark_orders.append(candidate_order)
            if candidate_order.get("status") in {"filled", "partial_fill"}:
                benchmark_cash = candidate_cash
                benchmark_shares = candidate_shares
                benchmark_order = candidate_order
        if pending is not None:
            prior_shares = shares
            cash, shares, order, trade, commission, stamp, slippage_cost = _execute_target(
                signal_date=str(pending["date"]),
                execution=candle,
                previous_close=previous_close,
                target_weight=Decimal(str(pending["targetWeight"])),
                cash=cash,
                shares=shares,
                max_position_pct=max_position_pct,
                commission_rate=commission_rate,
                minimum_commission=minimum_commission,
                slippage_rate=slippage_rate,
                symbol=snapshot.symbol,
                max_participation_pct=max_participation_pct,
            )
            orders.append(order)
            total_commission += commission
            total_stamp += stamp
            total_slippage += slippage_cost
            if trade is not None:
                trades.append(trade)
                turnover += Decimal(str(trade["notional"]))
                if trade["side"] == "buy":
                    cost_basis += Decimal(str(trade["notional"])) + commission + stamp
                else:
                    filled = int(trade["shares"])
                    average_basis = cost_basis / prior_shares if prior_shares else Decimal(0)
                    removed_basis = average_basis * filled
                    proceeds = Decimal(str(trade["notional"])) - commission - stamp
                    realized_roundtrips.append(proceeds - removed_basis)
                    cost_basis = max(Decimal(0), cost_basis - removed_basis)
            pending = None

        equity.append(
            _equity_row(
                candle,
                cash=cash,
                shares=shares,
                benchmark_cash=benchmark_cash,
                benchmark_shares=benchmark_shares,
            )
        )
        decision = decision_rows.get(candle.date)
        if decision is not None:
            pending = decision

    current_row = equity[-1]
    current_portfolio = {
        "date": through_date,
        "cash": current_row["cash"],
        "shares": shares,
        "sellableShares": shares,
        "marketValue": current_row["marketValue"],
        "equity": current_row["equity"],
        "positionWeightPct": (
            current_row["marketValue"] / current_row["equity"] * 100.0
            if current_row["equity"] > 0
            else 0.0
        ),
        "latestOrders": orders[-5:],
    }
    if not complete:
        return {"currentPortfolio": current_portfolio, "orders": orders, "trades": trades}

    if benchmark_order is None:
        raise _benchmark_unavailable_error(benchmark_orders)
    if pending is not None:
        raise BacktestDecisionError("区间末尾存在没有下一交易日可撮合的AI决策")
    metrics = calculate_metrics(
        equity,
        initial_cash=float(initial_cash),
        trade_count=len(trades),
        closed_trade_count=len(realized_roundtrips),
        winning_trade_count=sum(1 for item in realized_roundtrips if item > 0),
        gross_turnover=float(turnover),
        total_fees=float(total_commission + total_stamp),
        commission_fees=float(total_commission),
        stamp_duty=float(total_stamp),
    )
    benchmark_commission = Decimal(str(benchmark_order.get("commission") or 0))
    benchmark_stamp = Decimal(str(benchmark_order.get("stampDuty") or 0))
    metrics["benchmarkFees"] = float(benchmark_commission + benchmark_stamp)
    metrics["slippageCost"] = float(_money(total_slippage))
    metrics["benchmarkSlippageCost"] = float(benchmark_order.get("slippageCost") or 0)
    notices = [
        "A股按100股整手买卖，现金账户，禁止做空；收盘信号下一交易日开盘执行，买入股份执行后至少持有至下一个交易日。",
        "滑点成交价限制在当日OHLC区间内；零成交量拒单。触及常见涨跌幅的单一价格日线会保守拒单，但腾讯不提供历史ST、上市初期及逐日涨跌幅状态，故limitStatus不是权威判定。",
        "佣金按用户输入的固定费率和最低佣金；印花税按成交日历史税率自动计取。未建模过户费、监管费、分红现金入账与送转股；检测到公司行动会阻断。",
        "这是历史行情上的模拟研究，不代表可成交的真实订单或未来收益。",
    ]
    if max_participation_pct is not None:
        notices.append(
            f"启用日成交量参与率上限：每只股票每个交易日的单笔成交量不超过日线成交股数的{max_participation_pct}%并下取整至100股；日线容量仅为近似，不代表开盘真实可成交。策略未成交部分不跨日续挂；基准首笔有成交（含部分成交）即固定买持，剩余现金保留。"
        )
    return {
        "status": "completed",
        "symbol": snapshot.symbol,
        "metrics": metrics,
        "equity": equity,
        "trades": trades,
        "orders": orders,
        "benchmarkOrders": benchmark_orders,
        "decisions": [dict(decision_rows[key]) for key in expected_schedule],
        "decisionSchedule": list(expected_schedule),
        "currentPortfolio": current_portfolio,
        "source": snapshot.source,
        "sourceUrl": snapshot.source_url,
        "fetchedAt": snapshot.fetched_at,
        "adjustment": "raw",
        "actionsStatus": snapshot.actions_status,
        "dataHash": snapshot.data_hash,
        "coverage": snapshot.coverage.to_dict(),
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "parameters": {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in normalized.items()
        },
        "notice": list(snapshot.notice) + notices,
    }


def simulate(
    snapshot: BacktestSnapshot,
    params: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run a complete deterministic backtest; no missing decision is treated as hold."""
    normalized = _normalize_params(params)
    schedule = _prepare_schedule(snapshot, params)
    decision_rows = _validate_decisions(decisions, schedule)
    return _simulate_prefix(
        snapshot,
        normalized,
        decision_rows,
        through_date=snapshot.candles[-1].date,
        expected_schedule=schedule,
        complete=True,
    )


def validate_benchmark(
    snapshot: BacktestSnapshot, params: Mapping[str, Any]
) -> None:
    """Check that a same-cost buy-and-hold benchmark can fill before AI work starts."""
    build_decision_schedule(snapshot, params)
    normalized = _normalize_params(params)
    initial_cash: Decimal = normalized["initialCash"]
    commission_rate: Decimal = normalized["commissionBps"] / _BPS
    minimum_commission: Decimal = normalized["minimumCommission"]
    slippage_rate: Decimal = normalized["slippageBps"] / _BPS
    attempts: list[dict[str, Any]] = []
    for index in range(1, len(snapshot.candles)):
        execution = snapshot.candles[index]
        previous_close = snapshot.candles[index - 1].close
        _, _, order = _execute_benchmark(
            execution=execution,
            previous_close=previous_close,
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
            slippage_rate=slippage_rate,
            symbol=snapshot.symbol,
            max_participation_pct=normalized.get("maxParticipationPct"),
        )
        if order.get("status") in {"filled", "partial_fill"}:
            return
        attempts.append(order)
    raise _benchmark_unavailable_error(attempts)


def portfolio_at(
    snapshot: BacktestSnapshot,
    params: Mapping[str, Any],
    decisions_so_far: Sequence[Mapping[str, Any]],
    as_of_date: str,
) -> dict[str, Any]:
    """Rebuild the portfolio at a decision close using only earlier decisions."""
    normalized = _normalize_params(params)
    schedule = _prepare_schedule(snapshot, params)
    if as_of_date not in schedule:
        raise BacktestInputError("asOfDate不是本次AI决策计划中的日期")
    prefix = tuple(item for item in schedule if item < as_of_date)
    decision_rows = _validate_decisions(decisions_so_far, prefix)
    result = _simulate_prefix(
        snapshot,
        normalized,
        decision_rows,
        through_date=as_of_date,
        expected_schedule=prefix,
        complete=False,
    )
    return result["currentPortfolio"]


__all__ = [
    "BacktestDecisionError",
    "build_decision_schedule",
    "portfolio_at",
    "simulate",
    "validate_benchmark",
]
