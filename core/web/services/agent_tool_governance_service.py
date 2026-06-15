"""Controlled Agent tool-permission governance.

This module lets advisor-style Agents propose or apply bounded ToolPolicy
changes without becoming a second source of truth. Applied changes always end
up in the target AgentDirectory ToolPolicy; request records stay in the target
Agent's private event log for audit and UI review.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.logging import debug as _debug_logger

from . import agent_directory_service
from .runtime_scene_service import record_runtime_scene_event
from .tool_catalog import HIGH_PERMISSION_TIER, LOW_PERMISSION_TIER, permission_tier_for_tool, risk_tags_for_tool


TOOL_GOVERNANCE_EVENT_FILE = "tool_governance_requests.jsonl"
LOW_RISK_GRANT_TOOLS = {
    "grep_search_tool",
    "glob_tool",
    "read_file_tool",
    "get_current_goal_tool",
    "get_core_context_tool",
    "get_git_status_summary_tool",
    "get_recent_changes_tool",
    "get_entity_history_tool",
    "history_search_tool",
    "history_fetch_tool",
    "history_timeline_tool",
    "history_checkpoint_tool",
    "explain_current_worktree_tool",
    "task_list_tool",
    "get_evolution_fitness_tool",
    "get_mental_state_tool",
}
HIGH_RISK_GRANT_TOOLS = {
    "agent_message_tool",
    "agent_tool_permission_request_tool",
    "apply_diff_edit_tool",
    "apply_patch_tool",
    "clean_workspace_debris_tool",
    "cli_tool",
    "close_evolution_transaction_tool",
    "commit_compressed_memory_tool",
    "compress_context_tool",
    "image2_generate_tool",
    "knowledge_proposal_tool",
    "knowledge_query_tool",
    "open_evolution_transaction_tool",
    "plan_update_tool",
    "record_evolution_tool",
    "record_learning_tool",
    "research_knowledge_query_tool",
    "search_error_archive_tool",
    "search_memory_tool",
    "task_create_tool",
    "task_start_tool",
    "task_stop_tool",
    "task_update_tool",
    "trigger_self_restart_tool",
    "update_diagnosis_rules_tool",
    "update_self_model_tool",
    "web_fetch_tool",
    "web_search_tool",
    "write_file_tool",
}
GOVERNANCE_SYSTEM_ROLES = {"ceo", "organization_advisor", "capability_steward"}
REQUEST_STATUSES = {"pending_review", "applied", "rejected"}
GRANT_SCOPES = {"persistent", "session", "turn"}


class AgentToolGovernanceError(ValueError):
    """Raised when a tool-governance request is invalid."""


class AgentToolGovernanceNotFoundError(AgentToolGovernanceError):
    """Raised when a governance request does not exist."""


def submit_tool_governance_request(
    target_agent_id: str,
    *,
    proposed_by_agent_id: str = "",
    grant_tools: list[str] | None = None,
    revoke_tools: list[str] | None = None,
    block_tools: list[str] | None = None,
    unblock_tools: list[str] | None = None,
    reason: str = "",
    apply_mode: str = "auto",
    grant_scope: str = "persistent",
    source_session_id: str = "",
    source_turn_id: str = "",
) -> dict[str, Any]:
    """Create a controlled ToolPolicy change request.

    Low-risk requests from governance Agents may be applied immediately when
    apply_mode is auto. Higher-risk requests are persisted for user approval.
    """

    target_agent = _raw_agent(target_agent_id, include_archived=False)
    if not target_agent:
        raise agent_directory_service.AgentNotFoundError(f"Agent not found: {target_agent_id}")
    proposer = _resolve_optional_agent(proposed_by_agent_id)
    delta = _normalize_delta(
        grant_tools=grant_tools,
        revoke_tools=revoke_tools,
        block_tools=block_tools,
        unblock_tools=unblock_tools,
    )
    if not any(delta.values()):
        raise AgentToolGovernanceError("Tool governance request must include at least one tool change.")
    normalized_grant_scope = _normalize_grant_scope(grant_scope)
    _validate_grant_scope_delta(normalized_grant_scope, delta)

    authority = _actor_authority(proposer, target_agent)
    risk = _classify_delta(delta)
    normalized_apply_mode = str(apply_mode or "auto").strip().lower()
    auto_requested = normalized_apply_mode == "auto"
    requires_approval = (
        risk["requiresApproval"]
        or not authority["canApplyLowRisk"]
        or not auto_requested
    )
    status = "pending_review"
    applied_agent: dict[str, Any] | None = None
    resolved_at = ""
    resolved_by = ""
    if not requires_approval:
        if normalized_grant_scope == "persistent":
            applied_agent = _apply_tool_delta(str(target_agent["agentId"]), delta)
        status = "applied"
        resolved_at = utc_now_iso()
        resolved_by = _actor_label(proposer) or "agent_tool_governance"

    request = _request_payload(
        target_agent=applied_agent or target_agent,
        proposer=proposer,
        delta=delta,
        reason=reason,
        authority=authority,
        risk=risk,
        status=status,
        resolved_at=resolved_at,
        resolved_by=resolved_by,
        resolution_note="auto_applied_low_risk" if status == "applied" else "",
        grant_scope=normalized_grant_scope,
        source_session_id=source_session_id,
        source_turn_id=source_turn_id,
    )
    _append_request(applied_agent or target_agent, request)
    _record_tool_governance_event("agent_tool_governance.request_created", request)
    if status == "applied":
        _record_tool_governance_event("agent_tool_governance.request_applied", request, outcome="applied")
    return request


def list_tool_governance_requests(
    *,
    agent_id: str = "",
    status: str = "pending_review",
    limit: int = 50,
) -> list[dict[str, Any]]:
    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        agent = _raw_agent(normalized_agent_id, include_archived=True)
        agents = [agent] if agent else []
    else:
        agents = _raw_agents(include_archived=True)
    normalized_status = str(status or "").strip().lower()
    requests: list[dict[str, Any]] = []
    for agent in agents:
        if not agent:
            continue
        for item in _read_requests(agent):
            if normalized_status and str(item.get("status") or "").strip().lower() != normalized_status:
                continue
            requests.append(item)
    requests.sort(
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("requestId") or item.get("eventId") or ""),
        ),
        reverse=True,
    )
    return requests[: max(1, int(limit or 1))]


def resolve_tool_governance_request(
    target_agent_id: str,
    request_id: str,
    *,
    decision: str,
    resolved_by: str = "user",
    resolution_note: str = "",
) -> dict[str, Any]:
    target_agent = _raw_agent(target_agent_id, include_archived=True)
    if not target_agent:
        raise agent_directory_service.AgentNotFoundError(f"Agent not found: {target_agent_id}")
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise AgentToolGovernanceNotFoundError("Tool governance request id is required.")
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise AgentToolGovernanceError("Unsupported tool governance decision.")

    path = _request_path(target_agent)
    requests = _read_requests(target_agent)
    for item in requests:
        if str(item.get("requestId") or item.get("eventId") or "").strip() != normalized_request_id:
            continue
        current_status = str(item.get("status") or "pending_review").strip().lower()
        if current_status != "pending_review":
            return item
        if normalized_decision == "reject":
            item["status"] = "rejected"
            item["resolvedAt"] = utc_now_iso()
            item["resolvedBy"] = trim_lines(str(resolved_by or "user"), max_lines=1) or "user"
            item["resolutionNote"] = trim_lines(str(resolution_note or ""), max_lines=4)
            _write_requests(path, requests)
            _record_tool_governance_event("agent_tool_governance.request_rejected", item, outcome="rejected")
            return item

        delta = item.get("policyDelta") if isinstance(item.get("policyDelta"), dict) else {}
        normalized_delta = _normalize_delta_from_payload(delta)
        grant_scope = _normalize_grant_scope(str(item.get("grantScope") or "persistent"))
        item["status"] = "applied"
        item["resolvedAt"] = utc_now_iso()
        item["resolvedBy"] = trim_lines(str(resolved_by or "user"), max_lines=1) or "user"
        item["resolutionNote"] = trim_lines(str(resolution_note or "approved"), max_lines=4)
        if grant_scope == "persistent":
            applied_agent = _apply_tool_delta(str(target_agent.get("agentId") or ""), normalized_delta)
            item["appliedToolPolicyId"] = str(applied_agent.get("toolPolicyId") or "")
            item["after"] = _policy_snapshot(applied_agent.get("toolPolicy") if isinstance(applied_agent.get("toolPolicy"), dict) else {})
        else:
            policy = target_agent.get("toolPolicy") if isinstance(target_agent.get("toolPolicy"), dict) else {}
            item["appliedToolPolicyId"] = ""
            item["temporaryGrant"] = _temporary_grant_payload(
                delta=normalized_delta,
                grant_scope=grant_scope,
                source_session_id=str(item.get("sourceSessionId") or "").strip(),
                source_turn_id=str(item.get("sourceTurnId") or "").strip(),
                applied_at=str(item.get("resolvedAt") or "").strip(),
            )
            item["after"] = _policy_snapshot(_policy_with_temporary_delta(policy, normalized_delta))
        _write_requests(path, requests)
        _record_tool_governance_event("agent_tool_governance.request_applied", item, outcome="applied")
        return item
    raise AgentToolGovernanceNotFoundError(f"Tool governance request not found: {request_id}")


def temporary_granted_tools_for_agent(
    agent_id: str,
    *,
    session_id: str = "",
    turn_id: str = "",
) -> list[str]:
    """Return approved non-persistent grants visible to the current runtime scope."""

    agent = _raw_agent(agent_id, include_archived=True)
    if not agent:
        return []
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    result: list[str] = []
    seen: set[str] = set()
    for item in _read_requests(agent):
        if str(item.get("status") or "").strip().lower() != "applied":
            continue
        grant_scope = _normalize_grant_scope(str(item.get("grantScope") or "persistent"))
        if grant_scope == "persistent":
            continue
        if not _grant_scope_matches(item, grant_scope, session_id=normalized_session_id, turn_id=normalized_turn_id):
            continue
        grant_payload = item.get("temporaryGrant") if isinstance(item.get("temporaryGrant"), dict) else {}
        delta = _normalize_delta_from_payload(item.get("policyDelta") if isinstance(item.get("policyDelta"), dict) else {})
        tools = _unique_tools(list(grant_payload.get("grantTools") or []) or delta.get("grantTools") or [])
        for tool in tools:
            if tool in seen:
                continue
            result.append(tool)
            seen.add(tool)
    return result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_optional_agent(agent_id: str) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    agent = _raw_agent(normalized, include_archived=False)
    if not agent:
        raise agent_directory_service.AgentNotFoundError(f"Proposer Agent not found: {normalized}")
    return agent


def _raw_agent(agent_id: str, *, include_archived: bool) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    for agent in _raw_agents(include_archived=include_archived):
        if str(agent.get("agentId") or "").strip() == normalized:
            return dict(agent)
    return None


def _raw_agents(*, include_archived: bool) -> list[dict[str, Any]]:
    state = agent_directory_service.load_state()
    agents = []
    for item in state.get("agents") or []:
        if not isinstance(item, dict):
            continue
        if not include_archived and str(item.get("status") or "active").strip() == "archived":
            continue
        agents.append(dict(item))
    return agents


def _normalize_delta(
    *,
    grant_tools: list[str] | None = None,
    revoke_tools: list[str] | None = None,
    block_tools: list[str] | None = None,
    unblock_tools: list[str] | None = None,
) -> dict[str, list[str]]:
    return {
        "grantTools": _unique_tools(grant_tools),
        "revokeTools": _unique_tools(revoke_tools),
        "blockTools": _unique_tools(block_tools),
        "unblockTools": _unique_tools(unblock_tools),
    }


def _normalize_delta_from_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    return _normalize_delta(
        grant_tools=list(payload.get("grantTools") or []),
        revoke_tools=list(payload.get("revokeTools") or []),
        block_tools=list(payload.get("blockTools") or []),
        unblock_tools=list(payload.get("unblockTools") or []),
    )


def _normalize_grant_scope(value: str) -> str:
    normalized = str(value or "persistent").strip().lower()
    if not normalized:
        normalized = "persistent"
    if normalized not in GRANT_SCOPES:
        raise AgentToolGovernanceError("Unsupported tool governance grant scope.")
    return normalized


def _validate_grant_scope_delta(grant_scope: str, delta: dict[str, list[str]]) -> None:
    if grant_scope == "persistent":
        return
    if not delta.get("grantTools"):
        raise AgentToolGovernanceError("Temporary tool governance requests must grant at least one tool.")
    if delta.get("revokeTools") or delta.get("blockTools") or delta.get("unblockTools"):
        raise AgentToolGovernanceError("Temporary tool governance requests only support grantTools.")


def _unique_tools(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        tool = str(value or "").strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        result.append(tool)
    return result[:80]


def _actor_authority(proposer: dict[str, Any] | None, target_agent: dict[str, Any]) -> dict[str, Any]:
    if not proposer:
        return {
            "actorKind": "user_or_coordinator",
            "role": "user",
            "canApplyLowRisk": True,
            "reason": "direct_user_or_coordinator_request",
        }
    proposer_id = str(proposer.get("agentId") or "").strip()
    target_id = str(target_agent.get("agentId") or "").strip()
    metadata = proposer.get("metadata") if isinstance(proposer.get("metadata"), dict) else {}
    role = str(metadata.get("systemRole") or metadata.get("researchOrgRole") or proposer.get("roleKey") or "").strip()
    if proposer_id and proposer_id == target_id:
        return {
            "actorKind": "agent",
            "role": role,
            "canApplyLowRisk": False,
            "reason": "self_permission_change_requires_review",
        }
    return {
        "actorKind": "agent",
        "role": role,
        "canApplyLowRisk": role in GOVERNANCE_SYSTEM_ROLES,
        "reason": "governance_role" if role in GOVERNANCE_SYSTEM_ROLES else "request_only_agent",
    }


def _classify_delta(delta: dict[str, list[str]]) -> dict[str, Any]:
    grant_tools = set(delta.get("grantTools") or [])
    risk_tags: list[str] = []
    high_risk_tools = sorted(
        tool
        for tool in grant_tools
        if tool in HIGH_RISK_GRANT_TOOLS or permission_tier_for_tool(tool) == HIGH_PERMISSION_TIER
    )
    for tool in high_risk_tools:
        risk_tags.extend(risk_tags_for_tool(tool) or ["high_risk_tool"])
    unknown_grants = sorted(
        tool
        for tool in grant_tools
        if tool not in LOW_RISK_GRANT_TOOLS
        and tool not in HIGH_RISK_GRANT_TOOLS
        and permission_tier_for_tool(tool) != LOW_PERMISSION_TIER
        and tool not in high_risk_tools
    )
    if unknown_grants:
        risk_tags.append("unknown_tool")
    if high_risk_tools:
        risk_level = "high"
        requires_approval = True
        reason = "high_risk_tool_grant"
    elif unknown_grants:
        risk_level = "medium"
        requires_approval = True
        reason = "unknown_or_unclassified_tool_grant"
    else:
        risk_level = "low"
        requires_approval = False
        reason = "low_risk_or_restrictive_change"
    return {
        "riskLevel": risk_level,
        "riskTags": sorted(set(risk_tags)),
        "requiresApproval": requires_approval,
        "approvalReason": reason,
        "highRiskTools": high_risk_tools,
        "unknownGrantTools": unknown_grants,
    }


def _apply_tool_delta(agent_id: str, delta: dict[str, list[str]]) -> dict[str, Any]:
    policy = agent_directory_service.resolve_tool_policy_for_agent(agent_id)
    allowed = _ordered_set(policy.get("allowedTools") or [])
    blocked = _ordered_set(policy.get("blockedTools") or [])
    for tool in delta.get("grantTools") or []:
        allowed.append(tool)
        blocked = [item for item in blocked if item != tool]
    for tool in delta.get("revokeTools") or []:
        allowed = [item for item in allowed if item != tool]
    for tool in delta.get("blockTools") or []:
        blocked.append(tool)
        allowed = [item for item in allowed if item != tool]
    for tool in delta.get("unblockTools") or []:
        blocked = [item for item in blocked if item != tool]
    next_policy = {
        **policy,
        "allowedTools": _ordered_set(allowed),
        "blockedTools": _ordered_set(blocked),
    }
    return agent_directory_service.update_agent_instance(agent_id, tool_policy=next_policy)


def _request_payload(
    *,
    target_agent: dict[str, Any],
    proposer: dict[str, Any] | None,
    delta: dict[str, list[str]],
    reason: str,
    authority: dict[str, Any],
    risk: dict[str, Any],
    status: str,
    resolved_at: str = "",
    resolved_by: str = "",
    resolution_note: str = "",
    grant_scope: str = "persistent",
    source_session_id: str = "",
    source_turn_id: str = "",
) -> dict[str, Any]:
    now = utc_now_iso()
    request_id = _new_request_id()
    policy = target_agent.get("toolPolicy") if isinstance(target_agent.get("toolPolicy"), dict) else {}
    normalized_grant_scope = _normalize_grant_scope(grant_scope)
    temporary_grant = (
        _temporary_grant_payload(
            delta=delta,
            grant_scope=normalized_grant_scope,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            applied_at=resolved_at or now,
        )
        if status == "applied" and normalized_grant_scope != "persistent"
        else {}
    )
    after_policy = (
        _policy_with_temporary_delta(policy, delta)
        if status == "applied" and normalized_grant_scope != "persistent"
        else policy
    )
    return {
        "eventId": request_id,
        "requestId": request_id,
        "kind": "tool_governance_request",
        "status": status if status in REQUEST_STATUSES else "pending_review",
        "grantScope": normalized_grant_scope,
        "sourceSessionId": trim_lines(str(source_session_id or ""), max_lines=1),
        "sourceTurnId": trim_lines(str(source_turn_id or ""), max_lines=1),
        "targetAgentId": str(target_agent.get("agentId") or "").strip(),
        "targetAgentCode": str(target_agent.get("agentCode") or "").strip(),
        "targetAgentName": str(target_agent.get("displayName") or "").strip(),
        "proposedByAgentId": str((proposer or {}).get("agentId") or "").strip(),
        "proposedByAgentCode": str((proposer or {}).get("agentCode") or "").strip(),
        "proposedByAgentName": str((proposer or {}).get("displayName") or "").strip(),
        "policyDelta": delta,
        "reason": trim_lines(str(reason or ""), max_lines=4),
        "authority": authority,
        "riskLevel": str(risk.get("riskLevel") or "low"),
        "riskTags": list(risk.get("riskTags") or []),
        "requiresApproval": bool(risk.get("requiresApproval")) or status == "pending_review",
        "approvalReason": str(risk.get("approvalReason") or ""),
        "createdAt": now,
        "resolvedAt": resolved_at,
        "resolvedBy": resolved_by,
        "resolutionNote": resolution_note,
        "appliedToolPolicyId": str(target_agent.get("toolPolicyId") or "") if status == "applied" and normalized_grant_scope == "persistent" else "",
        "temporaryGrant": temporary_grant,
        "after": _policy_snapshot(after_policy) if status == "applied" else {},
    }


def _policy_snapshot(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "policyId": str(policy.get("policyId") or ""),
        "allowedTools": list(policy.get("allowedTools") or [])[:120],
        "blockedTools": list(policy.get("blockedTools") or [])[:120],
        "writeScopes": list(policy.get("writeScopes") or [])[:12],
    }


def _policy_with_temporary_delta(policy: dict[str, Any], delta: dict[str, list[str]]) -> dict[str, Any]:
    allowed = _ordered_set(policy.get("allowedTools") or [])
    blocked = set(_ordered_set(policy.get("blockedTools") or []))
    temporary_allowed: list[str] = []
    for tool in delta.get("grantTools") or []:
        if not tool or tool in blocked:
            continue
        if tool not in allowed:
            allowed.append(tool)
            temporary_allowed.append(tool)
    return {
        **policy,
        "allowedTools": _ordered_set(allowed),
        "temporaryAllowedTools": _ordered_set(list(policy.get("temporaryAllowedTools") or []) + temporary_allowed),
    }


def _temporary_grant_payload(
    *,
    delta: dict[str, list[str]],
    grant_scope: str,
    source_session_id: str,
    source_turn_id: str,
    applied_at: str,
) -> dict[str, Any]:
    return {
        "scope": grant_scope,
        "sessionId": trim_lines(str(source_session_id or ""), max_lines=1),
        "turnId": trim_lines(str(source_turn_id or ""), max_lines=1),
        "grantTools": _unique_tools(delta.get("grantTools") or []),
        "appliedAt": trim_lines(str(applied_at or utc_now_iso()), max_lines=1),
    }


def _grant_scope_matches(
    request: dict[str, Any],
    grant_scope: str,
    *,
    session_id: str,
    turn_id: str,
) -> bool:
    if grant_scope == "session":
        request_session_id = str(request.get("sourceSessionId") or "").strip()
        return bool(session_id and request_session_id and request_session_id == session_id)
    if grant_scope == "turn":
        request_session_id = str(request.get("sourceSessionId") or "").strip()
        request_turn_id = str(request.get("sourceTurnId") or "").strip()
        return bool(
            session_id
            and turn_id
            and request_session_id
            and request_turn_id
            and request_session_id == session_id
            and request_turn_id == turn_id
        )
    return False


def _ordered_set(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _append_request(agent: dict[str, Any], request: dict[str, Any]) -> None:
    path = _request_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n")
    agent_directory_service.record_agent_api_hydration_event_file_changed(path)


def _write_requests(path: Path, requests: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in list(requests or [])
        if isinstance(item, dict)
    ]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8", newline="\n")
    agent_directory_service.record_agent_api_hydration_event_file_changed(path)


def _read_requests(agent: dict[str, Any]) -> list[dict[str, Any]]:
    path = _request_path(agent)
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            _debug_logger.warning(
                f"[工具治理] 治理事件日志 JSON 解析失败: path={path}, {type(exc).__name__}: {exc}",
                tag="TOOL_GOVERNANCE",
            )
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _request_path(agent: dict[str, Any]) -> Path:
    root = Path(agent_directory_service.PROJECT_ROOT).resolve()
    if root.name.lower() == "workspace":
        root = root.parent
    workspace_path = str(agent.get("workspacePath") or "").strip()
    return (root / workspace_path / "events" / TOOL_GOVERNANCE_EVENT_FILE).resolve()


def _actor_label(agent: dict[str, Any] | None) -> str:
    if not agent:
        return ""
    code = str(agent.get("agentCode") or "").strip()
    name = str(agent.get("displayName") or "").strip()
    return " · ".join(item for item in (code, name) if item)


def _new_request_id() -> str:
    return f"toolgov-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"


def _record_tool_governance_event(event_code: str, request: dict[str, Any], *, outcome: str = "observed") -> None:
    try:
        delta = request.get("policyDelta") if isinstance(request.get("policyDelta"), dict) else {}
        record_runtime_scene_event(
            "agent_tool_governance",
            "tool_policy",
            event_code,
            message=event_code,
            level="warning" if request.get("status") == "pending_review" else "info",
            outcome=outcome,
            fields={
                "requestId": str(request.get("requestId") or "").strip(),
                "targetAgentId": str(request.get("targetAgentId") or "").strip(),
                "proposedByAgentId": str(request.get("proposedByAgentId") or "").strip(),
                "status": str(request.get("status") or "").strip(),
                "riskLevel": str(request.get("riskLevel") or "").strip(),
                "requiresApproval": bool(request.get("requiresApproval")),
                "grantCount": len(list(delta.get("grantTools") or [])),
                "revokeCount": len(list(delta.get("revokeTools") or [])),
                "blockCount": len(list(delta.get("blockTools") or [])),
                "unblockCount": len(list(delta.get("unblockTools") or [])),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"[工具治理] 记录 runtime scene 失败: event={event_code}, target={request.get('targetAgentId')}, {type(exc).__name__}: {exc}",
            tag="TOOL_GOVERNANCE",
        )
        return
