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
from core.web.services.financial_backtest.quantity_rules import (
    ASHARE_QUANTITY_V2,
    LEGACY_100_V1,
    SUPPORTED_QUANTITY_RULE_VERSIONS,
    floor_buy_quantity,
    floor_sell_quantity,
    maximum_affordable_buy,
    maximum_order_quantity,
    resolve_quantity_rule,
    sell_target_shares,
)

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
    quantity_rule_version = _param(
        params, "quantityRuleVersion", "quantity_rule_version", LEGACY_100_V1
    )
    if (
        not isinstance(quantity_rule_version, str)
        or quantity_rule_version not in SUPPORTED_QUANTITY_RULE_VERSIONS
    ):
        raise BacktestInputError("quantityRuleVersion不是支持的撮合股数规则")
    normalized = {
        "initialCash": initial_cash,
        "maxPositionPct": max_position_pct,
        "decisionInterval": decision_interval,
        "commissionBps": commission_bps,
        "minimumCommission": minimum_commission,
        "slippageBps": slippage_bps,
        "maxDecisions": max_decisions,
        "quantityRuleVersion": quantity_rule_version,
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


def _deduct_dividend_sale_tax(
    *,
    ledger: Any,
    day: str,
    shares: int,
    cash: Decimal,
    symbol: str,
    order: Mapping[str, Any],
    trade: Mapping[str, Any],
) -> Decimal:
    tax_due = ledger.sell(day, shares)
    if tax_due > cash:
        raise BacktestDecisionError(
            "卖出后可用现金不足以支付已到账现金分红的递延税款，回测已阻断。",
            metadata={
                "failure": "insufficient_cash_for_dividend_tax",
                "date": day,
                "symbol": symbol,
                "availableCash": str(cash),
                "dividendTaxDue": str(tax_due),
                "projectedCashAfterTax": str(cash - tax_due),
                "order": dict(order),
                "trade": dict(trade),
            },
        )
    return cash - tax_due


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


def _is_locked(
    candle: Candle, previous_close: float | Decimal | None, side: str, symbol: str
) -> str | None:
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


def _execution_reference_close(
    snapshot: BacktestSnapshot, index: int
) -> float | Decimal | None:
    """Use the ex-right reference price for execution checks, preserving raw marks."""
    if index <= 0 or index >= len(snapshot.candles):
        return None
    previous_close = snapshot.candles[index - 1].close
    artifact = getattr(snapshot, "corporate_actions", None)
    if not isinstance(artifact, Mapping):
        return previous_close
    cash_per_share = sum(
        (
            Decimal(str(event["cashPerShare"]))
            for event in artifact.get("events", ())
            if isinstance(event, Mapping)
            and event.get("exDate") == snapshot.candles[index].date
        ),
        Decimal(0),
    )
    if cash_per_share == 0:
        return previous_close
    reference = Decimal(str(previous_close)) - cash_per_share
    if reference <= 0:
        raise BacktestInputError("除息参考价必须大于0")
    return reference


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


def _new_dividend_ledger(snapshot: BacktestSnapshot) -> Any | None:
    """Create a deterministic ledger only for snapshots frozen with actions."""
    artifact = getattr(snapshot, "corporate_actions", None)
    if artifact is None:
        return None
    from core.web.services.financial_backtest.corporate_actions import DividendLedger

    return DividendLedger(snapshot.symbol, artifact)


def _dividend_net_assets(ledger: Any | None) -> Decimal:
    if ledger is None:
        return Decimal(0)
    return ledger.receivable - ledger.tax_payable


def _add_dividend_metrics(
    metrics: dict[str, Any], strategy_ledger: Any | None, benchmark_ledger: Any | None
) -> None:
    if strategy_ledger is None and benchmark_ledger is None:
        return
    for prefix, ledger in (("", strategy_ledger), ("benchmark", benchmark_ledger)):
        if ledger is None:
            gross = tax_total = tax_payable = Decimal(0)
        else:
            gross = ledger.dividends_total
            tax_total = ledger.tax_total
            tax_payable = ledger.tax_payable
        if prefix:
            metrics["benchmarkGrossDividends"] = float(gross)
            metrics["benchmarkDividendTaxPaid"] = float(tax_total - tax_payable)
            metrics["benchmarkDividendTaxPayable"] = float(tax_payable)
            metrics["benchmarkNetDividendIncome"] = float(gross - tax_total)
        else:
            metrics["grossDividends"] = float(gross)
            metrics["dividendTaxPaid"] = float(tax_total - tax_payable)
            metrics["dividendTaxPayable"] = float(tax_payable)
            metrics["netDividendIncome"] = float(gross - tax_total)
    # Existing round-trip win rates exclude dividends and deferred dividend tax.
    metrics["closedTradeCount"] = None
    metrics["winningTradeCount"] = None
    metrics["winRatePct"] = None


def _raw_shares_for_target(value: Decimal, price: Decimal) -> int:
    if value <= 0 or price <= 0:
        return 0
    return int((value / price).to_integral_value(rounding=ROUND_FLOOR))


def _shares_for_target(
    value: Decimal,
    price: Decimal,
    *,
    symbol: str = "sh600000",
    execution_date: str = "1970-01-01",
    quantity_rule_version: str = LEGACY_100_V1,
) -> int:
    requested = _raw_shares_for_target(value, price)
    if requested == 0:
        return 0
    rule = resolve_quantity_rule(symbol, execution_date, quantity_rule_version)
    return floor_buy_quantity(requested, rule)


def _max_participation_shares(
    execution: Candle,
    max_participation_pct: Decimal | None,
) -> int | None:
    """Return the raw whole-share daily cap; the board rule rounds per side.

    Missing participation limits preserve the legacy unlimited-volume behavior.
    Candle volume is already normalized to shares by the frozen-data layer.
    """
    if max_participation_pct is None:
        return None
    allowed = Decimal(str(execution.volume)) * max_participation_pct / Decimal(100)
    whole_shares = int(allowed.to_integral_value(rounding=ROUND_FLOOR))
    return whole_shares


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
    previous_close: float | Decimal | None,
    target_weight: Decimal,
    cash: Decimal,
    shares: int,
    max_position_pct: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    symbol: str,
    extra_equity: Decimal = Decimal(0),
    max_participation_pct: Decimal | None = None,
    quantity_rule_version: str = LEGACY_100_V1,
) -> tuple[Decimal, int, dict[str, Any], dict[str, Any] | None, Decimal, Decimal, Decimal]:
    if target_weight > max_position_pct / Decimal(100):
        raise BacktestDecisionError("AI目标仓位超过本次最大仓位上限")
    open_price = Decimal(str(execution.open))
    pre_equity = _account_equity(cash, shares, open_price) + extra_equity
    target_value = pre_equity * target_weight
    # Position sizing uses the observable next open. Slippage affects the fill
    # and cash constraint only, never the target percentage calculation.
    rule = resolve_quantity_rule(symbol, execution.date, quantity_rule_version)
    desired = _shares_for_target(
        target_value,
        open_price,
        symbol=symbol,
        execution_date=execution.date,
        quantity_rule_version=quantity_rule_version,
    )
    desired = sell_target_shares(shares, desired, rule)
    delta = desired - shares
    if delta == 0:
        raw_desired = _raw_shares_for_target(target_value, open_price)
        if (
            shares == 0
            and raw_desired > 0
            and quantity_rule_version == ASHARE_QUANTITY_V2
        ):
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side="buy",
                status="rejected",
                reason="below_board_minimum_buy",
                requested_shares=raw_desired,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)
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

    participation_cap = _max_participation_shares(
        execution, max_participation_pct
    )
    order_cap = maximum_order_quantity(rule)
    order_limited = order_cap is not None and requested > order_cap
    volume_limited = participation_cap is not None and participation_cap < requested
    fill_limit = min(
        requested,
        order_cap if order_cap is not None else requested,
        participation_cap if participation_cap is not None else requested,
    )

    if side == "buy":
        filled = floor_buy_quantity(fill_limit, rule)
        sell_increment_limited = False
        if not filled:
            reason = (
                (
                    "volume_participation_below_one_lot"
                    if quantity_rule_version == LEGACY_100_V1
                    else "volume_participation_below_minimum_order"
                )
                if volume_limited
                else "order_quantity_below_minimum"
                if order_limited
                else "below_board_minimum_buy"
            )
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason=reason,
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

        def is_affordable(candidate: int) -> bool:
            notional = Decimal(candidate) * fill_price
            commission = _fee(notional, commission_rate, minimum_commission)
            stamp = _stamp_duty(notional, execution.date, side)
            return notional + commission + stamp <= cash

        filled = maximum_affordable_buy(fill_limit, rule, is_affordable)
        if not filled:
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason=(
                    "insufficient_cash_for_one_lot"
                    if quantity_rule_version == LEGACY_100_V1
                    else "insufficient_cash_for_minimum_order"
                ),
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
        filled = floor_sell_quantity(requested, shares, fill_limit, rule)
        sell_increment_limited = (
            filled > 0
            and filled < min(requested, fill_limit)
            and not order_limited
            and not volume_limited
        )
        if not filled:
            reason = (
                "volume_participation_below_sell_increment"
                if volume_limited and fill_limit < rule.minimum_sell_shares
                else "order_quantity_below_sell_increment"
                if order_limited and fill_limit < rule.minimum_sell_shares
                else "below_minimum_sell_order"
                if requested < rule.minimum_sell_shares and requested < shares
                else "no_sellable_quantity"
            )
            order = _make_order(
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason=reason,
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
        status="partial_fill"
        if volume_limited or order_limited or sell_increment_limited
        else "filled",
        reason=(
            "order_and_volume_quantity_limit"
            if order_limited and volume_limited
            else "order_quantity_limit"
            if order_limited
            else "daily_volume_participation_limit"
            if volume_limited
            else "board_sell_increment_limit"
            if sell_increment_limited
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
    previous_close: float | Decimal | None,
    initial_cash: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    symbol: str,
    max_participation_pct: Decimal | None = None,
    quantity_rule_version: str = LEGACY_100_V1,
) -> tuple[Decimal, int, dict[str, Any]]:
    fill_price, per_share_slippage = _execution_price(execution, "buy", slippage_rate)
    rejection = _is_locked(execution, previous_close, "buy", symbol)
    if rejection:
        return initial_cash, 0, _make_order(
            signal_date=execution.date, candle=execution, side="buy",
            status="rejected", reason=rejection, requested_shares=0,
        )
    rule = resolve_quantity_rule(symbol, execution.date, quantity_rule_version)
    requested = _shares_for_target(
        Decimal(initial_cash),
        fill_price,
        symbol=symbol,
        execution_date=execution.date,
        quantity_rule_version=quantity_rule_version,
    )
    raw_requested = _raw_shares_for_target(Decimal(initial_cash), fill_price)
    if (
        quantity_rule_version == ASHARE_QUANTITY_V2
        and raw_requested > 0
        and requested == 0
    ):
        return initial_cash, 0, _make_order(
            signal_date=execution.date,
            candle=execution,
            side="buy",
            status="rejected",
            reason="below_board_minimum_buy",
            requested_shares=raw_requested,
        )
    participation_cap = _max_participation_shares(
        execution, max_participation_pct
    )
    order_cap = maximum_order_quantity(rule)
    order_limited = order_cap is not None and requested > order_cap
    volume_limited = participation_cap is not None and participation_cap < requested
    fill_limit = min(
        requested,
        order_cap if order_cap is not None else requested,
        participation_cap if participation_cap is not None else requested,
    )
    fill_limit = floor_buy_quantity(fill_limit, rule)
    if requested and fill_limit == 0:
        return initial_cash, 0, _make_order(
            signal_date=execution.date,
            candle=execution,
            side="buy",
            status="rejected",
            reason=(
                (
                    "volume_participation_below_one_lot"
                    if quantity_rule_version == LEGACY_100_V1
                    else "volume_participation_below_minimum_order"
                )
                if volume_limited
                else "order_quantity_below_minimum"
                if order_limited
                else "below_board_minimum_buy"
            ),
            requested_shares=requested,
        )

    def is_affordable(candidate: int) -> bool:
        notional = Decimal(candidate) * fill_price
        fee = _fee(notional, commission_rate, minimum_commission)
        stamp = _stamp_duty(notional, execution.date, "buy")
        return notional + fee + stamp <= initial_cash

    filled = maximum_affordable_buy(fill_limit, rule, is_affordable)
    if not filled:
        return initial_cash, 0, _make_order(
            signal_date=execution.date, candle=execution, side="buy",
            status="rejected",
            reason=(
                "insufficient_cash_for_one_lot"
                if quantity_rule_version == LEGACY_100_V1
                else "insufficient_cash_for_minimum_order"
            ),
            requested_shares=requested,
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
        status="partial_fill" if volume_limited or order_limited else "filled",
        reason=(
            "order_and_volume_quantity_limit"
            if order_limited and volume_limited
            else "order_quantity_limit"
            if order_limited
            else "daily_volume_participation_limit"
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
    dividend_ledger: Any | None = None,
    benchmark_dividend_ledger: Any | None = None,
) -> dict[str, Any]:
    close = Decimal(str(candle.close))
    equity = _account_equity(cash, shares, close) + _dividend_net_assets(
        dividend_ledger
    )
    benchmark_equity = _account_equity(
        benchmark_cash, benchmark_shares, close
    ) + _dividend_net_assets(benchmark_dividend_ledger)
    row = {
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
    if dividend_ledger is not None or benchmark_dividend_ledger is not None:
        row.update(
            {
                "dividendReceivable": float(
                    _money(
                        Decimal(0)
                        if dividend_ledger is None
                        else dividend_ledger.receivable
                    )
                ),
                "dividendTaxPayable": float(
                    _money(
                        Decimal(0)
                        if dividend_ledger is None
                        else dividend_ledger.tax_payable
                    )
                ),
                "benchmarkDividendReceivable": float(
                    _money(
                        Decimal(0)
                        if benchmark_dividend_ledger is None
                        else benchmark_dividend_ledger.receivable
                    )
                ),
                "benchmarkDividendTaxPayable": float(
                    _money(
                        Decimal(0)
                        if benchmark_dividend_ledger is None
                        else benchmark_dividend_ledger.tax_payable
                    )
                ),
            }
        )
    return row


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
    quantity_rule_version: str = normalized["quantityRuleVersion"]
    cash = initial_cash
    shares = 0
    benchmark_cash = initial_cash
    benchmark_shares = 0
    dividend_ledger = _new_dividend_ledger(snapshot)
    benchmark_dividend_ledger = _new_dividend_ledger(snapshot)
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
        opening_shares = shares
        previous_close = _execution_reference_close(snapshot, index)
        if dividend_ledger is not None:
            dividend_ledger.open_session(candle.date)
        if benchmark_dividend_ledger is not None:
            benchmark_dividend_ledger.open_session(candle.date)
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
                quantity_rule_version=quantity_rule_version,
            )
            benchmark_orders.append(candidate_order)
            if candidate_order.get("status") in {"filled", "partial_fill"}:
                benchmark_cash = candidate_cash
                benchmark_shares = candidate_shares
                benchmark_order = candidate_order
                if benchmark_dividend_ledger is not None and candidate_shares:
                    benchmark_dividend_ledger.buy(candle.date, candidate_shares)
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
                extra_equity=_dividend_net_assets(dividend_ledger),
                max_participation_pct=max_participation_pct,
                quantity_rule_version=quantity_rule_version,
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
                    if dividend_ledger is not None:
                        dividend_ledger.buy(candle.date, int(trade["shares"]))
                else:
                    filled = int(trade["shares"])
                    if dividend_ledger is not None:
                        cash = _deduct_dividend_sale_tax(
                            ledger=dividend_ledger,
                            day=candle.date,
                            shares=filled,
                            cash=cash,
                            symbol=snapshot.symbol,
                            order=order,
                            trade=trade,
                        )
                    average_basis = cost_basis / prior_shares if prior_shares else Decimal(0)
                    removed_basis = average_basis * filled
                    proceeds = Decimal(str(trade["notional"])) - commission - stamp
                    realized_roundtrips.append(proceeds - removed_basis)
                    cost_basis = max(Decimal(0), cost_basis - removed_basis)
            pending = None

        if dividend_ledger is not None:
            cash += dividend_ledger.close_session(candle.date)
        if benchmark_dividend_ledger is not None:
            benchmark_cash += benchmark_dividend_ledger.close_session(candle.date)

        equity.append(
            _equity_row(
                candle,
                cash=cash,
                shares=shares,
                benchmark_cash=benchmark_cash,
                benchmark_shares=benchmark_shares,
                dividend_ledger=dividend_ledger,
                benchmark_dividend_ledger=benchmark_dividend_ledger,
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
        "sellableShares": (
            min(opening_shares, shares)
            if quantity_rule_version == ASHARE_QUANTITY_V2 else shares
        ),
        "marketValue": current_row["marketValue"],
        "equity": current_row["equity"],
        "positionWeightPct": (
            current_row["marketValue"] / current_row["equity"] * 100.0
            if current_row["equity"] > 0
            else 0.0
        ),
        "latestOrders": orders[-5:],
    }
    if dividend_ledger is not None:
        current_portfolio.update(
            {
                "dividendReceivable": float(_money(dividend_ledger.receivable)),
                "dividendTaxPayable": float(_money(dividend_ledger.tax_payable)),
            }
        )
    if not complete:
        result = {
            "currentPortfolio": current_portfolio,
            "orders": orders,
            "trades": trades,
        }
        if dividend_ledger is not None:
            result["dividendAccounting"] = dividend_ledger.audit()
            result["benchmarkDividendAccounting"] = benchmark_dividend_ledger.audit()
        return result

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
    _add_dividend_metrics(metrics, dividend_ledger, benchmark_dividend_ledger)
    benchmark_commission = Decimal(str(benchmark_order.get("commission") or 0))
    benchmark_stamp = Decimal(str(benchmark_order.get("stampDuty") or 0))
    metrics["benchmarkFees"] = float(benchmark_commission + benchmark_stamp)
    metrics["slippageCost"] = float(_money(total_slippage))
    metrics["benchmarkSlippageCost"] = float(benchmark_order.get("slippageCost") or 0)
    quantity_notice = (
        "按板块和成交日撮合A股数量：主板/创业板按100股递增；科创板买卖至少200股、北交所至少100股且1股递增，门槛以下余股只可整仓一次卖出。限价单上限为科创板10万股、创业板2020-08-24起30万股、主板/北交所100万股；未模拟市价单、集合竞价或盘口。"
        if quantity_rule_version == ASHARE_QUANTITY_V2
        else "沿用 legacy_100_v1：所有股票均按100股整手计算，供旧回测回放。"
    )
    action_notice = (
        "现金分红按冻结的官方实施公告记入：登记日收盘确认权益，除权日确认为应收，派息日收盘转为可用现金；卖出时按FIFO持有期评估红利税。分币结算规则尚未核实。"
        if dividend_ledger is not None
        else "佣金按用户输入的固定费率和最低佣金；印花税按成交日历史税率自动计取。未建模过户费、监管费、分红现金入账与送转股；检测到公司行动会阻断。"
    )
    notices = [
        quantity_notice,
        "A股现金账户，禁止做空；收盘信号下一交易日开盘执行，买入股份执行后至少持有至下一个交易日。",
        "滑点成交价限制在当日OHLC区间内；零成交量拒单。触及常见涨跌幅的单一价格日线会保守拒单，但腾讯不提供历史ST、上市初期及逐日涨跌幅状态，故limitStatus不是权威判定。",
        action_notice,
        "这是历史行情上的模拟研究，不代表可成交的真实订单或未来收益。",
    ]
    if max_participation_pct is not None:
        notices.append(
            f"启用日成交量参与率上限：每只股票每个交易日的单笔成交量不超过日线成交股数的{max_participation_pct}%，并按板块数量规则向下调整；日线容量仅为近似，不代表开盘真实可成交。策略未成交部分不跨日续挂；基准首笔有成交（含部分成交）即固定买持，剩余现金保留。"
        )
    result = {
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
    if dividend_ledger is not None:
        result["dividendAccounting"] = dividend_ledger.audit()
        result["benchmarkDividendAccounting"] = benchmark_dividend_ledger.audit()
    return result


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
        previous_close = _execution_reference_close(snapshot, index)
        _, _, order = _execute_benchmark(
            execution=execution,
            previous_close=previous_close,
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
            slippage_rate=slippage_rate,
            symbol=snapshot.symbol,
            max_participation_pct=normalized.get("maxParticipationPct"),
            quantity_rule_version=normalized["quantityRuleVersion"],
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
