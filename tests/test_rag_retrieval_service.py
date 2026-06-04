import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


@pytest.fixture()
def rag_knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)

    lead = agent_directory_service.create_agent_instance(display_name="RAG Lead")
    member = agent_directory_service.create_agent_instance(display_name="RAG Member")
    outsider = agent_directory_service.create_agent_instance(display_name="RAG Outsider")
    private_lead = agent_directory_service.create_agent_instance(
        display_name="Private RAG Lead",
    )

    team = team_service.create_team(
        name="RAG Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    private_team = team_service.create_team(
        name="Private RAG Team",
        members=[
            {"agentId": private_lead["agentId"], "role": "lead"},
        ],
    )
    readable_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Readable RAG Base",
        actor_agent_id=lead["agentId"],
        acl={"grants": {"review": [lead["agentId"]], "rate": [lead["agentId"]]}},
    )
    private_base = team_knowledge_service.create_knowledge_base(
        private_team["teamId"],
        name="Private RAG Base",
        actor_agent_id=private_lead["agentId"],
        acl={"grants": {"review": [private_lead["agentId"]], "rate": [private_lead["agentId"]]}},
    )

    source = team_knowledge_service.create_source_artifact(
        readable_base["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "rag-contract"},
        title="RAG contract source",
        summary="Source summary for governed retrieval.",
        actor_agent_id=member["agentId"],
    )
    first_proposal = team_knowledge_service.create_refinement_proposal(
        readable_base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=member["agentId"],
        title="Governed retrieval contract",
        summary="RAG retrieval must keep source citations.",
        content="RAG retrieval returns compact context blocks with stable citations and never mutates formal knowledge.",
        tags=["rag", "governance"],
    )
    second_proposal = team_knowledge_service.create_refinement_proposal(
        readable_base["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=member["agentId"],
        title="Prompt injection boundary",
        summary="Retrieved knowledge is explicit and budgeted.",
        content="The memory platform should not inject retrieved text into prompts by default.",
        tags=["rag", "prompt"],
    )
    first_item = team_knowledge_service.review_refinement_proposal(
        readable_base["knowledgeBaseId"],
        first_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=lead["agentId"],
    )["item"]
    second_item = team_knowledge_service.review_refinement_proposal(
        readable_base["knowledgeBaseId"],
        second_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=lead["agentId"],
    )["item"]
    private_proposal = team_knowledge_service.create_refinement_proposal(
        private_base["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=private_lead["agentId"],
        title="Private vector secret",
        summary="This private item must not leak through retrieval.",
        content="Unauthorized RAG retrieval must never expose this private vector secret.",
        tags=["rag", "private"],
    )
    private_item = team_knowledge_service.review_refinement_proposal(
        private_base["knowledgeBaseId"],
        private_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=private_lead["agentId"],
    )["item"]

    return {
        "team": team,
        "privateTeam": private_team,
        "readableBase": readable_base,
        "privateBase": private_base,
        "lead": lead,
        "member": member,
        "outsider": outsider,
        "privateLead": private_lead,
        "source": source,
        "items": [first_item, second_item],
        "privateItem": private_item,
    }


def test_local_rag_retrieval_returns_contexts_with_citations(rag_knowledge_env):
    from core.web.services import rag_retrieval_service

    payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=rag_knowledge_env["member"]["agentId"],
        query="rag citations",
        knowledge_base_id=rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        retrieval_mode="hybrid",
        provider="local",
        top_k=1,
        max_context_chars=500,
    )

    assert payload["schemaVersion"] == 1
    assert payload["agentId"] == rag_knowledge_env["member"]["agentId"]
    assert payload["request"]["provider"] == "local"
    assert payload["request"]["retrievalMode"] == "hybrid"
    assert payload["summary"]["contextCount"] == 1
    assert len(payload["contexts"]) == 1
    assert len(payload["citations"]) == 1
    context = payload["contexts"][0]
    citation = payload["citations"][0]
    assert context["provider"] == "local"
    assert context["retrievalMode"] == "hybrid"
    assert context["rank"] == 1
    assert context["source"]["teamId"] == rag_knowledge_env["team"]["teamId"]
    assert context["source"]["knowledgeBaseId"] == rag_knowledge_env["readableBase"]["knowledgeBaseId"]
    assert context["source"]["knowledgeItemId"] in {item["knowledgeItemId"] for item in rag_knowledge_env["items"]}
    assert citation["contextId"] == context["contextId"]
    assert citation["knowledgeItemId"] == context["source"]["knowledgeItemId"]
    assert citation["sourceArtifactIds"] == context["source"]["sourceArtifactIds"]


def test_rag_retrieval_health_reports_local_provider_ready():
    from core.web.services import rag_retrieval_service

    payload = rag_retrieval_service.get_rag_retrieval_health()

    assert payload["schemaVersion"] == 1
    assert payload["provider"] == "local"
    assert payload["status"] == "ready"
    assert payload["providers"] == [
        {
            "provider": "local",
            "status": "ready",
            "vectorEnabled": False,
            "indexedItemCount": 0,
            "staleItemCount": 0,
        }
    ]
    assert payload["retrievalPolicy"]["provider"] == "local"
    assert payload["retrievalPolicy"]["honorsKnowledgeAcl"] is True
    assert payload["retrievalPolicy"]["honorsMemoryPolicy"] is True
    assert payload["retrievalPolicy"]["mutatesFormalKnowledge"] is False
    assert payload["retrievalPolicy"]["injectsPromptByDefault"] is False
    assert payload["updatedAt"]


def test_rag_retrieval_honors_knowledge_acl(rag_knowledge_env):
    from core.web.services import rag_retrieval_service

    payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=rag_knowledge_env["member"]["agentId"],
        query="private vector secret",
        retrieval_mode="hybrid",
        provider="local",
        top_k=5,
    )

    all_context_text = "\n".join(context["text"] for context in payload["contexts"])
    assert "private vector secret" not in all_context_text.lower()
    assert rag_knowledge_env["privateItem"]["knowledgeItemId"] not in {
        context["source"]["knowledgeItemId"] for context in payload["contexts"]
    }
    assert payload["summary"]["scannedKnowledgeBaseCount"] == 1


def test_rag_context_budget_trims_text_but_keeps_source(rag_knowledge_env):
    from core.web.services import rag_retrieval_service

    payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=rag_knowledge_env["member"]["agentId"],
        query="retrieval",
        knowledge_base_id=rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        retrieval_mode="semantic",
        provider="local",
        top_k=1,
        max_context_chars=80,
    )

    assert payload["contexts"]
    context = payload["contexts"][0]
    assert len(context["text"]) <= 80
    assert context["text"].endswith("...")
    assert context["source"]["teamId"] == rag_knowledge_env["team"]["teamId"]
    assert context["source"]["knowledgeBaseId"] == rag_knowledge_env["readableBase"]["knowledgeBaseId"]
    assert context["source"]["knowledgeItemId"]
    assert payload["citations"][0]["knowledgeItemId"] == context["source"]["knowledgeItemId"]
