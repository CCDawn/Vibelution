import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import knowledge as knowledge_routes
from core.web.services import agent_directory_service, chat_room_service, session_service, team_knowledge_service, team_service
from core.web.services.session import document_attachments
from tests.helpers.web_chat_state import _bind_seeded_session_agent, _seed_chat_state


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


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


def test_central_source_artifact_route_replays_idempotency_key_and_conflicts_on_changed_body(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Idempotent route KB", "actorAgentId": lead["agentId"]},
    ).json()
    central_source = _promote_central_source(client, team, lead, member, title="Idempotency route source")
    url = f"/api/knowledge-bases/{base['knowledgeBaseId']}/central-source-artifacts"
    headers = {"Idempotency-Key": "route-artifact-key-001"}
    payload = {
        "centralSourceId": central_source["centralSourceId"],
        "actorAgentId": member["agentId"],
        "title": "Stable artifact title",
        "summary": "Stable artifact summary",
    }

    first = client.post(url, json=payload, headers=headers)
    replay = client.post(url, json=payload, headers=headers)
    changed = client.post(url, json={**payload, "title": "Changed artifact title"}, headers=headers)

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json()["sourceArtifactId"] == first.json()["sourceArtifactId"]
    assert "_idempotency" not in first.json()
    assert changed.status_code == 409, changed.text

    owner = team_knowledge_service._require_base_with_owner(base["knowledgeBaseId"])[0]
    stored = team_knowledge_service._read_jsonl(team_knowledge_service._source_artifacts_path_for_owner(owner))
    assert sum(item.get("sourceArtifactId") == first.json()["sourceArtifactId"] for item in stored) == 1


def test_session_attachment_can_only_be_staged_from_the_actor_bound_session(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_id = str(member["directSessionId"])
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": session_id,
                "title": "Member source session",
                "updated_at": "2026-09-29T10:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )
    _bind_seeded_session_agent(tmp_path, member, session_id=session_id)
    attachment_payload = "A durable source fact from an attached document.".encode("utf-8")
    attachment = document_attachments.store_session_user_document_attachment(
        session_id,
        attachment_payload,
        filename="memory-evidence.txt",
        content_type="text/plain",
    )
    observed_runtime_events = []

    def capture_runtime_event(*args, **kwargs):
        observed_runtime_events.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(team_knowledge_service, "record_runtime_scene_event", capture_runtime_event)

    response = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "actorAgentId": member["agentId"],
            "sessionId": session_id,
            "attachmentId": attachment["artifactId"],
            "title": "Session attachment evidence",
        },
    )
    cross_agent = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "actorAgentId": lead["agentId"],
            "sessionId": session_id,
            "attachmentId": attachment["artifactId"],
        },
    )

    assert response.status_code == 201, response.text
    source = response.json()
    assert source["status"] == "pending"
    assert source["curationStatus"] == "owner_inbox"
    assert source["centralSourceId"] == ""
    assert source["sourceRef"]["sessionId"] == session_id
    assert source["sourceRef"]["attachmentId"] == attachment["artifactId"]
    source_body = team_knowledge_service._project_path_from_relative(source["originalPath"])
    assert source_body.read_text(encoding="utf-8") == "A durable source fact from an attached document."
    copied_attachment = source["localCopies"][0]
    assert "originalPath" not in copied_attachment
    copied_path = team_knowledge_service._project_path_from_relative(copied_attachment["inboxPath"])
    assert copied_path.read_bytes() == attachment_payload
    assert cross_agent.status_code == 403, cross_agent.text

    owner = team_knowledge_service._require_owner_context("team", team["teamId"])
    audit_rows = team_knowledge_service._read_jsonl(team_knowledge_service._audit_path_for_owner(owner))
    collection_audit = [item for item in audit_rows if item.get("action") == "knowledge.source_inbox.collected"]
    assert len(collection_audit) == 1

    audit_text = json.dumps(collection_audit, ensure_ascii=False, sort_keys=True)
    runtime_text = json.dumps(observed_runtime_events, ensure_ascii=False, sort_keys=True)
    for sensitive_value in (
        session_id,
        attachment["artifactId"],
        source["inboxSourceId"],
        "memory-evidence.txt",
        "A durable source fact from an attached document.",
    ):
        assert sensitive_value not in audit_text
        assert sensitive_value not in runtime_text
    assert {item["args"][2] for item in observed_runtime_events} == {
        "knowledge.source_inbox.collected",
        "knowledge.source_inbox.attachment_staged",
    }


def test_session_attachment_team_collector_cannot_self_review_but_agent_private_owner_can(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lead_session_id = str(lead["directSessionId"])
    member_session_id = str(member["directSessionId"])
    conversations = [
        {
            "conversation_id": session_id,
            "title": "Attachment review session",
            "updated_at": "2026-09-29T10:00:00",
            "last_turn_status": "ready",
            "messages": [],
        }
        for session_id in (lead_session_id, member_session_id)
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    _bind_seeded_session_agent(tmp_path, lead, session_id=lead_session_id)
    _bind_seeded_session_agent(tmp_path, member, session_id=member_session_id)
    team_attachment = document_attachments.store_session_user_document_attachment(
        lead_session_id,
        b"The Team lead's own attachment cannot be directly approved by that lead.",
        filename="lead-private-decision.txt",
        content_type="text/plain",
    )
    private_attachment = document_attachments.store_session_user_document_attachment(
        member_session_id,
        b"An Agent owner may govern their own private memory source.",
        filename="agent-private-decision.txt",
        content_type="text/plain",
    )
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Attachment review KB", "actorAgentId": lead["agentId"]},
    ).json()
    team_knowledge_service.update_owner_source_governance(
        "team",
        team["teamId"],
        local_steward_agent_ids=[member["agentId"]],
        actor_agent_id=lead["agentId"],
    )

    collected = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "actorAgentId": lead["agentId"],
            "sessionId": lead_session_id,
            "attachmentId": team_attachment["artifactId"],
            "title": "Team lead attachment",
        },
    )
    assert collected.status_code == 201, collected.text
    inbox_source_id = collected.json()["inboxSourceId"]
    assert "_sessionAttachmentCollectorAgentId" not in collected.json()

    own_review = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{inbox_source_id}/review",
        json={
            "decision": "accepted",
            "reviewedByAgentId": lead["agentId"],
            "ingestOnAccept": True,
            "knowledgeBaseId": base["knowledgeBaseId"],
            "knowledgeTitle": "Rejected self-review",
            "knowledgeContent": "This must stay pending until another Team Agent reviews it.",
        },
    )
    team_knowledge_service.ensure_knowledge_base_review_grant(base["knowledgeBaseId"], member["agentId"])
    independent_review = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{inbox_source_id}/review",
        json={
            "decision": "accepted",
            "reviewedByAgentId": member["agentId"],
            "ingestOnAccept": True,
            "knowledgeBaseId": base["knowledgeBaseId"],
            "knowledgeTitle": "Independently reviewed attachment",
            "knowledgeContent": "The separate Team reviewer can ingest the staged attachment as formal knowledge.",
        },
    )

    assert own_review.status_code == 403, own_review.text
    assert independent_review.status_code == 200, independent_review.text
    assert independent_review.json()["directIngestion"]["status"] == "ingested"

    private_base = team_knowledge_service.create_agent_knowledge_base(
        member["agentId"],
        name="Private Attachment Knowledge",
        actor_agent_id=member["agentId"],
    )
    private_source = team_knowledge_service.collect_session_attachment_to_inbox(
        "agent",
        member["agentId"],
        session_id=member_session_id,
        attachment_id=private_attachment["artifactId"],
        actor_agent_id=member["agentId"],
    )
    private_review = team_knowledge_service.review_owner_inbox_source(
        "agent",
        member["agentId"],
        private_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=member["agentId"],
        ingest_on_accept=True,
        knowledge_base_id=private_base["knowledgeBaseId"],
        knowledge_title="Private self-reviewed attachment",
        knowledge_content="The Agent owner can still directly govern private memory.",
    )
    assert private_review["directIngestion"]["status"] == "ingested"


def test_session_attachment_idempotency_replays_conflicts_and_serializes_concurrent_requests(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_id = str(member["directSessionId"])
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": session_id,
                "title": "Idempotent attachment session",
                "updated_at": "2026-09-29T10:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )
    _bind_seeded_session_agent(tmp_path, member, session_id=session_id)
    attachment_payload = b"Stable attachment content for timeout-safe inbox ingestion."
    attachment = document_attachments.store_session_user_document_attachment(
        session_id,
        attachment_payload,
        filename="idempotent-memory.txt",
        content_type="text/plain",
    )
    idempotency_key = "session-attachment-retry-001"
    barrier = threading.Barrier(6)
    observed_runtime_events = []

    def capture_runtime_event(*args, **kwargs):
        observed_runtime_events.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(team_knowledge_service, "record_runtime_scene_event", capture_runtime_event)

    def stage_concurrently(_index: int) -> dict:
        barrier.wait(timeout=5)
        return team_knowledge_service.collect_session_attachment_to_inbox(
            "team",
            team["teamId"],
            session_id=session_id,
            attachment_id=attachment["artifactId"],
            actor_agent_id=member["agentId"],
            title="Stable attachment title",
            summary="Stable attachment summary",
            idempotency_key=idempotency_key,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(stage_concurrently, range(6)))
    source_ids = {item["inboxSourceId"] for item in results}
    assert len(source_ids) == 1

    url = "/api/knowledge/sources/inbox"
    payload = {
        "ownerType": "team",
        "ownerId": team["teamId"],
        "actorAgentId": member["agentId"],
        "sessionId": session_id,
        "attachmentId": attachment["artifactId"],
        "title": "Stable attachment title",
        "summary": "Stable attachment summary",
    }
    replay = client.post(url, json=payload, headers={"Idempotency-Key": idempotency_key})
    assert replay.status_code == 201, replay.text
    assert replay.json()["inboxSourceId"] == next(iter(source_ids))
    listed = client.get(
        url,
        params={"ownerType": "team", "ownerId": team["teamId"], "agentId": lead["agentId"]},
    )
    assert listed.status_code == 200, listed.text
    assert all("_idempotency" not in item for item in listed.json()["sources"])
    assert all("_sessionAttachmentCollectorAgentId" not in item for item in listed.json()["sources"])

    reviewed = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{next(iter(source_ids))}/review",
        json={"decision": "accepted", "reviewedByAgentId": lead["agentId"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert "_idempotency" not in reviewed.json()["source"]
    assert "_sessionAttachmentCollectorAgentId" not in reviewed.json()["source"]
    after_review_retry = client.post(url, json=payload, headers={"Idempotency-Key": idempotency_key})
    assert after_review_retry.status_code == 201, after_review_retry.text
    assert after_review_retry.json()["inboxSourceId"] == next(iter(source_ids))
    assert after_review_retry.json()["status"] == "accepted"

    attachment_path, _content_type = document_attachments.resolve_session_document_artifact(
        session_id,
        attachment["artifactId"],
    )
    attachment_path.write_bytes(b"Changed attachment content under the same attachment id.")
    conflict = client.post(url, json=payload, headers={"Idempotency-Key": idempotency_key})
    assert conflict.status_code == 409, conflict.text

    other_attachment = document_attachments.store_session_user_document_attachment(
        session_id,
        b"A different attachment must not reuse the same retry key.",
        filename="different-memory.txt",
        content_type="text/plain",
    )
    different_attachment = client.post(
        url,
        json={**payload, "attachmentId": other_attachment["artifactId"]},
        headers={"Idempotency-Key": idempotency_key},
    )
    assert different_attachment.status_code == 409, different_attachment.text

    owner = team_knowledge_service._require_owner_context("team", team["teamId"])
    stored = team_knowledge_service._read_jsonl(team_knowledge_service._owner_source_index_path(owner))
    assert len(stored) == 1
    matches = [item for item in stored if item.get("sourceRef", {}).get("attachmentId") == attachment["artifactId"]]
    assert len(matches) == 1
    assert matches[0]["_idempotency"]["scopeHash"]
    assert matches[0]["_idempotency"]["requestFingerprint"]
    assert matches[0]["_sessionAttachmentCollectorAgentId"] == member["agentId"]
    assert idempotency_key not in json.dumps(matches, ensure_ascii=False)
    assert {item["args"][2] for item in observed_runtime_events} >= {
        "knowledge.source_inbox.collected",
        "knowledge.source_inbox.attachment_staged",
        "knowledge.source_inbox.attachment_idempotency_replayed",
        "knowledge.source_inbox.attachment_idempotency_conflict",
    }
    runtime_text = json.dumps(observed_runtime_events, ensure_ascii=False, sort_keys=True)
    for sensitive_value in (idempotency_key, session_id, attachment["artifactId"], "Stable attachment content"):
        assert sensitive_value not in runtime_text


def test_knowledge_source_review_route_can_directly_ingest_to_formal_knowledge(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Direct Ingest KB", "actorAgentId": lead["agentId"]},
    ).json()
    collect_response = client.post(
        "/api/knowledge/sources/inbox",
        json={
            "ownerType": "team",
            "ownerId": team["teamId"],
            "sourceType": "manual_user_entry",
            "sourceRef": {"note": "direct route source"},
            "originalContent": "Direct route source content.",
            "originalFilename": "direct-route-source.txt",
            "title": "Direct route source",
            "summary": "Route review should create formal knowledge.",
            "actorAgentId": member["agentId"],
        },
    )
    inbox_source = collect_response.json()

    review_response = client.patch(
        f"/api/knowledge/sources/inbox/team/{team['teamId']}/{inbox_source['inboxSourceId']}/review",
        json={
            "decision": "accepted",
            "reviewedByAgentId": lead["agentId"],
            "resolutionNote": "筛选通过，直接进入正式知识库。",
            "ingestOnAccept": True,
            "knowledgeBaseId": base["knowledgeBaseId"],
            "knowledgeTitle": "Direct route source becomes memory",
            "knowledgeSummary": "The review route can write a formal KnowledgeItem directly.",
            "knowledgeContent": "The knowledge source review API supports direct formal ingestion after steward screening.",
            "tags": ["direct-ingestion", "route"],
        },
    )
    items_response = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/items",
        params={"agentId": member["agentId"]},
    )

    assert review_response.status_code == 200, review_response.text
    payload = review_response.json()
    assert payload["directIngestion"]["status"] == "ingested"
    assert payload["directIngestion"]["item"]["title"] == "Direct route source becomes memory"
    assert items_response.json()["summary"]["itemCount"] == 1


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
    recorded_events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        recorded_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )

    monkeypatch.setattr(knowledge_routes, "record_runtime_scene_event", fake_record_runtime_scene_event)
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
    assert client.get("/api/knowledge/agent-readiness").status_code == 422
    assert client.get("/api/knowledge/governance/plan").status_code == 422
    assert client.get("/api/knowledge/rag/health").status_code == 422
    assert client.get(f"/api/agents/{member['agentId']}/knowledge-bases").status_code == 422
    assert any(event["eventCode"] == "knowledge.rag.health.blocked" for event in recorded_events)

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


def test_knowledge_rag_retrieve_route_accepts_bm25_mode(tmp_path, monkeypatch):
    client, team, lead, member, _outsider = _setup(tmp_path, monkeypatch)
    base = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "BM25 Route KB", "actorAgentId": lead["agentId"]},
    ).json()
    source = _source_artifact(client, base, team, lead, member, title="BM25 route source")
    proposal = client.post(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/refinement-proposals",
        json={
            "sourceArtifactIds": [source["sourceArtifactId"]],
            "proposedByAgentId": member["agentId"],
            "title": "BM25 route context",
            "summary": "BM25 should be available as a governed RAG mode.",
            "content": "BM25 retrieval ranks formal memory using term frequency and source-governed knowledge.",
            "tags": ["rag", "bm25"],
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
            "query": "bm25 formal memory",
            "knowledgeBaseId": base["knowledgeBaseId"],
            "retrievalMode": "bm25",
            "provider": "local",
            "topK": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["retrievalMode"] == "bm25"
    assert payload["summary"]["contextCount"] == 1
    assert payload["contexts"][0]["source"]["knowledgeItemId"] == applied["item"]["knowledgeItemId"]
    assert payload["contexts"][0]["score"] > 0
    assert payload["contexts"][0]["matchReason"] == "bm25"


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
    client, _team, _lead, member, _outsider = _setup(tmp_path, monkeypatch)

    response = client.get("/api/knowledge/rag/health", params={"agentId": member["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["agentId"] == member["agentId"]
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
    assert payload["retrievalPolicy"]["honorsKnowledgeAcl"] is True
    assert payload["retrievalPolicy"]["honorsMemoryPolicy"] is True
    assert "bm25" in payload["retrievalPolicy"]["supportedRetrievalModes"]
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
    assert payload["steward"]["permissionBoundary"] == "governed_stage_writeback_ingestion"
    assert payload["steward"]["protected"] is True
    assert payload["steward"]["directChatPath"].startswith("/chat?session=")
    assert "knowledge_governance_tasks_tool" in payload["steward"]["toolPolicy"]["allowedTools"]
    assert "research_proposal_apply_tool" not in payload["steward"]["toolPolicy"]["allowedTools"]
    assert payload["operatingBoundary"]["canDirectlyApplyKnowledge"] is True
    assert payload["operatingBoundary"]["canDirectlyIngestScreenedSources"] is True
    assert payload["operatingBoundary"]["canDeleteKnowledge"] is False
    assert payload["operatingBoundary"]["canChangeAcl"] is False
    assert payload["operatingBoundary"]["canBypassReviewer"] is False
    assert payload["operatingBoundary"]["formalKnowledgeRequiresReviewer"] is False
    assert payload["operatingBoundary"]["screeningAgentIsReviewer"] is True
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


def test_knowledge_agent_readiness_route_reports_agent_memory_access(tmp_path, monkeypatch):
    client, _team, _lead, member, _outsider = _setup(tmp_path, monkeypatch)
    research_agent = agent_directory_service.create_agent_instance(
        display_name="Route Research Agent",
        primary_mode="research",
        role_key="research_paper_reader",
    )
    research_team = team_service.create_team(
        name="Route Research Team",
        members=[{"agentId": research_agent["agentId"], "role": "member"}],
    )
    client.post(
        f"/api/teams/{research_team['teamId']}/knowledge-bases",
        json={"name": "Route Research KB", "actorAgentId": research_agent["agentId"]},
    )

    response = client.get("/api/knowledge/agent-readiness", params={"agentId": member["agentId"]})

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload["agents"] if item["agentId"] == research_agent["agentId"])
    assert payload["schemaVersion"] == 1
    assert payload["agentId"] == member["agentId"]
    assert payload["operatingBoundary"]["readOnly"] is True
    assert payload["summary"]["unifiedMemorySearchToolAgentCount"] >= 1
    assert row["memorySearch"]["hasUnifiedMemorySearchTool"] is True
    assert row["formalKnowledge"]["visibleKnowledgeBaseCount"] == 1
