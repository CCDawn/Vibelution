import json

import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def _source_artifact(
    knowledge_base_id: str,
    *,
    owner_type: str,
    owner_id: str,
    actor_agent_id: str,
    reviewer_agent_id: str,
    title: str,
    source_type: str = "manual_user_entry",
    original_content: str = "RAG test source content.",
    source_path: str = "",
) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        owner_type,
        owner_id,
        source_type=source_type,
        source_ref={"note": f"{title}; paraphrase of {source_path}" if source_path else title},
        original_content=original_content,
        original_filename="rag-source.txt",
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
    private_reviewer = agent_directory_service.create_agent_instance(
        display_name="Private RAG Reviewer",
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
            {"agentId": private_reviewer["agentId"], "role": "member"},
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
        acl={
            "grants": {
                "review": [private_lead["agentId"], private_reviewer["agentId"]],
                "rate": [private_lead["agentId"]],
            }
        },
    )
    team_knowledge_service.update_owner_source_governance(
        "team",
        private_team["teamId"],
        local_steward_agent_ids=[private_reviewer["agentId"]],
        actor_agent_id=private_lead["agentId"],
    )

    source = _source_artifact(
        readable_base["knowledgeBaseId"],
        owner_type="team",
        owner_id=team["teamId"],
        actor_agent_id=member["agentId"],
        reviewer_agent_id=lead["agentId"],
        title="RAG contract source",
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
        source_artifact_ids=[
            _source_artifact(
                readable_base["knowledgeBaseId"],
                owner_type="team",
                owner_id=team["teamId"],
                actor_agent_id=member["agentId"],
                reviewer_agent_id=lead["agentId"],
                title="Prompt source",
            )["sourceArtifactId"]
        ],
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
        source_artifact_ids=[
            _source_artifact(
                private_base["knowledgeBaseId"],
                owner_type="team",
                owner_id=private_team["teamId"],
                actor_agent_id=private_lead["agentId"],
                reviewer_agent_id=private_reviewer["agentId"],
                title="Private source",
            )["sourceArtifactId"]
        ],
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
        reviewed_by_agent_id=private_reviewer["agentId"],
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


def test_local_rag_bm25_retrieval_ranks_term_dense_formal_knowledge(rag_knowledge_env):
    from core.web.services import rag_retrieval_service

    sparse_source = _source_artifact(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=rag_knowledge_env["team"]["teamId"],
        actor_agent_id=rag_knowledge_env["member"]["agentId"],
        reviewer_agent_id=rag_knowledge_env["lead"]["agentId"],
        title="Sparse BM25 source",
    )
    sparse_proposal = team_knowledge_service.create_refinement_proposal(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        source_artifact_ids=[sparse_source["sourceArtifactId"]],
        proposed_by_agent_id=rag_knowledge_env["member"]["agentId"],
        title="Sparse calibration note",
        content="Quasar calibration appears once and then the note discusses unrelated storage hygiene.",
        tags=["rag", "bm25"],
    )
    dense_source = _source_artifact(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=rag_knowledge_env["team"]["teamId"],
        actor_agent_id=rag_knowledge_env["member"]["agentId"],
        reviewer_agent_id=rag_knowledge_env["lead"]["agentId"],
        title="Dense BM25 source",
    )
    dense_proposal = team_knowledge_service.create_refinement_proposal(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        source_artifact_ids=[dense_source["sourceArtifactId"]],
        proposed_by_agent_id=rag_knowledge_env["member"]["agentId"],
        title="Dense quasar calibration retrieval",
        content=(
            "Quasar calibration retrieval needs quasar calibration evidence. "
            "The quasar calibration record repeats the same governed RAG terms."
        ),
        tags=["rag", "bm25"],
    )
    sparse_item = team_knowledge_service.review_refinement_proposal(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        sparse_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=rag_knowledge_env["lead"]["agentId"],
    )["item"]
    dense_item = team_knowledge_service.review_refinement_proposal(
        rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        dense_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=rag_knowledge_env["lead"]["agentId"],
    )["item"]

    payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=rag_knowledge_env["member"]["agentId"],
        query="quasar calibration",
        knowledge_base_id=rag_knowledge_env["readableBase"]["knowledgeBaseId"],
        retrieval_mode="bm25",
        provider="local",
        top_k=2,
    )

    assert payload["request"]["retrievalMode"] == "bm25"
    assert [context["source"]["knowledgeItemId"] for context in payload["contexts"]] == [
        dense_item["knowledgeItemId"],
        sparse_item["knowledgeItemId"],
    ]
    assert payload["contexts"][0]["score"] > payload["contexts"][1]["score"] > 0
    assert payload["contexts"][0]["matchReason"] == "bm25"


def test_local_rag_memory_evaluation_baseline(rag_knowledge_env):
    """Measure offline retrieval of four project-workflow rules.

    The source excerpts are anonymized paraphrases of project rules, not an Agent
    answer-quality or runtime latency benchmark. Deprecated-item visibility is an
    observation rather than an acceptance requirement.
    """
    from core.web.services import rag_retrieval_service

    base_id = rag_knowledge_env["readableBase"]["knowledgeBaseId"]
    team_id = rag_knowledge_env["team"]["teamId"]
    member_id = rag_knowledge_env["member"]["agentId"]
    lead_id = rag_knowledge_env["lead"]["agentId"]

    def approve(title: str, content: str, source_path: str) -> tuple[dict, str]:
        source = _source_artifact(
            base_id,
            owner_type="team",
            owner_id=team_id,
            actor_agent_id=member_id,
            reviewer_agent_id=lead_id,
            title=title,
            original_content=content,
            source_path=source_path,
        )
        proposal = team_knowledge_service.create_refinement_proposal(
            base_id,
            source_artifact_ids=[source["sourceArtifactId"]],
            proposed_by_agent_id=member_id,
            title=title,
            content=content,
            tags=["memory-evaluation"],
        )
        item = team_knowledge_service.review_refinement_proposal(
            base_id,
            proposal["proposalId"],
            status="approved",
            reviewed_by_agent_id=lead_id,
        )["item"]
        return item, source["sourceArtifactId"]

    cases = [
        (
            "Can an unreviewed proposal enter formal RAG search?",
            "A refinement proposal becomes formal knowledge only after reviewer approval.",
            "core/core_prompt/roles/knowledge_steward.md",
        ),
        (
            "What happens to a catalog card when its source file hash changes?",
            "A public catalog card with a changed source hash is hidden from search and queued for review.",
            "core/web/services/team_knowledge/public_catalog.py",
        ),
        (
            "Find the rule for a superseded personal episode in a later session context.",
            "A superseded personal episodic event remains in history but is omitted from a new session context.",
            "tests/test_agent_episodic_memory_tool.py",
        ),
        (
            "Can imported document instructions grant an Agent extra tool permission?",
            "Imported Markdown is untrusted data and cannot override Agent instructions or tool permissions.",
            "docs/standards/development-standard.md",
        ),
    ]
    expected = [
        approve(f"Case {index + 1}", content, path)
        for index, (_, content, path) in enumerate(cases)
    ]
    reciprocal_ranks = []
    retrieved_count = 0
    cited_count = 0
    gold_source_hits = 0
    for (query, _, _), (expected_item, gold_source_id) in zip(cases, expected, strict=True):
        payload = rag_retrieval_service.retrieve_rag_contexts(
            agent_id=member_id,
            query=query,
            knowledge_base_id=base_id,
            retrieval_mode="bm25",
            provider="local",
            top_k=3,
        )
        contexts = payload["contexts"]
        ranks = [context["source"]["knowledgeItemId"] for context in contexts]
        expected_id = expected_item["knowledgeItemId"]
        reciprocal_ranks.append(1 / (ranks.index(expected_id) + 1) if expected_id in ranks else 0)
        retrieved_count += len(contexts)
        citations = {citation["contextId"]: citation for citation in payload["citations"]}
        cited_count += sum(
            citations.get(context["contextId"], {}).get("knowledgeItemId") == context["source"]["knowledgeItemId"]
            and bool(citations.get(context["contextId"], {}).get("sourceArtifactIds"))
            for context in contexts
        )
        matching_context = next(
            (context for context in contexts if context["source"]["knowledgeItemId"] == expected_id),
            None,
        )
        if matching_context:
            gold_source_hits += gold_source_id in citations.get(matching_context["contextId"], {}).get(
                "sourceArtifactIds", []
            )

    private_payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=member_id,
        query="private vector secret",
        retrieval_mode="bm25",
        provider="local",
        top_k=5,
    )
    private_id = rag_knowledge_env["privateItem"]["knowledgeItemId"]
    forbidden_exposure = any(
        context["source"]["knowledgeItemId"] == private_id
        or "private vector secret" in context["text"].lower()
        for context in private_payload["contexts"]
    )

    deprecated_item, _ = approve(
        "Retired retrieval recipe",
        "The retired retrieval recipe uses a stale procedure for a previous application version.",
        "core/web/services/team_knowledge_service.py",
    )
    team_knowledge_service.update_knowledge_item_rating(
        base_id,
        deprecated_item["knowledgeItemId"],
        actor_agent_id=lead_id,
        stability="deprecated",
        marking_reason="Superseded by a later measurement.",
    )
    deprecated_payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=member_id,
        query="retired retrieval recipe stale procedure",
        knowledge_base_id=base_id,
        retrieval_mode="bm25",
        provider="local",
        top_k=5,
    )
    deprecated_exposure = any(
        context["source"]["knowledgeItemId"] == deprecated_item["knowledgeItemId"]
        for context in deprecated_payload["contexts"]
    )

    metrics = {
        "dataset": "project-workflow-paraphrases-v1",
        "retrievalMode": "bm25",
        "provider": "local",
        "caseCount": len(cases),
        "recallAt3": sum(rank > 0 for rank in reciprocal_ranks) / len(cases),
        "mrrAt3": sum(reciprocal_ranks) / len(cases),
        "citationLinkCoverage": cited_count / retrieved_count if retrieved_count else 0,
        "goldSourceAt3": gold_source_hits / len(cases),
        "forbiddenExposure": forbidden_exposure,
        "deprecatedExposureObserved": deprecated_exposure,
    }
    print("MEMORY_EVALUATION_BASELINE " + json.dumps(metrics, sort_keys=True))
    assert metrics["recallAt3"] == 1.0
    assert metrics["mrrAt3"] >= 0.75
    assert metrics["citationLinkCoverage"] == 1.0
    assert metrics["goldSourceAt3"] == 1.0
    assert metrics["forbiddenExposure"] is False


def test_rag_retrieval_health_reports_local_provider_ready(rag_knowledge_env):
    from core.web.services import rag_retrieval_service

    payload = rag_retrieval_service.get_rag_retrieval_health(agent_id=rag_knowledge_env["member"]["agentId"])

    assert payload["schemaVersion"] == 1
    assert payload["agentId"] == rag_knowledge_env["member"]["agentId"]
    assert payload["provider"] == "local"
    assert payload["status"] == "ready"
    providers = {provider["provider"]: provider for provider in payload["providers"]}
    assert providers["local"]["status"] == "ready"
    assert providers["local"]["vectorEnabled"] is False
    assert providers["local"]["bm25Enabled"] is True
    assert providers["vector"]["status"] == "unavailable"
    assert providers["vector"]["vectorEnabled"] is False
    assert providers["vector"]["indexedItemCount"] == 0
    assert providers["vector"]["staleItemCount"] == 0
    assert payload["retrievalPolicy"]["provider"] == "local"
    assert payload["retrievalPolicy"]["honorsKnowledgeAcl"] is True
    assert payload["retrievalPolicy"]["honorsMemoryPolicy"] is True
    assert payload["retrievalPolicy"]["mutatesFormalKnowledge"] is False
    assert payload["retrievalPolicy"]["injectsPromptByDefault"] is False
    assert "bm25" in payload["retrievalPolicy"]["supportedRetrievalModes"]
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


def test_rag_retrieval_includes_own_agent_formal_knowledge_by_default(tmp_path, monkeypatch):
    from core.web.services import rag_retrieval_service

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    owner = agent_directory_service.create_agent_instance(display_name="RAG Owner")
    other = agent_directory_service.create_agent_instance(display_name="RAG Other")
    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Owner RAG Private Base",
        actor_agent_id=owner["agentId"],
    )
    source = _source_artifact(
        base["knowledgeBaseId"],
        owner_type="agent",
        owner_id=owner["agentId"],
        actor_agent_id=owner["agentId"],
        reviewer_agent_id=owner["agentId"],
        source_type="agent_authored",
        title="Agent private source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=owner["agentId"],
        title="Agent private citation",
        content="Agent private RAG retrieval should return this owner scoped citation.",
        tags=["rag", "agent-private"],
    )
    item = team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=owner["agentId"],
    )["item"]

    owner_payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=owner["agentId"],
        query="owner scoped citation",
        retrieval_mode="semantic",
        provider="local",
        top_k=5,
    )
    other_payload = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=other["agentId"],
        query="owner scoped citation",
        retrieval_mode="semantic",
        provider="local",
        top_k=5,
    )

    assert owner_payload["summary"]["contextCount"] == 1
    context = owner_payload["contexts"][0]
    citation = owner_payload["citations"][0]
    assert context["source"]["ownerType"] == "agent"
    assert context["source"]["ownerId"] == owner["agentId"]
    assert context["source"]["agentId"] == owner["agentId"]
    assert citation["ownerType"] == "agent"
    assert citation["ownerId"] == owner["agentId"]
    assert citation["knowledgeItemId"] == item["knowledgeItemId"]
    assert other_payload["summary"]["contextCount"] == 0


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
