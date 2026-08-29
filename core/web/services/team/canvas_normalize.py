"""Team canvas normalize / validate / default layout helpers.

Claim scope: node/member/canvas normalization with Agent lookup, validation
issues, default canvas builders, and canvas summary projection.
Late-binds ``team_service`` for index locks, path helpers, and membership conflict
recording. Pure edge normalize remains in canvas_primitives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.web.services import agent_directory_service


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def get_team_canvas(team_id: str) -> dict[str, Any]:
    s = _service()
    agent_refs = s._agent_reference_maps()
    team = s._get_team_record(team_id, agent_refs=agent_refs)
    return s._team_canvas_with_validation(
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )


def list_team_role_binding_sources(team_id: str) -> dict[str, Any]:
    """Return Team members as the sole role→Agent mapping source.

    ``canvas_nodes`` remains as an empty compatibility field for older callers;
    organization canvas data is a projection and never a binding authority.
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, normalized_team_id)
        if team is None:
            return {"team_exists": False, "canvas_nodes": [], "members": []}
        members = [dict(item) for item in list(team.get("members") or []) if isinstance(item, dict)]
    return {"team_exists": True, "canvas_nodes": [], "members": members}


def _team_canvas_with_validation(
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    canvas_path = s._team_canvas_path(team["teamId"])
    raw = s._read_json(canvas_path) if canvas_path.exists() else {}
    canvas = s._normalize_canvas(
        raw or s._default_canvas_for_team(team),
        team,
        agents_by_id=agents_by_id,
        active_agents_by_id=active_agents_by_id,
    )
    if s._default_canvas_edges_missing_for_team(team, canvas_path):
        default_edges = s._default_edges_for_team(team, list(canvas.get("nodes") or []))
        if default_edges:
            previous_edge_count = len(list(canvas.get("edges") or []))
            canvas["edges"] = default_edges
            s._record_team_event(
                "team.canvas.default_edges_repaired",
                team,
                fields={
                    "previousEdgeCount": previous_edge_count,
                    "edgeCount": len(default_edges),
                    "reason": "missing_default_edges",
                },
            )
    validation = s._validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=active_agents_by_id)
    stored_canvas = (
        s._challenge_cup_canvas_storage_projection(canvas)
        if str(team.get("teamId") or "").strip()
        == s.CHALLENGE_CUP_RESEARCH_TEAM_ID
        else canvas
    )
    if raw != stored_canvas:
        s._write_json(canvas_path, stored_canvas)
    return {**canvas, "validation": validation}


def save_team_canvas(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent_refs = s._agent_reference_maps()
    team = s.get_team(team_id)
    canvas = s._normalize_canvas(
        payload,
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )
    validation = s._validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=agent_refs["active_by_id"])
    if not validation["valid"]:
        raise s.TeamServiceError(s._format_validation_error(validation))
    canvas["updatedAt"] = s.utc_now_iso()
    with s._TEAM_LOCK:
        state = s._load_index()
        stored = s._find_team(state, team["teamId"])
        stored_canvas = (
            s._challenge_cup_canvas_storage_projection(canvas)
            if str(team.get("teamId") or "").strip()
            == s.CHALLENGE_CUP_RESEARCH_TEAM_ID
            else canvas
        )
        s._write_json(s._team_canvas_path(team["teamId"]), stored_canvas)
        if stored is not None:
            stored["updatedAt"] = canvas["updatedAt"]
            stored["canvasPath"] = s._relative_path(s._team_canvas_path(team["teamId"]))
            s._ensure_team_chat_room_link(stored, agent_refs=agent_refs)
            state["updatedAt"] = canvas["updatedAt"]
            s._save_index(state)
    s._record_team_event(
        "team.canvas.updated",
        team,
        fields={"nodeCount": len(canvas["nodes"]), "edgeCount": len(canvas["edges"]), "valid": validation["valid"]},
    )
    return {**canvas, "validation": validation}


def _normalize_canvas(
    raw: dict[str, Any],
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    if not isinstance(raw, dict):
        raise s.TeamServiceError("Team canvas payload must be an object.")
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if not nodes:
        nodes = s._default_nodes_for_members(team.get("members") or [])
    nodes = _project_member_bindings_onto_nodes(nodes, team.get("members") or [])
    normalized_nodes = [
        s._normalize_node(
            item,
            index,
            agents_by_id=agents_by_id,
            active_agents_by_id=active_agents_by_id,
        )
        for index, item in enumerate(nodes[:120])
    ]
    node_ids = [node["id"] for node in normalized_nodes]
    if len(node_ids) != len(set(node_ids)):
        raise s.TeamServiceError("Team canvas node ids must be unique.")
    node_id_set = set(node_ids)
    try:
        normalized_edges = [s._normalize_edge_pure(item, index, node_id_set) for index, item in enumerate(edges[:240])]
    except s.TeamCanvasValidationError as exc:
        raise s.TeamServiceError(str(exc)) from exc
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "canvasKind": s.CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(raw.get("updatedAt") or team.get("updatedAt") or s.utc_now_iso()),
        "path": s._relative_path(s._team_canvas_path(team["teamId"])),
        "viewport": {
            "x": s._safe_float(viewport.get("x"), 0.0),
            "y": s._safe_float(viewport.get("y"), 0.0),
            "zoom": min(2.0, max(0.45, s._safe_float(viewport.get("zoom"), 1.0))),
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def _project_member_bindings_onto_nodes(
    nodes: list[Any],
    members: list[Any],
) -> list[Any]:
    """Project canonical Team membership onto editable canvas layout nodes."""

    member_rows = [item for item in members if isinstance(item, dict)]
    by_agent_id = {
        str(item.get("agentId") or "").strip(): item
        for item in member_rows
        if str(item.get("agentId") or "").strip()
    }
    role_candidates: dict[str, list[dict[str, Any]]] = {}
    for member in member_rows:
        role = str(member.get("role") or "").strip()
        if role:
            role_candidates.setdefault(role, []).append(member)
    by_role = {
        role: rows[0]
        for role, rows in role_candidates.items()
        if len(rows) == 1
    }
    projected: list[Any] = []
    for item in nodes:
        if not isinstance(item, dict):
            projected.append(item)
            continue
        row = dict(item)
        role = str(row.get("role") or "").strip()
        agent_id = str(row.get("agentId") or "").strip()
        member = by_role.get(role) or by_agent_id.get(agent_id)
        if member is None:
            row["agentId"] = ""
        else:
            row["agentId"] = str(member.get("agentId") or "").strip()
            row["role"] = str(member.get("role") or role).strip()
        projected.append(row)
    return projected


def _normalize_node(
    item: Any,
    index: int,
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    if not isinstance(item, dict):
        raise s.TeamServiceError("Team canvas node must be an object.")
    agent_id = s._safe_token(item.get("agentId"), default="", max_length=128)
    node_id = s._safe_token(item.get("id") or agent_id, default=f"node-{index + 1}", max_length=128)
    if agent_id and agents_by_id is not None:
        agent = agents_by_id.get(agent_id)
    else:
        agent = agent_directory_service.get_agent(agent_id, include_archived=True) if agent_id else None
    if agent_id and active_agents_by_id is not None:
        active_agent = active_agents_by_id.get(agent_id)
    else:
        active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
    node_type = s._safe_token(item.get("type"), default="role", max_length=40)
    status = "bound" if active_agent else "stale" if agent_id else "unbound"
    agent_source_ref = s._source_authority_ref("agent", agent_id) if agent_id else None
    agent_projection_edit = s._projection_edit_contract("agent", agent_id) if agent_id else None
    return {
        "id": node_id,
        "label": trim_lines(item.get("label") or (agent or {}).get("displayName") or f"角色 {index + 1}", max_lines=1).strip(),
        "type": node_type if node_type in s.NODE_TYPES else "role",
        "status": status,
        "x": s._safe_float(item.get("x"), 120.0 + index * 220.0),
        "y": s._safe_float(item.get("y"), 120.0),
        "agentId": agent_id,
        "agentCode": str((agent or {}).get("agentCode") or "").strip(),
        "agentName": str((agent or {}).get("displayName") or "").strip(),
        "agentSourceRef": agent_source_ref,
        "agentProjectionEdit": agent_projection_edit,
        "agentProjectionCanWrite": False,
        "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
        "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
        "responsibilities": [
            trim_lines(value, max_lines=2).strip()
            for value in list(item.get("responsibilities") or [])[:8]
            if str(value or "").strip()
        ],
    }


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    from core.agent_kernel.source_authority import source_ref

    return source_ref(kind, source_id, metadata)


def _projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    from core.agent_kernel.source_authority import projection_edit_contract

    return projection_edit_contract(kind, source_id, metadata)


def _validate_canvas(
    canvas: dict[str, Any],
    *,
    team_id: str = "",
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    issues: list[dict[str, Any]] = []
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    node_ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            issues.append(s._issue("error", "missing_node_id", "画布节点缺少 id。"))
            continue
        if node_id in node_ids:
            issues.append(s._issue("error", "duplicate_node_id", f"节点 id 重复：{node_id}", node_id=node_id))
        node_ids.add(node_id)
        agent_id = str(node.get("agentId") or "").strip()
        if agent_id and active_agents_by_id is not None:
            active_agent = active_agents_by_id.get(agent_id)
        else:
            active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
        if agent_id and not active_agent:
            issues.append(s._issue("warning", "stale_agent_ref", f"节点绑定的 Agent 不可用：{agent_id}", node_id=node_id))
        if agent_id:
            conflict = s._find_active_team_for_agent(agent_id, excluding_team_id=team_id)
            if conflict:
                issues.append(
                    s._issue(
                        "error",
                        "agent_team_conflict",
                        f"Agent 已属于团队 {conflict.get('name') or conflict.get('teamId')}，不能同时加入当前团队。",
                        node_id=node_id,
                    )
                )
    for edge in edges:
        edge_id = str(edge.get("id") or "").strip()
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            issues.append(s._issue("error", "missing_edge_endpoint", "组织关系线引用了不存在的节点。", edge_id=edge_id, source=source, target=target))
    errors = [item for item in issues if item.get("severity") == "error"]
    warnings = [item for item in issues if item.get("severity") == "warning"]
    return {
        "valid": not errors,
        "summary": {"errorCount": len(errors), "warningCount": len(warnings), "issueCount": len(issues)},
        "issues": issues,
    }


def _normalize_members(items: list[dict[str, Any]], *, require_active: bool) -> list[dict[str, Any]]:
    s = _service()
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=not require_active)
        if not agent:
            if require_active:
                raise s.TeamServiceError(f"Team member Agent is not active: {agent_id}")
            continue
        seen.add(agent_id)
        members.append(
            {
                "memberId": s._safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "responsibilities": [
                    trim_lines(value, max_lines=2).strip()
                    for value in list(item.get("responsibilities") or [])[:8]
                    if str(value or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _ensure_members_can_join_team(members: list[dict[str, Any]], state: dict[str, Any], team_id: str) -> None:
    s = _service()
    for member in members:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        conflict = s._find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            conflict_label = str(conflict.get("name") or conflict.get("teamId") or "").strip()
            s._record_team_membership_conflict(team_id, agent_id, conflict)
            raise s.TeamServiceError(f"Agent already belongs to Team {conflict_label}: {agent_id}")


def _members_without_cross_team_conflicts(
    members: list[dict[str, Any]],
    state: dict[str, Any],
    team_id: str,
    *,
    source: str,
) -> list[dict[str, Any]]:
    s = _service()
    available: list[dict[str, Any]] = []
    for member in members:
        agent_id = str(member.get("agentId") or "").strip()
        conflict = s._find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            s._record_system_team_membership_conflict(team_id, agent_id, conflict, source=source)
            continue
        available.append(member)
    return available


def _remove_agent_from_team_canvas(team: dict[str, Any], agent_id: str) -> None:
    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not team_id or not normalized_agent_id:
        return
    canvas_path = s._team_canvas_path(team_id)
    raw = s._read_json(canvas_path) if canvas_path.exists() else s._default_canvas_for_team(team)
    if not isinstance(raw, dict):
        raw = s._default_canvas_for_team(team)
    removed_node_ids = {
        str(node.get("id") or "").strip()
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() == normalized_agent_id
    }
    nodes = [
        dict(node)
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() != normalized_agent_id
    ]
    if not nodes:
        nodes = s._default_nodes_for_members(team.get("members") or [])
    edges = [
        dict(edge)
        for edge in list(raw.get("edges") or [])
        if isinstance(edge, dict)
        and str(edge.get("source") or "").strip() not in removed_node_ids
        and str(edge.get("target") or "").strip() not in removed_node_ids
    ]
    canvas = {
        **raw,
        "schemaVersion": s.SCHEMA_VERSION,
        "canvasKind": s.CANVAS_KIND,
        "teamId": team_id,
        "updatedAt": str(team.get("updatedAt") or s.utc_now_iso()),
        "path": s._relative_path(canvas_path),
        "nodes": nodes,
        "edges": edges,
    }
    s._write_json(canvas_path, canvas)


def _default_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    nodes = s._default_nodes_for_members(team.get("members") or [])
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "canvasKind": s.CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(team.get("updatedAt") or s.utc_now_iso()),
        "path": s._relative_path(s._team_canvas_path(team["teamId"])),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": s._default_edges_for_team(team, nodes),
    }


def _challenge_cup_canvas_storage_projection(
    canvas: dict[str, Any],
) -> dict[str, Any]:
    """Persist Challenge Cup canvas layout plus role→agentId references only."""

    nodes: list[dict[str, Any]] = []
    for item in list(canvas.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        nodes.append(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "agentCode",
                    "agentName",
                    "agentSourceRef",
                    "agentProjectionEdit",
                    "agentProjectionCanWrite",
                }
            }
        )
    return {
        key: value
        for key, value in canvas.items()
        if key not in {"nodes", "validation"}
    } | {"nodes": nodes}


def _ai_search_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    members_by_role = {
        str(member.get("role") or "").strip(): member
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("role") or "").strip()
    }
    positions = {
        "ai_search_scope_lead": (120, 210),
        "global_primary_sources": (420, 80),
        "cn_primary_sources": (420, 340),
        "signal_quality_gate": (720, 210),
    }
    nodes: list[dict[str, Any]] = []
    for index, role in enumerate(s.AI_SEARCH_SYSTEM_ROLES, start=1):
        role_key = str(role.get("role") or "").strip()
        member = members_by_role.get(role_key) or {}
        x, y = positions.get(role_key, (120 + index * 220, 210))
        nodes.append(
            {
                "id": f"ai-search-{index}",
                "label": str(member.get("agentName") or role.get("label") or role_key).strip(),
                "type": "agent" if str(member.get("agentId") or "").strip() else "role",
                "status": str(member.get("agentStatus") or ("bound" if member.get("agentId") else "unbound")).strip(),
                "x": x,
                "y": y,
                "agentId": str(member.get("agentId") or "").strip(),
                "agentCode": str(member.get("agentCode") or "").strip(),
                "agentName": str(member.get("agentName") or "").strip(),
                "role": role_key,
                "purpose": str(role.get("label") or "").strip(),
                "responsibilities": list(role.get("responsibilities") or []),
            }
        )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "canvasKind": s.CANVAS_KIND,
        "teamId": s.AI_SEARCH_TEAM_ID,
        "updatedAt": str(team.get("updatedAt") or s.utc_now_iso()),
        "path": s._relative_path(s._team_canvas_path(s.AI_SEARCH_TEAM_ID)),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": s._ai_search_canvas_edges(),
    }


def _ai_search_canvas_edges() -> list[dict[str, Any]]:
    s = _service()
    return [
        {"id": "ai-search-scope-global", "source": "ai-search-1", "target": "ai-search-2", "type": "communication", "label": "全球源边界"},
        {"id": "ai-search-scope-cn", "source": "ai-search-1", "target": "ai-search-3", "type": "communication", "label": "中国源边界"},
        {"id": "ai-search-global-quality", "source": "ai-search-2", "target": "ai-search-4", "type": "supports", "label": "一手源回链"},
        {"id": "ai-search-cn-quality", "source": "ai-search-3", "target": "ai-search-4", "type": "supports", "label": "一手源回链"},
        {"id": "ai-search-quality-scope", "source": "ai-search-4", "target": "ai-search-1", "type": "supports", "label": "启用规则回写"},
    ]


def _ai_search_canvas_needs_sync(canvas_path: Path, team: dict[str, Any]) -> bool:
    s = _service()
    if not canvas_path.exists():
        return True
    try:
        canvas = s._read_json(canvas_path)
    except Exception:
        return True
    expected_roles = {str(role.get("role") or "").strip() for role in s.AI_SEARCH_SYSTEM_ROLES}
    node_roles = {
        str(node.get("role") or "").strip()
        for node in list(canvas.get("nodes") or [])
        if isinstance(node, dict)
    }
    expected_agent_ids_by_role = {
        str(member.get("role") or "").strip(): str(member.get("agentId") or "").strip()
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("role") or "").strip()
    }
    canvas_agent_ids_by_role = {
        str(node.get("role") or "").strip(): str(node.get("agentId") or "").strip()
        for node in list(canvas.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("role") or "").strip()
    }
    expected_edges = {str(edge.get("id") or "").strip() for edge in s._ai_search_canvas_edges()}
    edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in list(canvas.get("edges") or [])
        if isinstance(edge, dict)
    }
    agents_match = all(
        not expected_agent_id or canvas_agent_ids_by_role.get(role_key) == expected_agent_id
        for role_key, expected_agent_id in expected_agent_ids_by_role.items()
    )
    return not expected_roles.issubset(node_roles) or not expected_edges.issubset(edge_ids) or not agents_match


def _default_nodes_for_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    nodes: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        nodes.append(
            {
                "id": f"node-{index + 1}",
                "label": str(member.get("agentName") or agent_id),
                "type": "agent",
                "status": str(member.get("agentStatus") or "active"),
                "x": 120 + index * 220,
                "y": 120,
                "agentId": agent_id,
                "agentCode": str(member.get("agentCode") or ""),
                "agentName": str(member.get("agentName") or ""),
                "role": str(member.get("role") or ""),
                "purpose": str(member.get("purpose") or ""),
            }
        )
    if nodes:
        return nodes
    return [
        {
            "id": "team-lead",
            "label": "团队负责人",
            "type": "role",
            "status": "unbound",
            "x": 220,
            "y": 120,
            "agentId": "",
            "agentCode": "",
            "agentName": "",
            "role": "lead",
            "purpose": "",
        }
    ]


def _default_edges_for_team(team: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    nodes_by_role: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = str(node.get("role") or "").strip()
        if role and role not in nodes_by_role:
            nodes_by_role[role] = node
    if s._infer_team_kind(team) == "self_evolution":
        return s._edges_from_role_chain(
            nodes_by_role,
            [
                ("executor", "reviewer", "执行交付评审"),
                ("reviewer", "observer", "旁路观察记录"),
            ],
        )
    if s._infer_team_kind(team) == "supervised_evolution":
        return s._edges_from_role_chain(
            nodes_by_role,
            [
                ("baseline", "reviewer", "基线方案评审"),
                ("candidate", "reviewer", "候选方案评审"),
                ("reviewer", "auditor", "评审进入审计"),
                ("auditor", "judge", "审计进入裁决"),
            ],
        )
    if s._infer_team_kind(team) == "ai_search":
        return s._edges_from_role_chain(
            nodes_by_role,
            [
                ("ai_search_scope_lead", "global_primary_sources", "全球源边界"),
                ("ai_search_scope_lead", "cn_primary_sources", "中国源边界"),
                ("global_primary_sources", "signal_quality_gate", "一手源回链"),
                ("cn_primary_sources", "signal_quality_gate", "一手源回链"),
                ("signal_quality_gate", "ai_search_scope_lead", "启用规则回写"),
            ],
        )
    if s._infer_team_kind(team) == "research":
        return s._edges_from_role_links(
            nodes_by_role,
            [
                ("challenge_cup_search", "challenge_cup_extractor", "交接可追溯资料", "reports_to"),
                (
                    "challenge_cup_extractor",
                    "challenge_cup_knowledge_manager",
                    "交接证据与限制",
                    "reports_to",
                ),
                (
                    "challenge_cup_knowledge_manager",
                    "challenge_cup_experiment_revision",
                    "提供证据关系与缺口",
                    "reports_to",
                ),
                (
                    "challenge_cup_experiment_revision",
                    "challenge_cup_execution_steward",
                    "提交冻结协议",
                    "reports_to",
                ),
                (
                    "challenge_cup_execution_steward",
                    "challenge_cup_evaluator",
                    "交付不可变运行工件",
                    "reports_to",
                ),
                (
                    "challenge_cup_evaluator",
                    "challenge_cup_experiment_revision",
                    "反馈评估与主张边界",
                    "communication",
                ),
                (
                    "challenge_cup_knowledge_manager",
                    "challenge_cup_search",
                    "反馈知识缺口",
                    "communication",
                ),
            ],
        )
    return []


def _edges_from_role_chain(
    nodes_by_role: dict[str, dict[str, Any]],
    links: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    s = _service()
    edges: list[dict[str, Any]] = []
    for index, (source_role, target_role, label) in enumerate(links, start=1):
        source = nodes_by_role.get(source_role)
        target = nodes_by_role.get(target_role)
        if not source or not target:
            continue
        source_id = str(source.get("id") or "").strip()
        target_id = str(target.get("id") or "").strip()
        if not source_id or not target_id:
            continue
        edges.append(
            {
                "id": s._safe_token(f"{source_role}-{target_role}", default=f"edge-{index}", max_length=96),
                "source": source_id,
                "target": target_id,
                "label": label,
                "type": "communication",
            }
        )
    return edges


def _edges_from_role_links(
    nodes_by_role: dict[str, dict[str, Any]],
    links: list[tuple[str, str, str, str]],
) -> list[dict[str, Any]]:
    s = _service()
    edges: list[dict[str, Any]] = []
    for index, (source_role, target_role, label, edge_type) in enumerate(links, start=1):
        source = nodes_by_role.get(source_role)
        target = nodes_by_role.get(target_role)
        if not source or not target:
            continue
        source_id = str(source.get("id") or "").strip()
        target_id = str(target.get("id") or "").strip()
        if not source_id or not target_id:
            continue
        normalized_type = str(edge_type or "communication").strip()
        if normalized_type not in s.EDGE_TYPES:
            normalized_type = "communication"
        edges.append(
            {
                "id": s._safe_token(f"{normalized_type}-{source_role}-{target_role}", default=f"edge-{index}", max_length=96),
                "source": source_id,
                "target": target_id,
                "label": label,
                "type": normalized_type,
            }
        )
    return edges


def _default_canvas_edges_missing_for_team(team: dict[str, Any], canvas_path: Path) -> bool:
    s = _service()
    if s._infer_team_kind(team) not in {"self_evolution", "supervised_evolution", "ai_search", "research"}:
        return False
    if not canvas_path.exists():
        return True
    try:
        canvas = s._read_json(canvas_path)
    except Exception:
        return True
    return not list(canvas.get("edges") or [])


def _canvas_summary_for_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    s = _service()
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return {"path": "", "nodeCount": 0, "edgeCount": 0, "validation": s._validate_canvas({"nodes": [], "edges": []}, team_id=team_id)}
    canvas_path = s._team_canvas_path(team_id)
    raw = s._read_json(canvas_path) if canvas_path.exists() else {}
    agent_refs = agent_refs or s._agent_reference_maps()
    try:
        canvas = s._normalize_canvas(
            raw or s._default_canvas_for_team(team),
            team,
            agents_by_id=agent_refs["by_id"],
            active_agents_by_id=agent_refs["active_by_id"],
        )
        validation = s._validate_canvas(canvas, team_id=team_id, active_agents_by_id=agent_refs["active_by_id"])
    except s.TeamServiceError as exc:
        canvas = {"nodes": [], "edges": []}
        validation = {
            "valid": False,
            "summary": {"errorCount": 1, "warningCount": 0, "issueCount": 1},
            "issues": [s._issue("error", "invalid_canvas", str(exc))],
        }
    return {
        "path": str(team.get("canvasPath") or s._relative_path(canvas_path)),
        "nodeCount": len(canvas.get("nodes") or []),
        "edgeCount": len(canvas.get("edges") or []),
        "validation": validation,
    }


def _canvas_path_summary(team: dict[str, Any], *, team_id: str = "") -> dict[str, Any]:
    s = _service()
    normalized_team_id = str(team_id or team.get("teamId") or "").strip()
    canvas_path = s._team_canvas_path(normalized_team_id) if normalized_team_id else Path("")
    return {
        "path": str(team.get("canvasPath") or (s._relative_path(canvas_path) if normalized_team_id else "")),
        "nodeCount": 0,
        "edgeCount": 0,
        "validation": {"valid": True, "summary": {"errorCount": 0, "warningCount": 0, "issueCount": 0}, "issues": []},
    }
