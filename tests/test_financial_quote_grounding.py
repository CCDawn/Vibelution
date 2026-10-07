"""Same-Turn market quotes may ground only their own conclusion claim."""

import json

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
)
from core.web.services import financial_report_service
from core.web.services.financial_report.conclusion_figures import (
    MISSING_FIGURE,
    ground_completed_report,
)

SYMBOL = "sz000001"
TICKER = "000001"
SOURCE_URL = f"https://gu.qq.com/{SYMBOL}/gp"
QUOTE_DATE = "2026-09-30"


def _payload(**updates) -> str:
    value = {
        "ok": True,
        "status": "ok",
        "message": "",
        "ticker": SYMBOL,
        "requestedLimit": 120,
        "availableCandleCount": 0,
        "returnedCandleCount": 0,
        "omittedCandleCount": 0,
        "source": "腾讯财经",
        "currency": "CNY",
        "marketCode": "CN",
        "priceUnit": "元",
        "sourceUrl": SOURCE_URL,
        "fetchedAt": "2026-09-30T16:20:00+08:00",
        "quote": {
            "symbol": SYMBOL,
            "ticker": TICKER,
            "name": "平安银行",
            "market": "深交所",
            "marketCode": "CN",
            "currency": "CNY",
            "marketTimeZone": "Asia/Shanghai",
            "priceUnit": "CNY/share",
            "price": 11.57,
            "previousClose": 11.35,
            "open": 11.4,
            "high": 11.6,
            "low": 11.3,
            "change": 0.22,
            "changePercent": 1.94,
            "volume": 123456,
            "volumeLots": 1234.56,
            "volumeUnit": "shares",
            "turnover": 1000000,
            "turnoverYuan": 1000000,
            "peRatio": 5.5,
            "pbRatio": 0.5,
            "marketCap": 1000000000,
            "totalMarketCapYuan": 1000000000,
            "timestamp": "2026-09-30T16:15:00+08:00",
        },
        "period": "day",
        "adjustment": "qfq",
        "volumeUnit": "手（1手=100股）",
        "candles": {"columns": ["date", "open", "close", "high", "low", "volumeLots"], "rows": []},
        "candleError": "",
        "notice": "公开报价可能延迟。",
    }
    quote_updates = updates.pop("quote", {})
    value.update(updates)
    value["quote"].update(quote_updates)
    return json.dumps(value, ensure_ascii=False)


def _report(
    claim: str = "**最新公开报价**为 **11.57 元/股**",
    *,
    identity: str = "平安银行（000001）",
    source_url: str = SOURCE_URL,
    date_label: str = "行情日期：2026-09-30",
    details: str = "",
) -> str:
    return (
        f"**结论**：{identity}{claim}（{date_label}），来源腾讯（{source_url}）。{details}\n\n"
        "**关键事实**\n前收 11.35 元。"
    )


def _item(output: str, status: str = "completed") -> list[dict]:
    return [{"type": "tool_call", "toolName": "financial_market_snapshot_tool", "output": output, "status": status}]


def test_bold_quote_conclusion_is_kept_without_whitelisting_the_same_value():
    report = _report(claim="**最新公开报价**为 **11.57 元/股**，净利润同为 11.57 元")
    grounded = ground_completed_report(report, _item(_payload()), [])

    assert "**11.57 元/股**" in grounded
    assert f"净利润同为 {MISSING_FIGURE}" in grounded
    assert "前收 11.35 元" in grounded
    assert f"来源腾讯（<{SOURCE_URL}>）。" in grounded


def test_claim_needs_a_same_turn_quote_and_matching_price():
    report = _report()
    assert "11.57 元/股" not in ground_completed_report(report, [], [])
    assert "11.57 元/股" not in ground_completed_report(report, _item(_payload(), "failed"), [])
    assert "11.57 元/股" not in ground_completed_report(report, _item(_payload(quote={"price": 11.56})), [])
    assert "11.57 元/股" in ground_completed_report(report, _item(_payload(), "partial"), [])


@pytest.mark.parametrize(
    "report,updates",
    [
        (_report(source_url="https://gu.qq.com/sz000002/gp"), {}),
        (_report(identity="平安银行", source_url=SOURCE_URL), {}),
        (_report(date_label="抓取时间：2026-09-30"), {}),
        (_report(date_label="行情日期：2026-10-01"), {}),
        (_report(identity="平安银行（000001），另一只股票 sh600000"), {}),
        (_report(claim="净利润为 11.57 元，股价是 11.57 元/股"), {}),
        (_report(claim="**最新公开报价**为 **11.57 港元/股**"), {}),
        (_report(claim="目标股价为 11.57 元/股"), {}),
        (_report(claim="最新报价为 11.5700000000000001 元/股"), {}),
        (_report(), {"ticker": "sh600000"}),
        (_report(), {"quote": {"ticker": "600000"}}),
        (_report(), {"currency": "HKD"}),
        (_report(), {"quote": {"currency": "HKD"}}),
        (_report(), {"sourceUrl": "https://example.com/quote"}),
        (_report(), {"quote": {"timestamp": "not-a-timestamp"}}),
        (_report(), {"ok": False}),
        (_report(), {"status": "error"}),
    ],
)
def test_unmatched_or_cross_bound_claim_is_hidden(report: str, updates: dict):
    grounded = ground_completed_report(report, _item(_payload(**updates)), [])
    assert "11.57" not in grounded
    assert MISSING_FIGURE in grounded


@pytest.mark.parametrize(
    "claim",
    [
        "最新报价为 11.57 港元/股",
        "最新报价为 11.57 HKD/share",
        "最新报价为 11.57 美元/股",
        "latest quote: 11.57 USD/share",
    ],
)
def test_quote_currency_must_match_the_report_unit(claim: str):
    assert "11.57" not in ground_completed_report(_report(claim=claim), _item(_payload()), [])


def test_us_quote_preserves_canonical_symbol_case_and_requires_usd_share_unit():
    source_url = "https://gu.qq.com/usAAPL/gp"
    payload = _payload(
        ticker="usAAPL",
        currency="USD",
        marketCode="US",
        priceUnit="USD/share",
        sourceUrl=source_url,
        quote={
            "symbol": "usAAPL",
            "ticker": "AAPL",
            "marketCode": "US",
            "currency": "USD",
            "priceUnit": "USD/share",
        },
    )
    report = (
        f"**结论**：AAPL 最新报价11.57 美元/股，报价日期：{QUOTE_DATE}，"
        f"来源：{source_url}。"
    )
    assert "11.57 美元" in ground_completed_report(report, _item(payload), [])
    assert "11.57" not in ground_completed_report(report.replace("美元", "港元"), _item(payload), [])


def test_market_quote_is_scoped_to_its_conclusion_paragraph():
    report = (
        "**结论**：平安银行（000001）最新报价为 11.57 元/股。\n\n"
        f"行情日期：{QUOTE_DATE}，来源：{SOURCE_URL}。"
    )
    grounded = ground_completed_report(report, _item(_payload()), [])
    assert "11.57" not in grounded


def test_quote_date_must_be_labelled_and_link_normalization_skips_markdown_and_code():
    report = _report(
        source_url=f"[{SOURCE_URL}]({SOURCE_URL})",
        date_label=f"抓取时间：{QUOTE_DATE}",
    )
    assert "11.57 元/股" not in ground_completed_report(report, _item(_payload()), [])
    raw = f"裸链接（{SOURCE_URL}），链接 [{SOURCE_URL}]({SOURCE_URL})，代码 `{SOURCE_URL}，`。"
    grounded = ground_completed_report(raw, [], [])
    assert f"<{SOURCE_URL}>），" in grounded
    assert f"[{SOURCE_URL}]({SOURCE_URL})" in grounded
    assert f"`{SOURCE_URL}，`" in grounded


def _event(event_type: str, sequence: int, status: str = "", payload: dict | None = None) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=2,
        event_id=f"event-{sequence}",
        session_id="session-quote",
        turn_id="turn-quote",
        sequence=sequence,
        event_type=event_type,
        status=status,
        timestamp=f"2026-09-30T16:15:{sequence:02d}+08:00",
        source="test",
        payload=payload or {},
    )


def test_export_projection_uses_same_turn_quote_grounding():
    answer = _report()
    events = [
        _event(EVENT_USER_MESSAGE, 1, "recorded", {
            "content": "请研究平安银行（000001），分析日期 2026-09-30，使用 Markdown 二级标题整理研究报告。"
        }),
        _event(EVENT_ASSISTANT_ITEM_COMMITTED, 2, "completed", {
            "kind": "tool_call",
            "toolName": "financial_market_snapshot_tool",
            "status": "completed",
            "output": _payload(),
            "itemId": "tool-quote",
            "revision": 0,
        }),
        _event(EVENT_ASSISTANT_ITEM_COMMITTED, 3, "completed", {
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "status": "completed",
            "text": answer,
            "itemId": "answer-quote",
            "revision": 0,
        }),
        _event(EVENT_TURN_COMPLETED, 4, "completed"),
    ]

    exported, _, _ = financial_report_service._completed_report_from_events(
        events,
        "session-quote",
        "turn-quote",
    )
    assert "11.57 元/股" in exported
    assert f"<{SOURCE_URL}>" in exported
