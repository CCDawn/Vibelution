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


def test_knowledge_routes_create_source_proposal_review_and_rate(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)

    base_response = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Route KB", "actorAgentId": lead["agentId"]},
    )
    assert base_response.status_code == 201
    base = base_response.json()

    source_response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={
            "sourceType": "external_search_refinement",
            "sourceRef": {"url": "https://example.test/report", "query": "memory platform"},
            "title": "External source",
            "actorAgentId": member["agentId"],
        },
    )
    assert source_response.status_code == 201
    source = source_response.json()

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


def test_knowledge_routes_reject_non_member_and_bad_source_type(tmp_path, monkeypatch):
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

    bad_source = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={"sourceType": "unknown_source", "actorAgentId": lead["agentId"]},
    )
    assert bad_source.status_code == 422


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


def test_knowledge_search_permission_audit_and_rating_suggestion_routes(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Governance KB", "actorAgentId": lead["agentId"]},
    ).json()
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
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
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
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


def test_knowledge_ingestion_package_route_creates_pending_candidate_only(tmp_path, monkeypatch):
    client, team, lead, member, outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Ingestion KB", "actorAgentId": lead["agentId"]},
    ).json()

    response = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/ingestion-packages",
        json={
            "sourceType": "external_search_refinement",
            "sourceRef": {"url": "https://example.test/a", "query": "memory ingestion"},
            "sourceTitle": "Search result",
            "sourceSummary": "External search evidence.",
            "excerpt": "Search result says ingestion should keep URL and query.",
            "proposedByAgentId": member["agentId"],
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
    package = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/ingestion-packages",
        json={
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "route trace"},
            "excerpt": "Route trace evidence.",
            "proposedByAgentId": member["agentId"],
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
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "proposedByAgentId": member["agentId"],
            "title": "Steward should see governance",
            "content": "Knowledge steward overview should expose queue counts without applying knowledge.",
        },
    ).json()

    response = client.get("/api/knowledge/steward/overview")

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
    source = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "needs proposal"},
            "title": "Source needs steward recommendation",
            "actorAgentId": member["agentId"],
        },
    ).json()
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
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
    source = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "workbench source"},
            "title": "Workbench source",
            "actorAgentId": member["agentId"],
        },
    ).json()
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
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


def test_knowledge_operations_health_and_governance_plan_routes_are_read_only(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Plan KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts",
        json={
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "plan route source"},
            "title": "Plan route source",
            "actorAgentId": member["agentId"],
        },
    ).json()
    client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
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
