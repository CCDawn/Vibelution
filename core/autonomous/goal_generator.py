#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目标生成器 (GoalGenerator) - Phase 8 自主探索引擎核心模块

负责：
- 基于自我分析生成进化目标
- 将改进机会转化为 SMART 目标
- 评估目标可行性和优先级
- 生成多候选目标供选择

Phase 8.1 核心模块
"""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import json


# ============================================================================
# 枚举和数据结构
# ============================================================================

class GoalCategory(Enum):
    """目标类别"""
    CODE_QUALITY = "code_quality"
    TEST_COVERAGE = "test_coverage"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    PERFORMANCE = "performance"
    SECURITY = "security"
    AUTONOMY = "autonomy"
    LEARNING = "learning"


class GoalStatus(Enum):
    """目标状态"""
    DRAFT = "draft"           # 草稿
    PROPOSED = "proposed"     # 已提出
    APPROVED = "approved"      # 已批准
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class GoalPriority(Enum):
    """目标优先级"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SuccessCriterion:
    """成功标准"""
    description: str
    metric: str
    target_value: Any
    current_value: Optional[Any] = None

    def is_met(self) -> bool:
        """检查是否达成"""
        if self.current_value is None:
            return False
        if isinstance(self.target_value, (int, float)):
            return self.current_value >= self.target_value
        return self.current_value == self.target_value


@dataclass
class EvolutionGoal:
    """
    进化目标

    遵循 SMART 原则：
    - Specific（具体）
    - Measurable（可衡量）
    - Achievable（可实现）
    - Relevant（相关）
    - Time-bound（有时限）
    """
    goal_id: str
    title: str
    description: str
    category: GoalCategory
    priority: GoalPriority
    risk_level: RiskLevel
    estimated_hours: float

    # 目标和范围
    target_files: List[str] = field(default_factory=list)
    target_modules: List[str] = field(default_factory=list)

    # 时间估算置信度
    time_estimate_confidence: float = 0.8

    # 成功标准
    success_criteria: List[SuccessCriterion] = field(default_factory=list)

    # 依赖和前提条件
    dependencies: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)

    # 相关机会
    related_opportunities: List[str] = field(default_factory=list)

    # 状态和元数据
    status: GoalStatus = GoalStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    estimated_completion: Optional[str] = None

    # 效果评估
    expected_impact: float = 0.0
    confidence: float = 0.0

    # 标签和分类
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "priority": self.priority.value,
            "risk_level": self.risk_level.value,
            "target_files": self.target_files,
            "target_modules": self.target_modules,
            "estimated_hours": self.estimated_hours,
            "time_estimate_confidence": self.time_estimate_confidence,
            "success_criteria": [
                {
                    "description": c.description,
                    "metric": c.metric,
                    "target_value": c.target_value,
                    "current_value": c.current_value,
                }
                for c in self.success_criteria
            ],
            "dependencies": self.dependencies,
            "prerequisites": self.prerequisites,
            "related_opportunities": self.related_opportunities,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "estimated_completion": self.estimated_completion,
            "expected_impact": self.expected_impact,
            "confidence": self.confidence,
            "tags": self.tags,
        }


@dataclass
class GoalGenerationContext:
    """目标生成上下文"""
    generation: int
    overall_score: float
    strengths: List[str]
    weaknesses: List[str]
    opportunity_scan_result: Optional[Any] = None
    skills_profile: Optional[Dict] = None
    time_budget_hours: float = 8.0
    constraints: List[str] = field(default_factory=list)


# ============================================================================
# 目标生成器
# ============================================================================

class GoalGenerator:
    """
    目标生成器

    功能：
    - 基于机会扫描生成改进目标
    - 基于能力短板生成提升目标
    - 评估和排序目标
    - 生成 SMART 目标
    """

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = Path(project_root) if project_root else Path(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._goal_counter = 0
        self._goals: Dict[str, EvolutionGoal] = {}
        self._goal_templates = self._load_goal_templates()

    def generate_goals_from_opportunities(
        self,
        opportunities: List[Any],
        context: GoalGenerationContext,
    ) -> List[EvolutionGoal]:
        """
        基于改进机会生成目标

        Args:
            opportunities: 改进机会列表
            context: 生成上下文

        Returns:
            生成的目标列表
        """
        goals = []

        # 按类别分组机会
        by_category = {}
        for opp in opportunities:
            cat = getattr(opp, 'category', 'unknown')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(opp)

        # 为每个类别生成目标
        for category, category_opps in by_category.items():
            category_goal = self._create_goal_from_category(
                category, category_opps, context
            )
            if category_goal:
                goals.append(category_goal)

        # 按优先级排序
        goals = sorted(goals, key=lambda g: (
            g.priority.value,
            -g.expected_impact,
            -g.confidence,
        ))

        # 存储目标
        for goal in goals:
            self._goals[goal.goal_id] = goal

        return goals

    def generate_smart_goal(
        self,
        title: str,
        description: str,
        category: GoalCategory,
        target_files: List[str],
        success_criteria: List[Dict],
        estimated_hours: float = 4.0,
    ) -> EvolutionGoal:
        """
        生成符合 SMART 原则的目标

        Args:
            title: 目标标题
            description: 目标描述
            category: 目标类别
            target_files: 目标文件列表
            success_criteria: 成功标准
            estimated_hours: 预计小时数

        Returns:
            EvolutionGoal: 生成的目标
        """
        self._goal_counter += 1
        goal_id = f"goal_{self._goal_counter:03d}"

        criteria = []
        for sc in success_criteria:
            criteria.append(SuccessCriterion(
                description=sc["description"],
                metric=sc["metric"],
                target_value=sc["target_value"],
                current_value=sc.get("current_value"),
            ))

        # 根据类别设置优先级
        priority = self._estimate_priority(category, target_files)
        risk = self._estimate_risk(target_files)

        return EvolutionGoal(
            goal_id=goal_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            risk_level=risk,
            estimated_hours=estimated_hours,
            target_files=target_files,
            success_criteria=criteria,
            status=GoalStatus.DRAFT,
        )

    def _create_goal_from_category(
        self,
        category: str,
        opportunities: List[Any],
        context: GoalGenerationContext,
    ) -> Optional[EvolutionGoal]:
        """根据类别创建目标"""
        if not opportunities:
            return None

        self._goal_counter += 1
        goal_id = f"goal_{self._goal_counter:03d}"

        # 收集信息
        total_impact = sum(getattr(o, 'impact_score', 5.0) for o in opportunities)
        avg_confidence = sum(getattr(o, 'confidence', 0.7) for o in opportunities) / len(opportunities)
        total_effort = sum(getattr(o, 'estimated_effort_hours', 2.0) for o in opportunities)
        files = list(set(getattr(o, 'file_path', None) for o in opportunities if getattr(o, 'file_path', None)))

        # 确定类别
        try:
            goal_category = GoalCategory(category)
        except ValueError:
            goal_category = GoalCategory.CODE_QUALITY

        # 设置优先级
        priority = self._estimate_priority(goal_category, files)
        risk = self._estimate_risk(files)

        # 生成标题和描述
        title_map = {
            "code_quality": "提升代码质量",
            "test_coverage": "提高测试覆盖率",
            "architecture": "优化系统架构",
            "documentation": "完善文档",
            "performance": "提升性能",
            "security": "增强安全性",
        }
        title = title_map.get(category, f"改进 {category}")

        # 生成成功标准
        criteria = self._generate_criteria(category, opportunities)

        goal = EvolutionGoal(
            goal_id=goal_id,
            title=title,
            description=f"基于 {len(opportunities)} 个改进机会制定的 {title} 目标",
            category=goal_category,
            priority=priority,
            risk_level=risk,
            estimated_hours=min(total_effort, context.time_budget_hours),
            target_files=files[:10],
            success_criteria=criteria,
            related_opportunities=[getattr(o, 'opportunity_id', f'opp_{i}') for i, o in enumerate(opportunities)],
            expected_impact=total_impact / len(opportunities),
            confidence=avg_confidence,
            status=GoalStatus.PROPOSED,
        )

        return goal

    def _generate_criteria(
        self,
        category: str,
        opportunities: List[Any],
    ) -> List[SuccessCriterion]:
        """生成成功标准"""
        criteria = []

        if category == "code_quality":
            criteria.append(SuccessCriterion(
                description="代码圈复杂度降低",
                metric="avg_cyclomatic_complexity",
                target_value=10,
            ))
            criteria.append(SuccessCriterion(
                description="消除高复杂度函数 (>20)",
                metric="high_complexity_functions",
                target_value=0,
            ))

        elif category == "test_coverage":
            criteria.append(SuccessCriterion(
                description="测试覆盖率提升",
                metric="test_coverage_percentage",
                target_value=80,
            ))

        elif category == "architecture":
            criteria.append(SuccessCriterion(
                description="减少核心模块耦合",
                metric="avg_coupling",
                target_value=5,
            ))

        elif category == "documentation":
            criteria.append(SuccessCriterion(
                description="文档覆盖率提升",
                metric="doc_coverage_percentage",
                target_value=90,
            ))

        return criteria

    def _estimate_priority(
        self,
        category: GoalCategory,
        target_files: List[str],
    ) -> GoalPriority:
        """估算优先级"""
        high_priority_patterns = [
            "agent.py", "core/agent", "core/evolution",
        ]

        # 检查是否是高优先级文件
        for pattern in high_priority_patterns:
            if any(pattern in f for f in target_files):
                return GoalPriority.HIGH

        # 根据类别确定优先级
        category_priority = {
            GoalCategory.SECURITY: GoalPriority.CRITICAL,
            GoalCategory.CODE_QUALITY: GoalPriority.HIGH,
            GoalCategory.ARCHITECTURE: GoalPriority.HIGH,
            GoalCategory.TEST_COVERAGE: GoalPriority.MEDIUM,
            GoalCategory.PERFORMANCE: GoalPriority.MEDIUM,
            GoalCategory.DOCUMENTATION: GoalPriority.LOW,
            GoalCategory.AUTONOMY: GoalPriority.MEDIUM,
            GoalCategory.LEARNING: GoalPriority.MEDIUM,
        }

        return category_priority.get(category, GoalPriority.MEDIUM)

    def _estimate_risk(self, target_files: List[str]) -> RiskLevel:
        """估算风险"""
        critical_patterns = [
            "agent.py", "core/security", "config",
        ]

        for pattern in critical_patterns:
            if any(pattern in f for f in target_files):
                return RiskLevel.HIGH

        return RiskLevel.MEDIUM

    def _load_goal_templates(self) -> Dict[str, Dict]:
        """加载目标模板"""
        return {
            "code_quality": {
                "title": "代码质量提升计划",
                "description": "通过重构和分析提升代码质量",
                "typical_hours": 8.0,
            },
            "test_coverage": {
                "title": "测试覆盖率提升计划",
                "description": "为关键模块添加测试",
                "typical_hours": 6.0,
            },
            "architecture": {
                "title": "架构优化计划",
                "description": "改进系统架构和模块划分",
                "typical_hours": 16.0,
            },
        }

    def validate_goal(self, goal: EvolutionGoal) -> Tuple[bool, List[str]]:
        """
        验证目标是否符合 SMART 原则

        Returns:
            (is_valid, issues): 是否有效及问题列表
        """
        issues = []

        # 检查标题
        if not goal.title or len(goal.title) < 5:
            issues.append("标题太短")

        # 检查描述
        if not goal.description or len(goal.description) < 20:
            issues.append("描述太短，需要更详细的说明")

        # 检查成功标准
        if not goal.success_criteria:
            issues.append("缺少成功标准")

        # 检查时间估算
        if goal.estimated_hours <= 0:
            issues.append("需要提供时间估算")

        # 检查置信度
        if goal.confidence <= 0:
            issues.append("需要评估目标置信度")

        return len(issues) == 0, issues

    def prioritize_goals(
        self,
        goals: List[EvolutionGoal],
        context: GoalGenerationContext,
    ) -> List[EvolutionGoal]:
        """
        对目标进行优先级排序

        考虑因素：
        - 优先级
        - 预期影响
        - 置信度
        - 时间成本
        - 依赖关系
        """
        if not goals:
            return goals

        def score_goal(goal: EvolutionGoal) -> float:
            # 基础分
            base_score = 100

            # 优先级调整
            priority_bonus = (5 - goal.priority.value) * 10
            base_score += priority_bonus

            # 影响调整
            impact_bonus = goal.expected_impact * 2
            base_score += impact_bonus

            # 置信度调整
            confidence_bonus = goal.confidence * 20
            base_score += confidence_bonus

            # 时间效率调整（小时产出比）
            if goal.estimated_hours > 0:
                efficiency = goal.expected_impact / goal.estimated_hours
                base_score += efficiency * 5

            # 风险惩罚
            risk_penalty = {"low": 0, "medium": 5, "high": 15, "critical": 30}.get(
                goal.risk_level.value, 10
            )
            base_score -= risk_penalty

            return base_score

        return sorted(goals, key=score_goal, reverse=True)

    def get_goal(self, goal_id: str) -> Optional[EvolutionGoal]:
        """获取目标"""
        return self._goals.get(goal_id)

    def update_goal_status(
        self,
        goal_id: str,
        status: GoalStatus,
    ) -> bool:
        """更新目标状态"""
        if goal_id in self._goals:
            self._goals[goal_id].status = status
            self._goals[goal_id].updated_at = datetime.now().isoformat()
            return True
        return False

    def get_all_goals(
        self,
        status: Optional[GoalStatus] = None,
    ) -> List[EvolutionGoal]:
        """获取所有目标"""
        goals = list(self._goals.values())
        if status:
            goals = [g for g in goals if g.status == status]
        return goals


# ============================================================================
# 单例和工具函数
# ============================================================================

_goal_generator_instance: Optional[GoalGenerator] = None


def get_goal_generator(project_root: Optional[str] = None) -> GoalGenerator:
    """获取目标生成器单例"""
    global _goal_generator_instance

    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if _goal_generator_instance is None:
        _goal_generator_instance = GoalGenerator(project_root)

    return _goal_generator_instance


def reset_goal_generator() -> None:
    """重置目标生成器单例"""
    global _goal_generator_instance
    _goal_generator_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def generate_goals(
    opportunities: List[Any],
    generation: int = 1,
    overall_score: float = 0.5,
) -> List[EvolutionGoal]:
    """
    快捷函数：基于机会生成目标

    Args:
        opportunities: 改进机会列表
        generation: 当前世代
        overall_score: 总体评分

    Returns:
        生成的目标列表
    """
    context = GoalGenerationContext(
        generation=generation,
        overall_score=overall_score,
        strengths=["有完整的模块化架构"],
        weaknesses=["部分模块缺少测试"],
    )

    generator = get_goal_generator()
    return generator.generate_goals_from_opportunities(opportunities, context)
