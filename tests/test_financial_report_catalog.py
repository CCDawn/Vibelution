"""Catalog and ZIP preserve exact native Turn ownership and pagination."""

import base64
from io import BytesIO
import zipfile

import pytest

from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED, EVENT_TURN_COMPLETED, EVENT_USER_MESSAGE, TurnJournalEvent
from core.chat.conversation_store.repository import directory_cursor_for_row
from core.web.services import financial_report_service as reports
from core.web.services.financial_report import catalog


def _turn(session, turn, request, stamp="2026-10-06T12:00:00+08:00"):
    records = [(EVENT_USER_MESSAGE, "recorded", {"content": request}), (EVENT_ASSISTANT_ITEM_COMMITTED, "completed", {"kind": "assistant_message", "channel": "answer", "phase": "final_answer", "status": "completed", "text": f"## 结论\n{turn} 原始结果", "itemId": f"answer-{turn}"}), (EVENT_TURN_COMPLETED, "completed", {})]
    return [TurnJournalEvent(schema_version=2, event_id=f"{turn}-{index}", session_id=session, turn_id=turn, sequence=index, event_type=kind, status=status, timestamp=stamp, source="test", payload=payload) for index, (kind, status, payload) in enumerate(records, 1)]


@pytest.fixture
def env(monkeypatch):
    requests = ["请研究 腾讯（00700，港交所），分析日期 2026-10-06。", "请研究 Apple（AAPL，NASDAQ），分析日期 2026-10-06。", "请研究 银行（600000，上交所），分析日期 2026-10-06。"]
    rows = [{"id": "session-new", "title": "最近会话"}, {"id": "session-old", "title": "较早会话"}, {"id": "foreign", "title": "其他助手"}]
    events = {"session-new": _turn("session-new", "turn-hk", requests[0]) + _turn("session-new", "turn-us", requests[1], "2026-10-06T13:00:00+08:00") + _turn("session-new", "followup", "谢谢"), "session-old": _turn("session-old", "turn-cn", requests[2]), "foreign": _turn("foreign", "private", requests[0])}
    monkeypatch.setattr(reports.directory, "get_agent", lambda agent_id: {"metadata": {"financialAssistantProfile": reports.assistant_service.PROFILE}})
    monkeypatch.setattr(reports.session_service, "load_session_chat_state", lambda root, session_id: {"agentId": "other" if session_id == "foreign" else "agent-1"})
    monkeypatch.setattr(reports.session_service, "load_session_conversation_events_snapshot", lambda session_id: events[session_id])
    monkeypatch.setattr(reports, "_record_report_export_event", lambda *args, **kwargs: None)
    def query(*, agent_id, limit, cursor):
        offset = int(cursor or 0)
        return {"items": rows[offset:offset + limit], "nextCursor": str(offset + limit) if offset + limit < len(rows) else ""}
    monkeypatch.setattr(reports.session_service, "query_sessions", query)
    return rows, events


def test_catalog_paginates_individual_reports_without_followup_or_foreign_content(env):
    first = catalog.list_reports("agent-1", limit=1)
    assert [(row["sessionId"], row["turnId"]) for row in first["items"]] == [("session-new", "turn-us")]
    assert first["nextCursor"] == "0:1"
    second = catalog.list_reports("agent-1", limit=1, cursor=first["nextCursor"])
    assert second["items"][0]["turnId"] == "turn-hk"
    assert second["nextCursor"] == "1:0"
    final = catalog.list_reports("agent-1", cursor=second["nextCursor"])
    assert [row["turnId"] for row in final["items"]] == ["turn-cn"]
    assert final["nextCursor"] is None
    assert first["order"] == "session_recency"


def test_catalog_filters_real_calendar_market_and_exact_ticker(env):
    us = catalog.list_reports("agent-1", market_code="US", q="AAPL", date_from="2026-10-06", date_to="2026-10-06")
    assert [(row["ticker"], row["marketCode"]) for row in us["items"]] == [("AAPL", "US")]
    assert catalog.list_reports("agent-1", date_to="2026-10-05")["items"] == []
    for values in ({"date_from": "2026-02-30"}, {"date_from": "2026-10-07", "date_to": "2026-10-06"}, {"cursor": "../private"}):
        with pytest.raises(reports.FinancialReportInvalid):
            catalog.list_reports("agent-1", **values)


@pytest.mark.parametrize("pinned_at", [None, 1791270000000])
def test_catalog_preserves_native_directory_cursor_across_turn_and_session_pages(env, monkeypatch, pinned_at):
    rows, _events = env
    tokens = [directory_cursor_for_row({"recencyAtMs": 1791270000000 - index, "sessionId": row["id"], "pinnedAtMs": pinned_at}) for index, row in enumerate(rows)]
    seen = []

    def native_query(*, agent_id, limit, cursor):
        seen.append(cursor)
        offset = tokens.index(cursor) + 1 if cursor not in {"", "0"} else 0
        return {"items": rows[offset:offset + limit], "nextCursor": tokens[offset] if offset + limit < len(rows) else ""}

    monkeypatch.setattr(reports.session_service, "query_sessions", native_query)
    first = catalog.list_reports("agent-1", limit=1)
    second = catalog.list_reports("agent-1", limit=1, cursor=first["nextCursor"])
    assert second["items"][0]["turnId"] == "turn-hk"
    assert second["nextCursor"] == tokens[0] + ":0"
    final = catalog.list_reports("agent-1", cursor=second["nextCursor"])
    assert [row["turnId"] for row in final["items"]] == ["turn-cn"]
    assert final["nextCursor"] is None
    assert tokens[0] in seen and tokens[1] in seen


def test_catalog_budget_returns_continuation_and_empty_page_clears_it(env):
    rows, events = env
    rows[:] = [{"id": f"blank-{i}", "title": "空会话"} for i in range(25)]
    events.update({row["id"]: [] for row in rows})
    first = catalog.list_reports("agent-1")
    assert first["items"] == [] and first["scannedSessions"] == 20 and first["nextCursor"] == "20:0"
    assert catalog.list_reports("agent-1", cursor="25:0")["nextCursor"] is None
    last = catalog.list_reports("agent-1", cursor=first["nextCursor"])
    assert last["scannedSessions"] == 5 and last["nextCursor"] is None


def test_subject_does_not_extract_date_or_prompt_heading_as_stock_code():
    title, ticker, code = catalog._subject("请对以下主题开展投资研究：AI产业。分析截至 2026-10-06。", "主题 · AI")
    assert title == "主题 · AI" and ticker is None and code == ""
    assert catalog._subject("请研究 腾讯（00700，港交所），分析日期 2026-10-06。", "研究")[1:] == ("00700", "HK")


@pytest.mark.parametrize("symbol,ticker,market_code", [("sh600519", "600519", "CN"), ("sz000001", "000001", "CN"), ("hk00700", "00700", "HK"), ("usNVDA", "NVDA", "US"), ("（SH600519）", "600519", "CN"), ("（HK00700）", "00700", "HK")])
def test_subject_resolves_prefixed_market_identity(symbol, ticker, market_code):
    request = f"你是主助手的股票研究汇总角色。请综合股票 {symbol} 的多分析师研究。研究日期：2026-10-06。"
    assert catalog._subject(request, "研究")[1:] == (ticker, market_code)


def test_subject_does_not_guess_market_from_bare_ticker():
    assert catalog._subject("请研究 贵州茅台（600519），分析日期 2026-10-06。", "研究")[1:] == ("600519", "")


@pytest.mark.parametrize("prompt", ["Please use financial evidence for this research.", "请研究 主题，分析日期 2026-10-06，所有金额按 USD 展示。", "Please use USD for the reported amounts."])
def test_subject_does_not_treat_english_words_or_currency_as_us_symbols(prompt):
    assert catalog._subject(prompt, "研究")[1:] == (None, "")


def test_batch_zip_contains_distinct_exact_native_turns_and_rejects_duplicates(env):
    targets = [{"sessionId": "session-new", "turnId": "turn-hk"}, {"sessionId": "session-new", "turnId": "turn-us"}]
    result = reports.export_financial_reports("agent-1", targets=targets, format="markdown")
    with zipfile.ZipFile(BytesIO(base64.b64decode(result["content"]))) as package:
        assert package.namelist() == ["01-stock-research-2026-10-06-00700.md", "02-stock-research-2026-10-06-AAPL.md"]
        assert package.read(package.namelist()[0]).decode() == "## 结论\nturn-hk 原始结果"
    assert result["count"] == 2
    for invalid in ([], targets * 11, [targets[0], targets[0]]):
        with pytest.raises(reports.FinancialReportInvalid):
            reports.export_financial_reports("agent-1", targets=invalid, format="markdown")
    with pytest.raises(reports.FinancialReportNotFound):
        reports.export_financial_reports("agent-1", targets=[{"sessionId": "foreign", "turnId": "private"}], format="markdown")
