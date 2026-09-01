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

生产实锤（run-882610596ddb，RETRY_NODE 重放直通 materialize）追加的叠加
缺口契约：

9. 兜底扩展到嵌套 claims/keyFindings 级（materializable claim 继承所属
   父项同源时间，显式合规 claim 值不覆盖）；且 node retry 重放历史持久化
   result 不经回写边界时，materialize 读点用同一权威 backfill 先修复再过
   契约——读点只修消费侧，不回写 canonical 存储。
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
    """quote 不是存储 summary 的逐字子串 → 首次停靠 needs_review 给修正反馈，二次拒绝。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entry = _anchored_extraction_entry(setup["candidates"][0])
    entry["evidenceRefs"][0]["quote"] = "预测编码证据支持内容提炼覆盖。"

    # 一次性修正反馈：首个只含"quote 不匹配"的 completed 回写不拒绝，
    # 停靠 needs_review 并携带结构化 quoteAnchorRemediation。
    parked = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成资料提炼（quote 首次不匹配）。",
            "result": {"candidateExtractions": [entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert parked["task"]["status"] == "needs_review"
    assert parked["writeback"]["status"] == "needs_review"
    assert parked["writeback"]["agentRequestedStatus"] == "completed"
    remediation = parked["writeback"]["quoteAnchorRemediation"]
    assert remediation["attempt"] == 1
    assert remediation["findings"][0]["sourceId"] == setup["candidates"][0]["candidateId"]
    assert remediation["findings"][0]["finding"] == "mismatched_quote"
    assert remediation["findings"][0]["nearestMatch"]["snippet"]

    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    assert stored_task["status"] == "needs_review"
    assert stored_task["quoteAnchorRemediation"]["attempt"] == 1
    # 停靠路径不落 agent 原始 result：改写 quote 不得泄漏进 canonical 存储。
    assert not stored_task.get("result")

    # 修正机会只有一次：再次不匹配走既有契约拒绝语义。
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="逐字子串",
    ):
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            task["taskId"],
            {
                "status": "completed",
                "summary": "完成资料提炼（quote 二次不匹配）。",
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


# ---------------------------------------------------------------------------
# Challenge v2 证据卡契约回写门（生产实锤 run-882610596ddb / N3）——叠加语义
#
# 两层防线（f8d5d08e2 兜底在前，本门在后，不是二选一）：
# 1. 服务端兜底先消灭「模型遗漏 retrieved_at」主流失败（真实链上时间补齐）；
# 2. 兜底补齐之后仍违反 Challenge v2 卡契约的（其他必填缺失、结构违约），
#    在写回接受边界用与 materialize 相同的校验器（_materializable_claims +
#    normalize_challenge_evidence_fields，禁止第二套规则）结构化拒绝并带
#    精确 path，agent 同任务补正；completionGate 不得在违约数据上 passed。
# ---------------------------------------------------------------------------


def _missing_retrieved_at_entry(candidate, *, index: int = 1) -> dict:
    """run-882610596ddb 的条目形态：quote 锚齐全但系统性缺 retrieved_at。"""
    entry = _anchored_extraction_entry(candidate, index=index)
    entry.pop("retrieved_at")
    return entry


def test_missing_retrieved_at_backfilled_then_gate_passes_and_materializes(
    tmp_path, monkeypatch
):
    """①缺 retrieved_at → 服务端兜底补齐 → 契约门放行 → 真实物化成功。

    与 SCI-091 兜底用例互补：那里锁定兜底值本身与 build_source_extraction_
    evidence_cards 放行；这里锁定叠加链路的终点——回写被接受、canonical
    result 带兜底时间、真实 claim materializer 物化出 ledger 行 + ClaimEvidence。
    """
    from datetime import datetime

    from core.research.evidence import ClaimEvidenceStore
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
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
                    _missing_retrieved_at_entry(item, index=index)
                    for index, item in enumerate(setup["candidates"], start=1)
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    # 不再拒绝：兜底补齐后契约门放行，任务落成 completed。
    assert complete["task"]["status"] == "completed"

    # 兜底值为该候选被注册的真实时间，且满足 RFC3339 带时区。
    created_by_id = {item["candidateId"]: item["createdAt"] for item in setup["candidates"]}
    stored_entries = complete["task"]["result"]["candidateExtractions"]
    assert len(stored_entries) == 3
    for entry in stored_entries:
        assert entry["retrieved_at"] == created_by_id[entry["candidateId"]]
        parsed = datetime.fromisoformat(entry["retrieved_at"].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    # 真实物化链路终点：ledger 幂合一行 + ClaimEvidence 按候选各一条。
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
    assert result["claimMaterialization"]["claimEvidenceCount"] == 3
    stored = ClaimEvidenceStore(tmp_path).list(setup["teamId"])
    assert len(stored) == 3


def test_post_backfill_contract_violation_rejected_then_corrected_round_trip(
    tmp_path, monkeypatch
):
    """②兜底后仍违约（缺 title，非 retrieved_at）→ 精确 path 拒绝 → 补正 → 物化成功。"""
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    broken = _missing_retrieved_at_entry(setup["candidates"][0])
    broken.pop("title")  # 兜底只管 retrieved_at，title 仍由契约门拦截。
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="title",
    ) as excinfo:
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            setup["teamId"],
            task["taskId"],
            {
                "status": "completed",
                "summary": "完成资料提炼。",
                "result": {"candidateExtractions": [broken]},
                "recordedByAgent": task["task"]["agentId"],
            },
        )
    # 拒绝必须带精确 path，agent 才能在同一任务内定位补正重写。
    assert "candidateExtractions[0]" in str(excinfo.value)
    assert "Challenge v2" in str(excinfo.value)

    stored_task, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    # 违约数据不得落成 completed 任务（completionGate 不得放行）。
    assert stored_task["status"] != "completed"

    # 补正重写：同一任务、同一 candidateId，补上 title（retrieved_at 继续交给兜底；
    # 3 条全覆盖保 completed）。
    entries = [
        _missing_retrieved_at_entry(item, index=index)
        for index, item in enumerate(setup["candidates"], start=1)
    ]
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "补正 1/3 条候选的 title 后完成资料提炼。",
            "result": {"candidateExtractions": entries},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    # 真实物化链路：ledger 幂合一行 + ClaimEvidence 按候选各一条。
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
    assert result["claimMaterialization"]["claimEvidenceCount"] == 3
    stored = ClaimEvidenceStore(tmp_path).list(setup["teamId"])
    assert len(stored) == 3


def test_card_gate_preserves_legal_writeback_shapes(tmp_path, monkeypatch):
    """④合法回写不受影响：exclude 条目与诚实 missing_evidence_anchor 不参与卡契约。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    excluded = {
        "candidateId": setup["candidates"][1]["candidateId"],
        "decision": "exclude",
        "valueSummary": "与问题无关，仅保留否决理由。",
    }
    entries = [
        _anchored_extraction_entry(setup["candidates"][0], index=1),
        excluded,
        _anchored_extraction_entry(setup["candidates"][2], index=3),
    ]
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼（1 条否决）。",
            "result": {"candidateExtractions": entries},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    # exclude 条目没有 v2 字段也必须照常接受——materializer 会跳过它。
    assert complete["task"]["status"] == "completed"


def test_card_gate_skips_missing_evidence_anchor_alias_entry(tmp_path, monkeypatch):
    """④别名归一后的诚实跳过条目（missing_evidence_anchor）不被卡契约误拒。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    alias_entry = _incident_extraction_entry(setup["candidates"][0])
    alias_entry["evidenceRefs"] = [
        {"id": "abstract-quote-1", "type": "quote", "quote": _CANDIDATE_SUMMARY_QUOTE}
    ]
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "单条候选诚实跳过。",
            "result": {"candidateExtractions": [alias_entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] in {"completed", "needs_review"}
    assert complete["task"]["result"]["candidateExtractions"][0]["evidenceStatus"] == (
        "missing_evidence_anchor"
    )


# ---------------------------------------------------------------------------
# retrieved_at 兜底扩展到嵌套 claims 级 + materialize 读点重放兜底
# （生产实锤 run-882610596ddb 叠加缺口）
#
# 缺口一：兜底只补 candidateExtractions/recordExtractions 父项级，嵌套
# claims[]/keyFindings[] 项缺 retrieved_at（或不带时区伪值）时，物化校验器
# 读 item 优先，仍会在 claims 级 fail-closed。
# 缺口二：RETRY_NODE 重试重放上次持久化的 result 直通 materialize，不经过
# 回写边界，兜底与契约门都被绕过。
# 修复：单一权威 backfill（父项+materializable claims）同时服务回写边界与
# materialize 读点（agent_claim_evidence_materializer）。
# ---------------------------------------------------------------------------


def _claims_anchored_extraction_entry(candidate, *, index: int = 1) -> dict:
    """嵌套 claims 形态：quote 锚在 claims 项上，父项与 claim 都可带/缺 retrieved_at。"""
    entry = _anchored_extraction_entry(candidate, index=index)
    entry["claims"] = [
        {
            "fact": f"{candidate['title']} 的摘要支持内容提炼结论。",
            "quote": _CANDIDATE_SUMMARY_QUOTE,
            "sourceRef": candidate["sourceUrl"],
            "evidenceRef": f"abstract-quote-{index}",
        }
    ]
    return entry


def _patch_claim_materialization_env(tmp_path, monkeypatch, team_id):
    """与真实物化链路对齐：ledger/链根 + 问题 scope + agent modelRef。"""
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    monkeypatch.setattr(claim_ledger, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path, raising=False)
    scope = chain._question_scope_envelope(team_id, "SCI-096")
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


def test_backfill_extends_to_nested_claims_inheriting_parent_value(
    tmp_path, monkeypatch
):
    """①a 父项有显式 retrieved_at、嵌套 claim 缺失 → claim 继承父项同源时间。

    回写被接受、canonical result 的 claim 带父项时间，且真实 materializer
    在 claims 级校验通过并物化出 ledger 行 + ClaimEvidence。
    """
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼（嵌套 claims 省略 retrieved_at）。",
            "result": {
                "candidateExtractions": [
                    _claims_anchored_extraction_entry(item, index=index)
                    for index, item in enumerate(setup["candidates"], start=1)
                ]
            },
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    stored_entries = complete["task"]["result"]["candidateExtractions"]
    assert len(stored_entries) == 3
    for entry in stored_entries:
        # 父项显式合规值不动；缺时间的 claim 继承父项同源时间。
        assert entry["retrieved_at"] == "2026-08-31T14:28:07Z"
        assert entry["claims"][0]["retrieved_at"] == entry["retrieved_at"]

    _patch_claim_materialization_env(tmp_path, monkeypatch, setup["teamId"])
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
    assert result["claimMaterialization"]["claimEvidenceCount"] == 3


def test_backfill_extends_to_nested_claims_when_parent_time_missing(
    tmp_path, monkeypatch
):
    """①b 父项与嵌套 claim 都缺 retrieved_at → 两级同补该候选真实链上时间。"""
    from datetime import datetime

    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entries = []
    for index, item in enumerate(setup["candidates"], start=1):
        entry = _claims_anchored_extraction_entry(item, index=index)
        entry.pop("retrieved_at")
        entries.append(entry)
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼（父项与 claims 均缺 retrieved_at）。",
            "result": {"candidateExtractions": entries},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] == "completed"

    created_by_id = {item["candidateId"]: item["createdAt"] for item in setup["candidates"]}
    stored_entries = complete["task"]["result"]["candidateExtractions"]
    for entry in stored_entries:
        expected = created_by_id[entry["candidateId"]]
        assert entry["retrieved_at"] == expected
        assert entry["claims"][0]["retrieved_at"] == expected
        parsed = datetime.fromisoformat(expected.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


def test_backfill_preserves_explicit_compliant_claim_retrieved_at(
    tmp_path, monkeypatch
):
    """③ claim 已显式写合规 retrieved_at → 不被父项时间覆盖。"""
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entry = _claims_anchored_extraction_entry(setup["candidates"][0])
    entry["claims"][0]["retrieved_at"] = "2026-08-01T00:00:00+08:00"
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        setup["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 1/3 条候选资料提炼（claim 自带合规时间）。",
            "result": {"candidateExtractions": [entry]},
            "recordedByAgent": task["task"]["agentId"],
        },
    )
    assert complete["task"]["status"] in {"completed", "needs_review"}
    stored_entry = complete["task"]["result"]["candidateExtractions"][0]
    assert stored_entry["claims"][0]["retrieved_at"] == "2026-08-01T00:00:00+08:00"


def test_replayed_persisted_result_backfilled_at_materialize_read_point(
    tmp_path, monkeypatch
):
    """②RETRY_NODE 重放路径：持久化 result 缺两级 retrieved_at → 读点兜底后物化成功。

    防线合入前的历史持久化数据没有兜底时间。把 canonical task 的 result（含
    writeback envelope 副本）剥成历史形态原样落盘，再走 reconcile →
    materialize_completed_extraction_task 重放，读点 backfill 必须把它修好。
    """
    setup = _seed_completed_extraction_task(tmp_path, monkeypatch)
    task = setup["task"]
    _append_stage_task_tool_trace(tmp_path, task["task"])

    entries = [
        _claims_anchored_extraction_entry(item, index=index)
        for index, item in enumerate(setup["candidates"], start=1)
    ]
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

    stored_task, run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    # 模拟历史持久化数据：剥掉 result 与 writeback envelope 里两级的 retrieved_at。
    for payload_key in ("result", "writeback"):
        payload = stored_task.get(payload_key)
        if not isinstance(payload, dict):
            continue
        for entry in payload.get("candidateExtractions") or []:
            if isinstance(entry, dict):
                entry.pop("retrieved_at", None)
                for claim in entry.get("claims") or []:
                    if isinstance(claim, dict):
                        claim.pop("retrieved_at", None)
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        setup["teamId"], run_id, stored_task
    )

    _patch_claim_materialization_env(tmp_path, monkeypatch, setup["teamId"])
    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        setup["teamId"],
        task["taskId"],
        run_id=setup["runId"],
        session_id=task["sessionId"],
        turn_id=task["task"]["turn"]["turnId"],
        final_status="completed",
    )
    # 不修复的话：claims 级缺 retrieved_at 会在 materialize fail-closed。
    assert result["claimMaterialization"]["status"] == "materialized"
    assert result["claimMaterialization"]["claimEvidenceCount"] == 3

    # 读点兜底只修消费侧：canonical 存储保持回写边界接受的原始形态。
    reread, _run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        setup["teamId"], task["taskId"]
    )
    for entry in reread["result"]["candidateExtractions"]:
        assert "retrieved_at" not in entry
