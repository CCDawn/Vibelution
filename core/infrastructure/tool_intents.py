# -*- coding: utf-8 -*-
"""
工具意图层定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.logging import debug as _debug_logger


@dataclass(frozen=True)
class ToolIntent:
    name: str
    recommended_tools: List[str]
    description: str


TOOL_INTENTS = {
    "locate_text": ToolIntent(
        name="locate_text",
        recommended_tools=["grep_search_tool"],
        description="先定位文本或关键词命中，再决定下一步精读对象。",
    ),
    "locate_symbol": ToolIntent(
        name="locate_symbol",
        recommended_tools=["code_symbol_tool", "grep_search_tool"],
        description="优先用项目代码图谱确认符号、引用或真实落点。",
    ),
    "locate_calls": ToolIntent(
        name="locate_calls",
        recommended_tools=["grep_search_tool", "code_symbol_tool"],
        description="定位函数、方法或路径引用点。",
    ),
    "inspect_structure": ToolIntent(
        name="inspect_structure",
        recommended_tools=["code_symbol_tool"],
        description="先看项目图谱和文件结构，避免直接吞整文件。",
    ),
    "inspect_entity": ToolIntent(
        name="inspect_entity",
        recommended_tools=["code_symbol_tool"],
        description="精读目标文件、符号和相关上下文。",
    ),
    "inspect_range": ToolIntent(
        name="inspect_range",
        recommended_tools=["read_file_tool"],
        description="分页阅读局部上下文。",
    ),
    "verify_change": ToolIntent(
        name="verify_change",
        recommended_tools=["python_lint_tool", "run_test_for_tool", "cli_tool"],
        description="按 lint / test / compile 闭环验证修改。",
    ),
    "synthesize_answer": ToolIntent(
        name="synthesize_answer",
        recommended_tools=[],
        description="基于已有证据给出结论、修改计划或明确缺口，避免继续机械读取。",
    ),
    "inspect_history": ToolIntent(
        name="inspect_history",
        recommended_tools=[
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
            "get_entity_history_tool",
        ],
        description="查看 Git 变化、实体历史和 worktree 状态。",
    ),
}


def _current_agent_visible_tool_names() -> set[str] | None:
    try:
        from core.web.services.agent_directory_service import (
            current_agent_runtime,
            effective_visible_tool_names_for_current_agent,
        )

        runtime = current_agent_runtime()
        if not str((runtime or {}).get("agentId") or "").strip():
            return None
        return set(effective_visible_tool_names_for_current_agent())
    except Exception as exc:
        _debug_logger.warning(f"[工具意图] 获取当前 Agent 可见工具失败: {type(exc).__name__}: {exc}")
        return None


def _filter_for_current_agent(tool_names: List[str]) -> List[str]:
    visible = _current_agent_visible_tool_names()
    if visible is None:
        return list(tool_names)
    return [name for name in tool_names if name in visible]


def get_tool_intent(name: str, *, respect_current_agent_policy: bool = True) -> ToolIntent | None:
    intent = TOOL_INTENTS.get(name)
    if intent is None or not respect_current_agent_policy:
        return intent
    return ToolIntent(
        name=intent.name,
        recommended_tools=_filter_for_current_agent(intent.recommended_tools),
        description=intent.description,
    )


def humanize_reading_task(task: str) -> str:
    mapping = {
        "locate": "定位",
        "understand": "理解",
        "modify": "修改",
        "verify": "验证",
        "analyze": "分析",
    }
    return mapping.get((task or "").lower(), task or "")


def humanize_tool_intent(intent: str) -> str:
    mapping = {
        "locate_text": "定位文本",
        "locate_symbol": "定位符号",
        "locate_calls": "定位调用",
        "inspect_structure": "查看结构",
        "inspect_entity": "精读实体",
        "inspect_range": "查看片段",
        "verify_change": "验证改动",
        "inspect_history": "查看历史",
        "edit_target": "开始修改",
        "synthesize_answer": "综合结论",
    }
    return mapping.get((intent or "").lower(), intent or "")


def humanize_tool_name(tool_name: str) -> str:
    mapping = {
        "grep_search_tool": "搜索命中",
        "code_symbol_tool": "代码图谱",
        "read_file_tool": "读局部片段",
        "python_lint_tool": "Lint 检查",
        "run_test_for_tool": "运行测试",
        "cli_tool": "命令兜底",
        "apply_diff_edit_tool": "应用修改",
        "get_git_status_summary_tool": "工作区状态",
        "get_recent_changes_tool": "最近变化",
        "get_entity_history_tool": "实体历史",
    }
    return mapping.get(tool_name, tool_name)


def humanize_tool_chain(tool_names: List[str], limit: int | None = None) -> str:
    names = tool_names[:limit] if limit is not None else tool_names
    return " -> ".join(humanize_tool_name(name) for name in names)


__all__ = [
    "ToolIntent",
    "TOOL_INTENTS",
    "get_tool_intent",
    "humanize_reading_task",
    "humanize_tool_intent",
    "humanize_tool_name",
    "humanize_tool_chain",
]
