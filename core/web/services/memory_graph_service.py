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
DETAIL_ITEM_LIMIT = 24
NODE_DETAIL_ITEM_LIMIT = 40
NODE_DETAIL_CONTENT_LIMIT = 12000


class MemoryKnowledgeGraphAmbiguousNodeError(ValueError):
    """Raised when an unscoped graph node id matches multiple accessible owners."""


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
    filter_owner_type, filter_owner_id, normalized_base_id = _parse_owner_scoped_node_value(knowledge_base_id)
    include_set = _include_set(include)
    node_limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    graph = _GraphBuilder(node_limit)
    detail_cache: dict[str, list[dict[str, Any]]] = {}

    project_node_id = "project:vibelution"
    agents = agent_directory_service.list_agents(include_archived=False)
    agents_by_id = {str(agent.get("agentId") or "").strip(): agent for agent in agents if str(agent.get("agentId") or "").strip()}
    team_member_agent_ids: set[str] = set()
    teams = [
        team
        for team in list(team_service.list_team_graph_references(include_archived=False).get("teams") or [])
        if isinstance(team, dict) and (not normalized_team_id or str(team.get("teamId") or "") == normalized_team_id)
    ]
    for team in teams:
        for member in list(team.get("members") or []):
            if isinstance(member, dict):
                member_agent_id = str(member.get("agentId") or "").strip()
                if member_agent_id:
                    team_member_agent_ids.add(member_agent_id)

    visible_team_ids: set[str] = set()
    visible_agent_ids: set[str] = set()
    agent_team_ids: set[str] = set()
    for team in teams:
        team_id_value = str(team.get("teamId") or "").strip()
        team_owner = team_knowledge_service._owner_context("team", team_id_value, team=team)
        if normalized_agent_id and any(
            str(member.get("agentId") or "").strip() == normalized_agent_id
            for member in list(team.get("members") or [])
            if isinstance(member, dict)
        ):
            agent_team_ids.add(team_id_value)
        for base in team_knowledge_service._knowledge_bases_for_owner(team_owner):
            base_id = str(base.get("knowledgeBaseId") or "").strip()
            if not _knowledge_base_matches_filter(team_owner, base, filter_owner_type, filter_owner_id, normalized_base_id):
                continue
            if team_knowledge_service._can_access(team_owner, base, normalized_agent_id, "read"):
                visible_team_ids.add(team_id_value)
                for member in list(team.get("members") or []):
                    if isinstance(member, dict):
                        member_agent_id = str(member.get("agentId") or "").strip()
                        if member_agent_id:
                            visible_agent_ids.add(member_agent_id)
    if normalized_agent_id:
        visible_agent_ids.add(normalized_agent_id)
        visible_team_ids.update(agent_team_ids)
        for team in teams:
            team_id_value = str(team.get("teamId") or "").strip()
            if team_id_value in visible_team_ids:
                for member in list(team.get("members") or []):
                    if isinstance(member, dict):
                        member_agent_id = str(member.get("agentId") or "").strip()
                        if member_agent_id:
                            visible_agent_ids.add(member_agent_id)

    project_child_node_ids = [
        _node_id("team", str(team.get("teamId") or "").strip())
        for team in teams
        if str(team.get("teamId") or "").strip() in visible_team_ids
    ]
    project_child_node_ids.extend(
        _node_id("agent", agent_id_value)
        for agent_id_value in sorted(visible_agent_ids)
        if agent_id_value not in team_member_agent_ids and agent_id_value in agents_by_id
    )
    graph.add_node(
        project_node_id,
        "project",
        "Vibelution",
        summary="项目运行结构、Agent、Team、记忆域和知识库的只读图谱根节点。",
        status="active",
        metadata={"root": _rel(_project_root())},
        responsibility_question=_responsibility_question("project", {"label": "Vibelution"}),
        visual={"size": "root"},
        child_node_ids=project_child_node_ids,
    )

    for agent in agents:
        agent_id_value = str(agent.get("agentId") or "").strip()
        if not agent_id_value or agent_id_value not in visible_agent_ids:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        agent_category = "team_member_agent" if agent_id_value in team_member_agent_ids else "session_agent"
        agent_detail = _owner_knowledge_detail(
            team_knowledge_service._owner_context("agent", agent_id_value, agent=agent),
            normalized_agent_id,
            cache=detail_cache,
        )
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
                "agentCategory": agent_category,
            },
            responsibility_question=_responsibility_question("agent", agent, agent_category=agent_category),
            visual={"size": "leaf", "agentCategory": agent_category},
            content_items=agent_detail,
        )
        graph.add_edge(project_node_id, _node_id("agent", agent_id_value), "project_has_agent")

    for team in teams:
        team_id_value = str(team.get("teamId") or "").strip()
        if not team_id_value or team_id_value not in visible_team_ids:
            continue
        team_node_id = _node_id("team", team_id_value)
        child_node_ids = [
            _node_id("agent", str(member.get("agentId") or "").strip())
            for member in list(team.get("members") or [])
            if isinstance(member, dict) and str(member.get("agentId") or "").strip() in visible_agent_ids and str(member.get("agentId") or "").strip() in agents_by_id
        ]
        team_detail = _owner_knowledge_detail(
            team_knowledge_service._owner_context("team", team_id_value, team=team),
            normalized_agent_id,
            cache=detail_cache,
        )
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
            responsibility_question=_responsibility_question("team", team),
            visual={"size": "group"},
            child_node_ids=child_node_ids,
            content_items=team_detail,
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
        if "officialresearchgraph" in include_set or "official_research_graph" in include_set or "all" in include_set:
            _add_official_research_graph_nodes(
                graph,
                team_node_id,
                team_knowledge_service._owner_context("team", team_id_value, team=team),
                actor_agent_id=normalized_agent_id,
                knowledge_base_owner_type=filter_owner_type,
                knowledge_base_owner_id=filter_owner_id,
                knowledge_base_id=normalized_base_id,
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
            "knowledgeBaseOwnerType": filter_owner_type,
            "knowledgeBaseOwnerId": filter_owner_id,
            "include": sorted(include_set),
            "limit": node_limit,
        },
        elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
    )
    _record_graph_event(payload, normalized_agent_id)
    return payload


def get_memory_knowledge_graph_node_detail(node_id: str, *, agent_id: str = "", limit: int = NODE_DETAIL_ITEM_LIMIT) -> dict[str, Any] | None:
    """Return full formal-knowledge content for one graph node, honoring the same ACL boundary as Team Knowledge."""

    started_at = time.perf_counter()
    _sync_roots()
    normalized_node_id = str(node_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(int(limit or NODE_DETAIL_ITEM_LIMIT), NODE_DETAIL_ITEM_LIMIT))
    try:
        resolved = _resolve_node_detail(normalized_node_id, normalized_agent_id, limit=bounded_limit)
    except MemoryKnowledgeGraphAmbiguousNodeError:
        _record_node_detail_event(
            normalized_node_id,
            normalized_agent_id,
            item_count=0,
            found=False,
            elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
            outcome="ambiguous",
            reason="owner_scope_required",
        )
        raise
    if resolved is None:
        _record_node_detail_event(
            normalized_node_id,
            normalized_agent_id,
            item_count=0,
            found=False,
            elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
        )
        return None
    content_items = resolved.get("contentItems") if isinstance(resolved.get("contentItems"), list) else []
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "read_only_project_memory_graph_node_detail",
        "nodeId": normalized_node_id,
        "agentId": normalized_agent_id,
        "nodeType": str(resolved.get("nodeType") or ""),
        "label": str(resolved.get("label") or ""),
        "summary": str(resolved.get("summary") or ""),
        "contentItems": content_items,
        "summaryCounts": {
            "contentItemCount": len(content_items),
            "truncatedContentItemCount": sum(1 for item in content_items if bool(item.get("contentTruncated"))),
        },
        "operatingBoundary": {
            "readOnly": True,
            "honorsKnowledgeAcl": True,
            "fullContentIncluded": True,
            "canEditGraph": False,
            "canApplyKnowledge": False,
        },
        "elapsedMs": round((time.perf_counter() - started_at) * 1000.0, 2),
    }
    _record_node_detail_event(
        normalized_node_id,
        normalized_agent_id,
        item_count=len(content_items),
        found=True,
        elapsed_ms=float(payload["elapsedMs"]),
    )
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
        responsibility_question: str = "",
        visual: dict[str, Any] | None = None,
        child_node_ids: list[str] | None = None,
        content_items: list[dict[str, Any]] | None = None,
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
            "responsibilityQuestion": _trim(responsibility_question or _responsibility_question(node_type, {"label": label}), 180),
            "visual": _sanitize_metadata(visual or _default_visual(node_type)),
            "childNodeIds": _string_list(child_node_ids or [], limit=80),
            "contentItems": _sanitize_content_items(content_items or [], limit=DETAIL_ITEM_LIMIT),
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


def _add_official_research_graph_nodes(
    graph: _GraphBuilder,
    team_node_id: str,
    owner: dict[str, Any],
    *,
    actor_agent_id: str,
    knowledge_base_owner_type: str,
    knowledge_base_owner_id: str,
    knowledge_base_id: str,
) -> None:
    for base in team_knowledge_service._knowledge_bases_for_owner(owner):
        base_id = str(base.get("knowledgeBaseId") or "").strip()
        if not _knowledge_base_matches_filter(owner, base, knowledge_base_owner_type, knowledge_base_owner_id, knowledge_base_id):
            continue
        if not team_knowledge_service._can_access(owner, base, actor_agent_id, "read"):
            continue
        base_node_id = _owner_scoped_node_id("knowledge_base", owner, base_id)
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
                "ownerType": owner.get("ownerType"),
                "ownerId": owner.get("ownerId"),
                "legacyNodeId": _node_id("knowledge_base", base_id),
            },
            responsibility_question=_responsibility_question("knowledge_base", base),
            visual={"size": "container"},
        )
        graph.add_edge(team_node_id, base_node_id, "team_has_knowledge_base")
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner)):
            if str(item.get("knowledgeBaseId") or "") != base_id:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            official_graph = metadata.get("officialResearchGraph") if isinstance(metadata.get("officialResearchGraph"), dict) else {}
            if str(official_graph.get("status") or "") != "synced":
                continue
            item_id = str(item.get("knowledgeItemId") or "").strip()
            if not item_id:
                continue
            item_node_id = _owner_scoped_node_id("knowledge_item", owner, item_id)
            graph.add_node(
                item_node_id,
                "knowledge_item",
                str(item.get("title") or item_id),
                summary=str(item.get("summary") or ""),
                status=str(item.get("importanceLevel") or "medium"),
                created_at=str(item.get("createdAt") or ""),
                updated_at=str(item.get("updatedAt") or item.get("appliedAt") or ""),
                metadata={
                    "knowledgeItemId": item_id,
                    "knowledgeBaseId": base_id,
                    "ownerType": owner.get("ownerType"),
                    "ownerId": owner.get("ownerId"),
                    "graphKind": str(official_graph.get("graphKind") or "formal_research_trace"),
                    "edgeCount": int((official_graph.get("summary") or {}).get("edgeCount") or 0)
                    if isinstance(official_graph.get("summary"), dict)
                    else 0,
                    "fullContentIncluded": False,
                    "legacyNodeId": _node_id("knowledge_item", item_id),
                },
                visual={"size": "leaf"},
                content_items=[],
            )
            graph.add_edge(base_node_id, item_node_id, "knowledge_base_has_item")
            for edge in official_graph.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                source_id = str(edge.get("sourceId") or "").strip()
                relation = str(edge.get("relation") or "").strip()
                if not source_id or not relation:
                    continue
                source_type = str(edge.get("sourceType") or "research_ref").strip() or "research_ref"
                ref_node_id = _node_id("official_research_ref", f"{source_type}:{source_id}")
                graph.add_node(
                    ref_node_id,
                    "official_research_ref",
                    source_id,
                    summary=f"{source_type} reference promoted into formal research trace.",
                    status="official_synced",
                    metadata={
                        "sourceId": source_id,
                        "sourceType": source_type,
                        "knowledgeItemId": item_id,
                        "knowledgeBaseId": base_id,
                        "fullContentIncluded": False,
                    },
                    visual={"size": "support", "sourceType": source_type},
                )
                graph.add_edge(
                    ref_node_id,
                    item_node_id,
                    f"official_{relation}",
                    label=relation,
                    metadata={
                        "relation": relation,
                        "edgeState": str(edge.get("edgeState") or "official_synced"),
                        "targetType": str(edge.get("targetType") or "knowledge_item"),
                    },
                )


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


def record_memory_knowledge_graph_blocked(*, reason: str, team_id: str = "", knowledge_base_id: str = "", include: str = "") -> None:
    try:
        record_runtime_scene_event(
            "memory_graph_service",
            "memory_graph",
            "memory.knowledge_graph.blocked",
            message="Memory knowledge graph request blocked.",
            outcome="blocked",
            fields={
                "reason": str(reason or "").strip(),
                "teamId": str(team_id or "").strip(),
                "knowledgeBaseId": str(knowledge_base_id or "").strip(),
                "include": sorted(_include_set(include)),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _record_node_detail_event(
    node_id: str,
    agent_id: str,
    *,
    item_count: int,
    found: bool,
    elapsed_ms: float,
    outcome: str = "",
    reason: str = "",
) -> None:
    try:
        normalized_outcome = outcome or ("observed" if found else "not_found")
        record_runtime_scene_event(
            "memory_graph_service",
            "memory_graph",
            "memory.knowledge_graph.node_detail.viewed",
            message="Memory knowledge graph node detail viewed.",
            outcome=normalized_outcome,
            fields={
                "agentId": agent_id,
                "nodeId": node_id,
                "contentItemCount": int(item_count),
                "elapsedMs": round(float(elapsed_ms), 2),
                "fullContentIncluded": True,
                "reason": reason,
            },
        )
    except Exception:
        pass


def _resolve_node_detail(node_id: str, actor_agent_id: str, *, limit: int) -> dict[str, Any] | None:
    node_type, raw_value = _parse_node_id(node_id)
    if not node_type or not raw_value:
        return {"nodeType": node_type, "label": node_id, "summary": "", "contentItems": []}
    if node_type == "team":
        team = _get_team_or_none(raw_value)
        if not team:
            return None
        owner = team_knowledge_service._owner_context("team", raw_value, team=team)
        return {
            "nodeType": "team",
            "label": str(team.get("name") or raw_value),
            "summary": str(team.get("purpose") or team.get("description") or ""),
            "contentItems": _owner_full_knowledge_detail(owner, actor_agent_id, limit=limit),
        }
    if node_type == "agent":
        agent = agent_directory_service.get_agent(raw_value, include_archived=True)
        if not agent:
            return None
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        owner = team_knowledge_service._owner_context("agent", raw_value, agent=agent)
        return {
            "nodeType": "agent",
            "label": str(agent.get("displayName") or agent.get("agentCode") or raw_value),
            "summary": str(metadata.get("functionalDisplayName") or agent.get("primaryMode") or ""),
            "contentItems": _owner_full_knowledge_detail(owner, actor_agent_id, limit=limit),
        }
    if node_type == "knowledge_base":
        found = _find_accessible_knowledge_base(raw_value, actor_agent_id)
        if found is None:
            return None
        owner, base = found
        return {
            "nodeType": "knowledge_base",
            "label": str(base.get("name") or raw_value),
            "summary": str(base.get("description") or ""),
            "contentItems": _base_full_knowledge_detail(owner, base, limit=limit),
        }
    if node_type == "knowledge_item":
        found_item = _find_accessible_knowledge_item(raw_value, actor_agent_id)
        if found_item is None:
            return None
        owner, base, item = found_item
        return {
            "nodeType": "knowledge_item",
            "label": str(item.get("title") or raw_value),
            "summary": str(item.get("summary") or ""),
            "contentItems": [_full_knowledge_item_detail(item, base=base, owner=owner)],
        }
    return {"nodeType": node_type, "label": node_id, "summary": "", "contentItems": []}


def _owner_full_knowledge_detail(owner: dict[str, Any], actor_agent_id: str, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] | None = None
    for base in team_knowledge_service._knowledge_bases_for_owner(owner):
        if not team_knowledge_service._can_access(owner, base, actor_agent_id, "read"):
            continue
        if all_items is None:
            all_items = team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
        items.extend(_items_for_base_full_detail(owner, base, all_items))
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return items[:limit]


def _base_full_knowledge_detail(owner: dict[str, Any], base: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    all_items = team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
    items = _items_for_base_full_detail(owner, base, all_items)
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return items[:limit]


def _items_for_base_full_detail(
    owner: dict[str, Any],
    base: dict[str, Any],
    all_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_id = str(base.get("knowledgeBaseId") or "").strip()
    items: list[dict[str, Any]] = []
    for item in all_items:
        if str(item.get("knowledgeBaseId") or "") != base_id:
            continue
        items.append(_full_knowledge_item_detail(item, base=base, owner=owner))
    return items


def _find_accessible_knowledge_base(knowledge_base_id: str, actor_agent_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    owner_type, owner_id, normalized_base_id = _parse_owner_scoped_node_value(knowledge_base_id)
    if not normalized_base_id:
        return None
    has_owner_scope = bool(owner_type and owner_id)
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for owner in _iter_known_knowledge_owners():
        if has_owner_scope and not _owner_matches_scope(owner, owner_type, owner_id):
            continue
        for base in team_knowledge_service._knowledge_bases_for_owner(owner):
            if not _node_fragment_matches(base.get("knowledgeBaseId"), normalized_base_id):
                continue
            if not team_knowledge_service._can_access(owner, base, actor_agent_id, "read"):
                if has_owner_scope:
                    return None
                continue
            if has_owner_scope:
                return owner, base
            matches.append((owner, base))
    if len(matches) > 1:
        raise MemoryKnowledgeGraphAmbiguousNodeError("Memory graph node id is ambiguous across owners; use owner-scoped node id.")
    return matches[0] if matches else None


def _find_accessible_knowledge_item(knowledge_item_id: str, actor_agent_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    owner_type, owner_id, normalized_item_id = _parse_owner_scoped_node_value(knowledge_item_id)
    if not normalized_item_id:
        return None
    has_owner_scope = bool(owner_type and owner_id)
    matches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for owner in _iter_known_knowledge_owners():
        if has_owner_scope and not _owner_matches_scope(owner, owner_type, owner_id):
            continue
        for item in team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner)):
            if not _node_fragment_matches(item.get("knowledgeItemId"), normalized_item_id):
                continue
            base = team_knowledge_service._find_knowledge_base_for_owner(owner, str(item.get("knowledgeBaseId") or ""))
            if not base:
                if has_owner_scope:
                    return None
                continue
            if not team_knowledge_service._can_access(owner, base, actor_agent_id, "read"):
                if has_owner_scope:
                    return None
                continue
            if has_owner_scope:
                return owner, base, item
            matches.append((owner, base, item))
    if len(matches) > 1:
        raise MemoryKnowledgeGraphAmbiguousNodeError("Memory graph node id is ambiguous across owners; use owner-scoped node id.")
    return matches[0] if matches else None


def _iter_known_knowledge_owners() -> list[dict[str, Any]]:
    owners: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for team in team_service.list_team_graph_references(include_archived=True).get("teams") or []:
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or "").strip()
        key = ("team", team_id)
        if team_id and key not in seen:
            seen.add(key)
            owners.append(team_knowledge_service._owner_context("team", team_id, team=team))
    for agent in agent_directory_service.list_agents(include_archived=True):
        agent_id = str(agent.get("agentId") or "").strip()
        key = ("agent", agent_id)
        if agent_id and key not in seen:
            seen.add(key)
            owners.append(team_knowledge_service._owner_context("agent", agent_id, agent=agent))
    return owners


def _full_knowledge_item_detail(item: dict[str, Any], *, base: dict[str, Any], owner: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content") or "")
    trimmed_content = _trim(content, NODE_DETAIL_CONTENT_LIMIT)
    return {
        **_knowledge_item_detail(item, base=base),
        "ownerType": str(owner.get("ownerType") or item.get("ownerType") or base.get("ownerType") or ""),
        "ownerId": str(owner.get("ownerId") or item.get("ownerId") or base.get("ownerId") or ""),
        "teamId": str(item.get("teamId") or (owner.get("ownerId") if owner.get("ownerType") == "team" else "")),
        "agentId": str(item.get("agentId") or (owner.get("ownerId") if owner.get("ownerType") == "agent" else "")),
        "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
        "content": trimmed_content,
        "contentTruncated": len(content) > len(trimmed_content),
        "sourceArtifactIds": _string_list(item.get("sourceArtifactIds"), limit=24),
        "batchId": str(item.get("batchId") or ""),
        "confidence": item.get("confidence"),
        "stability": str(item.get("stability") or ""),
        "scope": str(item.get("scope") or ""),
        "reviewPriority": str(item.get("reviewPriority") or ""),
        "fullContentIncluded": True,
    }


def _parse_node_id(node_id: str) -> tuple[str, str]:
    normalized = str(node_id or "").strip()
    if ":" not in normalized:
        return "", normalized
    node_type, raw_value = normalized.split(":", 1)
    return node_type.strip(), raw_value.strip()


def _parse_owner_scoped_node_value(value: str) -> tuple[str, str, str]:
    normalized = str(value or "").strip()
    parts = normalized.split(":", 2)
    if len(parts) == 3 and parts[0] in {"team", "agent"} and parts[1].strip() and parts[2].strip():
        return _safe_id(parts[0]), _safe_id(parts[1]), parts[2].strip()
    return "", "", normalized


def _knowledge_base_matches_filter(
    owner: dict[str, Any],
    base: dict[str, Any],
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
) -> bool:
    if owner_type and owner_id and not _owner_matches_scope(owner, owner_type, owner_id):
        return False
    if knowledge_base_id and not _node_fragment_matches(base.get("knowledgeBaseId"), knowledge_base_id):
        return False
    return True


def _get_team_or_none(team_id: str) -> dict[str, Any] | None:
    try:
        return team_service.get_team(team_id)
    except Exception:
        return None


def _owner_knowledge_detail(owner: dict[str, Any], actor_agent_id: str, *, cache: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    cache_key = f"{owner.get('ownerType')}:{owner.get('ownerId')}:{actor_agent_id}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    items: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] | None = None
    for base in team_knowledge_service._knowledge_bases_for_owner(owner):
        if not team_knowledge_service._can_access(owner, base, actor_agent_id, "read"):
            continue
        base_id = str(base.get("knowledgeBaseId") or "").strip()
        if all_items is None:
            all_items = team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
        for item in all_items:
            if str(item.get("knowledgeBaseId") or "") == base_id:
                items.append(_knowledge_item_detail(item, base=base))
            if len(items) >= DETAIL_ITEM_LIMIT:
                if cache is not None:
                    cache[cache_key] = items
                return items
    if cache is not None:
        cache[cache_key] = items
    return items


def _knowledge_item_detail(item: dict[str, Any], *, base: dict[str, Any]) -> dict[str, Any]:
    owner = {
        "ownerType": str(item.get("ownerType") or base.get("ownerType") or ""),
        "ownerId": str(item.get("ownerId") or base.get("ownerId") or ""),
    }
    return {
        "id": _owner_scoped_value(owner, str(item.get("knowledgeItemId") or "")),
        "type": "knowledge_item",
        "title": _trim(item.get("title") or item.get("knowledgeItemId") or "Knowledge item", 160),
        "summary": _trim(item.get("summary") or "", 500),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or item.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "ownerType": str(item.get("ownerType") or base.get("ownerType") or ""),
        "ownerId": str(item.get("ownerId") or base.get("ownerId") or ""),
        "status": str(item.get("importanceLevel") or "medium"),
        "tags": _string_list(item.get("tags"), limit=12),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or item.get("appliedAt") or ""),
        "fullContentIncluded": False,
    }


def _responsibility_question(node_type: str, value: dict[str, Any], *, agent_category: str = "") -> str:
    if node_type == "project":
        return "这个项目级记忆入口负责回答什么全局问题？"
    if node_type == "team":
        name = str(value.get("name") or value.get("label") or "这个团队").strip()
        return f"{name} 负责沉淀和回答什么团队问题？"
    if node_type == "agent":
        label = str(value.get("displayName") or value.get("agentCode") or value.get("label") or "这个 Agent").strip()
        prefix = "会话 Agent" if agent_category == "session_agent" else "团队成员 Agent"
        return f"{prefix} {label} 负责回答什么问题？"
    if node_type == "knowledge_base":
        name = str(value.get("name") or value.get("label") or "这个知识库").strip()
        return f"{name} 负责保存哪类知识？"
    if node_type == "agent_private_memory":
        return "这个 Agent 私有记忆入口负责保存什么个人运行记忆？"
    if node_type == "runtime_scene":
        return "这个运行现场负责证明哪次运行发生了什么？"
    if node_type == "evolution":
        return "自进化记忆负责回答哪些版本演化问题？"
    if node_type == "supervision":
        return "监督进化记忆负责回答哪些评审和晋升问题？"
    return "这个节点负责回答什么问题？"


def _default_visual(node_type: str) -> dict[str, Any]:
    if node_type == "project":
        return {"size": "root"}
    if node_type == "team":
        return {"size": "group"}
    if node_type == "knowledge_base":
        return {"size": "container"}
    if node_type == "agent":
        return {"size": "leaf"}
    return {"size": "support"}


def _sanitize_content_items(value: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            items.append(_sanitize_metadata(item))
    return items


def _include_set(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").split(",") if item.strip()}


def _node_id(node_type: str, value: str) -> str:
    return f"{node_type}:{_safe_id(value)}"


def _owner_scoped_node_id(node_type: str, owner: dict[str, Any], value: str) -> str:
    return f"{node_type}:{_owner_scoped_value(owner, value)}"


def _owner_scoped_value(owner: dict[str, Any], value: str) -> str:
    owner_type = _safe_id(str(owner.get("ownerType") or "").strip())
    owner_id = _safe_id(str(owner.get("ownerId") or "").strip())
    item_id = _safe_id(value)
    if owner_type and owner_type != "unknown" and owner_id and owner_id != "unknown":
        return f"{owner_type}:{owner_id}:{item_id}"
    return item_id


def _owner_matches_scope(owner: dict[str, Any], owner_type: str, owner_id: str) -> bool:
    return _safe_id(str(owner.get("ownerType") or "")) == owner_type and _safe_id(str(owner.get("ownerId") or "")) == owner_id


def _node_fragment_matches(value: Any, fragment: str) -> bool:
    return str(value or "").strip() == fragment or _safe_id(value) == fragment


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
