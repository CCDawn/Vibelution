"""Shadow-mode integration for canonical Agent tool authorization."""

from __future__ import annotations

from collections import Counter, OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from threading import Lock, local
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
from .tool_policy_models import AuthorizationDecision, TurnToolGrant


MAX_TERMINAL_WAITS_PER_SESSION = 8
MAX_TERMINAL_WAITS_PER_TURN = 16
# 执行上下文携带的决策级 deny 规则上限：ruleId 审计富化用，超出部分由
# decision_reasons 事件面覆盖，避免上下文随注册表规模无界增长。
MAX_DENY_RULES_IN_CONTEXT = 256

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
    deny_rules: tuple[tuple[str, str, str], ...] = ()
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
    reason_code: str = ""
    rule_id: str = ""


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
    # writeScopes 闸门派生判定（由 Registry 投影 writeScopeGated 透传）；
    # 缺省 True 保持 fail-closed：旧 payload 未带字段时写工具照旧受闸。
    write_scope_gated: bool = True


@dataclass(frozen=True, slots=True)
class AuthorizationReport:
    decision: AuthorizationDecision
    deny_code_counts: tuple[tuple[str, int], ...]
    registry_fingerprint: str
    duration_ms: int
    # TTFT 批五任务 C：turn 无关决策模板缓存身份。命中时非空且表示本决策由
    # 输入完全相同的上一次评估模板重建（含本轮 turn_id/时间戳/指纹）。
    decision_cache_key: str = ""
    # 本决策是否来自模板缓存命中（False = 全量评估）。
    decision_cache_hit: bool = False
    # TTFT 批六：本次解析内注册表加载段（peek/get）耗时（毫秒）。绑定层用它
    # 把整段 resolve 拆成 registryMs 与决策段（cache key + 评估/命中重水化）。
    registry_ms: int = 0


# ---------------------------------------------------------------------------
# Turn-independent decision template cache (TTFT batch 5 task C)
#
# ``evaluate_tool_policy`` 的输出中只有 turn_id、generated_at 与
# decision_fingerprint（含 turnId）是回合相关的；其余（visible/executable/
# denied/approval_requirements）是以下回合无关输入的纯函数：
#   agent_id、policy 投影、grant 去掉 turnId 的投影、registry descriptors、
#   registry 版本/指纹、available_tool_names、externally_blocked_tools。
# （``_role_policy_projection`` 只读 ``agent_role_tool_profile_service`` 的
# 模块内常量表，无外部 I/O，因此 policy 投影由这些输入完全决定。）
# 对这些输入做 sha256 签名，签名未变时跳过全量 rule 评估，用模板重建本回合
# 决策（新 turn_id + 相同口径重算指纹）。策略/注册表/封禁名单任一变化都会
# 改变签名并自动失效。
# ---------------------------------------------------------------------------
_TURN_DECISION_TEMPLATE_CACHE_MAX = 16
_TURN_DECISION_TEMPLATE_LOCK = Lock()
_TURN_DECISION_TEMPLATES: "OrderedDict[str, tuple[AuthorizationDecision, dict[str, Any]]]" = OrderedDict()


def _fingerprint_canonical(value: Any) -> str:
    # 与 evaluator 的 _fingerprint 使用同一序列化参数，保证重建指纹与全量
    # 评估产生的指纹逐位一致（同包内私有复用，避免口径漂移）。
    from .tool_policy_evaluator import _fingerprint

    return _fingerprint(value)


def _descriptor_cache_projection(descriptors: Sequence[_RegistryDescriptor]) -> list[dict[str, Any]]:
    return [
        {
            "name": descriptor.name,
            "enabled": bool(descriptor.enabled),
            "capabilities": list(descriptor.capabilities),
            "risk": descriptor.risk,
            "approval": descriptor.approval,
            "aliases": list(descriptor.aliases),
            "writeScopeGated": bool(descriptor.write_scope_gated),
        }
        for descriptor in descriptors
    ]


def _turn_decision_cache_key(
    *,
    agent_id: str,
    policy: Any,
    grant: TurnToolGrant,
    descriptors: Sequence[_RegistryDescriptor],
    registry_version: int,
    registry_fingerprint: str,
    available_names: Sequence[str],
    externally_blocked_tools: Sequence[str],
) -> str:
    grant_projection = grant.public_projection()
    grant_projection.pop("turnId", None)
    payload = {
        "agentId": str(agent_id or "").strip(),
        "policy": policy.public_projection(),
        "grantBase": grant_projection,
        "descriptors": _descriptor_cache_projection(descriptors),
        "registryVersion": int(registry_version),
        "registryFingerprint": str(registry_fingerprint or "").strip(),
        "availableToolNames": sorted({str(name or "").strip() for name in available_names if str(name or "").strip()}),
        "externallyBlockedTools": sorted({str(name or "").strip() for name in externally_blocked_tools if str(name or "").strip()}),
    }
    return _fingerprint_canonical(payload)


def _rehydrate_turn_decision(
    template: AuthorizationDecision,
    *,
    policy_projection: Mapping[str, Any],
    grant: TurnToolGrant,
    registry_fingerprint: str,
    generated_at: str,
) -> AuthorizationDecision:
    """Rebuild one turn-scoped decision from a cached turn-independent template."""

    decision_payload = {
        "agentId": template.agent_id,
        "turnId": grant.turn_id,
        "policy": dict(policy_projection),
        "grant": grant.public_projection(),
        "registryVersion": template.registry_version,
        "registryFingerprint": str(registry_fingerprint or "").strip(),
        "visibleTools": list(template.visible_tools),
        "executableTools": list(template.executable_tools),
        "preferredTools": list(template.preferred_tools),
        "denied": {name: reason.public_projection() for name, reason in template.denied},
        "approvalRequirements": [list(item) for item in template.approval_requirements],
    }
    return replace(
        template,
        turn_id=grant.turn_id,
        generated_at=str(generated_at or ""),
        decision_fingerprint=_fingerprint_canonical(decision_payload),
    )


def _cached_turn_decision_template(key: str) -> tuple[AuthorizationDecision, dict[str, Any]] | None:
    with _TURN_DECISION_TEMPLATE_LOCK:
        entry = _TURN_DECISION_TEMPLATES.get(key)
        if entry is not None:
            _TURN_DECISION_TEMPLATES.move_to_end(key)
        return entry


def _store_turn_decision_template(key: str, decision: AuthorizationDecision, policy_projection: dict[str, Any]) -> None:
    with _TURN_DECISION_TEMPLATE_LOCK:
        _TURN_DECISION_TEMPLATES[key] = (decision, policy_projection)
        _TURN_DECISION_TEMPLATES.move_to_end(key)
        while len(_TURN_DECISION_TEMPLATES) > _TURN_DECISION_TEMPLATE_CACHE_MAX:
            _TURN_DECISION_TEMPLATES.popitem(last=False)


def clear_turn_decision_template_cache() -> None:
    """Drop all cached turn-decision templates (tests and explicit invalidation)."""

    with _TURN_DECISION_TEMPLATE_LOCK:
        _TURN_DECISION_TEMPLATES.clear()


# ---------------------------------------------------------------------------
# LLM identity fallback memo (TTFT batch 6)
#
# ``_runtime_llm_identity`` 在 runtime/快照带不出 model/provider 时回退到
# ``config.get_config().llm.get_profile(role="primary")``；该回退每次 install
# 都会走一遍 config 解析，是命中路径的已知嫌疑开销。memo 以 runtime 快照身份
# （configRevision + configHash，与执行面 agent_config_mismatch 闸门同一信任
# 口径）加上显式输入字段为键：同键必同内容，全局 config 变化必然推进
# revision/hash，因此不引入额外失效通道。无可信快照身份（revision<1 或缺
# hash）时不 memo，保持逐次解析；容量有界防漂移。
# ---------------------------------------------------------------------------
_LLM_IDENTITY_MEMO_MAX = 64
_LLM_IDENTITY_MEMO_LOCK = Lock()
_LLM_IDENTITY_MEMO: "OrderedDict[tuple[str, str, str, int, str], tuple[str, str, str]]" = OrderedDict()


def _llm_identity_memo_key(
    *,
    model: str,
    provider: str,
    profile_id: str,
    config_snapshot: Mapping[str, Any],
) -> tuple[str, str, str, int, str] | None:
    revision = _safe_int(config_snapshot.get("configRevision"), 0)
    config_hash = _coerce_text(config_snapshot.get("configHash")).strip()
    if revision < 1 or not config_hash:
        return None
    return (model, provider, profile_id, revision, config_hash)


def clear_llm_identity_memo() -> None:
    """Drop all cached LLM identity fallbacks (tests and explicit invalidation)."""

    with _LLM_IDENTITY_MEMO_LOCK:
        _LLM_IDENTITY_MEMO.clear()


def _resolve_authorization(
    *,
    runtime: Mapping[str, Any],
    registry_payload: Mapping[str, Any] | None = None,
    registry_loader: Callable[[], Mapping[str, Any]] | None = None,
    generated_at: str = "",
) -> AuthorizationReport:
    """Resolve one canonical decision without any legacy visibility input."""

    started = perf_counter()
    registry_started = perf_counter()
    loaded = registry_payload if registry_payload is not None else _load_registry_payload(registry_loader)
    registry_ms = (perf_counter() - registry_started) * 1000
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
    turn_cache_key = _turn_decision_cache_key(
        agent_id=_coerce_text(runtime_values.get("agentId") or agent.get("agentId")).strip(),
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=_safe_int(payload.get("registryVersion"), 0),
        registry_fingerprint=_coerce_text(payload.get("registryFingerprint")).strip(),
        available_names=available_names,
        externally_blocked_tools=externally_blocked_tools,
    )
    cached_template = _cached_turn_decision_template(turn_cache_key)
    if cached_template is not None:
        cached_decision, cached_policy_projection = cached_template
        decision = _rehydrate_turn_decision(
            cached_decision,
            policy_projection=cached_policy_projection,
            grant=grant,
            registry_fingerprint=_coerce_text(payload.get("registryFingerprint")).strip(),
            generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        )
    else:
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
        _store_turn_decision_template(turn_cache_key, decision, policy.public_projection())
    deny_counts = Counter(reason.code.value for _, reason in decision.denied)
    return AuthorizationReport(
        decision=decision,
        deny_code_counts=tuple(sorted(deny_counts.items())),
        registry_fingerprint=_coerce_text(payload.get("registryFingerprint")).strip(),
        duration_ms=max(0, int((perf_counter() - started) * 1000)),
        decision_cache_key=turn_cache_key,
        decision_cache_hit=cached_template is not None,
        registry_ms=max(0, int(registry_ms)),
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
        memo_key = _llm_identity_memo_key(
            model=model,
            provider=provider,
            profile_id=profile_id,
            config_snapshot=config_snapshot,
        )
        if memo_key is not None:
            with _LLM_IDENTITY_MEMO_LOCK:
                cached = _LLM_IDENTITY_MEMO.get(memo_key)
                if cached is not None:
                    _LLM_IDENTITY_MEMO.move_to_end(memo_key)
                    return cached
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
        if memo_key is not None:
            with _LLM_IDENTITY_MEMO_LOCK:
                _LLM_IDENTITY_MEMO[memo_key] = (model, provider, profile_id)
                _LLM_IDENTITY_MEMO.move_to_end(memo_key)
                while len(_LLM_IDENTITY_MEMO) > _LLM_IDENTITY_MEMO_MAX:
                    _LLM_IDENTITY_MEMO.popitem(last=False)
    return model, provider, profile_id


def _deny_rules_from_decision(decision: Any) -> tuple[tuple[str, str, str], ...]:
    """Bound (toolName, reasonCode, ruleId) triples for execution-time audit."""

    rules: list[tuple[str, str, str]] = []
    for item in tuple(getattr(decision, "denied", ()) or ())[:MAX_DENY_RULES_IN_CONTEXT]:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        name, reason = item
        code = getattr(reason, "code", "")
        rules.append(
            (
                _coerce_text(name).strip(),
                _coerce_text(getattr(code, "value", code)).strip(),
                _coerce_text(getattr(reason, "rule_id", "")).strip(),
            )
        )
    return tuple(rules)


# ---------------------------------------------------------------------------
# Session budget override memo (TTFT batch 7)
#
# 批七 install 拆锚实测：``_session_override_max_calls_per_turn`` 每回合经
# ``get_session_budget_parameters`` 做一次 session store 读 + agent registry
# 读，是 installMs 64-220ms 的主要来源（读缓存在每轮 chat-state 写后被
# epoch 失效，稳态回合近似每轮真实 I/O）。memo 以可信快照身份
# （sessionId + agentId + configRevision + configHash）为键：会话预算
# override 存放在绑定 Agent 的 registry metadata 下，写路径以该 Agent 的
# ``configRevision`` compare-and-swap 守护（见 session_budget_resolve 模块
# 注释），override 变化必然推进 revision；session 重绑会改变 runtime 投影的
# agentId。因此同键必同内容，无需额外失效通道。无可信快照身份（revision<1
# 或缺 hash）或缺 sessionId/agentId 时不 memo，保持逐次解析；容量有界防漂
# 移。读失败的负例（0）同样按快照身份缓存：真实 override 变更必然推进
# revision 产生新键，不会被打断可见性。
#
# 缓存值同时绑定解析函数的对象同一性（``is``）：生产进程中模块级解析函数
# 恒定，命中不受影响；同键下解析函数被替换（测试 monkeypatch、热修复）时
# 视为 miss 重新解析，杜绝「同键不同源」的串值命中。
# ---------------------------------------------------------------------------
_SESSION_OVERRIDE_MEMO_MAX = 64
_SESSION_OVERRIDE_MEMO_LOCK = Lock()
_SESSION_OVERRIDE_MEMO: "OrderedDict[tuple[str, str, int, str], tuple[Any, int]]" = OrderedDict()


def _session_override_memo_key(
    *,
    session_id: str,
    agent_id: str,
    config_snapshot: Mapping[str, Any],
) -> tuple[str, str, int, str] | None:
    if not session_id or not agent_id:
        return None
    revision = _safe_int(config_snapshot.get("configRevision"), 0)
    config_hash = _coerce_text(config_snapshot.get("configHash")).strip()
    if revision < 1 or not config_hash:
        return None
    return (session_id, agent_id, revision, config_hash)


def clear_session_override_memo() -> None:
    """Drop all cached session budget overrides (tests and explicit invalidation)."""

    with _SESSION_OVERRIDE_MEMO_LOCK:
        _SESSION_OVERRIDE_MEMO.clear()


def _session_override_max_calls_per_turn(runtime: Mapping[str, Any]) -> int | None:
    """Session-configured maxCallsPerTurn override (session > family > base).

    Returns ``None`` when no override applies and ``0`` when the session
    explicitly disables the per-turn cap; both differ from a positive quota.

    Best-effort: unknown sessions, missing bindings, and read failures keep the
    family/base resolution already computed by the caller. Repeat lookups for
    one stable (sessionId, agentId, configRevision, configHash) identity are
    served from the bounded memo above.
    """

    session_id = _coerce_text(runtime.get("sessionId")).strip()
    if not session_id:
        agent = _as_mapping(runtime.get("agent"))
        session_id = _coerce_text(agent.get("directSessionId")).strip()
    if not session_id:
        return None
    agent_id = _coerce_text(runtime.get("agentId")).strip()
    if not agent_id:
        agent = _as_mapping(runtime.get("agent"))
        agent_id = _coerce_text(agent.get("agentId")).strip()
    memo_key = _session_override_memo_key(
        session_id=session_id,
        agent_id=agent_id,
        config_snapshot=_as_mapping(runtime.get("agentConfigSnapshot")),
    )
    try:
        from core.orchestration.session_budget_resolve import get_session_budget_parameters
    except Exception:  # noqa: BLE001 - override lookup must never break install
        return None
    if memo_key is not None:
        with _SESSION_OVERRIDE_MEMO_LOCK:
            cached = _SESSION_OVERRIDE_MEMO.get(memo_key)
            if cached is not None and cached[0] is get_session_budget_parameters:
                _SESSION_OVERRIDE_MEMO.move_to_end(memo_key)
                return cached[1]
    try:
        parameters = get_session_budget_parameters(session_id)
    except Exception:  # noqa: BLE001 - override lookup must never break install
        return None
    value = parameters.maxCallsPerTurn if parameters is not None else None
    try:
        resolved = int(value) if value is not None else None
    except (TypeError, ValueError):
        resolved = None
    if memo_key is not None:
        with _SESSION_OVERRIDE_MEMO_LOCK:
            _SESSION_OVERRIDE_MEMO[memo_key] = (get_session_budget_parameters, resolved)
            _SESSION_OVERRIDE_MEMO.move_to_end(memo_key)
            while len(_SESSION_OVERRIDE_MEMO) > _SESSION_OVERRIDE_MEMO_MAX:
                _SESSION_OVERRIDE_MEMO.popitem(last=False)
    return resolved


# ---------------------------------------------------------------------------
# Install sub-anchor timing (TTFT batch 7)
#
# 批六拆锚实测 installMs 64-220ms 是回合授权链路唯一大头，但 install 内部
# 无段级归因。这里把 install 三段耗时写入线程局部，由绑定层在
# ``install_execution_authorization`` 返回后读取并并入
# ``tool.authorization.timing`` 事件（扩展字段，不另开事件通道）：
# ``identityMs`` = LLM 身份解析（含 config 回退与 memo）；``maxCallsMs`` =
# 回合预算解析（family/base + session override 查询）；``installCoreMs`` =
# 执行上下文构建 + 身份闸门校验 + ContextVar 安装。仅计时，不参与任何决策。
# ---------------------------------------------------------------------------
_INSTALL_TIMING = local()


def last_install_execution_timing() -> dict[str, int] | None:
    """Return the current thread's most recent install sub-anchor timing."""

    identity_ms = getattr(_INSTALL_TIMING, "identityMs", None)
    if not isinstance(identity_ms, (int, float)):
        return None
    return {
        "identityMs": max(0, int(identity_ms)),
        "maxCallsMs": max(0, int(getattr(_INSTALL_TIMING, "maxCallsMs", 0) or 0)),
        "installCoreMs": max(0, int(getattr(_INSTALL_TIMING, "installCoreMs", 0) or 0)),
    }


def install_execution_authorization(
    report: AuthorizationReport,
    runtime: Mapping[str, Any] | None = None,
) -> ToolExecutionAuthorizationContext:
    """Install one turn-scoped execution context.

    ``runtime`` 由绑定层传入 bind 阶段已取到的 runtime 投影，消掉本函数原本
    的第二次 ``current_agent_runtime()`` getter；缺省 None 时保持旧行为
    （自行从 current_agent_runtime 读取），供独立调用方使用。
    """

    from core.orchestration.tool_budget_profiles import resolve_max_calls_per_turn

    decision = report.decision
    if runtime is None:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = _as_mapping(current_agent_runtime())
    else:
        runtime = _as_mapping(runtime)
    policy = runtime.get("toolPolicy")
    if policy is None:
        policy = runtime.get("tool_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    config_snapshot = _as_mapping(runtime.get("agentConfigSnapshot"))
    phase_started = perf_counter()
    model, provider, profile_id = _runtime_llm_identity(runtime)
    identity_ms = (perf_counter() - phase_started) * 1000
    phase_started = perf_counter()
    max_calls_per_turn, budget_profile = resolve_max_calls_per_turn(
        policy,
        model=model,
        provider=provider,
        profile_id=profile_id,
    )
    # Session-configured override wins over the family/base resolution; the
    # installed cap is the one the Turn Status Bar displays as the final value.
    session_max_calls = _session_override_max_calls_per_turn(runtime)
    # 0 is an explicit 'no cap' from the session; None means no override.
    if session_max_calls is not None:
        max_calls_per_turn = session_max_calls
    max_calls_ms = (perf_counter() - phase_started) * 1000
    phase_started = perf_counter()
    context = ToolExecutionAuthorizationContext(
        agent_id=_coerce_text(decision.agent_id).strip(),
        turn_id=_coerce_text(decision.turn_id).strip(),
        decision_fingerprint=_coerce_text(decision.decision_fingerprint).strip(),
        config_revision=_safe_int(config_snapshot.get("configRevision"), 0),
        config_hash=_coerce_text(config_snapshot.get("configHash")).strip(),
        permission_preset=_coerce_text(runtime.get("permissionPreset")).strip(),
        executable_tools=tuple(decision.executable_tools),
        approval_requirements=tuple(getattr(decision, "approval_requirements", ()) or ()),
        deny_rules=_deny_rules_from_decision(decision),
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
    _INSTALL_TIMING.identityMs = max(0, identity_ms)
    _INSTALL_TIMING.maxCallsMs = max(0, max_calls_ms)
    _INSTALL_TIMING.installCoreMs = max(0, (perf_counter() - phase_started) * 1000)
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
    normalized_tool = _coerce_text(tool_name).strip()
    context = current_execution_authorization()
    if context is None:
        return _execution_denial(
            "missing_decision",
            "当前 Agent 缺少可信工具授权决策。",
            runtime_agent_id,
            runtime_turn_id,
            tool_name=normalized_tool,
        )
    if not _coerce_text(tool_call_id).strip():
        return _execution_denial(
            "missing_call_id",
            "当前工具调用缺少 callId。",
            runtime_agent_id,
            runtime_turn_id,
            context,
            tool_name=normalized_tool,
        )
    if context.agent_id != runtime_agent_id:
        return _execution_denial(
            "agent_mismatch",
            "工具授权决策不属于当前 Agent。",
            runtime_agent_id,
            runtime_turn_id,
            context,
            tool_name=normalized_tool,
        )
    if runtime_turn_id and context.turn_id != runtime_turn_id:
        return _execution_denial(
            "turn_mismatch",
            "工具授权决策不属于当前回合。",
            runtime_agent_id,
            runtime_turn_id,
            context,
            tool_name=normalized_tool,
        )
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
            tool_name=normalized_tool,
        )
    if normalized_tool not in set(context.executable_tools):
        return _execution_denial(
            "tool_not_executable",
            "当前工具未被本回合授权执行。",
            runtime_agent_id,
            runtime_turn_id,
            context,
            tool_name=normalized_tool,
        )
    from core.agent_plugins.runtime_extensions import agent_plugin_tool_execution_denial

    plugin_denial = agent_plugin_tool_execution_denial(runtime, normalized_tool)
    if plugin_denial:
        return _execution_denial(
            "agent_plugin_execution_denied", plugin_denial,
            runtime_agent_id, runtime_turn_id, context, tool_name=normalized_tool,
        )
    constraint_denial = _runtime_constraint_denial(runtime, normalized_tool, tool_args or {})
    if constraint_denial:
        code, detail = constraint_denial
        return _execution_denial(
            code,
            detail,
            runtime_agent_id,
            runtime_turn_id,
            context,
            tool_name=normalized_tool,
        )
    collaboration = _collaboration_decision(runtime, normalized_tool, tool_args or {})
    if collaboration is not None and collaboration.decision == "deny":
        _record_execution_denial_reason(
            tool_name=normalized_tool,
            gate_id="collaboration_mode_denied",
            reason_code="",
            rule_id=collaboration.rule_id,
            agent_id=runtime_agent_id,
            turn_id=runtime_turn_id,
            context=context,
        )
        return ToolExecutionAuthorizationResult(
            enforced=True,
            allowed=False,
            code="collaboration_mode_denied",
            message=collaboration.reason,
            agent_id=runtime_agent_id,
            turn_id=runtime_turn_id,
            decision_fingerprint=context.decision_fingerprint,
            rule_id=collaboration.rule_id,
        )
    from core.web.services.agent_perception.access import legacy_tool_read_denial, current_perception_turn

    perception_turn = current_perception_turn()
    if (perception_turn is not None and perception_turn.trigger == "background"
            and normalized_tool not in {"unified_memory_search_tool", "search_agent_private_memory_tool",
                                        "github_project_library_search_tool", "read_knowledge_item_tool"}):
        return _execution_denial(
            "perception_background_read_only", "后台感知只允许已授权来源的只读检索。",
            runtime_agent_id, runtime_turn_id, context, tool_name=normalized_tool,
        )
    perception_denial = legacy_tool_read_denial(normalized_tool, runtime_agent_id, dict(tool_args or {}))
    if perception_denial:
        return _execution_denial(
            "perception_read_denied", "当前感知设置不允许此来源读取：" + perception_denial,
            runtime_agent_id, runtime_turn_id, context, tool_name=normalized_tool,
        )
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
                    tool_name=normalized_tool,
                )
            count = context.terminal_wait_counts.get(terminal_wait_session_id, 0)
            if count >= MAX_TERMINAL_WAITS_PER_SESSION:
                return _execution_denial(
                    "terminal_wait_budget_exhausted",
                    "当前终端会话的轮询次数已用尽。",
                    runtime_agent_id,
                    runtime_turn_id,
                    context,
                    tool_name=normalized_tool,
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
                    tool_name=normalized_tool,
                )
        elif context.max_calls_per_turn > 0 and context.call_count >= context.max_calls_per_turn:
            return _execution_denial(
                "call_budget_exhausted",
                "当前回合工具调用额度已用尽。",
                runtime_agent_id,
                runtime_turn_id,
                context,
                tool_name=normalized_tool,
            )
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
    if collaboration is not None and collaboration.decision == "allow":
        approval_requirement = None
    elif collaboration is not None and collaboration.decision == "ask" and approval_requirement is None:
        approval_requirement = ("always", "low")
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
                tool_name=normalized_tool,
            )
        if not approval_outcome.allowed:
            # 额度在审批等待前已预扣（见上方 call_count_lock 段），但被拒/超时/
            # 取消的调用没有执行任何工具：退还这一格，否则零执行也能撞熔断。
            # 交付豁免类走独立计数、未动 call_count，不退。
            if not _is_delivery_exempt_tool(normalized_tool):
                with context.call_count_lock:
                    context.call_count = max(0, context.call_count - 1)
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
    from core.web.services.agent_perception.runtime import charge_perception_tool_call

    try:
        budget_allowed = charge_perception_tool_call()
    except (RuntimeError, ValueError, PermissionError):
        budget_allowed = False
    if budget_allowed is False:
        return _execution_denial(
            "perception_budget_exhausted", "后台感知已停止或本次工具额度已用尽。",
            runtime_agent_id, runtime_turn_id, context, tool_name=normalized_tool,
        )
    return ToolExecutionAuthorizationResult(
        enforced=True,
        allowed=True,
        code=approval_code,
        message="",
        agent_id=context.agent_id,
        turn_id=context.turn_id,
        decision_fingerprint=context.decision_fingerprint,
    )


def _collaboration_decision(runtime: Mapping[str, Any], tool_name: str, tool_args: Mapping[str, Any]):
    embedded = runtime.get("collaborationMode")
    session_id = _coerce_text(runtime.get("sessionId")).strip()
    if not isinstance(embedded, Mapping) and not session_id:
        return None
    from core.authorization.collaboration_mode import check_collaboration_mode, normalize_collaboration_state

    if isinstance(embedded, Mapping):
        state = normalize_collaboration_state(embedded)
    else:
        from core.web.services.session.collaboration_mode import load_collaboration_state

        try:
            state = load_collaboration_state(session_id)
        except Exception:
            return None
    return check_collaboration_mode(state, tool_name, tool_args=tool_args)


def _runtime_constraint_denial(
    runtime: Mapping[str, Any],
    tool_name: str,
    tool_args: Mapping[str, Any],
) -> tuple[str, str] | None:
    del tool_args
    from core.web.services.agent_directory_service import (
        SUBAGENT_DELEGATION_TOOL_NAMES,
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
    *,
    tool_name: str = "",
) -> ToolExecutionAuthorizationResult:
    normalized_tool = _coerce_text(tool_name).strip()
    reason_code, rule_id = _decision_deny_rule_for(context, normalized_tool)
    _record_execution_denial_reason(
        tool_name=normalized_tool,
        gate_id=code,
        reason_code=reason_code,
        rule_id=rule_id,
        agent_id=agent_id,
        turn_id=turn_id,
        context=context,
    )
    return ToolExecutionAuthorizationResult(
        enforced=True,
        allowed=False,
        code=code,
        message=f"[工具授权] {detail} 请刷新 Agent 工具配置后重试。",
        agent_id=agent_id,
        turn_id=turn_id,
        decision_fingerprint=str(getattr(context, "decision_fingerprint", "") or ""),
        reason_code=reason_code,
        rule_id=rule_id,
    )


def _decision_deny_rule_for(
    context: ToolExecutionAuthorizationContext | None,
    tool_name: str,
) -> tuple[str, str]:
    """Resolve the decision-level deny rule (reasonCode, ruleId) for one tool."""

    if context is None or not tool_name:
        return "", ""
    for name, reason_code, rule_id in tuple(getattr(context, "deny_rules", ()) or ()):
        if name == tool_name:
            return reason_code, rule_id
    return "", ""


def _record_execution_denial_reason(
    *,
    tool_name: str,
    gate_id: str,
    reason_code: str,
    rule_id: str,
    agent_id: str,
    turn_id: str,
    context: ToolExecutionAuthorizationContext | None,
) -> None:
    try:
        from core.logging.tool_authorization_events import record_execution_denial_reason

        record_execution_denial_reason(
            tool_name=tool_name,
            gate_id=gate_id,
            reason_code=reason_code,
            rule_id=rule_id,
            agent_id=agent_id,
            turn_id=turn_id,
            decision_fingerprint=str(getattr(context, "decision_fingerprint", "") or ""),
        )
    except Exception:
        return


def _load_registry_payload(registry_loader: Callable[[], Mapping[str, Any]] | None) -> Mapping[str, Any]:
    if registry_loader is not None:
        return registry_loader()
    # 热态优先走签名校验后的共享缓存（只读、无深拷贝）；未命中再全量取。
    from core.web.services.tool_registry_service import get_tool_registry, peek_cached_tool_registry

    return peek_cached_tool_registry() or get_tool_registry()


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
                write_scope_gated=_coerce_bool(item.get("writeScopeGated"), True),
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
