from __future__ import annotations

import copy
import re

from core.research.competition.question_result_package import canonical_model_policy
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.problem_understanding_artifact_writer import (
    write_problem_understanding_artifact,
)
from tests._support.team_workflow.helpers import *  # noqa: F403
from tests.test_challenge_question_runs import _append_canonical_turn_output


def test_source_collection_summary_reuses_processing_status_for_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    real_get_processing_status = data_processing_service.get_processing_status
    status_calls = []

    def counted_get_processing_status(requested_run_id):
        status_calls.append(requested_run_id)
        return real_get_processing_status(requested_run_id)

    monkeypatch.setattr(data_processing_service, "get_processing_status", counted_get_processing_status)

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    assert payload["runId"] == run_id
    assert status_calls == [run_id]

def test_source_collection_summary_reconciles_needs_continue_stage_task(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    workflow_run_id = "workflow-stage-summary-needs-continue"
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
            "scope": {"workflowRunId": workflow_run_id},
        },
    )
    run_id = run_response["run"]["runId"]
    write_problem_understanding_artifact(
        team_id=team["teamId"],
        workflow_run_id=workflow_run_id,
        source_collection_run_id=run_id,
        node_run_id="node-problem-stage-summary-needs-continue",
        problem_understanding={
            "scope": "验证资料搜集任务在中断后可以继续。",
            "subquestions": ["finding 阶段是否保留可恢复的任务状态？"],
            "assumptions": ["资料搜集运行已绑定当前工作流。"],
            "known_unknowns": ["恢复后的实际搜索结果尚未产生。"],
            "human_gate": {
                "required": True,
                "decision": "approved",
                "reviewer": "test-reviewer",
                "decided_at": "2026-08-24T00:00:00Z",
                "rationale": "测试已确认问题边界，可以进入 finding 阶段。",
            },
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-summary-needs-continue",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    events_path = tmp_path / "workspace" / "agents" / discovery["agentId"] / "events" / "agent_turn_results.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {
                "eventId": "turn-result-needs-continue",
                "runId": "turn-stage-summary-needs-continue",
                "agentId": discovery["agentId"],
                "sessionId": task["sessionId"],
                "status": "needs_continue",
                "summary": "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
                "toolCallCount": 4,
                "createdAt": "2026-07-05T00:58:10+08:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    card = next(item for item in payload["stageCards"] if item["stageId"] == "finding")
    assert card["agentTaskStatus"] == "interrupted"
    assert card["status"] == "agent_interrupted"
    assert card["actionReadiness"]["canStart"] is True
    assert card["actionReadiness"]["recommendedAction"] == "continue"
    assert card["actionReadiness"]["actionLabel"] == "继续这次任务"
    assert card["latestTask"]["status"] == "interrupted"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["status"] == "interrupted"
    assert stored_task["reconciledFromTurn"]["status"] == "needs_continue"

def test_source_collection_run_start_preserves_previous_stage_agent_session_records(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    old_session_id = agent_directory_service.get_agent(discovery["agentId"])["directSessionId"]
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    first_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding old round",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding old round"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    session_service.append_session_assistant_artifact_message(
        old_session_id,
        "上一轮资料搜集任务上下文。",
        metadata={
            "kind": team_workflow_orchestration_service.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND,
            "teamId": team["teamId"],
            "runId": first_run["run"]["runId"],
            "stageId": "finding",
            "agentId": discovery["agentId"],
            "agentRole": "source_finder",
            "sourceCollectionStageTaskId": "stagetask-old-round",
            "turnId": "turn-old-round",
        },
    )
    second_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding new round",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding new round"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    cleanup = second_run["sessionCleanup"]
    new_session_id = agent_directory_service.get_agent(discovery["agentId"])["directSessionId"]

    assert cleanup["status"] == "not_required"
    assert cleanup["cleanedCount"] == 0
    assert cleanup["items"] == []
    assert new_session_id == old_session_id
    old_detail = session_service.get_session_detail(old_session_id)
    assert old_detail is not None
    assert any(
        message.get("metadata", {}).get("sourceCollectionStageTaskId") == "stagetask-old-round"
        for message in old_detail["messages"]
    )

def test_source_collection_summary_defaults_to_latest_run_with_records(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    first_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    first_run_id = first_run["run"]["runId"]
    data_processing_service.add_record(
        first_run_id,
        {
            "sourceType": "paper",
            "sourceRef": "10.1000/example",
            "title": "Useful predictive coding source",
        },
    )
    empty_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding retry",
            "agentRoles": ["source_finder"],
            "querySeeds": ["already excluded source"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"])

    assert empty_run["run"]["runId"] != first_run_id
    assert payload["runId"] == first_run_id
    assert payload["summary"]["recordCount"] == 1
    assert payload["searchPlan"]["planId"] == first_run["searchPlan"]["planId"]
    assert payload["searchPlan"]["querySeeds"] == ["predictive coding"]
    assert payload["searchPlan"]["queryCount"] == first_run["searchPlan"]["queryCount"]


def test_source_collection_summary_never_selects_a_round_from_another_research_project(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    old_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    old_run_id = old_run["run"]["runId"]
    data_processing_service.add_record(
        old_run_id,
        {"sourceType": "paper", "sourceRef": "10.1000/old", "title": "Old project source"},
    )
    chemistry_project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "AI chemistry", "topic": "AI-driven reaction discovery"},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(team["teamId"], chemistry_project["projectId"])
    chemistry_run = data_processing_service.create_processing_run(
        data_processing_service.DEFAULT_PROFILE_ID,
        title="AI chemistry source collection",
        scope={
            "teamId": team["teamId"],
            "workflowStage": "knowledge_collection",
            "researchProjectId": chemistry_project["projectId"],
        },
        metadata={
            "startedFrom": "team_workflow_source_collection",
            "teamId": team["teamId"],
            "researchProjectId": chemistry_project["projectId"],
        },
    )

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"])

    assert payload["runId"] == chemistry_run["runId"]
    assert payload["summary"]["recordCount"] == 0
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="active research project",
    ):
        team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=old_run_id)

def test_source_collection_summary_status_ignores_legacy_collecting_after_stage_round():
    assert (
        team_workflow_orchestration_service._source_collection_summary_payload_status(
            "run-with-stage-round",
            run_status={"runStatus": "collecting"},
            active_work_run={},
            stage_round_ref={"stageRoundId": "stage-1"},
            projection={"latestTasks": {}},
        )
        == "ready"
    )
    assert (
        team_workflow_orchestration_service._source_collection_summary_payload_status(
            "run-with-active-agent-task",
            run_status={"runStatus": "reviewing"},
            active_work_run={},
            stage_round_ref={"stageRoundId": "stage-1"},
            projection={"latestTasks": {"finding": {"status": "running"}}},
        )
        == "active"
    )
    assert (
        team_workflow_orchestration_service._source_collection_summary_payload_status(
            "run-with-background-search",
            run_status={"runStatus": "collecting"},
            active_work_run={"runId": "work-1"},
            stage_round_ref={"stageRoundId": "stage-1"},
            projection={"latestTasks": {}},
        )
        == "active"
    )

def test_source_collection_stage_turn_failure_uses_terminal_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session_id = "session-stage-tool-blocked"
    turn_id = "turn-stage-tool-blocked"
    blocked_tool_event = SimpleNamespace(
        turn_id=turn_id,
        event_type="tool_result",
        status="blocked",
        payload={
            "toolCall": {
                "name": "source_collection_stage_writeback_tool",
                "status": "blocked",
            }
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_stage_session_task_completion_snapshot_result",
        lambda current_session_id, current_turn_id: {
            "eventId": "session_completion_snapshot",
            "runId": current_turn_id,
            "sessionId": current_session_id,
            "status": "interrupted",
            "summary": "工具额度耗尽，阶段写回未完成。",
            "createdAt": "",
            "source": "session_completion_snapshot",
        },
    )

    result = team_workflow_orchestration_service._source_collection_stage_session_task_turn_result(
        "agent-source-finder",
        session_id,
        turn_id,
        conversation_events_by_session={session_id: [blocked_tool_event]},
    )

    assert result["status"] == "interrupted"
    assert result["summary"] == "工具额度耗尽，阶段写回未完成。"

def test_import_data_record_as_source_candidate_preserves_trace_and_is_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(title="Source collection")
    record = data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "url",
            "sourceRef": "https://example.test/neuro-paper",
            "title": "Neurology source",
            "summary": "A useful candidate source.",
            "qualitySignals": {"confidence": 0.82},
            "metadata": {"allowedForAnalysis": True, "pageScope": "1-3"},
        },
    )

    response = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run["runId"],
        record["recordId"],
        {"createdByAgent": "data_intake_coordinator", "tags": ["neuro"]},
    )
    duplicate = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run["runId"],
        record["recordId"],
        {"createdByAgent": "data_intake_coordinator"},
    )
    source_list = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")

    candidate = response["candidate"]
    assert response["created"] is True
    assert duplicate["created"] is False
    assert duplicate["candidate"]["candidateId"] == candidate["candidateId"]
    assert source_list["candidateCount"] == 1
    assert candidate["candidateType"] == "source_manifest"
    assert candidate["sourceUrl"] == "https://example.test/neuro-paper"
    assert candidate["allowedForAnalysis"] is True
    assert candidate["pageScope"] == "1-3"
    assert candidate["metadata"]["importedFromDataRecord"]["runId"] == run["runId"]
    assert candidate["metadata"]["importedFromDataRecord"]["recordId"] == record["recordId"]
    assert candidate["metadata"]["dataProcessingQualitySignals"]["confidence"] == 0.82
    assert {item["type"] for item in candidate["evidenceRefs"]} >= {"data_record", "data_processing_run"}
    duplicate_events = _workflow_scene_events_by_code(scene_events, "candidate.import_duplicate_skipped")
    assert duplicate_events
    assert duplicate_events[-1]["fields"]["recordId"] == record["recordId"]
    assert duplicate_events[-1]["fields"]["duplicateReason"] == "imported_from_data_record"
    assert duplicate_events[-1]["fields"]["duplicateOfCandidateId"] == candidate["candidateId"]

def test_import_data_record_as_source_candidate_rejects_missing_record(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(title="Source collection")

    try:
        team_workflow_orchestration_service.import_data_record_as_source_candidate(team["teamId"], run["runId"], "missing-record", {})
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "Data processing record not found" in str(exc)
    else:
        raise AssertionError("Expected TeamWorkflowOrchestrationError")

def test_extract_source_collection_candidates_imports_records_and_closes_extraction_assignment(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(
        title="Neural source collection",
        scope={"teamId": team["teamId"], "workflowKind": "challenge_cup_research"},
    )
    data_processing_service.create_collection_assignment(
        run["runId"],
        {
            "agentRole": "source_extractor",
            "agentId": "source-extractor-agent",
            "scope": {"topic": "predictive coding"},
            "expectedRecordTypes": ["source_manifest"],
        },
    )
    first_record = data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/predictive-coding",
            "title": "Predictive coding paper",
            "summary": "Predictive coding evidence.",
        },
    )
    second_record = data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "dataset",
            "sourceRef": "https://example.test/dataset",
            "title": "Neural coding dataset",
            "summary": "Dataset for neural coding.",
        },
    )

    response = team_workflow_orchestration_service.extract_source_collection_candidates(
        team["teamId"],
        {
            "runId": run["runId"],
            "extractionAgentId": "source-extractor-agent",
            "maxRecords": 10,
        },
    )
    duplicate = team_workflow_orchestration_service.extract_source_collection_candidates(
        team["teamId"],
        {
            "runId": run["runId"],
            "extractionAgentId": "source-extractor-agent",
            "maxRecords": 10,
            "force": True,
        },
    )
    source_list = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assignments = data_processing_service.list_collection_assignments(run["runId"])["assignments"]

    assert response["status"] == "completed"
    assert response["importedCount"] == 2
    assert response["candidateCount"] == 2
    assert response["pendingRecordCount"] == 0
    assert response["completedExtractionAssignmentCount"] == 1
    assert {item["dataRecordRef"]["recordId"] for item in response["imported"]} == {first_record["recordId"], second_record["recordId"]}
    assert duplicate["status"] == "completed"
    assert duplicate["importedCount"] == 0
    assert duplicate["skippedCount"] == 2
    assert source_list["candidateCount"] == 2
    assert assignments[0]["status"] == "completed"
    assert response["boundaries"]["writesFormalKnowledge"] is False
    assert response["boundaries"]["writesRag"] is False
    assert response["boundaries"]["writesOfficialGraph"] is False
    extraction_events = _workflow_scene_events_by_code(scene_events, "source_collection.candidates_extracted")
    assert extraction_events
    child_payload = extraction_events[-1]["child_log_payload"]
    assert extraction_events[-1]["child_log_path"].endswith("-candidate-extraction.jsonl")
    assert child_payload["kind"] == "source_collection_candidate_extraction"
    assert child_payload["importedCount"] == 0
    assert child_payload["skippedCount"] == 2
    assert {item["status"] for item in child_payload["recordOutcomes"]} == {"skipped"}
    assert {item["reason"] for item in child_payload["recordOutcomes"]} == {"imported_from_data_record"}

def test_extract_source_collection_candidates_keeps_assignment_open_when_batch_is_partial(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(
        title="Neural source collection",
        scope={"teamId": team["teamId"], "workflowKind": "challenge_cup_research"},
    )
    data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_extractor", "agentId": "source-extractor-agent"},
    )
    for index in range(2):
        data_processing_service.add_record(
            run["runId"],
            {
                "sourceType": "paper",
                "sourceRef": f"https://doi.org/10.0000/source-{index}",
                "title": f"Neural source {index}",
            },
        )

    response = team_workflow_orchestration_service.extract_source_collection_candidates(
        team["teamId"],
        {
            "runId": run["runId"],
            "extractionAgentId": "source-extractor-agent",
            "maxRecords": 1,
        },
    )
    assignments = data_processing_service.list_collection_assignments(run["runId"])["assignments"]

    assert response["status"] == "partial"
    assert response["importedCount"] == 1
    assert response["pendingRecordCount"] == 1
    assert assignments[0]["status"] == "returned"

def test_start_source_collection_run_creates_generic_run_and_assignments(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neurology source batch",
            "goal": "Collect sources about neural gating.",
            "topic": "neural gating",
            "requestedByAgent": "Research Coordination Agent",
            "agentRoles": ["source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"],
            "inputRefs": ["seed-query:neural gating"],
        },
    )
    run_status = data_processing_service.get_processing_status(response["run"]["runId"])
    assignments = data_processing_service.list_collection_assignments(response["run"]["runId"])

    assert response["run"]["profileId"] == "generic_document_processing"
    assert response["run"]["scope"]["teamId"] == team["teamId"]
    assert response["run"]["scope"]["topic"] == "neural gating"
    assert response["run"]["scope"]["dataSearchPlanRef"]["queryCount"] == response["searchPlan"]["queryCount"]
    assert response["searchPlan"]["planKind"] == "source_collection_data_search"
    assert response["searchPlan"]["status"] == "planned"
    assert response["searchPlan"]["runId"] == response["run"]["runId"]
    assert response["searchPlan"]["querySeeds"] == ["neural gating"]
    assert response["searchPlan"]["queryCount"] > 0
    assert response["searchPlan"]["boundaries"]["externalSearchTriggered"] is False
    assert response["searchPlan"]["boundaries"]["requiresPromptCacheForAgentExecution"] is True
    assert response["searchPlan"]["promptCachePolicy"]["gate"]["status"] == "satisfied"
    assert response["searchPlan"]["promptCachePolicy"]["promptCacheMode"] == "explicit_cache_control"
    assert response["promptCachePolicy"]["requirement"] == "required_for_llm_execution"
    assert response["run"]["scope"]["promptCachePolicyRef"]["gateStatus"] == "satisfied"
    assert response["run"]["metadata"]["promptCacheMode"] == "explicit_cache_control"
    assert response["searchPlan"]["resultWritebackContract"]["formalKnowledgeWrites"] is False
    expected_roles = {"source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"}
    assert response["assignmentCount"] == 4
    assert {item["agentRole"] for item in response["assignments"]} == expected_roles
    assert all(item["inputRefs"] == ["seed-query:neural gating"] for item in response["assignments"])
    assert all(item["scope"]["dataSearchPlanRef"]["planId"] == response["searchPlan"]["planId"] for item in response["assignments"])
    assignment_by_role = {item["agentRole"]: item for item in response["assignments"]}
    assert assignment_by_role["source_finder"]["scope"]["assignedQueries"]
    assert assignment_by_role["source_extractor"]["scope"]["assignedQueries"] == []
    assert assignment_by_role["source_relation_mapper"]["scope"]["assignedQueries"] == []
    assert assignment_by_role["source_ingestor"]["scope"]["assignedQueries"] == []
    assert all(item["scope"]["promptCachePolicyRef"]["gateStatus"] == "satisfied" for item in response["assignments"])
    assert all(item["scope"]["promptCachePartition"].startswith("research-team-") for item in response["assignments"])
    assert all(item["execution"]["promptCacheRequired"] is True for item in response["searchPlan"]["queries"])
    assert {item["assignedAgentRole"] for item in response["searchPlan"]["queries"]} == {"source_finder"}
    assert all(item["execution"]["promptCachePartition"].startswith("research-team-") for item in response["searchPlan"]["queries"])
    assert all(item["scope"]["resultWritebackContract"]["ragWrites"] is False for item in response["assignments"])
    assert assignments["summary"]["assignmentCount"] == 4
    assert run_status["boundaries"]["writesFormalKnowledge"] is False
    assert response["workflow"]["activeWorkflowItems"][0]["candidateId"] == response["run"]["runId"]
    assert response["workflow"]["activeWorkflowItems"][0]["status"] == "source_collection_started"

def test_unregistered_source_collection_stage_tasks_are_rejected(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="旧资料质检")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="旧资料质检")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "unsupported_source_role", "agentName": "未注册资料角色"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码资料审查",
            "agentRoles": ["unsupported_source_role"],
            "agentIds": {"unsupported_source_role": agent["agentId"]},
            "querySeeds": ["predictive coding source review"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Unsupported source collection stage"):
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run_id,
            {"stageId": "screening", "agentId": agent["agentId"], "agentRole": "unsupported_source_role"},
        )

def test_start_source_collection_run_imports_local_workspace_sources_for_knowledge_expansion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]
    source_member = next(member for member in team["members"] if member["role"] == "source_finder")
    source_file = tmp_path / "workspace" / "knowledge" / "notes" / "predictive-coding.md"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "# Predictive coding\n\nEvidence for cortical hierarchy and error minimization.",
        encoding="utf-8",
    )

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Knowledge expansion local intake",
            "workflowPurpose": "knowledge_expansion",
            "collectionMode": "local_workspace",
            "topic": "predictive coding",
            "goal": "扩充团队知识库",
            "agentRoles": ["source_finder", "source_extractor", "source_ingestor"],
            "agentIds": {"source_finder": source_member["agentId"]},
            "localScanScope": {"roots": ["workspace/knowledge"], "maxFiles": 10},
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = response["run"]["runId"]
    context = team_workflow_orchestration_service._source_collection_run_context_bundle(team["teamId"], run_id)

    assert response["run"]["scope"]["workflowKind"] == "knowledge_expansion"
    assert response["run"]["metadata"]["collectionMode"] == "local_workspace"
    assert response["searchPlan"]["collectionMode"] == "local_workspace"
    assert response["localWorkspaceScan"]["status"] == "completed"
    assert response["localWorkspaceScan"]["importedCount"] == 1
    assert response["localWorkspaceScan"]["skippedCount"] == 0
    assert context["runStatus"]["summary"]["recordCount"] == 1
    assert len(context["records"]) == 1
    assert len(context["sourceCandidates"]) == 1
    candidate = context["sourceCandidates"][0]
    assert candidate["metadata"]["sourceCollectionRunId"] == run_id
    assert candidate["metadata"]["sourceCategory"] == "local_file"
    assert candidate["metadata"]["localWorkspaceImport"]["relativePath"] == "workspace/knowledge/notes/predictive-coding.md"
    assert candidate["sourcePath"].endswith("workspace/knowledge/notes/predictive-coding.md")
    # 旧 localScanScope 入口也不得把绝对路径写进 rawLocation（与受管根 managed:// 同风格）
    record = context["records"][0]
    assert record["rawLocation"] == "project://workspace/knowledge/notes/predictive-coding.md"
    assert not re.match(r"^[A-Za-z]:[/\\]", record["rawLocation"])
    assert "C:\\" not in str(record.get("metadata", {}))

def test_start_source_collection_run_blocks_without_required_prompt_cache(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: _fake_local_research_public_config(prompt_cache_mode="unsupported"),
    )
    team = team_service.create_team(name="挑战杯科研团队")

    try:
        team_workflow_orchestration_service.start_source_collection_run(
            team["teamId"],
            {"topic": "predictive coding"},
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "requires prompt cache/KV reuse" in str(exc)
        assert "prompt_cache.mode" in str(exc)
        assert "automatic or explicit_cache_control" in str(exc)
    else:
        raise AssertionError("source collection should block when required prompt cache is unsupported")


def test_source_collection_prompt_cache_resolves_provider_first_schema_v2(monkeypatch):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "relay_openai": {
                        "label": "Relay OpenAI",
                        "driver": "openai",
                        "service_class": "relay",
                        "credential_ref": "env:RELAY_OPENAI_API_KEY",
                        "protocols": {"default": "responses", "supported": ["responses"]},
                        "models": {
                            "gpt-5.6-luna": {
                                "label": "GPT-5.6 Luna",
                                "upstream_id": "gpt-5.6-luna",
                                "wire_protocol": "responses",
                                "interaction_contract": "tool_chat",
                                "defaults": {"prompt_cache": {"mode": "automatic"}},
                            }
                        },
                    }
                },
                "profiles": {
                    "primary": {
                        "model_ref": "relay_openai/gpt-5.6-luna",
                        "overrides": {},
                    }
                },
            }
        },
    )

    policy = team_workflow_orchestration_service._source_collection_prompt_cache_policy(
        "research-team",
        {},
        ["source_finder"],
    )

    assert policy["modelId"] == "relay_openai/gpt-5.6-luna"
    assert policy["promptCacheMode"] == "automatic"
    assert policy["modelResolution"]["status"] == "auto"
    assert policy["gate"]["status"] == "satisfied"
    assert policy["gate"]["passed"] is True


def test_start_source_collection_run_ignores_invalid_collection_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {"agentRoles": ["unsupported_source_role", "research_specific_role"]},
    )

    expected_roles = {"source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"}
    assert response["assignmentCount"] == 4
    assert {item["agentRole"] for item in response["assignments"]} == expected_roles

def test_start_source_collection_run_maps_roles_to_team_canvas_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    coordinator = session_service.create_chat_session(title="Coordinator")
    other_research_agent = session_service.create_chat_session(title="Other Research Agent")
    finder = session_service.create_chat_session(title="Source Finder")
    extractor = session_service.create_chat_session(title="Source Extractor")
    organization = {
        "agents": [
            {"nodeId": "coordinator", "agentId": coordinator["agentId"], "displayName": "Coordinator", "role": "ceo", "status": "active"},
            {"nodeId": "other-research-agent", "agentId": other_research_agent["agentId"], "displayName": "Other Research Agent", "role": "other_research_role", "status": "active"},
            {"nodeId": "finder", "agentId": finder["agentId"], "displayName": "Source Finder", "role": "source_finder", "status": "active"},
            {"nodeId": "extractor", "agentId": extractor["agentId"], "displayName": "Source Extractor", "role": "source_extractor", "status": "active"},
        ],
        "edges": [],
    }
    team = team_service.ensure_research_team_from_organization(organization)

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder", "source_extractor"],
        },
    )

    role_to_agent_id = {item["agentRole"]: item["agentId"] for item in response["assignments"]}
    assert response["run"]["metadata"]["ownerAgentId"] == coordinator["agentId"]
    assert response["searchPlan"]["roleAssignmentInputs"][0]["agentId"] == finder["agentId"]
    assert role_to_agent_id == {
        "source_finder": finder["agentId"],
        "source_extractor": extractor["agentId"],
    }

def test_start_source_collection_run_accepts_traceable_query_seed_contract(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "neural predictive coding",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 7,
            "agentRoles": ["source_finder", "source_extractor"],
            "agentIds": {"source_extractor": "Source Extractor Agent"},
        },
    )

    search_plan = response["searchPlan"]
    queries = search_plan["queries"]

    assert search_plan["querySeeds"] == ["predictive coding cortical hierarchy", "neural predictive coding"]
    assert search_plan["searchLanguages"] == ["en"]
    assert search_plan["sourceTypes"] == ["paper"]
    assert search_plan["maxResultsPerQuery"] == 7
    assert search_plan["queryCount"] == 2
    assert {item["assignedAgentRole"] for item in queries} == {"source_finder"}
    assert all(item["status"] == "planned" for item in queries)
    assert all(item["execution"]["externalSearchTriggered"] is False for item in queries)
    assert response["assignments"][1]["agentId"] == "Source Extractor Agent"
    assert response["assignments"][1]["scope"]["assignedQueries"] == []
    assert response["assignments"][1]["acceptance"]["resultWritebackContract"]["candidateImport"]["targetCandidateType"] == "source_manifest"
    assert response["assignments"][1]["acceptance"]["resultWritebackContract"]["officialGraphWrites"] is False

def test_seed_source_collection_agent_session_context_writes_and_dedupes_project_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    _use_fake_local_research_config(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    direct_session = session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )

    workflow_run_id = "workflow-seed-agent-session-context"
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
            "scope": {"workflowRunId": workflow_run_id},
        },
    )
    source_run_id = run_response["run"]["runId"]
    write_problem_understanding_artifact(
        team_id=team["teamId"],
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        node_run_id="node-problem-seed-agent-session-context",
        problem_understanding={
            "scope": "验证资料搜集 Agent 会话上下文的创建与去重。",
            "subquestions": ["同一 finding 上下文是否只写入一次？"],
            "assumptions": ["资料搜集运行已绑定当前工作流。"],
            "known_unknowns": ["Agent 尚未返回资料结果。"],
            "human_gate": {
                "required": True,
                "decision": "approved",
                "reviewer": "test-reviewer",
                "decided_at": "2026-08-24T00:00:00Z",
                "rationale": "测试已确认问题边界，可以创建 finding 会话。",
            },
        },
    )

    first = team_workflow_orchestration_service.seed_source_collection_agent_session_context(
        team["teamId"],
        source_run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    second = team_workflow_orchestration_service.seed_source_collection_agent_session_context(
        team["teamId"],
        source_run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )

    assert first["created"] is True
    assert first["sessionCreated"] is True
    assert first["sessionId"] != direct_session["id"]
    assert agent_directory_service.get_agent(discovery["agentId"])["directSessionId"] == direct_session["id"]
    assert first["message"]["metadata"]["kind"] == "source_collection_agent_context"
    assert first["message"]["metadata"]["sourceCollectionContextKey"] == first["contextKey"]
    # Assistant detail messages are projected from turnItems only; content is
    # intentionally not duplicated as a second renderer source.
    assert "content" not in first["message"]
    assert any(
        "脑启发路由" in str(item.get("text") or "")
        for item in first["message"]["turnItems"]
        if isinstance(item, dict)
    )
    assert second["created"] is False
    assert second["sessionCreated"] is False
    assert second["sessionId"] == first["sessionId"]
    assert second["alreadyPresent"] is True
    detail = session_service.get_session_detail(first["sessionId"])
    context_messages = [
        message for message in detail["messages"]
        if message.get("metadata", {}).get("kind") == "source_collection_agent_context"
    ]
    assert len(context_messages) == 1

def test_start_source_collection_stage_session_task_submits_project_session_task(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    submitted: list[dict] = []

    finder = agent_directory_service.create_agent_instance(display_name="资料寻找")
    direct_session = session_service.ensure_agent_direct_session(agent_id=finder["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": finder["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted.append({"sessionId": session_id, "content": content, "kwargs": kwargs})
        turn_id = f"turn-stage-task-{len(submitted)}"
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": turn_id,
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "returnTo": "/teams?team=research-team&researchView=knowledge_collection&collectionStage=finding",
            "returnLabel": "返回搜索资料",
        },
    )
    second = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "returnTo": "/teams?team=research-team&researchView=knowledge_collection&collectionStage=finding",
            "returnLabel": "返回搜索资料",
        },
    )
    explicit_once = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "idempotencyKey": "stage-task-click-explicit",
        },
    )
    explicit_duplicate = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "idempotencyKey": "stage-task-click-explicit",
        },
    )

    assert task["created"] is True
    assert task["alreadyPresent"] is False
    assert task["sessionCreated"] is True
    assert task["sessionId"] != direct_session["id"]
    assert task["chatRoute"].startswith(f"/chat?session={task['sessionId']}")
    assert agent_directory_service.get_agent(finder["agentId"])["directSessionId"] == direct_session["id"]
    assert task["turn"]["turnId"] == "turn-stage-task-1"
    assert task["task"]["status"] == "running"
    assert task["task"]["writebackContract"]["writesFormalKnowledge"] is False
    assert task["task"]["writebackContract"]["endpoint"].endswith(f"/stage-session-tasks/{task['taskId']}/writeback")
    assert task["task"]["taskToolRequired"] is False
    assert task["task"]["checklistBinding"] == {
        "mode": "stage_task",
        "bound": True,
        "boundAt": task["task"]["createdAt"],
        "source": "backend",
    }
    assert task["task"]["completionGate"]["requiresTaskChecklist"] is True
    assert task["task"]["completionGate"]["requiresArtifact"] is True
    assert [item["id"] for item in task["task"]["taskChecklist"]] == [
        "read_context",
        "page_existing_sources",
        "search_and_dedupe_sources",
        "write_candidate_leads",
        "write_invalid_sources",
        "confirm_materialized_sources",
    ]
    assert submitted[0]["sessionId"] == task["sessionId"]
    assert "资料搜集阶段任务" in submitted[0]["content"]
    assert "会立即要求当前 Agent 在本会话执行" in submitted[0]["content"]
    assert "checklist 已由后端绑定" in submitted[0]["content"]
    assert "不要调用通用 `task_list_tool`、`task_create_tool` 或 `task_update_tool`" in submitted[0]["content"]
    assert "candidateLeads[]" in submitted[0]["content"]
    assert "每条 `candidateLeads[]` 至少包含" in submitted[0]["content"]
    assert "`limitation_or_null`" in submitted[0]["content"]
    assert "`falsification`" in submitted[0]["content"]
    assert "`result.searchTrace[]`" in submitted[0]["content"]
    assert "不得伪造负面资料" in submitted[0]["content"]
    assert "`locator`（可验证 DOI 或 https URL）" in submitted[0]["content"]
    assert "资料提炼阶段如果 `candidatePage.total=0`" not in submitted[0]["content"]
    assert "`recordExtractions[]` 回写" not in submitted[0]["content"]
    assert "第一动作必须是 `task_list_tool`" not in submitted[0]["content"]
    assert "先用一句简短状态回应已接收任务" not in submitted[0]["content"]
    assert "source_collection_context_tool" in submitted[0]["content"]
    assert "source_collection_stage_writeback_tool" in submitted[0]["content"]
    assert "不要使用 `web_fetch_tool` 读取 `file://`" in submitted[0]["content"]
    assert "不会自动启动 Agent 回答" not in submitted[0]["content"]
    assert submitted[0]["kwargs"]["message_source"] == "agent_inbox"
    assert submitted[0]["kwargs"]["lightweight_response"] is True
    assert submitted[0]["kwargs"]["include_started_turn_id"] is True
    metadata = submitted[0]["kwargs"]["message_metadata"]
    assert metadata["kind"] == "source_collection_stage_session_task"
    assert metadata["sourceSurface"] == "team_workflow_stage_task"
    assert metadata["sourceCollectionStageTaskId"] == task["taskId"]
    assert metadata["writebackContract"]["taskId"] == task["taskId"]
    assert metadata["taskToolRequired"] is False
    assert metadata["checklistBinding"]["mode"] == "stage_task"
    assert second["created"] is True
    assert second["alreadyPresent"] is False
    assert second["taskId"] != task["taskId"]
    assert second["turn"]["turnId"] == "turn-stage-task-2"
    assert explicit_once["created"] is True
    assert explicit_once["alreadyPresent"] is False
    assert explicit_duplicate["created"] is False
    assert explicit_duplicate["alreadyPresent"] is True
    assert explicit_duplicate["taskId"] == explicit_once["taskId"]
    assert len(submitted) == 3


def test_formal_run_stage_sessions_do_not_inherit_other_runs(tmp_path, monkeypatch):
    """Finding stage sessions are scoped to their own formal workflow run.

    The stage-session resolver previously used the flat per-agent registry
    key, so a formal run inherited the dprun-era session (with its stale
    prompt context) of the same Agent.  With a workflow run binding the
    second formal run must open its own session while continuity inside one
    run is preserved.
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    submitted: list[dict] = []

    finder = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=finder["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted.append({"sessionId": session_id, "content": content})
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-scoped-{len(submitted)}",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)

    def _start_run():
        return _start_source_collection_run_with_problem_understanding(
            team["teamId"],
            {
                "topic": "脑启发路由",
                "goal": "搜集神经机制启发算法资料",
                "agentRoles": ["source_finder"],
                "agentIds": {"source_finder": finder["agentId"]},
                "querySeeds": ["brain-inspired routing"],
                "promptCachePolicy": {"requirement": "disabled"},
            },
        )

    def _start_finding(source_run_id):
        return team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            source_run_id,
            {
                "stageId": "finding",
                "agentId": finder["agentId"],
                "agentRole": "source_finder",
            },
        )

    run_a = _start_run()
    run_b = _start_run()
    workflow_run_a = str(run_a["run"]["scope"]["workflowRunId"])
    workflow_run_b = str(run_b["run"]["scope"]["workflowRunId"])
    assert workflow_run_a and workflow_run_b and workflow_run_a != workflow_run_b

    task_a1 = _start_finding(run_a["run"]["runId"])
    task_a2 = _start_finding(run_a["run"]["runId"])
    task_b = _start_finding(run_b["run"]["runId"])

    # 同一 run 内：session 连续性保留（复用同一 canonical session）。
    assert task_a1["sessionCreated"] is True
    assert task_a2["sessionId"] == task_a1["sessionId"]
    assert task_a2["sessionCreated"] is False

    # 跨 run：第二个 formal run 不得继承第一个 run 的 session。
    assert task_b["sessionCreated"] is True
    assert task_b["sessionId"] != task_a1["sessionId"]

    binding_a = session_service.get_session_detail(task_a1["sessionId"])["experimentBinding"]
    assert binding_a["workflowRunId"] == workflow_run_a
    assert binding_a["workflowNodeId"] == "source_collection"
    binding_b = session_service.get_session_detail(task_b["sessionId"])["experimentBinding"]
    assert binding_b["workflowRunId"] == workflow_run_b
    assert binding_b["workflowNodeId"] == "source_collection"

    # 派发的任务消息只进入自己 run 的 session。
    assert submitted[0]["sessionId"] == task_a1["sessionId"]
    assert submitted[1]["sessionId"] == task_a2["sessionId"]
    assert submitted[2]["sessionId"] == task_b["sessionId"]


def test_start_source_collection_ingestion_stage_routes_to_bound_source_ingestor(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    submitted: list[dict] = []

    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    ingestor = agent_directory_service.create_agent_instance(display_name="资料入库")
    ingestor_session = session_service.ensure_agent_direct_session(agent_id=ingestor["agentId"], title="资料入库")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料发现"},
            {"agentId": ingestor["agentId"], "role": "source_ingestor", "agentName": "资料入库"},
        ],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder", "source_ingestor"],
            "agentIds": {"source_finder": discovery["agentId"], "source_ingestor": ingestor["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    # Ingestion hard gate requires at least one ready source candidate for the run.
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Approved predictive coding source for ingestion routing",
            "sourceUrl": "https://doi.org/10.0000/ingestion-routing",
            "sourceKind": "paper",
            "summary": "Seed candidate so ingestion stage can open under product preflight.",
            "allowedForAnalysis": True,
            "qualityStatus": "approved",
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/ingestion-routing",
            },
            "createdByAgent": discovery["agentId"],
        },
    )

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted.append({"sessionId": session_id, "content": content, "kwargs": kwargs})
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-kb-admin-ingestion",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "ingestion",
            "agentId": ingestor["agentId"],
            "agentRole": "source_ingestor",
            "returnTo": "/teams?team=research-team&researchView=knowledge_collection&collectionStage=ingestion",
            "returnLabel": "返回资料入库",
        },
    )

    assert task["agentId"] == ingestor["agentId"]
    assert task["agentRole"] == "source_ingestor"
    assert task["sessionCreated"] is True
    assert task["sessionId"] != ingestor_session["id"]
    assert task["task"]["title"] == "资料入库任务"
    assert task["task"]["writesFormalKnowledge"] is True
    assert task["writebackContract"]["writesFormalKnowledge"] is True
    assert task["writebackContract"]["resultAuthority"] == "source_collection_stage_writeback_tool+knowledge_ingestion_gate"
    assert submitted[0]["sessionId"] == task["sessionId"]
    assert agent_directory_service.get_agent(ingestor["agentId"])["directSessionId"] == ingestor_session["id"]
    assert "资料入库任务" in submitted[0]["content"]
    assert "资料入库 Agent" in submitted[0]["content"]
    assert "共享记忆前审" not in submitted[0]["content"]
    assert "approved 候选" in submitted[0]["content"]
    assert "不要推断截断或隐藏候选" in submitted[0]["content"]
    assert "stewardActionPacket.approvedCandidateIds" in submitted[0]["content"]
    assert "writebackResultSkeleton" in submitted[0]["content"]
    assert "不要因为 `recordPage.hasMore=true` 或 `candidatePage.hasMore=true` 自动翻完整批次" in submitted[0]["content"]
    assert "如果返回的 `recordPage.hasMore=true`，必须继续按 `record_offset=recordPage.nextOffset` 分页读取" not in submitted[0]["content"]
    assert "如果返回的 `candidatePage.hasMore=true`，必须继续按 `candidate_offset=candidatePage.nextOffset` 分页读取" not in submitted[0]["content"]
    metadata = submitted[0]["kwargs"]["message_metadata"]
    assert metadata["agentId"] == ingestor["agentId"]
    assert metadata["agentRole"] == "source_ingestor"

def test_source_collection_stage_task_context_returns_bounded_records_for_extraction(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": "extraction-agent"},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    assignment_id = run_response["assignments"][0]["assignmentId"]
    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/predictive-coding",
            "rawLocation": "https://example.test/paper",
            "title": "Predictive coding for cortical hierarchy",
            "summary": "A relevant neural mechanism source.",
            "metadata": {
                "doi": "10.0000/predictive-coding",
                "containerTitle": "Neural Computation",
                "issued": "2026",
                "sourceCollectionTrace": {
                    "query": "brain-inspired routing",
                    "searchProvider": "crossref_rest_api",
                    "assignmentId": assignment_id,
                },
            },
        },
    )
    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "metadata-only-source",
            "title": "Unrelated mineral prediction",
            "summary": "A noisy Crossref result.",
            "metadata": {"containerTitle": "Geology Journal"},
        },
    )
    task = {
        "taskId": "stagetask-context",
        "runId": run_id,
        "stageId": "extraction",
        "agentId": "extraction-agent",
        "agentRole": "source_extractor",
        "sessionId": "session-extraction",
        "status": "running",
        "title": "资料提炼任务",
        "writebackContract": {"taskId": "stagetask-context"},
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-context",
        max_records=1,
    )

    assert context["status"] == "ok"
    assert context["stageId"] == "extraction"
    assert context["counts"]["recordCount"] == 2
    assert context["counts"]["returnedRecordCount"] == 1
    assert context["records"][0]["doi"] == "10.0000/predictive-coding"
    assert context["records"][0]["query"] == "brain-inspired routing"
    assert context["records"][0]["assignmentId"] == assignment_id
    assert context["usage"]["readTool"] == "source_collection_context_tool"
    assert context["usage"]["writebackTool"] == "source_collection_stage_writeback_tool"
    assert "file://" in context["usage"]["doNotUse"]

def test_source_collection_stage_task_context_pages_raw_records_when_candidates_absent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码资料提炼",
            "goal": "把原始 DataRecord 提炼成候选资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": "extraction-agent"},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    record_ids = []
    for index in range(3):
        record = data_processing_service.add_record(
            run_id,
            {
                "sourceType": "paper",
                "sourceRef": f"https://doi.org/10.0000/raw-record-page-{index}",
                "title": f"Predictive coding raw record {index}",
                "summary": "A candidate raw source that still needs extraction.",
                "metadata": {"doi": f"10.0000/raw-record-page-{index}"},
            },
        )
        record_ids.append(record["recordId"])
    task = {
        "taskId": "stagetask-record-page",
        "runId": run_id,
        "stageId": "extraction",
        "agentId": "extraction-agent",
        "agentRole": "source_extractor",
        "sessionId": "session-extraction",
        "status": "running",
        "title": "资料提炼任务",
        "writebackContract": {"taskId": "stagetask-record-page"},
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)

    first_page = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-record-page",
        record_offset=0,
        record_limit=2,
        candidate_limit=2,
    )
    second_page = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-record-page",
        record_offset=2,
        record_limit=2,
        candidate_limit=2,
    )

    assert first_page["counts"]["candidateCount"] == 0
    assert first_page["recordPage"]["total"] == 3
    assert first_page["recordPage"]["returned"] == 2
    assert first_page["recordPage"]["hasMore"] is True
    assert first_page["recordPage"]["nextOffset"] == 2
    assert first_page["recordIds"] == record_ids[:2]
    assert "record_offset=2" in first_page["usage"]["recordContinuationHint"]
    assert second_page["recordPage"]["hasMore"] is False
    assert second_page["recordIds"] == record_ids[2:]

def test_source_collection_stage_task_context_uses_lightweight_team_existence(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": "extraction-agent"},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/predictive-coding",
            "title": "Predictive coding for cortical hierarchy",
            "metadata": {"allowedForAnalysis": True},
        },
    )
    task = {
        "taskId": "stagetask-context-lightweight",
        "runId": run_id,
        "stageId": "extraction",
        "agentId": "extraction-agent",
        "agentRole": "source_extractor",
        "sessionId": "session-extraction",
        "status": "running",
        "title": "资料提炼任务",
        "writebackContract": {"taskId": "stagetask-context-lightweight"},
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)
    existence_reads = []

    def counted_assert_team_exists(team_id):
        existence_reads.append(team_id)
        return {"teamId": team_id}

    def fail_full_team_read(team_id):
        raise AssertionError("stage task context must not hydrate full team detail")

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "assert_team_exists", counted_assert_team_exists)
    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", fail_full_team_read)

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-context-lightweight",
        max_records=1,
    )

    assert context["status"] == "ok"
    assert context["counts"]["recordCount"] == 1
    assert existence_reads == [team["teamId"]]

def test_source_collection_stage_task_context_uses_source_ingestor_boundaries(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码",
            "agentRoles": ["source_ingestor"],
            "agentIds": {"source_ingestor": "agent-source-ingestor"},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    task = {
        "taskId": "stagetask-ingestion-context",
        "runId": run_id,
        "stageId": "ingestion",
        "agentId": "agent-source-ingestor",
        "agentRole": "source_ingestor",
        "sessionId": "session-ingestor",
        "status": "running",
        "title": "资料入库任务",
        "writebackContract": {
            "taskId": "stagetask-ingestion-context",
            "writesFormalKnowledge": True,
            "writesOfficialGraph": True,
        },
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-ingestion-context",
    )

    assert context["stageId"] == "ingestion"
    assert context["agentRole"] == "source_ingestor"
    assert context["boundaries"]["writesFormalKnowledge"] is True
    assert context["boundaries"]["writesOfficialGraph"] is True
    assert context["writebackContract"]["writesFormalKnowledge"] is True

def test_source_collection_stage_task_records_high_roi_runtime_events(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    events = _capture_workflow_events(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    monkeypatch.setattr(
        agent_directory_service,
        "resolve_tool_policy_for_agent",
        lambda agent_id, **kwargs: {
            "policyId": "tool-missing-stage-writeback",
            "allowedTools": ["source_collection_context_tool", "web_search_tool"],
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": False,
            "sessionId": session_id,
            "turnId": "",
            "status": "busy",
        },
    )

    created = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": discovery["agentId"],
            "agentRole": "source_finder",
            "idempotencyKey": "stage-click",
        },
    )
    # Once the canonical task/session/turn exists, an idempotent replay must
    # reuse that anchor without consulting the mutable Agent directory again.
    # This is the production outbox retry path after a long-running turn wait.
    monkeypatch.setattr(agent_directory_service, "get_agent", lambda _agent_id: None)
    reused = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "finding",
            "agentId": discovery["agentId"],
            "agentRole": "source_finder",
            "idempotencyKey": "stage-click",
        },
    )

    assert created["task"]["status"] == "queued"
    assert reused["alreadyPresent"] is True
    event_by_code = {args[2]: kwargs for args, kwargs in events}
    missing = event_by_code["source_collection.stage_session_task_tool_contract_missing"]
    assert missing["level"] == "warning"
    assert missing["outcome"] == "blocked"
    assert "source_collection_stage_writeback_tool" in missing["fields"]["missingTools"]
    assert "batch_web_search_tool" in missing["fields"]["missingTools"]
    not_accepted = event_by_code["source_collection.stage_session_task_submit_not_accepted"]
    assert not_accepted["fields"]["turnStatus"] == "busy"
    reused_event = event_by_code["source_collection.stage_session_task_reused"]
    assert reused_event["fields"]["taskId"] == created["taskId"]

def test_source_collection_stage_session_task_writeback_closes_running_turn_status(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-needs-review",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )

    result = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "needs_review",
            "summary": "搜索工具质量不足，但已回写可审查文献线索。",
            "result": {"candidate_leads": [{"title": "Predictive coding", "locator": "DOI:10.1038/4580"}]},
            "evidenceRefs": [{"type": "paper", "label": "lead-rao1999"}],
            "nextActions": ["资料寻找 Agent 打开 DOI 验证"],
        },
    )

    assert result["task"]["status"] == "needs_review"
    assert result["task"]["turn"]["status"] == "needs_review"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["turn"]["status"] == "needs_review"
    stored_task["turn"]["status"] = "running"
    team_workflow_orchestration_service._write_source_collection_stage_session_task_store(team["teamId"], run_id, task_store)

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    latest_round = status_payload["latestRound"]
    collection_card = next(card for card in latest_round["sourceCollectionStageCards"] if card["stageId"] == "finding")
    assert collection_card["agentTaskStatus"] == "needs_review"
    assert collection_card["latestTask"]["status"] == "needs_review"
    assert collection_card["status"] != "agent_running"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["turn"]["status"] == "needs_review"

def test_source_collection_stage_session_task_writeback_materializes_search_leads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "搜集可追踪资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-materialize",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    payload = {
        "status": "needs_review",
        "summary": "整理出两条可追踪线索和一条待定位线索。",
        "result": {
            "candidateLeads": [
                {
                    "leadId": "lead-01",
                    "title": "Predictive coding in the visual cortex",
                    "authors": "Rao RPN, Ballard DH",
                    "year": "1999",
                    "locator": "DOI: 10.1038/4580",
                    "sourceType": "paper",
                    "query": "predictive coding falsification failure result",
                    "perspective": "falsification",
                    "relevance": "预测编码奠基论文。",
                },
                {
                    "leadId": "lead-02",
                    "title": "A free energy principle for the brain",
                    "year": "2010",
                    "url": "https://doi.org/10.1038/nrn2787",
                    "sourceType": "review",
                    "relevance": "自由能原理综述。",
                },
                {
                    "leadId": "lead-03",
                    "title": "A vague paper without locator",
                    "year": "2020",
                    "locator": "DOI待查",
                    "sourceType": "paper",
                },
            ]
        },
    }

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(team["teamId"], task["taskId"], payload)

    materialized = first["writeback"]["materializedSources"]
    assert materialized["sourceLeadCount"] == 3
    assert materialized["createdRecordCount"] == 2
    assert materialized["importedCandidateCount"] == 2
    assert materialized["skippedCount"] == 1
    assert materialized["skipped"][0]["reason"] == "insufficient_source_identity"
    assert len(materialized["lineage"]) == 3
    assert [item["record"]["status"] for item in materialized["lineage"]] == [
        "created",
        "created",
        "failed",
    ]
    assert [item["candidate"]["status"] for item in materialized["lineage"]] == [
        "created",
        "created",
        "not_attempted",
    ]
    assert all(
        item["leadId"].startswith("lead-")
        and item["leadId"] not in {"lead-01", "lead-02", "lead-03"}
        and item["fingerprint"]
        for item in materialized["lineage"]
    )
    records = data_processing_service.list_records(run_id)
    assert records["summary"]["recordCount"] == 2
    assert records["records"][0]["metadata"]["perspective"] == "falsification"
    assert (
        records["records"][0]["metadata"]["sourceCollectionTrace"]["perspective"]
        == "falsification"
    )
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 2
    assert {item["metadata"]["doi"] for item in candidates["candidates"]} == {"10.1038/4580", "10.1038/nrn2787"}

    second = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(team["teamId"], task["taskId"], payload)

    assert second["writeback"]["materializedSources"]["createdRecordCount"] == 0
    assert second["writeback"]["materializedSources"]["importedCandidateCount"] == 0
    assert second["writeback"]["materializedSources"]["skippedDuplicateCount"] == 2
    replay_lineage = second["writeback"]["materializedSources"]["lineage"]
    assert [item["record"]["status"] for item in replay_lineage] == [
        "reused",
        "reused",
        "failed",
    ]
    assert [item["candidate"]["status"] for item in replay_lineage] == [
        "reused",
        "reused",
        "not_attempted",
    ]
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 2
    assert team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidateCount"] == 2
    writeback_events = _workflow_scene_events_by_code(scene_events, "source_collection.stage_session_task_writeback")
    assert writeback_events[-1]["child_log_payload"]["kind"] == "source_collection_stage_writeback_materialization"
    assert writeback_events[-1]["child_log_payload"]["materializedSources"]["status"] == "completed"
    assert writeback_events[-1]["child_log_payload"]["materializedSources"]["skippedDuplicateCount"] == 2
    assert writeback_events[-1]["child_log_payload"]["materializedSourceQuality"]["status"] == "skipped_stage"
    assert writeback_events[-1]["child_log_payload"]["materializedCandidateGraph"]["status"] == "skipped_stage"
    assert writeback_events[-1]["child_log_payload"]["materializedKnowledgeIngestion"]["status"] == "skipped_stage"

def test_source_collection_stage_session_task_writeback_materializes_source_records_alias(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "搜集可追踪资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-source-records",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已发现 1 条核心论文，并排除 1 条无效来源。",
            "result": {
                "source_records": [
                    {
                        "title": "Predictive coding in the visual cortex",
                        "authors": "Rao RPN, Ballard DH",
                        "year": "1999",
                        "doi": "10.1038/4580",
                        "sourceType": "paper",
                        "summary": "预测编码奠基论文。",
                    }
                ],
                "invalid_sources": [
                    {
                        "title": "Unrelated machining paper",
                        "sourceRef": "https://example.com/noise",
                        "reason": "out_of_scope",
                    }
                ],
            },
        },
    )

    materialized = response["writeback"]["materializedSources"]
    assert response["task"]["status"] == "needs_review"
    assert response["task"]["result"]["closureSummary"]["artifactComplete"] is True
    assert response["task"]["result"]["closureSummary"]["completionGatePassed"] is False
    assert response["task"]["result"]["closureSummary"]["taskToolProgress"]["taskCreateObserved"] is False
    assert materialized["sourceLeadCount"] == 1
    assert materialized["createdRecordCount"] == 1
    assert materialized["importedCandidateCount"] == 1
    assert materialized["excludedSourceCount"] == 1
    assert materialized["excludedSources"][0]["reason"] == "out_of_scope"
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 1
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 1
    _append_stage_task_tool_trace(tmp_path, response["task"])

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    latest_round = status_payload["latestRound"]
    collection_card = next(card for card in latest_round["sourceCollectionStageCards"] if card["stageId"] == "finding")
    assert collection_card["latestTask"]["status"] == "completed"
    assert collection_card["latestTask"]["closureSummary"]["completionGatePassed"] is True
    assert collection_card["latestTask"]["closureSummary"]["taskToolProgress"]["completed"] == len(response["task"]["taskChecklist"])

def test_source_collection_stage_session_task_writeback_rejects_leads_without_identity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-invalid-lead",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        stage_response["run"]["runId"],
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "只有一条缺少 locator 的线索。",
            "result": {"source_records": [{"title": "A vague source without locator", "year": "2020"}]},
        },
    )

    assert response["task"]["status"] == "needs_review"
    materialized = response["writeback"]["materializedSources"]
    assert materialized["sourceLeadCount"] == 1
    assert materialized["createdRecordCount"] == 0
    assert materialized["importedCandidateCount"] == 0
    assert materialized["skippedCount"] == 1
    assert response["task"]["result"]["closureSummary"]["artifactComplete"] is False
    assert response["task"]["result"]["closureSummary"]["completionGatePassed"] is False

def test_source_ingestor_writeback_auto_ingests_high_confidence_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]
    ingestor = next(member for member in team["members"] if member["role"] == "source_ingestor")
    ingestor_agent_id = ingestor["agentId"]
    ingestor_session = session_service.ensure_agent_direct_session(agent_id=ingestor_agent_id, title="资料入库")
    agent_directory_service.update_agent_instance(ingestor_agent_id, direct_session_id=ingestor_session["id"])
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Knowledge Expansion Library",
        actor_agent_id=ingestor_agent_id,
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "workflowPurpose": "knowledge_expansion",
            "collectionMode": "web_search",
            "topic": "predictive coding",
            "agentRoles": ["source_finder", "source_extractor", "source_ingestor"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "candidateType": "source_manifest",
            "title": "Predictive coding cortical hierarchy",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "High-confidence source for predictive coding.",
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/predictive-coding",
            },
            "createdByAgent": "knowledge-expansion-source-finder",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": "knowledge-expansion-source-extractor",
            "decision": "approved",
            "notes": "Source is traceable and relevant.",
        },
    )
    pack_output = _steward_pack_output(candidate_ids=[source["candidateId"]], confidence=0.92)
    pack_output.update(
        {
            "targetDomain": "team_knowledge_expansion",
            "sourceTrace": {
                "sourceIds": [source["candidateId"]],
                "sourceCollectionRunId": run_id,
            },
            "riskSummary": "Traceable source with high confidence; suitable for governed Team Knowledge.",
            "proposalPayload": {
                "title": "Predictive coding cortical hierarchy",
                "summary": "Add predictive coding hierarchy as governed Team Knowledge.",
            },
            "ratingSuggestion": {
                "importanceLevel": "high",
                "confidence": 0.92,
                "stability": "evolving",
                "reviewPriority": "elevated",
            },
        }
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-knowledge-expansion-ingestor",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor_agent_id, "agentRole": "source_ingestor"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "资料入库 Agent 已审核并入库高置信资料。",
            "result": {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "stewardPackDraft": pack_output,
                "autoIngestDecision": {
                    "decision": "approved",
                    "confidence": 0.92,
                    "reason": "Source quality approved and steward confidence is high.",
                },
            },
            "recordedByAgent": ingestor_agent_id,
            "evidenceRefs": [{"kind": "candidate", "ref": source["candidateId"]}],
            "nextActions": ["继续下一轮知识扩充"],
        },
    )
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base["knowledgeBaseId"],
        agent_id=ingestor_agent_id,
    )
    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)
    ingestion_card = next(card for card in projection["cards"] if card["stageId"] == "ingestion")

    assert response["task"]["writesFormalKnowledge"] is True
    assert response["writeback"]["materializedKnowledgeIngestion"]["status"] == "completed"
    assert response["writeback"]["materializedKnowledgeIngestion"]["approvedCandidateCount"] == 1
    assert response["writeback"]["materializedKnowledgeIngestion"]["formalKnowledgeItemCount"] == 1
    assert knowledge_items["summary"]["itemCount"] == 1
    assert response["task"]["status"] == "needs_review"
    assert response["task"]["result"]["closureSummary"]["completionGatePassed"] is False
    assert ingestion_card["status"] == "artifact_ready_agent_needs_review"
    _append_stage_task_tool_trace(tmp_path, response["task"])

    team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)
    ingestion_card = next(card for card in projection["cards"] if card["stageId"] == "ingestion")
    assert ingestion_card["status"] == "closed_loop"
    assert ingestion_card["counts"]["output"] == 1
    assert ingestion_card["latestTask"]["materializedKnowledgeIngestion"]["status"] == "completed"
    assert ingestion_card["latestTask"]["closureSummary"]["completionGatePassed"] is True
    ingestion_events = _workflow_scene_events_by_code(scene_events, "source_collection.stage_session_task_knowledge_ingestion_materialized")
    assert ingestion_events[-1]["child_log_payload"]["kind"] == "source_collection_stage_knowledge_ingestion_materialization"
    assert ingestion_events[-1]["child_log_payload"]["status"] == "completed"
    assert ingestion_events[-1]["child_log_payload"]["steps"][0]["stageId"] == "auto_ingest_gate"
    assert ingestion_events[-1]["child_log_payload"]["steps"][-1]["stageId"] == "official_sync"
    assert ingestion_events[-1]["child_log_payload"]["formalKnowledgeItemIds"] == response["writeback"]["materializedKnowledgeIngestion"]["formalKnowledgeItemIds"]

def test_source_ingestor_writeback_reuses_existing_knowledge_expansion_library_when_request_id_missing(tmp_path, monkeypatch):
    """缺省 knowledgeBaseId 的重试必须复用同名既有库，而不是每次新建。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]
    ingestor = next(member for member in team["members"] if member["role"] == "source_ingestor")
    ingestor_agent_id = ingestor["agentId"]
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "workflowPurpose": "knowledge_expansion",
            "collectionMode": "web_search",
            "topic": "predictive coding",
            "agentRoles": ["source_finder", "source_extractor", "source_ingestor"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]

    def register_approved_source(title: str, doi_slug: str) -> str:
        source = team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "candidateType": "source_manifest",
                "title": title,
                "sourceUrl": f"https://doi.org/10.0000/{doi_slug}",
                "sourceKind": "paper",
                "summary": "High-confidence source for predictive coding.",
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/{doi_slug}"},
                "createdByAgent": "knowledge-expansion-source-finder",
            },
        )["candidate"]
        team_workflow_orchestration_service.assess_source_candidate_quality(
            team["teamId"],
            source["candidateId"],
            {
                "assessedByAgent": "knowledge-expansion-source-extractor",
                "decision": "approved",
                "notes": "Source is traceable and relevant.",
            },
        )
        return source["candidateId"]

    def materialize_without_knowledge_base_id(candidate_id: str, task_id: str) -> dict:
        pack_output = _steward_pack_output(candidate_ids=[candidate_id], confidence=0.92)
        pack_output.update(
            {
                "targetDomain": "team_knowledge_expansion",
                "sourceTrace": {"sourceIds": [candidate_id], "sourceCollectionRunId": run_id},
                "riskSummary": "Traceable source with high confidence; suitable for governed Team Knowledge.",
                "proposalPayload": {
                    "title": "Predictive coding cortical hierarchy",
                    "summary": "Add predictive coding hierarchy as governed Team Knowledge.",
                },
                "ratingSuggestion": {
                    "importanceLevel": "high",
                    "confidence": 0.92,
                    "stability": "evolving",
                    "reviewPriority": "elevated",
                },
            }
        )
        task = {
            "taskId": task_id,
            "stageId": "ingestion",
            "agentRole": "source_ingestor",
            "agentId": ingestor_agent_id,
        }
        writeback = {
            "status": "completed",
            "summary": "资料入库 Agent 已审核并入库高置信资料。",
            "result": {
                # 故意缺省 knowledgeBaseId：命中自动复用/建库分支。
                "stewardPackDraft": pack_output,
                "autoIngestDecision": {
                    "decision": "approved",
                    "confidence": 0.92,
                    "reason": "Source quality approved and steward confidence is high.",
                },
            },
            "recordedByAgent": ingestor_agent_id,
        }
        return team_workflow_orchestration_service._materialize_source_collection_stage_writeback_knowledge_ingestion(
            team["teamId"],
            run_id,
            task,
            writeback,
        )

    first = materialize_without_knowledge_base_id(
        register_approved_source("Predictive coding cortical hierarchy", "predictive-coding"),
        "task-kb-dedupe-1",
    )
    second = materialize_without_knowledge_base_id(
        register_approved_source("Predictive coding follow-up", "predictive-coding-follow-up"),
        "task-kb-dedupe-2",
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert first["knowledgeBaseId"] == second["knowledgeBaseId"]
    assert first["scopedKnowledgeBaseId"] == second["scopedKnowledgeBaseId"]
    bases = team_knowledge_service.list_team_knowledge_bases(team["teamId"], internal=True)["knowledgeBases"]
    assert [str(item.get("name") or "") for item in bases] == ["Knowledge Expansion Library"]

def test_source_ingestor_writeback_auto_ingests_approved_candidate_summary(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]
    ingestor = next(member for member in team["members"] if member["role"] == "source_ingestor")
    ingestor_agent_id = ingestor["agentId"]
    ingestor_session = session_service.ensure_agent_direct_session(agent_id=ingestor_agent_id, title="资料入库")
    agent_directory_service.update_agent_instance(ingestor_agent_id, direct_session_id=ingestor_session["id"])
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Knowledge Expansion Library",
        actor_agent_id=ingestor_agent_id,
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "workflowPurpose": "knowledge_expansion",
            "collectionMode": "web_search",
            "topic": "predictive coding",
            "agentRoles": ["source_finder", "source_extractor", "source_ingestor"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "candidateType": "source_manifest",
            "title": "Predictive coding candidate summary source",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding-summary",
            "sourceKind": "paper",
            "summary": "High-confidence candidate summary source.",
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/predictive-coding-summary",
            },
            "createdByAgent": "knowledge-expansion-source-finder",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": "knowledge-expansion-source-extractor",
            "decision": "approved",
            "notes": "Source is traceable and relevant.",
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-knowledge-expansion-ingestor-summary",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor_agent_id, "agentRole": "source_ingestor"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "资料入库 Agent 通过 1 条候选，进入正式入库。",
            "result": {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "candidate_summary": {
                    "approved": {
                        "count": 1,
                        "candidates": [
                            {
                                "candidateId": source["candidateId"],
                                "title": source["title"],
                                "overall_score": 92,
                                "assessment_notes": "可直接进入知识库扩充。",
                            }
                        ],
                    }
                },
                "steward_assessment": {"decision": "approved", "targetDomain": "team_knowledge_expansion"},
            },
            "recordedByAgent": ingestor_agent_id,
            "evidenceRefs": [{"kind": "candidate", "ref": source["candidateId"]}],
            "nextActions": ["继续下一轮知识扩充"],
        },
    )
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base["knowledgeBaseId"],
        agent_id=ingestor_agent_id,
    )

    assert response["writeback"]["materializedKnowledgeIngestion"]["status"] == "completed"
    assert response["writeback"]["materializedKnowledgeIngestion"]["approvedCandidateCount"] == 1
    assert response["writeback"]["materializedKnowledgeIngestion"]["formalKnowledgeItemCount"] == 1
    assert response["task"]["writesFormalKnowledge"] is True
    assert knowledge_items["summary"]["itemCount"] == 1

def test_research_stage_status_materializes_legacy_stage_task_writeback_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "补齐历史任务资料池",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-legacy-materialize",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    legacy_result = {
        "candidateLeads": [
            {
                "leadId": "lead-legacy-01",
                "title": "Predictive coding in the visual cortex",
                "authors": "Rao RPN, Ballard DH",
                "year": "1999",
                "locator": "DOI: 10.1038/13067 (Nature Neuroscience)",
                "sourceType": "paper",
            },
            {
                "leadId": "lead-legacy-02",
                "title": "The free-energy principle: a unified brain theory?",
                "year": "2010",
                "locator": "DOI: 10.1038/nrn2787 (Nature Reviews Neuroscience)",
                "sourceType": "review",
            },
            {
                "leadId": "lead-legacy-03",
                "title": "Unverified predictive coding lead",
                "year": "2022",
                "locator": "DOI待查",
                "sourceType": "paper",
            },
        ]
    }
    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in store["tasks"] if item["taskId"] == task["taskId"])
    stored_task["status"] = "needs_review"
    stored_task["summary"] = "旧任务已经回写候选线索，但尚未物化资料池。"
    stored_task["result"] = legacy_result
    stored_task["writeback"] = {
        "status": "needs_review",
        "summary": stored_task["summary"],
        "result": legacy_result,
        "resultAuthority": "source_collection_stage_writeback_tool",
        "updatedAt": "2026-06-23T00:00:00+00:00",
    }
    team_workflow_orchestration_service._write_source_collection_stage_session_task_store(team["teamId"], run_id, store)
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 0
    assert team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidateCount"] == 0

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled_ref = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled_ref["status"] == "needs_review"
    records = data_processing_service.list_records(run_id)
    assert records["summary"]["recordCount"] == 2
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 2
    assert {item["metadata"]["doi"] for item in candidates["candidates"]} == {"10.1038/13067", "10.1038/nrn2787"}
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    reconciled_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    materialized = reconciled_task["writeback"]["materializedSources"]
    assert materialized["sourceLeadCount"] == 3
    assert materialized["createdRecordCount"] == 2
    assert materialized["importedCandidateCount"] == 2
    assert materialized["skippedCount"] == 1
    assert materialized["skipped"][0]["reason"] == "insufficient_source_identity"

    team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 2
    assert team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidateCount"] == 2

def test_research_stage_status_repairs_missing_round_and_projects_stage_cards(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    extraction = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=extraction["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": extraction["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "提炼本轮候选资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": extraction["agentId"]},
            "querySeeds": ["brain inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-candidate",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": extraction["agentId"], "agentRole": "source_extractor"},
    )
    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in store["tasks"] if item["taskId"] == task["taskId"])
    stored_task["status"] = "completed"
    stored_task["summary"] = "已在私聊完成资料提炼，但尚未生成团队候选资料卡。"
    stored_task["result"] = {
        "evidenceItems": [
            {"title": f"Evidence {index}", "url": f"https://example.test/evidence-{index}"}
            for index in range(1, 6)
        ],
        "nextActions": ["补 DOI", "筛选来源", "构建图谱", "准备入库预检"],
    }
    stored_task["evidenceRefs"] = [{"kind": "evidence", "ref": f"ev-{index}"} for index in range(1, 6)]
    stored_task["nextActions"] = ["补 DOI", "筛选来源", "构建图谱", "准备入库预检"]
    stored_task["writeback"] = {
        "status": "completed",
        "summary": stored_task["summary"],
        "result": stored_task["result"],
        "resultAuthority": "source_collection_stage_writeback_tool",
        "updatedAt": "2026-06-24T05:06:17+00:00",
    }
    team_workflow_orchestration_service._write_source_collection_stage_session_task_store(team["teamId"], run_id, store)
    round_store_path = team_workflow_orchestration_service._stage_round_store_path(team["teamId"])
    team_workflow_orchestration_service._write_json(
        round_store_path,
        {"schemaVersion": 1, "teamId": team["teamId"], "rounds": [], "updatedAt": "2026-06-24T05:00:00+00:00"},
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    assert status_payload["roundCount"] == 1
    latest_round = status_payload["latestRound"]
    assert latest_round["stageType"] == "knowledge_collection"
    assert latest_round["sourceRunIds"] == [run_id]
    assert any(item["taskId"] == task["taskId"] for item in latest_round["sourceCollectionStageSessionTasks"])
    cards = latest_round["sourceCollectionStageCards"]
    assert len(cards) == 4
    card_by_stage = {card["stageId"]: card for card in cards}
    assert set(card_by_stage) == {"finding", "extraction", "relations", "ingestion"}
    candidate_card = card_by_stage["extraction"]
    assert candidate_card["status"] == "agent_done_artifact_pending"
    assert candidate_card["agentTaskStatus"] == "needs_review"
    assert candidate_card["artifactStatus"] == "empty"
    assert candidate_card["counts"]["artifact"] == 0
    assert candidate_card["latestTask"]["taskId"] == task["taskId"]
    assert candidate_card["latestTask"]["status"] == "needs_review"
    assert candidate_card["latestTask"]["closureSummary"]["completionGatePassed"] is False
    assert candidate_card["latestTask"]["evidenceRefCount"] == 5
    assert candidate_card["latestTask"]["nextActionCount"] == 4
    assert candidate_card["blockingReasons"]
    assert {"evidenceItems", "nextActions"} <= set(candidate_card["resultKeys"])
    assert latest_round["sourceCollectionStageCardSummary"]["closedLoopCount"] == 0

def test_source_collection_stage_card_projection_is_scoped_to_current_run_artifacts(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_one = data_processing_service.create_processing_run(
        title="Knowledge collection round 1",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    record_one = data_processing_service.add_record(
        run_one["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/round-one",
            "title": "Round one neural evidence",
            "summary": "Evidence from the first collection round.",
        },
    )
    source_one = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_one["runId"],
        record_one["recordId"],
        {"createdByAgent": "content-extraction-agent"},
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source_one["candidateId"],
        {
            "decision": "approved",
            "assessedByAgent": "source-quality-agent",
            "notes": "第一轮来源通过。",
            "relevanceScore": 85,
            "traceabilityScore": 80,
            "credibilityScore": 80,
        },
    )
    graph_response = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {"createdByAgent": "candidate-graph-agent", "curationMode": "agent_approved_only", "forceRebuild": True},
    )
    steward_response = team_workflow_orchestration_service.run_knowledge_ingestion_precheck(
        team["teamId"],
        {"stewardAgentId": "knowledge-steward-agent", "forceRebuild": True},
    )

    run_two = data_processing_service.create_processing_run(
        title="Knowledge collection round 2",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    record_two = data_processing_service.add_record(
        run_two["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/round-two",
            "title": "Round two neural evidence",
            "summary": "Evidence from the second collection round.",
        },
    )
    source_two = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_two["runId"],
        record_two["recordId"],
        {"createdByAgent": "content-extraction-agent"},
    )["candidate"]

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_two["runId"])

    card_by_stage = {card["stageId"]: card for card in projection["cards"]}
    assert source_one["candidateId"] in graph_response["candidateGraph"]["metadata"]["generatedFromCandidateIds"]
    assert source_one["candidateId"] in steward_response["candidate"]["metadata"]["output"]["candidateIds"]
    assert source_two["candidateId"] not in graph_response["candidateGraph"]["metadata"]["generatedFromCandidateIds"]
    assert projection["summary"]["sourceCandidateCount"] == 1
    assert projection["summary"]["graphNodeCount"] == 0
    assert projection["summary"]["stewardPackCount"] == 0
    assert projection["summary"]["formalKnowledgeSyncCount"] == 0
    assert card_by_stage["extraction"]["status"] == "pending"
    assert card_by_stage["extraction"]["counts"]["artifact"] == 1
    assert card_by_stage["relations"]["status"] == "idle"
    assert card_by_stage["relations"]["counts"]["input"] == 0
    assert card_by_stage["relations"]["counts"]["artifact"] == 0
    assert card_by_stage["ingestion"]["status"] == "idle"
    assert card_by_stage["ingestion"]["counts"]["input"] == 0
    assert card_by_stage["ingestion"]["counts"]["artifact"] == 0

def test_source_collection_stage_card_projection_ignores_stale_agent_tasks_for_current_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    current_agent = agent_directory_service.create_agent_instance(display_name="当前资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": current_agent["agentId"], "role": "source_extractor", "agentName": "当前资料提炼"}],
    )
    run = data_processing_service.create_processing_run(
        title="Knowledge collection current round",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    record = data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/current-round",
            "title": "Current round source",
            "summary": "Evidence from the current collection round.",
        },
    )
    source = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run["runId"],
        record["recordId"],
        {"createdByAgent": current_agent["agentId"]},
    )["candidate"]
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        {
            "taskId": "stagetask-stale-candidate",
            "runId": run["runId"],
            "stageId": "candidate",
            "agentId": "agent-old-content-extraction",
            "agentRole": "source_extractor",
            "sessionId": "session-old-content-extraction",
            "status": "running",
            "summary": "旧会话的资料提炼任务仍显示运行中。",
            "createdAt": "2026-06-20T00:00:00+00:00",
            "updatedAt": "2026-06-20T00:00:00+00:00",
        },
    )

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run["runId"])

    candidate_card = next(item for item in projection["cards"] if item["stageId"] == "extraction")
    assert source["candidateId"]
    assert candidate_card["status"] == "pending"
    assert candidate_card["agentTaskStatus"] == "not_started"
    assert candidate_card["latestTask"] == {}
    assert candidate_card["counts"]["task"] == 0
    assert candidate_card["counts"]["historicalTask"] == 0

def test_source_collection_stage_card_projection_closes_finding_with_downstream_assignments_open(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    finder = agent_directory_service.create_agent_instance(display_name="资料寻找")
    extractor = agent_directory_service.create_agent_instance(display_name="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"},
            {"agentId": extractor["agentId"], "role": "source_extractor", "agentName": "资料提炼"},
        ],
    )
    run = data_processing_service.create_processing_run(
        title="Knowledge collection current round",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    finder_assignment = data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_finder", "agentId": finder["agentId"]},
    )
    data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_extractor", "agentId": extractor["agentId"]},
    )
    data_processing_service.record_collection_output(
        run["runId"],
        finder_assignment["assignmentId"],
        {
            "status": "completed",
            "records": [
                {
                    "sourceType": "paper",
                    "sourceRef": "https://doi.org/10.0000/finder-done",
                    "title": "Finder completed source",
                }
            ],
        },
    )
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        {
            "taskId": "stagetask-finder-completed",
            "runId": run["runId"],
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "sessionId": "session-finder-completed",
            "status": "completed",
            "summary": "资料寻找已完成并产出资料。",
            "createdAt": "2026-06-30T00:00:00+00:00",
            "updatedAt": "2026-06-30T00:00:00+00:00",
        },
    )

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run["runId"])

    finding_card = next(item for item in projection["cards"] if item["stageId"] == "finding")
    assert finding_card["status"] == "closed_loop"
    assert finding_card["counts"]["pending"] == 0
    assert finding_card["counts"]["searchOpenAssignment"] == 0
    assert finding_card["counts"]["downstreamOpenAssignment"] == 1
    assert "0 search assignments remain" in finding_card["artifactSummary"]

def test_source_collection_stage_card_projection_ignores_stale_finder_assignment_after_verified_completion(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    finder = agent_directory_service.create_agent_instance(display_name="Source finder")
    team = team_service.create_team(
        name="Research team",
        members=[
            {
                "agentId": finder["agentId"],
                "role": "source_finder",
                "agentName": "Source finder",
            }
        ],
    )
    run = data_processing_service.create_processing_run(
        title="Knowledge collection current round",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    completed_assignment = data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_finder", "agentId": finder["agentId"]},
    )
    data_processing_service.record_collection_output(
        run["runId"],
        completed_assignment["assignmentId"],
        {
            "status": "completed",
            "records": [
                {
                    "sourceType": "paper",
                    "sourceRef": "https://doi.org/10.0000/verified-finding",
                    "title": "Verified finding",
                }
            ],
        },
    )
    data_processing_service.create_collection_assignment(
        run["runId"],
        {"agentRole": "source_finder", "agentId": finder["agentId"]},
    )
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        {
            "taskId": "stagetask-finder-verified",
            "runId": run["runId"],
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "sessionId": "session-finder-verified",
            "status": "completed",
            "summary": "The current finding checklist and artifact gate passed.",
            "completionGate": {"passed": True},
            "createdAt": "2026-07-24T12:00:00+00:00",
            "updatedAt": "2026-07-24T12:00:00+00:00",
        },
    )

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(
        team["teamId"],
        run["runId"],
    )

    finding_card = next(item for item in projection["cards"] if item["stageId"] == "finding")
    assert finding_card["status"] == "closed_loop"
    assert finding_card["counts"]["pending"] == 0
    assert finding_card["counts"]["searchOpenAssignment"] == 1

def test_source_collection_stage_card_projection_suppresses_interrupted_task_after_one_click_completion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "completion-work-runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_knowledge_ingestion_work_run_store",
        lambda: isolated_store,
    )
    finder = agent_directory_service.create_agent_instance(display_name="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run = data_processing_service.create_processing_run(
        title="Knowledge collection current round",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/one-click-supersedes-interrupt",
            "title": "One-click completion source",
        },
    )
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run["runId"],
        {
            "taskId": "stagetask-interrupted-before-completion",
            "runId": run["runId"],
            "stageId": "finding",
            "agentId": finder["agentId"],
            "agentRole": "source_finder",
            "sessionId": "session-finder-interrupted",
            "status": "interrupted",
            "summary": "Agent 私聊在阶段回写前中断。",
            "createdAt": "2026-07-07T22:47:27+08:00",
            "updatedAt": "2026-07-07T22:50:55+08:00",
        },
    )
    isolated_store.persist_snapshot(
        team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        {
            "runId": "knowledge-completion-supersedes-interrupted-task",
            "runKind": team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
            "kind": team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
            "teamId": team["teamId"],
            "status": "completed",
            "currentPhase": "completed",
            "sourceRunId": run["runId"],
            "flowVisualization": {
                "kind": "knowledge_collection_completion",
                "schemaVersion": team_workflow_orchestration_service.SCHEMA_VERSION,
                "status": "completed",
                "currentStageId": "",
                "nodes": [
                    {"stageId": "finding", "agentRole": "source_finder", "status": "executed"},
                    {"stageId": "extraction", "agentRole": "source_extractor", "status": "completed"},
                    {"stageId": "relations", "agentRole": "source_relation_mapper", "status": "completed"},
                    {"stageId": "ingestion", "agentRole": "source_ingestor", "status": "completed"},
                ],
            },
            "updatedAt": "2026-07-08T00:27:17+08:00",
        },
    )

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run["runId"])

    finding_card = next(item for item in projection["cards"] if item["stageId"] == "finding")
    assert finding_card["status"] == "artifact_ready_no_latest_agent_task"
    assert finding_card["agentTaskStatus"] == "not_started"
    assert finding_card["latestTask"] == {}
    assert finding_card["counts"]["historicalTask"] == 1

def test_source_collection_stage_card_projection_does_not_close_partial_needs_review_artifacts():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "stagetask-needs-review",
                "stageId": "extraction",
                "agentId": "source-extractor-agent",
                "agentRole": "source_extractor",
                "sessionId": "session-source-extractor",
                "status": "needs_review",
                "summary": "Agent 已回写部分审查结果，但还有候选资料待审。",
                "updatedAt": "2026-06-25T00:00:00+00:00",
            }
        ],
        artifact_count=10,
        input_count=10,
        output_count=1,
        pending_count=5,
        artifact_status="partial",
        artifact_summary="5/10 source candidates assessed; 1 approved.",
    )

    assert card["status"] == "partial_current_inputs"
    assert card["isClosedLoop"] is False
    assert card["agentTaskStatus"] == "needs_review"
    assert card["counts"]["pending"] == 5
    assert card["currentCoverageSummary"]["processed"] == 5
    assert card["currentCoverageSummary"]["total"] == 10
    assert card["blockingReasons"]

def test_source_collection_stage_card_projection_reports_processed_inputs_that_need_evidence():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "stagetask-extraction-needs-evidence",
                "stageId": "extraction",
                "agentId": "source-extractor-agent",
                "agentRole": "source_extractor",
                "sessionId": "session-source-extractor",
                "status": "needs_review",
                "summary": "34 条候选资料均已提炼，但缺少可核验的证据锚点。",
                "updatedAt": "2026-07-15T15:20:36+00:00",
                "result": {
                    "coverageSummary": {
                        "applicable": True,
                        "coverageKind": "candidate_extractions",
                        "complete": True,
                        "total": 34,
                        "processed": 34,
                        "missing": 0,
                        "invalid": 0,
                        "blocked": 34,
                    },
                    "closureSummary": {
                        "userStatus": "success",
                        "message": "已生成 34 个候选资料，本阶段闭环成功。",
                    },
                },
            }
        ],
        artifact_count=34,
        input_count=34,
        output_count=0,
        pending_count=34,
        artifact_status="partial",
        artifact_summary="34 source_manifest candidates; 0/34 assessed; 0 approved.",
    )

    assert card["status"] == "partial_current_inputs"
    assert card["isClosedLoop"] is False
    assert card["currentCoverageSummary"]["processed"] == 34
    assert card["currentCoverageSummary"]["total"] == 34
    assert card["currentCoverageSummary"]["missing"] == 0
    assert card["currentCoverageSummary"]["blocked"] == 34
    assert "已处理 34/34" in card["userSummary"]
    assert "34 条需要补充证据" in card["userSummary"]
    assert "闭环成功" not in card["userSummary"]
    assert any("34 条需要补充证据" in reason for reason in card["blockingReasons"])


def test_source_collection_stage_card_projection_accepts_completed_superset_after_supersession():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "stagetask-extraction-superseded-version",
                "stageId": "extraction",
                "agentId": "source-extractor-agent",
                "agentRole": "source_extractor",
                "sessionId": "session-source-extractor",
                "status": "needs_review",
                "summary": "14 条候选资料均已提炼；版本归并后当前有效候选为 13 条。",
                "updatedAt": "2026-08-01T15:24:58+08:00",
                "result": {
                    "coverageSummary": {
                        "applicable": True,
                        "coverageKind": "candidate_extractions",
                        "complete": True,
                        "total": 14,
                        "processed": 14,
                        "missing": 0,
                        "invalid": 0,
                        "blocked": 14,
                    },
                },
            }
        ],
        artifact_count=13,
        input_count=14,
        output_count=0,
        pending_count=13,
        artifact_status="partial",
        artifact_summary="13 current candidates; all require evidence supplementation.",
    )

    assert card["status"] == "partial_current_inputs"
    assert card["isClosedLoop"] is False
    assert card["currentCoverageSummary"] == {
        "applicable": True,
        "coverageKind": "candidate_extractions",
        "complete": True,
        "total": 13,
        "processed": 13,
        "missing": 0,
        "invalid": 0,
        "blocked": 13,
        "duplicate": 0,
    }
    assert card["userStatusLabel"] == "提炼完成，待补证据"
    assert card["actionReadiness"]["reasonCode"] == "evidence_supplement_required"
    assert card["actionReadiness"]["actionLabel"] == "Agent 补充证据"
    assert "已处理 13/13" in card["userSummary"]
    assert "13 条需要补充证据" in card["userSummary"]


def test_source_collection_stage_card_projection_marks_stale_success_as_partial_current_inputs():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "stagetask-extraction-previous-success",
                "stageId": "extraction",
                "agentId": "source-extractor-agent",
                "agentRole": "source_extractor",
                "sessionId": "session-source-extractor",
                "status": "completed",
                "summary": "Agent completed the previous 15 candidates.",
                "updatedAt": "2026-06-30T00:00:00+00:00",
                "result": {
                    "coverageSummary": {
                        "applicable": True,
                        "coverageKind": "candidate_extractions",
                        "complete": True,
                        "total": 15,
                        "processed": 15,
                        "missing": 0,
                        "invalid": 0,
                    }
                },
            }
        ],
        artifact_count=21,
        input_count=26,
        output_count=15,
        pending_count=6,
        artifact_status="partial",
        artifact_summary="21 source_manifest candidates; 15/21 assessed; 15 approved.",
    )

    assert card["status"] == "partial_current_inputs"
    assert card["isClosedLoop"] is False
    assert card["latestTask"]["coverageSummary"]["processed"] == 15
    assert card["latestTask"]["coverageSummary"]["total"] == 15
    assert card["currentCoverageSummary"]["processed"] == 15
    assert card["currentCoverageSummary"]["total"] == 21
    assert card["currentCoverageSummary"]["missing"] == 6
    assert any("当前阶段覆盖不足" in reason for reason in card["blockingReasons"])

def test_source_collection_stage_card_projection_counts_approved_sources_pending_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队", members=[])
    run = data_processing_service.create_processing_run(
        title="Knowledge collection current round",
        scope={"teamId": team["teamId"], "workflowStage": "knowledge_collection"},
        metadata={"startedFrom": "team_workflow_source_collection"},
    )
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "candidateType": "source_manifest",
            "title": "Predictive coding source",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding-source",
            "sourceKind": "paper",
            "summary": "Relevant predictive coding source.",
            "metadata": {"sourceCollectionRunId": run["runId"]},
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {"decision": "approved", "notes": "Ready for ingestion."},
    )

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run["runId"])

    ingestion_card = next(item for item in projection["cards"] if item["stageId"] == "ingestion")
    assert ingestion_card["status"] == "pending"
    assert ingestion_card["counts"]["input"] == 1
    assert ingestion_card["counts"]["pending"] == 1
    assert ingestion_card["currentCoverageSummary"]["total"] == 1
    assert ingestion_card["currentCoverageSummary"]["missing"] == 1
    relations_card = next(item for item in projection["cards"] if item["stageId"] == "relations")
    assert relations_card["counts"]["input"] == 1
    assert relations_card["counts"]["pending"] == 1

def test_research_stage_status_reconciles_completed_stage_task_turn_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-completed",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    events_path = tmp_path / "workspace" / "agents" / discovery["agentId"] / "events" / "agent_turn_results.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {
                "eventId": "turn-result-completed",
                "runId": "turn-stage-task-completed",
                "agentId": discovery["agentId"],
                "sessionId": task["sessionId"],
                "status": "completed",
                "summary": "已完成本轮资料搜集，结构化结果可进入下一步。",
                "createdAt": "2026-06-23T00:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled["status"] == "needs_review"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["status"] == "needs_review"
    assert stored_task["writeback"]["resultAuthority"] == "agent_turn_result_reconciliation"
    assert stored_task["result"]["closureSummary"]["completionGatePassed"] is False

def test_research_stage_status_reconciles_interrupted_stage_task_turn_journal(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-interrupted",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        "turn-stage-task-interrupted",
        "turn_started",
        status="running",
        payload={"source": "test"},
    )
    interrupted_event = append_conversation_event(
        tmp_path,
        task["sessionId"],
        "turn-stage-task-interrupted",
        "turn_interrupted",
        status="interrupted",
        payload={"reason": "user_stop", "summary": "本轮已按请求停止。"},
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled["status"] == "interrupted"
    collection_card = next(card for card in latest_round["sourceCollectionStageCards"] if card["stageId"] == "finding")
    assert collection_card["agentTaskStatus"] == "interrupted"
    assert collection_card["status"] == "agent_interrupted"
    assert collection_card["userStatusLabel"] == "已中断，需要继续"
    assert collection_card["actionReadiness"]["canStart"] is True
    assert collection_card["actionReadiness"]["recommendedAction"] == "continue"
    assert collection_card["actionReadiness"]["actionLabel"] == "继续这次任务"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["status"] == "interrupted"
    assert stored_task["turn"]["status"] == "interrupted"
    assert stored_task["reconciledFromTurn"]["resultEventId"] == interrupted_event.event_id
    assert stored_task["result"]["closureSummary"]["userStatus"] == "interrupted"
    assert "尚未完成阶段写回" in stored_task["result"]["closureSummary"]["message"]
    assert "继续时请先查看上一轮" in stored_task["result"]["closureSummary"]["retryInstruction"]

def test_research_stage_status_reconciles_terminal_stage_task_snapshot_as_interrupted(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    extraction = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=extraction["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": extraction["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "提炼神经机制启发算法资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": extraction["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-terminal-ready",
            "status": "running",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id="": {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": True,
            "terminalStatus": "ready",
            "completionSource": "last_turn_status",
            "assistantText": "已读取全部候选，但没有完成阶段写回。",
            "lastTurnStatus": "ready",
            "isRunning": False,
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": extraction["agentId"], "agentRole": "source_extractor"},
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled["status"] == "interrupted"
    extraction_card = next(card for card in latest_round["sourceCollectionStageCards"] if card["stageId"] == "extraction")
    assert extraction_card["status"] == "agent_interrupted"
    assert extraction_card["userStatusLabel"] == "已中断，需要继续"
    assert "继续这次任务" in extraction_card["userSummary"]

def test_research_stage_status_reconciles_blocked_stage_task_turn_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    extraction = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=extraction["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": extraction["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": extraction["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-blocked",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": extraction["agentId"], "agentRole": "source_extractor"},
    )
    events_path = tmp_path / "workspace" / "agents" / extraction["agentId"] / "events" / "agent_turn_results.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {
                "eventId": "turn-result-blocked",
                "runId": "turn-stage-task-blocked",
                "agentId": extraction["agentId"],
                "sessionId": task["sessionId"],
                "status": "completed",
                "summary": "状态：blocked。缺少 source_collection_context_tool，无法完成结构化提炼。",
                "createdAt": "2026-06-23T00:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled["status"] == "blocked"
    assert latest_round["status"] == "needs_attention"

def test_source_collection_stage_tools_read_context_and_writeback(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    from core.web.services import runtime_scene_service
    from tools.source_collection_stage_tools import source_collection_context_tool, source_collection_stage_writeback_tool

    tool_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: tool_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    data_record = data_processing_service.add_record(
        run_response["run"]["runId"],
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/tool-context",
            "title": "Tool context source",
            "summary": "Relevant source for the tool smoke test.",
            "metadata": {"doi": "10.0000/tool-context"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-stage-tool", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    context_payload = json.loads(
        source_collection_context_tool(
            team_id=team["teamId"],
            task_id=task["taskId"],
            max_records=5,
        )
    )
    assert context_payload["status"] == "ok"
    assert context_payload["records"][0]["doi"] == "10.0000/tool-context"
    _append_stage_task_tool_trace(tmp_path, task["task"])
    writeback_payload = json.loads(
        source_collection_stage_writeback_tool(
            team_id=team["teamId"],
            task_id=task["taskId"],
            status="completed",
            summary="工具回写完成。",
            result_json=json.dumps(
                {
                    "recordExtractions": [
                        {
                            "recordId": data_record["recordId"],
                            "decision": "keep",
                            "valueSummary": "Relevant source for the tool smoke test.",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            evidence_refs_json=f'[{{"type":"run","id":"{run_response["run"]["runId"]}","label":"source run"}}]',
            next_actions_json='["进入资料审查"]',
            recorded_by_agent=agent["agentId"],
        )
    )
    assert writeback_payload["status"] == "completed"
    assert writeback_payload["coverageSummary"]["processed"] == 1
    assert "task" not in writeback_payload
    assert "writeback" not in writeback_payload
    assert "recordExtractions" not in json.dumps(writeback_payload, ensure_ascii=False)
    assert len(json.dumps(writeback_payload, ensure_ascii=False)) < 3000
    tool_event_codes = [args[2] for args, _kwargs in tool_events]
    assert "tool.source_collection_context.completed" in tool_event_codes
    assert "tool.source_collection_stage_writeback.completed" in tool_event_codes
    writeback_event = next(kwargs for args, kwargs in tool_events if args[2] == "tool.source_collection_stage_writeback.completed")
    assert writeback_event["fields"]["taskId"] == task["taskId"]
    assert writeback_event["fields"]["status"] == "completed"

def test_source_collection_context_reports_actual_candidate_page(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码皮层层级",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding cortical hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    for index in range(3):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/context-page-{index}",
                "sourceKind": "paper",
                "summary": "Neural predictive coding evidence.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/context-page-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-context-page", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        max_records=2,
    )

    assert len(context["candidates"]) == 2
    assert context["counts"]["candidateCount"] == 3
    assert context["counts"]["returnedCandidateCount"] == 2
    assert context["candidatePage"] == {
        "offset": 0,
        "limit": 2,
        "returned": 2,
        "total": 3,
        "hasMore": True,
        "nextOffset": 2,
    }
    assert context["unassessedCandidateIds"] == [item["candidateId"] for item in context["candidates"]]
    assert all(item["qualityBucket"] == "pending" for item in context["candidates"])

def test_source_collection_context_compact_candidate_paging_stays_model_visible(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码皮层层级",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding cortical hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    candidate_ids = []
    for index in range(15):
        candidate = team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/compact-page-{index}",
                "sourceKind": "paper",
                "summary": "Neural predictive coding evidence for model-visible compact context. " * 4,
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/compact-page-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        candidate_ids.append(candidate["candidateId"])
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-compact-context", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    pages = [
        team_workflow_orchestration_service.get_source_collection_stage_task_context(
            team["teamId"],
            task_id=task["taskId"],
            max_records=1,
            candidate_offset=offset,
            candidate_limit=5,
            context_mode="compact",
        )
        for offset in (0, 5, 10)
    ]

    paged_candidate_ids = [item["candidateId"] for page in pages for item in page["candidates"]]
    assert paged_candidate_ids == candidate_ids
    assert pages[0]["contextMode"] == "compact"
    assert pages[0]["candidatePage"]["hasMore"] is True
    assert pages[0]["candidatePage"]["nextOffset"] == 5
    assert "candidate_offset=5" in pages[0]["usage"]["continuationHint"]
    assert pages[2]["candidatePage"]["hasMore"] is False
    assert pages[0]["fieldMode"] == "preview_only"
    assert pages[0]["candidateFieldsTruncated"] is True
    assert pages[0]["doNotUsePreviewAsEvidence"] is True
    assert pages[0]["visibleCandidateCount"] == 5
    assert pages[0]["omittedReturnedCandidateCount"] == 0
    assert "summaryPreview" in pages[0]["candidates"][0]
    assert "summary" not in pages[0]["candidates"][0]
    # quote 锚供给链：compact 页现在必须携带 quotableSources[].blocks 可逐字
    # 复制原文块与 quote 锚指令（run-882610596ddb：无块可抄导致 quote=''），
    # 页体量护栏相应放宽，但仍保持有界（模型可见）。
    supply = {item["sourceId"]: item for item in pages[0]["quotableSources"]}
    assert all(supply[item["candidateId"]]["quoteAvailable"] for item in pages[0]["candidates"])
    assert "禁止改写" in pages[0]["usage"]["quoteAnchorInstruction"]
    assert len(json.dumps(pages[0], ensure_ascii=False)) < 9000

def test_source_collection_context_retry_missing_returns_only_uncovered_candidates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding retry candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/retry-missing-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for retry-missing context.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/retry-missing-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index in range(6)
    ]
    submitted_messages: list[str] = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: submitted_messages.append(content)
        or {"accepted": True, "sessionId": session_id, "turnId": f"turn-retry-{len(submitted_messages)}", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    partial = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "只完成 2/6 条候选提炼。",
            "result": {
                "candidateExtractions": [
                    {"candidateId": item["candidateId"], "status": "extracted", "summary": f"{item['title']} 已提炼。"}
                    for item in candidates[:2]
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert partial["writeback"]["status"] == "needs_review"
    retry_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        candidate_offset=0,
        candidate_limit=5,
        context_mode="retry_missing",
    )

    expected_missing_ids = [item["candidateId"] for item in candidates[2:]]
    assert retry_context["contextMode"] == "retry_missing"
    assert [item["candidateId"] for item in retry_context["candidates"]] == expected_missing_ids
    assert retry_context["candidatePage"]["total"] == 4
    assert retry_context["candidatePage"]["hasMore"] is False
    assert retry_context["retryFocus"]["missingCandidateIds"] == expected_missing_ids
    assert "只补" in retry_context["usage"]["retryInstruction"]

    retry_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "extraction",
            "agentId": agent["agentId"],
            "agentRole": "source_extractor",
            "idempotencyKey": "retry-missing-candidate-coverage",
        },
    )

    assert retry_task["created"] is True
    assert retry_task["task"]["sourceContextMode"] == "retry_missing"
    assert retry_task["task"]["retrySourceTaskId"] == task["taskId"]
    assert len(submitted_messages) == 2
    assert '"context_mode": "retry_missing"' in submitted_messages[-1]
    assert "只补" in submitted_messages[-1]
    assert candidates[0]["candidateId"] not in submitted_messages[-1]
    assert candidates[2]["candidateId"] in submitted_messages[-1]
    new_task_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=retry_task["taskId"],
        candidate_limit=5,
        context_mode="retry_missing",
    )
    assert [item["candidateId"] for item in new_task_context["candidates"]] == expected_missing_ids

def test_source_collection_context_evidence_mode_returns_bounded_summary_and_source_anchor(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
    summary = "Predictive coding evidence retained from the governed source-collection record. " * 8
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding evidence source",
            "sourceUrl": "https://doi.org/10.0000/evidence-context",
            "sourceKind": "paper",
            "summary": summary,
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/evidence-context"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-evidence-context",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        candidate_limit=5,
        context_mode="evidence",
    )

    assert context["contextMode"] == "evidence"
    assert context["fieldMode"] == "evidence_source"
    assert context["candidateFieldsTruncated"] is False
    assert context["doNotUsePreviewAsEvidence"] is False
    assert context["candidates"][0]["candidateId"] == candidate["candidateId"]
    assert context["candidates"][0]["summary"] == summary.strip()
    assert "summaryPreview" not in context["candidates"][0]
    assert context["candidates"][0]["evidenceRefs"] == [
        {"type": "doi", "id": "10.0000/evidence-context", "label": "Predictive coding evidence source"}
    ]
    assert context["candidates"][0]["evidenceScope"] == "collected_summary_metadata"
    assert "不等于全文" in context["usage"]["evidenceInstruction"]

def test_source_collection_context_evidence_mode_anchors_raw_records_when_candidates_are_absent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码原始资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": "extraction-agent"},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/raw-evidence-context",
            "title": "Predictive coding raw evidence source",
            "summary": "A governed abstract retained on the raw DataRecord before candidate import.",
            "metadata": {"doi": "10.0000/raw-evidence-context"},
        },
    )
    task = {
        "taskId": "stagetask-raw-evidence-context",
        "runId": run_id,
        "stageId": "extraction",
        "agentId": "extraction-agent",
        "agentRole": "source_extractor",
        "sessionId": "session-extraction",
        "status": "running",
        "title": "资料提炼任务",
        "writebackContract": {"taskId": "stagetask-raw-evidence-context"},
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        record_limit=5,
        context_mode="evidence",
    )

    assert context["candidatePage"]["total"] == 0
    assert context["records"][0]["recordId"] == record["recordId"]
    assert context["records"][0]["summary"].startswith("A governed abstract")
    assert context["records"][0]["evidenceRefs"] == [
        {"type": "data_record", "id": record["recordId"], "label": "Predictive coding raw evidence source"}
    ]
    assert context["records"][0]["evidenceScope"] == "collected_summary_metadata"

def test_source_collection_context_retry_evidence_returns_only_missing_anchor_candidates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding evidence retry {index}",
                "sourceUrl": f"https://doi.org/10.0000/retry-evidence-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding summary retained by the source collection stage.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/retry-evidence-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index in range(2)
    ]
    submitted_messages: list[str] = []
    submitted_metadata: list[dict[str, object]] = []

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted_messages.append(content)
        submitted_metadata.append(dict(kwargs.get("message_metadata") or {}))
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-retry-evidence-{len(submitted_messages)}",
            "status": "running",
        }

    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        fake_submit_session_message,
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "两条资料均已覆盖，但第二条尚缺证据锚点。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidates[0]["candidateId"],
                        "decision": "keep",
                        "summary": "已有摘要证据。",
                        "evidenceRefs": [{"type": "record_anchor", "id": "retry-evidence-0-abstract"}],
                    },
                    {
                        "candidateId": candidates[1]["candidateId"],
                        "decision": "needs_more_info",
                        "summary": "内容有价值，但没有写入锚点。",
                    },
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["coverageSummary"]["complete"] is True
    assert response["writeback"]["materializedContentExtraction"]["missingEvidenceAnchorCount"] == 0
    assert response["writeback"]["coverageSummary"]["blockedCandidateIds"] == [candidates[1]["candidateId"]]
    retry_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        candidate_limit=5,
        context_mode="retry_evidence",
    )

    assert retry_context["contextMode"] == "retry_evidence"
    assert retry_context["fieldMode"] == "evidence_source"
    assert [item["candidateId"] for item in retry_context["candidates"]] == [candidates[1]["candidateId"]]
    assert retry_context["retryFocus"]["evidenceGapCandidateIds"] == [candidates[1]["candidateId"]]
    assert retry_context["retryFocus"]["missingEvidenceAnchorCount"] == 1
    assert retry_context["candidates"][0]["evidenceRefs"] == [
        {
            "type": "doi",
            "id": "10.0000/retry-evidence-1",
            "label": "Predictive coding evidence retry 1",
        }
    ]

    retry_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "extraction",
            "agentId": agent["agentId"],
            "agentRole": "source_extractor",
            "idempotencyKey": "retry-missing-evidence-anchor",
            "formalRetry": True,
            "evidenceRemediationContract": {
                "schemaVersion": 1,
                "parentRunId": "research-parent-run",
                "sourceNodeId": "source_extraction",
                "resolutionKind": "add_budget",
                "evidenceGapCandidateIds": [candidates[1]["candidateId"]],
                "scopeCandidateIds": [candidates[1]["candidateId"]],
                "requiredExistingLocatorFetch": True,
                "additionalBudget": {"toolCalls": 1},
                "operatorReason": "补抓唯一缺少证据锚点的候选",
            },
        },
    )

    assert retry_task["created"] is True
    assert retry_task["task"]["sourceContextMode"] == "retry_evidence"
    assert retry_task["task"]["retrySourceTaskId"] == task["taskId"]
    assert retry_task["task"]["evidenceRemediationContract"]["scopeCandidateIds"] == [
        candidates[1]["candidateId"]
    ]
    assert any(
        item["id"] == "fetch_existing_locators"
        and item["requiredTool"] == "web_fetch_tool"
        for item in retry_task["task"]["taskChecklist"]
    )
    assert '"context_mode": "retry_evidence"' in submitted_messages[-1]
    assert "只返回 `retryFocus.evidenceGapCandidateIds`" in submitted_messages[-1]
    assert "仅抓取该既有定位符补证" in submitted_messages[-1]
    assert "不要扩展检索方向" in submitted_messages[-1]
    assert "当前批读取完毕后一次性补证" in submitted_messages[-1]
    assert "1-2 次回写完成本批结果" in submitted_messages[-1]
    assert "正式证据修复 child Run" in submitted_messages[-1]
    assert "`web_fetch_tool`" in submitted_messages[-1]
    assert "`evidenceFetchAttempts[]`" in submitted_messages[-1]
    assert submitted_metadata[-1]["sourceContextMode"] == "retry_evidence"
    new_task_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=retry_task["taskId"],
        candidate_limit=5,
        context_mode="retry_evidence",
    )
    assert [item["candidateId"] for item in new_task_context["candidates"]] == [candidates[1]["candidateId"]]
    authoritative_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=retry_task["taskId"],
        candidate_limit=5,
        context_mode="retry_missing",
    )
    assert authoritative_context["contextMode"] == "retry_evidence"
    assert [item["candidateId"] for item in authoritative_context["candidates"]] == [candidates[1]["candidateId"]]

    _append_stage_task_tool_trace(tmp_path, retry_task["task"])

    retry_writeback = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        retry_task["taskId"],
        {
            "status": "needs_review",
            "summary": "已为剩余候选补入受控摘要记录锚点。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidates[1]["candidateId"],
                        "decision": "needs_more_info",
                        "summary": "仅登记受控摘要记录锚点，不扩展全文结论。",
                        "evidenceRefs": [{"type": "record_anchor", "id": "retry-evidence-1-abstract"}],
                    }
                ],
                # A retry can retain record-oriented output from an earlier pre-candidate pass.
                # Once canonical source candidates exist, that legacy array must not replace
                # candidate coverage as the authoritative completion basis.
                "recordExtractions": [
                    {
                        "recordId": "legacy-record-before-candidate-materialization",
                        "decision": "keep",
                        "summary": "Legacy pre-candidate extraction retained for audit only.",
                    }
                ],
                "evidenceFetchAttempts": [
                    {
                        "candidateId": candidates[1]["candidateId"],
                        "locator": candidates[1]["sourceUrl"],
                        "status": "fetched",
                        "toolName": "web_fetch_tool",
                    }
                ],
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    assert retry_writeback["writeback"]["coverageSummary"]["total"] == 2
    assert retry_writeback["writeback"]["coverageSummary"]["processed"] == 2
    assert retry_writeback["writeback"]["coverageSummary"]["missing"] == 0
    assert retry_writeback["writeback"]["coverageSummary"]["complete"] is True
    assert retry_writeback["writeback"]["coverageSummary"]["coverageKind"] == "candidate_extractions"
    assert retry_writeback["writeback"]["closureSummary"]["evidenceFetchProgress"] == {
        "required": True,
        "total": 1,
        "completed": 1,
        "complete": True,
        "completedCandidateIds": [candidates[1]["candidateId"]],
        "missingCandidateIds": [],
        "invalidCandidateIds": [],
    }
    assert {
        item["candidateId"]
        for item in retry_writeback["task"]["result"]["candidateExtractions"]
    } == {candidate["candidateId"] for candidate in candidates}
    legacy_retry_task = dict(retry_writeback["task"])
    legacy_retry_result = {
        "candidateExtractions": [retry_writeback["task"]["result"]["candidateExtractions"][-1]],
    }
    legacy_retry_writeback = dict(legacy_retry_task["writeback"])
    legacy_retry_writeback["result"] = legacy_retry_result
    legacy_retry_writeback["coverageSummary"] = {
        "applicable": True,
        "coverageKind": "candidate_extractions",
        "total": 2,
        "processed": 1,
        "missing": 1,
        "invalid": 0,
        "complete": False,
    }
    legacy_retry_task["writeback"] = legacy_retry_writeback
    legacy_retry_task["result"] = dict(legacy_retry_result)
    reconciled_retry_task = (
        team_workflow_orchestration_service._reconcile_source_collection_stage_session_task_retry_coverage(
            team["teamId"],
            run_id,
            legacy_retry_task,
        )
    )
    assert reconciled_retry_task["writeback"]["coverageSummary"]["processed"] == 2
    assert reconciled_retry_task["writeback"]["coverageSummary"]["complete"] is True
    completed_retry_context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=retry_task["taskId"],
        candidate_limit=5,
        context_mode="retry_evidence",
    )

    assert completed_retry_context["candidatePage"]["total"] == 0
    assert completed_retry_context["candidates"] == []
    assert completed_retry_context.get("retryFocus") in (None, {})

    follow_up_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "extraction",
            "agentId": agent["agentId"],
            "agentRole": "source_extractor",
            "idempotencyKey": "review-after-evidence-retry-settled",
        },
    )

    assert follow_up_task["task"]["sourceContextMode"] == "evidence"
    assert follow_up_task["task"]["retrySourceTaskId"] == retry_task["taskId"]

def test_source_collection_extraction_resume_after_interrupted_reading_prioritizes_writeback(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    for index in range(8):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding interrupted candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/interrupted-resume-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence already reviewed in the interrupted turn.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/interrupted-resume-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )
    submitted_messages: list[str] = []

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted_messages.append(content)
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-interrupted-resume-{len(submitted_messages)}",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        task["turn"]["turnId"],
        "turn_started",
        status="running",
        payload={
            "metadata": {
                "kind": "source_collection_stage_session_task",
                "sourceCollectionStageTaskId": task["taskId"],
            }
        },
    )
    _append_stage_task_tool_trace(tmp_path, task["task"], complete=False)
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        task["turn"]["turnId"],
        "turn_interrupted",
        status="interrupted",
        payload={"reason": "turn_budget_exhausted", "summary": "已读完候选，尚未调用 writeback。"},
    )
    team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    retry_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "extraction",
            "agentId": agent["agentId"],
            "agentRole": "source_extractor",
            "idempotencyKey": "resume-after-interrupted-before-writeback",
        },
    )

    assert retry_task["created"] is True
    assert retry_task["task"]["retrySourceTaskId"] == task["taskId"]
    assert len(submitted_messages) == 2
    retry_message = submitted_messages[-1]
    assert "上一轮结果" in retry_message
    assert "状态：已中断，需要继续" in retry_message
    assert "优先直接调用 `source_collection_stage_writeback_tool`" in retry_message
    assert "写回恢复阶段禁止调用 `web_fetch_tool`" in retry_message
    assert '"candidate_limit": 80' in retry_message
    assert "如果返回的 `candidatePage.hasMore=true`，必须继续按 `candidate_offset=candidatePage.nextOffset` 分页读取" not in retry_message

def test_source_collection_context_minimal_strips_stale_candidate_artifacts(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    for index in range(5):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding minimal candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/minimal-context-{index}",
                "sourceKind": "paper",
                "summary": "Detailed predictive coding source summary. " * 8,
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/minimal-context-{index}",
                    "contentExtraction": {
                        "status": "stale",
                        "summary": "上一轮很长的提炼摘要不应污染本轮模型可见输入。" * 20,
                        "taskId": "old-task",
                    },
                },
                "createdByAgent": "content-extraction-agent",
            },
        )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-minimal-context", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        candidate_limit=5,
        context_mode="minimal",
    )

    assert context["contextMode"] == "minimal"
    assert context["candidatePage"]["returned"] == 5
    assert context["fieldMode"] == "id_and_locator_only"
    assert "writebackContract" not in context
    assert "boundaries" not in context
    assert "records" not in context
    assert "contentExtraction" not in context["candidates"][0]
    assert "latestAssessment" not in context["candidates"][0]
    assert "summary" not in context["candidates"][0]
    assert "summaryPreview" in context["candidates"][0]
    assert len(json.dumps(context, ensure_ascii=False)) < 2600

def test_source_quality_stage_writeback_materializes_candidate_extraction_decisions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经算法资料质检",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    approved = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/source-quality-approved",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for network learning and attention mechanisms.",
            "tags": ["neuro", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/source-quality-approved"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    rejected = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Satellite SAR ionosphere encoding source",
            "sourceUrl": "https://doi.org/10.0000/source-quality-rejected",
            "sourceKind": "paper",
            "summary": "Ionosphere measurement encoding unrelated to neural algorithms.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/source-quality-rejected"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    needs_info = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Pain coding cortical source needing abstract",
            "sourceUrl": "https://doi.org/10.0000/source-quality-needs-info",
            "sourceKind": "paper",
            "summary": "Potentially relevant cortical coding source but abstract is missing.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/source-quality-needs-info"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-source-quality", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "needs_review",
            "summary": "审查 3/3 条候选：通过 1，拒绝 1，退回补充 1。",
            "result": {
                "reviewSummary": {"total": 3, "assessed": 3, "pass": 1, "rejected": 1, "needsMoreInfo": 1},
                "candidateExtractions": [
                    {
                        "candidateId": approved["candidateId"],
                        "decision": "keep",
                        "reason": "神经预测编码主题相关，元数据可追踪。",
                        "evidenceRefs": [{"type": "doi", "id": "10.0000/source-quality-approved"}],
                    },
                    {
                        "candidateId": rejected["candidateId"],
                        "decision": "reject",
                        "reason": "SAR 电离层编码，不属于神经算法资料。",
                        "riskFlags": ["topic_mismatch"],
                    },
                    {
                        "candidateId": needs_info["candidateId"],
                        "decision": "needs_more_info",
                        "reason": "标题可能相关，但缺摘要，需补充公开内容。",
                        "requiredFixes": ["补充摘要或正文证据。"],
                    },
                ],
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    status = team_workflow_orchestration_service.get_source_quality_status(team["teamId"])
    candidates = {
        item["candidateId"]: item
        for item in team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    }
    materialized = response["writeback"]["materializedSourceQuality"]
    assert materialized["assessedCandidateCount"] == 3
    assert materialized["approvedCandidateCount"] == 1
    assert materialized["rejectedCandidateCount"] == 1
    assert materialized["needsRevisionCandidateCount"] == 1
    assert candidates[approved["candidateId"]]["qualityStatus"] == "source_quality_approved"
    assert candidates[rejected["candidateId"]]["qualityStatus"] == "source_quality_rejected"
    assert candidates[needs_info["candidateId"]]["qualityStatus"] == "source_quality_needs_revision"
    assert status["summary"]["assessedSourceCandidateCount"] == 3
    assert status["summary"]["approvedSourceCandidateCount"] == 1
    assert status["summary"]["rejectedSourceCandidateCount"] == 1
    assert status["summary"]["needsRevisionSourceCandidateCount"] == 1
    screening_projection = next(
        card
        for card in team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)["cards"]
        if card["stageId"] == "extraction"
    )
    assert screening_projection["status"] == "partial_current_inputs"
    assert screening_projection["counts"]["artifact"] == 3
    assert screening_projection["counts"]["pending"] == 1
    assert screening_projection["counts"]["needsRevision"] == 1
    assert screening_projection["artifactStatus"] == "partial"
    assert screening_projection["isClosedLoop"] is False


def test_source_quality_batch_skips_superseded_source_versions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    version_candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Sleep downscaling preprint {version_label}",
                "sourceUrl": f"https://doi.org/10.21203/rs.3.rs-10024823/{version_label}",
                "sourceKind": "paper",
                "summary": "Sleep-dependent synaptic downscaling evidence from a versioned preprint.",
                "allowedForAnalysis": True,
                "createdByAgent": "Source Finder Agent",
            },
        )["candidate"]
        for version_label in ("v1", "v2")
    ]

    response = team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {"assessedByAgent": "资料提炼 Agent"},
    )

    assert response["summary"]["assessedCandidateCount"] == 1
    assert response["assessments"][0]["candidateId"] == version_candidates[1]["candidateId"]
    assert response["summary"]["skippedCandidateCount"] == 1
    assert response["sourceQualityStatus"]["summary"]["sourceCandidateCount"] == 2
    assert response["sourceQualityStatus"]["summary"]["independentSourceCandidateCount"] == 1
    assert response["sourceQualityStatus"]["summary"]["supersededSourceCandidateCount"] == 1
    assert response["sourceQualityStatus"]["summary"]["unassessedSourceCandidateCount"] == 0
    assert response["skippedCandidates"] == [
        {
            "candidateId": version_candidates[0]["candidateId"],
            "title": "Sleep downscaling preprint v1",
            "reason": "superseded_source_version",
        }
    ]


def test_source_collection_ingestion_stage_writeback_uses_scoped_team_base_when_ids_overlap(tmp_path, monkeypatch):
    """Stage writeback must scope a raw team KB id before granting/reviewing ingestion."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    extractor = agent_directory_service.create_agent_instance(display_name="资料提炼")
    ingestor = agent_directory_service.create_agent_instance(display_name="资料入库")
    duplicate_ingestor = agent_directory_service.create_agent_instance(display_name="另一队资料入库")
    session_service.ensure_agent_direct_session(agent_id=extractor["agentId"], title="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=ingestor["agentId"], title="资料入库")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {"agentId": extractor["agentId"], "role": "source_extractor", "agentName": "资料提炼"},
            {"agentId": ingestor["agentId"], "role": "source_ingestor", "agentName": "资料入库"},
        ],
    )
    other_team = team_service.create_team(
        name="另一支科研团队",
        members=[{"agentId": duplicate_ingestor["agentId"], "role": "source_ingestor", "agentName": "另一队资料入库"}],
    )
    target_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="挑战杯科研知识库",
        description="Target team base",
        actor_agent_id=ingestor["agentId"],
    )
    duplicate_base = team_knowledge_service.create_knowledge_base(
        other_team["teamId"],
        name="挑战杯科研知识库",
        description="Duplicate raw id under another owner",
        actor_agent_id=duplicate_ingestor["agentId"],
    )
    assert target_base["knowledgeBaseId"] == duplicate_base["knowledgeBaseId"]
    assert target_base["scopedKnowledgeBaseId"] != duplicate_base["scopedKnowledgeBaseId"]

    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经算法资料入库",
            "agentRoles": ["source_extractor", "source_ingestor"],
            "agentIds": {"source_extractor": extractor["agentId"], "source_ingestor": ingestor["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/source-ingestion-scoped",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for network learning and attention mechanisms.",
            "tags": ["neuro", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/source-ingestion-scoped"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-scoped-ingestion", "status": "running"},
    )
    quality_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": extractor["agentId"], "agentRole": "source_extractor"},
    )
    _append_stage_task_tool_trace(tmp_path, quality_task["task"])
    team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        quality_task["taskId"],
        {
            "status": "needs_review",
            "summary": "审查 1/1 条候选：通过 1。",
            "result": {
                "reviewSummary": {"total": 1, "assessed": 1, "pass": 1},
                "candidateDecisions": [
                    {
                        "candidateId": source["candidateId"],
                        "decision": "keep",
                        "reason": "主题相关且 DOI 可追踪。",
                        "evidenceRefs": [{"type": "doi", "id": "10.0000/source-ingestion-scoped"}],
                    }
                ],
            },
            "recordedByAgent": extractor["agentId"],
        },
    )
    ingestion_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor["agentId"], "agentRole": "source_ingestor"},
    )
    _append_stage_task_tool_trace(tmp_path, ingestion_task["task"])

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        ingestion_task["taskId"],
        {
            "status": "completed",
            "summary": "生成 steward pack 并写入团队知识库。",
            "result": {
                "knowledgeBaseId": target_base["knowledgeBaseId"],
                "targetDomain": "神经学启发神经网络算法",
                "stewardPackDraft": {
                    "candidateType": "review_record",
                    "sourceRefs": [{"type": "source_manifest", "id": source["candidateId"], "label": source["title"]}],
                    "evidenceRefs": [{"type": "doi", "id": "10.0000/source-ingestion-scoped"}],
                    "claims": [{"claim": "预测编码层级可作为算法设计启发。", "sourceRef": source["candidateId"]}],
                    "uncertainty": [],
                    "riskFlags": [],
                    "candidateIds": [source["candidateId"]],
                    "targetDomain": "神经学启发神经网络算法",
                    "sourceTrace": {
                        "sourceCollectionRunId": run_id,
                        "stageTaskId": ingestion_task["taskId"],
                        "sourceCandidateIds": [source["candidateId"]],
                    },
                    "riskSummary": "候选资料来源可追踪，适合入库。",
                    "proposalPayload": {
                        "title": "Predictive coding cortical hierarchy neural network paper",
                        "summary": "神经预测编码层级证据可支持神经网络学习机制分析。",
                        "claims": [{"claim": "预测编码层级可作为算法设计启发。", "sourceRef": source["candidateId"]}],
                    },
                    "ratingSuggestion": {"rating": "high", "confidence": 0.92},
                    "approvalRequired": True,
                    "confidence": 0.92,
                    "nextAction": "submit_to_knowledge_ingestion",
                    "requiresReview": True,
                },
                "autoIngestDecision": {
                    "decision": "approved",
                    "confidence": 0.92,
                    "knowledgeBaseId": target_base["knowledgeBaseId"],
                    "reason": "候选资料已通过质量审查。",
                },
            },
            "recordedByAgent": ingestor["agentId"],
        },
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]
    assert materialized["failed"] == [], materialized["failed"]
    assert materialized["status"] == "completed", materialized
    assert materialized["knowledgeBaseId"] == target_base["knowledgeBaseId"]
    assert materialized["scopedKnowledgeBaseId"] == target_base["scopedKnowledgeBaseId"]
    assert materialized["formalKnowledgeItemCount"] >= 1

def test_content_extraction_writeback_requires_candidate_coverage_and_materializes_extractions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-content-extraction", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    partial = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "只提炼了 1 条，但错误声明完成。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidates[0]["candidateId"],
                        "status": "extracted",
                        "summary": "预测编码皮层层级可启发神经网络结构。",
                        "evidenceRefs": [{"type": "doi", "id": "10.0000/extraction-coverage-0"}],
                    },
                    {
                        "candidateId": "remaining_2_candidates",
                        "status": "extracted",
                        "summary": "这是伪造聚合 ID，不能计入覆盖。",
                    },
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert partial["writeback"]["status"] == "needs_review"
    assert partial["task"]["status"] == "needs_review"
    assert partial["writeback"]["coverageSummary"]["total"] == 3
    assert partial["writeback"]["coverageSummary"]["processed"] == 1
    assert partial["writeback"]["coverageSummary"]["missing"] == 2
    assert partial["writeback"]["coverageSummary"]["invalid"] == 1
    assert partial["writeback"]["invalidCandidateIds"] == ["remaining_2_candidates"]
    refreshed_candidates = {
        item["candidateId"]: item
        for item in team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    }
    extraction = refreshed_candidates[candidates[0]["candidateId"]]["metadata"]["contentExtraction"]
    assert extraction["taskId"] == task["taskId"]
    assert extraction["summary"] == "预测编码皮层层级可启发神经网络结构。"

    _append_stage_task_tool_trace(tmp_path, task["task"])
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 3/3 条候选资料提炼。",
            "result": {
                "candidateExtractions": [
                    {"candidateId": item["candidateId"], "status": "extracted", "summary": f"{item['title']} 已提炼。"}
                    for item in candidates
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert complete["writeback"]["status"] == "completed"
    assert complete["writeback"]["coverageSummary"]["processed"] == 3
    assert complete["writeback"]["coverageSummary"]["missing"] == 0

def test_content_extraction_writeback_materializes_candidate_evidence_ledger(tmp_path, monkeypatch):
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
            "title": "Predictive coding source with anchored finding",
            "sourceUrl": "https://doi.org/10.0000/evidence-ledger",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence for an anchored extraction ledger.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/evidence-ledger"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-ledger", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成带引用锚点的资料提炼。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "decision": "keep",
                        "summary": "预测编码层级误差传播可启发多层控制结构。",
                        # Challenge v2 fail-closed card contract (enforced at
                        # the completed-writeback boundary): shared source
                        # metadata lives on the entry, `fact` on each claim.
                        "title": "Predictive coding source with anchored finding",
                        "source_type": "peer_reviewed_paper",
                        "source_url": "https://doi.org/10.0000/evidence-ledger",
                        "retrieved_at": "2026-09-01T08:00:00Z",
                        "relation": "supports",
                        "verification_status": "metadata_checked",
                        "claims": [
                            {
                                "claim": "Predictive coding uses hierarchical prediction errors.",
                                "fact": "Predictive coding uses hierarchical prediction errors.",
                                # Completed extraction writebacks on the formal
                                # claim path require a verbatim quote anchor
                                # copied from the stored candidate summary.
                                "quote": "Predictive coding evidence",
                                "sourceRef": "source-1",
                                "supportLevel": "strong",
                            }
                        ],
                        "keyFindings": [
                            {
                                "finding": "层级预测误差支持跨层控制结构设计。",
                                "fact": "层级预测误差支持跨层控制结构设计。",
                                "sourceRef": "source-1",
                                "page": "3",
                                "citation": "Predictive Coding Source, p.3",
                            }
                        ],
                        "citations": [
                            {"sourceRef": "source-1", "page": "3", "citation": "Predictive Coding Source, p.3"}
                        ],
                        "sourceRefs": [{"type": "paper", "id": "source-1", "label": "Predictive Coding Source"}],
                        "evidenceRefs": [{"type": "page_anchor", "id": "source-1-p3", "label": "p.3"}],
                        "limitations": ["样本来源需要后续复核"],
                        "uncertainty": ["机制迁移到算法仍需实验验证"],
                        "riskFlags": ["analogy_risk"],
                        "supportLevel": "strong",
                        "nextAction": "draft_paper_note",
                    }
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    refreshed = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"][0]
    extraction = refreshed["metadata"]["contentExtraction"]
    ledger = extraction["evidenceLedger"]
    assert response["writeback"]["materializedContentExtraction"]["evidenceLedgerCandidateCount"] == 1
    assert response["writeback"]["materializedContentExtraction"]["evidenceReadyCandidateCount"] == 1
    assert extraction["evidenceStatus"] == "evidence_ready"
    assert ledger["status"] == "evidence_ready"
    assert ledger["sourceRefs"] == [{"type": "paper", "id": "source-1", "label": "Predictive Coding Source"}]
    assert ledger["claims"][0]["claim"] == "Predictive coding uses hierarchical prediction errors."
    assert ledger["keyFindings"][0]["citation"] == "Predictive Coding Source, p.3"
    assert ledger["citations"][0]["page"] == "3"
    assert ledger["evidenceRefs"] == [{"type": "page_anchor", "id": "source-1-p3", "label": "p.3"}]
    assert ledger["limitations"] == ["样本来源需要后续复核"]
    assert ledger["uncertainty"] == ["机制迁移到算法仍需实验验证"]
    assert ledger["riskFlags"] == ["analogy_risk"]
    assert ledger["supportLevel"] == "strong"
    assert ledger["nextAction"] == "draft_paper_note"

def test_source_collection_context_reconciles_checklist_updates_after_writeback(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
            "title": "Predictive coding closure candidate",
            "sourceUrl": "https://doi.org/10.0000/closure-candidate",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence for closure.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/closure-candidate"},
            "createdByAgent": agent["agentId"],
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-context-reconcile", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已提炼候选，但 task 工具稍后才补齐打勾。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "status": "extracted",
                        "summary": "预测编码候选已提炼。",
                    }
                ],
                "candidateDecisions": [{"candidateId": candidate["candidateId"], "decision": "keep"}],
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    assert first["task"]["status"] == "needs_review"
    assert first["task"]["completionGate"]["artifactComplete"] is True
    assert first["task"]["completionGate"]["taskChecklistComplete"] is False

    _append_stage_task_tool_trace(tmp_path, task["task"])
    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        run_id=run_id,
        stage_id="extraction",
        task_id=task["taskId"],
        context_mode="compact",
    )

    assert context["task"]["status"] == "completed"
    assert context["task"]["taskToolProgress"]["completed"] == len(task["task"]["taskChecklist"])
    assert context["task"]["completionGate"]["passed"] is True
    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    assert stored_task["status"] == "completed"
    assert stored_task["completionGate"]["passed"] is True

def test_source_collection_stage_turn_completion_reconciles_post_writeback_checklist(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    direct_session = session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
            "title": "Predictive coding turn closure candidate",
            "sourceUrl": "https://doi.org/10.0000/turn-closure-candidate",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence for turn closure.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/turn-closure-candidate"},
            "createdByAgent": agent["agentId"],
        },
    )["candidate"]
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已提炼候选，但 checklist 在 writeback 之后才补齐。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "status": "extracted",
                        "summary": "预测编码候选已提炼。",
                    }
                ],
                "candidateDecisions": [{"candidateId": candidate["candidateId"], "decision": "keep"}],
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    assert first["task"]["status"] == "needs_review"
    assert first["task"]["completionGate"]["artifactComplete"] is True
    assert first["task"]["completionGate"]["taskChecklistComplete"] is False

    _append_stage_task_tool_trace(tmp_path, first["task"])
    session_service._persist_session_turn_result(
        task["sessionId"],
        {
            "status": "needs_continue",
            "summary": "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
            "raw_output": "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
            "tool_call_count": len(first["task"]["taskChecklist"]) + 1,
            "tool_trace": [],
        },
        turn_id=task["turn"]["turnId"],
    )

    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    assert stored_task["status"] == "completed"
    assert stored_task["completionGate"]["passed"] is True
    assert stored_task["taskToolProgress"]["completed"] == len(stored_task["taskChecklist"])

def test_source_collection_stage_turn_completion_reconciles_feedback_event_checklist(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    agent = agent_directory_service.create_agent_instance(display_name="资料入库")
    direct_session = session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料入库")
    coordinator = agent_directory_service.create_agent_instance(display_name="科研协调")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {"agentId": coordinator["agentId"], "role": "research_coordination", "agentName": "科研协调"},
            {"agentId": agent["agentId"], "role": "source_ingestor", "agentName": "资料入库"},
        ],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="挑战杯科研知识库",
        actor_agent_id=coordinator["agentId"],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料入库",
            "agentRoles": ["source_ingestor"],
            "agentIds": {"source_ingestor": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding ingestion closure candidate",
            "sourceUrl": "https://doi.org/10.0000/feedback-closure-candidate",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence for feedback event closure.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/feedback-closure-candidate"},
            "createdByAgent": agent["agentId"],
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        candidate["candidateId"],
        {
            "assessedByAgent": agent["agentId"],
            "decision": "approved",
            "notes": "来源可追踪，允许知识库管理员入库。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/feedback-closure-candidate"}],
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": agent["agentId"], "agentRole": "source_ingestor"},
    )

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已完成正式知识入库，但 checklist 在同轮 feedback events 末尾才补齐。",
            "result": {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "stewardPackDraft": {
                    "approvedCandidateIds": [candidate["candidateId"]],
                    "targetDomain": "神经机制启发神经网络算法",
                    "proposalPayload": {
                        "title": candidate["title"],
                        "summary": "将已通过质检的预测编码 DOI 资料写入团队知识库。",
                    },
                },
                "autoIngestDecision": {
                    "decision": "approved_for_ingestion",
                    "reason": "候选已通过资料质检，知识库管理员批准直接入库。",
                    "approvedCandidates": [{"candidateId": candidate["candidateId"], "title": candidate["title"]}],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    assert first["task"]["status"] == "needs_review"
    assert first["task"]["completionGate"]["artifactComplete"] is True
    assert first["task"]["completionGate"]["taskChecklistComplete"] is False

    session_service._persist_session_turn_result(
        task["sessionId"],
        {
            "status": "needs_continue",
            "summary": "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
            "raw_output": "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
            "tool_call_count": len(first["task"]["taskChecklist"]) + 1,
            "tool_trace": [],
            "feedback_events": _stage_task_feedback_events(first["task"]),
        },
        turn_id=task["turn"]["turnId"],
    )

    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    assert stored_task["status"] == "completed"
    assert stored_task["completionGate"]["passed"] is True
    assert stored_task["taskToolProgress"]["completed"] == len(stored_task["taskChecklist"])
    assert stored_task["taskToolProgress"]["source"] == "feedback_events"


def test_source_collection_ingestion_reconciles_nested_approve_all_decision_after_no_steward_pack(
    tmp_path, monkeypatch
):
    """A saved approve-all ingestion decision must recover without another model turn."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    ingestor = agent_directory_service.create_agent_instance(display_name="资料入库")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": ingestor["agentId"], "role": "source_ingestor", "agentName": "资料入库"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料入库恢复",
            "agentRoles": ["source_ingestor"],
            "agentIds": {"source_ingestor": ingestor["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding nested ingestion recovery candidate",
            "sourceUrl": "https://doi.org/10.0000/nested-ingestion-recovery",
            "sourceKind": "paper",
            "summary": "A quality-approved candidate that should be recovered into governed knowledge.",
            "allowedForAnalysis": True,
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/nested-ingestion-recovery",
            },
            "createdByAgent": ingestor["agentId"],
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        candidate["candidateId"],
        {
            "assessedByAgent": ingestor["agentId"],
            "decision": "approved",
            "notes": "来源可追踪，允许进入受控知识入库。",
            "evidenceRefs": [
                {"type": "doi", "id": "10.0000/nested-ingestion-recovery"}
            ],
        },
    )
    task_response = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor["agentId"], "agentRole": "source_ingestor"},
    )
    task = task_response["task"]
    _append_stage_task_tool_trace(tmp_path, task)
    nested_result = {
        "ingestionDecision": {
            "decision": "approve_all",
            "approvedCandidateIds": [candidate["candidateId"]],
            "targetDomain": "神经机制启发神经网络算法",
        },
    }
    recovered_task = dict(task)
    recovered_task.update(
        {
            "status": "needs_review",
            "result": dict(nested_result),
            "writeback": {
                "status": "needs_review",
                "agentRequestedStatus": "completed",
                "summary": "已有入库决定，但旧版本未生成知识审核包。",
                "result": dict(nested_result),
                "recordedByAgent": ingestor["agentId"],
                "materializedKnowledgeIngestion": {"status": "no_steward_pack"},
            },
        }
    )
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        recovered_task,
    )

    team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    materialized = stored_task["writeback"]["materializedKnowledgeIngestion"]
    assert materialized["status"] == "completed", materialized
    assert materialized["formalKnowledgeItemCount"] >= 1
    assert stored_task["completionGate"]["artifactComplete"] is True
    assert stored_task["status"] == "completed"


def test_source_collection_stage_task_after_turn_accepts_continuation_turn_for_same_task(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-original",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    old_placeholder = "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。"
    events_path = tmp_path / "workspace" / "agents" / discovery["agentId"] / "events" / "agent_turn_results.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {
                "eventId": "turn-result-needs-continue",
                "runId": "turn-stage-task-original",
                "agentId": discovery["agentId"],
                "sessionId": task["sessionId"],
                "status": "needs_continue",
                "summary": old_placeholder,
                "createdAt": "2026-07-06T16:27:47+08:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    first_reconcile = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        team["teamId"],
        task["taskId"],
        run_id=run_id,
        session_id=task["sessionId"],
        turn_id="turn-stage-task-original",
    )
    assert first_reconcile["taskStatus"] == "interrupted"

    continuation_turn_id = "turn-stage-task-continuation"
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        continuation_turn_id,
        "turn_started",
        status="running",
        payload={
            "metadata": {
                "kind": "source_collection_stage_session_task",
                "teamId": team["teamId"],
                "runId": run_id,
                "stageId": "finding",
                "agentId": discovery["agentId"],
                "agentRole": "source_finder",
                "sourceCollectionStageTaskId": task["taskId"],
            }
        },
    )
    _append_stage_task_tool_trace(tmp_path, task["task"], turn_id=continuation_turn_id)
    writeback = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "继续轮已完成资料寻找，新增 1 条候选线索。",
            "result": {
                "candidateLeads": [
                    {
                        "title": "Predictive coding in the visual cortex",
                        "doi": "10.1038/4580",
                        "summary": "预测编码奠基论文。",
                    }
                ]
            },
            "recordedByAgent": discovery["agentId"],
        },
    )
    assert writeback["task"]["status"] == "completed"
    events_path.write_text(
        events_path.read_text(encoding="utf-8")
        + json.dumps(
            {
                "eventId": "turn-result-completed",
                "runId": continuation_turn_id,
                "agentId": discovery["agentId"],
                "sessionId": task["sessionId"],
                "status": "completed",
                "summary": "继续轮已完成资料寻找，新增 1 条候选线索。",
                "createdAt": "2026-07-06T16:41:01+08:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    continuation_reconcile = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        team["teamId"],
        task["taskId"],
        run_id=run_id,
        session_id=task["sessionId"],
        turn_id=continuation_turn_id,
        reason="session_turn_completed",
    )

    assert continuation_reconcile["status"] == "reconciled"
    assert continuation_reconcile["changed"] is True
    assert continuation_reconcile["turnId"] == continuation_turn_id
    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    assert stored_task["turn"]["turnId"] == continuation_turn_id
    assert stored_task["turn"]["previousTurnId"] == "turn-stage-task-original"
    assert stored_task["turn"]["status"] == "completed"
    assert stored_task["reconciledFromTurn"]["turnId"] == continuation_turn_id
    assert stored_task["summary"] == "继续轮已完成资料寻找，新增 1 条候选线索。"
    assert old_placeholder not in stored_task["summary"]

def test_source_collection_stage_task_after_turn_rejects_unrelated_new_turn(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-original",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        "turn-unrelated-followup",
        "turn_started",
        status="running",
        payload={"metadata": {"kind": "ordinary_chat"}},
    )

    result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        team["teamId"],
        task["taskId"],
        run_id=run_id,
        session_id=task["sessionId"],
        turn_id="turn-unrelated-followup",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "turn_id_mismatch"
    stored_task, _stored_run_id = team_workflow_orchestration_service._find_source_collection_stage_session_task_by_id(
        team["teamId"],
        task["taskId"],
    )
    assert stored_task["turn"]["turnId"] == "turn-stage-task-original"

def test_source_collection_stage_task_progress_counts_later_turn_tool_updates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": discovery["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-stage-task-start",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        task["turn"]["turnId"],
        "turn_started",
        status="running",
        payload={
            "metadata": {
                "kind": "source_collection_stage_session_task",
                "sourceCollectionStageTaskId": task["taskId"],
            }
        },
    )
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已发现 1 条核心论文。",
            "result": {
                "candidateLeads": [
                    {
                        "title": "Predictive coding in the visual cortex",
                        "doi": "10.1038/4580",
                        "summary": "预测编码奠基论文。",
                    }
                ]
            },
        },
    )
    assert response["task"]["status"] == "needs_review"

    _append_stage_task_tool_trace(tmp_path, response["task"], turn_id="turn-stage-task-followup")
    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        run_id=run_id,
        stage_id="finding",
        task_id=task["taskId"],
        context_mode="compact",
    )

    assert context["task"]["status"] == "completed"
    assert context["task"]["taskToolProgress"]["taskCreateObserved"] is False
    assert context["task"]["taskToolProgress"]["completed"] == len(response["task"]["taskChecklist"])
    assert context["task"]["completionGate"]["passed"] is True

def test_source_collection_stage_reconciliation_reuses_session_event_snapshot(monkeypatch):
    load_calls: list[str] = []

    def fake_load_conversation_events(project_root, session_id):
        load_calls.append(session_id)
        return []

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_conversation_events",
        fake_load_conversation_events,
    )
    checklist = team_workflow_orchestration_service._source_collection_stage_task_checklist(
        "extraction",
        "source_extractor",
    )
    event_snapshots: dict[str, list] = {}

    for turn_id in ("turn-shared-session-1", "turn-shared-session-2"):
        team_workflow_orchestration_service._source_collection_stage_task_tool_progress_from_trace(
            {
                "sessionId": "session-shared-stage-reconciliation",
                "turn": {"turnId": turn_id},
                "checklistBinding": {"mode": "stage_task"},
            },
            checklist,
            conversation_events_by_session=event_snapshots,
        )

    assert load_calls == ["session-shared-stage-reconciliation"]


def test_evidence_remediation_fetch_progress_requires_auditable_result_per_candidate():
    task = {
        "evidenceRemediationContract": {
            "requiredExistingLocatorFetch": True,
            "scopeCandidateIds": ["candidate-a", "candidate-b"],
        }
    }

    incomplete = team_workflow_orchestration_service._source_collection_evidence_fetch_progress(
        task,
        {
            "evidenceFetchAttempts": [
                {
                    "candidateId": "candidate-a",
                    "locator": "https://doi.org/10.0000/a",
                    "status": "fetched",
                    "toolName": "web_fetch_tool",
                },
                {
                    "candidateId": "candidate-b",
                    "locator": "https://doi.org/10.0000/b",
                    "status": "failed",
                    "toolName": "web_fetch_tool",
                },
            ]
        },
    )

    assert incomplete["complete"] is False
    assert incomplete["completedCandidateIds"] == ["candidate-a"]
    assert incomplete["missingCandidateIds"] == ["candidate-b"]
    assert incomplete["invalidCandidateIds"] == ["candidate-b"]

    complete = team_workflow_orchestration_service._source_collection_evidence_fetch_progress(
        task,
        {
            "evidenceFetchAttempts": [
                {
                    "candidateId": "candidate-a",
                    "locator": "https://doi.org/10.0000/a",
                    "status": "fetched",
                    "toolName": "web_fetch_tool",
                },
                {
                    "candidateId": "candidate-b",
                    "locator": "https://doi.org/10.0000/b",
                    "status": "failed",
                    "failureCode": "upstream_not_found",
                    "toolName": "web_fetch_tool",
                },
            ]
        },
    )

    assert complete["complete"] is True
    assert complete["completedCandidateIds"] == ["candidate-a", "candidate-b"]
    assert complete["missingCandidateIds"] == []
    assert complete["invalidCandidateIds"] == []

def test_content_extraction_writeback_materializes_record_extractions_and_reports_partial_closure(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
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
    records = [
        data_processing_service.add_record(
            run_id,
            {
                "sourceType": "paper",
                "sourceRef": f"https://doi.org/10.0000/record-extraction-{index}",
                "title": f"Predictive coding raw source {index}",
                "summary": "A raw DataRecord to be promoted into a source_manifest candidate.",
                "metadata": {"doi": f"10.0000/record-extraction-{index}"},
            },
        )
        for index in range(3)
    ]
    submitted_messages = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: submitted_messages.append(content)
        or {"accepted": True, "sessionId": session_id, "turnId": f"turn-{len(submitted_messages)}", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    partial = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "提炼 1 条，另有 1 个错误 ID。",
            "result": {
                "recordExtractions": [
                    {
                        "recordId": records[0]["recordId"],
                        "status": "extracted",
                        "summary": "该资料可作为预测编码神经机制候选来源。",
                        "evidenceRefs": [{"type": "doi", "id": "10.0000/record-extraction-0"}],
                    },
                    {
                        "recordId": "missing-record-id",
                        "status": "extracted",
                        "summary": "这个 ID 不属于当前批次。",
                    },
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert partial["writeback"]["status"] == "needs_review"
    assert partial["writeback"]["coverageSummary"]["coverageKind"] == "record_extractions"
    assert partial["writeback"]["coverageSummary"]["total"] == 3
    assert partial["writeback"]["coverageSummary"]["processed"] == 1
    assert partial["writeback"]["coverageSummary"]["missing"] == 2
    assert partial["writeback"]["coverageSummary"]["invalid"] == 1
    assert partial["writeback"]["invalidRecordIds"] == ["missing-record-id"]
    assert partial["writeback"]["materializedSources"]["importedCandidateCount"] == 1
    assert partial["writeback"]["closureSummary"]["userStatus"] == "partial"
    assert partial["writeback"]["closureSummary"]["successCount"] == 1
    assert "完整 recordId" in partial["writeback"]["closureSummary"]["retryInstruction"]
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["metadata"]["contentExtraction"]["sourceRecordId"] == records[0]["recordId"]

    retry_task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    assert retry_task["created"] is True
    assert len(submitted_messages) == 2
    assert "上一轮结果" in submitted_messages[-1]
    assert "提炼 1/3" in submitted_messages[-1]
    assert "完整 recordId" in submitted_messages[-1]
    assert "missing-record-id" in submitted_messages[-1]

def test_record_extraction_writeback_materializes_evidence_ledger_on_imported_candidate(tmp_path, monkeypatch):
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
    record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/record-ledger",
            "title": "Predictive coding raw record with anchored evidence",
            "summary": "A raw DataRecord to be promoted into a source_manifest candidate with evidence ledger.",
            "metadata": {"doi": "10.0000/record-ledger"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-record-ledger", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 DataRecord 提炼。",
            "result": {
                "recordExtractions": [
                    {
                        "recordId": record["recordId"],
                        "decision": "keep",
                        "valueSummary": "原始记录可作为预测编码机制候选来源。",
                        # Challenge v2 fail-closed card contract (enforced at
                        # the completed-writeback boundary): shared source
                        # metadata lives on the entry, `fact` on each claim.
                        "title": "Predictive coding raw record with anchored evidence",
                        "source_type": "preprint",
                        "source_url": "https://doi.org/10.0000/record-ledger",
                        "retrieved_at": "2026-09-01T08:00:00Z",
                        "relation": "supports",
                        "verification_status": "metadata_checked",
                        "claims": [
                            {
                                "claim": "Predictive coding raw record supports hierarchical control analogy.",
                                "fact": "Predictive coding raw record supports hierarchical control analogy.",
                                # Verbatim quote anchor from the stored record
                                # summary (formal claim path contract).
                                "quote": "A raw DataRecord",
                                "sourceRef": "record-source-1",
                                "supportLevel": "medium",
                            }
                        ],
                        "keyFindings": [
                            {
                                "finding": "原始记录包含可追溯层级误差控制线索。",
                                "fact": "原始记录包含可追溯层级误差控制线索。",
                                "sourceRef": "record-source-1",
                                "page": "abstract",
                                "citation": "Record Ledger Source, abstract",
                            }
                        ],
                        "citations": [
                            {"sourceRef": "record-source-1", "page": "abstract", "citation": "Record Ledger Source, abstract"}
                        ],
                        "sourceRefs": [{"type": "record", "id": "record-source-1", "label": "Record Ledger Source"}],
                        "evidenceRefs": [{"type": "record_anchor", "id": "record-source-1-abstract", "label": "abstract"}],
                        "limitations": ["只有摘要级证据"],
                        "uncertainty": ["后续需要全文复核"],
                        "riskFlags": ["abstract_only"],
                        "supportLevel": "medium",
                        "nextAction": "source_quality_review",
                    }
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 1
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    extraction = candidates[0]["metadata"]["contentExtraction"]
    ledger = extraction["evidenceLedger"]
    assert extraction["evidenceStatus"] == "evidence_ready"
    assert ledger["status"] == "evidence_ready"
    assert ledger["sourceRefs"] == [{"type": "record", "id": "record-source-1", "label": "Record Ledger Source"}]
    assert ledger["claims"][0]["supportLevel"] == "medium"
    assert ledger["keyFindings"][0]["page"] == "abstract"
    assert ledger["citations"][0]["citation"] == "Record Ledger Source, abstract"
    assert ledger["evidenceRefs"] == [{"type": "record_anchor", "id": "record-source-1-abstract", "label": "abstract"}]
    assert ledger["limitations"] == ["只有摘要级证据"]
    assert ledger["uncertainty"] == ["后续需要全文复核"]
    assert ledger["riskFlags"] == ["abstract_only"]
    assert ledger["nextAction"] == "source_quality_review"

def test_content_extraction_writeback_excludes_no_content_records_and_keeps_valuable_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    invalid_record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/empty-source",
            "title": "Empty landing page for predictive coding",
            "summary": "",
            "metadata": {"doi": "10.0000/empty-source", "containerTitle": "Placeholder Journal"},
        },
    )
    useful_record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "url",
            "sourceRef": "https://example.test/predictive-coding-useful-note",
            "title": "Predictive coding useful web note",
            "summary": "A useful explanation of predictive coding hierarchy without DOI metadata.",
            "metadata": {"containerTitle": "Neural Research Notes", "published": "2025"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-exclusion", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "排除 1 条空资料，保留 1 条有价值资料。",
            "result": {
                "recordExtractions": [
                    {
                        "recordId": invalid_record["recordId"],
                        "decision": "exclude",
                        "excludeReason": "no_effective_content",
                        "evidence": ["只有占位标题，没有摘要、正文或可验证内容。"],
                    },
                    {
                        "recordId": useful_record["recordId"],
                        "decision": "keep",
                        "valueSummary": "虽然没有 DOI，但提供了预测编码层级的可用解释和关键词线索。",
                        # Verbatim quote anchor from the stored record summary
                        # (formal claim path contract).
                        "evidenceRefs": [
                            {
                                "id": "summary-quote-1",
                                "type": "quote",
                                "quote": "A useful explanation of predictive coding hierarchy",
                            }
                        ],
                        "defects": ["缺少 DOI"],
                        "followUpSuggestion": "后续补充更权威论文来源。",
                    },
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["status"] == "completed"
    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 1
    assert response["writeback"]["materializedSources"]["excludedSourceCount"] == 1
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    assert [candidate["metadata"]["sourceRecordId"] for candidate in candidates] == [useful_record["recordId"]]
    assert candidates[0]["metadata"]["contentExtraction"]["status"] == "kept_with_notes"
    assert candidates[0]["metadata"]["contentExtraction"]["valueSummary"].startswith("虽然没有 DOI")
    ledger = team_workflow_orchestration_service.get_source_collection_exclusion_ledger(team["teamId"])
    assert ledger["excludedCount"] == 1
    assert ledger["entries"][0]["sourceIdentityKey"] == "doi:10.0000/empty-source"
    assert ledger["entries"][0]["reason"] == "no_effective_content"

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        run_id=run_id,
        stage_id="extraction",
        task_id=task["taskId"],
        record_limit=5,
        context_mode="compact",
    )
    assert invalid_record["recordId"] not in context["recordIds"]
    assert useful_record["recordId"] in context["recordIds"]
    assert context["excludedSourceSummary"]["excludedCount"] == 1

def test_execute_source_collection_search_filters_previously_excluded_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    first_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    first_run_id = first_run["run"]["runId"]
    bad_record = data_processing_service.add_record(
        first_run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/empty-source",
            "title": "Empty landing page for predictive coding",
            "summary": "",
            "metadata": {"doi": "10.0000/empty-source", "containerTitle": "Placeholder Journal"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-exclusion-seed", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        first_run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "排除无有效内容资料。",
            "result": {
                "recordExtractions": [
                    {
                        "recordId": bad_record["recordId"],
                        "decision": "exclude",
                        "excludeReason": "no_effective_content",
                        "evidence": ["没有摘要、正文或可验证内容。"],
                    }
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_execute_source_collection_query",
        _fake_mixed_excluded_source_search_response,
    )
    second_run = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
            "querySeeds": ["predictive coding hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
            "maxResultsPerQuery": 2,
        },
    )
    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        second_run["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    records = data_processing_service.list_records(second_run["run"]["runId"])["records"]
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]

    # All default providers returned the excluded source; each replay is
    # filtered and counted.
    assert execution["filteredExcludedCount"] == 3
    assert execution["recordCount"] == 1
    assert execution["importedCount"] == 1
    assert [record["title"] for record in records] == ["Predictive coding useful web note"]
    assert [candidate["title"] for candidate in candidates] == ["Predictive coding useful web note"]
    assert "search.excluded_source_filtered" in {event["eventType"] for event in execution["executionEvents"]}
    ledger = team_workflow_orchestration_service.get_source_collection_exclusion_ledger(team["teamId"])
    assert ledger["entries"][0]["hitCount"] == 4

def test_source_quality_writeback_downgrades_completed_when_candidate_coverage_is_partial(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经算法资料审查",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    candidates = [
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding review candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/source-quality-coverage-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for source quality coverage.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/source-quality-coverage-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index in range(3)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-source-quality-partial", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "只审查了 1 条，但错误声明完成。",
            "result": {
                "candidateDecisions": [
                    {"candidateId": candidates[0]["candidateId"], "decision": "pass", "reason": "可追踪。"},
                    {"candidateId": "fake-candidate-id", "decision": "pass", "reason": "伪造 ID。"},
                ],
                "unassessedCandidates": ["remaining_2_candidates"],
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["status"] == "needs_review"
    assert response["task"]["status"] == "needs_review"
    assert response["writeback"]["coverageSummary"]["total"] == 3
    assert response["writeback"]["coverageSummary"]["processed"] == 1
    assert response["writeback"]["coverageSummary"]["missing"] == 2
    assert response["writeback"]["coverageSummary"]["invalid"] == 1
    assert response["writeback"]["invalidCandidateIds"] == ["fake-candidate-id"]

def test_candidate_graph_stage_writeback_materializes_candidate_graph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码候选图谱",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["predictive coding neural graph"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding hierarchy source",
            "sourceUrl": "https://doi.org/10.0000/graph-source-one",
            "sourceKind": "paper",
            "summary": "Predictive coding hierarchy supports neural algorithm design.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/graph-source-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Attention precision source",
            "sourceUrl": "https://doi.org/10.0000/graph-source-two",
            "sourceKind": "paper",
            "summary": "Attention modulates precision in predictive processing.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/graph-source-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-candidate-graph", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "基于 2 条 source_manifest 候选构建候选关系图。",
            "result": {
                "candidateGraph": {
                    "theme": "神经预测编码",
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "label": "predictive hierarchy"},
                        {"candidateId": source_two["candidateId"], "label": "attention precision"},
                    ],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": source_two["candidateId"],
                            "relation": "supports_precision_modulation",
                        }
                    ],
                    "graphSummary": {"totalNodes": 2, "totalEdges": 1},
                }
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    materialized = response["writeback"]["materializedCandidateGraph"]
    graph_list = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="candidate_graph")
    graph_candidate = graph_list["candidates"][0]
    graph_projection = next(
        card
        for card in team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)["cards"]
        if card["stageId"] == "relations"
    )
    assert materialized["createdCandidateGraphCount"] == 1
    assert materialized["candidateGraphId"] == graph_candidate["candidateId"]
    assert materialized["nodeCount"] == 2
    assert materialized["edgeCount"] >= 0
    assert graph_candidate["candidateType"] == "candidate_graph"
    assert graph_candidate["metadata"]["stageAgentRole"] == "source_relation_mapper"
    assert graph_candidate["metadata"]["agentWriteback"]["taskId"] == task["taskId"]
    assert graph_candidate["metadata"]["agentWriteback"]["result"]["candidateGraph"]["theme"] == "神经预测编码"
    assert graph_projection["stageId"] == "relations"
    assert graph_projection["status"] == "closed_loop"
    assert graph_projection["counts"]["artifact"] == 2

def test_candidate_graph_stage_writeback_materializes_agent_relation_edges(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码候选图谱",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["predictive coding neural graph"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding hierarchy source",
            "sourceUrl": "https://doi.org/10.0000/graph-source-one",
            "sourceKind": "paper",
            "summary": "Predictive coding hierarchy supports neural algorithm design.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/graph-source-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Attention precision source",
            "sourceUrl": "https://doi.org/10.0000/graph-source-two",
            "sourceKind": "paper",
            "summary": "Attention modulates precision in predictive processing.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/graph-source-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-relation-edges", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "needs_review",
            "summary": "形成2条来源-主题候选边和1条主题间候选关系。",
            "result": {
                "relationCoverage": {
                    "sourceCandidateCount": 2,
                    "themeNodeCount": 2,
                    "sourceThemeEdgeCount": 2,
                    "topicRelationCount": 1,
                    "graphBoundary": "candidate_only",
                },
                "candidateGraph": {
                    "nodes": [
                        {
                            "candidateId": source_one["candidateId"],
                            "nodeId": "n1",
                            "title": "预测编码层级",
                        },
                        {
                            "candidateId": source_two["candidateId"],
                            "nodeId": "n2",
                            "title": "注意精度调节",
                        },
                    ],
                    "edges": [
                        {
                            "source": "n1",
                            "target": "n2",
                            "relationType": "theory_informs_attention",
                        },
                    ],
                },
                "themeNodes": [
                    {"themeId": "T1", "label": "预测编码基础理论"},
                    {"themeId": "T2", "label": "注意与精度调节"},
                ],
                "sourceThemeEdges": [
                    {
                        "candidateId": "n1",
                        "themeId": "T1",
                        "relation": "source_supports_theme",
                        "confidence": "high",
                    },
                    {
                        "candidateId": "n2",
                        "themeId": "T2",
                        "relation": "source_supports_theme",
                        "confidence": "high",
                    },
                ],
                "topicRelations": [
                    {"from": "T1", "to": "T2", "relation": "theory_informs_precision_attention", "confidence": "medium"}
                ],
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    materialized = response["writeback"]["materializedCandidateGraph"]
    graph_candidate = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"],
        candidate_type="candidate_graph",
    )["candidates"][0]
    graph = graph_candidate["metadata"]["graph"]
    edge_triples = {
        (edge["sourceCandidateId"], edge["targetCandidateId"], edge["relation"])
        for edge in graph["edges"]
    }
    graph_projection = next(
        card
        for card in team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)["cards"]
        if card["stageId"] == "relations"
    )

    assert materialized["nodeCount"] == 4
    assert materialized["edgeCount"] == 4
    assert graph["summary"]["nodeCount"] == 4
    assert graph["summary"]["edgeCount"] == 4
    assert {node["candidateId"] for node in graph["nodes"]} >= {
        source_one["candidateId"],
        source_two["candidateId"],
        "source-theme:T1",
        "source-theme:T2",
    }
    assert edge_triples == {
        (source_one["candidateId"], source_two["candidateId"], "theory_informs_attention"),
        (source_one["candidateId"], "source-theme:T1", "source_supports_theme"),
        (source_two["candidateId"], "source-theme:T2", "source_supports_theme"),
        ("source-theme:T1", "source-theme:T2", "theory_informs_precision_attention"),
    }
    assert graph_projection["counts"]["artifact"] == 4
    assert graph_projection["counts"]["output"] == 4


def test_candidate_graph_stage_writeback_requires_materialized_relation_edges(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "关系物化门槛",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["candidate graph relation gate"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Candidate graph source one",
            "sourceUrl": "https://doi.org/10.0000/relation-gate-one",
            "sourceKind": "paper",
            "summary": "Candidate graph source one.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/relation-gate-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Candidate graph source two",
            "sourceUrl": "https://doi.org/10.0000/relation-gate-two",
            "sourceKind": "paper",
            "summary": "Candidate graph source two.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/relation-gate-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-relation-gate", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])
    original_agent_graph_edges = team_workflow_orchestration_service._source_collection_agent_graph_edges

    def legacy_agent_graph_edges(agent_graph):
        return [
            team_workflow_orchestration_service._candidate_graph_edge(
                "n1",
                "n2",
                "candidate_supports_candidate",
            )
        ]

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        legacy_agent_graph_edges,
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "声称形成一条关系，但端点未绑定到候选资料。",
            "result": {
                "candidateGraph": {
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "nodeId": "n1"},
                        {"candidateId": source_two["candidateId"], "nodeId": "n2"},
                    ],
                    "edges": [
                        {
                            "source": "n1",
                            "target": "n2",
                            "relation": "candidate_supports_candidate",
                        },
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    closure = response["task"]["result"]["closureSummary"]
    materialized = response["writeback"]["materializedCandidateGraph"]
    assert materialized["edgeCount"] == 0
    assert materialized["missingLinkCount"] == 1
    assert response["task"]["status"] == "needs_review"
    assert closure["artifactComplete"] is False
    assert closure["artifactStatus"] == "candidate_graph_relation_edges_missing"

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        original_agent_graph_edges,
    )
    reconciled = team_workflow_orchestration_service._reconcile_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        response["task"],
    )

    assert reconciled["status"] == "completed"
    assert reconciled["writeback"]["materializedCandidateGraph"]["edgeCount"] == 1


def test_candidate_graph_dangling_edges_block_closure_until_rebound(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "悬空关系边门槛",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["candidate graph dangling edge gate"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Dangling gate source one",
            "sourceUrl": "https://doi.org/10.0000/dangling-gate-one",
            "sourceKind": "paper",
            "summary": "Dangling gate source one.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/dangling-gate-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Dangling gate source two",
            "sourceUrl": "https://doi.org/10.0000/dangling-gate-two",
            "sourceKind": "paper",
            "summary": "Dangling gate source two.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/dangling-gate-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-dangling-gate", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])
    original_agent_graph_edges = team_workflow_orchestration_service._source_collection_agent_graph_edges

    # 一条边绑定真实节点成功物化，另一条发明了逻辑端点 rh_claim，应只降级后者。
    def partially_dangling_agent_graph_edges(agent_graph):
        return [
            team_workflow_orchestration_service._candidate_graph_edge(
                source_one["candidateId"],
                source_two["candidateId"],
                "candidate_supports_candidate",
            ),
            team_workflow_orchestration_service._candidate_graph_edge(
                source_one["candidateId"],
                "rh_claim",
                "candidate_supports_claim",
            ),
        ]

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        partially_dangling_agent_graph_edges,
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "声称完成关系建图，其中一条边使用了发明的逻辑端点。",
            "result": {
                "candidateGraph": {
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "title": "Dangling gate source one"},
                        {"candidateId": source_two["candidateId"], "title": "Dangling gate source two"},
                    ],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": source_two["candidateId"],
                            "relation": "candidate_supports_candidate",
                        }
                    ],
                },
                "missingLinks": [
                    {
                        "id": "gap-replication",
                        "description": "缺少独立样本复现。",
                        "neededEvidence": ["跨数据集复现结果"],
                        "blocksConclusion": "预测编码通用性",
                    }
                ],
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    closure = response["task"]["result"]["closureSummary"]
    materialized = response["writeback"]["materializedCandidateGraph"]
    assert materialized["edgeCount"] == 1
    assert materialized["danglingEdgeCount"] == 1
    assert response["task"]["status"] == "needs_review"
    assert closure["artifactComplete"] is False
    assert closure["artifactStatus"] == "candidate_graph_dangling_edges"
    assert "rh_claim" in str(closure.get("retryInstruction") or "")
    assert closure["advanceOutcome"] == "partial"

    # Agent 按 retryInstruction 重读节点候选，用真实完整 candidateId 重新回写这些关系，
    # 即对同一任务再次提交 stage writeback（既有重试循环）。
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        original_agent_graph_edges,
    )
    retried = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "重读候选后用真实 candidateId 重写全部关系边。",
            "result": {
                "candidateGraph": {
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "title": "Dangling gate source one"},
                        {"candidateId": source_two["candidateId"], "title": "Dangling gate source two"},
                    ],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": source_two["candidateId"],
                            "relation": "candidate_supports_candidate",
                        }
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert retried["task"]["status"] == "completed"
    retried_materialized = retried["writeback"]["materializedCandidateGraph"]
    assert retried_materialized["edgeCount"] == 1
    assert retried_materialized["danglingEdgeCount"] == 0
    retried_closure = retried["task"]["result"]["closureSummary"]
    assert retried_closure["artifactComplete"] is True
    assert retried_closure["artifactStatus"] == "candidate_graph_ready"


def test_candidate_graph_stage_writeback_materializes_root_graph_payload_on_reuse(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_id = "run-root-relation-graph"
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding framework",
            "sourceUrl": "https://doi.org/10.0000/root-graph-one",
            "sourceKind": "paper",
            "summary": "Predictive coding provides a framework for neural computation.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/root-graph-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Prediction error evidence",
            "sourceUrl": "https://doi.org/10.0000/root-graph-two",
            "sourceKind": "paper",
            "summary": "Prediction error is observed in sensory mismatch paradigms.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/root-graph-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    initial = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {"createdByAgent": "Source Relation Mapper Agent"},
    )
    assert initial["reusedCandidateGraph"] is False
    assert initial["graph"]["summary"]["edgeCount"] == 0

    materialized = team_workflow_orchestration_service._materialize_source_collection_stage_writeback_candidate_graph(
        team["teamId"],
        run_id,
        {
            "taskId": "stage-task-root-graph",
            "runId": run_id,
            "stageId": "relations",
            "agentId": "source-relation-agent",
            "agentRole": "source_relation_mapper",
        },
        {
            "status": "needs_review",
            "summary": "根据已收集资料补充预测处理与预测误差的候选关系。",
            "recordedByAgent": "source-relation-agent",
            "result": {
                "artifactType": "candidate_relation_graph",
                "nodes": [
                    {"id": "predictive_processing_framework", "label": "预测处理框架"},
                    {"id": "prediction_error_mismatch", "label": "预测误差与失配响应"},
                ],
                "edges": [
                    {
                        "from": "predictive_processing_framework",
                        "to": "prediction_error_mismatch",
                        "relation": "provides_candidate_theoretical_account_of",
                        "support": [source_one["candidateId"], source_two["candidateId"]],
                    }
                ],
            },
        },
    )

    graph_candidate = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"],
        candidate_type="candidate_graph",
    )["candidates"][0]
    graph = graph_candidate["metadata"]["graph"]

    assert materialized["reusedCandidateGraph"] is True
    assert materialized["edgeCount"] == 1
    assert graph["summary"]["edgeCount"] == 1
    assert {
        (edge["sourceCandidateId"], edge["targetCandidateId"], edge["relation"])
        for edge in graph["edges"]
    } == {
        (
            "predictive_processing_framework",
            "prediction_error_mismatch",
            "provides_candidate_theoretical_account_of",
        )
    }

def test_unregistered_quality_stage_task_is_rejected(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料审查")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料审查")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "unsupported_source_role", "agentName": "资料审查"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码资料审查",
            "agentRoles": ["unsupported_source_role"],
            "agentIds": {"unsupported_source_role": agent["agentId"]},
            "querySeeds": ["predictive coding source review"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Unsupported source collection stage"):
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run_id,
            {"stageId": "screening", "agentId": agent["agentId"], "agentRole": "unsupported_source_role"},
        )

def test_unregistered_candidate_graph_stage_task_is_rejected(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="候选图谱")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="候选图谱")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "unsupported_relation_role", "agentName": "候选图谱"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码候选图谱",
            "agentRoles": ["unsupported_relation_role"],
            "agentIds": {"unsupported_relation_role": agent["agentId"]},
            "querySeeds": ["predictive coding candidate graph"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Unsupported source collection stage"):
        team_workflow_orchestration_service.start_source_collection_stage_session_task(
            team["teamId"],
            run_id,
            {"stageId": "graph", "agentId": agent["agentId"], "agentRole": "unsupported_relation_role"},
        )

def test_source_collection_stage_tools_record_failure_runtime_events(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    from core.web.services import runtime_scene_service
    from tools.source_collection_stage_tools import source_collection_context_tool, source_collection_stage_writeback_tool

    tool_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: tool_events.append((args, kwargs)) or {"accepted": True},
    )

    context_payload = json.loads(source_collection_context_tool(team_id="missing-team", run_id="missing-run", task_id="missing-task"))
    writeback_payload = json.loads(
        source_collection_stage_writeback_tool(
            team_id="missing-team",
            task_id="missing-task",
            status="blocked",
            summary="上下文缺失。",
        )
    )

    assert context_payload["status"] == "error"
    assert writeback_payload["status"] == "error"
    failure_events = {args[2]: kwargs for args, kwargs in tool_events}
    assert failure_events["tool.source_collection_context.failed"]["level"] == "warning"
    assert failure_events["tool.source_collection_context.failed"]["fields"]["errorType"]
    assert failure_events["tool.source_collection_stage_writeback.failed"]["fields"]["status"] == "blocked"

def test_execute_source_collection_search_writes_records_and_imports_candidates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", _fake_source_search_response)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neural algorithm source batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 2,
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    records = data_processing_service.list_records(run_response["run"]["runId"])["records"]
    assignments = data_processing_service.list_collection_assignments(run_response["run"]["runId"])["assignments"]
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")

    assert execution["status"] == "executed"
    assert execution["provider"] == "crossref_rest_api"
    assert execution["attemptedQueryCount"] == 1
    assert execution["executedQueryCount"] == 1
    assert execution["recordCount"] == 2
    assert execution["createdUniqueRecordCount"] == 2
    assert execution["importedCount"] == 2
    # The default provider set runs crossref first; the arXiv and OpenAlex
    # replays of the same two records are deduped through sourceIdentityKey.
    assert execution["skippedDuplicateCount"] == 4
    assert execution["boundaries"]["externalSearchTriggered"] is True
    assert execution["boundaries"]["metadataOnlyDownload"] is True
    assert execution["boundaries"]["writesFormalKnowledge"] is False
    assert execution["boundaries"]["writesRag"] is False
    assert execution["boundaries"]["writesOfficialGraph"] is False
    assert assignments[0]["status"] == "completed"
    assert len(records) == 2
    assert records[0]["metadata"]["sourceCollectionTrace"]["queryId"] == run_response["searchPlan"]["queries"][0]["queryId"]
    assert records[0]["metadata"]["sourceCollectionTrace"]["externalSearchTriggered"] is True
    assert records[0]["metadata"]["sourceCollectionTrace"]["storageTarget"] == "data_processing.records"
    assert records[0]["metadata"]["metadataOnlyDownload"] is True
    assert records[0]["metadata"]["sourceIdentityKey"] == "doi:10.0000/predictive-coding"
    assert records[0]["collectionTrace"]["assignmentId"] == run_response["assignments"][0]["assignmentId"]
    assert candidates["candidateCount"] == 2
    assert all(candidate["metadata"]["sourceCollectionSearchExecution"] is True for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["importedFromDataRecord"]["runId"] == run_response["run"]["runId"] for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["sourceRunId"] == run_response["run"]["runId"] for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["sourceRecordId"] for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["queryId"] == run_response["searchPlan"]["queries"][0]["queryId"] for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["assignmentId"] == run_response["assignments"][0]["assignmentId"] for candidate in candidates["candidates"])
    assert {candidate["metadata"]["sourceCategory"] for candidate in candidates["candidates"]} == {"paper_web", "dataset"}
    assert candidates["candidates"][0]["metadata"]["doi"] == "10.0000/predictive-coding"
    assert {event["eventType"] for event in execution["executionEvents"]} >= {
        "search.executed",
        "storage.data_record_written",
        "storage.source_manifest_imported",
    }
    storage = execution["storageArtifacts"]
    assert storage["runDirectory"] == f"workspace/teams/{team['teamId']}/source_collection_runs/{run_response['run']['runId']}"
    assert storage["searchPlanPath"].endswith("/search_plan.json")
    assert storage["recordsPath"].endswith("/records.jsonl")
    assert storage["candidatesPath"].endswith("/candidates.jsonl")
    search_plan_file = tmp_path / storage["searchPlanPath"]
    events_file = tmp_path / storage["searchEventsPath"]
    records_file = tmp_path / storage["recordsPath"]
    candidates_file = tmp_path / storage["candidatesPath"]
    assert search_plan_file.exists()
    assert events_file.exists()
    assert records_file.exists()
    assert candidates_file.exists()
    assert json.loads(search_plan_file.read_text(encoding="utf-8"))["planId"] == run_response["searchPlan"]["planId"]
    stored_events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    stored_records = [json.loads(line) for line in records_file.read_text(encoding="utf-8").splitlines()]
    stored_candidates = [json.loads(line) for line in candidates_file.read_text(encoding="utf-8").splitlines()]
    assert {event["eventType"] for event in stored_events} >= {"search.executed", "storage.data_record_written"}
    assert [record["recordId"] for record in stored_records] == [record["recordId"] for record in records]
    assert [candidate["candidateId"] for candidate in stored_candidates] == [
        candidate["candidateId"] for candidate in candidates["candidates"]
    ]

def test_arxiv_atom_entry_mapping_parses_search_result_fields():
    from core.web.services.team_workflow.source_collection import residual

    feed = _fake_arxiv_atom_feed(
        entries=[
            {
                "id": "http://arxiv.org/abs/2101.00983v1",
                "title": "Counts of zeros of the Riemann zeta function",
                "summary": "We prove bounds on simple zeros of the zeta function from rigorous Platt and Trudgian computations.",
                "published": "2021-01-11T18:00:00Z",
                "updated": "2021-03-02T10:00:00Z",
                "authors": ["Timothy Platt", "Tim Trudgian"],
                "categories": ["math.NT"],
            }
        ]
    )
    entries = _fake_arxiv_atom_entries(feed)
    assert len(entries) == 1
    result = residual._source_collection_result_from_arxiv_entry(entries[0], fallback_source_type="preprint")

    assert result["sourceRef"] == "http://arxiv.org/abs/2101.00983v1"
    assert result["rawLocation"] == "http://arxiv.org/abs/2101.00983v1"
    assert result["title"] == "Counts of zeros of the Riemann zeta function"
    # The abstract must land in summary with a hasAbstract signal: extraction
    # produces the verbatim quotes from this field.
    assert "rigorous Platt and Trudgian computations" in result["summary"]
    assert result["qualitySignals"]["hasAbstract"] is True
    assert result["metadata"]["published"] == "2021-01-11T18:00:00Z"
    assert result["metadata"]["updated"] == "2021-03-02T10:00:00Z"
    assert result["metadata"]["authors"] == ["Timothy Platt", "Tim Trudgian"]
    assert result["metadata"]["arxivId"] == "2101.00983v1"
    assert result["metadata"]["primaryCategory"] == "math.NT"
    assert result["sourceType"] == "paper"

class _FakeAtomHttpResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_arxiv_provider_helpers_are_bound_into_orchestration_service_namespace():
    # The background search thread resolves every provider helper through the
    # orchestration_service namespace (``s.<name>``).  A new provider helper
    # that is defined but not bound into that namespace raises AttributeError
    # at runtime and fails the whole collection batch, so the binding is part
    # of the provider contract.
    from core.web.services import team_workflow_orchestration_service as s

    assert hasattr(s, "_execute_arxiv_source_collection_query")
    assert hasattr(s, "_execute_source_collection_query")
    assert hasattr(s, "_arxiv_search_url")
    assert hasattr(s, "_arxiv_search_query")
    assert hasattr(s, "_source_collection_arxiv_atom_entries")
    assert hasattr(s, "_source_collection_result_from_arxiv_entry")


def test_execute_arxiv_source_collection_query_runs_through_service_namespace(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    from core.web.services import team_workflow_orchestration_service as s

    feed = _fake_arxiv_atom_feed(
        entries=[
            {
                "id": "http://arxiv.org/abs/2101.00983v1",
                "title": "Counts of zeros of the Riemann zeta function",
                "summary": "We prove bounds on simple zeros of the zeta function from rigorous Platt and Trudgian computations.",
                "published": "2021-01-11T18:00:00Z",
                "authors": ["Timothy Platt", "Tim Trudgian"],
                "categories": ["math.NT"],
            }
        ]
    )
    seen_urls = []

    def _fake_urlopen(request, timeout=0):
        seen_urls.append(request.full_url)
        return _FakeAtomHttpResponse(feed)

    monkeypatch.setattr(s.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(s.time, "sleep", lambda *_args: None)

    response = s._execute_arxiv_source_collection_query(
        "Platt Trudgian zeta zeros",
        rows=2,
        provider=s.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
        fallback_source_type="preprint",
    )

    assert seen_urls and "export.arxiv.org/api/query" in seen_urls[0]
    assert not response.get("error")
    results = response.get("results") or []
    assert len(results) == 1
    assert results[0]["sourceRef"] == "http://arxiv.org/abs/2101.00983v1"
    assert "Platt and Trudgian" in (results[0]["summary"] or "")


def test_execute_source_collection_search_accepts_arxiv_provider_and_rejects_unknown(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", _fake_arxiv_search_response)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Arxiv source batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"provider": "arxiv_api", "maxQueries": 1, "maxResultsPerQuery": 2},
    )
    records = data_processing_service.list_records(run_response["run"]["runId"])["records"]

    assert execution["status"] == "executed"
    assert execution["provider"] == "arxiv_api"
    assert execution["providers"] == ["arxiv_api"]
    assert execution["executedQueryCount"] == 1
    assert execution["recordCount"] == 2
    assert all(record["metadata"]["searchProvider"] == "arxiv_api" for record in records)
    first_record = records[0]
    assert first_record["sourceRef"] == "http://arxiv.org/abs/2101.00983v1"
    assert "predictive coding" in first_record["summary"]
    assert first_record["metadata"]["arxivId"] == "2101.00983v1"
    assert first_record["metadata"]["authors"] == ["Timothy Platt", "Tim Trudgian"]
    assert first_record["metadata"]["sourceCollectionTrace"]["searchProvider"] == "arxiv_api"
    executed_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.executed"]
    assert len(executed_events) == 1
    assert executed_events[0]["provider"] == "arxiv_api"

    # Unknown providers are rejected at the execution entrypoint before any
    # query runs, while all default-set members are accepted.
    observed_queries = []

    def observing_fake(query, *, max_results, provider):
        observed_queries.append(provider)
        return {"provider": provider, "results": []}

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", observing_fake)
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="Unsupported source collection search provider: rss_feed",
    ):
        team_workflow_orchestration_service.execute_source_collection_search(
            team["teamId"],
            run_response["run"]["runId"],
            {"provider": "rss_feed", "maxQueries": 1},
        )
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="Unsupported source collection search provider: rss_feed",
    ):
        team_workflow_orchestration_service.start_source_collection_search_background(
            team["teamId"],
            run_response["run"]["runId"],
            {"provider": "rss_feed", "backgroundExecution": True},
        )
    assert observed_queries == []

def test_execute_source_collection_search_runs_default_provider_set_with_merge_and_isolation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    observed_providers = []

    def provider_dispatch_fake(query, *, max_results, provider):
        observed_providers.append(provider)
        if provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
            return {
                "provider": provider,
                "searchUrl": "https://api.example.test/search?q=crossref",
                "results": [
                    {
                        "title": "Shared predictive coding source",
                        "sourceRef": "https://doi.org/10.0000/shared-source",
                        "rawLocation": "https://api.example.test/works/10.0000/shared-source",
                        "summary": "Crossref metadata record about predictive coding cortical hierarchy.",
                        "sourceType": "paper",
                        "metadata": {"doi": "10.0000/shared-source", "containerTitle": "Journal of Neural Computation"},
                        "qualitySignals": {"hasDoi": True},
                    },
                    {
                        "title": "Crossref only cortical hierarchy study",
                        "sourceRef": "https://doi.org/10.0000/crossref-only",
                        "rawLocation": "https://api.example.test/works/10.0000/crossref-only",
                        "summary": "Crossref exclusive record on predictive coding hierarchy mechanisms.",
                        "sourceType": "paper",
                        "metadata": {"doi": "10.0000/crossref-only", "containerTitle": "Journal of Neuroscience"},
                        "qualitySignals": {"hasDoi": True},
                    },
                ][:max_results],
            }
        if provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX:
            return {
                "provider": provider,
                "searchUrl": "https://api.openalex.org/works?search=predictive",
                "results": [
                    {
                        "title": "Shared predictive coding source (OpenAlex preprint)",
                        "sourceRef": "https://doi.org/10.0000/shared-source",
                        "rawLocation": "https://arxiv.org/abs/2101.00983",
                        "summary": "OpenAlex rebuilt abstract for the shared predictive coding cortical hierarchy record.",
                        "sourceType": "paper",
                        "metadata": {"doi": "10.0000/shared-source", "openalexId": "https://openalex.org/W210100983"},
                        "qualitySignals": {"hasAbstract": True},
                    },
                    {
                        "title": "OpenAlex only cortical hierarchy survey",
                        "sourceRef": "https://doi.org/10.0000/openalex-only",
                        "rawLocation": "https://example.org/works/openalex-only-survey",
                        "summary": "OpenAlex exclusive survey on predictive coding cortical hierarchy mechanisms.",
                        "sourceType": "paper",
                        "metadata": {"doi": "10.0000/openalex-only", "openalexId": "https://openalex.org/W300000001"},
                        "qualitySignals": {"hasAbstract": True},
                    },
                ][:max_results],
            }
        return {
            "provider": provider,
            "searchUrl": "https://export.arxiv.org/api/query?search_query=all%3Apredictive",
            "results": [
                {
                    "title": "Shared predictive coding source preprint",
                    "sourceRef": "http://arxiv.org/abs/2101.00983v1",
                    "rawLocation": "http://arxiv.org/abs/2101.00983v1",
                    "summary": "arXiv abstract for the shared predictive coding cortical hierarchy record.",
                    "sourceType": "paper",
                    "metadata": {"doi": "10.0000/shared-source", "arxivId": "2101.00983v1"},
                    "qualitySignals": {"hasAbstract": True},
                },
                {
                    "title": "arXiv only cortical hierarchy preprint",
                    "sourceRef": "http://arxiv.org/abs/2007.00001v2",
                    "rawLocation": "http://arxiv.org/abs/2007.00001v2",
                    "summary": "arXiv exclusive preprint on predictive coding cortical hierarchy verification.",
                    "sourceType": "paper",
                    "metadata": {"arxivId": "2007.00001v2"},
                    "qualitySignals": {"hasAbstract": True},
                },
            ][:max_results],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", provider_dispatch_fake)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Provider set batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )

    assert observed_providers == [
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
    ]
    assert execution["providers"] == [
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
    ]
    assert execution["provider"] == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF
    assert execution["attemptedQueryCount"] == 1
    assert execution["executedQueryCount"] == 1
    assert execution["resultCount"] == 6
    assert execution["recordCount"] == 4
    assert execution["skippedDuplicateCount"] == 2
    records = data_processing_service.list_records(run_response["run"]["runId"])["records"]
    assert {record["metadata"]["searchProvider"] for record in records} == {
        "crossref_rest_api",
        "arxiv_api",
        "openalex_api",
    }
    shared_records = [record for record in records if record["metadata"].get("doi") == "10.0000/shared-source"]
    assert len(shared_records) == 1
    assert shared_records[0]["metadata"]["searchProvider"] == "crossref_rest_api"
    executed_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.executed"]
    assert sorted(event["provider"] for event in executed_events) == [
        "arxiv_api",
        "crossref_rest_api",
        "openalex_api",
    ]

    # A failing provider is isolated: the other provider still delivers records.
    def failing_crossref_fake(query, *, max_results, provider):
        if provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
            return {"provider": provider, "searchUrl": "https://api.example.test/search?q=x", "results": [], "error": "crossref throttled"}
        return _fake_arxiv_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", failing_crossref_fake)
    run_two = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Provider isolation batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    isolated = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_two["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    assert isolated["executedQueryCount"] == 1
    assert isolated["failedQueryCount"] == 0
    assert isolated["recordCount"] == 2
    failed_events = [event for event in isolated["executionEvents"] if event["eventType"] == "search.failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["provider"] == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF

    # When every provider fails the query stays runnable and no output lands.
    def always_failing_fake(query, *, max_results, provider):
        return {"provider": provider, "results": [], "error": f"{provider} unavailable"}

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", always_failing_fake)
    run_three = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "All providers failing batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    all_failed = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_three["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    assert all_failed["executedQueryCount"] == 0
    assert all_failed["failedQueryCount"] == 1
    assert all_failed["attemptedQueryCount"] == 1
    assert all_failed["recordCount"] == 0
    assert all_failed["outputCount"] == 0
    assert all_failed["status"] == "partial"
    assert {event["provider"] for event in all_failed["executionEvents"] if event["eventType"] == "search.failed"} == {
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
    }

def test_execute_source_collection_search_marks_cooldown_skip_events(tmp_path, monkeypatch):
    """A 429-cooldown skip reuses the blocked search.failed shape with reason=cooldown."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)

    def cooldown_crossref_fake(query, *, max_results, provider):
        if provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
            return {
                "provider": provider,
                "results": [],
                "error": (
                    "crossref_rest_api is in a 429 cooldown window for another 240s; "
                    "the provider stayed rate-limited, so this search skipped it without an HTTP call."
                ),
                "errorReason": "cooldown",
            }
        if provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX:
            return {"provider": provider, "searchUrl": "https://api.openalex.org/works?search=predictive", "results": []}
        return _fake_arxiv_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", cooldown_crossref_fake)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Cooldown skip batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    failed_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.failed"]
    assert [event["provider"] for event in failed_events] == [
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF
    ]
    assert failed_events[0]["status"] == "blocked"
    assert failed_events[0]["reason"] == "cooldown"
    assert "cooldown" in failed_events[0]["summary"]
    # The collection loop moved on: the other providers still served the query.
    executed_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.executed"]
    assert {event["provider"] for event in executed_events} == {
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV,
        team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
    }
    assert execution["executedQueryCount"] == 1
    assert execution["failedQueryCount"] == 0
    assert execution["recordCount"] == 2

def test_execute_source_collection_search_applies_quality_gate_to_arxiv_results(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)

    def irrelevant_arxiv_fake(query, *, max_results, provider):
        assert provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV
        feed = _fake_arxiv_atom_feed(
            entries=[
                {
                    "id": "http://arxiv.org/abs/2212.00001v1",
                    "title": "Quantum sourdough fermentation dynamics",
                    "summary": "A study of bread starter cultures and oven thermodynamics with no neural content.",
                    "published": "2022-12-01T00:00:00Z",
                    "authors": ["Sample Author"],
                }
            ]
        )
        from core.web.services.team_workflow.source_collection import residual

        results = [
            residual._source_collection_result_from_arxiv_entry(entry, fallback_source_type="paper")
            for entry in _fake_arxiv_atom_entries(feed)
        ]
        return {"provider": provider, "searchUrl": "https://export.arxiv.org/api/query?search_query=x", "results": results[:max_results]}

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", irrelevant_arxiv_fake)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"provider": "arxiv_api", "maxQueries": 1, "maxResultsPerQuery": 1},
    )

    assert execution["resultCount"] == 1
    assert execution["rejectedResultCount"] == 1
    assert execution["recordCount"] == 0
    rejected_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.low_quality_rejected"]
    assert len(rejected_events) == 1
    assert rejected_events[0]["provider"] == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV
    assert "insufficient_query_overlap" in rejected_events[0]["summary"]

def test_openalex_work_mapping_rebuilds_inverted_index_abstract_and_fields():
    # The OpenAlex abstract arrives as a {word: [position, ...]} inverted
    # index; the mapper must rebuild the original sentence order and land it
    # in summary (with hasAbstract) because downstream extraction produces
    # verbatim quotes from that field.
    from core.web.services.team_workflow.source_collection import residual

    work = {
        "id": "https://openalex.org/W210100983",
        "doi": "https://doi.org/10.0000/openalex-predictive",
        "title": "Predictive coding cortical hierarchy preprint",
        "publication_year": 2021,
        "publication_date": "2021-01-11",
        "type": "preprint",
        "authorships": [
            {"author": {"display_name": "Timothy Platt"}},
            {"author": {"display_name": "Tim Trudgian"}},
            {"author": {"display_name": ""}},
            "not-a-dict",
        ],
        "primary_location": {
            "landing_page_url": "https://arxiv.org/abs/2101.00983",
            "source": {"display_name": "arXiv (Cornell University)"},
        },
        "abstract_inverted_index": {
            "coding": [3],
            "predictive": [2],
            "We": [0],
            "hierarchy.": [6],
            "study": [4],
            "cortical": [5],
            "the": [1],
        },
    }
    result = residual._source_collection_result_from_openalex_work(work, fallback_source_type="")

    assert result["summary"] == "We the predictive coding study cortical hierarchy."
    assert result["qualitySignals"]["hasAbstract"] is True
    assert result["title"] == "Predictive coding cortical hierarchy preprint"
    assert result["sourceRef"] == "https://doi.org/10.0000/openalex-predictive"
    assert result["rawLocation"] == "https://arxiv.org/abs/2101.00983"
    assert result["metadata"]["openalexId"] == "https://openalex.org/W210100983"
    assert result["metadata"]["doi"] == "10.0000/openalex-predictive"
    assert result["metadata"]["publicationYear"] == 2021
    assert result["metadata"]["publicationDate"] == "2021-01-11"
    assert result["metadata"]["authors"] == ["Timothy Platt", "Tim Trudgian"]
    assert result["metadata"]["venue"] == "arXiv (Cornell University)"
    # OpenAlex "preprint" is normalized through the shared source-type map.
    assert result["sourceType"] == "paper"

    # A journal "article" alias lands on the Crossref-style paper vocabulary.
    article_result = residual._source_collection_result_from_openalex_work(
        {"title": "Article work", "type": "article"}, fallback_source_type=""
    )
    assert article_result["sourceType"] == "paper"
    assert article_result["metadata"]["openalexType"] == "journal-article"

    # Missing or malformed inverted indexes degrade to no abstract.
    empty_result = residual._source_collection_result_from_openalex_work(
        {"title": "No abstract work", "abstract_inverted_index": {}}, fallback_source_type="paper"
    )
    assert empty_result["summary"] == ""
    assert empty_result["qualitySignals"]["hasAbstract"] is False
    assert empty_result["sourceType"] == "paper"
    broken_result = residual._source_collection_result_from_openalex_work(
        {"title": "Broken abstract work", "abstract_inverted_index": {"word": "not-a-list"}}, fallback_source_type=""
    )
    assert broken_result["qualitySignals"]["hasAbstract"] is False

class _FakeOpenAlexHttpResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

def test_openalex_provider_helpers_are_bound_into_orchestration_service_namespace():
    # The background search thread resolves every provider helper through the
    # orchestration_service namespace (``s.<name>``).  An OpenAlex helper that
    # is defined but not bound into that namespace raises AttributeError at
    # runtime and fails the whole collection batch, so the binding is part of
    # the provider contract.
    from core.web.services import team_workflow_orchestration_service as s

    assert hasattr(s, "_execute_openalex_source_collection_query")
    assert hasattr(s, "_execute_source_collection_query")
    assert hasattr(s, "_openalex_search_url")
    assert hasattr(s, "_source_collection_openalex_abstract")
    assert hasattr(s, "_source_collection_result_from_openalex_work")
    assert hasattr(s, "_arxiv_search_url")

def test_execute_openalex_source_collection_query_dispatches_through_service_namespace(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    from core.web.services import team_workflow_orchestration_service as s

    payload = _fake_openalex_works_payload(
        [
            {
                "id": "https://openalex.org/W210100983",
                "doi": "https://doi.org/10.0000/openalex-predictive",
                "title": "Predictive coding cortical hierarchy preprint",
                "publication_year": 2021,
                "type": "preprint",
                "authorships": [{"author": {"display_name": "Timothy Platt"}}],
                "primary_location": {
                    "landing_page_url": "https://arxiv.org/abs/2101.00983",
                    "source": {"display_name": "arXiv (Cornell University)"},
                },
                "abstract_inverted_index": {"predictive": [1], "We": [0], "coding.": [2]},
            }
        ]
    )
    seen_requests = []

    def _fake_urlopen(request, timeout=0):
        seen_requests.append((request.full_url, timeout))
        return _FakeOpenAlexHttpResponse(payload)

    monkeypatch.setattr(s.urllib.request, "urlopen", _fake_urlopen)

    response = s._execute_source_collection_query(
        {"query": "predictive coding cortical hierarchy", "sourceType": "preprint"},
        max_results=3,
        provider=s.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX,
    )

    assert seen_requests and "api.openalex.org/works" in seen_requests[0][0]
    # The mailto contact keeps the request in OpenAlex's polite pool.
    assert "mailto=" in seen_requests[0][0]
    assert seen_requests[0][1] == 15
    assert not response.get("error")
    assert response["provider"] == "openalex_api"
    results = response.get("results") or []
    assert len(results) == 1
    assert results[0]["sourceRef"] == "https://doi.org/10.0000/openalex-predictive"
    assert results[0]["summary"] == "We predictive coding."
    assert results[0]["sourceType"] == "paper"

    # Unknown providers are rejected at the query dispatch, not by HTTP.
    unknown = s._execute_source_collection_query(
        {"query": "anything"}, max_results=1, provider="rss_feed"
    )
    assert unknown.get("error") == "Unsupported provider: rss_feed"
    assert len(seen_requests) == 1

def test_execute_source_collection_search_accepts_openalex_provider(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", _fake_openalex_search_response)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "OpenAlex source batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"provider": "openalex_api", "maxQueries": 1, "maxResultsPerQuery": 2},
    )
    records = data_processing_service.list_records(run_response["run"]["runId"])["records"]

    assert execution["status"] == "executed"
    assert execution["provider"] == "openalex_api"
    assert execution["providers"] == ["openalex_api"]
    assert execution["executedQueryCount"] == 1
    assert execution["recordCount"] == 2
    assert all(record["metadata"]["searchProvider"] == "openalex_api" for record in records)
    first_record = records[0]
    assert first_record["sourceRef"] == "https://doi.org/10.0000/openalex-predictive"
    # The rebuilt abstract (not just the title) lands in the record summary.
    assert "We the predictive coding study cortical hierarchy." in first_record["summary"]
    assert first_record["metadata"]["authors"] == ["Timothy Platt", "Tim Trudgian"]
    assert first_record["metadata"]["venue"] == "arXiv (Cornell University)"
    assert first_record["metadata"]["publicationYear"] == 2021
    assert first_record["metadata"]["doi"] == "10.0000/openalex-predictive"
    assert first_record["sourceType"] == "paper"
    assert first_record["metadata"]["sourceCollectionTrace"]["searchProvider"] == "openalex_api"
    executed_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.executed"]
    assert len(executed_events) == 1
    assert executed_events[0]["provider"] == "openalex_api"

def test_execute_source_collection_search_applies_quality_gate_to_openalex_results(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)

    def irrelevant_openalex_fake(query, *, max_results, provider):
        assert provider == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX
        from core.web.services.team_workflow.source_collection import residual

        work = {
            "id": "https://openalex.org/W220000001",
            "title": "Quantum sourdough fermentation dynamics",
            "type": "article",
            "authorships": [{"author": {"display_name": "Sample Author"}}],
            "primary_location": {
                "landing_page_url": "https://example.org/works/quantum-sourdough",
                "source": {"display_name": "Journal of Baking"},
            },
            "abstract_inverted_index": {
                "bread": [2],
                "A": [0],
                "thermodynamics": [5],
                "study": [1],
                "starter": [3],
                "oven": [6],
                "of": [4],
                "cultures.": [7],
            },
        }
        results = [residual._source_collection_result_from_openalex_work(work, fallback_source_type="paper")]
        return {"provider": provider, "searchUrl": "https://api.openalex.org/works?search=x", "results": results[:max_results]}

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", irrelevant_openalex_fake)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"provider": "openalex_api", "maxQueries": 1, "maxResultsPerQuery": 1},
    )

    assert execution["resultCount"] == 1
    assert execution["rejectedResultCount"] == 1
    assert execution["recordCount"] == 0
    rejected_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.low_quality_rejected"]
    assert len(rejected_events) == 1
    assert rejected_events[0]["provider"] == team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX
    assert "insufficient_query_overlap" in rejected_events[0]["summary"]

def test_execute_source_collection_search_rejects_low_relevance_results_before_storage(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_execute_source_collection_query",
        _fake_low_quality_source_search_response,
    )
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neural algorithm source batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 1,
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )
    records = data_processing_service.list_records(run_response["run"]["runId"])["records"]
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    event_types = {event["eventType"] for event in execution["executionEvents"]}

    assert execution["status"] == "partial"
    # All default providers returned the same irrelevant record; each replay
    # is rejected by the quality gate.
    assert execution["resultCount"] == 3
    assert execution["recordCount"] == 0
    assert execution["createdUniqueRecordCount"] == 0
    assert execution["importedCount"] == 0
    assert execution["rejectedResultCount"] == 3
    assert records == []
    assert candidates["candidateCount"] == 0
    assert "search.low_quality_rejected" in event_types
    assert "storage.data_record_written" not in event_types
    assert "storage.source_manifest_imported" not in event_types

def test_execute_source_collection_search_publishes_runtime_work_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    events = _capture_workflow_events(monkeypatch)
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    observed_active = []

    def fake_search(query, *, max_results, provider):
        observed_active.append(team_workflow_orchestration_service.load_source_collection_work_run_summary()["active"])
        return _fake_source_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neural algorithm source batch",
            "topic": "neural predictive coding",
            "querySeeds": ["neural predictive coding"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )
    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()

    assert execution["executedQueryCount"] == 1
    assert observed_active
    assert observed_active[0]["runKind"] == "source_collection_run"
    assert observed_active[0]["status"] == "running"
    assert observed_active[0]["currentPhase"] == "searching"
    assert observed_active[0]["teamName"] == "ai科学研究团队"
    assert observed_active[0]["topic"] == "neural predictive coding"
    assert summary["active"] is None
    assert summary["latest"]["runId"] == run_response["run"]["runId"]
    assert summary["latest"]["status"] == "completed"
    assert summary["latest"]["recordCount"] == 1
    assert summary["latest"]["importedCount"] == 1
    search_event = next(kwargs for args, kwargs in events if args[2] == "source_collection.search_executed")
    assert search_event["fields"]["attemptedQueryCount"] == 1
    assert search_event["child_log_path"].startswith("artifacts/source-collection-")
    assert search_event["child_log_payload"]["summary"]["attemptedQueryCount"] == 1
    assert search_event["child_log_payload"]["summary"]["executedQueryCount"] == 1
    assert search_event["child_log_payload"]["queryEvents"]
    assert search_event["child_log_payload"]["queryEvents"][0]["assignmentId"]
    assert search_event["child_log_payload"]["queryEvents"][0]["queryId"]

def test_execute_source_collection_search_does_not_mark_downstream_assignments_as_running_search(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_execute_source_collection_query",
        lambda query, *, max_results, provider: _fake_source_search_response(query, max_results=max_results, provider=provider),
    )
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neural algorithm source batch",
            "topic": "neural predictive coding",
            "querySeeds": ["neural predictive coding"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )
    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()

    assert execution["executedQueryCount"] == 1
    assert execution["sourceCollectionSummary"]["openAssignmentCount"] == 3
    assert execution["sourceCollectionSummary"]["searchOpenAssignmentCount"] == 0
    assert execution["sourceCollectionSummary"]["downstreamOpenAssignmentCount"] == 3
    assert execution["runStatus"]["summary"]["searchOpenAssignmentCount"] == 0
    assert execution["runStatus"]["summary"]["downstreamOpenAssignmentCount"] == 3
    assert summary["active"] is None
    assert summary["latest"]["status"] == "completed"
    assert summary["latest"]["currentPhase"] == "completed"
    assert summary["latest"]["openAssignmentCount"] == 3
    assert summary["latest"]["searchOpenAssignmentCount"] == 0
    assert summary["latest"]["downstreamOpenAssignmentCount"] == 3

def test_execute_source_collection_search_skips_existing_query_without_force(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    calls = []

    def fake_search(query, *, max_results, provider):
        calls.append(query["queryId"])
        return _fake_source_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    first = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_response["run"]["runId"], {"maxQueries": 1})
    second = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_response["run"]["runId"], {"maxQueries": 1})

    assert first["executedQueryCount"] == 1
    assert second["executedQueryCount"] == 0
    assert second["skippedQueryCount"] == 0
    assert second["skippedDuplicateCount"] == 0
    assert second["status"] == "no_open_assignment"
    # The first execution ran all three default providers for the same query.
    assert calls == [run_response["searchPlan"]["queries"][0]["queryId"]] * 3
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2

def test_execute_source_collection_search_limits_failed_provider_attempt_to_max_queries(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    calls = []

    def fake_search(query, *, max_results, provider):
        calls.append(query["queryId"])
        return {"error": "provider throttled"}

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy", "predictive coding neural algorithm"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    first_query_id = run_response["searchPlan"]["queries"][0]["queryId"]
    second_query_id = run_response["searchPlan"]["queries"][1]["queryId"]

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )

    assert execution["attemptedQueryCount"] == 1
    assert execution["executedQueryCount"] == 0
    assert execution["failedQueryCount"] == 1
    assert execution["recordCount"] == 0
    assert execution["status"] == "partial"
    assert calls == [first_query_id] * 3
    assert second_query_id in execution["nextRunnableQueryIds"]
    assert [event["eventType"] for event in execution["executionEvents"]] == [
        "search.failed",
        "search.failed",
        "search.failed",
    ]
    assert {event["provider"] for event in execution["executionEvents"]} == {
        "crossref_rest_api",
        "arxiv_api",
        "openalex_api",
    }
    assert execution["boundaries"]["externalSearchTriggered"] is True

def test_execute_source_collection_search_advances_after_no_record_output(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    calls = []

    def fake_search(query, *, max_results, provider):
        calls.append(query["queryId"])
        if query["queryId"] == first_query_id:
            return _fake_low_quality_source_search_response(query, max_results=max_results, provider=provider)
        return _fake_source_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy", "predictive coding neural algorithm"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    first_query_id = run_response["searchPlan"]["queries"][0]["queryId"]
    second_query_id = run_response["searchPlan"]["queries"][1]["queryId"]

    first = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )
    second = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )

    assert first["recordCount"] == 0
    assert first["outputCount"] == 1
    assert second["executedQueryCount"] == 1
    assert second["recordCount"] == 1
    # Each execution runs all three default providers for its query.
    assert calls == [
        first_query_id,
        first_query_id,
        first_query_id,
        second_query_id,
        second_query_id,
        second_query_id,
    ]

def test_execute_source_collection_search_records_output_per_query(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)

    def fake_search(query, *, max_results, provider):
        query_id = str(query.get("queryId") or "query")
        query_text = str(query.get("query") or query_id)
        return {
            "provider": provider,
            "searchUrl": f"https://api.example.test/search?q={query_text}",
            "results": [
                {
                    "title": f"Incremental source {query_text}",
                    "sourceRef": f"https://doi.org/10.0000/{query_id}",
                    "rawLocation": f"https://api.example.test/works/10.0000/{query_id}",
                    "summary": "Metadata-only result for incremental output.",
                    "sourceType": "paper",
                    "metadata": {"doi": f"10.0000/{query_id}", "containerTitle": "Incremental Journal"},
                    "qualitySignals": {"providerScore": 90},
                }
            ][:max_results],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "first query",
            "querySeeds": ["first query", "second query"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 2, "maxResultsPerQuery": 1},
    )

    assert execution["executedQueryCount"] == 2
    assert execution["recordCount"] == 2
    assert execution["outputCount"] == 2
    assert [output["status"] for output in execution["outputs"]] == ["returned", "completed"]
    assert execution["runStatus"]["summary"]["outputCount"] == 2

def test_execute_source_collection_search_skips_duplicate_sources_on_force_rerun(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", _fake_source_search_response)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    first = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    second = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2, "force": True},
    )

    assert first["recordCount"] == 2
    assert second["status"] == "duplicates_skipped"
    assert second["recordCount"] == 0
    assert second["createdUniqueRecordCount"] == 0
    assert second["importedCount"] == 0
    # Force replays all three default providers; every replayed result matches
    # an existing record identity.
    assert second["skippedDuplicateCount"] == 6
    assert second["remainingQueryCount"] == 0
    assert second["hasMore"] is False
    assert second["duplicateSourceKeys"] == [
        "doi:10.0000/predictive-coding",
        "doi:10.0000/cortical-dataset",
        "doi:10.0000/predictive-coding",
        "doi:10.0000/cortical-dataset",
        "doi:10.0000/predictive-coding",
        "doi:10.0000/cortical-dataset",
    ]
    assert {event["eventType"] for event in second["executionEvents"]} >= {"search.duplicate_skipped"}
    assignments = data_processing_service.list_collection_assignments(run_response["run"]["runId"])["assignments"]
    assert assignments[0]["status"] == "completed"
    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()
    assert summary["latest"]["status"] == "completed"
    assert summary["latest"]["currentPhase"] == "completed"
    assert summary["latest"]["searchOpenAssignmentCount"] == 0
    assert "跳过 6 条重复资料" in summary["latest"]["summary"]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 2

def test_execute_source_collection_search_dedupes_metadata_doi_and_sorted_url_query(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    responses = [
        {
            "provider": "crossref_rest_api",
            "searchUrl": "https://api.example.test/search?q=first",
            "results": [
                {
                    "title": "First metadata DOI source identity",
                    "sourceRef": "metadata-doi-source",
                    "rawLocation": "metadata-doi-location",
                    "summary": "First query DOI only appears in metadata.",
                    "sourceType": "paper",
                    "metadata": {"doi": "10.0000/metadata-only", "containerTitle": "Journal", "issued": "2025"},
                },
                {
                    "title": "First URL query order source identity",
                    "sourceRef": "https://example.test/source?b=2&a=1&utm_source=tracker",
                    "rawLocation": "https://example.test/source?a=1&b=2",
                    "summary": "First query equivalent URLs should dedupe.",
                    "sourceType": "paper",
                    "metadata": {"containerTitle": "Journal", "issued": "2025"},
                },
            ],
        },
        {
            "provider": "crossref_rest_api",
            "searchUrl": "https://api.example.test/search?q=second",
            "results": [
                {
                    "title": "Second metadata DOI source identity duplicate",
                    "sourceRef": "different-source-ref",
                    "rawLocation": "different-location",
                    "summary": "Second query same DOI only appears in metadata.",
                    "sourceType": "paper",
                    "metadata": {"doi": "10.0000/metadata-only", "containerTitle": "Journal", "issued": "2025"},
                },
                {
                    "title": "Second URL query order source identity duplicate",
                    "sourceRef": "https://example.test/source?a=1&b=2",
                    "rawLocation": "https://example.test/source?b=2&a=1",
                    "summary": "Second query equivalent URL with different query order.",
                    "sourceType": "paper",
                    "metadata": {"containerTitle": "Journal", "issued": "2025"},
                },
            ],
        },
    ]

    def fake_search(query, *, max_results, provider):
        query_text = str(query.get("query") or "")
        base = responses[0] if "first" in query_text else responses[1]
        return copy.deepcopy(base)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "source identity",
            "querySeeds": ["first", "second"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )

    first = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    second = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )

    assert first["recordCount"] == 2
    assert second["status"] == "duplicates_skipped"
    assert second["recordCount"] == 0
    # The second batch replays all three default providers over the same
    # identities.
    assert second["skippedDuplicateCount"] == 6
    assert second["duplicateSourceKeys"] == [
        "doi:10.0000/metadata-only",
        "url:https://example.test/source?a=1&b=2",
        "doi:10.0000/metadata-only",
        "url:https://example.test/source?a=1&b=2",
        "doi:10.0000/metadata-only",
        "url:https://example.test/source?a=1&b=2",
    ]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2

def test_start_research_stage_round_creates_knowledge_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    search_calls = _stub_source_collection_search_background(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")

    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "goal": "Collect traceable neuroscience sources.",
            "querySeeds": ["cortical predictive coding"],
            "agentRoles": ["source_finder", "source_extractor"],
        },
    )

    stage_round = response["stageRound"]
    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    assert response["created"] is True
    assert stage_round["stageType"] == "knowledge_collection"
    assert stage_round["status"] == "running"
    assert response["sourceCollectionSearchExecution"]["accepted"] is True
    assert response["sourceCollectionSearchExecution"]["executionMode"] == "background"
    assert stage_round["sourceCollectionSearchExecution"]["status"] == "accepted"
    assert search_calls == [
        {
            "teamId": team["teamId"],
            "runId": response["run"]["runId"],
            "payload": {
                "backgroundExecution": True,
                # No explicit provider: the automatic chain relies on the
                # executor's default SOURCE_COLLECTION_SEARCH_PROVIDERS set.
                "maxQueries": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES,
                "maxResultsPerQuery": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY,
            },
        }
    ]
    assert stage_round["roundNumber"] == 1
    assert stage_round["sourceRunIds"] == [response["run"]["runId"]]
    assert stage_round["dataSearchPlanRef"]["planId"] == response["searchPlan"]["planId"]
    assert stage_round["promptCachePolicy"]["gate"]["status"] == "satisfied"
    assert stage_round["teamMemoryRecord"]["promptCachePolicyRef"]["gateStatus"] == "satisfied"
    assert stage_round["teamMemoryRecord"]["recordKind"] == "team_workflow_stage_record"
    assert stage_round["teamMemoryRecord"]["boundary"] == "runtime_stage_record_only_not_formal_team_knowledge"
    assert stage_round["coordinationContract"]["autoStarted"] is False
    assert stage_round["coordinationContract"]["trigger"] == "manual"
    assert stage_round["coordinationContract"]["startResult"]["started"] is False
    assert stage_round["coordinationContract"]["startResult"]["skipReason"] == "manual_only"
    assert "coordination_round_not_started" not in {item["code"] for item in stage_round["warnings"]}
    assert response["boundaries"]["writesFormalKnowledge"] is False
    assert response["searchPlan"]["boundaries"]["externalSearchTriggered"] is False
    assert response["searchPlan"]["promptCachePolicy"]["requirement"] == "required_for_llm_execution"
    assert status_payload["phases"][0]["activeRoundId"] == stage_round["stageRoundId"]
    assert status_payload["phases"][0]["roundCount"] == 1

def test_source_collection_search_syncs_stage_round_terminal_state(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)

    def fake_search(query, *, max_results, provider):
        query_id = str(query.get("queryId") or "query")
        query_text = str(query.get("query") or query_id)
        return {
            "provider": provider,
            "searchUrl": f"https://api.example.test/search?q={query_text}",
            "results": [
                {
                    "title": f"Stage sync source {query_text}",
                    "sourceRef": f"https://doi.org/10.0000/{query_id}",
                    "rawLocation": f"https://api.example.test/works/10.0000/{query_id}",
                    "summary": "Metadata-only result for stage status sync.",
                    "sourceType": "paper",
                    "metadata": {"doi": f"10.0000/{query_id}", "containerTitle": "Stage Sync Journal"},
                    "qualitySignals": {"providerScore": 90},
                }
            ][:max_results],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "first stage query",
            "goal": "Collect traceable sources incrementally.",
            "querySeeds": ["first stage query", "second stage query"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    run_id = response["run"]["runId"]

    first = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 1})
    first_status = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    first_latest = first_status["latestRound"]

    assert first["hasMore"] is True
    assert first_latest["status"] == "needs_continue"
    assert first_status["phases"][0]["activeRoundId"] == ""
    assert first_latest["sourceCollectionSearchExecution"]["status"] == "needs_continue"
    assert first_latest["sourceCollectionSearchExecution"]["activeWorkRunId"] == ""

    second = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 1})
    second_status = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    second_latest = second_status["latestRound"]

    assert second["hasMore"] is False
    assert second_latest["status"] == "needs_screening"
    assert second_status["phases"][0]["activeRoundId"] == ""
    assert second_latest["sourceCollectionSearchExecution"]["status"] == "completed"
    assert second_latest["sourceCollectionSummary"]["candidateCount"] == 2

def test_research_stage_status_recovers_stale_running_source_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    events = _capture_workflow_events(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)

    def fake_search(query, *, max_results, provider):
        query_id = str(query.get("queryId") or "query")
        return {
            "provider": provider,
            "searchUrl": f"https://api.example.test/search?q={query_id}",
            "results": [
                {
                    "title": f"Recover stale source {query_id}",
                    "sourceRef": f"https://doi.org/10.0000/{query_id}",
                    "rawLocation": f"https://api.example.test/works/10.0000/{query_id}",
                    "summary": "Metadata-only result for stale status recovery.",
                    "sourceType": "paper",
                    "metadata": {"doi": f"10.0000/{query_id}", "containerTitle": "Status Recovery Journal"},
                    "qualitySignals": {"providerScore": 90},
                }
            ][:max_results],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "stale status recovery",
            "querySeeds": ["first query", "second query"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
        },
    )
    run_id = response["run"]["runId"]
    first = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 1})

    assert first["hasMore"] is True

    store_path = team_workflow_orchestration_service._stage_round_store_path(team["teamId"])
    store = json.loads(store_path.read_text(encoding="utf-8"))
    stage_round = store["rounds"][0]
    stage_round["status"] = "running"
    stage_round["sourceCollectionSearchExecution"]["status"] = "accepted"
    stage_round["sourceCollectionSearchExecution"]["activeWorkRunId"] = run_id
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    latest_round = status_payload["latestRound"]

    assert latest_round["status"] == "needs_continue"
    assert status_payload["phases"][0]["activeRoundId"] == ""
    assert latest_round["sourceCollectionSearchExecution"]["status"] == "needs_continue"
    assert latest_round["sourceCollectionSearchExecution"]["activeWorkRunId"] == ""
    recovery_event = next(
        kwargs
        for args, kwargs in events
        if args[2] == "research_stage_round.source_collection_search_recovered_from_work_run"
    )
    assert recovery_event["fields"]["runId"] == run_id
    assert recovery_event["fields"]["searchStatus"] == "needs_continue"
    assert recovery_event["fields"]["status"] == "needs_continue"

def test_start_research_stage_round_reuses_active_knowledge_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    search_calls = _stub_source_collection_search_background(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")

    first = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "knowledge_collection", "topic": "predictive coding"},
    )
    duplicate = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "knowledge_collection", "topic": "predictive coding"},
    )

    assert duplicate["created"] is False
    assert duplicate["continued"] is True
    assert len(search_calls) == 1
    assert duplicate["stageRound"]["stageRoundId"] == first["stageRound"]["stageRoundId"]
    assert duplicate["run"]["runId"] == first["run"]["runId"]
    assert duplicate["continuedSourceRunRef"]["runId"] == first["run"]["runId"]
    assert duplicate["continuedSourceRunRef"]["status"] == "collecting"
    assert duplicate["continuedSourceRunRef"]["assignmentCount"] == len(first["assignments"])
    assert duplicate["continuedSourceRunRef"]["openAssignmentCount"] == len(first["assignments"])
    assert duplicate["continuedSourceRunRef"]["externalSearchTriggered"] is False
    assert len(duplicate["assignments"]) == len(first["assignments"])
    assert duplicate["nextActions"][0] == "Continue the active stage round instead of creating a duplicate."
    assert team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])["roundCount"] == 1

def test_start_research_stage_round_does_not_auto_start_team_coordination_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team = team_service.create_team(name="ai科学研究团队", members=[{"agentId": agent["agentId"], "role": "research_coordination"}])

    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
        },
    )
    room = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])

    assert response["stageRound"]["status"] == "running"
    assert not response["stageRound"].get("coordinationRoundId")
    assert response["stageRound"]["coordinationContract"]["autoStarted"] is False
    assert response["stageRound"]["coordinationContract"]["startResult"]["started"] is False
    assert response["stageRound"]["coordinationContract"]["startResult"]["skipReason"] == "manual_only"
    assert not room["activeRoundId"]

def test_retry_research_stage_round_coordination_starts_room_and_clears_warning(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    start = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "knowledge_collection", "topic": "predictive coding"},
    )
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team_service.update_team(team["teamId"], members=[{"agentId": agent["agentId"], "role": "research_coordination"}])

    retry = team_workflow_orchestration_service.retry_research_stage_round_coordination(
        team["teamId"],
        start["stageRound"]["stageRoundId"],
    )

    assert retry["stageRound"]["status"] == "running"
    assert retry["stageRound"]["coordinationContract"]["autoStarted"] is False
    assert retry["stageRound"]["coordinationContract"]["trigger"] == "explicit_retry"
    assert retry["stageRound"]["coordinationContract"]["startResult"]["started"] is True
    assert retry["stageRound"]["coordinationRoundId"]
    assert "coordination_round_not_started" not in {item["code"] for item in retry["stageRound"]["warnings"]}

def test_start_research_stage_round_new_round_inherits_previous_topic_and_links_upstream(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    search_calls = _stub_source_collection_search_background(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    first = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "neural gating",
            "goal": "Collect gating sources.",
            "querySeeds": ["thalamic gating"],
        },
    )

    second = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "knowledge_collection", "mode": "new_round"},
    )

    assert second["created"] is True
    assert second["stageRound"]["roundNumber"] == 2
    assert second["stageRound"]["topic"] == "neural gating"
    assert second["stageRound"]["goal"] == "Collect gating sources."
    assert second["stageRound"]["upstreamRoundIds"] == [first["stageRound"]["stageRoundId"]]
    assert "thalamic gating missing evidence" in second["stageRound"]["querySeeds"]
    assert len(search_calls) == 2

def test_start_research_stage_round_creates_experiment_planning_placeholder(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team = team_service.create_team(name="ai科学研究团队", members=[{"agentId": agent["agentId"], "role": "research_coordination"}])

    experiment = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "plasticity experiment plan"},
    )

    assert experiment["stageRound"]["stageType"] == "experiment"
    assert experiment["stageRound"]["status"] == "planning"
    assert experiment["stageRound"]["sourceRunIds"] == []
    assert experiment["stageRound"]["upstreamRoundIds"] == []
    assert experiment["stageRound"]["planningContract"]["autoExecution"] is False
    assert experiment["stageRound"]["planningContract"]["requiresUserDecision"] is True
    assert experiment["boundaries"]["autoTransitionsNextStage"] is False


def test_start_iteration_stage_round_requires_frozen_design_and_result(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "迭代门禁验收"},
    )["project"]
    team_workflow_orchestration_service.activate_research_project(
        team["teamId"],
        project["projectId"],
    )
    team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "controlled experiment plan"},
    )
    plan = {
        "planId": "plan-iteration-gate",
        "researchProjectId": project["projectId"],
        "contractValidation": {"valid": True},
        "readiness": {"readyForPlanReview": True},
        "designGate": {"status": "frozen"},
    }
    plan_store = {"plans": []}
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda _team_id: plan_store,
    )

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="frozen executable experiment design",
    ):
        team_workflow_orchestration_service.start_research_stage_round(
            team["teamId"],
            {"stageType": "iteration"},
        )

    plan_store["plans"] = [plan]
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="registered smoke or full-run result",
    ):
        team_workflow_orchestration_service.start_research_stage_round(
            team["teamId"],
            {"stageType": "iteration"},
        )

    plan["activeFullRunResult"] = {
        "fullRunResultId": "full-run-failed",
        "status": "failed",
    }
    iteration = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "iteration"},
    )
    assert iteration["stageRound"]["stageType"] == "iteration"
    assert iteration["stageRound"]["status"] == "planning"


def test_start_research_stage_round_keeps_experiment_plan_when_coordination_busy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team = team_service.create_team(name="ai科学研究团队", members=[{"agentId": agent["agentId"], "role": "research_coordination"}])
    knowledge = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "knowledge_collection", "topic": "synaptic plasticity"},
    )

    experiment = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "plasticity experiment plan"},
    )

    assert experiment["stageRound"]["stageType"] == "experiment"
    assert experiment["stageRound"]["status"] == "planning"
    assert experiment["stageRound"]["upstreamRoundIds"] == [knowledge["stageRound"]["stageRoundId"]]
    assert experiment["stageRound"]["planningContract"]["requiresUserDecision"] is True
    assert experiment["stageRound"]["coordinationContract"]["startResult"]["started"] is False
    assert experiment["stageRound"]["coordinationContract"]["startResult"]["skipReason"] == "manual_only"
    assert "coordination_round_not_started" not in {item["code"] for item in experiment["stageRound"]["warnings"]}

def test_experiment_plan_requires_experiment_stage_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Start an experiment planning stage round"):
        team_workflow_orchestration_service.create_experiment_plan(team["teamId"], {})

def test_source_collection_summary_uses_lightweight_team_existence(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.1038/4580",
            "title": "Predictive coding in the visual cortex",
            "summary": "A useful source.",
            "metadata": {"allowedForAnalysis": True},
        },
    )
    team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_id,
        record["recordId"],
        {"createdByAgent": "Content Extraction Agent"},
    )

    def fail_full_team_read(team_id):
        raise AssertionError("summary must not hydrate full team detail")

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", fail_full_team_read)

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    assert payload["runId"] == run_id
    assert payload["summary"]["recordCount"] == 1
    assert payload["summary"]["sourceCandidateCount"] == 1
    assert [card["stageId"] for card in payload["stageCards"]] == ["finding", "extraction", "relations", "ingestion"]
    assert payload["stageCardSummary"]["sourceCandidateCount"] == 1

def test_source_collection_summary_exposes_run_scoped_phase_close_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.1038/4581",
            "title": "Predictive coding source",
            "summary": "A source for the current run.",
            "metadata": {"allowedForAnalysis": True},
        },
    )
    team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_id,
        record["recordId"],
        {"createdByAgent": "Content Extraction Agent"},
    )

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    assert payload["scope"] == {
        "kind": "source_run",
        "runId": run_id,
        "stageRoundId": payload["stageRound"].get("stageRoundId", ""),
        "includesHistorical": False,
        "eligibleForPhaseCloseGate": True,
    }
    gate = payload["phaseCloseGate"]
    assert gate["runId"] == run_id
    assert gate["status"] == "needs_continue"
    assert gate["passed"] is False
    assert gate["stageCount"] == 4
    assert gate["closedLoopCount"] == 0
    assert {item["stageId"] for item in gate["stages"]} == {"finding", "extraction", "relations", "ingestion"}
    assert gate["blockingReasons"]

def test_source_collection_phase_close_gate_waits_for_stage_round_reconciliation():
    projection = {
        "cards": [
            {"stageId": stage_id, "status": "closed_loop", "isClosedLoop": True}
            for stage_id in ("finding", "extraction", "relations", "ingestion")
        ]
    }

    pending = team_workflow_orchestration_service._source_collection_phase_close_gate(
        "run-close-gate",
        projection=projection,
        stage_round_ref={"stageRoundId": "round-close-gate", "status": "needs_continue"},
    )
    completed = team_workflow_orchestration_service._source_collection_phase_close_gate(
        "run-close-gate",
        projection=projection,
        stage_round_ref={"stageRoundId": "round-close-gate", "status": "completed"},
    )

    assert pending["status"] == "ready_to_close"
    assert pending["stageGatePassed"] is True
    assert pending["passed"] is False
    assert pending["stateReconciliationRequired"] is True
    assert completed["status"] == "closed_loop"
    assert completed["passed"] is True
    assert completed["stateReconciliationRequired"] is False

def test_research_stage_round_status_uses_lightweight_team_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])

    def fail_full_team_read(team_id):
        raise AssertionError("stage round status must not hydrate full team detail")

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", fail_full_team_read)

    payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    assert payload["teamId"] == team["teamId"]
    assert payload["roundCount"] == 0
    assert payload["currentStage"] == "knowledge_collection"
    assert {phase["stageType"] for phase in payload["phases"]} == set(
        team_workflow_orchestration_service.RESEARCH_STAGE_TYPES
    )
    assert {phase["coordinationRoomId"] for phase in payload["phases"]} == {team["linkedChatRoomId"]}

def test_research_stage_round_status_skips_repair_hydration_when_round_exists(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "taskId": "stagetask-existing-round",
            "runId": run_id,
            "stageId": "finding",
            "agentId": "source-finder-agent",
            "agentRole": "source_finder",
            "sessionId": "session-source-finder",
            "status": "completed",
            "summary": "已完成资料搜索。",
            "writebackContract": {"taskId": "stagetask-existing-round"},
        },
    )

    def fail_full_team_read(team_id):
        raise AssertionError("existing stage round repair must not hydrate full team detail")

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", fail_full_team_read)

    payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    assert payload["latestRound"]["sourceRunIds"] == [run_id]
    collection_card = next(
        item for item in payload["latestRound"]["sourceCollectionStageCards"] if item["stageId"] == "finding"
    )
    assert collection_card["latestTask"]["taskId"] == "stagetask-existing-round"

def test_source_collection_stage_card_projection_resolves_current_stage_agents_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_id = "run-stage-card-projection-fast-path"
    stage_roles = {
        "finding": "source_finder",
        "extraction": "source_extractor",
        "relations": "source_relation_mapper",
        "ingestion": "source_ingestor",
    }
    for stage_id, agent_role in stage_roles.items():
        team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
            team["teamId"],
            run_id,
            {
                "taskId": f"task-{stage_id}",
                "stageId": stage_id,
                "agentId": f"agent-{stage_id}",
                "agentRole": agent_role,
                "sessionId": f"session-{stage_id}",
                "status": "completed",
                "summary": f"{stage_id} done",
                "updatedAt": f"2026-06-27T09:00:0{len(stage_id) % 10}Z",
            },
        )

    team_reads = []

    def counted_get_team(team_id):
        team_reads.append(team_id)
        return {
            "teamId": team_id,
            "members": [
                {"agentId": "agent-finding", "role": "source_finder"},
                {"agentId": "agent-extraction", "role": "source_extractor"},
                {"agentId": "agent-relations", "role": "source_relation_mapper"},
                {"agentId": "agent-ingestion", "role": "source_ingestor"},
            ],
        }

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", counted_get_team)

    projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(
        team["teamId"],
        run_id,
        run_status={"summary": {"recordCount": 1, "assignmentCount": 1, "openAssignmentCount": 0}},
    )

    assert len(projection["cards"]) == 4
    assert [card["stageId"] for card in projection["cards"]] == ["finding", "extraction", "relations", "ingestion"]
    assert team_reads == []

def test_source_collection_summary_records_slow_runtime_event(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.1038/slow-summary",
            "title": "Predictive coding evidence",
            "summary": "A source used to prove slow summary diagnostics.",
        },
    )
    ticks = iter([10.0, 11.6])
    events = []

    def fake_record_runtime_scene_event(component, category, event_code, **kwargs):
        events.append(
            {
                "component": component,
                "category": category,
                "eventCode": event_code,
                **kwargs,
            },
        )

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "time",
        SimpleNamespace(perf_counter=lambda: next(ticks)),
        raising=False,
    )
    monkeypatch.setattr(team_workflow_orchestration_service, "record_runtime_scene_event", fake_record_runtime_scene_event)

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)

    slow_events = [event for event in events if event["eventCode"] == "source_collection.summary.slow"]
    assert payload["summary"]["recordCount"] == 1
    assert len(slow_events) == 1
    assert slow_events[0]["fields"]["teamId"] == team["teamId"]
    assert slow_events[0]["fields"]["runId"] == run_id
    assert slow_events[0]["fields"]["durationMs"] == 1600
    assert slow_events[0]["fields"]["recordCount"] == 1
    assert slow_events[0]["fields"]["stageCardCount"] == 4

def test_source_collection_stage_card_projection_exposes_user_action_contract():
    running_card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "task-extraction-running",
                "stageId": "extraction",
                "status": "running",
                "summary": "正在分页提炼候选资料。",
                "updatedAt": "2026-06-27T09:10:00Z",
            }
        ],
        artifact_count=4,
        input_count=10,
        output_count=4,
        pending_count=6,
        artifact_status="partial",
        artifact_summary="4 source_manifest candidates; 4/10 assessed.",
    )

    assert running_card["userStatusLabel"] == "Agent 正在处理"
    assert running_card["userSummary"] == "Agent 正在处理本阶段，请等待结果同步。"
    assert running_card["actionReadiness"]["canStart"] is False
    assert running_card["actionReadiness"]["recommendedAction"] == "wait"
    assert running_card["actionReadiness"]["disabledReason"] == "已有 Agent 正在执行"

    interrupted_card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "task-extraction-interrupted",
                "stageId": "extraction",
                "status": "interrupted",
                "summary": "完成分页读取后被中断，尚未回写资料提炼结果。",
                "updatedAt": "2026-06-27T09:10:30Z",
            }
        ],
        artifact_count=0,
        input_count=10,
        output_count=0,
        pending_count=10,
        artifact_status="empty",
        artifact_summary="0 source_manifest candidates; 10 records need extraction.",
    )

    assert interrupted_card["status"] == "agent_interrupted"
    assert interrupted_card["userStatusLabel"] == "已中断，需要继续"
    assert "尚未回写" in interrupted_card["userSummary"]
    assert interrupted_card["actionReadiness"]["canStart"] is True
    assert interrupted_card["actionReadiness"]["recommendedAction"] == "continue"
    assert interrupted_card["actionReadiness"]["actionLabel"] == "继续这次任务"
    assert "最近一次 Agent 会话在阶段写回前中断，需要继续这次任务或重试。" in interrupted_card["blockingReasons"]

    partial_card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "extraction",
        [
            {
                "taskId": "task-extraction-partial",
                "stageId": "extraction",
                "status": "needs_review",
                "summary": "已提炼部分资料，需要继续补齐。",
                "updatedAt": "2026-06-27T09:11:00Z",
            }
        ],
        artifact_count=4,
        input_count=10,
        output_count=4,
        pending_count=6,
        artifact_status="partial",
        artifact_summary="4 source_manifest candidates; 4/10 assessed.",
    )

    assert partial_card["status"] == "partial_current_inputs"
    assert partial_card["userStatusLabel"] == "待补提炼"
    assert "已处理 4/10" in partial_card["userSummary"]
    assert partial_card["actionReadiness"]["canStart"] is True
    assert partial_card["actionReadiness"]["recommendedAction"] == "continue"
    assert partial_card["actionReadiness"]["actionLabel"] == "Agent 继续提炼"

    idle_relation_card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "relations",
        [],
        artifact_count=0,
        input_count=0,
        output_count=0,
        pending_count=0,
        artifact_status="empty",
        artifact_summary="0 graph nodes; 0 graph edges.",
    )

    assert idle_relation_card["userStatusLabel"] == "未开始"
    assert idle_relation_card["actionReadiness"]["canStart"] is False
    assert idle_relation_card["actionReadiness"]["recommendedAction"] == "wait"
    assert idle_relation_card["actionReadiness"]["disabledReason"] == "当前阶段还没有可执行输入"

def test_source_collection_stage_card_projection_keeps_ready_artifact_when_latest_task_blocked():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "finding",
        [
            {
                "taskId": "task-supplemental-search-blocked",
                "stageId": "finding",
                "status": "blocked",
                "summary": "Supplemental public search was blocked by low quality results.",
                "updatedAt": "2026-06-27T09:10:00Z",
                "evidenceRefs": [{"id": "tool-quality", "label": "search quality gate blocked"}],
                "nextActions": ["Use DOI direct acquisition for classic references."],
            }
        ],
        artifact_count=20,
        input_count=4,
        output_count=20,
        pending_count=3,
        artifact_status="ready",
        artifact_summary="20 DataRecord records; 3 assignments remain.",
        historical_task_count=1,
    )

    assert card["status"] == "artifact_ready_agent_blocked"
    assert card["agentTaskStatus"] == "blocked"
    assert card["artifactStatus"] == "ready"
    assert card["counts"]["artifact"] == 20
    assert card["latestTask"]["taskId"] == "task-supplemental-search-blocked"
    assert card["latestTask"]["status"] == "blocked"
    assert "Latest Agent task is blocked or failed." not in card["blockingReasons"]
    assert "Ready artifact exists, but the latest Agent task is blocked or failed." in card["blockingReasons"]

def test_source_collection_stage_card_projection_preserves_verified_success_after_blocked_retry():
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "ingestion",
        [
            {
                "taskId": "task-ingestion-success",
                "stageId": "ingestion",
                "status": "completed",
                "summary": "The approved knowledge package was formally synchronized.",
                "updatedAt": "2026-07-24T12:00:00Z",
                "completionGate": {"passed": True},
            },
            {
                "taskId": "task-ingestion-duplicate-retry",
                "stageId": "ingestion",
                "status": "blocked",
                "summary": "A duplicate retry did not locate the compact action packet.",
                "updatedAt": "2026-07-24T12:03:00Z",
                "completionGate": {"passed": False},
            },
        ],
        artifact_count=1,
        input_count=6,
        output_count=1,
        pending_count=0,
        artifact_status="ready",
        artifact_summary="1 steward package; 1 formal knowledge item synchronized.",
    )

    assert card["status"] == "closed_loop"
    assert card["isClosedLoop"] is True
    assert card["latestTask"]["taskId"] == "task-ingestion-duplicate-retry"
    assert card["agentTaskStatus"] == "blocked"


def test_source_collection_stage_card_projection_exposes_structured_knowledge_ingestion_payload():
    from core.web.routes.team_workflows.source_collection_catalog_models import (
        SourceCollectionStageCardResponse,
        SourceCollectionSummaryResponse,
    )

    materialized = {
        "status": "completed",
        "stewardPackCandidateId": "pack-ingestion-1",
        "knowledgeBaseId": "kb-ingestion-1",
        "approvedCandidateCount": 1,
        "approvedCandidateIds": ["candidate-1"],
        "formalKnowledgeItemCount": 1,
        "formalKnowledgeItemIds": ["knowledge-1"],
        "writesFormalKnowledge": True,
        "confidence": 0.94,
        "knowledgeSubmissionStatus": "completed",
        "knowledgeReviewStatus": "completed",
        "createdKnowledgeBaseId": "kb-ingestion-1",
        "skippedCount": 0,
        "failedCount": 0,
        "failed": [],
    }
    card = team_workflow_orchestration_service._source_collection_stage_card_projection(
        "ingestion",
        [
            {
                "taskId": "task-ingestion-structured",
                "stageId": "ingestion",
                "status": "completed",
                "updatedAt": "2026-07-24T12:00:00Z",
                "completionGate": {"passed": True},
                "writeback": {"materializedKnowledgeIngestion": materialized},
            },
        ],
        artifact_count=1,
        input_count=1,
        output_count=1,
        pending_count=0,
        artifact_status="ready",
        artifact_summary="1 formal knowledge item synchronized.",
    )

    assert card["latestTask"]["materializedKnowledgeIngestion"] == materialized
    response = SourceCollectionSummaryResponse.model_validate({"stageCards": [card]})
    assert isinstance(response.stageCards[0], SourceCollectionStageCardResponse)
    assert response.stageCards[0].latestTask.materializedKnowledgeIngestion.formalKnowledgeItemCount == 1
    assert response.stageCards[0].latestTask.materializedKnowledgeIngestion.formalKnowledgeItemIds == ["knowledge-1"]

def test_load_source_collection_work_run_summary_cleanses_invalid_storage_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    invalid_path = tmp_path / "workspace" / "legacy-source-collection-run"
    invalid_path.mkdir(parents=True, exist_ok=True)

    source_work_runs.persist_snapshot(
        team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
        {
            "runId": run_id,
            "runKind": team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
            "status": "running",
            "teamId": team["teamId"],
            "storagePath": str(invalid_path),
        },
        active_run_id=run_id,
    )

    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()

    assert summary["active"]["runId"] == run_id
    assert summary["latest"]["runId"] == run_id
    assert "storagePath" not in summary["active"]
    assert "pathValidationError" in summary["active"]
    assert "pathValidationError" in summary["latest"]

def test_load_source_collection_work_run_summary_marks_missing_data_run_stale(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    run_id = "dprun-missing-source-data-run"

    source_work_runs.persist_snapshot(
        team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
        {
            "runId": run_id,
            "runKind": team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
            "status": "running",
            "teamId": team["teamId"],
            "updatedAt": "2026-06-27T10:40:00Z",
        },
        active_run_id=run_id,
    )

    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()

    assert summary["active"] is None
    assert summary["activeItems"] == []
    assert summary["latest"]["runId"] == run_id
    assert summary["latest"]["dataRunExists"] is False
    assert summary["latest"]["staleReason"] == "missing_data_processing_run"
    assert "missing_data_processing_run" in summary["latest"]["staleReasons"]

def _seed_invalid_source_collection_active_work_run(
    *,
    tmp_path,
    monkeypatch,
    team_id: str,
    run_id: str,
    path_leaf: str,
) -> WorkRunStore:
    """Isolate WorkRunStore under tmp and seed an active snapshot with a bad storagePath.

    Product code filters non-active / stale snapshots to ``{}``; the store must stay
    process-local so xdist loadfile neighbors cannot clobber activeRunId.
    """
    source_work_runs = WorkRunStore(root=tmp_path / ".runtime" / "work_runs" / path_leaf)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_work_run_store",
        lambda: source_work_runs,
    )
    invalid_path = tmp_path / "workspace" / path_leaf
    invalid_path.mkdir(parents=True, exist_ok=True)
    source_work_runs.persist_snapshot(
        team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
        {
            "runId": run_id,
            "runKind": team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND,
            "status": "running",
            "currentPhase": "running",
            "teamId": team_id,
            "storagePath": str(invalid_path),
        },
        active_run_id=run_id,
    )
    seeded = source_work_runs.load_active_snapshot(
        team_workflow_orchestration_service.SOURCE_COLLECTION_WORK_RUN_KIND
    )
    assert isinstance(seeded, dict)
    assert seeded.get("runId") == run_id
    assert seeded.get("teamId") == team_id
    return source_work_runs


def test_source_collection_summary_cleanses_active_work_run_invalid_storage_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_invalid_source_collection_active_work_run(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        team_id=team["teamId"],
        run_id=run_id,
        path_leaf="legacy-source-collection-summary",
    )

    payload = team_workflow_orchestration_service.get_source_collection_summary(team["teamId"], run_id=run_id)
    active = payload.get("activeWorkRun")

    assert isinstance(active, dict) and active, "activeWorkRun should remain visible after path cleanse"
    assert active.get("runId") == run_id
    assert "storagePath" not in active
    assert "pathValidationError" in active

def test_source_collection_run_context_bundle_cleanses_invalid_active_storage_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_invalid_source_collection_active_work_run(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        team_id=team["teamId"],
        run_id=run_id,
        path_leaf="legacy-source-collection-context",
    )

    bundle = team_workflow_orchestration_service._source_collection_run_context_bundle(team["teamId"], run_id)
    active = bundle.get("activeWorkRun")

    assert isinstance(active, dict) and active, (
        "activeWorkRun must stay non-empty when snapshot is running for this team/run; "
        "empty {} used to raise KeyError('runId') under parallel suites"
    )
    assert active.get("runId") == run_id
    assert "storagePath" not in active
    assert "pathValidationError" in active


def test_challenge_stage_task_uses_configured_agent_model_without_official_evidence_qualification(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                        "schema_version": 1,
                "profiles": {},
                "model_library": {
                    "relay_openai/gpt-5.6-luna": {
                        "model": "gpt-5.6-luna",
                        "upstream_id": "gpt-5.6-luna",
                        "provider_id": "relay_openai",
                    }
                },
            }
        },
    )
    finder = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        llm_bindings={"dialogue": {"modelId": "relay_openai/gpt-5.6-luna"}},
    )
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": finder["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
            "questionId": "SCI-096",
            "requiredModelPolicy": {
                "providerIds": ["dashscope_main"],
                "modelIds": ["qwen3.6-plus"],
                "requireOfficialProvider": True,
            },
        },
    )
    submitted = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *args, **kwargs: (
            submitted.append((args, kwargs))
            or {
                "accepted": True,
                "turnId": "turn-configured-luna-1",
                "status": "running",
            }
        ),
    )

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {"stageId": "finding", "agentId": finder["agentId"], "agentRole": "source_finder"},
    )

    assert len(submitted) == 1
    assert task["task"]["challengeTaskContract"]["effectiveRoute"] == {
        "modelRef": "relay_openai/gpt-5.6-luna",
        "providerId": "relay_openai",
        "modelId": "gpt-5.6-luna",
    }
    assert task["task"]["challengeTaskContract"]["evidencePolicy"]["officialEvidenceEligible"] is False
    reconciled = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        team["teamId"],
        task["taskId"],
        run_id=run_response["run"]["runId"],
        session_id=task["sessionId"],
        turn_id="turn-configured-luna-1",
        final_status="completed",
        llm_usage={
            "source": "provider",
            "provider": "relay_openai",
            "model": "gpt-5.6-luna",
            "llmModelId": "relay_openai/gpt-5.6-luna",
        },
    )
    assert reconciled["officialModelEvidence"] == {}


def test_challenge_source_run_derives_required_policy_from_official_prompt_cache_route(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                        "schema_version": 1,
                "profiles": {},
                "model_library": {
                    "dashscope_main/qwen3.6-plus": {
                        "model": "qwen3.6-plus",
                        "upstream_id": "qwen3.6-plus",
                        "provider_id": "dashscope_main",
                        "prompt_cache": {"mode": "explicit_cache_control"},
                    }
                },
            }
        },
    )
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {
                "requirement": "required_for_llm_execution",
                "modelId": "dashscope_main/qwen3.6-plus",
            },
            "scope": {
                "questionId": "SCI-096",
                "workflowKind": "challenge_cup_research",
            },
        },
    )

    expected_policy = {
        "providerIds": ["dashscope_main"],
        "modelIds": ["qwen3.6-plus"],
        "requireOfficialProvider": True,
    }
    assert response["questionId"] == "SCI-096"
    assert response["requiredModelPolicy"] == expected_policy
    assert response["run"]["scope"]["requiredModelPolicy"] == expected_policy
    assert response["run"]["metadata"]["requiredModelPolicy"] == expected_policy


def test_legacy_challenge_stage_task_recovers_policy_from_prompt_cache_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                        "schema_version": 1,
                "profiles": {},
                "model_library": {
                    "dashscope_main/qwen3.6-plus": {
                        "model": "qwen3.6-plus",
                        "upstream_id": "qwen3.6-plus",
                        "provider_id": "dashscope_main",
                        "prompt_cache": {"mode": "explicit_cache_control"},
                    }
                },
            }
        },
    )
    finder = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        llm_bindings={"dialogue": {"modelId": "dashscope_main/qwen3.6-plus"}},
    )
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": finder["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {
                "requirement": "required_for_llm_execution",
                "modelId": "dashscope_main/qwen3.6-plus",
            },
        },
    )
    run_id = run_response["run"]["runId"]
    real_get_processing_run = data_processing_service.get_processing_run

    def legacy_get_processing_run(requested_run_id):
        run = real_get_processing_run(requested_run_id)
        if requested_run_id == run_id:
            run["scope"]["questionId"] = "SCI-096"
            run["scope"].pop("requiredModelPolicy", None)
            run["metadata"].pop("requiredModelPolicy", None)
        return run

    monkeypatch.setattr(data_processing_service, "get_processing_run", legacy_get_processing_run)
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-legacy-challenge-qwen-1",
            "status": "running",
        },
    )

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "finding", "agentId": finder["agentId"], "agentRole": "source_finder"},
    )

    assert task["task"]["challengeTaskContract"]["questionId"] == "SCI-096"
    assert task["task"]["challengeTaskContract"]["requiredModelPolicy"] == {
        "providerIds": ["dashscope_main"],
        "modelIds": ["qwen3.6-plus"],
        "requireOfficialProvider": True,
    }
    assert task["task"]["challengeTaskContract"]["effectiveRoute"] == {
        "modelRef": "dashscope_main/qwen3.6-plus",
        "providerId": "dashscope_main",
        "modelId": "qwen3.6-plus",
    }


def test_challenge_qwen_stage_task_records_bounded_canonical_evidence(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "schema_version": 1,
                "profiles": {},
                "model_library": {
                    "dashscope_main/qwen3.6-plus": {
                        "model": "qwen3.6-plus",
                        "upstream_id": "qwen3.6-plus",
                        "provider_id": "dashscope_main",
                    }
                },
            }
        },
    )
    finder = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        llm_bindings={"dialogue": {"modelId": "dashscope_main/qwen3.6-plus"}},
    )
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": finder["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    run_response = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": finder["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
            "questionId": "SCI-096",
            "requiredModelPolicy": canonical_model_policy(
                {
                    "family": "qwen",
                    "providerIds": ["dashscope_main"],
                    "modelIds": ["qwen3.6-plus"],
                    "requireOfficialProvider": True,
                }
            ),
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-challenge-qwen-1",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {"stageId": "finding", "agentId": finder["agentId"], "agentRole": "source_finder"},
    )

    _append_canonical_turn_output(
        tmp_path,
        {
            "sessionId": task["sessionId"],
            "turn": {"turnId": "turn-challenge-qwen-1"},
        },
        {"run": {"run_id": run_response["run"]["runId"]}},
    )

    reconciled = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
        team["teamId"],
        task["taskId"],
        run_id=run_response["run"]["runId"],
        session_id=task["sessionId"],
        turn_id="turn-challenge-qwen-1",
        final_status="completed",
        llm_usage={
            "source": "provider",
            "provider": "dashscope_main",
            "model": "qwen3.6-plus",
            "llmModelId": "dashscope_main/qwen3.6-plus",
            "inputTokens": 120,
            "outputTokens": 80,
            "totalTokens": 200,
        },
    )

    evidence = reconciled["officialModelEvidence"]
    assert task["task"]["challengeTaskContract"]["questionId"] == "SCI-096"
    assert task["task"]["challengeTaskContract"]["effectiveRoute"] == {
        "modelRef": "dashscope_main/qwen3.6-plus",
        "providerId": "dashscope_main",
        "modelId": "qwen3.6-plus",
    }
    assert task["task"]["challengeTaskContract"]["taskId"] == task["taskId"]
    assert task["task"]["challengeTaskContract"]["turnId"] == "turn-challenge-qwen-1"
    assert evidence["questionId"] == "SCI-096"
    assert evidence["taskId"] == task["taskId"]
    assert evidence["turnId"] == "turn-challenge-qwen-1"
    assert evidence["metadata"] == {
        "llmUsageSource": "provider",
        "inputTokens": 120,
        "outputTokens": 80,
        "totalTokens": 200,
    }
    assert "prompt" not in json.dumps(evidence).lower()
    project_root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        task["researchProjectId"],
    )
    stored = json.loads(
        (project_root / "official_model_evidence" / "index.json").read_text(encoding="utf-8")
    )
    assert [item["evidenceId"] for item in stored["evidence"]] == [evidence["evidenceId"]]


def _finding_close_first_step_task(
    tmp_path,
    monkeypatch,
    *,
    stage_id="finding",
    role="source_finder",
    role_label="资料寻找",
):
    """Start a stage session task for the finding close-first-step cases."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name=role_label)
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title=role_label)
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": role, "agentName": role_label}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "搜集可追踪资料",
            "agentRoles": [role],
            "agentIds": {role: agent["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]
    submitted: list[dict] = []

    def _capture_submit(session_id, content, **kwargs):
        submitted.append({"sessionId": session_id, "content": content})
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-{stage_id}-close-first-step",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", _capture_submit)
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": stage_id, "agentId": agent["agentId"], "agentRole": role},
    )
    return {"team": team, "runId": run_id, "task": task, "submitted": submitted}


def _append_single_context_tool_event(tmp_path, task) -> None:
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        task["turn"]["turnId"],
        "tool_result",
        status="done",
        payload={
            "toolCall": {
                "name": "source_collection_context_tool",
                "status": "done",
                "args": {"task_id": task["taskId"]},
                "result": "stage tool completed",
            }
        },
    )


def test_finding_close_first_step_checklist_single_read_and_gate(tmp_path, monkeypatch):
    """finding checklist 奖励单次读取；门禁一次成功读取即勾，不再等翻页或产物。"""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]

    checklist = {item["id"]: item for item in task["task"]["taskChecklist"]}
    assert "一次读取当前上下文" in checklist["page_existing_sources"]["description"]
    assert "无需翻页" in checklist["page_existing_sources"]["description"]

    extraction_by_id = {
        item["id"]: item
        for item in team_workflow_orchestration_service._source_collection_stage_task_checklist("extraction")
    }
    assert extraction_by_id["page_candidate_inputs"]["description"] == "分页覆盖本阶段输入"

    _append_single_context_tool_event(tmp_path, task["task"])
    # blocked 写回不带任何产物：artifactComplete=False 时单次成功读取也应勾选该项。
    blocked = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {"status": "blocked", "summary": "读取后暂无可写回线索，先阻塞。"},
    )
    progress = blocked["task"]["taskToolProgress"]
    assert blocked["writeback"]["closureSummary"]["artifactComplete"] is False
    assert "page_existing_sources" in progress["completedIds"]
    assert "page_existing_sources" not in progress["pendingIds"]

    assert "一次性读取当前批上下文" in env["submitted"][0]["content"]
    assert "补读必要页" not in env["submitted"][0]["content"]
    assert "写回预算" in env["submitted"][0]["content"]
    assert "总计最多接受 8 条去重来源" in env["submitted"][0]["content"]
    assert "每批 `candidateLeads[]` 最多 4 条" in env["submitted"][0]["content"]


def test_finding_close_first_step_context_has_no_continuation_invite(tmp_path, monkeypatch):
    """finding 上下文不再下发续读邀请：hasMore 恒为 false、continuationHint 置空。"""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]
    for index in range(7):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding finding candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/finding-close-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for finding close-first-step context. " * 3,
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/finding-close-{index}",
                },
                "createdByAgent": "source-finder",
            },
        )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        max_records=1,
        candidate_offset=0,
        candidate_limit=5,
        context_mode="compact",
    )
    assert context["stageId"] == "finding"
    assert context["candidatePage"]["total"] == 7
    assert context["candidatePage"]["returned"] == 5
    assert context["candidatePage"]["hasMore"] is False
    assert context["candidatePage"]["nextOffset"] == 5
    assert context["usage"]["continuationHint"] == ""
    assert "candidate_offset" not in json.dumps(context["usage"], ensure_ascii=False)


def test_finding_close_first_step_writeback_batch_limit_and_replay(tmp_path, monkeypatch):
    """第五个不同批次被拒；同批重放幂等且不重复消耗来源预算。"""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]

    lead_a = {
        "leadId": "lead-close-a",
        "title": "Predictive coding in the visual cortex",
        "locator": "https://doi.org/10.1038/4580",
        "sourceType": "paper",
        "query": "predictive coding mechanism",
        "perspective": "mechanism",
    }

    def _payload(lead):
        return {
            "status": "needs_review",
            "summary": "写回一批候选线索。",
            "result": {"candidateLeads": [lead]},
        }

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        _payload(lead_a),
    )
    assert first["writeback"]["materializedSources"]["sourceLeadCount"] == 1

    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(
        team["teamId"], run_id
    )
    stored_task = next(item for item in store["tasks"] if item["taskId"] == task["taskId"])
    assert len(stored_task["sourceCollectionWritebackBatches"]) == 1
    assert stored_task["sourceCollectionWritebackBatches"][0]["leadCount"] == 1

    replay = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        _payload(lead_a),
    )
    assert replay["writeback"]["materializedSources"]["createdRecordCount"] == 0
    assert replay["writeback"]["materializedSources"]["skippedDuplicateCount"] == 1

    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(
        team["teamId"], run_id
    )
    stored_task = next(item for item in store["tasks"] if item["taskId"] == task["taskId"])
    assert len(stored_task["sourceCollectionWritebackBatches"]) == 1

    for suffix in ("b", "c", "d"):
        next_lead = dict(
            lead_a,
            leadId=f"lead-close-{suffix}",
            title=f"Distinct source {suffix}",
            locator=f"https://example.test/{suffix}",
        )
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            team["teamId"],
            task["taskId"],
            _payload(next_lead),
        )
    lead_e = dict(
        lead_a,
        leadId="lead-close-e",
        title="Distinct source e",
        locator="https://example.test/e",
    )
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="检索批次已达上限",
    ) as exc_info:
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            team["teamId"],
            task["taskId"],
            _payload(lead_e),
        )
    assert "请立即以现有 searchTrace[] 与 candidateLeads[] 写回收口并结束任务" in str(exc_info.value)
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 4


def test_finding_running_writebacks_materialize_and_close_at_frozen_lead_limit(
    tmp_path,
    monkeypatch,
):
    """Two rolling batches persist immediately and the frozen cap closes the task."""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]
    perspectives = [
        "mechanism",
        "independent_baseline",
        "limitation_or_null",
        "falsification",
    ]

    def _batch(offset: int):
        return {
            "status": "running",
            "summary": f"滚动写回第 {offset // 4 + 1} 批候选线索。",
            "result": {
                "candidateLeads": [
                    {
                        "title": f"Bounded source {index}",
                        "locator": f"https://example.test/bounded-{index}",
                        "sourceType": "paper",
                        "summary": f"Bounded evidence summary {index}",
                        "query": f"bounded query {index}",
                        "perspective": perspectives[index % len(perspectives)],
                    }
                    for index in range(offset, offset + 4)
                ],
                "invalidSources": [],
            },
        }

    for tool_name in ("source_collection_context_tool", "batch_web_search_tool"):
        append_conversation_event(
            tmp_path,
            task["sessionId"],
            task["turn"]["turnId"],
            "tool_result",
            status="done",
            payload={
                "toolCall": {
                    "name": tool_name,
                    "status": "done",
                    "args": {"task_id": task["taskId"]},
                    "result": "stage tool completed",
                }
            },
        )

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        _batch(0),
    )
    assert first["writeback"]["status"] == "running"
    assert first["writeback"]["materializedSources"]["createdRecordCount"] == 4
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 4
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        task["turn"]["turnId"],
        "tool_result",
        status="done",
        payload={
            "toolCall": {
                "name": "source_collection_stage_writeback_tool",
                "status": "done",
                "args": {"task_id": task["taskId"]},
                "result": "first rolling batch materialized",
            }
        },
    )

    second = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        _batch(4),
    )
    assert second["writeback"]["agentRequestedStatus"] == "running"
    assert second["writeback"]["status"] == "completed", {
        "status": second["writeback"]["status"],
        "closureSummary": second["writeback"]["closureSummary"],
        "taskToolProgress": second["task"]["taskToolProgress"],
    }
    assert second["writeback"]["autoCloseReason"] == "finding_search_envelope_saturated"
    assert second["task"]["status"] == "completed"
    assert len(second["task"]["sourceCollectionWritebackBatches"]) == 2
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 8


def test_finding_close_first_step_writeback_rejects_oversized_lead_batch(tmp_path, monkeypatch):
    """单批 candidateLeads[] 超过每批上限即拒绝整批，不物化任何来源。"""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]
    leads = [
        {
            "leadId": f"lead-over-{index}",
            "title": f"Predictive coding oversized lead {index}",
            "locator": f"https://doi.org/10.2000/over-{index}",
            "sourceType": "paper",
            "query": "predictive coding",
            "perspective": "mechanism",
        }
        for index in range(6)
    ]
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="每批最多 4 条",
    ):
        team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            team["teamId"],
            task["taskId"],
            {"status": "needs_review", "summary": "单批超限。", "result": {"candidateLeads": leads}},
        )
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 0


def test_extraction_stage_pagination_and_invite_regression_unchanged(tmp_path, monkeypatch):
    """extraction 翻页、续读邀请与分页 checklist 保持现状，finding 收紧不外溢。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码皮层层级",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding cortical hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    _seed_source_collection_raw_records(run_id)
    for index in range(7):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding extraction candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/extraction-regression-{index}",
                "sourceKind": "paper",
                "summary": "Neural predictive coding evidence for extraction regression. " * 4,
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/extraction-regression-{index}",
                },
                "createdByAgent": "content-extraction-agent",
            },
        )
    submitted: list[dict] = []

    def _capture_submit(session_id, content, **kwargs):
        submitted.append({"content": content})
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-extraction-regression",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", _capture_submit)
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    first_page = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        max_records=1,
        candidate_offset=0,
        candidate_limit=5,
        context_mode="compact",
    )
    assert first_page["stageId"] == "extraction"
    assert first_page["candidatePage"]["hasMore"] is True
    assert first_page["candidatePage"]["nextOffset"] == 5
    assert "candidate_offset=5" in first_page["usage"]["continuationHint"]

    assert "补读必要页" in submitted[0]["content"]
    assert "分页覆盖本阶段输入" in submitted[0]["content"]
    assert "写回预算" not in submitted[0]["content"]


def test_stage_task_store_follows_run_owner_project_after_active_project_switch(tmp_path, monkeypatch):
    """根因 A：stage 任务账本与 run 产物路径按 run 属主项目解析，不随活跃项目漂移。

    复现 run-16cfab646d08：run 属主 challenge-sci-003，账本却落/读在 challenge-sci-001。
    """
    from core.web.services.team_workflow import research_projects as research_projects_service

    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]

    run_scope = (data_processing_service.get_processing_run(run_id).get("scope") or {})
    owner_project_id = str(run_scope.get("researchProjectId") or "")
    assert owner_project_id

    owner_store_path = (
        Path(
            team_workflow_orchestration_service._source_collection_storage_artifact_paths(
                team["teamId"], run_id
            )["runDirectory"]
        )
        / "stage_session_tasks.json"
    )
    assert owner_store_path.exists()

    project_b = research_projects_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-001-sim"}
    )["project"]
    research_projects_service.activate_research_project(team["teamId"], project_b["projectId"])

    # 读：切换活跃项目后，属主项目下的账本仍然可见（优先生主项目）。
    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(
        team["teamId"], run_id
    )
    assert [item["taskId"] for item in store["tasks"]] == [task["taskId"]]

    # 写：账本更新归一到属主项目，不再落到活跃项目 B。
    store["tasks"][0]["status"] = "completed"
    team_workflow_orchestration_service._write_source_collection_stage_session_task_store(
        team["teamId"], run_id, store
    )
    active_project_root = research_projects_service.resolve_research_project_workspace_root(
        team["teamId"], project_b["projectId"]
    )
    assert not (active_project_root / "source_collection_runs" / run_id / "stage_session_tasks.json").exists()

    # 兼容读取：修复前错位落在活跃项目根的存量账本也能被读到。
    misplaced_directory = active_project_root / "source_collection_runs" / run_id
    misplaced_directory.mkdir(parents=True, exist_ok=True)
    owner_store_path.rename(misplaced_directory / "stage_session_tasks.json")
    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(
        team["teamId"], run_id
    )
    assert [item["taskId"] for item in store["tasks"]] == [task["taskId"]]

    # run 产物路径权威同样按属主项目解析。
    paths = team_workflow_orchestration_service._source_collection_storage_artifact_paths(
        team["teamId"], run_id
    )
    owner_root = research_projects_service.resolve_research_project_workspace_root(
        team["teamId"], owner_project_id
    )
    assert Path(paths["runDirectory"]).is_relative_to(owner_root)


def test_relations_graph_materialization_and_precheck_follow_run_owner_store(tmp_path, monkeypatch):
    """关系图物化与入库预检按 run 属主 store 读写，不随活跃项目漂移。

    复现 run-16cfab646d08：relations 写回物化把 candidate_graph 记录落在活跃项目
    store（challenge-sci-001），入库预检读到陈旧 graph（有节点 0 边）被拦。
    同时覆盖 candidateRelations[]（relations 契约规范输出）必须物化进图边。
    """
    from core.web.services.team_workflow import research_projects as research_projects_service

    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    stage_response = _start_research_stage_round_with_problem_understanding(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "搜集可追踪资料",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = stage_response["run"]["runId"]

    def _capture_submit(session_id, content, **kwargs):
        return {"accepted": True, "sessionId": session_id, "turnId": "turn-relations-owner-store", "status": "running"}

    monkeypatch.setattr(session_service, "submit_session_message", _capture_submit)

    # relations 开任务前置门：先落候选，再开阶段任务。
    candidate_ids: list[str] = []
    for index in range(3):
        candidate = team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Predictive coding relation candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/relation-regression-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for relation regression. " * 4,
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id},
                "createdByAgent": "relation-mapper-agent",
            },
        )["candidate"]
        candidate_ids.append(candidate["candidateId"])

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )

    project_b = research_projects_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-001-sim"}
    )["project"]
    research_projects_service.activate_research_project(team["teamId"], project_b["projectId"])

    owner_store_path = team_workflow_orchestration_service._candidate_store_path(team["teamId"], run_id)
    active_store_path = team_workflow_orchestration_service._candidate_store_path(team["teamId"])
    assert owner_store_path != active_store_path

    # 模拟修复前错位：a1 时代的陈旧 graph（有节点 0 边）挂在活跃项目 B 的 store。
    stale_record = {
        "schemaVersion": team_workflow_orchestration_service.SCHEMA_VERSION,
        "candidateId": "candidate-graph-stale-misplaced",
        "candidateType": "candidate_graph",
        "teamId": team["teamId"],
        "workflowId": "workflow-stale",
        "title": "Stale candidate graph snapshot",
        "sourceKind": "candidate_graph_builder",
        "summary": "2 nodes, 0 edges",
        "sourceRefs": [],
        "evidenceRefs": [],
        "metadata": {
            "generatedFromCandidateIds": candidate_ids[:1],
            "graph": {
                "nodes": [
                    {"candidateId": candidate_ids[0], "candidateType": "source_manifest", "title": "stale node"},
                ],
                "edges": [],
                "missingLinks": [],
                "unreviewedNodes": [],
                "summary": {"nodeCount": 1, "edgeCount": 0, "missingLinkCount": 0},
            },
            "knowledgeCollectionIngestion": {
                "fingerprint": "stale-fingerprint",
                "purpose": "candidate_graph",
                "inputCandidateIds": candidate_ids[:1],
                "sourceCollectionRunId": run_id,
            },
        },
        "createdByAgent": "relation-mapper-agent",
        "currentWorkflowNode": "candidate_graph",
        "currentState": "candidate_graph_visible",
        "qualityStatus": "preview_ready",
        "createdAt": "2026-08-01T00:00:00+00:00",
        "updatedAt": "2026-08-01T00:00:00+00:00",
    }
    active_store = team_workflow_orchestration_service._read_json(active_store_path)
    active_store.setdefault("candidates", []).append(stale_record)
    team_workflow_orchestration_service._write_json(active_store_path, active_store)

    agent_graph = {
        "themeNodes": [
            {"themeId": "theme-prediction-error", "label": "预测误差"},
            {"themeId": "theme-hierarchical-models", "label": "层级模型"},
        ],
        "candidateRelations": [
            {
                "sourceCandidateId": candidate_ids[0],
                "targetCandidateId": "theme-prediction-error",
                "relation": "supports_theme",
                "evidenceRefs": ["ev-1"],
            },
            {
                "sourceCandidateId": candidate_ids[1],
                "targetCandidateId": "theme-hierarchical-models",
                "relation": "extends_theme",
                "evidenceRefs": ["ev-2"],
            },
            {
                "sourceCandidateId": candidate_ids[0],
                "targetCandidateId": candidate_ids[1],
                "relation": "complements_evidence",
                "evidenceRefs": ["ev-3"],
            },
            {
                "sourceCandidateId": candidate_ids[2],
                "targetCandidateId": candidate_ids[1],
                "relation": "replicates_finding",
                "evidenceRefs": ["ev-4"],
            },
        ],
    }
    summary = team_workflow_orchestration_service._materialize_source_collection_stage_writeback_candidate_graph(
        team["teamId"],
        run_id,
        task,
        {"status": "needs_review", "result": {"candidateGraph": agent_graph}},
    )
    assert summary["status"] == "completed"
    assert summary["edgeCount"] == 4
    assert summary["nodeCount"] == 5
    assert summary["danglingEdgeCount"] == 0

    # 新图（含 4 条 candidateRelations 物化边）落在 run 属主 store。
    owner_store = team_workflow_orchestration_service._read_json(owner_store_path)
    owner_graphs = [
        item for item in list(owner_store.get("candidates") or []) if item.get("candidateType") == "candidate_graph"
    ]
    fresh_records = [item for item in owner_graphs if item.get("candidateId") == summary["candidateGraphId"]]
    assert len(fresh_records) == 1
    fresh_record = fresh_records[0]
    assert fresh_record["metadata"]["graph"]["summary"]["edgeCount"] == 4
    assert fresh_record["metadata"]["graph"]["summary"]["nodeCount"] == 5
    assert [item["taskId"] for item in fresh_record["metadata"].get("stageTaskWritebacks") or []] == [task["taskId"]]
    # 访问即认领：写回把活跃项目 store 的存量记录一并归一到属主 store（读侧按 candidateId 去重）。
    assert "candidate-graph-stale-misplaced" in [item.get("candidateId") for item in owner_graphs]
    # 活跃项目 B 的 store 不新增图记录，只剩错位存量。
    active_after = team_workflow_orchestration_service._read_json(active_store_path)
    assert [
        item.get("candidateId")
        for item in list(active_after.get("candidates") or [])
        if item.get("candidateType") == "candidate_graph"
    ] == ["candidate-graph-stale-misplaced"]

    # 入库预检（run-scoped 合并读）能看到最新图：5 节点 / 4 边 / 0 缺口，门禁放行。
    from core.web.services.team_workflow.source_collection.stage_session import (
        _source_collection_run_graph_metrics,
        assert_source_collection_stage_advance_ready,
    )

    source_candidates = team_workflow_orchestration_service._source_collection_candidates_for_run(
        team["teamId"], run_id
    )
    metrics = _source_collection_run_graph_metrics(team["teamId"], run_id, source_candidates)
    assert metrics == {"nodeCount": 5, "edgeCount": 4, "missingLinkCount": 0}
    assert_source_collection_stage_advance_ready(
        stage_id="ingestion",
        record_count=1,
        approved_or_source_candidate_count=len(source_candidates),
        graph_node_count=metrics["nodeCount"],
        graph_edge_count=metrics["edgeCount"],
        graph_missing_link_count=metrics["missingLinkCount"],
    )


def test_agent_graph_edges_extract_candidate_relations_contract_payload() -> None:
    """candidateRelations[] 是 relations 写回契约的规范输出，边提取必须解析它。

    复现 a3 写回：15 条 candidateRelations 因提取器只认 edges/sourceThemeEdges/
    topicRelations 被整体丢弃，图停留在 0 边，而闭门判定仍报 candidate_graph_ready。
    """
    agent_graph = {
        "themeNodes": [
            {"themeId": "theme-numerical-verification", "label": "数值验证"},
            {"themeId": "theme-analytic-progress", "label": "解析进展"},
        ],
        "candidateRelations": [
            {
                "sourceCandidateId": "candidate-a",
                "targetCandidateId": "theme-numerical-verification",
                "relation": "independent_strict_verification_baseline",
                "evidenceRefs": ["dprec-1"],
            },
            {
                "from": "candidate-b",
                "to": "candidate-c",
                "type": "complementary_numerical_coverage",
            },
            {
                "sourceCandidateId": "theme-numerical-verification",
                "targetCandidateId": "theme-analytic-progress",
                "relation": "grounds_progress",
                "evidenceRefs": ["dprec-2"],
            },
        ],
    }
    edges = team_workflow_orchestration_service._source_collection_agent_graph_edges(agent_graph)
    assert len(edges) == 3
    by_relation = {edge["relation"]: edge for edge in edges}
    assert by_relation["independent_strict_verification_baseline"]["targetCandidateId"] == (
        "source-theme:theme-numerical-verification"
    )
    assert by_relation["independent_strict_verification_baseline"]["sourceCandidateId"] == "candidate-a"
    assert by_relation["independent_strict_verification_baseline"]["evidenceRefs"] == ["dprec-1"]
    assert by_relation["complementary_numerical_coverage"]["sourceCandidateId"] == "candidate-b"
    assert by_relation["complementary_numerical_coverage"]["targetCandidateId"] == "candidate-c"
    assert by_relation["grounds_progress"]["sourceCandidateId"] == "source-theme:theme-numerical-verification"
    assert by_relation["grounds_progress"]["targetCandidateId"] == "source-theme:theme-analytic-progress"


def test_finding_writeback_candidates_carry_scope_markers(tmp_path, monkeypatch):
    """根因 B：finding 写回物化创建的候选带 SC run / workflow run / 研究项目三类定界标记。"""
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team = env["team"]
    run_id = env["runId"]
    task = env["task"]

    lead = {
        "leadId": "lead-scope-marker",
        "title": "Predictive coding with scope markers",
        "locator": "https://doi.org/10.1038/scope",
        "sourceType": "paper",
        "query": "predictive coding",
        "perspective": "mechanism",
    }
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {"status": "needs_review", "summary": "写回一条带标记候选。", "result": {"candidateLeads": [lead]}},
    )
    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 1

    run_scope = (data_processing_service.get_processing_run(run_id).get("scope") or {})
    candidates = team_workflow_orchestration_service._source_collection_candidates_for_run(
        team["teamId"], run_id
    )
    assert len(candidates) == 1
    metadata = candidates[0].get("metadata") if isinstance(candidates[0].get("metadata"), dict) else {}
    assert metadata.get("sourceCollectionRunId") == run_id
    assert metadata.get("researchProjectId") == str(run_scope.get("researchProjectId") or "")
    assert metadata.get("workflowRunId") == str(run_scope.get("workflowRunId") or "")
