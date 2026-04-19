#!/usr/bin/env python3
"""
任务状态机 - 强目标驱动与打勾收网机制

负责管理每个世代的任务清单，支持细粒度状态追踪。
只有在所有子任务完成（打勾）后，才允许结束本轮/触发重启。

数据结构：
- generation_goal: 当前世代的总目标
- subtasks: 列表 [{id, description, is_completed, result_summary, created_at, completed_at}]
"""

import json
import os
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime


class TaskManager:
    """任务状态机 - 单例模式，线程安全"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 数据文件路径
        self._data_dir = Path("workspace/memory")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._data_dir / "tasks.json"
        
        # 内存中的状态
        self._state = {
            "generation_goal": "",
            "subtasks": [],
            "created_at": None,
            "updated_at": None,
        }
        
        self._load()
    
    def _load(self) -> None:
        """从文件加载状态"""
        try:
            if self._state_file.exists():
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    self._state = json.load(f)
        except Exception:
            pass
    
    def _save(self) -> None:
        """持久化状态到文件"""
        self._state["updated_at"] = datetime.now().isoformat()
        try:
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.error(f"[TaskManager] 保存失败: {e}")
    
    @property
    def generation_goal(self) -> str:
        """获取当前世代总目标"""
        return self._state.get("generation_goal", "")
    
    @property
    def subtasks(self) -> List[Dict[str, Any]]:
        """获取所有子任务"""
        return self._state.get("subtasks", [])
    
    @property
    def completion_rate(self) -> float:
        """计算完成率"""
        tasks = self.subtasks
        if not tasks:
            return 0.0
        completed = sum(1 for t in tasks if t.get("is_completed", False))
        return completed / len(tasks)
    
    @property
    def is_all_completed(self) -> bool:
        """检查是否所有任务都已完成"""
        if not self.subtasks:
            return False  # 没有任何任务时不允许结束
        return all(t.get("is_completed", False) for t in self.subtasks)
    
    def set_plan(self, goal: str, tasks: List[str]) -> Dict[str, Any]:
        """
        覆盖当前计划，初始化多个未完成的子任务。
        
        Args:
            goal: 总目标描述
            tasks: 子任务描述列表
            
        Returns:
            {"status": "success", "goal": str, "tasks": list, "summary": str}
        """
        subtasks = []
        for i, desc in enumerate(tasks):
            subtasks.append({
                "id": i + 1,
                "description": desc,
                "is_completed": False,
                "result_summary": "",
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
            })
        
        self._state["generation_goal"] = goal
        self._state["subtasks"] = subtasks
        self._state["created_at"] = datetime.now().isoformat()
        self._save()
        
        summary = f"已设置 {len(tasks)} 个任务目标: {goal[:50]}..."
        return {
            "status": "success",
            "goal": goal,
            "tasks": [{"id": t["id"], "description": t["description"]} for t in subtasks],
            "summary": summary,
            "pending_count": len(tasks),
        }
    
    def tick_subtask(self, task_id: int, summary: str) -> Dict[str, Any]:
        """
        将指定任务标记为完成（打勾），并记录该步骤的结论摘要。
        
        Args:
            task_id: 任务 ID (1-based)
            summary: 完成该任务的摘要描述
            
        Returns:
            {"status": "success", "task_id": int, "completed_count": int, "total": int}
        """
        for task in self._state["subtasks"]:
            if task["id"] == task_id:
                task["is_completed"] = True
                task["result_summary"] = summary
                task["completed_at"] = datetime.now().isoformat()
                self._save()
                
                completed_count = sum(1 for t in self._state["subtasks"] if t["is_completed"])
                total = len(self._state["subtasks"])
                
                return {
                    "status": "success",
                    "task_id": task_id,
                    "description": task["description"],
                    "result_summary": summary,
                    "completed_count": completed_count,
                    "total": total,
                    "remaining": total - completed_count,
                    "all_done": completed_count == total,
                }
        
        return {
            "status": "error",
            "message": f"任务 ID {task_id} 不存在",
            "available_ids": [t["id"] for t in self._state["subtasks"]],
        }
    
    def uncheck_subtask(self, task_id: int) -> Dict[str, Any]:
        """将指定任务标记为未完成（取消勾选）"""
        for task in self._state["subtasks"]:
            if task["id"] == task_id:
                task["is_completed"] = False
                task["result_summary"] = ""
                task["completed_at"] = None
                self._save()
                
                return {
                    "status": "success",
                    "task_id": task_id,
                    "remaining": sum(1 for t in self._state["subtasks"] if not t["is_completed"]),
                }
        
        return {"status": "error", "message": f"任务 ID {task_id} 不存在"}
    
    def modify_task(self, task_id: int, new_description: str) -> Dict[str, Any]:
        """修改任务描述"""
        for task in self._state["subtasks"]:
            if task["id"] == task_id:
                task["description"] = new_description
                self._save()
                return {"status": "success", "task_id": task_id, "new_description": new_description}
        
        return {"status": "error", "message": f"任务 ID {task_id} 不存在"}
    
    def add_task(self, description: str) -> Dict[str, Any]:
        """追加新任务"""
        new_id = max([t["id"] for t in self._state["subtasks"]], default=0) + 1
        self._state["subtasks"].append({
            "id": new_id,
            "description": description,
            "is_completed": False,
            "result_summary": "",
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        })
        self._save()
        
        return {"status": "success", "task_id": new_id, "total": len(self._state["subtasks"])}
    
    def remove_task(self, task_id: int) -> Dict[str, Any]:
        """删除任务"""
        original_len = len(self._state["subtasks"])
        self._state["subtasks"] = [t for t in self._state["subtasks"] if t["id"] != task_id]
        
        if len(self._state["subtasks"]) < original_len:
            self._save()
            return {"status": "success", "removed_id": task_id, "remaining": len(self._state["subtasks"])}
        
        return {"status": "error", "message": f"任务 ID {task_id} 不存在"}
    
    def render_prompt_checklist(self) -> str:
        """
        将当前进度渲染为严格的 Markdown 文本，注入到 System Prompt。
        
        Returns:
            Markdown 格式的任务清单
        """
        goal = self.generation_goal
        tasks = self.subtasks
        
        if not goal and not tasks:
            return ""
        
        lines = []
        lines.append("")
        lines.append("=" * 60)
        
        # 总目标
        if goal:
            lines.append(f"🎯 【本轮总目标】: {goal}")
        
        # 执行清单
        if tasks:
            completed = sum(1 for t in tasks if t.get("is_completed", False))
            total = len(tasks)
            lines.append("")
            lines.append(f"📋 【执行清单】({completed}/{total} 已完成):")
            lines.append("(只有全部打勾才能结束本轮)")
            lines.append("")
            
            for task in tasks:
                check = "✅" if task["is_completed"] else "⏳"
                task_id = task["id"]
                desc = task["description"]
                
                if task["is_completed"] and task.get("result_summary"):
                    summary = task["result_summary"]
                    lines.append(f"{check} [x] {task_id}. {desc}")
                    lines.append(f"   └─ 结果: {summary}")
                else:
                    lines.append(f"{check} [ ] {task_id}. {desc}")
        else:
            lines.append("")
            lines.append("📋 【执行清单】: (暂无任务，请调用 set_plan 设置)")
        
        lines.append("=" * 60)
        lines.append("")
        
        return "\n".join(lines)
    
    def render_tui_status(self) -> str:
        """
        渲染 TUI 状态行（单行摘要）。
        
        Returns:
            "[G{n}] 目标: ... | 进度: 3/5 | 状态: 进行中"
        """
        goal = self.generation_goal[:30] + "..." if len(self.generation_goal) > 30 else self.generation_goal
        completed = sum(1 for t in self.subtasks if t["is_completed"])
        total = len(self.subtasks)
        
        if total == 0:
            return f"[无任务清单]"
        
        status = "✅全部完成" if completed == total else f"⏳进行中({completed}/{total})"
        return f"[G??] {goal} | 进度: {completed}/{total} | {status}"
    
    def clear_all(self) -> None:
        """清空所有任务（用于新世代开始）"""
        self._state = {
            "generation_goal": "",
            "subtasks": [],
            "created_at": None,
            "updated_at": None,
        }
        self._save()


# 全局单例
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """获取任务管理器单例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


def set_plan(goal: str, tasks: List[str]) -> Dict[str, Any]:
    """快捷接口：设置任务计划"""
    return get_task_manager().set_plan(goal, tasks)


def tick_subtask(task_id: int, summary: str) -> Dict[str, Any]:
    """快捷接口：完成子任务"""
    return get_task_manager().tick_subtask(task_id, summary)


def render_checklist() -> str:
    """快捷接口：渲染清单"""
    return get_task_manager().render_prompt_checklist()