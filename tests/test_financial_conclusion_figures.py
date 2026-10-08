"""Conclusion amounts stay only when a cited filing page or a checked sum supports them."""

import json
import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
)
from core.web.services import financial_report_service as service
from core.web.services.financial_report.conclusion_figures import (
    MISSING_FIGURE,
    excerpts_from_turn,
    filing_excerpts_from_tool_output,
    ground_completed_report,
    ground_report_text,
)

REQUEST = "请研究 示例公司（600000，上海证券交易所），分析日期 2026-10-06，使用 Markdown 二级标题整理研究报告。"
PAGE = [(5, "营业收入 200.00 元 净利润 15.38 1.50 2.50 2.00 3.00 150.00 200.00 174,144,069,958.25")]


def _evidence(excerpt: str, page: object = 5, item_id: str = "k1") -> str:
    return json.dumps(
        {
            "results": [{"knowledgeItemId": item_id, "excerpt": excerpt}],
            "citations": [{"knowledgeItemId": item_id, "financialEvidence": [{"page": page}]}],
        },
        ensure_ascii=False,
    )


def _event(event_type: str, sequence: int, *, status: str = "", payload: dict | None = None) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=2,
        event_id=f"event-{sequence}",
        session_id="session-1",
        turn_id="turn-1",
        sequence=sequence,
        event_type=event_type,
        status=status,
        timestamp=f"2026-10-06T12:00:{sequence:02d}+08:00",
        source="test",
        payload=payload or {},
    )


def _report_events(answer: str, *, tool_output: str = "", tool_result: str = "", tool_status: str = "completed") -> list:
    events = [
        _event(EVENT_USER_MESSAGE, 1, status="recorded", payload={"content": REQUEST}),
    ]
    if tool_output:
        events.append(_event(EVENT_ASSISTANT_ITEM_COMMITTED, 2, status="completed", payload={
            "kind": "tool_call",
            "toolName": "financial_evidence_search_tool",
            "status": tool_status,
            "output": tool_output,
            "itemId": "tool-1",
            "revision": 0,
        }))
    if tool_result:
        events.append(_event(EVENT_TOOL_RESULT, 3, status=tool_status, payload={
            "toolCall": {
                "name": "financial_evidence_search_tool",
                "result": tool_result,
                "status": tool_status,
            }
        }))
    events.append(_event(EVENT_ASSISTANT_ITEM_COMMITTED, 4, status="completed", payload={
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "completed",
        "text": answer,
        "itemId": "answer-1",
        "revision": 0,
    }))
    events.append(_event(EVENT_TURN_COMPLETED, 5, status="completed"))
    return events


def test_uncited_ratio_is_hidden_and_a_cited_amount_stays():
    text = "## 结论\n营业收入 200.00 元，见第5页。毛利率约为 91.93%。\n## 风险\n跌幅 9.99%。"
    grounded = ground_report_text(text, [(5, "营业收入 200.00 元")])
    assert "200.00 元" in grounded
    assert "9.99%" in grounded
    assert "91.93" not in grounded
    assert MISSING_FIGURE in grounded


def test_program_checked_expression_keeps_only_the_matching_result():
    text = "## 结论\n150.00 / 200.00 = 75.00%，另有 150.00 / 200.00 = 0.75%，以及 150.00 / 200.00 = 0.75。见第5页。"
    grounded = ground_report_text(text, PAGE)
    assert "75.00%" in grounded
    assert "0.75%" not in grounded
    assert "= 0.75。" in grounded
    wrong = ground_report_text("## 结论\n150.00 / 200.00 = 91.93%。见第5页。", PAGE)
    assert "150.00" in wrong and "200.00" in wrong and "91.93" not in wrong


def test_rounding_subtraction_and_a_later_expression_use_checked_results():
    ratio = ground_report_text("## 结论\n2.00 / 3.00 = 66.67%，2.00 / 3.00 = 0.67。见第5页。", PAGE)
    assert "66.67%" in ratio and "0.67" in ratio
    difference = ground_report_text("## 结论\n1.50 - 2.50 = -1.00。见第5页。", PAGE)
    assert "-1.00" in difference
    wrong = ground_report_text("## 结论\n1.50 - 2.50 = -9.00。见第5页。", PAGE)
    assert "-9.00" not in wrong and MISSING_FIGURE in wrong
    chain = ground_report_text("## 结论\n1.50 + 2.50 = 4.00，4.00 * 2.00 = 8.00。见第5页。", PAGE)
    assert "4.00" in chain and "8.00" in chain


def test_page_scope_tools_and_non_amounts():
    hidden = ground_report_text("## 结论\n毛利率 9.99%。见第5页。", [(63, "毛利率 9.99%")])
    assert "9.99" not in hidden
    kept = ground_report_text("## 结论\n2024 年代码 600519，见第5页。营业总收入 174,144,069,958.25 元。", PAGE)
    assert kept.endswith("174,144,069,958.25 元。") or "174,144,069,958.25 元" in kept
    assert "2024" in kept and "600519" in kept and "第5页" in kept
    bare = "## 风险\n跌幅 9.99%。"
    assert ground_report_text(bare, []) == bare
    assert ground_report_text("营收 12 亿元", []) == f"营收 {MISSING_FIGURE}"
    glued = ground_report_text("## 结论\n下跌-15.38%。见第5页。", PAGE)
    assert "-15.38" not in glued and MISSING_FIGURE in glued


def test_code_urls_science_fullwidth_and_repeat_runs_stay_stable():
    fenced = ground_report_text("## 结论\n正文 12 亿元。\n```\n12 亿元\n```", [])
    assert fenced.startswith(f"## 结论\n正文 {MISSING_FIGURE}。")
    assert "```\n12 亿元\n```" in fenced
    linked = ground_report_text("## 结论\n见 https://example.com/12.50 之后 12.50 元", [])
    assert "https://example.com/12.50" in linked
    assert linked.endswith(f"之后 {MISSING_FIGURE}")
    science = ground_report_text("## 结论\n增速 1.5e10。链接 https://example.com/q?x=1.5e10\n```\n1.2e3\n```", [])
    assert "增速 没有这一项。" in science
    assert "x=1.5e10" in science and "1.2e3" in science
    fullwidth = ground_report_text("## 结论\n营业收入 ２００.００ 元，见第5页。毛利率 ９１.９３％。", [(5, "200.00")])
    assert "２００.００ 元" in fullwidth
    assert "９１.９３" not in fullwidth
    risk = "## 结论\n见第5页。\n## 风险\n跌幅 ９.９９％。"
    assert ground_report_text(risk, []) == risk
    once = ground_report_text("## 结论\n毛利率 91.93%。", [])
    assert ground_report_text(once, []) == once


@pytest.mark.parametrize("identity", ["600519", "sh600519", "hk00700", "０００００１"])
@pytest.mark.parametrize("label", ["股价", "股票价格"])
def test_stock_identity_before_a_price_label_is_not_a_share_quantity(identity, label):
    text = f"## 结论\n{identity} {label} 123.45 元。持仓 600519 股。"
    projected = ground_report_text(text, [])
    assert f"{identity} {label}" in projected
    assert "123.45" not in projected
    assert "持仓 600519 股" not in projected
    assert projected.count(MISSING_FIGURE) == 2


def test_only_successful_filing_search_can_ground_a_number():
    output = _evidence("营业收入 200.00 元", page="5")
    assert filing_excerpts_from_tool_output("financial_evidence_search_tool", output) == [(5, "营业收入 200.00 元")]
    assert filing_excerpts_from_tool_output("news_search_tool", output) == []
    assert filing_excerpts_from_tool_output("financial_report_query_tool", output) == []
    assert filing_excerpts_from_tool_output("financial_evidence_search_tool", _evidence("200.00", page=True)) == []
    assert filing_excerpts_from_tool_output("financial_evidence_search_tool", "[1, 2]") == []
    assert filing_excerpts_from_tool_output("financial_evidence_search_tool", "{") == []
    failed = excerpts_from_turn(
        [{"type": "tool_call", "toolName": "financial_evidence_search_tool", "output": output, "status": "failed"}],
        [],
    )
    assert failed == []
    grounded = ground_completed_report(
        "## 结论\n营业收入 200.00 元，见第5页。",
        [{"type": "tool_call", "toolName": "financial_evidence_search_tool", "output": output, "status": "completed"}],
        [],
    )
    assert "200.00 元" in grounded


def test_completed_report_reads_item_output_and_tool_result_payload():
    answer = "## 结论\n营业收入 200.00 元，见第5页。毛利率约为 91.93%。"
    output = _evidence("营业收入 200.00 元")
    from_item, _, _ = service._completed_report_from_events(_report_events(answer, tool_output=output), "session-1", "turn-1")
    from_event, _, _ = service._completed_report_from_events(_report_events(answer, tool_result=output), "session-1", "turn-1")
    for grounded in (from_item, from_event):
        assert "200.00 元" in grounded
        assert "91.93" not in grounded
        assert MISSING_FIGURE in grounded
    failed, _, _ = service._completed_report_from_events(
        _report_events(answer, tool_result=output, tool_status="timeout"),
        "session-1",
        "turn-1",
    )
    assert "200.00" not in failed
