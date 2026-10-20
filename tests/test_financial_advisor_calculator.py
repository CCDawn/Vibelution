"""Money, quote and quantity boundaries for the read-only advisor calculation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import localcontext
import json

import pytest

from core.web.services.financial_preferences.advisor_calculator import calculate


NOW = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
SYMBOL = "sh600000"


def state(**profile):
    return {
        "investmentProfile": {
            "budgetCny": 6000,
            "availableCashCny": 6000,
            "cashReserveCny": 0,
            "maxPositionPct": 100,
            "maxLossCny": 600,
            "holdingsStatus": "none",
            "market": "CN",
            **profile,
        },
        "manualPositions": [],
    }


def quotes(price=10, **extra):
    return {SYMBOL: {"price": price, "asOf": NOW.isoformat(), "source": "test-market", **extra}}


def order(quantity=100, side="buy", symbol=SYMBOL):
    return {"symbol": symbol, "side": side, "quantity": quantity}


def held(quantity=150, **profile):
    value = state(holdingsStatus="recorded", **profile)
    value["manualPositions"] = [{"stock": {"symbol": SYMBOL}, "quantity": quantity, "costPrice": 0.01, "currency": "CNY"}]
    return value


def test_6000_budget_cannot_silently_buy_6000_notional_plus_fees():
    result = calculate(state(), [order(600)], quotes(), now=NOW)
    assert result["passed"] is False
    assert result["feesCny"] == 5.06
    assert result["cashAfterCny"] == -5.06
    assert result["orders"][0]["quantity"] == 600
    assert any("预算" in reason for reason in result["blockers"])
    assert any("现金" in reason for reason in result["blockers"])


def test_fee_aware_buy_is_pure_and_has_quote_provenance():
    value, requested, prices = state(), [order(500)], quotes()
    before = deepcopy((value, requested, prices))
    result = calculate(value, requested, prices, now=NOW)
    assert result["passed"] is True
    assert result["cashAfterCny"] == 994.95
    assert result["feesCny"] == 5.05
    assert result["orders"][0]["quoteAsOf"] == NOW.isoformat()
    assert result["orders"][0]["quoteSource"] == "test-market"
    assert any("0.0003" in warning and "5元" in warning for warning in result["warnings"])
    assert any("不保证" in warning for warning in result["warnings"])
    assert (value, requested, prices) == before
    assert calculate(value, requested, prices, now=NOW) == result
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field", ["budgetCny", "availableCashCny", "cashReserveCny", "maxPositionPct"])
@pytest.mark.parametrize("bad", [None, True, float("nan"), float("inf"), "6000", -1])
def test_unknown_or_invalid_money_and_risk_fields_fail_closed(field, bad):
    result = calculate(state(**{field: bad}), [order()], quotes(), now=NOW)
    assert result["passed"] is False
    assert result["cashAfterCny"] is None
    assert any(field in reason for reason in result["blockers"])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("status", ["unknown", "recorded"])
def test_holdings_unknown_or_recorded_but_empty_cannot_be_treated_as_empty(status):
    assert not calculate(state(holdingsStatus=status), [order()], quotes(), now=NOW)["passed"]


def test_explicit_empty_holdings_must_match_positions():
    value = held()
    value["investmentProfile"]["holdingsStatus"] = "none"
    assert not calculate(value, [order()], quotes(), now=NOW)["passed"]


@pytest.mark.parametrize("quantity", [0, -100, 1.5, 100.0, True, "100", float("inf"), 99, 1000001])
def test_order_quantities_are_never_coerced_or_rounded(quantity):
    result = calculate(state(), [order(quantity)], quotes(), now=NOW)
    assert not result["passed"]
    assert result["orders"] == []
    assert result["cashAfterCny"] is None


@pytest.mark.parametrize("symbol", ["600000", "SH600000", "bj920001", "sh000001", "sz200001", "usAAPL", "hk00700"])
def test_only_canonical_verified_shanghai_shenzhen_a_shares_are_supported(symbol):
    assert not calculate(state(), [order(symbol=symbol)], quotes(), now=NOW)["passed"]


def test_duplicates_do_not_double_spend_or_net_opposite_orders():
    assert not calculate(state(), [order(), order(side="sell")], quotes(), now=NOW)["passed"]
    value = held()
    value["manualPositions"].append(deepcopy(value["manualPositions"][0]))
    assert not calculate(value, [order()], quotes(), now=NOW)["passed"]


@pytest.mark.parametrize("quote", [{}, {"price": 10}, {"price": 0, "asOf": NOW.isoformat()}, {"price": float("nan"), "asOf": NOW.isoformat()}, {"price": float("inf"), "asOf": NOW.isoformat()}, {"price": 10, "asOf": NOW.replace(tzinfo=None).isoformat()}, {"price": 10, "asOf": (NOW + timedelta(microseconds=1)).isoformat()}, {"price": 10, "asOf": (NOW - timedelta(minutes=15, microseconds=1)).isoformat()}])
def test_missing_invalid_stale_or_future_quotes_block(quote):
    result = calculate(state(), [order()], {SYMBOL: quote}, now=NOW)
    assert not result["passed"]
    assert result["cashAfterCny"] is None


def test_exact_freshness_boundary_and_z_timestamp_are_accepted():
    result = calculate(state(), [order()], quotes(asOf=(NOW - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")), now=NOW)
    assert result["passed"]


def test_existing_holdings_must_have_fresh_market_price_never_cost_fallback():
    value = held()
    assert not calculate(value, [order(symbol="sz000001")], {"sz000001": {"price": 10, "asOf": NOW.isoformat()}}, now=NOW)["passed"]
    result = calculate(held(100, maxPositionPct=20), [order()], quotes(10), now=NOW)
    assert not result["passed"]
    assert result["orders"][0]["positionAfterPct"] == pytest.approx(2000 / 7000 * 100, abs=.01)
    assert any("单股" in reason for reason in result["blockers"])


def test_cash_reserve_and_budget_are_independent_of_total_wealth():
    result = calculate(state(cashReserveCny=1000), [order(500)], quotes(), now=NOW)
    assert not result["passed"]
    assert any("预留" in reason for reason in result["blockers"])
    result = calculate(state(availableCashCny=20000, budgetCny=1000), [order(100)], quotes(), now=NOW)
    assert not result["passed"]
    assert any("预算" in reason for reason in result["blockers"])


def test_existing_appreciation_does_not_redefine_new_purchase_budget():
    result = calculate(held(1000, budgetCny=2000), [order()], quotes(), now=NOW)
    assert result["passed"]


@pytest.mark.parametrize(("quantity", "valid_lot"), [(50, False), (100, True), (150, True), (200, False)])
def test_sales_obey_holdings_odd_lot_rules_and_always_block_unverified_sellability(quantity, valid_lot):
    result = calculate(held(), [order(quantity, "sell")], quotes(), now=NOW)
    assert not result["passed"]
    if valid_lot:
        assert result["orders"][0]["quantity"] == quantity
        assert any("T+1" in reason for reason in result["blockers"])
        assert result["feesCny"] == (5.51 if quantity == 100 else 5.77)
    else:
        assert result["orders"] == []


def test_sell_proceeds_never_finance_buys():
    value = held(500, availableCashCny=100)
    prices = {**quotes(), "sz000001": {"price": 10, "asOf": NOW.isoformat()}}
    result = calculate(value, [order(500, "sell"), order(100, symbol="sz000001")], prices, now=NOW)
    assert result["cashAfterCny"] > 0
    assert any("买入" in reason and "现金" in reason for reason in result["blockers"])


def test_star_market_uses_200_minimum_and_single_share_increment():
    for quantity, passed in [(100, False), (200, True), (201, True)]:
        result = calculate(state(), [order(quantity, symbol="sh688001")], {"sh688001": {"price": 10, "asOf": NOW.isoformat()}}, now=NOW)
        assert result["passed"] is passed


def test_invalid_time_and_fee_window_surface_blockers_instead_of_exceptions():
    assert not calculate(state(), [order()], quotes(), now=NOW.replace(tzinfo=None))["passed"]
    old = NOW.replace(year=2014)
    result = calculate(state(), [order()], quotes(asOf=old.isoformat()), now=old)
    assert not result["passed"]
    assert any("费用" in reason for reason in result["blockers"])


def test_unknown_loss_tolerance_warns_without_inventing_stop_price():
    result = calculate(state(maxLossCny=None), [order()], quotes(), now=NOW)
    assert result["passed"]
    assert any("未知" in warning and "亏损" in warning for warning in result["warnings"])
    assert "stopPrice" not in json.dumps(result)


def test_caller_decimal_context_does_not_change_trial_result():
    expected = calculate(state(), [order(500)], quotes(), now=NOW)
    with localcontext() as context:
        context.prec = 4
        assert calculate(state(), [order(500)], quotes(), now=NOW) == expected


@pytest.mark.parametrize("field", ["budgetCny", "availableCashCny", "cashReserveCny"])
def test_sub_cent_funding_is_rejected_instead_of_rounded_up(field):
    assert not calculate(state(**{field: 6000.001}), [order()], quotes(), now=NOW)["passed"]


@pytest.mark.parametrize("bad", [[], {}, float("nan")])
def test_malformed_holdings_status_is_a_blocker(bad):
    result = calculate(state(holdingsStatus=bad), [order()], quotes(), now=NOW)
    assert not result["passed"]
    assert result["cashAfterCny"] is None


def test_nonfinite_manual_asset_data_does_not_enter_a_trial_result():
    value = held()
    value["manualPositions"][0]["costPrice"] = float("inf")
    result = calculate(value, [order()], quotes(), now=NOW)
    assert not result["passed"]
    json.dumps(result, allow_nan=False)


def test_hold_plan_keeps_cash_and_still_validates_portfolio_authorities():
    result = calculate(state(), [], {}, now=NOW)
    assert result["passed"]
    assert result["orders"] == []
    assert result["feesCny"] == 0
    assert result["cashAfterCny"] == 6000
    assert calculate(state(availableCashCny=0), [], {}, now=NOW)["passed"]
    assert not calculate(state(holdingsStatus="unknown"), [], {}, now=NOW)["passed"]
    assert not calculate(held(), [], {}, now=NOW)["passed"]
    assert not calculate(held(100.0, maxPositionPct=10), [], quotes(), now=NOW)["passed"]
    assert calculate(held(100.0), [], quotes(), now=NOW)["passed"]
