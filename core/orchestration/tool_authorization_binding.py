# -*- coding: utf-8 -*-
"""Agent-side authorization binding. Policy stays in core.authorization."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from core.orchestration.agent_runtime_bindings import _turn_runtime_from_env


TurnRuntimeFn = Callable[[], Dict[str, Any]]
CurrentRuntimeFn = Callable[[], Any]

RESTART_ALLOWED_TOOL_NAMES: tuple[str, ...] = (
    "task_create_tool",
    "task_update_tool",
    "task_list_tool",
    "get_current_goal_tool",
    "get_core_context_tool",
    "get_memory_summary_tool",
    "trigger_self_restart_tool",
    "close_evolution_transaction_tool",
)

HIDDEN_TOOL_CALL_MESSAGE = (
    "[工具可见性提示] `{name}` 未暴露给当前 Agent。"
    "请只使用当前工具 schema 或工具索引中列出的工具；"
    "如果确实需要该能力，请让用户或能力管家调整该 Agent 的 ToolPolicy。"
)

RESTART_FOCUS_GUARD_MESSAGE = (
    "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。"
    "请优先：创建任务 -> 勾选任务 -> 调用 trigger_self_restart_tool。"
)

# ---------------------------------------------------------------------------
# Turn authorization telemetry + scene-event dedupe (TTFT batch 5 task C)
#
# 会话热态每 turn 的 resolve_turn_authorization 在输入（agent 策略/注册表/
# 封禁名单）未变时会产出与上一回合内容完全相同的决策，并每次写两条
# runtime_scene 事件（tool.authorization.decision / decision_reasons）。
# 消费者核查：前端与后端没有依赖这两条事件「每轮出现」的读取方（时间线
# 展示用途）；执行面按调用粒度仍有 tool.authorization.execution_* 事件，
# 回合诊断仍携带 decision fingerprint。因此当决策来自 turn 无关模板缓存
# 且与上一次已记录的决策签名一致时跳过重复写事件；输入或决策变化立即
# 恢复记录（下一次变化后的首轮回合）。
# ---------------------------------------------------------------------------
_TURN_AUTHORIZATION_TIMING = threading.local()
_RECORDED_DECISION_KEYS_LOCK = threading.Lock()
_RECORDED_DECISION_KEYS: Dict[str, str] = {}
_RECORDED_DECISION_KEYS_MAX = 64


def _record_turn_authorization_timing(
    duration_ms: float,
    *,
    cache_hit: bool,
    bind_ms: float = 0.0,
    registry_ms: float = 0.0,
    resolve_ms: float = 0.0,
    install_ms: float = 0.0,
    record_ms: float = 0.0,
    identity_ms: float = 0.0,
    max_calls_ms: float = 0.0,
    install_core_ms: float = 0.0,
) -> None:
    _TURN_AUTHORIZATION_TIMING.durationMs = max(0, int(duration_ms))
    _TURN_AUTHORIZATION_TIMING.cacheHit = bool(cache_hit)
    # TTFT 批六子锚点：与 durationMs 同源于一次 resolve_turn_authorization，
    # 供命中路径 144-570ms 缺口做段级归因。
    _TURN_AUTHORIZATION_TIMING.bindMs = max(0, int(bind_ms))
    _TURN_AUTHORIZATION_TIMING.registryMs = max(0, int(registry_ms))
    _TURN_AUTHORIZATION_TIMING.resolveMs = max(0, int(resolve_ms))
    _TURN_AUTHORIZATION_TIMING.installMs = max(0, int(install_ms))
    _TURN_AUTHORIZATION_TIMING.recordMs = max(0, int(record_ms))
    # TTFT 批七 install 内部细分：由 install 层线程局部上报，installMs ≥ 三者之和。
    _TURN_AUTHORIZATION_TIMING.identityMs = max(0, int(identity_ms))
    _TURN_AUTHORIZATION_TIMING.maxCallsMs = max(0, int(max_calls_ms))
    _TURN_AUTHORIZATION_TIMING.installCoreMs = max(0, int(install_core_ms))
    _TURN_AUTHORIZATION_TIMING.recordedAtMonotonic = time.monotonic()


def last_turn_authorization_timing() -> Dict[str, Any] | None:
    """Return the current thread's most recent turn-authorization telemetry."""

    duration_ms = getattr(_TURN_AUTHORIZATION_TIMING, "durationMs", None)
    if not isinstance(duration_ms, (int, float)):
        return None
    return {
        "turnAuthorizationMs": int(duration_ms),
        "turnAuthorizationCacheHit": bool(getattr(_TURN_AUTHORIZATION_TIMING, "cacheHit", False)),
        "recordedAtMonotonic": float(getattr(_TURN_AUTHORIZATION_TIMING, "recordedAtMonotonic", 0.0) or 0.0),
        # 子锚点（毫秒整数）；journal 白名单暂不消费，scene timing 事件使用。
        "bindMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "bindMs", 0) or 0)),
        "registryMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "registryMs", 0) or 0)),
        "resolveMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "resolveMs", 0) or 0)),
        "installMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "installMs", 0) or 0)),
        "recordMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "recordMs", 0) or 0)),
        "identityMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "identityMs", 0) or 0)),
        "maxCallsMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "maxCallsMs", 0) or 0)),
        "installCoreMs": max(0, int(getattr(_TURN_AUTHORIZATION_TIMING, "installCoreMs", 0) or 0)),
    }


def clear_turn_authorization_telemetry_state() -> None:
    """Reset dedupe markers and thread telemetry (tests and explicit resets)."""

    with _RECORDED_DECISION_KEYS_LOCK:
        _RECORDED_DECISION_KEYS.clear()
    for attribute in (
        "durationMs",
        "cacheHit",
        "recordedAtMonotonic",
        "bindMs",
        "registryMs",
        "resolveMs",
        "installMs",
        "recordMs",
        "identityMs",
        "maxCallsMs",
        "installCoreMs",
    ):
        try:
            delattr(_TURN_AUTHORIZATION_TIMING, attribute)
        except AttributeError:
            pass


def _decision_already_recorded(agent_id: str, decision_cache_key: str) -> bool:
    if not decision_cache_key:
        return False
    with _RECORDED_DECISION_KEYS_LOCK:
        return _RECORDED_DECISION_KEYS.get(agent_id) == decision_cache_key


def _mark_decision_recorded(agent_id: str, decision_cache_key: str) -> None:
    with _RECORDED_DECISION_KEYS_LOCK:
        _RECORDED_DECISION_KEYS[agent_id] = str(decision_cache_key or "")
        while len(_RECORDED_DECISION_KEYS) > _RECORDED_DECISION_KEYS_MAX:
            oldest = next(iter(_RECORDED_DECISION_KEYS))
            _RECORDED_DECISION_KEYS.pop(oldest)


def _decode_binary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def _maybe_json(value: Any) -> Any:
    value = _decode_binary(value)
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    value = _decode_binary(value)
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value = _decode_binary(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _flag_enabled(value: Any, default: bool = True) -> bool:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        nested = value.get("enabled")
        if nested is None:
            nested = value.get("visible")
        if nested is None:
            nested = value.get("allowed")
        return _coerce_bool(nested, default)
    return _coerce_bool(value, default)


_IDENTITY_KEYS = (
    "agentId",
    "agent_id",
    "turnId",
    "turn_id",
    "runId",
    "run_id",
    "mode",
    "directSessionId",
    "direct_session_id",
)
_RUNTIME_ENVELOPES = ("runtime", "payload", "config", "binding", "current")
_TOOL_LIST_KEYS = ("tools", "visible_tools", "visibleTools", "items", "names")


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if not isinstance(value, Mapping):
        return {}
    mapping = dict(value)
    if any(key in mapping for key in _IDENTITY_KEYS):
        return mapping
    for envelope in _RUNTIME_ENVELOPES:
        if envelope not in mapping:
            continue
        nested = _coerce_mapping(mapping.get(envelope))
        if nested:
            return nested
    return mapping


def _tool_name_set(items: Iterable[Any] | None) -> set[str]:
    names: set[str] = set()
    items = _maybe_json(items)
    if items is None:
        return names
    if isinstance(items, (str, bytes, bytearray, memoryview)):
        text = _coerce_text(items).strip()
        if not text:
            return names
        parsed = _maybe_json(text)
        if parsed is not text and not isinstance(parsed, (str, bytes, bytearray, memoryview)):
            return _tool_name_set(parsed)
        names.add(text)
        return names
    if isinstance(items, Mapping):
        for key in _TOOL_LIST_KEYS:
            if key not in items:
                continue
            nested = items.get(key)
            if nested is None or isinstance(nested, (bool, int, float)):
                continue
            return _tool_name_set(nested)
        tool_name = items.get("name")
        if tool_name is None:
            tool_name = items.get("id")
        if tool_name is not None and not any(key in items for key in _TOOL_LIST_KEYS):
            if not _flag_enabled(items, True):
                return set()
            name = _coerce_text(tool_name).strip()
            return {name} if name else set()
        for key, enabled in items.items():
            name = _coerce_text(key).strip()
            if name and _flag_enabled(enabled, True):
                names.add(name)
        return names
    try:
        iterator = list(items)
    except TypeError:
        name = _coerce_text(getattr(items, "name", items)).strip()
        return {name} if name else set()
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            names.update(_tool_name_set(item))
            continue
        name = _coerce_text(getattr(item, "name", item)).strip()
        if name:
            names.add(name)
    return names


def bind_authorization_runtime(
    *,
    current_runtime: Dict[str, Any] | None,
    turn_runtime: Dict[str, Any] | None,
    agent_binding: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Fill identity fields for the canonical authorization service. No policy."""
    runtime = _coerce_mapping(current_runtime)
    turn = _coerce_mapping(turn_runtime)
    binding = _coerce_mapping(agent_binding)

    def _first(*values: Any) -> str:
        for value in values:
            text = _coerce_text(value).strip()
            if text:
                return text
        return ""

    agent_id = _first(
        runtime.get("agentId"),
        runtime.get("agent_id"),
        turn.get("agentId"),
        turn.get("agent_id"),
        binding.get("agentId"),
        binding.get("agent_id"),
    )
    turn_id = _first(
        runtime.get("turnId"),
        runtime.get("turn_id"),
        turn.get("turnId"),
        turn.get("turn_id"),
        turn.get("runId"),
        turn.get("run_id"),
        binding.get("directSessionId"),
        binding.get("direct_session_id"),
        f"agent-bootstrap:{agent_id}" if agent_id else "",
    )
    run_id = _first(
        runtime.get("runId"),
        runtime.get("run_id"),
        turn.get("runId"),
        turn.get("run_id"),
    )
    mode = _first(runtime.get("mode"), turn.get("mode"))
    if agent_id:
        runtime["agentId"] = agent_id
    if turn_id:
        runtime["turnId"] = turn_id
    if run_id:
        runtime["runId"] = run_id
    if mode:
        runtime["mode"] = mode
    return runtime


def resolve_turn_authorization(
    *,
    runtime_agent_binding: Dict[str, Any] | None = None,
    turn_runtime_fn: TurnRuntimeFn | None = None,
    current_runtime_fn: CurrentRuntimeFn | None = None,
) -> Any:
    """Bind runtime identity and call the canonical authorization service."""

    started = time.perf_counter()
    runtime: Dict[str, Any] = {}
    bind_ms = registry_ms = resolve_ms = install_ms = record_ms = 0.0
    try:
        from core.authorization.tool_authorization_service import (
            install_execution_authorization,
            last_install_execution_timing,
            resolve_enforced_authorization,
        )
        from core.logging.tool_authorization_events import (
            record_authorization_decision,
            record_authorization_timing,
        )
        from core.web.services.agent_directory_service import current_agent_runtime

        # bindMs：current/turn runtime 获取 + 身份绑定。
        phase_started = time.perf_counter()
        runtime_getter = current_runtime_fn or current_agent_runtime
        runtime = bind_authorization_runtime(
            current_runtime=_coerce_mapping(runtime_getter()),
            turn_runtime=_coerce_mapping((turn_runtime_fn or _turn_runtime_from_env)()),
            agent_binding=runtime_agent_binding,
        )
        bind_ms = (time.perf_counter() - phase_started) * 1000

        # resolveMs：整段 resolve 减去 service 报告的注册表加载段（registryMs），
        # 剩余即决策段（cache key + 评估/命中重水化）。
        phase_started = time.perf_counter()
        report = resolve_enforced_authorization(runtime=runtime)
        resolve_total_ms = (time.perf_counter() - phase_started) * 1000
        registry_ms = float(max(0, int(getattr(report, "registry_ms", 0) or 0)))
        resolve_ms = max(0.0, resolve_total_ms - registry_ms)

        # installMs：执行上下文安装（预算解析 + 身份闸门），复用 bind 的 runtime。
        phase_started = time.perf_counter()
        install_execution_authorization(report, runtime=runtime)
        install_ms = (time.perf_counter() - phase_started) * 1000

        # recordMs：场景事件去重判定 + 决策事件写出。
        phase_started = time.perf_counter()
        # Scene-event dedupe：决策来自 turn 无关模板缓存且与上一次已记录
        # 签名一致时跳过重复写事件；变化后的首个回合恢复记录。
        decision = getattr(report, "decision", None)
        decision_cache_key = str(getattr(report, "decision_cache_key", "") or "")
        agent_id = str(getattr(decision, "agent_id", "") or "").strip()
        if _decision_already_recorded(agent_id, decision_cache_key):
            pass
        else:
            record_authorization_decision(report)
            _mark_decision_recorded(agent_id, decision_cache_key)
        record_ms = (time.perf_counter() - phase_started) * 1000

        total_ms = (time.perf_counter() - started) * 1000
        cache_hit = bool(getattr(report, "decision_cache_hit", False))
        # 批七：install 内部细分（identity/maxCalls/core）由 install 层线程
        # 局部上报；install 被 mock 或失败时读不到，按 0 兜底，事件字段恒在。
        install_sub = last_install_execution_timing() or {}
        identity_ms = float(install_sub.get("identityMs", 0) or 0)
        max_calls_ms = float(install_sub.get("maxCallsMs", 0) or 0)
        install_core_ms = float(install_sub.get("installCoreMs", 0) or 0)
        # 子锚点走独立轻量 timing 事件、每回合写出：decision 事件在命中去重
        # 轮被跳过，而命中轮正是本批要归因的 turnAuthorizationMs 缺口所在。
        record_authorization_timing(
            agent_id=agent_id,
            turn_id=str(getattr(decision, "turn_id", "") or ""),
            duration_ms=total_ms,
            cache_hit=cache_hit,
            bind_ms=bind_ms,
            registry_ms=registry_ms,
            resolve_ms=resolve_ms,
            install_ms=install_ms,
            record_ms=record_ms,
            identity_ms=identity_ms,
            max_calls_ms=max_calls_ms,
            install_core_ms=install_core_ms,
        )
        _record_turn_authorization_timing(
            total_ms,
            cache_hit=cache_hit,
            bind_ms=bind_ms,
            registry_ms=registry_ms,
            resolve_ms=resolve_ms,
            install_ms=install_ms,
            record_ms=record_ms,
            identity_ms=identity_ms,
            max_calls_ms=max_calls_ms,
            install_core_ms=install_core_ms,
        )
        return report
    except Exception as exc:
        try:
            from core.authorization.tool_authorization_service import clear_execution_authorization
            from core.logging.tool_authorization_events import record_authorization_failure

            clear_execution_authorization()
            record_authorization_failure(
                runtime=runtime,
                error=exc,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
        except Exception:
            pass
        _record_turn_authorization_timing(
            (time.perf_counter() - started) * 1000,
            cache_hit=False,
            bind_ms=bind_ms,
            registry_ms=registry_ms,
            resolve_ms=resolve_ms,
            install_ms=install_ms,
            record_ms=record_ms,
        )
        return None


def materialize_authorized_tools(
    registered_tools: Iterable[Any] | None,
    authorization_report: Any,
) -> List[Any]:
    decision = getattr(authorization_report, "decision", None)
    visible_names = _tool_name_set(getattr(decision, "visible_tools", ()) or ())
    if not visible_names:
        return []
    if isinstance(registered_tools, (str, bytes, bytearray, memoryview)):
        return []
    try:
        tools = list(registered_tools or [])
    except TypeError:
        return []
    return [
        tool
        for tool in tools
        if _coerce_text(getattr(tool, "name", "")).strip() in visible_names
    ]


def is_tool_visible_to_agent(tool_name: str, visible_tool_names: Iterable[Any] | None) -> bool:
    name = _coerce_text(tool_name).strip()
    return bool(name and name in _tool_name_set(visible_tool_names))


def hidden_tool_call_message(tool_name: str) -> str:
    name = _coerce_text(tool_name).strip() or "[unknown_tool]"
    return HIDDEN_TOOL_CALL_MESSAGE.format(name=name)


def restart_allowed_tool_names() -> tuple[str, ...]:
    return RESTART_ALLOWED_TOOL_NAMES


def guard_restart_focus_tool(tool_name: str, *, restart_focus: bool) -> Optional[str]:
    if not _flag_enabled(restart_focus, False):
        return None
    if _coerce_text(tool_name).strip() in RESTART_ALLOWED_TOOL_NAMES:
        return None
    return RESTART_FOCUS_GUARD_MESSAGE
