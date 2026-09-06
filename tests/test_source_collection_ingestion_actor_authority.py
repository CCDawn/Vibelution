from __future__ import annotations

from typing import Any

from tests._support.team_workflow.helpers import (
    _append_stage_task_tool_trace,
    _use_fake_local_research_config,
    _use_tmp_project_root,
    agent_directory_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)


def _prepare_ingestion_writeback_case(
    tmp_path,
    monkeypatch,
    *,
    include_ingestor_in_team: bool,
    recorded_by_agent: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)

    ingestor = agent_directory_service.create_agent_instance(display_name="资料入库")
    ingestor_session = session_service.ensure_agent_direct_session(
        agent_id=ingestor["agentId"],
        title="资料入库",
    )
    agent_directory_service.update_agent_instance(
        ingestor["agentId"],
        direct_session_id=ingestor_session["id"],
    )
    coordinator = agent_directory_service.create_agent_instance(display_name="科研协调")
    session_service.ensure_agent_direct_session(
        agent_id=coordinator["agentId"],
        title="科研协调",
    )
    members = [
        {
            "agentId": coordinator["agentId"],
            "role": "research_coordination",
            "agentName": "科研协调",
        }
    ]
    if include_ingestor_in_team:
        members.append(
            {
                "agentId": ingestor["agentId"],
                "role": "source_ingestor",
                "agentName": "资料入库",
            }
        )
    team = team_service.create_team(name="挑战杯科研团队", members=members)

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
            "sourceUrl": "https://doi.org/10.0000/ingestion-actor-authority",
            "sourceKind": "paper",
            "summary": "Neural predictive coding evidence for a governed knowledge item.",
            "tags": ["neuroscience", "algorithm"],
            "allowedForAnalysis": True,
            "metadata": {
                "sourceCollectionRunId": run_id,
                "doi": "10.0000/ingestion-actor-authority",
            },
            "createdByAgent": ingestor["agentId"],
        },
        run_id=run_id,
    )["candidate"]
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        source["candidateId"],
        {
            "assessedByAgent": coordinator["agentId"],
            "decision": "approved",
            "notes": "来源与主题相关，元数据可追踪。",
            "evidenceRefs": [{"type": "doi", "id": "10.0000/ingestion-actor-authority"}],
        },
        run_id=run_id,
    )

    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-ingestion-actor-authority",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {
            "stageId": "ingestion",
            "agentId": ingestor["agentId"],
            "agentRole": "source_ingestor",
        },
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])

    writeback = {
        "status": "completed",
        "summary": "知识库管理员通过 1 条候选，直接入库。",
        "result": {
            "candidate_summary": {
                "approved": {
                    "count": 1,
                    "candidates": [
                        {
                            "candidateId": source["candidateId"],
                            "title": source["title"],
                            "doi": "10.0000/ingestion-actor-authority",
                            "overall_score": 88,
                            "relevance_score": 96,
                            "assessment_notes": "可直接支撑受管知识条目。",
                        }
                    ],
                }
            },
            "steward_assessment": {
                "decision": "approved",
                "confidence": 0.95,
                "targetDomain": "神经机制启发神经网络算法",
            },
        },
        "recordedByAgent": recorded_by_agent,
        "evidenceRefs": [{"type": "candidate", "id": source["candidateId"]}],
        "nextActions": ["进入实验规划"],
    }
    return team, source, task, writeback


def test_ingestion_uses_canonical_task_actor_when_writeback_uses_display_name(
    tmp_path,
    monkeypatch,
):
    team, source, task, writeback = _prepare_ingestion_writeback_case(
        tmp_path,
        monkeypatch,
        include_ingestor_in_team=True,
        recorded_by_agent="知识管理 Agent (agent-display-name)",
    )
    captured: dict[str, str] = {}
    real_get_or_create = team_knowledge_service.get_or_create_team_knowledge_base

    def capture_get_or_create(team_id: str, **kwargs):
        captured["actorAgentId"] = str(kwargs.get("actor_agent_id") or "")
        return real_get_or_create(team_id, **kwargs)

    monkeypatch.setattr(
        team_knowledge_service,
        "get_or_create_team_knowledge_base",
        capture_get_or_create,
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"], task["taskId"], writeback
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]
    assert captured["actorAgentId"] == task["agentId"]
    assert captured["actorAgentId"] != writeback["recordedByAgent"]
    assert materialized["status"] == "completed"
    assert materialized["formalKnowledgeItemCount"] == 1
    assert source["title"]


def test_ingestion_does_not_authorize_non_member_from_writeback_actor(
    tmp_path,
    monkeypatch,
):
    team, _source, task, writeback = _prepare_ingestion_writeback_case(
        tmp_path,
        monkeypatch,
        include_ingestor_in_team=False,
        # This is a real Team member ID supplied through the untrusted
        # writeback payload. It must not authorize the non-member task actor.
        recorded_by_agent="agent-member-signature",
    )
    coordinator = next(
        member["agentId"]
        for member in team_service.get_team(team["teamId"])["members"]
        if member.get("role") == "research_coordination"
    )
    writeback["recordedByAgent"] = coordinator
    captured: dict[str, str] = {}
    real_get_or_create = team_knowledge_service.get_or_create_team_knowledge_base

    def capture_get_or_create(team_id: str, **kwargs):
        captured["actorAgentId"] = str(kwargs.get("actor_agent_id") or "")
        return real_get_or_create(team_id, **kwargs)

    monkeypatch.setattr(
        team_knowledge_service,
        "get_or_create_team_knowledge_base",
        capture_get_or_create,
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"], task["taskId"], writeback
    )

    materialized = response["writeback"]["materializedKnowledgeIngestion"]
    assert captured["actorAgentId"] == task["agentId"]
    assert captured["actorAgentId"] != coordinator
    assert materialized["status"] == "failed"
    assert materialized["failed"][0]["reason"] == "knowledge_ingestion_failed"
    assert "Only Team members can create a team knowledge base" in materialized["failed"][0]["error"]
    assert team_knowledge_service.list_team_knowledge_bases(
        team["teamId"], internal=True
    )["summary"]["knowledgeBaseCount"] == 0
