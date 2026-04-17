#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优先级优化器 (PriorityOptimizer) - 智能任务优先级管理

Phase 6 核心模块

功能：
- 多维度优先级计算
- 动态优先级调整
- 资源约束下的优化
- 优先级队列管理
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# 优先级定义
# ============================================================================

@dataclass
class PriorityScore:
    """优先级分数"""
    base: float = 0.0
    urgency: float = 0.0
    importance: float = 0.0
    effort_ratio: float = 0.0
    deadline: float = 0.0
    dependency: float = 0.0

    @property
    def total(self) -> float:
        """总分"""
        return self.base + self.urgency + self.importance + \
               self.effort_ratio + self.deadline + self.dependency


@dataclass
class Task:
    """任务"""
    task_id: str
    name: str
    description: str = ""
    priority: float = 0.5
    estimated_time: float = 1.0  # 小时
    deadline: Optional[datetime] = None
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class OptimizationResult:
    """优化结果"""
    task_order: List[str]  # 任务 ID 顺序
    scores: Dict[str, float]
    total_time: float
    constraints_satisfied: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 优先级优化器
# ============================================================================

class PriorityOptimizer:
    """
    优先级优化器

    智能管理任务优先级：

    优化流程：
    1. 收集任务信息
    2. 计算多维度优先级
    3. 应用约束条件
    4. 优化任务顺序
    5. 持续监控调整

    使用方式：
        optimizer = PriorityOptimizer()
        optimizer.add_task(task)
        result = optimizer.optimize(constraints)
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        max_time_per_cycle: float = 4.0,
    ):
        """
        初始化优先级优化器

        Args:
            project_root: 项目根目录
            max_time_per_cycle: 每周期最大时间（小时）
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        self.max_time_per_cycle = max_time_per_cycle

        # 任务存储
        self._tasks: Dict[str, Task] = {}
        self._priority_cache: Dict[str, PriorityScore] = {}

        # 历史记录
        self._history: List[OptimizationResult] = []

        # 统计
        self._stats = {
            "tasks_added": 0,
            "optimizations_run": 0,
            "average_priority": 0.5,
        }

    # =========================================================================
    # 任务管理
    # =========================================================================

    def add_task(self, task: Task) -> None:
        """
        添加任务

        Args:
            task: 任务对象
        """
        self._tasks[task.task_id] = task
        self._priority_cache.pop(task.task_id, None)  # 清除缓存
        self._stats["tasks_added"] += 1

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._priority_cache.pop(task_id, None)
            return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs) -> bool:
        """更新任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)

        self._priority_cache.pop(task_id, None)
        return True

    # =========================================================================
    # 优先级计算
    # =========================================================================

    def calculate_priority(
        self,
        task_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PriorityScore:
        """
        计算任务优先级

        Args:
            task_id: 任务 ID
            context: 上下文信息

        Returns:
            优先级分数
        """
        if task_id in self._priority_cache:
            return self._priority_cache[task_id]

        task = self._tasks.get(task_id)
        if not task:
            return PriorityScore()

        score = PriorityScore()

        # 基础优先级
        score.base = task.priority * 0.3

        # 紧迫性（基于截止时间）
        if task.deadline:
            time_left = (task.deadline - datetime.now()).total_seconds()
            hours_left = time_left / 3600
            if hours_left < 0:
                score.urgency = 1.0  # 已过期
            elif hours_left < 2:
                score.urgency = 0.9
            elif hours_left < 8:
                score.urgency = 0.7
            elif hours_left < 24:
                score.urgency = 0.5
            else:
                score.urgency = 0.2

        # 重要性（基于元数据）
        importance = task.metadata.get("importance", 0.5)
        score.importance = importance * 0.2

        # 效率比（工作量/价值）
        effort = task.estimated_time
        value = task.metadata.get("value", 1.0)
        if effort > 0:
            score.effort_ratio = min(value / effort, 1.0) * 0.15

        # 截止时间压力
        if task.deadline:
            score.deadline = min(1.0, 1.0 / (hours_left + 1)) * 0.1

        # 依赖性（阻塞其他任务）
        dependents = self._get_dependent_tasks(task_id)
        score.dependency = min(len(dependents) * 0.05, 0.2)

        # 上下文调整
        if context:
            score = self._adjust_score_with_context(score, task, context)

        # 缓存
        self._priority_cache[task_id] = score

        return score

    def _adjust_score_with_context(
        self,
        score: PriorityScore,
        task: Task,
        context: Dict[str, Any],
    ) -> PriorityScore:
        """根据上下文调整分数"""
        # 时间段调整
        hour = datetime.now().hour
        if task.metadata.get("best_in_morning") and 6 <= hour < 12:
            score.base += 0.1
        if task.metadata.get("best_in_afternoon") and 12 <= hour < 18:
            score.base += 0.1

        # 能量级别调整
        energy = context.get("energy_level", 0.5)
        complexity = task.metadata.get("complexity", 0.5)

        if energy < 0.3 and complexity > 0.7:
            score.base -= 0.2  # 低能量时不做复杂任务

        # 连续任务惩罚（避免同类任务堆积）
        recent_types = context.get("recent_task_types", [])
        current_type = task.metadata.get("type", "default")
        if recent_types and recent_types[-1] == current_type:
            score.base -= 0.1

        return score

    def _get_dependent_tasks(self, task_id: str) -> List[str]:
        """获取依赖此任务的其他任务"""
        dependents = []
        for other_id, other_task in self._tasks.items():
            if task_id in other_task.dependencies:
                dependents.append(other_id)
        return dependents

    # =========================================================================
    # 优化执行
    # =========================================================================

    def optimize(
        self,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> OptimizationResult:
        """
        优化任务顺序

        Args:
            context: 上下文信息
            constraints: 约束条件

        Returns:
            优化结果
        """
        if constraints is None:
            constraints = {}

        max_time = constraints.get("max_time", self.max_time_per_cycle)
        max_tasks = constraints.get("max_tasks", 10)

        # 计算所有任务优先级
        scores = {}
        for task_id in self._tasks:
            score = self.calculate_priority(task_id, context)
            scores[task_id] = score.total

        # 按分数排序
        sorted_tasks = sorted(
            self._tasks.keys(),
            key=lambda tid: scores.get(tid, 0),
            reverse=True,
        )

        # 应用约束
        selected_tasks = []
        total_time = 0.0

        for task_id in sorted_tasks:
            task = self._tasks[task_id]
            task_time = task.estimated_time

            # 检查时间约束
            if total_time + task_time > max_time:
                break

            # 检查依赖约束
            if not self._dependencies_satisfied(task_id, selected_tasks):
                continue

            selected_tasks.append(task_id)
            total_time += task_time

            if len(selected_tasks) >= max_tasks:
                break

        # 再次排序（考虑依赖）
        final_order = self._resolve_dependencies(selected_tasks)

        result = OptimizationResult(
            task_order=final_order,
            scores={tid: scores.get(tid, 0) for tid in final_order},
            total_time=total_time,
            constraints_satisfied=True,
            metadata={
                "optimization_time": datetime.now().isoformat(),
                "total_tasks": len(self._tasks),
                "selected_tasks": len(final_order),
            },
        )

        self._history.append(result)
        self._stats["optimizations_run"] += 1

        return result

    def _dependencies_satisfied(
        self,
        task_id: str,
        completed: List[str],
    ) -> bool:
        """检查依赖是否满足"""
        task = self._tasks.get(task_id)
        if not task:
            return True

        for dep_id in task.dependencies:
            if dep_id not in completed:
                return False

        return True

    def _resolve_dependencies(
        self,
        task_ids: List[str],
    ) -> List[str]:
        """解析依赖，确定最终顺序"""
        result = []
        remaining = set(task_ids)
        completed = set()

        while remaining:
            made_progress = False

            for task_id in list(remaining):
                task = self._tasks[task_id]

                # 检查依赖是否完成
                if all(dep in completed for dep in task.dependencies):
                    result.append(task_id)
                    remaining.remove(task_id)
                    completed.add(task_id)
                    made_progress = True

            if not made_progress:
                # 有循环依赖，任意选择一个
                result.append(next(iter(remaining)))
                remaining.remove(result[-1])

        return result

    # =========================================================================
    # 优先级调整
    # =========================================================================

    def adjust_priority(
        self,
        task_id: str,
        adjustment: float,
        reason: Optional[str] = None,
    ) -> bool:
        """
        调整任务优先级

        Args:
            task_id: 任务 ID
            adjustment: 调整量 (-1.0 ~ 1.0)
            reason: 调整原因

        Returns:
            是否成功
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        # 应用调整（限制范围）
        new_priority = max(0.0, min(1.0, task.priority + adjustment))
        task.priority = new_priority

        # 记录调整历史
        if "adjustments" not in task.metadata:
            task.metadata["adjustments"] = []

        task.metadata["adjustments"].append({
            "timestamp": datetime.now().isoformat(),
            "adjustment": adjustment,
            "reason": reason,
            "new_priority": new_priority,
        })

        # 清除缓存
        self._priority_cache.pop(task_id, None)

        return True

    def boost_task(self, task_id: str, boost: float = 0.2) -> bool:
        """提升任务优先级"""
        return self.adjust_priority(task_id, boost, "boost")

    def postpone_task(self, task_id: str, delay: float = -0.1) -> bool:
        """降低任务优先级"""
        return self.adjust_priority(task_id, delay, "postpone")

    # =========================================================================
    # 统计和分析
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self._tasks:
            return self._stats

        priorities = [t.priority for t in self._tasks.values()]
        times = [t.estimated_time for t in self._tasks.values()]

        return {
            **self._stats,
            "total_tasks": len(self._tasks),
            "average_priority": sum(priorities) / len(priorities),
            "total_estimated_time": sum(times),
            "tasks_with_deadline": sum(
                1 for t in self._tasks.values() if t.deadline
            ),
            "tasks_with_dependencies": sum(
                1 for t in self._tasks.values() if t.dependencies
            ),
        }

    def get_priority_distribution(self) -> Dict[str, int]:
        """获取优先级分布"""
        distribution = {"high": 0, "medium": 0, "low": 0}

        for task in self._tasks.values():
            if task.priority >= 0.7:
                distribution["high"] += 1
            elif task.priority >= 0.4:
                distribution["medium"] += 1
            else:
                distribution["low"] += 1

        return distribution

    def suggest_reevaluate(self) -> List[str]:
        """建议重新评估的任务"""
        suggestions = []

        now = datetime.now()

        for task_id, task in self._tasks.items():
            # 长期未调整的任务
            age = now - task.created_at
            if age > timedelta(days=7):
                suggestions.append(task_id)

            # 截止时间接近但优先级较低
            if task.deadline:
                time_left = task.deadline - now
                if timedelta(hours=2) < time_left < timedelta(hours=24):
                    if task.priority < 0.5:
                        suggestions.append(task_id)

        return list(set(suggestions))

    # =========================================================================
    # 导出和保存
    # =========================================================================

    def export_to_file(self, file_path: Optional[str] = None) -> str:
        """导出任务到文件"""
        if file_path is None:
            file_path = str(
                self.project_root / "workspace" / "tasks" / "priority_queue.json"
            )

        data = {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "description": t.description,
                    "priority": t.priority,
                    "estimated_time": t.estimated_time,
                    "deadline": t.deadline.isoformat() if t.deadline else None,
                    "dependencies": t.dependencies,
                    "metadata": t.metadata,
                    "created_at": t.created_at.isoformat(),
                }
                for t in self._tasks.values()
            ],
            "stats": self.get_statistics(),
        }

        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return file_path

    def import_from_file(self, file_path: str) -> int:
        """从文件导入任务"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        imported = 0
        for task_data in data.get("tasks", []):
            task = Task(
                task_id=task_data["task_id"],
                name=task_data["name"],
                description=task_data.get("description", ""),
                priority=task_data.get("priority", 0.5),
                estimated_time=task_data.get("estimated_time", 1.0),
                deadline=(
                    datetime.fromisoformat(task_data["deadline"])
                    if task_data.get("deadline") else None
                ),
                dependencies=task_data.get("dependencies", []),
                metadata=task_data.get("metadata", {}),
                created_at=(
                    datetime.fromisoformat(task_data["created_at"])
                    if task_data.get("created_at") else datetime.now()
                ),
            )
            self.add_task(task)
            imported += 1

        return imported


# ============================================================================
# 全局单例
# ============================================================================

_priority_optimizer: Optional[PriorityOptimizer] = None


def get_priority_optimizer(
    project_root: Optional[str] = None,
) -> PriorityOptimizer:
    """获取优先级优化器单例"""
    global _priority_optimizer
    if _priority_optimizer is None:
        _priority_optimizer = PriorityOptimizer(project_root)
    return _priority_optimizer


def reset_priority_optimizer() -> None:
    """重置优先级优化器"""
    global _priority_optimizer
    _priority_optimizer = None