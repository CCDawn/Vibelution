"""Versioned A-share order quantity rules for deterministic research fills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

LEGACY_100_V1 = "legacy_100_v1"
ASHARE_QUANTITY_V2 = "ashare_quantity_v2"
SUPPORTED_QUANTITY_RULE_VERSIONS = frozenset(
    {LEGACY_100_V1, ASHARE_QUANTITY_V2}
)

_CHINEXT_ORDER_CAP_EFFECTIVE = date(2020, 8, 24)


@dataclass(frozen=True)
class QuantityRule:
    """One-board buy/sell increments and research order-size ceiling."""

    board: str
    minimum_buy_shares: int
    buy_increment: int
    minimum_sell_shares: int
    sell_increment: int
    residual_sell_threshold: int
    maximum_order_shares: int | None


_LEGACY_RULE = QuantityRule(
    board="legacy_100",
    minimum_buy_shares=100,
    buy_increment=100,
    minimum_sell_shares=100,
    sell_increment=100,
    residual_sell_threshold=100,
    maximum_order_shares=None,
)
_MAIN_BOARD_RULE = QuantityRule(
    board="main_board",
    minimum_buy_shares=100,
    buy_increment=100,
    minimum_sell_shares=100,
    sell_increment=100,
    residual_sell_threshold=100,
    maximum_order_shares=1_000_000,
)
_STAR_MARKET_RULE = QuantityRule(
    board="star_market",
    minimum_buy_shares=200,
    buy_increment=1,
    minimum_sell_shares=200,
    sell_increment=1,
    residual_sell_threshold=200,
    maximum_order_shares=100_000,
)
_BEIJING_RULE = QuantityRule(
    board="beijing",
    minimum_buy_shares=100,
    buy_increment=1,
    minimum_sell_shares=100,
    sell_increment=1,
    residual_sell_threshold=100,
    maximum_order_shares=1_000_000,
)


def resolve_quantity_rule(
    symbol: str,
    execution_date: str,
    version: str = LEGACY_100_V1,
) -> QuantityRule:
    """Resolve board rules for one A-share fill date.

    The current simulator has no order-type field, so this applies the
    exchange's limit-order quantity ceiling as a conservative single-order
    research cap. It does not simulate market orders or order-book matching.
    """
    if not isinstance(version, str) or version not in SUPPORTED_QUANTITY_RULE_VERSIONS:
        raise ValueError("unsupported A-share quantity rule version")
    if version == LEGACY_100_V1:
        return _LEGACY_RULE

    value = str(symbol).lower()
    code = value[2:] if len(value) == 8 else ""
    try:
        trade_date = date.fromisoformat(execution_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid A-share execution date") from exc

    if value.startswith("sh") and code[:2] in {"68", "69"}:
        return _STAR_MARKET_RULE
    if value.startswith("bj"):
        return _BEIJING_RULE
    if value.startswith("sz") and code.startswith("3"):
        cap = (
            1_000_000
            if trade_date < _CHINEXT_ORDER_CAP_EFFECTIVE
            else 300_000
        )
        return QuantityRule(
            board="chinext",
            minimum_buy_shares=100,
            buy_increment=100,
            minimum_sell_shares=100,
            sell_increment=100,
            residual_sell_threshold=100,
            maximum_order_shares=cap,
        )
    return _MAIN_BOARD_RULE


def floor_buy_quantity(shares: int, rule: QuantityRule) -> int:
    """Return the largest legal purchase quantity no greater than ``shares``."""
    if shares < rule.minimum_buy_shares:
        return 0
    increments = (shares - rule.minimum_buy_shares) // rule.buy_increment
    return rule.minimum_buy_shares + increments * rule.buy_increment


def sell_target_shares(
    current_shares: int, desired_shares: int, rule: QuantityRule
) -> int:
    """Avoid targets that would leave a prohibited sub-minimum residual."""
    if (
        0 < desired_shares < rule.residual_sell_threshold
        and desired_shares < current_shares
    ):
        return 0
    return desired_shares


def floor_sell_quantity(
    requested_shares: int,
    held_shares: int,
    maximum_fill_shares: int,
    rule: QuantityRule,
) -> int:
    """Round a partial sale down, while permitting a complete residual sale."""
    upper = min(requested_shares, held_shares, maximum_fill_shares)
    if upper <= 0:
        return 0
    if requested_shares >= held_shares and upper == held_shares:
        return held_shares
    quantity = (upper // rule.sell_increment) * rule.sell_increment
    if quantity < rule.minimum_sell_shares:
        return 0
    return quantity


def maximum_affordable_buy(
    maximum_shares: int,
    rule: QuantityRule,
    is_affordable: Callable[[int], bool],
) -> int:
    """Find the largest legal affordable purchase with logarithmic work."""
    upper = floor_buy_quantity(maximum_shares, rule)
    if upper == 0:
        return 0
    increments = (upper - rule.minimum_buy_shares) // rule.buy_increment + 1
    low = 0
    high = increments
    while low < high:
        middle = (low + high + 1) // 2
        shares = rule.minimum_buy_shares + (middle - 1) * rule.buy_increment
        if is_affordable(shares):
            low = middle
        else:
            high = middle - 1
    if low == 0:
        return 0
    return rule.minimum_buy_shares + (low - 1) * rule.buy_increment


def maximum_order_quantity(rule: QuantityRule) -> int | None:
    return rule.maximum_order_shares
