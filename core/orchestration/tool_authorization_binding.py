# -*- coding: utf-8 -*-
"""Agent-side authorization binding. Policy stays in core.authorization."""

from __future__ import annotations

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


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _tool_name_set(items: Iterable[Any] | None) -> set[str]:
    names: set[str] = set()
    if items is None:
        return names
    if isinstance(items, bytes):
        items = items.decode("utf-8", errors="replace")
    if isinstance(items, str):
        name = items.strip()
        if name:
            names.add(name)
        return names
    if isinstance(items, Mapping):
        for key in items:
            name = str(key or "").strip()
            if name:
                names.add(name)
        return names
    try:
        iterator = list(items)
    except TypeError:
        name = str(getattr(items, "name", items) or "").strip()
        return {name} if name else set()
    for item in iterator:
        name = str(getattr(item, "name", item) or "").strip()
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
    agent_id = str(
        runtime.get("agentId")
        or turn.get("agentId")
        or binding.get("agentId")
        or ""
    ).strip()
    if not str(runtime.get("agentId") or "").strip():
        runtime["agentId"] = agent_id
    if not str(runtime.get("turnId") or "").strip():
        runtime["turnId"] = str(
            turn.get("runId")
            or binding.get("directSessionId")
            or (f"agent-bootstrap:{agent_id}" if agent_id else "")
        ).strip()
    if not str(runtime.get("runId") or "").strip():
        runtime["runId"] = str(turn.get("runId") or "").strip()
    if not str(runtime.get("mode") or "").strip():
        runtime["mode"] = str(turn.get("mode") or "").strip()
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
    try:
        tools = list(registered_tools or [])
    except TypeError:
        return []
    return [
        tool
        for tool in tools
        if str(getattr(tool, "name", "") or "").strip() in visible_names
    ]


def is_tool_visible_to_agent(tool_name: str, visible_tool_names: Iterable[Any] | None) -> bool:
    name = str(tool_name or "").strip()
    return bool(name and name in _tool_name_set(visible_tool_names))


def hidden_tool_call_message(tool_name: str) -> str:
    name = str(tool_name or "").strip() or "[unknown_tool]"
    return HIDDEN_TOOL_CALL_MESSAGE.format(name=name)


def restart_allowed_tool_names() -> tuple[str, ...]:
    return RESTART_ALLOWED_TOOL_NAMES


def guard_restart_focus_tool(tool_name: str, *, restart_focus: bool) -> Optional[str]:
    if not restart_focus:
        return None
    if str(tool_name or "").strip() in RESTART_ALLOWED_TOOL_NAMES:
        return None
    return RESTART_FOCUS_GUARD_MESSAGE
