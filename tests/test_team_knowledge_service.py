import pytest

from core.web.services import agent_directory_service, chat_room_service, memory_graph_service, team_knowledge_service, team_service


@pytest.fixture()
def knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_graph_service, "PROJECT_ROOT", tmp_path)
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


def _promote_central_source(
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
    title: str = "Test source",
    summary: str = "Governed test source.",
    original_content: str = "Governed test source content.",
) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        owner_type,
        owner_id,
        source_type=source_type,
        source_ref=source_ref or {"note": title},
        original_content=original_content,
        original_filename="test-source.txt",
        title=title,
        summary=summary,
        actor_agent_id=actor_agent_id,
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        owner_type,
        owner_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=reviewer_agent_id,
    )
    return reviewed["centralSource"]


def _create_central_source_artifact(
    knowledge_base_id: str,
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
    title: str = "Test source",
    summary: str = "Governed test source.",
) -> dict:
    central_source = _promote_central_source(
        owner_type=owner_type,
        owner_id=owner_id,
        actor_agent_id=actor_agent_id,
        reviewer_agent_id=reviewer_agent_id,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
        summary=summary,
    )
    return team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id,
        central_source["centralSourceId"],
        actor_agent_id=actor_agent_id,
        title=title,
        summary=summary,
    )


def _source_ids_for_env(knowledge_env: dict, *, title: str = "Test source") -> list[str]:
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title=title,
    )
    return [source["sourceArtifactId"]]


def test_team_member_can_register_source_and_submit_proposal(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Standup source",
        summary="Decision source",
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


def test_owner_inbox_promotes_source_to_central_registry_and_formal_artifact(knowledge_env, tmp_path):
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test/source", "query": "source governance"},
        original_content="Original external search capture for governed source storage.",
        original_filename="search-capture.txt",
        title="Governed source capture",
        summary="Captured source waits in the owner inbox before central promotion.",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    inbox_path = tmp_path / inbox_source["originalPath"]
    assert inbox_source["status"] == "pending"
    assert inbox_path.exists()
    assert "Original external search capture" in inbox_path.read_text(encoding="utf-8")
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_owner_source_inbox(
            "team",
            knowledge_env["team"]["teamId"],
            agent_id=knowledge_env["outsider"]["agentId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["member"]["agentId"],
        )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="Source is relevant and has preserved capture.",
    )
    central_source = reviewed["centralSource"]
    central_path = tmp_path / central_source["centralPath"]
    registry = team_knowledge_service.list_central_sources(agent_id=knowledge_env["member"]["agentId"])

    assert reviewed["source"]["status"] == "accepted"
    assert reviewed["promotion"]["dedupeStatus"] == "created"
    assert central_source["centralSourceId"]
    assert central_path.exists()
    assert registry["summary"]["centralSourceCount"] == 1
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["outsider"]["agentId"])["summary"]["centralSourceCount"] == 0

    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_env["base"]["knowledgeBaseId"],
        central_source["centralSourceId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Central source references survive review",
        content="Formal knowledge items should retain central source references for RAG citation provenance.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert source_artifact["centralSourceId"] == central_source["centralSourceId"]
    assert proposal["centralSourceIds"] == [central_source["centralSourceId"]]
    assert applied["item"]["centralSourceIds"] == [central_source["centralSourceId"]]


def test_agent_inbox_is_private_and_global_steward_can_promote(knowledge_env):
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "agent",
        knowledge_env["member"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"], "note": "private source"},
        original_content="Private Agent source should remain owner-scoped before central review.",
        title="Private Agent source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_owner_source_inbox(
            "agent",
            knowledge_env["member"]["agentId"],
            agent_id=knowledge_env["outsider"]["agentId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "agent",
            knowledge_env["member"]["agentId"],
            inbox_source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["outsider"]["agentId"],
        )

    reviewed = team_knowledge_service.review_owner_inbox_source(
        "agent",
        knowledge_env["member"]["agentId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
    )

    assert reviewed["centralSource"]["centralSourceId"]
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["member"]["agentId"])["summary"]["centralSourceCount"] == 1
    assert team_knowledge_service.list_central_sources(agent_id=knowledge_env["outsider"]["agentId"])["summary"]["centralSourceCount"] == 0


def test_central_source_registry_dedupes_by_source_hash(knowledge_env):
    first = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "duplicate source"},
        original_content="Same source body.",
        title="Duplicate source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    second = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "duplicate source"},
        original_content="Same source body.",
        title="Duplicate source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )

    first_review = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        first["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    second_review = team_knowledge_service.review_owner_inbox_source(
        "team",
        knowledge_env["team"]["teamId"],
        second["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    registry = team_knowledge_service.list_central_sources(agent_id=knowledge_env["lead"]["agentId"])

    assert first_review["centralSource"]["centralSourceId"] == second_review["centralSource"]["centralSourceId"]
    assert second_review["promotion"]["dedupeStatus"] == "reused"
    assert registry["summary"]["centralSourceCount"] == 1
    assert registry["summary"]["ownerRefCount"] == 2


def test_agent_formal_knowledge_is_private_and_governed(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    owner = agent_directory_service.create_agent_instance(display_name="Owner Agent")
    other = agent_directory_service.create_agent_instance(display_name="Other Agent")

    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Owner Private Formal Knowledge",
        actor_agent_id=owner["agentId"],
    )
    source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        actor_agent_id=owner["agentId"],
        reviewer_agent_id=owner["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": owner["agentId"], "note": "private formal memory"},
        title="Private source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=owner["agentId"],
        title="Private RAG boundary",
        content="Agent private formal knowledge can be governed and retrieved only by its owning Agent.",
        tags=["agent-private"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=owner["agentId"],
    )

    owner_results = team_knowledge_service.search_knowledge_items(
        agent_id=owner["agentId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        query="private formal knowledge",
        search_mode="semantic",
    )
    other_results = team_knowledge_service.search_knowledge_items(
        agent_id=other["agentId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        query="private formal knowledge",
        search_mode="semantic",
    )

    assert base["ownerType"] == "agent"
    assert base["ownerId"] == owner["agentId"]
    assert reviewed["item"]["ownerType"] == "agent"
    assert reviewed["item"]["agentId"] == owner["agentId"]
    assert owner_results["summary"]["resultCount"] == 1
    assert owner_results["results"][0]["ownerType"] == "agent"
    assert owner_results["results"][0]["agentId"] == owner["agentId"]
    assert other_results["summary"]["resultCount"] == 0
    assert (tmp_path / "workspace" / "agents" / owner["agentId"] / "knowledge" / "knowledge_bases.json").exists()


def test_duplicate_knowledge_base_ids_require_owner_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    first_agent = agent_directory_service.create_agent_instance(display_name="First KB Owner")
    second_agent = agent_directory_service.create_agent_instance(display_name="Second KB Owner")
    viewer = agent_directory_service.create_agent_instance(display_name="Duplicate KB Viewer")
    first_team = team_service.create_team(name="First KB Team", members=[{"agentId": first_agent["agentId"], "role": "lead"}])
    second_team = team_service.create_team(name="Second KB Team", members=[{"agentId": second_agent["agentId"], "role": "lead"}])
    first_base = team_knowledge_service.create_knowledge_base(
        first_team["teamId"],
        name="Duplicate KB",
        actor_agent_id=first_agent["agentId"],
        acl={"grants": {"read": [viewer["agentId"]]}},
    )
    second_base = team_knowledge_service.create_knowledge_base(
        second_team["teamId"],
        name="Duplicate KB",
        actor_agent_id=second_agent["agentId"],
        acl={"grants": {"read": [viewer["agentId"]]}},
    )

    assert first_base["knowledgeBaseId"] == second_base["knowledgeBaseId"]
    assert first_base["scopedKnowledgeBaseId"] != second_base["scopedKnowledgeBaseId"]
    with pytest.raises(team_knowledge_service.TeamKnowledgeAmbiguousKnowledgeBaseError):
        team_knowledge_service.list_knowledge_items(first_base["knowledgeBaseId"], agent_id=first_agent["agentId"])
    with pytest.raises(team_knowledge_service.TeamKnowledgeAmbiguousKnowledgeBaseError):
        team_knowledge_service.search_knowledge_items(
            agent_id=viewer["agentId"],
            knowledge_base_id=first_base["knowledgeBaseId"],
        )

    scoped_source = _create_central_source_artifact(
        first_base["scopedKnowledgeBaseId"],
        owner_type="team",
        owner_id=first_team["teamId"],
        actor_agent_id=first_agent["agentId"],
        reviewer_agent_id=first_agent["agentId"],
        title="First scoped source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        source_artifact_ids=[scoped_source["sourceArtifactId"]],
        proposed_by_agent_id=first_agent["agentId"],
        title="First scoped item",
        content="Only the scoped first knowledge base should receive this item.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=first_agent["agentId"],
    )
    scoped_items = team_knowledge_service.list_knowledge_items(
        first_base["scopedKnowledgeBaseId"],
        agent_id=first_agent["agentId"],
    )
    second_items = team_knowledge_service.list_knowledge_items(
        second_base["scopedKnowledgeBaseId"],
        agent_id=second_agent["agentId"],
    )

    assert scoped_items["summary"]["itemCount"] == 1
    assert scoped_items["items"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert second_items["summary"]["itemCount"] == 0


def test_empty_actor_cannot_create_or_read_governed_knowledge_service(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_knowledge_base(
            knowledge_env["team"]["teamId"],
            name="Anonymous Team KB",
        )

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.create_agent_knowledge_base(
            knowledge_env["member"]["agentId"],
            name="Anonymous Agent KB",
        )

    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Empty actor source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Empty actor service guard",
        content="Empty actor service calls must not read governed knowledge.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert team_knowledge_service.list_knowledge_overview()["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.list_knowledge_governance_tasks(status="all")["summary"]["taskCount"] == 0
    assert team_knowledge_service.get_knowledge_operations_health()["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.get_knowledge_governance_plan()["summary"]["actionCount"] == 0
    assert team_knowledge_service.list_knowledge_steward_recommendations()["summary"]["recommendationCount"] == 0
    assert team_knowledge_service.get_knowledge_steward_workbench()["summary"]["openTaskCount"] == 0
    assert team_knowledge_service.get_knowledge_dashboard_snapshot()["overview"]["summary"]["knowledgeBaseCount"] == 0
    assert team_knowledge_service.get_knowledge_steward_overview()["governance"]["summary"]["openTaskCount"] == 0
    assert team_knowledge_service.search_knowledge_items(query="empty actor")["summary"]["resultCount"] == 0

    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_knowledge_items(knowledge_env["base"]["knowledgeBaseId"])
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.get_knowledge_trace(
            knowledge_env["base"]["knowledgeBaseId"],
            reviewed["item"]["knowledgeItemId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.list_rating_suggestions(knowledge_env["base"]["knowledgeBaseId"])

    internal_overview = team_knowledge_service.list_knowledge_overview(internal=True)
    internal_health = team_knowledge_service.get_knowledge_operations_health(internal=True)

    assert internal_overview["summary"]["knowledgeBaseCount"] == 1
    assert internal_health["summary"]["knowledgeBaseCount"] == 1


def test_team_knowledge_memory_section_summary_uses_lightweight_disk_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lead Agent")
    team = team_service.create_team(name="Knowledge Team", members=[{"agentId": lead["agentId"], "role": "lead"}])
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Shared Decisions",
        actor_agent_id=lead["agentId"],
    )
    source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=lead["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="Summary source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=lead["agentId"],
        title="Pending summary proposal",
        content="Pending proposal should be counted by the lightweight summary.",
    )
    team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=lead["agentId"],
    )
    pending_source = _create_central_source_artifact(
        base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=lead["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="Still pending source",
    )
    team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[pending_source["sourceArtifactId"]],
        proposed_by_agent_id=lead["agentId"],
        title="Still pending",
        content="This proposal remains pending.",
    )

    def fail_full_overview(**_kwargs):
        raise AssertionError("memory summary must not call full list_knowledge_overview")

    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", fail_full_overview)

    summary = team_knowledge_service.team_knowledge_memory_section_summary()

    assert summary["knowledgeBaseCount"] == 1
    assert summary["pendingProposalCount"] == 1
    assert summary["itemCount"] == 1
    assert summary["sourceArtifactCount"] == 2
    assert summary["updatedAt"]


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
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Agent note",
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


def test_team_chat_refinement_source_collection_requires_team_linked_room(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="linked chat room"):
        team_knowledge_service.collect_source_to_inbox(
            "team",
            knowledge_env["team"]["teamId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 0, "to": 1}},
            actor_agent_id=knowledge_env["member"]["agentId"],
        )

    linked_room_id = knowledge_env["team"]["linkedChatRoomId"]
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": linked_room_id, "messageRange": {"from": 0, "to": 1}},
    )
    assert source["sourceType"] == "team_chat_refinement"


def test_rating_update_records_marker_and_audit(knowledge_env, tmp_path):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Rate knowledge source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
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


def test_rating_suggestion_is_reviewable_before_item_update(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Suggested rating source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Suggested rating",
        content="A reviewer should apply rating suggestions before item metadata changes.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    suggestion = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=reviewed["item"]["knowledgeItemId"],
        importance_level="critical",
        confidence=0.96,
        stability="stable",
        review_priority="urgent",
        marking_reason="Management agent suggests promotion.",
    )
    before = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )["items"][0]

    assert suggestion["status"] == "pending"
    assert before["importanceLevel"] == "medium"

    applied = team_knowledge_service.review_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion["suggestionId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    assert applied["suggestion"]["status"] == "applied"
    assert applied["item"]["importanceLevel"] == "critical"
    assert applied["item"]["markedBy"] == knowledge_env["lead"]["agentId"]


def test_rating_suggestion_bulk_review_applies_pending_and_skips_closed(knowledge_env, tmp_path):
    proposal_one = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Bulk rating one source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Bulk rating one",
        content="First item should receive bulk rating.",
    )
    proposal_two = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Bulk rating two source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Bulk rating two",
        content="Second item should receive bulk rating.",
    )
    item_one = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal_one["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )["item"]
    item_two = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal_two["proposalId"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )["item"]
    suggestion_one = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=item_one["knowledgeItemId"],
        importance_level="critical",
        confidence=0.91,
        stability="stable",
        review_priority="urgent",
        marking_reason="Bulk promotion one.",
    )
    suggestion_two = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=item_two["knowledgeItemId"],
        importance_level="high",
        confidence=0.81,
        stability="evolving",
        review_priority="elevated",
        marking_reason="Bulk promotion two.",
    )
    team_knowledge_service.review_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion_two["suggestionId"],
        status="rejected",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    result = team_knowledge_service.review_rating_suggestions_bulk(
        knowledge_env["base"]["knowledgeBaseId"],
        suggestion_ids=[suggestion_one["suggestionId"], suggestion_two["suggestionId"], "missing-suggestion"],
        status="applied",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="Batch queue reviewed.",
    )

    assert result["summary"] == {
        "requestedCount": 3,
        "reviewedCount": 1,
        "skippedCount": 2,
        "appliedItemCount": 1,
    }
    assert {item["reason"] for item in result["skipped"]} == {"not_pending", "not_found"}
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )["items"]
    rated_item = next(item for item in items if item["knowledgeItemId"] == item_one["knowledgeItemId"])
    untouched_item = next(item for item in items if item["knowledgeItemId"] == item_two["knowledgeItemId"])
    assert rated_item["importanceLevel"] == "critical"
    assert untouched_item["importanceLevel"] == "medium"
    audit_path = tmp_path / "workspace" / "teams" / knowledge_env["team"]["teamId"] / "knowledge" / "audit.jsonl"
    assert "knowledge.rating_suggestion.bulk_reviewed" in audit_path.read_text(encoding="utf-8")


def test_search_filters_only_visible_formal_items(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Searchable source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Searchable governance knowledge",
        content="Formal knowledge search should include reviewed items only.",
        tags=["governance", "search"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.update_knowledge_item_rating(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        importance_level="high",
    )

    member_results = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        query="governance",
        tags=["search"],
        importance_level="high",
    )
    outsider_results = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["outsider"]["agentId"],
        query="governance",
    )

    assert member_results["summary"]["resultCount"] == 1
    assert member_results["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert outsider_results["summary"]["resultCount"] == 0


def test_permission_audit_explains_tool_memory_and_team_boundaries(knowledge_env):
    agent_directory_service.update_agent_instance(
        knowledge_env["member"]["agentId"],
        tool_policy={"allowedTools": ["knowledge_query_tool"]},
        memory_policy={"readKnowledgeBaseIds": [knowledge_env["base"]["knowledgeBaseId"]]},
    )

    audit = team_knowledge_service.knowledge_permission_audit(agent_id=knowledge_env["member"]["agentId"])

    assert audit["tools"]["knowledge_query_tool"]["visible"] is True
    assert audit["tools"]["knowledge_proposal_tool"]["reason"] == "available"
    row = audit["knowledgeBases"][0]
    assert row["permissions"]["read"]["allowed"] is True
    assert row["permissions"]["review"]["allowed"] is False
    assert row["permissions"]["review"]["reason"] == "team_acl_blocked"


def test_ingestion_package_creates_source_and_pending_proposal_only(knowledge_env):
    central_source = _promote_central_source(
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="pdf_refinement",
        source_ref={"filePath": "workspace/research/report.pdf", "pageRange": "3-5"},
        title="Report pages 3-5",
        summary="PDF evidence about memory governance.",
    )
    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="pdf_refinement",
        source_ref={"filePath": "workspace/research/report.pdf", "pageRange": "3-5"},
        source_title="Report pages 3-5",
        source_summary="PDF evidence about memory governance.",
        excerpt="The PDF says governance knowledge must keep source pages.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        proposal_title="Keep PDF page provenance",
        tags=["pdf", "governance"],
        central_source_id=central_source["centralSourceId"],
    )
    items = team_knowledge_service.list_knowledge_items(
        knowledge_env["base"]["knowledgeBaseId"],
        agent_id=knowledge_env["member"]["agentId"],
    )

    assert package["status"] == "submitted"
    assert package["sourceArtifact"]["sourceType"] == "pdf_refinement"
    assert package["proposal"]["status"] == "pending"
    assert package["proposal"]["sourceArtifactIds"] == [package["sourceArtifact"]["sourceArtifactId"]]
    assert items["summary"]["itemCount"] == 0


def test_governance_tasks_adapters_and_trace_are_readable(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Orphan source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Traceable proposal",
        content="Traceable knowledge proposal.",
    )

    tasks = team_knowledge_service.list_knowledge_governance_tasks(agent_id=knowledge_env["lead"]["agentId"])
    adapters = team_knowledge_service.list_ingestion_adapters()
    trace = team_knowledge_service.get_knowledge_trace(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        agent_id=knowledge_env["member"]["agentId"],
    )

    assert tasks["summary"]["proposalReviewCount"] == 1
    assert any(task["taskType"] == "proposal_review" for task in tasks["tasks"])
    assert adapters["summary"]["adapterCount"] == len(team_knowledge_service.SOURCE_TYPES)
    assert trace["targetType"] == "proposal"
    assert trace["summary"]["sourceArtifacts"] == 1
    assert trace["summary"]["proposals"] == 1


def test_memory_knowledge_graph_links_project_agents_team_and_knowledge_without_bodies(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"], "excerpt": "do not expose source body"},
        title="Graph source",
        summary="Graph source summary.",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Graph proposal",
        summary="Graph proposal summary.",
        content="SECRET FORMAL KNOWLEDGE BODY SHOULD NOT LEAK",
        tags=["graph"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    node_types = {node["type"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    payload_text = str(graph)

    assert graph["mode"] == "read_only_project_memory_graph"
    assert graph["operatingBoundary"]["readOnly"] is True
    assert graph["operatingBoundary"]["gpuPreferred"] is True
    assert {"project", "team", "agent"}.issubset(node_types)
    assert not {"agent_private_memory", "knowledge_base", "knowledge_item", "source_artifact"}.intersection(node_types)
    assert {"project_has_team", "team_has_agent"}.issubset(edge_types)
    member_node = next(
        node for node in graph["nodes"]
        if node["type"] == "agent" and node["metadata"]["agentId"] == knowledge_env["member"]["agentId"]
    )
    team_node = next(node for node in graph["nodes"] if node["type"] == "team")
    assert member_node["visual"]["agentCategory"] == "team_member_agent"
    assert member_node["responsibilityQuestion"]
    assert {member_node["id"], f"agent:{knowledge_env['lead']['agentId']}"}.issubset(set(team_node["childNodeIds"]))
    assert member_node["contentItems"] == []
    assert team_node["contentItems"][0]["title"] == "Graph proposal"
    assert reviewed["item"]["knowledgeItemId"] in payload_text
    assert "SECRET FORMAL KNOWLEDGE BODY SHOULD NOT LEAK" not in payload_text
    assert "do not expose source body" not in payload_text


def test_memory_knowledge_graph_node_detail_returns_acl_scoped_full_content(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Node detail source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Node detail knowledge",
        summary="Node detail summary.",
        content="NODE DETAIL FORMAL KNOWLEDGE BODY",
        tags=["node-detail"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    member_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"team:{knowledge_env['team']['teamId']}",
        agent_id=knowledge_env["member"]["agentId"],
    )
    item_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"knowledge_item:{reviewed['item']['knowledgeItemId']}",
        agent_id=knowledge_env["member"]["agentId"],
    )
    outsider_detail = memory_graph_service.get_memory_knowledge_graph_node_detail(
        f"team:{knowledge_env['team']['teamId']}",
        agent_id=knowledge_env["outsider"]["agentId"],
    )

    assert "NODE DETAIL FORMAL KNOWLEDGE BODY" not in str(graph)
    assert member_detail is not None
    assert member_detail["operatingBoundary"]["fullContentIncluded"] is True
    assert member_detail["summaryCounts"]["contentItemCount"] == 1
    assert member_detail["contentItems"][0]["content"] == "NODE DETAIL FORMAL KNOWLEDGE BODY"
    assert member_detail["contentItems"][0]["fullContentIncluded"] is True
    assert item_detail is not None
    assert item_detail["contentItems"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert item_detail["contentItems"][0]["content"] == "NODE DETAIL FORMAL KNOWLEDGE BODY"
    assert outsider_detail is None


def test_memory_knowledge_graph_expands_official_research_trace_on_include(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="agent_authored",
        source_ref={"agentId": knowledge_env["member"]["agentId"]},
        title="Official graph source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Official graph item",
        summary="Trace summary.",
        content="OFFICIAL GRAPH BODY SHOULD NOT LEAK",
        tags=["challenge-cup"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.update_knowledge_item_metadata(
        knowledge_env["base"]["knowledgeBaseId"],
        reviewed["item"]["knowledgeItemId"],
        actor_agent_id=knowledge_env["lead"]["agentId"],
        metadata_patch={
            "officialResearchGraph": {
                "status": "synced",
                "graphKind": "formal_research_trace",
                "summary": {"edgeCount": 2},
                "edges": [
                    {
                        "sourceId": "paper-note-1",
                        "sourceType": "paper_note",
                        "targetId": reviewed["item"]["knowledgeItemId"],
                        "targetType": "knowledge_item",
                        "relation": "supports",
                        "edgeState": "official_synced",
                    },
                    {
                        "sourceId": "hypothesis-1",
                        "sourceType": "algorithm_hypothesis",
                        "targetId": reviewed["item"]["knowledgeItemId"],
                        "targetType": "knowledge_item",
                        "relation": "inspires",
                        "edgeState": "official_synced",
                    },
                ],
            }
        },
    )

    default_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    expanded_graph = memory_graph_service.get_memory_knowledge_graph(
        agent_id=knowledge_env["member"]["agentId"],
        include="officialResearchGraph",
    )
    expanded_text = str(expanded_graph)
    node_types = {node["type"] for node in expanded_graph["nodes"]}
    edge_types = {edge["type"] for edge in expanded_graph["edges"]}

    assert default_graph["summary"]["nodeTypeCounts"].get("knowledge_item", 0) == 0
    assert {"knowledge_base", "knowledge_item", "official_research_ref"}.issubset(node_types)
    assert {"team_has_knowledge_base", "knowledge_base_has_item", "official_supports", "official_inspires"}.issubset(edge_types)
    assert any(node["metadata"].get("sourceId") == "paper-note-1" for node in expanded_graph["nodes"])
    assert reviewed["item"]["knowledgeItemId"] in expanded_text
    assert "OFFICIAL GRAPH BODY SHOULD NOT LEAK" not in expanded_text


def test_memory_knowledge_graph_honors_team_knowledge_acl(knowledge_env):
    team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="ACL source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Visible only to members",
        content="hidden body",
    )

    member_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])
    outsider_graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["outsider"]["agentId"])

    assert any(
        node["type"] == "team" and node["metadata"]["teamId"] == knowledge_env["team"]["teamId"]
        for node in member_graph["nodes"]
    )
    assert not any(
        node["type"] == "team" and node["metadata"].get("teamId") == knowledge_env["team"]["teamId"]
        for node in outsider_graph["nodes"]
    )


def test_memory_knowledge_graph_uses_lightweight_team_graph_references(knowledge_env, monkeypatch):
    def fail_compact(*, include_archived: bool = False):
        raise AssertionError("memory graph must not hydrate compact team chat rooms")

    monkeypatch.setattr(team_service, "list_teams_compact", fail_compact)

    graph = memory_graph_service.get_memory_knowledge_graph(agent_id=knowledge_env["member"]["agentId"])

    assert any(
        node["type"] == "team" and node["metadata"]["teamId"] == knowledge_env["team"]["teamId"]
        for node in graph["nodes"]
    )


def test_steward_recommendations_are_read_only_actions(knowledge_env):
    orphan_source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Source without proposal",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Recommendation proposal source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Proposal needing review",
        content="Reviewer should inspect this candidate.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=applied["item"]["knowledgeItemId"],
        importance_level="critical",
        confidence=0.9,
        stability="stable",
        review_priority="urgent",
        marking_reason="Core knowledge should be marked critical.",
    )

    payload = team_knowledge_service.list_knowledge_steward_recommendations(agent_id=knowledge_env["lead"]["agentId"])

    actions = {item["recommendedAction"] for item in payload["recommendations"]}
    assert "draft_refinement_proposal" in actions
    assert "review_rating_suggestion" in actions
    assert any(item["targetId"] == orphan_source["sourceArtifactId"] for item in payload["recommendations"])
    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["summary"]["proposalDraftCount"] == 1
    assert payload["summary"]["ratingReviewCount"] == 1


def test_steward_workbench_groups_actions_without_applying_knowledge(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Workbench source without proposal",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Workbench proposal source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Workbench proposal",
        content="Workbench should show this proposal without applying it.",
    )

    payload = team_knowledge_service.get_knowledge_steward_workbench(agent_id=knowledge_env["lead"]["agentId"], limit=5)

    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["summary"]["openTaskCount"] >= 2
    assert {stage["stageId"] for stage in payload["stages"]} == {"source_to_proposal", "proposal_review", "rating_review"}
    source_stage = next(stage for stage in payload["stages"] if stage["stageId"] == "source_to_proposal")
    proposal_stage = next(stage for stage in payload["stages"] if stage["stageId"] == "proposal_review")
    assert any(item["targetId"] == source["sourceArtifactId"] for item in source_stage["items"])
    assert any(item["targetId"] == proposal["proposalId"] for item in proposal_stage["items"])
    assert payload["acceptanceChecklist"][0]["required"] is True
    assert not team_knowledge_service.list_knowledge_items(knowledge_env["base"]["knowledgeBaseId"], agent_id=knowledge_env["lead"]["agentId"])["items"]


def test_ingestion_package_preserves_team_chat_room_guard(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="linked chat room"):
        central_source = _promote_central_source(
            owner_type="team",
            owner_id=knowledge_env["team"]["teamId"],
            actor_agent_id=knowledge_env["member"]["agentId"],
            reviewer_agent_id=knowledge_env["lead"]["agentId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 1, "to": 4}},
            title="Unlinked chat source",
        )
        team_knowledge_service.create_ingestion_package(
            knowledge_env["base"]["knowledgeBaseId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 1, "to": 4}},
            excerpt="Unlinked chat room must be rejected.",
            proposed_by_agent_id=knowledge_env["member"]["agentId"],
            central_source_id=central_source["centralSourceId"],
        )

    linked_central_source = _promote_central_source(
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": knowledge_env["team"]["linkedChatRoomId"], "messageRange": {"from": 1, "to": 4}},
        title="Linked chat source",
    )
    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": knowledge_env["team"]["linkedChatRoomId"], "messageRange": {"from": 1, "to": 4}},
        excerpt="Linked room decisions can become pending proposals.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        central_source_id=linked_central_source["centralSourceId"],
    )

    assert package["sourceArtifact"]["sourceRef"]["roomId"] == knowledge_env["team"]["linkedChatRoomId"]
    assert package["proposal"]["status"] == "pending"


def test_semantic_search_matches_token_overlap_without_exact_substring(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Planner cadence source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Planner cadence",
        content="Governance planner health signals should be visible before reviewer action.",
        tags=["ops"],
    )
    team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )

    exact = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        query="health governance missing",
        search_mode="exact",
    )
    semantic = team_knowledge_service.search_knowledge_items(
        agent_id=knowledge_env["member"]["agentId"],
        knowledge_base_id=knowledge_env["base"]["knowledgeBaseId"],
        query="health governance missing",
        search_mode="semantic",
    )

    assert exact["summary"]["resultCount"] == 0
    assert semantic["summary"]["resultCount"] == 1
    assert semantic["results"][0]["semanticScore"] > 0
    assert semantic["results"][0]["matchReason"] == "token_overlap"


def test_operations_health_reports_orphan_pending_and_unrated_items(knowledge_env):
    source = _create_central_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=knowledge_env["team"]["teamId"],
        actor_agent_id=knowledge_env["member"]["agentId"],
        reviewer_agent_id=knowledge_env["lead"]["agentId"],
        title="Orphan source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Pending health source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Pending health proposal",
        content="Pending proposal should be reported.",
    )
    applied = team_knowledge_service.review_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    pending_rating = team_knowledge_service.create_rating_suggestion(
        knowledge_env["base"]["knowledgeBaseId"],
        suggested_by_agent_id=knowledge_env["lead"]["agentId"],
        target_type="knowledge_item",
        knowledge_item_id=applied["item"]["knowledgeItemId"],
        importance_level="high",
        stability="stable",
        review_priority="elevated",
    )

    health = team_knowledge_service.get_knowledge_operations_health(agent_id=knowledge_env["member"]["agentId"])

    assert health["summary"]["knowledgeBaseCount"] == 1
    assert health["summary"]["orphanSourceCount"] == 1
    assert health["summary"]["pendingRatingSuggestionCount"] == 1
    assert health["summary"]["unratedItemCount"] == 1
    finding_types = {finding["findingType"] for finding in health["findings"]}
    assert {"orphan_sources", "pending_rating_suggestions", "unrated_items"}.issubset(finding_types)
    assert source["sourceArtifactId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]
    assert pending_rating["suggestionId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]


def test_governance_plan_is_read_only_and_links_tools(knowledge_env):
    team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=_source_ids_for_env(knowledge_env, title="Plan source"),
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Plan proposal",
        content="Governance plan should recommend review without applying.",
    )

    plan = team_knowledge_service.get_knowledge_governance_plan(agent_id=knowledge_env["lead"]["agentId"], limit=4)

    assert plan["mode"] == "recommendations_only"
    assert plan["operatingBoundary"]["planOnly"] is True
    assert plan["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert plan["operatingBoundary"]["canDeleteKnowledge"] is False
    assert plan["actions"]
    assert plan["actions"][0]["mutatesFormalKnowledge"] is False
    assert plan["actions"][0]["recommendedTool"] == "knowledge_governance_tasks_tool"
