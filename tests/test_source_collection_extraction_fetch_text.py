# -*- coding: utf-8 -*-
"""task_fetched_text：web_fetch_tool 成功回执 → quotable 原文供给的准入边界。

两种成功回执前缀（[网页内容] / [PDF 文本]）都必须进入供给；PDF 回执此前被
拒之门外，纯 PDF 来源（如 arXiv /pdf/）即使抓取成功也必然 no_quotable_text。
同时覆盖 arXiv export 镜像改道后的回执 URL 策略：回执行报告原始请求 URL，
sourceUrl=arxiv.org/abs/x 的源按精确串 locator 匹配必须命中。
"""

from __future__ import annotations

from types import SimpleNamespace

from core.web.services import team_workflow_orchestration_service as s
from core.web.services.team_workflow.source_collection.extraction_fetch_text import (
    task_fetched_text,
)
from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
    source_quotable_blocks,
)


def _tool_result_event(turn_id: str, url: str, result: str, *, status: str = "done", event_id: str = "evt-1"):
    return SimpleNamespace(
        event_type="tool_result",
        turn_id=turn_id,
        event_id=event_id,
        payload={"toolCall": {
            "name": "web_fetch_tool", "status": status,
            "arguments": {"url": url}, "result": result,
        }},
    )


def _install_events(monkeypatch, events):
    monkeypatch.setattr(
        s,
        "_source_collection_stage_conversation_events",
        lambda session_id: events,
    )


def _task(session_id: str = "sess-1", turn_id: str = "turn-1") -> dict:
    # 生产 stage task 的形状：sessionId/turnId 挂在 turn 里。
    return {"turn": {"sessionId": session_id, "turnId": turn_id}}


def test_html_receipt_stays_admitted(monkeypatch):
    receipt = "[网页内容] https://example.org/paper\n\nOriginal abstract body."
    _install_events(monkeypatch, [_tool_result_event("turn-1", "https://example.org/paper", receipt)])

    texts = task_fetched_text(_task())

    assert set(texts) == {"https://example.org/paper"}
    assert texts["https://example.org/paper"]["text"] == "Original abstract body."
    assert texts["https://example.org/paper"]["resolvedUrl"] == "https://example.org/paper"


def test_pdf_receipt_is_admitted_as_quotable_text(monkeypatch):
    receipt = (
        "[PDF 文本] https://arxiv.org/pdf/2401.12345v2\n\n"
        "Mixture-of-experts routing text.\n\n"
        "... [截断，原内容 42000 字符]"
    )
    _install_events(monkeypatch, [_tool_result_event("turn-1", "https://arxiv.org/pdf/2401.12345v2", receipt)])

    texts = task_fetched_text(_task())

    assert set(texts) == {"https://arxiv.org/pdf/2401.12345v2"}
    # 截断提示被剥掉，只保留抓取原文。
    assert texts["https://arxiv.org/pdf/2401.12345v2"]["text"] == "Mixture-of-experts routing text."
    assert texts["https://arxiv.org/pdf/2401.12345v2"]["resolvedUrl"] == "https://arxiv.org/pdf/2401.12345v2"


def test_failed_call_and_error_receipts_are_not_admitted(monkeypatch):
    events = [
        _tool_result_event(
            "turn-1", "https://arxiv.org/abs/2401.12345",
            "[错误] HTTP 403: https://arxiv.org/abs/2401.12345",
            status="failed", event_id="evt-1",
        ),
        _tool_result_event(
            "turn-1", "https://arxiv.org/abs/2401.12346",
            "[错误] HTTP 403: https://arxiv.org/abs/2401.12346",
            event_id="evt-2",
        ),
        _tool_result_event(
            "turn-1", "https://arxiv.org/abs/2401.12347",
            "[网页抓取] URL 内容为空: https://arxiv.org/abs/2401.12347",
            event_id="evt-3",
        ),
        _tool_result_event(
            "turn-1", "https://arxiv.org/abs/2401.12348",
            "[网页内容] https://arxiv.org/abs/2401.12348\n\n",
            event_id="evt-4",
        ),
    ]
    _install_events(monkeypatch, events)

    assert task_fetched_text(_task()) == {}


def test_arxiv_mirrored_receipt_matches_source_locator_blocks(monkeypatch):
    # 工具改道 export 镜像抓取后，回执行仍报告原始请求 URL（策略 a）：
    # sourceUrl=arxiv.org/abs/x 的源必须能按精确串 locator 命中该回执。
    receipt = "[网页内容] https://arxiv.org/abs/2401.12345\n\nPredictive coding abstract body."
    _install_events(monkeypatch, [_tool_result_event("turn-1", "https://arxiv.org/abs/2401.12345", receipt)])

    texts = task_fetched_text(_task())
    source = {"sourceUrl": "https://arxiv.org/abs/2401.12345", "title": "paper"}

    blocks = source_quotable_blocks(source, {}, fetched_text_by_locator=texts)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "Predictive coding abstract body."
    assert blocks[0]["locator"] == "https://arxiv.org/abs/2401.12345"
    assert blocks[0]["resolvedUrl"] == "https://arxiv.org/abs/2401.12345"


def test_arxiv_pdf_receipt_supplies_quotable_blocks_for_pdf_source(monkeypatch):
    receipt = "[PDF 文本] https://arxiv.org/pdf/2401.12345v2\n\nFull text paragraph from the mirrored PDF."
    _install_events(monkeypatch, [_tool_result_event("turn-1", "https://arxiv.org/pdf/2401.12345v2", receipt)])

    texts = task_fetched_text(_task())
    source = {"sourceRef": "https://arxiv.org/pdf/2401.12345v2", "title": "paper"}

    blocks = source_quotable_blocks(source, {}, fetched_text_by_locator=texts)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "Full text paragraph from the mirrored PDF."
