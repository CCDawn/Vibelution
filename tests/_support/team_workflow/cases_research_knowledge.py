from __future__ import annotations

from core.web.services.team_workflow import knowledge as _team_workflow_knowledge
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.problem_understanding_artifact_writer import (
    write_problem_understanding_artifact,
)
from tests._support.team_workflow.helpers import *  # noqa: F403


def _patch_knowledge_background_thread_immediate(monkeypatch):
    """Patch knowledge module threading binding so only background workers run inline."""
    real_threading = _team_workflow_knowledge.threading

    class _ImmediateThread:
        def __init__(self, *, target=None, args=(), name="", daemon=None, **_kwargs):
            self._target = target
            self._args = args
            self.name = name

        def start(self):
            self._target(*self._args)

    class _KnowledgeThreadingBinding:
        Thread = _ImmediateThread

        def __getattr__(self, name):
            return getattr(real_threading, name)

    monkeypatch.setattr(_team_workflow_knowledge, "threading", _KnowledgeThreadingBinding())


def test_register_candidate_source_strict_blocks_invalid(tmp_path, monkeypatch):
    """写入口统一校验：缺来源位置的候选——非 strict 隔离写入；strict 硬拦截。envelope 级始终通过。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"], {"title": "No source location note"}
    )
    assert response["candidate"]["currentState"] == "source_needs_confirmation"
    assert response["candidate"]["qualityStatus"] == "source_manifest_invalid"
    assert response["candidate"]["envelopeValidation"]["valid"] is True

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"], {"title": "No source location note"}, strict=True
        )

def test_extract_neuro_mechanism_from_paper_note_links_and_gates(tmp_path, monkeypatch):
    """N-02：从 paper_note 抽取 neuro_mechanism，建 supports 谱系；高置信度 → ready。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    note_id = _register_paper_note(team["teamId"])

    captured = {}

    def fake_invoke(team_id, payload, *, llm_client_factory=None):
        captured["payload"] = payload
        return {
            "candidate": {"candidateId": "mech-1", "candidateType": "neuro_mechanism", "confidence": 0.72},
            "validation": {"valid": True, "issues": []},
            "task": {"taskId": "task-1"},
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "invoke_local_research_model", fake_invoke)
    response = team_workflow_orchestration_service.extract_neuro_mechanism_from_paper_note(
        team["teamId"], {"paperNoteId": note_id}
    )

    assert response["mechanismGate"] == "ready"
    assert captured["payload"]["taskType"] == "neuro_mechanism_extract"
    assert captured["payload"]["paperNoteIds"] == [note_id]
    drafts = response["paperNoteCandidate"]["metadata"]["mechanismDrafts"]
    assert drafts[-1]["candidateId"] == "mech-1"
    assert drafts[-1]["edgeType"] == "supports"

def test_extract_neuro_mechanism_low_confidence_needs_human(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    note_id = _register_paper_note(team["teamId"])
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "invoke_local_research_model",
        lambda team_id, payload, *, llm_client_factory=None: {
            "candidate": {"candidateId": "m2", "candidateType": "neuro_mechanism", "confidence": 0.3},
            "validation": {"valid": True, "issues": []},
            "task": {"taskId": "t2"},
        },
    )
    response = team_workflow_orchestration_service.extract_neuro_mechanism_from_paper_note(
        team["teamId"], {"paperNoteId": note_id}
    )
    assert response["mechanismGate"] == "review_needs_human"

def test_extract_neuro_mechanism_requires_paper_note_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"], {"title": "s", "sourceUrl": "https://example.test/s"}
    )
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.extract_neuro_mechanism_from_paper_note(
            team["teamId"], {"paperNoteId": source["candidate"]["candidateId"]}
        )

def test_map_mechanism_to_abstraction_gates_high_over_analogy(tmp_path, monkeypatch):
    """N-03：映射建 maps_to 谱系；overAnalogyRisk=high → review_needs_human。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    mech_id = _register_typed_candidate(team["teamId"], "neuro_mechanism")

    _mock_local_research_invoke(
        monkeypatch, {"candidateId": "map-1", "candidateType": "mechanism_mapping", "overAnalogyRisk": "medium"}
    )
    res = team_workflow_orchestration_service.map_mechanism_to_abstraction(team["teamId"], {"mechanismId": mech_id})
    assert res["mappingGate"] == "ready"
    assert res["mechanismCandidate"]["metadata"]["mappingDrafts"][-1]["edgeType"] == "maps_to"

    _mock_local_research_invoke(
        monkeypatch, {"candidateId": "map-2", "candidateType": "mechanism_mapping", "overAnalogyRisk": "high"}
    )
    res2 = team_workflow_orchestration_service.map_mechanism_to_abstraction(team["teamId"], {"mechanismId": mech_id})
    assert res2["mappingGate"] == "review_needs_human"

def test_generate_hypothesis_review_ready_and_links(tmp_path, monkeypatch):
    """N-04：从 mechanism_mapping 生成假设，建 inspires 谱系；有效 → review_ready。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    map_id = _register_typed_candidate(team["teamId"], "mechanism_mapping")
    _mock_local_research_invoke(monkeypatch, {"candidateId": "hyp-1", "candidateType": "algorithm_hypothesis"})
    res = team_workflow_orchestration_service.generate_algorithm_hypothesis_from_mechanism_mapping(
        team["teamId"], {"mappingId": map_id}
    )
    assert res["hypothesisGate"] == "review_ready"
    assert res["mappingCandidate"]["metadata"]["hypothesisDrafts"][-1]["edgeType"] == "inspires"

def test_generate_hypothesis_blocks_high_over_analogy_mapping(tmp_path, monkeypatch):
    """N-04 门禁：上游 overAnalogyRisk=high 的 mapping 不得生成假设（须先过 Review Gate）。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    map_id = _register_typed_candidate(team["teamId"], "mechanism_mapping", metadata={"overAnalogyRisk": "high"})
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.generate_algorithm_hypothesis_from_mechanism_mapping(
            team["teamId"], {"mappingId": map_id}
        )

def test_sync_official_research_graph_blocks_candidate_only(tmp_path, monkeypatch):
    """N-07 边界：无 approved 正式知识（candidate-only）→ 拒绝同步。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.sync_official_research_graph(team["teamId"], {})

def test_sync_official_research_graph_completes_and_is_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_knowledge_ingestion_status",
        lambda team_id: {"summary": {"formalKnowledgeItemCount": 2}},
    )
    first = team_workflow_orchestration_service.sync_official_research_graph(team["teamId"], {})
    assert first["status"] == "completed"
    assert first["sync"]["graphStatus"] == "synced"
    assert first["sync"]["officialBoundary"]["createsKnowledgeItem"] is False
    second = team_workflow_orchestration_service.sync_official_research_graph(team["teamId"], {})
    assert second.get("idempotentReuse") is True
    assert second["sync"]["syncId"] == first["sync"]["syncId"]

def test_rollback_official_research_graph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_knowledge_ingestion_status",
        lambda team_id: {"summary": {"formalKnowledgeItemCount": 1}},
    )
    sync = team_workflow_orchestration_service.sync_official_research_graph(team["teamId"], {})
    sync_id = sync["sync"]["syncId"]
    res = team_workflow_orchestration_service.rollback_official_research_graph(team["teamId"], sync_id, {})
    assert res["status"] == "rolled_back"
    assert res["sync"]["graphStatus"] == "rolled_back"
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.rollback_official_research_graph(team["teamId"], sync_id, {})
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.rollback_official_research_graph(team["teamId"], "nonexistent", {})

def test_validate_prd_passes_for_consistent_code(tmp_path, monkeypatch):
    """N-14：schemas/registry/端点/runner 一致时 valid=True。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    res = team_workflow_orchestration_service.validate_prd(team["teamId"], {}, registered_paths=_PRD_VALIDATE_PATHS)
    assert res["valid"] is True
    assert res["failedCount"] == 0
    names = {item["check"] for item in res["checks"]}
    assert {
        "schemas_present",
        "candidate_types_in_sync",
        "research_task_outputs_in_sync",
        "research_endpoints_registered",
        "smoke_runner_markers",
    } <= names

def test_validate_prd_detects_candidate_type_drift(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    monkeypatch.setattr(team_workflow_orchestration_service, "CANDIDATE_TYPES", {"source_manifest"})
    res = team_workflow_orchestration_service.validate_prd(team["teamId"], {})
    assert res["valid"] is False
    assert any(item["check"] == "candidate_types_in_sync" and not item["ok"] for item in res["checks"])

def test_validate_prd_detects_missing_endpoint(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    res = team_workflow_orchestration_service.validate_prd(team["teamId"], {}, registered_paths=["/only/one/path"])
    assert res["valid"] is False
    assert any(item["check"] == "research_endpoints_registered" and not item["ok"] for item in res["checks"])

def test_export_deliverables_empty_team_is_blocked(tmp_path, monkeypatch):
    """N-13：证据不足时返回 blocker 清单而非伪造完整材料；不回写知识库。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    res = team_workflow_orchestration_service.export_deliverables(team["teamId"], {})
    assert res["status"] == "blocked"
    codes = {item["code"] for item in res["blockers"]}
    assert {"no_reviewed_hypothesis", "experiment_loop_incomplete", "no_official_knowledge"} <= codes
    assert res["deliverableManifest"]["officialBoundary"]["writesBackToKnowledge"] is False

def test_export_deliverables_with_reviewed_hypothesis_and_artifact(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    _register_typed_candidate(
        team["teamId"],
        "algorithm_hypothesis",
        metadata={"reviewRecords": [{"decision": "approve", "reviewRecordId": "rev-1"}]},
    )
    _seed_plan_with_smoke_run(team["teamId"])
    res = team_workflow_orchestration_service.export_deliverables(team["teamId"], {})
    codes = {item["code"] for item in res["blockers"]}
    assert "no_reviewed_hypothesis" not in codes
    assert "experiment_loop_incomplete" not in codes
    assert res["deliverableManifest"]["artifactRefs"][0]["artifactHash"] == "sha256:abc"

def test_propose_iteration_iterate_creates_supersedes_and_draft(tmp_path, monkeypatch):
    """N-12：iterate 新建 v2 draft + supersedes 边，保留 parentCandidateId/changeReason，不覆盖原候选。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(team["teamId"], "algorithm_hypothesis")
    res = team_workflow_orchestration_service.propose_iteration(
        team["teamId"], {"parentCandidateId": hyp_id, "action": "iterate", "changeReason": "tune routing gate"}
    )
    assert res["action"] == "iterate"
    draft = res["proposal"]["newCandidateDraft"]
    assert draft["parentCandidateId"] == hyp_id and draft["changeReason"] == "tune routing gate"
    edges = res["versionEdges"]
    assert any(e["edgeType"] == "supersedes" and e["to"] == hyp_id and e["from"] == draft["candidateId"] for e in edges)

def test_propose_iteration_requires_change_reason(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(team["teamId"], "algorithm_hypothesis")
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.propose_iteration(
            team["teamId"], {"parentCandidateId": hyp_id, "action": "iterate"}
        )

def test_propose_iteration_reject_writes_archive_edge(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(team["teamId"], "algorithm_hypothesis")
    res = team_workflow_orchestration_service.propose_iteration(
        team["teamId"], {"parentCandidateId": hyp_id, "action": "reject", "changeReason": "variant underperformed"}
    )
    assert res["proposal"]["rejectionArchive"]["reason"] == "variant underperformed"
    assert any(e["edgeType"] == "rejected_because" and e["from"] == hyp_id for e in res["versionEdges"])

def test_propose_iteration_merge_requires_target(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(team["teamId"], "algorithm_hypothesis")
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.propose_iteration(
            team["teamId"], {"parentCandidateId": hyp_id, "action": "merge", "changeReason": "dedupe"}
        )
    other_id = _register_typed_candidate(team["teamId"], "algorithm_hypothesis")
    res = team_workflow_orchestration_service.propose_iteration(
        team["teamId"],
        {"parentCandidateId": hyp_id, "action": "merge", "changeReason": "dedupe", "mergeWithCandidateId": other_id},
    )
    assert any(e["edgeType"] == "merged_with" and e["to"] == other_id for e in res["versionEdges"])

def test_decide_research_review_approves_clean_hypothesis(tmp_path, monkeypatch):
    """N-05：证据/事实分界/可测性齐全且无高过度类比 → approve（review_ready）。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(
        team["teamId"],
        "algorithm_hypothesis",
        metadata={"experimentPlan": {"dataset": "d", "metric": ["acc"], "baseline": "b"}, "factLayer": ["f"]},
    )
    res = team_workflow_orchestration_service.decide_research_review(team["teamId"], {"candidateIds": [hyp_id]})
    assert res["decision"] == "approve"
    assert res["reviewRecord"]["candidateType"] == "review_record"
    assert res["reviewRecord"]["currentState"] == "review_ready"
    assert res["riskFlags"] == []

def test_decide_research_review_blocks_approve_on_high_over_analogy(tmp_path, monkeypatch):
    """N-05 硬门禁：high_over_analogy → 自动 needs_human；显式 approve 被拦截。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    map_id = _register_typed_candidate(
        team["teamId"], "mechanism_mapping", metadata={"overAnalogyRisk": "high", "factLayer": ["f"]}
    )
    res = team_workflow_orchestration_service.decide_research_review(team["teamId"], {"candidateIds": [map_id]})
    assert res["decision"] == "needs_human"
    assert "high_over_analogy" in res["riskFlags"]
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.decide_research_review(
            team["teamId"], {"candidateIds": [map_id], "decision": "approve"}
        )

def test_decide_research_review_reject_requires_reason(tmp_path, monkeypatch):
    """N-05：reject 必须带 rejectionReason（requiredChanges 或 comments）。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hyp_id = _register_typed_candidate(
        team["teamId"], "algorithm_hypothesis", metadata={"experimentPlan": {"x": 1}, "factLayer": ["f"]}
    )
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.decide_research_review(
            team["teamId"], {"candidateIds": [hyp_id], "decision": "reject"}
        )
    res = team_workflow_orchestration_service.decide_research_review(
        team["teamId"], {"candidateIds": [hyp_id], "decision": "reject", "requiredChanges": ["fix baseline"]}
    )
    assert res["decision"] == "reject"

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

def test_knowledge_expansion_team_agents_purge_unregistered_source_role_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    legacy_agent = agent_directory_service.create_agent_instance(
        display_name="未注册资料角色",
        created_by=team_service.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
        role_key="unsupported_source_role",
        metadata={
            "knowledgeExpansionTeamId": team_service.KNOWLEDGE_EXPANSION_TEAM_ID,
            "knowledgeExpansionTeamManagedVersion": 1,
            "knowledgeExpansionTeamRole": "unsupported_source_role",
            "knowledgeExpansionTeamRoleKey": "unsupported_source_role",
        },
    )

    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]

    assert legacy_agent["agentId"] in result["purgedAgentIds"]
    assert agent_directory_service.get_agent(legacy_agent["agentId"], include_archived=True) is None
    assert [member["role"] for member in team["members"]] == [
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
    ]

def test_research_stage_status_does_not_reconcile_nonterminal_failed_tool_event(tmp_path, monkeypatch):
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
    workflow_run_id = "workflow-stage-task-tool-error"
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
            "scope": {"workflowRunId": workflow_run_id},
        },
    )
    source_run_id = stage_response["run"]["runId"]
    write_problem_understanding_artifact(
        team_id=team["teamId"],
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        node_run_id="node-problem-stage-task-tool-error",
        problem_understanding={
            "scope": "验证非终态工具错误不会被误判为任务完成。",
            "subquestions": ["单次工具失败是否保持当前 Agent 任务运行态？"],
            "assumptions": ["资料搜集运行已绑定当前工作流。"],
            "known_unknowns": ["后续工具调用是否成功尚未确定。"],
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
            "turnId": "turn-stage-task-tool-error",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        source_run_id,
        {"stageId": "finding", "agentId": discovery["agentId"], "agentRole": "source_finder"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        "turn-stage-task-tool-error",
        "turn_started",
        status="running",
        payload={"source": "test"},
    )
    append_conversation_event(
        tmp_path,
        task["sessionId"],
        "turn-stage-task-tool-error",
        "tool_result",
        status="failed",
        payload={"toolCall": {"name": "batch_web_search_tool", "status": "failed"}},
    )

    status_payload = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])

    latest_round = status_payload["latestRound"]
    stage_tasks = latest_round.get("sourceCollectionStageSessionTasks", [])
    reconciled = next(item for item in stage_tasks if item["taskId"] == task["taskId"])
    assert reconciled["status"] == "running"
    collection_card = next(card for card in latest_round["sourceCollectionStageCards"] if card["stageId"] == "finding")
    assert collection_card["agentTaskStatus"] == "running"
    assert collection_card["status"] == "agent_running"

def test_source_quality_reconcile_retries_legacy_no_assessable_keep_decisions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_id = "run-legacy-keep-quality-reconcile"
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding keep decision source",
            "sourceUrl": "https://doi.org/10.0000/legacy-keep",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence suitable for keeping.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/legacy-keep"},
            "createdByAgent": agent["agentId"],
        },
    )["candidate"]
    team_workflow_orchestration_service._upsert_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "taskId": "stagetask-legacy-keep-quality",
            "runId": run_id,
            "stageId": "extraction",
            "agentId": agent["agentId"],
            "agentRole": "source_extractor",
            "sessionId": "session-legacy-keep-quality",
            "status": "completed",
            "summary": "旧版本把 keep 判定跳过为 unsupported_decision。",
            "writeback": {
                "status": "completed",
                "summary": "旧版本回写。",
                "result": {
                    "candidateDecisions": [
                        {
                            "candidateId": candidate["candidateId"],
                            "decision": "keep",
                            "reason": "有价值资料，保留进入关系整理。",
                        }
                    ]
                },
                "materializedSourceQuality": {
                    "status": "no_assessable_decisions",
                    "skippedCandidateCount": 1,
                    "skippedCandidates": [{"candidateId": candidate["candidateId"], "reason": "unsupported_decision"}],
                },
            },
            "result": {
                "candidateDecisions": [
                    {
                        "candidateId": candidate["candidateId"],
                        "decision": "keep",
                        "reason": "有价值资料，保留进入关系整理。",
                    }
                ],
                "materializedSourceQuality": {
                    "status": "no_assessable_decisions",
                    "skippedCandidateCount": 1,
                    "skippedCandidates": [{"candidateId": candidate["candidateId"], "reason": "unsupported_decision"}],
                },
            },
            "createdAt": "2026-06-30T00:00:00+00:00",
            "updatedAt": "2026-06-30T00:00:00+00:00",
        },
    )

    changed = team_workflow_orchestration_service._reconcile_source_collection_stage_session_tasks(team["teamId"])

    store = team_workflow_orchestration_service._load_source_collection_stage_session_task_store(team["teamId"], run_id)
    stored_task = next(item for item in store["tasks"] if item["taskId"] == "stagetask-legacy-keep-quality")
    candidates = {
        item["candidateId"]: item
        for item in team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    }
    assert changed is True
    assert stored_task["writeback"]["materializedSourceQuality"]["status"] == "completed"
    assert stored_task["writeback"]["materializedSourceQuality"]["approvedCandidateCount"] == 1
    assert candidates[candidate["candidateId"]]["qualityStatus"] == "source_quality_approved"

def test_content_extraction_writeback_accumulates_partial_candidate_batches(tmp_path, monkeypatch):
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
                "title": f"Predictive coding batched candidate {index}",
                "sourceUrl": f"https://doi.org/10.0000/extraction-batch-{index}",
                "sourceKind": "paper",
                "summary": "Predictive coding evidence for batched writeback.",
                "allowedForAnalysis": True,
                "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/extraction-batch-{index}"},
                "createdByAgent": "content-extraction-agent",
            },
        )["candidate"]
        for index in range(4)
    ]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-content-batch", "status": "running"},
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
            "status": "needs_review",
            "summary": "先回写前 2 条候选提炼。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": item["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "summary": f"{item['title']} 第一批已提炼。",
                    }
                    for item in candidates[:2]
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    assert first["writeback"]["coverageSummary"]["processed"] == 2
    assert first["writeback"]["coverageSummary"]["missing"] == 2

    _append_stage_task_tool_trace(tmp_path, task["task"])
    complete = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "再回写后 2 条候选提炼，应与上一批合并为 4/4。",
            "result": {
                "candidateExtractions": [
                    {
                        "candidateId": item["candidateId"],
                        "status": "extracted",
                        "decision": "keep",
                        "summary": f"{item['title']} 第二批已提炼。",
                    }
                    for item in candidates[2:]
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert complete["writeback"]["status"] == "completed"
    assert complete["writeback"]["coverageSummary"]["processed"] == 4
    assert complete["writeback"]["coverageSummary"]["missing"] == 0
    assert len(complete["task"]["result"]["candidateExtractions"]) == 4
    refreshed_candidates = {
        item["candidateId"]: item
        for item in team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    }
    assert all(
        refreshed_candidates[item["candidateId"]]["metadata"]["contentExtraction"]["summary"]
        for item in candidates
    )

def test_knowledge_steward_memory_writeback_auto_ingests_approved_candidates(tmp_path, monkeypatch):
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
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/steward-auto-ingest",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and attention mechanisms.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/steward-auto-ingest"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": "source-quality-agent",
            "decision": "approved",
            "notes": "神经预测编码主题相关，元数据可追踪。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/steward-auto-ingest"}],
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-memory-ingest", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor["agentId"], "agentRole": "source_ingestor"},
    )
    writeback_payload = {
        "status": "completed",
        "summary": "知识库管理员通过 1 条候选，直接入库。",
        "result": {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "candidate_summary": {
                "approved": {
                    "count": 1,
                    "candidates": [
                        {
                            "candidateId": source["candidateId"],
                            "title": source["title"],
                            "doi": "10.0000/steward-auto-ingest",
                            "overall_score": 88,
                            "relevance_score": 96,
                            "assessment_notes": "可直接支撑神经预测编码算法假设。",
                        }
                    ],
                }
            },
            "steward_assessment": {"decision": "approved", "targetDomain": "神经机制启发神经网络算法"},
        },
        "recordedByAgent": ingestor["agentId"],
        "evidenceRefs": [{"type": "candidate", "id": source["candidateId"]}],
        "nextActions": ["进入实验规划"],
    }

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        writeback_payload,
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]
    knowledge_base_id = materialized["knowledgeBaseId"]
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base_id,
        agent_id=ingestor["agentId"],
    )
    memory_projection = next(
        card
        for card in team_workflow_orchestration_service._source_collection_stage_cards_projection(team["teamId"], run_id)["cards"]
        if card["stageId"] == "ingestion"
    )

    assert materialized["status"] == "completed"
    assert materialized["approvedCandidateCount"] == 1
    assert materialized["formalKnowledgeItemCount"] == 1
    assert materialized["writesFormalKnowledge"] is True
    assert knowledge_base_id == knowledge_base["knowledgeBaseId"]
    assert knowledge_items["summary"]["itemCount"] == 1
    assert source["title"] in knowledge_items["items"][0]["title"]
    assert response["task"]["writesFormalKnowledge"] is True
    assert memory_projection["status"] == "closed_loop"
    assert memory_projection["counts"]["output"] == 1

    second_response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        writeback_payload,
    )
    second_items = team_knowledge_service.list_knowledge_items(
        knowledge_base_id,
        agent_id=ingestor["agentId"],
    )
    second_materialized = second_response["writeback"]["materializedKnowledgeIngestion"]
    assert second_materialized["status"] == "completed"
    assert second_materialized["reusedOfficialSync"] is True
    assert second_items["summary"]["itemCount"] == 1

def test_research_stage_status_supersedes_older_active_round_when_newer_round_exists(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    now = "2026-07-16T08:00:00+08:00"
    older_round = {
        "schemaVersion": 1,
        "stageRoundId": "stage-round-older",
        "teamId": team["teamId"],
        "stageType": "knowledge_collection",
        "roundNumber": 1,
        "status": "needs_attention",
        "sourceRunIds": [],
        "createdAt": "2026-07-15T08:00:00+08:00",
        "updatedAt": "2026-07-15T08:00:00+08:00",
    }
    newer_round = {
        "schemaVersion": 1,
        "stageRoundId": "stage-round-newer",
        "teamId": team["teamId"],
        "stageType": "knowledge_collection",
        "roundNumber": 2,
        "status": "needs_continue",
        "sourceRunIds": [],
        "createdAt": now,
        "updatedAt": now,
    }
    store = team_workflow_orchestration_service._load_stage_round_store(team["teamId"])
    store["rounds"] = [older_round, newer_round]
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._stage_round_store_path(team["teamId"]),
        store,
    )

    status = team_workflow_orchestration_service.get_research_stage_round_status(team["teamId"])
    persisted_store = team_workflow_orchestration_service._load_stage_round_store(team["teamId"])
    persisted_older = next(item for item in persisted_store["rounds"] if item["stageRoundId"] == "stage-round-older")

    assert persisted_older["status"] == "superseded"
    assert persisted_older["supersededByStageRoundId"] == "stage-round-newer"
    assert status["latestRound"]["stageRoundId"] == "stage-round-newer"
    assert status["activeRounds"] == []
    assert status["phases"][0]["activeRoundId"] == ""
    event = next(
        item
        for item in events
        if len(item[0]) >= 3 and item[0][2] == "research_stage_round.superseded_by_newer_round"
    )
    assert event[1]["fields"]["stageRoundId"] == "stage-round-older"

def test_research_memory_claim_map_keeps_status_without_result_artifact():
    context = team_workflow_orchestration_service._build_research_memory_context(
        stage_type="experiment_design",
        research_question="Bounded claim status",
        plans=[
            {
                "planId": "plan-qualified-with-knowledge",
                "status": "ingested",
                "experimentContract": {"researchQuestion": "Qualified claim"},
                "knowledgeIngestion": {
                    "status": "ingested",
                    "result": {"knowledgeItemId": "kitem-qualified"},
                },
            },
            {
                "planId": "plan-unsupported-without-artifact",
                "status": "smoke_needs_review",
                "experimentContract": {"researchQuestion": "Unsupported claim"},
            },
            {
                "planId": "plan-not-established",
                "status": "draft",
                "experimentContract": {"researchQuestion": "Unvalidated claim"},
            },
        ],
        candidates=[
            {
                "candidateId": "candidate-rejected",
                "candidateType": "algorithm_hypothesis",
                "currentState": "rejected",
                "claims": [{"claim": "Rejected claim"}],
            }
        ],
    )

    by_claim = {item["claim"]: item for item in context["claimMap"]}
    assert by_claim["Qualified claim"]["status"] == "qualified"
    assert by_claim["Qualified claim"]["supportEvidenceRefs"] == [
        {"type": "knowledge_item", "id": "kitem-qualified"}
    ]
    assert by_claim["Unsupported claim"]["status"] == "unsupported"
    assert by_claim["Unsupported claim"]["counterEvidenceRefs"] == []
    assert by_claim["Unvalidated claim"]["status"] == "not_established"
    assert by_claim["Rejected claim"]["status"] == "rejected"

def test_research_memory_context_uses_active_design_for_nested_allowed_variable():
    context = team_workflow_orchestration_service._build_research_memory_context(
        stage_type="experiment_design",
        research_question="Does the smoke budget preserve the formal gate profile?",
        plans=[
            {
                "planId": "plan-best-validated",
                "status": "ingested",
                "experimentContract": {
                    "revision": 4,
                    "researchQuestion": "Does the candidate improve the primary metric?",
                },
                "activeFullRunResult": {
                    "fullRunResultId": "full-best",
                    "status": "passed",
                },
            },
            {
                "planId": "plan-active-diagnostic",
                "status": "smoke_needs_review",
                "experimentContract": {
                    "revision": 12,
                    "researchQuestion": "Does the smoke budget preserve the formal gate profile?",
                    "methodConfig": {"budget": {"epochs": [2, 8]}},
                    "constraints": ["same seed and controls", "only epochs changes from 2 to 8"],
                },
            },
        ],
        control_plan={
            "planId": "plan-active-diagnostic",
            "experimentContract": {
                "methodConfig": {"budget": {"epochs": [2, 8]}},
                "constraints": ["same seed and controls", "only epochs changes from 2 to 8"],
            },
        },
    )

    assert context["currentBest"]["planId"] == "plan-best-validated"
    assert context["allowedVariableContract"] == {
        "status": "derived_from_frozen_constraints",
        "variables": [
            {
                "path": "methodConfig.budget.epochs",
                "source": "frozen_constraint",
                "evidenceRef": "plan-active-diagnostic",
            }
        ],
        "frozenControls": ["same seed and controls"],
    }
    assert "explicit_allowed_variable_changes" not in context["missingEvidence"]

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

def test_local_research_model_task_accepts_ready_evidence_ledger_input(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    task_response = team_workflow_orchestration_service.build_local_research_model_task(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "evidenceLedger": {
                "status": "evidence_ready",
                "claims": [{"claim": "Predictive coding uses hierarchical prediction errors.", "sourceRef": "ledger-source"}],
                "keyFindings": [
                    {
                        "finding": "层级预测误差支持跨层控制结构设计。",
                        "sourceRef": "ledger-source",
                        "page": "3",
                        "citation": "Ledger Source, p.3",
                    }
                ],
                "sourceRefs": [{"type": "paper", "id": "ledger-source", "label": "Ledger Source"}],
                "evidenceRefs": [{"type": "page_anchor", "id": "ledger-source-p3", "label": "Ledger Source p.3"}],
            },
        },
    )

    task = task_response["task"]
    assert task["evidenceLedger"]["status"] == "evidence_ready"
    assert task["evidenceLedger"]["claims"][0]["claim"] == "Predictive coding uses hierarchical prediction errors."
    assert task["sourceRefs"] == []
    assert task["evidenceRefs"] == []

def test_local_research_model_task_rejects_missing_anchor_evidence_ledger_input(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="evidenceLedger"):
        team_workflow_orchestration_service.build_local_research_model_task(
            team["teamId"],
            {
                "taskType": "paper_note_draft",
                "evidenceLedger": {
                    "status": "missing_evidence_anchor",
                    "claims": [{"claim": "Unanchored claim must not enter paper_note input."}],
                    "keyFindings": [{"finding": "缺少来源锚点的发现。"}],
                },
            },
        )

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
            "createdByAgent": "Source Finder Agent",
        },
    )["candidate"]
    revision_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Unlocated source",
            "sourceKind": "paper",
            "summary": "Potentially relevant but missing a source location.",
            "createdByAgent": "Source Finder Agent",
        },
    )["candidate"]

    response = team_workflow_orchestration_service.assess_source_quality_batch(
        team["teamId"],
        {"assessedByAgent": "Source Extractor Agent"},
    )
    status_payload = team_workflow_orchestration_service.get_source_quality_status(team["teamId"])
    decisions = {item["candidateId"]: item["decision"] for item in response["assessments"]}

    assert response["status"] == "completed"
    assert response["executionMode"] == "source_quality_agent_batch"
    assert response["assessedByAgent"] == "Source Extractor Agent"
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
            "createdByAgent": "Source Finder Agent",
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
            "createdByAgent": "Source Finder Agent",
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

def test_paper_note_autodraft_feeds_ready_evidence_ledger_to_model_input(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source_path = tmp_path / "sources" / "ledger.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"%PDF-1.4\nfake local pdf bytes\n")

    def fake_extract(path, *, page_scope, max_pages, max_chars_per_page):
        return [
            {
                "type": "pdf_page",
                "id": "ledger-p3",
                "label": "p. 3",
                "page": 3,
                "text": "Predictive coding excerpt from source extraction.",
            }
        ]

    monkeypatch.setattr(team_workflow_orchestration_service, "_extract_pdf_page_anchors", fake_extract)
    _FakeLocalResearchClient.response = _FakeLocalResearchMessage(
        """
        {
          "candidateType": "paper_note",
          "sourceRefs": [{"type": "paper", "id": "ledger-source", "label": "Ledger Source"}],
          "evidenceRefs": [{"type": "page_anchor", "id": "ledger-source-p3", "label": "Ledger Source p.3"}],
          "claims": [{"claim": "Ledger claim is preserved.", "sourceRef": "ledger-source"}],
          "keyFindings": [{"finding": "Ledger finding enters the paper note.", "sourceRef": "ledger-source", "page": "3", "citation": "Ledger Source, p.3"}],
          "methods": ["evidence ledger synthesis"],
          "limitations": ["autodraft requires review"],
          "citations": [{"sourceRef": "ledger-source", "page": "3", "citation": "Ledger Source, p.3"}],
          "uncertainty": [],
          "riskFlags": [],
          "confidence": 0.75,
          "nextAction": "send_to_mechanism_extraction",
          "requiresReview": true
        }
        """
    )
    _FakeLocalResearchClient.captured_messages = []
    candidate = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Ledger PDF",
            "sourcePath": str(source_path),
            "sourceKind": "pdf",
            "allowedForAnalysis": False,
            "createdByAgent": "Source Intake Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.extract_candidate_source_pages(
        team["teamId"],
        candidate["candidateId"],
        {"allowedForAnalysis": True, "pageScope": "3"},
    )
    store_path = team_workflow_orchestration_service._candidate_store_path(team["teamId"])
    store = json.loads(store_path.read_text(encoding="utf-8"))
    source_candidate = next(item for item in store["candidates"] if item["candidateId"] == candidate["candidateId"])
    source_candidate["metadata"]["contentExtraction"] = {
        "status": "kept_with_notes",
        "summary": "Ledger summary should be visible to paper_note drafting.",
        "evidenceStatus": "evidence_ready",
        "evidenceLedger": {
            "status": "evidence_ready",
            "claims": [
                {
                    "claim": "Predictive coding uses hierarchical prediction errors.",
                    "sourceRef": "ledger-source",
                    "supportLevel": "strong",
                }
            ],
            "keyFindings": [
                {
                    "finding": "层级预测误差支持跨层控制结构设计。",
                    "sourceRef": "ledger-source",
                    "page": "3",
                    "citation": "Ledger Source, p.3",
                }
            ],
            "citations": [
                {"sourceRef": "ledger-source", "page": "3", "citation": "Ledger Source, p.3"}
            ],
            "sourceRefs": [{"type": "paper", "id": "ledger-source", "label": "Ledger Source"}],
            "evidenceRefs": [{"type": "page_anchor", "id": "ledger-source-p3", "label": "Ledger Source p.3"}],
            "limitations": ["样本来源需要后续复核"],
            "uncertainty": ["机制迁移到算法仍需实验验证"],
            "riskFlags": ["analogy_risk"],
            "supportLevel": "strong",
            "nextAction": "draft_paper_note",
        },
    }
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    response = team_workflow_orchestration_service.draft_paper_note_from_source_candidate(
        team["teamId"],
        candidate["candidateId"],
        {"createdByAgent": "Paper Note Extraction Agent"},
        llm_client_factory=_FakeLocalResearchClient,
    )

    captured_payload = _FakeLocalResearchClient.captured_messages[-1]["messages"][1]["content"]
    assert response["validation"]["valid"] is True
    assert "Predictive coding excerpt from source extraction" in captured_payload
    assert "Predictive coding uses hierarchical prediction errors" in captured_payload
    assert "层级预测误差支持跨层控制结构设计" in captured_payload
    assert "Ledger Source, p.3" in captured_payload
    assert "ledger-source-p3" in captured_payload
    assert "missing_evidence_anchor" not in captured_payload

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

    source_list = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest", include_validation=True)
    paper_notes = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="paper_note")

    assert source_list["candidateCount"] == 1
    assert source_list["candidates"][0]["candidateType"] == "source_manifest"
    assert source_list["validationSummary"]["candidateCount"] == 2
    assert paper_notes["candidateCount"] == 1
    assert paper_notes["candidates"][0]["candidateType"] == "paper_note"

def test_candidate_store_list_skips_validation_by_default(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Fast list source",
            "sourcePath": "C:/papers/fast.pdf",
            "sourceKind": "pdf",
            "sha256": "b" * 64,
            "allowedForAnalysis": True,
            "createdByAgent": "Source Intake Agent",
        },
    )

    def fail_validation(team_id):
        raise AssertionError("candidate list should not validate unless requested")

    monkeypatch.setattr(team_workflow_orchestration_service, "validate_candidate_store", fail_validation)

    response = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")

    assert response["candidateCount"] == 1
    assert response["validationSummary"]["skipped"] is True

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

    response = team_workflow_orchestration_service.build_candidate_graph(team["teamId"], {"createdByAgent": "资料关系整理 Agent"})

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
            "createdByAgent": "Source Finder Agent",
        },
    )["candidate"]
    revision_source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Untraceable neuroscience note",
            "sourceKind": "paper",
            "summary": "Potentially relevant but missing a source location.",
            "createdByAgent": "Source Finder Agent",
        },
    )["candidate"]
    team_workflow_orchestration_service.assess_source_quality_batch(team["teamId"], {})

    response = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {
            "createdByAgent": "Source Relation Mapper Agent",
            "curationMode": "agent_approved_only",
        },
    )

    graph_node_ids = {node["candidateId"] for node in response["graph"]["nodes"]}
    assert response["graph"]["summary"]["curationMode"] == "agent_approved_only"
    assert response["graph"]["summary"]["createdByAgent"] == "Source Relation Mapper Agent"
    assert response["graph"]["summary"]["stageAgentRole"] == "source_relation_mapper"
    assert response["reusedCandidateGraph"] is False
    assert response["ingestionFingerprint"]
    assert response["graph"]["summary"]["nodeCount"] == 1
    assert response["graph"]["summary"]["filteredCandidateCount"] == 1
    assert response["candidateGraph"]["createdByAgent"] == "Source Relation Mapper Agent"
    assert response["candidateGraph"]["metadata"]["stageAgentRole"] == "source_relation_mapper"
    assert response["candidateGraph"]["metadata"]["agentProcess"][0]["agentRole"] == "source_relation_mapper"
    assert response["candidateGraph"]["metadata"]["agentProcess"][1]["nextAction"] == "knowledge_ingestion_precheck"
    assert approved_source["candidateId"] in graph_node_ids
    assert revision_source["candidateId"] not in graph_node_ids

    reused = team_workflow_orchestration_service.build_candidate_graph(
        team["teamId"],
        {
            "createdByAgent": "Source Relation Mapper Agent",
            "curationMode": "agent_approved_only",
        },
    )

    assert reused["reusedCandidateGraph"] is True
    assert reused["candidateGraph"]["candidateId"] == response["candidateGraph"]["candidateId"]
    reused_events = _workflow_scene_events_by_code(scene_events, "candidate_graph.reused")
    assert reused_events
    assert reused_events[-1]["fields"]["candidateId"] == response["candidateGraph"]["candidateId"]
    assert reused_events[-1]["fields"]["ingestionFingerprint"] == response["ingestionFingerprint"]

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
            "createdByAgent": "Source Finder Agent",
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

def test_knowledge_collection_ingestion_auto_closes_to_formal_item_via_coordinator(tmp_path, monkeypatch):
    """同步闭环：steward 提案、coordinator 审批，一键直接产出正式 KnowledgeItem。

    回归保护：步骤4「一键入库」走 autoSubmit/autoReviewSource/autoApprove 同步路径时，
    最终审批由独立的 coordinator/lead 成员完成（职责分离），不再依赖唤醒 steward agent。
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    coordinator = agent_directory_service.create_agent_instance(display_name="Research Coordinator")
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[
            {"agentId": steward_id, "role": "knowledge_steward"},
            {"agentId": coordinator["agentId"], "role": "research_coordination"},
        ],
    )
    for source_payload in (
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and learning.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Finder Agent",
        },
        {
            "title": "Synaptic plasticity learning rule review",
            "sourceUrl": "https://doi.org/10.0000/stdp-review",
            "sourceKind": "review",
            "summary": "Synaptic plasticity evidence can support learning-rule hypotheses.",
            "tags": ["neuroscience", "learning"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Acquisition Agent",
        },
    ):
        team_workflow_orchestration_service.register_candidate_source(team["teamId"], source_payload)

    response = team_workflow_orchestration_service.run_knowledge_collection_ingestion(
        team["teamId"],
        {
            "stewardAgentId": steward_id,
            "targetDomain": "神经学启发神经网络算法",
            "maxCandidates": 10,
            "autoCreateKnowledgeBase": True,
            "autoSubmit": True,
            "autoReviewSource": True,
            "autoApprove": True,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
        },
    )

    knowledge_base_id = response["summary"]["knowledgeBaseId"]
    knowledge_items = team_knowledge_service.list_knowledge_items(
        knowledge_base_id, agent_id=coordinator["agentId"]
    )

    # 同步闭环真正产出正式 KnowledgeItem，且没有回落到唤醒 steward agent 的异步路径。
    assert response["knowledgeReview"] is not None
    assert response["knowledgeStewardActivation"] is None
    assert response["summary"]["formalKnowledgeItemCount"] >= 1
    assert response["statusSnapshot"]["summary"]["formalKnowledgeItemCount"] >= 1
    assert knowledge_items["summary"]["itemCount"] >= 1

def test_knowledge_collection_ingestion_uses_scoped_existing_team_base_when_ids_overlap(tmp_path, monkeypatch):
    """Existing team KB selection must stay owner-scoped when another owner has the same base id."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    coordinator = agent_directory_service.create_agent_instance(display_name="Research Coordinator")
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[
            {"agentId": steward_id, "role": "knowledge_steward"},
            {"agentId": coordinator["agentId"], "role": "research_coordination"},
        ],
    )
    duplicate_steward = agent_directory_service.create_agent_instance(display_name="Duplicate Steward")
    other_team = team_service.create_team(
        name="另一支科研团队",
        members=[{"agentId": duplicate_steward["agentId"], "role": "knowledge_steward"}],
    )
    target_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="挑战杯科研知识库",
        description="Target team base",
        actor_agent_id=steward_id,
    )
    duplicate_base = team_knowledge_service.create_knowledge_base(
        other_team["teamId"],
        name="挑战杯科研知识库",
        description="Duplicate raw id under another owner",
        actor_agent_id=duplicate_steward["agentId"],
    )
    assert target_base["knowledgeBaseId"] == duplicate_base["knowledgeBaseId"]
    assert target_base["scopedKnowledgeBaseId"] != duplicate_base["scopedKnowledgeBaseId"]

    for source_payload in (
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and learning.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Finder Agent",
        },
        {
            "title": "Synaptic plasticity learning rule review",
            "sourceUrl": "https://doi.org/10.0000/stdp-review",
            "sourceKind": "review",
            "summary": "Synaptic plasticity evidence can support learning-rule hypotheses.",
            "tags": ["neuroscience", "learning"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Acquisition Agent",
        },
    ):
        team_workflow_orchestration_service.register_candidate_source(team["teamId"], source_payload)

    response = team_workflow_orchestration_service.run_knowledge_collection_ingestion(
        team["teamId"],
        {
            "stewardAgentId": steward_id,
            "targetDomain": "神经学启发神经网络算法",
            "maxCandidates": 10,
            "autoCreateKnowledgeBase": True,
            "autoSubmit": True,
            "autoReviewSource": True,
            "autoApprove": True,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
        },
    )

    assert response["knowledgeReview"] is not None
    assert response["summary"]["knowledgeBaseId"] == target_base["knowledgeBaseId"]
    assert response["summary"]["scopedKnowledgeBaseId"] == target_base["scopedKnowledgeBaseId"]
    assert response["summary"]["formalKnowledgeItemCount"] >= 1
    assert response["statusSnapshot"]["officialBoundary"]["writesOfficialKnowledge"] is True

def test_knowledge_collection_ingestion_auto_approve_needs_distinct_reviewer(tmp_path, monkeypatch):
    """职责分离负例：团队没有 coordinator/lead 审批人时，autoApprove 不应自提自批出正式知识。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[{"agentId": steward_id, "role": "knowledge_steward"}],
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
            "createdByAgent": "Source Finder Agent",
        },
    )

    response = team_workflow_orchestration_service.run_knowledge_collection_ingestion(
        team["teamId"],
        {
            "stewardAgentId": steward_id,
            "maxCandidates": 10,
            "autoCreateKnowledgeBase": True,
            "autoSubmit": True,
            "autoReviewSource": True,
            "autoApprove": True,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
        },
    )

    assert response["knowledgeReview"] is None
    assert response["statusSnapshot"]["summary"]["formalKnowledgeItemCount"] == 0

def test_knowledge_collection_ingestion_background_completes_and_reports_status(tmp_path, monkeypatch):
    """后台执行：点击立即返回 accepted；worker 完成后 status 显示终态 + 正式 KnowledgeItem。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "work_runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service, "_knowledge_ingestion_work_run_store", lambda: isolated_store
    )
    _patch_knowledge_background_thread_immediate(monkeypatch)

    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    coordinator = agent_directory_service.create_agent_instance(display_name="Research Coordinator")
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[
            {"agentId": steward_id, "role": "knowledge_steward"},
            {"agentId": coordinator["agentId"], "role": "research_coordination"},
        ],
    )
    for source_payload in (
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/predictive-coding",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and learning.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Finder Agent",
        },
        {
            "title": "Synaptic plasticity learning rule review",
            "sourceUrl": "https://doi.org/10.0000/stdp-review",
            "sourceKind": "review",
            "summary": "Synaptic plasticity evidence can support learning-rule hypotheses.",
            "tags": ["neuroscience", "learning"],
            "allowedForAnalysis": True,
            "createdByAgent": "Source Acquisition Agent",
        },
    ):
        team_workflow_orchestration_service.register_candidate_source(team["teamId"], source_payload)

    accepted = team_workflow_orchestration_service.start_knowledge_collection_ingestion_background(
        team["teamId"],
        {
            "stewardAgentId": steward_id,
            "maxCandidates": 10,
            "autoCreateKnowledgeBase": True,
            "autoSubmit": True,
            "autoReviewSource": True,
            "autoApprove": True,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
        },
    )

    assert accepted["accepted"] is True
    assert accepted["executionMode"] == "background"
    assert accepted["activeWorkRun"]["status"] == "running"

    status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])
    assert status["activeWorkRun"] is None
    assert status["latestWorkRun"]["status"] == "completed"
    assert status["latestWorkRun"]["result"]["formalKnowledgeItemCount"] >= 1
    assert status["summary"]["formalKnowledgeItemCount"] >= 1

def test_knowledge_collection_completion_background_normalizes_one_click_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "completion-work-runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service, "_knowledge_ingestion_work_run_store", lambda: isolated_store
    )
    captured = {}
    _patch_knowledge_background_thread_immediate(monkeypatch)

    def fake_completion(team_id, payload):
        captured["team_id"] = team_id
        captured["payload"] = payload
        return {
            "status": "completed",
            "sourceRunId": "source-run-1",
            "searchExecutions": [{"status": "completed", "summary": {"recordCount": 4, "openAssignmentCount": 0}}],
            "extraction": {"status": "completed", "importedCount": 3, "skippedCount": 1, "failedCount": 0},
            "ingestion": {"status": "completed", "summary": {"formalKnowledgeItemCount": 1, "knowledgeBaseId": "kb-1"}},
            "summary": {"formalKnowledgeItemCount": 1, "knowledgeBaseId": "kb-1"},
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "run_knowledge_collection_completion", fake_completion)
    team = team_service.create_team(name="挑战杯科研团队", members=[])

    accepted = team_workflow_orchestration_service.start_knowledge_collection_completion_background(
        team["teamId"],
        {
            "stewardAgentId": "knowledge-steward",
            "sourceQualityAgentId": "source-quality",
            "candidateGraphAgentId": "candidate-graph",
            "targetDomain": "神经预测编码",
            "maxCandidates": 16,
        },
    )

    assert accepted["accepted"] is True
    assert captured["team_id"] == team["teamId"]
    assert captured["payload"]["backgroundExecution"] is True
    assert captured["payload"]["autoCreateKnowledgeBase"] is True
    assert captured["payload"]["autoSubmit"] is True
    assert captured["payload"]["autoReviewSource"] is True
    assert captured["payload"]["autoApprove"] is True
    assert captured["payload"]["notifyStewardAgent"] is False
    assert captured["payload"]["wakeStewardAgent"] is False
    assert captured["payload"]["sourceQualityAgentId"] == "source-quality"
    assert captured["payload"]["candidateGraphAgentId"] == "candidate-graph"
    assert captured["payload"]["stewardAgentId"] == "knowledge-steward"
    assert captured["payload"]["targetDomain"] == "神经预测编码"
    assert captured["payload"]["maxCandidates"] == 16

    completed_events = _workflow_scene_events_by_code(scene_events, "knowledge_collection.completion_background_completed")
    assert completed_events
    child_payload = completed_events[-1]["child_log_payload"]
    assert child_payload["kind"] == "knowledge_collection_completion"
    assert child_payload["status"] == "completed"
    assert child_payload["sourceRunId"] == "source-run-1"
    assert [step["stageId"] for step in child_payload["steps"]] == [
        "remaining_search",
        "candidate_extraction",
        "knowledge_ingestion",
    ]
    assert child_payload["steps"][0]["outputCount"] == 4
    assert child_payload["steps"][1]["outputCount"] == 3
    assert child_payload["formalKnowledgeItemCount"] == 1

    status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])
    active_flow = accepted["activeWorkRun"]["flowVisualization"]
    latest_run = status["latestWorkRun"]
    latest_flow = latest_run["flowVisualization"]
    assert [node["stageId"] for node in active_flow["nodes"]] == ["finding", "extraction", "relations", "ingestion"]
    assert active_flow["nodes"][0]["agentRole"] == "source_finder"
    assert latest_run["completionSteps"][0]["stageId"] == "remaining_search"
    assert latest_flow["status"] == "completed"
    assert latest_flow["nodes"][-1]["status"] == "completed"
    assert latest_flow["nodes"][-1]["outputCount"] == 1
    assert latest_flow["nodes"][-1]["agentRole"] == "source_ingestor"

def test_knowledge_collection_completion_flow_treats_official_knowledge_as_ingestion_done():
    step = team_workflow_orchestration_service._knowledge_collection_completion_step
    flow = team_workflow_orchestration_service._knowledge_collection_completion_flow_visualization(
        "completed",
        steps=[
            step("remaining_search", "no_open_assignment", input_count=1, output_count=0),
            step("candidate_extraction", "partial", input_count=10, output_count=0),
            step("source_review", "completed", input_count=34, output_count=28),
            step("candidate_graph", "completed", input_count=34, output_count=28),
            step("steward_pack", "completed", input_count=28, output_count=1),
            step("source_gate", "pending_review", input_count=1, output_count=1),
            step("knowledge_proposal", "pending_review", input_count=1, output_count=1),
            step("official_knowledge", "completed", input_count=1, output_count=1),
        ],
    )

    nodes = {node["stageId"]: node for node in flow["nodes"]}
    assert flow["status"] == "completed"
    assert nodes["ingestion"]["status"] == "completed"
    assert nodes["ingestion"]["outputCount"] == 4

def test_knowledge_collection_completion_background_failure_logs_child_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "completion-work-runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service, "_knowledge_ingestion_work_run_store", lambda: isolated_store
    )
    _patch_knowledge_background_thread_immediate(monkeypatch)

    def fake_completion(_team_id, _payload):
        exc = team_workflow_orchestration_service.TeamWorkflowOrchestrationError("Source extraction failed.")
        exc.completion_log_payload = {
            "kind": "knowledge_collection_completion",
            "status": "failed",
            "sourceRunId": "source-run-failed",
            "steps": [
                {"stageId": "remaining_search", "status": "completed", "inputCount": 1, "outputCount": 2},
                {"stageId": "candidate_extraction", "status": "failed", "inputCount": 2, "outputCount": 0, "errorType": "TeamWorkflowOrchestrationError"},
            ],
        }
        raise exc

    monkeypatch.setattr(team_workflow_orchestration_service, "run_knowledge_collection_completion", fake_completion)
    team = team_service.create_team(name="挑战杯科研团队", members=[])

    accepted = team_workflow_orchestration_service.start_knowledge_collection_completion_background(
        team["teamId"],
        {"runId": "source-run-failed", "stewardAgentId": "source-ingestor"},
    )

    assert accepted["accepted"] is True
    failed_events = _workflow_scene_events_by_code(scene_events, "knowledge_collection.completion_background_failed")
    assert failed_events
    child_payload = failed_events[-1]["child_log_payload"]
    assert child_payload["kind"] == "knowledge_collection_completion"
    assert child_payload["status"] == "failed"
    assert child_payload["sourceRunId"] == "source-run-failed"
    assert child_payload["steps"][-1]["stageId"] == "candidate_extraction"
    assert child_payload["steps"][-1]["errorType"] == "TeamWorkflowOrchestrationError"

    status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])
    failed_flow = status["latestWorkRun"]["flowVisualization"]
    failed_nodes = {node["stageId"]: node for node in failed_flow["nodes"]}
    assert failed_flow["status"] == "failed"
    assert failed_nodes["finding"]["status"] == "completed"
    assert failed_nodes["extraction"]["status"] == "failed"
    assert failed_nodes["extraction"]["errorType"] == "TeamWorkflowOrchestrationError"
    assert "Source extraction failed" in failed_flow["error"]

def test_knowledge_ingestion_status_backfills_failed_completion_flow(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "completion-work-runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_knowledge_ingestion_work_run_store",
        lambda: isolated_store,
    )
    team = team_service.create_team(name="挑战杯科研团队", members=[])
    run_id = "knowledge-completion-flowless-failure"

    isolated_store.persist_snapshot(
        team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        {
            "runId": run_id,
            "runKind": team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
            "teamId": team["teamId"],
            "status": "failed",
            "currentPhase": "knowledge_ingestion",
            "error": "Knowledge review grant failed: Knowledge base id is ambiguous across owners.",
            "errorType": "TeamWorkflowOrchestrationError",
            "summary": {"formalKnowledgeItemCount": 0},
            "updatedAt": "2026-06-27T10:42:00Z",
        },
        active_run_id=run_id,
    )

    status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])
    latest_run = status["latestWorkRun"]
    flow = latest_run["flowVisualization"]
    nodes = {node["stageId"]: node for node in flow["nodes"]}

    assert status["activeWorkRun"] is None
    assert latest_run["runId"] == run_id
    assert flow["status"] == "failed"
    assert flow["currentStageId"] == "ingestion"
    assert nodes["ingestion"]["status"] == "failed"
    assert nodes["ingestion"]["errorType"] == "TeamWorkflowOrchestrationError"
    assert "Knowledge review grant failed" in flow["error"]

def test_knowledge_ingestion_status_repairs_stale_completed_completion_flow(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    isolated_store = WorkRunStore(root=tmp_path / "completion-work-runs")
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_knowledge_ingestion_work_run_store",
        lambda: isolated_store,
    )
    team = team_service.create_team(name="挑战杯科研团队", members=[])
    run_id = "knowledge-completion-stale-flow"
    source_run_id = "source-run-completed"

    isolated_store.persist_snapshot(
        team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        {
            "runId": run_id,
            "runKind": team_workflow_orchestration_service.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
            "teamId": team["teamId"],
            "status": "completed",
            "currentPhase": "completed",
            "sourceRunId": source_run_id,
            "completionSteps": [
                {"stageId": "source_gate", "status": "pending_review", "inputCount": 1, "outputCount": 1},
                {"stageId": "knowledge_proposal", "status": "pending_review", "inputCount": 1, "outputCount": 1},
                {"stageId": "official_knowledge", "status": "completed", "inputCount": 1, "outputCount": 1},
            ],
            "flowVisualization": {
                "kind": "knowledge_collection_completion",
                "schemaVersion": team_workflow_orchestration_service.SCHEMA_VERSION,
                "status": "completed",
                "currentStageId": "ingestion",
                "nodes": [
                    {"stageId": "finding", "label": "资料寻找", "agentRole": "source_finder", "status": "completed"},
                    {"stageId": "extraction", "label": "资料提炼", "agentRole": "source_extractor", "status": "completed"},
                    {"stageId": "relations", "label": "资料关系整理", "agentRole": "source_relation_mapper", "status": "completed"},
                    {"stageId": "ingestion", "label": "资料入库", "agentRole": "source_ingestor", "status": "pending"},
                ],
            },
            "summary": {"formalKnowledgeItemCount": 1},
            "updatedAt": "2026-07-07T15:49:52Z",
        },
    )

    status = team_workflow_orchestration_service.get_knowledge_ingestion_status(team["teamId"])
    latest_run = status["latestWorkRun"]
    flow = latest_run["flowVisualization"]
    nodes = {node["stageId"]: node for node in flow["nodes"]}

    assert latest_run["runId"] == run_id
    assert latest_run["sourceRunId"] == source_run_id
    assert flow["status"] == "completed"
    assert nodes["ingestion"]["status"] == "completed"
    assert nodes["ingestion"]["outputCount"] == 3

def test_knowledge_collection_completion_runs_search_extract_before_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    calls: list[tuple[str, dict]] = []

    def fake_search(team_id, run_id, payload):
        calls.append(("search", {"teamId": team_id, "runId": run_id, "payload": payload}))
        return {
            "status": "completed",
            "summary": {"recordCount": 3, "openAssignmentCount": 0},
        }

    def fake_extract(team_id, payload):
        calls.append(("extract", {"teamId": team_id, "payload": payload}))
        return {"status": "completed", "importedCount": 3, "skippedCount": 0, "failedCount": 0}

    def fake_ingest(team_id, payload):
        calls.append(("ingest", {"teamId": team_id, "payload": payload}))
        return {
            "status": "completed",
            "summary": {"formalKnowledgeItemCount": 2, "knowledgeBaseId": "kb-1"},
            "statusSnapshot": {"summary": {"formalKnowledgeItemCount": 2}},
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "execute_source_collection_search", fake_search)
    monkeypatch.setattr(team_workflow_orchestration_service, "extract_source_collection_candidates", fake_extract)
    monkeypatch.setattr(team_workflow_orchestration_service, "run_knowledge_collection_ingestion", fake_ingest)

    result = team_workflow_orchestration_service.run_knowledge_collection_completion(
        "challenge-team",
        {
            "runId": "source-run-1",
            "extractionAgentId": "content-extraction-agent",
            "sourceQualityAgentId": "source-quality",
            "candidateGraphAgentId": "candidate-graph",
            "stewardAgentId": "knowledge-steward",
            "maxSearchBatches": 1,
            "maxQueriesPerBatch": 5,
            "maxResultsPerQuery": 4,
            "maxRecords": 120,
        },
    )

    assert [name for name, _ in calls] == ["search", "extract", "ingest"]
    assert calls[0][1]["runId"] == "source-run-1"
    assert calls[0][1]["payload"]["maxQueries"] == 5
    assert calls[0][1]["payload"]["maxResultsPerQuery"] == 4
    assert calls[1][1]["payload"]["runId"] == "source-run-1"
    assert calls[1][1]["payload"]["extractionAgentId"] == "content-extraction-agent"
    assert calls[1][1]["payload"]["maxRecords"] == 120
    assert calls[2][1]["payload"]["backgroundExecution"] is True
    assert calls[2][1]["payload"]["autoSubmit"] is True
    assert calls[2][1]["payload"]["autoReviewSource"] is True
    assert calls[2][1]["payload"]["autoApprove"] is True
    assert calls[2][1]["payload"]["notifyStewardAgent"] is False
    assert result["searchExecutions"][0]["status"] == "completed"
    assert result["extraction"]["importedCount"] == 3
    assert result["ingestion"]["summary"]["formalKnowledgeItemCount"] == 2
    assert result["summary"]["formalKnowledgeItemCount"] == 2

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


def test_local_research_model_invoke_records_dashscope_provider_for_canonical_qwen_ref(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_local_research_llm_client",
        lambda model_id, *, llm_client_factory=None: _FakeLocalResearchClient(),
    )

    response = team_workflow_orchestration_service.invoke_local_research_model(
        team["teamId"],
        {
            "taskType": "paper_note_draft",
            "modelId": "dashscope_main/qwen3.6-plus",
            "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
            "evidenceRefs": [{"type": "page", "id": "p3", "label": "page 3"}],
            "excerpt": "A short source excerpt.",
            "createdByAgent": "Paper Note Extraction Agent",
        },
    )

    assert response["modelEvidence"]["modelProvider"] == "dashscope"
    assert response["modelEvidence"]["modelId"] == "dashscope_main/qwen3.6-plus"
    assert response["modelEvidence"]["modelName"] == "qwen3.6-plus"


def test_local_research_model_client_resolves_schema_v2_canonical_model_ref(monkeypatch):
    model_ref = "pixel_relay/gpt-5.6-terra"
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "pixel_relay": {
                        "label": "Pixel Relay",
                        "service_class": "relay",
                        "vendor": "multi_model",
                        "driver": "openai",
                        "base_url": "https://relay.example/v1",
                        "auth_kind": "api_key",
                        "credential_ref": "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY",
                        "requires_credential": True,
                        "protocols": {"default": "responses", "allowed": ["responses"]},
                        "discovery": {"mode": "manual", "adapter": "openai_compatible"},
                        "models": {
                            "gpt-5.6-terra": {
                                "upstream_id": "gpt-5.6-terra",
                                "label": "GPT-5.6 Terra",
                                "enabled": True,
                                "defaults": {"max_output_tokens": 32000, "timeout": 120},
                            }
                        },
                    }
                },
                "profiles": {},
            }
        },
    )

    client = team_workflow_orchestration_service._local_research_llm_client(
        model_ref,
        llm_client_factory=_FakeLocalResearchClient,
    )

    profile = client.config.llm.get_profile("__challenge_cup_local_research_model")
    assert profile.model_ref == model_ref
    assert profile.model == "gpt-5.6-terra"
    assert model_ref in client.config.llm.model_library

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


def test_steward_pack_writeback_lands_in_run_owner_project_store(tmp_path, monkeypatch):
    """SCI-091 回归：活跃工程 A + authority run 属工程 B 时，writeback 自动链物化的
    steward_pack_draft 候选必须落 B 的 owner 工程店；owner+active 读兼容合并仍工作。"""
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
    # 活跃工程 A（sci-001 语境），run 经 workflowRunId 钉到工程 B（sci-091 语境）。
    project_active = team_workflow_orchestration_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-001"}
    )["project"]
    team_workflow_orchestration_service.activate_research_project(team["teamId"], project_active["projectId"])
    project_owner = team_workflow_orchestration_service.create_research_project(
        team["teamId"], {"name": "challenge-sci-091"}
    )["project"]
    active_store_path = team_workflow_orchestration_service._candidate_store_path(team["teamId"])
    from core.web.services.team_workflow.research_projects import resolve_research_project_workspace_root

    owner_store_path = (
        resolve_research_project_workspace_root(team["teamId"], project_owner["projectId"])
        / "candidate_store"
        / "index.json"
    )
    assert active_store_path != owner_store_path

    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码",
            "researchProjectId": project_owner["projectId"],
            "scope": {"workflowRunId": "wr-owner-store-regression"},
            "agentRoles": ["source_ingestor"],
            "agentIds": {"source_ingestor": ingestor["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    assert (
        team_workflow_orchestration_service._source_collection_run_owner_research_project_id(team["teamId"], run_id)
        == project_owner["projectId"]
    )
    source = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Predictive coding cortical hierarchy neural network paper",
            "sourceUrl": "https://doi.org/10.0000/steward-owner-store",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for neural-network hierarchy and attention mechanisms.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/steward-owner-store"},
            "createdByAgent": "content-extraction-agent",
        },
        run_id=run_id,
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": "source-quality-agent",
            "decision": "approved",
            "notes": "神经预测编码主题相关，元数据可追踪。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/steward-owner-store"}],
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-owner-store", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "ingestion", "agentId": ingestor["agentId"], "agentRole": "source_ingestor"},
    )
    writeback_payload = {
        "status": "completed",
        "summary": "知识库管理员通过 1 条候选，直接入库。",
        "result": {
            "knowledgeBaseId": knowledge_base["knowledgeBaseId"],
            "candidate_summary": {
                "approved": {
                    "count": 1,
                    "candidates": [
                        {
                            "candidateId": source["candidateId"],
                            "title": source["title"],
                            "doi": "10.0000/steward-owner-store",
                            "overall_score": 88,
                            "relevance_score": 96,
                            "assessment_notes": "可直接支撑神经预测编码算法假设。",
                        }
                    ],
                }
            },
            "steward_assessment": {"decision": "approved", "targetDomain": "神经机制启发神经网络算法"},
        },
        "recordedByAgent": ingestor["agentId"],
        "evidenceRefs": [{"type": "candidate", "id": source["candidateId"]}],
        "nextActions": ["进入实验规划"],
    }

    _append_stage_task_tool_trace(tmp_path, task["task"])
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        writeback_payload,
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]
    assert materialized["status"] == "completed"
    assert materialized["stewardPackCandidateId"]

    # owner 店（工程 B）必须拿到 steward_pack_draft 候选；活跃工程 A 的店不得收留它。
    owner_store = team_workflow_orchestration_service._read_json(owner_store_path)
    owner_pack_candidates = [
        item
        for item in list(owner_store.get("candidates") or [])
        if isinstance(item, dict) and str((item.get("metadata") or {}).get("taskType") or "") == "steward_pack_draft"
    ]
    assert [str(item.get("candidateId") or "") for item in owner_pack_candidates] == [
        materialized["stewardPackCandidateId"]
    ]
    active_store = team_workflow_orchestration_service._read_json(active_store_path)
    active_pack_candidates = [
        item
        for item in list(active_store.get("candidates") or [])
        if isinstance(item, dict) and str((item.get("metadata") or {}).get("taskType") or "") == "steward_pack_draft"
    ]
    assert active_pack_candidates == []

    # 读兼容合并仍工作：活跃店候选通过 owner-first merged read 仍可见。
    stray = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "活跃店遗留候选",
            "createdByAgent": ingestor["agentId"],
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-legacy", "label": "Paper legacy"}],
                "evidenceRefs": [{"type": "review", "id": "review-legacy", "label": "Review legacy"}],
                "candidateIds": [source["candidateId"]],
                "proposalPayload": {"title": "活跃店遗留候选", "summary": "遗留", "excerpt": "遗留摘要", "ratingSuggestion": {"rating": 4, "confidence": 0.9}, "claims": [], "uncertainty": [], "riskSummary": "", "nextAction": "提交审核"},
            },
        },
    )["candidate"]
    merged = team_workflow_orchestration_service._load_candidate_store(team["teamId"], run_id=run_id)
    merged_ids = {str(item.get("candidateId") or "") for item in list(merged.get("candidates") or [])}
    assert materialized["stewardPackCandidateId"] in merged_ids
    assert stray["candidateId"] in merged_ids
    # 无 run 的读取仍以活跃店为视角。
    active_only = team_workflow_orchestration_service._load_candidate_store(team["teamId"])
    active_only_ids = {str(item.get("candidateId") or "") for item in list(active_only.get("candidates") or [])}
    assert stray["candidateId"] in active_only_ids
    assert materialized["stewardPackCandidateId"] not in active_only_ids


def test_run_scoped_steward_pack_write_records_reason_when_owner_unresolved(tmp_path, monkeypatch):
    """带 authority run 但 owner 工程不可解析（legacy/已删 run）时：保持历史活跃店
    目标（legacy 流程不破坏），但必须记录明确 reason 的 warning 事件并在返回里带
    candidateStoreScope，不静默漂移。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    active_store_path = team_workflow_orchestration_service._candidate_store_path(team["teamId"])

    recorded_events: list[tuple[tuple, dict]] = []
    real_record_event = team_workflow_orchestration_service.record_runtime_scene_event

    def _spy_record_event(*args, **kwargs):
        recorded_events.append((args, kwargs))
        return real_record_event(*args, **kwargs)

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "record_runtime_scene_event",
        _spy_record_event,
    )

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "owner 不可解析的包",
            "createdByAgent": "knowledge-steward",
            "output": {
                "candidateType": "review_record",
                "sourceRefs": [{"type": "paper", "id": "paper-x", "label": "Paper X"}],
                "evidenceRefs": [{"type": "review", "id": "review-x", "label": "Review X"}],
                "candidateIds": ["candidate-x"],
                "proposalPayload": {"title": "包", "summary": "摘要", "excerpt": "证据摘录", "ratingSuggestion": {"rating": 4, "confidence": 0.9}, "claims": [], "uncertainty": [], "riskSummary": "", "nextAction": "提交审核"},
            },
        },
        run_id="dprun-owner-unresolvable",
    )

    # 返回里带明确 reason。
    scope = response.get("candidateStoreScope")
    assert scope["requestedRunId"] == "dprun-owner-unresolvable"
    assert scope["resolvedRunId"] == ""
    assert scope["resolution"] == "active_project_owner_unresolved"
    # warning 事件带明确 reason，不静默。
    warning_events = [
        (args, kwargs)
        for args, kwargs in recorded_events
        if len(args) >= 3 and args[2] == "candidate.store_owner_project_unresolved"
    ]
    assert warning_events, "expected a store_owner_project_unresolved workflow event"
    event_fields = warning_events[0][0][3] if len(warning_events[0][0]) > 3 else warning_events[0][1].get("fields") or {}
    assert event_fields.get("runId") == "dprun-owner-unresolvable"
    assert event_fields.get("reason") == "authority_run_has_no_resolvable_owner_research_project"
    assert warning_events[0][1].get("level") == "warning"
    # 历史行为保持：候选仍写入活跃店（legacy run 场景不破坏）。
    store = team_workflow_orchestration_service._read_json(active_store_path)
    store_ids = {str(item.get("candidateId") or "") for item in list(store.get("candidates") or [])}
    assert response["candidate"]["candidateId"] in store_ids
