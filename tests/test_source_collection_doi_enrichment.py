# -*- coding: utf-8 -*-
"""候选 DOI 补全 + 诚实 exclude 收口：SCI-021 实弹的两条堵点。

生产实锤（SCI-021）：

1. 检索 provider 不带 DOI 的候选（www.mdpi.com 裸 URL）在出版方 403 后
   无从走 doi.org → EuropePMC 镜像备援——备援链已存在，缺的是
   ``metadata.doi``。锁定：
   - finding 落库（record payload）在 DOI 为空且 title 非空时按 OpenAlex
     标题精确反查补全（fail-open，miss 保持原状）；
   - extraction 上下文读时对存量无 DOI 候选补全并**持久化回候选存储**
     （sideflow 模式下候选元数据的真实持久化位置是 run 级
     ``candidate_store/index.json``，不是 dprun-*/candidates.jsonl）；
   - 补到 DOI 的候选在 quotableSources 里以可抓的
     ``https://doi.org/<doi>`` 形态与原 URL 并列出现；
   - 从 doi.org（或路径含 DOI 段的出版方镜像）抓回的回执能通过
     ``doi:<doi>`` 桥接键命中原 mdpi.com 候选——含真实 writeback 门禁。

2. OUP 非 OA / dbbs 学位论文登录墙是真不可得。提示契约已教
   ``decision=exclude`` 诚实剔除，锁定门禁核验：
   - 逐字 quote 锚校验豁免 exclude 条目（原样成立）；
   - 覆盖门把 exclude 条目算已处理（原样成立）；
   - ``missingEvidenceAnchorCount`` 不统计 exclude 条目（本批修正：
     exclude 条目的 contentExtraction.evidenceStatus=excluded，不进
     evidence ledger 计数）；
   - 一卷 writeback = 1 条 evidence_ready 带逐字 quote + 1 条 exclude 带
     原因 → completed 不降级、物化执行、evidence_card_batch 非空。

所有网络交互都 mock 传输层（``_openalex_exact_title_doi`` /
``core.research.providers._fetch_json``），绝不真打外网。
"""

from __future__ import annotations

import json

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)
from core.web.services.team_workflow.source_collection import doi_enrichment
from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
    audit_extraction_quote_anchors,
    extraction_quotable_sources,
    source_quotable_blocks,
)
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _source_collection_stage_writeback_record_payload,
)
from core.chat.conversation_ledger import append_conversation_event
from tests._support.team_workflow.helpers import (
    _append_stage_task_tool_trace,
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

# SCI-021 实弹形态：mdpi 期刊式路径（卷/期/文章号），路径里没有 DOI 段，
# 检索 provider 也不带 DOI 元数据——正是补全要解决的输入形状。
_MDPI_URL = "https://www.mdpi.com/2073-4395/18/11/2609"
_MDPI_DOI = "10.3390/agriculture18112609"
_MDPI_TITLE = "Deep Soil Organic Carbon Under Cover Crops"
_QUOTE = "Cover crops significantly increased soil organic carbon stocks."


def _openalex_payload(*works: dict) -> dict:
    return {"meta": {"count": len(works)}, "results": list(works)}


def _work(display_name: str, doi: str | None) -> dict:
    return {"display_name": display_name, "doi": f"https://doi.org/{doi}" if doi else None}


def _patch_transport(monkeypatch, payload=None, error=None):
    """Fake the OpenAlex transport at the ``_openalex_transport_fetch`` seam.

    Everything above the seam (URL building, etiquette limiter, parsing,
    exact-title normalization, caching) stays live.
    """
    calls: list[str] = []

    def fake_fetch(url):
        calls.append(url)
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(doi_enrichment, "_openalex_transport_fetch", fake_fetch)
    return calls


def _setup_extraction_run(
    tmp_path,
    monkeypatch,
    *,
    candidates_spec: list[dict],
):
    """Open one extraction stage task over candidates built from spec."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="资料提炼",
        llm_bindings={"dialogue": {"modelId": "houmo_qwen35_9b_agent"}},
    )
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "覆盖作物土壤有机碳",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["cover crops soil organic carbon"],
            "promptCachePolicy": {"requirement": "disabled"},
            # run scope 冻结 questionId（真实 materializer 的 tier-2 question
            # scoping 依赖）；questionId 必须是官方目录内真实题目（与
            # cases_source_collection.py 的 SCI-096 用例同形），否则
            # start_source_collection_run 直接 challenge_task_question_unknown。
            "questionId": "SCI-096",
            "requiredModelPolicy": {
                "providerIds": ["dashscope_main"],
                "modelIds": ["qwen3.6-plus"],
                "requireOfficialProvider": True,
            },
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": spec["title"],
                "sourceUrl": spec["sourceUrl"],
                "sourceKind": "paper",
                "summary": spec.get("summary", _QUOTE),
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, **spec.get("metadata", {})},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for spec in candidates_spec
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-doi-enrichment",
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
# A1 OpenAlex 标题反查（传输层全 mock）
# ---------------------------------------------------------------------------


def test_enrich_missing_doi_exact_normalized_match_returns_bare_doi(monkeypatch):
    calls = _patch_transport(
        monkeypatch,
        payload=_openalex_payload(
            _work("Some Other Paper Entirely", "10.9999/other"),
            _work("  Deep Soil ORGANIC Carbon Under Cover Crops. ", _MDPI_DOI),
        ),
    )
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE) == _MDPI_DOI
    assert len(calls) == 1
    assert calls[0].startswith("https://api.openalex.org/works?search=")
    assert "per-page=5" in calls[0]


def test_enrich_missing_doi_no_exact_match_returns_none(monkeypatch):
    # 宁缺勿错：结果窗口里没有归一化后完全一致的标题就不补。
    _patch_transport(
        monkeypatch,
        payload=_openalex_payload(
            _work("Deep Soil Organic Carbon Under Cover Crops: A Review", "10.9999/close"),
            _work(None, "10.9999/anonymous"),
        ),
    )
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE) is None


def test_enrich_missing_doi_fail_open_on_transport_and_parse_errors(monkeypatch):
    _patch_transport(monkeypatch, error=RuntimeError("HTTP 500"))
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE) is None
    _patch_transport(monkeypatch, payload={"unexpected": "shape"})
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE) is None
    assert doi_enrichment.enrich_missing_doi("   ") is None


def test_enrich_missing_doi_caches_positive_and_negative_results(monkeypatch):
    calls = _patch_transport(monkeypatch, payload=_openalex_payload(_work(_MDPI_TITLE, _MDPI_DOI)))
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE) == _MDPI_DOI
    assert doi_enrichment.enrich_missing_doi(_MDPI_TITLE.upper() + "  ") == _MDPI_DOI
    assert len(calls) == 1  # 缓存命中不再打外网

    miss_calls = _patch_transport(monkeypatch, payload=_openalex_payload())
    assert doi_enrichment.enrich_missing_doi("A Title With No Match") is None
    assert doi_enrichment.enrich_missing_doi("a title with NO match") is None
    assert len(miss_calls) == 1  # 负结果同样缓存


# ---------------------------------------------------------------------------
# A2 finding 落库补全
# ---------------------------------------------------------------------------


def test_finding_record_payload_enriches_missing_doi_from_title(monkeypatch):
    monkeypatch.setattr(
        writeback_materialize_module(),
        "enrich_missing_doi",
        lambda title: _MDPI_DOI if title == _MDPI_TITLE else None,
    )
    payload = _source_collection_stage_writeback_record_payload(
        {
            "title": _MDPI_TITLE,
            "locator": _MDPI_URL,
            "sourceType": "paper",
            "summary": "Cover crop field trial.",
        },
        team_id="team-1",
        run_id="run-1",
        task_id="task-1",
        stage_id="finding",
        agent_id="agent-1",
        agent_role="source_finder",
        index=0,
    )
    assert payload["metadata"]["doi"] == _MDPI_DOI
    # 原 URL 定位保持不变：DOI 只是并列元数据，不替换 sourceRef。
    assert payload["sourceRef"] == _MDPI_URL


def test_finding_record_payload_keeps_existing_doi_and_survives_miss(monkeypatch):
    enrich_calls: list[str] = []

    def fake_enrich(title):
        enrich_calls.append(title)
        return None

    monkeypatch.setattr(writeback_materialize_module(), "enrich_missing_doi", fake_enrich)
    with_doi = _source_collection_stage_writeback_record_payload(
        {"title": "Existing", "locator": "https://doi.org/10.1234/existing", "doi": "10.1234/existing"},
        team_id="team-1", run_id="run-1", task_id="task-1",
        stage_id="finding", agent_id="agent-1", agent_role="source_finder", index=0,
    )
    assert with_doi["metadata"]["doi"] == "10.1234/existing"
    assert enrich_calls == []  # 已有 DOI 不反查

    miss = _source_collection_stage_writeback_record_payload(
        {"title": "Unknown Paper", "locator": "https://example.org/unknown"},
        team_id="team-1", run_id="run-1", task_id="task-1",
        stage_id="finding", agent_id="agent-1", agent_role="source_finder", index=0,
    )
    assert miss["metadata"]["doi"] == ""  # miss 保持历史无 DOI 形状


def writeback_materialize_module():
    from core.web.services.team_workflow.source_collection import writeback_materialize

    return writeback_materialize


# ---------------------------------------------------------------------------
# A3 读时补全 + 持久化回候选存储 + locator 桥接
# ---------------------------------------------------------------------------


def test_extraction_context_enriches_and_persists_missing_doi(tmp_path, monkeypatch):
    setup = _setup_extraction_run(
        tmp_path,
        monkeypatch,
        candidates_spec=[
            {"title": _MDPI_TITLE, "sourceUrl": _MDPI_URL},
            {"title": "Already DoiEd Paper", "sourceUrl": "https://example.org/other", "metadata": {"doi": "10.1234/known"}},
        ],
    )
    calls = _patch_transport(monkeypatch, payload=_openalex_payload(_work(_MDPI_TITLE, _MDPI_DOI)))

    context = _read_context(setup)

    # 上下文可见性：compact 候选摘要的 locator 由补到的 DOI 顶替（既有
    # compact 行为：doi or sourceUrl），quotableSources 的 doi/locators 与
    # 原 URL 并列（compaction 现在透传这两个键）。
    by_id = {item["candidateId"]: item for item in context["candidates"]}
    enriched_id = setup["candidates"][0]["candidateId"]
    assert by_id[enriched_id]["locator"] == _MDPI_DOI
    sources_by_id = {item["sourceId"]: item for item in context["quotableSources"]}
    entry = sources_by_id[enriched_id]
    assert entry["doi"] == _MDPI_DOI
    assert entry["locators"][0] == _MDPI_URL
    assert f"https://doi.org/{_MDPI_DOI}" in entry["locators"]
    assert len(calls) == 1  # 已有 DOI 的候选不反查

    # 持久化：候选存储（candidate_store/index.json）回写了 metadata.doi。
    store_path = team_workflow_orchestration_service._candidate_store_path(setup["teamId"], setup["runId"])
    store = json.loads(store_path.read_text(encoding="utf-8"))
    stored = {item["candidateId"]: item for item in store["candidates"]}[enriched_id]
    assert stored["metadata"]["doi"] == _MDPI_DOI
    assert stored["metadata"]["doiEnrichment"]["provider"] == "openalex_title_lookup"

    # 幂等：重读上下文不再打外网（正结果缓存命中）。
    _read_context(setup)
    assert len(calls) == 1


def test_extraction_context_enrichment_bounds_real_network_lookups(tmp_path, monkeypatch):
    specs = [
        {"title": f"Unmatched Paper {index}", "sourceUrl": f"https://example.org/p{index}"}
        for index in range(6)
    ]
    setup = _setup_extraction_run(tmp_path, monkeypatch, candidates_spec=specs)
    calls = _patch_transport(monkeypatch, payload=_openalex_payload())
    _read_context(setup)
    assert len(calls) == doi_enrichment.READ_PATH_MAX_NETWORK_LOOKUPS


def test_doi_locator_binds_doi_org_and_publisher_mirror_receipts():
    candidate = {
        "candidateId": "c-mdpi",
        "sourceUrl": _MDPI_URL,
        "title": _MDPI_TITLE,
        "metadata": {"doi": _MDPI_DOI},
    }
    doi_receipt = {"text": _QUOTE, "locator": f"https://doi.org/{_MDPI_DOI}"}
    mirror_receipt = {"text": _QUOTE, "locator": f"https://pub.example.org/article/doi/{_MDPI_DOI}"}

    # doi.org 形态（web_fetch 内部走 EuropePMC 镜像备援也回同一参数键）。
    blocks = source_quotable_blocks(
        candidate, {}, fetched_text_by_locator={f"https://doi.org/{_MDPI_DOI}": doi_receipt}
    )
    assert [b["text"] for b in blocks] == [_QUOTE]

    # 路径含 DOI 段的出版方镜像。
    blocks = source_quotable_blocks(
        candidate, {}, fetched_text_by_locator={mirror_receipt["locator"]: mirror_receipt}
    )
    assert [b["text"] for b in blocks] == [_QUOTE]

    # 无 DOI 元数据时（补全前）不桥接——精确性回归。
    legacy = dict(candidate, metadata={})
    assert source_quotable_blocks(
        legacy, {}, fetched_text_by_locator={f"https://doi.org/{_MDPI_DOI}": doi_receipt}
    ) == []


def test_quotable_sources_entry_lists_original_url_plus_doi_link():
    candidate = {
        "candidateId": "c-mdpi",
        "sourceUrl": _MDPI_URL,
        "title": _MDPI_TITLE,
        "summary": _QUOTE,
        "metadata": {"doi": _MDPI_DOI},
    }
    sources = extraction_quotable_sources(
        [candidate],
        [],
        fetched_text_by_locator={_MDPI_URL: {"text": _QUOTE, "locator": _MDPI_URL}},
    )
    entry = sources[0]
    assert entry["doi"] == _MDPI_DOI
    assert entry["locators"] == [_MDPI_URL, f"https://doi.org/{_MDPI_DOI}"]
    # 无 DOI 候选保持历史形状：没有 doi/locators 新键的强约束。
    plain = extraction_quotable_sources(
        [{**candidate, "metadata": {}}],
        [],
        fetched_text_by_locator={_MDPI_URL: {"text": _QUOTE, "locator": _MDPI_URL}},
    )
    assert plain[0]["locators"] == [_MDPI_URL]
    assert "doi" not in plain[0]


def test_doi_bridged_receipt_feeds_the_verbatim_quote_audit():
    # SCI-021 闭环：候选=mdpi.com URL + doi.org 形态并列，回执=doi.org（其
    # 内容由 EuropePMC 镜像备援取回），quote 从回执文本逐字复制 → 审计通过。
    candidate = {
        "candidateId": "c-mdpi",
        "sourceUrl": _MDPI_URL,
        "title": _MDPI_TITLE,
        "metadata": {"doi": _MDPI_DOI},
    }
    receipt_locator = f"https://doi.org/{_MDPI_DOI}"
    blocks = source_quotable_blocks(
        candidate, {}, fetched_text_by_locator={receipt_locator: {"text": _QUOTE, "locator": receipt_locator}}
    )
    assert blocks, "doi.org receipt must bind the mdpi candidate via metadata.doi"
    entry = {
        "candidateId": "c-mdpi",
        "decision": "keep",
        "claims": [{"fact": "cover crops sequester carbon", "quote": _QUOTE, "sourceRef": receipt_locator}],
    }
    findings = audit_extraction_quote_anchors(
        [entry],
        {"c-mdpi": blocks},
        resolve_source_id=lambda item: str(item.get("candidateId") or ""),
    )
    assert findings == []


def test_end_to_end_mdpi_writeback_completes_through_doi_reroute(tmp_path, monkeypatch):
    """实弹形态复现：mdpi 候选 403 → 读上下文补 DOI → 按 doi.org 抓回 → completed。"""
    setup = _setup_extraction_run(
        tmp_path,
        monkeypatch,
        candidates_spec=[{"title": _MDPI_TITLE, "sourceUrl": _MDPI_URL}],
    )
    _patch_transport(monkeypatch, payload=_openalex_payload(_work(_MDPI_TITLE, _MDPI_DOI)))
    context = _read_context(setup)
    assert context["quotableSources"][0]["locators"][-1] == f"https://doi.org/{_MDPI_DOI}"

    # Agent 按 403 提示改走 DOI 链接（EuropePMC 镜像备援在工具内部生效）。
    doi_link = f"https://doi.org/{_MDPI_DOI}"
    append_conversation_event(
        tmp_path,
        setup["task"]["sessionId"],
        setup["task"]["turn"]["turnId"],
        "tool_result",
        status="done",
        payload={"toolCall": {
            "name": "web_fetch_tool", "status": "done",
            "arguments": {"url": doi_link},
            "result": "[网页内容] " + doi_link + "\n\n" + _QUOTE,
        }},
    )
    candidate = setup["candidates"][0]
    _append_stage_task_tool_trace(tmp_path, setup["task"])
    response = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "1/1 候选经 DOI 改道取得原文。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "evidenceStatus": "evidence_ready",
                        "title": candidate["title"],
                        "source_type": "peer_reviewed_paper",
                        "source_url": _MDPI_URL,
                        "retrieved_at": "2026-10-19T08:00:00Z",
                        "fact": "覆盖作物显著提高土壤有机碳。",
                        "relation": "supports",
                        "verification_status": "metadata_checked",
                        "claims": [
                            {
                                "fact": "覆盖作物显著提高土壤有机碳。",
                                "quote": _QUOTE,
                                "sourceRef": doi_link,
                            }
                        ],
                        "evidenceRefs": [
                            {"id": "quote-mdpi-1", "type": "quote", "quote": _QUOTE}
                        ],
                    }
                ]
            },
        },
    )
    assert response["task"]["status"] == "completed"
    assert response["writeback"]["coverageSummary"]["complete"] is True


# ---------------------------------------------------------------------------
# B 诚实 exclude 收口（门禁核验 + 集成用例）
# ---------------------------------------------------------------------------


def test_quote_anchor_audit_exempts_exclude_entries():
    # 原样成立：decision=exclude 的条目不做 quote 锚校验。
    def _audit(entry):
        return audit_extraction_quote_anchors(
            [entry], {"c-1": []}, resolve_source_id=lambda item: str(item.get("candidateId") or "")
        )

    assert _audit({"candidateId": "c-1", "decision": "exclude", "defects": ["付费墙"]}) == []
    # 对照：同一来源保留 keep 且无诚实声明 → 硬错误。
    findings = _audit({"candidateId": "c-1", "decision": "keep"})
    assert [item["finding"] for item in findings] == ["empty_source"]


def test_honest_exclusion_closes_batch_completed_and_materializes(tmp_path, monkeypatch):
    """1 条 evidence_ready 带逐字 quote + 1 条 exclude 带原因 → 不降级、物化、卡批非空。"""
    wall_title = "Paywalled OUP Paper Behind Login Wall"
    setup = _setup_extraction_run(
        tmp_path,
        monkeypatch,
        candidates_spec=[
            {"title": _MDPI_TITLE, "sourceUrl": _MDPI_URL},
            {"title": wall_title, "sourceUrl": "https://academic.oup.com/paywalled"},
        ],
    )
    # 上下文读时补全只命中 mdpi（OUP 标题反查 miss，fail-open）。
    _patch_transport(monkeypatch, payload=_openalex_payload(_work(_MDPI_TITLE, _MDPI_DOI)))
    context = _read_context(setup)

    quotable = setup["candidates"][0]
    walled = setup["candidates"][1]
    append_conversation_event(
        tmp_path,
        setup["task"]["sessionId"],
        setup["task"]["turn"]["turnId"],
        "tool_result",
        status="done",
        payload={"toolCall": {
            "name": "web_fetch_tool", "status": "done",
            "arguments": {"url": quotable["sourceUrl"]},
            "result": "[网页内容] " + quotable["sourceUrl"] + "\n\n" + _QUOTE,
        }},
    )
    _append_stage_task_tool_trace(tmp_path, setup["task"])

    response = _writeback(
        setup,
        {
            "status": "completed",
            "summary": "1 条取得原文；1 条登录墙诚实剔除。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": quotable["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "evidenceStatus": "evidence_ready",
                        "title": quotable["title"],
                        "source_type": "peer_reviewed_paper",
                        "source_url": quotable["sourceUrl"],
                        "retrieved_at": "2026-10-19T08:00:00Z",
                        "fact": "覆盖作物显著提高土壤有机碳。",
                        "relation": "supports",
                        "verification_status": "metadata_checked",
                        "claims": [
                            {
                                "fact": "覆盖作物显著提高土壤有机碳。",
                                "quote": _QUOTE,
                                "sourceRef": quotable["sourceUrl"],
                            }
                        ],
                        "evidenceRefs": [
                            {"id": "quote-quotable-1", "type": "quote", "quote": _QUOTE}
                        ],
                    },
                    {
                        "candidateId": walled["candidateId"],
                        "status": "excluded",
                        "decision": "exclude",
                        "title": walled["title"],
                        "defects": ["非 OA 论文付费墙，登录后不可得，且非结论必需证据"],
                        "summary": "多轮抓取与镜像备援后仍不可得，诚实剔除。",
                    },
                ]
            },
        },
    )

    # 门禁三点：不拒绝、覆盖完整、不因 exclude 降级。
    assert response["task"]["status"] == "completed", response["writeback"].get("evidenceReviewRequiredReason")
    coverage = response["writeback"]["coverageSummary"]
    assert coverage["complete"] is True
    assert walled["candidateId"] in coverage["processedCandidateIds"]
    assert response["writeback"]["status"] == "completed"

    # exclude 条目不进 missingEvidenceAnchorCount，contentExtraction 标记 excluded。
    store_path = team_workflow_orchestration_service._candidate_store_path(setup["teamId"], setup["runId"])
    store = json.loads(store_path.read_text(encoding="utf-8"))
    stored_by_id = {item["candidateId"]: item for item in store["candidates"]}
    excluded_extraction = stored_by_id[walled["candidateId"]]["metadata"]["contentExtraction"]
    assert excluded_extraction["decision"] == "exclude"
    assert excluded_extraction["evidenceStatus"] == "excluded"

    # 物化执行：reconcile 桥接触发真实 materializer，evidence_card_batch 非空。
    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        setup["task"]["taskId"],
        run_id=setup["runId"],
        session_id=setup["task"]["sessionId"],
        turn_id=setup["task"]["task"]["turn"]["turnId"],
        final_status="completed",
    )
    assert result["taskStatus"] == "completed", result
    assert result["claimMaterialization"]["claimEvidenceCount"] >= 1
    workflow_run_id = result["claimMaterialization"]["workflowRunId"]
    batch = load_scoped_artifact_payload(
        "evidence_card_batch",
        team_id=setup["teamId"],
        authority_run_id=setup["runId"],
        workflow_run_id=workflow_run_id,
    )
    assert batch and batch["cardCount"] >= 1
    # evidence card 的 sourceId 是 claim 的 sourceRef（来源 URL 空间，不是
    # candidateId 空间）：keep 条目的 mdpi 来源在，exclude 的 OUP 来源不在。
    card_sources = {card.get("sourceId") for card in batch["evidenceCards"]}
    assert quotable["sourceUrl"] in card_sources
    assert "https://academic.oup.com/paywalled" not in card_sources
