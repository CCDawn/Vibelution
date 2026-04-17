#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈循环 (FeedbackLoop) - 从执行结果中学习

Phase 5 核心模块

功能：
- 收集执行反馈
- 评估行动效果
- 调整策略
- 持续改进
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from enum import Enum


# ============================================================================
# 反馈定义
# ============================================================================

class FeedbackType(Enum):
    """反馈类型"""
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    INFO = "info"
    IMPROVEMENT = "improvement"


class FeedbackSource(Enum):
    """反馈来源"""
    USER = "user"
    SYSTEM = "system"
    SELF = "self"
    EXTERNAL = "external"


@dataclass
class Feedback:
    """反馈"""
    feedback_id: str
    feedback_type: FeedbackType
    source: FeedbackSource
    content: str
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    action_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class FeedbackResult:
    """反馈结果"""
    accepted: bool
    action_taken: Optional[str] = None
    new_recommendation: Optional[str] = None


# ============================================================================
# 反馈循环
# ============================================================================

class FeedbackLoop:
    """
    反馈循环

    从各种来源收集反馈，评估效果，调整策略：

    反馈流程：
    1. 收集反馈 (从用户、系统、自我)
    2. 评估反馈质量和可信度
    3. 过滤和分类反馈
    4. 生成改进建议
    5. 应用改进

    使用方式：
        loop = FeedbackLoop()
        loop.collect_feedback(FeedbackType.SUCCESS, content)
        improvements = loop.get_improvements()
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化反馈循环

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 反馈存储
        self._feedbacks: List[Feedback] = []
        self._feedback_index: Dict[str, List[int]] = defaultdict(list)

        # 处理器
        self._handlers: Dict[FeedbackType, List[Callable]] = defaultdict(list)

        # 配置
        self._config = {
            "max_feedbacks": 1000,
            "auto_apply_threshold": 0.8,
            "aggregation_window": 3600,  # 1小时
        }

        # 统计
        self._stats = {
            "total_feedbacks": 0,
            "improvements_applied": 0,
            "recommendations_generated": 0,
        }

        # 加载数据
        self._load_data()

    # =========================================================================
    # 反馈收集
    # =========================================================================

    def collect_feedback(
        self,
        feedback_type: FeedbackType,
        content: str,
        source: FeedbackSource = FeedbackSource.SYSTEM,
        context: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
    ) -> Feedback:
        """
        收集反馈

        Args:
            feedback_type: 反馈类型
            content: 反馈内容
            source: 反馈来源
            context: 上下文
            confidence: 可信度

        Returns:
            反馈对象
        """
        feedback = Feedback(
            feedback_id=f"fb_{datetime.now().timestamp()}",
            feedback_type=feedback_type,
            source=source,
            content=content,
            context=context or {},
            confidence=confidence,
        )

        self._feedbacks.append(feedback)
        self._feedback_index[feedback_type.value].append(len(self._feedbacks) - 1)
        self._stats["total_feedbacks"] += 1

        # 调用处理器
        self._process_feedback(feedback)

        # 保存数据
        self._save_data()

        return feedback

    def collect_from_result(
        self,
        action_id: str,
        action_type: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
    ) -> Feedback:
        """
        从执行结果收集反馈

        Args:
            action_id: 动作 ID
            action_type: 动作类型
            success: 是否成功
            result: 执行结果

        Returns:
            反馈对象
        """
        feedback_type = FeedbackType.SUCCESS if success else FeedbackType.FAILURE

        feedback = self.collect_feedback(
            feedback_type=feedback_type,
            content=f"Action {action_id} {'succeeded' if success else 'failed'}",
            source=FeedbackSource.SELF,
            context={
                "action_id": action_id,
                "action_type": action_type,
                "result": result,
            },
            confidence=0.9 if success else 0.8,
        )

        feedback.action_id = action_id
        return feedback

    # =========================================================================
    # 反馈处理
    # =========================================================================

    def register_handler(
        self,
        feedback_type: FeedbackType,
        handler: Callable[[Feedback], Optional[FeedbackResult]],
    ) -> None:
        """
        注册反馈处理器

        Args:
            feedback_type: 反馈类型
            handler: 处理函数
        """
        self._handlers[feedback_type].append(handler)

    def _process_feedback(self, feedback: Feedback) -> None:
        """处理反馈"""
        handlers = self._handlers.get(feedback.feedback_type, [])

        for handler in handlers:
            try:
                result = handler(feedback)
                if result and result.accepted:
                    self._stats["improvements_applied"] += 1
            except Exception:
                pass

    def aggregate_feedback(
        self,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        聚合反馈

        Args:
            time_window: 时间窗口（秒）

        Returns:
            聚合结果
        """
        if time_window is None:
            time_window = self._config["aggregation_window"]

        cutoff = datetime.now().timestamp() - time_window
        recent = [
            f for f in self._feedbacks
            if f.timestamp.timestamp() >= cutoff
        ]

        # 按类型统计
        by_type = defaultdict(int)
        for f in recent:
            by_type[f.feedback_type.value] += 1

        # 按来源统计
        by_source = defaultdict(int)
        for f in recent:
            by_source[f.source.value] += 1

        return {
            "total": len(recent),
            "by_type": dict(by_type),
            "by_source": dict(by_source),
            "time_window": time_window,
        }

    # =========================================================================
    # 改进建议
    # =========================================================================

    def get_improvements(
        self,
        min_confidence: float = 0.6,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取改进建议

        Args:
            min_confidence: 最低置信度
            limit: 返回数量限制

        Returns:
            改进建议列表
        """
        improvements = []

        # 从失败反馈中提取改进建议
        failures = self._feedbacks[-100:]  # 最近 100 个
        for f in failures:
            if f.feedback_type == FeedbackType.FAILURE:
                suggestion = self._generate_improvement(f)
                if suggestion and f.confidence >= min_confidence:
                    improvements.append(suggestion)

        # 从警告反馈中提取改进建议
        for f in failures:
            if f.feedback_type == FeedbackType.WARNING:
                suggestion = self._generate_improvement(f)
                if suggestion and f.confidence >= min_confidence:
                    improvements.append(suggestion)

        # 按置信度排序
        improvements.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return improvements[:limit]

    def _generate_improvement(self, feedback: Feedback) -> Dict[str, Any]:
        """生成改进建议"""
        # 简单的规则生成
        content = feedback.content.lower()

        if "timeout" in content:
            return {
                "type": "timeout_handling",
                "description": "增加超时处理和重试机制",
                "confidence": feedback.confidence * 0.9,
            }
        elif "error" in content:
            return {
                "type": "error_handling",
                "description": "改进错误处理逻辑",
                "confidence": feedback.confidence * 0.8,
            }
        elif "memory" in content:
            return {
                "type": "memory_management",
                "description": "优化内存使用",
                "confidence": feedback.confidence * 0.7,
            }
        else:
            return {
                "type": "general",
                "description": f"根据反馈调整: {feedback.content[:50]}",
                "confidence": feedback.confidence * 0.5,
            }

    def apply_improvement(
        self,
        improvement: Dict[str, Any],
    ) -> bool:
        """
        应用改进

        Args:
            improvement: 改进建议

        Returns:
            是否成功
        """
        improvement_type = improvement.get("type", "unknown")
        self._stats["improvements_applied"] += 1

        # 记录应用
        self.collect_feedback(
            FeedbackType.IMPROVEMENT,
            f"Applied improvement: {improvement_type}",
            source=FeedbackSource.SELF,
            context={"improvement": improvement},
        )

        return True

    # =========================================================================
    # 查询接口
    # =========================================================================

    def get_feedbacks(
        self,
        feedback_type: Optional[FeedbackType] = None,
        source: Optional[FeedbackSource] = None,
        limit: int = 100,
    ) -> List[Feedback]:
        """
        获取反馈列表

        Args:
            feedback_type: 反馈类型过滤
            source: 来源过滤
            limit: 返回数量限制

        Returns:
            反馈列表
        """
        results = self._feedbacks

        if feedback_type:
            results = [
                f for i in self._feedback_index.get(feedback_type.value, [])
                if i < len(self._feedbacks)
                for f in [self._feedbacks[i]]
            ]

        if source:
            results = [f for f in results if f.source == source]

        return results[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "total_feedbacks": len(self._feedbacks),
            "by_type": {
                ft: len(ids)
                for ft, ids in self._feedback_index.items()
            },
            "improvement_rate": (
                self._stats["improvements_applied"] / self._stats["total_feedbacks"]
                if self._stats["total_feedbacks"] > 0 else 0
            ),
        }

    # =========================================================================
    # 持久化
    # =========================================================================

    def _get_data_path(self) -> Path:
        """获取数据文件路径"""
        data_dir = self.project_root / "workspace" / "feedback"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "feedback_data.json"

    def _load_data(self) -> None:
        """加载数据"""
        data_path = self._get_data_path()
        if not data_path.exists():
            return

        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._feedbacks = [
                Feedback(
                    feedback_id=f["feedback_id"],
                    feedback_type=FeedbackType(f["feedback_type"]),
                    source=FeedbackSource(f["source"]),
                    content=f["content"],
                    context=f.get("context", {}),
                    timestamp=datetime.fromisoformat(f["timestamp"]),
                    action_id=f.get("action_id"),
                    confidence=f.get("confidence", 1.0),
                )
                for f in data.get("feedbacks", [])
            ]

            # 重建索引
            for i, f in enumerate(self._feedbacks):
                self._feedback_index[f.feedback_type.value].append(i)

            self._stats = data.get("stats", self._stats)

        except Exception:
            pass

    def _save_data(self) -> None:
        """保存数据"""
        data_path = self._get_data_path()

        data = {
            "feedbacks": [
                {
                    "feedback_id": f.feedback_id,
                    "feedback_type": f.feedback_type.value,
                    "source": f.source.value,
                    "content": f.content,
                    "context": f.context,
                    "timestamp": f.timestamp.isoformat(),
                    "action_id": f.action_id,
                    "confidence": f.confidence,
                }
                for f in self._feedbacks[-self._config["max_feedbacks"]:]
            ],
            "stats": self._stats,
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # 分析
    # =========================================================================

    def analyze_trends(self, days: int = 7) -> Dict[str, Any]:
        """
        分析反馈趋势

        Args:
            days: 分析天数

        Returns:
            趋势分析结果
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)
        recent = [f for f in self._feedbacks if f.timestamp >= cutoff]

        # 计算成功率
        success = sum(1 for f in recent if f.feedback_type == FeedbackType.SUCCESS)
        failure = sum(1 for f in recent if f.feedback_type == FeedbackType.FAILURE)
        total = success + failure

        # 按天统计
        by_day = defaultdict(lambda: {"success": 0, "failure": 0})
        for f in recent:
            day = f.timestamp.strftime("%Y-%m-%d")
            if f.feedback_type == FeedbackType.SUCCESS:
                by_day[day]["success"] += 1
            elif f.feedback_type == FeedbackType.FAILURE:
                by_day[day]["failure"] += 1

        return {
            "period_days": days,
            "total_feedbacks": len(recent),
            "success_rate": success / total if total > 0 else 0,
            "failure_rate": failure / total if total > 0 else 0,
            "by_day": dict(by_day),
        }


# ============================================================================
# 全局单例
# ============================================================================

_feedback_loop: Optional[FeedbackLoop] = None


def get_feedback_loop(project_root: Optional[str] = None) -> FeedbackLoop:
    """获取反馈循环单例"""
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop(project_root)
    return _feedback_loop


def reset_feedback_loop() -> None:
    """重置反馈循环"""
    global _feedback_loop
    _feedback_loop = None
