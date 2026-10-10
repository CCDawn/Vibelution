from datetime import date
from decimal import Decimal

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestFeeAudit
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_backtest.fees import (
    LEGACY_FEE_MODEL,
    VERIFIED_FEE_MODEL,
    calculate_fees,
    fee_model_audit,
    normalize_fee_model,
    stamp_duty_rate,
    validate_fee_window,
)


def test_fee_model_defaults_to_legacy_without_changing_frozen_identity():
    assert normalize_fee_model({}) == LEGACY_FEE_MODEL
    assert normalize_fee_model({"feeModel": LEGACY_FEE_MODEL}) == LEGACY_FEE_MODEL
    assert fee_model_audit({}, ["sh600000"], "2024-01-01", "2024-12-31") is None


def test_fee_model_selection_rejects_unknown_and_conflicting_aliases():
    with pytest.raises(BacktestInputError):
        normalize_fee_model({"feeModel": "unknown"})
    with pytest.raises(BacktestInputError):
        normalize_fee_model(
            {"feeModel": VERIFIED_FEE_MODEL, "fee_model": LEGACY_FEE_MODEL}
        )


@pytest.mark.parametrize(
    ("day", "side", "expected"),
    [
        ("2005-01-24", "buy", Decimal("0.001")),
        ("2007-05-29", "sell", Decimal("0.001")),
        ("2007-05-30", "buy", Decimal("0.003")),
        ("2008-04-23", "sell", Decimal("0.003")),
        ("2008-04-24", "buy", Decimal("0.001")),
        ("2008-09-18", "buy", Decimal("0.001")),
        ("2008-09-19", "buy", Decimal(0)),
        ("2008-09-19", "sell", Decimal("0.001")),
        ("2023-08-27", "sell", Decimal("0.001")),
        ("2023-08-28", "sell", Decimal("0.0005")),
        ("2023-08-28", "buy", Decimal(0)),
    ],
)
def test_stamp_duty_rate_preserves_historical_engine_schedule(day, side, expected):
    assert stamp_duty_rate(day, side) == expected


@pytest.mark.parametrize("day", ["2024-2-01", "2024-02-30", "2024-W05-1", ""])
def test_stamp_duty_rate_requires_canonical_calendar_date(day):
    with pytest.raises(BacktestInputError):
        stamp_duty_rate(day, "sell")


def test_legacy_fee_calculation_preserves_zero_rate_and_historical_stamp_semantics():
    no_commission = calculate_fees(
        Decimal(1000),
        "2023-08-27",
        "sell",
        "sh600000",
        Decimal(0),
        Decimal(5),
        LEGACY_FEE_MODEL,
    )
    assert no_commission == {
        "commission": Decimal("0.00"),
        "stampDuty": Decimal("1.00"),
        "transferFee": Decimal("0.00"),
        "fee": Decimal("1.00"),
    }

    regular = calculate_fees(
        Decimal(1000),
        "2023-08-28",
        "sell",
        "sh600000",
        Decimal("0.0003"),
        Decimal(5),
        LEGACY_FEE_MODEL,
    )
    assert regular["commission"] == Decimal("5.00")
    assert regular["stampDuty"] == Decimal("0.50")
    assert regular["fee"] == Decimal("5.50")
    assert set(regular) == {"commission", "stampDuty", "transferFee", "fee"}


def test_verified_fee_decomposes_embedded_charges_without_double_counting():
    result = calculate_fees(
        Decimal(100000),
        "2024-01-02",
        "sell",
        "sh600000",
        Decimal("0.0003"),
        Decimal(5),
        VERIFIED_FEE_MODEL,
    )

    assert result == {
        "commission": Decimal("30.00"),
        "stampDuty": Decimal("50.00"),
        "transferFee": Decimal("1.00"),
        "handlingFee": Decimal("3.41"),
        "regulatoryFee": Decimal("2.00"),
        "brokerCommission": Decimal("24.59"),
        "fee": Decimal("81.00"),
    }
    assert result["fee"] == result["commission"] + result["transferFee"] + result["stampDuty"]


def test_verified_fee_uses_historical_transfer_and_stamp_rates():
    result = calculate_fees(
        Decimal(100000),
        "2021-01-04",
        "buy",
        "sz000001",
        Decimal("0.0003"),
        Decimal(5),
        VERIFIED_FEE_MODEL,
    )

    assert result["commission"] == Decimal("30.00")
    assert result["handlingFee"] == Decimal("4.87")
    assert result["regulatoryFee"] == Decimal("2.00")
    assert result["brokerCommission"] == Decimal("23.13")
    assert result["stampDuty"] == Decimal("0.00")
    assert result["transferFee"] == Decimal("2.00")
    assert result["fee"] == Decimal("32.00")


def test_verified_fee_blocks_when_separate_rounding_exceeds_user_commission():
    # At the exact 2015-2023 fee floor, 73,250 yuan produces a gross
    # commission of 5.03 while the separately rounded included components sum
    # to 5.04. The simulator must not silently increase the configured charge.
    with pytest.raises(BacktestInputError, match="舍入"):
        calculate_fees(
            Decimal(73250),
            "2022-01-04",
            "buy",
            "sz000001",
            Decimal("0.0000687"),
            Decimal(5),
            VERIFIED_FEE_MODEL,
        )


@pytest.mark.parametrize(
    "params",
    [
        {"feeModel": VERIFIED_FEE_MODEL, "commissionBps": 0.6, "minimumCommission": 5},
        {"feeModel": VERIFIED_FEE_MODEL, "commissionBps": 3, "minimumCommission": 4.99},
        {"feeModel": VERIFIED_FEE_MODEL, "commissionBps": 30.01, "minimumCommission": 5},
    ],
)
def test_verified_window_rejects_terms_outside_official_commission_bounds(params):
    with pytest.raises(BacktestInputError):
        validate_fee_window("sh600000", "2015-08-01", "2024-01-01", params)


def test_verified_commission_floor_tracks_fee_schedule_window():
    before_current_rate = {
        "feeModel": VERIFIED_FEE_MODEL,
        "commissionBps": Decimal("0.69"),
        "minimumCommission": Decimal(5),
    }
    after_current_rate = {
        "feeModel": VERIFIED_FEE_MODEL,
        "commissionBps": Decimal("0.55"),
        "minimumCommission": Decimal(5),
    }
    validate_fee_window("sz000001", "2015-08-01", "2023-08-27", before_current_rate)
    validate_fee_window("sz000001", "2023-08-28", "2024-01-01", after_current_rate)
    with pytest.raises(BacktestInputError):
        validate_fee_window("sz000001", "2015-08-01", "2024-01-01", after_current_rate)


@pytest.mark.parametrize(
    ("symbol", "start", "end"),
    [
        ("hk00001", "2015-08-01", "2020-01-01"),
        ("bj830001", "2015-08-01", "2020-01-01"),
        ("sh600000", "2015-07-31", "2020-01-01"),
        ("sh600000", "2015-08-01", "2015-07-31"),
        ("sh600000", "2015-08-01T00:00:00", "2020-01-01"),
        ("sh600000", date(2015, 8, 1), "2020-01-01"),
    ],
)
def test_verified_fee_window_rejects_unsupported_symbol_or_date(symbol, start, end):
    params = {"feeModel": VERIFIED_FEE_MODEL, "commissionBps": 3, "minimumCommission": 5}
    with pytest.raises(BacktestInputError):
        validate_fee_window(symbol, start, end, params)


def test_verified_audit_reports_clipped_rate_segments_and_source_limitations():
    params = {
        "feeModel": VERIFIED_FEE_MODEL,
        "commissionBps": Decimal(3),
        "minimumCommission": Decimal(5),
    }
    audit = fee_model_audit(
        params,
        ["sz000001", "sh600000"],
        "2022-04-28",
        "2023-08-28",
    )

    assert audit["feeModel"] == VERIFIED_FEE_MODEL
    assert audit["startDate"] == "2022-04-28"
    assert audit["endDate"] == "2023-08-28"
    assert audit["symbols"] == ["sh600000", "sz000001"]
    assert audit["commissionIncludes"] == ["证券交易经手费", "证券交易监管费"]
    assert audit["roundingStatus"] == "unverified_broker_settlement"
    assert audit["minimumGranularity"] == "simulated_order"
    assert all(url.startswith("https://") for url in audit["sourceURLs"])
    assert any("2015-08-01" <= row["startDate"] <= row["endDate"] for row in audit["rates"])
    transfer_segments = [row for row in audit["rates"] if row["component"] == "transferFee"]
    assert transfer_segments == [
        {
            "component": "transferFee",
            "startDate": "2022-04-28",
            "endDate": "2022-04-28",
            "rate": "0.00002",
            "side": "both",
        },
        {
            "component": "transferFee",
            "startDate": "2022-04-29",
            "endDate": "2023-08-28",
            "rate": "0.00001",
            "side": "both",
        },
    ]


def test_fee_audit_http_dto_roundtrip_preserves_canonical_hash():
    params = {
        "feeModel": VERIFIED_FEE_MODEL,
        "commissionBps": Decimal(3),
        "minimumCommission": Decimal(5),
    }
    audit = fee_model_audit(params, ["sh600000"], "2024-01-02", "2024-01-31")
    assert audit is not None

    serialized = FinancialBacktestFeeAudit.model_validate(audit).model_dump(mode="json")

    assert serialized == audit
    assert sha256_json(serialized) == sha256_json(audit)
    assert all(
        value is not None
        for rate in serialized["rates"]
        for key, value in rate.items()
        if key not in {"component", "startDate", "endDate", "side"}
    )
