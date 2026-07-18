# -*- coding: utf-8 -*-
"""工具生命周期桥接器。

将工具执行、结果回写、生命周期动作派生从 agent.py 主循环中抽离，
让主循环只保留高层调度职责。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, ToolMessage

from core.llm.types import CanonicalToolCall, CanonicalToolResult
from core.infrastructure.llm_utils import parse_tool_args
from core.infrastructure.tool_result import (
    infer_tool_business_success,
    package_tool_result_facts,
    project_runtime_tool_metadata,
    render_tool_result_for_model,
    RuntimeToolMetadata,
)
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger
from core.ui.cli_ui import get_ui
from tools.rebirth_tools import handle_restart_request


ToolExecuteFn = Callable[..., Tuple[Any, Optional[str]]]
ToolGuardFn = Callable[[str, dict], Optional[str]]
ToolResultObserverFn = Callable[[Dict[str, Any], Any, Optional[str]], None]
ToolRuntimeMetadataObserverFn = Callable[[Dict[str, Any], RuntimeToolMetadata], None]


def _coerce_result_status(value: Any) -> str:
    return str(value or "").lstrip("\ufeff").strip().lower()


class ToolLifecycleBridge:
    """负责工具调用的执行、结果回写与生命周期动作派生。"""

    # 显式列出已知 read-only 的工具，让 execute_tools 把连续的 read-only 调用
    # 用 threadpool 并发执行；mutating 工具仍走串行，且 read-only 与 mutating
    # 之间保持原序边界。保守白名单 —— 不在表里的一律按 mutating 处理。
    READONLY_TOOL_NAMES: ClassVar[set[str]] = {
        "read_file_tool",
        "grep_search_tool",
        "glob_tool",
        "glob_search_tool",
        "list_directory_tool",
        "list_files_tool",
        "web_search_tool",
        "web_fetch_tool",
        "fetch_url_tool",
        "get_git_status_summary_tool",
        "get_recent_changes_tool",
        "get_current_goal_tool",
        "get_core_context_tool",
        "task_list_tool",
        "read_memory_tool",
        "get_memory_summary_tool",
        "code_symbol_tool",
        "conversation_log_inspect_tool",
        "history_search_tool",
        "history_fetch_tool",
        "history_timeline_tool",
        "history_checkpoint_tool",
        "search_memory_tool",
    }

    DEFAULT_PARALLEL_READONLY_WORKERS: ClassVar[int] = 4

    @classmethod
    def is_readonly_tool(cls, tool_name: Any) -> bool:
        return str(tool_name or "").strip() in cls.READONLY_TOOL_NAMES

    def __init__(
        self,
        *,
        tool_executor_execute: ToolExecuteFn,
        tool_guard: Optional[ToolGuardFn] = None,
        tool_result_observer: Optional[ToolResultObserverFn] = None,
        runtime_metadata_observer: Optional[ToolRuntimeMetadataObserverFn] = None,
        post_close_action_pending: Optional[Callable[[], bool]] = None,
        self_modified: bool = False,
    ) -> None:
        self._tool_executor_execute = tool_executor_execute
        self._tool_guard = tool_guard
        self._tool_result_observer = tool_result_observer
        self._runtime_metadata_observer = runtime_metadata_observer
        self._post_close_action_pending = post_close_action_pending
        self._self_modified = self_modified

    def execute_tool(self, tool_call: Dict[str, Any], messages: list) -> tuple:
        """执行单个工具调用。"""
        ui = get_ui()
        tool_name = tool_call.get("name", "unknown")
        tool_args = parse_tool_args(
            tool_call.get("args") or tool_call.get("arguments") or {}
        )
        tool_call_id = tool_call.get("id", None)

        _debug_logger.tool_start(tool_name, tool_args)

        if self._tool_guard:
            blocked_reason = self._tool_guard(tool_name, tool_args)
            if blocked_reason:
                ui.update_status("ERROR")
                logger.log_tool_call(
                    tool_name,
                    tool_args,
                    blocked_reason,
                    status="error",
                    tool_call_id=tool_call_id,
                )
                _debug_logger.warning(f"[工具护栏] {tool_name} 被短路: {blocked_reason}", tag="TOOL")
                self._observe_tool_result(tool_call, blocked_reason, None)
                return (blocked_reason, None)

        if tool_name == "trigger_self_restart_tool":
            from core.authorization.tool_authorization_service import authorize_tool_execution

            authorization = authorize_tool_execution(
                tool_name=tool_name,
                tool_call_id=str(tool_call_id or "").strip(),
            )
            if authorization.enforced and not authorization.allowed:
                blocked_reason = authorization.message
                ui.update_status("ERROR")
                logger.log_tool_call(
                    tool_name,
                    tool_args,
                    blocked_reason,
                    status="error",
                    tool_call_id=tool_call_id,
                )
                _debug_logger.warning(
                    f"[工具授权] {tool_name} 被 canonical execution authorization 拦截: {authorization.code}",
                    tag="TOOL",
                )
                self._observe_tool_result(tool_call, blocked_reason, None)
                return (blocked_reason, None)
            ui.update_status("ACTING")
            result, action = handle_restart_request(
                tool_args=tool_args,
                messages=messages,
                self_modified=self._self_modified,
            )
            logger.log_tool_call(
                tool_name,
                tool_args,
                str(result) if result else "",
                status="success",
                tool_call_id=tool_call_id,
            )
            self._observe_tool_result(tool_call, result, action)
            return (result, action)

        ui.update_status("ACTING")
        result, tool_action = self._tool_executor_execute(
            tool_name,
            tool_args,
            tool_call_id=str(tool_call_id or "").strip(),
        )
        action = tool_action or self.derive_lifecycle_action(
            tool_name,
            result,
            post_close_action_pending=self._has_post_close_action_pending(),
        )
        business_success = infer_tool_business_success(result)
        is_err = not business_success
        ui.update_status("ERROR" if is_err else "WORKING")

        if result is not None:
            status = "error" if is_err else "success"
            logger.log_tool_call(
                tool_name,
                tool_args,
                str(result),
                status=status,
                tool_call_id=tool_call_id,
            )
            _debug_logger.tool_result(tool_name, str(result), success=not is_err)
        else:
            logger.log_tool_call(
                tool_name,
                tool_args,
                "",
                status="error",
                tool_call_id=tool_call_id,
            )
            _debug_logger.warning(f"[警告] {tool_name} 返回 None", tag="TOOL")

        self._observe_tool_result(tool_call, result, action)
        return (result, action)

    def _observe_tool_result(self, tool_call: Dict[str, Any], result: Any, action: Optional[str]) -> None:
        if self._tool_result_observer is not None:
            try:
                self._tool_result_observer(tool_call, result, action)
            except Exception as exc:
                _debug_logger.warning(f"[工具生命周期] 工具结果观察器回调失败: {type(exc).__name__}: {exc}")

        if self._runtime_metadata_observer is not None:
            try:
                runtime_metadata = project_runtime_tool_metadata(
                    result,
                    tool_name=str(tool_call.get("name") or "").strip(),
                )
                self._runtime_metadata_observer(tool_call, runtime_metadata)
            except Exception as exc:
                _debug_logger.warning(f"[工具生命周期] 运行时元数据观察器回调失败: {type(exc).__name__}: {exc}")

    def _has_post_close_action_pending(self) -> bool:
        if self._post_close_action_pending is None:
            return False
        try:
            return bool(self._post_close_action_pending())
        except Exception as exc:
            _debug_logger.warning(f"[工具生命周期] 查询后续关闭动作失败，按无待处理动作继续: {type(exc).__name__}: {exc}", tag="TOOL")
            return False

    @staticmethod
    def derive_lifecycle_action(
        tool_name: str,
        result: Any,
        *,
        post_close_action_pending: bool = False,
    ) -> Optional[str]:
        """根据工具结果推导生命周期动作。"""
        if tool_name != "close_evolution_transaction_tool":
            return None
        payload: dict[str, Any] | None
        if isinstance(result, dict):
            payload = result
        elif isinstance(result, (bytes, bytearray)):
            try:
                payload = json.loads(result.decode("utf-8", errors="replace").lstrip("\ufeff").strip())
            except Exception as exc:
                _debug_logger.warning(f"[工具生命周期] 关闭事务结果解析失败: {type(exc).__name__}: {exc}")
                return None
        else:
            try:
                payload = json.loads(str(result or "").lstrip("\ufeff").strip())
            except Exception as exc:
                _debug_logger.warning(f"[工具生命周期] 关闭事务结果解析失败: {type(exc).__name__}: {exc}")
                return None
        if not isinstance(payload, dict):
            return None
        status = _coerce_result_status(payload.get("status"))
        transaction_status = _coerce_result_status(payload.get("transaction_status"))
        if status not in {"success", "ok"}:
            return None
        if transaction_status not in {"success", "ok"}:
            return None
        if post_close_action_pending:
            _debug_logger.info(
                "[生命周期] 事务已成功关账，但当前目标仍有后续动作，继续主循环。",
                tag="TOOL",
            )
            return None
        return "turn_complete"

    @staticmethod
    def handle_tool_result(
        tool_call: Dict[str, Any],
        result: Any,
        action: Optional[str],
        messages: list,
    ) -> Optional[CanonicalToolResult]:
        """将工具结果回写到消息历史。"""
        facts = package_tool_result_facts(
            result,
            tool_name=str(tool_call.get("name") or "").strip(),
            action=action,
        )
        result_str = render_tool_result_for_model(facts)
        if action in ("restart", "skip", "hibernated"):
            logger.log_action(action, {"tool": tool_call["name"]})
        tool_call_id = tool_call.get("id")
        canonical_call = tool_call.get("canonical_tool_call")
        canonical_result: Optional[CanonicalToolResult] = None
        if isinstance(canonical_call, CanonicalToolCall):
            is_error = not infer_tool_business_success(result) or action == "skip"
            canonical_result = CanonicalToolResult(
                identity=canonical_call.identity,
                call_id=canonical_call.call_id,
                tool_name=canonical_call.name,
                output=result_str,
                status="failed" if is_error else "completed",
                is_error=is_error,
            )
        if tool_call_id:
            additional_kwargs = (
                {"canonical_tool_result": canonical_result}
                if canonical_result is not None
                else {}
            )
            messages.append(
                ToolMessage(
                    content=result_str,
                    tool_call_id=tool_call_id,
                    additional_kwargs=additional_kwargs,
                )
            )
        else:
            messages.append(AIMessage(content=result_str))
        ToolLifecycleBridge._record_tool_result_binding(
            tool_call=tool_call,
            canonical_call=canonical_call,
            canonical_result=canonical_result,
            action=action,
            model_message_written=bool(tool_call_id),
        )
        if facts.truncated:
            _debug_logger.warning(f"[工具] {tool_call['name']} 结果过长，已截断", tag="TOOL")
        return canonical_result

    @staticmethod
    def _record_tool_result_binding(
        *,
        tool_call: Dict[str, Any],
        canonical_call: Any,
        canonical_result: Optional[CanonicalToolResult],
        action: Optional[str],
        model_message_written: bool,
    ) -> None:
        """Emit one content-free proof that a tool result entered model history."""
        try:
            from core.web.services.runtime_scene_service import record_runtime_scene_event

            identity = getattr(canonical_result, "identity", None) or getattr(canonical_call, "identity", None)
            fields: dict[str, Any] = {
                "toolCallId": str(tool_call.get("id") or "").strip(),
                "toolName": str(tool_call.get("name") or "").strip(),
                "resultBound": bool(model_message_written),
                "canonicalResult": canonical_result is not None,
                "semanticStatus": str(
                    getattr(canonical_result, "status", "")
                    or ("completed" if model_message_written else "missing_call_id")
                ).strip(),
            }
            if action:
                fields["action"] = str(action).strip()
            for source_name, field_name in (
                ("session_id", "sessionId"),
                ("turn_id", "turnId"),
                ("invocation_id", "invocationId"),
            ):
                value = str(getattr(identity, source_name, "") or "").strip()
                if value:
                    fields[field_name] = value
            record_runtime_scene_event(
                "tool_lifecycle",
                "result_binding",
                "tool.result.bound",
                message="Tool result binding to model history recorded.",
                level="info" if model_message_written else "warning",
                outcome="completed" if model_message_written else "missing_call_id",
                fields=fields,
                lifecycle=not model_message_written,
            )
        except Exception as exc:
            _debug_logger.warning(
                f"[工具生命周期] 记录工具结果绑定失败: {type(exc).__name__}: {exc}",
                tag="TOOL",
            )

    def execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: list,
        *,
        max_parallel_readonly: Optional[int] = None,
    ) -> Optional[str]:
        """按原序执行工具，read-only 段并发，mutating 段串行；返回生命周期动作。

        分批策略：连续 read-only 调用合成一个并行 batch；mutating 调用各自成串行
        batch。这样保证 mutating 之间、mutating 与 read-only 之间的顺序不变，
        只在已确认 read-only 的段内提升并发，避免误判副作用。
        """

        if not tool_calls:
            return None

        workers_cap = int(max_parallel_readonly or self.DEFAULT_PARALLEL_READONLY_WORKERS)
        lifecycle_action: Optional[str] = None
        for batch in self._partition_tool_calls(tool_calls):
            if len(batch) == 1:
                tool_call = batch[0]
                result, action = self.execute_tool(tool_call, messages)
                self.handle_tool_result(tool_call, result, action, messages)
                if action in ("restart", "hibernated", "turn_complete"):
                    lifecycle_action = action
                    break
                continue
            results = self._execute_readonly_batch(batch, messages, workers=workers_cap)
            for tool_call, (result, action) in zip(batch, results):
                self.handle_tool_result(tool_call, result, action, messages)
                if action in ("restart", "hibernated", "turn_complete"):
                    # read-only 工具理论上不应触发生命周期切换，但出现就尊重它。
                    lifecycle_action = action
                    break
            if lifecycle_action:
                break
        return lifecycle_action

    def _partition_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """把 tool_calls 切成保留原序的 batch 序列：read-only 连续段合一批，其余各自单批。"""

        batches: List[List[Dict[str, Any]]] = []
        readonly_buf: List[Dict[str, Any]] = []
        for tc in tool_calls:
            if self.is_readonly_tool(tc.get("name")):
                readonly_buf.append(tc)
                continue
            if readonly_buf:
                batches.append(readonly_buf)
                readonly_buf = []
            batches.append([tc])
        if readonly_buf:
            batches.append(readonly_buf)
        return batches

    def _execute_readonly_batch(
        self,
        batch: List[Dict[str, Any]],
        messages: list,
        *,
        workers: int,
    ) -> List[Tuple[Any, Optional[str]]]:
        """并发执行 read-only batch，按 batch 原序返回结果。

        每个 worker 独立调 execute_tool。为了避免异常工具拖垮整个 batch，每个 future
        单独归档结果；失败工具回写错误占位，成功工具仍按原序进入消息历史。
        """

        worker_count = max(1, min(workers, len(batch)))
        results: List[Tuple[Any, Optional[str]] | None] = [None] * len(batch)
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="readonly-tool",
        ) as pool:
            futures = {
                pool.submit(copy_context().run, self.execute_tool, tc, list(messages)): index
                for index, tc in enumerate(batch)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    tool_call = batch[index]
                    results[index] = (self._readonly_batch_error_result(tool_call, exc), None)
                    _debug_logger.warning(
                        f"[工具生命周期] read-only batch 工具失败但不终止整批: "
                        f"{tool_call.get('name', 'unknown')} {type(exc).__name__}: {exc}",
                        tag="TOOL",
                    )
        return [
            item
            if item is not None
            else (
                self._readonly_batch_error_result(
                    batch[index],
                    RuntimeError("missing readonly batch result"),
                ),
                None,
            )
            for index, item in enumerate(results)
        ]

    @staticmethod
    def _readonly_batch_error_result(tool_call: Dict[str, Any], exc: Exception) -> str:
        tool_name = str(tool_call.get("name") or "unknown")
        return f"[错误] read-only 工具 {tool_name} 执行失败: {type(exc).__name__}: {exc}"
