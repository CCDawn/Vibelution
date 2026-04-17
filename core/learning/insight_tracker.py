#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洞察追踪器 (InsightTracker) - 追踪重要洞察

Phase 5 核心模块

功能：
- 记录重要洞察
- 分类和管理洞察
- 评估洞察价值
- 关联洞察到行动
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from enum import Enum


# ============================================================================
# 洞察定义
# ============================================================================

class InsightCategory(Enum):
    """洞察类别"""
    CODE = "code"
    ARCHITECTURE = "architecture"
    PATTERN = "pattern"
    ERROR = "error"
    OPTIMIZATION = "optimization"
    LEARNING = "learning"
    DECISION = "decision"


class InsightPriority(Enum):
    """洞察优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Insight:
    """洞察"""
    insight_id: str
    category: InsightCategory
    title: str
    content: str
    priority: InsightPriority
    source: str  # "user", "self", "system", "learning"
    context: Dict[str, Any] = field(default_factory=dict)
    related_actions: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    accessed_at: Optional[datetime] = None
    impact_score: float = 0.0  # 影响分数
    evidence: List[str] = field(default_factory=list)


# ============================================================================
# 洞察追踪器
# ============================================================================

class InsightTracker:
    """
    洞察追踪器

    管理重要洞察的收集、分类和应用：

    洞察流程：
    1. 收集洞察 (从执行、反馈、学习中)
    2. 分类和标记
    3. 评估影响
    4. 关联行动
    5. 应用洞察

    使用方式：
        tracker = InsightTracker()
        tracker.record_insight(InsightCategory.CODE, "优化建议")
        insights = tracker.get_insights(category=CODE)
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化洞察追踪器

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 洞察存储
        self._insights: Dict[str, Insight] = {}
        self._insight_index: Dict[str, List[str]] = defaultdict(list)

        # 统计
        self._stats = {
            "total_insights": 0,
            "by_category": defaultdict(int),
            "by_priority": defaultdict(int),
        }

        # 加载数据
        self._load_data()

    # =========================================================================
    # 核心接口
    # =========================================================================

    def record_insight(
        self,
        category: InsightCategory,
        title: str,
        content: str,
        source: str = "self",
        priority: InsightPriority = InsightPriority.MEDIUM,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Insight:
        """
        记录洞察

        Args:
            category: 类别
            title: 标题
            content: 内容
            source: 来源
            priority: 优先级
            context: 上下文
            tags: 标签

        Returns:
            洞察对象
        """
        insight = Insight(
            insight_id=f"ins_{datetime.now().timestamp()}",
            category=category,
            title=title,
            content=content,
            priority=priority,
            source=source,
            context=context or {},
            tags=tags or [],
        )

        self._insights[insight.insight_id] = insight
        self._insight_index[category.value].append(insight.insight_id)

        # 更新统计
        self._stats["total_insights"] += 1
        self._stats["by_category"][category.value] += 1
        self._stats["by_priority"][priority.name] += 1

        # 保存数据
        self._save_data()

        return insight

    def get_insights(
        self,
        category: Optional[InsightCategory] = None,
        priority: Optional[InsightPriority] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Insight]:
        """
        获取洞察

        Args:
            category: 类别过滤
            priority: 优先级过滤
            tags: 标签过滤
            limit: 返回数量限制

        Returns:
            洞察列表
        """
        results = list(self._insights.values())

        # 按类别过滤
        if category:
            results = [
                i for i in results if i.category == category
            ]

        # 按优先级过滤
        if priority:
            results = [
                i for i in results if i.priority == priority
            ]

        # 按标签过滤
        if tags:
            results = [
                i for i in results
                if any(tag in i.tags for tag in tags)
            ]

        # 按创建时间排序
        results.sort(key=lambda i: i.created_at, reverse=True)

        return results[:limit]

    def get_insight(self, insight_id: str) -> Optional[Insight]:
        """
        获取单个洞察

        Args:
            insight_id: 洞察 ID

        Returns:
            洞察对象
        """
        insight = self._insights.get(insight_id)
        if insight:
            insight.accessed_at = datetime.now()
        return insight

    # =========================================================================
    # 洞察管理
    # =========================================================================

    def update_insight(
        self,
        insight_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        priority: Optional[InsightPriority] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        更新洞察

        Args:
            insight_id: 洞察 ID
            title: 标题
            content: 内容
            priority: 优先级
            tags: 标签

        Returns:
            是否成功
        """
        insight = self._insights.get(insight_id)
        if not insight:
            return False

        if title:
            insight.title = title
        if content:
            insight.content = content
        if priority:
            insight.priority = priority
        if tags:
            insight.tags = tags

        insight.updated_at = datetime.now()
        self._save_data()

        return True

    def add_evidence(
        self,
        insight_id: str,
        evidence: str,
    ) -> bool:
        """
        添加证据

        Args:
            insight_id: 洞察 ID
            evidence: 证据

        Returns:
            是否成功
        """
        insight = self._insights.get(insight_id)
        if not insight:
            return False

        insight.evidence.append(evidence)
        insight.updated_at = datetime.now()
        self._save_data()

        return True

    def link_action(
        self,
        insight_id: str,
        action_id: str,
    ) -> bool:
        """
        关联行动

        Args:
            insight_id: 洞察 ID
            action_id: 行动 ID

        Returns:
            是否成功
        """
        insight = self._insights.get(insight_id)
        if not insight:
            return False

        if action_id not in insight.related_actions:
            insight.related_actions.append(action_id)
            insight.updated_at = datetime.now()
            self._save_data()

        return True

    def delete_insight(self, insight_id: str) -> bool:
        """
        删除洞察

        Args:
            insight_id: 洞察 ID

        Returns:
            是否成功
        """
        if insight_id not in self._insights:
            return False

        insight = self._insights.pop(insight_id)

        # 从索引中移除
        for category, ids in self._insight_index.items():
            if insight_id in ids:
                ids.remove(insight_id)

        # 更新统计
        self._stats["total_insights"] -= 1
        self._stats["by_category"][insight.category.value] -= 1
        self._stats["by_priority"][insight.priority.name] -= 1

        self._save_data()
        return True

    # =========================================================================
    # 搜索和分析
    # =========================================================================

    def search_insights(
        self,
        query: str,
        limit: int = 20,
    ) -> List[Insight]:
        """
        搜索洞察

        Args:
            query: 搜索关键词
            limit: 返回数量限制

        Returns:
            匹配的洞察
        """
        query_lower = query.lower()
        results = []

        for insight in self._insights.values():
            score = 0

            # 标题匹配
            if query_lower in insight.title.lower():
                score += 3

            # 内容匹配
            if query_lower in insight.content.lower():
                score += 2

            # 标签匹配
            for tag in insight.tags:
                if query_lower in tag.lower():
                    score += 1
                    break

            if score > 0:
                results.append((insight, score))

        # 按分数排序
        results.sort(key=lambda x: x[1], reverse=True)

        return [r[0] for r in results[:limit]]

    def get_high_value_insights(self, min_impact: float = 0.7) -> List[Insight]:
        """
        获取高价值洞察

        Args:
            min_impact: 最低影响分数

        Returns:
            高价值洞察列表
        """
        return [
            i for i in self._insights.values()
            if i.impact_score >= min_impact
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_insights": len(self._insights),
            "by_category": dict(self._stats["by_category"]),
            "by_priority": dict(self._stats["by_priority"]),
            "average_impact": (
                sum(i.impact_score for i in self._insights.values()) / len(self._insights)
                if self._insights else 0
            ),
        }

    def analyze_insights_by_category(self) -> Dict[str, Any]:
        """按类别分析洞察"""
        analysis = {}

        for category in InsightCategory:
            insights = self.get_insights(category=category)
            if insights:
                analysis[category.value] = {
                    "count": len(insights),
                    "high_priority": sum(
                        1 for i in insights
                        if i.priority in (InsightPriority.HIGH, InsightPriority.CRITICAL)
                    ),
                    "average_impact": (
                        sum(i.impact_score for i in insights) / len(insights)
                        if insights else 0
                    ),
                    "latest": insights[0].created_at.isoformat() if insights else None,
                }

        return analysis

    # =========================================================================
    # 持久化
    # =========================================================================

    def _get_data_path(self) -> Path:
        """获取数据文件路径"""
        data_dir = self.project_root / "workspace" / "insights"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "insights_data.json"

    def _load_data(self) -> None:
        """加载数据"""
        data_path = self._get_data_path()
        if not data_path.exists():
            return

        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._insights = {
                iid: Insight(
                    insight_id=iid,
                    category=InsightCategory(i["category"]),
                    title=i["title"],
                    content=i["content"],
                    priority=InsightPriority[i["priority"]],
                    source=i["source"],
                    context=i.get("context", {}),
                    related_actions=i.get("related_actions", []),
                    tags=i.get("tags", []),
                    created_at=datetime.fromisoformat(i["created_at"]),
                    updated_at=datetime.fromisoformat(i["updated_at"]),
                    accessed_at=(
                        datetime.fromisoformat(i["accessed_at"])
                        if i.get("accessed_at") else None
                    ),
                    impact_score=i.get("impact_score", 0.0),
                    evidence=i.get("evidence", []),
                )
                for iid, i in data.get("insights", {}).items()
            }

            # 重建索引
            for insight in self._insights.values():
                self._insight_index[insight.category.value].append(insight.insight_id)

            self._stats = data.get("stats", self._stats)

        except Exception:
            pass

    def _save_data(self) -> None:
        """保存数据"""
        data_path = self._get_data_path()

        data = {
            "insights": {
                iid: {
                    "category": i.category.value,
                    "title": i.title,
                    "content": i.content,
                    "priority": i.priority.name,
                    "source": i.source,
                    "context": i.context,
                    "related_actions": i.related_actions,
                    "tags": i.tags,
                    "created_at": i.created_at.isoformat(),
                    "updated_at": i.updated_at.isoformat(),
                    "accessed_at": (
                        i.accessed_at.isoformat() if i.accessed_at else None
                    ),
                    "impact_score": i.impact_score,
                    "evidence": i.evidence,
                }
                for iid, i in self._insights.items()
            },
            "stats": {
                "total_insights": len(self._insights),
                "by_category": dict(self._stats["by_category"]),
                "by_priority": dict(self._stats["by_priority"]),
            },
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # 导出
    # =========================================================================

    def export_insights(
        self,
        file_path: Optional[str] = None,
        category: Optional[InsightCategory] = None,
    ) -> str:
        """
        导出洞察

        Args:
            file_path: 文件路径
            category: 类别过滤

        Returns:
            导出内容
        """
        if file_path is None:
            file_path = str(
                self.project_root / "workspace" / "insights" / "export.json"
            )

        insights = self.get_insights(category=category) if category else list(self._insights.values())

        export_data = [
            {
                "id": i.insight_id,
                "category": i.category.value,
                "title": i.title,
                "content": i.content,
                "priority": i.priority.name,
                "tags": i.tags,
                "created_at": i.created_at.isoformat(),
                "impact_score": i.impact_score,
            }
            for i in insights
        ]

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        return file_path


# ============================================================================
# 全局单例
# ============================================================================

_insight_tracker: Optional[InsightTracker] = None


def get_insight_tracker(project_root: Optional[str] = None) -> InsightTracker:
    """获取洞察追踪器单例"""
    global _insight_tracker
    if _insight_tracker is None:
        _insight_tracker = InsightTracker(project_root)
    return _insight_tracker


def reset_insight_tracker() -> None:
    """重置洞察追踪器"""
    global _insight_tracker
    _insight_tracker = None
