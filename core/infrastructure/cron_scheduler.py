#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron 调度系统

提供：
- CronScheduler: 定时任务管理，支持 5 字段 cron 和间隔模式
- 持久化存储到 workspace/cron_jobs.json
- 由 agent.py 主循环调用 get_due_jobs() 触发到期任务
"""

from __future__ import annotations

import os
import json
import time
import uuid
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


def _match_cron_field(value: int, pattern: str, field_min: int, field_max: int) -> bool:
    """
    匹配单个 cron 字段

    支持: *, */N, N, N-M, N,M,O

    Args:
        value: 当前时间值
        pattern: cron 模式
        field_min: 字段最小值
        field_max: 字段最大值

    Returns:
        是否匹配
    """
    if pattern == "*":
        return True

    for part in pattern.split(","):
        part = part.strip()
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                start = field_min
            else:
                start = int(base)
            if value >= start and (value - start) % step == 0:
                return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        else:
            if int(part) == value:
                return True

    return False


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """
    检查给定时间是否匹配 cron 表达式

    Args:
        cron_expr: 5 字段 cron 表达式 (minute hour dom month dow)
        dt: 要检查的时间

    Returns:
        是否匹配
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    try:
        minute, hour, dom, month, dow = fields
        return (
            _match_cron_field(dt.minute, minute, 0, 59)
            and _match_cron_field(dt.hour, hour, 0, 23)
            and _match_cron_field(dt.day, dom, 1, 31)
            and _match_cron_field(dt.month, month, 1, 12)
            and _match_cron_field(dt.weekday(), dow, 0, 6)
        )
    except (ValueError, IndexError):
        return False


class CronScheduler:
    """Cron 调度器 — 持久化定时任务管理"""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, dict] = {}
        self._storage_path: Optional[Path] = None
        self._load()

    def _get_storage_path(self) -> Path:
        if self._storage_path:
            return self._storage_path
        ws = os.environ.get("VIBELUTION_WORKSPACE", "workspace")
        path = Path(ws) / "cron_jobs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path = path
        return path

    def _load(self):
        """从磁盘加载任务"""
        try:
            path = self._get_storage_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._jobs = data.get("jobs", {})
        except (json.JSONDecodeError, OSError):
            self._jobs = {}

    def _save(self):
        """持久化到磁盘"""
        try:
            path = self._get_storage_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"jobs": self._jobs, "updated_at": time.time()}, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def create_job(self, name: str, command: str, schedule: str) -> str:
        """
        创建定时任务

        Args:
            name: 任务名称
            command: 要执行的 Shell 命令
            schedule: 调度表达式
                - "interval:N" — 每 N 秒执行一次
                - "*/5 * * * *" — 标准 5 字段 cron 表达式

        Returns:
            包含 job_id 的 JSON
        """
        if not name or not name.strip():
            return json.dumps({"status": "error", "code": "MISSING_NAME", "message": "任务名称不能为空"})
        if not command or not command.strip():
            return json.dumps({"status": "error", "code": "MISSING_COMMAND", "message": "命令不能为空"})
        if not schedule or not schedule.strip():
            return json.dumps({"status": "error", "code": "MISSING_SCHEDULE", "message": "调度表达式不能为空"})

        schedule = schedule.strip()
        job_id = str(uuid.uuid4())[:8]

        # 验证 cron 格式
        if not schedule.startswith("interval:"):
            fields = schedule.split()
            if len(fields) != 5:
                return json.dumps({
                    "status": "error", "code": "INVALID_SCHEDULE",
                    "message": "调度格式错误。使用 'interval:N' (每 N 秒) 或标准 5 字段 cron 表达式"
                })

        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "name": name.strip(),
                "command": command.strip(),
                "schedule": schedule,
                "created_at": time.time(),
                "last_run": 0,
                "enabled": True,
            }
            self._save()

        return json.dumps({
            "status": "created",
            "job_id": job_id,
            "name": name.strip(),
            "schedule": schedule,
            "message": f"定时任务已创建，使用 cron_list_tool 查看",
        }, ensure_ascii=False)

    def list_jobs(self) -> str:
        """列出所有定时任务"""
        with self._lock:
            jobs = list(self._jobs.values())

        if not jobs:
            return json.dumps({"status": "empty", "jobs": [], "message": "无定时任务"}, ensure_ascii=False)

        job_list = []
        for j in jobs:
            last = "从未执行" if j["last_run"] == 0 else datetime.fromtimestamp(j["last_run"]).strftime("%Y-%m-%d %H:%M:%S")
            job_list.append({
                "id": j["id"],
                "name": j["name"],
                "schedule": j["schedule"],
                "command": j["command"][:60],
                "enabled": j["enabled"],
                "last_run": last,
            })

        return json.dumps({"status": "ok", "count": len(job_list), "jobs": job_list}, ensure_ascii=False)

    def delete_job(self, job_id: str) -> str:
        """删除定时任务"""
        with self._lock:
            if job_id not in self._jobs:
                return json.dumps({"status": "error", "code": "NOT_FOUND", "message": f"任务不存在: {job_id}"}, ensure_ascii=False)
            del self._jobs[job_id]
            self._save()

        return json.dumps({"status": "deleted", "job_id": job_id, "message": "定时任务已删除"}, ensure_ascii=False)

    def get_due_jobs(self) -> List[dict]:
        """
        获取到期的任务列表（由 agent.py 主循环调用）

        Returns:
            到期任务列表，每个任务包含 id, name, command
        """
        now = time.time()
        now_dt = datetime.now()
        due = []

        with self._lock:
            for job in self._jobs.values():
                if not job.get("enabled", True):
                    continue

                schedule = job["schedule"]
                should_run = False

                if schedule.startswith("interval:"):
                    interval = int(schedule.split(":", 1)[1])
                    if now - job.get("last_run", 0) >= interval:
                        should_run = True
                else:
                    if _cron_matches(schedule, now_dt):
                        last_run_dt = datetime.fromtimestamp(job.get("last_run", 0))
                        if last_run_dt.minute != now_dt.minute or last_run_dt.hour != now_dt.hour:
                            should_run = True

                if should_run:
                    job["last_run"] = now
                    due.append({
                        "id": job["id"],
                        "name": job["name"],
                        "command": job["command"],
                    })

            if due:
                self._save()

        return due


# 全局单例
_cron_scheduler: Optional[CronScheduler] = None


def get_cron_scheduler() -> CronScheduler:
    """获取 Cron 调度器单例"""
    global _cron_scheduler
    if _cron_scheduler is None:
        _cron_scheduler = CronScheduler()
    return _cron_scheduler
