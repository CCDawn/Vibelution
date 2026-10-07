"""Financial exports read only an owned, completed canonical research Turn."""

import base64
import json
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
)
from core.web.services import financial_report_service as service

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REPORT = "## 结论\n\n结论文字 **可信**。\n\n| 项目 | 数值 |\n| --- | --- |\n| 营收 | 12 亿元 |\n\n来源：<script>alert(1)</script>"
GATED_REPORT = REPORT.replace("| 营收 | 12 亿元 |", "| 营收 | 没有这一项 |")
RESEARCH_REQUEST = "请研究 示例公司（600000，上海证券交易所），分析日期 2026-10-06，使用 Markdown 二级标题整理研究报告。"


def _event(event_type: str, sequence: int, *, turn_id: str = "turn-1", status: str = "", payload: dict | None = None, session_id: str = "session-1"):
    return TurnJournalEvent(
        schema_version=2,
        event_id=f"event-{sequence}",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status=status,
        timestamp=f"2026-10-06T12:00:{sequence:02d}+08:00",
        source="test",
        payload=payload or {},
    )


def _turn(*, request: str = RESEARCH_REQUEST, terminal: str = EVENT_TURN_COMPLETED, status: str = "completed", answer: str = REPORT, turn_id: str = "turn-1", session_id: str = "session-1"):
    events = [
        _event(EVENT_USER_MESSAGE, 1, turn_id=turn_id, session_id=session_id, status="recorded", payload={"content": request}),
    ]
    if answer:
        events.append(_event(EVENT_ASSISTANT_ITEM_COMMITTED, 2, turn_id=turn_id, session_id=session_id, status="completed", payload={
            "kind": "assistant_message", "channel": "answer", "phase": "final_answer",
            "status": "completed", "text": answer, "itemId": "answer-1", "revision": 0,
        }))
    events.append(_event(terminal, 3, turn_id=turn_id, session_id=session_id, status=status))
    return events


@pytest.fixture
def report_env(monkeypatch):
    events = _turn()
    monkeypatch.setattr(service, "_record_report_export_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.directory, "get_agent", lambda agent_id: {
        "agentId": agent_id, "metadata": {"financialAssistantProfile": "financial_assistant_v1"}
    })
    monkeypatch.setattr(service.session_service, "load_session_chat_state", lambda root, session_id: {"agentId": "agent-1"})
    monkeypatch.setattr(service.session_service, "load_session_conversation_events_snapshot", lambda session_id: events)
    return events


def _export(format: str = "markdown"):
    return service.export_financial_report(
        "agent-1", session_id="session-1", turn_id="turn-1", format=format
    )


def test_markdown_and_json_export_hide_uncited_conclusion_amounts(report_env):
    markdown = _export("markdown")
    assert markdown["content"] == GATED_REPORT
    assert "亿元" not in markdown["content"]
    assert markdown["fileName"] == "stock-research-2026-10-06-600000.md"
    parsed = json.loads(_export("json")["content"])
    assert parsed["assistantAgentId"] == "agent-1"
    assert parsed["sessionId"] == "session-1" and parsed["turnId"] == "turn-1"
    assert parsed["content"] == GATED_REPORT


def test_export_runtime_scene_events_keep_only_bounded_metadata(report_env, monkeypatch):
    records: list[dict] = []
    monkeypatch.setattr(
        service,
        "_record_report_export_event",
        lambda event_code, **kwargs: records.append({"eventCode": event_code, **kwargs}),
    )

    _export("markdown")

    success = records.pop()
    assert success["eventCode"] == "finance.report_export.succeeded"
    assert success["outcome"] == "succeeded"
    assert success["fields"] == {
        "assistantAgentId": "agent-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "format": "markdown",
        "reportChars": len(GATED_REPORT),
    }
    assert REPORT not in repr(success)

    sensitive_request = "不应记录的完整用户请求内容"
    report_env[:] = _turn(request=sensitive_request)
    with pytest.raises(service.FinancialReportUnavailable):
        _export()

    rejected = records.pop()
    assert rejected["eventCode"] == "finance.report_export.rejected"
    assert rejected["outcome"] == "rejected"
    assert rejected["fields"] == {
        "format": "markdown",
        "reasonCategory": "unavailable",
    }
    assert sensitive_request not in repr(rejected)


def test_docx_is_valid_ooxml_with_chinese_and_a_real_table(report_env):
    result = _export("docx")
    assert result["encoding"] == "base64"
    content = base64.b64decode(result["content"], validate=True)
    with zipfile.ZipFile(BytesIO(content)) as package:
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(package.namelist())
        document = ET.fromstring(package.read("word/document.xml"))
    assert len(document.findall(f".//{{{W}}}tbl")) == 1
    assert "结论文字" in "".join(document.itertext())
    assert "营收" in "".join(document.itertext())


def test_print_html_is_standalone_and_escapes_untrusted_answer_markup(report_env):
    result = _export("pdf")
    assert result["mediaType"].startswith("text/html")
    assert result["fileName"].endswith(".html")
    assert "<table>" in result["content"]
    assert "&lt;script&gt;" in result["content"]
    assert "<script>" not in result["content"]
    assert "http-equiv=\"Content-Security-Policy\"" in result["content"]


def test_pdf_file_exports_real_chinese_pdf_for_the_exact_report(report_env):
    from pypdf import PdfReader

    result = _export("pdf-file")
    content = base64.b64decode(result["content"], validate=True)
    assert result["mediaType"] == "application/pdf"
    assert result["fileName"] == "stock-research-2026-10-06-600000.pdf"
    assert result["encoding"] == "base64"
    assert content.startswith(b"%PDF-")
    text = "".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    assert "结论文字" in text and "营收" in text


@pytest.mark.parametrize("pdf_error,expected", [
    (service.FinancialPdfUnavailable, service.FinancialReportUnavailable),
    (service.FinancialPdfTooLarge, service.FinancialReportTooLarge),
])
def test_pdf_failure_uses_existing_report_error_contract(report_env, monkeypatch, pdf_error, expected):
    monkeypatch.setattr(service, "render_pdf", lambda *_args, **_kwargs: (_ for _ in ()).throw(pdf_error("PDF 无法生成")))
    with pytest.raises(expected, match="PDF 无法生成"):
        _export("pdf-file")


def test_only_exact_owned_completed_research_turn_can_export(report_env, monkeypatch):
    report_env.extend(_turn(turn_id="older-good"))
    # The later interrupted Turn must not mask the successful historical report.
    report_env.extend(_turn(turn_id="later-stop", terminal=EVENT_TURN_INTERRUPTED, status="stopped_by_user"))
    assert _export("markdown")["content"] == GATED_REPORT

    report_env[:] = _turn(request="帮我介绍一下公司", turn_id="turn-1")
    with pytest.raises(service.FinancialReportUnavailable, match="不是研究报告"):
        _export()

    report_env[:] = _turn(terminal=EVENT_TURN_FAILED, status="failed_provider")
    with pytest.raises(service.FinancialReportUnavailable, match="尚未成功完成"):
        _export()

    report_env[:] = _turn(answer="")
    with pytest.raises(service.FinancialReportUnavailable, match="没有已提交"):
        _export()

    report_env[:] = _turn(answer="本轮已按请求停止。")
    with pytest.raises(service.FinancialReportUnavailable, match="已停止"):
        _export()

    report_env[:] = _turn()
    report_env[-1].payload["resultStatus"] = "needs_continue"
    with pytest.raises(service.FinancialReportUnavailable, match="尚未成功完成"):
        _export()

    synthesis_request = (
        "你是主助手的股票研究汇总角色。请综合股票 sh600000 的多分析师研究。"
        "研究日期：2026-10-06；观察周期：近30天；研究深度：标准。综合结论与主要风险。\n\n"
        "分析员甲：交叉比较 000001 与 sz300750，另有财务数字 123456；这些都不是目标股票。"
    )
    report_env[:] = _turn(request=synthesis_request)
    synthesis_export = _export("markdown")
    assert synthesis_export["content"] == GATED_REPORT
    assert synthesis_export["fileName"] == "stock-research-2026-10-06-600000.md"


def test_finance_screen_prompt_exports_the_requested_completed_turn(report_env):
    request = (
        "请研究以下股票筛选条件，生成筛选报告。分析截至 2026-10-06。"
        "按条件筛选股票，列出候选、筛选依据和数据限制。\n\n"
        "用户选股条件：PE低于20，PB低于3，成交额高于10亿元\n\n"
        "请调用 financial_market_screen_tool 获取真实候选，不得虚构或补齐股票数据。\n\n"
        "回答需列出行情来源、抓取时间、已加载数量/行情池总数、覆盖是否完整和符合条件数量；"
        "覆盖不完整时明确结果仅基于已加载范围。\n\n"
        "若工具不支持某项条件或调用失败，说明具体缺项，不要用猜测替代。"
    )
    older_turn = _turn(request=request, answer="较早筛选结论", turn_id="older-screen")
    requested_turn = _turn(request=request, answer="目标Turn筛选结论", turn_id="turn-1")
    report_env[:] = older_turn + requested_turn

    assert _export("markdown")["content"] == "目标Turn筛选结论"


@pytest.mark.parametrize("prompt_text", [
    "请筛选 PE 低于20、PB低于3、成交额高于10亿元的股票",
    "请研究以下股票筛选条件，生成筛选报告。分析截至 2026-02-30。按条件筛选股票，列出候选、筛选依据和数据限制。\n\n用户选股条件：PE低于20",
])
def test_noncanonical_screening_requests_are_not_classified_as_research_reports(report_env, prompt_text):
    report_env[:] = _turn(request=prompt_text)

    with pytest.raises(service.FinancialReportUnavailable, match="不是研究报告"):
        _export("markdown")


@pytest.mark.parametrize("symbol,suffix", [("hk00700", "00700"), ("usAAPL", "AAPL"), ("usBRK.B", "BRK.B")])
def test_international_synthesis_exports_keep_the_canonical_stock_code(report_env, symbol, suffix):
    request = f"你是主助手的股票研究汇总角色。请综合股票 {symbol} 的多分析师研究。研究日期：2026-10-06；观察周期：近30天；研究深度：标准。"
    report_env[:] = _turn(request=request)
    assert _export("markdown")["fileName"] == f"stock-research-2026-10-06-{suffix}.md"


def test_topic_exports_use_distinct_hash_suffixes_for_shared_turn_prefix(report_env):
    request = "请对以下主题开展投资研究：银行股估值；分析截至2026-10-06。"
    turn_ids = ("session2-turn-a", "session2-turn-b")
    assert turn_ids[0][:8] == turn_ids[1][:8]
    report_env[:] = _turn(request=request, turn_id=turn_ids[0])
    report_env.extend(_turn(request=request, turn_id=turn_ids[1]))

    names = [
        service.export_financial_report(
            "agent-1", session_id="session-1", turn_id=turn_id, format="markdown"
        )["fileName"]
        for turn_id in turn_ids
    ]

    suffixes = [name.removesuffix(".md").rsplit("-", 1)[-1] for name in names]
    assert all(len(suffix) == 8 for suffix in suffixes)
    assert suffixes[0] != suffixes[1]
    assert names[0] != names[1]


def test_foreign_agent_and_malformed_ids_are_rejected(report_env, monkeypatch):
    monkeypatch.setattr(service.session_service, "load_session_chat_state", lambda root, session_id: {"agentId": "other-agent"})
    with pytest.raises(service.FinancialReportNotFound):
        _export()
    with pytest.raises(service.FinancialReportInvalid):
        service.export_financial_report("agent-1", session_id="../outside", turn_id="turn-1", format="markdown")


def test_oversized_turn_is_rejected_before_formatting(report_env):
    report_env[:] = _turn(answer="x" * (service.MAX_REPORT_TEXT_CHARS + 1))
    with pytest.raises(service.FinancialReportTooLarge):
        _export("docx")


SCREEN_REQUEST = (
    "请研究以下股票筛选条件，生成筛选报告。分析截至 2026-10-06。"
    "按条件筛选股票，列出候选、筛选依据和数据限制。\n\n"
    "用户选股条件：PE低于20"
)
NOTICE = "来源只提供行情时分，未提供交易日期；抓取时间不代表行情日期。市值单位未核实，未用于筛选。"


def _screen_output(items, **extra):
    payload = {
        "ok": True,
        "status": "partial",
        "source": "新浪财经",
        "fetchedAt": "2026-10-06T10:00:00+08:00",
        "coverage": {"providerTotal": 5000, "loaded": 120, "complete": False, "totalFiltered": len(items)},
        "returnedCount": len(items),
        "items": items,
        "notice": NOTICE,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _evidence(ticker, page, excerpt="营业收入 200.00 元"):
    return json.dumps({"ticker": ticker, "query": "营收", "report_period": "2024FY"}, ensure_ascii=False), json.dumps({
        "results": [{"knowledgeItemId": "k1", "excerpt": excerpt}],
        "citations": [{"knowledgeItemId": "k1", "financialEvidence": [{"page": page}]}],
    }, ensure_ascii=False)


def _screen_turn(answer, tools):
    events = [_event(EVENT_USER_MESSAGE, 1, status="recorded", payload={"content": SCREEN_REQUEST})]
    sequence = 2
    for tool in tools:
        events.append(_event(
            EVENT_ASSISTANT_ITEM_COMMITTED,
            sequence,
            status=tool.get("status", "completed"),
            payload={
                "kind": "tool_call",
                "toolName": tool["name"],
                "status": tool.get("status", "completed"),
                "input": tool.get("input", ""),
                "output": tool["output"],
                "itemId": tool["id"],
                "revision": 0,
            },
        ))
        sequence += 1
    events.append(_event(EVENT_ASSISTANT_ITEM_COMMITTED, sequence, status="completed", payload={
        "kind": "assistant_message", "channel": "answer", "phase": "final_answer",
        "status": "completed", "text": answer, "itemId": "answer-1", "revision": 0,
    }))
    events.append(_event(EVENT_TURN_COMPLETED, sequence + 1, status="completed"))
    return events


def test_screening_export_lists_tool_candidates_and_only_matching_filing_pages(report_env):
    evidence_input, evidence_output = _evidence("sh600519", 42)
    failed_input, failed_output = _evidence("000001", 99)
    report_env[:] = _screen_turn("模型说明工具不支持市值。毛利率 91.93%。", [
        {"id": "screen", "name": "financial_market_screen_tool", "output": _screen_output([
            {"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "price": 1258.62, "peRatio": 20.1},
            {"symbol": "sz000001", "ticker": "000001", "name": "平安银行", "price": 10},
        ], coverage={"providerTotal": 5000, "loaded": 120, "complete": False, "totalFiltered": 2}, returnedCount=2)},
        {"id": "evidence", "name": "financial_evidence_search_tool", "input": evidence_input, "output": evidence_output},
        {"id": "failed", "name": "financial_evidence_search_tool", "status": "failed", "input": failed_input, "output": failed_output},
        {"id": "rag", "name": "financial_report_query_tool", "output": json.dumps({"page": 7, "text": "第 7 页"})},
    ])

    content = _export("markdown")["content"]

    assert content.startswith("## 筛选对照（本轮工具结果）\n")
    assert "| 贵州茅台 | 600519 | 第 42 页 |" in content
    assert "| 平安银行 | 000001 | 没有这一项 |" in content
    assert "覆盖不完整，结果仅基于已加载范围。" in content
    assert "候选和财报页码以上表为准。" in content
    assert "工具不支持市值" in content
    assert "1258.62" not in content
    assert "91.93" not in content
    assert "第 7 页" not in content
    assert "第 99 页" not in content
    assert _export("markdown")["content"] == content


def test_cleared_screen_export_does_not_keep_invented_candidates(report_env):
    message = "筛选快照没有不晚于分析日期 2024-12-31 的交易日期，未作为本次研究依据。"
    report_env[:] = _screen_turn("虚构股份 999999 见第1页", [
        {"id": "screen", "name": "financial_market_screen_tool", "output": _screen_output(
            [],
            message=message,
            notice=message,
            returnedCount=0,
            coverage={"providerTotal": 5000, "loaded": 120, "complete": False, "totalFiltered": 0},
        )},
    ])

    content = _export("markdown")["content"]

    assert message in content
    assert "没有符合条件的候选。" in content
    assert "虚构股份" not in content
    assert "999999" not in content
    assert "## 模型原文" not in content


def test_screen_projection_ignores_a_missing_or_failed_payload():
    from core.web.services.financial_report.screen_comparison import project_screening_comparison

    answer = "目标Turn筛选结论"
    assert project_screening_comparison(answer, SCREEN_REQUEST, [], []) == answer
    failed = json.dumps({"ok": False, "status": "unavailable", "items": [{"ticker": "600519", "name": "贵州茅台"}]})
    items = [{"type": "tool_call", "toolName": "financial_market_screen_tool", "status": "failed", "output": _screen_output([{"ticker": "600519", "name": "贵州茅台"}])}]
    assert project_screening_comparison(answer, SCREEN_REQUEST, items, []) == answer
    unavailable = [{"type": "tool_call", "toolName": "financial_market_screen_tool", "status": "completed", "output": failed}]
    assert project_screening_comparison(answer, SCREEN_REQUEST, unavailable, []) == answer
    assert project_screening_comparison(answer, "请研究 示例公司，分析日期 2026-10-06", [
        {"type": "tool_call", "toolName": "financial_market_screen_tool", "status": "completed", "output": _screen_output([{"ticker": "600519", "name": "贵州茅台"}])},
    ], []) == answer


def test_screen_page_matches_symbol_prefix_and_not_a_longer_number():
    from core.chat.turn_journal import EVENT_TOOL_RESULT
    from core.web.services.financial_report.screen_comparison import project_screening_comparison

    output = _screen_output([
        {"ticker": "600519", "name": "贵州茅台"},
    ], coverage={"providerTotal": 10, "loaded": 10, "complete": True, "totalFiltered": 8}, returnedCount=2, outputTruncated=True)
    evidence_output = json.dumps({
        "results": [{"knowledgeItemId": "k1", "excerpt": "营业收入 200.00 元"}],
        "citations": [{"knowledgeItemId": "k1", "financialEvidence": [{"page": 12}, {"page": 40}, {"page": True}]}],
    }, ensure_ascii=False)
    event = TurnJournalEvent(
        schema_version=2, event_id="event-tool", session_id="session-1", turn_id="turn-1", sequence=2,
        event_type=EVENT_TOOL_RESULT, status="completed", timestamp="2026-10-06T12:00:02+08:00", source="test",
        payload={"toolCall": {"name": "financial_evidence_search_tool", "status": "completed", "arguments": {"ticker": "sh600519"}, "result": evidence_output}},
    )
    items = [{"type": "tool_call", "toolName": "financial_market_screen_tool", "status": "completed", "output": output}]
    content = project_screening_comparison("原文", SCREEN_REQUEST, items, [event])
    assert "已加载 10 / 行情池 10。覆盖完整。" in content
    assert "符合条件 8，本次返回 2。" in content
    assert "工具输出已截断，未列入被省略的候选。" in content
    assert "| 贵州茅台 | 600519 | 第 12 页、第 40 页 |" in content
    assert content == project_screening_comparison(content, SCREEN_REQUEST, items, [event])
    glued = [{"type": "tool_call", "toolName": "financial_evidence_search_tool", "status": "completed", "input": json.dumps({"ticker": "1600519"}), "output": evidence_output}]
    without_page = project_screening_comparison("原文", SCREEN_REQUEST, items + glued, [])
    assert "| 贵州茅台 | 600519 | 没有这一项 |" in without_page
