#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具执行器模块

负责：
- 管理工具函数映射
- 通过事件总线解耦工具执行
- 提供工具超时和重试机制
"""

from __future__ import annotations

import os
import re
import inspect
import threading
import time
import json
from typing import Dict, Callable, Any, Optional
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# 核心模块导入
from core.chat.chat_result_contract import verification_from_tool_record
from core.infrastructure.event_bus import get_event_bus, EventNames
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.evolution_governor import get_evolution_governor
from core.infrastructure.llm_utils import parse_tool_args
from core.infrastructure.tool_result import (
    extract_tool_result_semantics,
    infer_tool_business_success,
    package_tool_result_facts,
    tool_result_facts_payload,
)
from core.logging import debug as _debug_logger


IMAGE2_TOOL_TIMEOUT_SECONDS = 300


def _record_tool_scene_event(
    phase: str,
    event_code: str,
    *,
    tool_name: str,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        event_fields: dict[str, Any] = {"toolName": str(tool_name or "").strip()}
        if fields:
            event_fields.update(fields)
        record_runtime_scene_event(
            "tool_executor",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            lifecycle=lifecycle,
        )
    except Exception as exc:
        _debug_logger.warning(f"[工具场景] 记录 tool scene 事件失败: {type(exc).__name__}: {exc}")
        return


def _summarize_tool_args(tool_args: dict) -> dict[str, Any]:
    payload = tool_args if isinstance(tool_args, dict) else {}
    keys = sorted(str(key) for key in payload.keys() if str(key) != "_cancel_checker")
    summary: dict[str, Any] = {
        "argKeys": keys[:24],
        "argCount": len(keys),
    }
    for path_key in ("file_path", "path", "target_path", "directory", "cwd"):
        if path_key in payload:
            summary[path_key] = str(payload.get(path_key) or "")
    if "command" in payload:
        summary["commandLength"] = len(str(payload.get("command") or ""))
    return summary


def _summarize_tool_result(result: Any) -> dict[str, Any]:
    text = str(result or "")
    semantics = extract_tool_result_semantics(result)
    return {
        "resultType": type(result).__name__,
        "resultPreview": text[:320],
        "resultLength": len(text),
        **{key: value for key, value in semantics.items() if value not in {None, ""}},
    }


def _tool_error_event_facts(
    tool_name: str,
    error: Any,
    *,
    semantic_status: str = "failed",
    failure_class: str = "",
    timed_out: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": semantic_status,
        "error": str(error or ""),
        "timedOut": bool(timed_out),
    }
    if failure_class:
        payload["failureClass"] = failure_class
    facts = tool_result_facts_payload(package_tool_result_facts(payload, tool_name=tool_name))
    facts["semanticStatus"] = semantic_status
    facts["timedOut"] = bool(timed_out)
    if failure_class:
        facts["failureClass"] = failure_class
    if timed_out:
        facts["transportStatus"] = "timeout"
    elif semantic_status == "cancelled":
        facts["transportStatus"] = "cancelled"
    elif failure_class in {
        "policy_blocked",
        "readonly_subagent_block",
        "runtime_block",
        "unknown_tool",
        "invalid_args",
    }:
        facts["transportStatus"] = "not_called"
    elif failure_class == "tool_error":
        facts["transportStatus"] = "raised"
    return facts


def _coerce_tool_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, (bytes, bytearray)):
        try:
            return _parse_json_object(result.decode("utf-8", errors="replace"))
        except Exception as exc:
            _debug_logger.warning(f"[工具结果] bytes 工具结果解析为 JSON payload 失败: {type(exc).__name__}: {exc}")
            return {}
    return _parse_json_object(str(result or "").strip())


def _coerce_result_status(value: Any) -> str:
    """Normalize tool result status strings to remove common BOM/whitespace noise."""
    if not isinstance(value, str):
        return ""
    return value.lstrip("\ufeff").strip().lower()


def _record_current_agent_tool_observation(tool_name: str, status: str, tool_args: dict[str, Any], summary: str = "") -> None:
    try:
        from core.web.services.agent_directory_service import write_current_tool_observation

        write_current_tool_observation(
            tool_name=tool_name,
            status=status,
            summary=summary,
            arg_keys=sorted(str(key) for key in (tool_args or {}).keys() if str(key) != "_cancel_checker"),
        )
    except Exception as exc:
        _debug_logger.warning(f"[工具观测] 记录当前工具观测失败: {type(exc).__name__}: {exc}")
        return


def _format_tool_argument_error(
    tool_name: str,
    func: Callable,
    tool_args: dict[str, Any],
    error: Exception | str,
) -> str:
    """Return an agent-readable correction hint for invalid tool arguments."""
    payload = tool_args if isinstance(tool_args, dict) else {}
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return (
            f"[工具参数错误] {tool_name} 参数不符合工具函数要求：{error}。"
            "请查看当前工具描述，改正参数名与参数类型后重试。"
        )

    parameters = [
        param
        for param in signature.parameters.values()
        if param.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        and not str(param.name).startswith("_")
    ]
    required = [
        param.name
        for param in parameters
        if param.default is inspect.Parameter.empty
    ]
    optional = [
        param.name
        for param in parameters
        if param.default is not inspect.Parameter.empty
    ]
    received = sorted(str(key) for key in payload.keys() if not str(key).startswith("_"))
    example_items: list[str] = []
    for param in parameters:
        if param.default is not inspect.Parameter.empty:
            value = param.default
        else:
            annotation = param.annotation
            if annotation in {int, "int"}:
                value = 1
            elif annotation in {float, "float"}:
                value = 1.0
            elif annotation in {bool, "bool"}:
                value = False
            else:
                value = f"<{param.name}>"
        example_items.append(f'"{param.name}": {json.dumps(value, ensure_ascii=False)}')
    example = "{" + ", ".join(example_items[:8]) + "}"
    return (
        f"[工具参数错误] {tool_name} 参数不符合当前工具签名：{error}。"
        f" 必填参数：{', '.join(required) if required else '无'}。"
        f" 可选参数：{', '.join(optional) if optional else '无'}。"
        f" 已收到参数：{', '.join(received) if received else '无'}。"
        f" 示例：{tool_name}({example})。"
        "请按工具描述修正参数名和类型后重试。"
    )


def _validate_tool_arguments(tool_name: str, func: Callable, tool_args: dict[str, Any]) -> str | None:
    payload = tool_args if isinstance(tool_args, dict) else {}
    try:
        signature = inspect.signature(func)
        signature.bind(**payload)
    except TypeError as exc:
        return _format_tool_argument_error(tool_name, func, payload, exc)
    except ValueError:
        return None

    type_errors: list[str] = []
    for name, value in payload.items():
        if str(name).startswith("_") or value is None or name not in signature.parameters:
            continue
        annotation = signature.parameters[name].annotation
        expected_name = ""
        expected_type: Any = None
        if annotation in {str, "str"}:
            expected_name = "str"
            expected_type = str
        elif annotation in {int, "int"}:
            expected_name = "int"
            expected_type = int
        elif annotation in {float, "float"}:
            expected_name = "float"
            expected_type = (int, float)
        elif annotation in {bool, "bool"}:
            expected_name = "bool"
            expected_type = bool
        if expected_type is None:
            continue
        if expected_name == "int" and isinstance(value, bool):
            type_errors.append(f"{name} 需要 int，收到 bool")
        elif expected_name == "bool" and not isinstance(value, bool):
            type_errors.append(f"{name} 需要 bool，收到 {type(value).__name__}")
        elif expected_name != "bool" and not isinstance(value, expected_type):
            type_errors.append(f"{name} 需要 {expected_name}，收到 {type(value).__name__}")

    if type_errors:
        return _format_tool_argument_error(tool_name, func, payload, "; ".join(type_errors))
    return None


def _tool_accepts_cancel_checker(func: Callable) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return "_cancel_checker" in signature.parameters


def _classify_tool_semantic_result(tool_name: str, result: Any) -> dict[str, Any]:
    text = str(result or "").strip()
    fields: dict[str, Any] = {"semanticStatus": "succeeded"}
    payload = _coerce_tool_result_payload(result)
    payload_status = _coerce_result_status(payload.get("status"))
    transaction_status = _coerce_result_status(payload.get("transaction_status")) if payload else ""
    if tool_name == "close_evolution_transaction_tool" and transaction_status and not payload_status:
        payload_status = transaction_status
    if (
        tool_name == "close_evolution_transaction_tool"
        and transaction_status
        and transaction_status not in {"success", "ok"}
        and payload_status in {"", "ok", "success"}
    ):
        payload_status = transaction_status
    if payload_status and payload.get("status") != payload_status:
        payload = dict(payload)
        payload["status"] = payload_status
    if tool_name == "close_evolution_transaction_tool" and payload_status:
        fields["toolResultStatus"] = payload_status
    is_business_success = infer_tool_business_success(payload) if payload else True
    if tool_name == "close_evolution_transaction_tool" and transaction_status and transaction_status not in {"success", "ok"}:
        is_business_success = False
    if not is_business_success:
        outcome = "failed"
        event_code = "tool.execute.failed"
        level = "error"
        result_status = payload_status
        if not result_status:
            if tool_name == "close_evolution_transaction_tool" and transaction_status:
                result_status = transaction_status
            else:
                result_status = "failed"
        if result_status in {"blocked", "policy_blocked"}:
            outcome = "blocked"
            event_code = "tool.execute.blocked"
            level = "warning"
        elif result_status in {"cancelled"}:
            outcome = "cancelled"
            event_code = "tool.execute.cancelled"
            level = "warning"
        elif result_status in {"timeout", "timed_out"}:
            outcome = "timeout"
            event_code = "tool.execute.timeout"
            level = "error"

        return {
            "eventCode": event_code,
            "level": level,
            "outcome": outcome,
            "lifecycle": True,
            "fields": {
                **fields,
                "semanticStatus": outcome,
                "toolResultStatus": result_status,
                "toolResultError": str(payload.get("error") or "").strip()[:120],
            },
        }
    if payload_status in {"degraded", "partial"}:
        failure_class = str(
            payload.get("failureClass")
            or payload.get("failure_class")
            or ("partial_result" if payload_status == "partial" else "degraded_result")
        ).strip()
        return {
            "eventCode": "tool.execute.degraded",
            "level": "warning",
            "outcome": "degraded",
            "lifecycle": True,
            "fields": {
                **fields,
                "semanticStatus": "degraded",
                "toolResultStatus": payload_status,
                "failureClass": failure_class,
            },
        }
    if text.startswith("[工具参数错误]"):
        return {
            "eventCode": "tool.execute.failed",
            "level": "error",
            "outcome": "failed",
            "lifecycle": True,
            "fields": {
                **fields,
                "semanticStatus": "failed",
                "failureClass": "tool_argument_error",
            },
        }
    if text.startswith(("[错误]", "[超时]", "[短路]")):
        return {
            "eventCode": "tool.execute.failed",
            "level": "error",
            "outcome": "failed",
            "lifecycle": True,
            "fields": {**fields, "semanticStatus": "failed"},
        }
    if text.startswith("[搜索质量不足]"):
        return {
            "eventCode": "tool.execute.degraded",
            "level": "warning",
            "outcome": "degraded",
            "lifecycle": True,
            "fields": {
                **fields,
                "semanticStatus": "degraded",
                "failureClass": "low_quality_search_results",
            },
        }
    if tool_name == "cli_tool":
        if "[EXEC FAILURE" in text or "[执行失败" in text:
            return {
                "eventCode": "tool.execute.failed",
                "level": "error",
                "outcome": "failed",
                "lifecycle": True,
                "fields": {**fields, "semanticStatus": "failed"},
            }
        if "[WARNING" in text or "[警告" in text or "[跨平台警告]" in text:
            return {
                "eventCode": "tool.execute.degraded",
                "level": "warning",
                "outcome": "degraded",
                "lifecycle": False,
                "fields": {**fields, "semanticStatus": "degraded"},
            }
    if tool_name == "python_lint_tool":
        lint_payload = _parse_json_object(text)
        issue_count = _coerce_int(lint_payload.get("issue_count") or lint_payload.get("issueCount"))
        lint_status = str(lint_payload.get("status") or "").strip().lower()
        fields.update(
            {
                "lintStatus": lint_status,
                "issueCount": issue_count,
            }
        )
        if lint_status and lint_status not in {"ok", "success", "passed"}:
            return {
                "eventCode": "tool.execute.failed",
                "level": "error",
                "outcome": "failed",
                "lifecycle": True,
                "fields": {**fields, "semanticStatus": "failed"},
            }
        if issue_count > 0:
            return {
                "eventCode": "tool.execute.degraded",
                "level": "warning",
                "outcome": "degraded",
                "lifecycle": False,
                "fields": {**fields, "semanticStatus": "degraded"},
            }
    return {
        "eventCode": "tool.execute.succeeded",
        "level": "info",
        "outcome": "succeeded",
        "lifecycle": False,
        "fields": fields,
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(text or "").lstrip("\ufeff").strip())
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _detect_unquoted_cli_operator(command: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False
    has_pipe = False
    has_subexpression = False
    index = 0
    text = str(command or "")
    length = len(text)

    while index < length:
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and in_double:
            escaped = True
            index += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue
        if in_single or in_double:
            index += 1
            continue
        if text.startswith("&&", index) or text.startswith("||", index):
            return "cli_tool:command_chain"
        if text.startswith("$(", index):
            has_subexpression = True
            index += 2
            continue
        if char in {";", "`"}:
            return "cli_tool:command_chain"
        if char == "|":
            has_pipe = True
        index += 1

    if has_pipe:
        return "cli_tool:pipe"
    if has_subexpression:
        return "cli_tool:subexpression"
    return None


class ToolExecutor:
    """
    工具执行器

    负责管理所有工具的注册、执行、超时和重试。
    """

    def __init__(self):
        self._tool_map: Dict[str, Callable] = {}
        self._timeout_map: Dict[str, int] = {}
        self._retryable_tools: set = set()
        self._event_bus = get_event_bus()
        self._cancel_checker: Optional[Callable[[], str]] = None
        self._cancel_checker_owner: Any = None
        self._cancel_checker_lock = threading.Lock()
        self._cancel_checker_context: ContextVar[tuple[Optional[Callable[[], str]], Any] | None] = ContextVar(
            f"vibelution_tool_cancel_checker_{id(self)}",
            default=None,
        )
        self._register_default_tools()

    _READ_ONLY_BLOCKED_TOOLS = {
        "spawn_agent_tool",
        "apply_patch_tool",
        "apply_diff_edit_tool",
        "write_file_tool",
        "commit_compressed_memory_tool",
        "record_learning_tool",
        "trigger_self_restart_tool",
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "cli_tool",
        "cli_agent_run_tool",
        "task_create_tool",
        "task_update_tool",
        "plan_update_tool",
        "task_start_tool",
        "task_stop_tool",
        "clean_workspace_debris_tool",
        "agent_message_tool",
        "agent_tool_permission_request_tool",
        "image2_generate_tool",
        "computer_use_session_tool",
        "computer_use_task_tool",
        "update_diagnosis_rules_tool",
        "update_self_model_tool",
        "record_evolution_tool",
        "compress_context_tool",
    }
    _RUNTIME_GOAL_WRITE_BLOCKED_TOOLS = set(_READ_ONLY_BLOCKED_TOOLS)
    _RUNTIME_GOAL_GIT_BLOCKED_TOOLS = {
        "cli_tool",
        "commit_compressed_memory_tool",
        "trigger_self_restart_tool",
    }
    _RUNTIME_GOAL_SUBAGENT_BLOCKED_TOOLS = {
        "spawn_agent_tool",
        "cli_agent_run_tool",
        "agent_message_tool",
    }
    _RUNTIME_GOAL_EVOLUTION_BLOCKED_TOOLS = {
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "record_evolution_tool",
        "update_self_model_tool",
    }

    def _register_default_tools(self):
        """注册默认工具映射：只注册 canonical agent 工具名和内部委派入口。"""
        from tools.agent_tools import spawn_agent as spawn_agent_tool

        # ── 从 Key_Tools 自动推导工具映射 ──────────────────────────────
        from tools.Key_Tools import create_key_tools
        for tool in create_key_tools():
            self._tool_map[tool.name] = tool.func

        # 只供主 agent 调度层内部使用，不向 LLM 工具目录暴露。
        self._tool_map["spawn_agent_tool"] = spawn_agent_tool

        self._timeout_map = {
            "cli_tool": 60,
            "cli_agent_run_tool": 900,
            "grep_search_tool": 30,
            "web_fetch_tool": 30,
            "web_search_tool": 30,
            "run_test_for_tool": 120,
            "code_symbol_tool": 30,
            "python_lint_tool": 60,
            "spawn_agent_tool": 150,
            "image2_generate_tool": IMAGE2_TOOL_TIMEOUT_SECONDS,
            "computer_use_session_tool": 180,
            "computer_use_task_tool": 180,
        }
        self._retryable_tools = {"grep_search_tool"}

    def register_tool(self, name: str, func: Callable, timeout: int = 30):
        """注册自定义工具"""
        self._tool_map[name] = func
        self._timeout_map[name] = timeout

    def set_cancel_checker(
        self,
        checker: Optional[Callable[[], str]] = None,
        *,
        owner: Any = None,
    ) -> None:
        """Attach the current turn cancellation checker to tool execution."""

        with self._cancel_checker_lock:
            current_context = self._cancel_checker_context.get(None)
            if checker is None:
                current_owner = current_context[1] if current_context else None
                if owner is None or current_owner is owner:
                    self._cancel_checker_context.set(None)
                if owner is None or self._cancel_checker_owner is owner:
                    self._cancel_checker = None
                    self._cancel_checker_owner = None
                return
            context_owner = owner if owner is not None else checker
            self._cancel_checker_context.set((checker, context_owner))
            self._cancel_checker = checker
            self._cancel_checker_owner = context_owner

    def _snapshot_cancel_checker(self) -> Optional[Callable[[], str]]:
        current_context = self._cancel_checker_context.get(None)
        if current_context and callable(current_context[0]):
            return current_context[0]
        with self._cancel_checker_lock:
            return None

    def _current_cancel_reason(self, checker: Optional[Callable[[], str]] = None) -> str:
        if checker is None:
            checker = self._snapshot_cancel_checker()
        if not callable(checker):
            return ""
        try:
            return str(checker() or "").strip()
        except Exception:
            return ""

    def execute(self, tool_name: str, tool_args: dict, *, tool_call_id: str = "") -> tuple:
        """
        执行工具

        Args:
            tool_name: 工具名称
            tool_args: 工具参数字典

        Returns:
            (result, action): 元组
                result: 工具执行结果
                action: 特殊动作 (如 "restart", "hibernated", None)
        """
        tool_args = parse_tool_args(tool_args or {})
        call_id = str(tool_call_id or "").strip()

        def publish_tool_event(event_name: str, payload: dict[str, Any]) -> None:
            event_payload = dict(payload)
            if call_id:
                event_payload["callId"] = call_id
            self._event_bus.publish(event_name, event_payload)

        started_at = time.monotonic()

        execution_authorization = self._check_canonical_execution_authorization(tool_name, call_id, tool_args)
        if execution_authorization is not None and not execution_authorization.allowed:
            authorization_error = execution_authorization.message
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": authorization_error,
                "result": authorization_error,
                "args": tool_args,
                **_tool_error_event_facts(
                    tool_name,
                    authorization_error,
                    semantic_status="blocked",
                    failure_class="authorization_denied",
                ),
            })
            _record_current_agent_tool_observation(tool_name, "authorization_denied", tool_args, authorization_error)
            _record_tool_scene_event(
                "authorize",
                "tool.authorization.execution_denied",
                tool_name=tool_name,
                message=authorization_error,
                level="warning",
                outcome="blocked",
                fields={
                    "code": execution_authorization.code,
                    "agentId": execution_authorization.agent_id,
                    "turnId": execution_authorization.turn_id,
                    "callIdPresent": bool(call_id),
                    "decisionFingerprintPresent": bool(execution_authorization.decision_fingerprint),
                },
                lifecycle=True,
            )
            return (authorization_error, None)
        if execution_authorization is not None and execution_authorization.enforced:
            _record_tool_scene_event(
                "authorize",
                "tool.authorization.execution_allowed",
                tool_name=tool_name,
                message="Canonical tool execution authorization passed.",
                level="info",
                outcome="allowed",
                fields={
                    "code": execution_authorization.code,
                    "agentId": execution_authorization.agent_id,
                    "turnId": execution_authorization.turn_id,
                    "callIdPresent": True,
                    "decisionFingerprintPresent": True,
                },
                lifecycle=True,
            )

        readonly_block = self._check_readonly_subagent_block(tool_name)
        if readonly_block:
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": readonly_block,
                "result": readonly_block,
                "args": tool_args,
                **_tool_error_event_facts(
                    tool_name,
                    readonly_block,
                    semantic_status="blocked",
                    failure_class="readonly_subagent_block",
                ),
            })
            _record_tool_scene_event(
                "execute",
                "tool.execute.blocked",
                tool_name=tool_name,
                message=readonly_block,
                level="warning",
                outcome="blocked",
                fields=_summarize_tool_args(tool_args),
            )
            return (readonly_block, None)

        blocked_message = self._check_runtime_block(tool_name, tool_args)
        if blocked_message:
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": blocked_message,
                "result": blocked_message,
                "args": tool_args,
                **_tool_error_event_facts(
                    tool_name,
                    blocked_message,
                    semantic_status="blocked",
                    failure_class="runtime_block",
                ),
            })
            _record_tool_scene_event(
                "execute",
                "tool.execute.blocked",
                tool_name=tool_name,
                message=blocked_message,
                level="warning",
                outcome="blocked",
                fields=_summarize_tool_args(tool_args),
            )
            return (blocked_message, None)

        if tool_name not in self._tool_map:
            error_msg = self._unknown_tool_message_for_current_context()
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": "[unknown_tool]",
                "error": error_msg,
                "result": error_msg,
                "args": tool_args,
                **_tool_error_event_facts(
                    "[unknown_tool]",
                    error_msg,
                    semantic_status="failed",
                    failure_class="unknown_tool",
                ),
            })
            _record_current_agent_tool_observation(str(tool_name or "[unknown_tool]"), "unknown_tool", tool_args, error_msg)
            _record_tool_scene_event(
                "execute",
                "tool.execute.failed",
                tool_name="[unknown_tool]",
                message=error_msg,
                level="error",
                outcome="failed",
                fields={
                    **_summarize_tool_args(tool_args),
                    "error": error_msg,
                    "unknownToolNameLength": len(str(tool_name or "")),
                },
                lifecycle=True,
            )
            return (error_msg, None)

        # 发布工具开始事件。未知工具不发布 start，避免把错误工具名写入可见事件流。
        publish_tool_event(EventNames.TOOL_START, {
            "name": tool_name,
            "args": tool_args,
        })

        func = self._tool_map[tool_name]
        timeout = self._resolve_timeout(tool_name, tool_args)
        call_args = dict(tool_args or {})
        # 内部治理哨兵只用于执行权限判断，不能透传给真实工具函数。
        call_args.pop("_internal_delegate", None)
        call_args.pop("force", None)
        argument_error = _validate_tool_arguments(tool_name, func, call_args)
        if argument_error:
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": argument_error,
                "result": argument_error,
                "args": tool_args,
                "durationMs": int((time.monotonic() - started_at) * 1000),
                **_tool_error_event_facts(
                    tool_name,
                    argument_error,
                    semantic_status="failed",
                    failure_class="invalid_args",
                ),
            })
            self._record_runtime_signals(tool_name, tool_args, argument_error)
            _record_current_agent_tool_observation(tool_name, "invalid_args", tool_args, argument_error)
            _record_tool_scene_event(
                "execute",
                "tool.execute.invalid_args",
                tool_name=tool_name,
                message=argument_error,
                level="warning",
                outcome="failed",
                fields={
                    **_summarize_tool_args(tool_args),
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "error": argument_error,
                },
                lifecycle=True,
            )
            return (argument_error, None)
        cancel_checker = self._snapshot_cancel_checker()
        if _tool_accepts_cancel_checker(func) and "_cancel_checker" not in call_args:
            call_args["_cancel_checker"] = lambda: self._current_cancel_reason(cancel_checker)

        executor = ThreadPoolExecutor(max_workers=1)
        future = None

        try:
            cancel_reason = self._current_cancel_reason(cancel_checker)
            if cancel_reason:
                error_msg = f"[取消] {tool_name} 已因停止请求跳过执行：{cancel_reason}"
                publish_tool_event(EventNames.TOOL_ERROR, {
                    "name": tool_name,
                    "error": error_msg,
                    "result": error_msg,
                    "args": tool_args,
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "timeoutSeconds": timeout,
                    **_tool_error_event_facts(
                        tool_name,
                        error_msg,
                        semantic_status="cancelled",
                        failure_class="cancelled",
                    ),
                })
                _record_tool_scene_event(
                    "execute",
                    "tool.execute.cancelled",
                    tool_name=tool_name,
                    message=error_msg,
                    level="warning",
                    outcome="cancelled",
                    fields={
                        **_summarize_tool_args(tool_args),
                        "durationMs": int((time.monotonic() - started_at) * 1000),
                        "cancelReason": cancel_reason,
                    },
                    lifecycle=True,
                )
                return (error_msg, None)
            tool_context = copy_context()
            future = executor.submit(tool_context.run, func, **call_args)
            deadline = time.monotonic() + max(float(timeout), 0.1)
            while True:
                cancel_reason = self._current_cancel_reason(cancel_checker)
                if cancel_reason:
                    future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    error_msg = f"[取消] {tool_name} 已因停止请求中断：{cancel_reason}"
                    publish_tool_event(EventNames.TOOL_ERROR, {
                        "name": tool_name,
                        "error": error_msg,
                        "result": error_msg,
                        "args": tool_args,
                        "durationMs": int((time.monotonic() - started_at) * 1000),
                        "timeoutSeconds": timeout,
                        **_tool_error_event_facts(
                            tool_name,
                            error_msg,
                            semantic_status="cancelled",
                            failure_class="cancelled",
                        ),
                    })
                    self._record_runtime_signals(tool_name, tool_args, error_msg)
                    _record_tool_scene_event(
                        "execute",
                        "tool.execute.cancelled",
                        tool_name=tool_name,
                        message=error_msg,
                        level="warning",
                        outcome="cancelled",
                        fields={
                            **_summarize_tool_args(tool_args),
                            "durationMs": int((time.monotonic() - started_at) * 1000),
                            "cancelReason": cancel_reason,
                        },
                        lifecycle=True,
                    )
                    return (error_msg, None)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                try:
                    result = future.result(timeout=min(0.2, remaining))
                    cancel_reason = self._current_cancel_reason(cancel_checker)
                    if cancel_reason:
                        error_msg = f"[取消] {tool_name} 已因停止请求中断：{cancel_reason}"
                        publish_tool_event(EventNames.TOOL_ERROR, {
                            "name": tool_name,
                            "error": error_msg,
                            "result": error_msg,
                            "args": tool_args,
                            "durationMs": int((time.monotonic() - started_at) * 1000),
                            "timeoutSeconds": timeout,
                            **_tool_error_event_facts(
                                tool_name,
                                error_msg,
                                semantic_status="cancelled",
                                failure_class="cancelled",
                            ),
                        })
                        self._record_runtime_signals(tool_name, tool_args, error_msg)
                        _record_tool_scene_event(
                            "execute",
                            "tool.execute.cancelled",
                            tool_name=tool_name,
                            message=error_msg,
                            level="warning",
                            outcome="cancelled",
                            fields={
                                **_summarize_tool_args(tool_args),
                                "durationMs": int((time.monotonic() - started_at) * 1000),
                                "cancelReason": cancel_reason,
                            },
                            lifecycle=True,
                        )
                        return (error_msg, None)
                    break
                except TimeoutError:
                    continue

            duration_ms = int((time.monotonic() - started_at) * 1000)
            semantic = _classify_tool_semantic_result(tool_name, result)
            semantic_outcome = str(semantic.get("outcome") or "succeeded")
            result_facts = tool_result_facts_payload(
                package_tool_result_facts(result, tool_name=tool_name)
            )
            result_facts["semanticStatus"] = semantic_outcome
            if semantic_outcome == "timeout":
                result_facts["timedOut"] = True
                result_facts["failureClass"] = result_facts.get("failureClass") or "timeout"

            event_payload = {
                "name": tool_name,
                "args": tool_args,
                "result": result,
                "durationMs": duration_ms,
                "timeoutSeconds": timeout,
                **result_facts,
            }
            if semantic_outcome in {"succeeded", "degraded", "observed"}:
                publish_tool_event(EventNames.TOOL_SUCCESS, event_payload)
            else:
                publish_tool_event(EventNames.TOOL_ERROR, {
                    **event_payload,
                    "error": str(result or ""),
                })

            self._record_runtime_signals(tool_name, tool_args, result)
            _record_current_agent_tool_observation(
                tool_name,
                semantic_outcome,
                tool_args,
                str(result or "")[:320],
            )
            _record_tool_scene_event(
                "execute",
                str(semantic.get("eventCode") or "tool.execute.succeeded"),
                tool_name=tool_name,
                message=f"Tool executed: {tool_name}",
                level=str(semantic.get("level") or "info"),
                outcome=str(semantic.get("outcome") or "succeeded"),
                fields={
                    **_summarize_tool_args(tool_args),
                    **_summarize_tool_result(result),
                    **result_facts,
                    **(semantic.get("fields") if isinstance(semantic.get("fields"), dict) else {}),
                    "durationMs": duration_ms,
                    "timeoutSeconds": timeout,
                },
                lifecycle=bool(semantic.get("lifecycle")),
            )

            # ── 自动更新代码库地图（检测文件修改工具）──
            self._try_auto_update_map(tool_name, tool_args)

            executor.shutdown(wait=False, cancel_futures=False)
            return (result, None)

        except TimeoutError:
            if future is not None:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            error_msg = f"[超时] {tool_name} 执行超时 ({timeout}秒)"
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
                "result": error_msg,
                "args": tool_args,
                "durationMs": int((time.monotonic() - started_at) * 1000),
                "timeoutSeconds": timeout,
                **_tool_error_event_facts(
                    tool_name,
                    error_msg,
                    semantic_status="timeout",
                    failure_class="timeout",
                    timed_out=True,
                ),
            })
            self._record_runtime_signals(tool_name, tool_args, error_msg)
            _record_current_agent_tool_observation(tool_name, "timeout", tool_args, error_msg)
            _record_tool_scene_event(
                "execute",
                "tool.execute.timeout",
                tool_name=tool_name,
                message=error_msg,
                level="error",
                outcome="timeout",
                fields={
                    **_summarize_tool_args(tool_args),
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "timeoutSeconds": timeout,
                    "error": error_msg,
                },
                lifecycle=True,
            )
            return (error_msg, None)

        except TypeError as e:
            executor.shutdown(wait=False, cancel_futures=True)
            error_msg = _format_tool_argument_error(tool_name, func, call_args, e)
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
                "result": error_msg,
                "args": tool_args,
                "durationMs": int((time.monotonic() - started_at) * 1000),
                "timeoutSeconds": timeout,
                **_tool_error_event_facts(
                    tool_name,
                    error_msg,
                    semantic_status="failed",
                    failure_class="invalid_args",
                ),
            })
            self._record_runtime_signals(tool_name, tool_args, error_msg)
            _record_current_agent_tool_observation(tool_name, "invalid_args", tool_args, error_msg)
            _record_tool_scene_event(
                "execute",
                "tool.execute.invalid_args",
                tool_name=tool_name,
                message=error_msg,
                level="warning",
                outcome="failed",
                fields={
                    **_summarize_tool_args(tool_args),
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "errorType": "TypeError",
                    "error": str(e),
                },
                lifecycle=True,
            )
            return (error_msg, None)

        except Exception as e:
            executor.shutdown(wait=False, cancel_futures=True)
            error_msg = f"[错误] {type(e).__name__}: {e}"
            publish_tool_event(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
                "result": error_msg,
                "args": tool_args,
                "durationMs": int((time.monotonic() - started_at) * 1000),
                "timeoutSeconds": timeout,
                **_tool_error_event_facts(
                    tool_name,
                    error_msg,
                    semantic_status="failed",
                    failure_class="tool_error",
                ),
            })
            self._record_runtime_signals(tool_name, tool_args, error_msg)
            _record_current_agent_tool_observation(tool_name, "failed", tool_args, error_msg)
            _record_tool_scene_event(
                "execute",
                "tool.execute.failed",
                tool_name=tool_name,
                message=error_msg,
                level="error",
                outcome="failed",
                fields={
                    **_summarize_tool_args(tool_args),
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "errorType": type(e).__name__,
                    "error": str(e),
                },
                lifecycle=True,
            )
            return (error_msg, None)

    def _resolve_timeout(self, tool_name: str, tool_args: dict) -> int:
        timeout = self._timeout_map.get(tool_name, 30)
        requested = (tool_args or {}).get("timeout")
        try:
            requested_int = int(requested)
        except (TypeError, ValueError):
            requested_int = 0

        # 除 spawn_agent_tool 外，其它工具允许按调用方显式拉长超时。
        if tool_name != "spawn_agent_tool":
            if requested_int > 0:
                return max(timeout, requested_int)
            return timeout

        if requested_int <= 0:
            return timeout

        # 给外层线程执行器留一点缓冲，避免子进程还在收尾时外层先误杀。
        return max(timeout, requested_int + 15)

    @classmethod
    def _check_readonly_subagent_block(cls, tool_name: str) -> Optional[str]:
        if os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() != "readonly":
            return None
        if tool_name not in cls._READ_ONLY_BLOCKED_TOOLS:
            return None
        if tool_name == "spawn_agent_tool":
            return "[只读子代理] 当前子 agent 运行在只读模式，禁止继续派发子 agent。"
        return f"[只读子代理] 当前子 agent 运行在只读模式，禁止调用 `{tool_name}`。"

    def _check_runtime_block(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """检查当前轮次是否已记录同类失败模式。"""
        session = get_session_state()
        spawn_block = self._check_spawn_agent_permission(tool_name, tool_args)
        if spawn_block:
            return spawn_block
        delegation_block = self._check_delegation_policy_block(tool_name, tool_args)
        if delegation_block:
            return delegation_block
        capability_block = self._check_runtime_goal_capability_block(session, tool_name, tool_args)
        if capability_block:
            return capability_block
        evolution_block = self._check_evolution_mutation_guard(session, tool_name, tool_args)
        if evolution_block:
            return evolution_block
        return None

    @classmethod
    def _check_runtime_goal_capability_block(cls, session, tool_name: str, tool_args: dict) -> Optional[str]:
        """Enforce the current RuntimeGoalPacket as the tool side-effect authority."""

        try:
            packet = session.get_runtime_goal_packet()
        except Exception:
            packet = None
        if packet is None:
            return None
        normalized_tool = str(tool_name or "").strip()
        profile = str(getattr(packet, "capability_profile", "") or getattr(packet, "objective_type", "") or "").strip()
        if (
            not bool(getattr(packet, "allow_subagents", True))
            and normalized_tool in cls._RUNTIME_GOAL_SUBAGENT_BLOCKED_TOOLS
        ):
            return (
                "[运行目标包] 当前能力边界禁止子 agent 或跨会话派发。"
                f"能力 Profile: {profile or 'unknown'}；工具 `{normalized_tool}` 已被拦截。"
            )
        if (
            not bool(getattr(packet, "allow_file_writes", True))
            and normalized_tool in cls._RUNTIME_GOAL_WRITE_BLOCKED_TOOLS
        ):
            return (
                "[运行目标包] 当前能力边界为只读，禁止文件、命令、记忆或状态写入。"
                f"能力 Profile: {profile or 'unknown'}；工具 `{normalized_tool}` 已被拦截。"
            )
        if (
            not bool(getattr(packet, "allow_git_commit", True))
            and normalized_tool in cls._RUNTIME_GOAL_GIT_BLOCKED_TOOLS
        ):
            if (
                normalized_tool == "cli_tool"
                and profile == "supervised_evaluation"
                and cls._is_supervised_evaluation_validation_cli(tool_args)
            ):
                return None
            return (
                "[运行目标包] 当前能力边界禁止 Git 提交、重启或可能触发 Git 写入的命令。"
                f"能力 Profile: {profile or 'unknown'}；工具 `{normalized_tool}` 已被拦截。"
            )
        if (
            not bool(getattr(packet, "allow_evolution_transaction", True))
            and normalized_tool in cls._RUNTIME_GOAL_EVOLUTION_BLOCKED_TOOLS
        ):
            return (
                "[运行目标包] 当前能力边界禁止进化事务写入。"
                f"能力 Profile: {profile or 'unknown'}；工具 `{normalized_tool}` 已被拦截。"
            )
        return None

    @classmethod
    def _is_supervised_evaluation_validation_cli(cls, tool_args: dict) -> bool:
        command = str((tool_args or {}).get("command") or "").strip()
        if not command:
            return False
        lowered = command.lower()
        blocked_fragments = ("&&", "||", "|", ">", "<", "\n", "\r", "`", "$(")
        if any(fragment in lowered for fragment in blocked_fragments):
            return False
        blocked_patterns = (
            r"\bgit\s+(?:commit|push|merge|reset|checkout|switch|branch|tag|rebase|cherry-pick)\b",
            r"\b(?:remove-item|del|erase|rmdir)\b",
            r"(^|\s)rm\s+",
            r"\btrigger_self_restart_tool\b",
        )
        if any(re.search(pattern, lowered) for pattern in blocked_patterns):
            return False
        return bool(
            re.match(
                r'^(?:&\s*)?(?:(?:"[^"]*(?:python|py)(?:\.exe)?")|(?:[^\s"]*(?:python|py)(?:\.exe)?))\s+-m\s+pytest(?:\s|$)',
                command,
                flags=re.IGNORECASE,
            )
            or re.match(r"^pytest(?:\.exe)?(?:\s|$)", command, flags=re.IGNORECASE)
        )

    def _check_canonical_execution_authorization(self, tool_name: str, tool_call_id: str, tool_args: dict):
        if str(tool_name or "").strip() not in self._tool_map:
            return None
        try:
            from core.authorization.tool_authorization_service import authorize_tool_execution

            return authorize_tool_execution(tool_name=tool_name, tool_call_id=tool_call_id, tool_args=tool_args)
        except Exception as exc:
            _debug_logger.warning(f"[工具授权] canonical execution authorization failed: {type(exc).__name__}: {exc}")
            from core.authorization.tool_authorization_service import ToolExecutionAuthorizationResult

            return ToolExecutionAuthorizationResult(
                enforced=True,
                allowed=False,
                code="authorization_error",
                message="[工具授权] 无法验证当前工具调用，已按 fail-closed 拦截。",
            )

    def _unknown_tool_message_for_current_context(self) -> str:
        fallback_context_warning = ""
        try:
            from core.authorization.tool_authorization_service import current_execution_authorization
            from core.web.services.agent_directory_service import current_agent_runtime

            runtime = current_agent_runtime()
            agent_id = str((runtime or {}).get("agentId") or "").strip()
            if agent_id:
                authorization = current_execution_authorization()
                visible_names = [name for name in tuple(getattr(authorization, "executable_tools", ()) or ()) if name in self._tool_map][:24]
                if visible_names:
                    visible = ", ".join(visible_names)
                    return (
                        "[错误] 未知工具：该工具未注册到当前 Agent 可用工具集中。"
                        f"当前 Agent 可用工具包括：{visible}。"
                        "请换用已注册工具。"
                    )
                return (
                    "[错误] 未知工具：该工具未注册到当前 Agent 可用工具集中。"
                    "当前 Agent 当前没有可用的已注册工具。"
                )
        except Exception as exc:
            fallback_context_warning = f" 当前 Agent 上下文不可用（{type(exc).__name__}）。"

        available_tool_names = sorted(self._tool_map)
        preview_tool_names = available_tool_names[:24]
        for recovery_tool in ("read_file_tool", "grep_search_tool", "glob_tool", "cli_tool"):
            if recovery_tool in self._tool_map and recovery_tool not in preview_tool_names:
                preview_tool_names.append(recovery_tool)
        available_tools = ", ".join(preview_tool_names)
        return (
            "[错误] 未知工具：该工具名不在当前工具目录中。"
            f"{fallback_context_warning} 已回退到通用工具预览。"
            f"当前可用工具包括：{available_tools}。"
            "请选择功能匹配的工具名，并按该工具的参数 schema 重试。"
        )

    @staticmethod
    def _check_delegation_policy_block(tool_name: str, tool_args: dict) -> Optional[str]:
        if tool_name != "spawn_agent_tool":
            return None
        if os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() == "readonly":
            return None
        if (tool_args or {}).get("_internal_delegate") is not True:
            return None
        try:
            from core.web.services.agent_directory_service import evaluate_current_delegation_policy

            decision = evaluate_current_delegation_policy(
                context_mode=str((tool_args or {}).get("context_mode") or (tool_args or {}).get("contextMode") or "isolated"),
                requested_depth=None,
            )
        except Exception as exc:
            _debug_logger.warning(f"[委托策略] 查询 delegation policy 失败: {type(exc).__name__}: {exc}")
            return None
        if getattr(decision, "allowed", True):
            return None
        return str(getattr(decision, "message", "") or "[委托策略提示] 当前 Agent 的 DelegationPolicy 拦截了子 Agent 派发。")

    @staticmethod
    def _check_evolution_mutation_guard(session, tool_name: str, tool_args: dict) -> Optional[str]:
        active_txn_id = session.get_active_evolution_txn()
        if not active_txn_id and not ToolExecutor._runtime_goal_allows_evolution_transaction(session):
            return None
        governor = get_evolution_governor()
        return governor.check_mutation_allowed(
            tool_name=tool_name,
            tool_args=tool_args or {},
            active_txn_id=active_txn_id,
        )

    @staticmethod
    def _runtime_goal_allows_evolution_transaction(session) -> bool:
        try:
            packet = session.get_runtime_goal_packet()
        except Exception:
            packet = None
        if packet is None:
            return True
        return bool(getattr(packet, "allow_evolution_transaction", False))

    @staticmethod
    def _check_spawn_agent_permission(tool_name: str, tool_args: dict) -> Optional[str]:
        """禁止 LLM 直接调用子 agent；只允许主脑调度层显式放行。"""
        if tool_name != "spawn_agent_tool":
            return None
        if os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() == "readonly":
            return "[只读子代理] 当前子 agent 运行在只读模式，禁止继续派发子 agent。"
        if (tool_args or {}).get("_internal_delegate") is True:
            return None
        return "[短路] spawn_agent_tool 仅允许主 agent 的委派治理层内部调用，不能直接作为普通工具发起。"

    def _record_runtime_signals(self, tool_name: str, tool_args: dict, result: Any) -> None:
        """把工具执行结果转成会话级短期约束。"""
        session = get_session_state()
        result_text = str(result or "")
        pattern = self._detect_tool_pattern(tool_name, tool_args)
        pet = None
        try:
            from core.pet_system import get_pet_system
            pet = get_pet_system()
        except Exception:
            pet = None

        if "[安全拦截]" in result_text and pattern:
            hint = self._pattern_hint(pattern)
            session.record_blocked_tool_pattern(pattern, "安全策略已拦截该模式", hint)
            session.record_blocker("security_block", f"{tool_name} 触发 `{pattern}` 安全拦截", hint)

        command = str((tool_args or {}).get("command") or "")
        if tool_name in {"run_test_for_tool", "cli_tool"} and ("pytest" in command or tool_name == "run_test_for_tool"):
            verification_status, verification_summary, _ = verification_from_tool_record(
                {"name": tool_name, "args": tool_args or {}, "result_preview": result_text}
            )
            is_cross_platform_warning = "[跨平台警告]" in result_text
            passed = verification_status == "passed"
            summary = "pytest 通过" if passed else (verification_summary or result_text)[:200]
            if is_cross_platform_warning:
                session.record_blocked_tool_pattern(
                    "cli_tool:unix_shell_on_windows",
                    "跨平台检查已拦截 Unix shell 片段",
                    "改用 PowerShell 等价命令或结构化工具",
                )
                session.record_blocker(
                    "cross_platform_command",
                    summary,
                    "改用 PowerShell 等价命令或结构化工具",
                    severity="hint",
                )
            else:
                session.record_validation_result(summary, passed, kind="tests")
                session.note_feedback_loop(
                    loop_type="tests",
                    target=command or "pytest",
                    result=summary,
                    phase="reproduce",
                )
                session.set_diagnostic_phase("reproduce")
                self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                    "kind": "tests",
                    "passed": passed,
                    "message": summary,
                })
                if pet and passed:
                    pet.reward_validation("tests", True)
        elif tool_name == "cli_tool" and "py_compile" in command:
            verification_status, verification_summary, _ = verification_from_tool_record(
                {"name": tool_name, "args": tool_args or {}, "result_preview": result_text}
            )
            passed = verification_status == "passed"
            summary = verification_summary or ("python -m py_compile 通过" if passed else result_text[:200])
            session.record_validation_result(summary, passed, kind="compile")
            session.note_feedback_loop(
                loop_type="compile",
                target=command or "python -m py_compile",
                result=summary,
                phase="reproduce",
            )
            session.set_diagnostic_phase("reproduce")
            self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                "kind": "compile",
                "passed": passed,
                "message": summary,
            })
            if pet and passed:
                pet.reward_validation("compile", True)
        elif tool_name == "python_lint_tool":
            verification_status, verification_summary, _ = verification_from_tool_record(
                {"name": tool_name, "args": tool_args or {}, "result_preview": result_text}
            )
            passed = verification_status == "passed"
            summary = "ruff lint 通过" if passed else (verification_summary or result_text)[:200]
            session.record_validation_result(summary, passed, kind="lint")
            session.note_feedback_loop(
                loop_type="lint",
                target=str((tool_args or {}).get("file_path") or "python_lint_tool"),
                result=summary,
                phase="reproduce",
            )
            self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                "kind": "lint",
                "passed": passed,
                "message": summary,
            })
            if pet and passed:
                pet.reward_validation("lint", True)

        if pet and tool_name == "task_update_tool":
            is_completed = bool((tool_args or {}).get("is_completed"))
            if is_completed:
                pet.reward_task_completion(str((tool_args or {}).get("task_id") or "task"))

        get_evolution_governor().record_mutation_result(
            tool_name=tool_name,
            tool_args=tool_args or {},
            result=result,
            active_txn_id=session.get_active_evolution_txn(),
        )

        reading_signal_tools = {
            "read_file_tool", "code_symbol_tool",
            "grep_search_tool", "python_lint_tool",
            "run_test_for_tool", "cli_tool",
        }
        action_phase_tools = {
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "trigger_self_restart_tool",
            "apply_patch_tool",
            "write_file_tool",
            "task_create_tool",
            "task_update_tool",
            "plan_update_tool",
        }

        if tool_name in {"read_file_tool", "code_symbol_tool", "grep_search_tool"}:
            session.note_diagnostic_inspection()
            session.note_diagnostic_observation()

        if tool_name == "read_file_tool":
            self._record_file_read(session, tool_args, result_text, tool_name)
        elif tool_name == "code_symbol_tool" and str((tool_args or {}).get("mode") or "").lower() == "inspect":
            path = str((tool_args or {}).get("file_path") or "")
            entity = str((tool_args or {}).get("symbol") or (tool_args or {}).get("query") or "")
            if path:
                session.clear_pending_continuation(path=path)
            if entity:
                session.record_read_entity(path, entity)
        elif tool_name == "grep_search_tool":
            query = str((tool_args or {}).get("regex_pattern") or "")
            scope = str((tool_args or {}).get("search_dir") or "")
            session.record_search_query(
                query,
                scope,
            )

        if tool_name in reading_signal_tools:
            sufficiency = session.evaluate_reading_sufficiency()
            if sufficiency:
                session.set_reading_sufficiency(sufficiency)
        elif tool_name in action_phase_tools:
            session.clear_reading_guidance()

    def _detect_tool_pattern(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """识别高价值重复失败模式。"""
        if tool_name != "cli_tool":
            return None
        command = str((tool_args or {}).get("command") or "")
        return _detect_unquoted_cli_operator(command)

    @staticmethod
    def _pattern_hint(pattern: str) -> str:
        if pattern == "cli_tool:command_chain":
            return "拆成多个独立工具调用 / 分开执行 python 与 pytest / 仅在已授权时使用专用读写工具"
        if pattern == "cli_tool:pipe":
            return "无 pipe 的有界命令 / 无 pipe 的 git 子命令 / 已授权的专用读搜工具"
        if pattern == "cli_tool:subexpression":
            return "有界命令 / 专用 Python 工具 / 显式参数传递"
        return ""

    @staticmethod
    def _record_file_read(session, tool_args: dict, result_text: str, tool_name: str):
        file_path = str((tool_args or {}).get("file_path") or "")
        if not file_path:
            return
        session.clear_pending_continuation(path=file_path)
        match = re.search(r"\[区间\]\s*第\s*(\d+)-(\d+)\s*行", result_text)
        if match:
            start_line = int(match.group(1))
            end_line = int(match.group(2))
            session.record_read_range(file_path, start_line, end_line, source=tool_name)
        else:
            offset = int((tool_args or {}).get("offset") or 0)
            max_lines = int((tool_args or {}).get("max_lines") or 0)
            if max_lines > 0:
                start_line = offset + 1
                end_line = offset + max_lines
                session.record_read_range(file_path, start_line, end_line, source=tool_name)

    def _try_auto_update_map(self, tool_name: str, tool_args: dict):
        """文件修改工具执行成功后，自动触发代码库地图和 Git 注意力刷新。"""
        try:
            from core.prompt_manager.codebase_map_builder import (
                is_file_modifying_tool,
                extract_file_path,
                on_file_modified,
            )
            from core.infrastructure.git_memory import get_git_memory_service
            from core.infrastructure.event_bus import EventNames
            if is_file_modifying_tool(tool_name):
                filepath = extract_file_path(tool_name, tool_args)
                if filepath:
                    self._event_bus.publish(EventNames.WORKSPACE_FILE_MODIFIED, {
                        "path": filepath,
                        "tool_name": tool_name,
                    })
                    on_file_modified(filepath)
                    get_git_memory_service().note_file_modified(filepath)
        except Exception as exc:
            _debug_logger.warning(f"[工具副作用] 文件修改后通知失败: {type(exc).__name__}: {exc}")


# 全局工具执行器单例
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器单例"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
