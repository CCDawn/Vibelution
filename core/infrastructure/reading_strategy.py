# -*- coding: utf-8 -*-
"""
最小阅读策略器

职责：
- 根据当前任务文本与状态推断阅读任务类型
- 为不同任务类型给出推荐读取工具
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ReadingStrategy:
    task_type: str
    recommended_tools: List[str]
    rationale: str


def infer_reading_task(prompt: str = "", current_status: str = "", last_validation: str = "") -> str:
    text = " ".join(part for part in [prompt or "", current_status or "", last_validation or ""] if part).lower()

    if any(word in text for word in ["pytest", "lint", "compile", "测试", "验证", "报错", "失败", "error", "traceback"]):
        return "verify"
    if any(word in text for word in ["修改", "重构", "修复", "apply_patch", "edit", "patch", "replace"]):
        return "modify"
    if any(word in text for word in ["为什么", "原因", "分析", "diagnose", "归因", "复盘"]):
        return "analyze"
    if any(word in text for word in ["理解", "看看", "read", "understand", "结构", "实现"]):
        return "understand"
    return "locate"


def build_reading_strategy(prompt: str = "", current_status: str = "", last_validation: str = "") -> ReadingStrategy:
    task_type = infer_reading_task(prompt=prompt, current_status=current_status, last_validation=last_validation)
    if task_type == "verify":
        return ReadingStrategy(
            task_type=task_type,
            recommended_tools=["grep_search_tool", "read_file_tool", "python_lint_tool"],
            rationale="先看验证输出和命中位置，再分页读取相关片段。",
        )
    if task_type == "modify":
        return ReadingStrategy(
            task_type=task_type,
            recommended_tools=["code_symbol_tool", "read_file_tool"],
            rationale="优先用代码图谱确认影响范围和候选测试，再补局部文件上下文。",
        )
    if task_type == "analyze":
        return ReadingStrategy(
            task_type=task_type,
            recommended_tools=["grep_search_tool", "code_symbol_tool", "read_file_tool"],
            rationale="先定位症状路径，再补局部证据做归因。",
        )
    if task_type == "understand":
        return ReadingStrategy(
            task_type=task_type,
            recommended_tools=["code_symbol_tool", "read_file_tool"],
            rationale="先看项目图谱，再读目标文件、符号和局部上下文。",
        )
    return ReadingStrategy(
        task_type="locate",
        recommended_tools=["grep_search_tool", "code_symbol_tool"],
        rationale="先缩小范围，再用代码图谱决定读哪个文件、符号或影响链。",
    )


__all__ = ["ReadingStrategy", "infer_reading_task", "build_reading_strategy"]
