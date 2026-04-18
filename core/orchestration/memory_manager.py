#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Memory Manager (记忆管理器)

Phase 7 核心模块

功能：
- 短期记忆管理（当前会话）
- 中期记忆管理（世代内）
- 长期记忆管理（跨世代）
- 记忆检索和聚合
- 记忆持久化
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

# 导入新的记忆组件
from core.orchestration.semantic_retriever import SemanticRetriever, get_semantic_retriever
from core.orchestration.compression_persister import CompressionPersister, get_compression_persister
from core.orchestration.forgetting_engine import ForgettingEngine, get_forgetting_engine


# ============================================================================
# 记忆定义
# ============================================================================

@dataclass
class ShortTermMemory:
    """短期记忆（当前会话）"""
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    task_list: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thoughts: List[str] = field(default_factory=list)
    user_inputs: List[str] = field(default_factory=list)


@dataclass
class MidTermMemory:
    """中期记忆（世代内）"""
    generation: int
    created_at: datetime = field(default_factory=datetime.now)
    current_task: str = ""
    task_plan: List[Dict[str, Any]] = field(default_factory=list)
    completed_tasks: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    code_insights: List[Dict[str, Any]] = field(default_factory=list)
    tool_stats: Dict[str, int] = field(default_factory=dict)


@dataclass
class LongTermMemory:
    """长期记忆（跨世代）"""
    current_generation: int = 1
    total_generations: int = 1
    core_wisdom: str = ""
    skills_profile: Dict[str, Any] = field(default_factory=dict)
    evolution_history: List[Dict[str, Any]] = field(default_factory=list)
    next_targets: List[str] = field(default_factory=list)
    archive_index: Dict[int, str] = field(default_factory=dict)  # generation -> archive_path


@dataclass
class MemorySummary:
    """记忆摘要"""
    generation: int
    short_term_count: int = 0
    mid_term_count: int = 0
    long_term_count: int = 0
    recent_insights: List[str] = field(default_factory=list)
    current_task: str = ""
    progress: str = ""


# ============================================================================
# Memory Manager
# ============================================================================

class MemoryManager:
    """
    记忆管理器

    统一管理三层记忆系统：
    - 短期记忆：当前会话的任务、工具调用、思考过程
    - 中期记忆：世代内的任务计划、洞察、代码理解
    - 长期记忆：跨世代的核心智慧、能力画像、进化历史

    使用方式：
        manager = MemoryManager()
        manager.record_tool_call("read_file", {"path": "..."})
        summary = manager.get_summary()
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化记忆管理器

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 三层记忆
        self.short_term: ShortTermMemory = ShortTermMemory(session_id=self._generate_session_id())
        self.mid_term: MidTermMemory = self._load_mid_term()
        self.long_term: LongTermMemory = self._load_long_term()

        # 新的记忆组件（语义检索、压缩持久化、遗忘引擎）
        self.semantic_retriever = get_semantic_retriever(project_root)
        self.compression_persister = get_compression_persister(project_root)
        self.forgetting_engine = get_forgetting_engine(project_root)

        # 统计
        self._stats = {
            "tool_calls_recorded": 0,
            "insights_recorded": 0,
            "memory_saves": 0,
        }

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _get_memory_path(self) -> Path:
        """获取记忆文件路径"""
        memory_dir = self.project_root / "workspace" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        return memory_dir / "memory.json"

    def _get_archive_dir(self) -> Path:
        """获取归档目录"""
        archive_dir = self.project_root / "workspace" / "memory" / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir

    # =========================================================================
    # 短期记忆操作
    # =========================================================================

    def record_tool_call(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """
        记录工具调用

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 执行结果
            success: 是否成功
        """
        call_record = {
            "tool": tool_name,
            "args": args or {},
            "result": result or "",
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        self.short_term.tool_calls.append(call_record)
        self._stats["tool_calls_recorded"] += 1

        # 更新中期记忆的工具统计
        if tool_name not in self.mid_term.tool_stats:
            self.mid_term.tool_stats[tool_name] = 0
        self.mid_term.tool_stats[tool_name] += 1

    def record_thought(self, thought: str) -> None:
        """记录思考过程"""
        self.short_term.thoughts.append({
            "content": thought,
            "timestamp": datetime.now().isoformat(),
        })

    def record_user_input(self, user_input: str) -> None:
        """记录用户输入"""
        self.short_term.user_inputs.append({
            "content": user_input,
            "timestamp": datetime.now().isoformat(),
        })

    def add_task(self, task: Dict[str, Any]) -> None:
        """添加任务到短期记忆"""
        self.short_term.task_list.append(task)

    def complete_task(self, task_id: str, summary: str) -> None:
        """标记任务完成"""
        # 从任务列表移除
        self.short_term.task_list = [
            t for t in self.short_term.task_list
            if t.get("id") != task_id
        ]
        # 添加到已完成
        self.mid_term.completed_tasks.append({
            "task_id": task_id,
            "summary": summary,
            "completed_at": datetime.now().isoformat(),
        })

    def get_short_term_summary(self) -> Dict[str, Any]:
        """获取短期记忆摘要"""
        return {
            "session_id": self.short_term.session_id,
            "created_at": self.short_term.created_at.isoformat(),
            "task_count": len(self.short_term.task_list),
            "tool_call_count": len(self.short_term.tool_calls),
            "thought_count": len(self.short_term.thoughts),
            "recent_tool_calls": [
                {
                    "tool": tc["tool"],
                    "success": tc["success"],
                    "timestamp": tc["timestamp"],
                }
                for tc in self.short_term.tool_calls[-10:]
            ],
        }

    # =========================================================================
    # 中期记忆操作
    # =========================================================================

    def set_current_task(self, task: str) -> None:
        """设置当前任务"""
        self.mid_term.current_task = task

    def get_current_task(self) -> str:
        """获取当前任务"""
        return self.mid_term.current_task

    def add_insight(self, insight: str, category: str = "general") -> None:
        """
        添加洞察

        Args:
            insight: 洞察内容
            category: 分类
        """
        self.mid_term.insights.append({
            "content": insight,
            "category": category,
            "timestamp": datetime.now().isoformat(),
        })
        self._stats["insights_recorded"] += 1

    def add_code_insight(self, module: str, insight: str) -> None:
        """添加代码洞察"""
        self.mid_term.code_insights.append({
            "module": module,
            "insight": insight,
            "timestamp": datetime.now().isoformat(),
        })

    def get_insights(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取洞察"""
        if category:
            return [i for i in self.mid_term.insights if i.get("category") == category]
        return self.mid_term.insights

    def get_code_insights(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取代码洞察"""
        if module:
            return [i for i in self.mid_term.code_insights if i.get("module") == module]
        return self.mid_term.code_insights

    def _load_mid_term(self) -> MidTermMemory:
        """加载中期记忆"""
        memory_file = self._get_memory_path()
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return MidTermMemory(
                    generation=data.get("generation", 1),
                    current_task=data.get("current_task", ""),
                    task_plan=data.get("task_plan", []),
                    completed_tasks=data.get("completed_tasks", []),
                    insights=data.get("insights", []),
                    code_insights=data.get("code_insights", []),
                    tool_stats=data.get("tool_stats", {}),
                )
            except Exception:
                pass
        return MidTermMemory(generation=self._get_current_generation())

    def _save_mid_term(self) -> None:
        """保存中期记忆"""
        memory_file = self._get_memory_path()
        data = {
            "generation": self.mid_term.generation,
            "current_task": self.mid_term.current_task,
            "task_plan": self.mid_term.task_plan,
            "completed_tasks": self.mid_term.completed_tasks,
            "insights": self.mid_term.insights,
            "code_insights": self.mid_term.code_insights,
            "tool_stats": self.mid_term.tool_stats,
        }
        Path(memory_file).parent.mkdir(parents=True, exist_ok=True)
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # 长期记忆操作
    # =========================================================================

    def _load_long_term(self) -> LongTermMemory:
        """加载长期记忆"""
        memory_file = self._get_memory_path()
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return LongTermMemory(
                    current_generation=data.get("generation", 1),
                    total_generations=data.get("total_generations", 1),
                    core_wisdom=data.get("core_wisdom", ""),
                    skills_profile=data.get("skills_profile", {}),
                    evolution_history=data.get("evolution_history", []),
                    next_targets=data.get("next_targets", []),
                    archive_index=data.get("archive_index", {}),
                )
            except Exception:
                pass
        return LongTermMemory()

    def set_core_wisdom(self, wisdom: str) -> None:
        """设置核心智慧"""
        self.long_term.core_wisdom = wisdom
        self._save_long_term()

    def get_core_wisdom(self) -> str:
        """获取核心智慧"""
        return self.long_term.core_wisdom

    def update_skills_profile(self, skills: Dict[str, Any]) -> None:
        """更新能力画像"""
        self.long_term.skills_profile.update(skills)
        self._save_long_term()

    def get_skills_profile(self) -> Dict[str, Any]:
        """获取能力画像"""
        return self.long_term.skills_profile

    def add_evolution_record(self, evolution: Dict[str, Any]) -> None:
        """添加进化记录"""
        self.long_term.evolution_history.append({
            **evolution,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_long_term()

    def advance_generation(self) -> int:
        """推进世代"""
        new_generation = self.long_term.current_generation + 1
        self.long_term.current_generations = new_generation
        self.mid_term.generation = new_generation
        self._archive_current_generation()
        self._save_long_term()
        return new_generation

    def _archive_current_generation(self) -> str:
        """归档当前世代"""
        archive_dir = self._get_archive_dir()
        archive_file = archive_dir / f"gen_{self.mid_term.generation}.json"

        archive_data = {
            "generation": self.mid_term.generation,
            "created_at": self.mid_term.created_at.isoformat(),
            "current_task": self.mid_term.current_task,
            "task_plan": self.mid_term.task_plan,
            "completed_tasks": self.mid_term.completed_tasks,
            "insights": self.mid_term.insights,
            "code_insights": self.mid_term.code_insights,
            "tool_stats": self.mid_term.tool_stats,
        }

        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)

        self.long_term.archive_index[self.mid_term.generation] = str(archive_file)
        return str(archive_file)

    def _save_long_term(self) -> None:
        """保存长期记忆"""
        memory_file = self._get_memory_path()
        data = {
            "generation": self.long_term.current_generation,
            "total_generations": self.long_term.total_generations,
            "core_wisdom": self.long_term.core_wisdom,
            "skills_profile": self.long_term.skills_profile,
            "evolution_history": self.long_term.evolution_history,
            "next_targets": self.long_term.next_targets,
            "archive_index": {
                str(k): v for k, v in self.long_term.archive_index.items()
            },
        }
        Path(memory_file).parent.mkdir(parents=True, exist_ok=True)
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._stats["memory_saves"] += 1

    def get_archive(self, generation: int) -> Optional[Dict[str, Any]]:
        """获取指定世代的归档"""
        archive_file = self.long_term.archive_index.get(generation)
        if archive_file and Path(archive_file).exists():
            with open(archive_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def list_archives(self) -> List[int]:
        """列出所有归档的世代"""
        return sorted(self.long_term.archive_index.keys())

    def _get_current_generation(self) -> int:
        """获取当前世代"""
        memory_file = self._get_memory_path()
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get("generation", 1)
            except Exception:
                pass
        return 1

    # =========================================================================
    # 聚合操作
    # =========================================================================

    def get_summary(self) -> MemorySummary:
        """获取记忆摘要"""
        return MemorySummary(
            generation=self.long_term.current_generation,
            short_term_count=len(self.short_term.tool_calls),
            mid_term_count=len(self.mid_term.insights),
            long_term_count=len(self.long_term.evolution_history),
            recent_insights=[i["content"][:100] for i in self.mid_term.insights[-5:]],
            current_task=self.mid_term.current_task,
            progress=f"{len(self.mid_term.completed_tasks)} tasks completed",
        )

    def get_full_memory(self) -> Dict[str, Any]:
        """获取完整记忆"""
        return {
            "short_term": {
                "session_id": self.short_term.session_id,
                "tool_call_count": len(self.short_term.tool_calls),
                "thought_count": len(self.short_term.thoughts),
                "task_count": len(self.short_term.task_list),
            },
            "mid_term": {
                "generation": self.mid_term.generation,
                "current_task": self.mid_term.current_task,
                "completed_tasks": len(self.mid_term.completed_tasks),
                "insights": len(self.mid_term.insights),
                "tool_stats": self.mid_term.tool_stats,
            },
            "long_term": {
                "current_generation": self.long_term.current_generation,
                "total_generations": self.long_term.total_generations,
                "core_wisdom": self.long_term.core_wisdom[:200] if self.long_term.core_wisdom else "",
                "skills_profile": self.long_term.skills_profile,
                "evolution_history": len(self.long_term.evolution_history),
            },
        }

    def save_all(self) -> None:
        """保存所有记忆"""
        self._save_mid_term()
        self._save_long_term()

    def clear_short_term(self) -> None:
        """清除短期记忆"""
        self.short_term = ShortTermMemory(session_id=self._generate_session_id())

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "generation": self.long_term.current_generation,
            "short_term_tool_calls": len(self.short_term.tool_calls),
            "mid_term_insights": len(self.mid_term.insights),
            "long_term_archives": len(self.long_term.archive_index),
        }

    # =========================================================================
    # 语义检索集成 (Phase 3)
    # =========================================================================

    def search_memories(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[tuple]:
        """
        语义搜索记忆

        Args:
            query: 查询文本
            top_k: 返回数量
            memory_type: 记忆类型过滤

        Returns:
            (记忆条目, 相似度) 列表
        """
        return self.semantic_retriever.search(
            query=query,
            top_k=top_k,
            memory_type=memory_type,
        )

    def search_decisions(self, query: str, top_k: int = 3) -> List[tuple]:
        """
        搜索相关决策

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            (记忆条目, 相似度) 列表
        """
        return self.semantic_retriever.search_decisions(query, top_k)

    def search_insights(self, query: str, top_k: int = 5) -> List[tuple]:
        """
        搜索相关洞察

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            (记忆条目, 相似度) 列表
        """
        return self.semantic_retriever.search_insights(query, top_k)

    def index_decision(self, decision: str, context: str = "") -> Any:
        """
        索引关键决策

        Args:
            decision: 决策内容
            context: 决策上下文

        Returns:
            记忆条目
        """
        entry = self.semantic_retriever.index_decision(
            decision=decision,
            context=context,
            generation=self.long_term.current_generation,
        )
        # 同时保存到中期记忆的压缩持久化
        self.compression_persister.save_decision(
            generation=self.long_term.current_generation,
            decision=decision,
            context=context,
        )
        return entry

    def index_insight(self, insight: str, category: str = "general") -> Any:
        """
        索引洞察

        Args:
            insight: 洞察内容
            category: 分类

        Returns:
            记忆条目
        """
        return self.semantic_retriever.index_insight(
            insight=insight,
            category=category,
            generation=self.long_term.current_generation,
        )

    def index_tool_usage(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
    ) -> Any:
        """
        索引工具使用

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 执行结果
            success: 是否成功

        Returns:
            记忆条目
        """
        return self.semantic_retriever.index_tool_usage(
            tool_name=tool_name,
            args=args,
            result=result,
            success=success,
            generation=self.long_term.current_generation,
        )

    # =========================================================================
    # 压缩持久化集成 (Phase 2)
    # =========================================================================

    def save_compression_snapshot(
        self,
        messages: List[Any],
        summary: str,
        before_tokens: int,
        after_tokens: int,
        level: str = "standard",
        reason: str = "",
        key_decisions: Optional[List[Dict[str, Any]]] = None,
        tool_stats: Optional[Dict[str, int]] = None,
    ) -> Any:
        """
        保存压缩快照

        Args:
            messages: 压缩后的消息列表
            summary: 压缩摘要
            before_tokens: 压缩前 token 数
            after_tokens: 压缩后 token 数
            level: 压缩级别
            reason: 压缩原因
            key_decisions: 关键决策
            tool_stats: 工具统计

        Returns:
            压缩快照
        """
        return self.compression_persister.save_snapshot(
            generation=self.long_term.current_generation,
            messages=messages,
            summary=summary,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            level=level,
            reason=reason,
            key_decisions=key_decisions,
            tool_stats=tool_stats,
        )

    def load_latest_snapshot(self) -> Optional[Any]:
        """
        加载最新压缩快照

        Returns:
            最新压缩快照
        """
        return self.compression_persister.load_latest_snapshot(self.long_term.current_generation)

    # =========================================================================
    # 遗忘引擎集成 (Phase 4)
    # =========================================================================

    def run_forgetting(self) -> int:
        """
        运行遗忘引擎

        Returns:
            遗忘的记忆数量
        """
        all_entries = list(self.semantic_retriever.index.values())
        forgotten_count = 0

        for entry in all_entries:
            should_forget, reason = self.forgetting_engine.should_forget(entry)
            if should_forget:
                self.forgetting_engine.forget(entry.id, entry, reason)
                self.semantic_retriever.delete(entry.id)
                forgotten_count += 1

        self.forgetting_engine.cleanup_trash()
        return forgotten_count

    # =========================================================================
    # 增强统计 (Phase 5)
    # =========================================================================

    def get_full_stats(self) -> Dict[str, Any]:
        """
        获取完整统计

        Returns:
            完整统计信息
        """
        semantic_stats = self.semantic_retriever.get_stats()
        forgetting_stats = self.forgetting_engine.get_forgetting_stats()
        persister_stats = self.compression_persister.get_storage_stats()

        return {
            "basic": self.get_statistics(),
            "semantic": semantic_stats,
            "compression": persister_stats,
            "forgetting": forgetting_stats,
            "generation": self.long_term.current_generation,
        }


# ============================================================================
# 全局单例
# ============================================================================

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager(project_root: Optional[str] = None) -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(project_root)
    return _memory_manager


def reset_memory_manager() -> None:
    """重置记忆管理器"""
    global _memory_manager
    _memory_manager = None
