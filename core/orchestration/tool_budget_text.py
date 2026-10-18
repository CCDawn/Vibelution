# -*- coding: utf-8 -*-
"""Prompt 侧工具回合预算终值解析（与授权层同一优先级链）。

授权层 ``install_execution_authorization`` 的执行额度按
「会话覆盖（sessionBudgetParameters）> 模型家族解析
（``tool_budget_profiles.resolve_max_calls_per_turn``）> 策略 base」得到。
所有把数字写进 prompt 的表面（SPEC_DIGEST / ENV_INFO / runtime goal 包 /
Agent Runtime Context 投影）必须读同一终值，禁止引用策略 base 或写死
"常见 32 次"，否则同一上下文里 prompt 数字与执行额度自相矛盾。

本模块是这些表面的共享读路径：import 保持轻量，web/authorization 服务
只在函数内 late-bind；任何读取失败都退回无身份/无覆盖的保守解析，
绝不让预算文案计算打断回合。
"""

from __future__ import annotations

from typing import Any, Mapping

from core.orchestration.tool_budget_profiles import resolve_max_calls_per_turn


def _as_mapping(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def llm_identity_from_runtime(runtime: Mapping[str, Any] | None) -> tuple[str, str, str]:
    """从运行时映射提取 (model, provider, profile_id)。

    直接复用授权层的 ``_runtime_llm_identity``（含 config primary 兜底），
    保证 prompt 侧与执行侧永远用同一套身份推导，不复制第二份逻辑。
    仅在 runtime 非空时调用；导入失败或异常时返回空身份（家族退回
    default，策略 base 原样保留）。
    """

    if not isinstance(runtime, Mapping) or not runtime:
        return "", "", ""
    try:
        from core.authorization.tool_authorization_service import _runtime_llm_identity

        model, provider, profile_id = _runtime_llm_identity(runtime)
        return (
            _coerce_text(model).strip(),
            _coerce_text(provider).strip(),
            _coerce_text(profile_id).strip(),
        )
    except Exception:  # noqa: BLE001 - 身份提取必须 best-effort
        return "", "", ""


def session_id_from_runtime(runtime: Mapping[str, Any] | None) -> str:
    """按授权层同款键序提取会话 ID（runtime.sessionId > agent.directSessionId）。"""

    if not isinstance(runtime, Mapping):
        return ""
    session_id = _coerce_text(runtime.get("sessionId")).strip()
    if not session_id:
        agent = _as_mapping(runtime.get("agent"))
        session_id = _coerce_text(agent.get("directSessionId")).strip()
    return session_id


def _session_override_max_calls(session_id: str) -> int:
    """会话级 maxCallsPerTurn 覆盖；未知/未配置/读取失败返回 0（不覆盖）。"""

    if not session_id:
        return 0
    try:
        from core.orchestration.session_budget_resolve import get_session_budget_parameters

        parameters = get_session_budget_parameters(session_id)
    except Exception:  # noqa: BLE001 - 覆盖读取必须 best-effort
        return 0
    value = parameters.maxCallsPerTurn if parameters is not None else None
    try:
        return int(value) if value else 0
    except (TypeError, ValueError):
        return 0


def resolve_effective_max_calls_per_turn(
    tool_policy: Mapping[str, Any] | None = None,
    *,
    model: str = "",
    provider: str = "",
    profile_id: str = "",
    session_id: str = "",
    runtime: Mapping[str, Any] | None = None,
) -> tuple[int, str]:
    """解析回合工具额度终值：会话覆盖 > 家族解析 > 策略 base。

    与授权层 ``install_execution_authorization`` 的优先级逐字对齐：
    先 ``resolve_max_calls_per_turn``（base + 家族覆盖），再让会话覆盖
    整体替换。返回 ``(max_calls_per_turn, family)``；0 表示未解析到
    上限（unlimited），调用方文案不得给出猜测数字。
    """

    if not (model or provider or profile_id):
        model, provider, profile_id = llm_identity_from_runtime(runtime)
    max_calls, family = resolve_max_calls_per_turn(
        tool_policy,
        model=model,
        provider=provider,
        profile_id=profile_id,
    )
    resolved_session_id = _coerce_text(session_id).strip() or session_id_from_runtime(runtime)
    if resolved_session_id:
        session_override = _session_override_max_calls(resolved_session_id)
        if session_override > 0:
            max_calls = session_override
    return max_calls, family


def resolve_current_runtime_max_calls_per_turn(
    tool_policy: Mapping[str, Any] | None = None,
) -> tuple[int, str]:
    """从当前 Agent 运行时上下文解析终值（prompt 章节的便捷入口）。

    runtime 非空时身份推导与授权层完全一致；runtime 为空（测试、
    无上下文流程）时不做 config 兜底，家族退回 default、base 原样
    保留。``tool_policy`` 缺省时优先使用 runtime 携带的生效 toolPolicy。
    """

    runtime: Mapping[str, Any] | None = None
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        candidate = current_agent_runtime()
        if isinstance(candidate, dict) and candidate:
            runtime = candidate
            if tool_policy is None:
                policy = candidate.get("toolPolicy") or candidate.get("tool_policy")
                if isinstance(policy, Mapping):
                    tool_policy = policy
    except Exception:  # noqa: BLE001 - 运行时读取必须 best-effort
        runtime = None
    return resolve_effective_max_calls_per_turn(tool_policy, runtime=runtime)


def resolve_agent_scoped_max_calls_per_turn(
    agent: Mapping[str, Any] | None,
    tool_policy: Mapping[str, Any] | None = None,
    *,
    agent_id: str = "",
) -> tuple[int, str]:
    """Agent 快照视角的终值解析（Agent Runtime Context 投影入口）。

    ambient 运行时属于同一 agent 时优先用它（与授权层读到的身份、
    会话完全同源）；否则退回 ``{"agent": agent}`` 快照——身份与授权层
    一样走 config primary 兜底，会话覆盖读 agent.directSessionId。
    """

    snapshot = _as_mapping(agent)
    target_id = (
        _coerce_text(agent_id).strip()
        or _coerce_text(snapshot.get("agentId")).strip()
    )
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        ambient = current_agent_runtime()
        if isinstance(ambient, dict) and ambient:
            ambient_id = _coerce_text(ambient.get("agentId")).strip()
            if not target_id or ambient_id == target_id:
                return resolve_effective_max_calls_per_turn(tool_policy, runtime=ambient)
    except Exception:  # noqa: BLE001 - 运行时读取必须 best-effort
        pass
    return resolve_effective_max_calls_per_turn(tool_policy, runtime={"agent": snapshot})


__all__ = [
    "llm_identity_from_runtime",
    "resolve_agent_scoped_max_calls_per_turn",
    "resolve_current_runtime_max_calls_per_turn",
    "resolve_effective_max_calls_per_turn",
    "session_id_from_runtime",
]
