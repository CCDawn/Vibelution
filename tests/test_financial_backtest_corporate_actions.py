from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from core.web.services.financial_backtest.corporate_actions import (
    CASH_DIVIDEND_RULE_V1,
    DividendLedger,
    _tax_rate,
    freeze_cash_dividend_artifact,
    validate_cash_dividend_artifact,
)
from core.web.services.financial_backtest.data import BacktestInputError


def _page(excerpt: str = "实施方案：每股派发现金红利0.50元。") -> dict:
    return {
        "page": 2,
        "excerpt": excerpt,
        "excerptSha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }


def _event(
    *,
    action_id: str = "action-2024-001",
    symbol: str = "sh600036",
    record_date: str = "2024-04-10",
    ex_date: str = "2024-04-11",
    payment_date: str = "2024-04-20",
    cash_per_share: str = "0.50",
    stock_ratio: str = "0",
    capitalization_ratio: str = "0",
) -> dict:
    return {
        "symbol": symbol,
        "actionId": action_id,
        "noticeId": "1221234567",
        "publishedDate": "2024-03-20",
        "sourceUrl": "https://static.cninfo.com.cn/finalpage/2024-03-20/1221234567.PDF",
        "pdfSha256": "a" * 64,
        "title": "2023年度权益分派实施公告",
        "recordDate": record_date,
        "exDate": ex_date,
        "paymentDate": payment_date,
        "cashPerShare": cash_per_share,
        "stockDividendRatio": stock_ratio,
        "capitalizationRatio": capitalization_ratio,
        "evidencePages": [_page()],
    }


def _artifact(*events: dict, symbol: str = "sh600036") -> dict:
    return {
        "schemaVersion": 1,
        "ruleVersion": CASH_DIVIDEND_RULE_V1,
        "symbol": symbol,
        "coverageStartDate": "2024-01-01",
        "coverageEndDate": "2024-12-31",
        "coverageStatus": "complete",
        "events": list(events),
    }


def test_frozen_cash_dividend_artifact_has_stable_verifiable_hash() -> None:
    draft = _artifact(_event())

    frozen = freeze_cash_dividend_artifact(draft)

    validated = validate_cash_dividend_artifact(frozen, expected_symbol="sh600036")
    assert frozen["ruleVersion"] == CASH_DIVIDEND_RULE_V1
    assert len(frozen["artifactHash"]) == 64
    assert validated == frozen
    assert (
        freeze_cash_dividend_artifact(draft)["artifactHash"] == frozen["artifactHash"]
    )

    tampered = deepcopy(frozen)
    tampered["events"][0]["cashPerShare"] = "0.51"
    with pytest.raises(BacktestInputError, match="摘要"):
        validate_cash_dividend_artifact(tampered)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda event: event.update(stockDividendRatio="0.1"), "送股"),
        (lambda event: event.update(capitalizationRatio="0.1"), "转增"),
        (lambda event: event.update(recordDate="2024-02-30"), "无效"),
        (lambda event: event.update(exDate="2024-04-10"), "日期顺序"),
        (lambda event: event.update(paymentDate="2024-04-10"), "日期顺序"),
        (lambda event: event.update(cashPerShare="1e-2"), "现金红利"),
        (
            lambda event: event.update(sourceUrl="http://example.com/action.pdf"),
            "官方白名单PDF",
        ),
        (
            lambda event: event.update(
                evidencePages=[{"page": 0, "excerpt": "x", "excerptSha256": "0" * 64}]
            ),
            "证据页",
        ),
    ],
)
def test_unsupported_or_ambiguous_events_fail_closed(change, message: str) -> None:
    event = _event()
    change(event)

    with pytest.raises(BacktestInputError, match=message):
        freeze_cash_dividend_artifact(_artifact(event))


def test_cash_dividend_artifact_requires_complete_coverage_and_matching_symbol() -> (
    None
):
    incomplete = _artifact(_event())
    incomplete["coverageStatus"] = "partial"
    with pytest.raises(BacktestInputError, match="完整"):
        freeze_cash_dividend_artifact(incomplete)

    frozen = freeze_cash_dividend_artifact(_artifact(_event()))
    with pytest.raises(BacktestInputError, match="标的"):
        validate_cash_dividend_artifact(frozen, expected_symbol="sz000001")


def test_price_and_coverage_evidence_are_canonicalized_and_covered_by_artifact_hash() -> (
    None
):
    draft = _artifact(_event())
    draft["coverageEvidence"] = {
        "source": "cninfo",
        "queryStartDate": "2022-01-01",
        "queryEndDate": "2024-12-31",
        "pagesRead": 2,
        "terminalPage": True,
        "noticeIds": ["1221234567", "n-2"],
    }
    ohlc = {"open": "9.900", "high": "10.100", "low": "9.800", "close": "10.0000"}
    draft["priceValidation"] = {
        "detectedDates": [],
        "pairs": [
            {
                "exDate": "2024-04-11",
                "previousDate": "2024-04-10",
                "rawPrevious": ohlc,
                "rawCurrent": ohlc,
                "qfqPrevious": ohlc,
                "qfqCurrent": ohlc,
            }
        ],
    }

    frozen = freeze_cash_dividend_artifact(draft)
    assert (
        validate_cash_dividend_artifact(frozen)["coverageEvidence"]
        == draft["coverageEvidence"]
    )
    assert (
        frozen["artifactHash"] == freeze_cash_dividend_artifact(draft)["artifactHash"]
    )
    assert frozen["priceValidation"]["pairs"][0]["rawCurrent"]["close"] == "10.0000"

    tampered = deepcopy(frozen)
    tampered["priceValidation"]["pairs"][0]["rawCurrent"]["close"] = "9.5"
    with pytest.raises(BacktestInputError, match="摘要"):
        validate_cash_dividend_artifact(tampered)


def test_conflicting_duplicate_ex_date_fails_closed() -> None:
    first = _event(action_id="action-a")
    second = _event(action_id="action-b", cash_per_share="0.60")
    with pytest.raises(BacktestInputError, match="重复除权日"):
        freeze_cash_dividend_artifact(_artifact(first, second))


def test_action_notice_must_be_present_in_complete_coverage_query() -> None:
    draft = _artifact(_event())
    draft["coverageEvidence"] = {
        "source": "cninfo",
        "queryStartDate": "2022-01-01",
        "queryEndDate": "2024-12-31",
        "pagesRead": 1,
        "terminalPage": True,
        "noticeIds": ["different-notice"],
    }

    with pytest.raises(BacktestInputError, match="覆盖证据"):
        freeze_cash_dividend_artifact(draft)


@pytest.mark.parametrize(
    ("symbol", "record_date"),
    [
        ("sh600036", "2015-09-07"),
        ("sz000001", "2015-09-07"),
        ("bj920185", "2024-06-30"),
        ("bj920185", "2028-01-01"),
    ],
)
def test_tax_rule_effective_date_gaps_are_rejected(
    symbol: str, record_date: str
) -> None:
    ex_date = (
        "2015-09-08"
        if record_date == "2015-09-07"
        else "2024-07-01"
        if record_date == "2024-06-30"
        else "2028-01-02"
    )
    payment_date = ex_date
    published_date = (
        "2015-09-01"
        if record_date.startswith("2015")
        else "2024-06-01"
        if record_date.startswith("2024")
        else "2027-12-01"
    )
    event = _event(
        symbol=symbol,
        record_date=record_date,
        ex_date=ex_date,
        payment_date=payment_date,
    )
    event["publishedDate"] = published_date
    notice_file = event["sourceUrl"].rsplit("/", 1)[-1]
    event["sourceUrl"] = (
        f"https://static.cninfo.com.cn/finalpage/{published_date}/{notice_file}"
    )
    artifact = _artifact(event, symbol=symbol)
    artifact["coverageStartDate"] = record_date
    artifact["coverageEndDate"] = payment_date

    with pytest.raises(BacktestInputError, match="税制有效期"):
        freeze_cash_dividend_artifact(artifact)


@pytest.mark.parametrize(
    ("symbol", "record", "ex_date", "payment", "published"),
    [
        ("sh600036", "2015-09-08", "2015-09-09", "2015-09-10", "2015-09-01"),
        ("bj920185", "2024-07-01", "2024-07-02", "2024-07-03", "2024-06-20"),
    ],
)
def test_supported_tax_policy_effective_start_boundaries_are_accepted(
    symbol: str, record: str, ex_date: str, payment: str, published: str
) -> None:
    event = _event(
        symbol=symbol,
        record_date=record,
        ex_date=ex_date,
        payment_date=payment,
    )
    event["publishedDate"] = published
    event["sourceUrl"] = (
        f"https://static.cninfo.com.cn/finalpage/{published}/1221234567.PDF"
    )
    artifact = _artifact(event, symbol=symbol)
    artifact["coverageStartDate"] = record
    artifact["coverageEndDate"] = payment

    frozen = freeze_cash_dividend_artifact(artifact)
    assert validate_cash_dividend_artifact(frozen)["events"][0]["recordDate"] == record


def test_dividend_entitlement_survives_fifo_sale_and_tax_is_deferred_until_payment() -> (
    None
):
    ledger = DividendLedger(
        "sh600036", freeze_cash_dividend_artifact(_artifact(_event()))
    )

    ledger.open_session("2024-03-16")
    ledger.buy("2024-03-16", 100)
    ledger.close_session("2024-03-16")
    ledger.open_session("2024-04-10")
    ledger.close_session("2024-04-10")
    assert ledger.dividends_total == Decimal(0)

    assert ledger.open_session("2024-04-11") == Decimal(0)
    ledger.close_session("2024-04-11")
    assert ledger.receivable == Decimal("50.00")
    assert ledger.dividends_total == Decimal("50.00")

    ledger.open_session("2024-04-15")
    cash_tax = ledger.sell("2024-04-15", 100)
    assert cash_tax == Decimal(0)
    assert ledger.tax_payable == Decimal("10.00")
    assert ledger.receivable == Decimal("50.00")
    ledger.close_session("2024-04-15")

    ledger.open_session("2024-04-20")
    cash_delta = ledger.close_session("2024-04-20")
    assert cash_delta == Decimal("40.00")
    assert ledger.receivable == Decimal(0)
    assert ledger.tax_payable == Decimal(0)
    assert ledger.tax_total == Decimal("10.00")


def test_sale_after_cash_payment_deducts_fifo_tax_immediately() -> None:
    ledger = DividendLedger(
        "sh600036", freeze_cash_dividend_artifact(_artifact(_event()))
    )
    ledger.open_session("2024-03-01")
    ledger.buy("2024-03-01", 100)
    ledger.close_session("2024-03-01")
    ledger.open_session("2024-04-10")
    ledger.close_session("2024-04-10")
    ledger.open_session("2024-04-11")
    ledger.close_session("2024-04-11")
    ledger.open_session("2024-04-20")
    assert ledger.close_session("2024-04-20") == Decimal("50.00")

    ledger.open_session("2024-04-21")
    assert ledger.sell("2024-04-21", 100) == Decimal("5.00")
    assert ledger.tax_payable == Decimal(0)
    assert ledger.tax_total == Decimal("5.00")
    ledger.close_session("2024-04-21")


def test_multiple_dividend_events_keep_partial_fifo_rights_separate() -> None:
    first = _event(action_id="action-2024-001")
    second = _event(
        action_id="action-2024-002",
        record_date="2024-05-10",
        ex_date="2024-05-13",
        payment_date="2024-05-20",
    )
    second["publishedDate"] = "2024-04-20"
    second["sourceUrl"] = (
        "https://static.cninfo.com.cn/finalpage/2024-04-20/1221234567.PDF"
    )
    ledger = DividendLedger(
        "sh600036",
        freeze_cash_dividend_artifact(_artifact(first, second)),
    )

    ledger.open_session("2024-04-09")
    ledger.buy("2024-04-09", 100)
    ledger.close_session("2024-04-09")
    ledger.open_session("2024-04-10")
    ledger.close_session("2024-04-10")
    ledger.open_session("2024-04-11")
    ledger.close_session("2024-04-11")
    ledger.open_session("2024-04-20")
    assert ledger.close_session("2024-04-20") == Decimal("50.00")

    ledger.open_session("2024-05-09")
    ledger.buy("2024-05-09", 100)
    ledger.close_session("2024-05-09")
    ledger.open_session("2024-05-10")
    ledger.close_session("2024-05-10")
    ledger.open_session("2024-05-13")
    ledger.close_session("2024-05-13")
    ledger.open_session("2024-05-14")
    assert ledger.sell("2024-05-14", 50) == Decimal("2.50")
    assert ledger.tax_payable == Decimal("2.50")
    ledger.close_session("2024-05-14")

    ledger.open_session("2024-05-20")
    assert ledger.close_session("2024-05-20") == Decimal("97.50")
    audit = ledger.audit()
    assert [event["entitledShares"] for event in audit["events"]] == [100, 200]
    assert [event["paymentComplete"] for event in audit["events"]] == [True, True]
    assert audit["taxPayable"] == "0.00"
    assert audit["taxTotal"] == "5.00"


def test_record_date_uses_net_close_position_and_ex_open_does_not_create_spendable_cash() -> (
    None
):
    ledger = DividendLedger(
        "sh600036", freeze_cash_dividend_artifact(_artifact(_event()))
    )

    ledger.open_session("2024-04-09")
    ledger.buy("2024-04-09", 100)
    ledger.close_session("2024-04-09")
    ledger.open_session("2024-04-10")
    ledger.buy("2024-04-10", 100)
    ledger.sell("2024-04-10", 50)
    ledger.close_session("2024-04-10")

    cash_delta = ledger.open_session("2024-04-11")
    assert ledger.receivable == Decimal("75.00")
    assert cash_delta == Decimal(0)
    ledger.close_session("2024-04-11")


def test_fifo_tax_uses_natural_month_and_year_anniversaries_on_trade_date() -> None:
    artifact = _artifact(
        _event(
            record_date="2025-04-10",
            ex_date="2025-04-11",
            payment_date="2025-04-20",
        )
    )
    artifact["coverageStartDate"] = "2023-01-01"
    artifact["coverageEndDate"] = "2025-12-31"
    frozen = freeze_cash_dividend_artifact(artifact)
    ledger = DividendLedger("sh600036", frozen)
    ledger.open_session("2023-04-10")
    ledger.buy("2023-04-10", 100)
    ledger.close_session("2023-04-10")
    ledger.open_session("2024-04-11")
    ledger.buy("2024-04-11", 100)
    ledger.close_session("2024-04-11")
    ledger.open_session("2025-03-12")
    ledger.buy("2025-03-12", 100)
    ledger.close_session("2025-03-12")

    # This ledger is driven only across sessions relevant to the simulation;
    # the caller must keep the cash/share fills in date order.
    ledger.open_session("2025-04-10")
    ledger.close_session("2025-04-10")
    ledger.open_session("2025-04-11")
    assert ledger.sell("2025-04-11", 100) == Decimal(0)
    assert ledger.tax_total == Decimal(0)
    assert ledger.sell("2025-04-11", 100) == Decimal(0)
    assert ledger.tax_total == Decimal("5.00")
    assert ledger.sell("2025-04-11", 100) == Decimal(0)
    ledger.close_session("2025-04-11")

    audit = ledger.audit()
    assert audit["symbol"] == "sh600036"
    assert audit["ruleVersion"] == CASH_DIVIDEND_RULE_V1
    assert audit["artifactHash"] == frozen["artifactHash"]
    assert audit["events"][0]["entitledShares"] == 300
    assert audit["events"][0]["grossAmount"] == "150.00"
    assert ledger.tax_payable == Decimal("15.00")
    ledger.open_session("2025-04-20")
    assert ledger.close_session("2025-04-20") == Decimal("135.00")


@pytest.mark.parametrize(
    ("acquired", "sold", "expected_rate"),
    [
        ("2013-01-08", "2013-02-07", "0.20"),
        ("2013-01-08", "2013-02-08", "0.20"),
        ("2013-01-08", "2013-02-09", "0.10"),
        ("2013-01-31", "2013-02-28", "0.20"),
    ],
)
def test_tax_rate_keeps_one_month_anniversary_in_the_20_percent_tier(
    acquired: str, sold: str, expected_rate: str
) -> None:
    # CSRC's official FAQ treats Jan 8 -> Feb 8 and Jan 28-31 -> Feb 28 as one month.
    assert _tax_rate(date.fromisoformat(acquired), date.fromisoformat(sold)) == Decimal(
        expected_rate
    )


def test_session_order_and_unobserved_record_date_fail_closed() -> None:
    ledger = DividendLedger(
        "sh600036", freeze_cash_dividend_artifact(_artifact(_event()))
    )
    with pytest.raises(BacktestInputError, match="先开市"):
        ledger.buy("2024-03-01", 100)

    with pytest.raises(BacktestInputError, match="登记日"):
        ledger.open_session("2024-04-11")


def test_pre_window_record_date_is_retained_for_price_evidence_without_cash_entitlement() -> (
    None
):
    event = _event(
        record_date="2023-12-28",
        ex_date="2024-01-02",
        payment_date="2024-01-05",
    )
    event["publishedDate"] = "2023-12-01"
    event["sourceUrl"] = (
        "https://static.cninfo.com.cn/finalpage/2023-12-01/1221234567.PDF"
    )
    artifact = _artifact(event)
    ledger = DividendLedger("sh600036", freeze_cash_dividend_artifact(artifact))

    assert ledger.open_session("2024-01-02") == Decimal(0)
    assert ledger.close_session("2024-01-02") == Decimal(0)
    assert ledger.receivable == Decimal(0)
    assert ledger.dividends_total == Decimal(0)
