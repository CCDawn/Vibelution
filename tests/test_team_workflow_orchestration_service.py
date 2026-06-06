from core.web.services import (
    agent_directory_service,
    chat_room_service,
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

    def invoke(self, messages, metadata=None):
        type(self).captured_messages.append({"messages": messages, "metadata": metadata, "profile_id": self.profile_id})
        return type(self).response


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)


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
    assert status["queues"]["pendingTransfers"][0]["candidateId"] == source["candidateId"]
    assert status["queues"]["needsRework"][0]["candidateId"] == rework["candidateId"]
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

    response = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        candidate["candidateId"],
        {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
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
    pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        candidate["candidateId"],
        {"knowledgeBaseId": knowledge_base["knowledgeBaseId"], "proposedByAgentId": steward["agentId"]},
    )["candidate"]

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

    pending_candidate = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        steward_candidate["candidateId"],
        {"knowledgeBaseId": knowledge_base["knowledgeBaseId"], "proposedByAgentId": steward["agentId"]},
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
    pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team["teamId"],
        candidate["candidateId"],
        {"knowledgeBaseId": knowledge_base["knowledgeBaseId"], "proposedByAgentId": steward["agentId"]},
    )["candidate"]

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
        assert "Only steward_pack_draft candidates" in str(exc)
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
