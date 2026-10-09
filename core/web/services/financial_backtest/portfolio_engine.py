"""Deterministic shared-cash portfolio simulation over frozen basket data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from core.web.services.financial_backtest import engine as single_engine
from core.web.services.financial_backtest.basket_data import (
    BasketSnapshot,
    validate_basket_snapshot,
)
from core.web.services.financial_backtest.data import (
    BacktestInputError,
    Candle,
)
from core.web.services.financial_backtest.metrics import calculate_metrics

_LOT_SIZE = single_engine._LOT_SIZE
_BPS = single_engine._BPS


def build_decision_schedule(
    snapshot: BasketSnapshot, params: Mapping[str, Any] | None = None
) -> tuple[str, ...]:
    """Return the complete close-time schedule with an in-range next open."""
    validate_basket_snapshot(snapshot)
    first_asset = snapshot.assets[snapshot.symbols[0]]
    return single_engine.build_decision_schedule(first_asset, params)


def _validate_decisions(
    decisions: Sequence[Mapping[str, Any]],
    expected_dates: tuple[str, ...],
    symbols: tuple[str, ...],
    max_position_pct: Decimal,
) -> dict[str, dict[str, Any]]:
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        raise single_engine.BacktestDecisionError("AI组合决策必须是列表")
    by_date: dict[str, dict[str, Any]] = {}
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise single_engine.BacktestDecisionError("AI组合决策行必须是对象")
        decision_date = raw.get("date")
        if not isinstance(decision_date, str) or decision_date not in expected_dates:
            raise single_engine.BacktestDecisionError(
                "AI决策日期不在完整交易日决策计划内"
            )
        if decision_date in by_date:
            raise single_engine.BacktestDecisionError(
                f"AI决策日期重复：{decision_date}"
            )
        raw_weights = raw.get("targetWeights")
        if not isinstance(raw_weights, Mapping) or set(raw_weights) != set(symbols):
            raise single_engine.BacktestDecisionError(
                "targetWeights必须完整覆盖本次全部股票且不能多传"
            )
        weights: dict[str, Decimal] = {}
        for symbol in symbols:
            weight = single_engine._decimal(
                raw_weights[symbol],
                f"targetWeights.{symbol}",
                minimum=Decimal(0),
                maximum=Decimal(1),
            )
            if weight > max_position_pct / Decimal(100):
                raise single_engine.BacktestDecisionError(
                    f"股票{symbol}的目标仓位超过本次最大仓位上限"
                )
            weights[symbol] = weight
        if sum(weights.values(), Decimal(0)) > Decimal(1):
            raise single_engine.BacktestDecisionError("组合目标权重之和不能超过1")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2_000:
            raise single_engine.BacktestDecisionError(
                "每个AI组合决策都必须有不超过2000字的理由"
            )
        row: dict[str, Any] = {
            "date": decision_date,
            "targetWeights": {symbol: float(weights[symbol]) for symbol in symbols},
            "reason": reason.strip(),
        }
        confidence = raw.get("confidence")
        if confidence is not None:
            row["confidence"] = float(
                single_engine._decimal(
                    confidence,
                    "confidence",
                    minimum=Decimal(0),
                    maximum=Decimal(1),
                )
            )
        for key in ("inputHash", "outputHash"):
            value = raw.get(key)
            if value is not None:
                if not isinstance(value, str) or not single_engine._HASH_RE.fullmatch(
                    value
                ):
                    raise single_engine.BacktestDecisionError(
                        f"{key}必须是SHA-256十六进制摘要"
                    )
                row[key] = value
        by_date[decision_date] = row
    if set(by_date) != set(expected_dates):
        missing = [value for value in expected_dates if value not in by_date]
        extra = [value for value in by_date if value not in expected_dates]
        raise single_engine.BacktestDecisionError(
            "AI组合决策计划不完整；缺少="
            + ",".join(missing[:8])
            + "; 多余="
            + ",".join(extra[:8])
        )
    return by_date


def _symbol_order(
    *,
    symbol: str,
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
    order = single_engine._make_order(
        signal_date=signal_date,
        candle=candle,
        side=side,
        status=status,
        reason=reason,
        requested_shares=requested_shares,
        filled_shares=filled_shares,
        fill_price=fill_price,
        commission=commission,
        stamp=stamp,
        slippage_cost=slippage_cost,
    )
    order["symbol"] = symbol
    return order


def _execute_target(
    *,
    symbol: str,
    signal_date: str,
    execution: Candle,
    previous_close: float | None,
    desired_shares: int,
    cash: Decimal,
    shares: int,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    max_participation_pct: Decimal | None = None,
) -> tuple[
    Decimal, int, dict[str, Any], dict[str, Any] | None, Decimal, Decimal, Decimal
]:
    delta = desired_shares - shares
    if delta == 0:
        order = _symbol_order(
            symbol=symbol,
            signal_date=signal_date,
            candle=execution,
            side="hold",
            status="no_action",
            reason="target_shares_unchanged",
            requested_shares=0,
        )
        return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    side = "buy" if delta > 0 else "sell"
    requested = abs(delta)
    fill_price, per_share_slippage = single_engine._execution_price(
        execution, side, slippage_rate
    )
    rejection = single_engine._is_locked(execution, previous_close, side, symbol)
    if rejection:
        order = _symbol_order(
            symbol=symbol,
            signal_date=signal_date,
            candle=execution,
            side=side,
            status="rejected",
            reason=rejection,
            requested_shares=requested,
        )
        return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    if side == "buy":
        executable_requested = (requested // _LOT_SIZE) * _LOT_SIZE
    else:
        executable_requested = (min(shares, requested) // _LOT_SIZE) * _LOT_SIZE
        if not executable_requested:
            order = _symbol_order(
                symbol=symbol,
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="no_sellable_board_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    participation_cap = single_engine._max_participation_shares(
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
        order = _symbol_order(
            symbol=symbol,
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
            commission = single_engine._fee(
                notional, commission_rate, minimum_commission
            )
            stamp = single_engine._stamp_duty(notional, execution.date, side)
            if notional + commission + stamp <= cash:
                break
            filled -= _LOT_SIZE
        if not filled:
            order = _symbol_order(
                symbol=symbol,
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="insufficient_cash_for_one_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)
    else:
        filled = min(shares, fill_limit)
        filled = (filled // _LOT_SIZE) * _LOT_SIZE
        if not filled:
            order = _symbol_order(
                symbol=symbol,
                signal_date=signal_date,
                candle=execution,
                side=side,
                status="rejected",
                reason="no_sellable_board_lot",
                requested_shares=requested,
            )
            return cash, shares, order, None, Decimal(0), Decimal(0), Decimal(0)

    notional = Decimal(filled) * fill_price
    commission = single_engine._fee(notional, commission_rate, minimum_commission)
    stamp = single_engine._stamp_duty(notional, execution.date, side)
    fee = commission + stamp
    if side == "buy":
        cash -= notional + fee
        shares += filled
    else:
        cash += notional - fee
        shares -= filled
    trade = {
        "symbol": symbol,
        "signalDate": signal_date,
        "date": execution.date,
        "side": side,
        "price": float(fill_price),
        "units": filled,
        "shares": filled,
        "fee": float(fee),
        "commission": float(commission),
        "stampDuty": float(stamp),
        "slippageCost": float(
            single_engine._money(Decimal(filled) * per_share_slippage)
        ),
        "notional": float(single_engine._money(notional)),
        "tPlusOne": True,
    }
    order = _symbol_order(
        symbol=symbol,
        signal_date=signal_date,
        candle=execution,
        side=side,
        status="partial_fill" if volume_limited else "filled",
        reason=(
            "daily_volume_participation_limit"
            if volume_limited
            else (
                "next_session_open"
                if filled == requested
                else "cash_limited_board_lots"
            )
        ),
        requested_shares=requested,
        filled_shares=filled,
        fill_price=fill_price,
        commission=commission,
        stamp=stamp,
        slippage_cost=per_share_slippage,
    )
    return (
        cash,
        shares,
        order,
        trade,
        commission,
        stamp,
        Decimal(filled) * per_share_slippage,
    )


def _cash_sleeves(
    initial_cash: Decimal, symbols: tuple[str, ...]
) -> dict[str, Decimal]:
    sleeve = initial_cash / Decimal(len(symbols))
    result = {symbol: sleeve for symbol in symbols}
    # Keep every cent and any fractional-cent precision in the benchmark account.
    result[symbols[-1]] = initial_cash - sum(
        (result[symbol] for symbol in symbols[:-1]), Decimal(0)
    )
    return result


def _execute_benchmark_sleeve(
    *,
    symbol: str,
    execution: Candle,
    previous_close: float | None,
    cash: Decimal,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    slippage_rate: Decimal,
    max_participation_pct: Decimal | None = None,
) -> tuple[Decimal, int, dict[str, Any]]:
    """Buy one equal-weight sleeve, reserving cash for every applicable fee."""
    fill_price, per_share_slippage = single_engine._execution_price(
        execution, "buy", slippage_rate
    )
    rejection = single_engine._is_locked(execution, previous_close, "buy", symbol)
    if rejection:
        return (
            cash,
            0,
            _symbol_order(
                symbol=symbol,
                signal_date=execution.date,
                candle=execution,
                side="buy",
                status="rejected",
                reason=rejection,
                requested_shares=0,
            ),
        )
    requested = single_engine._shares_for_target(cash, fill_price)
    participation_cap = single_engine._max_participation_shares(
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
        return (
            cash,
            0,
            _symbol_order(
                symbol=symbol,
                signal_date=execution.date,
                candle=execution,
                side="buy",
                status="rejected",
                reason="volume_participation_below_one_lot",
                requested_shares=requested,
            ),
        )
    filled = fill_limit
    while filled:
        notional = Decimal(filled) * fill_price
        commission = single_engine._fee(notional, commission_rate, minimum_commission)
        stamp = single_engine._stamp_duty(notional, execution.date, "buy")
        if notional + commission + stamp <= cash:
            break
        filled -= _LOT_SIZE
    if not filled:
        return (
            cash,
            0,
            _symbol_order(
                symbol=symbol,
                signal_date=execution.date,
                candle=execution,
                side="buy",
                status="rejected",
                reason="insufficient_cash_for_one_lot",
                requested_shares=requested,
            ),
        )
    notional = Decimal(filled) * fill_price
    commission = single_engine._fee(notional, commission_rate, minimum_commission)
    stamp = single_engine._stamp_duty(notional, execution.date, "buy")
    remaining_cash = cash - notional - commission - stamp
    order = _symbol_order(
        symbol=symbol,
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
    return remaining_cash, filled, order


def _current_portfolio(
    snapshot: BasketSnapshot,
    *,
    through_date: str,
    cash: Decimal,
    shares: Mapping[str, int],
    sellable_shares: Mapping[str, int],
    latest_orders: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    index = snapshot.session_dates.index(through_date)
    market_values: dict[str, Decimal] = {}
    position_rows: list[dict[str, Any]] = []
    for symbol in snapshot.symbols:
        close = Decimal(str(snapshot.assets[symbol].candles[index].close))
        market_value = Decimal(shares[symbol]) * close
        market_values[symbol] = market_value
    total_market_value = sum(market_values.values(), Decimal(0))
    equity = cash + total_market_value
    for symbol in snapshot.symbols:
        candle = snapshot.assets[symbol].candles[index]
        market_value = market_values[symbol]
        position_rows.append(
            {
                "symbol": symbol,
                "shares": shares[symbol],
                "sellableShares": sellable_shares[symbol],
                "marketValue": float(single_engine._money(market_value)),
                "weightPct": float(market_value / equity * 100) if equity > 0 else 0.0,
                "close": candle.close,
            }
        )
    return {
        "date": through_date,
        "cash": float(single_engine._money(cash)),
        "equity": float(single_engine._money(equity)),
        "marketValue": float(single_engine._money(total_market_value)),
        "positionWeightPct": float(total_market_value / equity * 100)
        if equity > 0
        else 0.0,
        "positions": position_rows,
        "latestOrders": [dict(order) for order in latest_orders[-5:]],
    }


def _simulate_prefix(
    snapshot: BasketSnapshot,
    normalized: Mapping[str, Any],
    decision_rows: Mapping[str, Mapping[str, Any]],
    *,
    through_date: str,
    expected_schedule: tuple[str, ...],
    complete: bool,
) -> dict[str, Any]:
    if through_date not in snapshot.session_dates:
        raise BacktestInputError("asOfDate必须是所选区间内的完整交易日")
    end_index = snapshot.session_dates.index(through_date)
    symbols = snapshot.symbols
    initial_cash: Decimal = normalized["initialCash"]
    commission_rate: Decimal = normalized["commissionBps"] / _BPS
    minimum_commission: Decimal = normalized["minimumCommission"]
    slippage_rate: Decimal = normalized["slippageBps"] / _BPS
    max_participation_pct: Decimal | None = normalized.get("maxParticipationPct")
    cash = initial_cash
    shares = {symbol: 0 for symbol in symbols}
    cost_basis = {symbol: Decimal(0) for symbol in symbols}
    benchmark_cash = _cash_sleeves(initial_cash, symbols)
    benchmark_shares = {symbol: 0 for symbol in symbols}
    benchmark_filled: set[str] = set()
    benchmark_orders: list[dict[str, Any]] = []
    benchmark_commission = Decimal(0)
    benchmark_stamp = Decimal(0)
    benchmark_slippage = Decimal(0)
    pending: Mapping[str, Any] | None = None
    orders: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    total_commission = Decimal(0)
    total_stamp = Decimal(0)
    total_slippage = Decimal(0)
    turnover = Decimal(0)
    realized_roundtrips: list[Decimal] = []
    latest_sellable_shares = dict(shares)

    for index, session_date in enumerate(snapshot.session_dates[: end_index + 1]):
        candles = {symbol: snapshot.assets[symbol].candles[index] for symbol in symbols}
        bought_this_session = {symbol: 0 for symbol in symbols}
        previous_closes = {
            symbol: snapshot.assets[symbol].candles[index - 1].close
            if index > 0
            else None
            for symbol in symbols
        }
        # Each benchmark ticker retains its original equal-weight cash sleeve.
        for symbol in symbols:
            # Both strategies first have an executable signal after day-one close.
            if index == 0 or symbol in benchmark_filled:
                continue
            candle = candles[symbol]
            benchmark_cash[symbol], benchmark_shares[symbol], order = (
                _execute_benchmark_sleeve(
                    execution=candle,
                    previous_close=previous_closes[symbol],
                    cash=benchmark_cash[symbol],
                    commission_rate=commission_rate,
                    minimum_commission=minimum_commission,
                    slippage_rate=slippage_rate,
                    max_participation_pct=max_participation_pct,
                    symbol=symbol,
                )
            )
            benchmark_orders.append(order)
            if order.get("status") in {"filled", "partial_fill"}:
                benchmark_filled.add(symbol)
                benchmark_commission += Decimal(str(order.get("commission") or 0))
                benchmark_stamp += Decimal(str(order.get("stampDuty") or 0))
                benchmark_slippage += Decimal(str(order.get("slippageCost") or 0))

        if pending is not None:
            open_prices = {
                symbol: Decimal(str(candles[symbol].open)) for symbol in symbols
            }
            pre_trade_equity = cash + sum(
                (Decimal(shares[symbol]) * open_prices[symbol] for symbol in symbols),
                Decimal(0),
            )
            desired_shares = {
                symbol: single_engine._shares_for_target(
                    pre_trade_equity * Decimal(str(pending["targetWeights"][symbol])),
                    open_prices[symbol],
                )
                for symbol in symbols
            }
            session_orders: list[dict[str, Any]] = []
            for symbol in symbols:
                if desired_shares[symbol] >= shares[symbol]:
                    continue
                prior_shares = shares[symbol]
                cash, shares[symbol], order, trade, commission, stamp, slip = (
                    _execute_target(
                        symbol=symbol,
                        signal_date=str(pending["date"]),
                        execution=candles[symbol],
                        previous_close=previous_closes[symbol],
                        desired_shares=desired_shares[symbol],
                        cash=cash,
                        shares=shares[symbol],
                        commission_rate=commission_rate,
                        minimum_commission=minimum_commission,
                        slippage_rate=slippage_rate,
                        max_participation_pct=max_participation_pct,
                    )
                )
                session_orders.append(order)
                total_commission += commission
                total_stamp += stamp
                total_slippage += slip
                if trade is not None:
                    trades.append(trade)
                    turnover += Decimal(str(trade["notional"]))
                    filled = int(trade["shares"])
                    average_basis = (
                        cost_basis[symbol] / prior_shares
                        if prior_shares
                        else Decimal(0)
                    )
                    removed_basis = average_basis * filled
                    proceeds = Decimal(str(trade["notional"])) - commission - stamp
                    realized_roundtrips.append(proceeds - removed_basis)
                    cost_basis[symbol] = max(
                        Decimal(0), cost_basis[symbol] - removed_basis
                    )

            for symbol in symbols:
                if desired_shares[symbol] != shares[symbol] or any(
                    order.get("symbol") == symbol for order in session_orders
                ):
                    continue
                _cash, _shares, order, _trade, _commission, _stamp, _slip = (
                    _execute_target(
                        symbol=symbol,
                        signal_date=str(pending["date"]),
                        execution=candles[symbol],
                        previous_close=previous_closes[symbol],
                        desired_shares=desired_shares[symbol],
                        cash=cash,
                        shares=shares[symbol],
                        commission_rate=commission_rate,
                        minimum_commission=minimum_commission,
                        slippage_rate=slippage_rate,
                        max_participation_pct=max_participation_pct,
                    )
                )
                session_orders.append(order)

            for symbol in symbols:
                if desired_shares[symbol] <= shares[symbol]:
                    continue
                cash, shares[symbol], order, trade, commission, stamp, slip = (
                    _execute_target(
                        symbol=symbol,
                        signal_date=str(pending["date"]),
                        execution=candles[symbol],
                        previous_close=previous_closes[symbol],
                        desired_shares=desired_shares[symbol],
                        cash=cash,
                        shares=shares[symbol],
                        commission_rate=commission_rate,
                        minimum_commission=minimum_commission,
                        slippage_rate=slippage_rate,
                        max_participation_pct=max_participation_pct,
                    )
                )
                session_orders.append(order)
                total_commission += commission
                total_stamp += stamp
                total_slippage += slip
                if trade is not None:
                    trades.append(trade)
                    turnover += Decimal(str(trade["notional"]))
                    cost_basis[symbol] += (
                        Decimal(str(trade["notional"])) + commission + stamp
                    )
                    bought_this_session[symbol] += int(trade["shares"])
            orders.extend(session_orders)
            pending = None

        latest_sellable_shares = {
            symbol: shares[symbol] - bought_this_session[symbol] for symbol in symbols
        }

        close_values = {
            symbol: Decimal(str(candles[symbol].close)) for symbol in symbols
        }
        market_values = {
            symbol: Decimal(shares[symbol]) * close_values[symbol] for symbol in symbols
        }
        equity_value = cash + sum(market_values.values(), Decimal(0))
        benchmark_equity = sum(
            (
                benchmark_cash[symbol]
                + Decimal(benchmark_shares[symbol]) * close_values[symbol]
                for symbol in symbols
            ),
            Decimal(0),
        )
        equity_rows.append(
            {
                "date": session_date,
                "equity": float(single_engine._money(equity_value)),
                "benchmarkEquity": float(single_engine._money(benchmark_equity)),
                "cash": float(single_engine._money(cash)),
                "marketValue": float(
                    single_engine._money(sum(market_values.values(), Decimal(0)))
                ),
                "positions": dict(shares),
                "marketValues": {
                    symbol: float(single_engine._money(market_values[symbol]))
                    for symbol in symbols
                },
                "sellablePositions": dict(latest_sellable_shares),
                "benchmarkCash": float(
                    single_engine._money(sum(benchmark_cash.values(), Decimal(0)))
                ),
                "benchmarkPositions": dict(benchmark_shares),
            }
        )
        decision = decision_rows.get(session_date)
        if decision is not None:
            pending = decision

    current_portfolio = _current_portfolio(
        snapshot,
        through_date=through_date,
        cash=cash,
        shares=shares,
        sellable_shares=latest_sellable_shares,
        latest_orders=orders,
    )
    if not complete:
        return {
            "currentPortfolio": current_portfolio,
            "orders": orders,
            "trades": trades,
        }
    if pending is not None:
        raise single_engine.BacktestDecisionError(
            "区间末尾存在没有下一交易日可撮合的AI决策"
        )

    metrics = calculate_metrics(
        equity_rows,
        initial_cash=float(initial_cash),
        trade_count=len(trades),
        closed_trade_count=len(realized_roundtrips),
        winning_trade_count=sum(1 for item in realized_roundtrips if item > 0),
        gross_turnover=float(turnover),
        total_fees=float(total_commission + total_stamp),
        commission_fees=float(total_commission),
        stamp_duty=float(total_stamp),
    )
    metrics["benchmarkFees"] = float(benchmark_commission + benchmark_stamp)
    metrics["slippageCost"] = float(single_engine._money(total_slippage))
    metrics["benchmarkSlippageCost"] = float(single_engine._money(benchmark_slippage))
    unfilled_benchmark = [
        symbol for symbol in symbols if symbol not in benchmark_filled
    ]
    benchmark_status = (
        "invested"
        if not unfilled_benchmark
        else ("partial_cash_sleeves" if benchmark_filled else "cash_only")
    )
    notices = [
        "A股组合使用共享现金，按100股整手买卖、禁止做空；收盘信号下一共同交易日开盘执行。",
        "同一开盘先按交易前组合权益计算全部目标股数，再卖后买；买单按规范股票代码顺序竞争现金。",
        "基准为每只股票预留等额固定现金份额；无成交的拒单日可在后续交易日重试，首笔完整或部分成交即固定买持，剩余现金保留。",
        "期末持仓按收盘价估值，不假设强制平仓；回测不代表真实订单可成交或未来收益。",
    ]
    if max_participation_pct is not None:
        notices.append(
            f"启用日成交量参与率上限：每只股票每个交易日的单笔成交量不超过日线成交股数的{max_participation_pct}%并下取整至100股；日线容量仅为近似，不代表开盘真实可成交。策略未成交部分不跨日续挂；基准首笔有成交（含部分成交）即固定买持，剩余现金保留。"
        )
    return {
        "status": "completed",
        "symbols": list(symbols),
        "metrics": metrics,
        "equity": equity_rows,
        "trades": trades,
        "orders": orders,
        "benchmarkOrders": benchmark_orders,
        "benchmarkStatus": benchmark_status,
        "unfilledBenchmarkSymbols": unfilled_benchmark,
        "decisions": [dict(decision_rows[key]) for key in expected_schedule],
        "decisionSchedule": list(expected_schedule),
        "currentPortfolio": current_portfolio,
        "source": snapshot.source,
        "dataHash": snapshot.data_hash,
        "assetDataHashes": {
            symbol: snapshot.assets[symbol].data_hash for symbol in symbols
        },
        "coverage": {
            symbol: snapshot.assets[symbol].coverage.to_dict() for symbol in symbols
        },
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "parameters": {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in normalized.items()
        },
        "notice": list(snapshot.notice) + notices,
    }


def simulate(
    snapshot: BasketSnapshot,
    params: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run a complete portfolio backtest with one shared cash balance."""
    validate_basket_snapshot(snapshot)
    normalized = single_engine._normalize_params(params)
    schedule = build_decision_schedule(snapshot, params)
    decision_rows = _validate_decisions(
        decisions, schedule, snapshot.symbols, normalized["maxPositionPct"]
    )
    return _simulate_prefix(
        snapshot,
        normalized,
        decision_rows,
        through_date=snapshot.end_date,
        expected_schedule=schedule,
        complete=True,
    )


def portfolio_at(
    snapshot: BasketSnapshot,
    params: Mapping[str, Any],
    decisions_so_far: Sequence[Mapping[str, Any]],
    as_of_date: str,
) -> dict[str, Any]:
    """Rebuild a decision-close portfolio using only earlier decisions."""
    validate_basket_snapshot(snapshot)
    normalized = single_engine._normalize_params(params)
    schedule = build_decision_schedule(snapshot, params)
    if as_of_date not in schedule:
        raise BacktestInputError("asOfDate不是本次AI决策计划中的日期")
    prefix = tuple(item for item in schedule if item < as_of_date)
    decision_rows = _validate_decisions(
        decisions_so_far, prefix, snapshot.symbols, normalized["maxPositionPct"]
    )
    result = _simulate_prefix(
        snapshot,
        normalized,
        decision_rows,
        through_date=as_of_date,
        expected_schedule=prefix,
        complete=False,
    )
    return result["currentPortfolio"]


__all__ = ["build_decision_schedule", "portfolio_at", "simulate"]
