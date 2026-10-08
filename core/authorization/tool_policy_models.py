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

# writeScopes 闸门的控制面豁免标签集。语义定案：本闸门管辖「工作区/产物
# 写」（文件/内存/会话状态等落盘变更）；下列标签表达的是控制面操作——
# 跨 agent 消息与唤醒（cross_agent_message / can_wake_agent）和团队工作流
# 状态写（team_workflow_state_write，如任务看板）——由各自更细的门（板服务
# apply_* 角色门、唤醒/协作策略）管辖，豁免于本闸门。写类标签全部落在此
# 集合内的工具（如 agent_message_tool / dev_task_board_tool）不受「声明空
# 写范围即硬禁」影响，仍受 allowedTools / mutationAccess 等其他闸门管辖。
WRITE_SCOPE_EXEMPT_RISK_TAGS = frozenset(
    {"cross_agent_message", "can_wake_agent", "team_workflow_state_write"}
)


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
    WRITE_SCOPE_DENIED = "write_scope_denied"
    APPROVAL_REQUIRED = "approval_required"


# 审计规则标识（ruleId）最大长度：policyId 段按需截断，保证事件字段有界。
MAX_RULE_ID_LENGTH = 120


def compose_deny_rule_id(policy_id: str, code: ToolDenyCode, gate_id: str) -> str:
    """Compose the stable audit ruleId for one deny rule: policyId + gate + code.

    ``gate_id`` names the rule source that fired (for example
    ``policy.allowedTools``), so the same deny code triggered by different
    rules yields different ruleIds while staying deterministic per policy.
    """

    normalized_policy = str(policy_id or "").strip() or "policy-unresolved"
    normalized_gate = str(gate_id or "").strip() or "rule.unspecified"
    return f"{normalized_policy}:{normalized_gate}:{code.value}"[:MAX_RULE_ID_LENGTH]


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
    # 仅当源 policy 显式携带 writeScopes 键时为 True（空数组与非空皆算）。
    # 决策层分工：本标志只在「声明了写范围却为零范围」时对写类工具硬禁
    # （WRITE_SCOPE_DENIED）；非空 scope 的路径包含约束由会话工作区容器层
    # （任务 worktree 绑定）承担，决策层不做路径判定。未声明（键缺失）时
    # 本标志为 False，写工具行为与历史版本完全一致。
    write_scopes_declared: bool = False
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
    gate_id: str = ""
    rule_id: str = ""

    def public_projection(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "phase": self.phase,
            "message": self.message,
            "ruleId": self.rule_id,
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
    approval_requirements: tuple[tuple[str, ApprovalMode, str], ...] = ()

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
            "approvalRequirements": {
                name: {"approval": approval, "risk": risk}
                for name, approval, risk in self.approval_requirements
            },
        }


@dataclass(frozen=True, slots=True)
class AuthorizationCacheKey:
    agent_id: str
    policy_version: int
    registry_version: int
    registry_fingerprint: str
    turn_grant_hash: str
    environment_hash: str
