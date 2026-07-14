"""Versioned Agent ToolPolicy configuration, validation, and explain projections."""

from __future__ import annotations

from typing import Any

from core.web.services import agent_directory_service, tool_registry_service


class ToolPolicyConfigurationError(ValueError):
    """Base error for ToolPolicy configuration operations."""


class ToolPolicyConfigurationNotFoundError(ToolPolicyConfigurationError):
    """Raised when an Agent cannot be resolved."""


class ToolPolicyConfigurationConflictError(ToolPolicyConfigurationError):
    """Raised when an optimistic concurrency condition is stale."""


class ToolPolicyConfigurationConfirmationRequired(ToolPolicyConfigurationError):
    """Raised when a shared or high-risk change lacks explicit confirmation."""


def list_tool_policy_configurations() -> dict[str, Any]:
    agents = agent_directory_service.list_agents(include_archived=False, detail="full")
    grouped: dict[str, dict[str, Any]] = {}
    for agent in agents:
        policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}
        policy_id = str(policy.get("policyId") or agent.get("toolPolicyId") or "").strip()
        if not policy_id:
            continue
        item = grouped.setdefault(
            policy_id,
            {
                "policyId": policy_id,
                "policyVersion": int(policy.get("policyVersion") or 1),
                "policyFingerprint": agent_directory_service.tool_policy_fingerprint(policy),
                "agentCount": 0,
                "agents": [],
            },
        )
        item["agentCount"] += 1
        item["agents"].append(_agent_identity(agent))
    return {"schemaVersion": 1, "items": sorted(grouped.values(), key=lambda item: item["policyId"])}


def get_tool_policy_configuration(agent_id: str) -> dict[str, Any]:
    agent = agent_directory_service.get_agent(agent_id)
    if not agent:
        raise ToolPolicyConfigurationNotFoundError(f"Agent not found: {agent_id}")
    policy = agent_directory_service.normalize_tool_policy(
        agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {},
        str(agent.get("toolPolicyId") or ""),
    )
    return _configuration_payload(agent, policy, proposed_policy=policy)


def validate_tool_policy_configuration(agent_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    agent = agent_directory_service.get_agent(agent_id)
    if not agent:
        raise ToolPolicyConfigurationNotFoundError(f"Agent not found: {agent_id}")
    current_policy = agent_directory_service.normalize_tool_policy(
        agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {},
        str(agent.get("toolPolicyId") or ""),
    )
    proposed = agent_directory_service.normalize_tool_policy(
        {**current_policy, **dict(policy or {})},
        str(current_policy.get("policyId") or agent.get("toolPolicyId") or ""),
    )
    proposed["policyVersion"] = int(current_policy.get("policyVersion") or 1) + 1
    return _configuration_payload(agent, current_policy, proposed_policy=proposed)


def update_tool_policy_configuration(
    agent_id: str,
    *,
    policy: dict[str, Any],
    expected_agent_updated_at: str,
    expected_policy_fingerprint: str,
    confirmed: bool,
) -> dict[str, Any]:
    preview = validate_tool_policy_configuration(agent_id, policy)
    if not preview["validation"]["valid"]:
        raise ToolPolicyConfigurationError("; ".join(preview["validation"]["errors"]))
    if preview["confirmation"]["required"] and not confirmed:
        raise ToolPolicyConfigurationConfirmationRequired(preview["confirmation"]["summary"])
    try:
        agent_directory_service.update_agent_instance(
            agent_id,
            tool_policy=preview["proposedPolicy"],
            expected_updated_at=expected_agent_updated_at,
            expected_tool_policy_fingerprint=expected_policy_fingerprint,
            confirm_shared_tool_policy=confirmed,
        )
    except agent_directory_service.AgentStateConflictError as exc:
        raise ToolPolicyConfigurationConflictError(str(exc)) from exc
    return get_tool_policy_configuration(agent_id)


def _configuration_payload(
    agent: dict[str, Any],
    current_policy: dict[str, Any],
    *,
    proposed_policy: dict[str, Any],
) -> dict[str, Any]:
    registry = tool_registry_service.get_tool_registry()
    registry_items = [item for item in list(registry.get("tools") or []) if isinstance(item, dict)]
    registry_by_name = {str(item.get("name") or "").strip(): item for item in registry_items if str(item.get("name") or "").strip()}
    configured_names = _ordered_unique(
        [
            *list(proposed_policy.get("allowedTools") or []),
            *list(proposed_policy.get("blockedTools") or []),
            *list(proposed_policy.get("preferredTools") or []),
        ]
    )
    unknown = [name for name in configured_names if name not in registry_by_name]
    available_names = [name for name, item in registry_by_name.items() if _tool_available(item)]
    visibility = agent_directory_service.compute_effective_tool_visibility(available_names, policy=proposed_policy)
    allowed = set(proposed_policy.get("allowedTools") or [])
    blocked = set(proposed_policy.get("blockedTools") or [])
    preferred = set(proposed_policy.get("preferredTools") or [])
    overlap = sorted(allowed & blocked)
    invalid_preferred = sorted(preferred - allowed)
    errors: list[str] = []
    if unknown:
        errors.append("Unknown tools: " + ", ".join(unknown[:12]))
    if overlap:
        errors.append("Tools cannot be both allowed and blocked: " + ", ".join(overlap[:12]))
    if invalid_preferred:
        errors.append("Preferred tools must also be allowed: " + ", ".join(invalid_preferred[:12]))
    unavailable = [name for name in proposed_policy.get("allowedTools") or [] if name in registry_by_name and name not in available_names]
    approval_required = [
        name
        for name in visibility.visible_tools
        if _tool_requires_approval(registry_by_name.get(name) or {}, proposed_policy)
    ]
    executable = [name for name in visibility.visible_tools if name not in set(approval_required)]
    policy_id = str(current_policy.get("policyId") or agent.get("toolPolicyId") or "").strip()
    affected_agents = [
        _agent_identity(item)
        for item in agent_directory_service.list_agents(include_archived=False, detail="full")
        if str(item.get("toolPolicyId") or "").strip() == policy_id
    ]
    newly_allowed = set(proposed_policy.get("allowedTools") or []) - set(current_policy.get("allowedTools") or [])
    high_risk_tools = sorted(name for name in newly_allowed if _tool_high_risk(registry_by_name.get(name) or {}))
    confirmation_reasons: list[str] = []
    if len(affected_agents) > 1:
        confirmation_reasons.append(f"shared_policy:{len(affected_agents)}")
    if high_risk_tools:
        confirmation_reasons.append("high_risk_tools")
    if "shared" in set(proposed_policy.get("writeScopes") or []) and "shared" not in set(current_policy.get("writeScopes") or []):
        confirmation_reasons.append("shared_write_scope")
    if str(proposed_policy.get("mutationAccess") or "") == "unrestricted" and str(current_policy.get("mutationAccess") or "") != "unrestricted":
        confirmation_reasons.append("unrestricted_mutation")
    if str(proposed_policy.get("networkAccess") or "") == "unrestricted" and str(current_policy.get("networkAccess") or "") != "unrestricted":
        confirmation_reasons.append("unrestricted_network")
    warnings = ["Configured tools are currently unavailable: " + ", ".join(unavailable[:12])] if unavailable else []
    return {
        "schemaVersion": 1,
        "agent": _agent_identity(agent) | {"updatedAt": str(agent.get("updatedAt") or "")},
        "policyId": policy_id,
        "policyVersion": int(current_policy.get("policyVersion") or 1),
        "policyFingerprint": agent_directory_service.tool_policy_fingerprint(current_policy),
        "proposedPolicyFingerprint": agent_directory_service.tool_policy_fingerprint(proposed_policy),
        "registryVersion": str(registry.get("registryVersion") or ""),
        "currentPolicy": current_policy,
        "proposedPolicy": proposed_policy,
        "validation": {"valid": not errors, "errors": errors, "warnings": warnings},
        "impact": {
            "sharedPolicy": len(affected_agents) > 1,
            "affectedAgentCount": len(affected_agents),
            "affectedAgents": affected_agents,
        },
        "preview": {
            "visibleTools": list(visibility.visible_tools),
            "executableTools": executable,
            "preferredTools": list(visibility.preferred_tools),
            "blockedTools": list(visibility.blocked_tools),
            "unavailableTools": unavailable,
            "unknownTools": unknown,
            "approvalRequiredTools": approval_required,
        },
        "confirmation": {
            "required": bool(confirmation_reasons),
            "reasons": confirmation_reasons,
            "highRiskTools": high_risk_tools,
            "summary": _confirmation_summary(confirmation_reasons, affected_agents, high_risk_tools),
        },
    }


def _tool_available(item: dict[str, Any]) -> bool:
    dependency = item.get("dependencyStatus") if isinstance(item.get("dependencyStatus"), dict) else {}
    return bool(item.get("enabled", True)) and bool(item.get("runtimeActive", True)) and item.get("status") != "invalid" and dependency.get("available", True) is not False


def _tool_requires_approval(item: dict[str, Any], policy: dict[str, Any]) -> bool:
    rules = policy.get("perToolRules") if isinstance(policy.get("perToolRules"), dict) else {}
    rule = rules.get(str(item.get("name") or "")) if isinstance(rules.get(str(item.get("name") or "")), dict) else {}
    return bool(rule.get("requiresApproval"))


def _tool_high_risk(item: dict[str, Any]) -> bool:
    permission = item.get("permissionPolicy") if isinstance(item.get("permissionPolicy"), dict) else {}
    descriptor = item.get("descriptor") if isinstance(item.get("descriptor"), dict) else {}
    return bool(permission.get("requiresExplicitAllow")) or str(descriptor.get("riskLevel") or item.get("riskLevel") or "").lower() in {"high", "critical"}


def _agent_identity(agent: dict[str, Any]) -> dict[str, str]:
    return {
        "agentId": str(agent.get("agentId") or ""),
        "agentCode": str(agent.get("agentCode") or ""),
        "displayName": str(agent.get("displayName") or ""),
    }


def _ordered_unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _confirmation_summary(reasons: list[str], agents: list[dict[str, str]], tools: list[str]) -> str:
    details: list[str] = []
    if any(reason.startswith("shared_policy:") for reason in reasons):
        details.append(f"This shared policy affects {len(agents)} Agents")
    if tools:
        details.append("High-risk tools: " + ", ".join(tools[:8]))
    if "shared_write_scope" in reasons:
        details.append("Shared workspace write access will be enabled")
    if "unrestricted_mutation" in reasons:
        details.append("Unrestricted mutation access will be enabled")
    if "unrestricted_network" in reasons:
        details.append("Unrestricted network access will be enabled")
    return "; ".join(details) or "No additional confirmation is required."
