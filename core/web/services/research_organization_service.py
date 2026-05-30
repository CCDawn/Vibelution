"""Research organization graph and communication bus."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.infrastructure.workspace_manager import get_workspace

from . import agent_mode_binding_service, session_service
from .agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    archive_agent_instance,
    evaluate_supervision_policy,
    get_agent,
    list_agent_inbox_messages_for_agent,
    list_agents,
    record_supervision_policy_decision,
    resolve_memory_policy_for_agent,
    resolve_tool_policy_for_agent,
    resolve_supervision_policy_for_agent,
    update_agent_instance,
    write_agent_inbox_message,
)
from .runtime_scene_service import record_research_scene_event


ORG_SCHEMA_VERSION = 1
MAX_ORG_MESSAGES = 200
MAX_AUDIT_EVENTS = 500
MESSAGE_TYPES = {"notice", "request", "task", "report", "escalation", "decision"}
DELIVERY_MODES = {"private", "broadcast", "zone"}
PROTECTED_SYSTEM_ROLES = {"ceo", "organization_advisor", "capability_steward"}
HIGH_RISK_ACTIONS = {"create_agent", "archive_agent", "update_tool_policy", "expand_tool_permissions"}
CEO_AGENT_TOOLS = ["agent_message_tool", "web_search_tool", "web_fetch_tool"]
ORGANIZATION_ADVISOR_TOOLS = ["agent_message_tool", "web_search_tool", "web_fetch_tool"]
CAPABILITY_STEWARD_TOOLS = [
    "agent_message_tool",
    "web_search_tool",
    "web_fetch_tool",
    "read_memory_tool",
    "get_memory_summary_tool",
    "search_memory_tool",
    "read_dynamic_prompt_tool",
    "research_knowledge_query_tool",
]
DEFAULT_CREATED_AGENT_TOOLS = ["agent_message_tool", "web_search_tool", "web_fetch_tool"]
ROLE_GOVERNANCE_BOUNDARIES = {
    "ceo": {
        "authority": "decides research priorities, delegates work, and may approve organization recommendations",
        "must_not": "must not apply high-risk organization changes without the user gate",
        "proposal_actions": ["approve_recommendation", "request_create_agent", "request_permission_change", "request_edge_change"],
    },
    "organization_advisor": {
        "authority": "designs organization structure, role boundaries, communication edges, and staffing changes",
        "must_not": "must not directly apply new Agent creation, archives, or permission expansion",
        "proposal_actions": ["propose_create_agent", "propose_archive_agent", "propose_permission_change", "propose_edge_change"],
    },
    "capability_steward": {
        "authority": "audits prompt, tool, and memory policy boundaries for each Agent",
        "must_not": "must not grant high-risk tools or rewrite core roles without CEO/user approval",
        "proposal_actions": ["propose_prompt_policy", "propose_tool_policy", "propose_memory_policy", "report_capability_gap"],
    },
    "research_specialist": {
        "authority": "executes the specific research or engineering responsibility assigned in its role contract",
        "must_not": "must not expand its own team membership, tools, memory writes, or communication edges",
        "proposal_actions": ["report_gap", "request_help", "request_permission_review"],
    },
}
RANK_WEIGHTS = {
    "ceo": 100,
    "advisor": 80,
    "director": 70,
    "lead": 60,
    "senior": 50,
    "specialist": 40,
    "member": 30,
    "intern": 10,
}


class ResearchOrganizationError(ValueError):
    """Raised when a research organization request is invalid."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_research_organization() -> dict[str, Any]:
    """Return the current organization graph, ensuring the protected core exists."""

    graph = _read_organization()
    graph = _ensure_default_organization(graph)
    _write_organization(graph)
    return _organization_to_api(graph)


def get_research_organization_canvas_graph() -> dict[str, Any]:
    """Return a lightweight organization graph for read-only canvas rendering."""

    workspace = get_workspace()
    reader = getattr(workspace, "read_research_organization", None)
    raw = reader() if callable(reader) else (
        json.loads(_organization_path(workspace).read_text(encoding="utf-8"))
        if _organization_path(workspace).exists()
        else {}
    )
    graph = _normalize_organization(raw if isinstance(raw, dict) else {})
    if not graph.get("agents"):
        graph = _ensure_default_organization(graph)
        _write_organization(graph)
    canvas = _organization_to_canvas_api(graph)
    if not canvas.get("agents"):
        graph = _prune_unresolvable_active_nodes(graph)
        graph = _ensure_default_organization(graph)
        _write_organization(graph)
        canvas = _organization_to_canvas_api(graph)
    return canvas


def build_research_organization_context_block(agent_id: str, *, limit: int = 6) -> str:
    """Return a compact read-only org view for Agents that belong to the research org graph."""

    organization = get_research_organization()
    normalized_agent_id = _clean_id(agent_id)
    agents = [
        item for item in list(organization.get("agents") or [])
        if isinstance(item, dict) and _clean_id(item.get("agentId"))
    ]
    if not any(_clean_id(item.get("agentId")) == normalized_agent_id for item in agents):
        return ""
    active_agents = [
        item for item in agents
        if str(item.get("status") or "active").strip() != "archived"
    ]
    edges = [
        item for item in list(organization.get("edges") or [])
        if isinstance(item, dict) and str(item.get("status") or "active").strip() == "active"
    ]
    outbound_edges = [
        edge for edge in edges
        if _clean_id(edge.get("fromAgentId")) == normalized_agent_id
    ]
    inbound_edges = [
        edge for edge in edges
        if _clean_id(edge.get("toAgentId")) == normalized_agent_id
    ]
    connected_agent_ids = {normalized_agent_id}
    for edge in [*outbound_edges, *inbound_edges]:
        connected_agent_ids.add(_clean_id(edge.get("fromAgentId")))
        connected_agent_ids.add(_clean_id(edge.get("toAgentId")))
    if len(connected_agent_ids) > 1:
        active_agents = [
            item for item in active_agents
            if _clean_id(item.get("agentId")) in connected_agent_ids
        ]
    agents_by_id = {_clean_id(item.get("agentId")): item for item in active_agents}
    bounded_limit = max(1, int(limit or 1)) + 8
    lines = [
        "## Research Organization Context",
        "This is a read-only snapshot of your current research organization membership and communication graph.",
        "Use AgentId or AgentCode with agent_message_tool when contacting an Agent. Communication still follows edge policy, supervision policy, and wake rules.",
        "Organization Governance Protocol:",
        "- CEO decides priorities and may approve recommendations; high-risk changes still require the user gate before application.",
        "- Organization Advisor can propose new Agents, archives, permission changes, and communication edges, but does not directly apply them.",
        "- Capability Steward manages prompt/tool/memory policy recommendations and audits least-privilege boundaries; it does not grant hidden tools by itself.",
        "- Created specialist Agents must follow their role contract and request changes through CEO/Advisor/Capability Steward instead of self-expanding.",
        "Members:",
    ]
    for member in active_agents[:bounded_limit]:
        lines.extend(_format_research_org_context_member_lines(member, self_agent_id=normalized_agent_id))
    lines.extend(_format_organization_capability_roster(active_agents[:bounded_limit], self_agent_id=normalized_agent_id))
    lines.extend(_format_team_onboarding_context(agents_by_id.get(normalized_agent_id, {})))
    if outbound_edges:
        lines.append("Directly reachable from you:")
        for edge in outbound_edges[:bounded_limit]:
            target = agents_by_id.get(_clean_id(edge.get("toAgentId")), {})
            lines.append(_format_research_org_context_edge_line(edge, target=target, direction="to"))
    else:
        lines.append("Directly reachable from you: none declared")
    if inbound_edges:
        lines.append("Agents that can contact you:")
        for edge in inbound_edges[:bounded_limit]:
            source = agents_by_id.get(_clean_id(edge.get("fromAgentId")), {})
            lines.append(_format_research_org_context_edge_line(edge, target=source, direction="from"))
    return "\n".join(line for line in lines if str(line or "").strip()).strip()


def save_research_organization(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a caller-provided organization graph after normalization."""

    graph = _normalize_organization(payload)
    graph = _ensure_default_organization(graph)
    graph["updatedAt"] = utc_now_iso()
    _write_organization(graph)
    _record_org_event(
        "research.organization.updated",
        outcome="saved",
        fields={
            "agentCount": len(graph.get("agents") or []),
            "edgeCount": len(graph.get("edges") or []),
        },
    )
    return _organization_to_api(graph)


def send_research_org_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Deliver a user/Agent message through the research organization policy layer."""

    graph = _ensure_default_organization(_read_organization())
    source_agent_id = _clean_id(payload.get("sourceAgentId"))
    source_type = str(payload.get("sourceType") or "").strip().lower()
    if not source_type:
        source_type = "agent" if source_agent_id else "user"
    if source_type not in {"user", "agent"}:
        raise ResearchOrganizationError("Unsupported research organization message source.")
    human_override = bool(payload.get("humanOverride", source_type == "user"))
    message_type = _normalize_message_type(payload.get("messageType"))
    delivery_mode = _normalize_delivery_mode(payload.get("deliveryMode"))
    content = trim_lines(str(payload.get("content") or ""), max_lines=30).strip()
    if not content:
        raise ResearchOrganizationError("Research organization message content is required.")
    intent = trim_lines(str(payload.get("intent") or ""), max_lines=1).strip()
    recipients = _resolve_message_recipients(graph, payload, delivery_mode, source_agent_id)
    if not recipients:
        raise ResearchOrganizationError("Research organization message target is required.")

    now = utc_now_iso()
    message_id = _new_org_id("romsg")
    message_record = {
        "messageId": message_id,
        "sourceType": source_type,
        "sourceAgentId": source_agent_id,
        "sourceAgentCode": _agent_field(source_agent_id, "agentCode"),
        "sourceAgentName": _agent_field(source_agent_id, "displayName"),
        "targetAgentIds": recipients,
        "deliveryMode": delivery_mode,
        "zoneId": _clean_id(payload.get("zoneId")),
        "messageType": message_type,
        "intent": intent,
        "content": content,
        "summary": trim_lines(str(payload.get("summary") or content), max_lines=4),
        "threadId": _clean_id(payload.get("threadId")) or message_id,
        "humanOverride": human_override,
        "wakeTarget": bool(payload.get("wakeTarget", source_type == "user")),
        "createdBy": str(payload.get("createdBy") or source_type).strip() or source_type,
        "createdAt": now,
        "deliveries": [],
    }

    for target_agent_id in recipients:
        delivery = _deliver_message_to_agent(
            graph,
            message_record,
            target_agent_id,
            payload=payload,
        )
        message_record["deliveries"].append(delivery)
        graph = _append_audit_event(graph, _audit_from_delivery(message_record, delivery))
        _record_org_event(
            "research.organization.message_delivered" if delivery.get("allowed") else "research.organization.message_blocked",
            outcome="allowed" if delivery.get("allowed") else "blocked",
            level="info" if delivery.get("allowed") else "warning",
            fields={
                "messageId": message_id,
                "messageType": message_type,
                "sourceType": source_type,
                "sourceAgentId": source_agent_id,
                "targetAgentId": target_agent_id,
                "deliveryMode": delivery_mode,
                "allowed": bool(delivery.get("allowed")),
                "reason": str(delivery.get("reason") or ""),
                "edgeId": str(delivery.get("edgeId") or ""),
                "wakeStatus": str(delivery.get("wakeStatus") or ""),
            },
        )

    graph["messages"] = _limit_tail([*(graph.get("messages") or []), message_record], MAX_ORG_MESSAGES)
    graph["updatedAt"] = utc_now_iso()
    _write_organization(graph)
    return {
        "organization": _organization_to_api(graph),
        "message": message_record,
    }


def create_research_org_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    """Create an organization-change proposal."""

    graph = _ensure_default_organization(_read_organization())
    actions = _normalize_proposal_actions(payload)
    if not actions:
        raise ResearchOrganizationError("Research organization proposal requires at least one action.")
    risk_level = _proposal_risk_level(payload, actions)
    now = utc_now_iso()
    proposal = {
        "proposalId": _new_org_id("roprop"),
        "title": trim_lines(str(payload.get("title") or _default_proposal_title(actions)), max_lines=1),
        "description": trim_lines(str(payload.get("description") or ""), max_lines=12),
        "proposedByAgentId": _clean_id(payload.get("proposedByAgentId")),
        "recommendedByAgentId": _clean_id(payload.get("recommendedByAgentId")),
        "ceoApproved": True,
        "ceoApprovalMode": "automatic",
        "requiresUserConfirmation": risk_level == "high",
        "riskLevel": risk_level,
        "status": "pending_user_confirmation" if risk_level == "high" else "ceo_approved",
        "actions": actions,
        "createdAt": now,
        "updatedAt": now,
        "appliedAt": "",
        "auditTrail": [
            {
                "at": now,
                "actor": "ceo",
                "event": "auto_approved",
                "reason": "CEO may recommend and approve, but high-risk application remains user-gated.",
            }
        ],
    }
    graph["proposals"] = [*(graph.get("proposals") or []), proposal]
    graph = _append_audit_event(
        graph,
        {
            "eventType": "proposal_created",
            "proposalId": proposal["proposalId"],
            "allowed": True,
            "reason": proposal["status"],
            "summary": proposal["title"],
        },
    )
    graph["updatedAt"] = utc_now_iso()
    _write_organization(graph)
    _record_org_event(
        "research.organization.proposal_created",
        outcome=proposal["status"],
        fields={
            "proposalId": proposal["proposalId"],
            "riskLevel": risk_level,
            "actionCount": len(actions),
            "requiresUserConfirmation": proposal["requiresUserConfirmation"],
        },
    )
    return {
        "organization": _organization_to_api(graph),
        "proposal": proposal,
    }


def apply_research_org_proposal(proposal_id: str) -> dict[str, Any]:
    """Apply a user-confirmed organization proposal."""

    normalized_id = _clean_id(proposal_id)
    if not normalized_id:
        raise ResearchOrganizationError("Research organization proposal id is required.")
    graph = _ensure_default_organization(_read_organization())
    proposals = [item for item in graph.get("proposals") or [] if isinstance(item, dict)]
    proposal = next((item for item in proposals if _clean_id(item.get("proposalId")) == normalized_id), None)
    if not proposal:
        raise FileNotFoundError(f"Research organization proposal not found: {proposal_id}")
    if str(proposal.get("status") or "").strip() == "applied":
        return {"organization": _organization_to_api(graph), "proposal": proposal, "results": []}
    if str(proposal.get("status") or "").strip() not in {"pending_user_confirmation", "ceo_approved"}:
        raise ResearchOrganizationError("Research organization proposal is not ready to apply.")

    results: list[dict[str, Any]] = []
    for action in list(proposal.get("actions") or []):
        result = _apply_proposal_action(graph, action if isinstance(action, dict) else {})
        graph = result.pop("_graph")
        results.append(result)

    now = utc_now_iso()
    proposal["status"] = "applied"
    proposal["appliedAt"] = now
    proposal["updatedAt"] = now
    proposal.setdefault("auditTrail", []).append(
        {
            "at": now,
            "actor": "user",
            "event": "applied",
            "reason": "User confirmed proposal application.",
        }
    )
    graph["proposals"] = proposals
    graph = _append_audit_event(
        graph,
        {
            "eventType": "proposal_applied",
            "proposalId": proposal["proposalId"],
            "allowed": True,
            "reason": "user_confirmed",
            "summary": proposal.get("title") or "",
        },
    )
    graph["updatedAt"] = now
    _write_organization(graph)
    _record_org_event(
        "research.organization.proposal_applied",
        outcome="applied",
        fields={
            "proposalId": proposal["proposalId"],
            "actionCount": len(results),
            "resultStatuses": [item.get("status") for item in results],
        },
    )
    return {
        "organization": _organization_to_api(graph),
        "proposal": proposal,
        "results": results,
    }


def retry_research_org_message_wake(message_id: str) -> dict[str, Any]:
    """Retry wake delivery for a pending organization/inbox message."""

    normalized_id = _clean_id(message_id)
    if not normalized_id:
        raise ResearchOrganizationError("Research organization message id is required.")
    graph = _ensure_default_organization(_read_organization())
    messages = [item for item in graph.get("messages") or [] if isinstance(item, dict)]
    message = next(
        (
            item for item in messages
            if _clean_id(item.get("messageId")) == normalized_id
            or any(_clean_id(delivery.get("inboxMessageId")) == normalized_id for delivery in item.get("deliveries") or [] if isinstance(delivery, dict))
        ),
        None,
    )
    if not message:
        raise FileNotFoundError(f"Research organization message not found: {message_id}")

    results = []
    for delivery in list(message.get("deliveries") or []):
        if not isinstance(delivery, dict) or not delivery.get("allowed"):
            continue
        inbox_message_id = _clean_id(delivery.get("inboxMessageId"))
        target_agent_id = _clean_id(delivery.get("targetAgentId"))
        if not inbox_message_id or not target_agent_id:
            continue
        inbox_message = _find_pending_inbox_message(target_agent_id, inbox_message_id)
        if not inbox_message:
            result = {
                "messageId": inbox_message_id,
                "targetAgentId": target_agent_id,
                "wakeStatus": "skipped_missing_pending_message",
                "reason": "pending_inbox_message_not_found",
            }
            results.append(result)
            continue
        wake = session_service.wake_agent_for_inbox_message(inbox_message)
        delivery["wakeStatus"] = str(wake.get("wakeStatus") or "")
        delivery["wakeReason"] = str(wake.get("reason") or "")
        delivery["turnId"] = str(wake.get("turnId") or "")
        delivery["retriedAt"] = utc_now_iso()
        results.append(wake)
        graph = _append_audit_event(
            graph,
            {
                "eventType": "message_retry_wake",
                "messageId": message.get("messageId") or "",
                "targetAgentId": target_agent_id,
                "allowed": True,
                "reason": str(wake.get("reason") or ""),
                "wakeStatus": str(wake.get("wakeStatus") or ""),
                "summary": "Retry wake for pending research organization message.",
            },
        )

    graph["messages"] = messages
    graph["updatedAt"] = utc_now_iso()
    _write_organization(graph)
    _record_org_event(
        "research.organization.message_retry_wake",
        outcome="retried",
        fields={
            "messageId": normalized_id,
            "resultCount": len(results),
            "wakeStatuses": [str(item.get("wakeStatus") or "") for item in results],
        },
    )
    return {
        "organization": _organization_to_api(graph),
        "message": message,
        "results": results,
    }


def _read_organization() -> dict[str, Any]:
    workspace = get_workspace()
    reader = getattr(workspace, "read_research_organization", None)
    if callable(reader):
        raw = reader()
    else:
        path = _organization_path(workspace)
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _normalize_organization(raw)


def _write_organization(graph: dict[str, Any]) -> None:
    workspace = get_workspace()
    payload = _normalize_organization(graph)
    payload.pop("path", None)
    writer = getattr(workspace, "write_research_organization", None)
    if callable(writer):
        if not writer(payload):
            raise ResearchOrganizationError("Failed to persist research organization graph.")
        return
    path = _organization_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _organization_path(workspace: Any) -> Path:
    getter = getattr(workspace, "get_research_organization_path", None)
    if callable(getter):
        return Path(getter())
    root = Path(getattr(workspace, "root", "") or "workspace")
    if root.name == "workspace":
        return root / "research" / "organization_graph.json"
    return root / "workspace" / "research" / "organization_graph.json"


def _normalize_organization(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    now = utc_now_iso()
    return {
        "schemaVersion": ORG_SCHEMA_VERSION,
        "updatedAt": str(payload.get("updatedAt") or now),
        "agents": [item for item in list(payload.get("agents") or []) if isinstance(item, dict)],
        "edges": [item for item in list(payload.get("edges") or []) if isinstance(item, dict)],
        "zones": [item for item in list(payload.get("zones") or []) if isinstance(item, dict)],
        "messages": _limit_tail([item for item in list(payload.get("messages") or []) if isinstance(item, dict)], MAX_ORG_MESSAGES),
        "proposals": [item for item in list(payload.get("proposals") or []) if isinstance(item, dict)],
        "auditEvents": _limit_tail([item for item in list(payload.get("auditEvents") or []) if isinstance(item, dict)], MAX_AUDIT_EVENTS),
    }


def _organization_to_api(graph: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_organization(graph)
    payload["path"] = str(_organization_path(get_workspace()))
    payload["agents"] = [_agent_node_to_api(node) for node in payload.get("agents") or []]
    payload["edges"] = [_edge_to_api(edge) for edge in payload.get("edges") or []]
    return payload


def _organization_to_canvas_api(graph: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_organization(graph)
    active_agents_by_id = {
        _clean_id(agent.get("agentId")): agent
        for agent in list_agents(include_archived=False)
        if isinstance(agent, dict) and _clean_id(agent.get("agentId"))
    }
    payload["path"] = str(_organization_path(get_workspace()))
    payload["agents"] = [
        _agent_node_to_canvas_api(node, active_agents_by_id.get(_clean_id(node.get("agentId"))))
        for node in payload.get("agents") or []
        if _clean_id(node.get("agentId")) in active_agents_by_id
        and str(node.get("status") or "active").strip() == "active"
    ]
    active_node_ids = {_clean_id(node.get("agentId")) for node in payload["agents"]}
    payload["edges"] = [
        _edge_to_api(edge)
        for edge in payload.get("edges") or []
        if _clean_id(edge.get("fromAgentId") or edge.get("source")) in active_node_ids
        and _clean_id(edge.get("toAgentId") or edge.get("target")) in active_node_ids
    ]
    return payload


def _prune_unresolvable_active_nodes(graph: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_organization(graph)
    active_agent_ids = {
        _clean_id(agent.get("agentId"))
        for agent in list_agents(include_archived=False)
        if isinstance(agent, dict) and _clean_id(agent.get("agentId"))
    }
    stale_agent_ids = {
        _clean_id(node.get("agentId"))
        for node in list(payload.get("agents") or [])
        if isinstance(node, dict)
        and _clean_id(node.get("agentId"))
        and str(node.get("status") or "active").strip() == "active"
        and _clean_id(node.get("agentId")) not in active_agent_ids
    }
    if not stale_agent_ids:
        return payload
    payload["agents"] = [
        node for node in list(payload.get("agents") or [])
        if isinstance(node, dict) and _clean_id(node.get("agentId")) not in stale_agent_ids
    ]
    payload["edges"] = _drop_edges_for_agents(payload.get("edges") or [], agent_ids=stale_agent_ids)
    _record_org_event(
        "research.organization.unresolvable_active_nodes_pruned",
        outcome="pruned",
        level="warning",
        fields={
            "staleActiveNodeCount": len(stale_agent_ids),
            "activeAgentDirectoryCount": len(active_agent_ids),
        },
    )
    return payload


def _ensure_default_organization(graph: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_organization(graph)
    nodes = [item for item in payload.get("agents") or [] if isinstance(item, dict)]
    ceo = _ensure_core_agent(
        system_role="ceo",
        preferred_agent_ids=_preferred_core_agent_ids("ceo", nodes),
        display_name="CEO Agent",
        role_key="research_ceo",
        prompt_template_id="prompt-research-ceo",
        employee_rank="ceo",
        title="CEO Agent",
        responsibilities=[
            "Directly communicates with the user.",
            "Turns research goals into organizational tasks.",
            "May approve recommendations, while high-risk changes stay user-gated.",
        ],
        allowed_tools=CEO_AGENT_TOOLS,
        memory_policy={
            "readSharedGroups": ["project", "research", "agent_config"],
            "writeSharedGroups": ["research"],
        },
    )
    advisor = _ensure_core_agent(
        system_role="organization_advisor",
        preferred_agent_ids=_preferred_core_agent_ids("organization_advisor", nodes),
        display_name="组织顾问 Agent",
        role_key="research_organization_advisor",
        prompt_template_id="prompt-research-organization-advisor",
        employee_rank="advisor",
        title="组织顾问 Agent",
        responsibilities=[
            "Designs temporary research organizations.",
            "Proposes Agent creation, permission changes, archives, and communication edges.",
            "Keeps former employee information preserved.",
        ],
        allowed_tools=ORGANIZATION_ADVISOR_TOOLS,
        memory_policy={
            "readSharedGroups": ["project", "research", "agent_config"],
            "writeSharedGroups": ["research"],
        },
    )
    steward = _ensure_core_agent(
        system_role="capability_steward",
        preferred_agent_ids=_preferred_core_agent_ids("capability_steward", nodes),
        display_name="能力管家 Agent",
        role_key="research_capability_steward",
        prompt_template_id="prompt-research-capability-steward",
        employee_rank="advisor",
        title="能力管家 Agent",
        responsibilities=[
            "Manages Agent prompt, tool, and memory policy boundaries.",
            "Audits whether requested capabilities match task risk.",
            "Coordinates policy changes through CEO approval and user gates.",
        ],
        allowed_tools=CAPABILITY_STEWARD_TOOLS,
        memory_policy={
            "readSharedGroups": ["project", "research", "agent_config"],
            "writeSharedGroups": ["agent_config"],
        },
    )
    current_core_agent_ids = {ceo["agentId"], advisor["agentId"], steward["agentId"]}
    dropped_core_agent_ids = _stale_core_agent_ids(nodes, current_agent_ids=current_core_agent_ids)
    if dropped_core_agent_ids:
        _record_stale_core_pruned_event(dropped_core_agent_ids, current_agent_ids=current_core_agent_ids)
    nodes = _drop_stale_core_nodes(nodes, stale_core_agent_ids=dropped_core_agent_ids)
    nodes = _upsert_agent_node(
        nodes,
        ceo,
        role="ceo",
        employee_rank="ceo",
        x=120,
        y=120,
        protected=True,
        zone_id="core",
    )
    nodes = _upsert_agent_node(
        nodes,
        advisor,
        role="organization_advisor",
        employee_rank="advisor",
        x=460,
        y=120,
        protected=True,
        zone_id="core",
    )
    nodes = _upsert_agent_node(
        nodes,
        steward,
        role="capability_steward",
        employee_rank="advisor",
        x=800,
        y=120,
        protected=True,
        zone_id="core",
    )
    previously_archived_core_agent_ids = {
        _clean_id(node.get("agentId"))
        for node in nodes
        if str(node.get("archiveReason") or "") == "duplicate_research_core_role"
    }
    nodes = _archive_stale_core_nodes(
        nodes,
        current_agent_ids_by_role={
            "ceo": _clean_id(ceo.get("agentId")),
            "organization_advisor": _clean_id(advisor.get("agentId")),
            "capability_steward": _clean_id(steward.get("agentId")),
        },
    )
    stale_core_agent_ids = {
        _clean_id(node.get("agentId"))
        for node in nodes
        if str(node.get("archiveReason") or "") == "duplicate_research_core_role"
        and str(node.get("status") or "active").strip() == "archived"
    }
    newly_archived_core_agent_ids = stale_core_agent_ids - previously_archived_core_agent_ids
    payload["agents"] = nodes
    payload["zones"] = _ensure_core_zone(payload.get("zones") or [])
    edges = _drop_edges_for_agents(payload.get("edges") or [], agent_ids=dropped_core_agent_ids)
    edges = _ensure_core_edges(edges, ceo["agentId"], advisor["agentId"], steward["agentId"])
    previously_archived_core_edge_count = _stale_core_edge_count(edges)
    payload["edges"] = _archive_stale_core_edges(edges, stale_core_agent_ids=stale_core_agent_ids)
    newly_archived_core_edge_count = max(0, _stale_core_edge_count(payload["edges"]) - previously_archived_core_edge_count)
    payload["updatedAt"] = str(payload.get("updatedAt") or utc_now_iso())
    _record_core_repair_event(
        payload,
        newly_archived_core_agent_ids=newly_archived_core_agent_ids,
        newly_archived_core_edge_count=newly_archived_core_edge_count,
    )
    return payload


def _ensure_core_agent(
    *,
    system_role: str,
    preferred_agent_ids: list[str],
    display_name: str,
    role_key: str,
    prompt_template_id: str,
    employee_rank: str,
    title: str,
    responsibilities: list[str],
    allowed_tools: list[str],
    memory_policy: dict[str, Any],
) -> dict[str, Any]:
    agent = _find_active_core_agent(system_role, preferred_agent_ids=preferred_agent_ids)
    if not agent:
        detail = session_service.create_chat_session(
            title=display_name,
            profile_id="primary",
            created_by="research_organization",
        )
        agent_id = _clean_id(detail.get("agentId"))
        agent = get_agent(agent_id) if agent_id else None
        if not agent:
            raise ResearchOrganizationError(f"Failed to create protected core Agent: {display_name}")

    metadata = dict(agent.get("metadata") or {})
    desired_metadata = {
        **metadata,
        "researchOrgRole": system_role,
        "systemRole": system_role,
        "protected": True,
        "employeeRank": employee_rank,
        "responsibilities": responsibilities,
    }
    desired_tools = _normalize_allowed_tools(allowed_tools)
    current_policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}
    current_memory_policy = agent.get("memoryPolicy") if isinstance(agent.get("memoryPolicy"), dict) else {}
    desired_read_groups = _normalize_allowed_tools(memory_policy.get("readSharedGroups") or [])
    desired_write_groups = _normalize_allowed_tools(memory_policy.get("writeSharedGroups") or [])
    needs_update = (
        str(agent.get("primaryMode") or "") != "research"
        or str(agent.get("roleKey") or "") != role_key
        or str(agent.get("promptTemplateId") or "") != prompt_template_id
        or any(metadata.get(key) != desired_metadata.get(key) for key in ("researchOrgRole", "systemRole", "protected", "employeeRank"))
        or list(current_policy.get("allowedTools") or []) != desired_tools
        or list(current_memory_policy.get("readSharedGroups") or []) != desired_read_groups
        or list(current_memory_policy.get("writeSharedGroups") or []) != desired_write_groups
    )
    if needs_update:
        agent = update_agent_instance(
            agent["agentId"],
            primary_mode="research",
            role_key=role_key,
            prompt_template_id=prompt_template_id,
            metadata=desired_metadata,
            tool_policy=_explicit_tool_policy_payload(desired_tools, preferred_tools=["agent_message_tool"]),
            memory_policy={
                "readSharedGroups": desired_read_groups,
                "writeSharedGroups": desired_write_groups,
            },
        )
    return agent


def _find_active_core_agent(system_role: str, *, preferred_agent_ids: list[str] | None = None) -> dict[str, Any] | None:
    candidates = [
        agent for agent in list_agents(include_archived=False)
        if _agent_core_role(agent) == system_role
    ]
    candidates_by_id = {_clean_id(agent.get("agentId")): agent for agent in candidates}
    for agent_id in _dedupe_ids(list(preferred_agent_ids or []) + _research_mode_agent_ids()):
        agent = candidates_by_id.get(agent_id)
        if agent:
            return agent
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""))[0]


def _preferred_core_agent_ids(system_role: str, nodes: list[dict[str, Any]]) -> list[str]:
    active_graph_ids = [
        _clean_id(node.get("agentId"))
        for node in nodes
        if _core_role_for_node(node) == system_role
        and str(node.get("status") or "active").strip() == "active"
    ]
    return _dedupe_ids([*_research_mode_agent_ids(), *active_graph_ids])


def _research_mode_agent_ids() -> list[str]:
    try:
        path = agent_mode_binding_service.mode_binding_path()
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    binding = next(
        (
            item for item in list(payload.get("bindings") or [])
            if isinstance(item, dict) and str(item.get("mode") or "").strip() == "research"
        ),
        {},
    )
    ids: list[str] = []
    ids.append(_clean_id(binding.get("defaultAgentId")))
    ids.extend(_clean_id(item) for item in list(binding.get("pool") or []))
    ids.extend(_clean_id(item) for item in list(binding.get("availableAgentIds") or []))
    flow_bindings = binding.get("flowBindings") if isinstance(binding.get("flowBindings"), dict) else {}
    ids.extend(_clean_id(item) for item in flow_bindings.values())
    return _dedupe_ids(ids)


def _agent_core_role(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role = str(metadata.get("systemRole") or metadata.get("researchOrgRole") or "").strip()
    return role if role in PROTECTED_SYSTEM_ROLES else ""


def _dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        agent_id = _clean_id(value)
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        result.append(agent_id)
    return result


def _upsert_agent_node(
    nodes: list[dict[str, Any]],
    agent: dict[str, Any],
    *,
    role: str,
    employee_rank: str,
    x: int,
    y: int,
    protected: bool,
    zone_id: str,
) -> list[dict[str, Any]]:
    agent_id = _clean_id(agent.get("agentId"))
    existing = next((item for item in nodes if _clean_id(item.get("agentId")) == agent_id), None)
    base = existing or {}
    node = {
        **base,
        "nodeId": str(base.get("nodeId") or agent_id),
        "agentId": agent_id,
        "agentCode": str(agent.get("agentCode") or ""),
        "displayName": str(agent.get("displayName") or ""),
        "role": str(base.get("role") or role),
        "employeeRank": str(base.get("employeeRank") or employee_rank),
        "protected": bool(base.get("protected", protected)),
        "zoneId": str(base.get("zoneId") or zone_id),
        "status": str(agent.get("status") or base.get("status") or "active"),
        "x": _coerce_int(base.get("x"), x),
        "y": _coerce_int(base.get("y"), y),
        "agent": agent,
        "toolPolicy": resolve_tool_policy_for_agent(agent_id),
        "updatedAt": str(agent.get("updatedAt") or base.get("updatedAt") or ""),
    }
    if node["status"] != "archived":
        node.pop("stale", None)
        node.pop("missingAgent", None)
        node.pop("archiveReason", None)
        node.pop("archivedAt", None)
    others = [item for item in nodes if _clean_id(item.get("agentId")) != agent_id]
    return [*others, node]


def _archive_stale_core_nodes(
    nodes: list[dict[str, Any]],
    *,
    current_agent_ids_by_role: dict[str, str],
) -> list[dict[str, Any]]:
    now = utc_now_iso()
    archived: list[dict[str, Any]] = []
    for item in nodes:
        if not isinstance(item, dict):
            continue
        node = dict(item)
        role = _core_role_for_node(node)
        agent_id = _clean_id(node.get("agentId"))
        current_agent_id = _clean_id(current_agent_ids_by_role.get(role))
        if (
            role in PROTECTED_SYSTEM_ROLES
            and agent_id
            and current_agent_id
            and agent_id != current_agent_id
            and str(node.get("status") or "active").strip() != "archived"
        ):
            node["status"] = "archived"
            node["stale"] = True
            node["missingAgent"] = get_agent(agent_id, include_archived=True) is None
            node["archivedAt"] = str(node.get("archivedAt") or now)
            node["updatedAt"] = now
            node["archiveReason"] = "duplicate_research_core_role"
        archived.append(node)
    return archived


def _stale_core_agent_ids(nodes: list[dict[str, Any]], *, current_agent_ids: set[str]) -> set[str]:
    current_ids = {_clean_id(item) for item in current_agent_ids if _clean_id(item)}
    dropped_ids: set[str] = set()
    for item in nodes:
        if not isinstance(item, dict):
            continue
        role = _core_role_for_node(item)
        agent_id = _clean_id(item.get("agentId"))
        if role in PROTECTED_SYSTEM_ROLES and agent_id and agent_id not in current_ids:
            dropped_ids.add(agent_id)
    return dropped_ids


def _drop_stale_core_nodes(nodes: list[dict[str, Any]], *, stale_core_agent_ids: set[str]) -> list[dict[str, Any]]:
    stale_ids = {_clean_id(item) for item in stale_core_agent_ids if _clean_id(item)}
    if not stale_ids:
        return nodes
    return [
        item for item in nodes
        if isinstance(item, dict) and _clean_id(item.get("agentId")) not in stale_ids
    ]


def _drop_edges_for_agents(edges: list[dict[str, Any]], *, agent_ids: set[str]) -> list[dict[str, Any]]:
    stale_ids = {_clean_id(item) for item in agent_ids if _clean_id(item)}
    if not stale_ids:
        return edges
    return [
        edge for edge in edges
        if isinstance(edge, dict)
        and _clean_id(edge.get("fromAgentId") or edge.get("source")) not in stale_ids
        and _clean_id(edge.get("toAgentId") or edge.get("target")) not in stale_ids
    ]


def _record_stale_core_pruned_event(stale_core_agent_ids: set[str], *, current_agent_ids: set[str]) -> None:
    current_ids = {_clean_id(item) for item in current_agent_ids if _clean_id(item)}
    if stale_core_agent_ids:
        _record_org_event(
            "research.organization.stale_core_nodes_pruned",
            outcome="pruned",
            level="warning",
            fields={
                "staleCoreNodeCount": len(stale_core_agent_ids),
                "currentCoreAgentIds": sorted(current_ids),
            },
        )


def _archive_stale_core_edges(
    edges: list[dict[str, Any]],
    *,
    stale_core_agent_ids: set[str],
) -> list[dict[str, Any]]:
    if not stale_core_agent_ids:
        return edges
    now = utc_now_iso()
    result: list[dict[str, Any]] = []
    for item in edges:
        if not isinstance(item, dict):
            continue
        edge = dict(item)
        from_agent_id = _clean_id(edge.get("fromAgentId") or edge.get("source"))
        to_agent_id = _clean_id(edge.get("toAgentId") or edge.get("target"))
        if (
            (from_agent_id in stale_core_agent_ids or to_agent_id in stale_core_agent_ids)
            and str(edge.get("status") or "active").strip() != "archived"
        ):
            edge["status"] = "archived"
            edge["stale"] = True
            edge["archivedAt"] = str(edge.get("archivedAt") or now)
            edge["updatedAt"] = now
            edge["archiveReason"] = "stale_research_core_endpoint"
        result.append(edge)
    return result


def _stale_core_edge_count(edges: list[dict[str, Any]]) -> int:
    return sum(
        1
        for edge in edges
        if isinstance(edge, dict) and str(edge.get("archiveReason") or "") == "stale_research_core_endpoint"
    )


def _record_core_repair_event(
    payload: dict[str, Any],
    *,
    newly_archived_core_agent_ids: set[str],
    newly_archived_core_edge_count: int,
) -> None:
    if not newly_archived_core_agent_ids and newly_archived_core_edge_count <= 0:
        return
    active_core_ids_by_role = {
        role: [
            _clean_id(node.get("agentId"))
            for node in list(payload.get("agents") or [])
            if isinstance(node, dict)
            and _core_role_for_node(node) == role
            and str(node.get("status") or "active").strip() == "active"
        ]
        for role in sorted(PROTECTED_SYSTEM_ROLES)
    }
    archived_edge_count = sum(
        1
        for edge in list(payload.get("edges") or [])
        if isinstance(edge, dict) and str(edge.get("archiveReason") or "") == "stale_research_core_endpoint"
    )
    _record_org_event(
        "research.organization.core_repaired",
        outcome="repaired",
        level="warning",
        fields={
            "newlyArchivedStaleCoreNodeCount": len(newly_archived_core_agent_ids),
            "newlyArchivedStaleCoreEdgeCount": newly_archived_core_edge_count,
            "totalArchivedStaleCoreEdgeCount": archived_edge_count,
            "activeCoreIdsByRole": active_core_ids_by_role,
        },
    )


def _core_role_for_node(node: dict[str, Any]) -> str:
    agent = node.get("agent") if isinstance(node.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role = str(
        node.get("role")
        or metadata.get("systemRole")
        or metadata.get("researchOrgRole")
        or ""
    ).strip()
    return role if role in PROTECTED_SYSTEM_ROLES else ""


def _ensure_core_zone(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(_clean_id(item.get("zoneId")) == "core" for item in zones if isinstance(item, dict)):
        return zones
    return [
        *zones,
        {
            "zoneId": "core",
            "label": "核心管理区",
            "description": "CEO、组织顾问与能力管家所在的受保护默认区域。",
            "agentIds": [],
            "createdAt": utc_now_iso(),
        },
    ]


def _ensure_core_edges(
    edges: list[dict[str, Any]],
    ceo_agent_id: str,
    advisor_agent_id: str,
    steward_agent_id: str,
) -> list[dict[str, Any]]:
    result = [edge for edge in edges if isinstance(edge, dict)]
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{ceo_agent_id}-{advisor_agent_id}",
            "fromAgentId": ceo_agent_id,
            "toAgentId": advisor_agent_id,
            "label": "CEO 下达组织调整任务",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "task", "decision"],
                "allowedIntents": ["organize", "delegate", "review", "approve", "research_goal"],
                "wakeStrategy": "immediate",
                "maxForwardDepth": 2,
            },
            "status": "active",
        },
    )
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{ceo_agent_id}-{steward_agent_id}",
            "fromAgentId": ceo_agent_id,
            "toAgentId": steward_agent_id,
            "label": "CEO 请求能力策略",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "task", "decision"],
                "allowedIntents": ["capability_policy", "prompt_policy", "tool_policy", "memory_policy", "research_goal"],
                "wakeStrategy": "immediate",
                "maxForwardDepth": 2,
            },
            "status": "active",
        },
    )
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{advisor_agent_id}-{ceo_agent_id}",
            "fromAgentId": advisor_agent_id,
            "toAgentId": ceo_agent_id,
            "label": "组织顾问向 CEO 汇报",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "report", "escalation"],
                "allowedIntents": ["proposal", "report", "risk", "organization_design"],
                "wakeStrategy": "mailbox_only",
                "maxForwardDepth": 1,
            },
            "status": "active",
        },
    )
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{steward_agent_id}-{ceo_agent_id}",
            "fromAgentId": steward_agent_id,
            "toAgentId": ceo_agent_id,
            "label": "能力管家向 CEO 汇报",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "report", "escalation"],
                "allowedIntents": ["capability_report", "risk", "prompt_policy", "tool_policy", "memory_policy"],
                "wakeStrategy": "mailbox_only",
                "maxForwardDepth": 1,
            },
            "status": "active",
        },
    )
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{advisor_agent_id}-{steward_agent_id}",
            "fromAgentId": advisor_agent_id,
            "toAgentId": steward_agent_id,
            "label": "组织顾问请求能力配置",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "task"],
                "allowedIntents": ["capability_design", "role_setup", "permission_review", "memory_policy"],
                "wakeStrategy": "conditional",
                "maxForwardDepth": 1,
            },
            "status": "active",
        },
    )
    result = _upsert_edge(
        result,
        {
            "edgeId": f"edge-{steward_agent_id}-{advisor_agent_id}",
            "fromAgentId": steward_agent_id,
            "toAgentId": advisor_agent_id,
            "label": "能力管家反馈组织配置",
            "communicationPolicy": {
                "allowedMessageTypes": ["notice", "request", "report"],
                "allowedIntents": ["capability_plan", "permission_review", "risk", "policy_update"],
                "wakeStrategy": "mailbox_only",
                "maxForwardDepth": 1,
            },
            "status": "active",
        },
    )
    return result


def _upsert_edge(edges: list[dict[str, Any]], edge: dict[str, Any]) -> list[dict[str, Any]]:
    from_agent_id = _clean_id(edge.get("fromAgentId") or edge.get("source"))
    to_agent_id = _clean_id(edge.get("toAgentId") or edge.get("target"))
    edge_id = _clean_id(edge.get("edgeId") or edge.get("id")) or f"edge-{from_agent_id}-{to_agent_id}"
    existing_index = next(
        (
            index for index, item in enumerate(edges)
            if _clean_id(item.get("edgeId") or item.get("id")) == edge_id
            or (_clean_id(item.get("fromAgentId") or item.get("source")) == from_agent_id and _clean_id(item.get("toAgentId") or item.get("target")) == to_agent_id)
        ),
        None,
    )
    normalized = _edge_to_api({**(edges[existing_index] if existing_index is not None else {}), **edge, "edgeId": edge_id})
    if normalized["status"] != "archived":
        normalized["stale"] = False
        normalized["archiveReason"] = ""
        normalized["archivedAt"] = ""
    if existing_index is None:
        return [*edges, normalized]
    next_edges = list(edges)
    next_edges[existing_index] = normalized
    return next_edges


def _edge_to_api(edge: dict[str, Any]) -> dict[str, Any]:
    from_agent_id = _clean_id(edge.get("fromAgentId") or edge.get("source"))
    to_agent_id = _clean_id(edge.get("toAgentId") or edge.get("target"))
    policy = edge.get("communicationPolicy") if isinstance(edge.get("communicationPolicy"), dict) else {}
    now = utc_now_iso()
    return {
        "edgeId": _clean_id(edge.get("edgeId") or edge.get("id")) or f"edge-{from_agent_id}-{to_agent_id}",
        "fromAgentId": from_agent_id,
        "toAgentId": to_agent_id,
        "label": trim_lines(str(edge.get("label") or ""), max_lines=1),
        "communicationPolicy": _normalize_communication_policy(policy),
        "status": str(edge.get("status") or "active").strip() or "active",
        "stale": bool(edge.get("stale")),
        "archiveReason": str(edge.get("archiveReason") or ""),
        "createdAt": str(edge.get("createdAt") or now),
        "archivedAt": str(edge.get("archivedAt") or ""),
        "updatedAt": str(edge.get("updatedAt") or now),
    }


def _agent_node_to_api(node: dict[str, Any]) -> dict[str, Any]:
    agent_id = _clean_id(node.get("agentId"))
    agent = get_agent(agent_id, include_archived=True) if agent_id else None
    tool_policy = resolve_tool_policy_for_agent(agent_id) if agent_id else {}
    missing_agent = bool(agent_id and agent is None)
    node_status = str(node.get("status") or "active").strip() or "active"
    if node_status == "archived":
        status = "archived"
    elif missing_agent:
        status = "stale"
    else:
        status = str((agent or {}).get("status") or node_status)
    return {
        "nodeId": _clean_id(node.get("nodeId")) or agent_id,
        "agentId": agent_id,
        "agentCode": str((agent or {}).get("agentCode") or node.get("agentCode") or ""),
        "displayName": str((agent or {}).get("displayName") or node.get("displayName") or ""),
        "role": str(node.get("role") or ""),
        "employeeRank": str(node.get("employeeRank") or ((agent or {}).get("metadata") or {}).get("employeeRank") or "member"),
        "protected": bool(node.get("protected") or ((agent or {}).get("metadata") or {}).get("protected")),
        "zoneId": str(node.get("zoneId") or ""),
        "status": status,
        "stale": bool(node.get("stale") or missing_agent or status == "stale"),
        "missingAgent": missing_agent,
        "archiveReason": str(node.get("archiveReason") or ""),
        "x": _coerce_int(node.get("x"), 0),
        "y": _coerce_int(node.get("y"), 0),
        "agent": agent,
        "toolPolicy": tool_policy,
        "memoryPolicy": resolve_memory_policy_for_agent(agent_id) if agent_id else {},
        "allowedTools": list(tool_policy.get("allowedTools") or []),
        "updatedAt": str((agent or {}).get("updatedAt") or node.get("updatedAt") or ""),
    }


def _agent_node_to_canvas_api(node: dict[str, Any], active_agent: dict[str, Any] | None = None) -> dict[str, Any]:
    stored_agent = node.get("agent") if isinstance(node.get("agent"), dict) else {}
    agent = active_agent if isinstance(active_agent, dict) else stored_agent
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return {
        "nodeId": _clean_id(node.get("nodeId")) or _clean_id(node.get("agentId")),
        "agentId": _clean_id(node.get("agentId")),
        "agentCode": str(agent.get("agentCode") or node.get("agentCode") or ""),
        "displayName": str(agent.get("displayName") or node.get("displayName") or ""),
        "role": str(node.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole") or ""),
        "employeeRank": str(node.get("employeeRank") or metadata.get("employeeRank") or "member"),
        "protected": bool(node.get("protected") or metadata.get("protected")),
        "zoneId": str(node.get("zoneId") or ""),
        "status": str(node.get("status") or agent.get("status") or "active"),
        "x": _coerce_int(node.get("x"), 0),
        "y": _coerce_int(node.get("y"), 0),
        "agent": {
            "agentId": str(agent.get("agentId") or node.get("agentId") or ""),
            "agentCode": str(agent.get("agentCode") or node.get("agentCode") or ""),
            "displayName": str(agent.get("displayName") or node.get("displayName") or ""),
            "roleKey": str(agent.get("roleKey") or ""),
            "promptTemplateId": str(agent.get("promptTemplateId") or ""),
            "templateId": str(agent.get("templateId") or ""),
            "metadata": {
                "functionalDisplayName": str(metadata.get("functionalDisplayName") or ""),
                "responsibilities": list(metadata.get("responsibilities") or [])[:8]
                if isinstance(metadata.get("responsibilities"), list)
                else [],
            },
        },
        "allowedTools": list((node.get("toolPolicy") if isinstance(node.get("toolPolicy"), dict) else {}).get("allowedTools") or [])[:40],
        "updatedAt": str(agent.get("updatedAt") or node.get("updatedAt") or ""),
    }


def _normalize_communication_policy(policy: dict[str, Any]) -> dict[str, Any]:
    allowed_types = [
        _normalize_message_type(item)
        for item in list(policy.get("allowedMessageTypes") or policy.get("messageTypes") or [])
        if str(item or "").strip()
    ]
    if not allowed_types:
        allowed_types = ["notice", "request", "report"]
    wake_strategy = str(policy.get("wakeStrategy") or "conditional").strip()
    if wake_strategy not in {"immediate", "conditional", "mailbox_only", "never"}:
        wake_strategy = "conditional"
    try:
        max_forward_depth = max(0, min(8, int(policy.get("maxForwardDepth", 1))))
    except (TypeError, ValueError):
        max_forward_depth = 1
    return {
        "allowedMessageTypes": list(dict.fromkeys(allowed_types)),
        "allowedIntents": [trim_lines(str(item or ""), max_lines=1) for item in list(policy.get("allowedIntents") or []) if str(item or "").strip()],
        "wakeStrategy": wake_strategy,
        "maxForwardDepth": max_forward_depth,
    }


def _resolve_message_recipients(
    graph: dict[str, Any],
    payload: dict[str, Any],
    delivery_mode: str,
    source_agent_id: str,
) -> list[str]:
    if delivery_mode == "broadcast":
        recipients = [
            _clean_id(node.get("agentId"))
            for node in graph.get("agents") or []
            if _clean_id(node.get("agentId")) and str(node.get("status") or "active") != "archived"
        ]
    elif delivery_mode == "zone":
        zone_id = _clean_id(payload.get("zoneId"))
        recipients = [
            _clean_id(node.get("agentId"))
            for node in graph.get("agents") or []
            if _clean_id(node.get("zoneId")) == zone_id and str(node.get("status") or "active") != "archived"
        ]
    else:
        raw_targets = list(payload.get("targetAgentIds") or [])
        single = _clean_id(payload.get("targetAgentId"))
        if single:
            raw_targets.append(single)
        if not raw_targets and str(payload.get("sourceType") or "").strip().lower() != "agent":
            ceo = _find_org_agent_by_role(graph, "ceo")
            if ceo:
                raw_targets.append(ceo.get("agentId"))
        recipients = [_clean_id(item) for item in raw_targets]
    return [
        item for item in dict.fromkeys(recipients)
        if item and item != source_agent_id
    ]


def _deliver_message_to_agent(
    graph: dict[str, Any],
    message: dict[str, Any],
    target_agent_id: str,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_agent_id = _clean_id(message.get("sourceAgentId"))
    message_type = _normalize_message_type(message.get("messageType"))
    policy_result = _evaluate_communication_policy(
        graph,
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        source_type=str(message.get("sourceType") or ""),
        message_type=message_type,
        intent=str(message.get("intent") or ""),
        human_override=bool(message.get("humanOverride")),
    )
    delivery = {
        "targetAgentId": target_agent_id,
        "targetAgentCode": _agent_field(target_agent_id, "agentCode"),
        "targetAgentName": _agent_field(target_agent_id, "displayName"),
        "allowed": bool(policy_result.get("allowed")),
        "reason": str(policy_result.get("reason") or ""),
        "edgeId": str(policy_result.get("edgeId") or ""),
        "policy": policy_result.get("policy") or {},
        "inboxMessageId": "",
        "wakeRequested": False,
        "wakeStatus": "not_requested",
        "wakeReason": "",
        "turnId": "",
        "deliveredAt": "",
    }
    if not delivery["allowed"]:
        delivery["wakeStatus"] = "blocked"
        return delivery
    supervision_decision = _evaluate_message_supervision_policy(message)
    delivery["supervision"] = _supervision_decision_to_delivery(supervision_decision)
    record_supervision_policy_decision(supervision_decision)
    if not supervision_decision.allowed:
        delivery["allowed"] = False
        delivery["reason"] = supervision_decision.reason
        delivery["wakeStatus"] = "blocked"
        return delivery

    wake_requested = _should_wake_target(
        policy=policy_result.get("policy") or {},
        message_type=message_type,
        source_type=str(message.get("sourceType") or ""),
        requested=bool(message.get("wakeTarget")),
        mailbox_only=bool(payload.get("mailboxOnly")),
    )
    try:
        inbox_message = write_agent_inbox_message(
            target_agent_id,
            content=str(message.get("content") or ""),
            source_agent_id=source_agent_id,
            source_session_id=str(payload.get("sourceSessionId") or ""),
            source_room_id=str(payload.get("sourceRoomId") or ""),
            source_round_id=str(payload.get("sourceRoundId") or ""),
            thread_id=str(message.get("threadId") or ""),
            kind=f"research_org_{message_type}",
            summary=str(message.get("summary") or ""),
            prompt_eligible=True,
            created_by="human_override" if message.get("humanOverride") else "research_org",
            metadata={
                "researchOrgMessageId": message.get("messageId") or "",
                "researchOrgDeliveryMode": message.get("deliveryMode") or "",
                "researchOrgMessageType": message_type,
                "researchOrgIntent": message.get("intent") or "",
                "humanOverride": bool(message.get("humanOverride")),
                "communicationEdgeId": delivery["edgeId"],
            },
        )
    except (AgentDirectoryError, AgentNotFoundError) as exc:
        delivery["allowed"] = False
        delivery["reason"] = type(exc).__name__
        delivery["wakeStatus"] = "blocked"
        return delivery

    delivery["inboxMessageId"] = str(inbox_message.get("messageId") or inbox_message.get("eventId") or "")
    delivery["deliveredAt"] = utc_now_iso()
    delivery["wakeRequested"] = wake_requested
    if wake_requested:
        wake = session_service.wake_agent_for_inbox_message(inbox_message)
        delivery["wakeStatus"] = str(wake.get("wakeStatus") or "")
        delivery["wakeReason"] = str(wake.get("reason") or "")
        delivery["turnId"] = str(wake.get("turnId") or "")
    return delivery


def _evaluate_message_supervision_policy(message: dict[str, Any]):
    source_agent_id = _clean_id(message.get("sourceAgentId"))
    return evaluate_supervision_policy(
        resolve_supervision_policy_for_agent(source_agent_id),
        agent_id=source_agent_id,
        action="research_org_message",
        human_override=bool(message.get("humanOverride")),
        user_initiated=str(message.get("sourceType") or "").strip().lower() == "user",
    )


def _supervision_decision_to_delivery(decision: Any) -> dict[str, Any]:
    return {
        "allowed": bool(getattr(decision, "allowed", True)),
        "reason": str(getattr(decision, "reason", "") or ""),
        "supervisionEnabled": bool(getattr(decision, "supervision_enabled", False)),
        "requiresReview": bool(getattr(decision, "requires_review", False)),
        "reviewMode": str(getattr(decision, "review_mode", "") or ""),
        "evidenceLevel": str(getattr(decision, "evidence_level", "") or ""),
    }


def _evaluate_communication_policy(
    graph: dict[str, Any],
    *,
    source_agent_id: str,
    target_agent_id: str,
    source_type: str,
    message_type: str,
    intent: str,
    human_override: bool,
) -> dict[str, Any]:
    target_node = _find_org_agent_node(graph, target_agent_id)
    if not target_node:
        return {"allowed": False, "reason": "target_not_in_organization"}
    target_agent = get_agent(target_agent_id, include_archived=True)
    if not target_agent or str(target_agent.get("status") or "active").strip() == "archived":
        return {"allowed": False, "reason": "target_agent_archived_or_missing"}
    if human_override or source_type == "user":
        return {
            "allowed": True,
            "reason": "human_override",
            "edgeId": "",
            "policy": {"wakeStrategy": "immediate", "allowedMessageTypes": list(MESSAGE_TYPES), "allowedIntents": [], "maxForwardDepth": 0},
        }
    if not source_agent_id:
        return {"allowed": False, "reason": "source_agent_required"}
    source_node = _find_org_agent_node(graph, source_agent_id)
    if not source_node:
        return {"allowed": False, "reason": "source_not_in_organization"}
    source_agent = get_agent(source_agent_id, include_archived=True)
    if not source_agent or str(source_agent.get("status") or "active").strip() == "archived":
        return {"allowed": False, "reason": "source_agent_archived_or_missing"}
    edge = _find_communication_edge(graph, source_agent_id, target_agent_id)
    if not edge:
        return {"allowed": False, "reason": "communication_edge_missing"}
    policy = _normalize_communication_policy(edge.get("communicationPolicy") if isinstance(edge.get("communicationPolicy"), dict) else {})
    if message_type not in set(policy.get("allowedMessageTypes") or []):
        return {"allowed": False, "reason": "message_type_not_allowed", "edgeId": edge.get("edgeId") or "", "policy": policy}
    allowed_intents = {str(item or "").strip().casefold() for item in policy.get("allowedIntents") or [] if str(item or "").strip()}
    if allowed_intents and intent and intent.casefold() not in allowed_intents:
        return {"allowed": False, "reason": "intent_not_allowed", "edgeId": edge.get("edgeId") or "", "policy": policy}
    if _rank_weight(source_node) < _rank_weight(target_node) and message_type in {"task", "decision"}:
        return {"allowed": False, "reason": "rank_cannot_assign_upward", "edgeId": edge.get("edgeId") or "", "policy": policy}
    return {"allowed": True, "reason": "policy_allowed", "edgeId": edge.get("edgeId") or "", "policy": policy}


def _should_wake_target(
    *,
    policy: dict[str, Any],
    message_type: str,
    source_type: str,
    requested: bool,
    mailbox_only: bool,
) -> bool:
    if mailbox_only or not requested:
        return False
    if source_type == "user":
        return True
    strategy = str(policy.get("wakeStrategy") or "conditional").strip()
    if strategy == "immediate":
        return True
    if strategy in {"mailbox_only", "never"}:
        return False
    return message_type in {"task", "escalation", "decision"}


def _normalize_proposal_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_actions = list(payload.get("actions") or [])
    if not raw_actions:
        action = payload.get("action") if isinstance(payload.get("action"), dict) else dict(payload)
        raw_actions = [action]
    actions = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("actionType") or item.get("type") or item.get("action") or "").strip()
        if not action_type:
            continue
        actions.append({**item, "actionType": action_type})
    return actions


def _proposal_risk_level(payload: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    explicit = str(payload.get("riskLevel") or "").strip().lower()
    if explicit in {"low", "medium", "high"}:
        return explicit
    for action in actions:
        action_type = str(action.get("actionType") or "").strip()
        if action_type in HIGH_RISK_ACTIONS:
            return "high"
    return "medium"


def _apply_proposal_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("actionType") or "").strip()
    if action_type == "create_agent":
        return _apply_create_agent_action(graph, action)
    if action_type == "archive_agent":
        return _apply_archive_agent_action(graph, action)
    if action_type in {"update_tool_policy", "expand_tool_permissions"}:
        return _apply_tool_policy_action(graph, action)
    if action_type in {"create_edge", "update_edge", "update_communication_edge"}:
        return _apply_edge_action(graph, action)
    if action_type == "delete_edge":
        return _apply_delete_edge_action(graph, action)
    return {"_graph": graph, "actionType": action_type, "status": "skipped", "reason": "unsupported_action_type"}


def _apply_create_agent_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    display_name = trim_lines(str(action.get("displayName") or action.get("title") or "科研 Agent"), max_lines=1)
    session = session_service.create_chat_session(
        title=display_name,
        profile_id=str(action.get("profileId") or "primary").strip() or "primary",
        created_by="research_organization_proposal",
    )
    agent_id = _clean_id(session.get("agentId"))
    if not agent_id:
        raise ResearchOrganizationError("Failed to create Agent for organization proposal.")
    employee_rank = str(action.get("employeeRank") or "specialist").strip() or "specialist"
    allowed_tools = _normalize_allowed_tools(action.get("allowedTools") or DEFAULT_CREATED_AGENT_TOOLS)
    research_role = str(action.get("role") or "research_specialist").strip() or "research_specialist"
    role_key = str(action.get("roleKey") or research_role).strip() or research_role
    prompt_template_id = str(action.get("promptTemplateId") or "").strip()
    responsibilities = _normalize_contract_lines(action.get("responsibilities") or action.get("deliverables") or [])
    forbidden = _normalize_contract_lines(
        action.get("forbidden")
        or [
            "Do not expand your own tools, memory writes, team membership, or communication edges.",
            "Do not claim direct organization-change authority; request CEO/Advisor/Capability Steward review.",
        ]
    )
    metadata = {
        **(action.get("metadata") if isinstance(action.get("metadata"), dict) else {}),
        "researchOrgRole": research_role,
        "employeeRank": employee_rank,
        "protected": False,
        "roleContract": {
            "teamId": str(action.get("teamId") or "research-team").strip() or "research-team",
            "role": research_role,
            "roleKey": role_key,
            "promptTemplateId": prompt_template_id,
            "reportTo": str(action.get("reportTo") or "CEO").strip() or "CEO",
            "responsibilities": responsibilities,
            "forbidden": forbidden,
            "allowedTools": allowed_tools,
            "readSharedGroups": _normalize_allowed_tools(action.get("readSharedGroups") or ["project", "research"]),
            "writeSharedGroups": _normalize_allowed_tools(action.get("writeSharedGroups") or []),
            "communicationTargets": _normalize_contract_lines(action.get("communicationTargets") or ["CEO", "Organization Advisor", "Capability Steward"]),
            "escalationPath": str(action.get("escalationPath") or "CEO -> Organization Advisor -> Capability Steward -> User gate").strip(),
            "onboardingRequired": True,
        },
    }
    agent = update_agent_instance(
        agent_id,
        primary_mode=str(action.get("primaryMode") or "research").strip() or "research",
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        metadata=metadata,
        tool_policy=_explicit_tool_policy_payload(allowed_tools, preferred_tools=["agent_message_tool"]),
        memory_policy={
            "readSharedGroups": metadata["roleContract"]["readSharedGroups"],
            "writeSharedGroups": metadata["roleContract"]["writeSharedGroups"],
        },
    )
    nodes = graph.get("agents") or []
    graph["agents"] = _upsert_agent_node(
        nodes,
        agent,
        role=metadata["researchOrgRole"],
        employee_rank=employee_rank,
        x=_coerce_int(action.get("x"), 260 + len(nodes) * 80),
        y=_coerce_int(action.get("y"), 320),
        protected=False,
        zone_id=str(action.get("zoneId") or "research").strip() or "research",
    )
    for edge in list(action.get("edges") or []):
        if isinstance(edge, dict):
            graph["edges"] = _upsert_edge(graph.get("edges") or [], {**edge, "toAgentId": edge.get("toAgentId") or agent_id})
    return {
        "_graph": graph,
        "actionType": "create_agent",
        "status": "applied",
        "agentId": agent_id,
        "displayName": display_name,
    }


def _apply_archive_agent_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    agent_id = _clean_id(action.get("agentId") or action.get("targetAgentId"))
    if not agent_id:
        raise ResearchOrganizationError("Archive Agent action requires agentId.")
    archived = archive_agent_instance(agent_id)
    for node in graph.get("agents") or []:
        if _clean_id(node.get("agentId")) == agent_id:
            node["status"] = "archived"
            node["archivedAt"] = utc_now_iso()
    return {
        "_graph": graph,
        "actionType": "archive_agent",
        "status": "applied",
        "agentId": agent_id,
        "displayName": archived.get("displayName") or "",
    }


def _apply_tool_policy_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    agent_id = _clean_id(action.get("agentId") or action.get("targetAgentId"))
    if not agent_id:
        raise ResearchOrganizationError("Tool policy action requires agentId.")
    allowed_tools = _normalize_allowed_tools(action.get("allowedTools") or (action.get("toolPolicy") or {}).get("allowedTools") or [])
    if not allowed_tools:
        raise ResearchOrganizationError("Tool policy action requires explicit allowedTools.")
    tool_policy = action.get("toolPolicy") if isinstance(action.get("toolPolicy"), dict) else {}
    agent = update_agent_instance(
        agent_id,
        tool_policy={
            **tool_policy,
            **_explicit_tool_policy_payload(allowed_tools, preferred_tools=list(tool_policy.get("preferredTools") or [])),
        },
    )
    graph["agents"] = _upsert_agent_node(
        graph.get("agents") or [],
        agent,
        role=str(((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("researchOrgRole") or ""),
        employee_rank=str(((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("employeeRank") or "member"),
        x=0,
        y=0,
        protected=bool(((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("protected")),
        zone_id="",
    )
    return {"_graph": graph, "actionType": action.get("actionType") or "", "status": "applied", "agentId": agent_id}


def _apply_edge_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    from_agent_id = _clean_id(action.get("fromAgentId") or action.get("sourceAgentId"))
    to_agent_id = _clean_id(action.get("toAgentId") or action.get("targetAgentId"))
    if not from_agent_id or not to_agent_id:
        raise ResearchOrganizationError("Communication edge action requires fromAgentId and toAgentId.")
    edge = _edge_to_api(
        {
            "edgeId": action.get("edgeId") or action.get("id"),
            "fromAgentId": from_agent_id,
            "toAgentId": to_agent_id,
            "label": action.get("label") or "",
            "communicationPolicy": action.get("communicationPolicy") if isinstance(action.get("communicationPolicy"), dict) else {},
            "status": action.get("status") or "active",
        }
    )
    graph["edges"] = _upsert_edge(graph.get("edges") or [], edge)
    return {
        "_graph": graph,
        "actionType": action.get("actionType") or "",
        "status": "applied",
        "edgeId": edge["edgeId"],
    }


def _apply_delete_edge_action(graph: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    edge_id = _clean_id(action.get("edgeId") or action.get("id"))
    if not edge_id:
        raise ResearchOrganizationError("Delete edge action requires edgeId.")
    graph["edges"] = [
        edge for edge in graph.get("edges") or []
        if _clean_id(edge.get("edgeId") or edge.get("id")) != edge_id
    ]
    return {"_graph": graph, "actionType": "delete_edge", "status": "applied", "edgeId": edge_id}


def _append_audit_event(graph: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    payload.setdefault("auditEventId", _new_org_id("roaudit"))
    payload.setdefault("createdAt", utc_now_iso())
    graph["auditEvents"] = _limit_tail([*(graph.get("auditEvents") or []), payload], MAX_AUDIT_EVENTS)
    return graph


def _audit_from_delivery(message: dict[str, Any], delivery: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventType": "message_delivered" if delivery.get("allowed") else "message_blocked",
        "messageId": message.get("messageId") or "",
        "messageType": message.get("messageType") or "",
        "sourceType": message.get("sourceType") or "",
        "sourceAgentId": message.get("sourceAgentId") or "",
        "targetAgentId": delivery.get("targetAgentId") or "",
        "allowed": bool(delivery.get("allowed")),
        "reason": delivery.get("reason") or "",
        "edgeId": delivery.get("edgeId") or "",
        "inboxMessageId": delivery.get("inboxMessageId") or "",
        "wakeRequested": bool(delivery.get("wakeRequested")),
        "wakeStatus": delivery.get("wakeStatus") or "",
        "summary": message.get("summary") or "",
    }


def _find_pending_inbox_message(agent_id: str, message_id: str) -> dict[str, Any] | None:
    for item in list_agent_inbox_messages_for_agent(agent_id, status="pending", limit=200):
        if _clean_id(item.get("messageId") or item.get("eventId")) == message_id:
            return item
    return None


def _find_org_agent_node(graph: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    return next((_agent_node_to_api(node) for node in graph.get("agents") or [] if _clean_id(node.get("agentId")) == agent_id), None)


def _find_org_agent_by_role(graph: dict[str, Any], role: str) -> dict[str, Any] | None:
    return next((node for node in graph.get("agents") or [] if str(node.get("role") or "").strip() == role), None)


def _find_communication_edge(graph: dict[str, Any], source_agent_id: str, target_agent_id: str) -> dict[str, Any] | None:
    for edge in graph.get("edges") or []:
        normalized = _edge_to_api(edge)
        if normalized["fromAgentId"] == source_agent_id and normalized["toAgentId"] == target_agent_id and normalized["status"] == "active":
            return normalized
    return None


def _format_research_org_context_member_lines(member: dict[str, Any], *, self_agent_id: str) -> list[str]:
    agent_id = _clean_id(member.get("agentId"))
    agent = member.get("agent") if isinstance(member.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    code = _clean_id(member.get("agentCode") or agent.get("agentCode"))
    name = _clean_id(member.get("displayName") or agent.get("displayName"))
    role = _clean_id(member.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole"))
    rank = _clean_id(member.get("employeeRank") or metadata.get("employeeRank"))
    functional_name = _clean_id(metadata.get("functionalDisplayName"))
    suffix = " (you)" if agent_id == self_agent_id else ""
    first_line = f"- {code or agent_id} · {name}{suffix}: agentId={agent_id} role={role or '-'} rank={rank or '-'}"
    responsibilities = [
        trim_lines(str(item or ""), max_lines=1)
        for item in list(metadata.get("responsibilities") or [])[:3]
        if str(item or "").strip()
    ]
    lines = [first_line]
    if functional_name:
        lines.append(f"  function: {functional_name}")
    if responsibilities:
        lines.append(f"  responsibilities: {'; '.join(responsibilities)}")
    return lines


def _format_organization_capability_roster(members: list[dict[str, Any]], *, self_agent_id: str) -> list[str]:
    lines = ["Organization Capability Roster:"]
    for member in members:
        agent_id = _clean_id(member.get("agentId"))
        agent = member.get("agent") if isinstance(member.get("agent"), dict) else {}
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = _clean_id(member.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole"))
        boundary = _role_governance_boundary(role)
        code = _clean_id(member.get("agentCode") or agent.get("agentCode")) or agent_id
        name = _clean_id(member.get("displayName") or agent.get("displayName"))
        own = " (you)" if agent_id == self_agent_id else ""
        proposal_actions = ", ".join(boundary.get("proposal_actions") or [])
        allowed_tools = ", ".join(
            _normalize_allowed_tools(
                (member.get("toolPolicy") if isinstance(member.get("toolPolicy"), dict) else {}).get("allowedTools")
                or (agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}).get("allowedTools")
                or []
            )[:8]
        ) or "none"
        lines.append(
            f"- {code} · {name}{own}: role={role or 'research_specialist'} "
            f"authority={boundary['authority']} proposalActions={proposal_actions} visibleTools={allowed_tools}"
        )
        lines.append(f"  boundary: {boundary['must_not']}")
    return lines


def _format_team_onboarding_context(member: dict[str, Any]) -> list[str]:
    agent_id = _clean_id(member.get("agentId"))
    if not agent_id:
        return []
    agent = member.get("agent") if isinstance(member.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role_contract = metadata.get("roleContract") if isinstance(metadata.get("roleContract"), dict) else {}
    role = _clean_id(member.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole"))
    boundary = _role_governance_boundary(role)
    lines = [
        "Team Onboarding Context:",
        f"- Your teamId: {role_contract.get('teamId') or 'research-team'}",
        f"- Your role: {role_contract.get('role') or role or 'research_specialist'}",
        f"- Your reportTo: {role_contract.get('reportTo') or 'CEO'}",
        "- Before first execution or after role changes, self-check: identity, responsibility boundary, visible tools, memory scope, communication targets, and escalation path.",
        f"- If blocked: report the gap instead of inventing tools or changing your own permissions. Escalation path: {role_contract.get('escalationPath') or 'CEO -> Organization Advisor -> Capability Steward -> User gate'}.",
        f"- You may treat other members' roster entries as their responsibilities, not as tools you can call. Your own boundary: {boundary['must_not']}",
    ]
    responsibilities = [
        trim_lines(str(item or ""), max_lines=1)
        for item in list(role_contract.get("responsibilities") or metadata.get("responsibilities") or [])[:5]
        if str(item or "").strip()
    ]
    if responsibilities:
        lines.append(f"- Your responsibilities: {'; '.join(responsibilities)}")
    forbidden = [
        trim_lines(str(item or ""), max_lines=1)
        for item in list(role_contract.get("forbidden") or [])[:5]
        if str(item or "").strip()
    ]
    if forbidden:
        lines.append(f"- Forbidden without approval: {'; '.join(forbidden)}")
    return lines


def _role_governance_boundary(role: str) -> dict[str, Any]:
    normalized = _clean_id(role) or "research_specialist"
    if normalized in ROLE_GOVERNANCE_BOUNDARIES:
        return ROLE_GOVERNANCE_BOUNDARIES[normalized]
    if normalized.startswith("research_") and normalized != "research_ceo":
        return ROLE_GOVERNANCE_BOUNDARIES["research_specialist"]
    return ROLE_GOVERNANCE_BOUNDARIES["research_specialist"]


def _format_research_org_context_edge_line(edge: dict[str, Any], *, target: dict[str, Any], direction: str) -> str:
    agent = target.get("agent") if isinstance(target.get("agent"), dict) else {}
    code = _clean_id(target.get("agentCode") or agent.get("agentCode"))
    name = _clean_id(target.get("displayName") or agent.get("displayName"))
    agent_id = _clean_id(target.get("agentId") or agent.get("agentId"))
    policy = edge.get("communicationPolicy") if isinstance(edge.get("communicationPolicy"), dict) else {}
    message_types = ", ".join(
        _clean_id(item)
        for item in list(policy.get("allowedMessageTypes") or [])
        if _clean_id(item)
    ) or "notice/request/report"
    intents = ", ".join(
        _clean_id(item)
        for item in list(policy.get("allowedIntents") or [])[:6]
        if _clean_id(item)
    ) or "any"
    wake = _clean_id(policy.get("wakeStrategy") or "conditional") or "conditional"
    label = trim_lines(str(edge.get("label") or ""), max_lines=1)
    prefix = "to" if direction == "to" else "from"
    return (
        f"- {prefix} {code or agent_id} · {name}: agentId={agent_id} "
        f"edgeId={edge.get('edgeId') or ''} allowedTypes={message_types} "
        f"allowedIntents={intents} wake={wake}"
        + (f" label={label}" if label else "")
    )


def _rank_weight(node: dict[str, Any]) -> int:
    rank = str(node.get("employeeRank") or "").strip()
    return RANK_WEIGHTS.get(rank, RANK_WEIGHTS["member"])


def _normalize_message_type(value: Any) -> str:
    normalized = str(value or "notice").strip().lower()
    return normalized if normalized in MESSAGE_TYPES else "notice"


def _normalize_delivery_mode(value: Any) -> str:
    normalized = str(value or "private").strip().lower()
    return normalized if normalized in DELIVERY_MODES else "private"


def _normalize_allowed_tools(values: Any) -> list[str]:
    items = [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]
    return list(dict.fromkeys(items))


def _normalize_contract_lines(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_items = [values]
    else:
        raw_items = list(values or [])
    return [
        trim_lines(str(item or ""), max_lines=1)
        for item in raw_items
        if str(item or "").strip()
    ][:12]


def _explicit_tool_policy_payload(allowed_tools: list[str], *, preferred_tools: list[str] | None = None) -> dict[str, Any]:
    return {
        "allowedTools": _normalize_allowed_tools(allowed_tools),
        "preferredTools": _normalize_allowed_tools(preferred_tools or []),
        "blockedTools": [],
        "readScopes": ["private", "shared"],
        "writeScopes": ["private"],
        "networkAccess": "controlled",
        "mutationAccess": "controlled",
    }


def _default_proposal_title(actions: list[dict[str, Any]]) -> str:
    first = actions[0] if actions else {}
    action_type = str(first.get("actionType") or "organization_change").strip()
    return f"组织调整提案: {action_type}"


def _agent_field(agent_id: str, field: str) -> str:
    agent = get_agent(agent_id, include_archived=True) if agent_id else None
    return str((agent or {}).get(field) or "").strip()


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _new_org_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{stamp}"


def _limit_tail(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return items[-max(1, int(limit or 1)) :]


def _record_org_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any],
    level: str = "info",
) -> None:
    try:
        record_research_scene_event(
            event_code,
            phase="organization",
            level=level,
            outcome=outcome,
            message=event_code,
            fields=fields,
        )
    except Exception:
        return
