# -*- coding: utf-8 -*-
"""Session 路径 extraction stage task 终结后的 claim 物化桥接与 quote 契约。

缺陷 #10：graph dispatch 路径在 turn 终结时物化 claim evidence
（agent_turn_completion），但经 POST /source-collection-runs/{run}/stage-session-tasks
创建的 stage task 走 session 消息路径，终结对账从不物化，completed 任务
在 claim_ledger.jsonl 中始终为 0。本文件锁定 reconcile 处的桥接契约：

1. canonical 终态为 completed 的 extraction 任务必须触发物化，且参数
   （team/workflow/source-run/task）取自对账后的 canonical 任务；
2. stageId 非 extraction 或终态非 completed 一律不调物化（终态以对账后
   状态为准，不看请求参数）；
3. 物化失败只留诊断事件，不得翻转任务状态或阻塞 reconcile 返回。

生产实锤（run dprun-20260831142015208397-93ca7108）追加的回写 quote 契约：
completed 提炼回写若不带逐字 quote 锚（verification_status 键跑偏、
evidenceRefs 无 quote），物化静默为 0。锁定：

4. 正式 claim 路径的 completed 回写缺逐字 quote 锚或 quote 非存储 summary
   逐字子串 → 服务端按校验错误拒绝回写；
5. verification_status 作为 evidenceStatus 别名键按值正确归一分流；
6. 存储 summary 为空的候选必须声明 missing_evidence_anchor 诚实跳过；
7. completed 任务物化出 0 条 claim 但 run 存在带摘要候选 → 停靠
   needs_review 并给 remediation（不自动重开）；全空摘要诚实跳过 → 正常
   completed。

生产实锤（run SCI-091，2026-09-01 source_extraction 被 fail-closed 证据契约
拒绝）追加的 retrieved_at 兜底契约：

8. 提炼回写条目缺 retrieved_at（或值不带时区）→ 服务端在回写边界用真实
   链上时间（record/candidate 的 createdAt，最后兜底当前回写时间）补齐；
   agent 显式写的合规值（含 retrievedAt 别名）不覆盖；canonical result
   必须直接通过 build_source_extraction_evidence_cards 契约。
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
    agent_claim_evidence_materializer,
)
from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
    EvidenceMaterializationError,
)
from core.web.services.team_workflow.source_collection.stage_writeback import (
    _materialize_extraction_claim_evidence_after_reconcile,
)
from tests._support.team_workflow.helpers import (
    _append_stage_task_tool_trace,
    _capture_workflow_events,
    _seed_source_collection_raw_records,
    _start_source_collection_run_with_problem_understanding,
    _use_fake_local_research_config,
    _use_tmp_project_root,
    _workflow_scene_events_by_code,
)


def _forbid_materialize(**_kwargs):
    raise AssertionError("materialize_completed_extraction_task must not be called")


def _seed_completed_extraction_task(tmp_path, monkeypatch):
    """Open one extraction stage task through the session path and complete it."""
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
    workflow_run_id = str(run_response["run"].get("scope", {}).get("workflowRunId") or "")
    assert workflow_run_id
    _seed_source_collection_raw_records(run_id)
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding extraction candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/extraction-coverage-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for content extraction coverage.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/extraction-coverage-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index in range(3)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-session-path-extraction",
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
        "workflowRunId": workflow_run_id,
        "candidates": candidates,
        "task": task,
    }


def _anchored_extraction_entry(candidate, *, index: int = 1) -> dict:
    """Contract-shaped extraction entry: verbatim quote anchor from the stored summary."""
    return {
        "candidateId": candidate["candidateId"],
        "status": "extracted",
        "decision": "keep",
        "evidenceStatus": "verified_abstract",
        "title": candidate["title"],
        "source_type": "preprint",
        "source_url": candidate["sourceUrl"],
        "retrieved_at": "2026-08-31T14:28:07Z",
        "fact": f"{candidate['title']} 的摘要支持内容提炼结论。",
        "relation": "supports",
        "verification_status": "metadata_checked",
        "evidenceRefs": [
            {
                "id": f"abstract-quote-{index}",
                "type": "quote",
                "quote": "Predictive coding evidence",
            }
        ],
    }


def test_reconcile_completed_extraction_task_materializes_claim_evidence(tmp_path, monkeypatch):
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼。",
            "result": {
                "candidateExtractions": [
                    _anchored_extraction_entry(item, index=index)
                    for index, item in enumerate(setup["candidates"], start=1)
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    captured = {}

    def fake_materialize(**kwargs):
        captured.update(kwargs)
        return [{"claimEvidenceId": "ce-1"}, {"claimEvidenceId": "ce-2"}]

    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        fake_materialize,
    )

    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )

    assert result["status"] == "reconciled"
    assert result["taskStatus"] == "completed"
    assert captured == {
        "team_id": setup["teamId"],
        "workflow_run_id": setup["workflowRunId"],
        "source_collection_run_id": setup["runId"],
        "task_id": task["taskId"],
    }
    assert result["claimMaterialization"] == {
        "status": "materialized",
        "workflowRunId": setup["workflowRunId"],
        "claimEvidenceCount": 2,
    }


def test_reconcile_does_not_materialize_before_canonical_completion(tmp_path, monkeypatch):
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        _forbid_materialize,
    )

    # final_status 是请求参数；canonical 任务仍未写回 completed，不得物化。
    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )

    assert result["status"] == "reconciled"
    assert result["taskStatus"] != "completed"
    assert result["claimMaterialization"] == {
        "status": "skipped",
        "reason": "not_completed_extraction_task",
    }


def test_materialization_gate_skips_non_extraction_stage(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        _forbid_materialize,
    )

    assert _materialize_extraction_claim_evidence_after_reconcile(
        "team-a",
        "run-a",
        {"taskId": "task-a", "stageId": "relations", "status": "completed"},
    ) == {"status": "skipped", "reason": "not_completed_extraction_task"}
    assert _materialize_extraction_claim_evidence_after_reconcile(
        "team-a",
        "run-a",
        {"taskId": "task-a", "stageId": "extraction", "status": "needs_review"},
    ) == {"status": "skipped", "reason": "not_completed_extraction_task"}


def test_reconcile_returns_normally_when_materialization_fails(tmp_path, monkeypatch):
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼。",
            "result": {
                "candidateExtractions": [
                    _anchored_extraction_entry(item, index=index)
                    for index, item in enumerate(setup["candidates"], start=1)
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    events = _capture_workflow_events(monkeypatch)

    def failing_materialize(**_kwargs):
        raise EvidenceMaterializationError(
            "formal workflow run does not carry a question; claims cannot be "
            "proposed in the question-scoped claim ledger"
        )

    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        failing_materialize,
    )

    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )

    assert result["status"] == "reconciled"
    assert result["taskStatus"] == "completed"
    assert result["claimMaterialization"]["status"] == "failed"
    assert result["claimMaterialization"]["errorType"] == "EvidenceMaterializationError"
    assert result["claimMaterialization"]["workflowRunId"] == setup["workflowRunId"]
    failures = _workflow_scene_events_by_code(
        events,
        "source_collection.stage_session_task_claim_materialization_failed",
    )
    assert len(failures) == 1
    assert failures[0]["fields"]["teamId"] == setup["teamId"]
    assert failures[0]["fields"]["taskId"] == task["taskId"]
    assert failures[0]["fields"]["errorType"] == "EvidenceMaterializationError"
    assert "question" in failures[0]["fields"]["error"]


# ---------------------------------------------------------------------------
# 回写 quote 契约（生产实锤 dprun-20260831142015208397-93ca7108）
# ---------------------------------------------------------------------------

_CANDIDATE_SUMMARY_QUOTE = "Predictive coding evidence"


def _incident_extraction_entry(candidate) -> dict:
    """今晚实锤的条目 schema：键名跑偏 + evidenceRefs 只有 {locator, sourceRef, type}。"""
    return {
        "candidateId": candidate["candidateId"],
        "decision": "keep",
        "title": candidate["title"],
        "source_type": "preprint",
        "source_url": candidate["sourceUrl"],
        "retrieved_at": "2026-08-31T14:28:07Z",
        "fact": "Predictive coding evidence for content extraction coverage.",
        "relation": "supports",
        "verification_status": "missing_evidence_anchor",
        "valueSummary": "摘要支持预测编码结论。",
        "evidenceRefs": [
            {
                "locator": "abstract",
                "sourceRef": candidate["sourceUrl"],
                "type": "abstract",
            }
        ],
    }


def test_completed_extraction_writeback_without_quote_anchor_is_rejected(tmp_path, monkeypatch):
    """实锤复现：非空 summary 的候选 completed 回写无逐字 quote 锚 → 拒绝。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="quote",
    ) as excinfo:
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            task["taskId"],
            {
                "status": "completed",
                "summary": "完成资料提炼。",
                "result": {
                    "candidateExtractions": [
                        _incident_extraction_entry(setup["candidates"][0])
                    ]
                },
                "recordedByAgent": task["task"]["agentId"],
            },
        )
    # 诊断信息必须点名缺失的逐字 quote 锚与逐字复制要求。
    assert "逐字" in str(excinfo.value)

    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    assert stored_task["status"] != "completed"


def test_completed_extraction_writeback_rejects_paraphrased_quote(tmp_path, monkeypatch):
    """quote 不是存储 summary 的逐字子串 → 拒绝。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entry = _anchored_extraction_entry(setup["candidates"][0])
    entry["evidenceRefs"][0]["quote"] = "预测编码证据支持内容提炼覆盖。"

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="逐字子串",
    ):
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            task["taskId"],
            {
                "status": "completed",
                "summary": "完成资料提炼。",
                "result": {"candidateExtractions": [entry]},
                "recordedByAgent": task["task"]["agentId"],
            },
        )


def test_verification_status_alias_routes_by_value(tmp_path, monkeypatch):
    """verification_status 别名按值分流：枚举内归一为 evidenceStatus，枚举外保持卡元数据。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    # 枚举内别名值（missing_evidence_anchor）+ 逐字 quote 锚 → 归一为
    # evidenceStatus 后回写被接受，canonical result 携带归一键。
    alias_entry = _incident_extraction_entry(setup["candidates"][0])
    alias_entry["evidenceRefs"] = [
        {"id": "abstract-quote-1", "type": "quote", "quote": _CANDIDATE_SUMMARY_QUOTE}
    ]

    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 1/3 条候选资料提炼（其余见后续批次）。",
            "result": {"candidateExtractions": [alias_entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] in {"completed", "needs_review"}
    stored_entry = complete["task"]["result"]["candidateExtractions"][0]
    assert stored_entry["evidenceStatus"] == "missing_evidence_anchor"

    # 枚举外别名值（Challenge v2 卡元数据 metadata_checked）不得被当作 evidenceStatus。
    metadata_entry = _anchored_extraction_entry(setup["candidates"][1])
    metadata_entry.pop("evidenceStatus")
    metadata_entry["verification_status"] = "metadata_checked"
    second = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "needs_review",
            "summary": "继续补齐剩余候选提炼。",
            "result": {"candidateExtractions": [metadata_entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    second_entry = second["task"]["result"]["candidateExtractions"][-1]
    assert not second_entry.get("evidenceStatus")
    assert second_entry["verification_status"] == "metadata_checked"


# ---------------------------------------------------------------------------
# Challenge v2 retrieved_at 回写兜底（生产实锤 SCI-091）
# ---------------------------------------------------------------------------


def _untimestamped_extraction_entry(candidate) -> dict:
    """SCI-091 实锤形状：契约字段齐全但缺 retrieved_at（带逐字 quote 锚）。"""
    entry = _anchored_extraction_entry(candidate)
    entry.pop("retrieved_at")
    # 引用锚带 sourceRef，满足 Challenge v2 卡的 citationLocator 要求。
    entry["evidenceRefs"][0]["sourceRef"] = candidate["sourceUrl"]
    return entry


def test_completed_extraction_writeback_backfills_missing_retrieved_at(tmp_path, monkeypatch):
    """SCI-091 复现：回写缺 retrieved_at → 服务端按候选真实时间兜底，产物过契约。"""
    from datetime import datetime

    from core.web.services.team_workflow.research_runtime.source_extraction_evidence_cards import (
        build_source_extraction_evidence_cards,
    )

    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼（条目省略 retrieved_at）。",
            "result": {
                "candidateExtractions": [
                    _untimestamped_extraction_entry(item)
                    for item in setup["candidates"]
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] in {"completed", "needs_review"}

    created_by_id = {
        item["candidateId"]: item["createdAt"] for item in setup["candidates"]
    }
    stored_entries = complete["task"]["result"]["candidateExtractions"]
    assert len(stored_entries) == 3
    for entry in stored_entries:
        backfilled = entry["retrieved_at"]
        # 兜底值 = 该候选被检索注册的真实时间，且满足 RFC3339 带时区。
        assert backfilled == created_by_id[entry["candidateId"]]
        parsed = datetime.fromisoformat(backfilled.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    # writer 产物（canonical task result）必须直接通过 fail-closed 契约校验器。
    cards = build_source_extraction_evidence_cards(complete["task"]["result"])
    assert len(cards) == 3
    assert all(card["retrieved_at"] for card in cards)


def test_backfill_preserves_explicit_retrieved_at_alias(tmp_path, monkeypatch):
    """agent 已显式写 retrievedAt 别名 → 兜底不得覆盖。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entry = _untimestamped_extraction_entry(setup["candidates"][0])
    entry["retrievedAt"] = "2026-08-31T14:28:07+08:00"
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 1/3 条候选资料提炼（其余见后续批次）。",
            "result": {"candidateExtractions": [entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    stored_entry = complete["task"]["result"]["candidateExtractions"][0]
    assert stored_entry["retrievedAt"] == "2026-08-31T14:28:07+08:00"
    assert "retrieved_at" not in stored_entry


def test_backfill_replaces_malformed_retrieved_at(tmp_path, monkeypatch):
    """agent 写了不带时区的伪时间戳 → 兜底替换为真实链上时间，不再卡契约。"""
    from datetime import datetime

    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entry = _untimestamped_extraction_entry(setup["candidates"][0])
    entry["retrieved_at"] = "2026-08-31 14:28:07"
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 1/3 条候选资料提炼（其余见后续批次）。",
            "result": {"candidateExtractions": [entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    stored_entry = complete["task"]["result"]["candidateExtractions"][0]
    backfilled = stored_entry["retrieved_at"]
    assert backfilled != "2026-08-31 14:28:07"
    assert backfilled == setup["candidates"][0]["createdAt"]
    parsed = datetime.fromisoformat(backfilled.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def _seed_empty_summary_candidate_run(tmp_path, monkeypatch):
    """只注册一个空 summary 候选的运行：诚实跳过不应被 quote 锚校验卡死。"""
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
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding extraction candidate empty summary",
            "sourceUrl": "https://doi.org/10.0000/extraction-empty-summary",
            "sourceKind": "paper",
            "summary": "",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-empty-summary-extraction",
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
        "candidates": [candidate],
        "task": task,
    }


def test_empty_summary_candidate_with_missing_anchor_honestly_skips(tmp_path, monkeypatch):
    """空 summary 候选 + missing_evidence_anchor → 诚实跳过，正常 completed。"""
    setup = _seed_empty_summary_candidate_run(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "唯一候选无存储摘要，诚实声明缺证据锚。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": setup["candidates"][0]["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "evidenceStatus": "missing_evidence_anchor",
                        "valueSummary": "仅元数据可用，无摘要可逐字引用。",
                    }
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        lambda **_kwargs: [],
    )
    # 完成 gate 不停靠：run 内没有带摘要候选，0 物化属正常诚实跳过。
    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )
    assert result["taskStatus"] == "completed"
    assert result["claimMaterialization"]["status"] == "materialized"
    assert result["claimMaterialization"]["claimEvidenceCount"] == 0


def test_zero_claim_materialization_parks_completed_extraction_task(tmp_path, monkeypatch):
    """完成门 fail-loud：completed + 0 物化 claim + run 存在带摘要候选 → 停靠 needs_review。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼。",
            "result": {
                "candidateExtractions": [
                    _anchored_extraction_entry(item, index=index)
                    for index, item in enumerate(setup["candidates"], start=1)
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    events = _capture_workflow_events(monkeypatch)
    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "materialize_completed_extraction_task",
        lambda **_kwargs: [],
    )

    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )

    assert result["status"] == "reconciled"
    assert result["taskStatus"] == "needs_review"

    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    # 物化结果必须落在 canonical task 上，而不是只活在 reconcile 响应里。
    assert stored_task["claimMaterialization"]["status"] == "materialized"
    assert stored_task["claimMaterialization"]["claimEvidenceCount"] == 0
    assert stored_task["claimMaterialization"]["gate"] == "needs_quote_anchor_retry"
    assert "逐字" in stored_task["claimMaterialization"]["remediation"]
    assert stored_task["result"]["claimMaterializationRemediation"]
    assert stored_task["writeback"]["agentRequestedStatus"] == "needs_review"

    failures = _workflow_scene_events_by_code(
        events,
        "source_collection.stage_session_task_claim_materialization_gate_parked",
    )
    assert len(failures) == 1
    assert failures[0]["fields"]["previousStatus"] == "completed"
    assert failures[0]["fields"]["status"] == "needs_review"

    # 停靠态不被自动重开：再次 reconcile 保持 needs_review，不翻转回 completed。
    replay = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )
    assert replay["taskStatus"] == "needs_review"


def test_verbatim_quote_writeback_materializes_ledger_row_and_gate_allows(tmp_path, monkeypatch):
    """合法回写 → 真实物化 ledger 行 + 证据记录 + 完成 gate 放行（t51 断言风格）。"""
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    monkeypatch.setattr(claim_ledger, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path, raising=False)
    scope = chain._question_scope_envelope(setup["teamId"], "SCI-096")
    monkeypatch.setattr(
        agent_claim_evidence_materializer,
        "_formal_question_scope",
        lambda team_id, workflow_run_id: scope,
    )
    real_get_agent = agent_directory_service.get_agent

    def fake_get_agent(agent_id, **kwargs):
        agent = dict(real_get_agent(agent_id, **kwargs) or {})
        bindings = dict(agent.get("llmBindings") or {})
        bindings.setdefault("dialogue", {"modelId": "local/qwen3.5-9b"})
        agent["llmBindings"] = bindings
        return agent

    monkeypatch.setattr(agent_directory_service, "get_agent", fake_get_agent)

    entry = _anchored_extraction_entry(setup["candidates"][0])
    # 三条候选全覆盖（覆盖度完整才会保持 completed），共享同一 fact：
    # ledger 幂合为一行，证据按 candidateId 各挂一条。
    shared_fact = entry["fact"]
    entries = []
    for index, item in enumerate(setup["candidates"], start=1):
        next_entry = _anchored_extraction_entry(item, index=index)
        next_entry["fact"] = shared_fact
        entries.append(next_entry)
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼。",
            "result": {"candidateExtractions": entries},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )

    assert result["claimMaterialization"]["status"] == "materialized"
    assert result["claimMaterialization"]["claimEvidenceCount"] == 3

    # 1. claim ledger 出现真实行，claim 内容即条目 fact；幂合一行。
    listing = claim_ledger.list_claims(setup["teamId"])
    assert listing["claimCount"] == 1
    assert listing["claims"][0]["claim"] == shared_fact

    # 2. ClaimEvidenceStore 记录带逐字 quote 与 run 联结。
    stored = ClaimEvidenceStore(tmp_path).list(setup["teamId"])
    assert len(stored) == 3
    assert all(item["quote"] == _CANDIDATE_SUMMARY_QUOTE for item in stored)
    assert all(item["sourceCollectionRunId"] == setup["runId"] for item in stored)

    # 3. gate 放行：canonical task 保持终态且物化结果可见。
    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    assert stored_task["status"] != "needs_review"
    assert stored_task["claimMaterialization"]["claimEvidenceCount"] == 3
