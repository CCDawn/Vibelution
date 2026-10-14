"""Local-operator metadata projection over canonical formal knowledge.

No Agent impersonation, private-file reads, pending proposals, or body exposure.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from .. import team_knowledge_service as knowledge
from ..team_knowledge import lifecycle
from ..knowledge_read_service import _safe_source_url
from ..team_workflow.research_runtime.operator_authorization import require_server_operator
from ..team_workflow.research_runtime.operator_permissions import operator_has_privileged_role
from ..runtime_scene_service import record_runtime_scene_event

OFFICIAL_RELATIONS = {"supports": "支持", "maps_to": "映射到", "inspires": "启发", "approved_for_ingestion": "经审核收录"}


def _boundary() -> dict[str, Any]:
    return {"readOnly": True, "fullContentIncluded": False, "canEditGraph": False,
            "canApplyKnowledge": False, "accessAuthority": "local_operator", "excludedPrivateMemory": True,
            "contentAccess": "metadata_only", "honorsKnowledgeLifecycle": True}


def _project(*, knowledge_base_id: str = ""):
    # The service checks authority even when called outside HTTP.
    # A read projection has no workflow command to execute. Check the same
    # privileged role policy explicitly rather than extending that command table.
    operator = require_server_operator()
    if not operator_has_privileged_role(operator.roles):
        raise PermissionError("command_forbidden")
    from .. import memory_graph_service as graph_api

    graph_api._sync_roots()
    graph = graph_api._GraphBuilder(2**31 - 1)
    topics: dict[str, dict[str, Any]] = {}
    graph.add_node("project:vibelution", "project", "Vibelution", summary="全平台正式知识与来源依据，只读管理视图。")

    def edge(source, target, kind, label, layer, reason, *, evidence=(), confirmed=True):
        graph.add_edge(source, target, kind, label=label, metadata={"layer": layer,
            "status": "confirmed" if confirmed else "candidate", "reason": reason, "evidenceNodeIds": list(evidence)})

    def node_id(kind, owner, value):
        return graph_api._owner_scoped_node_id(kind, owner, value)

    def source_topic_membership(source_node, topic_id):
        metadata = graph.nodes[source_node]["metadata"]
        memberships = metadata.setdefault("topicIds", [])
        if topic_id not in memberships:
            memberships.append(topic_id)
        if len(memberships) > 1:
            # Shared evidence belongs to several reading contexts. Never assign
            # it solely to whichever item happened to be scanned first.
            metadata.pop("topicId", None)
            metadata.pop("topicLabel", None)

    owners = knowledge._iter_knowledge_owners(include_archived=False, include_all_agents=True)
    for owner in owners:
        owner_type, owner_value = owner["ownerType"], owner["ownerId"]
        bases = [base for base in knowledge._knowledge_bases_for_owner(owner)
                 if str(base.get("status") or "active") == "active"
                 and (not knowledge_base_id or knowledge_base_id in {str(base.get("knowledgeBaseId") or ""),
                      knowledge._owner_scoped_knowledge_base_id(owner, str(base.get("knowledgeBaseId") or ""))})]
        if not bases:
            continue
        owner_node = node_id(owner_type, owner, owner_value)
        identity = owner.get(owner_type) or {}
        graph.add_node(owner_node, owner_type, str(identity.get("displayName") or identity.get("name") or owner_value),
                       metadata={"ownerType": owner_type, "ownerId": owner_value})
        edge("project:vibelution", owner_node, f"project_has_{owner_type}", "包含", "ownership", "来自正式知识 owner 注册表。")
        all_items = knowledge._read_jsonl(knowledge._items_path_for_owner(owner))
        for base in bases:
            base_id = str(base.get("knowledgeBaseId") or "")
            base_node = node_id("knowledge_base", owner, base_id)
            base_name = str(base.get("name") or base_id)
            graph.add_node(base_node, "knowledge_base", base_name, summary=str(base.get("description") or ""),
                metadata={"ownerType": owner_type, "ownerId": owner_value, "knowledgeBaseId": base_id})
            edge(owner_node, base_node, f"{owner_type}_has_knowledge_base", "拥有知识库", "ownership", "来自知识库 owner 字段。")
            artifacts = {str(row.get("sourceArtifactId") or ""): row for row in knowledge._source_artifacts_for_base(owner, base_id)}
            states = lifecycle.lifecycle_states_for_base(owner, base, all_items, artifacts)
            financial = knowledge.eligible_financial_items(owner, base, all_items, artifacts)
            for item in all_items:
                item_id = str(item.get("knowledgeItemId") or "")
                if item.get("knowledgeBaseId") != base_id or not item_id or states.get(item_id) != "active":
                    continue
                if financial is not None and item_id not in financial:
                    continue
                raw_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                official = raw_metadata.get("officialResearchGraph") if isinstance(raw_metadata.get("officialResearchGraph"), dict) else {}
                synced = official.get("status") == "synced"
                tags = [str(tag).strip()[:160] for tag in item.get("tags") or [] if isinstance(tag, str) and tag.strip()]
                domain = str(official.get("targetDomain") or "").strip()[:160] if synced else ""
                topic_label = domain or (sorted(set(tags))[0] if tags else base_name)
                basis = "official_target_domain" if domain else "tag" if tags else "knowledge_base"
                topic_key = f"{basis}:{topic_label}" if basis != "knowledge_base" else f"{basis}:{base_node}"
                topic_id = "topic:" + hashlib.sha256(topic_key.encode()).hexdigest()[:24]
                topics.setdefault(topic_id, {"id": topic_id, "label": topic_label, "groupingBasis": basis, "nodeIds": []})
                graph.add_node(topic_id, "topic", topic_label, metadata={"groupingBasis": basis, "topicId": topic_id, "topicLabel": topic_label})
                item_node = node_id("knowledge_item", owner, item_id)
                metadata = {"ownerType": owner_type, "ownerId": owner_value, "knowledgeBaseId": base_id,
                    "knowledgeItemId": item_id, "knowledgeState": "active", "tags": tags, "topicId": topic_id,
                    "topicLabel": topic_label, "groupingBasis": basis, "revision": int(item.get("revision") or 1),
                    "groupingReason": "按已同步科研领域分组。" if domain else "以标签排序首项作为主主题，未表示全部分类。" if tags else "无主题标签，按所属知识库分组。",
                    "sourceArtifactIds": [str(value) for value in item.get("sourceArtifactIds") or []],
                    "centralSourceIds": sorted({str(artifacts[str(value)].get("centralSourceId") or "")
                        for value in item.get("sourceArtifactIds") or [] if str(value) in artifacts and artifacts[str(value)].get("centralSourceId")}),
                    "contentSha256": lifecycle.content_sha256(item), "rootKnowledgeItemId": str(item.get("rootKnowledgeItemId") or item_id),
                    "reviewedByAgentId": str(item.get("reviewedByAgentId") or official.get("reviewedByAgentId") or ""),
                    "reviewedAt": str(item.get("reviewedAt") or official.get("reviewedAt") or ""),
                    "proposalId": str(official.get("proposalId") or ""), "batchId": str(item.get("batchId") or official.get("batchId") or ""),
                    "fullContentIncluded": False}
                graph.add_node(item_node, "knowledge_item", str(item.get("title") or item_id), summary=str(item.get("summary") or ""),
                    status="active", created_at=str(item.get("createdAt") or ""), updated_at=str(item.get("updatedAt") or ""), metadata=metadata)
                topics[topic_id]["nodeIds"].append(item_node)
                edge(base_node, item_node, "knowledge_base_has_item", "收录", "ownership", "条目已写入正式知识库且当前生命周期有效。")
                edge(topic_id, item_node, "topic_has_item", "归入主题", "knowledge", f"按 {basis} 字段分组，不表示因果或支持关系。")
                for source_id in dict.fromkeys(str(value) for value in item.get("sourceArtifactIds") or []):
                    source = artifacts.get(source_id)
                    if source is None:
                        continue
                    source_node = node_id("source_artifact", owner, f"{base_id}:{source_id}")
                    source_ref = graph_api._sanitize_source_ref(source.get("sourceRef"))
                    if "url" in source_ref:
                        source_ref["url"] = _safe_source_url(source_ref["url"])
                    source_state = lifecycle.source_lifecycle_state(source, now=knowledge.utc_now_iso())
                    graph.add_node(source_node, "source_artifact", str(source.get("title") or source_id), status=source_state,
                        metadata={"ownerType": owner_type, "ownerId": owner_value, "knowledgeBaseId": base_id,
                            "sourceArtifactId": source_id, "centralSourceId": str(source.get("centralSourceId") or ""),
                            "sourceType": str(source.get("sourceType") or ""), "sourceRef": source_ref, "sourceState": source_state,
                            "sourceHash": str(source.get("sourceHash") or ""), "lifecycleRevision": int(source.get("lifecycleRevision") or 0),
                            "capturedAt": str(source.get("capturedAt") or ""), "topicId": topic_id, "topicLabel": topic_label})
                    source_topic_membership(source_node, topic_id)
                    edge(item_node, source_node, "knowledge_item_has_source", "来源于", "evidence", "来自条目已记录的直接来源关联，不等同于独立核实结论。", evidence=[source_node])
                if synced:
                    for relation in official.get("edges") or []:
                        if not isinstance(relation, dict) or not relation.get("sourceId") or not relation.get("relation"):
                            continue
                        if relation.get("targetId") and str(relation["targetId"]) != item_id:
                            continue
                        if relation.get("targetType") and relation["targetType"] != "knowledge_item":
                            continue
                        kind = str(relation["relation"])
                        ref_node = node_id("official_research_ref", owner, f"{relation.get('sourceType') or 'research_ref'}:{relation['sourceId']}")
                        graph.add_node(ref_node, "official_research_ref", str(relation["sourceId"]), status="official_synced",
                            metadata={"ownerType": owner_type, "ownerId": owner_value, "sourceType": str(relation.get("sourceType") or "research_ref"),
                                "sourceId": str(relation["sourceId"]), "topicId": topic_id, "topicLabel": topic_label,
                                "reviewedByAgentId": str(official.get("reviewedByAgentId") or ""), "reviewedAt": str(official.get("reviewedAt") or "")})
                        source_topic_membership(ref_node, topic_id)
                        confirmed = kind in OFFICIAL_RELATIONS and relation.get("edgeState", "official_synced") == "official_synced"
                        edge(ref_node, item_node, f"official_{kind}", OFFICIAL_RELATIONS.get(kind, f"关联（{kind}）"),
                            "knowledge" if kind in {"supports", "maps_to", "inspires"} else "evidence",
                            "来自已审核并同步到正式知识的科研关系记录。" if confirmed else "原关系类型或状态未确认，作为候选关联展示。",
                            evidence=[ref_node], confirmed=confirmed)
    return graph, topics


def get_platform_knowledge_graph(*, limit: int = 800, knowledge_base_id: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    bounded = max(1, min(int(limit), 5000))
    graph, topics = _project(knowledge_base_id=knowledge_base_id)
    payload = graph.to_payload(agent_id="", filters={"limit": bounded, "knowledgeBaseId": knowledge_base_id},
                               elapsed_ms=(time.perf_counter() - started) * 1000)
    total_nodes, total_edges = len(payload["nodes"]), len(payload["edges"])
    payload["nodes"] = payload["nodes"][:bounded]
    visible = {node["id"] for node in payload["nodes"]}
    payload["edges"] = [edge for edge in payload["edges"] if edge["source"] in visible and edge["target"] in visible]
    for node in payload["nodes"]:
        node["childNodeIds"] = [value for value in node["childNodeIds"] if value in visible]
    for edge in payload["edges"]:
        edge["metadata"]["evidenceNodeIds"] = [value for value in edge["metadata"]["evidenceNodeIds"] if value in visible]
    payload.update(mode="read_only_platform_knowledge_graph", operatingBoundary=_boundary(), topics=[
        {**topic, "nodeIds": [node_id for node_id in topic["nodeIds"] if node_id in visible]}
        for topic in topics.values() if topic["id"] in visible])
    payload["summary"].update(nodeCount=len(payload["nodes"]), edgeCount=len(payload["edges"]),
        totalNodeCount=total_nodes, totalEdgeCount=total_edges, topicsCount=len(topics),
        truncated=total_nodes > len(payload["nodes"]), nodeTypeCounts=_counts(payload["nodes"]), edgeTypeCounts=_counts(payload["edges"]))
    try:
        record_runtime_scene_event("memory_graph_service", "memory_graph", "memory.platform_knowledge_graph.viewed",
            message="Platform formal-knowledge metadata graph viewed.", outcome="observed",
            fields={"nodeCount": len(payload["nodes"]), "topicsCount": len(topics),
                    "truncated": payload["summary"]["truncated"], "elapsedMs": payload["summary"]["elapsedMs"],
                    "accessAuthority": "local_operator", "fullContentIncluded": False})
    except Exception:
        pass
    return payload


def _counts(rows):
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return counts


def get_platform_knowledge_graph_node_detail(node_id: str, *, limit: int = 40) -> dict[str, Any] | None:
    graph, _ = _project()
    node = graph.nodes.get(node_id)
    if node is None:
        return None
    edges = [edge for edge in graph.edges.values() if node_id in {edge["source"], edge["target"]}]
    related_ids = {value for edge in edges for value in (edge["source"], edge["target"])} - {node_id}
    bounded = max(1, min(int(limit), 5000))
    selected_ids = sorted(related_ids)[:bounded]
    visible = set(selected_ids) | {node_id}
    selected_edges = [edge for edge in edges if edge["source"] in visible and edge["target"] in visible][:bounded]
    selected_edges = [{**edge, "metadata": {**edge["metadata"], "evidenceNodeIds": [value for value in edge["metadata"]["evidenceNodeIds"] if value in visible]}}
                      for edge in selected_edges]
    return {"schemaVersion": 1, "mode": "read_only_platform_knowledge_graph_node_detail", "agentId": "", "nodeId": node_id,
        "node": node, "relatedNodes": [graph.nodes[value] for value in selected_ids], "edges": selected_edges, "operatingBoundary": _boundary(),
        "summaryCounts": {"relatedNodeCount": len(selected_ids), "totalRelatedNodeCount": len(related_ids),
            "edgeCount": len(selected_edges), "totalEdgeCount": len(edges), "limit": bounded,
            "truncated": len(selected_ids) < len(related_ids) or len(selected_edges) < len(edges)}}
