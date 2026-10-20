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
   同批混有「无原文硬错」条目时同样停靠（不再被硬错短路），反馈附
   honestSkipFindings 指引一次重写修两类问题；
4. 二次不匹配 → 走既有契约拒绝语义（无限循环被结构封死）；
5. 抓取失败且没有原文时不得将模型 summary 当摘要引文；
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
from core.chat.conversation_ledger import append_conversation_event
from tests._support.team_workflow.helpers import (
    _append_stage_task_tool_trace,
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_CANDIDATE_SUMMARY = "Predictive coding evidence for content extraction coverage."
_VERBATIM_QUOTE = "Predictive coding evidence"


def _setup_extraction_run(tmp_path, monkeypatch, *, candidate_summaries=None, with_fetch=True):
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
    if with_fetch:
        for candidate in candidates:
            if candidate["summary"]:
                append_conversation_event(
                    tmp_path, task["sessionId"], task["turn"]["turnId"], "tool_result",
                    status="done", payload={"toolCall": {
                        "name": "web_fetch_tool", "status": "done",
                        "arguments": {"url": candidate["sourceUrl"]},
                        "result": "[网页内容] " + candidate["sourceUrl"] + "\n\n" + candidate["summary"],
                    }},
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
    assert entry["blockOrigin"] == "fetched_text"
    block = entry["blocks"][0]
    assert block["origin"] == "fetched_text"
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
    candidate = {"candidateId": "c1", "sourceUrl": "https://example.org/paper", "summary": "Model invented text"}
    fetched = {candidate["sourceUrl"]: {"text": "Original source text " * 200}}
    assert source_quotable_blocks(candidate, {}) == []
    blocks = source_quotable_blocks(candidate, {}, fetched_text_by_locator=fetched)
    assert [b["origin"] for b in blocks] == ["fetched_text"]
    assert blocks[0]["truncated"]
    assert len(blocks[0]["text"]) <= QUOTE_BLOCK_MAX_CHARS
    sources = extraction_quotable_sources([candidate], [], fetched_text_by_locator=fetched,
                                         block_max_chars=120, total_char_budget=80)
    assert sum(b["chars"] for b in sources[0]["blocks"]) <= 80
    assert sources[0]["blockOmitted"] == "budget_exhausted"
    assert sources[0]["sourceAccess"]["access"] == "retrieved_text"
    exhausted = extraction_quotable_sources([candidate], [], fetched_text_by_locator=fetched, total_char_budget=0)
    assert not exhausted[0]["quoteAvailable"]
    assert exhausted[0]["blockOmitted"] == "budget_exhausted"


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
    assert finding["nearestMatch"]["blockOrigin"] == "fetched_text"
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


def test_mixed_batch_hard_error_plus_mismatch_parks_with_honest_skip_guidance(tmp_path, monkeypatch):
    """混合批次（1 条无原文硬错 + 1 条 quote 不匹配）首次停靠而非硬拒。

    生产实锤（session-20261020-211800-790319）：同一回写里 403 无原文候选
    与可抓取但引文不逐字候选并存时，旧门因 hard_errors 非空直接硬拒，
    一次性修正停靠永远不可达，代理烧完轮次后全量 exclude。
    """
    setup = _setup_extraction_run(
        tmp_path, monkeypatch, candidate_summaries=[_CANDIDATE_SUMMARY, ""]
    )
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    fetchable, unfetchable = setup["candidates"]

    parked = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "混合批次首次回写。",
            "result": {
                "candidateExtractions": [
                    _anchored_entry(fetchable, quote="一段凭记忆改写的引用"),
                    _anchored_entry(unfetchable, quote=_VERBATIM_QUOTE),
                ]
            },
        },
    )
    assert parked["task"]["status"] == "needs_review"
    remediation = parked["writeback"]["quoteAnchorRemediation"]
    assert remediation["attempt"] == 1
    finding = remediation["findings"][0]
    assert finding["sourceId"] == fetchable["candidateId"]
    assert finding["finding"] == "mismatched_quote"
    assert "Predictive coding" in finding["nearestMatch"]["snippet"]
    honest = remediation["honestSkipFindings"][0]
    assert honest["sourceId"] == unfetchable["candidateId"]
    assert honest["finding"] == "empty_source"
    assert "evidenceStatus=missing_evidence_anchor" in honest["guidance"]
    assert "decision=exclude" in honest["guidance"]
    assert "honestSkipFindings" in remediation["instruction"]
    # 停靠路径不落 agent 原始 result：改写 quote 不得泄漏进 canonical 存储。
    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], setup["task"]["taskId"]
    )
    assert stored_task["status"] == "needs_review"
    assert not stored_task.get("result")

    # 一次重写同时修两类问题：逐字 quote + 硬错条目诚实跳过 → completed 清 stale 标记。
    complete = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "混合批次修正：quote 已逐字，无原文条目诚实跳过。",
            "result": {
                "candidateExtractions": [
                    _anchored_entry(fetchable, quote=_VERBATIM_QUOTE),
                    {
                        "candidateId": unfetchable["candidateId"],
                        "status": "extracted",
                        "decision": "exclude",
                        "evidenceStatus": "missing_evidence_anchor",
                        "valueSummary": "源站 403 无原文，诚实跳过。",
                    },
                ]
            },
        },
    )
    assert complete["task"]["status"] == "completed"
    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], setup["task"]["taskId"]
    )
    assert "quoteAnchorRemediation" not in stored_task


def test_mixed_batch_second_attempt_after_parking_is_hard_rejected(tmp_path, monkeypatch):
    """停靠后再次失败（mismatch 或硬错任一/并存）→ 硬拒，环路有界。"""
    setup = _setup_extraction_run(
        tmp_path, monkeypatch, candidate_summaries=[_CANDIDATE_SUMMARY, ""]
    )
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    fetchable, unfetchable = setup["candidates"]

    parked = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "混合批次首次回写。",
            "result": {
                "candidateExtractions": [
                    _anchored_entry(fetchable, quote="一段凭记忆改写的引用"),
                    _anchored_entry(unfetchable, quote=_VERBATIM_QUOTE),
                ]
            },
        },
    )
    assert parked["task"]["status"] == "needs_review"

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
    ) as excinfo:
        _writeback(
            setup,
            {
                "status": "completed",
                "summary": "混合批次二次回写仍未修正。",
                "result": {
                    "candidateExtractions": [
                        _anchored_entry(fetchable, quote="还是凭记忆改写的引用"),
                        _anchored_entry(unfetchable, quote=_VERBATIM_QUOTE),
                    ]
                },
            },
        )
    message = str(excinfo.value)
    assert "真实抓取原文" in message
    assert "逐字子串" in message


def test_nearest_verbatim_hint_bounded_snippet(tmp_path, monkeypatch):
    blocks = [{"origin": "fetched_text", "text": _CANDIDATE_SUMMARY}]
    hint = nearest_verbatim_hint("Predictive coding evidense for coverage", blocks)
    assert hint["blockOrigin"] == "fetched_text"
    assert "Predictive coding" in hint["snippet"]
    assert len(hint["snippet"]) <= 240
    assert hint["similarity"] > 0.5
    assert nearest_verbatim_hint("完全无关的中文引用", blocks)["similarity"] >= 0


# ---------------------------------------------------------------------------
# ⑤ 抓取失败不能引用模型摘要；⑥ 无原文候选诚实跳过
# ---------------------------------------------------------------------------


def test_auth_wall_without_original_text_cannot_quote_model_summary(tmp_path, monkeypatch):
    """抓取失败且没有原文时，模型摘要不能成为可引用证据。"""
    setup = _setup_extraction_run(tmp_path, monkeypatch, with_fetch=False)
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
        "access": "no_quotable_text",
        "reason": "fetch_failed:http_403_auth_wall",
    }
    assert source["quoteAvailable"] is False

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="真实抓取原文"):
        _writeback(setup, {"status": "completed", "result": {
            "candidateExtractions": [_anchored_entry(candidate, quote=_VERBATIM_QUOTE)]}})


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
        "candidate-ok": [{"origin": "fetched_text", "text": _CANDIDATE_SUMMARY}],
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


def test_original_fetch_receipt_replaces_model_summary_in_context_and_gate(tmp_path, monkeypatch):
    setup = _setup_extraction_run(tmp_path, monkeypatch, with_fetch=False)
    candidate = setup["candidates"][0]
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task)
    source = _read_context(setup)["quotableSources"][0]
    assert not source["quoteAvailable"]
    # Another session's successful fetch still cannot supply this task's evidence.
    append_conversation_event(tmp_path, "unrelated-session", "turn-foreign", "tool_result",
        status="done", payload={"toolCall": {"name": "web_fetch_tool", "status": "done",
        "arguments": {"url": candidate["sourceUrl"]}, "result": "[网页内容] " + candidate["sourceUrl"] + "\n\nForeign session text"}})
    assert not _read_context(setup)["quotableSources"][0]["quoteAvailable"]
    # A1-a：同会话早一 turn 的成功抓取现在供给本任务——修正停靠后 agent 在
    # 新 turn 复看早前抓取时不再因 turn 边界丢原文块。
    append_conversation_event(tmp_path, task["sessionId"], "earlier-continuation-turn", "tool_result",
        status="done", payload={"toolCall": {"name": "web_fetch_tool", "status": "done",
        "arguments": {"url": candidate["sourceUrl"]}, "result": "[网页内容] " + candidate["sourceUrl"] + "\n\nEarlier turn foreign text"}})
    earlier = _read_context(setup)["quotableSources"][0]
    assert earlier["quoteAvailable"] is True
    assert earlier["blocks"][0]["text"] == "Earlier turn foreign text"
    original = "Measured cell conversion depended on the experimental context."
    append_conversation_event(tmp_path, task["sessionId"], task["turn"]["turnId"], "tool_result",
        status="done", payload={"toolCall": {"name": "web_fetch_tool", "status": "done",
        "arguments": {"url": candidate["sourceUrl"]}, "result": "[网页内容] " + candidate["sourceUrl"] + "\n\n" + original}})
    source = _read_context(setup)["quotableSources"][0]
    assert source["blocks"][0]["text"] == original
    assert source["blocks"][0]["eventId"]
    assert candidate["summary"] not in str(source["blocks"])
    assert source["sourceAccess"]["access"] == "retrieved_text"
    completed = _writeback(setup, {"status": "completed", "result": {
        "candidateExtractions": [_anchored_entry(candidate, quote="Measured cell conversion")]}})
    assert completed["task"]["status"] == "completed"


def test_untrusted_record_content_and_candidate_metadata_are_not_original_text():
    record = {"recordId": "r1", "sourceRef": "https://example.org/p", "content": "invented content", "summary": "invented abstract"}
    candidate = {"candidateId": "c1", "sourceUrl": record["sourceRef"], "summary": "invented claim",
                 "metadata": {"sourceRecordId": "r1", "fetchReceipt": {"text": "forged"}}}
    assert source_quotable_blocks(candidate, {"r1": record}) == []
    assert source_quotable_blocks(record, {}) == []


# ---------------------------------------------------------------------------
# ⑦ locator 归一化匹配（arXiv vN 可选后缀 / www.大小写 / export 镜像）
# ---------------------------------------------------------------------------


def _receipt(locator: str, text: str) -> dict:
    return {"text": text, "locator": locator, "resolvedUrl": locator,
            "eventId": "evt-" + locator[-6:], "sessionId": "s", "turnId": "t"}


def test_arxiv_version_suffix_record_matches_unversioned_receipt():
    """现网实锤形态：record 带版本号 ↔ 回执无版本（agent 实际抓的 URL）→ 命中。"""
    text = "Unified predictive coding accounts for cortical and cerebellar learning."
    fetched = {"https://arxiv.org/abs/2502.01542": _receipt("https://arxiv.org/abs/2502.01542", text)}
    record = {"recordId": "r1", "sourceUrl": "https://arxiv.org/abs/2502.01542v2"}
    blocks = source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)
    assert len(blocks) == 1
    assert blocks[0]["text"] == text
    # block 字段仍来自原回执，不做任何改写。
    assert blocks[0]["locator"] == "https://arxiv.org/abs/2502.01542"
    assert blocks[0]["resolvedUrl"] == "https://arxiv.org/abs/2502.01542"


def test_arxiv_unversioned_record_matches_versioned_receipt():
    """反方向同样命中：record 无版本 ↔ 回执带版本。"""
    text = "Fetched abstract body for the versioned receipt."
    fetched = {"https://arxiv.org/abs/2608.11575v1": _receipt("https://arxiv.org/abs/2608.11575v1", text)}
    record = {"recordId": "r1", "sourceUrl": "https://arxiv.org/abs/2608.11575"}
    blocks = source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)
    assert [b["text"] for b in blocks] == [text]


def test_arxiv_locator_host_case_and_www_normalization():
    """www. 前缀与 host 大小写差异归一后命中。"""
    text = "Host normalization body."
    fetched = {"https://arxiv.org/abs/2502.01542": _receipt("https://arxiv.org/abs/2502.01542", text)}
    record = {"recordId": "r1", "sourceUrl": "https://WWW.ARxiv.ORG/abs/2502.01542v2"}
    assert source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)[0]["text"] == text


def test_export_arxiv_mirror_receipt_matches_arxiv_record():
    """export.arxiv.org 镜像改道回执 ↔ arxiv.org record → 命中。"""
    text = "Mirror redirected fetch body."
    fetched = {"https://export.arxiv.org/abs/2502.01542": _receipt("https://export.arxiv.org/abs/2502.01542", text)}
    record = {"recordId": "r1", "sourceUrl": "https://arxiv.org/abs/2502.01542v2"}
    assert source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)[0]["text"] == text


def test_locator_normalization_does_not_overmatch():
    """不同 paper id、非 arXiv 站点不因归一化误命中；非 arXiv host 仍做 www/大小写归一。"""
    text = "Original fetched body."
    fetched = {"https://arxiv.org/abs/2502.01542": _receipt("https://arxiv.org/abs/2502.01542", text)}
    # 不同 paper id 不命中。
    other_paper = {"recordId": "r1", "sourceUrl": "https://arxiv.org/abs/2608.11575v1"}
    assert source_quotable_blocks(other_paper, {}, fetched_text_by_locator=fetched) == []
    # 非 arXiv 站点不动 path：版本号差异不归一。
    non_arxiv_versioned = {"recordId": "r1", "sourceUrl": "https://example.org/abs/2502.01542v2"}
    fetched_example = {"https://example.org/abs/2502.01542": _receipt("https://example.org/abs/2502.01542", text)}
    assert source_quotable_blocks(
        non_arxiv_versioned, {}, fetched_text_by_locator=fetched_example) == []
    # 非 arXiv 站点的 host/www 归一仍然生效。
    assert source_quotable_blocks(
        {"recordId": "r1", "sourceUrl": "https://WWW.Example.ORG/abs/2502.01542"},
        {}, fetched_text_by_locator=fetched_example,
    )[0]["text"] == text


def test_pmc_url_record_matches_ebi_pmc_url_receipt():
    """PMC 双镜像桥接：pmc.ncbi.nlm.nih.gov record ↔ ebi.ac.uk 回执 → pmc: 键命中。"""
    text = "PMC mirror full text body."
    fetched = {
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML": _receipt(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML", text
        )
    }
    record = {"recordId": "r1", "sourceUrl": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/"}
    assert source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)[0]["text"] == text


def test_pmc_url_receipt_matches_pmc_url_record_reverse_direction():
    """反方向同样命中：ebi.ac.uk record ↔ pmc.ncbi.nlm.nih.gov 回执。"""
    text = "Reverse PMC bridge body."
    fetched = {"https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/": _receipt(
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/", text)}
    record = {
        "recordId": "r1",
        "sourceUrl": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML",
    }
    assert source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)[0]["text"] == text


def test_pmc_locator_bridge_does_not_overmatch():
    """完整 PMC ID 匹配才桥接：不同 id、非镜像 host 的 PMC 字样不误命中。"""
    text = "Original PMC fetched body."
    fetched = {"https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/": _receipt(
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/", text)}
    # 不同 PMC id 不命中。
    other_pmc = {"recordId": "r1", "sourceUrl": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321/"}
    assert source_quotable_blocks(other_pmc, {}, fetched_text_by_locator=fetched) == []
    # 非镜像 host 即使 path 带 PMC 段也不发 pmc: 键。
    non_mirror = {"recordId": "r1", "sourceUrl": "https://example.org/articles/PMC1234567/"}
    fetched_example = {"https://example.org/articles/PMC9999999/": _receipt(
        "https://example.org/articles/PMC9999999/", text)}
    assert source_quotable_blocks(non_mirror, {}, fetched_text_by_locator=fetched_example) == []
    # PMC id 必须是完整 path 段：PMC1234567abc 这类粘连串不归一成键。
    glued = {"recordId": "r1", "sourceUrl": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567abc/"}
    assert source_quotable_blocks(glued, {}, fetched_text_by_locator=fetched) == []


def test_frontiers_mid_path_doi_bridge_does_not_swallow_trailing_segment():
    """frontiersin.org /articles/<doi>/full：DOI 段在 path 中段，键不得吞 /full。"""
    from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
        _normalized_locator_keys,
    )
    keys = _normalized_locator_keys(
        "https://www.frontiersin.org/articles/10.3389/fmicb.2023.1104454/full"
    )
    assert "doi:10.3389/fmicb.2023.1104454" in keys
    assert "doi:10.3389/fmicb.2023.1104454/full" not in keys


def test_doi_candidate_binds_frontiers_publisher_receipt():
    """现网实锤形态：候选 sourceRef 裸 DOI ↔ frontiersin.org 全文回执 → 命中。"""
    text = "Frontiers fetched abstract body for thiostrepton resistance."
    fetched = {
        "https://www.frontiersin.org/articles/10.3389/fmicb.2023.1104454/full": _receipt(
            "https://www.frontiersin.org/articles/10.3389/fmicb.2023.1104454/full", text
        )
    }
    candidate = {
        "candidateId": "c1",
        "sourceRef": "10.3389/fmicb.2023.1104454",
        "metadata": {"doi": "10.3389/fmicb.2023.1104454"},
    }
    blocks = source_quotable_blocks(candidate, {}, fetched_text_by_locator=fetched)
    assert [b["text"] for b in blocks] == [text]


def test_nature_host_doi_suffix_bridge_binds_implicit_prefix():
    """nature.com/articles/<suffix>：前缀 10.1038 隐含在 host，候选 DOI 桥接命中。"""
    text = "Nature Communications fetched abstract body."
    fetched = {
        "https://www.nature.com/articles/s41467-026-72496-4": _receipt(
            "https://www.nature.com/articles/s41467-026-72496-4", text
        )
    }
    candidate = {
        "candidateId": "c1",
        "sourceRef": "10.1038/s41467-026-72496-4",
        "metadata": {"doi": "10.1038/s41467-026-72496-4"},
    }
    blocks = source_quotable_blocks(candidate, {}, fetched_text_by_locator=fetched)
    assert [b["text"] for b in blocks] == [text]


def test_host_doi_suffix_bridge_does_not_overmatch():
    """nature 桥只认 /articles/<suffix> 形状；他站 /articles/ 路径、异 suffix 不误命中。"""
    from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
        _normalized_locator_keys,
    )
    # 非 nature 站点的同形 path 不发隐含前缀键。
    keys = _normalized_locator_keys("https://example.org/articles/s41467-026-72496-4")
    assert not any(key.startswith("doi:") for key in keys)
    # nature.com 非 /articles/ 路径不发键。
    keys = _normalized_locator_keys("https://www.nature.com/subjects/s41467-026-72496-4")
    assert not any(key.startswith("doi:10.1038/") for key in keys)


def test_doiorg_end_of_path_key_still_bridges():
    """回归：doi.org 结尾形态的既有桥不回归。"""
    from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
        _normalized_locator_keys,
    )
    keys = _normalized_locator_keys("https://doi.org/10.21656/1000-0887.390245")
    assert "doi:10.21656/1000-0887.390245" in keys


# ---------------------------------------------------------------------------
# ⑧ resolvedUrl 重定向变体绑定 + 空 quotableSources 字段保留
# ---------------------------------------------------------------------------


def test_redirected_bare_url_record_binds_receipt_via_resolved_url():
    """A1-b：裸 URL 重定向变体——record 带最终跳转地址，回执按原始请求抓取 → 命中。

    回执 header 的 resolvedUrl（抓取后的最终 URL）以归一化键进入索引；
    block 字段仍指向原始回执，不做任何改写。
    """
    text = "Redirected landing page abstract body."
    fetched = {
        "https://example.org/short-link": {
            "text": text,
            "locator": "https://example.org/short-link",
            "resolvedUrl": "https://www.publisher.example/articles/full-page.html",
            "eventId": "evt-redir", "sessionId": "s", "turnId": "t",
        }
    }
    record = {"recordId": "r1", "sourceUrl": "https://www.publisher.example/articles/full-page.html"}
    blocks = source_quotable_blocks(record, {}, fetched_text_by_locator=fetched)
    assert [b["text"] for b in blocks] == [text]
    assert blocks[0]["locator"] == "https://example.org/short-link"
    assert blocks[0]["resolvedUrl"] == "https://www.publisher.example/articles/full-page.html"


def test_resolved_url_binding_normalizes_and_does_not_overmatch():
    """resolvedUrl 键同样走归一化（www 前缀折叠命中）；不同最终地址不误命中。"""
    text = "Normalized redirect body."
    fetched = {
        "https://example.org/short-link": {
            "text": text,
            "locator": "https://example.org/short-link",
            "resolvedUrl": "https://www.publisher.example/articles/full-page.html",
            "eventId": "evt-redir", "sessionId": "s", "turnId": "t",
        }
    }
    # www. 差异：record 无 www、resolvedUrl 带 www → 归一化后命中。
    bare_host = {"recordId": "r1", "sourceUrl": "https://publisher.example/articles/full-page.html"}
    assert source_quotable_blocks(bare_host, {}, fetched_text_by_locator=fetched)[0]["text"] == text
    # 不同最终地址的 record 不命中。
    other_page = {"recordId": "r2", "sourceUrl": "https://www.publisher.example/articles/other-page.html"}
    assert source_quotable_blocks(other_page, {}, fetched_text_by_locator=fetched) == []


def test_compact_context_keeps_empty_quotable_sources_field():
    """A1-c：extraction 空 quotableSources 列表显式保留为空数组，不整字段丢弃。

    与同函数「空 blocks 显式保留」的语义对齐：agent 看到的是明确的
    「本任务没有任何可引用来源」供给状态，而不是「字段消失」。
    """
    from core.web.services.team_workflow.source_collection_context import (
        compact_source_collection_stage_task_context,
    )

    compact = compact_source_collection_stage_task_context({
        "stageId": "extraction", "contextMode": "compact", "quotableSources": [],
    })
    assert compact["quotableSources"] == []
    # 字段本就不存在的上下文（非 extraction）不会凭空多出该字段。
    without_field = compact_source_collection_stage_task_context({
        "stageId": "finding", "contextMode": "compact",
    })
    assert "quotableSources" not in without_field
