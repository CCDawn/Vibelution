# -*- coding: utf-8 -*-
"""
Task Classifier - 工具任务类型分类器

根据工具名称分类任务类型，用于策略选择和优先级优化。

功能：
- 根据工具名判断任务类型（code_read/write/analysis/search/memory/task/system）
- 纯函数，无 Agent 依赖

使用方式：
    from core.decision.task_classifier import classify_task_type
    task_type = classify_task_type("read_local_file")
"""

from __future__ import annotations

from typing import Literal


# ============================================================================
# 任务类型分类映射
# ============================================================================

TASK_CATEGORIES: dict[str, list[str]] = {
    "code_read": [
        "read_local_file", "grep_search", "grep_file",
        "list_directory", "get_file_info", "get_code_structure",
    ],
    "code_write": [
        "edit_local_file", "create_new_file", "create_file",
        "write_file", "append_to_file",
    ],
    "code_analysis": [
        "analyze_code", "get_code_structure", "get_function_structure",
        "get_class_structure", "analyze_file_quality",
    ],
    "search": [
        "web_search", "search_code", "grep_search",
        "semantic_search", "find_files",
    ],
    "memory": [
        "read_memory", "write_memory", "read_dynamic_prompt",
        "write_dynamic_prompt", "load_memory_tools",
    ],
    "task": [
        "set_plan", "set_generation_task", "tick_subtask",
        "update_task_status", "get_task_list",
    ],
    "system": [
        "trigger_self_restart_tool", "compress_context",
        "enter_hibernation", "exit_hibernation",
    ],
}


# ============================================================================
# 分类函数
# ============================================================================

def classify_task_type(tool_name: str) -> Literal["code_read", "code_write", "code_analysis", "search", "memory", "task", "system", "general"]:
    """
    根据工具名称分类任务类型

    Args:
        tool_name: 工具名称

    Returns:
        任务类型：
        - code_read: 代码读取类
        - code_write: 代码写入类
        - code_analysis: 代码分析类
        - search: 搜索类
        - memory: 记忆类
        - task: 任务管理类
        - system: 系统类
        - general: 其他/通用
    """
    if not tool_name:
        return "general"

    for category, tools in TASK_CATEGORIES.items():
        if tool_name in tools:
            return category  # type: ignore

    return "general"


def get_task_category_tools(category: str) -> list[str]:
    """
    获取指定类别的所有工具列表

    Args:
        category: 任务类型

    Returns:
        该类型对应的工具名称列表
    """
    return TASK_CATEGORIES.get(category, [])


def is_task_type(tool_name: str, category: str) -> bool:
    """
    判断工具是否属于指定类别

    Args:
        tool_name: 工具名称
        category: 任务类型

    Returns:
        True if 工具属于该类别
    """
    return classify_task_type(tool_name) == category


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "classify_task_type",
    "get_task_category_tools",
    "is_task_type",
    "TASK_CATEGORIES",
]
