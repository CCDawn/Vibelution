"""Platform metadata authority, lifecycle and compatibility contracts."""
import json
import copy

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import memory_graph_service, team_knowledge_service as knowledge
from core.web.services.memory import platform_graph
from core.web.services.memory.models import PlatformKnowledgeGraphResponse, PlatformKnowledgeGraphDetailResponse
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    CONTROL_OPERATOR_ROLES_ENV, server_operator_scope,
)


@pytest.fixture
def graph_store(monkeypatch):
    owners = [{"ownerType": kind, "ownerId": value, kind: {"name": value, "displayName": value}}
              for kind, value in [("team", "team-a"), ("team", "team-b"), ("agent", "agent-private")]]
    items = {}
    sources = {}
    for owner in owners:
        value = owner["ownerId"]
        items[value] = [{"knowledgeItemId": "same-id", "knowledgeBaseId": "same-kb", "title": value,
            "content": "SECRET BODY MUST NEVER BE EXPOSED", "summary": "正式摘要", "tags": ["中文主题"],
            "sourceArtifactIds": ["source"], "revision": 2, "reviewedByAgentId": "reviewer",
            "metadata": {"officialResearchGraph": {"status": "synced", "targetDomain": "科研主题",
                "reviewedAt": "2026-10-14T00:00:00Z", "reviewedByAgentId": "reviewer", "edges": [
                    {"sourceId": "same-ref", "sourceType": "paper_note", "targetId": "same-id", "relation": "supports"},
                    {"sourceId": "unknown-ref", "targetId": "same-id", "relation": "unverified"}]}}}]
        sources[value] = [{"sourceArtifactId": "source", "knowledgeBaseId": "same-kb", "centralSourceId": "central",
            "title": "论文来源", "sourceType": "pdf_refinement", "sourceHash": "sha256-proof", "status": "active",
            "sourceRef": {"url": "https://example.org/paper", "pageRange": "3-5", "prompt": "SECRET PROMPT"}}]
    reads = []
    def read(path):
        reads.append(path)
        if path == "central":
            return [{"centralSourceId": "central", "status": "active"}]
        return items[path]
    monkeypatch.setattr(memory_graph_service, "_sync_roots", lambda: None)
    monkeypatch.setattr(knowledge, "_iter_knowledge_owners", lambda **kwargs: owners if kwargs == {
        "include_archived": False, "include_all_agents": True} else pytest.fail("Agent impersonation or wrong enumeration"))
    monkeypatch.setattr(knowledge, "_knowledge_bases_for_owner", lambda owner: [{"knowledgeBaseId": "same-kb", "name": "知识库", "status": "active"}])
    monkeypatch.setattr(knowledge, "_items_path_for_owner", lambda owner: owner["ownerId"])
    monkeypatch.setattr(knowledge, "_read_jsonl", read)
    monkeypatch.setattr(knowledge, "_central_source_registry_path", lambda: "central")
    monkeypatch.setattr(knowledge, "_source_artifacts_for_base", lambda owner, base: sources[owner["ownerId"]])
    monkeypatch.setattr(knowledge, "eligible_financial_items", lambda *args: None)
    return items, sources, reads


def _graph(**kwargs):
    with server_operator_scope("operator", roles=("operator",)):
        return platform_graph.get_platform_knowledge_graph(**kwargs)


def test_platform_graph_all_owners_metadata_sources_and_scoped_ids(graph_store):
    payload = _graph()
    PlatformKnowledgeGraphResponse.model_validate(payload)
    item_nodes = [node for node in payload["nodes"] if node["type"] == "knowledge_item"]
    assert {node["metadata"]["ownerId"] for node in item_nodes} == {"team-a", "team-b", "agent-private"}
    assert len({node["id"] for node in item_nodes}) == 3
    refs = [node for node in payload["nodes"] if node["type"] == "official_research_ref"]
    assert len(refs) == 6  # no cross-owner merge by source id
    source = next(node for node in payload["nodes"] if node["type"] == "source_artifact")
    assert source["metadata"]["sourceRef"] == {"url": "https://example.org/paper", "pageRange": "3-5"}
    assert source["metadata"]["sourceHash"] == "sha256-proof"
    assert payload["topics"][0]["groupingBasis"] == "official_target_domain"
    for edge in payload["edges"]:
        assert set(edge["metadata"]) >= {"layer", "status", "reason", "evidenceNodeIds"}
    assert next(edge for edge in payload["edges"] if edge["type"] == "official_supports")["label"] == "支持"
    assert next(edge for edge in payload["edges"] if edge["type"] == "official_supports")["metadata"]["layer"] == "knowledge"
    provenance = next(edge for edge in payload["edges"] if edge["type"] == "knowledge_item_has_source")
    assert provenance["source"] in {node["id"] for node in item_nodes}
    assert provenance["target"] == provenance["metadata"]["evidenceNodeIds"][0]
    unknown = next(edge for edge in payload["edges"] if edge["type"] == "official_unverified")
    assert unknown["label"] == "关联（unverified）"
    assert unknown["metadata"]["status"] == "candidate"
    with server_operator_scope("operator", roles=("operator",)):
        detail = platform_graph.get_platform_knowledge_graph_node_detail(item_nodes[0]["id"])
    PlatformKnowledgeGraphDetailResponse.model_validate(detail)
    assert detail["node"]["metadata"]["revision"] == 2
    assert detail["operatingBoundary"]["fullContentIncluded"] is False
    assert "SECRET" not in json.dumps([payload, detail])
    assert set(graph_store[2]) <= {"central", "team-a", "team-b", "agent-private"}


def test_shared_sources_keep_multiple_topic_memberships(graph_store):
    items, _, _ = graph_store
    shared_item = copy.deepcopy(items["team-a"][0])
    shared_item["knowledgeItemId"] = "second-item"
    shared_item["metadata"]["officialResearchGraph"]["targetDomain"] = "第二主题"
    for relation in shared_item["metadata"]["officialResearchGraph"]["edges"]:
        relation["targetId"] = "second-item"
    items["team-a"].append(shared_item)
    payload = _graph()
    shared_nodes = [node for node in payload["nodes"] if node["type"] in {"source_artifact", "official_research_ref"}
                    and node["metadata"]["ownerId"] == "team-a"]
    assert shared_nodes
    for node in shared_nodes:
        assert len(node["metadata"]["topicIds"]) == 2
        assert "topicId" not in node["metadata"]
    assert len([node for node in payload["nodes"] if node["type"] == "source_artifact"
                and node["metadata"]["ownerId"] == "team-a"]) == 1


def test_platform_lifecycle_and_topic_fallback(graph_store):
    items, sources, _ = graph_store
    sources["team-a"][0]["status"] = "withdrawn"
    items["team-b"][0]["metadata"]["officialResearchGraph"]["status"] = "not_synced"
    items["agent-private"][0]["metadata"] = {}
    items["agent-private"][0]["tags"] = []
    items["agent-private"].append({"knowledgeItemId": "old", "knowledgeBaseId": "same-kb", "content": "SECRET HISTORY"})
    items["agent-private"][0]["supersedesKnowledgeItemId"] = "old"
    payload = _graph()
    assert len([node for node in payload["nodes"] if node["type"] == "knowledge_item"]) == 2
    assert {topic["groupingBasis"] for topic in payload["topics"]} == {"tag", "knowledge_base"}
    assert not any(edge["type"].startswith("official_") for edge in payload["edges"])
    assert "SECRET HISTORY" not in json.dumps(payload)
    tag_item = next(node for node in payload["nodes"] if node["type"] == "knowledge_item" and node["metadata"]["groupingBasis"] == "tag")
    assert "语义标签" in tag_item["metadata"]["groupingReason"]


def test_platform_detail_bounded_and_official_target_checked(graph_store):
    graph_store[0]["team-a"][0]["metadata"]["officialResearchGraph"]["edges"].append(
        {"sourceId": "wrong-target", "targetId": "other-item", "relation": "supports"})
    graph = _graph()
    assert not any(node.get("metadata", {}).get("sourceId") == "wrong-target" for node in graph["nodes"])
    item = next(node for node in graph["nodes"] if node["type"] == "knowledge_item")
    with server_operator_scope("operator", roles=("operator",)):
        detail = platform_graph.get_platform_knowledge_graph_node_detail(item["id"], limit=1)
    assert len(detail["relatedNodes"]) == 1
    assert len(detail["edges"]) <= 1
    assert detail["summaryCounts"]["truncated"] is True
    assert detail["summaryCounts"]["totalRelatedNodeCount"] > 1


@pytest.mark.parametrize("limit,expected", [(0, 1), (-9, 1), (1, 1), (6, 6), (9999, None)])
def test_platform_limit_real_counts_without_dangling_edges(graph_store, limit, expected):
    payload = _graph(limit=limit)
    visible = {node["id"] for node in payload["nodes"]}
    assert len(visible) == (expected or payload["summary"]["totalNodeCount"])
    assert payload["summary"]["nodeCount"] == len(visible)
    assert payload["summary"]["totalEdgeCount"] >= len(payload["edges"])
    assert payload["summary"]["truncated"] == (len(visible) < payload["summary"]["totalNodeCount"])
    assert all(edge["source"] in visible and edge["target"] in visible for edge in payload["edges"])
    assert all(set(edge["metadata"]["evidenceNodeIds"]) <= visible for edge in payload["edges"])


@pytest.mark.parametrize("roles", [None, ("viewer",)])
def test_platform_service_requires_bound_privileged_operator(graph_store, roles):
    if roles is None:
        with pytest.raises(PermissionError):
            platform_graph.get_platform_knowledge_graph()
        with pytest.raises(PermissionError):
            platform_graph.get_platform_knowledge_graph_node_detail("project:vibelution")
    else:
        with server_operator_scope("viewer", roles=roles), pytest.raises(PermissionError):
            platform_graph.get_platform_knowledge_graph()


def test_platform_http_control_identity_rejects_agents_and_client_roles(graph_store, monkeypatch):
    client = TestClient(create_app())
    paths = ["/api/memory/platform-knowledge-graph", "/api/memory/platform-knowledge-graph/node-detail?nodeId=project:vibelution"]
    for path in paths:
        assert client.get(path).status_code == 403
        assert client.get(path, headers={CONTROL_TOKEN_HEADER: "invalid"}).status_code == 403
        assert client.get(path, headers={"X-Vibelution-Operator-Id": "spoof", "X-Vibelution-Operator-Roles": "admin"}).status_code == 403
        token_headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        assert client.get(path, headers={**token_headers, "X-OpenCode-Session": "agent"}).status_code == 403
        monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "viewer")
        assert client.get(path, headers={**token_headers, "X-Vibelution-Operator-Roles": "admin"}).status_code == 403
        monkeypatch.setenv(CONTROL_OPERATOR_ROLES_ENV, "operator")
        assert client.get(path, headers=token_headers).status_code == 200
    assert client.get("/api/memory/platform-knowledge-graph/node-detail?nodeId=unknown", headers=token_headers).status_code == 404
