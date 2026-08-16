# -*- coding: utf-8 -*-
"""Agent-side authorization binding. Policy stays in core.authorization."""

from __future__ import annotations

import json
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


def _decode_binary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
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


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    value = _decode_binary(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _tool_name_set(items: Iterable[Any] | None) -> set[str]:
    names: set[str] = set()
    if items is None:
        return names
    items = _decode_binary(items)
    if isinstance(items, str):
        text = items.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                return _tool_name_set(json.loads(text))
            except json.JSONDecodeError:
                pass
        if text:
            names.add(text)
        return names
    if isinstance(items, Mapping):
        if "name" in items and not any(key in items for key in ("enabled", "visible", "allowed")):
            name = _coerce_text(items.get("name")).strip()
            return {name} if name else set()
        for key, enabled in items.items():
            name = _coerce_text(key).strip()
            if name and _coerce_bool(enabled, True):
                names.add(name)
        return names
    try:
        iterator = list(items)
    except TypeError:
        name = _coerce_text(getattr(items, "name", items)).strip()
        return {name} if name else set()
    for item in iterator:
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
    try:
        from core.authorization.tool_authorization_service import (
            install_execution_authorization,
            resolve_enforced_authorization,
        )
        from core.logging.tool_authorization_events import record_authorization_decision
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime_getter = current_runtime_fn or current_agent_runtime
        runtime = bind_authorization_runtime(
            current_runtime=_coerce_mapping(runtime_getter()),
            turn_runtime=_coerce_mapping((turn_runtime_fn or _turn_runtime_from_env)()),
            agent_binding=runtime_agent_binding,
        )
        report = resolve_enforced_authorization(runtime=runtime)
        install_execution_authorization(report)
        record_authorization_decision(report)
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
    if not _coerce_bool(restart_focus, False):
        return None
    if _coerce_text(tool_name).strip() in RESTART_ALLOWED_TOOL_NAMES:
        return None
    return RESTART_FOCUS_GUARD_MESSAGE
