import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


def _source_artifact(
    knowledge_base_id: str,
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    title: str,
    source_type: str = "manual_user_entry",
) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        owner_type,
        owner_id,
        source_type=source_type,
        source_ref={"note": title},
        original_content="Vector test source content.",
        original_filename="vector-source.txt",
        title=title,
        actor_agent_id=actor_agent_id,
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        owner_type,
        owner_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=reviewer_agent_id,
    )
    return team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id,
        reviewed["centralSource"]["centralSourceId"],
        actor_agent_id=actor_agent_id,
        title=title,
    )


@pytest.fixture()
def vector_index_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)

    lead = agent_directory_service.create_agent_instance(display_name="Vector Lead")
    member = agent_directory_service.create_agent_instance(display_name="Vector Member")
    team = team_service.create_team(
        name="Vector Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Vector Base",
        actor_agent_id=lead["agentId"],
        acl={"grants": {"review": [lead["agentId"]]}},
    )
    source = _source_artifact(
        base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=member["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="Vector source",
    )
    approved_proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=member["agentId"],
        title="Approved vector knowledge",
        summary="Only approved formal knowledge should be indexable.",
        content="Vector indexing must keep citations and never index pending proposal text.",
        tags=["rag", "vector"],
    )
    approved_item = team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        approved_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=lead["agentId"],
    )["item"]
    pending_proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[
            _source_artifact(
                base["knowledgeBaseId"],
                owner_type="team",
                owner_id=team["teamId"],
                actor_agent_id=member["agentId"],
                reviewer_agent_id=lead["agentId"],
                title="Pending vector source",
            )["sourceArtifactId"]
        ],
        proposed_by_agent_id=member["agentId"],
        title="Pending vector proposal",
        summary="This pending proposal must not be indexable yet.",
        content="Pending proposal content is still unreviewed.",
        tags=["rag", "pending"],
    )
    return {
        "tmpPath": tmp_path,
        "team": team,
        "base": base,
        "lead": lead,
        "member": member,
        "approvedItem": approved_item,
        "pendingProposal": pending_proposal,
        "source": source,
    }


def test_vector_index_lists_only_reviewed_formal_knowledge(vector_index_env):
    from core.web.services import rag_vector_index_service

    assert rag_vector_index_service.list_indexable_knowledge_items() == []

    items = rag_vector_index_service.list_indexable_knowledge_items(internal=True)

    assert [item["knowledgeItemId"] for item in items] == [vector_index_env["approvedItem"]["knowledgeItemId"]]
    indexable = items[0]
    assert indexable["teamId"] == vector_index_env["team"]["teamId"]
    assert indexable["knowledgeBaseId"] == vector_index_env["base"]["knowledgeBaseId"]
    assert indexable["sourceArtifactIds"] == [vector_index_env["source"]["sourceArtifactId"]]
    assert indexable["contentHash"]
    assert vector_index_env["pendingProposal"]["proposalId"] not in str(indexable)


def test_vector_index_keeps_central_source_ids_and_uses_unified_rag_root(vector_index_env):
    from core.web.services import rag_vector_index_service

    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        vector_index_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "central vector source"},
        original_content="Central vector source original file.",
        title="Central vector source",
        actor_agent_id=vector_index_env["member"]["agentId"],
    )
    reviewed_source = team_knowledge_service.review_owner_inbox_source(
        "team",
        vector_index_env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=vector_index_env["lead"]["agentId"],
    )
    central_source_id = reviewed_source["centralSource"]["centralSourceId"]
    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        vector_index_env["base"]["knowledgeBaseId"],
        central_source_id,
        actor_agent_id=vector_index_env["member"]["agentId"],
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        vector_index_env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=vector_index_env["member"]["agentId"],
        title="Central vector item",
        content="Central source ids should flow into vector index metadata.",
    )
    reviewed_item = team_knowledge_service.review_refinement_proposal(
        vector_index_env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=vector_index_env["lead"]["agentId"],
    )["item"]

    indexable = [
        item
        for item in rag_vector_index_service.list_indexable_knowledge_items(internal=True)
        if item["knowledgeItemId"] == reviewed_item["knowledgeItemId"]
    ][0]
    record = rag_vector_index_service.write_index_record(indexable, embedding_provider="test", embedding_model="central-v1")

    assert indexable["centralSourceIds"] == [central_source_id]
    assert record["centralSourceIds"] == [central_source_id]
    assert (vector_index_env["tmpPath"] / "workspace" / "knowledge" / "rag" / "index.json").exists()


def test_vector_index_metadata_includes_agent_owner_partition(tmp_path, monkeypatch):
    from core.web.services import rag_vector_index_service

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Vector Owner Agent")
    base = team_knowledge_service.create_agent_knowledge_base(
        agent["agentId"],
        name="Agent Vector Base",
        actor_agent_id=agent["agentId"],
    )
    source = _source_artifact(
        base["knowledgeBaseId"],
        owner_type="agent",
        owner_id=agent["agentId"],
        actor_agent_id=agent["agentId"],
        reviewer_agent_id=agent["agentId"],
        source_type="agent_authored",
        title="Agent vector source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=agent["agentId"],
        title="Agent vector partition",
        content="Vector metadata should preserve the Agent owner partition.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=agent["agentId"],
    )["item"]

    item = rag_vector_index_service.list_indexable_knowledge_items(agent_id=agent["agentId"])[0]
    record = rag_vector_index_service.write_index_record(item, embedding_provider="test", embedding_model="owner-v1")
    health = rag_vector_index_service.get_vector_index_health(agent_id=agent["agentId"])

    assert item["knowledgeItemId"] == reviewed["knowledgeItemId"]
    assert item["ownerType"] == "agent"
    assert item["ownerId"] == agent["agentId"]
    assert item["agentId"] == agent["agentId"]
    assert record["ownerType"] == "agent"
    assert record["ownerId"] == agent["agentId"]
    assert health["items"][0]["ownerType"] == "agent"
    assert health["items"][0]["ownerId"] == agent["agentId"]


def test_vector_index_records_are_owner_scoped_for_duplicate_item_ids(tmp_path, monkeypatch):
    from core.web.services import rag_vector_index_service

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    original_new_event_id = team_knowledge_service._new_event_id

    def fake_new_event_id(prefix: str) -> str:
        if prefix == "kitem":
            return "kitem-shared-vector"
        return original_new_event_id(prefix)

    monkeypatch.setattr(team_knowledge_service, "_new_event_id", fake_new_event_id)
    first_agent = agent_directory_service.create_agent_instance(display_name="Vector Collision One")
    second_agent = agent_directory_service.create_agent_instance(display_name="Vector Collision Two")
    first_base = team_knowledge_service.create_agent_knowledge_base(
        first_agent["agentId"],
        name="Collision Vector Base",
        actor_agent_id=first_agent["agentId"],
    )
    second_base = team_knowledge_service.create_agent_knowledge_base(
        second_agent["agentId"],
        name="Collision Vector Base",
        actor_agent_id=second_agent["agentId"],
    )
    first_source = _source_artifact(
        first_base["scopedKnowledgeBaseId"],
        owner_type="agent",
        owner_id=first_agent["agentId"],
        actor_agent_id=first_agent["agentId"],
        reviewer_agent_id=first_agent["agentId"],
        source_type="agent_authored",
        title="First vector source",
    )
    second_source = _source_artifact(
        second_base["scopedKnowledgeBaseId"],
        owner_type="agent",
        owner_id=second_agent["agentId"],
        actor_agent_id=second_agent["agentId"],
        reviewer_agent_id=second_agent["agentId"],
        source_type="agent_authored",
        title="Second vector source",
    )
    first_proposal = team_knowledge_service.create_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        source_artifact_ids=[first_source["sourceArtifactId"]],
        proposed_by_agent_id=first_agent["agentId"],
        title="First vector collision",
        content="First owner vector collision content.",
    )
    second_proposal = team_knowledge_service.create_refinement_proposal(
        second_base["scopedKnowledgeBaseId"],
        source_artifact_ids=[second_source["sourceArtifactId"]],
        proposed_by_agent_id=second_agent["agentId"],
        title="Second vector collision",
        content="Second owner vector collision content.",
    )
    team_knowledge_service.review_refinement_proposal(
        first_base["scopedKnowledgeBaseId"],
        first_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=first_agent["agentId"],
    )
    team_knowledge_service.review_refinement_proposal(
        second_base["scopedKnowledgeBaseId"],
        second_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=second_agent["agentId"],
    )

    first_item = rag_vector_index_service.list_indexable_knowledge_items(agent_id=first_agent["agentId"])[0]
    second_item = rag_vector_index_service.list_indexable_knowledge_items(agent_id=second_agent["agentId"])[0]
    first_record = rag_vector_index_service.write_index_record(first_item, embedding_provider="test", embedding_model="collision-v1")
    second_record = rag_vector_index_service.write_index_record(second_item, embedding_provider="test", embedding_model="collision-v1")
    health = rag_vector_index_service.get_vector_index_health(internal=True)

    assert first_item["knowledgeItemId"] == second_item["knowledgeItemId"] == "kitem-shared-vector"
    assert first_record["recordId"] != second_record["recordId"]
    assert first_record["recordId"].startswith(f"agent:{first_agent['agentId']}:")
    assert second_record["recordId"].startswith(f"agent:{second_agent['agentId']}:")
    assert health["indexedItemCount"] == 2
    assert {item["recordId"] for item in health["items"]} == {first_record["recordId"], second_record["recordId"]}


def test_vector_index_health_counts_empty_index_as_missing(vector_index_env):
    from core.web.services import rag_vector_index_service

    assert rag_vector_index_service.get_vector_index_health()["indexableItemCount"] == 0

    payload = rag_vector_index_service.get_vector_index_health(internal=True)

    assert payload["schemaVersion"] == 1
    assert payload["provider"] == "vector"
    assert payload["status"] == "unavailable"
    assert payload["vectorEnabled"] is False
    assert payload["indexedItemCount"] == 0
    assert payload["staleItemCount"] == 0
    assert payload["missingItemCount"] == 1
    assert payload["failedItemCount"] == 0
    assert payload["indexableItemCount"] == 1
    assert payload["embeddingProvider"] == ""
    assert payload["embeddingModel"] == ""


def test_vector_index_health_detects_indexed_and_stale_items(vector_index_env):
    from core.web.services import rag_vector_index_service

    items = rag_vector_index_service.list_indexable_knowledge_items(internal=True)
    item = items[0]
    rag_vector_index_service.write_index_record(
        item,
        embedding_provider="test-embedder",
        embedding_model="deterministic-v1",
    )

    indexed = rag_vector_index_service.get_vector_index_health(internal=True)

    assert indexed["status"] == "ready"
    assert indexed["vectorEnabled"] is True
    assert indexed["indexedItemCount"] == 1
    assert indexed["staleItemCount"] == 0
    assert indexed["missingItemCount"] == 0
    assert indexed["embeddingProvider"] == "test-embedder"
    assert indexed["embeddingModel"] == "deterministic-v1"

    changed = dict(item)
    changed["contentHash"] = "sha256:changed"
    rag_vector_index_service.write_index_record(
        changed,
        embedding_provider="test-embedder",
        embedding_model="deterministic-v1",
    )

    stale = rag_vector_index_service.get_vector_index_health(internal=True)

    assert stale["status"] == "degraded"
    assert stale["vectorEnabled"] is True
    assert stale["indexedItemCount"] == 0
    assert stale["staleItemCount"] == 1
    assert stale["missingItemCount"] == 0
    assert stale["items"][0]["status"] == "stale"
