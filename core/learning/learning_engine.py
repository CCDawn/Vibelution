#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习引擎 (LearningEngine) - 持续学习机制

Phase 5 核心模块

功能：
- 从任务执行中学习
- 提取成功模式
- 优化决策策略
- 遗忘过时知识
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import re


# ============================================================================
# 学习数据定义
# ============================================================================

@dataclass
class LearningExample:
    """学习示例"""
    example_id: str
    task_type: str
    context: Dict[str, Any]
    action: str
    result: str  # "success", "failure", "partial"
    outcome: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LearnedPattern:
    """学到的模式"""
    pattern_id: str
    pattern_type: str  # "action", "sequence", "condition"
    description: str
    confidence: float  # 0.0 - 1.0
    success_count: int = 0
    failure_count: int = 0
    examples: List[str] = field(default_factory=list)
    first_learned: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class LearningMetrics:
    """学习指标"""
    total_examples: int = 0
    patterns_learned: int = 0
    patterns_forgotten: int = 0
    average_confidence: float = 0.0
    learning_rate: float = 0.0  # 每时间单位学习的模式数


# ============================================================================
# 学习引擎
# ============================================================================

class LearningEngine:
    """
    学习引擎

    从执行历史中学习，提取模式，优化决策：

    学习流程：
    1. 记录执行示例
    2. 分析成功/失败模式
    3. 提取通用模式
    4. 评估模式置信度
    5. 更新模式库
    6. 应用模式到决策

    使用方式：
        engine = LearningEngine(project_root)
        engine.record_example(task_type, context, action, result)
        patterns = engine.get_best_patterns(task_type)
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        confidence_threshold: float = 0.6,
        max_patterns: int = 100,
    ):
        """
        初始化学习引擎

        Args:
            project_root: 项目根目录
            confidence_threshold: 置信度阈值
            max_patterns: 最大模式数量
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        self.confidence_threshold = confidence_threshold
        self.max_patterns = max_patterns

        # 数据存储
        self._examples: List[LearningExample] = []
        self._patterns: Dict[str, LearnedPattern] = {}
        self._pattern_index: Dict[str, List[str]] = defaultdict(list)

        # 统计
        self._metrics = LearningMetrics()

        # 加载已有数据
        self._load_data()

    # =========================================================================
    # 核心接口
    # =========================================================================

    def record_example(
        self,
        task_type: str,
        context: Dict[str, Any],
        action: str,
        result: str,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> LearningExample:
        """
        记录学习示例

        Args:
            task_type: 任务类型
            context: 执行上下文
            action: 执行的动作
            result: 执行结果
            outcome: 详细结果

        Returns:
            学习示例
        """
        example = LearningExample(
            example_id=f"ex_{datetime.now().timestamp()}",
            task_type=task_type,
            context=context,
            action=action,
            result=result,
            outcome=outcome or {},
        )

        self._examples.append(example)
        self._metrics.total_examples += 1

        # 如果成功，提取模式
        if result in ("success", "partial"):
            self._learn_from_success(example)

        # 如果失败，分析失败原因
        if result == "failure":
            self._analyze_failure(example)

        # 保存数据
        self._save_data()

        return example

    def get_best_patterns(
        self,
        task_type: str,
        limit: int = 5,
    ) -> List[LearnedPattern]:
        """
        获取最佳匹配模式

        Args:
            task_type: 任务类型
            limit: 返回数量限制

        Returns:
            最佳模式列表
        """
        pattern_ids = self._pattern_index.get(task_type, [])
        patterns = []

        for pid in pattern_ids:
            pattern = self._patterns.get(pid)
            if pattern and pattern.confidence >= self.confidence_threshold:
                patterns.append(pattern)

        # 按置信度排序
        patterns.sort(key=lambda p: p.confidence, reverse=True)

        return patterns[:limit]

    def suggest_action(
        self,
        task_type: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        根据学习到的模式建议动作

        Args:
            task_type: 任务类型
            context: 当前上下文

        Returns:
            建议的动作
        """
        patterns = self.get_best_patterns(task_type)

        for pattern in patterns:
            if self._matches_context(pattern, context):
                return pattern.description

        return None

    # =========================================================================
    # 模式学习
    # =========================================================================

    def _learn_from_success(self, example: LearningExample) -> None:
        """从成功案例中学习"""
        # 提取动作模式
        pattern_id = f"action_{example.task_type}_{example.action}"
        pattern_type = "action"

        if pattern_id in self._patterns:
            pattern = self._patterns[pattern_id]
            pattern.success_count += 1
            pattern.examples.append(example.example_id)
            pattern.last_updated = datetime.now()
            self._update_confidence(pattern)
        else:
            pattern = LearnedPattern(
                pattern_id=pattern_id,
                pattern_type=pattern_type,
                description=example.action,
                confidence=0.5,
                success_count=1,
                examples=[example.example_id],
            )
            self._patterns[pattern_id] = pattern
            self._pattern_index[example.task_type].append(pattern_id)
            self._metrics.patterns_learned += 1

        # 检查模式数量限制
        self._prune_patterns()

    def _analyze_failure(self, example: LearningExample) -> None:
        """分析失败案例"""
        # 记录失败模式，避免重复
        for pid in self._pattern_index.get(example.task_type, []):
            pattern = self._patterns.get(pid)
            if pattern and pattern.description == example.action:
                pattern.failure_count += 1
                pattern.last_updated = datetime.now()
                self._update_confidence(pattern)

    def _update_confidence(self, pattern: LearnedPattern) -> None:
        """更新模式置信度"""
        total = pattern.success_count + pattern.failure_count
        if total > 0:
            pattern.confidence = pattern.success_count / total

    def _matches_context(
        self,
        pattern: LearnedPattern,
        context: Dict[str, Any],
    ) -> bool:
        """检查上下文是否匹配"""
        # 简化匹配：只要有相关上下文即可
        return True

    def _prune_patterns(self) -> None:
        """修剪低置信度模式"""
        if len(self._patterns) <= self.max_patterns:
            return

        # 按置信度排序，保留高置信度模式
        sorted_patterns = sorted(
            self._patterns.items(),
            key=lambda x: x[1].confidence,
        )

        # 删除最低置信度模式
        to_remove = len(self._patterns) - self.max_patterns
        for pid, _ in sorted_patterns[:to_remove]:
            pattern = self._patterns.pop(pid, None)
            if pattern:
                self._metrics.patterns_forgotten += 1
                # 从索引中移除
                for task_type, pids in self._pattern_index.items():
                    if pid in pids:
                        pids.remove(pid)

    # =========================================================================
    # 统计和分析
    # =========================================================================

    def get_metrics(self) -> LearningMetrics:
        """获取学习指标"""
        self._metrics.patterns_learned = len(self._patterns)

        if self._patterns:
            self._metrics.average_confidence = sum(
                p.confidence for p in self._patterns.values()
            ) / len(self._patterns)

        return self._metrics

    def get_pattern_stats(self) -> Dict[str, Any]:
        """获取模式统计"""
        return {
            "total_patterns": len(self._patterns),
            "high_confidence": sum(
                1 for p in self._patterns.values() if p.confidence >= 0.8
            ),
            "medium_confidence": sum(
                1 for p in self._patterns.values()
                if 0.5 <= p.confidence < 0.8
            ),
            "low_confidence": sum(
                1 for p in self._patterns.values() if p.confidence < 0.5
            ),
            "patterns_by_type": defaultdict(int),
        }

    def analyze_learning_progress(
        self,
        time_window: Optional[timedelta] = None,
    ) -> Dict[str, Any]:
        """
        分析学习进度

        Args:
            time_window: 时间窗口

        Returns:
            学习进度报告
        """
        if time_window is None:
            time_window = timedelta(days=7)

        cutoff = datetime.now() - time_window
        recent_examples = [
            e for e in self._examples if e.timestamp >= cutoff
        ]

        success_count = sum(1 for e in recent_examples if e.result == "success")
        failure_count = sum(1 for e in recent_examples if e.result == "failure")

        return {
            "time_window_days": time_window.days,
            "examples_in_window": len(recent_examples),
            "success_rate": success_count / len(recent_examples) if recent_examples else 0,
            "failure_rate": failure_count / len(recent_examples) if recent_examples else 0,
            "new_patterns": len([
                p for p in self._patterns.values()
                if p.first_learned >= cutoff
            ]),
        }

    # =========================================================================
    # 持久化
    # =========================================================================

    def _get_data_path(self) -> Path:
        """获取数据文件路径"""
        data_dir = self.project_root / "workspace" / "learning"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "learning_data.json"

    def _load_data(self) -> None:
        """加载数据"""
        data_path = self._get_data_path()
        if not data_path.exists():
            return

        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 加载示例
            self._examples = [
                LearningExample(
                    example_id=e["example_id"],
                    task_type=e["task_type"],
                    context=e["context"],
                    action=e["action"],
                    result=e["result"],
                    outcome=e.get("outcome", {}),
                    timestamp=datetime.fromisoformat(e["timestamp"]),
                )
                for e in data.get("examples", [])
            ]

            # 加载模式
            self._patterns = {
                pid: LearnedPattern(
                    pattern_id=pid,
                    pattern_type=p["pattern_type"],
                    description=p["description"],
                    confidence=p["confidence"],
                    success_count=p.get("success_count", 0),
                    failure_count=p.get("failure_count", 0),
                    examples=p.get("examples", []),
                    first_learned=datetime.fromisoformat(p["first_learned"]),
                    last_updated=datetime.fromisoformat(p["last_updated"]),
                )
                for pid, p in data.get("patterns", {}).items()
            }

            # 重建索引
            for pattern in self._patterns.values():
                # 从 pattern_id 提取 task_type
                parts = pattern.pattern_id.split("_")
                if len(parts) >= 2:
                    task_type = parts[1]
                    self._pattern_index[task_type].append(pattern.pattern_id)

        except Exception:
            pass

    def _save_data(self) -> None:
        """保存数据"""
        data_path = self._get_data_path()

        data = {
            "examples": [
                {
                    "example_id": e.example_id,
                    "task_type": e.task_type,
                    "context": e.context,
                    "action": e.action,
                    "result": e.result,
                    "outcome": e.outcome,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in self._examples[-1000:]  # 只保存最近 1000 个
            ],
            "patterns": {
                pid: {
                    "pattern_type": p.pattern_type,
                    "description": p.description,
                    "confidence": p.confidence,
                    "success_count": p.success_count,
                    "failure_count": p.failure_count,
                    "examples": p.examples,
                    "first_learned": p.first_learned.isoformat(),
                    "last_updated": p.last_updated.isoformat(),
                }
                for pid, p in self._patterns.items()
            },
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # 导出和导入
    # =========================================================================

    def export_patterns(self, file_path: Optional[str] = None) -> str:
        """
        导出模式

        Args:
            file_path: 文件路径

        Returns:
            导出内容
        """
        if file_path is None:
            file_path = str(
                self.project_root / "workspace" / "learning" / "patterns.json"
            )

        patterns_data = {
            pid: {
                "pattern_type": p.pattern_type,
                "description": p.description,
                "confidence": p.confidence,
                "success_count": p.success_count,
            }
            for pid, p in self._patterns.items()
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(patterns_data, f, ensure_ascii=False, indent=2)

        return file_path

    def import_patterns(self, file_path: str) -> int:
        """
        导入模式

        Args:
            file_path: 文件路径

        Returns:
            导入的模式数量
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            patterns_data = json.load(f)

        imported = 0
        for pid, pdata in patterns_data.items():
            if pid not in self._patterns:
                pattern = LearnedPattern(
                    pattern_id=pid,
                    pattern_type=pdata["pattern_type"],
                    description=pdata["description"],
                    confidence=pdata["confidence"],
                    success_count=pdata.get("success_count", 0),
                )
                self._patterns[pid] = pattern
                imported += 1

        self._save_data()
        return imported


# ============================================================================
# 全局单例
# ============================================================================

_learning_engine: Optional[LearningEngine] = None


def get_learning_engine(
    project_root: Optional[str] = None,
) -> LearningEngine:
    """获取学习引擎单例"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine(project_root)
    return _learning_engine


def reset_learning_engine() -> None:
    """重置学习引擎"""
    global _learning_engine
    _learning_engine = None
