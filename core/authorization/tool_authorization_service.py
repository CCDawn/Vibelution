"""Shadow-mode integration for canonical Agent tool authorization."""

from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
from .tool_policy_models import AuthorizationDecision, TurnToolGrant


MAX_TERMINAL_WAITS_PER_SESSION = 8
MAX_TERMINAL_WAITS_PER_TURN = 16


class ToolAuthorizationContextError(ValueError):
    """Raised when an enforced authorization decision lacks trusted identity facts."""


@dataclass(slots=True)
class ToolExecutionAuthorizationContext:
    agent_id: str
    turn_id: str
    decision_fingerprint: str
    executable_tools: tuple[str, ...]
    approval_requirements: tuple[tuple[str, str, str], ...] = ()
    max_calls_per_turn: int = 0
    call_count: int = 0
    call_count_lock: Lock = field(default_factory=Lock, repr=False)
    terminal_wait_counts: dict[str, int] = field(default_factory=dict, repr=False)
    terminal_wait_count: int = 0


@dataclass(frozen=True, slots=True)
class ToolExecutionAuthorizationResult:
    enforced: bool
    allowed: bool
    code: str
    message: str
    agent_id: str = ""
    turn_id: str = ""
    decision_fingerprint: str = ""


_EXECUTION_AUTHORIZATION: ContextVar[ToolExecutionAuthorizationContext | None] = ContextVar(
    "vibelution_tool_execution_authorization",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _RegistryDescriptor:
    name: str
    enabled: bool
    capabilities: tuple[str, ...]
    risk: str
    approval: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorizationReport:
    decision: AuthorizationDecision
    deny_code_counts: tuple[tuple[str, int], ...]
    registry_fingerprint: str
    duration_ms: int


def _resolve_authorization(
    *,
    runtime: Mapping[str, Any],
    registry_payload: Mapping[str, Any] | None = None,
    registry_loader: Callable[[], Mapping[str, Any]] | None = None,
    generated_at: str = "",
) -> AuthorizationReport:
    """Resolve one canonical decision without any legacy visibility input."""

    started = perf_counter()
    payload = dict(registry_payload or _load_registry_payload(registry_loader))
    descriptors = _descriptors_from_registry(payload)
    registered_names = tuple(descriptor.name for descriptor in descriptors)
    agent = runtime.get("agent") if isinstance(runtime.get("agent"), Mapping) else {}
    raw_policy = runtime.get("toolPolicy")
    policy = _role_policy_projection(
        agent=agent,
        raw_policy=raw_policy,
        registered_names=registered_names,
    )
    turn_id = str(runtime.get("turnId") or runtime.get("runId") or "").strip()
    source = _turn_source(runtime, agent)
    capabilities = tuple(sorted({capability for descriptor in descriptors for capability in descriptor.capabilities}))
    grant = TurnToolGrant(
        turn_id=turn_id,
        source=source,
        allowed_capabilities=capabilities,
        denied_tools=(),
        approval_mode="on_request",
    )
    available_names = tuple(
        sorted(
            {
                str(item.get("name") or "").strip()
                for item in payload.get("tools") or []
                if isinstance(item, Mapping)
                and item.get("enabled")
                and item.get("runtimeActive")
                and item.get("llmVisible")
                and str(item.get("name") or "").strip()
            }
        )
    )
    decision = evaluate_tool_policy(
        agent_id=str(runtime.get("agentId") or agent.get("agentId") or "").strip(),
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=int(payload.get("registryVersion") or 0),
        registry_fingerprint=str(payload.get("registryFingerprint") or "").strip(),
        available_tool_names=available_names,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    deny_counts = Counter(reason.code.value for _, reason in decision.denied)
    return AuthorizationReport(
        decision=decision,
        deny_code_counts=tuple(sorted(deny_counts.items())),
        registry_fingerprint=str(payload.get("registryFingerprint") or "").strip(),
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
    )


def resolve_enforced_authorization(
    *,
    runtime: Mapping[str, Any],
    registry_payload: Mapping[str, Any] | None = None,
    registry_loader: Callable[[], Mapping[str, Any]] | None = None,
    generated_at: str = "",
) -> AuthorizationReport:
    """Resolve the only model-visible and executable tool decision."""

    values = dict(runtime or {})
    agent = values.get("agent") if isinstance(values.get("agent"), Mapping) else {}
    agent_id = str(values.get("agentId") or agent.get("agentId") or "").strip()
    if not agent_id:
        raise ToolAuthorizationContextError("tool authorization requires agentId")
    turn_id = str(values.get("turnId") or values.get("runId") or "").strip()
    if not turn_id:
        raise ToolAuthorizationContextError("tool authorization requires turnId")
    return _resolve_authorization(
        runtime=values,
        registry_payload=registry_payload,
        registry_loader=registry_loader,
        generated_at=generated_at,
    )


def install_execution_authorization(report: AuthorizationReport) -> ToolExecutionAuthorizationContext:
    from core.web.services.agent_directory_service import current_agent_runtime

    decision = report.decision
    runtime = dict(current_agent_runtime() or {})
    policy = runtime.get("toolPolicy") if isinstance(runtime.get("toolPolicy"), Mapping) else {}
    try:
        max_calls_per_turn = max(0, int(policy.get("maxCallsPerTurn") or 0))
    except (TypeError, ValueError):
        max_calls_per_turn = 0
    context = ToolExecutionAuthorizationContext(
        agent_id=str(decision.agent_id or "").strip(),
        turn_id=str(decision.turn_id or "").strip(),
        decision_fingerprint=str(decision.decision_fingerprint or "").strip(),
        executable_tools=tuple(decision.executable_tools),
        approval_requirements=tuple(getattr(decision, "approval_requirements", ()) or ()),
        max_calls_per_turn=max_calls_per_turn,
    )
    if not context.agent_id or not context.turn_id or not context.decision_fingerprint:
        raise ToolAuthorizationContextError("execution authorization requires agent, turn, and decision fingerprint")
    _EXECUTION_AUTHORIZATION.set(context)
    return context


def clear_execution_authorization() -> None:
    _EXECUTION_AUTHORIZATION.set(None)


def current_execution_authorization() -> ToolExecutionAuthorizationContext | None:
    return _EXECUTION_AUTHORIZATION.get(None)


def _empty_terminal_wait_session_id(
    tool_name: str,
    tool_args: Mapping[str, Any] | None,
) -> str:
    if str(tool_name or "").strip().lower() != "write_stdin" or not isinstance(tool_args, Mapping):
        return ""
    chars = tool_args.get("chars", tool_args.get("input", ""))
    if chars not in (None, ""):
        return ""
    for key in ("terminal_session_id", "session_id", "sessionId", "terminal_id", "terminalId"):
        session_id = str(tool_args.get(key) or "").strip()
        if session_id:
            return session_id
    return ""


def authorize_tool_execution(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: Mapping[str, Any] | None = None,
    cancel_checker: Callable[[], str] | None = None,
) -> ToolExecutionAuthorizationResult:
    from core.web.services.agent_directory_service import current_agent_runtime

    runtime = dict(current_agent_runtime() or {})
    runtime_agent_id = str(runtime.get("agentId") or "").strip()
    if not runtime_agent_id:
        return ToolExecutionAuthorizationResult(
            enforced=False,
            allowed=True,
            code="system_context",
            message="",
        )
    runtime_turn_id = str(runtime.get("turnId") or runtime.get("runId") or "").strip()
    context = current_execution_authorization()
    if context is None:
        return _execution_denial("missing_decision", "当前 Agent 缺少可信工具授权决策。", runtime_agent_id, runtime_turn_id)
    if not str(tool_call_id or "").strip():
        return _execution_denial("missing_call_id", "当前工具调用缺少 callId。", runtime_agent_id, runtime_turn_id, context)
    if context.agent_id != runtime_agent_id:
        return _execution_denial("agent_mismatch", "工具授权决策不属于当前 Agent。", runtime_agent_id, runtime_turn_id, context)
    if runtime_turn_id and context.turn_id != runtime_turn_id:
        return _execution_denial("turn_mismatch", "工具授权决策不属于当前回合。", runtime_agent_id, runtime_turn_id, context)
    normalized_tool = str(tool_name or "").strip()
    if normalized_tool not in set(context.executable_tools):
        return _execution_denial("tool_not_executable", "当前工具未被本回合授权执行。", runtime_agent_id, runtime_turn_id, context)
    constraint_denial = _runtime_constraint_denial(runtime, normalized_tool, tool_args or {})
    if constraint_denial:
        code, detail = constraint_denial
        return _execution_denial(code, detail, runtime_agent_id, runtime_turn_id, context)
    terminal_wait_session_id = _empty_terminal_wait_session_id(normalized_tool, tool_args)
    with context.call_count_lock:
        if terminal_wait_session_id:
            if context.terminal_wait_count >= MAX_TERMINAL_WAITS_PER_TURN:
                return _execution_denial(
                    "terminal_wait_turn_budget_exhausted",
                    "当前回合的终端轮询次数已用尽。",
                    runtime_agent_id,
                    runtime_turn_id,
                    context,
                )
            count = context.terminal_wait_counts.get(terminal_wait_session_id, 0)
            if count >= MAX_TERMINAL_WAITS_PER_SESSION:
                return _execution_denial(
                    "terminal_wait_budget_exhausted",
                    "当前终端会话的轮询次数已用尽。",
                    runtime_agent_id,
                    runtime_turn_id,
                    context,
                )
            context.terminal_wait_counts[terminal_wait_session_id] = count + 1
            context.terminal_wait_count += 1
            terminal_wait_result = ToolExecutionAuthorizationResult(
                enforced=True,
                allowed=True,
                code="allowed_terminal_wait",
                message="",
                agent_id=context.agent_id,
                turn_id=context.turn_id,
                decision_fingerprint=context.decision_fingerprint,
            )
            return terminal_wait_result
        if context.max_calls_per_turn > 0 and context.call_count >= context.max_calls_per_turn:
            return _execution_denial("call_budget_exhausted", "当前回合工具调用额度已用尽。", runtime_agent_id, runtime_turn_id, context)
        context.call_count += 1
    approval_requirement = next(
        (
            (approval, risk)
            for name, approval, risk in context.approval_requirements
            if name == normalized_tool
        ),
        None,
    )
    if approval_requirement is not None:
        from core.web.services.session.tool_approvals import (
            ToolApprovalError,
            authorize_or_wait,
        )

        approval, risk = approval_requirement
        try:
            approval_outcome = authorize_or_wait(
                session_id=str(runtime.get("sessionId") or "").strip(),
                turn_id=context.turn_id,
                agent_id=context.agent_id,
                call_id=str(tool_call_id or "").strip(),
                tool_name=normalized_tool,
                tool_args=tool_args or {},
                approval=approval,
                risk=risk,
                decision_fingerprint=context.decision_fingerprint,
                cancel_checker=cancel_checker,
            )
        except ToolApprovalError as exc:
            return _execution_denial(
                "approval_context_invalid",
                f"工具审批上下文无效：{exc}",
                runtime_agent_id,
                runtime_turn_id,
                context,
            )
        if not approval_outcome.allowed:
            return ToolExecutionAuthorizationResult(
                enforced=True,
                allowed=False,
                code=approval_outcome.code,
                message=approval_outcome.message,
                agent_id=context.agent_id,
                turn_id=context.turn_id,
                decision_fingerprint=context.decision_fingerprint,
            )
        approval_code = approval_outcome.code
    else:
        approval_code = "allowed"
    return ToolExecutionAuthorizationResult(
        enforced=True,
        allowed=True,
        code=approval_code,
        message="",
        agent_id=context.agent_id,
        turn_id=context.turn_id,
        decision_fingerprint=context.decision_fingerprint,
    )


def _runtime_constraint_denial(
    runtime: Mapping[str, Any],
    tool_name: str,
    tool_args: Mapping[str, Any],
) -> tuple[str, str] | None:
    del tool_args
    from core.web.services.agent_directory_service import (
        DISABLED_AGENT_DIRECT_READ_TOOL_NAMES,
        SUBAGENT_DELEGATION_TOOL_NAMES,
        normalize_delegation_policy,
    )

    if tool_name in DISABLED_AGENT_DIRECT_READ_TOOL_NAMES:
        return (
            "direct_read_tool_disabled",
            f"当前 Agent 已关闭 `{tool_name}` 直读能力，请使用已授权的受控读取工具。",
        )
    if tool_name in SUBAGENT_DELEGATION_TOOL_NAMES:
        delegation_policy = normalize_delegation_policy(runtime.get("delegationPolicy"))
        if not bool(delegation_policy.get("allowSubagents", False)):
            return (
                "subagent_delegation_disabled",
                "当前 Agent 的委托策略（DelegationPolicy）默认关闭子 agent 派发权限。",
            )
    return None


def _execution_denial(
    code: str,
    detail: str,
    agent_id: str,
    turn_id: str,
    context: ToolExecutionAuthorizationContext | None = None,
) -> ToolExecutionAuthorizationResult:
    return ToolExecutionAuthorizationResult(
        enforced=True,
        allowed=False,
        code=code,
        message=f"[工具授权] {detail} 请刷新 Agent 工具配置后重试。",
        agent_id=agent_id,
        turn_id=turn_id,
        decision_fingerprint=str(getattr(context, "decision_fingerprint", "") or ""),
    )


def _load_registry_payload(registry_loader: Callable[[], Mapping[str, Any]] | None) -> Mapping[str, Any]:
    if registry_loader is not None:
        return registry_loader()
    from core.web.services.tool_registry_service import get_tool_registry

    return get_tool_registry()


def _descriptors_from_registry(payload: Mapping[str, Any]) -> tuple[_RegistryDescriptor, ...]:
    descriptors: list[_RegistryDescriptor] = []
    for item in payload.get("descriptors") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        descriptors.append(
            _RegistryDescriptor(
                name=name,
                enabled=bool(item.get("enabled")),
                capabilities=tuple(str(value or "").strip() for value in item.get("capabilities") or [] if str(value or "").strip()),
                risk=str(item.get("risk") or "read").strip() or "read",
                approval=str(item.get("approval") or "never").strip() or "never",
                aliases=tuple(str(value or "").strip() for value in item.get("aliases") or [] if str(value or "").strip()),
            )
        )
    return tuple(descriptors)


def _role_policy_projection(*, agent: Mapping[str, Any], raw_policy: Any, registered_names: Sequence[str]):
    from core.web.services import agent_role_tool_profile_service

    role_policy = agent_role_tool_profile_service.resolve_role_tool_policy_v2(
        role_key=str(agent.get("roleKey") or "").strip(),
        primary_mode=str(agent.get("primaryMode") or "").strip(),
        metadata=dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), Mapping) else {},
        policy_id=str(
            (raw_policy or {}).get("policyId") if isinstance(raw_policy, Mapping) else ""
        ).strip()
        or f"tool-{str(agent.get('agentId') or 'agent').strip()}",
        registered_tool_names=registered_names,
    )
    if role_policy is not None and agent_role_tool_profile_service.role_has_explicit_tool_profile(
        str(agent.get("roleKey") or "").strip(),
        primary_mode=str(agent.get("primaryMode") or "").strip(),
        metadata=dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), Mapping) else {},
    ):
        return role_policy
    return normalize_legacy_tool_policy(
        raw_policy,
        registered_tool_names=registered_names,
    )


def _turn_source(runtime: Mapping[str, Any], agent: Mapping[str, Any]) -> str:
    mode = str(agent.get("primaryMode") or runtime.get("primaryMode") or runtime.get("mode") or "").strip().lower()
    if runtime.get("roomId") or runtime.get("roundId"):
        return "team"
    if mode == "research":
        return "research"
    if mode == "supervised_evolution" or runtime.get("supervisedRole"):
        return "supervised"
    if mode == "self_evolution":
        return "self_evolution"
    return "session"
