"""Immutable models for Agent tool policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


NetworkAccess = Literal["none", "restricted", "full"]
MutationAccess = Literal["none", "workspace", "controlled"]
DelegationAccess = Literal["none", "assigned_only"]
ApprovalMode = Literal["never", "on_request", "always"]
TurnSource = Literal["session", "team", "research", "supervised", "self_evolution"]


class ToolAuthorizationError(ValueError):
    """Base error for fail-closed authorization input failures."""


class AgentIdentityMissingError(ToolAuthorizationError):
    """Raised when a decision has no concrete Agent identity."""


class ToolPolicyMissingError(ToolAuthorizationError):
    """Raised when an Agent policy reference cannot be resolved."""


class ToolPolicyInvalidError(ToolAuthorizationError):
    """Raised when a policy cannot be projected without ambiguity."""


class ToolRegistryMissingError(ToolAuthorizationError):
    """Raised when no canonical Registry snapshot is supplied."""


class TurnToolGrantMissingError(ToolAuthorizationError):
    """Raised when a turn has no host-owned grant."""


class TurnToolGrantInvalidError(ToolAuthorizationError):
    """Raised when a turn grant is malformed or unsupported."""


class ToolDenyCode(str, Enum):
    TOOL_DISABLED = "tool_disabled"
    AGENT_BLOCKED = "agent_blocked"
    NOT_ASSIGNED = "not_assigned"
    TURN_DENIED = "turn_denied"
    CAPABILITY_MISMATCH = "capability_mismatch"
    ENVIRONMENT_UNAVAILABLE = "environment_unavailable"
    NETWORK_DENIED = "network_denied"
    MUTATION_DENIED = "mutation_denied"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class ToolPolicyV2:
    policy_id: str
    policy_version: int
    allowed_tools: tuple[str, ...]
    blocked_tools: tuple[str, ...]
    preferred_tools: tuple[str, ...]
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    network_access: NetworkAccess
    mutation_access: MutationAccess
    delegation_access: DelegationAccess
    max_calls_per_turn: int
    approval_overrides: tuple[tuple[str, ApprovalMode], ...] = ()

    def approval_override_for(self, tool_name: str) -> ApprovalMode | None:
        for name, mode in self.approval_overrides:
            if name == tool_name:
                return mode
        return None

    def public_projection(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "allowedTools": list(self.allowed_tools),
            "blockedTools": list(self.blocked_tools),
            "preferredTools": list(self.preferred_tools),
            "readScopes": list(self.read_scopes),
            "writeScopes": list(self.write_scopes),
            "networkAccess": self.network_access,
            "mutationAccess": self.mutation_access,
            "delegationAccess": self.delegation_access,
            "maxCallsPerTurn": self.max_calls_per_turn,
            "approvalOverrides": dict(self.approval_overrides),
        }


@dataclass(frozen=True, slots=True)
class TurnToolGrant:
    turn_id: str
    source: TurnSource
    allowed_capabilities: tuple[str, ...]
    denied_tools: tuple[str, ...]
    approval_mode: Literal["never", "on_request"]
    read_scopes: tuple[str, ...] | None = None
    write_scopes: tuple[str, ...] | None = None
    network_access: NetworkAccess | None = None
    mutation_access: MutationAccess | None = None

    def public_projection(self) -> dict[str, Any]:
        return {
            "turnId": self.turn_id,
            "source": self.source,
            "allowedCapabilities": list(self.allowed_capabilities),
            "deniedTools": list(self.denied_tools),
            "readScopes": None if self.read_scopes is None else list(self.read_scopes),
            "writeScopes": None if self.write_scopes is None else list(self.write_scopes),
            "networkAccess": self.network_access,
            "mutationAccess": self.mutation_access,
            "approvalMode": self.approval_mode,
        }


@dataclass(frozen=True, slots=True)
class ToolDenyReason:
    code: ToolDenyCode
    phase: Literal["visibility", "execution"]
    message: str

    def public_projection(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "phase": self.phase,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    agent_id: str
    turn_id: str
    policy_id: str
    policy_version: int
    registry_version: int
    visible_tools: tuple[str, ...]
    executable_tools: tuple[str, ...]
    preferred_tools: tuple[str, ...]
    denied: tuple[tuple[str, ToolDenyReason], ...]
    decision_fingerprint: str
    generated_at: str

    def deny_reason_for(self, tool_name: str) -> ToolDenyReason | None:
        for name, reason in self.denied:
            if name == tool_name:
                return reason
        return None

    def public_projection(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "turnId": self.turn_id,
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "registryVersion": self.registry_version,
            "visibleTools": list(self.visible_tools),
            "executableTools": list(self.executable_tools),
            "preferredTools": list(self.preferred_tools),
            "denied": {name: reason.public_projection() for name, reason in self.denied},
            "decisionFingerprint": self.decision_fingerprint,
            "generatedAt": self.generated_at,
        }


@dataclass(frozen=True, slots=True)
class AuthorizationCacheKey:
    agent_id: str
    policy_version: int
    registry_version: int
    registry_fingerprint: str
    turn_grant_hash: str
    environment_hash: str
