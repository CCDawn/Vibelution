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
