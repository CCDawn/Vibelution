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
from typing import Dict, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# 核心模块导入
from core.infrastructure.event_bus import get_event_bus, EventNames


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
        self._register_default_tools()

    def _register_default_tools(self):
        """注册默认工具映射 — Key_Tools 工具自动推导，程序化工具手动注册"""
        from tools import (
            list_directory_tool,
            check_python_syntax_tool, extract_symbols_tool, backup_project_tool,
            cleanup_test_files_tool, execute_shell_command_tool, run_powershell_tool,
            run_batch_tool, self_test_tool, get_agent_status_tool,
            read_memory_tool,
            get_current_goal_tool, get_core_context_tool,
            read_dynamic_prompt_tool,
            add_insight_to_dynamic_tool,
            get_memory_summary_tool, write_dynamic_prompt_tool,
            find_function_calls_tool, find_definitions_tool,
            search_imports_tool, search_and_read_tool,
            preview_diff_tool, get_file_entities_tool,
        )
        from core.infrastructure.mental_model import (
            get_mental_state_tool, update_diagnosis_rules_tool,
            update_self_model_tool, get_self_model_tool, record_evolution_tool,
        )

        # ── 从 Key_Tools 自动推导工具映射 ──────────────────────────────
        from tools.Key_Tools import create_key_tools
        for tool in create_key_tools():
            self._tool_map[tool.name] = tool.func

        # ── 程序化工具手动注册 (不对 LLM 暴露) ─────────────────────────
        self._tool_map.update({
            "list_directory": list_directory_tool,
            "check_python_syntax": check_python_syntax_tool,
            "extract_symbols": extract_symbols_tool,
            "backup_project": backup_project_tool,
            "cleanup_test_files": cleanup_test_files_tool,
            "execute_shell_command": execute_shell_command_tool,
            "run_powershell": run_powershell_tool,
            "run_batch": run_batch_tool,
            "self_test": self_test_tool,
            "get_agent_status": get_agent_status_tool,
            "read_memory": read_memory_tool,
            "get_current_goal": get_current_goal_tool,
            "get_core_context": get_core_context_tool,
            "read_dynamic_prompt": read_dynamic_prompt_tool,
            "add_insight_to_dynamic": add_insight_to_dynamic_tool,
            "get_memory_summary": get_memory_summary_tool,
            "write_dynamic_prompt": write_dynamic_prompt_tool,
            "find_function_calls": find_function_calls_tool,
            "find_definitions": find_definitions_tool,
            "search_imports": search_imports_tool,
            "search_and_read": search_and_read_tool,
            "preview_diff": preview_diff_tool,
            "get_file_entities": get_file_entities_tool,
            # 心智模型工具
            "get_mental_state": get_mental_state_tool,
            "update_diagnosis_rules": update_diagnosis_rules_tool,
            "update_self_model": update_self_model_tool,
            "get_self_model": get_self_model_tool,
            "record_evolution": record_evolution_tool,
        })

        self._timeout_map = {
            "execute_shell_command": 60,
            "run_powershell": 60,
            "run_batch": 60,
            "self_test": 30,
            "check_python_syntax": 10,
            "grep_search_tool": 30,
            "find_function_calls": 30,
            "find_definitions": 30,
            "search_and_read": 30,
            "backup_project": 60,
            "web_search_tool": 30,
        }
        self._retryable_tools = {"grep_search_tool", "search_and_read"}

    def register_tool(self, name: str, func: Callable, timeout: int = 30):
        """注册自定义工具"""
        self._tool_map[name] = func
        self._timeout_map[name] = timeout

    def execute(self, tool_name: str, tool_args: dict) -> tuple:
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
        # 发布工具开始事件
        self._event_bus.publish(EventNames.TOOL_START, {
            "name": tool_name,
            "args": tool_args,
        })

        if tool_name not in self._tool_map:
            error_msg = f"[错误] 未知工具 {tool_name}"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)

        func = self._tool_map[tool_name]
        timeout = self._timeout_map.get(tool_name, 30)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, **tool_args)
                result = future.result(timeout=timeout)

            # 发布工具成功事件
            self._event_bus.publish(EventNames.TOOL_SUCCESS, {
                "name": tool_name,
                "result": str(result)[:200],
            })

            # ── 自动更新代码库地图（检测文件修改工具）──
            self._try_auto_update_map(tool_name, tool_args)

            return (result, None)

        except TimeoutError:
            error_msg = f"[超时] {tool_name} 执行超时 ({timeout}秒)"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)

        except Exception as e:
            error_msg = f"[错误] {type(e).__name__}: {e}"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)

    def _try_auto_update_map(self, tool_name: str, tool_args: dict):
        """文件修改工具执行成功后，自动触发代码库地图增量更新。"""
        try:
            from core.prompt_manager.codebase_map_builder import (
                is_file_modifying_tool,
                extract_file_path,
                on_file_modified,
            )
            if is_file_modifying_tool(tool_name):
                filepath = extract_file_path(tool_name, tool_args)
                if filepath:
                    on_file_modified(filepath)
        except Exception:
            pass


# 全局工具执行器单例
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器单例"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
