"""Read-only project memory knowledge graph service."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import agent_directory_service, team_knowledge_service, team_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
DEFAULT_LIMIT = 800
MAX_LIMIT = 5000
BODY_KEYS = {"content", "excerpt", "raw", "prompt", "messages", "transcript"}


def get_memory_knowledge_graph(
    *,
    agent_id: str = "",
    team_id: str = "",
    knowledge_base_id: str = "",
    include: str = "",
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return an ACL-aware, read-only graph of project memory structures."""

    started_at = time.perf_counter()
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_team_id = str(team_id or "").strip()
    normalized_base_id = str(knowledge_base_id or "").strip()
    include_set = _include_set(include)
    node_limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    graph = _GraphBuilder(node_limit)

    project_node_id = "project:vibelution"
    graph.add_node(
        project_node_id,
        "project",
        "Vibelution",
        summary="项目运行结构、Agent、Team、记忆域和知识库的只读图谱根节点。",
        status="active",
        metadata={"root": _rel(_project_root())},
    )

    agents = agent_directory_service.list_agents(include_archived=False)
    agents_by_id = {str(agent.get("agentId") or "").strip(): agent for agent in agents if str(agent.get("agentId") or "").strip()}
    teams = [
        team
        for team in list(team_service.list_teams_compact(include_archived=False).get("teams") or [])
        if isinstance(team, dict) and (not normalized_team_id or str(team.get("teamId") or "") == normalized_team_id)
    ]

    visible_team_ids: set[str] = set()
    visible_base_ids: set[str] = set()
    agent_team_ids: set[str] = set()
    for team in teams:
        team_id_value = str(team.get("teamId") or "").strip()
        if normalized_agent_id and any(
            str(member.get("agentId") or "").strip() == normalized_agent_id
            for member in list(team.get("members") or [])
            if isinstance(member, dict)
        ):
            agent_team_ids.add(team_id_value)
        for base in team_knowledge_service._knowledge_bases_for_team(team_id_value):
            base_id = str(base.get("knowledgeBaseId") or "").strip()
            if normalized_base_id and base_id != normalized_base_id:
                continue
            if team_knowledge_service._can_access(team, base, normalized_agent_id, "read"):
                visible_team_ids.add(team_id_value)
                visible_base_ids.add(base_id)
        if not normalized_agent_id:
            visible_team_ids.add(team_id_value)
    if normalized_agent_id:
        visible_team_ids.update(agent_team_ids)

    for agent in agents:
        agent_id_value = str(agent.get("agentId") or "").strip()
        if not agent_id_value:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        graph.add_node(
            _node_id("agent", agent_id_value),
            "agent",
            str(agent.get("displayName") or agent.get("agentCode") or agent_id_value),
            summary=str(metadata.get("functionalDisplayName") or agent.get("primaryMode") or "").strip(),
            status=str(agent.get("status") or "active"),
            created_at=str(agent.get("createdAt") or ""),
            updated_at=str(agent.get("updatedAt") or ""),
            metadata={
                "agentId": agent_id_value,
                "agentCode": str(agent.get("agentCode") or ""),
                "primaryMode": str(agent.get("primaryMode") or ""),
                "roleKey": str(agent.get("roleKey") or ""),
                "memoryPolicyId": str(agent.get("memoryPolicyId") or ""),
                "workspacePath": str(agent.get("workspacePath") or ""),
            },
        )
        graph.add_edge(project_node_id, _node_id("agent", agent_id_value), "project_has_agent")
        if not normalized_agent_id or normalized_agent_id == agent_id_value:
            memory_node_id = _node_id("agent_private_memory", agent_id_value)
            graph.add_node(
                memory_node_id,
                "agent_private_memory",
                f"{str(agent.get('displayName') or agent_id_value)} 私有记忆",
                summary="Agent 私有记忆域；图谱只展示结构入口，不展开记忆正文。",
                status="visible" if not normalized_agent_id or normalized_agent_id == agent_id_value else "restricted",
                metadata={
                    "agentId": agent_id_value,
                    "storage": f"workspace/agents/{agent_id_value}/memory",
                    "fullContentIncluded": False,
                },
            )
            graph.add_edge(_node_id("agent", agent_id_value), memory_node_id, "agent_has_private_memory")

    for team in teams:
        team_id_value = str(team.get("teamId") or "").strip()
        if not team_id_value or team_id_value not in visible_team_ids:
            continue
        team_node_id = _node_id("team", team_id_value)
        graph.add_node(
            team_node_id,
            "team",
            str(team.get("name") or team_id_value),
            summary=str(team.get("purpose") or team.get("description") or ""),
            status=str(team.get("status") or "active"),
            created_at=str(team.get("createdAt") or ""),
            updated_at=str(team.get("updatedAt") or ""),
            metadata={
                "teamId": team_id_value,
                "memberCount": int(team.get("memberCount") or len(list(team.get("members") or []))),
                "linkedChatRoomId": str(team.get("linkedChatRoomId") or ""),
                "canvasPath": str(team.get("canvasPath") or ""),
            },
        )
        graph.add_edge(project_node_id, team_node_id, "project_has_team")
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            member_agent_id = str(member.get("agentId") or "").strip()
            if not member_agent_id:
                continue
            graph.add_edge(
                team_node_id,
                _node_id("agent", member_agent_id),
                "team_has_agent",
                label=str(member.get("role") or "member"),
                metadata={"role": str(member.get("role") or "member"), "agentStatus": str(member.get("agentStatus") or "")},
            )

        for base in team_knowledge_service._knowledge_bases_for_team(team_id_value):
            base_id = str(base.get("knowledgeBaseId") or "").strip()
            if not base_id or base_id not in visible_base_ids:
                continue
            if not team_knowledge_service._can_access(team, base, normalized_agent_id, "read"):
                continue
            _add_knowledge_base_subgraph(
                graph,
                team=team,
                base=base,
                team_node_id=team_node_id,
                agents_by_id=agents_by_id,
                include_set=include_set,
            )

    if "runtime" in include_set or "all" in include_set or not include_set:
        _add_runtime_scene_nodes(graph, project_node_id)
    if "evolution" in include_set or "all" in include_set or not include_set:
        _add_file_backed_domain_node(
            graph,
            project_node_id,
            node_type="evolution",
            node_key="self-evolution",
            label="自进化",
            paths=["workspace/evolution/audit.jsonl", "workspace/gym/active_promotions.json"],
            edge_type="project_has_evolution",
        )
    if "supervision" in include_set or "all" in include_set or not include_set:
        _add_file_backed_domain_node(
            graph,
            project_node_id,
            node_type="supervision",
            node_key="supervised-evolution",
            label="监督进化",
            paths=["workspace/supervised_evolution/history.jsonl", "workspace/supervised_evolution/workbench_state.json"],
            edge_type="project_has_supervision",
        )

    payload = graph.to_payload(
        agent_id=normalized_agent_id,
        filters={
            "teamId": normalized_team_id,
            "knowledgeBaseId": normalized_base_id,
            "include": sorted(include_set),
            "limit": node_limit,
        },
        elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
    )
    _record_graph_event(payload, normalized_agent_id)
    return payload


class _GraphBuilder:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.truncated = False

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        summary: str = "",
        status: str = "",
        created_at: str = "",
        updated_at: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not node_id or node_id in self.nodes:
            return
        if len(self.nodes) >= self.limit:
            self.truncated = True
            return
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": _trim(label, 160),
            "summary": _trim(summary, 600),
            "status": _trim(status, 80),
            "createdAt": created_at,
            "updatedAt": updated_at,
            "metadata": _sanitize_metadata(metadata or {}),
        }

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        label: str = "",
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not source or not target or source not in self.nodes or target not in self.nodes:
            return
        edge_id = f"{edge_type}:{source}->{target}"
        if edge_id in self.edges:
            return
        self.edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type,
            "label": _trim(label, 120),
            "weight": weight,
            "metadata": _sanitize_metadata(metadata or {}),
        }

    def to_payload(self, *, agent_id: str, filters: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
        nodes = list(self.nodes.values())
        edges = list(self.edges.values())
        node_counts: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        for node in nodes:
            node_counts[str(node.get("type") or "")] = node_counts.get(str(node.get("type") or ""), 0) + 1
        for edge in edges:
            edge_counts[str(edge.get("type") or "")] = edge_counts.get(str(edge.get("type") or ""), 0) + 1
        return {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "read_only_project_memory_graph",
            "agentId": agent_id,
            "summary": {
                "nodeCount": len(nodes),
                "edgeCount": len(edges),
                "truncated": self.truncated,
                "nodeTypeCounts": node_counts,
                "edgeTypeCounts": edge_counts,
                "elapsedMs": round(elapsed_ms, 2),
            },
            "nodes": nodes,
            "edges": edges,
            "filters": filters,
            "operatingBoundary": {
                "readOnly": True,
                "gpuPreferred": True,
                "layoutWorker": True,
                "honorsKnowledgeAcl": True,
                "fullContentIncluded": False,
                "canEditGraph": False,
                "canApplyKnowledge": False,
            },
        }


def _add_knowledge_base_subgraph(
    graph: _GraphBuilder,
    *,
    team: dict[str, Any],
    base: dict[str, Any],
    team_node_id: str,
    agents_by_id: dict[str, dict[str, Any]],
    include_set: set[str],
) -> None:
    team_id = str(team.get("teamId") or "").strip()
    base_id = str(base.get("knowledgeBaseId") or "").strip()
    base_node_id = _node_id("knowledge_base", base_id)
    stats = team_knowledge_service._knowledge_base_stats(team_id, base_id)
    graph.add_node(
        base_node_id,
        "knowledge_base",
        str(base.get("name") or base_id),
        summary=str(base.get("description") or ""),
        status=str(base.get("status") or "active"),
        created_at=str(base.get("createdAt") or ""),
        updated_at=str(base.get("updatedAt") or ""),
        metadata={
            "knowledgeBaseId": base_id,
            "teamId": team_id,
            "stats": stats,
            "fullContentIncluded": False,
        },
    )
    graph.add_edge(team_node_id, base_node_id, "team_owns_knowledge_base")

    artifacts = team_knowledge_service._source_artifacts_for_base(team_id, base_id)
    proposals = [
        item
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._proposals_path(team_id))
        if str(item.get("targetKnowledgeBaseId") or "") == base_id
    ]
    batches = [
        item
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._batches_path(team_id))
        if str(item.get("knowledgeBaseId") or "") == base_id
    ]
    items = [
        item
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._items_path(team_id))
        if str(item.get("knowledgeBaseId") or "") == base_id
    ]
    suggestions = [
        item
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._rating_suggestions_path(team_id))
        if str(item.get("knowledgeBaseId") or "") == base_id
    ]
    artifact_nodes = {_node_id("source_artifact", str(item.get("sourceArtifactId") or "")): item for item in artifacts}
    proposal_nodes = {_node_id("refinement_proposal", str(item.get("proposalId") or "")): item for item in proposals}
    batch_nodes = {_node_id("knowledge_batch", str(item.get("batchId") or "")): item for item in batches}
    item_nodes = {_node_id("knowledge_item", str(item.get("knowledgeItemId") or "")): item for item in items}

    for artifact_node_id, artifact in artifact_nodes.items():
        artifact_id = str(artifact.get("sourceArtifactId") or "")
        graph.add_node(
            artifact_node_id,
            "source_artifact",
            str(artifact.get("title") or artifact.get("sourceType") or artifact_id),
            summary=str(artifact.get("summary") or ""),
            status=str(artifact.get("sourceType") or ""),
            created_at=str(artifact.get("capturedAt") or ""),
            updated_at=str(artifact.get("capturedAt") or ""),
            metadata={
                "sourceArtifactId": artifact_id,
                "sourceType": str(artifact.get("sourceType") or ""),
                "sourceRef": _sanitize_source_ref(artifact.get("sourceRef")),
                "capturedBy": str(artifact.get("capturedBy") or ""),
            },
        )
        graph.add_edge(base_node_id, artifact_node_id, "knowledge_base_has_source")
        captured_by = str(artifact.get("capturedBy") or "").strip()
        if captured_by:
            graph.add_edge(_node_id("agent", captured_by), artifact_node_id, "agent_authored_source")

    for proposal_node_id, proposal in proposal_nodes.items():
        proposal_id = str(proposal.get("proposalId") or "")
        graph.add_node(
            proposal_node_id,
            "refinement_proposal",
            str(proposal.get("title") or proposal_id),
            summary=str(proposal.get("summary") or ""),
            status=str(proposal.get("status") or "pending"),
            created_at=str(proposal.get("createdAt") or ""),
            updated_at=str(proposal.get("updatedAt") or ""),
            metadata={
                "proposalId": proposal_id,
                "proposedByAgentId": str(proposal.get("proposedByAgentId") or ""),
                "sourceArtifactIds": _string_list(proposal.get("sourceArtifactIds"), limit=12),
                "knowledgeItemIds": _string_list(proposal.get("knowledgeItemIds"), limit=12),
                "fullContentIncluded": False,
            },
        )
        graph.add_edge(base_node_id, proposal_node_id, "knowledge_base_has_proposal")
        proposed_by = str(proposal.get("proposedByAgentId") or "").strip()
        if proposed_by:
            graph.add_edge(_node_id("agent", proposed_by), proposal_node_id, "agent_proposed_refinement")
        reviewed_by = str(proposal.get("reviewedByAgentId") or "").strip()
        if reviewed_by:
            graph.add_edge(_node_id("agent", reviewed_by), proposal_node_id, "agent_reviewed_proposal")
        for source_id in _string_list(proposal.get("sourceArtifactIds"), limit=80):
            graph.add_edge(_node_id("source_artifact", source_id), proposal_node_id, "source_supports_proposal")

    for batch_node_id, batch in batch_nodes.items():
        batch_id = str(batch.get("batchId") or "")
        graph.add_node(
            batch_node_id,
            "knowledge_batch",
            batch_id,
            summary="知识提案审核后形成的正式落盘批次。",
            status=str(batch.get("status") or "applied"),
            created_at=str(batch.get("appliedAt") or ""),
            updated_at=str(batch.get("appliedAt") or ""),
            metadata={
                "batchId": batch_id,
                "reviewedByAgentId": str(batch.get("reviewedByAgentId") or ""),
                "proposalIds": _string_list(batch.get("proposalIds"), limit=12),
                "sourceArtifactIds": _string_list(batch.get("sourceArtifactIds"), limit=12),
            },
        )
        graph.add_edge(base_node_id, batch_node_id, "knowledge_base_has_batch")
        reviewed_by = str(batch.get("reviewedByAgentId") or "").strip()
        if reviewed_by:
            graph.add_edge(_node_id("agent", reviewed_by), batch_node_id, "agent_reviewed_batch")
        for proposal_id in _string_list(batch.get("proposalIds"), limit=80):
            graph.add_edge(_node_id("refinement_proposal", proposal_id), batch_node_id, "proposal_applied_to_batch")

    for item_node_id, item in item_nodes.items():
        item_id = str(item.get("knowledgeItemId") or "")
        graph.add_node(
            item_node_id,
            "knowledge_item",
            str(item.get("title") or item_id),
            summary=str(item.get("summary") or ""),
            status=str(item.get("importanceLevel") or "medium"),
            created_at=str(item.get("createdAt") or ""),
            updated_at=str(item.get("updatedAt") or ""),
            metadata={
                "knowledgeItemId": item_id,
                "importanceLevel": str(item.get("importanceLevel") or ""),
                "confidence": item.get("confidence"),
                "stability": str(item.get("stability") or ""),
                "scope": str(item.get("scope") or ""),
                "reviewPriority": str(item.get("reviewPriority") or ""),
                "tags": _string_list(item.get("tags"), limit=20),
                "fullContentIncluded": False,
            },
        )
        graph.add_edge(base_node_id, item_node_id, "knowledge_base_contains_item")
        batch_id = str(item.get("batchId") or "").strip()
        if batch_id:
            graph.add_edge(_node_id("knowledge_batch", batch_id), item_node_id, "batch_created_item")
        for source_id in _string_list(item.get("sourceArtifactIds"), limit=80):
            graph.add_edge(item_node_id, _node_id("source_artifact", source_id), "item_derived_from_source")
        for tag in _string_list(item.get("tags"), limit=20):
            tag_node_id = _node_id("tag", tag)
            graph.add_node(tag_node_id, "tag", tag, summary="知识条目标签/概念节点。", status="active", metadata={"tag": tag})
            graph.add_edge(item_node_id, tag_node_id, "item_tagged_as_concept")
        marked_by = str(item.get("markedBy") or "").strip()
        if marked_by:
            graph.add_edge(_node_id("agent", marked_by), item_node_id, "agent_marked_rating")

    for suggestion in suggestions:
        suggestion_id = str(suggestion.get("suggestionId") or "").strip()
        if not suggestion_id:
            continue
        suggestion_node_id = _node_id("rating_suggestion", suggestion_id)
        graph.add_node(
            suggestion_node_id,
            "rating_suggestion",
            str(suggestion.get("importanceLevel") or suggestion_id),
            summary=str(suggestion.get("markingReason") or ""),
            status=str(suggestion.get("status") or "pending"),
            created_at=str(suggestion.get("createdAt") or ""),
            updated_at=str(suggestion.get("updatedAt") or ""),
            metadata={
                "suggestionId": suggestion_id,
                "targetType": str(suggestion.get("targetType") or ""),
                "knowledgeItemId": str(suggestion.get("knowledgeItemId") or ""),
                "proposalId": str(suggestion.get("proposalId") or ""),
                "suggestedByAgentId": str(suggestion.get("suggestedByAgentId") or ""),
            },
        )
        graph.add_edge(base_node_id, suggestion_node_id, "knowledge_base_has_rating_suggestion")
        suggested_by = str(suggestion.get("suggestedByAgentId") or "").strip()
        if suggested_by:
            graph.add_edge(_node_id("agent", suggested_by), suggestion_node_id, "agent_suggested_rating")
        knowledge_item_id = str(suggestion.get("knowledgeItemId") or "").strip()
        if knowledge_item_id:
            graph.add_edge(suggestion_node_id, _node_id("knowledge_item", knowledge_item_id), "rating_suggestion_targets_item")
        proposal_id = str(suggestion.get("proposalId") or "").strip()
        if proposal_id:
            graph.add_edge(suggestion_node_id, _node_id("refinement_proposal", proposal_id), "rating_suggestion_targets_proposal")


def _add_runtime_scene_nodes(graph: _GraphBuilder, project_node_id: str) -> None:
    scene_root = _project_root() / "logs" / "runtime_scenes"
    if not scene_root.exists():
        return
    scene_dirs = sorted([path for path in scene_root.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True)[:12]
    for scene_dir in scene_dirs:
        manifest = _load_json(scene_dir / "manifest.json", fallback={})
        scene_id = scene_dir.name
        node_id = _node_id("runtime_scene", scene_id)
        graph.add_node(
            node_id,
            "runtime_scene",
            str(manifest.get("title") or scene_id) if isinstance(manifest, dict) else scene_id,
            summary=str(manifest.get("summary") or manifest.get("result") or "") if isinstance(manifest, dict) else "",
            status=str(manifest.get("status") or "") if isinstance(manifest, dict) else "",
            created_at=str(manifest.get("started_at") or "") if isinstance(manifest, dict) else "",
            updated_at=str(manifest.get("ended_at") or "") if isinstance(manifest, dict) else "",
            metadata={"sceneId": scene_id, "path": _rel(scene_dir), "fullContentIncluded": False},
        )
        graph.add_edge(project_node_id, node_id, "project_has_runtime_scene")


def _add_file_backed_domain_node(
    graph: _GraphBuilder,
    project_node_id: str,
    *,
    node_type: str,
    node_key: str,
    label: str,
    paths: list[str],
    edge_type: str,
) -> None:
    root = _project_root()
    existing_paths = [path for path in paths if (root / path).exists()]
    if not existing_paths:
        return
    updated_at = ""
    try:
        updated_at = max((root / path).stat().st_mtime for path in existing_paths)
    except OSError:
        updated_at = ""
    node_id = _node_id(node_type, node_key)
    graph.add_node(
        node_id,
        node_type,
        label,
        summary="只读结构节点；详细证据仍通过对应页面或日志显式读取。",
        status="available",
        updated_at=str(updated_at),
        metadata={"paths": existing_paths, "fullContentIncluded": False},
    )
    graph.add_edge(project_node_id, node_id, edge_type)


def _sync_roots() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT
    if team_service.PROJECT_ROOT != PROJECT_ROOT:
        team_service.PROJECT_ROOT = PROJECT_ROOT
    if team_knowledge_service.PROJECT_ROOT != PROJECT_ROOT:
        team_knowledge_service.PROJECT_ROOT = PROJECT_ROOT


def _record_graph_event(payload: dict[str, Any], agent_id: str) -> None:
    try:
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        record_runtime_scene_event(
            "memory_graph_service",
            "memory_graph",
            "memory.knowledge_graph.viewed",
            message="Memory knowledge graph viewed.",
            outcome="observed",
            fields={
                "agentId": agent_id,
                "nodeCount": int(summary.get("nodeCount") or 0),
                "edgeCount": int(summary.get("edgeCount") or 0),
                "truncated": bool(summary.get("truncated")),
                "elapsedMs": float(summary.get("elapsedMs") or 0.0),
            },
        )
    except Exception:
        pass


def _include_set(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").split(",") if item.strip()}


def _node_id(node_type: str, value: str) -> str:
    return f"{node_type}:{_safe_id(value)}"


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in text)[:180] or "unknown"


def _trim(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _sanitize_metadata(value: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if key in BODY_KEYS:
            continue
        if isinstance(item, dict):
            clean[key] = _sanitize_metadata(item)
        elif isinstance(item, list):
            clean[key] = [
                _sanitize_metadata(entry) if isinstance(entry, dict) else entry
                for entry in item[:50]
                if not isinstance(entry, str) or len(entry) <= 500
            ]
        elif isinstance(item, str):
            clean[key] = _trim(item, 500)
        else:
            clean[key] = item
    return clean


def _sanitize_source_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "teamId",
        "roomId",
        "messageRange",
        "roundId",
        "url",
        "filePath",
        "pageRange",
        "query",
        "retrievedAt",
        "runtimeSceneId",
        "runId",
        "eventCode",
        "agentId",
        "sessionId",
        "turnId",
    }
    return _sanitize_metadata({key: value.get(key) for key in allowed if key in value})


def _load_json(path: Path, *, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return fallback


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _rel(path: Path) -> str:
    root = _project_root()
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
