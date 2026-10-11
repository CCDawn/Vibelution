"""Deterministic, long-only allocation and risk checks for paper proposals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from core.web.services import financial_market_service as market
from core.web.services.financial_paper import ledger

DEFAULT_POLICY = {"maxPositionPct": 30.0, "minCashPct": 10.0, "maxTurnoverPct": 100.0, "maxQuoteAgeHours": 72.0}
QUOTE_TTL_SECONDS = 120


class RebalanceError(ValueError):
    status_code = 422


class RebalanceConflict(RebalanceError):
    status_code = 409


class RebalanceNotFound(RebalanceError):
    status_code = 404


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def number(value: Any, label: str, low: float = 0, high: float = 100) -> Decimal:
    if isinstance(value, bool):
        raise RebalanceError(f"{label}必须是有效数字")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RebalanceError(f"{label}必须是有效数字") from exc
    if not result.is_finite() or result < Decimal(str(low)) or result > Decimal(str(high)):
        raise RebalanceError(f"{label}须在{low}到{high}之间")
    return result


def normalize_policy(value: dict | None) -> dict[str, float]:
    value = value or {}
    if set(value) - set(DEFAULT_POLICY):
        raise RebalanceError("风控参数包含未知字段")
    return {
        name: float(number(value.get(name, default), name, 1 if name in {"maxPositionPct", "maxQuoteAgeHours"} else 0, 168 if name == "maxQuoteAgeHours" else 200 if name == "maxTurnoverPct" else 100))
        for name, default in DEFAULT_POLICY.items()
    }


def normalize_targets(value: Any, symbols: list[str]) -> list[dict]:
    if not isinstance(value, list) or len(value) != len(symbols) or not 1 <= len(value) <= 20:
        raise RebalanceError("目标仓位必须完整列出候选股票和当前持仓，最多20只")
    rows = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"symbol", "weightPct", "reason"}:
            raise RebalanceError("目标仓位格式无效")
        symbol = market.normalize_a_share_symbol(str(item.get("symbol") or ""))
        reason = str(item.get("reason") or "").strip()
        if not reason or len(reason) > 500:
            raise RebalanceError("每个目标仓位需要1–500字的理由")
        rows.append({"symbol": symbol, "weightPct": float(number(item.get("weightPct"), "目标仓位")), "reason": reason})
    if len({row["symbol"] for row in rows}) != len(rows) or {row["symbol"] for row in rows} != set(symbols):
        raise RebalanceError("目标股票与本次候选及持仓不一致")
    return sorted(rows, key=lambda row: row["symbol"])


def _age(value: str, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return None
        return (now - parsed.astimezone(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        return None


def _percentage_text(amount: Decimal, total: Decimal) -> str:
    if total <= 0:
        return "0.00"
    percentage = (amount * Decimal(100) / total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return format(percentage, ".2f")


def build_plan(context: dict, targets: list[dict], quotes: dict[str, dict], policy: dict, *, now: datetime) -> dict:
    """Return the exact batch and independent risk results; never mutate an account."""
    checks: list[dict] = []

    def check(code: str, label: str, passed: bool, detail: str) -> None:
        checks.append({"code": code, "label": label, "passed": bool(passed), "detail": detail})

    positions = {row["symbol"]: row for row in context["positions"]}
    symbols = sorted(set(positions) | {row["symbol"] for row in targets})
    trade_day = ledger._beijing_date(now)
    try:
        market_open = ledger.trading_calendar.is_a_share_trading_day(trade_day)
    except ledger.trading_calendar.TradingCalendarUnavailable:
        market_open = False
    check(
        "execution_date",
        "模拟交易日",
        market_open,
        f"{trade_day.isoformat()} 可模拟成交" if market_open else f"{trade_day.isoformat()} 不是已核验的 A 股交易日，不能生成可执行方案",
    )
    available = all(symbol in quotes for symbol in symbols)
    check("quote_coverage", "行情覆盖", available, "所有候选与持仓均有报价" if available else "存在缺失行情，不能计算调仓")
    fresh = available
    execution_quotes_match = available
    for symbol in symbols:
        quote = quotes.get(symbol, {})
        age = _age(str(quote.get("timestamp") or ""), now)
        fetched_age = _age(str(quote.get("fetchedAt") or ""), now)
        valid = age is not None and -30 <= age <= policy["maxQuoteAgeHours"] * 3600 and fetched_age is not None and -30 <= fetched_age <= QUOTE_TTL_SECONDS
        fresh = fresh and valid
        try:
            quoted_at = ledger._parse_datetime(str(quote.get("timestamp") or ""))
            quote_day = ledger._beijing_date(quoted_at)
            matches_trade = quote_day == trade_day and quoted_at.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
        except (TypeError, ValueError):
            matches_trade = False
        execution_quotes_match = execution_quotes_match and matches_trade
    check("quote_freshness", "行情时效", fresh, f"报价不超过{policy['maxQuoteAgeHours']:g}小时，获取时间不超过{QUOTE_TTL_SECONDS}秒")
    check(
        "execution_quotes",
        "报价与模拟交易日",
        execution_quotes_match,
        "报价日期与模拟交易日一致且不晚于当前时间" if execution_quotes_match else "报价不是当前 A 股交易日行情，不能用于模拟成交",
    )
    total_weight = sum((Decimal(str(row["weightPct"])) for row in targets), Decimal(0))
    check("target_cash", "目标现金保留", total_weight <= 100 - Decimal(str(policy["minCashPct"])), f"目标总仓位{total_weight:g}%，现金至少{policy['minCashPct']:g}%")
    check("target_concentration", "目标单股上限", all(row["weightPct"] <= policy["maxPositionPct"] for row in targets), f"单股目标不超过{policy['maxPositionPct']:g}%")
    empty_metrics = {"equityYuan": "0.00", "cashAfterYuan": str(context["cashYuan"]), "turnoverPct": "0.00", "feesYuan": "0.00"}
    if not available or not market_open or not execution_quotes_match:
        return {"riskChecks": checks, "orders": [], "metrics": empty_metrics, "accountValuation": None, "canApprove": False}
    prices = {symbol: ledger._money(quotes[symbol]["priceYuan"]) for symbol in symbols}
    if any(price <= 0 for price in prices.values()):
        raise RebalanceError("报价必须大于零")
    cash = ledger._money(context["cashYuan"])
    position_values = {
        symbol: ledger._money(prices[symbol] * row["quantity"])
        for symbol, row in positions.items()
    }
    market_value = sum(position_values.values(), Decimal(0))
    equity = cash + market_value
    if equity <= 0:
        raise RebalanceError("模拟账户净值必须大于零")
    account_valuation = {
        "cashYuan": ledger._money_text(cash),
        "marketValueYuan": ledger._money_text(market_value),
        "equityYuan": ledger._money_text(equity),
        "cashWeightPct": _percentage_text(cash, equity),
        "positions": [
            {
                "symbol": symbol,
                "quantity": int(positions[symbol]["quantity"]),
                "sellableQuantity": int(positions[symbol].get("sellableQuantity") or 0),
                "priceYuan": ledger._money_text(prices[symbol]),
                "marketValueYuan": ledger._money_text(position_values[symbol]),
                "weightPct": _percentage_text(position_values[symbol], equity),
            }
            for symbol in sorted(position_values)
        ],
    }
    orders = []
    final_quantities = {symbol: row["quantity"] for symbol, row in positions.items()}
    fee_supported = True
    for symbol in symbols:
        quantity_rule = ledger._project_order_quantity_rule(symbol, trade_day)
        fee_supported = fee_supported and quantity_rule["supportedForSimulation"]
    check(
        "fee_support",
        "模拟费用覆盖",
        fee_supported,
        "所有股票均支持已核验的沪深 A 股费用" if fee_supported else "包含尚无已核验费用规则的股票，不能生成可执行方案",
    )
    if not fee_supported:
        return {"riskChecks": checks, "orders": [], "metrics": empty_metrics, "accountValuation": account_valuation, "canApprove": False}
    all_orders_legal = True
    all_planned_sales_sellable = True
    for target in targets:
        symbol = target["symbol"]
        quantity_rule = ledger._quantity_rule(symbol, trade_day)
        maximum_order_quantity = ledger._quantity_limit(quantity_rule)
        current = int(positions.get(symbol, {}).get("quantity", 0))
        sellable = int(positions.get(symbol, {}).get("sellableQuantity", 0))
        # Reserve a small fee allowance before lot rounding. All actual fees and
        # resulting constraints are checked below; this is not a risk override.
        target_quantity = int((equity * Decimal("0.999") * Decimal(str(target["weightPct"])) / 100 / prices[symbol]).to_integral_value(rounding=ROUND_FLOOR))
        if target_quantity > current:
            requested_buy = target_quantity - current
            buy_ceiling = min(requested_buy, maximum_order_quantity)
            buy_quantity = ledger.quantity_rules.floor_buy_quantity(
                buy_ceiling, quantity_rule
            )
            if requested_buy > maximum_order_quantity:
                all_orders_legal = False
            desired = current + buy_quantity
        else:
            target_quantity = ledger.quantity_rules.sell_target_shares(
                current, target_quantity, quantity_rule
            )
            planned_sale = current - target_quantity
            if planned_sale > sellable:
                all_planned_sales_sellable = False
            if planned_sale > maximum_order_quantity:
                all_orders_legal = False
            legal_sale = ledger.quantity_rules.floor_sell_quantity(
                planned_sale,
                current,
                min(sellable, maximum_order_quantity, planned_sale),
                quantity_rule,
            )
            # A smaller fill can be explained by T+1 only when the requested
            # sale exceeds today's sellable quantity. Otherwise the target
            # cannot be reached with a legal board lot and must fail closed.
            if legal_sale != planned_sale and planned_sale <= sellable:
                all_orders_legal = False
            desired = current - legal_sale
        final_quantities[symbol] = desired
        delta = desired - current
        if delta == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        quantity = abs(delta)
        gross = ledger._money(prices[symbol] * quantity)
        fee_breakdown = ledger._calculate_fee(gross, trade_day, side, symbol)
        fee = fee_breakdown["fee"]
        cash += -gross - fee if side == "buy" else gross - fee
        orders.append({"symbol": symbol, "name": quotes[symbol]["name"], "side": side, "quantity": quantity, "priceYuan": ledger._money_text(prices[symbol]), "grossAmountYuan": ledger._money_text(gross), "feeYuan": ledger._money_text(fee), "reason": target["reason"]})
    orders.sort(key=lambda row: (row["side"] != "sell", row["symbol"]))
    fees = sum((Decimal(row["feeYuan"]) for row in orders), Decimal(0))
    turnover = sum((Decimal(row["grossAmountYuan"]) for row in orders), Decimal(0)) / equity * 100
    post_equity = equity - fees
    check("order_size", "板块股数规则", all_orders_legal and all(
        row["quantity"] <= ledger._quantity_limit(ledger._quantity_rule(row["symbol"], trade_day))
        and (
            ledger.quantity_rules.floor_buy_quantity(row["quantity"], ledger._quantity_rule(row["symbol"], trade_day)) == row["quantity"]
            if row["side"] == "buy"
            else ledger.quantity_rules.floor_sell_quantity(
                row["quantity"],
                positions.get(row["symbol"], {}).get("quantity", 0),
                positions.get(row["symbol"], {}).get("sellableQuantity", 0),
                ledger._quantity_rule(row["symbol"], trade_day),
            ) == row["quantity"]
        )
        for row in orders
    ), "订单符合股票所属板块的起始股数、递增单位、单笔上限与余股卖出规则")
    sellable = all_planned_sales_sellable and all(row["side"] != "sell" or row["quantity"] <= positions.get(row["symbol"], {}).get("sellableQuantity", 0) for row in orders)
    check("sellable", "可卖与T+1", sellable, "卖出不得超过已满足模拟T+1的持仓")
    check("cash", "含费用现金", cash >= 0 and post_equity > 0 and cash >= post_equity * Decimal(str(policy["minCashPct"])) / 100, f"预计现金{cash:.2f}元，现金下限{policy['minCashPct']:g}%")
    concentration = post_equity > 0 and all(prices[symbol] * quantity <= post_equity * Decimal(str(policy["maxPositionPct"])) / 100 for symbol, quantity in final_quantities.items())
    check("concentration", "成交后集中度", concentration, f"含费用后的单股权重不超过{policy['maxPositionPct']:g}%")
    check("turnover", "调仓换手", turnover <= Decimal(str(policy["maxTurnoverPct"])), f"预计{turnover:.2f}%，上限{policy['maxTurnoverPct']:g}%（买卖金额之和/净值）")
    check("position_count", "持仓数量", sum(quantity > 0 for quantity in final_quantities.values()) <= 20, "最多20只持仓")
    empty_orders_reason = (
        "调仓差额不符合该板块股数规则，未生成可执行订单"
        if not all_orders_legal
        else "计划卖出超过当前可卖数量，可能受 T+1 冻结限制"
        if not all_planned_sales_sellable
        else "当前目标仓位无需调仓，或买入差额未达到一手"
    )
    check("orders", "可执行订单", bool(orders), "有待执行的模拟订单" if orders else empty_orders_reason)
    return {
        "riskChecks": checks,
        "orders": orders,
        "metrics": {
            "equityYuan": ledger._money_text(equity),
            "cashAfterYuan": ledger._money_text(cash),
            "turnoverPct": f"{turnover:.2f}",
            "feesYuan": ledger._money_text(fees),
        },
        "accountValuation": account_valuation,
        "canApprove": all(item["passed"] for item in checks),
    }
