"""Pure, deterministic, deny-first Agent tool policy evaluation."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .tool_policy_models import (
    AgentIdentityMissingError,
    ApprovalMode,
    AuthorizationCacheKey,
    AuthorizationDecision,
    ToolDenyCode,
    ToolDenyReason,
    ToolPolicyInvalidError,
    ToolPolicyMissingError,
    ToolPolicyV2,
    ToolRegistryMissingError,
    TurnToolGrant,
    TurnToolGrantInvalidError,
    TurnToolGrantMissingError,
)


_TOKEN_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{1,127}$")
_TURN_SOURCES = {"session", "team", "research", "supervised", "self_evolution"}
_NETWORK_ACCESS = {"none", "restricted", "full"}
_MUTATION_ACCESS = {"none", "workspace", "controlled"}
_DELEGATION_ACCESS = {"none", "assigned_only"}
_APPROVAL_MODES = {"never", "on_request", "always"}
_NETWORK_ALIASES = {"inherit": "restricted", "controlled": "restricted", "restricted": "restricted"}
_MUTATION_ALIASES = {"inherit": "controlled", "restricted": "controlled", "controlled": "controlled"}
_APPROVAL_RANK = {"never": 0, "on_request": 1, "always": 2}


class ToolDescriptorLike(Protocol):
    name: str
    enabled: bool
    capabilities: Sequence[str]
    risk: str
    approval: str
    aliases: Sequence[str]


def normalize_legacy_tool_policy(
    raw_policy: Mapping[str, Any] | None,
    *,
    registered_tool_names: Iterable[str],
    policy_id: str = "",
    aliases: Mapping[str, str] | None = None,
) -> ToolPolicyV2:
    """Project a legacy policy into v2 without adding implicit tools."""

    if raw_policy is None:
        raise ToolPolicyMissingError("Tool policy is missing")
    if not isinstance(raw_policy, Mapping):
        raise ToolPolicyInvalidError("Tool policy must be an object")

    registered = frozenset(_normalized_names(registered_tool_names, field="registered tool"))
    if not registered:
        raise ToolRegistryMissingError("Tool Registry is empty")
    alias_map = {str(key).strip(): str(value).strip() for key, value in dict(aliases or {}).items() if str(key).strip()}
    resolved_policy_id = str(policy_id or raw_policy.get("policyId") or raw_policy.get("id") or "").strip()
    if not resolved_policy_id:
        raise ToolPolicyInvalidError("Tool policy id is required")

    if "allowedTools" in raw_policy:
        allowed = _policy_tool_names(raw_policy.get("allowedTools"), alias_map=alias_map, field="allowedTools")
    elif raw_policy.get("allowAllTools") is True:
        allowed = tuple(sorted(registered))
    else:
        raise ToolPolicyInvalidError("Tool policy must explicitly define allowedTools")

    blocked = _ordered_union(
        _policy_tool_names(raw_policy.get("blockedTools", ()), alias_map=alias_map, field="blockedTools"),
        _policy_tool_names(raw_policy.get("deniedTools", ()), alias_map=alias_map, field="deniedTools"),
    )
    preferred = _policy_tool_names(raw_policy.get("preferredTools", ()), alias_map=alias_map, field="preferredTools")
    unknown_allowed = sorted(set(allowed).difference(registered))
    unknown_preferred = sorted(set(preferred).difference(registered))
    if unknown_allowed:
        raise ToolPolicyInvalidError(f"Policy allows unknown tools: {', '.join(unknown_allowed)}")
    if unknown_preferred:
        raise ToolPolicyInvalidError(f"Policy prefers unknown tools: {', '.join(unknown_preferred)}")
    effective_allowed = set(allowed).difference(blocked)
    invalid_preferred = sorted(set(preferred).difference(effective_allowed))
    if invalid_preferred:
        raise ToolPolicyInvalidError(f"Preferred tools are not effectively allowed: {', '.join(invalid_preferred)}")

    try:
        policy_version = int(raw_policy.get("policyVersion") or raw_policy.get("version") or 1)
        max_calls = max(0, int(raw_policy.get("maxCallsPerTurn") or 0))
    except (TypeError, ValueError) as exc:
        raise ToolPolicyInvalidError("Policy version and maxCallsPerTurn must be integers") from exc
    if policy_version < 1:
        raise ToolPolicyInvalidError("Tool policy version must be positive")

    network_access = _normalize_network_access(raw_policy.get("networkAccess"))
    mutation_access = _normalize_mutation_access(raw_policy.get("mutationAccess"))
    delegation_access = str(raw_policy.get("delegationAccess") or "none").strip()
    if delegation_access not in _DELEGATION_ACCESS:
        raise ToolPolicyInvalidError(f"Unsupported delegationAccess: {delegation_access}")
    approval_overrides = _normalize_approval_overrides(
        raw_policy.get("approvalOverrides"),
        registered=registered,
        alias_map=alias_map,
    )
    return ToolPolicyV2(
        policy_id=resolved_policy_id,
        policy_version=policy_version,
        allowed_tools=allowed,
        blocked_tools=blocked,
        preferred_tools=preferred,
        read_scopes=_normalized_names(raw_policy.get("readScopes") or (), field="read scope"),
        write_scopes=_normalized_names(raw_policy.get("writeScopes") or (), field="write scope"),
        network_access=network_access,
        mutation_access=mutation_access,
        delegation_access=delegation_access,  # type: ignore[arg-type]
        max_calls_per_turn=max_calls,
        approval_overrides=approval_overrides,
    )


def evaluate_tool_policy(
    *,
    agent_id: str,
    policy: ToolPolicyV2 | None,
    grant: TurnToolGrant | None,
    descriptors: Sequence[ToolDescriptorLike] | None,
    registry_version: int,
    registry_fingerprint: str,
    available_tool_names: Iterable[str] | None = None,
    generated_at: str = "",
) -> AuthorizationDecision:
    """Resolve one immutable decision without I/O or fail-open fallback."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentIdentityMissingError("Agent identity is required")
    if policy is None:
        raise ToolPolicyMissingError("Tool policy is missing")
    if not isinstance(policy, ToolPolicyV2):
        raise ToolPolicyInvalidError("Tool policy must be ToolPolicyV2")
    if grant is None:
        raise TurnToolGrantMissingError("Turn tool grant is missing")
    if not isinstance(grant, TurnToolGrant):
        raise TurnToolGrantInvalidError("Turn tool grant must be TurnToolGrant")
    descriptor_snapshot, alias_map = _validated_descriptor_snapshot(descriptors)
    _validate_policy(policy, descriptor_snapshot)
    _validate_grant(grant)
    try:
        normalized_registry_version = int(registry_version)
    except (TypeError, ValueError) as exc:
        raise ToolRegistryMissingError("Registry version must be an integer") from exc
    if normalized_registry_version < 1:
        raise ToolRegistryMissingError("Registry version must be positive")

    known_names = {descriptor.name for descriptor in descriptor_snapshot}
    allowed = {_resolve_alias(name, alias_map) for name in policy.allowed_tools}
    blocked = {_resolve_alias(name, alias_map) for name in policy.blocked_tools}
    turn_denied = {_resolve_alias(name, alias_map) for name in grant.denied_tools}
    allowed_capabilities = set(grant.allowed_capabilities)
    available = (
        {descriptor.name for descriptor in descriptor_snapshot if descriptor.enabled}
        if available_tool_names is None
        else {_resolve_alias(str(name or "").strip(), alias_map) for name in available_tool_names if str(name or "").strip()}
    )
    available.intersection_update(known_names)

    visible: list[str] = []
    executable: list[str] = []
    denied: dict[str, ToolDenyReason] = {}
    for descriptor in descriptor_snapshot:
        name = descriptor.name
        visibility_reason = _visibility_deny_reason(
            descriptor,
            allowed=allowed,
            blocked=blocked,
            turn_denied=turn_denied,
            allowed_capabilities=allowed_capabilities,
            available=available,
        )
        if visibility_reason is not None:
            denied[name] = visibility_reason
            continue
        visible.append(name)
        execution_reason = _execution_deny_reason(descriptor, policy=policy, grant=grant)
        if execution_reason is not None:
            denied[name] = execution_reason
            continue
        executable.append(name)

    visible_set = set(visible)
    preferred = tuple(name for name in policy.preferred_tools if name in visible_set)
    ordered_denied = tuple(sorted(denied.items(), key=lambda item: item[0]))
    decision_payload = {
        "agentId": normalized_agent_id,
        "turnId": grant.turn_id,
        "policy": policy.public_projection(),
        "grant": grant.public_projection(),
        "registryVersion": normalized_registry_version,
        "registryFingerprint": str(registry_fingerprint or "").strip(),
        "visibleTools": visible,
        "executableTools": executable,
        "preferredTools": list(preferred),
        "denied": {name: reason.public_projection() for name, reason in ordered_denied},
    }
    return AuthorizationDecision(
        agent_id=normalized_agent_id,
        turn_id=grant.turn_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        registry_version=normalized_registry_version,
        visible_tools=tuple(visible),
        executable_tools=tuple(executable),
        preferred_tools=preferred,
        denied=ordered_denied,
        decision_fingerprint=_fingerprint(decision_payload),
        generated_at=str(generated_at or ""),
    )


def authorization_cache_key(
    *,
    agent_id: str,
    policy: ToolPolicyV2,
    grant: TurnToolGrant,
    registry_version: int,
    registry_fingerprint: str,
    available_tool_names: Iterable[str],
) -> AuthorizationCacheKey:
    """Build the immutable cache identity described by the authorization contract."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentIdentityMissingError("Agent identity is required")
    return AuthorizationCacheKey(
        agent_id=normalized_agent_id,
        policy_version=policy.policy_version,
        registry_version=int(registry_version),
        registry_fingerprint=str(registry_fingerprint or "").strip(),
        turn_grant_hash=_fingerprint(grant.public_projection()),
        environment_hash=_fingerprint(sorted({str(name or "").strip() for name in available_tool_names if str(name or "").strip()})),
    )


def _visibility_deny_reason(
    descriptor: ToolDescriptorLike,
    *,
    allowed: set[str],
    blocked: set[str],
    turn_denied: set[str],
    allowed_capabilities: set[str],
    available: set[str],
) -> ToolDenyReason | None:
    name = descriptor.name
    if not descriptor.enabled:
        return ToolDenyReason(ToolDenyCode.TOOL_DISABLED, "visibility", "Tool is disabled in the Registry")
    if name in blocked:
        return ToolDenyReason(ToolDenyCode.AGENT_BLOCKED, "visibility", "Tool is blocked by the Agent policy")
    if name not in allowed:
        return ToolDenyReason(ToolDenyCode.NOT_ASSIGNED, "visibility", "Tool is not assigned to the Agent")
    if name in turn_denied:
        return ToolDenyReason(ToolDenyCode.TURN_DENIED, "visibility", "Tool is denied for this turn")
    if not set(descriptor.capabilities).intersection(allowed_capabilities):
        return ToolDenyReason(ToolDenyCode.CAPABILITY_MISMATCH, "visibility", "Turn grant lacks a compatible capability")
    if name not in available:
        return ToolDenyReason(ToolDenyCode.ENVIRONMENT_UNAVAILABLE, "visibility", "Tool is unavailable in the current environment")
    return None


def _execution_deny_reason(
    descriptor: ToolDescriptorLike,
    *,
    policy: ToolPolicyV2,
    grant: TurnToolGrant,
) -> ToolDenyReason | None:
    network_access = _narrow_network_access(policy.network_access, grant.network_access)
    mutation_access = _narrow_mutation_access(policy.mutation_access, grant.mutation_access)
    if descriptor.risk == "network" and network_access == "none":
        return ToolDenyReason(ToolDenyCode.NETWORK_DENIED, "execution", "Network access is disabled")
    if descriptor.risk in {"write", "execute", "destructive"} and mutation_access == "none":
        return ToolDenyReason(ToolDenyCode.MUTATION_DENIED, "execution", "Mutation access is disabled")
    required_approval = policy.approval_override_for(descriptor.name) or str(descriptor.approval or "never")
    if _APPROVAL_RANK.get(required_approval, 2) > _APPROVAL_RANK[grant.approval_mode]:
        return ToolDenyReason(ToolDenyCode.APPROVAL_REQUIRED, "execution", "Required approval mode is not available")
    return None


def _validated_descriptor_snapshot(
    descriptors: Sequence[ToolDescriptorLike] | None,
) -> tuple[tuple[ToolDescriptorLike, ...], dict[str, str]]:
    if not descriptors:
        raise ToolRegistryMissingError("Tool Registry is missing or empty")
    ordered = tuple(sorted(descriptors, key=lambda item: str(getattr(item, "name", ""))))
    names: set[str] = set()
    aliases: dict[str, str] = {}
    for descriptor in ordered:
        name = str(getattr(descriptor, "name", "") or "").strip()
        if not name or name in names:
            raise ToolRegistryMissingError(f"Registry contains an invalid or duplicate tool: {name or '<empty>'}")
        names.add(name)
        capabilities = tuple(str(item or "").strip() for item in getattr(descriptor, "capabilities", ()) if str(item or "").strip())
        if not capabilities:
            raise ToolRegistryMissingError(f"Registry tool has no capabilities: {name}")
        for alias in getattr(descriptor, "aliases", ()):
            normalized_alias = str(alias or "").strip()
            if not normalized_alias or normalized_alias in aliases:
                raise ToolRegistryMissingError(f"Registry contains an invalid or duplicate alias: {normalized_alias or '<empty>'}")
            aliases[normalized_alias] = name
    collisions = names.intersection(aliases)
    if collisions:
        raise ToolRegistryMissingError(f"Registry alias collides with a canonical tool: {sorted(collisions)[0]}")
    return ordered, aliases


def _validate_policy(policy: ToolPolicyV2, descriptors: Sequence[ToolDescriptorLike]) -> None:
    known = {descriptor.name for descriptor in descriptors}
    if not policy.policy_id or policy.policy_version < 1:
        raise ToolPolicyInvalidError("ToolPolicyV2 identity is invalid")
    unknown_allowed = sorted(set(policy.allowed_tools).difference(known))
    unknown_preferred = sorted(set(policy.preferred_tools).difference(known))
    if unknown_allowed or unknown_preferred:
        unknown = unknown_allowed or unknown_preferred
        raise ToolPolicyInvalidError(f"ToolPolicyV2 references unknown granted tools: {', '.join(unknown)}")
    effective = set(policy.allowed_tools).difference(policy.blocked_tools)
    if not set(policy.preferred_tools).issubset(effective):
        raise ToolPolicyInvalidError("Preferred tools must be effectively allowed")


def _validate_grant(grant: TurnToolGrant) -> None:
    if not str(grant.turn_id or "").strip():
        raise TurnToolGrantInvalidError("Turn id is required")
    if grant.source not in _TURN_SOURCES:
        raise TurnToolGrantInvalidError(f"Unsupported turn grant source: {grant.source}")
    if grant.approval_mode not in {"never", "on_request"}:
        raise TurnToolGrantInvalidError(f"Unsupported turn approval mode: {grant.approval_mode}")
    for capability in grant.allowed_capabilities:
        if not _TOKEN_PATTERN.fullmatch(str(capability or "")):
            raise TurnToolGrantInvalidError(f"Invalid turn capability: {capability}")


def _policy_tool_names(value: Any, *, alias_map: Mapping[str, str], field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ToolPolicyInvalidError(f"{field} must be an array")
    return _ordered_unique(_resolve_alias(str(item or "").strip(), alias_map) for item in value if str(item or "").strip())


def _normalized_names(values: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    try:
        normalized = _ordered_unique(str(item or "").strip() for item in values or () if str(item or "").strip())
    except TypeError as exc:
        raise ToolPolicyInvalidError(f"{field} values must be iterable") from exc
    for value in normalized:
        if not _TOKEN_PATTERN.fullmatch(value):
            raise ToolPolicyInvalidError(f"Invalid {field}: {value}")
    return normalized


def _normalize_approval_overrides(
    value: Any,
    *,
    registered: frozenset[str],
    alias_map: Mapping[str, str],
) -> tuple[tuple[str, ApprovalMode], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ToolPolicyInvalidError("approvalOverrides must be an object")
    result: list[tuple[str, ApprovalMode]] = []
    for raw_name, raw_mode in value.items():
        name = _resolve_alias(str(raw_name or "").strip(), alias_map)
        mode = str(raw_mode or "").strip()
        if name not in registered:
            raise ToolPolicyInvalidError(f"Approval override references unknown tool: {name}")
        if mode not in _APPROVAL_MODES:
            raise ToolPolicyInvalidError(f"Unsupported approval override for {name}: {mode}")
        result.append((name, mode))  # type: ignore[arg-type]
    return tuple(sorted(result))


def _normalize_network_access(value: Any) -> str:
    normalized = str(value or "restricted").strip()
    normalized = _NETWORK_ALIASES.get(normalized, normalized)
    if normalized not in _NETWORK_ACCESS:
        raise ToolPolicyInvalidError(f"Unsupported networkAccess: {normalized}")
    return normalized


def _normalize_mutation_access(value: Any) -> str:
    normalized = str(value or "controlled").strip()
    normalized = _MUTATION_ALIASES.get(normalized, normalized)
    if normalized not in _MUTATION_ACCESS:
        raise ToolPolicyInvalidError(f"Unsupported mutationAccess: {normalized}")
    return normalized


def _narrow_network_access(policy_value: str, grant_value: str | None) -> str:
    if grant_value is None:
        return policy_value
    rank = {"none": 0, "restricted": 1, "full": 2}
    return min((policy_value, grant_value), key=lambda value: rank[value])


def _narrow_mutation_access(policy_value: str, grant_value: str | None) -> str:
    if grant_value is None:
        return policy_value
    rank = {"none": 0, "controlled": 1, "workspace": 2}
    return min((policy_value, grant_value), key=lambda value: rank[value])


def _resolve_alias(name: str, aliases: Mapping[str, str]) -> str:
    return aliases.get(name, name)


def _ordered_union(*values: Sequence[str]) -> tuple[str, ...]:
    return _ordered_unique(item for sequence in values for item in sequence)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return tuple(result)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()
