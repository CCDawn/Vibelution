from __future__ import annotations

from tests._support.team_workflow.helpers import *  # noqa: F403

def test_challenge_cup_team_agents_purge_unregistered_source_role_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    legacy_agent = agent_directory_service.create_agent_instance(
        display_name="旧资料发现",
        created_by=team_service.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
        role_key="unsupported_source_role",
        metadata={
            "challengeCupTeamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
            "challengeCupTeamManagedVersion": 1,
            "challengeCupTeamRole": "unsupported_source_role",
            "challengeCupTeamRoleKey": "unsupported_source_role",
        },
    )

    result = team_service.ensure_challenge_cup_research_team_agents(purge_stale=True)
    roles = {member["role"] for member in result["team"]["members"]}

    assert legacy_agent["agentId"] in result["purgedAgentIds"]
    assert agent_directory_service.get_agent(legacy_agent["agentId"], include_archived=True) is None
    assert {"source_finder", "source_extractor", "source_relation_mapper", "source_ingestor"} <= roles
    assert "unsupported_source_role" not in roles

def test_source_relation_task_keeps_extraction_evidence_when_model_requests_minimal_context(tmp_path, monkeypatch):
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
            "topic": "预测编码资料关系",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["predictive coding relations"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding evidence candidate",
            "sourceUrl": "https://doi.org/10.0000/relation-evidence",
            "sourceKind": "paper",
            "summary": "Predictive coding hierarchy supports relation mapping.",
            "allowedForAnalysis": True,
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/relation-evidence",
                "contentExtraction": {
                    "status": "extracted",
                    "decision": "keep",
                    "summary": "层级预测误差支持跨层关系。",
                    "evidenceStatus": "evidence_ready",
                    "evidenceRefs": [{"type": "doi", "id": "10.0000/relation-evidence"}],
                    "evidenceLedger": {
                        "status": "evidence_ready",
                        "evidenceRefs": [{"type": "doi", "id": "10.0000/relation-evidence"}],
                    },
                },
            },
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-relation-evidence-context",
            "status": "running",
        },
    )

    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )
    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        candidate_limit=5,
        context_mode="minimal",
    )

    assert task["task"]["sourceContextMode"] == "evidence"
    assert context["contextMode"] == "evidence"
    relation_candidate = next(item for item in context["candidates"] if item["candidateId"] == candidate["candidateId"])
    assert relation_candidate["contentExtraction"]["decision"] == "keep"
    assert relation_candidate["contentExtraction"]["evidenceStatus"] == "evidence_ready"
    assert relation_candidate["contentExtraction"]["evidenceRefs"] == [
        {"type": "doi", "id": "10.0000/relation-evidence"}
    ]

def test_content_extraction_writeback_downgrades_unanchored_evidence_ledger(tmp_path, monkeypatch):
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
            "title": "Predictive coding source missing citation anchor",
            "sourceUrl": "https://doi.org/10.0000/missing-anchor",
            "sourceKind": "paper",
            "summary": "Predictive coding evidence with missing anchor.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/missing-anchor"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-missing-anchor", "status": "running"},
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
            "summary": "错误地把缺少引用锚点的提炼声明为完成。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "decision": "keep",
                        "summary": "预测编码可启发控制结构，但尚未写页码或 citation。",
                        "claims": [{"claim": "Predictive coding supports a hierarchy analogy.", "sourceRef": "source-1"}],
                        "keyFindings": [{"finding": "层级误差可用于控制结构类比。", "sourceRef": "source-1"}],
                        "sourceRefs": [{"type": "doi", "id": "10.0000/missing-anchor", "label": "Missing Anchor Source"}],
                        "evidenceRefs": [
                            {"type": "doi", "id": "10.0000/missing-anchor", "label": "DOI locator only"},
                            {"type": "url", "id": "https://doi.org/10.0000/missing-anchor", "label": "URL locator only"},
                        ],
                    }
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    refreshed = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"][0]
    extraction = refreshed["metadata"]["contentExtraction"]
    assert response["writeback"]["status"] == "needs_review"
    assert response["task"]["status"] == "needs_review"
    assert response["writeback"]["materializedContentExtraction"]["missingEvidenceAnchorCount"] == 1
    assert extraction["evidenceStatus"] == "missing_evidence_anchor"
    assert extraction["evidenceLedger"]["status"] == "missing_evidence_anchor"

def test_content_extraction_writeback_contract_distinguishes_source_locators_from_evidence_anchors():
    contract = team_workflow_orchestration_service._source_collection_stage_task_writeback_contract(
        "team-extraction-contract",
        "run-extraction-contract",
        "task-extraction-contract",
        stage_id="extraction",
        agent_id="extractor-agent",
        agent_role="source_extractor",
    )

    result_contract = contract["resultContract"]
    assert result_contract["acceptedCollections"] == ["candidateExtractions", "recordExtractions"]
    assert result_contract["sourceLocatorFields"] == ["sourceRefs"]
    assert result_contract["evidenceAnchorFields"] == ["evidenceRefs", "claims", "keyFindings", "citations"]
    assert result_contract["locatorOnlyTypes"] == ["doi", "url", "uri", "paper"]
    assert result_contract["locatorOnlySatisfiesEvidenceAnchor"] is False

def test_stage_checklist_accepts_persisted_writeback_recorded_after_interrupted_turn(monkeypatch):
    context_event = SimpleNamespace(
        sequence=1,
        turn_id="turn-delayed-writeback",
        event_type="tool_call",
        payload={
            "toolCall": {
                "name": "source_collection_context_tool",
                "status": "done",
            }
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_stage_conversation_events",
        lambda session_id, **kwargs: [context_event],
    )
    checklist = [
        {
            "id": "read_approved_candidates",
            "order": 1,
            "requiredTool": "source_collection_context_tool",
        },
        {
            "id": "build_candidate_relations",
            "order": 2,
            "requiredTool": "",
        },
        {
            "id": "write_candidate_graph",
            "order": 3,
            "requiredTool": "source_collection_stage_writeback_tool",
        },
        {
            "id": "confirm_graph_materialized",
            "order": 4,
            "requiredTool": "source_collection_stage_writeback_tool",
        },
    ]
    task = {
        "taskId": "stagetask-delayed-writeback",
        "sessionId": "session-delayed-writeback",
        "turn": {"turnId": "turn-delayed-writeback"},
        "checklistBinding": {"mode": "stage_task"},
        "reconciledFromTurn": {
            "status": "interrupted",
            "reconciledAt": "2026-07-16T06:33:59+08:00",
        },
        "writeback": {
            "recordedAt": "2026-07-16T06:34:57+08:00",
            "result": {"candidateGraph": {"nodes": [{"id": "topic:one"}], "edges": []}},
        },
    }

    progress = team_workflow_orchestration_service._source_collection_stage_task_tool_progress_from_trace(
        task,
        checklist,
        artifact_complete=True,
    )

    assert progress["complete"] is True
    assert progress["completedIds"] == [
        "read_approved_candidates",
        "build_candidate_relations",
        "write_candidate_graph",
        "confirm_graph_materialized",
    ]
    assert progress["persistedWritebackAfterTurn"] is True
    assert progress["source"] == "persisted_writeback_after_turn"

    task["writeback"]["recordedAt"] = "2026-07-16T06:32:00+08:00"
    stale_progress = team_workflow_orchestration_service._source_collection_stage_task_tool_progress_from_trace(
        task,
        checklist,
        artifact_complete=True,
    )

    assert stale_progress["complete"] is False
    assert stale_progress["completedIds"] == ["read_approved_candidates"]
    assert stale_progress.get("persistedWritebackAfterTurn") is not True

def test_content_extraction_writeback_reports_no_effect_closure_for_invalid_raw_record_ids(tmp_path, monkeypatch):
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
    for index in range(2):
        data_processing_service.add_record(
            run_id,
            {
                "sourceType": "paper",
                "sourceRef": f"https://doi.org/10.0000/no-effect-{index}",
                "title": f"Raw source {index}",
                "summary": "Raw source for no-effect closure test.",
                "metadata": {"doi": f"10.0000/no-effect-{index}"},
            },
        )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-no-effect", "status": "running"},
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
            "summary": "Agent 误用短 ID 声明完成。",
            "result": {
                "recordExtractions": [
                    {"recordId": "not-in-this-run", "status": "extracted", "summary": "无法匹配当前批次。"}
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["task"]["status"] == "needs_review"
    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 0
    assert response["writeback"]["coverageSummary"]["processed"] == 0
    assert response["writeback"]["coverageSummary"]["invalid"] == 1
    assert response["writeback"]["closureSummary"]["artifactStatus"] == "no_effect"
    assert response["writeback"]["closureSummary"]["userStatus"] == "failed"
    assert "没有生成候选资料" in response["writeback"]["closureSummary"]["message"]
    assert "完整 recordId" in response["writeback"]["closureSummary"]["retryInstruction"]

def test_stage_writeback_result_metadata_preserves_relation_edge_batches():
    result = {
        "sourceThemeEdges": [
            {"candidateId": f"candidate-{index}", "themeId": "T1", "relation": "source_supports_theme"}
            for index in range(34)
        ],
        "topicRelations": [
            {"from": "T1", "to": f"T{index}", "relation": "related_topic"}
            for index in range(30)
        ],
    }

    normalized = team_workflow_orchestration_service._normalize_source_collection_stage_writeback_result_metadata(result)

    assert len(normalized["sourceThemeEdges"]) == 34
    assert len(normalized["topicRelations"]) == 30

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

def test_workflow_overview_uses_lightweight_team_existence(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])

    def fail_full_team_read(team_id):
        raise AssertionError("workflow overview must not hydrate full team detail")

    monkeypatch.setattr(team_workflow_orchestration_service.team_service, "get_team", fail_full_team_read)

    payload = team_workflow_orchestration_service.get_team_workflow_orchestration(team["teamId"])

    assert payload["teamId"] == team["teamId"]
    assert payload["workflowId"]

def test_workflow_overview_does_not_rewrite_existing_workflow(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    workflow_path = team_workflow_orchestration_service._workflow_path(team["teamId"]).resolve()
    real_write_json = team_workflow_orchestration_service._write_json

    def guarded_write_json(path, payload):
        if path.resolve() == workflow_path:
            raise AssertionError("workflow overview GET should not rewrite an existing workflow")
        return real_write_json(path, payload)

    monkeypatch.setattr(team_workflow_orchestration_service, "_write_json", guarded_write_json)

    payload = team_workflow_orchestration_service.get_team_workflow_orchestration(team["teamId"])

    assert payload["teamId"] == team["teamId"]
    assert payload["workflowId"]

def test_team_aggregate_status_views_declare_non_gate_scope(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    payloads = [
        team_workflow_orchestration_service.get_source_quality_status(team["teamId"]),
        team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"]),
        team_workflow_orchestration_service.get_official_model_evidence_status(team["teamId"]),
        team_workflow_orchestration_service.get_team_workflow_coordination_status(team["teamId"]),
    ]

    expected_scope = {
        "kind": "team_aggregate",
        "runId": "",
        "includesHistorical": True,
        "eligibleForPhaseCloseGate": False,
    }
    assert [payload["scope"] for payload in payloads] == [expected_scope] * len(payloads)

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
