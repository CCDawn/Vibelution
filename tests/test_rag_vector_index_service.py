import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


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
    source = team_knowledge_service.create_source_artifact(
        base["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "vector-source"},
        title="Vector source",
        summary="Source evidence for vector indexing.",
        actor_agent_id=member["agentId"],
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
        source_artifact_ids=[],
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
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[],
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
