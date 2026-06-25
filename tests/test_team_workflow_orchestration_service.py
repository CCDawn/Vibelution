import json
from concurrent.futures import Future
from pathlib import Path

import pytest

from core.agent_kernel import service as agent_kernel_service
from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    data_processing_service,
    project_agent_bus_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)

pytestmark = pytest.mark.serial


def test_source_collection_stage_round_sync_has_single_implementation():
    service_path = Path(team_workflow_orchestration_service.__file__)
    source = service_path.read_text(encoding="utf-8")

    assert source.count("def _sync_source_collection_stage_round_after_search(") == 1


class _FakeLocalResearchMessage:
    def __init__(self, content, *, reasoning_content=""):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning_content} if reasoning_content else {}


class _FakeLocalResearchClient:
    response = _FakeLocalResearchMessage("{}")
    captured_messages = []

    def __init__(self, *, config=None, profile_id=None):
        self.config = config
        self.profile_id = profile_id

    def invoke(self, messages, tools=None, metadata=None):
        type(self).captured_messages.append({"messages": messages, "metadata": metadata, "profile_id": self.profile_id})
        return type(self).response


class _NoopBackgroundExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append({"fn": fn, "args": args, "kwargs": kwargs})
        future = Future()
        future.set_result(None)
        return future


def _fake_local_research_public_config(*, prompt_cache_mode="explicit_cache_control"):
    return {
        "llm": {
            "profiles": {},
            "model_library": {
                "houmo_qwen35_9b_agent": {
                    "model": "qwen3.5-9b",
                    "provider": "local",
                    "prompt_cache": {"mode": prompt_cache_mode},
                }
            },
        }
    }


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "load_public_config", _fake_local_research_public_config)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _NoopBackgroundExecutor())


def _capture_workflow_events(monkeypatch):
    events = []

    def fake_record_runtime_scene_event(*args, **kwargs):
        events.append((args, kwargs))
        return {"accepted": True, "path": kwargs.get("child_log_path", "")}

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "record_runtime_scene_event",
        fake_record_runtime_scene_event,
    )
    return events


def _workflow_scene_events_by_code(events, event_code):
    return [
        kwargs
        for args, kwargs in events
        if len(args) >= 3 and args[2] == event_code
    ]


def _stub_source_collection_search_background(monkeypatch):
    calls = []

    def fake_start(team_id, run_id, payload=None):
        calls.append({"teamId": team_id, "runId": run_id, "payload": dict(payload or {})})
        run = data_processing_service.get_processing_run(run_id)
        assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
        run_status = data_processing_service.get_processing_status(run_id)
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "runId": run_id,
            "status": "accepted",
            "executionMode": "background",
            "accepted": True,
            "provider": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "executedQueryCount": 0,
            "skippedQueryCount": 0,
            "failedQueryCount": 0,
            "resultCount": 0,
            "recordCount": 0,
            "outputCount": 0,
            "importedCount": 0,
            "run": run,
            "runStatus": run_status,
            "storageArtifacts": {"runDirectory": f"workspace/teams/{team_id}/source_collection_runs/{run_id}"},
            "assignments": assignments,
            "outputs": [],
            "createdRecords": [],
            "imported": [],
            "executionEvents": [],
            "activeWorkRun": {
                "runId": run_id,
                "status": "queued",
                "currentPhase": "queued",
                "summary": "资料搜索已进入后台执行，页面可继续操作。",
                "openAssignmentCount": len(assignments),
                "recordCount": 0,
                "queryCount": 1,
                "storagePath": f"workspace/teams/{team_id}/source_collection_runs/{run_id}",
            },
            "boundaries": {
                "externalSearchTriggered": False,
                "externalSearchQueued": True,
                "metadataOnlyDownload": True,
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
            },
            "nextActions": [],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "start_source_collection_search_background", fake_start)
    return calls


def _use_fake_local_research_config(monkeypatch):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "profiles": {},
                "model_library": {
                    "houmo_qwen35_9b_agent": {
                        "model": "qwen3.5-9b",
                        "provider": "local",
                        "prompt_cache": {"mode": "explicit_cache_control"},
                    }
                },
            }
        },
    )
    monkeypatch.setattr(team_workflow_orchestration_service, "build_effective_config", lambda public_config: public_config)


def _steward_pack_output(*, candidate_ids=None, confidence=0.61):
    normalized_candidate_ids = list(candidate_ids or ["hypothesis-1", "review-1"])
    return {
        "candidateType": "review_record",
        "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
        "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
        "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
        "candidateIds": normalized_candidate_ids,
        "targetDomain": "challenge_cup_neuro_algorithm",
        "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"], "candidateGraphId": "graph-1"},
        "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
        "proposalPayload": {"title": "Govern context-gated routing hypothesis", "summary": "Add the hypothesis as governed knowledge."},
        "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.66, "stability": "evolving", "reviewPriority": "elevated"},
        "approvalRequired": True,
        "uncertainty": ["experiment not yet validated"],
        "riskFlags": ["approval_required"],
        "confidence": confidence,
        "nextAction": "send_to_ingestion_approval_gate",
        "requiresReview": True,
    }


def _submit_steward_pack_through_source_review(team_id: str, candidate_id: str, knowledge_base_id: str, steward_agent_id: str) -> dict:
    source_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {"knowledgeBaseId": knowledge_base_id, "proposedByAgentId": steward_agent_id},
    )
    inbox_source_id = source_pending["candidate"]["metadata"]["knowledgeIngestion"]["inboxSourceId"]
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source_id,
        decision="accepted",
        reviewed_by_agent_id=steward_agent_id,
    )
    knowledge_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {
            "knowledgeBaseId": knowledge_base_id,
            "proposedByAgentId": steward_agent_id,
            "centralSourceId": reviewed["centralSource"]["centralSourceId"],
        },
    )
    return {"sourcePending": source_pending, "reviewedSource": reviewed, "knowledgePending": knowledge_pending}


def _fake_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "Predictive coding cortical hierarchy",
                "sourceRef": "https://doi.org/10.0000/predictive-coding",
                "rawLocation": "https://api.example.test/works/10.0000/predictive-coding",
                "summary": "Metadata-only result for a predictive coding paper.",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/predictive-coding", "containerTitle": "Journal of Neural Computation"},
                "qualitySignals": {"providerScore": 98.7, "hasDoi": True},
            },
            {
                "title": "Cortical hierarchy dataset",
                "sourceRef": "https://doi.org/10.0000/cortical-dataset",
                "rawLocation": "https://api.example.test/works/10.0000/cortical-dataset",
                "summary": "Metadata-only result for a related dataset.",
                "sourceType": "dataset",
                "metadata": {"doi": "10.0000/cortical-dataset", "containerTitle": "Neural Data Archive"},
                "qualitySignals": {"providerScore": 87.5, "hasDoi": True},
            },
        ][:max_results],
    }


def _create_experiment_plan_with_active_baseline(team_id):
    team_workflow_orchestration_service.record_local_research_model_output(
        team_id,
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team_id,
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )
    baseline = team_workflow_orchestration_service.register_experiment_baseline_artifact(
        team_id,
        draft["plan"]["planId"],
        {
            "artifactPath": "workspace/experiments/baselines/standard-moe-router.json",
            "reproductionCommand": "python experiments/run_baseline.py --config configs/standard_moe_router.yaml",
            "evaluationCommand": "python experiments/evaluate.py --run standard-moe-router",
            "metricValue": "0.71 validation accuracy",
            "registeredByAgent": "Experiment Planning Agent",
        },
    )
    return {"stage": stage, "draft": draft, "baseline": baseline}


def test_challenge_cup_workflow_registers_candidate_and_decides_transfer(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    workflow = team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    candidate_response = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Neuromodulation review",
            "sourceUrl": "https://example.test/paper",
            "sourceKind": "paper",
            "tags": ["neuro", "screening"],
            "createdByAgent": "Knowledge Collection Agent",
        },
    )
    candidate = candidate_response["candidate"]
    transfer_response = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": candidate["candidateId"],
            "fromNode": "knowledge_collection",
            "toNode": "source_screening",
            "requestedByAgent": "Knowledge Collection Agent",
            "reason": "资料已收集，进入筛选。",
        },
    )
    decision_response = team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        transfer_response["transfer"]["transferId"],
        {
            "decision": "approved",
            "decidedByAgent": workflow["ownerAgentId"],
            "targetState": "screening_ready",
        },
    )

    assert workflow["workflowKind"] == "challenge_cup_research"
    assert workflow["transferPolicy"]["requiresUserConfirmation"] is False
    assert workflow["transferPolicy"]["decidedBy"] == workflow["ownerAgentId"]
    assert workflow["routingPolicy"]["finalStateWriter"] == workflow["ownerAgentId"]
    assert candidate["candidateType"] == "source_manifest"
    assert transfer_response["transfer"]["requiresUserConfirmation"] is False
    assert decision_response["transfer"]["decidedByAgent"] == workflow["ownerAgentId"]
    assert decision_response["candidate"]["currentWorkflowNode"] == "source_screening"
    assert decision_response["candidate"]["currentState"] == "screening_ready"
    assert decision_response["workflow"]["candidateStore"]["candidateCount"] == 1


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
            "agentRole": "content_extraction",
            "agentId": "content-extraction-agent",
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
            "extractionAgentId": "content-extraction-agent",
            "maxRecords": 10,
        },
    )
    duplicate = team_workflow_orchestration_service.extract_source_collection_candidates(
        team["teamId"],
        {
            "runId": run["runId"],
            "extractionAgentId": "content-extraction-agent",
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
        {"agentRole": "content_extraction", "agentId": "content-extraction-agent"},
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
            "extractionAgentId": "content-extraction-agent",
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
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Neurology source batch",
            "goal": "Collect sources about neural gating.",
            "topic": "neural gating",
            "requestedByAgent": "Research Coordination Agent",
            "agentRoles": ["data_discovery", "source_acquisition", "content_extraction"],
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
    assert response["assignmentCount"] == 3
    assert {item["agentRole"] for item in response["assignments"]} == {"data_discovery", "source_acquisition", "content_extraction"}
    assert all(item["inputRefs"] == ["seed-query:neural gating"] for item in response["assignments"])
    assert all(item["scope"]["dataSearchPlanRef"]["planId"] == response["searchPlan"]["planId"] for item in response["assignments"])
    assert all(item["scope"]["assignedQueries"] for item in response["assignments"])
    assert all(item["scope"]["promptCachePolicyRef"]["gateStatus"] == "satisfied" for item in response["assignments"])
    assert all(item["scope"]["promptCachePartition"].startswith("research-team-") for item in response["assignments"])
    assert all(item["execution"]["promptCacheRequired"] is True for item in response["searchPlan"]["queries"])
    assert all(item["execution"]["promptCachePartition"].startswith("research-team-") for item in response["searchPlan"]["queries"])
    assert all(item["scope"]["resultWritebackContract"]["ragWrites"] is False for item in response["assignments"])
    assert assignments["summary"]["assignmentCount"] == 3
    assert run_status["boundaries"]["writesFormalKnowledge"] is False
    assert response["workflow"]["activeWorkflowItems"][0]["candidateId"] == response["run"]["runId"]
    assert response["workflow"]["activeWorkflowItems"][0]["status"] == "source_collection_started"


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


def test_start_source_collection_run_ignores_invalid_collection_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {"agentRoles": ["data_discovery", "research_specific_role"]},
    )

    assert response["assignmentCount"] == 1
    assert response["assignments"][0]["agentRole"] == "data_discovery"


def test_start_source_collection_run_maps_roles_to_team_canvas_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    coordinator = session_service.create_chat_session(title="Coordinator")
    discovery = session_service.create_chat_session(title="Discovery")
    acquisition = session_service.create_chat_session(title="Acquisition")
    extraction = session_service.create_chat_session(title="Extraction")
    organization = {
        "agents": [
            {"nodeId": "coordinator", "agentId": coordinator["agentId"], "displayName": "Coordinator", "role": "ceo", "status": "active"},
            {"nodeId": "discovery", "agentId": discovery["agentId"], "displayName": "Discovery", "role": "data_discovery", "status": "active"},
            {"nodeId": "acquisition", "agentId": acquisition["agentId"], "displayName": "Acquisition", "role": "source_acquisition", "status": "active"},
            {"nodeId": "extraction", "agentId": extraction["agentId"], "displayName": "Extraction", "role": "content_extraction", "status": "active"},
        ],
        "edges": [],
    }
    team = team_service.ensure_research_team_from_organization(organization)

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["data_discovery", "source_acquisition", "content_extraction"],
        },
    )

    role_to_agent_id = {item["agentRole"]: item["agentId"] for item in response["assignments"]}
    assert response["run"]["metadata"]["ownerAgentId"] == coordinator["agentId"]
    assert response["searchPlan"]["roleAssignmentInputs"][0]["agentId"] == discovery["agentId"]
    assert role_to_agent_id == {
        "data_discovery": discovery["agentId"],
        "source_acquisition": acquisition["agentId"],
        "content_extraction": extraction["agentId"],
    }


def test_start_source_collection_run_accepts_traceable_query_seed_contract(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "neural predictive coding",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 7,
            "agentRoles": ["data_discovery", "source_quality"],
            "agentIds": {"source_quality": "Source Quality Agent"},
        },
    )

    search_plan = response["searchPlan"]
    queries = search_plan["queries"]

    assert search_plan["querySeeds"] == ["predictive coding cortical hierarchy", "neural predictive coding"]
    assert search_plan["searchLanguages"] == ["en"]
    assert search_plan["sourceTypes"] == ["paper"]
    assert search_plan["maxResultsPerQuery"] == 7
    assert search_plan["queryCount"] == 2
    assert {item["assignedAgentRole"] for item in queries} == {"data_discovery", "source_quality"}
    assert all(item["status"] == "planned" for item in queries)
    assert all(item["execution"]["externalSearchTriggered"] is False for item in queries)
    assert response["assignments"][1]["agentId"] == "Source Quality Agent"
    assert response["assignments"][1]["scope"]["assignedQueries"][0]["assignedAgentRole"] == "source_quality"
    assert response["assignments"][1]["acceptance"]["resultWritebackContract"]["candidateImport"]["targetCandidateType"] == "source_manifest"
    assert response["assignments"][1]["acceptance"]["resultWritebackContract"]["officialGraphWrites"] is False


def test_seed_source_collection_agent_session_context_writes_and_dedupes_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    direct_session = session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )

    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )

    first = team_workflow_orchestration_service.seed_source_collection_agent_session_context(
        team["teamId"],
        run_response["run"]["runId"],
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
    )
    second = team_workflow_orchestration_service.seed_source_collection_agent_session_context(
        team["teamId"],
        run_response["run"]["runId"],
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
    )

    assert first["created"] is True
    assert first["sessionId"] == direct_session["id"]
    assert first["message"]["metadata"]["kind"] == "source_collection_agent_context"
    assert first["message"]["metadata"]["sourceCollectionContextKey"] == first["contextKey"]
    assert "脑启发路由" in first["message"]["content"]
    assert second["created"] is False
    assert second["alreadyPresent"] is True
    detail = session_service.get_session_detail(direct_session["id"])
    context_messages = [
        message for message in detail["messages"]
        if message.get("metadata", {}).get("kind") == "source_collection_agent_context"
    ]
    assert len(context_messages) == 1


def test_start_source_collection_stage_session_task_submits_direct_session_task(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    submitted: list[dict] = []

    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    direct_session = session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
            "returnTo": "/teams?team=research-team&researchView=knowledge_collection&collectionStage=collection",
            "returnLabel": "返回搜索资料",
        },
    )
    second = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
            "returnTo": "/teams?team=research-team&researchView=knowledge_collection&collectionStage=collection",
            "returnLabel": "返回搜索资料",
        },
    )
    explicit_once = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
            "idempotencyKey": "stage-task-click-explicit",
        },
    )
    explicit_duplicate = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
            "idempotencyKey": "stage-task-click-explicit",
        },
    )

    assert task["created"] is True
    assert task["alreadyPresent"] is False
    assert task["sessionId"] == direct_session["id"]
    assert task["chatRoute"].startswith(f"/chat?session={direct_session['id']}")
    assert task["turn"]["turnId"] == "turn-stage-task-1"
    assert task["task"]["status"] == "running"
    assert task["task"]["writebackContract"]["writesFormalKnowledge"] is False
    assert task["task"]["writebackContract"]["endpoint"].endswith(f"/stage-session-tasks/{task['taskId']}/writeback")
    assert submitted[0]["sessionId"] == direct_session["id"]
    assert "资料搜集阶段任务" in submitted[0]["content"]
    assert "会立即要求当前 Agent 在本会话执行" in submitted[0]["content"]
    assert "先用一句简短状态回应已接收任务" in submitted[0]["content"]
    assert "source_collection_context_tool" in submitted[0]["content"]
    assert "source_collection_stage_writeback_tool" in submitted[0]["content"]
    assert "不要使用 `web_fetch_tool` 读取 `file://`" in submitted[0]["content"]
    assert "不会自动启动 Agent 回答" not in submitted[0]["content"]
    assert submitted[0]["kwargs"]["message_source"] == "team_workflow_stage_task"
    assert submitted[0]["kwargs"]["lightweight_response"] is True
    assert submitted[0]["kwargs"]["include_started_turn_id"] is True
    metadata = submitted[0]["kwargs"]["message_metadata"]
    assert metadata["kind"] == "source_collection_stage_session_task"
    assert metadata["sourceCollectionStageTaskId"] == task["taskId"]
    assert metadata["writebackContract"]["taskId"] == task["taskId"]
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


def test_source_collection_stage_task_context_returns_bounded_records_for_extraction(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["content_extraction"],
            "agentIds": {"content_extraction": "extraction-agent"},
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
        "stageId": "candidate",
        "agentId": "extraction-agent",
        "agentRole": "content_extraction",
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
    assert context["stageId"] == "candidate"
    assert context["counts"]["recordCount"] == 2
    assert context["counts"]["returnedRecordCount"] == 1
    assert context["records"][0]["doi"] == "10.0000/predictive-coding"
    assert context["records"][0]["query"] == "brain-inspired routing"
    assert context["records"][0]["assignmentId"] == assignment_id
    assert context["usage"]["readTool"] == "source_collection_context_tool"
    assert context["usage"]["writebackTool"] == "source_collection_stage_writeback_tool"
    assert "file://" in context["usage"]["doNotUse"]


def test_source_collection_stage_task_records_high_roi_runtime_events(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    events = _capture_workflow_events(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
            "idempotencyKey": "stage-click",
        },
    )
    reused = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_response["run"]["runId"],
        {
            "stageId": "collection",
            "agentId": discovery["agentId"],
            "agentRole": "data_discovery",
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


def test_source_collection_stage_session_task_writeback_records_structured_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
            "turnId": "turn-stage-task",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
    )

    result = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "已完成第一轮资料搜索，建议进入资料提炼。",
            "result": {"recordCount": 3, "candidateCount": 2},
            "evidenceRefs": [{"kind": "run", "ref": run_id}],
            "nextActions": ["进入资料提炼"],
        },
    )

    assert result["task"]["status"] == "completed"
    assert result["task"]["result"]["recordCount"] == 3
    assert result["task"]["writesFormalKnowledge"] is False
    assert result["task"]["writesRag"] is False
    assert result["writeback"]["status"] == "completed"
    assert result["boundaries"]["writesFormalKnowledge"] is False
    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    latest_round = status_payload["latestRound"]
    stage_results = latest_round.get("sourceCollectionStageSessionTasks", [])
    assert any(item["taskId"] == task["taskId"] and item["status"] == "completed" for item in stage_results)


def test_source_collection_stage_session_task_writeback_materializes_search_leads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "搜集可追踪资料",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
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
    records = data_processing_service.list_records(run_id)
    assert records["summary"]["recordCount"] == 2
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 2
    assert {item["metadata"]["doi"] for item in candidates["candidates"]} == {"10.1038/4580", "10.1038/nrn2787"}

    second = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(team["teamId"], task["taskId"], payload)

    assert second["writeback"]["materializedSources"]["createdRecordCount"] == 0
    assert second["writeback"]["materializedSources"]["importedCandidateCount"] == 0
    assert second["writeback"]["materializedSources"]["skippedDuplicateCount"] == 2
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 2
    assert team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidateCount"] == 2


def test_research_stage_status_materializes_legacy_stage_task_writeback_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "预测编码",
            "goal": "补齐历史任务资料池",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
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
        members=[{"agentId": extraction["agentId"], "role": "content_extraction", "agentName": "资料提炼"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "提炼本轮候选资料",
            "agentRoles": ["content_extraction"],
            "agentIds": {"content_extraction": extraction["agentId"]},
            "querySeeds": ["brain inspired routing"],
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
            "turnId": "turn-stage-task-candidate",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "candidate", "agentId": extraction["agentId"], "agentRole": "content_extraction"},
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
    assert len(cards) == 5
    card_by_stage = {card["stageId"]: card for card in cards}
    candidate_card = card_by_stage["candidate"]
    assert candidate_card["status"] == "agent_done_artifact_pending"
    assert candidate_card["agentTaskStatus"] == "completed"
    assert candidate_card["artifactStatus"] == "empty"
    assert candidate_card["counts"]["artifact"] == 0
    assert candidate_card["latestTask"]["taskId"] == task["taskId"]
    assert candidate_card["latestTask"]["status"] == "completed"
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
    assert card_by_stage["candidate"]["status"] == "artifact_ready_no_latest_agent_task"
    assert card_by_stage["candidate"]["counts"]["artifact"] == 1
    assert card_by_stage["graph"]["status"] == "pending"
    assert card_by_stage["graph"]["counts"]["artifact"] == 0
    assert card_by_stage["memory"]["status"] == "pending"
    assert card_by_stage["memory"]["counts"]["artifact"] == 0


def test_research_stage_status_reconciles_completed_stage_task_turn_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料发现")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料发现")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "data_discovery", "agentName": "资料发现"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": discovery["agentId"]},
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
        {"stageId": "collection", "agentId": discovery["agentId"], "agentRole": "data_discovery"},
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
    assert reconciled["status"] == "completed"
    task_store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in task_store["tasks"] if item["taskId"] == task["taskId"])
    assert stored_task["status"] == "completed"
    assert stored_task["writeback"]["resultAuthority"] == "agent_turn_result_reconciliation"


def test_research_stage_status_reconciles_blocked_stage_task_turn_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    extraction = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=extraction["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": extraction["agentId"], "role": "content_extraction", "agentName": "资料提炼"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "脑启发路由",
            "goal": "搜集神经机制启发算法资料",
            "agentRoles": ["content_extraction"],
            "agentIds": {"content_extraction": extraction["agentId"]},
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
            "turnId": "turn-stage-task-blocked",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "candidate", "agentId": extraction["agentId"], "agentRole": "content_extraction"},
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
        members=[{"agentId": agent["agentId"], "role": "content_extraction", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "脑启发路由",
            "agentRoles": ["content_extraction"],
            "agentIds": {"content_extraction": agent["agentId"]},
            "querySeeds": ["brain-inspired routing"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    data_processing_service.add_record(
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
        {"stageId": "candidate", "agentId": agent["agentId"], "agentRole": "content_extraction"},
    )

    context_payload = json.loads(
        source_collection_context_tool(
            team_id=team["teamId"],
            task_id=task["taskId"],
            max_records=5,
        )
    )
    writeback_payload = json.loads(
        source_collection_stage_writeback_tool(
            team_id=team["teamId"],
            task_id=task["taskId"],
            status="completed",
            summary="工具回写完成。",
            result_json='{"extractedRecordCount": 1}',
            evidence_refs_json=f'[{{"type":"run","id":"{run_response["run"]["runId"]}","label":"source run"}}]',
            next_actions_json='["进入资料审查"]',
            recorded_by_agent=agent["agentId"],
        )
    )

    assert context_payload["status"] == "ok"
    assert context_payload["records"][0]["doi"] == "10.0000/tool-context"
    assert writeback_payload["writeback"]["status"] == "completed"
    assert writeback_payload["task"]["result"]["extractedRecordCount"] == 1
    tool_event_codes = [args[2] for args, _kwargs in tool_events]
    assert "tool.source_collection_context.completed" in tool_event_codes
    assert "tool.source_collection_stage_writeback.completed" in tool_event_codes
    writeback_event = next(kwargs for args, kwargs in tool_events if args[2] == "tool.source_collection_stage_writeback.completed")
    assert writeback_event["fields"]["taskId"] == task["taskId"]
    assert writeback_event["fields"]["status"] == "completed"


def test_source_collection_context_reports_actual_candidate_page(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料审查")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料审查")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_quality", "agentName": "资料审查"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "预测编码皮层层级",
            "agentRoles": ["source_quality"],
            "agentIds": {"source_quality": agent["agentId"]},
            "querySeeds": ["predictive coding cortical hierarchy"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
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
        {"stageId": "screening", "agentId": agent["agentId"], "agentRole": "source_quality"},
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


def test_source_quality_stage_writeback_materializes_candidate_decisions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料审查")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料审查")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_quality", "agentName": "资料审查"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经算法资料质检",
            "agentRoles": ["source_quality"],
            "agentIds": {"source_quality": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
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
        {"stageId": "screening", "agentId": agent["agentId"], "agentRole": "source_quality"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "needs_review",
            "summary": "审查 3/3 条候选：通过 1，拒绝 1，退回补充 1。",
            "result": {
                "reviewSummary": {"total": 3, "assessed": 3, "pass": 1, "rejected": 1, "needsMoreInfo": 1},
                "candidateDecisions": [
                    {
                        "candidateId": approved["candidateId"],
                        "decision": "pass",
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
    screening_projection = team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)["cards"][2]
    assert screening_projection["status"] == "closed_loop"
    assert screening_projection["counts"]["artifact"] == 3
    assert screening_projection["counts"]["pending"] == 0


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
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": "Data Discovery Agent"},
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
    assert execution["executedQueryCount"] == 1
    assert execution["recordCount"] == 2
    assert execution["createdUniqueRecordCount"] == 2
    assert execution["importedCount"] == 2
    assert execution["skippedDuplicateCount"] == 0
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


def test_execute_source_collection_search_publishes_runtime_work_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
            "agentRoles": ["data_discovery"],
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
    assert search_event["child_log_path"].startswith("artifacts/source-collection-")
    assert search_event["child_log_payload"]["summary"]["executedQueryCount"] == 1
    assert search_event["child_log_payload"]["queryEvents"]
    assert search_event["child_log_payload"]["queryEvents"][0]["assignmentId"]
    assert search_event["child_log_payload"]["queryEvents"][0]["queryId"]


def test_execute_source_collection_search_does_not_mark_downstream_assignments_as_running_search(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
            "agentRoles": ["data_discovery", "content_extraction", "source_quality"],
        },
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_response["run"]["runId"],
        {"maxQueries": 1, "maxResultsPerQuery": 1},
    )
    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()

    assert execution["executedQueryCount"] == 1
    assert execution["sourceCollectionSummary"]["openAssignmentCount"] == 2
    assert execution["sourceCollectionSummary"]["searchOpenAssignmentCount"] == 0
    assert execution["sourceCollectionSummary"]["downstreamOpenAssignmentCount"] == 2
    assert execution["runStatus"]["summary"]["searchOpenAssignmentCount"] == 0
    assert execution["runStatus"]["summary"]["downstreamOpenAssignmentCount"] == 2
    assert summary["active"] is None
    assert summary["latest"]["status"] == "completed"
    assert summary["latest"]["currentPhase"] == "completed"
    assert summary["latest"]["openAssignmentCount"] == 2
    assert summary["latest"]["searchOpenAssignmentCount"] == 0
    assert summary["latest"]["downstreamOpenAssignmentCount"] == 2


def test_execute_source_collection_search_skips_existing_query_without_force(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
            "agentRoles": ["data_discovery"],
        },
    )
    first = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_response["run"]["runId"], {"maxQueries": 1})
    second = team_workflow_orchestration_service.execute_source_collection_search(team["teamId"], run_response["run"]["runId"], {"maxQueries": 1})

    assert first["executedQueryCount"] == 1
    assert second["executedQueryCount"] == 0
    assert second["skippedQueryCount"] == 0
    assert second["skippedDuplicateCount"] == 0
    assert second["status"] == "no_open_assignment"
    assert calls == [run_response["searchPlan"]["queries"][0]["queryId"]]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2


def test_execute_source_collection_search_records_output_per_query(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

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
            "agentRoles": ["data_discovery"],
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
            "agentRoles": ["data_discovery"],
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
    assert second["skippedDuplicateCount"] == 2
    assert second["remainingQueryCount"] == 0
    assert second["hasMore"] is False
    assert second["duplicateSourceKeys"] == ["doi:10.0000/predictive-coding", "doi:10.0000/cortical-dataset"]
    assert {event["eventType"] for event in second["executionEvents"]} >= {"search.duplicate_skipped"}
    assignments = data_processing_service.list_collection_assignments(run_response["run"]["runId"])["assignments"]
    assert assignments[0]["status"] == "completed"
    summary = team_workflow_orchestration_service.load_source_collection_work_run_summary()
    assert summary["latest"]["status"] == "completed"
    assert summary["latest"]["currentPhase"] == "completed"
    assert summary["latest"]["searchOpenAssignmentCount"] == 0
    assert "跳过 2 条重复资料" in summary["latest"]["summary"]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    assert candidates["candidateCount"] == 2


def test_execute_source_collection_search_dedupes_metadata_doi_and_sorted_url_query(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    responses = [
        {
            "provider": "crossref_rest_api",
            "searchUrl": "https://api.example.test/search?q=first",
            "results": [
                {
                    "title": "Metadata DOI source identity",
                    "sourceRef": "metadata-doi-source",
                    "rawLocation": "metadata-doi-location",
                    "summary": "DOI only appears in metadata.",
                    "sourceType": "paper",
                    "metadata": {"doi": "10.0000/metadata-only", "containerTitle": "Journal", "issued": "2025"},
                },
                {
                    "title": "URL query order source identity",
                    "sourceRef": "https://example.test/source?b=2&a=1&utm_source=tracker",
                    "rawLocation": "https://example.test/source?a=1&b=2",
                    "summary": "Equivalent URLs should dedupe.",
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
                    "title": "Metadata DOI source identity duplicate",
                    "sourceRef": "different-source-ref",
                    "rawLocation": "different-location",
                    "summary": "Same DOI only appears in metadata.",
                    "sourceType": "paper",
                    "metadata": {"doi": "10.0000/metadata-only", "containerTitle": "Journal", "issued": "2025"},
                },
                {
                    "title": "URL query order source identity duplicate",
                    "sourceRef": "https://example.test/source?a=1&b=2",
                    "rawLocation": "https://example.test/source?b=2&a=1",
                    "summary": "Equivalent URL with different query order.",
                    "sourceType": "paper",
                    "metadata": {"containerTitle": "Journal", "issued": "2025"},
                },
            ],
        },
    ]

    def fake_search(query, *, max_results, provider):
        return responses.pop(0)

    monkeypatch.setattr(team_workflow_orchestration_service, "_execute_source_collection_query", fake_search)
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "source identity",
            "querySeeds": ["first", "second"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["data_discovery"],
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
    assert second["skippedDuplicateCount"] == 2
    assert second["duplicateSourceKeys"] == ["doi:10.0000/metadata-only", "url:https://example.test/source?a=1&b=2"]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2


def test_start_research_stage_round_creates_knowledge_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    search_calls = _stub_source_collection_search_background(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")

    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "goal": "Collect traceable neuroscience sources.",
            "querySeeds": ["cortical predictive coding"],
            "agentRoles": ["data_discovery", "source_quality"],
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
                "provider": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
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
            "agentRoles": ["data_discovery"],
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
            "agentRoles": ["data_discovery"],
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
    _stub_source_collection_search_background(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team = team_service.create_team(name="ai科学研究团队", members=[{"agentId": agent["agentId"], "role": "research_coordination"}])

    response = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "agentRoles": ["data_discovery"],
            "agentIds": {"data_discovery": agent["agentId"]},
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


def test_start_research_stage_round_keeps_experiment_plan_when_coordination_busy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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


def test_experiment_plan_draft_uses_ready_algorithm_hypotheses_and_blocks_full_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )

    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert draft["plan"]["status"] == "draft"
    assert draft["plan"]["experimentPlan"]["dataset"] == "synthetic task-switch benchmark"
    assert draft["plan"]["experimentPlan"]["metric"] == "validation accuracy and routing entropy"
    assert draft["plan"]["baselineSelection"]["activeBaselineReady"] is False
    assert draft["plan"]["readiness"]["readyForPlanReview"] is True
    assert draft["plan"]["readiness"]["readyForSmoke"] is False
    assert "active_baseline_record" in draft["plan"]["readiness"]["blockers"]
    assert draft["stageRound"]["experimentPlanRef"]["planId"] == draft["plan"]["planId"]
    assert draft["stageRound"]["planningContract"]["autoExecution"] is False
    assert status["summary"]["planCount"] == 1
    assert status["summary"]["readyHypothesisCandidateCount"] == 1
    assert any(gap["code"] == "active_baseline_not_registered" for gap in status["gaps"])
    assert status["boundaries"]["autoExecution"] is False
    assert status["boundaries"]["createsExperimentAttempt"] is False


def test_experiment_baseline_artifact_registration_unlocks_smoke_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )

    registered = team_workflow_orchestration_service.register_experiment_baseline_artifact(
        team["teamId"],
        draft["plan"]["planId"],
        {
            "artifactPath": "workspace/experiments/baselines/standard-moe-router.json",
            "reproductionCommand": "python experiments/run_baseline.py --config configs/standard_moe_router.yaml",
            "evaluationCommand": "python experiments/evaluate.py --run standard-moe-router",
            "metricValue": "0.71 validation accuracy",
            "registeredByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["baselineArtifact"]["artifactPath"].endswith("standard-moe-router.json")
    assert registered["plan"]["status"] == "baseline_ready"
    assert registered["plan"]["baselineSelection"]["activeBaselineReady"] is True
    assert registered["plan"]["baselineSelection"]["activeBaselineArtifactId"] == registered["baselineArtifact"]["artifactId"]
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is False
    assert "active_baseline_record" not in registered["plan"]["readiness"]["blockers"]
    assert "smoke_result" in registered["plan"]["readiness"]["blockers"]
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForSmoke"] is True
    assert status["status"] == "ready_for_smoke"
    assert status["readiness"]["readyForSmoke"] is True
    assert not any(gap["code"] == "active_baseline_not_registered" for gap in status["gaps"])
    assert any(gap["code"] == "smoke_result_not_recorded" for gap in status["gaps"])
    assert status["boundaries"]["createsExperimentAttempt"] is False


def test_experiment_baseline_artifact_requires_artifact_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "dataset": "synthetic task-switch benchmark",
            "metric": "validation accuracy",
            "baseline": "standard MoE router",
            "smokePlan": "train 200 mini-batches",
        },
    )

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Baseline artifact path is required"):
        team_workflow_orchestration_service.register_experiment_baseline_artifact(
            team["teamId"],
            draft["plan"]["planId"],
            {"reproductionCommand": "python experiments/run_baseline.py"},
        )


def test_experiment_smoke_result_registration_unlocks_full_run_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    registered = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "passed",
            "metricValue": "0.75 validation accuracy",
            "baselineMetricValue": "0.71 validation accuracy",
            "delta": "+0.04 accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing.json",
            "logRef": "logs/experiments/context-gated-routing-smoke.log",
            "evaluationCommand": "python experiments/evaluate.py --run context-gated-routing-smoke",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["smokeResult"]["status"] == "passed"
    assert registered["smokeResult"]["gateDecision"] == "promote_to_full_run"
    assert registered["plan"]["status"] == "smoke_passed"
    assert registered["plan"]["activeSmokeResultId"] == registered["smokeResult"]["smokeResultId"]
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is True
    assert registered["plan"]["readiness"]["blockers"] == []
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForFullRun"] is True
    assert status["status"] == "ready_for_full_run"
    assert status["readiness"]["readyForFullRun"] is True
    assert not any(gap["code"] == "smoke_result_not_recorded" for gap in status["gaps"])
    assert status["boundaries"]["createsExperimentAttempt"] is False


def test_experiment_smoke_result_failed_status_keeps_full_run_blocked(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    registered = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "failed",
            "metricValue": "0.65 validation accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing-failed.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["smokeResult"]["gateDecision"] == "reject_or_repair"
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is False
    assert registered["plan"]["readiness"]["blockers"] == ["smoke_result"]
    assert status["status"] == "ready_for_smoke"
    assert any(gap["code"] == "smoke_result_not_passed" for gap in status["gaps"])


def test_experiment_smoke_result_requires_active_baseline_artifact(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "dataset": "synthetic task-switch benchmark",
            "metric": "validation accuracy",
            "baseline": "standard MoE router",
            "smokePlan": "train 200 mini-batches",
        },
    )

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Register an active baseline artifact"):
        team_workflow_orchestration_service.register_experiment_smoke_result(
            team["teamId"],
            draft["plan"]["planId"],
            {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
        )


def test_experiment_full_run_result_registration_tracks_ledger_without_official_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "passed",
            "metricValue": "0.75 validation accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )

    registered = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {
            "status": "passed",
            "metricName": "validation accuracy",
            "metricValue": "0.79 validation accuracy",
            "baselineMetricValue": "0.71 validation accuracy",
            "smokeMetricValue": "0.75 validation accuracy",
            "delta": "+0.08 accuracy",
            "resultPath": "workspace/experiments/full_run/context-gated-routing.json",
            "logRef": "logs/experiments/context-gated-routing-full-run.log",
            "configPath": "workspace/experiments/full_run/context-gated-routing-config.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["fullRunResult"]["status"] == "passed"
    assert registered["fullRunResult"]["gateDecision"] == "ready_for_knowledge_review"
    assert registered["fullRunResult"]["smokeResultId"] == smoke["smokeResult"]["smokeResultId"]
    assert registered["plan"]["status"] == "full_run_passed"
    assert registered["plan"]["activeFullRunResultId"] == registered["fullRunResult"]["fullRunResultId"]
    assert registered["plan"]["readiness"]["readyForFullRun"] is True
    assert registered["plan"]["readiness"]["readyForKnowledgeIngestion"] is True
    assert registered["plan"]["readiness"]["knowledgeBlockers"] == []
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForKnowledgeIngestion"] is True
    assert status["status"] == "ready_for_knowledge_ingestion"
    assert status["summary"]["activeFullRunResultId"] == registered["fullRunResult"]["fullRunResultId"]
    assert status["boundaries"]["writesFormalKnowledge"] is False
    assert status["boundaries"]["writesRag"] is False
    assert status["boundaries"]["writesOfficialGraph"] is False


def test_experiment_full_run_result_requires_passing_smoke_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="passing smoke result"):
        team_workflow_orchestration_service.register_experiment_full_run_result(
            team["teamId"],
            prepared["baseline"]["plan"]["planId"],
            {
                "status": "passed",
                "metricValue": "0.79 validation accuracy",
                "resultPath": "workspace/experiments/full_run/context-gated-routing.json",
            },
        )


def test_experiment_result_knowledge_ingestion_request_notifies_steward_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    requester = agent_directory_service.create_agent_instance(display_name="Experiment Planning Agent")
    deliveries = []

    def fake_wake(message):
        deliveries.append(message)
        return {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-experiment-ingest",
            "reason": "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
    )
    full_run = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {"status": "passed", "metricValue": "0.79", "resultPath": "workspace/experiments/full_run/result.json"},
    )

    requested = team_workflow_orchestration_service.request_experiment_result_knowledge_ingestion(
        team["teamId"],
        full_run["plan"]["planId"],
        {
            "requestedByAgent": requester["agentId"],
            "knowledgeBaseId": "research-team-experiment-kb",
            "targetDomain": "挑战杯实验结果",
        },
    )
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, status="pending")

    assert requested["status"]["status"] == "knowledge_steward_notified"
    assert requested["plan"]["status"] == "knowledge_steward_notified"
    assert requested["experimentResultPack"]["fullRunResultId"] == full_run["fullRunResult"]["fullRunResultId"]
    assert requested["experimentResultPack"]["officialBoundary"]["currentWritesOfficialKnowledge"] is False
    assert requested["experimentResultPack"]["officialBoundary"]["ragUsesCuratedSummaryOnly"] is True
    assert requested["knowledgeStewardActivation"]["status"] == "agent_wake_started"
    assert requested["knowledgeStewardActivation"]["targetAgentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert requested["knowledgeStewardActivation"]["delivery"]["turnId"] == "turn-experiment-ingest"
    assert requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert requested["knowledgeStewardActivation"]["kernel"]["outcomeStatus"] == "succeeded"
    assert deliveries and deliveries[0]["kind"] == "challenge_cup_experiment_result_ingestion_request"
    assert deliveries[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert deliveries[0]["metadata"]["kernelTaskId"] == requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["messageId"] == requested["knowledgeStewardActivation"]["messageId"]
    assert inbox_messages[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert inbox_messages[0]["metadata"]["kernelTaskId"] == requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["metadata"]["experimentResultPackId"] == requested["experimentResultPack"]["packId"]
    assert inbox_messages[0]["metadata"]["fullRunResultId"] == full_run["fullRunResult"]["fullRunResultId"]


def test_experiment_plan_requires_experiment_stage_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Start an experiment planning stage round"):
        team_workflow_orchestration_service.create_experiment_plan(team["teamId"], {})


def test_transfer_decision_rejects_non_owner_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(
        team["teamId"],
        owner_agent_id="Research Coordination Agent",
    )
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {"title": "Source", "createdByAgent": "Knowledge Collection Agent"},
    )["candidate"]
    transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": candidate["candidateId"],
            "fromNode": "knowledge_collection",
            "toNode": "source_screening",
            "requestedByAgent": "Knowledge Collection Agent",
        },
    )["transfer"]

    try:
        team_workflow_orchestration_service.decide_transfer_request(
            team["teamId"],
            transfer["transferId"],
            {"decision": "approved", "decidedByAgent": "Knowledge Collection Agent"},
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "Only the workflow owner agent" in str(exc)
    else:
        raise AssertionError("non-owner transfer decision should fail")


def test_transfer_returned_moves_candidate_to_rework_node(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    workflow = team_workflow_orchestration_service.ensure_team_workflow_orchestration(
        team["teamId"],
        owner_agent_id="Research Coordination Agent",
    )
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Hypothesis note needing evidence",
            "sourceKind": "paper",
            "createdByAgent": "Evidence Review Agent",
        },
    )["candidate"]
    transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": candidate["candidateId"],
            "fromNode": "research_review",
            "toNode": "algorithm_hypothesis",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "Experiment plan is not testable enough for steward handoff.",
            "metadata": {
                "requiredChanges": ["Add dataset, metric, baseline, and smokePlan."],
                "reasonCode": "experiment_plan_gap",
            },
        },
    )["transfer"]

    response = team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        transfer["transferId"],
        {
            "decision": "returned",
            "decidedByAgent": workflow["ownerAgentId"],
            "targetState": "hypothesis_needs_revision",
            "decisionNote": "Return to the hypothesis agent for the smallest upstream fix.",
        },
    )

    assert response["transfer"]["status"] == "returned"
    assert response["transfer"]["targetState"] == "hypothesis_needs_revision"
    assert response["candidate"]["currentWorkflowNode"] == "algorithm_hypothesis"
    assert response["candidate"]["currentState"] == "hypothesis_needs_revision"
    assert response["candidate"]["qualityStatus"] == "needs_revision"
    assert response["candidate"]["transitionHistory"][-1]["toNode"] == "algorithm_hypothesis"
    assert response["candidate"]["transitionHistory"][-1]["metadata"]["requiredChanges"] == [
        "Add dataset, metric, baseline, and smokePlan."
    ]
    assert "pendingTransferId" not in response["candidate"]


def test_transfer_rejected_archives_candidate_and_excludes_graph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    workflow = team_workflow_orchestration_service.ensure_team_workflow_orchestration(
        team["teamId"],
        owner_agent_id="Research Coordination Agent",
    )
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Unsupported dopamine routing analogy",
            "sourceKind": "paper",
            "sourceUrl": "https://example.test/rejected",
            "createdByAgent": "Evidence Review Agent",
        },
    )["candidate"]
    transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": candidate["candidateId"],
            "fromNode": "research_review",
            "toNode": "rejection_archive",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "The analogy is unsupported by the cited source.",
            "evidenceRefs": [{"type": "review_record", "id": "review-unsupported", "label": "Unsupported analogy review"}],
        },
    )["transfer"]

    rejected = team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        transfer["transferId"],
        {
            "decision": "rejected",
            "decidedByAgent": workflow["ownerAgentId"],
            "decisionNote": "Archive until a reopen reason is provided by the review gate.",
        },
    )
    graph = team_workflow_orchestration_service.build_candidate_graph(team["teamId"], {})

    assert rejected["transfer"]["status"] == "rejected"
    assert rejected["candidate"]["currentWorkflowNode"] == "rejection_archive"
    assert rejected["candidate"]["currentState"] == "rejected"
    assert rejected["candidate"]["qualityStatus"] == "rejected"
    assert rejected["candidate"]["metadata"]["rejectionArchive"]["status"] == "archived"
    assert rejected["candidate"]["metadata"]["rejectionArchive"]["reopenRequiresTransfer"] is True
    assert graph["graph"]["summary"]["archivedCandidateCount"] == 1
    assert candidate["candidateId"] not in {node["candidateId"] for node in graph["graph"]["nodes"]}


def test_coordination_status_groups_pending_transfer_rework_and_blocked_candidates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    workflow = team_workflow_orchestration_service.ensure_team_workflow_orchestration(
        team["teamId"],
        owner_agent_id="Research Coordination Agent",
    )
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Candidate source",
            "sourceUrl": "https://example.test/source",
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": source["candidateId"],
            "fromNode": "knowledge_collection",
            "toNode": "source_screening",
            "requestedByAgent": "Source Intake Agent",
            "reason": "Ready for source screening.",
        },
    )
    rework = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Incomplete hypothesis",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Possible algorithm idea", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Dynamic routing may help.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better adaptation",
                "expectedComputeCost": "small overhead",
                "experimentPlan": {"dataset": "synthetic task-switch benchmark"},
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.38,
                "nextAction": "fix_experiment_plan",
                "requiresReview": True,
            },
        },
    )["candidate"]

    status = team_workflow_orchestration_service.get_team_workflow_coordination_status(team["teamId"])

    assert status["status"] == "blocked"
    assert status["ownerAgentId"] == workflow["ownerAgentId"]
    assert status["coordinationPolicy"]["requiresUserConfirmation"] is False
    assert status["coordinationPolicy"]["autoTransferEnabled"] is False
    assert status["summary"]["pendingTransferCount"] == 1
    assert status["summary"]["reworkCandidateCount"] == 1
    assert status["summary"]["blockedCandidateCount"] == 1
    assert status["summary"]["communicationBriefCount"] >= 2
    assert status["communication"]["autoSendEnabled"] is False
    assert status["communication"]["readOnly"] is True
    assert status["queues"]["pendingTransfers"][0]["candidateId"] == source["candidateId"]
    assert status["queues"]["pendingTransfers"][0]["communicationBrief"]["targetAgentRole"] == "Research Coordination Agent"
    assert status["queues"]["pendingTransfers"][0]["communicationBrief"]["autoSendEnabled"] is False
    assert status["queues"]["needsRework"][0]["candidateId"] == rework["candidateId"]
    assert status["queues"]["needsRework"][0]["communicationBrief"]["targetAgentRole"] == "Algorithm Hypothesis Agent"
    assert status["queues"]["needsRework"][0]["communicationBrief"]["channel"] == "project_agent_bus"
    assert status["queues"]["blocked"][0]["candidateId"] == rework["candidateId"]
    assert {item["code"] for item in status["actionItems"]} == {
        "transfer_decision_pending",
        "candidate_rework_pending",
        "coordination_blocked_candidates",
    }


def test_local_research_model_task_and_output_records_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    task_response = team_workflow_orchestration_service.build_local_research_model_task(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
            "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
            "excerpt": "A short source excerpt.",
            "createdByAgent": "Paper Note Extraction Agent",
        },
    )
    output_response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "title": "Paper note draft",
            "createdByAgent": "Paper Note Extraction Agent",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Observed effect", "sourceRef": "paper-1"}],
                "keyFindings": [
                    {
                        "finding": "Observed effect",
                        "sourceRef": "paper-1",
                        "page": "3",
                        "citation": "Paper 1, p.3",
                    }
                ],
                "methods": ["controlled experiment"],
                "limitations": ["small sample"],
                "citations": [{"sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.72,
                "nextAction": "send_to_mechanism_extraction",
                "requiresReview": True,
            },
        },
    )

    assert task_response["task"]["model"]["modelId"] == "houmo_qwen35_9b_agent"
    assert task_response["task"]["outputContract"]["format"] == "json_object"
    assert "weak_evidence" in " ".join(task_response["task"]["outputContract"]["hardBoundaries"])
    assert output_response["validation"]["valid"] is True
    assert output_response["candidate"]["candidateType"] == "paper_note"
    assert output_response["candidate"]["currentState"] == "paper_note_draft"
    assert output_response["workflow"]["candidateStore"]["candidateCount"] == 1


def test_candidate_store_validates_pdf_source_manifest(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Local PDF",
            "sourcePath": "C:/papers/neuro.pdf",
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    )
    report = team_workflow_orchestration_service.validate_candidate_store(team["teamId"])

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "source_needs_confirmation"
    assert response["candidate"]["qualityStatus"] == "source_manifest_invalid"
    assert {issue["code"] for issue in response["validation"]["issues"]} >= {"missing_sha256", "analysis_not_allowed"}
    assert report["summary"]["candidateCount"] == 1
    assert report["summary"]["invalidCandidateCount"] == 1
    assert report["summary"]["errorCount"] >= 2


def test_source_extraction_updates_pdf_manifest_with_page_anchors(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source_path = tmp_path / "sources" / "neuro.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"%PDF-1.4\nfake local pdf bytes\n")

    def fake_extract(path, *, page_scope, max_pages, max_chars_per_page):
        assert path == source_path
        assert page_scope == "1-2"
        assert max_pages == 2
        assert max_chars_per_page == 500
        return [
            {"type": "pdf_page", "id": "neuro-p1", "label": "p. 1", "page": 1, "text": "Neural evidence on page one."},
            {"type": "pdf_page", "id": "neuro-p2", "label": "p. 2", "page": 2, "text": "Mechanism evidence on page two."},
        ]

    monkeypatch.setattr(team_workflow_orchestration_service, "_extract_pdf_page_anchors", fake_extract)
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Local PDF",
            "sourcePath": str(source_path),
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]

    response = team_workflow_orchestration_service.extract_candidate_source_pages(
        team["teamId"],
        candidate["candidateId"],
        {
            "createdByAgent": "Source Extraction Agent",
            "allowedForAnalysis": True,
            "pageScope": "1-2",
            "maxPages": 2,
            "maxCharsPerPage": 500,
        },
    )

    extraction = response["sourceExtraction"]
    assert response["validation"]["valid"] is True
    assert response["candidate"]["currentState"] == "source_registered"
    assert response["candidate"]["qualityStatus"] == "source_manifest_ready"
    assert response["candidate"]["sha256"]
    assert response["candidate"]["pageScope"] == "1-2"
    assert extraction["status"] == "extracted"
    assert len(extraction["pageAnchors"]) == 2
    assert "[p. 1]" in extraction["excerpt"]
    assert response["workflow"]["candidateStore"]["candidateCount"] == 1


def test_assess_source_quality_batch_processes_pending_sources_by_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    approved_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for network learning and attention mechanisms.",
            "tags": ["neuro", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]
    revision_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Unlocated source",
            "sourceKind": "paper",
            "summary": "Potentially relevant but missing a source location.",
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]

    response = team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {"assessedByAgent": "Source Quality Agent"},
    )
    status_payload = team_workflow_orchestration_service.get_source_quality_status(team["teamId"])
    decisions = {item["candidateId"]: item["decision"] for item in response["assessments"]}

    assert response["status"] == "completed"
    assert response["executionMode"] == "source_quality_agent_batch"
    assert response["assessedByAgent"] == "Source Quality Agent"
    assert response["summary"]["assessedCandidateCount"] == 2
    assert response["summary"]["approvedCandidateCount"] == 1
    assert response["summary"]["needsRevisionCandidateCount"] == 1
    assert decisions[approved_source["candidateId"]] == "approved"
    assert decisions[revision_source["candidateId"]] == "needs_revision"
    assert response["officialBoundary"]["writesFormalKnowledge"] is False
    assert response["officialBoundary"]["writesRag"] is False
    assert response["officialBoundary"]["writesOfficialGraph"] is False
    assert status_payload["summary"]["unassessedSourceCandidateCount"] == 0
    assert status_payload["summary"]["approvedSourceCandidateCount"] == 1
    assert status_payload["summary"]["needsRevisionSourceCandidateCount"] == 1


def test_assess_source_quality_batch_reports_no_pending_candidates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding neural paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural network predictive coding.",
            "tags": ["neuro", "network"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]

    first = team_workflow_orchestration_service.assess_source_quality_batch(team["teamId"], {})
    second = team_workflow_orchestration_service.assess_source_quality_batch(team["teamId"], {})

    assert first["summary"]["assessedCandidateCount"] == 1
    assert first["assessments"][0]["candidateId"] == candidate["candidateId"]
    assert second["status"] == "no_pending_candidates"
    assert second["summary"]["assessedCandidateCount"] == 0
    assert second["summary"]["skippedCandidateCount"] == 1
    batch_events = _workflow_scene_events_by_code(scene_events, "source_quality.batch_assessed")
    assert batch_events
    assert batch_events[-1]["child_log_payload"]["kind"] == "source_quality_batch_assessment"
    assert batch_events[-1]["child_log_payload"]["summary"]["skippedCandidateCount"] == 1
    assert batch_events[-1]["child_log_payload"]["skippedCandidates"][0]["reason"] == "already_assessed"


def test_assess_source_quality_batch_force_rescreens_assessed_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding neural paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural network predictive coding.",
            "tags": ["neuro", "network"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]

    first = team_workflow_orchestration_service.assess_source_quality_batch(team["teamId"], {})
    second = team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {
            "assessedByAgent": "Source Quality Review Agent",
            "force": True,
            "notes": "Agent re-screen requested by user.",
        },
    )

    assert first["summary"]["assessedCandidateCount"] == 1
    assert second["status"] == "completed"
    assert second["assessedByAgent"] == "Source Quality Review Agent"
    assert second["summary"]["assessedCandidateCount"] == 1
    assert second["summary"]["skippedCandidateCount"] == 0
    assert second["assessments"][0]["candidateId"] == candidate["candidateId"]
    assert second["sourceQualityStatus"]["summary"]["assessedSourceCandidateCount"] == 1
    assert second["officialBoundary"]["writesFormalKnowledge"] is False
    assert second["officialBoundary"]["writesRag"] is False
    assert second["officialBoundary"]["writesOfficialGraph"] is False


def test_source_extraction_failure_keeps_manifest_needing_confirmation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    missing_path = tmp_path / "missing.pdf"
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Missing PDF",
            "sourcePath": str(missing_path),
            "sourceKind": "pdf",
            "allowedForAnalysis": True,
            "sha256": "a" * 64,
            "pageScope": "1",
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]

    response = team_workflow_orchestration_service.extract_candidate_source_pages(
        team["teamId"],
        candidate["candidateId"],
        {"createdByAgent": "Source Extraction Agent"},
    )

    assert response["sourceExtraction"]["status"] == "failed"
    assert response["sourceExtraction"]["errorCode"] == "missing_file"
    assert response["candidate"]["currentState"] == "source_needs_confirmation"
    assert response["candidate"]["qualityStatus"] == "source_manifest_invalid"
    assert {issue["code"] for issue in response["validation"]["issues"]} >= {"source_extraction_failed"}


def test_paper_note_autodraft_uses_source_extraction_excerpt_and_anchors(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source_path = tmp_path / "sources" / "neuro.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"%PDF-1.4\nfake local pdf bytes\n")

    def fake_extract(path, *, page_scope, max_pages, max_chars_per_page):
        return [
            {"type": "pdf_page", "id": "neuro-p1", "label": "p. 1", "page": 1, "text": "Neuromodulation evidence."},
            {"type": "pdf_page", "id": "neuro-p2", "label": "p. 2", "page": 2, "text": "Adaptive control finding."},
        ]

    monkeypatch.setattr(team_workflow_orchestration_service, "_extract_pdf_page_anchors", fake_extract)
    _FakeLocalResearchClient.response = _FakeLocalResearchMessage(
        """
        {
          "candidateType": "paper_note",
          "sourceRefs": [{"type": "pdf", "id": "source-1", "label": "Local PDF"}],
          "evidenceRefs": [{"type": "pdf_page", "id": "neuro-p1", "label": "Local PDF p. 1"}],
          "claims": [{"claim": "Neuromodulation supports adaptive control.", "sourceRef": "source-1"}],
          "keyFindings": [{"finding": "Neuromodulation supports adaptive control.", "sourceRef": "source-1", "page": "1", "citation": "Local PDF, p.1"}],
          "methods": ["paper excerpt synthesis"],
          "limitations": ["autodraft requires review"],
          "citations": [{"sourceRef": "source-1", "page": "1", "citation": "Local PDF, p.1"}],
          "uncertainty": [],
          "riskFlags": [],
          "confidence": 0.7,
          "nextAction": "send_to_mechanism_extraction",
          "requiresReview": true
        }
        """
    )
    _FakeLocalResearchClient.captured_messages = []
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Local PDF",
            "sourcePath": str(source_path),
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.extract_candidate_source_pages(
        team["teamId"],
        candidate["candidateId"],
        {"allowedForAnalysis": True, "pageScope": "1-2"},
    )

    response = team_workflow_orchestration_service.draft_paper_note_from_source_candidate(
        team["teamId"],
        candidate["candidateId"],
        {"createdByAgent": "Paper Note Extraction Agent"},
        llm_client_factory=_FakeLocalResearchClient,
    )

    assert response["validation"]["valid"] is True
    assert response["candidate"]["candidateType"] == "paper_note"
    assert response["candidate"]["currentState"] == "paper_note_draft"
    assert response["sourceCandidate"]["metadata"]["paperNoteDrafts"][0]["candidateId"] == response["candidate"]["candidateId"]
    captured_payload = _FakeLocalResearchClient.captured_messages[-1]["messages"][1]["content"]
    assert "Neuromodulation evidence" in captured_payload
    assert "neuro-p1" in captured_payload
    assert "source_manifest" in captured_payload
    assert response["workflow"]["candidateStore"]["candidateCount"] == 2


def test_paper_note_autodraft_requires_completed_source_extraction(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Unextracted PDF",
            "sourcePath": str(tmp_path / "missing.pdf"),
            "sourceKind": "pdf",
            "allowedForAnalysis": True,
            "sha256": "a" * 64,
            "pageScope": "1",
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]

    try:
        team_workflow_orchestration_service.draft_paper_note_from_source_candidate(
            team["teamId"],
            candidate["candidateId"],
            {},
            llm_client_factory=_FakeLocalResearchClient,
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "Source extraction must be completed" in str(exc)
    else:
        raise AssertionError("paper note autodraft should require completed source extraction")


def test_candidate_store_lists_candidates_with_filters(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Valid PDF",
            "sourcePath": "C:/papers/neuro.pdf",
            "sourceKind": "pdf",
            "sha256": "a" * 64,
            "allowedForAnalysis": True,
            "pageScope": "1-12",
            "createdByAgent": "Source Intake Agent",
        },
    )
    team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Observed effect"}],
                "keyFindings": [{"finding": "Observed effect", "sourceRef": "paper-1", "page": "3"}],
                "methods": ["controlled experiment"],
                "limitations": ["small sample"],
                "citations": [{"sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.7,
                "nextAction": "send_to_mechanism_extraction",
                "requiresReview": True,
            },
        },
    )

    source_list = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")
    paper_notes = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="paper_note")

    assert source_list["candidateCount"] == 1
    assert source_list["candidates"][0]["candidateType"] == "source_manifest"
    assert source_list["validationSummary"]["candidateCount"] == 2
    assert paper_notes["candidateCount"] == 1
    assert paper_notes["candidates"][0]["candidateType"] == "paper_note"


def test_local_research_model_output_requires_evidence_refs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [],
                "claims": [],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.4,
                "nextAction": "fix_evidence_refs",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "paper_note_needs_revision"
    assert any(issue["code"] == "missing_evidence_refs" for issue in response["validation"]["issues"])


def test_paper_note_draft_requires_key_finding_citation_anchor(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Observed effect", "sourceRef": "paper-1"}],
                "keyFindings": [{"finding": "Observed effect", "sourceRef": "paper-1"}],
                "methods": ["controlled experiment"],
                "limitations": ["small sample"],
                "citations": [{"sourceRef": "paper-1"}],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.62,
                "nextAction": "fix_citations",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "paper_note_needs_revision"
    issue_codes = {issue["code"] for issue in response["validation"]["issues"]}
    assert "missing_key_finding_citation" in issue_codes
    assert "missing_citation_anchor" in issue_codes


def test_neuro_mechanism_extract_records_mechanism_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "neuro_mechanism_extract",
            "title": "Mechanism candidate",
            "createdByAgent": "Neuro Mechanism Extraction Agent",
            "output": {
                "candidateType": "neuro_mechanism",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p5", "label": "page 5"}],
                "claims": [{"claim": "Candidate mechanism", "sourceRef": "paper-1"}],
                "paperNoteIds": ["paper-note-1"],
                "description": "Neuromodulation changes adaptive routing.",
                "brainSystems": ["prefrontal cortex"],
                "cognitiveFunctions": ["adaptive control"],
                "experimentalPhenomena": ["task-dependent modulation"],
                "authorInterpretation": "Authors link modulation to control.",
                "projectInterpretation": "Candidate routing analogy only.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.68,
                "nextAction": "send_to_mapping",
                "requiresReview": True,
            },
        },
    )
    mechanisms = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="neuro_mechanism")

    assert response["validation"]["valid"] is True
    assert response["candidate"]["currentState"] == "mechanism_candidate"
    assert response["candidate"]["currentWorkflowNode"] == "neuro_mechanism"
    assert mechanisms["candidateCount"] == 1
    assert mechanisms["candidates"][0]["candidateType"] == "neuro_mechanism"


def test_neuro_mechanism_extract_requires_terminology_uncertain_flag(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "neuro_mechanism_extract",
            "output": {
                "candidateType": "neuro_mechanism",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p5", "label": "page 5"}],
                "claims": [{"claim": "Candidate mechanism", "sourceRef": "paper-1"}],
                "paperNoteIds": ["paper-note-1"],
                "description": "Possible control-related mechanism.",
                "brainSystems": ["unknown"],
                "cognitiveFunctions": ["adaptive control"],
                "experimentalPhenomena": ["task-dependent modulation"],
                "authorInterpretation": "Authors suggest a control role.",
                "projectInterpretation": "Candidate mechanism only.",
                "uncertainty": ["brain system unknown"],
                "riskFlags": [],
                "confidence": 0.44,
                "nextAction": "fix_terminology",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "mechanism_needs_revision"
    assert any(issue["code"] == "terminology_uncertain_not_flagged" for issue in response["validation"]["issues"])


def test_mechanism_mapping_records_mapping_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "mechanism_mapping",
            "title": "Mapping candidate",
            "createdByAgent": "Mechanism Mapping Agent",
            "output": {
                "candidateType": "mechanism_mapping",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p8", "label": "page 8"}],
                "claims": [{"claim": "Adaptive routing can be treated as a computational abstraction.", "sourceRef": "paper-1"}],
                "neuroMechanismIds": ["mechanism-1"],
                "computationalAbstraction": "dynamic routing under context-dependent modulation",
                "factLayer": ["The paper reports context-dependent modulation."],
                "inferenceLayer": ["The project maps modulation to dynamic routing as an analogy."],
                "overAnalogyRisk": "low",
                "engineeringImplication": "Prototype a router that changes expert weights by context signal.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.59,
                "nextAction": "send_to_algorithm_hypothesis",
                "requiresReview": True,
            },
        },
    )
    mappings = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="mechanism_mapping")

    assert response["validation"]["valid"] is True
    assert response["candidate"]["currentState"] == "mechanism_mapping_candidate"
    assert response["candidate"]["currentWorkflowNode"] == "mechanism_mapping"
    assert mappings["candidateCount"] == 1
    assert mappings["candidates"][0]["candidateType"] == "mechanism_mapping"


def test_mechanism_mapping_requires_over_analogy_risk_flag(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "mechanism_mapping",
            "output": {
                "candidateType": "mechanism_mapping",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p8", "label": "page 8"}],
                "claims": [{"claim": "Possible mapping", "sourceRef": "paper-1"}],
                "neuroMechanismIds": ["mechanism-1"],
                "computationalAbstraction": "dynamic routing",
                "factLayer": ["The paper reports modulation."],
                "inferenceLayer": ["The project infers a routing analogy."],
                "overAnalogyRisk": "high",
                "engineeringImplication": "Try dynamic routing.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.41,
                "nextAction": "fix_analogy_risk",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "mapping_needs_revision"
    assert any(issue["code"] == "over_analogy_risk_not_flagged" for issue in response["validation"]["issues"])


def test_algorithm_hypothesis_records_hypothesis_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Algorithm hypothesis candidate",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve sample efficiency.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )
    hypotheses = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="algorithm_hypothesis")

    assert response["validation"]["valid"] is True
    assert response["candidate"]["currentState"] == "hypothesis_candidate"
    assert response["candidate"]["currentWorkflowNode"] == "algorithm_hypothesis"
    assert hypotheses["candidateCount"] == 1
    assert hypotheses["candidates"][0]["candidateType"] == "algorithm_hypothesis"


def test_algorithm_hypothesis_requires_complete_experiment_plan(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Possible algorithm idea", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Dynamic routing may help.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better adaptation",
                "expectedComputeCost": "small overhead",
                "experimentPlan": {"dataset": "synthetic task-switch benchmark"},
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.38,
                "nextAction": "fix_experiment_plan",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "hypothesis_needs_revision"
    assert any(issue["code"] == "incomplete_experiment_plan" for issue in response["validation"]["issues"])


def test_candidate_graph_builds_candidate_only_chain(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    paper_note = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Observed effect", "sourceRef": "paper-1"}],
                "keyFindings": [{"finding": "Observed effect", "sourceRef": "paper-1", "page": "3"}],
                "methods": ["controlled experiment"],
                "limitations": ["small sample"],
                "citations": [{"sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.7,
                "nextAction": "send_to_mechanism_extraction",
                "requiresReview": True,
            },
        },
    )["candidate"]
    mechanism = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "neuro_mechanism_extract",
            "output": {
                "candidateType": "neuro_mechanism",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p5", "label": "page 5"}],
                "claims": [{"claim": "Candidate mechanism", "sourceRef": "paper-1"}],
                "paperNoteIds": [paper_note["candidateId"]],
                "description": "Neuromodulation changes adaptive routing.",
                "brainSystems": ["prefrontal cortex"],
                "cognitiveFunctions": ["adaptive control"],
                "experimentalPhenomena": ["task-dependent modulation"],
                "authorInterpretation": "Authors link modulation to control.",
                "projectInterpretation": "Candidate routing analogy only.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.68,
                "nextAction": "send_to_mapping",
                "requiresReview": True,
            },
        },
    )["candidate"]
    mapping = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "mechanism_mapping",
            "output": {
                "candidateType": "mechanism_mapping",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p8", "label": "page 8"}],
                "claims": [{"claim": "Candidate abstraction", "sourceRef": "paper-1"}],
                "neuroMechanismIds": [mechanism["candidateId"]],
                "computationalAbstraction": "context-gated dynamic routing",
                "factLayer": ["The paper reports modulation."],
                "inferenceLayer": ["The project infers a routing analogy."],
                "overAnalogyRisk": "low",
                "engineeringImplication": "Use context signals to alter routing weights.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.57,
                "nextAction": "send_to_algorithm_hypothesis",
                "requiresReview": True,
            },
        },
    )["candidate"]
    team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": mapping["candidateId"], "label": "Mapping"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": [mapping["candidateId"]],
                "hypothesis": "Context-gated routing improves adaptation.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better adaptation",
                "expectedComputeCost": "small overhead",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )

    response = team_workflow_orchestration_service.build_candidate_graph(team["teamId"], {"createdByAgent": "Candidate Graph Preview Agent"})

    assert response["candidateGraph"]["candidateType"] == "candidate_graph"
    assert response["candidateGraph"]["currentState"] == "candidate_graph_visible"
    assert response["candidateGraph"]["qualityStatus"] == "preview_ready"
    assert response["graph"]["officialBoundary"]["writesOfficialGraph"] is False
    assert response["graph"]["summary"]["nodeCount"] == 4
    assert response["graph"]["summary"]["edgeCount"] == 3
    assert response["graph"]["missingLinks"] == []
    assert response["graph"]["unreviewedNodes"]


def test_candidate_graph_reports_missing_candidate_links(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "missing-mapping", "label": "Missing mapping"}],
                "claims": [{"claim": "Possible algorithm idea", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["missing-mapping"],
                "hypothesis": "Dynamic routing may help.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better adaptation",
                "expectedComputeCost": "small overhead",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.4,
                "nextAction": "fix_links",
                "requiresReview": True,
            },
        },
    )

    response = team_workflow_orchestration_service.build_candidate_graph(team["teamId"], {})

    assert response["candidateGraph"]["qualityStatus"] == "broken_links"
    assert response["graph"]["summary"]["missingLinkCount"] == 1
    assert response["graph"]["missingLinks"][0]["targetCandidateId"] == "missing-mapping"
    assert response["graph"]["missingLinks"][0]["relation"] == "inspired_by_mapping"


def test_candidate_graph_agent_curation_uses_approved_sources_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    approved_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding neural network evidence",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding supports learning and attention mechanisms.",
            "tags": ["neuro", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]
    revision_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Untraceable neuroscience note",
            "sourceKind": "paper",
            "summary": "Potentially relevant but missing a source location.",
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_quality_batch(team["teamId"], {})

    response = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {
            "createdByAgent": "Candidate Graph Agent",
            "curationMode": "agent_approved_only",
        },
    )

    graph_node_ids = {node["candidateId"] for node in response["graph"]["nodes"]}
    assert response["graph"]["summary"]["curationMode"] == "agent_approved_only"
    assert response["graph"]["summary"]["createdByAgent"] == "Candidate Graph Agent"
    assert response["graph"]["summary"]["stageAgentRole"] == "candidate_graph"
    assert response["reusedCandidateGraph"] is False
    assert response["ingestionFingerprint"]
    assert response["graph"]["summary"]["nodeCount"] == 1
    assert response["graph"]["summary"]["filteredCandidateCount"] == 1
    assert response["candidateGraph"]["createdByAgent"] == "Candidate Graph Agent"
    assert response["candidateGraph"]["metadata"]["stageAgentRole"] == "candidate_graph"
    assert response["candidateGraph"]["metadata"]["agentProcess"][0]["agentRole"] == "candidate_graph"
    assert response["candidateGraph"]["metadata"]["agentProcess"][1]["nextAction"] == "knowledge_ingestion_precheck"
    assert approved_source["candidateId"] in graph_node_ids
    assert revision_source["candidateId"] not in graph_node_ids

    reused = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {
            "createdByAgent": "Candidate Graph Agent",
            "curationMode": "agent_approved_only",
        },
    )

    assert reused["reusedCandidateGraph"] is True
    assert reused["candidateGraph"]["candidateId"] == response["candidateGraph"]["candidateId"]
    reused_events = _workflow_scene_events_by_code(scene_events, "candidate_graph.reused")
    assert reused_events
    assert reused_events[-1]["fields"]["candidateId"] == response["candidateGraph"]["candidateId"]
    assert reused_events[-1]["fields"]["ingestionFingerprint"] == response["ingestionFingerprint"]


def test_knowledge_ingestion_precheck_creates_candidate_only_steward_pack(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding neural network evidence",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding supports learning and attention mechanisms.",
            "tags": ["neuro", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {"assessedByAgent": "Source Quality Agent"},
    )
    graph_response = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {"createdByAgent": "Candidate Graph Agent", "curationMode": "agent_approved_only"},
    )

    response = team_workflow_orchestration_service.run_knowledge_ingestion_precheck(
        team["teamId"],
        {
            "stewardAgentId": "Knowledge Steward Agent",
            "targetDomain": "神经机制启发神经网络算法",
        },
    )

    output = response["candidate"]["metadata"]["output"]
    assert response["validation"]["valid"] is True
    assert response["candidate"]["candidateType"] == "review_record"
    assert response["candidate"]["currentWorkflowNode"] == "steward_ingestion"
    assert response["candidate"]["currentState"] == "steward_pack_draft"
    assert response["precheck"]["generatedByAgent"] == "Knowledge Steward Agent"
    assert response["precheck"]["candidateIds"] == [source["candidateId"]]
    assert response["precheck"]["candidateGraphId"] == graph_response["candidateGraph"]["candidateId"]
    assert output["agentProcess"][0]["agentRole"] == "knowledge_steward"
    assert output["agentProcess"][0]["candidateGraphId"] == graph_response["candidateGraph"]["candidateId"]
    assert output["approvalRequired"] is True
    assert "officialSync" not in output
    assert response["precheck"]["officialBoundary"]["writesOfficialKnowledge"] is False
    assert response["precheck"]["officialBoundary"]["writesOfficialRag"] is False
    assert response["precheck"]["officialBoundary"]["writesOfficialGraph"] is False
    assert response["status"]["summary"]["stewardPackCandidateCount"] == 1


def test_review_prefilter_records_review_record_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "review_prefilter",
            "title": "Review prefilter",
            "createdByAgent": "Evidence Review Agent",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "hypothesis", "id": "hypothesis-1", "label": "Hypothesis 1"}],
                "claims": [{"claim": "Candidate has a testable plan.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "checklist": [
                    {"item": "evidence trace", "status": "pass", "note": "source refs present"},
                    {"item": "experiment plan", "status": "needs_attention", "note": "smoke plan is minimal"},
                ],
                "comments": "Prefilter only: evidence exists but experiment plan should be reviewed.",
                "requiredChanges": ["Clarify dataset split before steward handoff."],
                "needsDecision": True,
                "uncertainty": ["dataset split not finalized"],
                "riskFlags": ["needs_human_decision"],
                "confidence": 0.64,
                "nextAction": "request_review_decision",
                "requiresReview": True,
            },
        },
    )
    reviews = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="review_record")

    assert response["validation"]["valid"] is True
    assert response["candidate"]["candidateType"] == "review_record"
    assert response["candidate"]["currentWorkflowNode"] == "research_review"
    assert response["candidate"]["currentState"] == "review_prefiltered"
    assert reviews["candidateCount"] == 1


def test_review_prefilter_rejects_final_decision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "review_prefilter",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "hypothesis", "id": "hypothesis-1", "label": "Hypothesis 1"}],
                "claims": [{"claim": "Candidate has a testable plan.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "checklist": [{"item": "evidence trace", "status": "pass"}],
                "comments": "Looks ready.",
                "requiredChanges": [],
                "needsDecision": False,
                "decision": "approve_for_steward",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.8,
                "nextAction": "send_to_steward",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "review_needs_revision"
    assert any(issue["code"] == "final_decision_not_allowed" for issue in response["validation"]["issues"])


def test_steward_pack_draft_records_ingestion_pack_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": "Knowledge Steward Agent",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {
                    "sourceIds": ["paper-1"],
                    "reviewRecordIds": ["review-1"],
                    "candidateGraphId": "graph-1",
                },
                "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
                "proposalPayload": {
                    "proposalType": "refinement_proposal",
                    "summary": "Add context-gated routing hypothesis as a governed research candidate.",
                },
                "ratingSuggestion": {
                    "rating": "reviewable",
                    "reason": "Needs approval before official ingestion.",
                },
                "approvalRequired": True,
                "uncertainty": ["experiment not yet validated"],
                "riskFlags": ["approval_required"],
                "confidence": 0.61,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is True
    assert response["candidate"]["candidateType"] == "review_record"
    assert response["candidate"]["currentWorkflowNode"] == "steward_ingestion"
    assert response["candidate"]["currentState"] == "steward_pack_draft"


def test_steward_pack_requires_approval_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"]},
                "riskSummary": "Needs approval.",
                "proposalPayload": {"proposalType": "refinement_proposal"},
                "ratingSuggestion": {"rating": "reviewable"},
                "approvalRequired": False,
                "officialSync": {"write": True},
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.5,
                "nextAction": "write_official",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "steward_needs_revision"
    issue_codes = {issue["code"] for issue in response["validation"]["issues"]}
    assert "approval_required_not_true" in issue_codes
    assert "official_write_not_allowed" in issue_codes


def test_steward_pack_submits_pending_knowledge_ingestion_without_official_write(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": steward["agentId"],
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"], "candidateGraphId": "graph-1"},
                "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
                "proposalPayload": {
                    "title": "Govern context-gated routing hypothesis",
                    "summary": "Add the hypothesis as a governed research candidate.",
                },
                "ratingSuggestion": {
                    "importanceLevel": "high",
                    "confidence": 0.66,
                    "stability": "evolving",
                    "reviewPriority": "elevated",
                    "reason": "Needs approval before official ingestion.",
                },
                "approvalRequired": True,
                "uncertainty": ["experiment not yet validated"],
                "riskFlags": ["approval_required"],
                "confidence": 0.61,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )["candidate"]

    source_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        candidate["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
        },
    )
    inbox_source_id = source_pending["candidate"]["metadata"]["knowledgeIngestion"]["inboxSourceId"]
    reviewed_source = team_knowledge_service.review_owner_inbox_source(
        "team",
        team["teamId"],
        inbox_source_id,
        decision="accepted",
        reviewed_by_agent_id=steward["agentId"],
    )
    response = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        candidate["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
            "centralSourceId": reviewed_source["centralSource"]["centralSourceId"],
        },
    )
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
    )
    rating_suggestions = team_knowledge_service.list_rating_suggestions(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
        status="pending",
    )

    assert source_pending["candidate"]["currentState"] == "steward_pending_source_review"
    assert source_pending["knowledgeIngestion"]["status"] == "pending_source_review"
    assert response["candidate"]["currentState"] == "steward_pending_knowledge_review"
    assert response["knowledgeIngestion"]["package"]["proposal"]["status"] == "pending"
    assert response["knowledgeIngestion"]["package"]["proposal"]["sourceArtifactIds"] == [
        response["knowledgeIngestion"]["package"]["sourceArtifact"]["sourceArtifactId"]
    ]
    assert response["knowledgeIngestion"]["officialBoundary"]["writesOfficialKnowledge"] is False
    assert response["knowledgeIngestion"]["officialBoundary"]["writesOfficialGraph"] is False
    assert response["knowledgeIngestion"]["ratingSuggestion"]["status"] == "pending"
    assert rating_suggestions["summary"]["suggestionCount"] == 1
    assert knowledge_items["summary"]["itemCount"] == 0


def test_steward_pack_approval_gate_applies_pending_ingestion_to_formal_knowledge(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": steward["agentId"],
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"], "candidateGraphId": "graph-1"},
                "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
                "proposalPayload": {"title": "Govern context-gated routing hypothesis", "summary": "Add the hypothesis as governed knowledge."},
                "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.66, "stability": "evolving", "reviewPriority": "elevated"},
                "approvalRequired": True,
                "uncertainty": ["experiment not yet validated"],
                "riskFlags": ["approval_required"],
                "confidence": 0.61,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )["candidate"]
    pending = _submit_steward_pack_through_source_review(
        team["teamId"],
        candidate["candidateId"],
        knowledge_base["knowledgeBaseId"],
        steward["agentId"],
    )["knowledgePending"]["candidate"]

    response = team_workflow_orchestration_service.review_steward_pack_knowledge_ingestion(
        team["teamId"],
        pending["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "reviewedByAgentId": steward["agentId"],
            "decision": "approved",
            "resolutionNote": "Evidence accepted for official knowledge.",
        },
    )
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
    )
    rating_suggestions = team_knowledge_service.list_rating_suggestions(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
    )

    official_record = response["candidate"]["metadata"]["officialSyncRecord"]
    rating_migration = official_record["ratingSuggestionMigration"]
    official_graph = official_record["officialResearchGraph"]
    migrated_source = next(
        item
        for item in rating_suggestions["suggestions"]
        if item["suggestionId"] == rating_migration["sourceSuggestionId"]
    )
    migrated_target = next(
        item
        for item in rating_suggestions["suggestions"]
        if item["suggestionId"] == rating_migration["targetSuggestionId"]
    )
    assert response["candidate"]["currentState"] == "official_synced"
    assert response["candidate"]["qualityStatus"] == "approved"
    assert response["knowledgeIngestion"]["review"]["proposal"]["status"] == "applied"
    assert response["knowledgeIngestion"]["review"]["item"]["knowledgeItemId"] in official_record["knowledgeItemIds"]
    assert official_record["formalKnowledgeItemCreated"] is True
    assert official_record["writesOfficialKnowledge"] is True
    assert official_record["writesOfficialRag"] is False
    assert official_record["writesOfficialGraph"] is True
    assert official_record["ragStatus"] == "queryable_via_reviewed_team_knowledge"
    assert official_record["graphStatus"] == "official_research_trace_synced"
    assert official_graph["status"] == "synced"
    assert official_graph["officialBoundary"]["writesOfficialGraph"] is True
    assert official_graph["summary"]["edgeCount"] >= 3
    assert {edge["relation"] for edge in official_graph["edges"]}.issuperset({"supports", "approved_for_ingestion"})
    formal_item = knowledge_items["items"][0]
    assert formal_item["metadata"]["officialResearchGraph"]["knowledgeItemIds"] == official_record["knowledgeItemIds"]
    assert formal_item["metadata"]["officialResearchGraph"]["edges"] == official_graph["edges"]
    assert rating_migration["status"] == "migrated"
    assert rating_migration["targetType"] == "knowledge_item"
    assert rating_migration["knowledgeItemId"] == response["knowledgeIngestion"]["review"]["item"]["knowledgeItemId"]
    assert migrated_source["targetType"] == "proposal"
    assert migrated_source["status"] == "applied"
    assert migrated_target["targetType"] == "knowledge_item"
    assert migrated_target["knowledgeItemId"] == rating_migration["knowledgeItemId"]
    assert migrated_target["importanceLevel"] == "high"
    assert migrated_target["status"] == "pending"
    assert knowledge_items["summary"]["itemCount"] == 1


def test_knowledge_collection_ingestion_notifies_steward_agent_for_final_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    deliveries = []

    def fake_wake(message):
        deliveries.append(message)
        return {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-steward-ingest",
            "reason": "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and learning.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Data Discovery Agent",
        },
    )
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Synaptic plasticity learning rule review",
            "sourceUrl": "https://doi.org/10.0000/stdp-review",
            "sourceKind": "review",
            "summary": "Synaptic plasticity evidence can support learning-rule hypotheses.",
            "tags": ["neuroscience", "learning"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Acquisition Agent",
        },
    )

    response = team_workflow_orchestration_service.run_knowledge_collection_ingestion(
        team["teamId"],
        {
            "sourceQualityAgentId": "资料审查 Agent",
            "candidateGraphAgentId": "候选关系 Agent",
            "stewardAgentId": steward["agentId"],
            "targetDomain": "神经学启发神经网络算法",
            "maxCandidates": 10,
        },
    )
    knowledge_base_id = response["summary"]["knowledgeBaseId"]
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base_id,
        agent_id=steward["agentId"],
    )
    step_ids = [step["stageId"] for step in response["steps"]]
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(steward["agentId"], status="pending")

    assert response["status"] == "agent_notified"
    assert response["reusedCandidateGraph"] is False
    assert response["reusedStewardPack"] is False
    assert response["ingestionFingerprint"]
    assert step_ids == [
        "source_review",
        "candidate_graph",
        "steward_pack",
        "knowledge_steward_request",
    ]
    assert response["sourceQuality"]["officialBoundary"]["writesFormalKnowledge"] is False
    assert response["candidateGraph"]["graph"]["officialBoundary"]["writesOfficialGraph"] is False
    assert response["precheck"]["precheck"]["officialBoundary"]["writesOfficialKnowledge"] is False
    assert response["sourceReview"] is None
    assert response["knowledgeSubmission"] is None
    assert response["knowledgeReview"] is None
    assert response["knowledgeStewardActivation"]["status"] == "agent_wake_started"
    assert response["knowledgeStewardActivation"]["messageId"]
    assert response["knowledgeStewardActivation"]["delivery"]["turnId"] == "turn-steward-ingest"
    assert response["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert response["knowledgeStewardActivation"]["kernel"]["outcomeStatus"] == "succeeded"
    assert deliveries and deliveries[0]["metadata"]["stewardPackCandidateId"] == response["summary"]["stewardPackCandidateId"]
    assert deliveries[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert deliveries[0]["metadata"]["kernelTaskId"] == response["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["messageId"] == response["summary"]["knowledgeStewardInboxMessageId"]
    assert inbox_messages[0]["kind"] == "challenge_cup_knowledge_ingestion_request"
    assert inbox_messages[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert inbox_messages[0]["metadata"]["kernelTaskId"] == response["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["metadata"]["knowledgeBaseId"] == knowledge_base_id

    second = team_workflow_orchestration_service.run_knowledge_collection_ingestion(
        team["teamId"],
        {
            "sourceQualityAgentId": "资料审查 Agent",
            "candidateGraphAgentId": "候选关系 Agent",
            "stewardAgentId": steward["agentId"],
            "targetDomain": "神经学启发神经网络算法",
            "maxCandidates": 10,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
        },
    )

    assert second["reusedCandidateGraph"] is True
    assert second["reusedStewardPack"] is True
    assert second["summary"]["stewardPackCandidateId"] == response["summary"]["stewardPackCandidateId"]
    assert response["statusSnapshot"]["summary"]["formalKnowledgeItemCount"] == 0
    assert knowledge_items["summary"]["itemCount"] == 0
    steward_events = _workflow_scene_events_by_code(scene_events, "knowledge_collection.steward_notification_completed")
    assert steward_events
    assert steward_events[-1]["fields"]["status"] == "agent_wake_started"
    assert steward_events[-1]["child_log_payload"]["turnId"] == "turn-steward-ingest"
    ingestion_events = _workflow_scene_events_by_code(scene_events, "knowledge_collection.ingested")
    assert ingestion_events[-2]["child_log_payload"]["kind"] == "knowledge_collection_ingestion"
    assert ingestion_events[-2]["child_log_payload"]["status"] == "agent_notified"
    assert [step["stageId"] for step in ingestion_events[-2]["child_log_payload"]["steps"]] == step_ids
    assert ingestion_events[-2]["child_log_payload"]["knowledgeStewardActivation"]["status"] == "agent_wake_started"
    precheck_reused_events = _workflow_scene_events_by_code(scene_events, "knowledge_ingestion.precheck_reused")
    assert precheck_reused_events
    assert precheck_reused_events[-1]["fields"]["candidateId"] == response["summary"]["stewardPackCandidateId"]


def test_knowledge_ingestion_status_tracks_pending_and_official_sync(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(
        team["teamId"],
        owner_agent_id="Research Coordination Agent",
    )
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Neuromodulation review",
            "sourceUrl": "https://example.test/paper",
            "sourceKind": "paper",
            "createdByAgent": "Knowledge Collection Agent",
        },
    )
    paper_note_candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "title": "Paper note draft",
            "createdByAgent": "Paper Note Extraction Agent",
            "output": {
                "candidateType": "paper_note",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Observed modulation effect.", "sourceRef": "paper-1"}],
                "keyFindings": [
                    {
                        "finding": "Observed modulation effect.",
                        "sourceRef": "paper-1",
                        "page": "3",
                        "citation": "Paper 1, p.3",
                    }
                ],
                "methods": ["controlled experiment"],
                "limitations": ["small sample"],
                "citations": [{"sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.72,
                "nextAction": "send_to_mechanism_extraction",
                "requiresReview": False,
            },
        },
    )["candidate"]
    paper_transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": paper_note_candidate["candidateId"],
            "fromNode": "paper_note",
            "toNode": "research_review",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "Paper note has citation anchors.",
        },
    )["transfer"]
    team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        paper_transfer["transferId"],
        {
            "decision": "approved",
            "decidedByAgent": "Research Coordination Agent",
            "targetState": "approved_to_ingest",
        },
    )
    mechanism_candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "neuro_mechanism_extract",
            "title": "Neuro mechanism draft",
            "createdByAgent": "Neuro Mechanism Extraction Agent",
            "output": {
                "candidateType": "neuro_mechanism",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "claims": [{"claim": "Candidate mechanism.", "sourceRef": "paper-1"}],
                "paperNoteIds": [paper_note_candidate["candidateId"]],
                "description": "Neuromodulation changes adaptive routing.",
                "brainSystems": ["prefrontal cortex"],
                "cognitiveFunctions": ["adaptive control"],
                "experimentalPhenomena": ["task-dependent modulation"],
                "authorInterpretation": "Authors link modulation to control.",
                "projectInterpretation": "Candidate routing analogy only.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.61,
                "nextAction": "send_to_algorithm_hypothesis",
                "requiresReview": False,
            },
        },
    )["candidate"]
    mechanism_transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": mechanism_candidate["candidateId"],
            "fromNode": "neuro_mechanism",
            "toNode": "research_review",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "Mechanism candidate has paper note support.",
        },
    )["transfer"]
    team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        mechanism_transfer["transferId"],
        {
            "decision": "approved",
            "decidedByAgent": "Research Coordination Agent",
            "targetState": "approved_to_ingest",
        },
    )
    hypothesis_candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Algorithm hypothesis draft",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mechanism", "id": mechanism_candidate["candidateId"], "label": "Mechanism 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "neuroMechanismIds": [mechanism_candidate["candidateId"]],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.53,
                "nextAction": "send_to_research_review",
                "requiresReview": False,
            },
        },
    )["candidate"]
    review_transfer = team_workflow_orchestration_service.submit_transfer_request(
        team["teamId"],
        {
            "candidateId": hypothesis_candidate["candidateId"],
            "fromNode": "algorithm_hypothesis",
            "toNode": "research_review",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "Hypothesis prefilter passed for steward ingestion pack.",
        },
    )["transfer"]
    hypothesis_candidate = team_workflow_orchestration_service.decide_transfer_request(
        team["teamId"],
        review_transfer["transferId"],
        {
            "decision": "approved",
            "decidedByAgent": "Research Coordination Agent",
            "targetState": "approved_to_ingest",
        },
    )["candidate"]
    steward_candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": steward["agentId"],
            "output": _steward_pack_output(candidate_ids=[hypothesis_candidate["candidateId"]]),
        },
    )["candidate"]

    source_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        steward_candidate["candidateId"],
        {"knowledgeBaseId": knowledge_base["knowledgeBaseId"], "proposedByAgentId": steward["agentId"]},
    )
    source_pending_status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])

    assert source_pending["candidate"]["currentState"] == "steward_pending_source_review"
    assert source_pending_status["summary"]["pendingKnowledgeReviewCandidateCount"] == 0
    assert source_pending_status["summary"]["pendingProposalCount"] == 0
    assert any(item["code"] == "steward_source_pending_review" for item in source_pending_status["actionItems"])

    inbox_source_id = source_pending["candidate"]["metadata"]["knowledgeIngestion"]["inboxSourceId"]
    reviewed_source = team_knowledge_service.review_owner_inbox_source(
        "team",
        team["teamId"],
        inbox_source_id,
        decision="accepted",
        reviewed_by_agent_id=steward["agentId"],
    )
    pending_candidate = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        steward_candidate["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
            "centralSourceId": reviewed_source["centralSource"]["centralSourceId"],
        },
    )["candidate"]
    pending_status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])

    assert pending_status["status"] == "needs_review"
    assert pending_status["summary"]["sourceCandidateCount"] == 1
    assert pending_status["summary"]["localDraftCandidateCount"] == 4
    assert pending_status["summary"]["pendingKnowledgeReviewCandidateCount"] == 1
    assert pending_status["summary"]["pendingProposalCount"] == 1
    assert pending_status["summary"]["formalKnowledgeItemCount"] == 0
    assert pending_status["officialBoundary"]["writesOfficialKnowledge"] is False
    assert pending_status["officialBoundary"]["writesOfficialGraph"] is False
    assert pending_status["officialBoundary"]["graphStatus"] == "candidate_graph_preview_only"
    assert any(item["code"] == "knowledge_proposal_pending_review" for item in pending_status["actionItems"])
    assert pending_status["knowledgeBases"][0]["stats"]["pendingProposalCount"] == 1

    team_workflow_orchestration_service.review_steward_pack_knowledge_ingestion(
        team["teamId"],
        pending_candidate["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "reviewedByAgentId": steward["agentId"],
            "decision": "approved",
            "resolutionNote": "Evidence accepted for official knowledge.",
        },
    )
    ready_status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])

    assert ready_status["status"] == "ready"
    assert ready_status["summary"]["pendingProposalCount"] == 0
    assert ready_status["summary"]["formalKnowledgeItemCount"] == 1
    assert ready_status["summary"]["officialSyncedCandidateCount"] == 1
    assert ready_status["summary"]["officialGraphSyncedCandidateCount"] == 1
    assert ready_status["officialBoundary"]["writesOfficialKnowledge"] is True
    assert ready_status["officialBoundary"]["writesOfficialRag"] is False
    assert ready_status["officialBoundary"]["writesOfficialGraph"] is True
    assert ready_status["officialBoundary"]["ragStatus"] == "queryable_via_reviewed_team_knowledge"
    assert ready_status["officialBoundary"]["graphStatus"] == "official_research_trace_synced"
    assert ready_status["actionItems"] == [
        {
            "code": "knowledge_ingestion_operational",
            "severity": "ready",
            "message": "资料搜索、提炼、审查和入库链路已跑通。",
            "nextAction": "",
            "workflowNode": "official_sync",
        }
    ]


def test_steward_pack_approval_gate_rejects_pending_ingestion_without_formal_write(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate needs governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"]},
                "riskSummary": "Evidence is not enough for official sync.",
                "proposalPayload": {"title": "Rejectable research candidate", "summary": "Needs stronger evidence."},
                "ratingSuggestion": {"importanceLevel": "medium", "confidence": 0.45, "stability": "evolving", "reviewPriority": "elevated"},
                "approvalRequired": True,
                "uncertainty": ["weak experiment evidence"],
                "riskFlags": ["approval_required", "weak_evidence"],
                "confidence": 0.45,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )["candidate"]
    pending = _submit_steward_pack_through_source_review(
        team["teamId"],
        candidate["candidateId"],
        knowledge_base["knowledgeBaseId"],
        steward["agentId"],
    )["knowledgePending"]["candidate"]

    response = team_workflow_orchestration_service.review_steward_pack_knowledge_ingestion(
        team["teamId"],
        pending["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "reviewedByAgentId": steward["agentId"],
            "decision": "rejected",
            "resolutionNote": "Evidence is too weak.",
        },
    )
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
    )
    rating_suggestions = team_knowledge_service.list_rating_suggestions(
        knowledge_base["knowledgeBaseId"],
        agent_id=steward["agentId"],
    )

    official_record = response["candidate"]["metadata"]["officialSyncRecord"]
    assert response["candidate"]["currentState"] == "steward_needs_revision"
    assert response["candidate"]["qualityStatus"] == "rejected_by_gate"
    assert response["knowledgeIngestion"]["review"]["proposal"]["status"] == "rejected"
    assert official_record["formalKnowledgeItemCreated"] is False
    assert official_record["writesOfficialKnowledge"] is False
    assert official_record["writesOfficialGraph"] is False
    assert official_record["ragStatus"] == "not_synced"
    assert official_record["graphStatus"] == "not_synced"
    assert official_record["officialResearchGraph"]["status"] == "not_synced"
    assert official_record["officialResearchGraph"]["reason"] == "decision_not_approved"
    assert official_record["ratingSuggestionMigration"]["status"] == "skipped"
    assert official_record["ratingSuggestionMigration"]["reason"] == "decision_not_approved"
    assert all(item["targetType"] != "knowledge_item" for item in rating_suggestions["suggestions"])
    assert knowledge_items["summary"]["itemCount"] == 0


def test_steward_pack_approval_gate_rejects_unsubmitted_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"]},
                "riskSummary": "Evidence is traceable.",
                "proposalPayload": {"title": "Unsubmitted candidate", "summary": "Not in pending queue."},
                "ratingSuggestion": {"importanceLevel": "medium", "confidence": 0.6, "stability": "evolving", "reviewPriority": "elevated"},
                "approvalRequired": True,
                "uncertainty": [],
                "riskFlags": ["approval_required"],
                "confidence": 0.6,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )["candidate"]

    try:
        team_workflow_orchestration_service.review_steward_pack_knowledge_ingestion(
            team["teamId"],
            candidate["candidateId"],
            {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "reviewedByAgentId": steward["agentId"],
                "decision": "approved",
            },
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "Only steward_pending_knowledge_review candidates" in str(exc)
    else:
        raise AssertionError("unsubmitted steward pack should not pass approval gate")


def test_steward_pack_submission_rejects_non_steward_pack_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": steward["agentId"], "role": "steward"}],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Challenge Cup Governed Knowledge",
        actor_agent_id=steward["agentId"],
    )
    candidate = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "review_prefilter",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "hypothesis", "id": "hypothesis-1", "label": "Hypothesis 1"}],
                "claims": [{"claim": "Candidate has a testable plan.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "checklist": [{"item": "experiment plan", "status": "pass"}],
                "comments": "Prefilter only.",
                "requiredChanges": [],
                "needsDecision": True,
                "uncertainty": [],
                "riskFlags": ["needs_human_decision"],
                "confidence": 0.66,
                "nextAction": "request_review_decision",
                "requiresReview": True,
            },
        },
    )["candidate"]

    try:
        team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
            team["teamId"],
            candidate["candidateId"],
            {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "proposedByAgentId": steward["agentId"],
            },
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert (
            "Only steward_pack_draft or steward_pending_source_review candidates"
            in str(exc)
        )
    else:
        raise AssertionError("non steward pack candidate should not be submitted to knowledge ingestion")


def test_local_research_model_invoke_records_candidate_from_json_content(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    _FakeLocalResearchClient.response = _FakeLocalResearchMessage(
        """
        {
          "candidateType": "paper_note",
          "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
          "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
          "claims": [{"claim": "Observed effect", "sourceRef": "paper-1"}],
          "keyFindings": [{"finding": "Observed effect", "sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
          "methods": ["controlled experiment"],
          "limitations": ["small sample"],
          "citations": [{"sourceRef": "paper-1", "page": "3", "citation": "Paper 1, p.3"}],
          "uncertainty": [],
          "riskFlags": [],
          "confidence": 0.73,
          "nextAction": "send_to_mechanism_extraction",
          "requiresReview": true
        }
        """
    )
    _FakeLocalResearchClient.captured_messages = []

    response = team_workflow_orchestration_service.invoke_local_research_model(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
            "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
            "excerpt": "A short source excerpt.",
            "createdByAgent": "Paper Note Extraction Agent",
        },
        llm_client_factory=_FakeLocalResearchClient,
    )

    assert response["validation"]["valid"] is True
    assert response["candidate"]["candidateType"] == "paper_note"
    assert response["candidate"]["currentState"] == "paper_note_draft"
    assert response["modelResponse"]["jsonSource"] == "content"
    assert response["modelResponse"]["modelId"] == "houmo_qwen35_9b_agent"
    assert response["modelResponse"]["modelProfileId"] == "__challenge_cup_local_research_model"
    assert "profileId" not in response["modelResponse"]
    assert _FakeLocalResearchClient.captured_messages[0]["profile_id"] == "__challenge_cup_local_research_model"
    assert _FakeLocalResearchClient.captured_messages[0]["metadata"]["taskType"] == "paper_note_draft"


def test_local_research_model_invoke_rejects_unparseable_output_without_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    _FakeLocalResearchClient.response = _FakeLocalResearchMessage("not json")
    _FakeLocalResearchClient.captured_messages = []

    try:
        team_workflow_orchestration_service.invoke_local_research_model(
            team["teamId"],
            {
                "taskType": "paper_note_draft",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
                "excerpt": "A short source excerpt.",
            },
            llm_client_factory=_FakeLocalResearchClient,
        )
    except team_workflow_orchestration_service.TeamWorkflowOrchestrationError as exc:
        assert "did not contain a JSON object" in str(exc)
    else:
        raise AssertionError("unparseable local model output should fail")

    workflow = team_workflow_orchestration_service.get_team_workflow_orchestration(team["teamId"])
    assert workflow["candidateStore"]["candidateCount"] == 0
