import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


@pytest.fixture()
def knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lead Agent", direct_session_id="session-lead")
    member = agent_directory_service.create_agent_instance(display_name="Member Agent", direct_session_id="session-member")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider Agent", direct_session_id="session-outsider")
    team = team_service.create_team(
        name="Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Shared Decisions",
        actor_agent_id=lead["agentId"],
    )
    return {"team": team, "base": base, "lead": lead, "member": member, "outsider": outsider}


def test_team_member_can_register_source_and_submit_proposal(knowledge_env):
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "from standup"},
        title="Standup source",
        summary="Decision source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Keep source links",
        content="Every knowledge item keeps source artifacts and timestamps.",
        tags=["memory-platform"],
    )

    assert proposal["status"] == "pending"
    assert proposal["sourceArtifactIds"] == [source["sourceArtifactId"]]


def test_non_member_cannot_submit_proposal(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_refinement_proposal(
            knowledge_env["base"]["knowledgeBaseId"],
            source_artifact_ids=[],
            proposed_by_agent_id=knowledge_env["outsider"]["agentId"],
            title="No access",
            content="This should be blocked.",
        )


def test_review_role_applies_proposal_into_batch_and_item(knowledge_env):
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Agent note",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Use proposal gate",
        summary="Formal knowledge is applied from proposals.",
        content="Agents submit candidates; leads apply them into batches.",
    )

    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert reviewed["proposal"]["status"] == "applied"
    assert reviewed["batch"]["sourceArtifactIds"] == [source["sourceArtifactId"]]
    assert reviewed["item"]["batchId"] == reviewed["batch"]["batchId"]
    assert reviewed["item"]["sourceArtifactIds"] == [source["sourceArtifactId"]]


def test_team_chat_refinement_requires_team_linked_room(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="linked chat room"):
        team_knowledge_service.create_source_artifact(
            knowledge_env["base"]["knowledgeBaseId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 0, "to": 1}},
            actor_agent_id=knowledge_env["member"]["agentId"],
        )

    linked_room_id = knowledge_env["team"]["linkedChatRoomId"]
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": linked_room_id, "messageRange": {"from": 0, "to": 1}},
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    assert source["sourceType"] == "team_chat_refinement"


def test_rating_update_records_marker_and_audit(knowledge_env, tmp_path):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Rate knowledge",
        content="Important knowledge can be marked later.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    rated = team_knowledge_service.update_knowledge_item_rating(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        importance_level="critical",
        confidence=0.95,
        stability="stable",
        scope="team",
        review_priority="urgent",
        marking_reason="Operationally required.",
    )

    assert rated["importanceLevel"] == "critical"
    assert rated["confidence"] == 0.95
    assert rated["markedBy"] == knowledge_env["lead"]["agentId"]
    audit_path = tmp_path / "workspace" / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "audit.jsonl"
    assert "knowledge.item.rating.updated" in audit_path.read_text(encoding="utf-8")
