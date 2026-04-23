# -*- coding: utf-8 -*-
"""
Plan Orchestrator (计划编排器)

职责：
- 接收模型输出的 <plan>...</plan> 纯文本块
- 解析目标 + 任务列表
- 委托 TaskPlanner 存储
- 渲染 Markdown 清单供 PromptManager 注入

数据流：
    模型输出 <plan> 文本
        ↓
    PlanOrchestrator.parse_and_store()
        ↓
    TaskPlanner.create_plan()
        ↓
    PlanOrchestrator.render_checklist()
        ↓
    PromptManager (TASK_CHECKLIST 组件)
        ↓
    系统提示词
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.orchestration.task_planner import (
    get_task_planner,
    TaskPlanner,
    TaskPriority,
)


# ============================================================================
# Plan Orchestrator
# ============================================================================

class PlanOrchestrator:
    """
    计划编排器。

    接收模型输出的 <plan> 文本，解析后委托 TaskPlanner 处理。

    模型输出格式示例：
        <plan>
        目标: 重构错误重试逻辑
        任务:
        - [ ] 1. 分析现有重试机制
        - [ ] 2. 设计统一的重试装饰器
        - [ ] 3. 实现并测试装饰器
        - [ ] 4. 替换现有重试调用点
        </plan>
    """

    PLAN_TAG_PATTERN = re.compile(
        r'<plan>\s*(.*?)\s*</plan>',
        re.DOTALL | re.IGNORECASE,
    )
    GOAL_PATTERN = re.compile(r'目标:\s*(.+)', re.MULTILINE)
    TASK_PATTERN = re.compile(
        r'-\s*\[?\s*\]?\s*\d*\.?\s*(.+)',
        re.MULTILINE,
    )

    def __init__(self, planner: Optional[TaskPlanner] = None):
        self._planner = planner

    @property
    def planner(self) -> TaskPlanner:
        if self._planner is None:
            self._planner = get_task_planner()
        return self._planner

    def extract_plan_tag(self, text: str) -> Optional[str]:
        """
        从文本中提取 <plan>...</plan> 标签内容。

        Args:
            text: 原始文本（可能是模型输出）

        Returns:
            plan 标签内的纯文本，无标签则返回 None
        """
        match = self.PLAN_TAG_PATTERN.search(text)
        return match.group(1).strip() if match else None

    def parse_plan_text(self, raw: str) -> Dict[str, Any]:
        """
        解析 plan 文本，提取 goal 和任务列表。

        Args:
            raw: <plan> 标签内的纯文本

        Returns:
            {"goal": str, "tasks": List[str]}
        """
        goal_match = self.GOAL_PATTERN.search(raw)
        goal = goal_match.group(1).strip() if goal_match else "未命名目标"

        task_descs: List[str] = []
        for m in self.TASK_PATTERN.finditer(raw):
            desc = m.group(1).strip()
            if desc:
                task_descs.append(desc)

        return {"goal": goal, "tasks": task_descs}

    def parse_and_store(self, raw_plan: str) -> str:
        """
        解析 <plan> 文本，存入 TaskPlanner，返回渲染后的清单。

        Args:
            raw_plan: <plan>...</plan> 文本块

        Returns:
            Markdown 格式的任务清单
        """
        parsed = self.parse_plan_text(raw_plan)
        goal = parsed["goal"]
        task_descs = parsed["tasks"]

        if not task_descs:
            return "[❌ 错误] 未能从 plan 中解析出任何任务"

        self.planner.create_plan(
            goal=goal,
            tasks=[{"name": d, "description": d} for d in task_descs],
        )
        return self.render_checklist()

    def render_checklist(self) -> str:
        """
        将 TaskPlanner 当前计划渲染为 Markdown 清单。

        Returns:
            Markdown 格式的清单
        """
        return self.planner.get_current_checklist_markdown()

    def complete_task(self, task_id: int, summary: str) -> str:
        """
        完成任务（打勾），返回更新后的清单。

        Args:
            task_id: 任务编号（1-based 整数，与清单渲染顺序对应）
            summary: 完成摘要

        Returns:
            更新后的 Markdown 清单
        """
        plan = self.planner.get_current_plan()
        if not plan:
            return "[❌ 错误] 当前没有活动计划"

        ordered_ids = list(plan.tasks.keys())
        if task_id < 1 or task_id > len(ordered_ids):
            return f"[❌ 错误] 无效的任务编号 {task_id}，有效范围 1-{len(ordered_ids)}"

        target_id = ordered_ids[task_id - 1]
        ok = self.planner.complete_task(target_id, summary)
        if not ok:
            return f"[❌ 错误] 任务 {task_id} 无法标记为完成（状态不匹配）"

        return self.render_checklist()

    def save(self, plan_dir: Path) -> None:
        """保存当前计划到磁盘"""
        self.planner.save_current_plan(plan_dir)

    def load(self, plan_dir: Path) -> bool:
        """从磁盘恢复计划"""
        return self.planner.load_latest_plan(plan_dir)


# ============================================================================
# 全局单例
# ============================================================================

_orchestrator: Optional[PlanOrchestrator] = None


def get_plan_orchestrator() -> PlanOrchestrator:
    """获取 PlanOrchestrator 单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PlanOrchestrator()
    return _orchestrator


def reset_plan_orchestrator() -> None:
    """重置单例（主要用于测试）"""
    global _orchestrator
    _orchestrator = None


__all__ = [
    "PlanOrchestrator",
    "get_plan_orchestrator",
    "reset_plan_orchestrator",
]
