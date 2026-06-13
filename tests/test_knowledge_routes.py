from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lead Agent", direct_session_id="session-lead")
    member = agent_directory_service.create_agent_instance(display_name="Member Agent", direct_session_id="session-member")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider Agent", direct_session_id="session-outsider")
    team = team_service.create_team(
        name="Route Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}), team, lead, member, outsider


def _promote_central_source(
    client: TestClient,
    team: dict,
    lead: dict,
    member: dict,
    *,
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
    title: str = "Route source",
) -> dict:
    collect_response = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "sourceType": source_type,
            "sourceRef": source_ref or {"note": title},
            "originalContent": "Route source content.",
            "originalFilename": "route-source.txt",
            "title": title,
            "actorAgentId": member["agentId"],
        },
    )
    assert collect_response.status_code == 201, collect_response.text
    inbox_source = collect_response.json()
    review_response = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{inbox_source['inboxSourceId']}/review",
        json={"decision": "accepted", "reviewedByAgentId": lead["agentId"]},
    )
    assert review_response.status_code == 200, review_response.text
    return review_response.json()["centralSource"]


def _source_artifact(
    client: TestClient,
    base: dict,
    team: dict,
    lead: dict,
    member: dict,
    *,
    title: str = "Route source",
    source_type: str = "manual_user_entry",
    source_ref: dict | None = None,
) -> dict:
    central_source = _promote_central_source(
        client,
        team,
        lead,
        member,
        source_type=source_type,
        source_ref=source_ref,
        title=title,
    )
    artifact_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/central-source-artifacts",
        json={"centralSourceId": central_source["centralSourceId"], "actorAgentId": member["agentId"], "title": title},
    )
    assert artifact_response.status_code == 201, artifact_response.text
    return artifact_response.json()


def _agent_source_artifact(client: TestClient, base: dict, agent: dict, *, title: str = "Agent route source") -> dict:
    collect_response = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "agent",
            "ownerId": agent["agentId"],
            "sourceType": "agent_authored",
            "sourceRef": {"agentId": agent["agentId"], "note": title},
            "originalContent": "Agent route source content.",
            "originalFilename": "agent-route-source.txt",
            "title": title,
            "actorAgentId": agent["agentId"],
        },
    )
    assert collect_response.status_code == 201, collect_response.text
    inbox_source = collect_response.json()
    review_response = client.patch(
        f"/api/knowledge/sources/inbox/agent/{agent['agentId']}/{inbox_source['inboxSourceId']}/review",
        json={"decision": "accepted", "reviewedByAgentId": agent["agentId"]},
    )
    assert review_response.status_code == 200, review_response.text
    central_source = review_response.json()["centralSource"]
    artifact_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/central-source-artifacts",
        json={"centralSourceId": central_source["centralSourceId"], "actorAgentId": agent["agentId"], "title": title},
    )
    assert artifact_response.status_code == 201, artifact_response.text
    return artifact_response.json()


def test_knowledge_routes_create_source_proposal_review_and_rate(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)

    base_response = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Route KB", "actorAgentId": lead["agentId"]},
    )
    assert base_response.status_code == 201
    base = base_response.json()

    central_source = _promote_central_source(
        client,
        team,
        lead,
        member,
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test/report", "query": "memory platform"},
        title="External source",
    )
    source_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/central-source-artifacts",
        json={
            "centralSourceId": central_source["centralSourceId"],
            "title": "External source",
            "actorAgentId": member["agentId"],
        },
    )
    assert source_response.status_code == 201
    source = source_response.json()
    assert source["centralSourceId"] == central_source["centralSourceId"]
    assert source["sourceType"] == "external_search_refinement"
    assert source["sourceRef"]["url"] == "https://example.test/report"
    assert source["sourceRef"]["centralSourceId"] == central_source["centralSourceId"]

    proposal_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "External source needs provenance",
            "content": "External search knowledge must keep URL and query provenance.",
            "tags": ["search"],
        },
    )
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()

    review_response = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals/{proposal['proposalId']}/review",
        json={"status": "approved", "reviewedByAgentId": lead["agentId"]},
    )
    assert review_response.status_code == 200
    applied = review_response.json()
    assert applied["item"]["sourceArtifactIds"] == [source["sourceArtifactId"]]

    rating_response = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/items/{applied['item']['knowledgeItemId']}/rating",
        json={
            "actorAgentId": lead["agentId"],
            "importanceLevel": "high",
            "confidence": 0.8,
            "stability": "evolving",
            "scope": "team",
            "reviewPriority": "elevated",
            "markingReason": "Useful for current implementation.",
        },
    )
    assert rating_response.status_code == 200
    assert rating_response.json()["importanceLevel"] == "high"

    items_response = client.get(f"/api/knowledge-bases/{base['knowledgeBaseId']}/items", params={"agentId": member["agentId"]})
    assert items_response.status_code == 200
    assert items_response.json()["summary"]["itemCount"] == 1


def test_knowledge_source_inbox_routes_promote_and_attach_central_source(tmp_path, monkeypatch):
    client, team, lead, member, outsider = _setup(tmp_path, monkeypatch)
    base_response = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Route Source Inbox KB", "actorAgentId": lead["agentId"]},
    )
    assert base_response.status_code == 201
    base = base_response.json()

    collect_response = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "sourceType": "external_search_refinement",
            "sourceRef": {"url": "https://example.test/route-source", "query": "route inbox"},
            "originalContent": "Route source capture waits for steward review.",
            "originalFilename": "route-source.txt",
            "title": "Route inbox source",
            "actorAgentId": member["agentId"],
        },
    )
    assert collect_response.status_code == 201
    inbox_source = collect_response.json()
    assert inbox_source["status"] == "pending"
    assert (tmp_path / inbox_source["originalPath"]).exists()

    blocked_response = client.get(
        "/api/knowledge/sources/inbox",
        params={"ownerType": "team", "ownerId": team["teamId"], "agentId": outsider["agentId"]},
    )
    assert blocked_response.status_code == 403

    review_response = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{inbox_source['inboxSourceId']}/review",
        json={"decision": "accepted", "reviewedByAgentId": lead["agentId"]},
    )
    assert review_response.status_code == 200
    central_source = review_response.json()["centralSource"]
    assert central_source["centralSourceId"]

    registry_response = client.get(
        "/api/knowledge/sources/registry",
        params={"agentId": member["agentId"], "ownerType": "team", "ownerId": team["teamId"]},
    )
    assert registry_response.status_code == 200
    assert registry_response.json()["summary"]["centralSourceCount"] == 1

    artifact_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/central-source-artifacts",
        json={"centralSourceId": central_source["centralSourceId"], "actorAgentId": member["agentId"]},
    )
    assert artifact_response.status_code == 201
    assert artifact_response.json()["centralSourceId"] == central_source["centralSourceId"]


def test_knowledge_routes_reject_non_member_and_legacy_source_artifact_route(tmp_path, monkeypatch):
    client, team, lead, _member, outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Route KB", "actorAgentId": lead["agentId"]},
    ).json()

    blocked = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={"proposedByAgentId": outsider["agentId"], "title": "Blocked", "content": "No team membership."},
    )
    assert blocked.status_code == 403

    legacy_source = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={"actorAgentId": lead["agentId"]},
    )
    assert legacy_source.status_code == 405


def test_knowledge_routes_reject_empty_actor_for_governed_content(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    empty_create = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "No Actor KB"},
    )
    assert empty_create.status_code == 403

    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Guarded KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Guarded source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Guarded item",
            "content": "Empty actor must not read this formal body.",
        },
    ).json()
    applied = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals/{proposal['proposalId']}/review",
        json={"status": "approved", "reviewedByAgentId": lead["agentId"]},
    ).json()

    assert client.get(f"/api/knowledge-bases/{base['knowledgeBaseId']}/items").status_code == 422
    assert client.get("/api/knowledge/search", params={"knowledgeBaseId": base["knowledgeBaseId"], "query": "formal body"}).status_code == 422
    assert client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/trace/{applied['item']['knowledgeItemId']}"
    ).status_code == 422
    assert client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/rating-suggestions"
    ).status_code == 422
    assert client.get("/api/knowledge/dashboard-snapshot").status_code == 422
    assert client.get("/api/knowledge/permissions/audit").status_code == 422
    assert client.get("/api/knowledge/governance/tasks").status_code == 422
    assert client.get("/api/knowledge/rag/retrieve", params={"query": "formal body"}).status_code == 422
    assert client.get("/api/knowledge/steward/overview").status_code == 422
    assert client.get("/api/knowledge/steward/recommendations").status_code == 422
    assert client.get("/api/knowledge/steward/workbench").status_code == 422
    assert client.get("/api/knowledge/operations/health").status_code == 422
    assert client.get("/api/knowledge/governance/plan").status_code == 422
    assert client.get(f"/api/agents/{member['agentId']}/knowledge-bases").status_code == 422

    allowed_items = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/items",
        params={"agentId": member["agentId"]},
    )
    assert allowed_items.status_code == 200
    assert allowed_items.json()["summary"]["itemCount"] == 1


def test_knowledge_overview_returns_visible_team_knowledge(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Visible KB", "actorAgentId": lead["agentId"]},
    ).json()

    response = client.get("/api/knowledge/overview", params={"agentId": member["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["knowledgeBaseCount"] == 1
    assert payload["knowledgeBases"][0]["knowledgeBaseId"] == base["knowledgeBaseId"]


def test_agent_knowledge_routes_create_private_formal_base_and_rag(tmp_path, monkeypatch):
    client, _team, _lead, member, outsider = _setup(tmp_path, monkeypatch)

    base_response = client.post(
        f"/api/agents/{member['agentId']}/knowledge-bases",
        json={"name": "Agent Route KB", "actorAgentId": member["agentId"]},
    )
    assert base_response.status_code == 201
    base = base_response.json()
    assert base["ownerType"] == "agent"
    assert base["ownerId"] == member["agentId"]

    source = _agent_source_artifact(client, base, member, title="Agent route private source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Agent route private RAG",
            "content": "Agent route private formal knowledge should be retrievable only by the owning Agent.",
            "tags": ["agent-private", "rag"],
        },
    ).json()
    applied = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals/{proposal['proposalId']}/review",
        json={"status": "approved", "reviewedByAgentId": member["agentId"]},
    ).json()

    list_response = client.get(
        f"/api/agents/{member['agentId']}/knowledge-bases",
        params={"actorAgentId": member["agentId"]},
    )
    rag_response = client.get(
        "/api/knowledge/rag/retrieve",
        params={
            "agentId": member["agentId"],
            "query": "private formal retrievable",
            "ownerType": "agent",
            "ownerId": member["agentId"],
            "retrievalMode": "semantic",
        },
    )
    blocked_response = client.get(
        "/api/knowledge/rag/retrieve",
        params={
            "agentId": outsider["agentId"],
            "query": "private formal retrievable",
            "ownerType": "agent",
            "ownerId": member["agentId"],
            "retrievalMode": "semantic",
        },
    )

    assert list_response.status_code == 200
    assert list_response.json()["summary"]["knowledgeBaseCount"] == 1
    assert rag_response.status_code == 200
    context = rag_response.json()["contexts"][0]
    assert context["source"]["ownerType"] == "agent"
    assert context["source"]["ownerId"] == member["agentId"]
    assert context["source"]["knowledgeItemId"] == applied["item"]["knowledgeItemId"]
    assert blocked_response.status_code == 200
    assert blocked_response.json()["summary"]["contextCount"] == 0


def test_knowledge_search_permission_audit_and_rating_suggestion_routes(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Governance KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Governed search source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Governed search item",
            "content": "Knowledge search and rating suggestions share governance rules.",
            "tags": ["governance"],
        },
    ).json()
    applied = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals/{proposal['proposalId']}/review",
        json={"status": "approved", "reviewedByAgentId": lead["agentId"]},
    ).json()

    search_response = client.get(
        "/api/knowledge/search",
        params={"agentId": member["agentId"], "query": "rating governance missing", "tags": "governance", "searchMode": "semantic"},
    )
    assert search_response.status_code == 200
    assert search_response.json()["summary"]["resultCount"] == 1
    assert search_response.json()["filters"]["searchMode"] == "semantic"
    assert search_response.json()["results"][0]["semanticScore"] > 0

    suggestion_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/rating-suggestions",
        json={
            "suggestedByAgentId": lead["agentId"],
            "targetType": "knowledge_item",
            "knowledgeItemId": applied["item"]["knowledgeItemId"],
            "importanceLevel": "critical",
            "confidence": 0.9,
            "stability": "stable",
            "reviewPriority": "urgent",
            "markingReason": "Governance test.",
        },
    )
    assert suggestion_response.status_code == 201
    suggestion = suggestion_response.json()
    assert suggestion["status"] == "pending"

    review_response = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/rating-suggestions/{suggestion['suggestionId']}/review",
        json={"status": "applied", "reviewedByAgentId": lead["agentId"]},
    )
    assert review_response.status_code == 200
    assert review_response.json()["item"]["importanceLevel"] == "critical"

    suggestion_two = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/rating-suggestions",
        json={
            "suggestedByAgentId": lead["agentId"],
            "targetType": "knowledge_item",
            "knowledgeItemId": applied["item"]["knowledgeItemId"],
            "importanceLevel": "high",
            "confidence": 0.8,
            "stability": "evolving",
            "reviewPriority": "elevated",
            "markingReason": "Bulk route test.",
        },
    ).json()
    bulk_response = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/rating-suggestions/review-batch",
        json={
            "suggestionIds": [suggestion_two["suggestionId"], suggestion["suggestionId"], "missing-suggestion"],
            "status": "rejected",
            "reviewedByAgentId": lead["agentId"],
        },
    )
    assert bulk_response.status_code == 200
    assert bulk_response.json()["summary"]["reviewedCount"] == 1
    assert bulk_response.json()["summary"]["skippedCount"] == 2

    audit_response = client.get("/api/knowledge/permissions/audit", params={"agentId": member["agentId"]})
    assert audit_response.status_code == 200
    assert audit_response.json()["summary"]["knowledgeBaseCount"] == 1


def test_knowledge_rag_retrieve_route_returns_contexts_and_citations(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "RAG Route KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="RAG route source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "RAG route context",
            "summary": "RAG route should expose compact context candidates.",
            "content": "RAG route retrieval returns cited context blocks without injecting prompt text by default.",
            "tags": ["rag", "route"],
        },
    ).json()
    applied = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals/{proposal['proposalId']}/review",
        json={"status": "approved", "reviewedByAgentId": lead["agentId"]},
    ).json()

    response = client.get(
        "/api/knowledge/rag/retrieve",
        params={
            "agentId": member["agentId"],
            "query": "rag route citations",
            "knowledgeBaseId": base["knowledgeBaseId"],
            "retrievalMode": "hybrid",
            "provider": "local",
            "topK": 3,
            "maxContextChars": 240,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["request"]["retrievalMode"] == "hybrid"
    assert payload["request"]["provider"] == "local"
    assert payload["summary"]["contextCount"] == 1
    assert payload["summary"]["citationCount"] == 1
    context = payload["contexts"][0]
    assert context["source"]["teamId"] == team["teamId"]
    assert context["source"]["knowledgeBaseId"] == base["knowledgeBaseId"]
    assert context["source"]["knowledgeItemId"] == applied["item"]["knowledgeItemId"]
    assert payload["citations"][0]["contextId"] == context["contextId"]
    assert payload["retrievalPolicy"]["injectsPromptByDefault"] is False


def test_knowledge_rag_retrieve_route_rejects_invalid_mode(tmp_path, monkeypatch):
    client, _team, _lead, member, _outsider = _setup(tmp_path, monkeypatch)

    response = client.get(
        "/api/knowledge/rag/retrieve",
        params={"agentId": member["agentId"], "query": "rag", "retrievalMode": "vector_magic"},
    )

    assert response.status_code == 422
    assert "Unsupported RAG retrieval mode" in response.json()["detail"]


def test_knowledge_rag_retrieve_route_requires_agent_id(tmp_path, monkeypatch):
    client, _team, _lead, _member, _outsider = _setup(tmp_path, monkeypatch)

    response = client.get(
        "/api/knowledge/rag/retrieve",
        params={"query": "rag", "retrievalMode": "hybrid"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "agentId is required for governed RAG retrieval."


def test_knowledge_rag_health_route_reports_local_provider_ready(tmp_path, monkeypatch):
    client, _team, _lead, _member, _outsider = _setup(tmp_path, monkeypatch)

    response = client.get("/api/knowledge/rag/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["provider"] == "local"
    assert payload["status"] == "ready"
    providers = {provider["provider"]: provider for provider in payload["providers"]}
    assert providers["local"]["status"] == "ready"
    assert providers["local"]["vectorEnabled"] is False
    assert providers["vector"]["status"] == "unavailable"
    assert providers["vector"]["vectorEnabled"] is False
    assert providers["vector"]["indexedItemCount"] == 0
    assert providers["vector"]["staleItemCount"] == 0
    assert payload["retrievalPolicy"]["honorsKnowledgeAcl"] is True
    assert payload["retrievalPolicy"]["honorsMemoryPolicy"] is True
    assert payload["retrievalPolicy"]["mutatesFormalKnowledge"] is False
    assert payload["retrievalPolicy"]["injectsPromptByDefault"] is False


def test_knowledge_ingestion_package_route_creates_pending_candidate_only(tmp_path, monkeypatch):
    client, team, lead, member, outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Ingestion KB", "actorAgentId": lead["agentId"]},
    ).json()

    central_source = _promote_central_source(
        client,
        team,
        lead,
        member,
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test/a", "query": "memory ingestion"},
        title="Search result",
    )
    response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/ingestion-packages",
        json={
            "sourceType": "external_search_refinement",
            "sourceRef": {"url": "https://example.test/a", "query": "memory ingestion"},
            "sourceTitle": "Search result",
            "sourceSummary": "External search evidence.",
            "excerpt": "Search result says ingestion should keep URL and query.",
            "proposedByAgentId": member["agentId"],
            "centralSourceId": central_source["centralSourceId"],
            "proposalTitle": "Preserve search URL and query",
            "tags": ["search", "ingestion"],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["sourceArtifact"]["sourceType"] == "external_search_refinement"
    assert payload["proposal"]["status"] == "pending"

    items_response = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/items",
        params={"agentId": member["agentId"]},
    )
    assert items_response.json()["summary"]["itemCount"] == 0


def test_knowledge_governance_tasks_adapters_and_trace_routes(tmp_path, monkeypatch):
    client, team, lead, member, outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Governance Ops KB", "actorAgentId": lead["agentId"]},
    ).json()
    central_source = _promote_central_source(client, team, lead, member, title="Route trace source")
    package = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/ingestion-packages",
        json={
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "route trace"},
            "excerpt": "Route trace evidence.",
            "proposedByAgentId": member["agentId"],
            "centralSourceId": central_source["centralSourceId"],
            "proposalTitle": "Route trace proposal",
        },
    ).json()

    tasks_response = client.get("/api/knowledge/governance/tasks", params={"agentId": lead["agentId"]})
    adapters_response = client.get("/api/knowledge/ingestion-adapters")
    trace_response = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/trace/{package['proposal']['proposalId']}",
        params={"agentId": member["agentId"]},
    )

    assert tasks_response.status_code == 200
    assert tasks_response.json()["summary"]["proposalReviewCount"] == 1
    assert adapters_response.status_code == 200
    assert adapters_response.json()["summary"]["adapterCount"] >= 6
    assert trace_response.status_code == 200
    assert trace_response.json()["summary"]["sourceArtifacts"] == 1

    blocked = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/ingestion-packages",
        json={
            "sourceType": "manual_user_entry",
            "excerpt": "Outsider cannot ingest.",
            "proposedByAgentId": outsider["agentId"],
        },
    )
    assert blocked.status_code == 403


def test_knowledge_steward_overview_surfaces_agent_boundary_and_queue(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Steward KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Steward overview source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Steward should see governance",
            "content": "Knowledge steward overview should expose queue counts without applying knowledge.",
        },
    ).json()

    response = client.get("/api/knowledge/steward/overview", params={"agentId": lead["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["steward"]["agentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert payload["steward"]["functionalDisplayName"] == "知识库管理员"
    assert payload["steward"]["permissionBoundary"] == "proposal_and_rating_suggestion_only"
    assert payload["steward"]["protected"] is True
    assert payload["steward"]["directChatPath"].startswith("/chat?session=")
    assert "knowledge_governance_tasks_tool" in payload["steward"]["toolPolicy"]["allowedTools"]
    assert "research_proposal_apply_tool" not in payload["steward"]["toolPolicy"]["allowedTools"]
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["operatingBoundary"]["canDeleteKnowledge"] is False
    assert payload["operatingBoundary"]["canChangeAcl"] is False
    assert payload["operatingBoundary"]["canBypassReviewer"] is False
    assert payload["operatingBoundary"]["formalKnowledgeRequiresReviewer"] is True
    assert payload["governance"]["summary"]["openTaskCount"] >= 1
    assert any(task["targetId"] == proposal["proposalId"] for task in payload["governance"]["openTasks"])


def test_knowledge_steward_recommendations_are_read_only(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Steward Recommendation KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Source needs steward recommendation")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [_source_artifact(client, base, team, lead, member, title="Steward recommendation source")["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Steward recommendation proposal",
            "content": "Knowledge steward should recommend review without applying it.",
        },
    ).json()

    response = client.get("/api/knowledge/steward/recommendations", params={"agentId": lead["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    actions = {item["recommendedAction"] for item in payload["recommendations"]}
    assert "review_proposal" in actions
    assert "draft_refinement_proposal" in actions
    assert any(item["targetId"] == proposal["proposalId"] for item in payload["recommendations"])
    assert any(item["targetId"] == source["sourceArtifactId"] for item in payload["recommendations"])
    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert payload["operatingBoundary"]["canBypassReviewer"] is False


def test_knowledge_steward_workbench_groups_next_actions(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Steward Workbench KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Workbench source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [_source_artifact(client, base, team, lead, member, title="Workbench proposal source")["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Workbench proposal",
            "content": "Workbench route should show next actions without applying.",
        },
    ).json()

    response = client.get("/api/knowledge/steward/workbench", params={"agentId": lead["agentId"], "limit": 6})

    assert response.status_code == 200
    payload = response.json()
    assert payload["steward"]["agentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert payload["operatingBoundary"]["recommendationsOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(action["targetId"] == proposal["proposalId"] for action in payload["nextActions"])
    assert any(
        item["targetId"] == source["sourceArtifactId"]
        for stage in payload["stages"]
        for item in stage["items"]
    )
    assert payload["acceptanceChecklist"][1]["id"] == "proposal_reviewed"


def test_knowledge_dashboard_snapshot_combines_memory_dashboard_state(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Dashboard Snapshot KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Snapshot source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [_source_artifact(client, base, team, lead, member, title="Snapshot proposal source")["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Snapshot proposal",
            "content": "Dashboard snapshot should gather read-only governance state.",
        },
    ).json()

    response = client.get(
        "/api/knowledge/dashboard-snapshot",
        params={"agentId": lead["agentId"], "recommendationLimit": 6, "workbenchLimit": 8, "planLimit": 8},
    )
    items_response = client.get(f"/api/knowledge-bases/{base['knowledgeBaseId']}/items", params={"agentId": member["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["agentId"] == lead["agentId"]
    assert payload["overview"]["summary"]["knowledgeBaseCount"] == 1
    assert payload["steward"]["steward"]["agentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert any(item["targetId"] == proposal["proposalId"] for item in payload["recommendations"]["recommendations"])
    assert any(action["targetId"] == proposal["proposalId"] for action in payload["workbench"]["nextActions"])
    assert payload["operationsHealth"]["summary"]["orphanSourceCount"] == 1
    assert any(finding["findingType"] == "orphan_sources" for finding in payload["operationsHealth"]["findings"])
    assert any(action["targetId"] == source["sourceArtifactId"] or action["targetId"] == proposal["proposalId"] for action in payload["governancePlan"]["actions"])
    assert payload["governancePlan"]["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert items_response.json()["summary"]["itemCount"] == 0


def test_knowledge_operations_health_and_governance_plan_routes_are_read_only(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Plan KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="Plan route source")
    client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [_source_artifact(client, base, team, lead, member, title="Plan proposal source")["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "Plan route proposal",
            "content": "Governance plan should be read-only.",
        },
    )

    health_response = client.get("/api/knowledge/operations/health", params={"agentId": lead["agentId"]})
    plan_response = client.get("/api/knowledge/governance/plan", params={"agentId": lead["agentId"], "limit": 6})
    items_response = client.get(f"/api/knowledge-bases/{base['knowledgeBaseId']}/items", params={"agentId": member["agentId"]})

    assert health_response.status_code == 200
    assert health_response.json()["summary"]["orphanSourceCount"] == 1
    assert any(finding["findingType"] == "orphan_sources" for finding in health_response.json()["findings"])
    assert source["sourceArtifactId"] in health_response.json()["knowledgeBases"][0]["nextReviewTargetIds"]
    assert plan_response.status_code == 200
    payload = plan_response.json()
    assert payload["mode"] == "recommendations_only"
    assert payload["operatingBoundary"]["planOnly"] is True
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert all(action["mutatesFormalKnowledge"] is False for action in payload["actions"])
    assert items_response.json()["summary"]["itemCount"] == 0
