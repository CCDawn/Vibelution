"""Same-Turn market quotes may ground only their own conclusion claim."""

import json
from datetime import date, timedelta

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    session_turn_items_from_events,
)
from core.web.services import financial_market_service as market_service
from core.web.services import financial_report_service
from core.web.services.financial_report.conclusion_figures import (
    MISSING_FIGURE,
    ground_completed_report,
)
from core.web.services.financial_research.as_of import research_analysis_date_context
from tools.financial_market_tools import MAX_RESULT_CHARS, financial_market_snapshot_tool

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


def _business_dates(end_date: str, count: int) -> list[str]:
    current = date.fromisoformat(end_date)
    dates = []
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    return list(reversed(dates))


def _daily_payload(
    closes: list[float],
    *,
    symbol: str = SYMBOL,
    end_date: str = QUOTE_DATE,
    payload_updates: dict | None = None,
    quote_updates: dict | None = None,
) -> str:
    market_code = "CN" if symbol[:2] in {"sh", "sz", "bj"} else symbol[:2].upper()
    currency, adjustment, root_unit, timezone = {
        "CN": ("CNY", "qfq", "元", "Asia/Shanghai"),
        "HK": ("HKD", "raw", "HKD/share", "Asia/Hong_Kong"),
        "US": ("USD", "raw", "USD/share", "America/New_York"),
    }[market_code]
    quote_unit = f"{currency}/share"
    source_url = f"https://gu.qq.com/{symbol}/gp"
    quote_timestamp = (
        f"{end_date}T16:15:00-04:00" if market_code == "US"
        else f"{end_date}T16:15:00+08:00"
    )
    quote_ticker = symbol[2:]
    quote_date_rows = _business_dates(end_date, len(closes))
    volume_column = "volumeLots" if market_code == "CN" else "volume"
    rows = [
        [day, close, close, close, close, 100]
        for day, close in zip(quote_date_rows, closes)
    ]
    payload = json.loads(_payload())
    payload.update({
        "ticker": symbol,
        "requestedLimit": 120,
        "availableCandleCount": len(rows),
        "returnedCandleCount": len(rows),
        "omittedCandleCount": 0,
        "source": "腾讯财经",
        "currency": currency,
        "marketCode": market_code,
        "priceUnit": root_unit,
        "sourceUrl": source_url,
        "quote": {
            **payload["quote"],
            "symbol": symbol,
            "ticker": quote_ticker,
            "marketCode": market_code,
            "currency": currency,
            "marketTimeZone": timezone,
            "priceUnit": quote_unit,
            "timestamp": quote_timestamp,
        },
        "period": "day",
        "adjustment": adjustment,
        "candles": {
            "columns": ["date", "open", "close", "high", "low", volume_column],
            "rows": rows,
        },
        "candleError": "",
    })
    payload.update(payload_updates or {})
    payload["quote"].update(quote_updates or {})
    return json.dumps(payload, ensure_ascii=False)


def _native_market_output(
    monkeypatch,
    closes: list[float],
    *,
    limit: int,
    candle_error: str = "",
    analysis_date: str | None = None,
) -> str:
    dates = _business_dates(QUOTE_DATE, len(closes))
    candles = [
        {
            "date": day,
            "open": close - 0.1,
            "close": close,
            "high": close + 0.1,
            "low": close - 0.2,
            "volumeLots": 100,
        }
        for day, close in zip(dates, closes)
    ]
    quote = {
        "symbol": SYMBOL,
        "ticker": TICKER,
        "name": "平安银行",
        "market": "深交所",
        "price": closes[-1],
        "previousClose": closes[-2] if len(closes) > 1 else closes[-1],
        "open": closes[-1] - 0.1,
        "high": closes[-1] + 0.1,
        "low": closes[-1] - 0.2,
        "change": 0.1,
        "changePercent": 1.94,
        "timestamp": f"{QUOTE_DATE}T15:00:00+08:00",
        "marketCode": "CN",
        "currency": "CNY",
        "priceUnit": "CNY/share",
        "marketTimeZone": "Asia/Shanghai",
    }
    snapshot = {
        "stock": quote,
        "candles": candles,
        "source": "腾讯财经",
        "sourceUrl": f"https://gu.qq.com/{SYMBOL}/gp",
        "fetchedAt": f"{QUOTE_DATE}T07:00:00+00:00",
        "candleError": candle_error,
    }
    monkeypatch.setattr(
        market_service,
        "get_stock_snapshot",
        lambda symbol, period: snapshot,
    )
    if analysis_date is None:
        output = financial_market_snapshot_tool(SYMBOL, "day", limit)
    else:
        with research_analysis_date_context(f"分析日期：{analysis_date}"):
            output = financial_market_snapshot_tool(SYMBOL, "day", limit)
    assert len(output) <= MAX_RESULT_CHARS
    return output


def _calculation_report(
    claim: str,
    *,
    symbol: str = SYMBOL,
    quote_date: str = QUOTE_DATE,
    source_url: str | None = None,
) -> str:
    source = source_url or f"https://gu.qq.com/{symbol}/gp"
    return (
        f"## 结论\n{symbol} 的行情指标可复核。\n\n"
        f"## 行情证据\n行情日期：{quote_date}，来源腾讯（{source}）。\n\n"
        f"## 综合结论\n{claim}"
    )


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
            "ticker": "AAPL.OQ",
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


def test_bold_risk_heading_does_not_trigger_full_report_fallback_but_inline_profit_does():
    risk = "**风险**\n跌幅 11.57%。"
    profit = "**利润**：11.57 元"

    assert ground_completed_report(risk, [], []) == risk
    grounded_profit = ground_completed_report(profit, [], [])
    assert "11.57" not in grounded_profit
    assert MISSING_FIGURE in grounded_profit


def test_single_stock_report_can_reuse_its_dated_source_paragraph():
    report = (
        "**结论**：平安银行（000001）最新报价为 11.57 元/股。\n\n"
        f"行情日期：{QUOTE_DATE}，来源：{SOURCE_URL}。"
    )
    grounded = ground_completed_report(report, _item(_payload()), [])
    assert "11.57 元/股" in grounded


def _synthesis(claim: str, *, date: str = QUOTE_DATE) -> str:
    return (
        f"## 结论\nsz000001（平安银行）证据不足。PB 0.48 的含义仍有分歧。\n\n"
        f"## 行情证据\n来源：{SOURCE_URL} ｜ 行情时间 **{date} 16:15**\n\n"
        f"## 综合结论\n{claim}"
    )


def test_dated_close_and_named_ratios_keep_only_the_matching_quote_field():
    claim = "09-30 收 11.57 元、+1.94%，PE 5.5，PB 0.5。净利润 11.57 元。箱体 11.3~11.8 元。"
    grounded = ground_completed_report(_synthesis(claim), _item(_payload()), [])
    assert "收 11.57 元、+1.94%" in grounded
    assert "PE 5.5，PB 0.5" in grounded
    assert "PB 0.48" not in grounded  # A ratio cannot borrow another field's value.
    assert "净利润 11.57" not in grounded
    assert "11.3~11.8" not in grounded  # No raw quote field verifies a predicted range.


@pytest.mark.parametrize("claim", [
    "10-01 收 11.57 元、+1.94%。",
    "2025-09-30 收 11.57 元、+1.94%。",
    "09-30 收 11.57 港元、+1.94%。",
    "09-30 收 11.57 元、-1.94%。",
    "预计收盘价 11.57 元，目标 PB 0.5，预测 PE 5.5。",
    "净利润 11.57 元，股价 11.57 元。",
    "股价 11.57 元 + 0.5 元，PB 0.5 * 2.0。",
    "PB 5.5，PE 0.5。",
    "PB 0.5 元，PE 5.5 美元。",
    "2.0 * PB 0.5。",
    "2025-09-30 PB 0.5，PE 5.5。",
    "sh600000 收盘价 11.57 元，PB 0.5。",
    "`09-30 收 11.57 元`，涨跌幅 9.99%。",
])
def test_report_context_does_not_authorize_forecasts_mismatches_or_math(claim: str):
    grounded = ground_completed_report(_synthesis(claim), _item(_payload()), [])
    conclusion = grounded.split("## 综合结论\n", 1)[1]
    if claim.startswith("`"):
        assert "涨跌幅 9.99" not in conclusion
    elif claim == "09-30 收 11.57 元、-1.94%。":
        assert "11.57 元" in conclusion and "-1.94%" not in conclusion
    else:
        assert "11.57" not in conclusion and "PB 0.5" not in conclusion and "PE 5.5" not in conclusion


@pytest.mark.parametrize("change", [-1.94, 0.0, 1.94])
def test_signed_quote_change_and_zero_ratios_are_field_checked(change: float):
    report = _synthesis(f"涨跌幅 {change:+.2f}%，PB 0.0，PE 0.0。")
    grounded = ground_completed_report(report, _item(_payload(quote={"changePercent": change, "pbRatio": 0.0, "peRatio": None})), [])
    assert f"{change:+.2f}%" in grounded and "PB 0.0" in grounded
    assert "PE 0.0" not in grounded


@pytest.mark.parametrize("updates,status", [
    ({"quote": {"changePercent": True, "pbRatio": "0.5"}}, "completed"),
    ({"quote": {"changePercent": float("inf"), "pbRatio": float("nan")}}, "completed"),
    ({}, "failed"),
    ({"ok": False}, "completed"),
])
def test_failed_or_malformed_metrics_never_ground_numbers(updates: dict, status: str):
    grounded = ground_completed_report(_synthesis("涨跌幅 +1.94%，PB 0.5。"), _item(_payload(**updates), status), [])
    assert "+1.94%" not in grounded and "PB 0.5" not in grounded


def test_wrong_source_date_and_multi_stock_report_cannot_supply_global_context():
    for report in (
        _synthesis("股价 11.57 元，PB 0.5。", date="2026-10-01"),
        _synthesis("股价 11.57 元，PB 0.5。").replace(SOURCE_URL, "https://example.com/quote"),
        _synthesis("股价 11.57 元，PB 0.5。") + "\n## 其他股票\nsh600000 的估值也很低。",
        _synthesis("股价 11.57 元，PB 0.5。").replace("行情时间", "抓取时间"),
    ):
        grounded = ground_completed_report(report, _item(_payload()), [])
        assert "11.57" not in grounded and "PB 0.5" not in grounded


def test_conflicting_same_stock_observations_do_not_supply_inherited_context():
    report = _synthesis("09-30 收 11.57 元，PB 0.5。")
    records = _item(_payload()) + _item(_payload(quote={"pbRatio": 0.6}))
    grounded = ground_completed_report(report, records, [])
    assert "11.57" not in grounded and "PB 0.5" not in grounded


def test_separate_list_claims_do_not_share_unrelated_dates_or_forecasts():
    report = _synthesis(
        "- 行情事实：09-30 收 11.57 元、+1.94%。\n"
        "- 财报资料：2026-06-30 净利润 11.57 元。\n"
        "- 预测：目标股价 11.57 元。"
    )
    grounded = ground_completed_report(report, _item(_payload()), [])
    assert "收 11.57 元、+1.94%" in grounded
    assert "净利润 11.57" not in grounded and "目标股价 11.57" not in grounded


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


def test_complete_daily_candles_ground_only_explicit_moving_averages_and_date_returns():
    closes = [10.0 + index * 0.1 for index in range(20)]
    dates = _business_dates(QUOTE_DATE, len(closes))
    payload = _daily_payload(closes)
    report = _calculation_report(
        f"MA5 11.70 元；MA10 11.45 CNY/share；20日均线为 10.95 CNY/share；"
        f"{dates[0]}至{dates[-1]}区间涨幅 +19.00%。"
    )

    grounded = ground_completed_report(report, _item(payload), [])

    assert "MA5 11.70 元" in grounded
    assert "MA10 11.45 CNY/share" in grounded
    assert "20日均线为 10.95 CNY/share" in grounded
    assert f"{dates[0]}至{dates[-1]}区间涨幅 +19.00%" in grounded


def test_native_market_adapter_request_limited_partial_window_grounds_computed_average(monkeypatch):
    closes = [10.0 + index * 0.1 for index in range(120)]
    output = _native_market_output(monkeypatch, closes, limit=25)
    payload = json.loads(output)

    assert payload["status"] == "partial"
    assert payload["message"] == "已按请求数量或输出长度限制保留最新 K 线。"
    assert payload["requestedLimit"] == 25
    assert payload["availableCandleCount"] == 120
    assert payload["returnedCandleCount"] == 25
    assert payload["omittedCandleCount"] == 95
    report = _calculation_report("MA20 20.95 元。")

    grounded = ground_completed_report(report, _item(output), [])

    assert "MA20 20.95 元" in grounded


def test_degraded_journal_market_result_grounds_a_complete_requested_window():
    closes = [10.0 + index * 0.01 for index in range(115)] + [
        11.35,
        11.36,
        11.37,
        11.38,
        11.39,
    ]
    payload = json.loads(_daily_payload(closes, end_date=QUOTE_DATE))
    payload.update(
        {
            "status": "partial",
            "message": "已按请求数量或输出长度限制保留最新 K 线。",
            "requestedLimit": 25,
            "availableCandleCount": 120,
            "returnedCandleCount": 25,
            "omittedCandleCount": 95,
        }
    )
    payload["candles"]["rows"] = payload["candles"]["rows"][-25:]
    output = json.dumps(payload, ensure_ascii=False)
    report = _calculation_report("MA5 11.37 元。")
    call_id = "market-snapshot-1"
    events = [
        _event(EVENT_USER_MESSAGE, 1, "recorded", {"content": "核对行情指标。"}),
        _event(
            EVENT_ASSISTANT_ITEM_COMMITTED,
            2,
            "ready",
            {
                "kind": "tool_call",
                "toolName": "financial_market_snapshot_tool",
                "status": "ready",
                "callId": call_id,
                "itemId": "tool-quote-degraded",
                "revision": 0,
            },
        ),
        _event(
            EVENT_TOOL_RESULT,
            3,
            "completed",
            {
                "toolCall": {
                    "id": call_id,
                    "name": "financial_market_snapshot_tool",
                    "result": output,
                    "status": "degraded",
                    "semanticStatus": "degraded",
                }
            },
        ),
        _event(
            EVENT_ASSISTANT_ITEM_COMMITTED,
            4,
            "completed",
            {
                "kind": "assistant_message",
                "channel": "answer",
                "phase": "final_answer",
                "status": "completed",
                "text": report,
                "itemId": "answer-quote-degraded",
                "revision": 0,
            },
        ),
        _event(EVENT_TURN_COMPLETED, 5, "completed"),
    ]
    items = session_turn_items_from_events(events, turn_id="turn-quote")

    assert items[0]["status"] == "completed"
    assert items[0]["semanticStatus"] == "degraded"
    assert payload["status"] == "partial"
    assert payload["requestedLimit"] == 25
    assert payload["availableCandleCount"] == 120
    assert payload["returnedCandleCount"] == 25
    assert payload["omittedCandleCount"] == 95
    assert payload["candles"]["rows"][-1][0] == QUOTE_DATE

    grounded = ground_completed_report(report, items, events)

    assert "MA5 11.37 元" in grounded


def test_native_market_adapter_length_clipping_does_not_ground_an_incomplete_request_window(monkeypatch):
    closes = [10.0 + index * 0.1 for index in range(120)]
    output = _native_market_output(monkeypatch, closes, limit=120)
    payload = json.loads(output)
    report = _calculation_report("MA20 20.95 元。")

    assert payload["status"] == "partial"
    assert payload["message"] == "已按请求数量或输出长度限制保留最新 K 线。"
    assert payload["returnedCandleCount"] < min(
        payload["requestedLimit"], payload["availableCandleCount"]
    )
    grounded = ground_completed_report(report, _item(output), [])
    assert f"MA20 {MISSING_FIGURE}" in grounded


@pytest.mark.parametrize(
    "candle_error,analysis_date",
    [("K 线数据暂不可用", None), ("", "2026-09-29")],
)
def test_native_market_adapter_error_or_analysis_cutoff_partial_never_grounds_ma(
    monkeypatch, candle_error: str, analysis_date: str | None
):
    output = _native_market_output(
        monkeypatch,
        [10.0 + index * 0.1 for index in range(20)],
        limit=20,
        candle_error=candle_error,
        analysis_date=analysis_date,
    )
    payload = json.loads(output)
    report = _calculation_report("MA20 10.95 元。")

    assert payload["status"] == "partial"
    if analysis_date:
        assert payload["quote"] is None
        assert "未返回该报价" in payload["message"]
    else:
        assert payload["candleError"]
    grounded = ground_completed_report(report, _item(output), [])

    assert f"MA20 {MISSING_FIGURE}" in grounded


def test_market_calculation_authority_is_per_occurrence_not_a_number_whitelist():
    payload = _daily_payload([10.0 + index * 0.1 for index in range(20)])
    report = _calculation_report(
        "MA5 11.70 元；净利润 11.70 元；目标 MA5 11.70 元；箱体 11.50 至 11.90 元。"
    )

    grounded = ground_completed_report(report, _item(payload), [])

    assert "MA5 11.70 元" in grounded
    assert f"净利润 {MISSING_FIGURE}" in grounded
    assert f"目标 MA5 {MISSING_FIGURE}" in grounded
    assert f"箱体 {MISSING_FIGURE} 至 {MISSING_FIGURE}" in grounded


@pytest.mark.parametrize(
    "symbol,unit",
    [("hk00700", "HKD/share"), ("usNVDA", "USD/share")],
)
def test_market_specific_currency_and_raw_adjustment_can_ground_their_daily_average(
    symbol: str, unit: str
):
    payload = _daily_payload(
        [11.5, 11.6, 11.7, 11.8, 11.9],
        symbol=symbol,
    )
    report = _calculation_report(
        f"MA5 11.70 {unit}。",
        symbol=symbol,
    )

    grounded = ground_completed_report(report, _item(payload), [])

    assert f"MA5 11.70 {unit}" in grounded


def test_current_us_ticker_is_allowed_but_another_bare_or_exchange_ticker_is_not():
    payload = _daily_payload(
        [11.5, 11.6, 11.7, 11.8, 11.9],
        symbol="usNVDA",
    )
    current_ticker = _calculation_report(
        "AI 需求推动 NVDA MA5 11.70 USD/share。", symbol="usNVDA"
    )
    other_bare_ticker = _calculation_report("AAPL MA5 11.70 USD/share。", symbol="usNVDA")
    other_exchange_ticker = _calculation_report(
        "NASDAQ:AAPL MA5 11.70 USD/share。", symbol="usNVDA"
    )

    assert "NVDA MA5 11.70 USD/share" in ground_completed_report(
        current_ticker, _item(payload), []
    )
    assert f"AAPL MA5 {MISSING_FIGURE}" in ground_completed_report(
        other_bare_ticker, _item(payload), []
    )
    assert f"NASDAQ:AAPL MA5 {MISSING_FIGURE}" in ground_completed_report(
        other_exchange_ticker, _item(payload), []
    )


@pytest.mark.parametrize("other_ticker", ["F", "T", "D"])
def test_other_single_character_us_ticker_cannot_authorize_a_calculation(other_ticker: str):
    payload = _daily_payload(
        [11.5, 11.6, 11.7, 11.8, 11.9],
        symbol="usNVDA",
    )
    report = _calculation_report(
        f"{other_ticker} MA5 11.70 USD/share。",
        symbol="usNVDA",
    )

    grounded = ground_completed_report(report, _item(payload), [])

    assert f"{other_ticker} MA5 {MISSING_FIGURE}" in grounded
    assert "11.70 USD/share" not in grounded


def test_current_single_character_us_ticker_is_allowed_for_its_own_calculation():
    payload = _daily_payload(
        [11.5, 11.6, 11.7, 11.8, 11.9],
        symbol="usD",
    )
    report = _calculation_report(
        "D MA5 11.70 USD/share。",
        symbol="usD",
    )

    grounded = ground_completed_report(report, _item(payload), [])

    assert "D MA5 11.70 USD/share" in grounded


def test_us_quote_date_is_checked_in_the_declared_market_timezone():
    payload = json.loads(_daily_payload(
        [11.5, 11.6, 11.7, 11.8, 11.9],
        symbol="usNVDA",
        end_date="2026-10-01",
    ))
    payload["quote"]["timestamp"] = "2026-10-01T00:30:00+14:00"
    report = _calculation_report(
        "MA5 11.70 USD/share。",
        symbol="usNVDA",
        quote_date="2026-10-01",
    )

    grounded = ground_completed_report(
        report,
        _item(json.dumps(payload, ensure_ascii=False)),
        [],
    )

    assert f"MA5 {MISSING_FIGURE}" in grounded


def test_market_calculation_uses_decimal_half_up_rounding():
    payload = _daily_payload([10.0, 10.0, 10.0, 10.0, 10.025])
    report = _calculation_report("MA5 10.01 元；MA5 10.00 元。")

    grounded = ground_completed_report(report, _item(payload), [])

    assert "MA5 10.01 元" in grounded
    assert f"MA5 {MISSING_FIGURE}" in grounded


@pytest.mark.parametrize(
    "payload_updates,quote_updates,tool_status",
    [
        ({"status": "partial"}, {}, "completed"),
        ({"period": "week"}, {}, "completed"),
        ({"source": "其他行情源"}, {}, "completed"),
        ({"currency": "HKD"}, {}, "completed"),
        ({"adjustment": "raw"}, {}, "completed"),
        ({"omittedCandleCount": 1}, {}, "completed"),
        ({"returnedCandleCount": 19}, {}, "completed"),
        ({"candleError": "K 线数据暂不可用"}, {}, "completed"),
        ({}, {"currency": "HKD"}, "completed"),
        ({}, {"marketTimeZone": "UTC"}, "completed"),
        ({}, {}, "partial"),
        ({}, {}, "failed"),
        ({}, {}, "cancelled"),
        ({}, {}, "timeout"),
        ({"returnedCandleCount": 19}, {}, "degraded"),
        ({"candleError": "K 线数据暂不可用"}, {}, "degraded"),
    ],
)
def test_market_calculation_rejects_unavailable_partial_or_mismatched_snapshot(
    payload_updates: dict, quote_updates: dict, tool_status: str
):
    payload = _daily_payload(
        [10.0 + index * 0.1 for index in range(20)],
        payload_updates=payload_updates,
        quote_updates=quote_updates,
    )
    report = _calculation_report("MA20 10.95 元。")

    grounded = ground_completed_report(report, _item(payload, tool_status), [])

    assert f"MA20 {MISSING_FIGURE}" in grounded


def test_market_calculation_rejects_missing_tool_incomplete_window_and_missing_range_endpoint():
    twenty_closes = [10.0 + index * 0.1 for index in range(20)]
    full_dates = _business_dates(QUOTE_DATE, len(twenty_closes))
    short_payload = _daily_payload(twenty_closes[1:])
    incomplete_report = _calculation_report("MA20 10.95 元。")
    assert f"MA20 {MISSING_FIGURE}" in ground_completed_report(
        incomplete_report, _item(short_payload), []
    )

    full_payload = _daily_payload(twenty_closes)
    missing_endpoint = _calculation_report(
        f"{full_dates[0]}至2026-10-01区间收益率 +19.00%。"
    )
    rejected_return = ground_completed_report(missing_endpoint, _item(full_payload), [])
    assert MISSING_FIGURE in rejected_return and "+19.00%" not in rejected_return
    assert f"MA20 {MISSING_FIGURE}" in ground_completed_report(
        incomplete_report, [], []
    )


@pytest.mark.parametrize(
    "claim,quote_date,source_url",
    [
        ("MA5 11.70 元。", "2026-10-01", SOURCE_URL),
        ("MA5 11.70 元。", QUOTE_DATE, "https://example.com/quote"),
        ("MA5 11.71 元。", QUOTE_DATE, SOURCE_URL),
        ("预计 MA5 11.70 元。", QUOTE_DATE, SOURCE_URL),
        ("近30天涨幅 +19.00%。", QUOTE_DATE, SOURCE_URL),
        ("2026-09-02至2026-09-30区间收益率 +19.00%。", QUOTE_DATE, SOURCE_URL),
        ("2026-09-03至2026-09-30区间收益率 +18.99%。", QUOTE_DATE, SOURCE_URL),
    ],
)
def test_wrong_date_wrong_result_forecast_and_fuzzy_return_are_not_grounded(
    claim: str, quote_date: str, source_url: str
):
    payload = _daily_payload([10.0 + index * 0.1 for index in range(20)])
    report = _calculation_report(
        claim,
        quote_date=quote_date,
        source_url=source_url,
    )
    grounded = ground_completed_report(report, _item(payload), [])

    assert MISSING_FIGURE in grounded


def test_cross_stock_context_and_conflicting_snapshots_cannot_ground_calculations():
    closes = [10.0 + index * 0.1 for index in range(20)]
    payload = _daily_payload(closes)
    report = _calculation_report("MA5 11.70 元。") + "\n\n## 其他股票\nsh600000 的数据另行分析。"
    assert f"MA5 {MISSING_FIGURE}" in ground_completed_report(
        report, _item(payload), []
    )

    conflicting = _daily_payload([10.0 + index * 0.2 for index in range(20)])
    assert f"MA5 {MISSING_FIGURE}" in ground_completed_report(
        _calculation_report("MA5 11.70 元。"),
        _item(payload) + _item(conflicting),
        [],
    )
