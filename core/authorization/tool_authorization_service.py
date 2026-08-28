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

# 交付类工具豁免回合调用额度：研究链路等 stage 会话在额度耗尽后仍必须能把已有
# 成果写回落盘，否则整个回合的检索成果零交付。只豁免白名单命中或以
# `_writeback_tool` 结尾的同类交付工具，不泛化到一般写工具。
DELIVERY_EXEMPT_TOOL_NAMES = {"source_collection_stage_writeback_tool"}
_DELIVERY_EXEMPT_TOOL_SUFFIX = "_writeback_tool"
# 豁免写回的独立宽松上限：滚动写回契约鼓励多批小写回，64 次/回合足够任何
# 合理交付节奏，同时封死熔断后无限连发写回的无人值守消耗通道。
MAX_DELIVERY_EXEMPT_CALLS_PER_TURN = 64


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        if any(key in value for key in ("name", "enabled", "capabilities", "aliases")):
            return [dict(value)]
        return [dict(item) for item in value.values() if isinstance(item, Mapping)]
    if isinstance(value, (str, bytes)) or value is None:
        return []
    try:
        iterator = list(value)
    except TypeError:
        return []
    return [dict(item) for item in iterator if isinstance(item, Mapping)]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _is_delivery_exempt_tool(tool_name: Any) -> bool:
    normalized = _coerce_text(tool_name).strip()
    return normalized in DELIVERY_EXEMPT_TOOL_NAMES or normalized.endswith(_DELIVERY_EXEMPT_TOOL_SUFFIX)


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").strip()
        return [text] if text else []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        return [str(key or "").strip() for key in value if str(key or "").strip()]
    try:
        iterator = list(value)
    except TypeError:
        text = str(value or "").strip()
        return [text] if text else []
    names: list[str] = []
    for item in iterator:
        text = str(item or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


class ToolAuthorizationContextError(ValueError):
    """Raised when an enforced authorization decision lacks trusted identity facts."""


@dataclass(slots=True)
class ToolExecutionAuthorizationContext:
    agent_id: str
    turn_id: str
    decision_fingerprint: str
    config_revision: int
    config_hash: str
    permission_preset: str
    executable_tools: tuple[str, ...]
    approval_requirements: tuple[tuple[str, str, str], ...] = ()
    max_calls_per_turn: int = 0
    call_count: int = 0
    delivery_exempt_call_count: int = 0
    budget_profile: str = ""
    model_family: str = ""
    model: str = ""
    provider: str = ""
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
    loaded = registry_payload if registry_payload is not None else _load_registry_payload(registry_loader)
    payload = _as_mapping(loaded)
    descriptors = _descriptors_from_registry(payload)
    registered_names = tuple(descriptor.name for descriptor in descriptors)
    runtime_values = _as_mapping(runtime)
    agent = _as_mapping(runtime_values.get("agent"))
    raw_policy = runtime_values.get("toolPolicy")
    if raw_policy is None:
        raw_policy = runtime_values.get("tool_policy")
    policy = _role_policy_projection(
        agent=agent,
        raw_policy=raw_policy,
        registered_names=registered_names,
    )
    turn_id = _coerce_text(runtime_values.get("turnId") or runtime_values.get("runId")).strip()
    source = _turn_source(runtime_values, agent)
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
                _coerce_text(item.get("name")).strip()
                for item in _mapping_items(payload.get("tools"))
                if _coerce_bool(item.get("enabled"), False)
                and _coerce_bool(item.get("runtimeActive"), False)
                and _coerce_bool(item.get("llmVisible"), False)
                and _coerce_text(item.get("name")).strip()
            }
        )
    )
    externally_blocked_tools = _coerce_str_list(
        runtime_values.get("externallyBlockedTools")
        or runtime_values.get("externally_blocked_tools")
    )
    decision = evaluate_tool_policy(
        agent_id=_coerce_text(runtime_values.get("agentId") or agent.get("agentId")).strip(),
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=_safe_int(payload.get("registryVersion"), 0),
        registry_fingerprint=_coerce_text(payload.get("registryFingerprint")).strip(),
        available_tool_names=available_names,
        externally_blocked_tools=externally_blocked_tools,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    deny_counts = Counter(reason.code.value for _, reason in decision.denied)
    return AuthorizationReport(
        decision=decision,
        deny_code_counts=tuple(sorted(deny_counts.items())),
        registry_fingerprint=_coerce_text(payload.get("registryFingerprint")).strip(),
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

    values = _as_mapping(runtime)
    agent = _as_mapping(values.get("agent"))
    agent_id = _coerce_text(values.get("agentId") or agent.get("agentId")).strip()
    if not agent_id:
        raise ToolAuthorizationContextError("tool authorization requires agentId")
    turn_id = _coerce_text(values.get("turnId") or values.get("runId")).strip()
    if not turn_id:
        raise ToolAuthorizationContextError("tool authorization requires turnId")
    return _resolve_authorization(
        runtime=values,
        registry_payload=registry_payload,
        registry_loader=registry_loader,
        generated_at=generated_at,
    )


def _runtime_llm_identity(runtime: Mapping[str, Any]) -> tuple[str, str, str]:
    """Best-effort model/provider/profile identity for budget profiles."""

    model = _coerce_text(runtime.get("model") or runtime.get("llmModel")).strip()
    provider = _coerce_text(runtime.get("provider") or runtime.get("llmProvider")).strip()
    profile_id = _coerce_text(runtime.get("llmProfileId") or runtime.get("profileId")).strip()
    config_snapshot = _as_mapping(runtime.get("agentConfigSnapshot"))
    if config_snapshot:
        model = model or _coerce_text(config_snapshot.get("model") or config_snapshot.get("llmModel")).strip()
        provider = provider or _coerce_text(
            config_snapshot.get("provider") or config_snapshot.get("llmProvider")
        ).strip()
        profile_id = profile_id or _coerce_text(
            config_snapshot.get("llmProfileId") or config_snapshot.get("profileId")
        ).strip()
        bindings = _as_mapping(config_snapshot.get("llmBindings"))
        primary = _as_mapping(bindings.get("primary"))
        if primary:
            model = model or _coerce_text(primary.get("model") or primary.get("modelId")).strip()
            provider = provider or _coerce_text(primary.get("provider") or primary.get("providerId")).strip()
    if not model or not provider:
        try:
            from config.settings import get_config

            profile = get_config().llm.get_profile(role="primary")
            model = model or str(getattr(profile, "model", "") or "").strip()
            profile_id = profile_id or str(getattr(profile, "profile_id", "") or getattr(profile, "id", "") or "").strip()
            provider_obj = getattr(profile, "provider", None)
            if provider_obj is not None:
                provider = provider or str(
                    getattr(provider_obj, "provider_id", "")
                    or getattr(provider_obj, "name", "")
                    or provider_obj
                    or ""
                ).strip()
        except Exception:
            pass
    return model, provider, profile_id


def install_execution_authorization(report: AuthorizationReport) -> ToolExecutionAuthorizationContext:
    from core.orchestration.tool_budget_profiles import resolve_max_calls_per_turn
    from core.web.services.agent_directory_service import current_agent_runtime

    decision = report.decision
    runtime = _as_mapping(current_agent_runtime())
    policy = runtime.get("toolPolicy")
    if policy is None:
        policy = runtime.get("tool_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    config_snapshot = _as_mapping(runtime.get("agentConfigSnapshot"))
    model, provider, profile_id = _runtime_llm_identity(runtime)
    max_calls_per_turn, budget_profile = resolve_max_calls_per_turn(
        policy,
        model=model,
        provider=provider,
        profile_id=profile_id,
    )
    context = ToolExecutionAuthorizationContext(
        agent_id=_coerce_text(decision.agent_id).strip(),
        turn_id=_coerce_text(decision.turn_id).strip(),
        decision_fingerprint=_coerce_text(decision.decision_fingerprint).strip(),
        config_revision=_safe_int(config_snapshot.get("configRevision"), 0),
        config_hash=_coerce_text(config_snapshot.get("configHash")).strip(),
        permission_preset=_coerce_text(runtime.get("permissionPreset")).strip(),
        executable_tools=tuple(decision.executable_tools),
        approval_requirements=tuple(getattr(decision, "approval_requirements", ()) or ()),
        max_calls_per_turn=max_calls_per_turn,
        budget_profile=budget_profile,
        model_family=budget_profile,
        model=model,
        provider=provider,
    )
    if (
        not context.agent_id
        or not context.turn_id
        or not context.decision_fingerprint
        or context.config_revision < 1
        or not context.config_hash
        or not context.permission_preset
    ):
        raise ToolAuthorizationContextError(
            "execution authorization requires Agent config identity"
        )
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
    if _coerce_text(tool_name).strip().lower() != "write_stdin" or not isinstance(tool_args, Mapping):
        return ""
    chars = tool_args.get("chars", tool_args.get("input", ""))
    if chars not in (None, ""):
        return ""
    for key in ("terminal_session_id", "session_id", "sessionId", "terminal_id", "terminalId"):
        session_id = _coerce_text(tool_args.get(key)).strip()
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

    runtime = _as_mapping(current_agent_runtime())
    runtime_agent_id = _coerce_text(runtime.get("agentId")).strip()
    if not runtime_agent_id:
        return ToolExecutionAuthorizationResult(
            enforced=False,
            allowed=True,
            code="system_context",
            message="",
        )
    runtime_turn_id = _coerce_text(runtime.get("turnId") or runtime.get("runId")).strip()
    context = current_execution_authorization()
    if context is None:
        return _execution_denial("missing_decision", "当前 Agent 缺少可信工具授权决策。", runtime_agent_id, runtime_turn_id)
    if not _coerce_text(tool_call_id).strip():
        return _execution_denial("missing_call_id", "当前工具调用缺少 callId。", runtime_agent_id, runtime_turn_id, context)
    if context.agent_id != runtime_agent_id:
        return _execution_denial("agent_mismatch", "工具授权决策不属于当前 Agent。", runtime_agent_id, runtime_turn_id, context)
    if runtime_turn_id and context.turn_id != runtime_turn_id:
        return _execution_denial("turn_mismatch", "工具授权决策不属于当前回合。", runtime_agent_id, runtime_turn_id, context)
    runtime_config_snapshot = _as_mapping(runtime.get("agentConfigSnapshot"))
    if (
        _safe_int(runtime_config_snapshot.get("configRevision"), 0)
        != context.config_revision
        or _coerce_text(runtime_config_snapshot.get("configHash")).strip()
        != context.config_hash
        or _coerce_text(runtime.get("permissionPreset")).strip()
        != context.permission_preset
    ):
        return _execution_denial(
            "agent_config_mismatch",
            "工具授权决策与当前 Agent 配置快照不一致。",
            runtime_agent_id,
            runtime_turn_id,
            context,
        )
    normalized_tool = _coerce_text(tool_name).strip()
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
        if _is_delivery_exempt_tool(normalized_tool):
            # 交付类工具不占回合额度、也不被额度拒绝：额度耗尽时仍必须放行成果落盘。
            # 但豁免必须有独立上限，否则失控模型可在熔断后无限连发写回。
            context.delivery_exempt_call_count += 1
            if (
                context.delivery_exempt_call_count
                > MAX_DELIVERY_EXEMPT_CALLS_PER_TURN
            ):
                return _execution_denial(
                    "delivery_writeback_budget_exhausted",
                    "本回合写回/交付类调用次数已达上限。请停止继续写回，以文本总结当前结果并结束回合。",
                    runtime_agent_id,
                    runtime_turn_id,
                    context,
                )
        elif context.max_calls_per_turn > 0 and context.call_count >= context.max_calls_per_turn:
            return _execution_denial("call_budget_exhausted", "当前回合工具调用额度已用尽。", runtime_agent_id, runtime_turn_id, context)
        else:
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
                config_revision=context.config_revision,
                config_hash=context.config_hash,
                permission_preset=context.permission_preset,
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
    )

    if tool_name in DISABLED_AGENT_DIRECT_READ_TOOL_NAMES:
        return (
            "direct_read_tool_disabled",
            f"当前 Agent 已关闭 `{tool_name}` 直读能力，请使用已授权的受控读取工具。",
        )
    if tool_name in SUBAGENT_DELEGATION_TOOL_NAMES:
        raw_policy = _as_mapping(runtime.get("delegationPolicy") or runtime.get("delegation_policy"))
        allow_subagents = _coerce_bool(
            raw_policy.get("allowSubagents")
            if "allowSubagents" in raw_policy
            else raw_policy.get("allow_subagents"),
            False,
        )
        if not allow_subagents:
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
    for item in _mapping_items(payload.get("descriptors")):
        name = _coerce_text(item.get("name")).strip()
        if not name:
            continue
        descriptors.append(
            _RegistryDescriptor(
                name=name,
                enabled=_coerce_bool(item.get("enabled"), False),
                capabilities=tuple(_coerce_str_list(item.get("capabilities"))),
                risk=_coerce_text(item.get("risk") or "read").strip() or "read",
                approval=_coerce_text(item.get("approval") or "never").strip() or "never",
                aliases=tuple(_coerce_str_list(item.get("aliases"))),
            )
        )
    return tuple(descriptors)


def _role_policy_projection(*, agent: Mapping[str, Any], raw_policy: Any, registered_names: Sequence[str]):
    from core.web.services import agent_role_tool_profile_service

    metadata = _as_mapping(agent.get("metadata"))
    policy = _as_mapping(raw_policy)
    role_key = _coerce_text(agent.get("roleKey")).strip()
    primary_mode = _coerce_text(agent.get("primaryMode")).strip()
    policy_id = (
        _coerce_text(policy.get("policyId") or policy.get("id")).strip()
        or f"tool-{_coerce_text(agent.get('agentId') or 'agent').strip()}"
    )
    role_policy = agent_role_tool_profile_service.resolve_role_tool_policy_v2(
        role_key=role_key,
        primary_mode=primary_mode,
        metadata=metadata,
        policy_id=policy_id,
        registered_tool_names=registered_names,
    )
    if role_policy is not None and agent_role_tool_profile_service.role_has_explicit_tool_profile(
        role_key,
        primary_mode=primary_mode,
        metadata=metadata,
    ):
        return role_policy
    return normalize_legacy_tool_policy(
        raw_policy if isinstance(raw_policy, Mapping) else policy or None,
        registered_tool_names=registered_names,
    )


def _turn_source(runtime: Mapping[str, Any], agent: Mapping[str, Any]) -> str:
    mode = _coerce_text(
        agent.get("primaryMode") or runtime.get("primaryMode") or runtime.get("mode")
    ).strip().lower()
    if runtime.get("roomId") or runtime.get("roundId"):
        return "team"
    if mode == "research":
        return "research"
    if mode == "supervised_evolution" or runtime.get("supervisedRole"):
        return "supervised"
    if mode == "self_evolution":
        return "self_evolution"
    return "session"
