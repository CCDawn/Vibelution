"""Research organization team sync helpers.

Claim scope: sync locked research-organization agents into the research Team,
role metadata alignment, and organization canvas projection.
Late-binds ``team_service`` for index locks, contracts, and chat-room link.
"""

from __future__ import annotations

import re
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.web.services import agent_directory_service


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def ensure_research_team_from_organization(organization: dict[str, Any]) -> dict[str, Any]:
    """Ensure the locked research organization has a stable Team reference."""

    s = _service()
    team_id = "research-team"
    now = s.utc_now_iso()
    members = s._members_from_research_organization(organization)
    if s._sync_research_team_member_agent_roles(members):
        agent_directory_service.repair_agent_directory()
    with s._TEAM_LOCK:
        state = s._load_index()
        if s._repair_index_state(state):
            state["updatedAt"] = now
        s._ensure_members_can_join_team(members, state, team_id)
        team = s._find_team(state, team_id)
        created = team is None
        if team is None:
            team = {
                "teamId": team_id,
                "name": s.RESEARCH_TEAM_DISPLAY_NAME,
                "description": "由科研组织架构自动同步的系统团队。",
                "purpose": "实时展示科研团队成员、职能与组织通信关系。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": s._relative_path(s._team_canvas_path(team_id)),
                "createdAt": now,
                "updatedAt": now,
            }
            s._apply_team_contract(team, team_kind="research", team_source="research_organization")
            state.setdefault("teams", []).append(team)
        else:
            team["name"] = s.RESEARCH_TEAM_DISPLAY_NAME
            team["description"] = "由科研组织架构自动同步的系统团队。"
            team["purpose"] = "实时展示科研团队成员、职能与组织通信关系。"
            team["status"] = s.DEFAULT_TEAM_STATUS
            team["members"] = members
            team["canvasPath"] = s._relative_path(s._team_canvas_path(team_id))
            team["updatedAt"] = now
            s._apply_team_contract(team, team_kind="research", team_source="research_organization")
        state["updatedAt"] = str(team.get("updatedAt") or now)
        s._save_index(state)
        canvas = s._canvas_from_research_organization(organization, team)
        s._write_json(s._team_canvas_path(team_id), canvas)
        s._ensure_team_chat_room_link(team)
        state["updatedAt"] = str(team.get("updatedAt") or now)
        s._save_index(state)
    s._record_team_event(
        "team.research_organization_synced",
        team,
        fields={
            "created": created,
            "memberCount": len(members),
            "nodeCount": len(canvas.get("nodes") or []),
            "edgeCount": len(canvas.get("edges") or []),
            "source": "research_organization",
        },
    )
    return s.get_team(team_id)


def _members_from_research_organization(organization: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen or str(item.get("status") or "active").strip() == "archived":
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            continue
        seen.add(agent_id)
        function_label = s._research_member_function_label(item, agent)
        responsibilities = s._research_member_responsibilities(item, agent)
        members.append(
            {
                "memberId": s._safe_token(item.get("nodeId") or agent_id, default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or item.get("displayName") or "").strip(),
                "role": str(item.get("role") or ((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("researchOrgRole") or "").strip(),
                "purpose": function_label,
                "responsibilities": responsibilities,
                "agentStatus": "active",
            }
        )
    return members


def _sync_research_team_member_agent_roles(members: list[dict[str, Any]]) -> bool:
    s = _service()
    changed = False
    for member in members:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        role = s._safe_token(member.get("role"), default="", max_length=96)
        role_key = s.RESEARCH_TEAM_MEMBER_ROLE_KEYS.get(role)
        if not agent_id or not role_key:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        expected_metadata = {
            "agentMode": "research",
            "configSurface": "team",
            "researchTeamRole": role,
            "researchTeamRoleKey": role_key,
        }
        current_policy = agent_directory_service.resolve_tool_policy_for_agent(agent_id)
        if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
            expected_policy = agent_directory_service._knowledge_steward_tool_policy()
        elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_KEYS:
            expected_policy = agent_directory_service.default_research_source_tool_policy(
                str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
                role_key=role_key,
            )
        else:
            expected_policy = agent_directory_service.default_research_role_tool_policy(
                str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
                role_key=role_key,
            )
        needs_update = (
            str(agent.get("primaryMode") or "").strip() != "research"
            or str(agent.get("roleKey") or "").strip() != role_key
            or any(metadata.get(key) != value for key, value in expected_metadata.items())
            or list(current_policy.get("allowedTools") or []) != list(expected_policy.get("allowedTools") or [])
            or current_policy.get("mutationAccess") != expected_policy.get("mutationAccess")
            or list(current_policy.get("writeScopes") or []) != list(expected_policy.get("writeScopes") or [])
        )
        if not needs_update:
            continue
        agent_directory_service.update_agent_instance(
            agent_id,
            primary_mode="research",
            role_key=role_key,
            tool_policy=expected_policy,
            metadata=expected_metadata,
            status="active",
        )
        changed = True
    return changed


def _canvas_from_research_organization(organization: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    members_by_agent_id = {
        str(member.get("agentId") or "").strip(): member
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        member = members_by_agent_id.get(agent_id)
        if not member:
            continue
        nodes.append(
            {
                "id": s._safe_token(agent_id, default=f"node-{index + 1}", max_length=96),
                "label": str(item.get("displayName") or member.get("agentName") or agent_id).strip(),
                "type": "agent",
                "status": "bound",
                "x": s._safe_float(item.get("x"), 120.0 + index * 220.0),
                "y": s._safe_float(item.get("y"), 120.0),
                "agentId": agent_id,
                "agentCode": str(item.get("agentCode") or member.get("agentCode") or "").strip(),
                "agentName": str(member.get("agentName") or item.get("displayName") or "").strip(),
                "role": str(member.get("role") or "").strip(),
                "purpose": str(member.get("purpose") or "").strip(),
                "responsibilities": list(member.get("responsibilities") or [])[:8],
            }
        )
    node_ids = {str(node.get("id") or "") for node in nodes}
    edges: list[dict[str, Any]] = s._organization_reporting_edges(organization, nodes)
    for index, item in enumerate(list(organization.get("edges") or [])[:240]):
        if not isinstance(item, dict) or str(item.get("status") or "active").strip() == "archived":
            continue
        source = s._safe_token(item.get("fromAgentId") or item.get("source"), default="", max_length=96)
        target = s._safe_token(item.get("toAgentId") or item.get("target"), default="", max_length=96)
        if source not in node_ids or target not in node_ids:
            continue
        edges.append(
            {
                "id": s._safe_token(item.get("edgeId") or item.get("id"), default=f"edge-{index + 1}", max_length=96),
                "source": source,
                "target": target,
                "label": trim_lines(item.get("label") or "组织通信", max_lines=1).strip(),
                "type": "communication",
            }
        )
    return s._normalize_canvas(
        {
            "schemaVersion": s.SCHEMA_VERSION,
            "canvasKind": s.CANVAS_KIND,
            "teamId": team["teamId"],
            "updatedAt": str(organization.get("updatedAt") or team.get("updatedAt") or s.utc_now_iso()),
            "path": s._relative_path(s._team_canvas_path(team["teamId"])),
            "viewport": {"x": 40, "y": 80, "zoom": 1},
            "nodes": nodes,
            "edges": edges,
        },
        team,
    )


def _organization_reporting_edges(organization: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    node_ids = {str(node.get("id") or "").strip() for node in nodes if str(node.get("id") or "").strip()}
    if len(node_ids) < 2:
        return []
    source_items = [
        item for item in list(organization.get("agents") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip() != "archived"
        and str(item.get("agentId") or "").strip() in node_ids
    ]
    nodes_by_agent_id = {str(node.get("agentId") or "").strip(): node for node in nodes}
    items_by_agent_id = {str(item.get("agentId") or "").strip(): item for item in source_items}
    role_index: dict[str, str] = {}
    label_index: dict[str, str] = {}
    for item in source_items:
        agent_id = str(item.get("agentId") or "").strip()
        role = s._research_org_role(item)
        if role and role not in role_index:
            role_index[role] = agent_id
        for value in (
            item.get("agentCode"),
            item.get("displayName"),
            item.get("role"),
            s._research_member_function_label(item, item.get("agent") if isinstance(item.get("agent"), dict) else {}),
        ):
            normalized = s._normalize_report_to_reference(value)
            if normalized and normalized not in label_index:
                label_index[normalized] = agent_id
    ceo_agent_id = role_index.get("ceo") or role_index.get("research_ceo") or label_index.get("ceo")
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in source_items:
        target_agent_id = str(item.get("agentId") or "").strip()
        if not target_agent_id:
            continue
        role = s._research_org_role(item)
        if role in {"ceo", "research_ceo"}:
            continue
        source_agent_id = s._resolve_report_to_agent_id(item, role_index=role_index, label_index=label_index, fallback_agent_id=ceo_agent_id or "")
        if not source_agent_id or source_agent_id == target_agent_id or source_agent_id not in node_ids:
            continue
        pair = (source_agent_id, target_agent_id)
        if pair in seen:
            continue
        seen.add(pair)
        source_node = nodes_by_agent_id.get(source_agent_id) or {}
        target_node = nodes_by_agent_id.get(target_agent_id) or {}
        edges.append(
            {
                "id": s._safe_token(f"reports-{source_agent_id}-{target_agent_id}", default=f"reports-{len(edges) + 1}", max_length=96),
                "source": source_agent_id,
                "target": target_agent_id,
                "label": trim_lines(
                    f"{source_node.get('label') or source_agent_id} 管理 {target_node.get('label') or target_agent_id}",
                    max_lines=1,
                ).strip(),
                "type": "reports_to",
            }
        )
    return edges


def _resolve_report_to_agent_id(
    item: dict[str, Any],
    *,
    role_index: dict[str, str],
    label_index: dict[str, str],
    fallback_agent_id: str,
) -> str:
    s = _service()
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role_contract = metadata.get("roleContract") if isinstance(metadata.get("roleContract"), dict) else {}
    candidates = [
        item.get("reportToAgentId"),
        item.get("reportsToAgentId"),
        role_contract.get("reportToAgentId"),
        role_contract.get("reportsToAgentId"),
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    report_to = s._normalize_report_to_reference(item.get("reportTo") or role_contract.get("reportTo") or "CEO")
    if report_to in role_index:
        return role_index[report_to]
    if report_to in label_index:
        return label_index[report_to]
    aliases = {
        "chiefexecutiveofficer": "ceo",
        "ceoagent": "ceo",
        "organizationadvisor": "organization_advisor",
        "organizationadvisoragent": "organization_advisor",
        "capabilitysteward": "capability_steward",
        "capabilitystewardagent": "capability_steward",
    }
    alias = aliases.get(report_to)
    if alias and alias in role_index:
        return role_index[alias]
    return fallback_agent_id


def _research_org_role(item: dict[str, Any]) -> str:
    s = _service()
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return str(item.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole") or "").strip()


def _normalize_report_to_reference(value: Any) -> str:
    s = _service()
    normalized = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "", str(value or "").strip().lower())
    return normalized


def _research_member_function_label(item: dict[str, Any], agent: dict[str, Any]) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    label = str(metadata.get("functionalDisplayName") or "").strip()
    if label:
        return trim_lines(label, max_lines=1).strip()
    responsibilities = metadata.get("responsibilities")
    if isinstance(responsibilities, list):
        joined = "；".join(str(value).strip() for value in responsibilities[:2] if str(value).strip())
        if joined:
            return trim_lines(joined, max_lines=1).strip()
    return trim_lines(item.get("role") or "科研协作", max_lines=1).strip()


def _research_member_responsibilities(item: dict[str, Any], agent: dict[str, Any]) -> list[str]:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    embedded_agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    embedded_metadata = embedded_agent.get("metadata") if isinstance(embedded_agent.get("metadata"), dict) else {}
    sources = [
        item.get("responsibilities"),
        (item.get("teamMembership") if isinstance(item.get("teamMembership"), dict) else {}).get("responsibilities"),
        embedded_metadata.get("responsibilities"),
        (embedded_metadata.get("teamMembership") if isinstance(embedded_metadata.get("teamMembership"), dict) else {}).get("responsibilities"),
        (embedded_metadata.get("taskProfile") if isinstance(embedded_metadata.get("taskProfile"), dict) else {}).get("responsibilities"),
        metadata.get("responsibilities"),
        (metadata.get("teamMembership") if isinstance(metadata.get("teamMembership"), dict) else {}).get("responsibilities"),
        (metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {}).get("responsibilities"),
        (agent.get("taskProfile") if isinstance(agent.get("taskProfile"), dict) else {}).get("responsibilities"),
    ]
    responsibilities: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for value in s._responsibility_values(source):
            normalized = trim_lines(value, max_lines=2).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            responsibilities.append(normalized)
            if len(responsibilities) >= 8:
                return responsibilities
    return responsibilities


def _responsibility_values(value: Any) -> list[str]:
    s = _service()
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[；;\n]+", value) if item.strip()]
    return []
