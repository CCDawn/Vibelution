#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自主探索引擎 (AutonomousExplorer) - Phase 8 自主探索核心模块

负责：
- 协调探索流程
- 在无任务时主动发现问题
- 管理探索会话
- 与 Agent 集成执行改进

Phase 8.1 核心模块
"""

from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock


# ============================================================================
# 枚举和配置
# ============================================================================

class ExplorationState(Enum):
    """探索状态"""
    IDLE = "idle"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PAUSED = "paused"


class ExplorationTrigger(Enum):
    """探索触发条件"""
    MANUAL = "manual"           # 手动触发
    SCHEDULED = "scheduled"     # 定时触发
    IDLE_DETECTED = "idle"      # 空闲检测
    ERROR_RECOVERY = "recovery"  # 错误恢复
    USER_REQUEST = "user"        # 用户请求


@dataclass
class ExplorationConfig:
    """探索配置"""
    # 扫描配置
    scan_interval_hours: float = 24.0  # 扫描间隔（小时）
    max_opportunities_per_scan: int = 20  # 每次扫描最多发现的机会数
    scan_on_startup: bool = True

    # 执行配置
    max_exploration_time_minutes: int = 30  # 最大探索时间
    max_explorations_per_session: int = 3  # 每次会话最大探索轮次
    require_confirmation: bool = True  # 执行前需要确认

    # 阈值配置
    min_opportunity_impact: float = 5.0  # 最小机会影响分数
    min_opportunity_confidence: float = 0.7  # 最小置信度

    # 过滤配置
    exclude_paths: List[str] = field(default_factory=lambda: [
        '__pycache__', '.pytest_cache', 'venv', '.git',
        'backups', 'temp', 'workspace/logs',
    ])


@dataclass
class ExplorationSession:
    """探索会话"""
    session_id: str
    started_at: str
    trigger: ExplorationTrigger
    state: ExplorationState
    scan_result: Optional[Any] = None
    goals_generated: List[str] = field(default_factory=list)  # goal_ids
    goals_executed: List[str] = field(default_factory=list)
    opportunities_found: int = 0
    errors: List[str] = field(default_factory=list)
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "trigger": self.trigger.value,
            "state": self.state.value,
            "goals_generated": self.goals_generated,
            "goals_executed": self.goals_executed,
            "opportunities_found": self.opportunities_found,
            "errors": self.errors,
            "completed_at": self.completed_at,
        }


@dataclass
class ExplorationResult:
    """探索结果"""
    session: ExplorationSession
    opportunities: List[Any]
    goals: List[Any]
    recommendations: List[str]
    statistics: Dict[str, Any]

    def get_summary(self) -> str:
        """获取摘要"""
        lines = [
            f"探索会话: {self.session.session_id}",
            f"发现机会: {len(self.opportunities)}",
            f"生成目标: {len(self.goals)}",
            f"推荐行动: {len(self.recommendations)}",
        ]
        return "\n".join(lines)


# ============================================================================
# 回调类型定义
# ============================================================================

ProgressCallback = Callable[[str, float], None]  # (message, progress)
GoalCallback = Callable[[str, Any], None]  # (goal_id, goal)


# ============================================================================
# 自主探索引擎
# ============================================================================

class AutonomousExplorer:
    """
    自主探索引擎 - Phase 8 核心

    功能：
    - 主动扫描代码库发现改进机会
    - 生成进化目标
    - 管理探索会话
    - 与 Agent 集成执行改进

    使用流程：
    1. 创建实例并配置
    2. 调用 explore() 开始探索
    3. 处理探索结果
    4. 可选：调用 execute_goal() 执行目标
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        config: Optional[ExplorationConfig] = None,
    ):
        """
        初始化自主探索引擎

        Args:
            project_root: 项目根目录
            config: 探索配置
        """
        self.project_root = Path(project_root) if project_root else Path(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.config = config or ExplorationConfig()
        self.logger = logging.getLogger(f"{__name__}.AutonomousExplorer")

        # 状态
        self._state = ExplorationState.IDLE
        self._current_session: Optional[ExplorationSession] = None
        self._lock = Lock()

        # 组件
        self._opportunity_finder = None
        self._goal_generator = None

        # 会话历史
        self._sessions: List[ExplorationSession] = []

        # 回调
        self._progress_callback: Optional[ProgressCallback] = None
        self._goal_callback: Optional[GoalCallback] = None

        # 统计
        self._total_scans = 0
        self._total_opportunities = 0

    # ==================== 核心方法 ====================

    def explore(
        self,
        trigger: ExplorationTrigger = ExplorationTrigger.MANUAL,
        force: bool = False,
    ) -> ExplorationResult:
        """
        执行完整探索流程

        Args:
            trigger: 探索触发条件
            force: 是否强制执行（忽略检查）

        Returns:
            ExplorationResult: 探索结果
        """
        with self._lock:
            if self._state not in (ExplorationState.IDLE, ExplorationState.COMPLETED):
                self.logger.warning(f"探索已在进行中: {self._state}")
                return self._create_empty_result("探索已在进行中")

            self._state = ExplorationState.SCANNING

        self.logger.info(f"开始探索，触发条件: {trigger.value}")

        # 创建会话
        session = ExplorationSession(
            session_id=self._generate_session_id(),
            started_at=datetime.now().isoformat(),
            trigger=trigger,
            state=ExplorationState.SCANNING,
        )
        self._current_session = session

        try:
            # 步骤 1: 扫描
            self._update_progress("正在扫描代码库...", 0.1)
            scan_result = self._scan_opportunities()

            # 步骤 2: 分析
            self._update_progress("正在分析结果...", 0.3)
            opportunities = self._filter_opportunities(scan_result)
            session.opportunities_found = len(opportunities)

            # 步骤 3: 生成目标
            self._update_progress("正在生成目标...", 0.5)
            goals = self._generate_goals(opportunities)
            session.goals_generated = [g.goal_id for g in goals]

            # 步骤 4: 评估
            self._update_progress("正在评估...", 0.7)
            recommendations = self._generate_recommendations(opportunities, goals)

            # 完成
            session.state = ExplorationState.COMPLETED
            session.completed_at = datetime.now().isoformat()
            self._state = ExplorationState.COMPLETED
            self._update_progress("探索完成", 1.0)

            self._total_scans += 1
            self._total_opportunities += len(opportunities)

            result = ExplorationResult(
                session=session,
                opportunities=opportunities,
                goals=goals,
                recommendations=recommendations,
                statistics=self._get_statistics(),
            )

            self._sessions.append(session)
            return result

        except Exception as e:
            session.state = ExplorationState.IDLE
            session.errors.append(str(e))
            self.logger.error(f"探索失败: {e}")
            self._state = ExplorationState.IDLE
            return self._create_empty_result(str(e))

    def quick_scan(self) -> List[Any]:
        """
        快速扫描（不生成目标）

        Returns:
            发现的改进机会列表
        """
        self._ensure_finders()
        scan_result = self._opportunity_finder.scan()
        return self._filter_opportunities(scan_result)

    def get_status(self) -> Dict[str, Any]:
        """获取探索器状态"""
        return {
            "state": self._state.value,
            "current_session": self._current_session.session_id if self._current_session else None,
            "total_scans": self._total_scans,
            "total_opportunities": self._total_opportunities,
            "recent_sessions": len(self._sessions),
            "config": {
                "scan_interval_hours": self.config.scan_interval_hours,
                "max_opportunities_per_scan": self.config.max_opportunities_per_scan,
            },
        }

    # ==================== 辅助方法 ====================

    def _ensure_finders(self):
        """确保查找器已初始化"""
        if self._opportunity_finder is None:
            from core.autonomous.opportunity_finder import get_opportunity_finder
            self._opportunity_finder = get_opportunity_finder(str(self.project_root))

        if self._goal_generator is None:
            from core.autonomous.goal_generator import get_goal_generator, GoalGenerationContext
            self._goal_generator = get_goal_generator(str(self.project_root))

    def _scan_opportunities(self):
        """扫描改进机会"""
        self._ensure_finders()
        return self._opportunity_finder.scan()

    def _filter_opportunities(self, scan_result) -> List[Any]:
        """过滤机会"""
        opportunities = []

        for opp in scan_result.opportunities:
            # 检查影响分数
            if opp.impact_score < self.config.min_opportunity_impact:
                continue

            # 检查置信度
            if opp.confidence < self.config.min_opportunity_confidence:
                continue

            opportunities.append(opp)

            # 限制数量
            if len(opportunities) >= self.config.max_opportunities_per_scan:
                break

        return opportunities

    def _generate_goals(self, opportunities: List[Any]) -> List[Any]:
        """生成目标"""
        self._ensure_finders()

        context = self._create_goal_context()
        goals = self._goal_generator.generate_goals_from_opportunities(
            opportunities, context
        )

        # 按优先级排序
        goals = self._goal_generator.prioritize_goals(goals, context)

        # 触发目标回调
        if self._goal_callback:
            for goal in goals[:5]:  # 最多通知前 5 个
                self._goal_callback(goal.goal_id, goal)

        return goals

    def _create_goal_context(self):
        """创建目标生成上下文"""
        from core.autonomous.goal_generator import GoalGenerationContext
        from tools.memory_tools import get_generation_tool

        generation = 1
        try:
            generation = get_generation_tool()
        except Exception:
            pass

        return GoalGenerationContext(
            generation=generation,
            overall_score=0.6,
            strengths=["模块化架构良好", "测试覆盖较全"],
            weaknesses=["部分代码复杂度高", "缺少文档"],
            time_budget_hours=8.0,
        )

    def _generate_recommendations(
        self,
        opportunities: List[Any],
        goals: List[Any],
    ) -> List[str]:
        """生成推荐"""
        recommendations = []

        # 基于机会生成推荐
        by_category = {}
        for opp in opportunities:
            cat = opp.category
            if cat not in by_category:
                by_category[cat] = 0
            by_category[cat] += 1

        for category, count in sorted(by_category.items(), key=lambda x: -x[1]):
            recommendations.append(
                f"发现 {count} 个 {category} 相关的改进机会"
            )

        # 基于目标生成推荐
        if goals:
            top_goal = goals[0]
            recommendations.insert(
                0,
                f"建议优先处理: {top_goal.title} (优先级: {top_goal.priority.name})"
            )

        return recommendations

    def _update_progress(self, message: str, progress: float):
        """更新进度"""
        self.logger.info(f"[{progress:.0%}] {message}")
        if self._progress_callback:
            self._progress_callback(message, progress)

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        import hashlib
        timestamp = datetime.now().isoformat()
        return f"exp_{hashlib.md5(timestamp.encode()).hexdigest()[:8]}"

    def _get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_scans": self._total_scans,
            "total_opportunities": self._total_opportunities,
            "recent_sessions": len(self._sessions),
        }

    def _create_empty_result(self, error: str) -> ExplorationResult:
        """创建空结果"""
        session = ExplorationSession(
            session_id=self._generate_session_id(),
            started_at=datetime.now().isoformat(),
            trigger=ExplorationTrigger.MANUAL,
            state=ExplorationState.IDLE,
            errors=[error],
        )
        session.completed_at = datetime.now().isoformat()

        return ExplorationResult(
            session=session,
            opportunities=[],
            goals=[],
            recommendations=[f"错误: {error}"],
            statistics={},
        )

    # ==================== 回调设置 ====================

    def set_progress_callback(self, callback: ProgressCallback):
        """设置进度回调"""
        self._progress_callback = callback

    def set_goal_callback(self, callback: GoalCallback):
        """设置目标回调"""
        self._goal_callback = callback

    # ==================== 会话管理 ====================

    def get_recent_sessions(self, limit: int = 5) -> List[ExplorationSession]:
        """获取最近的探索会话"""
        return self._sessions[-limit:]

    def get_session(self, session_id: str) -> Optional[ExplorationSession]:
        """获取指定会话"""
        for session in self._sessions:
            if session.session_id == session_id:
                return session
        return None


# ============================================================================
# 单例和工具函数
# ============================================================================

_autonomous_explorer_instance: Optional[AutonomousExplorer] = None
_autonomous_explorer_lock = Lock()


def get_autonomous_explorer(
    project_root: Optional[str] = None,
    config: Optional[ExplorationConfig] = None,
) -> AutonomousExplorer:
    """
    获取自主探索引擎单例

    Args:
        project_root: 项目根目录
        config: 探索配置

    Returns:
        AutonomousExplorer 实例
    """
    global _autonomous_explorer_instance

    with _autonomous_explorer_lock:
        if _autonomous_explorer_instance is None:
            _autonomous_explorer_instance = AutonomousExplorer(project_root, config)
        return _autonomous_explorer_instance


def reset_autonomous_explorer() -> None:
    """重置自主探索引擎单例"""
    global _autonomous_explorer_instance

    with _autonomous_explorer_lock:
        _autonomous_explorer_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def explore(
    project_root: Optional[str] = None,
    trigger: ExplorationTrigger = ExplorationTrigger.MANUAL,
) -> ExplorationResult:
    """
    快捷函数：执行探索

    Args:
        project_root: 项目根目录
        trigger: 触发条件

    Returns:
        ExplorationResult: 探索结果
    """
    explorer = get_autonomous_explorer(project_root)
    return explorer.explore(trigger)


def quick_scan_opportunities(project_root: Optional[str] = None) -> List[Any]:
    """
    快捷函数：快速扫描机会

    Args:
        project_root: 项目根目录

    Returns:
        改进机会列表
    """
    explorer = get_autonomous_explorer(project_root)
    return explorer.quick_scan()
