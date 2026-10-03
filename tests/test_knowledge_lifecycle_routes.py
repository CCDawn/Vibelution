"""HTTP contracts for bounded knowledge reads and governed source lifecycle."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import knowledge as knowledge_routes
from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service
from core.web.services.team_knowledge import governance, lifecycle


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def _environment(tmp_path, monkeypatch):
    for service in (agent_directory_service, chat_room_service, team_service, team_knowledge_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Lifecycle Route Lead")
    member = agent_directory_service.create_agent_instance(display_name="Lifecycle Route Member")
    outsider = agent_directory_service.create_agent_instance(display_name="Lifecycle Route Outsider")
    team = team_service.create_team(
        name="Lifecycle Route Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"], name="Lifecycle Route KB", actor_agent_id=lead["agentId"],
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    return client, team, base, lead, member, outsider


def _source_artifact(base, team, lead, member):
    inbox = team_knowledge_service.collect_source_to_inbox(
        "team", team["teamId"], source_type="manual_user_entry", source_ref={"note": "route source"},
        original_content="Immutable route source body for source-mode paging.",
        original_filename="route-source.txt", title="Lifecycle route source", actor_agent_id=member["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team", team["teamId"], inbox["inboxSourceId"], decision="accepted",
        reviewed_by_agent_id=lead["agentId"],
    )
    central_source = reviewed["centralSource"]
    return team_knowledge_service.create_source_artifact_from_central_source(
        base["knowledgeBaseId"], central_source["centralSourceId"],
        actor_agent_id=member["agentId"], title="Lifecycle route source",
    )


def _approved_item(base, source, lead, member, *, content):
    proposal = team_knowledge_service.create_refinement_proposal(
        base["knowledgeBaseId"], source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=member["agentId"], title="Lifecycle route item", content=content,
    )
    return team_knowledge_service.review_refinement_proposal(
        base["knowledgeBaseId"], proposal["proposalId"], status="applied",
        reviewed_by_agent_id=lead["agentId"],
    )["item"]


def test_knowledge_body_route_pages_item_and_checked_source_snapshot(tmp_path, monkeypatch):
    client, team, base, lead, member, outsider = _environment(tmp_path, monkeypatch)
    source = _source_artifact(base, team, lead, member)
    content = "0123456789" * 620
    item = _approved_item(base, source, lead, member, content=content)
    url = f"/api/knowledge-bases/{base['knowledgeBaseId']}/items/{item['knowledgeItemId']}/body"

    first = client.get(url, params={"agentId": member["agentId"], "offset": 117, "maxChars": 31})
    second = client.get(url, params={"agentId": member["agentId"], "offset": 148, "maxChars": 31})
    source_page = client.get(
        url,
        params={
            "agentId": member["agentId"], "readMode": "source",
            "sourceArtifactId": source["sourceArtifactId"], "offset": 4, "maxChars": 13,
        },
    )

    assert first.status_code == 200, first.text
    assert first.json()["content"] == content[117:148]
    assert first.json()["hasMore"] is True
    assert first.json()["nextOffset"] == 148
    assert first.json()["contentSha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert second.status_code == 200, second.text
    assert second.json()["content"] == content[148:179]
    assert source_page.status_code == 200, source_page.text
    assert source_page.json()["readMode"] == "source"
    assert source_page.json()["content"] == "Immutable route source body for source-mode paging."[4:17]
    assert source_page.json()["contentSha256"] == hashlib.sha256(
        "Immutable route source body for source-mode paging.".encode("utf-8")
    ).hexdigest()

    denied = client.get(url, params={"agentId": outsider["agentId"]})
    missing_actor = client.get(url)
    invalid_mode = client.get(url, params={"agentId": member["agentId"], "readMode": "raw"})
    assert denied.status_code == 403
    assert missing_actor.status_code == 422
    assert invalid_mode.status_code == 422


def test_knowledge_history_route_paginates_versions_without_returning_bodies(tmp_path, monkeypatch):
    client, team, base, lead, member, outsider = _environment(tmp_path, monkeypatch)
    source = _source_artifact(base, team, lead, member)
    original = _approved_item(base, source, lead, member, content="Original approved policy.")
    revision_proposal = governance.create_refinement_proposal(
        base["knowledgeBaseId"], source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=member["agentId"], title=original["title"], content="Corrected approved policy.",
        supersedes_knowledge_item_id=original["knowledgeItemId"],
        expected_content_sha256=lifecycle.content_sha256(original), revision_reason="Verified correction",
    )
    revised = governance.review_refinement_proposal(
        base["knowledgeBaseId"], revision_proposal["proposalId"], status="applied",
        reviewed_by_agent_id=lead["agentId"],
    )["item"]
    url = f"/api/knowledge-bases/{base['knowledgeBaseId']}/items/{revised['knowledgeItemId']}/body"

    latest = client.get(url, params={"agentId": member["agentId"], "readMode": "history", "offset": 0})
    earlier = client.get(url, params={"agentId": member["agentId"], "readMode": "history", "offset": 1})
    denied = client.get(url, params={"agentId": outsider["agentId"], "readMode": "history"})

    assert latest.status_code == 200, latest.text
    assert latest.json()["offsetUnit"] == "versions"
    assert latest.json()["versionCount"] == 2
    assert [row["revision"] for row in latest.json()["versions"]] == [2, 1]
    assert "content" not in latest.json()["versions"][0]
    assert latest.json()["hasMore"] is False
    assert earlier.status_code == 200, earlier.text
    assert [row["revision"] for row in earlier.json()["versions"]] == [1]
    assert earlier.json()["offset"] == 1
    assert denied.status_code == 403

    trace = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/trace/{revised['knowledgeItemId']}",
        params={"agentId": member["agentId"]},
    )
    assert trace.status_code == 200, trace.text
    nodes = trace.json()["nodes"]
    assert {row["knowledgeItemId"] for row in nodes["items"]} == {
        original["knowledgeItemId"], revised["knowledgeItemId"],
    }
    assert all("content" not in row for row in nodes["items"] + nodes["proposals"])
    assert all(row["contentLength"] > 0 and row["contentSha256"] for row in nodes["items"])

    listing = client.get(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/items", params={"agentId": member["agentId"]},
    )
    assert listing.status_code == 200, listing.text
    listed = {row["knowledgeItemId"]: row for row in listing.json()["items"]}
    assert listed[original["knowledgeItemId"]]["content"] == ""
    assert listed[original["knowledgeItemId"]]["contentLength"] == len(original["content"])
    assert listed[revised["knowledgeItemId"]]["content"] == revised["content"]


def test_private_trace_and_listing_deny_nonowner_even_with_steward_acl(tmp_path, monkeypatch):
    client, _team, _base, lead, _member, outsider = _environment(tmp_path, monkeypatch)
    private = team_knowledge_service.create_agent_knowledge_base(
        lead["agentId"], name="Private trace", actor_agent_id=lead["agentId"],
    )
    monkeypatch.setattr(team_knowledge_service, "_is_global_knowledge_steward", lambda actor: actor == outsider["agentId"])
    owner, stored = team_knowledge_service._require_base_with_owner(private["scopedKnowledgeBaseId"])
    assert team_knowledge_service._can_access(owner, stored, outsider["agentId"], "read")
    for suffix in ("items", "trace/private-item"):
        denied = client.get(
            f"/api/knowledge-bases/{private['scopedKnowledgeBaseId']}/{suffix}",
            params={"agentId": outsider["agentId"]},
        )
        assert denied.status_code == 403, denied.text


def test_source_lifecycle_route_maps_acl_validation_and_missing_source(tmp_path, monkeypatch):
    client, team, base, lead, member, _outsider = _environment(tmp_path, monkeypatch)
    source = _source_artifact(base, team, lead, member)
    url = f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts/{source['sourceArtifactId']}/lifecycle"
    payload = {"actorAgentId": lead["agentId"], "status": "withdrawn", "reason": "Evidence corrected"}

    denied = client.patch(url, json={**payload, "actorAgentId": member["agentId"]})
    updated = client.patch(url, json=payload)
    invalid_status = client.patch(url, json={**payload, "status": "archived"})
    missing_reason = client.patch(url, json={**payload, "reason": ""})
    missing_source = client.patch(
        f"/api/knowledge-bases/{base['knowledgeBaseId']}/source-artifacts/missing-source/lifecycle",
        json=payload,
    )

    assert denied.status_code == 403
    assert updated.status_code == 200, updated.text
    assert updated.json()["sourceArtifact"]["status"] == "withdrawn"
    assert updated.json()["sourceArtifact"]["lifecycleUpdatedByAgentId"] == lead["agentId"]
    assert invalid_status.status_code == 422
    assert missing_reason.status_code == 422
    assert missing_source.status_code == 404


def test_semantic_index_routes_require_actor_and_forward_prepare_model_explicitly(tmp_path, monkeypatch):
    client, _team, base, lead, _member, _outsider = _environment(tmp_path, monkeypatch)
    observed_health_actors = []
    monkeypatch.setattr(
        knowledge_routes, "get_semantic_index_health",
        lambda *, agent_id: observed_health_actors.append(agent_id) or {"status": "unavailable", "agentId": agent_id},
    )

    health = client.get("/api/knowledge/semantic-index/health", params={"agentId": lead["agentId"]})
    missing_health_actor = client.get("/api/knowledge/semantic-index/health")
    assert health.status_code == 200, health.text
    assert health.json()["agentId"] == lead["agentId"]
    assert observed_health_actors == [lead["agentId"]]
    assert missing_health_actor.status_code == 422

    observed_builds = []

    def build(knowledge_base_id, *, agent_id, prepare_model=False):
        observed_builds.append((knowledge_base_id, agent_id, prepare_model))
        return {"status": "unavailable", "indexedItemCount": 0}

    monkeypatch.setattr(knowledge_routes, "build_knowledge_index", build)
    path = f"/api/knowledge-bases/{base['knowledgeBaseId']}/semantic-index"
    default_prepare = client.post(path, json={"actorAgentId": lead["agentId"]})
    explicit_prepare = client.post(path, json={"actorAgentId": lead["agentId"], "prepareModel": True})
    assert default_prepare.status_code == 200, default_prepare.text
    assert explicit_prepare.status_code == 200, explicit_prepare.text
    assert observed_builds == [
        (base["knowledgeBaseId"], lead["agentId"], False),
        (base["knowledgeBaseId"], lead["agentId"], True),
    ]


def test_semantic_index_route_maps_review_acl_errors_and_model_adapter_failure(tmp_path, monkeypatch):
    client, _team, base, lead, member, _outsider = _environment(tmp_path, monkeypatch)
    path = f"/api/knowledge-bases/{base['knowledgeBaseId']}/semantic-index"
    body = {"actorAgentId": member["agentId"]}
    # The real index service checks reviewer ACL before looking at model readiness.
    acl_denied = client.post(path, json=body)
    missing_base = client.post("/api/knowledge-bases/missing-kb/semantic-index", json={"actorAgentId": lead["agentId"]})
    assert acl_denied.status_code == 403
    assert missing_base.status_code == 404

    from core.web.services.team_knowledge_service import TeamKnowledgeError

    def invalid_request(*_args, **_kwargs):
        raise TeamKnowledgeError("The knowledge base cannot be indexed.")

    def adapter_failure(*_args, **_kwargs):
        raise RuntimeError("offline model adapter")

    monkeypatch.setattr(knowledge_routes, "build_knowledge_index", invalid_request)
    invalid = client.post(path, json={"actorAgentId": lead["agentId"]})
    monkeypatch.setattr(knowledge_routes, "build_knowledge_index", adapter_failure)
    unavailable_adapter = client.post(path, json={"actorAgentId": lead["agentId"], "prepareModel": True})

    assert invalid.status_code == 422
    assert unavailable_adapter.status_code == 503
    assert unavailable_adapter.json()["detail"] == "The local embedding model could not be prepared or loaded."


def test_index_build_without_prepare_and_semantic_query_never_prepare_or_download_model(tmp_path, monkeypatch):
    from core.web.services.team_knowledge import semantic as knowledge_semantic_service

    _client, _team, base, lead, _member, _outsider = _environment(tmp_path, monkeypatch)
    monkeypatch.setattr(knowledge_semantic_service.embeddings, "readiness", lambda **_kwargs: {"status": "unavailable"})

    def unexpected_prepare(**_kwargs):
        pytest.fail("Only prepareModel=true may prepare or download the embedding model.")

    monkeypatch.setattr(knowledge_semantic_service.embeddings, "prepare", unexpected_prepare)
    build = knowledge_semantic_service.build_knowledge_index(
        base["knowledgeBaseId"], agent_id=lead["agentId"], prepare_model=False,
    )
    monkeypatch.setattr(knowledge_semantic_service, "_rank_bm25_search_results", lambda _rows, _query: [])
    ranked, diagnostics = knowledge_semantic_service.rank_candidates(
        [{"knowledgeItemId": "item-1"}], "semantic query", mode="semantic",
    )

    assert build["status"] == "unavailable"
    assert ranked == []
    assert diagnostics["status"] == "unavailable"


def test_public_revision_routes_enforce_lineage_conflicts_and_current_body_reads(tmp_path, monkeypatch):
    client, team, base, lead, member, outsider = _environment(tmp_path, monkeypatch)
    source = _source_artifact(base, team, lead, member)
    original = _approved_item(base, source, lead, member, content="Delivery takes 23 days.")
    base_path = f"/api/knowledge-bases/{base['knowledgeBaseId']}"
    revision_payload = {
        "sourceArtifactIds": [source["sourceArtifactId"]],
        "proposedByAgentId": member["agentId"],
        "title": original["title"],
        "content": "Delivery takes 17 days.",
        "supersedesKnowledgeItemId": original["knowledgeItemId"],
        "expectedContentSha256": hashlib.sha256(original["content"].encode()).hexdigest(),
        "revisionReason": "Correct the reviewed delivery time.",
    }
    first = client.post(f"{base_path}/refinement-proposals", json=revision_payload)
    competing = client.post(f"{base_path}/refinement-proposals", json=revision_payload)
    assert first.status_code == 201, first.text
    assert competing.status_code == 201, competing.text
    review_payload = {"status": "applied", "reviewedByAgentId": lead["agentId"]}
    applied = client.patch(
        f"{base_path}/refinement-proposals/{first.json()['proposalId']}/review", json=review_payload,
    )
    assert applied.status_code == 200, applied.text
    latest = applied.json()["item"]
    assert latest["knowledgeItemId"] != original["knowledgeItemId"]
    assert latest["revision"] == 2
    assert latest["rootKnowledgeItemId"] == original["knowledgeItemId"]
    assert latest["content"] == revision_payload["content"]
    stale = client.patch(
        f"{base_path}/refinement-proposals/{competing.json()['proposalId']}/review", json=review_payload,
    )
    assert stale.status_code == 409, stale.text
    old_body_path = f"{base_path}/items/{original['knowledgeItemId']}/body"
    new_body_path = f"{base_path}/items/{latest['knowledgeItemId']}/body"
    assert client.get(old_body_path, params={"agentId": member["agentId"]}).status_code == 404
    assert client.get(new_body_path, params={"agentId": outsider["agentId"]}).status_code == 403
    current = client.get(new_body_path, params={"agentId": member["agentId"]})
    assert current.status_code == 200, current.text
    assert current.json()["content"] == revision_payload["content"]
    history = client.get(old_body_path, params={"agentId": member["agentId"], "readMode": "history"})
    assert history.status_code == 200, history.text
    assert history.json()["versionCount"] == 2
    assert [row["state"] for row in history.json()["versions"]] == ["active", "superseded"]
    assert all("content" not in row for row in history.json()["versions"])
    withdrawn = client.patch(
        f"{base_path}/source-artifacts/{source['sourceArtifactId']}/lifecycle",
        json={"actorAgentId": lead["agentId"], "status": "withdrawn", "reason": "Source revoked."},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert client.get(new_body_path, params={"agentId": member["agentId"]}).status_code == 404
    assert client.get(old_body_path, params={"agentId": member["agentId"]}).status_code == 404
