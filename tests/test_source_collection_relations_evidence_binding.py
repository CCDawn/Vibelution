# -*- coding: utf-8 -*-
"""relations 上下文证据绑定图必须全量供给，不得被候选分页截断。

生产实锤（session-20261017-201057-238483，2026-10-17 e2e）：knowledge-sideflow
子 run 的 evidence_relations 阶段任务被代理诚实 blocked。turn journal seq 8 的
context 工具返回里 ``allowedEvidenceRefs=["ce-5974e2e05d6c4eb6fa3d"]``（全局权威）
而 ``relationEvidence=[]``——stage_writeback.py 的 relations 分支把绑定卡按
「当前分页候选」过滤，该 ce-* 绑定的候选不在当前页，绑定卡整页丢失，agent
无法把唯一的 canonical 证据绑定到任何候选，无法构造任何合法边，只能 blocked。

回归契约：
- 有绑定卡的候选不在当前分页时，``relationEvidence[]`` 仍必须包含其绑定卡
  （全量绑定图），仅以 ``inCurrentPage=false`` 标注页外；
- ``allowedEvidenceRefs`` 非空时绑定映射必须非空；
- 页内候选的绑定卡全部保留且 ``inCurrentPage=true``；
- 指令文本不得再宣称「relationEvidence 为空即证据缺失」误导页外绑定。
"""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.research_runtime import (
    artifact_readback_registry as registry,
)
from tests._support.team_workflow.helpers import (
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_CANDIDATE_COUNT = 3


def _setup_relations_run(tmp_path, monkeypatch):
    """Open one relations stage task over a multi-candidate run."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="证据关系")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="证据关系")
    team = team_service.create_team(
        name="证据绑定回归团队",
        members=[
            {"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "证据关系"}
        ],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "跨候选证据绑定回归",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["relation evidence binding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Relation binding candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/relation-binding-{index}",
                "sourceKind": "paper",
                "summary": f"Predictive coding binding candidate {index} summary.",
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/relation-binding-{index}",
                },
                "createdByAgent": "relation-binding-fixture",
            },
        )["candidate"]
        for index in range(1, _CANDIDATE_COUNT + 1)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-relation-binding",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "relations",
            "agentId": agent["agentId"],
            "agentRole": "source_relation_mapper",
        },
    )
    return {
        "teamId": team["teamId"],
        "runId": run_id,
        "candidates": candidates,
        "task": task,
    }


def _read_context(setup, **overrides) -> dict:
    return team_workflow_orchestration_service.get_source_collection_stage_task_context(
        setup["teamId"],
        run_id=setup["runId"],
        task_id=setup["task"]["taskId"],
        **overrides,
    )


def _stub_evidence(monkeypatch, cards):
    monkeypatch.setattr(
        registry,
        "load_relation_evidence_context",
        lambda **kwargs: [dict(card) for card in cards],
    )
    monkeypatch.setattr(
        registry,
        "load_allowed_evidence_refs",
        lambda **kwargs: sorted(
            card["claimEvidenceId"] for card in cards if card.get("claimEvidenceId")
        ),
    )


def _card(evidence_id: str, candidate_id: str) -> dict:
    return {
        "claimEvidenceId": evidence_id,
        "claimId": f"claim-{evidence_id}",
        "candidateId": candidate_id,
        "sourceId": candidate_id,
        "quote": f"{evidence_id} observed result",
        "supportLevel": "supports",
    }


def test_offpage_binding_cards_survive_candidate_paging(tmp_path, monkeypatch):
    """页外候选的绑定卡必须保留并标注 inCurrentPage=false，页内卡仍全量在。"""
    setup = _setup_relations_run(tmp_path, monkeypatch)
    # Discover which candidate lands on the first page under a one-slot page.
    paged = _read_context(setup, candidate_limit=1)
    assert len(paged["candidates"]) == 1
    page_candidate_id = paged["candidates"][0]["candidateId"]
    all_candidate_ids = {item["candidateId"] for item in setup["candidates"]}
    assert len(all_candidate_ids) == _CANDIDATE_COUNT
    offpage_candidate_id = next(
        item["candidateId"]
        for item in setup["candidates"]
        if item["candidateId"] != page_candidate_id
    )

    _stub_evidence(
        monkeypatch,
        [
            _card("ce-page", page_candidate_id),
            _card("ce-offpage", offpage_candidate_id),
        ],
    )
    context = _read_context(setup, candidate_limit=1)

    assert context["allowedEvidenceRefs"] == ["ce-offpage", "ce-page"]
    bindings = {item["claimEvidenceId"]: item for item in context["relationEvidence"]}
    # 旧实现在这里丢掉 ce-offpage（候选不在当前页 → 整卡被过滤）。
    assert set(bindings) == {"ce-page", "ce-offpage"}
    assert bindings["ce-page"]["inCurrentPage"] is True
    assert bindings["ce-page"]["candidateId"] == page_candidate_id
    assert bindings["ce-offpage"]["inCurrentPage"] is False
    assert bindings["ce-offpage"]["candidateId"] == offpage_candidate_id
    assert bindings["ce-offpage"]["quote"] == "ce-offpage observed result"
    # 指令必须告知全量绑定语义，不得再诱导「空列表即证据缺失」的页外误报。
    instruction = context["usage"]["evidenceInstruction"]
    assert "全量" in instruction
    assert "不因分页截断" in instruction
    assert "该列表为空时请报告证据缺失" not in instruction


def test_single_offpage_binding_still_supplied(tmp_path, monkeypatch):
    """事故重放：唯一的 ce-* 绑定在页外候选上，绑定映射仍必须非空。"""
    setup = _setup_relations_run(tmp_path, monkeypatch)
    paged = _read_context(setup, candidate_limit=1)
    page_candidate_id = paged["candidates"][0]["candidateId"]
    offpage_candidate_id = next(
        item["candidateId"]
        for item in setup["candidates"]
        if item["candidateId"] != page_candidate_id
    )

    _stub_evidence(monkeypatch, [_card("ce-5974e2e05d6c4eb6fa3d", offpage_candidate_id)])
    context = _read_context(setup, candidate_limit=1)

    assert context["allowedEvidenceRefs"] == ["ce-5974e2e05d6c4eb6fa3d"]
    # 旧实现：relationEvidence == [] → agent 无法绑定任何候选 → blocked。
    assert len(context["relationEvidence"]) == 1
    binding = context["relationEvidence"][0]
    assert binding["candidateId"] == offpage_candidate_id
    assert binding["inCurrentPage"] is False
    assert binding["claimEvidenceId"] in context["allowedEvidenceRefs"]
