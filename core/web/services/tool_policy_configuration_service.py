"""Versioned Agent ToolPolicy configuration, validation, and explain projections."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from core.authorization.tool_authorization_service import resolve_enforced_authorization
from core.authorization.tool_policy_models import ToolDenyCode
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


def _existing_agents(snapshot):
    state = snapshot.read_json(snapshot.path("agents", "agents.json"), strict=True)
    rows = state.get("agents")
    if (not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows)
            or any(not isinstance(row.get("agentId"), str) or not row["agentId"] for row in rows)
            or any(key in row and not isinstance(row[key], dict) for row in rows for key in ("toolPolicy", "metadata"))
            or len({row["agentId"] for row in rows}) != len(rows)):
        raise ToolPolicyConfigurationError("Existing Agent authority is unavailable")
    return state, rows


def _configuration_agent(agent_id: str, *, declared_policy: bool = False, existing_snapshot=None) -> dict[str, Any]:
    if existing_snapshot is not None:
        state, rows = _existing_agents(existing_snapshot)
        agent = next((deepcopy(row) for row in rows if row["agentId"] == agent_id), None)
    else:
        agent = agent_directory_service.get_agent(agent_id)
    if not agent:
        raise ToolPolicyConfigurationNotFoundError(f"Agent not found: {agent_id}")
    if declared_policy:
        # API Agent projections deliberately hide delegation-gated tools. An
        # editor must preserve the persisted declaration rather than saving
        # that effective runtime subset back as the owner's configuration.
        state = state if existing_snapshot is not None else agent_directory_service.load_state()
        raw = agent_directory_service._find_agent(state, agent_id)
        if raw is None:
            raise ToolPolicyConfigurationNotFoundError(f"Agent not found: {agent_id}")
        policy_id = str(raw.get("toolPolicyId") or agent_directory_service.DEFAULT_TOOL_POLICY_ID)
        source = raw.get("toolPolicy")
        if not isinstance(source, dict):
            source = agent_directory_service._tool_policies(state).get(policy_id)
        if not isinstance(source, dict):
            source = agent_directory_service.default_tool_policy(policy_id)
        agent = {**agent, "toolPolicy": deepcopy(source), "toolPolicyId": policy_id,
                 "metadata": deepcopy(raw.get("metadata") or {})}
    return agent


def get_tool_policy_configuration(agent_id: str, *, declared_policy: bool = False, existing_snapshot=None) -> dict[str, Any]:
    agent = _configuration_agent(agent_id, declared_policy=declared_policy, existing_snapshot=existing_snapshot)
    policy = agent_directory_service.normalize_tool_policy(
        agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {},
        str(agent.get("toolPolicyId") or ""),
    )
    return _configuration_payload(agent, policy, proposed_policy=policy, declared_policy=declared_policy,
                                  existing_snapshot=existing_snapshot)


def validate_tool_policy_configuration(agent_id: str, policy: dict[str, Any], *, declared_policy: bool = False,
                                      existing_snapshot=None) -> dict[str, Any]:
    agent = _configuration_agent(agent_id, declared_policy=declared_policy, existing_snapshot=existing_snapshot)
    current_policy = agent_directory_service.normalize_tool_policy(
        agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {},
        str(agent.get("toolPolicyId") or ""),
    )
    proposed = agent_directory_service.normalize_tool_policy(
        {**current_policy, **dict(policy or {})},
        str(current_policy.get("policyId") or agent.get("toolPolicyId") or ""),
    )
    proposed["policyVersion"] = int(current_policy.get("policyVersion") or 1) + 1
    return _configuration_payload(agent, current_policy, proposed_policy=proposed, declared_policy=declared_policy,
                                  existing_snapshot=existing_snapshot)


def update_tool_policy_configuration(
    agent_id: str,
    *,
    policy: dict[str, Any],
    expected_agent_updated_at: str,
    expected_policy_fingerprint: str,
    confirmed: bool,
    expected_registry_version: str | None = None,
    expected_registry_fingerprint: str | None = None,
    declared_policy: bool = False,
    existing_snapshot=None,
) -> dict[str, Any]:
    with agent_directory_service._STATE_LOCK if declared_policy else nullcontext():
        preview = validate_tool_policy_configuration(agent_id, policy, declared_policy=declared_policy,
                                                     existing_snapshot=existing_snapshot)
        if (expected_registry_version is not None and preview["registryVersion"] != expected_registry_version
                or expected_registry_fingerprint is not None and preview["registryFingerprint"] != expected_registry_fingerprint):
            raise ToolPolicyConfigurationConflictError("Tool Registry changed after this editor was opened. Refresh and retry.")
        if not preview["validation"]["valid"]:
            raise ToolPolicyConfigurationError("; ".join(preview["validation"]["errors"]))
        if preview["confirmation"]["required"] and not confirmed:
            raise ToolPolicyConfigurationConfirmationRequired(preview["confirmation"]["summary"])
        native_fingerprint = expected_policy_fingerprint
        if declared_policy:
            if preview["policyFingerprint"] != expected_policy_fingerprint:
                raise ToolPolicyConfigurationConflictError("Declared ToolPolicy changed. Refresh and retry.")
            # The existing directory mutator CAS is explicitly over its
            # effective projection. Translate only inside the same RLock after
            # checking the declared snapshot; never widen delegation rights.
            raw = agent_directory_service._find_agent(agent_directory_service.load_state(), agent_id)
            native_fingerprint = agent_directory_service.tool_policy_fingerprint(
                agent_directory_service._tool_policy_for_agent(raw))
        try:
            agent_directory_service.update_agent_instance(
                agent_id,
                tool_policy=preview["proposedPolicy"],
                expected_updated_at=expected_agent_updated_at,
                expected_tool_policy_fingerprint=native_fingerprint,
                confirm_shared_tool_policy=confirmed,
            )
        except agent_directory_service.AgentStateConflictError as exc:
            raise ToolPolicyConfigurationConflictError(str(exc)) from exc
        return get_tool_policy_configuration(agent_id, declared_policy=declared_policy, existing_snapshot=existing_snapshot)


def _configuration_payload(
    agent: dict[str, Any],
    current_policy: dict[str, Any],
    *,
    proposed_policy: dict[str, Any],
    declared_policy: bool = False,
    existing_snapshot=None,
) -> dict[str, Any]:
    registry = (tool_registry_service.get_tool_registry() if existing_snapshot is None
                else tool_registry_service.get_existing_tool_registry(existing_snapshot))
    registry_items = [item for item in list(registry.get("tools") or []) if isinstance(item, dict)]
    registry_by_name = {str(item.get("name") or "").strip(): item for item in registry_items if str(item.get("name") or "").strip()}
    configured_names = _ordered_unique(
        [
            *list(proposed_policy.get("allowedTools") or []),
            *list(proposed_policy.get("blockedTools") or []),
            *list(proposed_policy.get("preferredTools") or []),
            *list(proposed_policy.get("perToolRules") or {}),
            *list(proposed_policy.get("approvalOverrides") or {}),
        ]
    )
    unknown = [name for name in configured_names if name not in registry_by_name]
    available_names = [name for name, item in registry_by_name.items() if _tool_available(item)]
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
    preview_policy = _policy_with_known_tools(proposed_policy, registry_by_name)
    if declared_policy:
        preview_policy = agent_directory_service._effective_agent_tool_policy(
            preview_policy, (agent.get("metadata") or {}).get("delegationPolicy"))
    preview_decision = resolve_enforced_authorization(
        runtime={
            "agentId": str(agent.get("agentId") or "").strip(),
            "turnId": f"tool-policy-preview:{str(agent.get('agentId') or '').strip()}",
            "agent": agent,
            "toolPolicy": preview_policy,
        },
        registry_payload=registry,
    ).decision
    unavailable = [name for name in proposed_policy.get("allowedTools") or [] if name in registry_by_name and name not in available_names]
    approval_required = [
        name
        for name, approval, _risk in preview_decision.approval_requirements
        if approval != "never"
    ]
    blocked_tools = [
        name
        for name, reason in preview_decision.denied
        if reason.code == ToolDenyCode.AGENT_BLOCKED
    ]
    policy_id = str(current_policy.get("policyId") or agent.get("toolPolicyId") or "").strip()
    agents = (agent_directory_service.list_agents(include_archived=False, detail="full") if existing_snapshot is None
              else [row for row in _existing_agents(existing_snapshot)[1] if row.get("status") == "active"])
    affected_agents = [
        _agent_identity(item)
        for item in agents
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
        "registryFingerprint": str(registry.get("registryFingerprint") or ""),
        "currentPolicy": current_policy,
        "proposedPolicy": proposed_policy,
        "validation": {"valid": not errors, "errors": errors, "warnings": warnings},
        "impact": {
            "sharedPolicy": len(affected_agents) > 1,
            "affectedAgentCount": len(affected_agents),
            "affectedAgents": affected_agents,
        },
        "preview": {
            "visibleTools": list(preview_decision.visible_tools),
            "executableTools": list(preview_decision.executable_tools),
            "preferredTools": list(preview_decision.preferred_tools),
            "blockedTools": blocked_tools,
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
    return (
        bool(item.get("enabled", True))
        and bool(item.get("runtimeActive", True))
        and bool(item.get("llmVisible", True))
        and item.get("status") != "invalid"
        and dependency.get("available", True) is not False
    )


def _policy_with_known_tools(policy: dict[str, Any], registry_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    known_names = set(registry_by_name)
    effective_allowed = set(policy.get("allowedTools") or []) - set(policy.get("blockedTools") or [])
    return {
        **policy,
        "allowedTools": [name for name in policy.get("allowedTools") or [] if name in known_names],
        "blockedTools": [name for name in policy.get("blockedTools") or [] if name in known_names],
        # Invalid proposals must return their validation errors rather than
        # fail in the strict runtime evaluator. This changes only its preview;
        # the proposed policy and write admission retain the original errors.
        "preferredTools": [name for name in policy.get("preferredTools") or []
                           if name in known_names and name in effective_allowed],
    }


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
