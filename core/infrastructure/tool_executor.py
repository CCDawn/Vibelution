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
from typing import Dict, Callable, Any, Optional, List
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
        """注册默认工具映射"""
        from tools import (
            # Shell 工具
            read_file_tool, list_directory_tool, edit_file_tool, create_file_tool,
            check_python_syntax_tool, extract_symbols_tool, backup_project_tool,
            cleanup_test_files_tool, execute_shell_command_tool, run_powershell_tool,
            run_batch_tool, self_test_tool, get_agent_status_tool,
            # 记忆工具
            read_memory_tool, commit_compressed_memory_tool, get_generation_tool,
            get_current_goal_tool, get_core_context_tool, read_generation_archive_tool,
            list_archives_tool, read_dynamic_prompt_tool, update_generation_task_tool,
            add_insight_to_dynamic_tool, record_codebase_insight_tool, get_global_codebase_map_tool,
            get_memory_summary_tool,
            # 搜索工具
            grep_search_tool, find_function_calls_tool, find_definitions_tool,
            search_imports_tool, search_and_read_tool,
            # 代码分析工具
            apply_diff_edit_tool, validate_diff_format_tool, preview_diff_tool,
            get_code_entity_tool, list_file_entities_tool, get_file_entities_tool,
            # 任务工具
            set_plan_tool, tick_subtask_tool, modify_task_tool,
            add_task_tool, remove_task_tool, get_task_status_tool, check_restart_block_tool,
            # 重生工具
            trigger_self_restart_tool, enter_hibernation_tool,
            # 额外的工具别名 (LangChain @tool 装饰器会使用完整函数名)
            update_generation_task_tool,
            clear_generation_task,
            write_dynamic_prompt_tool,
        )

        # 构建工具映射
        self._tool_map = {
            # Shell 工具
            "read_file": read_file_tool,
            "read_file_tool": read_file_tool,
            "list_directory": list_directory_tool,
            "list_directory_tool": list_directory_tool,
            "edit_file": edit_file_tool,
            "edit_file_tool": edit_file_tool,
            "create_file": create_file_tool,
            "create_file_tool": create_file_tool,
            "check_python_syntax": check_python_syntax_tool,
            "check_python_syntax_tool": check_python_syntax_tool,
            "extract_symbols": extract_symbols_tool,
            "extract_symbols_tool": extract_symbols_tool,
            "backup_project": backup_project_tool,
            "backup_project_tool": backup_project_tool,
            "cleanup_test_files": cleanup_test_files_tool,
            "cleanup_test_files_tool": cleanup_test_files_tool,
            "execute_shell_command": execute_shell_command_tool,
            "execute_shell_command_tool": execute_shell_command_tool,
            "run_powershell": run_powershell_tool,
            "run_powershell_tool": run_powershell_tool,
            # 任务工具 (别名映射)
            "set_plan": set_plan_tool,
            "set_plan_tool": set_plan_tool,
            "tick_subtask": tick_subtask_tool,
            "tick_subtask_tool": tick_subtask_tool,
            "modify_task": modify_task_tool,
            "modify_task_tool": modify_task_tool,
            "add_task": add_task_tool,
            "add_task_tool": add_task_tool,
            "remove_task": remove_task_tool,
            "remove_task_tool": remove_task_tool,
            "get_task_status": get_task_status_tool,
            "get_task_status_tool": get_task_status_tool,
            "check_restart_block": check_restart_block_tool,
            "check_restart_block_tool": check_restart_block_tool,
            # 更新后的工具名
            "set_generation_task_tool": update_generation_task_tool,
            "update_generation_task_tool": update_generation_task_tool,
            # 重生工具 (别名映射)
            "trigger_self_restart": trigger_self_restart_tool,
            "trigger_self_restart_tool": trigger_self_restart_tool,
            "enter_hibernation": enter_hibernation_tool,
            "enter_hibernation_tool": enter_hibernation_tool,
            "run_batch": run_batch_tool,
            "run_batch_tool": run_batch_tool,
            "self_test": self_test_tool,
            "self_test_tool": self_test_tool,
            "get_agent_status": get_agent_status_tool,
            "get_agent_status_tool": get_agent_status_tool,
            # 记忆工具（双重注册：无后缀 + _tool 后缀，与 LLM tool name 一致）
            "read_memory": read_memory_tool,
            "read_memory_tool": read_memory_tool,
            "commit_compressed_memory": commit_compressed_memory_tool,
            "commit_compressed_memory_tool": commit_compressed_memory_tool,
            "get_generation": get_generation_tool,
            "get_generation_tool": get_generation_tool,
            "get_current_goal": get_current_goal_tool,
            "get_current_goal_tool": get_current_goal_tool,
            "get_core_context": get_core_context_tool,
            "get_core_context_tool": get_core_context_tool,
            "read_generation_archive": read_generation_archive_tool,
            "read_generation_archive_tool": read_generation_archive_tool,
            "list_archives": list_archives_tool,
            "list_archives_tool": list_archives_tool,
            "read_dynamic_prompt": read_dynamic_prompt_tool,
            "read_dynamic_prompt_tool": read_dynamic_prompt_tool,
            "update_generation_task": update_generation_task_tool,
            "update_generation_task_tool": update_generation_task_tool,
            "add_insight_to_dynamic": add_insight_to_dynamic_tool,
            "add_insight_to_dynamic_tool": add_insight_to_dynamic_tool,
            "record_codebase_insight": record_codebase_insight_tool,
            "record_codebase_insight_tool": record_codebase_insight_tool,
            "get_global_codebase_map": get_global_codebase_map_tool,
            "get_global_codebase_map_tool": get_global_codebase_map_tool,
            "get_memory_summary": get_memory_summary_tool,
            "get_memory_summary_tool": get_memory_summary_tool,
            "clear_generation_task": clear_generation_task,
            "clear_generation_task_tool": clear_generation_task,
            "write_dynamic_prompt": write_dynamic_prompt_tool,
            "write_dynamic_prompt_tool": write_dynamic_prompt_tool,
            # 搜索工具 (带 _tool 别名)
            "grep_search": grep_search_tool,
            "grep_search_tool": grep_search_tool,
            "find_function_calls": find_function_calls_tool,
            "find_function_calls_tool": find_function_calls_tool,
            "find_definitions": find_definitions_tool,
            "find_definitions_tool": find_definitions_tool,
            "search_imports": search_imports_tool,
            "search_imports_tool": search_imports_tool,
            "search_and_read": search_and_read_tool,
            "search_and_read_tool": search_and_read_tool,
            # 代码分析工具
            "apply_diff_edit": apply_diff_edit_tool,
            "apply_diff_edit_tool": apply_diff_edit_tool,
            "validate_diff_format": validate_diff_format_tool,
            "validate_diff_format_tool": validate_diff_format_tool,
            "preview_diff": preview_diff_tool,
            "preview_diff_tool": preview_diff_tool,
            "get_code_entity": get_code_entity_tool,
            "get_code_entity_tool": get_code_entity_tool,
            "list_file_entities": list_file_entities_tool,
            "list_file_entities_tool": list_file_entities_tool,
            "get_file_entities": get_file_entities_tool,
            "get_file_entities_tool": get_file_entities_tool,
            # CLI 工具
            "cli_tool": execute_shell_command_tool,
            # 项目结构工具
            "get_project_structure_tool": list_directory_tool,
            # 任务工具
            "set_plan": set_plan_tool,
            "tick_subtask": tick_subtask_tool,
            "modify_task": modify_task_tool,
            "add_task": add_task_tool,
            "remove_task": remove_task_tool,
            "get_task_status": get_task_status_tool,
            "check_restart_block": check_restart_block_tool,
            # 重生工具
            "trigger_self_restart": trigger_self_restart_tool,
            "enter_hibernation": enter_hibernation_tool,
        }

        # 默认超时配置
        self._timeout_map = {
            "execute_shell_command": 60,
            "run_powershell": 60,
            "run_batch": 60,
            "self_test": 30,
            "check_python_syntax": 10,
            "grep_search": 30,
            "find_function_calls": 30,
            "find_definitions": 30,
            "search_and_read": 30,
            "backup_project": 60,
        }
        self._retryable_tools = {"grep_search", "search_and_read"}

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

    def execute_parallel(
        self,
        tool_calls: List[Dict],
        handle_tool_result_callback: Callable = None,
    ) -> List[tuple]:
        """
        并行执行多个工具调用

        Args:
            tool_calls: 工具调用列表，每个元素包含 'name' 和 'args'
            handle_tool_result_callback: 处理结果的回调函数 (可选)

        Returns:
            [(tool_call, result, action), ...] 结果列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from core.logging.logger import debug as _debug_logger

        def _execute_single(tc):
            """执行单个工具调用"""
            tool_name = tc.get('name', 'unknown')
            tool_args = tc.get('args') or tc.get('arguments') or {}

            # 解析 JSON 字符串
            if isinstance(tool_args, str):
                try:
                    import json
                    tool_args = json.loads(tool_args)
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
            elif not isinstance(tool_args, dict):
                try:
                    import json
                    tool_args = json.loads(str(tool_args))
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

            return self.execute(tool_name, tool_args)

        results = []
        with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
            futures = {
                pool.submit(_execute_single, tc): tc
                for tc in tool_calls
            }
            for future in as_completed(futures):
                tc = futures[future]
                try:
                    result, action = future.result()
                    results.append((tc, result, action))
                    if handle_tool_result_callback:
                        handle_tool_result_callback(tc, result, action)
                except Exception as e:
                    result = f"[并行执行异常] {type(e).__name__}: {str(e)}"
                    results.append((tc, result, None))
                    if handle_tool_result_callback:
                        handle_tool_result_callback(tc, result, None)

        # 按原顺序排序（保持确定性）
        results.sort(key=lambda x: tool_calls.index(x[0]))

        _debug_logger.info(
            f"[并行] {len(tool_calls)} 个工具执行完成",
            tag="PARALLEL"
        )
        return results


# 全局工具执行器单例
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器单例"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
