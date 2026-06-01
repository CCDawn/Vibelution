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


def test_rating_suggestion_is_reviewable_before_item_update(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
        source_artifact_ids=[],
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
        title="Bulk rating one",
        content="First item should receive bulk rating.",
    )
    proposal_two = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
        source_artifact_ids=[],
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
    assert audit["tools"]["knowledge_proposal_tool"]["reason"] == "tool_policy_blocked"
    row = audit["knowledgeBases"][0]
    assert row["permissions"]["read"]["allowed"] is True
    assert row["permissions"]["review"]["allowed"] is False
    assert row["permissions"]["review"]["reason"] == "team_acl_blocked"


def test_ingestion_package_creates_source_and_pending_proposal_only(knowledge_env):
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
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "orphan source"},
        title="Orphan source",
        actor_agent_id=knowledge_env["member"]["agentId"],
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


def test_steward_recommendations_are_read_only_actions(knowledge_env):
    orphan_source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "needs proposal"},
        title="Source without proposal",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "workbench source"},
        title="Workbench source without proposal",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
        team_knowledge_service.create_ingestion_package(
            knowledge_env["base"]["knowledgeBaseId"],
            source_type="team_chat_refinement",
            source_ref={"roomId": "room-not-linked", "messageRange": {"from": 1, "to": 4}},
            excerpt="Unlinked chat room must be rejected.",
            proposed_by_agent_id=knowledge_env["member"]["agentId"],
        )

    package = team_knowledge_service.create_ingestion_package(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="team_chat_refinement",
        source_ref={"roomId": knowledge_env["team"]["linkedChatRoomId"], "messageRange": {"from": 1, "to": 4}},
        excerpt="Linked room decisions can become pending proposals.",
        proposed_by_agent_id=knowledge_env["member"]["agentId"],
    )

    assert package["sourceArtifact"]["sourceRef"]["roomId"] == knowledge_env["team"]["linkedChatRoomId"]
    assert package["proposal"]["status"] == "pending"


def test_semantic_search_matches_token_overlap_without_exact_substring(knowledge_env):
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
    source = team_knowledge_service.create_source_artifact(
        knowledge_env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "orphan"},
        title="Orphan source",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
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
        source_artifact_ids=[],
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
