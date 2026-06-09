from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import team_workflows
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


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)


def test_team_workflow_routes_run_candidate_transfer_slice(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    workflow_response = client.put(
        f"/api/teams/{team['teamId']}/workflow-orchestration",
        json={"workflowKind": "challenge_cup_research", "ownerAgentId": "Research Coordination Agent"},
    )
    candidate_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source",
        json={"title": "Neurology paper", "sourceKind": "paper", "createdByAgent": "Knowledge Collection Agent"},
    )
    transfer_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers",
        json={
            "candidateId": candidate_response.json()["candidate"]["candidateId"],
            "fromNode": "knowledge_collection",
            "toNode": "source_screening",
            "requestedByAgent": "Knowledge Collection Agent",
        },
    )
    decision_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers/{transfer_response.json()['transfer']['transferId']}/decide",
        json={"decision": "approved", "decidedByAgent": "Research Coordination Agent", "targetState": "screening_ready"},
    )

    assert workflow_response.status_code == 200, workflow_response.text
    assert workflow_response.json()["workflowKind"] == "challenge_cup_research"
    assert candidate_response.status_code == 201, candidate_response.text
    assert transfer_response.status_code == 201, transfer_response.text
    assert transfer_response.json()["transfer"]["requiresUserConfirmation"] is False
    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["transfer"]["decidedByAgent"] == "Research Coordination Agent"
    assert decision_response.json()["candidate"]["currentWorkflowNode"] == "source_screening"


def test_team_workflow_route_imports_data_record_as_source_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    run = client.post("/api/data-processing/runs", json={"title": "Source collection"}).json()
    record = client.post(
        f"/api/data-processing/runs/{run['runId']}/records",
        json={
            "sourceType": "url",
            "sourceRef": "https://example.test/source",
            "title": "Imported source",
            "metadata": {"allowedForAnalysis": True},
        },
    ).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/data-processing/runs/{run['runId']}/records/{record['recordId']}/source-candidate",
        json={"createdByAgent": "data_intake_coordinator", "tags": ["source"]},
    )
    duplicate_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/data-processing/runs/{run['runId']}/records/{record['recordId']}/source-candidate",
        json={"createdByAgent": "data_intake_coordinator"},
    )
    list_response = client.get(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates",
        params={"candidateType": "source_manifest"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["created"] is True
    assert response.json()["candidate"]["sourceUrl"] == "https://example.test/source"
    assert response.json()["candidate"]["metadata"]["importedFromDataRecord"]["recordId"] == record["recordId"]
    assert duplicate_response.status_code == 201, duplicate_response.text
    assert duplicate_response.json()["created"] is False
    assert duplicate_response.json()["candidate"]["candidateId"] == response.json()["candidate"]["candidateId"]
    assert list_response.json()["candidateCount"] == 1


def test_team_workflow_route_starts_source_collection_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/source-collection-runs",
        json={
            "title": "Neurology source batch",
            "topic": "neural gating",
            "requestedByAgent": "Research Coordination Agent",
            "agentRoles": ["data_discovery", "source_acquisition"],
            "inputRefs": ["seed-query:neural gating"],
            "querySeeds": ["thalamic gating"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 5,
        },
    )
    run_id = response.json()["run"]["runId"]
    assignments_response = client.get(f"/api/data-processing/runs/{run_id}/collection-assignments")
    status_response = client.get(f"/api/data-processing/runs/{run_id}/status")

    assert response.status_code == 201, response.text
    assert response.json()["assignmentCount"] == 2
    assert response.json()["searchPlan"]["querySeeds"] == ["thalamic gating", "neural gating"]
    assert response.json()["searchPlan"]["queryCount"] == 2
    assert response.json()["searchPlan"]["boundaries"]["externalSearchTriggered"] is False
    assert response.json()["searchPlan"]["resultWritebackContract"]["ragWrites"] is False
    assert {item["agentRole"] for item in response.json()["assignments"]} == {"data_discovery", "source_acquisition"}
    assert all(item["scope"]["assignedQueries"] for item in response.json()["assignments"])
    assert response.json()["workflow"]["activeWorkflowItems"][0]["candidateId"] == run_id
    assert assignments_response.json()["summary"]["assignmentCount"] == 2
    assert status_response.json()["boundaries"]["writesFormalKnowledge"] is False


def test_team_workflow_route_starts_research_stage_round(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "ai科学研究团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/stage-rounds/start",
        json={
            "stageType": "knowledge_collection",
            "topic": "predictive coding",
            "querySeeds": ["cortical predictive coding"],
            "agentRoles": ["data_discovery", "source_quality"],
        },
    )
    status_response = client.get(f"/api/teams/{team['teamId']}/workflow-orchestration/stage-rounds/status")

    assert response.status_code == 201, response.text
    assert response.json()["created"] is True
    assert response.json()["stageRound"]["status"] == "running"
    assert response.json()["stageRound"]["sourceRunIds"] == [response.json()["run"]["runId"]]
    assert response.json()["stageRound"]["teamMemoryRecord"]["recordKind"] == "team_workflow_stage_record"
    assert response.json()["stageRound"]["coordinationContract"]["autoStarted"] is False
    assert response.json()["searchPlan"]["boundaries"]["externalSearchTriggered"] is False
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["phases"][0]["activeRoundId"] == response.json()["stageRound"]["stageRoundId"]
    assert status_response.json()["boundaries"]["writesFormalKnowledge"] is False


def test_team_workflow_route_blocks_non_owner_transfer_decision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    client.put(
        f"/api/teams/{team['teamId']}/workflow-orchestration",
        json={"workflowKind": "challenge_cup_research", "ownerAgentId": "Research Coordination Agent"},
    )
    candidate = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source",
        json={"title": "Neurology paper", "createdByAgent": "Knowledge Collection Agent"},
    ).json()["candidate"]
    transfer = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers",
        json={
            "candidateId": candidate["candidateId"],
            "fromNode": "knowledge_collection",
            "toNode": "source_screening",
            "requestedByAgent": "Knowledge Collection Agent",
        },
    ).json()["transfer"]

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers/{transfer['transferId']}/decide",
        json={"decision": "approved", "decidedByAgent": "Knowledge Collection Agent"},
    )

    assert response.status_code == 422
    assert "Only the workflow owner agent" in response.json()["detail"]


def test_team_workflow_route_rejected_transfer_archives_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    client.put(
        f"/api/teams/{team['teamId']}/workflow-orchestration",
        json={"workflowKind": "challenge_cup_research", "ownerAgentId": "Research Coordination Agent"},
    )
    candidate = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source",
        json={
            "title": "Unsupported routing analogy",
            "sourceUrl": "https://example.test/rejected",
            "sourceKind": "paper",
            "createdByAgent": "Evidence Review Agent",
        },
    ).json()["candidate"]
    transfer = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers",
        json={
            "candidateId": candidate["candidateId"],
            "fromNode": "research_review",
            "toNode": "rejection_archive",
            "requestedByAgent": "Evidence Review Agent",
            "reason": "Evidence review rejected this analogy.",
        },
    ).json()["transfer"]

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/transfers/{transfer['transferId']}/decide",
        json={
            "decision": "rejected",
            "decidedByAgent": "Research Coordination Agent",
            "decisionNote": "Archive until a review gate gives a reopen reason.",
        },
    )
    graph_response = client.post(f"/api/teams/{team['teamId']}/workflow-orchestration/candidate-graph", json={})

    assert response.status_code == 200, response.text
    assert response.json()["candidate"]["currentWorkflowNode"] == "rejection_archive"
    assert response.json()["candidate"]["currentState"] == "rejected"
    assert response.json()["candidate"]["metadata"]["rejectionArchive"]["reopenRequiresTransfer"] is True
    assert graph_response.status_code == 201, graph_response.text
    assert graph_response.json()["graph"]["summary"]["archivedCandidateCount"] == 1
    assert candidate["candidateId"] not in {
        node["candidateId"] for node in graph_response.json()["graph"]["nodes"]
    }


def test_team_workflow_routes_build_and_record_local_research_model_output(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    task_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/tasks",
        json={
            "taskType": "neuro_mechanism_extract",
            "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
            "evidenceRefs": [{"type": "page", "id": "p5", "label": "page 5"}],
            "excerpt": "The study reports a mechanism.",
            "createdByAgent": "Neuro Mechanism Extraction Agent",
        },
    )
    output_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "neuro_mechanism_extract",
            "title": "Mechanism draft",
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
                "uncertainty": ["terminology may need review"],
                "riskFlags": ["terminology_uncertain"],
                "confidence": 0.61,
                "nextAction": "send_to_mapping",
                "requiresReview": True,
            },
        },
    )

    assert task_response.status_code == 201, task_response.text
    assert task_response.json()["task"]["taskType"] == "neuro_mechanism_extract"
    assert task_response.json()["task"]["model"]["contextWindow"] == 32000
    assert output_response.status_code == 201, output_response.text
    assert output_response.json()["validation"]["valid"] is True
    assert output_response.json()["candidate"]["currentWorkflowNode"] == "neuro_mechanism"
    assert output_response.json()["candidate"]["currentState"] == "mechanism_candidate"


def test_team_workflow_routes_list_and_validate_candidate_store(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    candidate_response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source",
        json={
            "title": "Incomplete PDF",
            "sourcePath": "C:/papers/neuro.pdf",
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    )
    list_response = client.get(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates",
        params={"candidateType": "source_manifest"},
    )
    validation_response = client.get(f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/validation")

    assert candidate_response.status_code == 201, candidate_response.text
    assert candidate_response.json()["validation"]["valid"] is False
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["candidateCount"] == 1
    assert list_response.json()["candidates"][0]["currentState"] == "source_needs_confirmation"
    assert validation_response.status_code == 200, validation_response.text
    assert validation_response.json()["summary"]["invalidCandidateCount"] == 1
    assert validation_response.json()["summary"]["errorCount"] >= 2


def test_team_workflow_route_returns_knowledge_ingestion_status(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_status(team_id):
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "workflowId": "challenge-cup-research-flow",
            "workflowKind": "challenge_cup_research",
            "status": "needs_review",
            "summary": {
                "candidateCount": 2,
                "pendingProposalCount": 1,
                "formalKnowledgeItemCount": 0,
                "actionItemCount": 1,
            },
            "stages": [{"stageId": "knowledge_review", "status": "needs_review"}],
            "actionItems": [{"code": "knowledge_proposal_pending_review", "severity": "needs_review"}],
            "officialBoundary": {
                "candidateGraphWritesOfficialGraph": False,
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
            },
            "knowledgeBases": [],
        }

    monkeypatch.setattr(team_workflows, "get_knowledge_ingestion_status", fake_status)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.get(f"/api/teams/{team['teamId']}/workflow-orchestration/knowledge-ingestion/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["teamId"] == team["teamId"]
    assert payload["status"] == "needs_review"
    assert payload["summary"]["pendingProposalCount"] == 1
    assert payload["actionItems"][0]["code"] == "knowledge_proposal_pending_review"
    assert payload["officialBoundary"]["candidateGraphWritesOfficialGraph"] is False


def test_team_workflow_route_returns_coordination_status(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_status(team_id):
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "workflowId": "challenge-cup-research-flow",
            "workflowKind": "challenge_cup_research",
            "status": "needs_transfer_decision",
            "ownerAgentId": "Research Coordination Agent",
            "summary": {
                "candidateCount": 2,
                "activeCandidateCount": 2,
                "pendingTransferCount": 1,
                "reworkCandidateCount": 0,
                "blockedCandidateCount": 0,
                "actionItemCount": 1,
            },
            "queues": {
                "pendingTransfers": [
                    {
                        "candidateId": "candidate-1",
                        "transferId": "transfer-1",
                        "communicationBrief": {"targetAgentRole": "Research Coordination Agent", "autoSendEnabled": False},
                    }
                ],
                "needsRework": [],
                "stewardship": [],
                "blocked": [],
                "active": [],
            },
            "actionItems": [{"code": "transfer_decision_pending", "severity": "needs_review"}],
            "communication": {
                "briefCount": 1,
                "readOnly": True,
                "autoSendEnabled": False,
                "recommendedSender": "Research Coordination Agent",
            },
            "coordinationPolicy": {
                "coordinationAgentId": "Research Coordination Agent",
                "requiresUserConfirmation": False,
                "autoTransferEnabled": False,
            },
        }

    monkeypatch.setattr(team_workflows, "get_team_workflow_coordination_status", fake_status)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.get(f"/api/teams/{team['teamId']}/workflow-orchestration/coordination/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["teamId"] == team["teamId"]
    assert payload["status"] == "needs_transfer_decision"
    assert payload["summary"]["pendingTransferCount"] == 1
    assert payload["queues"]["pendingTransfers"][0]["transferId"] == "transfer-1"
    assert payload["queues"]["pendingTransfers"][0]["communicationBrief"]["autoSendEnabled"] is False
    assert payload["communication"]["briefCount"] == 1
    assert payload["coordinationPolicy"]["autoTransferEnabled"] is False


def test_team_workflow_routes_extract_candidate_source_pages(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    source_path = tmp_path / "sources" / "neuro.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"%PDF-1.4\nfake local pdf bytes\n")

    def fake_extract(path, *, page_scope, max_pages, max_chars_per_page):
        assert path == source_path
        assert page_scope == "2"
        return [{"type": "pdf_page", "id": "neuro-p2", "label": "p. 2", "page": 2, "text": "Route extracted page text."}]

    monkeypatch.setattr(team_workflow_orchestration_service, "_extract_pdf_page_anchors", fake_extract)
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    candidate = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source",
        json={
            "title": "Local PDF",
            "sourcePath": str(source_path),
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    ).json()["candidate"]

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/{candidate['candidateId']}/source-extraction",
        json={
            "createdByAgent": "Source Extraction Agent",
            "allowedForAnalysis": True,
            "pageScope": "2",
            "maxPages": 1,
            "maxCharsPerPage": 400,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["validation"]["valid"] is True
    assert payload["candidate"]["currentState"] == "source_registered"
    assert payload["sourceExtraction"]["status"] == "extracted"
    assert payload["sourceExtraction"]["pageAnchors"][0]["page"] == 2
    assert payload["workflow"]["candidateStore"]["candidateCount"] == 1


def test_team_workflow_routes_reject_paper_note_without_citation_anchor(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "paper_note_draft",
            "title": "Paper note missing citation",
            "createdByAgent": "Paper Note Extraction Agent",
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

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is False
    assert response.json()["candidate"]["currentState"] == "paper_note_needs_revision"
    assert {issue["code"] for issue in response.json()["validation"]["issues"]} >= {
        "missing_key_finding_citation",
        "missing_citation_anchor",
    }


def test_team_workflow_routes_reject_neuro_mechanism_uncertain_terms_without_flag(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "neuro_mechanism_extract",
            "title": "Mechanism with uncertain terms",
            "createdByAgent": "Neuro Mechanism Extraction Agent",
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

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is False
    assert response.json()["candidate"]["currentState"] == "mechanism_needs_revision"
    assert {issue["code"] for issue in response.json()["validation"]["issues"]} >= {"terminology_uncertain_not_flagged"}


def test_team_workflow_routes_record_mechanism_mapping_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "mechanism_mapping",
            "title": "Mechanism mapping draft",
            "createdByAgent": "Mechanism Mapping Agent",
            "output": {
                "candidateType": "mechanism_mapping",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "page", "id": "p8", "label": "page 8"}],
                "claims": [{"claim": "Candidate computational abstraction", "sourceRef": "paper-1"}],
                "neuroMechanismIds": ["mechanism-1"],
                "computationalAbstraction": "context-gated dynamic routing",
                "factLayer": ["The paper reports context-dependent modulation."],
                "inferenceLayer": ["The project treats modulation as a routing analogy."],
                "overAnalogyRisk": "low",
                "engineeringImplication": "Use context signals to alter routing weights.",
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.57,
                "nextAction": "send_to_algorithm_hypothesis",
                "requiresReview": True,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is True
    assert response.json()["candidate"]["currentWorkflowNode"] == "mechanism_mapping"
    assert response.json()["candidate"]["currentState"] == "mechanism_mapping_candidate"


def test_team_workflow_routes_record_algorithm_hypothesis_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "algorithm_hypothesis_draft",
            "title": "Algorithm hypothesis draft",
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
                "confidence": 0.53,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is True
    assert response.json()["candidate"]["currentWorkflowNode"] == "algorithm_hypothesis"
    assert response.json()["candidate"]["currentState"] == "hypothesis_candidate"


def test_team_workflow_routes_build_candidate_graph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()
    client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "algorithm_hypothesis_draft",
            "title": "Algorithm hypothesis draft",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "missing-mapping", "label": "Missing mapping"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["missing-mapping"],
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
                "requiresReview": True,
            },
        },
    )

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidate-graph",
        json={"title": "Candidate graph preview", "createdByAgent": "Candidate Graph Preview Agent"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["candidateGraph"]["currentState"] == "candidate_graph_visible"
    assert response.json()["candidateGraph"]["qualityStatus"] == "broken_links"
    assert response.json()["graph"]["officialBoundary"]["writesOfficialKnowledge"] is False
    assert response.json()["graph"]["summary"]["missingLinkCount"] == 1
    assert response.json()["workflow"]["candidateStore"]["candidateCount"] == 2


def test_team_workflow_routes_record_review_prefilter(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "review_prefilter",
            "title": "Review prefilter",
            "createdByAgent": "Evidence Review Agent",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "hypothesis", "id": "hypothesis-1", "label": "Hypothesis 1"}],
                "claims": [{"claim": "Candidate has a testable plan.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1"],
                "checklist": [{"item": "experiment plan", "status": "pass"}],
                "comments": "Prefilter only; send to human review gate.",
                "requiredChanges": [],
                "needsDecision": True,
                "uncertainty": [],
                "riskFlags": ["needs_human_decision"],
                "confidence": 0.66,
                "nextAction": "request_review_decision",
                "requiresReview": True,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is True
    assert response.json()["candidate"]["candidateType"] == "review_record"
    assert response.json()["candidate"]["currentWorkflowNode"] == "research_review"
    assert response.json()["candidate"]["currentState"] == "review_prefiltered"


def test_team_workflow_routes_record_steward_pack_draft(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": "Knowledge Steward Agent",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"]},
                "riskSummary": "Evidence is traceable; official ingestion still requires approval.",
                "proposalPayload": {"proposalType": "refinement_proposal", "summary": "Governed research candidate."},
                "ratingSuggestion": {"rating": "reviewable", "reason": "Needs approval."},
                "approvalRequired": True,
                "uncertainty": [],
                "riskFlags": ["approval_required"],
                "confidence": 0.62,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["validation"]["valid"] is True
    assert response.json()["candidate"]["currentWorkflowNode"] == "steward_ingestion"
    assert response.json()["candidate"]["currentState"] == "steward_pack_draft"


def test_team_workflow_routes_submit_steward_pack_to_knowledge_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = client.post(
        "/api/teams",
        json={
            "name": "挑战杯科研团队",
            "members": [{"agentId": steward["agentId"], "role": "steward"}],
        },
    ).json()
    knowledge_base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Challenge Cup Governed Knowledge", "actorAgentId": steward["agentId"]},
    ).json()
    candidate = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": steward["agentId"],
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"]},
                "riskSummary": "Evidence is traceable; official ingestion still requires approval.",
                "proposalPayload": {"title": "Governed research candidate", "summary": "Governed research candidate."},
                "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.62, "stability": "evolving", "reviewPriority": "elevated"},
                "approvalRequired": True,
                "uncertainty": [],
                "riskFlags": ["approval_required"],
                "confidence": 0.62,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    ).json()["candidate"]

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/steward-packs/{candidate['candidateId']}/knowledge-ingestion",
        json={
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
        },
    )
    items_response = client.get(
        f"/api/knowledge-bases/{knowledge_base['knowledgeBaseId']}/items",
        params={"agentId": steward["agentId"]},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["candidate"]["currentState"] == "steward_pending_knowledge_review"
    assert payload["knowledgeIngestion"]["package"]["proposal"]["status"] == "pending"
    assert payload["knowledgeIngestion"]["officialBoundary"]["writesOfficialKnowledge"] is False
    assert payload["knowledgeIngestion"]["officialBoundary"]["writesOfficialGraph"] is False
    assert payload["knowledgeIngestion"]["ratingSuggestion"]["status"] == "pending"
    assert items_response.json()["summary"]["itemCount"] == 0


def test_team_workflow_routes_review_steward_pack_knowledge_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward Agent")
    team = client.post(
        "/api/teams",
        json={
            "name": "挑战杯科研团队",
            "members": [{"agentId": steward["agentId"], "role": "steward"}],
        },
    ).json()
    knowledge_base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Challenge Cup Governed Knowledge", "actorAgentId": steward["agentId"]},
    ).json()
    candidate = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/outputs",
        json={
            "taskType": "steward_pack_draft",
            "title": "Steward ingestion pack draft",
            "createdByAgent": steward["agentId"],
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
                "claims": [{"claim": "Candidate is ready for governance.", "sourceRef": "paper-1"}],
                "candidateIds": ["hypothesis-1", "review-1"],
                "targetDomain": "challenge_cup_neuro_algorithm",
                "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"]},
                "riskSummary": "Evidence is traceable; approval can create formal knowledge.",
                "proposalPayload": {"title": "Approved research candidate", "summary": "Approved research candidate."},
                "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.7, "stability": "evolving", "reviewPriority": "elevated"},
                "approvalRequired": True,
                "uncertainty": [],
                "riskFlags": ["approval_required"],
                "confidence": 0.7,
                "nextAction": "send_to_ingestion_approval_gate",
                "requiresReview": True,
            },
        },
    ).json()["candidate"]
    pending = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/steward-packs/{candidate['candidateId']}/knowledge-ingestion",
        json={
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "proposedByAgentId": steward["agentId"],
        },
    ).json()["candidate"]

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/steward-packs/{pending['candidateId']}/knowledge-ingestion/review",
        json={
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "reviewedByAgentId": steward["agentId"],
            "decision": "approved",
            "resolutionNote": "Approved for official sync.",
        },
    )
    items_response = client.get(
        f"/api/knowledge-bases/{knowledge_base['knowledgeBaseId']}/items",
        params={"agentId": steward["agentId"]},
    )
    rating_suggestions_response = client.get(
        f"/api/knowledge-bases/{knowledge_base['knowledgeBaseId']}/rating-suggestions",
        params={"agentId": steward["agentId"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    official_record = payload["candidate"]["metadata"]["officialSyncRecord"]
    rating_migration = payload["knowledgeIngestion"]["officialSyncRecord"]["ratingSuggestionMigration"]
    official_graph = payload["knowledgeIngestion"]["officialSyncRecord"]["officialResearchGraph"]
    migrated_target = next(
        item
        for item in rating_suggestions_response.json()["suggestions"]
        if item["suggestionId"] == rating_migration["targetSuggestionId"]
    )
    assert payload["candidate"]["currentState"] == "official_synced"
    assert payload["candidate"]["qualityStatus"] == "approved"
    assert payload["knowledgeIngestion"]["review"]["proposal"]["status"] == "applied"
    assert payload["knowledgeIngestion"]["review"]["item"]["knowledgeItemId"] in official_record["knowledgeItemIds"]
    assert official_record["writesOfficialKnowledge"] is True
    assert official_record["writesOfficialRag"] is False
    assert official_record["writesOfficialGraph"] is True
    assert official_graph["status"] == "synced"
    assert any(edge["relation"] == "approved_for_ingestion" for edge in official_graph["edges"])
    assert rating_migration["status"] == "migrated"
    assert migrated_target["targetType"] == "knowledge_item"
    assert migrated_target["status"] == "pending"
    assert items_response.json()["summary"]["itemCount"] == 1


def test_team_workflow_route_invokes_local_research_model(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_invoke(team_id, payload):
        return {
            "task": {"teamId": team_id, "taskType": payload["taskType"]},
            "candidate": {"candidateId": "local-model-output-1", "candidateType": "paper_note"},
            "validation": {"valid": True, "issues": []},
            "modelResponse": {"modelId": "houmo_qwen35_9b_agent", "jsonSource": "content"},
            "workflow": {"teamId": team_id, "candidateStore": {"candidateCount": 1}},
        }

    monkeypatch.setattr(team_workflows, "invoke_local_research_model", fake_invoke)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/local-research-model/invoke",
        json={
            "taskType": "paper_note_draft",
            "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
            "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
            "excerpt": "A short source excerpt.",
            "createdByAgent": "Paper Note Extraction Agent",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["task"]["taskType"] == "paper_note_draft"
    assert response.json()["modelResponse"]["modelId"] == "houmo_qwen35_9b_agent"


def test_team_workflow_route_autodrafts_paper_note_from_source_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_autodraft(team_id, candidate_id, payload):
        return {
            "task": {"teamId": team_id, "taskType": "paper_note_draft"},
            "sourceCandidate": {"candidateId": candidate_id, "candidateType": "source_manifest"},
            "candidate": {"candidateId": "paper-note-1", "candidateType": "paper_note"},
            "validation": {"valid": True, "issues": []},
            "modelResponse": {"modelId": "houmo_qwen35_9b_agent", "jsonSource": "content"},
            "workflow": {"teamId": team_id, "candidateStore": {"candidateCount": 2}},
        }

    monkeypatch.setattr(team_workflows, "draft_paper_note_from_source_candidate", fake_autodraft)
    client = _client()
    team = client.post("/api/teams", json={"name": "挑战杯科研团队"}).json()

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/candidates/source-1/paper-note-draft",
        json={
            "createdByAgent": "Paper Note Extraction Agent",
            "title": "Paper note draft",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["sourceCandidate"]["candidateId"] == "source-1"
    assert response.json()["candidate"]["candidateType"] == "paper_note"
    assert response.json()["workflow"]["candidateStore"]["candidateCount"] == 2
