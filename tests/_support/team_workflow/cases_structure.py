from __future__ import annotations

from tests._support.team_workflow.helpers import *  # noqa: F403

def test_source_collection_stage_round_sync_has_single_implementation_across_split_modules():
    service_path = Path(team_workflow_orchestration_service.__file__)
    # Packs may live under team_workflow/** (e.g. source_collection/), not only the top level.
    split_module_paths = sorted((service_path.parent / "team_workflow").rglob("*.py"))
    candidate_paths = [service_path, *split_module_paths]

    implementation_count = 0
    for path in candidate_paths:
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        implementation_count += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_sync_source_collection_stage_round_after_search"
        )

    assert implementation_count == 1
    assert (
        team_workflow_orchestration_service._sync_source_collection_stage_round_after_search.__module__
        == "core.web.services.team_workflow.source_collection.search_execution"
    )

def test_source_collection_pure_helpers_are_package_backed():
    from core.web.services.team_workflow import (
        source_collection_common,
        source_collection_context,
        source_collection_projection,
        source_collection_stage_tasks,
    )

    count_cases = [
        ("invalid", 0),
        (-7, 0),
        (42, 42),
        (1_000_000, 100_000),
    ]
    for value, expected in count_cases:
        package_result = source_collection_common.source_collection_count(value)
        facade_result = team_workflow_orchestration_service._source_collection_count(value)

        assert package_result == facade_result
        assert package_result == expected

    text_list_cases = [
        ("not-a-list", 4, 12, []),
        ([" alpha ", "", "alpha", " beta ", None], 5, 12, ["alpha", "beta"]),
        (["one", "two", "three"], 2, 12, ["one", "two"]),
        (["alphabet", "beta"], 2, 4, ["alph", "beta"]),
    ]
    for value, max_items, max_length, expected in text_list_cases:
        package_result = source_collection_common.normalize_text_list(
            value,
            max_items=max_items,
            max_length=max_length,
        )
        facade_result = team_workflow_orchestration_service._normalize_text_list(
            value,
            max_items=max_items,
            max_length=max_length,
        )

        assert package_result == facade_result
        assert package_result == expected
    assert (
        team_workflow_orchestration_service._source_collection_stage_task_checklist
        is source_collection_stage_tasks.source_collection_stage_task_checklist
    )
    assert (
        team_workflow_orchestration_service._source_collection_stage_card_projection
        is source_collection_projection.source_collection_stage_card_projection
    )
    assert (
        team_workflow_orchestration_service._source_collection_context_continuation_hint
        is source_collection_context.source_collection_context_continuation_hint
    )
    assert (
        team_workflow_orchestration_service._compact_source_collection_stage_task_context
        is source_collection_context.compact_source_collection_stage_task_context
    )

def test_source_collection_agent_role_registries_only_include_four_stage_roles():
    expected = {"source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"}

    assert agent_directory_service.RESEARCH_SOURCE_ROLE_KEYS == expected
    assert agent_role_tool_profile_service.RESEARCH_SOURCE_ROLE_KEYS == expected

def test_source_collection_formal_knowledge_boundary_requires_source_ingestor_stage():
    assert team_workflow_orchestration_service._source_collection_stage_can_materialize_formal_knowledge(
        "ingestion",
        "source_ingestor",
    ) is True
    assert team_workflow_orchestration_service._source_collection_stage_can_materialize_formal_knowledge(
        "ingestion",
        "source_extractor",
    ) is False
    assert team_workflow_orchestration_service._source_collection_stage_can_materialize_formal_knowledge(
        "extraction",
        "source_ingestor",
    ) is False

    contract = team_workflow_orchestration_service._source_collection_stage_task_writeback_contract(
        "team-boundary",
        "run-boundary",
        "task-boundary",
        stage_id="ingestion",
        agent_id="content-agent",
        agent_role="source_extractor",
    )
    assert contract["writesFormalKnowledge"] is False
    assert contract["writesOfficialGraph"] is False
    assert contract["resultAuthority"] == "source_collection_stage_writeback_tool"

def test_source_collection_writeback_contract_uses_facade_schema_version(monkeypatch):
    monkeypatch.setattr(team_workflow_orchestration_service, "SCHEMA_VERSION", 7)

    contract = team_workflow_orchestration_service._source_collection_stage_task_writeback_contract(
        "team-schema",
        "run-schema",
        "task-schema",
        stage_id="finding",
        agent_id="finder-agent",
        agent_role="source_finder",
    )

    assert contract["schemaVersion"] == 7

def test_memory_steward_context_returns_approved_candidate_action_packet_without_pending_body(tmp_path, monkeypatch):
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
    approved = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/steward-context-approved",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for hierarchy and attention mechanisms.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/steward-context-approved"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        approved["candidateId"],
        {
            "assessedByAgent": "source-quality-agent",
            "decision": "approved",
            "notes": "神经预测编码主题相关，元数据可追踪。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/steward-context-approved"}],
        },
    )
    pending_marker = "PENDING_BODY_SHOULD_NOT_BE_VISIBLE"
    for index in range(14):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Pending candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/steward-context-pending-{index}",
                "sourceKind": "paper",
                "summary": f"{pending_marker} " * 120,
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.0000/steward-context-pending-{index}",
                },
                "createdByAgent": "content-extraction-agent",
            },
        )
    task = {
        "taskId": "stagetask-memory-context-approved-action",
        "runId": run_id,
        "stageId": "ingestion",
        "agentId": "agent-source-ingestor",
        "agentRole": "source_ingestor",
        "sessionId": "session-ingestor",
        "status": "running",
        "title": "资料入库任务",
        "writebackContract": {
            "taskId": "stagetask-memory-context-approved-action",
            "writesFormalKnowledge": True,
            "writesOfficialGraph": True,
        },
    }
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(team["teamId"], run_id, task)

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id="stagetask-memory-context-approved-action",
        candidate_limit=80,
    )

    action_packet = context["stewardActionPacket"]
    assert action_packet["action"] == "writeback_approved_candidates"
    assert action_packet["approvedCandidateIds"] == [approved["candidateId"]]
    assert action_packet["deferredCandidateCounts"]["pending"] == 14
    assert action_packet["doNotInferHiddenOrTruncatedCandidates"] is True
    assert action_packet["writebackResultSkeleton"]["approvedCandidateIds"] == [approved["candidateId"]]
    assert context["fieldMode"] == "evidence_source"
    assert context["candidateFieldsTruncated"] is False
    assert context["doNotUsePreviewAsEvidence"] is False
    assert context["candidates"][0]["evidenceRefs"] == [
        {
            "type": "doi",
            "id": "10.0000/steward-context-approved",
            "label": "Predictive coding cortical hierarchy neural network paper",
        }
    ]
    assert "summaryPreview" not in context["candidates"][0]
    assert context["candidates"] == [
        item for item in context["candidates"] if item["qualityBucket"] == "approved"
    ]
    assert pending_marker not in json.dumps(context, ensure_ascii=False)

def test_source_collection_stage_session_task_writeback_records_structured_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_source_collection_search_background(monkeypatch)
    discovery = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=discovery["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": discovery["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    stage_response = team_workflow_orchestration_service.start_research_stage_round(
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
            "turnId": "turn-stage-task",
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
            "status": "completed",
            "summary": "已完成第一轮资料搜索，建议进入资料提炼。",
            "result": {"recordCount": 3, "candidateCount": 2},
            "evidenceRefs": [{"kind": "run", "ref": run_id}],
            "nextActions": ["进入资料提炼"],
        },
    )

    assert result["task"]["status"] == "needs_review"
    assert result["task"]["result"]["recordCount"] == 3
    assert result["task"]["result"]["closureSummary"]["artifactComplete"] is False
    assert result["task"]["result"]["closureSummary"]["completionGatePassed"] is False
    assert "没有生成可用" in result["task"]["result"]["closureSummary"]["message"]
    assert result["task"]["writesFormalKnowledge"] is False
    assert result["task"]["writesRag"] is False
    assert result["writeback"]["status"] == "needs_review"
    assert result["boundaries"]["writesFormalKnowledge"] is False
    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    latest_round = status_payload["latestRound"]
    stage_results = latest_round.get("sourceCollectionStageSessionTasks", [])
    assert any(item["taskId"] == task["taskId"] and item["status"] == "needs_review" for item in stage_results)

def test_source_collection_writeback_recovers_fenced_structured_result_text(tmp_path, monkeypatch):
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
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding fenced result candidate",
            "sourceUrl": "https://doi.org/10.0000/fenced-result-candidate",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence for fenced result recovery.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/fenced-result-candidate"},
            "createdByAgent": agent["agentId"],
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-fenced-result", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])
    structured_result = {
        "candidateExtractions": [
            {
                "candidateId": candidate["candidateId"],
                "status": "extracted",
                "summary": "预测编码候选已从围栏 JSON 恢复。",
            }
        ],
        "candidateDecisions": [{"candidateId": candidate["candidateId"], "decision": "keep"}],
    }

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "围栏 JSON 结构化回写。",
            "result": {
                "text": "Agent output:\n```json\n"
                + json.dumps(structured_result, ensure_ascii=False)
                + "\n```\nEnd.",
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["status"] == "completed"
    assert response["writeback"]["coverageSummary"]["processed"] == 1
    assert response["writeback"]["coverageSummary"]["missing"] == 0
    assert response["task"]["result"]["_structuredResultRecoveredFrom"] == "text"

def test_knowledge_steward_memory_writeback_auto_ingests_real_steward_pack_shape(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    ingestor = agent_directory_service.create_agent_instance(display_name="资料入库")
    ingestor_session = session_service.ensure_agent_direct_session(
        agent_id=ingestor["agentId"],
        title="资料入库",
    )
    agent_directory_service.update_agent_instance(ingestor["agentId"], direct_session_id=ingestor_session["id"])
    coordinator = agent_directory_service.create_agent_instance(display_name="科研协调")
    session_service.ensure_agent_direct_session(agent_id=coordinator["agentId"], title="科研协调")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {"agentId": coordinator["agentId"], "role": "research_coordination", "agentName": "科研协调"},
            {"agentId": ingestor["agentId"], "role": "source_ingestor", "agentName": "资料入库"},
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
            "topic": "神经预测编码",
            "agentRoles": ["source_ingestor"],
            "agentIds": {"source_ingestor": ingestor["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy DOI source",
            "sourceUrl": "https://doi.org/10.0000/real-steward-pack-shape",
            "sourceKind": "paper",
            "summary": "Traceable predictive coding source with DOI metadata.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/real-steward-pack-shape"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": "source-quality-agent",
            "decision": "approved",
            "notes": "主题相关、来源可追踪，允许知识库管理员入库。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/real-steward-pack-shape"}],
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-real-pack", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor["agentId"], "agentRole": "source_ingestor"},
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "知识库管理员审核通过，批准本轮候选直接入库。",
            "result": {
                "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
                "stewardPackDraft": {
                    "approvedCandidateIds": [source["candidateId"]],
                    "targetDomain": "神经机制启发神经网络算法",
                    "proposalPayload": {
                        "title": source["title"],
                        "summary": "将已通过质检的预测编码 DOI 资料写入团队知识库。",
                    },
                    "candidate_summary": {
                        "approved": {
                            "count": 1,
                            "candidates": [
                                {
                                    "candidateId": source["candidateId"],
                                    "title": source["title"],
                                    "overall_score": 72,
                                    "relevance_score": 98,
                                    "assessment_notes": "来源可追踪且与挑战杯神经算法方向高度相关。",
                                }
                            ],
                        }
                    },
                },
                "autoIngestDecision": {
                    "decision": "approved_for_ingestion",
                    "reason": "候选已通过资料质检，知识库管理员批准直接入库。",
                    "approvedCandidates": [{"candidateId": source["candidateId"], "title": source["title"]}],
                },
            },
            "recordedByAgent": ingestor["agentId"],
            "evidenceRefs": [{"type": "candidate", "id": source["candidateId"]}],
            "nextActions": ["进入实验规划"],
        },
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]

    assert materialized["status"] == "completed"
    assert materialized["approvedCandidateIds"] == [source["candidateId"]]
    assert materialized["formalKnowledgeItemCount"] == 1
    assert materialized["writesFormalKnowledge"] is True

    knowledge_items = team_knowledge_service.list_knowledge_items(
        materialized["knowledgeBaseId"],
        agent_id=ingestor["agentId"],
    )
    assert knowledge_items["summary"]["itemCount"] == 1

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
            "createdByAgent": "Source Finder Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {"assessedByAgent": "Source Extractor Agent"},
    )
    graph_response = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {"createdByAgent": "Source Relation Mapper Agent", "curationMode": "agent_approved_only"},
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
