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
    assert official_record["writesOfficialGraph"] is False
    assert official_record["ragStatus"] == "queryable_via_reviewed_team_knowledge"
    assert official_record["graphStatus"] == "visible_via_memory_knowledge_graph"
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
    assert official_record["ragStatus"] == "not_synced"
    assert official_record["graphStatus"] == "not_synced"
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
