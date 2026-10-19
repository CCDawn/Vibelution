# -*- coding: utf-8 -*-
"""写回补救契约（writebackRemediationContract）一次性回路回归。

生产实弹（session-20261017-203847-419417）：relations 代理把 ``dprec-*`` 记录 id
当 evidenceRefs 提交，回写被 ``evidence_relation_graph_invalid`` 确定性拒绝；
拒绝信息只有泛化指引（"Read source_collection_context_tool, then repair..."），
代理 11 次重读上下文仍重复同一违规——因为没有任何一方告诉它具体改什么。

回归契约（信息增强，不改拒绝语义）：
- 非法引用拒绝信息在保持历史前缀的前提下，内联允许的 canonical 引用清单、
  本次违规值与违规字段路径；
- 拒绝点把一次性 ``writebackRemediationContract`` upsert 进任务记录并记
  workflow 事件；下一次 ``source_collection_context_tool`` 读取注入
  ``context["writebackRemediation"]``（compact 上下文同样存活）；
- 同类第二次拒绝置 ``exhausted=true``（一次性界），上下文不再注入；
- 缺字段类（relation_missing_fields）与 Challenge v2 证据卡字段类
  （evidence_fields）同样生成结构化契约。

本套件全部走公开写回/上下文行为驱动（不 import 补救模块本身），因此对
pre-fix 代码是红的：旧实现拒绝信息无补救块、任务无契约、上下文无注入。
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
from core.web.services.team_workflow.source_collection import stage_writeback
from tests._support.team_workflow.helpers import (
    _capture_workflow_events,
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_ALLOWED_REFS = ["ce-good-alpha", "ce-good-beta"]
_OFFENDING_REF = "dprec-20261017-419417"


def _start_stage_task(tmp_path, monkeypatch, *, stage_id: str, agent_role: str):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="补救契约回归")
    session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"], title="写回补救契约回归"
    )
    team = team_service.create_team(
        name="写回补救契约回归团队",
        members=[
            {
                "agentId": agent["agentId"],
                "role": agent_role,
                "agentName": "补救契约回归",
            }
        ],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "写回补救契约回归",
            "agentRoles": [agent_role],
            "agentIds": {agent_role: agent["agentId"]},
            "querySeeds": ["writeback remediation contract"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Remediation candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/remediation-{index}",
                "sourceKind": "paper",
                "summary": f"Remediation regression candidate {index} summary.",
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/remediation-{index}",
                },
                "createdByAgent": "remediation-fixture",
            },
        )["candidate"]
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-writeback-remediation",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": stage_id,
            "agentId": agent["agentId"],
            "agentRole": agent_role,
        },
    )
    return {
        "teamId": team["teamId"],
        "runId": run_id,
        "agentId": agent["agentId"],
        "candidates": candidates,
        "task": task,
    }


def _stub_relation_graph(monkeypatch, *, graph: dict) -> None:
    """Point the readback validator at a fixed scoped graph and allowed refs."""
    monkeypatch.setattr(registry, "_load_scoped_relation_graph", lambda **_: graph)
    monkeypatch.setattr(
        registry,
        "load_allowed_evidence_refs",
        lambda **_: list(_ALLOWED_REFS),
    )
    monkeypatch.setattr(
        registry,
        "load_relation_evidence_context",
        lambda **_: [],
    )


def _stub_writeback_acceptance_path(monkeypatch) -> None:
    """Neutralize post-materialization internals to reach the relations wrap point.

    Same stub surface as the pinned rejection test in
    ``test_evidence_relation_feedback``: coverage/materializers/closure/gate are
    not under test here — the rejection wrap and the remediation contract are.
    """
    s = stage_writeback._service()
    monkeypatch.setattr(
        s, "_source_collection_stage_writeback_candidate_coverage", lambda *_a, **_kw: {}
    )
    for name in (
        "sources",
        "content_extraction",
        "quality",
        "candidate_graph",
        "knowledge_ingestion",
    ):
        monkeypatch.setattr(
            s, "_materialize_source_collection_stage_writeback_" + name, lambda *_a, **_kw: {}
        )
    monkeypatch.setattr(
        s,
        "_source_collection_stage_writeback_closure_summary",
        lambda *_a, **_kw: {"artifactComplete": True, "taskChecklistComplete": True},
    )
    monkeypatch.setattr(s, "_source_collection_stage_completion_gate", lambda **_: {"passed": True})


def _valid_graph() -> dict:
    return {
        "nodes": [
            {"candidateId": "cand-a"},
            {"candidateId": "cand-b"},
        ],
        "edges": [
            {
                "sourceCandidateId": "cand-a",
                "targetCandidateId": "cand-b",
                "relation": "supports",
                "evidenceRefs": [_OFFENDING_REF],
            }
        ],
        "evidenceGaps": [{"description": "Independent replication missing"}],
        "counterEvidenceRefs": [
            {"evidenceRef": "ce-good-beta", "claim": "Null result under stricter control"}
        ],
    }


def _invalid_refs_result() -> dict:
    return {
        "candidateRelations": [
            {
                "sourceCandidateId": "cand-a",
                "targetCandidateId": "cand-b",
                "relation": "supports",
                "evidenceRefs": [_OFFENDING_REF, "ce-good-alpha"],
            }
        ],
        "counterEvidenceRefs": [],
    }


def _stored_task(setup) -> dict:
    task, run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], setup["task"]["taskId"]
    )
    assert task is not None and run_id == setup["runId"]
    return task


def _read_context(setup) -> dict:
    return team_workflow_orchestration_service.get_source_collection_stage_task_context(
        setup["teamId"],
        run_id=setup["runId"],
        task_id=setup["task"]["taskId"],
    )


def _reject_relations_writeback(setup, result: dict) -> str:
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError
    ) as excinfo:
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            setup["task"]["taskId"],
            {"status": "completed", "result": result},
        )
    return str(excinfo.value)


def test_non_canonical_ref_rejection_inlines_allowed_refs_and_offending_values(
    tmp_path, monkeypatch
):
    """(a) 非法引用拒绝信息：历史前缀不变 + 允许清单 + 违规值 + 违规路径。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path(monkeypatch)

    message = _reject_relations_writeback(setup, _invalid_refs_result())

    # 历史门禁文案逐字保留（既有测试钉住的前缀与指引）。
    assert message.startswith(
        f"evidence_relation_graph_invalid: evidence relation references must be "
        "canonical claimEvidenceId values"
    )
    assert "Read source_collection_context_tool" in message
    # 追加的确定性补救块：允许清单、违规值、违规字段路径。
    assert "补救提示" in message
    for allowed in _ALLOWED_REFS:
        assert allowed in message
    assert _OFFENDING_REF in message
    assert "candidateRelations[0].evidenceRefs[0]" in message
    # 拒绝本身不改任务状态（拒绝语义未被触碰）。
    assert _stored_task(setup)["status"] == "running"


def test_first_rejection_persists_contract_and_context_injects_remediation(
    tmp_path, monkeypatch
):
    """(b) 拒绝后任务带一次性契约 + workflow 事件，下次上下文可见（compact 存活）。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    events = _capture_workflow_events(monkeypatch)
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path(monkeypatch)

    _reject_relations_writeback(setup, _invalid_refs_result())

    stored = _stored_task(setup)
    contract = stored.get("writebackRemediationContract")
    assert isinstance(contract, dict) and contract
    assert contract["schemaVersion"] == 1
    assert contract["kind"] == "relation_refs"
    assert contract["attempt"] == 1
    assert contract["exhausted"] is False
    assert contract["recordedAt"]
    assert contract["instruction"]
    findings = contract["findings"]
    assert any(
        item.get("finding") == "non_canonical_ref"
        and item.get("path") == "candidateRelations[0].evidenceRefs[0]"
        and item.get("value") == _OFFENDING_REF
        for item in findings
    )
    # 合法引用（ce-good-alpha）不得被误报为违规。
    assert not any(item.get("value") == "ce-good-alpha" for item in findings)
    remediation_events = [
        (args, kwargs)
        for args, kwargs in events
        if len(args) >= 3
        and args[2] == "source_collection.stage_session_task_writeback_remediation_contract"
    ]
    assert remediation_events, "rejection must record a workflow event for the contract"
    assert remediation_events[0][1]["fields"]["kind"] == "relation_refs"
    assert remediation_events[0][1]["fields"]["remediationAttempt"] == 1

    context = _read_context(setup)
    remediation = context.get("writebackRemediation")
    assert isinstance(remediation, dict) and remediation
    assert remediation["kind"] == "relation_refs"
    assert remediation["attempt"] == 1
    assert remediation["exhausted"] is False
    assert any(
        item.get("value") == _OFFENDING_REF for item in remediation["findings"]
    )


def test_second_same_kind_rejection_exhausts_contract_and_stops_injection(
    tmp_path, monkeypatch
):
    """(c) 同类第二次拒绝置 exhausted=true，上下文不再注入 writebackRemediation。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path(monkeypatch)

    _reject_relations_writeback(setup, _invalid_refs_result())
    assert "writebackRemediation" in _read_context(setup)

    second_message = _reject_relations_writeback(setup, _invalid_refs_result())

    # 第二次拒绝文案保持同一历史前缀（无新变体）。
    assert second_message.startswith(
        f"evidence_relation_graph_invalid: evidence relation references must be "
        "canonical claimEvidenceId values"
    )
    stored = _stored_task(setup)
    contract = stored["writebackRemediationContract"]
    assert contract["kind"] == "relation_refs"
    assert contract["attempt"] == 2
    assert contract["exhausted"] is True
    # 一次性界：耗尽后上下文不再注入。
    assert "writebackRemediation" not in _read_context(setup)


def test_missing_required_graph_fields_generate_missing_fields_contract(
    tmp_path, monkeypatch
):
    """(d1) 缺必需集合类：kind=relation_missing_fields，findings 带集合名。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    graph = _valid_graph()
    graph["evidenceGaps"] = []
    _stub_relation_graph(monkeypatch, graph=graph)
    _stub_writeback_acceptance_path(monkeypatch)

    message = _reject_relations_writeback(setup, _invalid_refs_result())

    assert message.startswith(
        "evidence_relation_graph_invalid: evidence_relation_graph missing required fields:"
    )
    assert "补救提示" in message
    assert "evidenceGaps" in message
    contract = _stored_task(setup)["writebackRemediationContract"]
    assert contract["kind"] == "relation_missing_fields"
    assert contract["attempt"] == 1
    assert contract["exhausted"] is False
    assert "evidenceGaps" in str(contract["findings"])
    context = _read_context(setup)
    assert context["writebackRemediation"]["kind"] == "relation_missing_fields"


def test_evidence_card_contract_rejection_generates_evidence_fields_contract(
    tmp_path, monkeypatch
):
    """(d2) Challenge v2 证据卡字段类：kind=evidence_fields，findings 带字段路径。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="extraction", agent_role="source_extractor"
    )
    # 走到证据卡契约门：quote 锚审计不在本用例范围，中性化之。
    monkeypatch.setattr(
        stage_writeback,
        "_source_collection_stage_writeback_quote_anchor_audit",
        lambda *_a, **_kw: {"hard_errors": [], "mismatches": [], "blocks_by_id": {}},
    )

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="Challenge v2 证据卡契约校验失败",
    ) as excinfo:
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            setup["task"]["taskId"],
            {
                "status": "completed",
                "result": {
                    # 可物化条目缺显式 title：契约门以路径化错误拒绝。
                    "candidateExtractions": [
                        {
                            "candidateId": setup["candidates"][0]["candidateId"],
                            "evidenceStatus": "verified_abstract",
                            "sourceUrl": "https://example.org/remediation-paper",
                            "relation": "supports",
                        }
                    ]
                },
            },
        )
    assert "candidateExtractions[0] is missing explicit title" in str(excinfo.value)

    contract = _stored_task(setup)["writebackRemediationContract"]
    assert contract["schemaVersion"] == 1
    assert contract["kind"] == "evidence_fields"
    assert contract["attempt"] == 1
    assert contract["exhausted"] is False
    findings = contract["findings"]
    assert findings
    assert any(
        item.get("finding") == "evidence_field_contract_violation"
        and "candidateExtractions[0]" in item.get("path", "")
        for item in findings
    )
    context = _read_context(setup)
    assert context["writebackRemediation"]["kind"] == "evidence_fields"


def _stub_writeback_acceptance_path_keep_graph(monkeypatch) -> None:
    """同 ``_stub_writeback_acceptance_path``，但保留 candidate_graph 物化器。

    形状拒绝发生在 agent-graph payload 解析处（先于 ``build_candidate_graph``
    与 closure/gate），因此真实物化器在本用例中必然走拒绝分支而不是落库。
    """
    s = stage_writeback._service()
    monkeypatch.setattr(
        s, "_source_collection_stage_writeback_candidate_coverage", lambda *_a, **_kw: {}
    )
    for name in (
        "sources",
        "content_extraction",
        "quality",
        "knowledge_ingestion",
    ):
        monkeypatch.setattr(
            s, "_materialize_source_collection_stage_writeback_" + name, lambda *_a, **_kw: {}
        )


def _shape_invalid_result() -> dict:
    # 形状类违规：agent 把图集合写成标量（summary counts 混入 graph 集合）。
    return {
        "candidateGraph": {
            "nodes": [{"candidateId": "cand-a"}],
            "edges": 5,
        }
    }


_SHAPE_REJECTION_PREFIX = (
    "evidence_relation_graph_invalid: result_json.candidateGraph.edges "
    "must be an array of objects; received int."
)


def test_shape_invalid_agent_graph_rejection_inlines_remediation(
    tmp_path, monkeypatch
):
    """(e1) 形状拒绝（edges 非对象数组）：历史前缀不变 + 内联清单 + 契约注入。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path_keep_graph(monkeypatch)

    message = _reject_relations_writeback(setup, _shape_invalid_result())

    # 形状守卫的历史拒绝前缀逐字保留（prompt contracts 测试钉住的文案）。
    assert message.startswith(_SHAPE_REJECTION_PREFIX)
    # 追加的确定性补救块：允许清单 + writebackRemediation 提示。
    assert "补救提示" in message
    for allowed in _ALLOWED_REFS:
        assert allowed in message
    assert "writebackRemediation" in message
    # 拒绝本身不改任务状态。
    assert _stored_task(setup)["status"] == "running"
    contract = _stored_task(setup)["writebackRemediationContract"]
    assert contract["kind"] == "relation_missing_fields"
    assert contract["attempt"] == 1
    assert contract["exhausted"] is False
    assert any(
        item.get("finding") == "malformed_collection"
        and item.get("path") == "candidateGraph.edges"
        for item in contract["findings"]
    )
    context = _read_context(setup)
    assert context["writebackRemediation"]["kind"] == "relation_missing_fields"


def test_second_shape_rejection_exhausts_contract_and_stops_injection(
    tmp_path, monkeypatch
):
    """(e2) 形状类同类第二次拒绝置 exhausted=true，上下文不再注入。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path_keep_graph(monkeypatch)

    _reject_relations_writeback(setup, _shape_invalid_result())
    assert "writebackRemediation" in _read_context(setup)

    second_message = _reject_relations_writeback(setup, _shape_invalid_result())

    assert second_message.startswith(_SHAPE_REJECTION_PREFIX)
    stored = _stored_task(setup)
    contract = stored["writebackRemediationContract"]
    assert contract["kind"] == "relation_missing_fields"
    assert contract["attempt"] == 2
    assert contract["exhausted"] is True
    assert "writebackRemediation" not in _read_context(setup)


def test_shape_rejection_hint_points_to_full_list_and_pairs_candidates(
    tmp_path, monkeypatch
):
    """(e3) 清单超 12 个截断时带全量指引句；内联 ref 配对 candidateId。"""
    setup = _start_stage_task(
        tmp_path, monkeypatch, stage_id="relations", agent_role="source_relation_mapper"
    )
    _stub_relation_graph(monkeypatch, graph=_valid_graph())
    _stub_writeback_acceptance_path_keep_graph(monkeypatch)
    many_refs = [f"ce-shape-{index:02d}" for index in range(1, 14)]
    monkeypatch.setattr(registry, "load_allowed_evidence_refs", lambda **_: list(many_refs))
    monkeypatch.setattr(
        registry,
        "load_relation_evidence_context",
        lambda **_: [
            {"claimEvidenceId": "ce-shape-01", "candidateId": "cand-shape-01"},
        ],
    )

    message = _reject_relations_writeback(setup, _shape_invalid_result())

    assert "共 13 个，仅展示前 12 个" in message
    assert (
        "全量清单见 source_collection_context_tool 的 allowedEvidenceRefs / relationEvidence"
        in message
    )
    # 可选增强：内联 ref 带 candidateId 配对，未配对的 ref 保持原样；
    # 第 13 个被截断，不出现在消息里。
    assert "ce-shape-01(cand-shape-01)" in message
    assert "ce-shape-12" in message
    assert "ce-shape-13" not in message
