# -*- coding: utf-8 -*-
"""提炼逐字 quote 锚供给链：上下文原文块供给 + 服务端子串校验 + 一次性修正反馈。

生产实锤（run-882610596ddb，2026-09-02 重跑）：11 个文献候选里 8 个因源站
auth wall/403 抓不到原文；抓到的 3 个也被 qwen3.6-plus 系统性写成
quote=''（只给 record_anchor 引用 id），硬化契约全部拒绝 →
claimEvidenceCount=0 → required_artifact_missing: evidence_card_batch。
根因是 stage task context 里没有可逐字复制的原文块。锁定：

1. extraction 上下文（含 compact 默认模式）必须内嵌 quotableSources[]：
   每个候选/记录带可逐字复制的 blocks[].text、来源优先级标记、
   sourceAccess 访问标记与 quoteAnchorInstruction 指令；
2. quote 合规的既有回写零差异：accepted、completed、不携带任何
   remediation 痕迹，且通过后清除停靠标记；
3. quote 非逐字子串 → 首次不拒绝：停靠 needs_review +
   quoteAnchorRemediation（最近匹配块片段/相似度），修正后重写成功并清标记；
4. 二次不匹配 → 走既有契约拒绝语义（无限循环被结构封死）；
5. auth wall / 抓取失败候选 → sourceAccess=abstract_only（含失败原因），
   摘要级逐字 quote 可过（evidenceStatus=verified_abstract）；
6. 无可引用原文候选 → quoteAvailable=false + no_quotable_text，
   诚实声明 missing_evidence_anchor 跳过即 completed，不产空 quote。
"""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
    QUOTE_BLOCK_MAX_CHARS,
    QUOTE_SOURCES_TOTAL_CHAR_BUDGET,
    audit_extraction_quote_anchors,
    extraction_quotable_sources,
    latest_failed_fetch_attempts,
    nearest_verbatim_hint,
    source_quotable_blocks,
)
from tests._support.team_workflow.helpers import (
    _append_stage_task_tool_trace,
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_CANDIDATE_SUMMARY = "Predictive coding evidence for content extraction coverage."
_VERBATIM_QUOTE = "Predictive coding evidence"


def _setup_extraction_run(tmp_path, monkeypatch, *, candidate_summaries=None):
    """Open one extraction stage task over candidates with the given summaries."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "神经预测编码资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    summaries = candidate_summaries if candidate_summaries is not None else [_CANDIDATE_SUMMARY]
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding supply candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/quote-supply-{index}",
                "sourceKind": "paper",
                "summary": summary,
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/quote-supply-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index, summary in enumerate(summaries, start=1)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-quote-anchor-supply",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    return {
        "teamId": team["teamId"],
        "runId": run_id,
        "candidates": candidates,
        "task": task,
    }


def _anchored_entry(candidate, *, quote: str) -> dict:
    return {
        "candidateId": candidate["candidateId"],
        "status": "extracted",
        "decision": "keep",
        "evidenceStatus": "verified_abstract",
        "title": candidate["title"],
        "source_type": "preprint",
        "source_url": candidate["sourceUrl"],
        "retrieved_at": "2026-09-02T10:00:00Z",
        "fact": f"{candidate['title']} 的摘要支持内容提炼结论。",
        "relation": "supports",
        "verification_status": "metadata_checked",
        "evidenceRefs": [
            {"id": "abstract-quote-1", "type": "quote", "quote": quote}
        ],
    }


def _read_context(setup) -> dict:
    return team_workflow_orchestration_service.get_source_collection_stage_task_context(
        setup["teamId"],
        run_id=setup["runId"],
        task_id=setup["task"]["taskId"],
    )


def _writeback(setup, payload: dict) -> dict:
    return team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        setup["task"]["taskId"],
        {**payload, "recordedByAgent": setup["task"]["task"]["agentId"]},
    )


# ---------------------------------------------------------------------------
# ① 上下文原文块供给（形状断言）
# ---------------------------------------------------------------------------


def test_extraction_context_embeds_quotable_sources_and_instruction(tmp_path, monkeypatch):
    """compact 默认模式也必须带 quotableSources[].blocks 与 quote 锚指令。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch)
    context = _read_context(setup)

    assert context["contextMode"] == "compact"
    sources = context["quotableSources"]
    assert sources, "extraction context must ship quotable sources"
    by_id = {item["sourceId"]: item for item in sources}
    candidate = setup["candidates"][0]
    entry = by_id[candidate["candidateId"]]
    assert entry["sourceKind"] == "candidate"
    assert entry["quoteAvailable"] is True
    assert entry["blockOrigin"] == "stored_summary"
    block = entry["blocks"][0]
    assert block["origin"] == "stored_summary"
    assert block["text"] == _CANDIDATE_SUMMARY
    assert block["chars"] == len(_CANDIDATE_SUMMARY)
    assert block["truncated"] is False

    usage = context["usage"]
    assert "quotableSources" in usage["quoteAnchorInstruction"]
    assert "禁止改写" in usage["quoteAnchorInstruction"]
    # compact 模式此前丢掉 writeback 契约，agent 从未见过逐字复制规则。
    assert "逐字子串" in usage["extractionWritebackContract"]
    assert "quoteAnchorRemediation" in usage["extractionWritebackContract"]

    # 候选页之外的记录同样供给原文块。
    record_sources = [item for item in sources if item["sourceKind"] == "record"]
    assert record_sources, "run records must also ship quotable blocks"


def test_quotable_source_block_priority_truncation_and_budget(tmp_path, monkeypatch):
    """纯函数：块优先级 fetched_body>abstract>stored_summary、截断与预算封顶。"""
    record = {
        "recordId": "record-1",
        "title": "Fetched paper",
        "summary": "Abstract sentence of the linked record.",
        "content": "Full text body paragraph " * 200,
    }
    candidate = {
        "candidateId": "candidate-1",
        "title": "Fetched paper",
        "summary": _CANDIDATE_SUMMARY,
        "metadata": {"sourceRecordId": "record-1"},
    }
    blocks = source_quotable_blocks(candidate, {"record-1": record})
    assert [block["origin"] for block in blocks] == ["fetched_body", "abstract", "stored_summary"]
    assert blocks[0]["truncated"] is True
    assert len(blocks[0]["text"]) <= QUOTE_BLOCK_MAX_CHARS
    assert blocks[1]["text"] == "Abstract sentence of the linked record."
    assert blocks[2]["text"] == _CANDIDATE_SUMMARY

    sources = extraction_quotable_sources(
        [candidate],
        [record],
        block_max_chars=120,
        total_char_budget=200,
    )
    first = sources[0]
    assert first["sourceAccess"] == {"access": "full_text", "reason": ""}
    assert sum(len(block["text"]) for block in first["blocks"]) <= 200
    assert first.get("blockOmitted") == "budget_exhausted"

    exhausted = extraction_quotable_sources(
        [{"candidateId": "candidate-2", "title": "Second", "summary": _CANDIDATE_SUMMARY}],
        [],
        block_max_chars=120,
        total_char_budget=0,
    )
    assert exhausted[0]["quoteAvailable"] is False
    assert exhausted[0].get("blockOmitted") == "budget_exhausted"
    assert exhausted[0]["sourceAccess"]["access"] == "abstract_only"


def test_latest_failed_fetch_attempts_keeps_latest_failure_per_candidate():
    result_first = {
        "evidenceFetchAttempts": [
            {"candidateId": "c-1", "locator": "https://a", "status": "failed", "failureCode": "http_403"},
            {"candidateId": "c-2", "locator": "https://b", "status": "fetched"},
        ]
    }
    result_second = {
        "evidenceFetchAttempts": [
            {"candidateId": "c-1", "locator": "https://a2", "status": "failed", "failureCode": "paywall"},
        ]
    }
    failed = latest_failed_fetch_attempts([result_first, result_second, None, {"evidenceFetchAttempts": "bad"}])
    assert failed == {"c-1": {"locator": "https://a2", "failureCode": "paywall"}}


# ---------------------------------------------------------------------------
# ② quote 合规零差异
# ---------------------------------------------------------------------------


def test_verbatim_quote_writeback_accepted_without_remediation_trace(tmp_path, monkeypatch):
    """合规逐字 quote 回写与既有流程零差异：completed、无 remediation 痕迹。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch)
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    candidate = setup["candidates"][0]

    complete = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "完成资料提炼。",
            "result": {"candidateExtractions": [_anchored_entry(candidate, quote=_VERBATIM_QUOTE)]},
        },
    )
    assert complete["task"]["status"] == "completed"
    assert complete["writeback"]["status"] == "completed"
    assert "quoteAnchorRemediation" not in complete["writeback"]
    assert "quoteAnchorRemediation" not in complete["task"]
    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], setup["task"]["taskId"]
    )
    assert stored_task["status"] == "completed"
    assert "quoteAnchorRemediation" not in stored_task
    assert stored_task["result"]["candidateExtractions"][0]["evidenceRefs"][0]["quote"] == _VERBATIM_QUOTE


# ---------------------------------------------------------------------------
# ③ quote 不匹配 → 反馈 → 修正成功；④ 二次失败 → 既有拒绝
# ---------------------------------------------------------------------------


def test_mismatched_quote_remediation_cycle_then_hard_rejection(tmp_path, monkeypatch):
    """不匹配停靠给反馈 → 修正成功清标记；二次不匹配直接拒绝。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch)
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    candidate = setup["candidates"][0]

    parked = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "完成资料提炼（quote 不匹配）。",
            "result": {
                "candidateExtractions": [
                    _anchored_entry(candidate, quote="预测编码证据支持内容提炼覆盖")
                ]
            },
        },
    )
    assert parked["task"]["status"] == "needs_review"
    remediation = parked["writeback"]["quoteAnchorRemediation"]
    assert remediation["attempt"] == 1
    assert remediation["reason"] == "quote_not_verbatim"
    finding = remediation["findings"][0]
    assert finding["sourceId"] == candidate["candidateId"]
    assert finding["finding"] == "mismatched_quote"
    assert finding["nearestMatch"]["blockOrigin"] == "stored_summary"
    assert "Predictive coding" in finding["nearestMatch"]["snippet"]
    # 中文改写 vs 英文原文无公共子串时相似度如实为 0，但仍给出最近块片段。
    assert finding["nearestMatch"]["similarity"] >= 0
    assert "唯一一次" in remediation["instruction"]

    # 修正成功：逐字 quote 重写 completed，停靠标记被清除。
    complete = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "完成资料提炼（quote 已修正）。",
            "result": {"candidateExtractions": [_anchored_entry(candidate, quote=_VERBATIM_QUOTE)]},
        },
    )
    assert complete["task"]["status"] == "completed"
    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], setup["task"]["taskId"]
    )
    assert "quoteAnchorRemediation" not in stored_task

    # 新一轮首次不匹配再次停靠；二次不匹配拒绝（循环有界）。
    parked_again = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "追加提炼（再次不匹配）。",
            "result": {
                "candidateExtractions": [
                    _anchored_entry(candidate, quote="又一段凭记忆重写的引用")
                ]
            },
        },
    )
    assert parked_again["task"]["status"] == "needs_review"
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="逐字子串",
    ):
        _writeback(
            setup,
            {
                "status": "completed",
                "summary": "追加提炼（第三次不匹配）。",
                "result": {
                    "candidateExtractions": [
                        _anchored_entry(candidate, quote="仍然不是逐字的引用")
                    ]
                },
            },
        )


def test_nearest_verbatim_hint_bounded_snippet(tmp_path, monkeypatch):
    blocks = [{"origin": "stored_summary", "text": _CANDIDATE_SUMMARY}]
    hint = nearest_verbatim_hint("Predictive coding evidense for coverage", blocks)
    assert hint["blockOrigin"] == "stored_summary"
    assert "Predictive coding" in hint["snippet"]
    assert len(hint["snippet"]) <= 240
    assert hint["similarity"] > 0.5
    assert nearest_verbatim_hint("完全无关的中文引用", blocks)["similarity"] >= 0


# ---------------------------------------------------------------------------
# ⑤ auth wall 候选 → 摘要级证据可过；⑥ 无摘要候选 → 诚实跳过
# ---------------------------------------------------------------------------


def test_auth_wall_candidate_degrades_to_abstract_only_quote(tmp_path, monkeypatch):
    """抓取失败（403/auth wall）→ abstract_only 标记，摘要级逐字 quote 可过。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch)
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    candidate = setup["candidates"][0]

    # 真实回写路径留下 failed 抓取尝试（web_fetch_tool 403/auth wall）。
    fetch_attempt = _writeback(
        setup,
        {
            "status": "needs_review",
            "summary": "全文抓取被 auth wall 拒绝，只有摘要可用。",
            "result": {
                "evidenceFetchAttempts": [
                    {
                        "candidateId": candidate["candidateId"],
                        "locator": candidate["sourceUrl"],
                        "status": "failed",
                        "toolName": "web_fetch_tool",
                        "failureCode": "http_403_auth_wall",
                    }
                ]
            },
        },
    )
    assert fetch_attempt["task"]["status"] == "needs_review"

    context = _read_context(setup)
    source = {item["sourceId"]: item for item in context["quotableSources"]}[candidate["candidateId"]]
    assert source["sourceAccess"] == {
        "access": "abstract_only",
        "reason": "fetch_failed:http_403_auth_wall",
    }
    assert source["quoteAvailable"] is True

    # 摘要级逐字 quote 通过既有契约（verified_abstract）。
    complete = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "以摘要为唯一可引用原文完成提炼。",
            "result": {"candidateExtractions": [_anchored_entry(candidate, quote=_VERBATIM_QUOTE)]},
        },
    )
    assert complete["task"]["status"] == "completed"
    assert complete["task"]["result"]["candidateExtractions"][0]["evidenceStatus"] == "verified_abstract"


def test_no_quotable_text_candidate_skips_quote_without_empty_quote(tmp_path, monkeypatch):
    """无可引用原文候选：上下文明确标注，missing_evidence_anchor 诚实跳过即 completed。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch, candidate_summaries=[""])
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    candidate = setup["candidates"][0]

    context = _read_context(setup)
    source = {item["sourceId"]: item for item in context["quotableSources"]}[candidate["candidateId"]]
    assert source["quoteAvailable"] is False
    assert source["blocks"] == []
    assert source["sourceAccess"]["access"] == "no_quotable_text"
    assert "missing_evidence_anchor" in context["usage"]["quoteAnchorInstruction"]

    # 诚实跳过（不产 quote/claim）→ 正常 completed，不被契约卡死。
    complete = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "候选无可引用原文，诚实跳过。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "evidenceStatus": "missing_evidence_anchor",
                        "valueSummary": "仅元数据可用，无摘要可逐字引用。",
                    }
                ]
            },
        },
    )
    assert complete["task"]["status"] == "completed"


def test_audit_classifies_findings_against_blocks(tmp_path, monkeypatch):
    """纯审计：has_anchor 不报、mismatch/missing/empty 分类正确。"""
    blocks_by_id = {
        "candidate-ok": [{"origin": "stored_summary", "text": _CANDIDATE_SUMMARY}],
        "candidate-none": [],
    }
    entries = [
        {"candidateId": "candidate-ok", "decision": "keep", "evidenceRefs": [{"id": "q", "quote": _VERBATIM_QUOTE}]},
        {"candidateId": "candidate-ok", "decision": "keep", "evidenceRefs": [{"id": "q", "quote": "改写的引用"}]},
        {"candidateId": "candidate-ok", "decision": "keep", "valueSummary": "没有 quote"},
        {"candidateId": "candidate-none", "decision": "keep", "evidenceStatus": "missing_evidence_anchor"},
        {"candidateId": "candidate-none", "decision": "keep"},
        {"candidateId": "candidate-ok", "decision": "exclude", "evidenceRefs": [{"id": "q", "quote": "改写的引用"}]},
        {"candidateId": "unknown-id", "decision": "keep"},
    ]
    findings = audit_extraction_quote_anchors(
        entries,
        blocks_by_id,
        resolve_source_id=lambda entry: entry.get("candidateId", ""),
        is_honest_skip=lambda entry: entry.get("evidenceStatus") == "missing_evidence_anchor",
    )
    assert [finding["finding"] for finding in findings] == [
        "mismatched_quote",
        "missing_quote",
        "empty_source",
    ]
    assert findings[0]["entryPath"] == "candidateExtractions[1]"
    assert findings[2]["quoteAvailable"] is False
