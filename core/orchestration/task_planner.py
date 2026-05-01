#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task Manager (统一任务管理器)

功能（合并自原 TaskPlanner + TaskManager）：
- 智能任务分解
- 依赖关系管理
- 优先级排序
- 风险评估
- 执行进度跟踪
- tasks.json 持久化
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict


# ============================================================================
# 任务定义
# ============================================================================

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    TRIVIAL = 1


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Task:
    """任务"""
    task_id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    estimated_hours: float = 1.0
    actual_hours: float = 0.0
    deadline: Optional[datetime] = None
    dependencies: List[str] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)  # 子任务 ID 列表
    parent_id: Optional[str] = None
    risk: RiskLevel = RiskLevel.LOW
    assignee: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_summary: str = ""


@dataclass
class TaskPlan:
    """任务计划"""
    plan_id: str
    goal: str
    tasks: Dict[str, Task] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    success_criteria: List[str] = field(default_factory=list)
    fallback_plan: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanningResult:
    """规划结果"""
    plan: TaskPlan
    execution_order: List[str]  # 任务 ID 列表
    critical_path: List[str]  # 关键路径
    estimated_total_hours: float
    risks: List[str]  # 风险列表
    blocked_tasks: List[str]  # 被阻塞的任务


# ============================================================================
# TaskManager — 统一任务管理器（合并自 TaskPlanner + 轻量 TaskManager）
# ============================================================================
# 功能：
#   - 完整任务状态机（Pending/Blocked/InProgress/Completed/Failed/Cancelled）
#   - 依赖管理、优先级排序、风险评估
#   - create_plan / topological sort / critical path
#   - tasks.json 持久化（统一数据源）
#   - task_create / task_update / task_list CRUD
#   - get_active_tasks / get_completion_stats Prompt 导出


class TaskManager:
    """
    任务规划器

    智能管理任务规划：
    - 任务分解
    - 依赖管理
    - 优先级排序
    - 风险评估
    - 执行跟踪

    使用方式：
        planner = TaskPlanner()
        result = planner.create_plan(goal, tasks)
        planner.execute_plan(result.plan_id)
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化统一任务管理器。

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # ── 复杂任务存储（来自原 TaskPlanner）───────────────────────────────
        self._tasks: Dict[str, Task] = {}
        self._plans: Dict[str, TaskPlan] = {}
        self._current_plan_id: Optional[str] = None

        # ── 轻量任务存储（来自原 TaskManager）─────────────────────────────
        self._TASKS_FILE = "workspace/memory/tasks.json"
        self._light_tasks: List[Dict[str, Any]] = []   # 扁平 list，持久化到 tasks.json
        self._generation_goal: str = ""
        self._next_light_id: int = 1

        # ── 统计 ────────────────────────────────────────────────────────
        self._stats = {
            "plans_created": 0,
            "tasks_created": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }

        # 加载 tasks.json
        self._load_light_tasks()

    def _generate_id(self, prefix: str = "task") -> str:
        """生成唯一 ID"""
        import uuid
        return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

    # =========================================================================
    # 任务操作
    # =========================================================================

    def create_task(
        self,
        name: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        estimated_hours: float = 1.0,
        deadline: Optional[datetime] = None,
        dependencies: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建任务

        Args:
            name: 任务名称
            description: 任务描述
            priority: 优先级
            estimated_hours: 预估小时数
            deadline: 截止时间
            dependencies: 依赖任务 ID 列表
            tags: 标签
            metadata: 元数据

        Returns:
            任务 ID
        """
        task_id = self._generate_id()
        task = Task(
            task_id=task_id,
            name=name,
            description=description,
            priority=priority,
            estimated_hours=estimated_hours,
            deadline=deadline,
            dependencies=dependencies or [],
            tags=tags or [],
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        self._stats["tasks_created"] += 1
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        **kwargs
    ) -> bool:
        """更新任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        return True

    def start_task(self, task_id: str) -> bool:
        """开始任务"""
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.PENDING:
            return False

        # 检查依赖是否满足
        if not self._dependencies_satisfied(task_id):
            task.status = TaskStatus.BLOCKED
            return False

        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()
        return True

    def complete_task(
        self,
        task_id: str,
        result_summary: str = "",
    ) -> bool:
        """完成任务（允许从 PENDING 或 IN_PROGRESS 直接完成）"""
        task = self._tasks.get(task_id)
        if not task or task.status not in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
            return False

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result_summary = result_summary
        if not task.started_at:
            task.started_at = task.completed_at

        if task.started_at:
            task.actual_hours = (
                task.completed_at - task.started_at
            ).total_seconds() / 3600

        self._stats["tasks_completed"] += 1

        # 解锁依赖此任务的其他任务
        self._unblock_dependents(task_id)

        return True

    def fail_task(self, task_id: str, reason: str = "") -> bool:
        """标记任务失败"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.result_summary = reason
        self._stats["tasks_failed"] += 1
        return True

    def _dependencies_satisfied(self, task_id: str) -> bool:
        """检查依赖是否满足"""
        task = self._tasks.get(task_id)
        if not task:
            return True

        for dep_id in task.dependencies:
            dep_task = self._tasks.get(dep_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                return False
        return True

    def _unblock_dependents(self, task_id: str) -> None:
        """解锁依赖任务"""
        for task in self._tasks.values():
            if task_id in task.dependencies:
                if task.status == TaskStatus.BLOCKED:
                    task.status = TaskStatus.PENDING

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Task]:
        """列出任务"""
        result = list(self._tasks.values())

        if status:
            result = [t for t in result if t.status == status]

        if priority:
            result = [t for t in result if t.priority == priority]

        if tags:
            result = [
                t for t in result
                if any(tag in t.tags for tag in tags)
            ]

        return result

    # =========================================================================
    # 计划操作
    # =========================================================================

    def create_plan(
        self,
        goal: str,
        tasks: Optional[List[Dict[str, Any]]] = None,
        success_criteria: Optional[List[str]] = None,
        fallback_plan: str = "",
    ) -> PlanningResult:
        """
        创建计划

        Args:
            goal: 目标
            tasks: 任务列表
            success_criteria: 成功标准
            fallback_plan: 备选计划

        Returns:
            规划结果
        """
        plan_id = self._generate_id("plan")
        plan = TaskPlan(
            plan_id=plan_id,
            goal=goal,
            success_criteria=success_criteria or [],
            fallback_plan=fallback_plan,
        )

        # 添加任务
        if tasks:
            for task_data in tasks:
                task_id = self.create_task(
                    name=task_data.get("name", ""),
                    description=task_data.get("description", ""),
                    priority=task_data.get("priority", TaskPriority.MEDIUM),
                    estimated_hours=task_data.get("estimated_hours", 1.0),
                    deadline=task_data.get("deadline"),
                    dependencies=task_data.get("dependencies", []),
                    tags=task_data.get("tags", []),
                )
                task = self._tasks[task_id]
                task.parent_id = plan_id
                plan.tasks[task_id] = task

        self._plans[plan_id] = plan
        self._current_plan_id = plan_id
        self._stats["plans_created"] += 1

        # 计算执行顺序
        execution_order = self._calculate_execution_order(plan)
        critical_path = self._calculate_critical_path(plan, execution_order)
        estimated_hours = sum(t.estimated_hours for t in plan.tasks.values())
        risks = self._assess_risks(plan)
        blocked = self._find_blocked_tasks(plan)

        return PlanningResult(
            plan=plan,
            execution_order=execution_order,
            critical_path=critical_path,
            estimated_total_hours=estimated_hours,
            risks=risks,
            blocked_tasks=blocked,
        )

    def _calculate_execution_order(self, plan: TaskPlan) -> List[str]:
        """计算执行顺序（拓扑排序）"""
        # Kahn's algorithm
        in_degree = defaultdict(int)
        task_ids = set(plan.tasks.keys())

        # 初始化入度
        for task_id in task_ids:
            for dep in plan.tasks[task_id].dependencies:
                if dep in task_ids:
                    in_degree[task_id] += 1

        # 从没有依赖的任务开始
        queue = [tid for tid in task_ids if in_degree[tid] == 0]
        result = []

        while queue:
            # 按优先级排序
            queue.sort(
                key=lambda tid: plan.tasks[tid].priority.value,
                reverse=True
            )
            task_id = queue.pop(0)
            result.append(task_id)

            # 更新依赖此任务的其他任务的入度
            for other_id in task_ids:
                if task_id in plan.tasks[other_id].dependencies:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        # 如果有循环依赖，返回原始顺序
        if len(result) < len(task_ids):
            return list(task_ids)

        return result

    def _calculate_critical_path(
        self,
        plan: TaskPlan,
        execution_order: List[str],
    ) -> List[str]:
        """计算关键路径"""
        # 简化的关键路径计算
        critical = []
        max_hours = 0.0

        for task_id in execution_order:
            task = plan.tasks[task_id]
            if task.estimated_hours >= max_hours:
                critical.append(task_id)
                max_hours = task.estimated_hours

        return critical

    def _assess_risks(self, plan: TaskPlan) -> List[str]:
        """评估风险"""
        risks = []

        for task in plan.tasks.values():
            # 高风险任务
            if task.risk == RiskLevel.HIGH or task.risk == RiskLevel.CRITICAL:
                risks.append(f"{task.name}: {task.risk.value} risk")

            # 截止时间接近
            if task.deadline:
                time_left = (task.deadline - datetime.now()).total_seconds() / 3600
                if time_left < task.estimated_hours:
                    risks.append(f"{task.name}: deadline may be missed")

            # 依赖过多
            if len(task.dependencies) > 3:
                risks.append(f"{task.name}: too many dependencies ({len(task.dependencies)})")

        return risks

    def _find_blocked_tasks(self, plan: TaskPlan) -> List[str]:
        """找出被阻塞的任务"""
        blocked = []

        for task in plan.tasks.values():
            if not self._dependencies_satisfied(task.task_id):
                blocked.append(task.task_id)

        return blocked

    def get_plan(self, plan_id: str) -> Optional[TaskPlan]:
        """获取计划"""
        return self._plans.get(plan_id)

    def get_current_plan(self) -> Optional[TaskPlan]:
        """获取当前计划"""
        if self._current_plan_id:
            return self._plans.get(self._current_plan_id)
        return None

    def get_plan_progress(self, plan_id: str) -> Dict[str, Any]:
        """获取计划进度"""
        plan = self._plans.get(plan_id)
        if not plan:
            return {}

        total = len(plan.tasks)
        completed = sum(
            1 for t in plan.tasks.values()
            if t.status == TaskStatus.COMPLETED
        )
        in_progress = sum(
            1 for t in plan.tasks.values()
            if t.status == TaskStatus.IN_PROGRESS
        )
        blocked = sum(
            1 for t in plan.tasks.values()
            if t.status == TaskStatus.BLOCKED
        )

        total_hours = sum(t.estimated_hours for t in plan.tasks.values())
        completed_hours = sum(
            t.actual_hours for t in plan.tasks.values()
            if t.status == TaskStatus.COMPLETED
        )

        return {
            "plan_id": plan_id,
            "goal": plan.goal,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "blocked_tasks": blocked,
            "progress_percent": (completed / total * 100) if total > 0 else 0,
            "total_hours": total_hours,
            "completed_hours": completed_hours,
            "time_estimate_percent": (
                completed_hours / total_hours * 100
            ) if total_hours > 0 else 0,
        }

    # =========================================================================
    # 统计分析
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        status_counts = defaultdict(int)
        priority_counts = defaultdict(int)

        for task in self._tasks.values():
            status_counts[task.status.value] += 1
            priority_counts[task.priority.name] += 1

        return {
            **self._stats,
            "total_tasks": len(self._tasks),
            "total_plans": len(self._plans),
            "current_plan_id": self._current_plan_id,
            "tasks_by_status": dict(status_counts),
            "tasks_by_priority": dict(priority_counts),
        }

    # =========================================================================
    # 持久化
    # =========================================================================

    def save_current_plan(self, plan_dir: Path) -> None:
        """
        将当前计划保存到 JSON 文件。

        Args:
            plan_dir: 计划文件存储目录（如 workspace/memory/plans/）
        """
        plan_dir.mkdir(parents=True, exist_ok=True)
        if not self._current_plan_id:
            return

        plan = self._plans.get(self._current_plan_id)
        if not plan:
            return

        tasks_data = {}
        for tid, task in plan.tasks.items():
            tasks_data[tid] = {
                "task_id": tid,
                "name": task.name,
                "description": task.description,
                "status": task.status.value,
                "priority": task.priority.value,
                "estimated_hours": task.estimated_hours,
                "actual_hours": task.actual_hours,
                "created_at": task.created_at.isoformat() if task.created_at else "",
                "started_at": task.started_at.isoformat() if task.started_at else "",
                "completed_at": task.completed_at.isoformat() if task.completed_at else "",
                "result_summary": task.result_summary,
            }

        data = {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "created_at": plan.created_at.isoformat() if plan.created_at else "",
            "completed_at": plan.completed_at.isoformat() if plan.completed_at else "",
            "tasks": tasks_data,
            "stats": self._stats,
        }

        out_file = plan_dir / f"{plan.plan_id}.json"
        import json
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_latest_plan(self, plan_dir: Path) -> bool:
        """
        从 plan_dir 加载最新的计划文件。

        Returns:
            是否成功加载
        """
        if not plan_dir.exists():
            return False

        files = sorted(plan_dir.glob("plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return False

        import json
        try:
            with open(files[0], 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._tasks.clear()
            self._plans.clear()
            self._current_plan_id = None

            plan_id = data["plan_id"]
            plan = TaskPlan(
                plan_id=plan_id,
                goal=data.get("goal", ""),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            )
            self._plans[plan_id] = plan

            for tid, tdata in data.get("tasks", {}).items():
                task = Task(
                    task_id=tid,
                    name=tdata["name"],
                    description=tdata.get("description", ""),
                    status=TaskStatus(tdata.get("status", "pending")),
                    priority=TaskPriority(tdata.get("priority", 3)),
                    estimated_hours=tdata.get("estimated_hours", 1.0),
                    actual_hours=tdata.get("actual_hours", 0.0),
                    created_at=datetime.fromisoformat(tdata["created_at"]) if tdata.get("created_at") else datetime.now(),
                    started_at=datetime.fromisoformat(tdata["started_at"]) if tdata.get("started_at") else None,
                    completed_at=datetime.fromisoformat(tdata["completed_at"]) if tdata.get("completed_at") else None,
                    result_summary=tdata.get("result_summary", ""),
                )
                self._tasks[tid] = task
                plan.tasks[tid] = task

            self._current_plan_id = plan_id
            self._stats = data.get("stats", self._stats.copy())
            return True
        except Exception:
            return False

    # =========================================================================
    # tasks.json 持久化（来自原 TaskManager）
    # =========================================================================

    def _resolve_project_root(self) -> Path:
        import sys
        for name, mod in list(sys.modules.items()):
            if name == "agent" and mod and getattr(mod, "__file__", None):
                return Path(mod.__file__).parent.resolve()
        for sp in sys.path:
            p = os.path.join(sp, "agent.py")
            if os.path.exists(p):
                return Path(sp).resolve()
        return Path(__file__).parent.parent.parent.resolve()

    def _load_light_tasks(self):
        fpath = self.project_root / self._TASKS_FILE if self.project_root else None
        if fpath and fpath.exists():
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._generation_goal = data.get("generation_goal", "")
                raw = data.get("subtasks", [])
                self._light_tasks = list(raw) if raw else []
                self._next_light_id = max([t["id"] for t in self._light_tasks], default=0) + 1
            except (json.JSONDecodeError, IOError):
                self._light_tasks = []
                self._next_light_id = 1
        else:
            self._light_tasks = []
            self._next_light_id = 1

    def _save_light_tasks(self):
        fpath = self.project_root / self._TASKS_FILE
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({
                "generation_goal": self._generation_goal,
                "subtasks": self._light_tasks,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def task_create(self, tasks: List[Dict[str, Any]], generation_goal: str = "") -> str:
        """创建任务清单（清空旧清单），返回摘要。"""
        self._generation_goal = generation_goal
        self._light_tasks = []
        self._next_light_id = 1
        for t in tasks:
            st: Dict[str, Any] = {
                "id": self._next_light_id,
                "description": t["description"],
                "is_completed": False,
                "result_summary": "",
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
            }
            self._light_tasks.append(st)
            self._next_light_id += 1
        self._save_light_tasks()
        return f"已创建 {len(tasks)} 个任务，当前共 {len(self._light_tasks)} 个子任务。"

    def task_update(self, task_id: int, is_completed: bool = None, result_summary: str = None, description: str = None) -> str:
        """更新任务状态/摘要/描述。"""
        for t in self._light_tasks:
            if t["id"] == task_id:
                if is_completed is not None:
                    t["is_completed"] = is_completed
                    if is_completed:
                        t["completed_at"] = datetime.now().isoformat()
                if result_summary is not None:
                    t["result_summary"] = result_summary
                if description is not None:
                    t["description"] = description
                self._save_light_tasks()
                return f"任务 {task_id} 已更新: completed={t['is_completed']}"
        return f"任务 {task_id} 未找到。"

    def task_list(self) -> List[Dict[str, Any]]:
        """返回所有任务的扁平列表。"""
        return list(self._light_tasks)

    def get_active_tasks(self) -> str:
        """渲染 Prompt 友好的 Markdown 进度表。"""
        if not self._light_tasks:
            return ""
        lines = ["\n\n---\n\n## 当前任务进度\n"]
        if self._generation_goal:
            lines.append(f"**目标**: {self._generation_goal}\n")
        lines.append("| # | 描述 | 状态 | 结果摘要 |\n")
        lines.append("|---|------|------|----------|\n")
        for t in self._light_tasks:
            status = "✅ 完成" if t.get("is_completed") else "⏳ 进行中"
            summary = t.get("result_summary") or "—"
            lines.append(f"| {t['id']} | {t['description']} | {status} | {summary} |\n")
        pending = [t for t in self._light_tasks if not t.get("is_completed")]
        if pending:
            lines.append(f"\n**未完成任务 {len(pending)} 个**，请继续执行下一个待办事项。\n")
        return "".join(lines)

    def get_completion_stats(self) -> Dict[str, int]:
        total = len(self._light_tasks)
        completed = sum(1 for t in self._light_tasks if t.get("is_completed"))
        return {"total": total, "completed": completed, "pending": total - completed}

    def task_breakdown(self, task_id: int) -> List[Dict[str, Any]]:
        """将指定任务拆分为子步骤。"""
        task = next((t for t in self._light_tasks if t["id"] == task_id), None)
        if not task:
            return []
        description = task.get("description", "")
        import re as _re
        steps = [s.strip() for s in _re.split(r"[。\n；;,、]", description) if s.strip()]
        if len(steps) <= 1:
            steps = [description] if description else []
        return [{"step": i + 1, "description": s} for i, s in enumerate(steps)]

    def task_prioritize(self, task_ids: List[int]) -> List[int]:
        """对指定任务 ID 列表按优先级排序（过滤无效 ID）。"""
        valid_ids = {t["id"] for t in self._light_tasks}
        return [tid for tid in task_ids if tid in valid_ids]

    def get_current_checklist_markdown(self) -> str:
        """将当前计划渲染为 Markdown 清单（PlanOrchestrator / PromptManager 专用）。"""
        plan = self.get_current_plan()
        if not plan:
            return ""

        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("## 当前任务清单")
        lines.append("")
        lines.append(f"**目标**: {plan.goal}")
        lines.append("")

        if not plan.tasks:
            lines.append("*（暂无任务）*")
            lines.append("")
            return "\n".join(lines)

        completed = 0
        total = len(plan.tasks)
        for task in plan.tasks.values():
            if task.status == TaskStatus.COMPLETED:
                completed += 1
                icon = "[√]"
                status_label = "**已完成**"
            elif task.status == TaskStatus.IN_PROGRESS:
                icon = "[→]"
                status_label = "进行中"
            elif task.status == TaskStatus.BLOCKED:
                icon = "[⊘]"
                status_label = "阻塞"
            else:
                icon = "[ ]"
                status_label = ""

            task_num = list(plan.tasks.keys()).index(task.task_id) + 1
            if status_label:
                lines.append(f"{icon} **{task_num}.** {task.description} — {status_label}")
            else:
                lines.append(f"{icon} **{task_num}.** {task.description}")

        lines.append("")
        lines.append(f"**进度**: {completed}/{total} ({completed*100//total if total else 0}%)")
        lines.append("=" * 60)
        lines.append("")
        return "\n".join(lines)


# ============================================================================
# 向后兼容别名（在函数定义之后赋值，避免 NameError）
# ============================================================================


# ============================================================================
# 全局单例（统一 TaskManager）
# ============================================================================

_task_manager_instance: Optional[TaskManager] = None
_task_manager_root: Optional[Path] = None


def get_task_manager(project_root: Optional[str] = None) -> TaskManager:
    """获取统一 TaskManager 单例，支持 project_root 校验。"""
    global _task_manager_instance, _task_manager_root
    if _task_manager_instance is None:
        if project_root:
            root = Path(project_root).resolve()
        else:
            root = _resolve_root()
        _task_manager_root = root
        _task_manager_instance = TaskManager(root)
    elif project_root is not None:
        incoming = Path(project_root).resolve()
        if incoming != _task_manager_root:
            import warnings
            warnings.warn(
                f"TaskManager 已在 {_task_manager_root} 初始化，忽略传入路径 {incoming}"
            )
    return _task_manager_instance


def _resolve_root() -> Path:
    """解析项目根目录（供单例初始化用）。"""
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, "__file__", None):
            return Path(mod.__file__).parent.resolve()
    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()
    return Path(__file__).parent.parent.parent.resolve()


def reset_task_manager() -> None:
    """重置 TaskManager 单例"""
    global _task_manager_instance, _task_manager_root
    _task_manager_instance = None
    _task_manager_root = None


# ============================================================================
# 向后兼容别名（必须放在函数定义之后）
# ============================================================================
TaskPlanner = TaskManager           # 旧类名 → 新类名
get_task_planner = get_task_manager  # 旧函数名 → 新函数名
reset_task_planner = reset_task_manager
