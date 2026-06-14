import json
from concurrent.futures import Future

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
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "load_public_config", _fake_local_research_public_config)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _NoopBackgroundExecutor())


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
    coordinator = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    discovery = agent_directory_service.create_agent_instance(display_name="Discovery", direct_session_id="session-discovery")
    acquisition = agent_directory_service.create_agent_instance(display_name="Acquisition", direct_session_id="session-acquisition")
    extraction = agent_directory_service.create_agent_instance(display_name="Extraction", direct_session_id="session-extraction")
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
    assert execution["importedCount"] == 2
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
    assert records[0]["collectionTrace"]["assignmentId"] == run_response["assignments"][0]["assignmentId"]
    assert candidates["candidateCount"] == 2
    assert all(candidate["metadata"]["sourceCollectionSearchExecution"] is True for candidate in candidates["candidates"])
    assert all(candidate["metadata"]["importedFromDataRecord"]["runId"] == run_response["run"]["runId"] for candidate in candidates["candidates"])
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
    assert second["status"] == "no_open_assignment"
    assert calls == [run_response["searchPlan"]["queries"][0]["queryId"]]
    assert data_processing_service.list_records(run_response["run"]["runId"])["summary"]["recordCount"] == 2


def test_start_research_stage_round_creates_knowledge_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    assert stage_round["status"] == "needs_attention"
    assert stage_round["roundNumber"] == 1
    assert stage_round["sourceRunIds"] == [response["run"]["runId"]]
    assert stage_round["dataSearchPlanRef"]["planId"] == response["searchPlan"]["planId"]
    assert stage_round["promptCachePolicy"]["gate"]["status"] == "satisfied"
    assert stage_round["teamMemoryRecord"]["promptCachePolicyRef"]["gateStatus"] == "satisfied"
    assert stage_round["teamMemoryRecord"]["recordKind"] == "team_workflow_stage_record"
    assert stage_round["teamMemoryRecord"]["boundary"] == "runtime_stage_record_only_not_formal_team_knowledge"
    assert stage_round["coordinationContract"]["autoStarted"] is True
    assert stage_round["coordinationContract"]["startResult"]["started"] is False
    assert "coordination_round_not_started" in {item["code"] for item in stage_round["warnings"]}
    assert response["boundaries"]["writesFormalKnowledge"] is False
    assert response["searchPlan"]["boundaries"]["externalSearchTriggered"] is False
    assert response["searchPlan"]["promptCachePolicy"]["requirement"] == "required_for_llm_execution"
    assert status_payload["phases"][0]["activeRoundId"] == stage_round["stageRoundId"]
    assert status_payload["phases"][0]["roundCount"] == 1


def test_start_research_stage_round_reuses_active_knowledge_collection_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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


def test_start_research_stage_round_auto_starts_team_coordination_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    assert response["stageRound"]["coordinationRoundId"]
    assert response["stageRound"]["coordinationContract"]["startResult"]["started"] is True
    assert response["stageRound"]["coordinationContract"]["startResult"]["roundId"] == response["stageRound"]["coordinationRoundId"]
    assert room["activeRoundId"] == response["stageRound"]["coordinationRoundId"]


def test_retry_research_stage_round_coordination_starts_room_and_clears_warning(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    assert retry["stageRound"]["coordinationContract"]["startResult"]["started"] is True
    assert retry["stageRound"]["coordinationRoundId"]
    assert "coordination_round_not_started" not in {item["code"] for item in retry["stageRound"]["warnings"]}


def test_start_research_stage_round_new_round_inherits_previous_topic_and_links_upstream(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    assert experiment["stageRound"]["status"] == "needs_attention"
    assert experiment["stageRound"]["upstreamRoundIds"] == [knowledge["stageRound"]["stageRoundId"]]
    assert experiment["stageRound"]["planningContract"]["requiresUserDecision"] is True
    assert experiment["stageRound"]["coordinationContract"]["startResult"]["started"] is False
    assert "coordination_round_not_started" in {item["code"] for item in experiment["stageRound"]["warnings"]}


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
            "message": "知识搜集、筛选、共享记忆和图谱同步链路已跑通。",
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
