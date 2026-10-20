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


def test_earlier_turn_fetch_in_same_session_stays_visible(monkeypatch):
    """A1-a：修正停靠后 agent 在新 turn 继续——早一 turn 的成功抓取不得因 turn 边界丢失。

    供给边界是本 stage task 会话，不是当前 turn；回执仍如实记录来源 turn。
    """
    receipt = "[网页内容] https://example.org/paper\n\nEarlier turn fetched body."
    _install_events(monkeypatch, [_tool_result_event("turn-earlier", "https://example.org/paper", receipt)])

    texts = task_fetched_text(_task(session_id="sess-1", turn_id="turn-current"))

    assert set(texts) == {"https://example.org/paper"}
    assert texts["https://example.org/paper"]["text"] == "Earlier turn fetched body."
    assert texts["https://example.org/paper"]["turnId"] == "turn-earlier"


def test_same_locator_refetch_in_later_turn_overwrites_earlier(monkeypatch):
    """同一 locator 跨 turn 重复抓取按 Journal 顺序后者覆盖前者（确定性 last-wins）。"""
    first = _tool_result_event(
        "turn-1", "https://example.org/paper",
        "[网页内容] https://example.org/paper\n\nFirst attempt body.", event_id="evt-1",
    )
    second = _tool_result_event(
        "turn-2", "https://example.org/paper",
        "[网页内容] https://example.org/paper\n\nRefetched authoritative body.", event_id="evt-2",
    )
    _install_events(monkeypatch, [first, second])

    texts = task_fetched_text(_task(session_id="sess-1", turn_id="turn-1"))

    assert texts["https://example.org/paper"]["text"] == "Refetched authoritative body."
    assert texts["https://example.org/paper"]["turnId"] == "turn-2"


# 真实事故 fixture：DOI 链接按安全策略在跨主机重定向处停靠，代理随后抓取
# 落地页成功——落地页路径不含 DOI 段，_normalized_locator_keys 的 doi 桥救
# 不了，停靠消息必须把原 URL 桥接为落地页的定位键别名。
_DOI_URL = "https://doi.org/10.13128/substantia-25"
_LANDING_URL = "https://riviste.fupress.net/index.php/subs/article/view/25"
_PARKING = (
    "[网页抓取] 目标发生跨主机重定向，已按安全策略停止自动跟随。\n"
    f"原 URL: {_DOI_URL}\n"
    f"重定向目标: {_LANDING_URL}\n"
    "如确认该目标可信，请直接用 web_fetch_tool 抓取重定向后的 URL。"
)
_LANDING_BODY = "Landing page body about substantia metabolism."
_LANDING_RECEIPT = f"[网页内容] {_LANDING_URL}\n\n{_LANDING_BODY}"


def test_doi_parking_bridges_alias_to_fetched_landing_page(monkeypatch):
    """停靠消息 + 落地页成功：原 URL 与目标双键同文，别名条目诚实标注出处。"""
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, _PARKING, event_id="evt-1"),
        _tool_result_event("turn-1", _LANDING_URL, _LANDING_RECEIPT, event_id="evt-2"),
    ])

    texts = task_fetched_text(_task())

    assert set(texts) == {_DOI_URL, _LANDING_URL}
    assert texts[_DOI_URL]["text"] == _LANDING_BODY
    assert texts[_LANDING_URL]["text"] == _LANDING_BODY
    alias = texts[_DOI_URL]
    assert alias["aliasOf"] == _LANDING_URL
    assert alias["locator"] == _DOI_URL
    # 出处诚实：resolvedUrl 与 Journal 证据沿用 target 的真实抓取。
    assert alias["resolvedUrl"] == _LANDING_URL
    assert alias["eventId"] == "evt-2"
    # 浅拷贝：target 条目自身不带别名标注。
    assert "aliasOf" not in texts[_LANDING_URL]


def test_alias_does_not_overwrite_direct_fetch_of_original(monkeypatch):
    """原 URL 已有直接成功抓取：直接抓取优先，别名只填空。"""
    direct_receipt = f"[网页内容] {_DOI_URL}\n\nDirect DOI fetch body."
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, _PARKING, event_id="evt-1"),
        _tool_result_event("turn-1", _DOI_URL, direct_receipt, event_id="evt-2"),
        _tool_result_event("turn-1", _LANDING_URL, _LANDING_RECEIPT, event_id="evt-3"),
    ])

    texts = task_fetched_text(_task())

    assert set(texts) == {_DOI_URL, _LANDING_URL}
    assert texts[_DOI_URL]["text"] == "Direct DOI fetch body."
    assert "aliasOf" not in texts[_DOI_URL]


def test_parked_redirect_without_target_fetch_stays_unregistered(monkeypatch):
    """停靠了但落地页从未成功抓取：原 URL 不注册条目，不做多跳。"""
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, _PARKING, event_id="evt-1"),
    ])

    assert task_fetched_text(_task()) == {}


def test_malformed_parking_message_is_skipped_without_error(monkeypatch):
    """停靠消息缺「重定向目标」行：解析不出就跳过，不抛错、不留半截条目。"""
    broken_parking = (
        "[网页抓取] 目标发生跨主机重定向，已按安全策略停止自动跟随。\n"
        f"原 URL: {_DOI_URL}\n"
        "如确认该目标可信，请直接用 web_fetch_tool 抓取重定向后的 URL。"
    )
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, broken_parking, event_id="evt-1"),
        _tool_result_event("turn-1", _LANDING_URL, _LANDING_RECEIPT, event_id="evt-2"),
    ])

    texts = task_fetched_text(_task())

    assert set(texts) == {_LANDING_URL}


def test_redirect_parking_tolerates_reordered_and_extra_whitespace(monkeypatch):
    """行序颠倒 + 多余空白 + 全角冒号的停靠消息同样完成桥接。"""
    loose_parking = (
        "[网页抓取] 目标发生跨主机重定向，已按安全策略停止自动跟随。\n"
        f"  重定向目标:  {_LANDING_URL}  \n"
        f"  原 URL：  {_DOI_URL}  \n"
        "如确认该目标可信，请直接用 web_fetch_tool 抓取重定向后的 URL。"
    )
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, loose_parking, event_id="evt-1"),
        _tool_result_event("turn-1", _LANDING_URL, _LANDING_RECEIPT, event_id="evt-2"),
    ])

    texts = task_fetched_text(_task())

    assert set(texts) == {_DOI_URL, _LANDING_URL}
    assert texts[_DOI_URL]["aliasOf"] == _LANDING_URL


def test_doi_candidate_binds_landing_text_through_alias(monkeypatch):
    """候选定位键=DOI URL：source_quotable_blocks 经别名映射拿到落地页原文块。"""
    _install_events(monkeypatch, [
        _tool_result_event("turn-1", _DOI_URL, _PARKING, event_id="evt-1"),
        _tool_result_event("turn-1", _LANDING_URL, _LANDING_RECEIPT, event_id="evt-2"),
    ])

    texts = task_fetched_text(_task())
    source = {"sourceUrl": _DOI_URL, "title": "Substantia 25"}

    blocks = source_quotable_blocks(source, {}, fetched_text_by_locator=texts)

    assert len(blocks) == 1
    assert blocks[0]["text"] == _LANDING_BODY
    assert blocks[0]["locator"] == _DOI_URL
    assert blocks[0]["resolvedUrl"] == _LANDING_URL
