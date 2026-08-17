#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task manager backed by a single tasks.json task list."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Optional

from core.prompt_manager.task_analyzer import TaskStatus


_TASK_STORAGE_OVERRIDE: ContextVar[str] = ContextVar("vibelution_task_storage_override", default="")


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _mapping_items(value: Any) -> List[Dict[str, Any]]:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("tasks")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("entries")
        if nested is None:
            nested = value.get("subtasks")
        if nested is not None:
            return _mapping_items(nested)
        if any(key in value for key in ("description", "name", "status", "is_completed", "isCompleted", "id")):
            return [dict(value)]
        return [dict(item) for item in value.values() if isinstance(item, Mapping)]
    try:
        iterator = list(value)
    except TypeError:
        return []
    items: List[Dict[str, Any]] = []
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            items.append(dict(item))
    return items


def _coerce_str_list(value: Any) -> List[str]:
    value = _maybe_json(value)
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).decode("utf-8", errors="replace").strip()
        return [text] if text else []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        nested = value.get("items")
        if nested is None:
            nested = value.get("names")
        if nested is None:
            nested = value.get("tags")
        if nested is not None:
            return _coerce_str_list(nested)
        names: List[str] = []
        for key, item in value.items():
            if isinstance(item, Mapping) and not _coerce_bool(
                item.get("enabled", item.get("enable")), True
            ):
                continue
            text = _coerce_text(key).strip()
            if text and text not in names:
                names.append(text)
        return names
    try:
        iterator = list(value)
    except TypeError:
        text = _coerce_text(value).strip()
        return [text] if text else []
    names = []
    for item in iterator:
        text = _coerce_text(item).strip()
        if text and text not in names:
            names.append(text)
    return names


def _safe_int(value: Any, default: int | None = 0) -> int | None:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _coerce_int_list(value: Any) -> List[int]:
    value = _maybe_json(value)
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        parsed = _safe_int(_coerce_text(value).strip(), None)
        return [parsed] if parsed is not None else []
    if isinstance(value, Mapping):
        nested = value.get("ids")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("taskIds")
        if nested is None:
            nested = value.get("task_ids")
        if nested is not None:
            return _coerce_int_list(nested)
        value = list(value)
    try:
        iterator = list(value)
    except TypeError:
        parsed = _safe_int(value, None)
        return [parsed] if parsed is not None else []
    ids: List[int] = []
    for item in iterator:
        parsed = _safe_int(item, None)
        if parsed is not None and parsed not in ids:
            ids.append(parsed)
    return ids


def _coerce_substeps(value: Any) -> List[Dict[str, Any]]:
    value = _maybe_json(value)
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        text = _coerce_text(value).strip()
        return [{"description": text}] if text else []
    if isinstance(value, Mapping):
        nested = value.get("items")
        if nested is None:
            nested = value.get("steps")
        if nested is None:
            nested = value.get("substeps")
        if nested is not None:
            return _coerce_substeps(nested)
        return [dict(value)] if value else []
    try:
        iterator = list(value)
    except TypeError:
        return []
    steps: List[Dict[str, Any]] = []
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            steps.append(dict(item))
            continue
        text = _coerce_text(item).strip()
        if text:
            steps.append({"description": text})
    return steps


@contextmanager
def task_storage_override(workspace_root: str | Path):
    token = _TASK_STORAGE_OVERRIDE.set(str(Path(workspace_root).resolve()))
    try:
        yield
    finally:
        _TASK_STORAGE_OVERRIDE.reset(token)


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


def _tasks_json_path() -> str:
    """返回任务清单持久化路径。测试会 monkeypatch 这个函数。"""
    workspace_override = _TASK_STORAGE_OVERRIDE.get("").strip()
    if workspace_override:
        return str(Path(workspace_override) / "memory" / "tasks.json")
    from core.infrastructure import developer_sandbox

    return str(developer_sandbox.formal_workspace_path(_resolve_root(), "memory", "tasks.json"))


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
    """Task view derived from the task list."""

    task_id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    estimated_hours: float = 1.0
    actual_hours: float = 0.0
    deadline: Optional[datetime] = None
    dependencies: List[str] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    risk: RiskLevel = RiskLevel.LOW
    assignee: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_summary: str = ""

    @property
    def id(self) -> str:
        return self.task_id

    @id.setter
    def id(self, value: str) -> None:
        self.task_id = str(value)


@dataclass
class PlanTask:
    """Plan task projection, built from the same task list."""

    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result_summary: str = ""
    substeps: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Plan:
    """Current task-list projection for callers that need grouped tasks."""

    goal: str = ""
    tasks: Dict[str, PlanTask] = field(default_factory=dict)
    created_at: str = ""


class TaskManager:
    """Manage tasks using one in-memory list and one persisted tasks.json file."""

    _instance: ClassVar[Optional["TaskManager"]] = None

    def __init__(self, project_root: Optional[str] = None):
        explicit_project_root = project_root is not None
        self._TASKS_FILE = "workspace/memory/tasks.json"
        if explicit_project_root:
            self.project_root = Path(project_root)
            self._tasks_path = self.project_root / self._TASKS_FILE
        else:
            self._tasks_path = Path(_tasks_json_path())
            self.project_root = self._tasks_path.parent.parent

        self._light_tasks: List[Dict[str, Any]] = []
        self._goal: str = ""
        self._next_light_id: int = 1
        self._created_at: str = ""
        self._stats = {
            "tasks_created": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }

        if not explicit_project_root:
            self._load_tasks()

    def _load_tasks(self) -> None:
        fpath = self._tasks_path
        if not fpath or not fpath.exists():
            return
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._goal = _coerce_text(
                _mapping_get(_as_mapping(data), "goal", "generation_goal")
            )
            self._created_at = _coerce_text(_mapping_get(_as_mapping(data), "created_at", "createdAt"))
            raw = _mapping_get(_as_mapping(data), "tasks", "subtasks") or []
            self._light_tasks = [self._normalize_light_task(task) for task in _mapping_items(raw)]
            self._next_light_id = max([t["id"] for t in self._light_tasks], default=0) + 1
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            self._light_tasks = []
            self._goal = ""
            self._created_at = ""
            self._next_light_id = 1

    def _save_tasks(self) -> None:
        fpath = self._tasks_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat()
        if not self._created_at:
            self._created_at = now
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "goal": self._goal,
                    "tasks": self._light_tasks,
                    "created_at": self._created_at,
                    "updated_at": now,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def _normalize_light_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        data = _as_mapping(task)
        task_id = _safe_int(_mapping_get(data, "id"), self._next_light_id)
        if task_id is None:
            task_id = self._next_light_id
        is_completed = _coerce_bool(_mapping_get(data, "is_completed", "isCompleted"), False)
        status = _mapping_get(data, "status") or ("completed" if is_completed else "pending")
        description = _coerce_text(
            _mapping_get(data, "description", "name") or ""
        )
        created_at = _mapping_get(data, "created_at", "createdAt") or datetime.now().isoformat()
        return {
            "id": task_id,
            "name": _coerce_text(_mapping_get(data, "name") or description),
            "description": description,
            "status": status,
            "is_completed": str(status) == TaskStatus.COMPLETED.value or is_completed,
            "result_summary": _coerce_text(_mapping_get(data, "result_summary", "resultSummary")),
            "substeps": _coerce_substeps(_mapping_get(data, "substeps")),
            "created_at": created_at,
            "started_at": _mapping_get(data, "started_at", "startedAt"),
            "completed_at": _mapping_get(data, "completed_at", "completedAt"),
            "priority": _mapping_get(data, "priority") or TaskPriority.MEDIUM.value,
            "estimated_hours": _safe_float(_mapping_get(data, "estimated_hours", "estimatedHours"), 1.0),
            "actual_hours": _safe_float(_mapping_get(data, "actual_hours", "actualHours"), 0.0),
            "dependencies": _coerce_str_list(_mapping_get(data, "dependencies")),
            "tags": _coerce_str_list(_mapping_get(data, "tags")),
            "metadata": _as_mapping(_mapping_get(data, "metadata")),
        }

    def _find_light_task(self, task_id: str | int) -> Optional[Dict[str, Any]]:
        tid = _safe_int(task_id, None)
        if tid is None:
            return None
        return next((task for task in self._light_tasks if task["id"] == tid), None)

    def _parse_datetime(self, raw: Any) -> Optional[datetime]:
        if not raw:
            return None
        if isinstance(raw, datetime):
            return raw
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None

    def _priority_from_raw(self, raw: Any) -> TaskPriority:
        if isinstance(raw, TaskPriority):
            return raw
        if isinstance(raw, bool) or raw is None:
            return TaskPriority.MEDIUM
        if isinstance(raw, (bytes, bytearray, memoryview)):
            raw = bytes(raw).decode("utf-8", errors="replace")
        try:
            return TaskPriority(int(raw))
        except (TypeError, ValueError):
            try:
                return TaskPriority[_coerce_text(raw).upper()]
            except (KeyError, TypeError):
                return TaskPriority.MEDIUM

    def _status_from_raw(self, raw: Any, is_completed: bool = False) -> TaskStatus:
        if isinstance(raw, TaskStatus):
            return raw
        if _coerce_bool(is_completed, False):
            return TaskStatus.COMPLETED
        try:
            return TaskStatus(_coerce_text(raw))
        except ValueError:
            return TaskStatus.PENDING

    def _task_from_light(self, light: Dict[str, Any]) -> Task:
        status = self._status_from_raw(light.get("status"), _coerce_bool(light.get("is_completed"), False))
        return Task(
            task_id=str(light["id"]),
            name=light.get("name") or light.get("description", ""),
            description=light.get("description", ""),
            status=status,
            priority=self._priority_from_raw(light.get("priority")),
            estimated_hours=_safe_float(light.get("estimated_hours"), 1.0),
            actual_hours=_safe_float(light.get("actual_hours"), 0.0),
            dependencies=_coerce_str_list(light.get("dependencies")),
            tags=_coerce_str_list(light.get("tags")),
            metadata={**_as_mapping(light.get("metadata")), "substeps": _coerce_substeps(light.get("substeps"))},
            created_at=self._parse_datetime(light.get("created_at")) or datetime.now(),
            started_at=self._parse_datetime(light.get("started_at")),
            completed_at=self._parse_datetime(light.get("completed_at")),
            result_summary=light.get("result_summary", ""),
        )

    def _apply_task_to_light(self, task: Task) -> Dict[str, Any]:
        light = self._find_light_task(task.task_id)
        if light is None:
            parsed_id = _safe_int(task.task_id, self._next_light_id)
            light = {"id": parsed_id if parsed_id is not None else self._next_light_id}
            self._light_tasks.append(light)
        metadata = _as_mapping(task.metadata)
        light.update(
            {
                "name": task.name,
                "description": task.description,
                "status": task.status.value,
                "is_completed": task.status == TaskStatus.COMPLETED,
                "result_summary": task.result_summary,
                "substeps": _coerce_substeps(metadata.get("substeps", light.get("substeps", []))),
                "created_at": task.created_at.isoformat() if task.created_at else datetime.now().isoformat(),
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "priority": task.priority.value,
                "estimated_hours": task.estimated_hours,
                "actual_hours": task.actual_hours,
                "dependencies": _coerce_str_list(task.dependencies),
                "tags": _coerce_str_list(task.tags),
                "metadata": metadata,
            }
        )
        next_id = _safe_int(task.task_id, None)
        if next_id is not None:
            self._next_light_id = max(self._next_light_id, next_id + 1)
        return light

    def _all_tasks(self) -> List[Task]:
        return [self._task_from_light(task) for task in self._light_tasks]

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
        task_id = str(self._next_light_id)
        task = Task(
            task_id=task_id,
            name=name,
            description=description,
            priority=priority,
            estimated_hours=estimated_hours,
            deadline=deadline,
            dependencies=_coerce_str_list(dependencies),
            tags=_coerce_str_list(tags),
            metadata=_as_mapping(metadata),
        )
        self._apply_task_to_light(task)
        self._stats["tasks_created"] += 1
        self._save_tasks()
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        light = self._find_light_task(task_id)
        return self._task_from_light(light) if light else None

    def update_task(self, task_id: str, **kwargs) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        for key, value in kwargs.items():
            if value is not None and hasattr(task, key):
                setattr(task, key, value)
        self._apply_task_to_light(task)
        self._save_tasks()
        return True

    def start_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task or task.status != TaskStatus.PENDING:
            return False
        if not self._dependencies_satisfied(task_id):
            task.status = TaskStatus.BLOCKED
            self._apply_task_to_light(task)
            self._save_tasks()
            return False
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()
        self._apply_task_to_light(task)
        self._save_tasks()
        return True

    def complete_task(self, task_id: str, result_summary: str = "") -> bool:
        task = self.get_task(task_id)
        if not task or task.status not in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
            return False
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.started_at = task.started_at or task.completed_at
        task.result_summary = _coerce_text(result_summary)
        task.actual_hours = (task.completed_at - task.started_at).total_seconds() / 3600
        self._stats["tasks_completed"] += 1
        self._apply_task_to_light(task)
        self._unblock_dependents(task_id)
        self._save_tasks()
        return True

    def fail_task(self, task_id: str, reason: str = "") -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.result_summary = _coerce_text(reason)
        self._stats["tasks_failed"] += 1
        self._apply_task_to_light(task)
        self._save_tasks()
        return True

    def _dependencies_satisfied(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return True
        for dep_id in task.dependencies:
            dep_task = self.get_task(dep_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                return False
        return True

    def _unblock_dependents(self, task_id: str) -> None:
        for task in self._all_tasks():
            if str(task_id) in task.dependencies and task.status == TaskStatus.BLOCKED:
                task.status = TaskStatus.PENDING
                self._apply_task_to_light(task)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Task]:
        result = self._all_tasks()
        if status:
            result = [task for task in result if task.status == status]
        if priority:
            result = [task for task in result if task.priority == priority]
        if tags:
            wanted = set(_coerce_str_list(tags))
            result = [task for task in result if wanted.intersection(task.tags)]
        return result

    def get_current_plan(self) -> Optional[Plan]:
        if not self._light_tasks and not self._goal:
            return None
        return Plan(
            goal=self._goal,
            created_at=self._created_at,
            tasks={
                str(task["id"]): PlanTask(
                    id=str(task["id"]),
                    name=task.get("name") or task.get("description", ""),
                    description=task.get("description", ""),
                    status=self._status_from_raw(task.get("status"), _coerce_bool(task.get("is_completed"), False)),
                    result_summary=task.get("result_summary", ""),
                    substeps=_coerce_substeps(task.get("substeps")),
                )
                for task in self._light_tasks
            },
        )

    def get_plan_progress(self, plan_id: str = "current") -> Dict[str, Any]:
        tasks = self._all_tasks()
        total = len(tasks)
        completed = sum(1 for task in tasks if task.status == TaskStatus.COMPLETED)
        in_progress = sum(1 for task in tasks if task.status == TaskStatus.IN_PROGRESS)
        blocked = sum(1 for task in tasks if task.status == TaskStatus.BLOCKED)
        total_hours = sum(task.estimated_hours for task in tasks)
        completed_hours = sum(task.actual_hours for task in tasks if task.status == TaskStatus.COMPLETED)
        return {
            "plan_id": "current",
            "goal": self._goal,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "blocked_tasks": blocked,
            "progress_percent": (completed / total * 100) if total else 0,
            "total_hours": total_hours,
            "completed_hours": completed_hours,
            "time_estimate_percent": (completed_hours / total_hours * 100) if total_hours else 0,
        }

    def get_statistics(self) -> Dict[str, Any]:
        status_counts = defaultdict(int)
        priority_counts = defaultdict(int)
        tasks = self._all_tasks()
        for task in tasks:
            status_counts[task.status.value] += 1
            priority_counts[task.priority.name] += 1
        return {
            **self._stats,
            "total_tasks": len(tasks),
            "tasks_by_status": dict(status_counts),
            "tasks_by_priority": dict(priority_counts),
        }

    def task_create(self, tasks: List[Dict[str, Any]], goal: str = "") -> str:
        """创建任务清单（清空旧清单），返回摘要。"""
        self._goal = _coerce_text(goal)
        self._light_tasks = []
        self._next_light_id = 1
        self._created_at = datetime.now().isoformat()
        for task in _mapping_items(tasks):
            description = _coerce_text(_mapping_get(task, "description", "name")).strip()
            estimated_hours = _mapping_get(task, "estimated_hours", "estimatedHours")
            light = self._normalize_light_task(
                {
                    "id": self._next_light_id,
                    "description": description,
                    "name": _coerce_text(_mapping_get(task, "name") or description),
                    "substeps": _mapping_get(task, "substeps") or [],
                    "priority": _mapping_get(task, "priority") or TaskPriority.MEDIUM.value,
                    "estimated_hours": 1.0 if estimated_hours is None else estimated_hours,
                    "dependencies": _mapping_get(task, "dependencies") or [],
                    "tags": _mapping_get(task, "tags") or [],
                    "metadata": _mapping_get(task, "metadata") or {},
                    "is_completed": _mapping_get(task, "is_completed", "isCompleted"),
                    "result_summary": _mapping_get(task, "result_summary", "resultSummary"),
                    "created_at": datetime.now().isoformat(),
                }
            )
            self._light_tasks.append(light)
            self._next_light_id += 1
        self._stats["tasks_created"] += len(self._light_tasks)
        self._save_tasks()
        created = len(self._light_tasks)
        return f"已创建 {created} 个任务，当前共 {created} 个子任务。"

    def task_update(
        self,
        task_id: int,
        is_completed: bool = None,
        result_summary: str = None,
        description: str = None,
    ) -> str:
        """更新任务状态/摘要/描述。"""
        task = self._find_light_task(task_id)
        if not task:
            return f"任务 {task_id} 不存在。"
        if is_completed is not None:
            completed = _coerce_bool(is_completed, False)
            task["is_completed"] = completed
            task["status"] = TaskStatus.COMPLETED.value if completed else TaskStatus.PENDING.value
            task["completed_at"] = datetime.now().isoformat() if completed else None
        if result_summary is not None:
            task["result_summary"] = _coerce_text(result_summary)
        if description is not None:
            text = _coerce_text(description)
            task["description"] = text
            task["name"] = text
        self._save_tasks()
        status_label = "完成" if task["is_completed"] else "未完成"
        return f"任务 {task_id} 已更新: {status_label}"

    def task_list(self) -> List[Dict[str, Any]]:
        """返回所有任务的扁平列表。"""
        return [dict(task) for task in self._light_tasks]

    def get_active_tasks(self) -> str:
        """渲染 Prompt 友好的 Markdown 进度表。"""
        if not self._light_tasks:
            return ""
        lines = ["\n\n---\n\n## 当前任务进度\n"]
        if self._goal:
            lines.append(f"**目标**: {self._goal}\n")
        lines.append("| # | 描述 | 状态 | 结果摘要 |\n")
        lines.append("|---|------|------|----------|\n")
        for task in self._light_tasks:
            status = "✅ 完成" if _coerce_bool(task.get("is_completed"), False) else "⏳ 进行中"
            summary = task.get("result_summary") or "—"
            lines.append(f"| {task['id']} | {task['description']} | {status} | {summary} |\n")
        pending = [task for task in self._light_tasks if not _coerce_bool(task.get("is_completed"), False)]
        if pending:
            lines.append(f"\n**未完成任务 {len(pending)} 个**，请继续执行下一个待办事项。\n")
        return "".join(lines)

    def get_completion_stats(self) -> Dict[str, int]:
        total = len(self._light_tasks)
        completed = sum(1 for task in self._light_tasks if _coerce_bool(task.get("is_completed"), False))
        return {"total": total, "completed": completed, "pending": total - completed}

    def task_breakdown(self, task_id: int) -> Optional[List[Dict[str, Any]]]:
        """将指定任务拆分为子步骤。"""
        task = self._find_light_task(task_id)
        if not task:
            return None
        if task.get("substeps"):
            return task["substeps"]
        description = task.get("description", "")
        lowered = description.lower()
        analysis_keywords = ("分析", "检查", "定位", "review", "inspect", "analyze")
        implementation_keywords = ("实现", "修复", "添加", "新增", "改造", "fix", "implement", "add")
        if any(keyword in lowered or keyword in description for keyword in analysis_keywords):
            descriptions = ["通读相关代码和上下文", "定位关键路径与风险点", "制定最小修复方案", "验证行为并记录结论"]
        elif any(keyword in lowered or keyword in description for keyword in implementation_keywords):
            descriptions = ["梳理需求和影响范围", "编写核心实现", "补充或调整测试", "运行验证并整理结果"]
        else:
            descriptions = ["分析需求和当前状态", "设计执行步骤", "完成主要变更", "验证结果并汇报"]
        task["substeps"] = [
            {"id": index + 1, "step": index + 1, "description": step_description, "is_completed": False}
            for index, step_description in enumerate(descriptions)
        ]
        self._save_tasks()
        return task["substeps"]

    def task_prioritize(self, task_ids: List[int]) -> Optional[List[int]]:
        """对指定任务 ID 列表按优先级排序（过滤无效 ID）。"""
        valid_ids = {task["id"] for task in self._light_tasks}
        ordered_ids = [tid for tid in _coerce_int_list(task_ids) if tid in valid_ids]
        if not ordered_ids:
            return None
        by_id = {task["id"]: task for task in self._light_tasks}
        remaining = [task for task in self._light_tasks if task["id"] not in ordered_ids]
        self._light_tasks = [by_id[tid] for tid in ordered_ids] + remaining
        self._save_tasks()
        return ordered_ids

    def get_current_checklist_markdown(self) -> str:
        """将当前任务清单渲染为 Markdown 清单。"""
        plan = self.get_current_plan()
        if not plan:
            return ""
        lines = ["", "=" * 60, "## 当前任务清单", "", f"**目标**: {plan.goal}", ""]
        if not plan.tasks:
            lines.extend(["*（暂无任务）*", ""])
            return "\n".join(lines)
        completed = 0
        total = len(plan.tasks)
        for index, task in enumerate(plan.tasks.values(), start=1):
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
            suffix = f" — {status_label}" if status_label else ""
            lines.append(f"{icon} **{index}.** {task.description}{suffix}")
        lines.extend(["", f"**进度**: {completed}/{total} ({completed * 100 // total if total else 0}%)", "=" * 60, ""])
        return "\n".join(lines)


_task_manager_instance: Optional[TaskManager] = None
_task_manager_root: Optional[Path] = None


def get_task_manager(project_root: Optional[str] = None) -> TaskManager:
    """获取统一 TaskManager 单例，支持 project_root 校验。"""
    global _task_manager_instance, _task_manager_root
    workspace_override = _TASK_STORAGE_OVERRIDE.get("").strip()
    if workspace_override and project_root is None:
        manager = TaskManager.__new__(TaskManager)
        manager._TASKS_FILE = "memory/tasks.json"
        manager.project_root = Path(workspace_override).resolve()
        manager._tasks_path = manager.project_root / "memory" / "tasks.json"
        manager._light_tasks = []
        manager._goal = ""
        manager._next_light_id = 1
        manager._created_at = ""
        manager._stats = {
            "tasks_created": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }
        manager._load_tasks()
        return manager
    if TaskManager._instance is not None and _task_manager_instance is None:
        _task_manager_instance = TaskManager._instance

    if _task_manager_instance is None:
        root = Path(project_root).resolve() if project_root else _resolve_root()
        _task_manager_root = root
        _task_manager_instance = TaskManager(root)
        TaskManager._instance = _task_manager_instance
    elif project_root is not None:
        incoming = Path(project_root).resolve()
        if incoming != _task_manager_root:
            import warnings

            warnings.warn(
                f"TaskManager 已在 {_task_manager_root} 初始化，忽略传入路径 {incoming}"
            )
    return _task_manager_instance


def reset_task_manager() -> None:
    """重置 TaskManager 单例。"""
    global _task_manager_instance, _task_manager_root
    _task_manager_instance = None
    _task_manager_root = None
    TaskManager._instance = None
