"""Pure, fail-closed A-share order estimates; never submit or resize an order.

``passed`` means the supplied money/quantity constraints pass this estimate. It
does not verify brokerage assets, market admission, execution or loss limits.
Quotes are canonical-symbol mappings to ``{price, asOf, source?}``; ``asOf`` is
the quote's timezone-aware source timestamp, never the HTTP fetch timestamp.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from core.web.services.financial_backtest.fees import VERIFIED_FEE_MODEL, calculate_fees
from core.web.services.financial_backtest.quantity_rules import (
    ASHARE_QUANTITY_V2,
    floor_buy_quantity,
    floor_sell_quantity,
    resolve_quantity_rule,
)

MAX_QUOTE_AGE = timedelta(minutes=15)
_CN = timezone(timedelta(hours=8))
_CENT = Decimal("0.01")
_ZERO = Decimal(0)
_SYMBOL = re.compile(r"(?:sh(?:600|601|603|605|688|689)|sz(?:000|001|002|003|300|301))\d{3}\Z")


def _number(value: Any, label: str, *, positive: bool = False, maximum: int = 100_000_000) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label}未知或不是有效数字")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label}不是有效数字") from exc
    if not result.is_finite() or result < 0 or result > maximum or (positive and result == 0):
        raise ValueError(f"{label}不是有效范围内的数字")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise ValueError("仅支持规范代码的沪深A股，不含指数、B股、北交所及境外市场")
    return value


def _quote(value: Any, symbol: str, now: datetime) -> tuple[Decimal, str, str | None]:
    if not isinstance(value, dict):
        raise ValueError(f"{symbol}缺少行情，不能用成本价代替市价")
    price = _number(value.get("price"), f"{symbol}行情价格", positive=True)
    try:
        raw_time = value.get("asOf")
        if not isinstance(raw_time, str):
            raise ValueError
        as_of = datetime.fromisoformat(raw_time)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError
        age = now - as_of
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{symbol}行情缺少有效的带时区来源时间") from exc
    if age < timedelta(0):
        raise ValueError(f"{symbol}行情时间晚于当前时间")
    if age > MAX_QUOTE_AGE:
        raise ValueError(f"{symbol}行情超过15分钟，不能用于本次试算")
    source = value.get("source")
    return price, as_of.isoformat(), source if isinstance(source, str) else None


def calculate(state: dict, orders: list[dict], quotes: dict, *, now: datetime) -> dict:
    """Calculate independently of the caller's ambient Decimal precision."""
    with localcontext(Context(prec=48, rounding=ROUND_HALF_UP)):
        return _calculate(state, orders, quotes, now=now)


def _calculate(state: dict, orders: list[dict], quotes: dict, *, now: datetime) -> dict:
    """Estimate exactly the requested plan with Decimal amounts and no I/O.

    Invalid or incomplete inputs return no partial-plan cash result. Policy
    failures retain the complete hypothetical result so overspending is visible.
    Budget limits gross buys including fees; existing appreciation is not new
    spending. Concentration uses current marked equity before this plan's fees.
    Sales always block because manual positions do not establish T+1 sellability;
    hypothetical proceeds are never allowed to fund this plan's purchases.
    """
    blockers: list[str] = []
    warnings = [
        "佣金按0.0003、每笔最低5元估算，另计适用税费；不是券商实际费率或清算结果。",
        "仅核对输入下的金额与数量约束；手动资产未与券商核实，行情、成交价、停牌、交易权限及滑点仍需核验。",
        "maxLossCny是可承受亏损范围，不是止损价，不保证实际亏损不超过该金额。",
    ]
    result = {"passed": False, "blockers": blockers, "warnings": warnings, "cashAfterCny": None, "feesCny": 0.0, "orders": []}
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        blockers.append("当前时间必须是带时区的datetime")
        return result
    if not isinstance(state, dict) or not isinstance(state.get("investmentProfile"), dict):
        blockers.append("投资配置未知，不能试算金额")
        return result
    profile = state["investmentProfile"]
    amounts: dict[str, Decimal] = {}
    for key in ("budgetCny", "availableCashCny", "cashReserveCny", "maxPositionPct"):
        try:
            amounts[key] = _number(profile.get(key), key, positive=key in {"budgetCny", "maxPositionPct"}, maximum=100 if key == "maxPositionPct" else 100_000_000)
            if key != "maxPositionPct" and _money(amounts[key]) != amounts[key]:
                blockers.append(f"{key}金额最多保留两位小数，不能向上舍入可用资金")
        except ValueError as exc:
            blockers.append(str(exc))
    if profile.get("market") != "CN":
        blockers.append("投资市场未知或不受支持，仅支持CN沪深A股")
    if profile.get("maxLossCny") is None:
        warnings.append("最大可承受亏损未知，未据此判断风险适合度。")
    else:
        try:
            loss = _number(profile["maxLossCny"], "maxLossCny")
            if "budgetCny" in amounts and loss > amounts["budgetCny"]:
                blockers.append("maxLossCny不能超过预算")
        except ValueError as exc:
            blockers.append(str(exc))
    if "budgetCny" in amounts and "cashReserveCny" in amounts and amounts["cashReserveCny"] > amounts["budgetCny"]:
        blockers.append("cashReserveCny不能超过预算")

    positions = state.get("manualPositions")
    status = profile.get("holdingsStatus")
    if status not in ("none", "recorded"):
        blockers.append("持仓状态未知，不能按空仓计算")
    if not isinstance(positions, list) or len(positions) > 50:
        blockers.append("手动持仓列表未知或超过50条")
        positions = []
    if status == "none" and positions:
        blockers.append("空仓声明与已录入持仓不一致")
    if status == "recorded" and not positions:
        blockers.append("已录入持仓为空，实际持仓仍未知")
    held: dict[str, int] = {}
    for row in positions:
        try:
            if not isinstance(row, dict) or not isinstance(row.get("stock"), dict):
                raise ValueError("手动持仓格式无效")
            symbol = _symbol(row["stock"].get("symbol"))
            if symbol in held:
                raise ValueError(f"持仓股票重复：{symbol}")
            quantity = _number(row.get("quantity"), f"{symbol}持仓数量", positive=True, maximum=10**12)
            if quantity != quantity.to_integral_value():
                raise ValueError(f"{symbol}持仓数量必须是整股")
            if row.get("currency") != "CNY":
                raise ValueError(f"{symbol}持仓必须为CNY币种")
            _number(row.get("costPrice"), f"{symbol}持仓成本价", positive=True)
            held[symbol] = int(quantity)
        except ValueError as exc:
            blockers.append(str(exc))

    requested: list[dict] = []
    seen: set[str] = set()
    try:
        trade_day = now.astimezone(_CN).date().isoformat()
    except (ValueError, OverflowError):
        blockers.append("当前时间超出支持的交易日期范围")
        return result
    if not isinstance(orders, list) or len(orders) > 50:
        blockers.append("订单必须为最多50条的列表，可为空表示观望")
        orders = []
    for row in orders:
        try:
            if not isinstance(row, dict):
                raise ValueError("订单格式无效")
            symbol = _symbol(row.get("symbol"))
            if symbol in seen:
                raise ValueError(f"订单股票重复，禁止拆单或买卖轧差：{symbol}")
            seen.add(symbol)
            side, quantity = row.get("side"), row.get("quantity")
            if side not in ("buy", "sell"):
                raise ValueError(f"{symbol}交易方向必须为buy或sell")
            if type(quantity) is not int or quantity <= 0:
                raise ValueError(f"{symbol}订单数量必须是正整数")
            rule = resolve_quantity_rule(symbol, trade_day, ASHARE_QUANTITY_V2)
            if rule.maximum_order_shares is not None and quantity > rule.maximum_order_shares:
                raise ValueError(f"{symbol}订单数量超过单笔上限")
            if side == "buy" and floor_buy_quantity(quantity, rule) != quantity:
                raise ValueError(f"{symbol}买入数量不符合所属板块最小数量与步长")
            if side == "sell":
                owned = held.get(symbol, 0)
                if quantity > owned:
                    raise ValueError(f"{symbol}卖出数量超过已录入持仓")
                if floor_sell_quantity(quantity, owned, quantity, rule) != quantity:
                    raise ValueError(f"{symbol}卖出数量不符合整手或余股一次卖出规则")
            requested.append({"symbol": symbol, "side": side, "quantity": quantity})
        except (ValueError, TypeError) as exc:
            blockers.append(str(exc))

    prices: dict[str, tuple[Decimal, str, str | None]] = {}
    if not isinstance(quotes, dict):
        blockers.append("行情映射无效")
        quotes = {}
    for symbol in sorted(set(held) | {row["symbol"] for row in requested}):
        try:
            prices[symbol] = _quote(quotes.get(symbol), symbol, now)
        except ValueError as exc:
            blockers.append(str(exc))
    if blockers:
        return result

    cash = _money(amounts["availableCashCny"])
    equity = cash + sum((_money(prices[symbol][0] * quantity) for symbol, quantity in held.items()), _ZERO)
    final_quantities = dict(held)
    previews: list[dict] = []
    total_fees, buy_cost, cash_after = _ZERO, _ZERO, cash
    for row in requested:
        symbol, side, quantity = row["symbol"], row["side"], row["quantity"]
        price, as_of, source = prices[symbol]
        notional = _money(price * quantity)
        if notional <= 0:
            blockers.append(f"{symbol}成交金额舍入后不大于零")
            return result
        try:
            fee = calculate_fees(notional, trade_day, side, symbol, Decimal("0.0003"), Decimal(5), VERIFIED_FEE_MODEL)["fee"]
        except (ValueError, TypeError, ArithmeticError) as exc:
            blockers.append(f"{symbol}费用核算失败：{exc}")
            return result
        cash_delta = -notional - fee if side == "buy" else notional - fee
        cash_after += cash_delta
        total_fees += fee
        final_quantities[symbol] = held.get(symbol, 0) + (quantity if side == "buy" else -quantity)
        if side == "buy":
            buy_cost += notional + fee
        else:
            blockers.append(f"{symbol}未核验券商可卖数量（含T+1限制），卖出方案不能通过")
        previews.append({**row, "priceCny": float(price), "quoteAsOf": as_of, "quoteSource": source, "notionalCny": float(notional), "feesCny": float(fee), "cashDeltaCny": float(cash_delta)})

    if buy_cost > amounts["budgetCny"]:
        blockers.append("买入总金额（含费用）超过预算，未自动减少数量")
    if buy_cost > cash:
        blockers.append("买入金额（含费用）超过原有可用现金，不得依赖本方案卖出所得")
    if cash - buy_cost < amounts["cashReserveCny"] or cash_after < amounts["cashReserveCny"]:
        blockers.append("试算后现金低于现金预留要求")
    if equity <= 0 and any(final_quantities.values()):
        blockers.append("当前市值与现金合计不大于零，无法核验仓位")
    elif equity > 0:
        for symbol in sorted(final_quantities):
            value = _money(prices[symbol][0] * final_quantities[symbol])
            if value * 100 > equity * amounts["maxPositionPct"]:
                blockers.append(f"{symbol}试算后单股仓位超过maxPositionPct（分母为当前市值加现金）")
    for preview in previews:
        symbol = preview["symbol"]
        value = _money(prices[symbol][0] * final_quantities[symbol])
        preview.update(positionAfterQuantity=final_quantities[symbol], positionAfterPct=float(_money(value * 100 / equity)) if equity > 0 else 0.0)
    result.update(passed=not blockers, cashAfterCny=float(_money(cash_after)), feesCny=float(_money(total_fees)), orders=previews)
    return result
