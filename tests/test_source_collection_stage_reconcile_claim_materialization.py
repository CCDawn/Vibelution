# -*- coding: utf-8 -*-
"""Session 路径 extraction stage task 终结后的 claim 物化桥接。

缺陷 #10：graph dispatch 路径在 turn 终结时物化 claim evidence
（agent_turn_completion），但经 POST /source-collection-runs/{run}/stage-session-tasks
创建的 stage task 走 session 消息路径，终结对账从不物化，completed 任务
在 claim_ledger.jsonl 中始终为 0。本文件锁定 reconcile 处的桥接契约：

1. canonical 终态为 completed 的 extraction 任务必须触发物化，且参数
   （team/workflow/source-run/task）取自对账后的 canonical 任务；
2. stageId 非 extraction 或终态非 completed 一律不调物化（终态以对账后
   状态为准，不看请求参数）；
3. 物化失败只留诊断事件，不得翻转任务状态或阻塞 reconcile 返回。
"""

from __future__ import annotations

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
                    {"candidateId": item["candidateId"], "status": "extracted", "summary": f"{item['title']} 已提炼。"}
                    for item in setup["candidates"]
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
                    {"candidateId": item["candidateId"], "status": "extracted", "summary": f"{item['title']} 已提炼。"}
                    for item in setup["candidates"]
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
