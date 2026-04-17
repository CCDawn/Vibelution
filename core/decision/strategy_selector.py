#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略选择器 (StrategySelector) - 智能策略选择和切换

Phase 6 核心模块

功能：
- 多策略管理
- 策略效果评估
- 自动策略切换
- 策略回退机制
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum


# ============================================================================
# 策略定义
# ============================================================================

class StrategyType(Enum):
    """策略类型"""
    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"


@dataclass
class Strategy:
    """策略"""
    strategy_id: str
    name: str
    strategy_type: StrategyType
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    success_rate: float = 0.0
    usage_count: int = 0
    last_used: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class StrategyResult:
    """策略执行结果"""
    strategy_id: str
    success: bool
    outcome: Any
    metrics: Dict[str, float] = field(default_factory=dict)
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StrategySelection:
    """策略选择结果"""
    selected_strategy: Strategy
    alternatives: List[Strategy]
    confidence: float
    reasoning: str


# ============================================================================
# 策略选择器
# ============================================================================

class StrategySelector:
    """
    策略选择器

    智能选择和管理策略：

    选择流程：
    1. 评估当前状态
    2. 收集可用策略
    3. 计算策略得分
    4. 选择最佳策略
    5. 监控执行效果
    6. 必要时切换策略

    使用方式：
        selector = StrategySelector()
        selector.add_strategy(strategy)
        selection = selector.select(context)
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化策略选择器

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 策略存储
        self._strategies: Dict[str, Strategy] = {}
        self._results: List[StrategyResult] = []

        # 配置
        self._config = {
            "switch_threshold": 0.3,
            "exploration_rate": 0.2,
            "min_success_rate": 0.3,
            "result_window": 50,
        }

        # 统计
        self._stats = {
            "selections_made": 0,
            "switches_made": 0,
            "strategy_usage": defaultdict(int),
        }

        # 加载数据
        self._load_data()

    # =========================================================================
    # 策略管理
    # =========================================================================

    def add_strategy(self, strategy: Strategy) -> None:
        """
        添加策略

        Args:
            strategy: 策略对象
        """
        self._strategies[strategy.strategy_id] = strategy

    def remove_strategy(self, strategy_id: str) -> bool:
        """移除策略"""
        if strategy_id in self._strategies:
            del self._strategies[strategy_id]
            return True
        return False

    def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        """获取策略"""
        return self._strategies.get(strategy_id)

    def list_strategies(
        self,
        strategy_type: Optional[StrategyType] = None,
    ) -> List[Strategy]:
        """列出策略"""
        if strategy_type:
            return [
                s for s in self._strategies.values()
                if s.strategy_type == strategy_type
            ]
        return list(self._strategies.values())

    # =========================================================================
    # 策略选择
    # =========================================================================

    def select(
        self,
        context: Dict[str, Any],
        forced_type: Optional[StrategyType] = None,
    ) -> StrategySelection:
        """
        选择最佳策略

        Args:
            context: 上下文信息
            forced_type: 强制策略类型

        Returns:
            策略选择结果
        """
        # 获取候选策略
        candidates = self._get_candidates(forced_type)

        if not candidates:
            return self._create_default_selection(context)

        # 计算每个策略的得分
        scored = []
        for strategy in candidates:
            score = self._calculate_strategy_score(strategy, context)
            scored.append((strategy, score))

        # 按得分排序
        scored.sort(key=lambda x: x[1], reverse=True)

        # 选择最佳策略
        best_strategy, best_score = scored[0]

        # 获取备选策略
        alternatives = [s for s, _ in scored[1:3]]

        # 计算置信度
        confidence = self._calculate_confidence(scored, best_score)

        # 生成推理说明
        reasoning = self._generate_reasoning(best_strategy, scored, context)

        self._stats["selections_made"] += 1
        self._stats["strategy_usage"][best_strategy.strategy_id] += 1

        return StrategySelection(
            selected_strategy=best_strategy,
            alternatives=alternatives,
            confidence=confidence,
            reasoning=reasoning,
        )

    def _get_candidates(
        self,
        forced_type: Optional[StrategyType],
    ) -> List[Strategy]:
        """获取候选策略"""
        candidates = list(self._strategies.values())

        if forced_type:
            candidates = [
                s for s in candidates if s.strategy_type == forced_type
            ]

        # 过滤成功率过低的策略
        min_rate = self._config["min_success_rate"]
        candidates = [
            s for s in candidates
            if s.usage_count == 0 or s.success_rate >= min_rate
        ]

        return candidates

    def _calculate_strategy_score(
        self,
        strategy: Strategy,
        context: Dict[str, Any],
    ) -> float:
        """计算策略得分"""
        score = 0.0

        # 成功率 (40%)
        score += strategy.success_rate * 0.4

        # 近期使用情况 (20%)
        if strategy.last_used:
            days_since = (datetime.now() - strategy.last_used).days
            if days_since < 7:
                score += 0.15
            elif days_since < 30:
                score += 0.05

        # 策略类型匹配 (20%)
        task_type = context.get("task_type", "default")
        if strategy.parameters.get("preferred_tasks"):
            if task_type in strategy.parameters["preferred_tasks"]:
                score += 0.2

        # 探索奖励 (20%)
        exploration_mode = context.get("exploration_mode", False)
        if exploration_mode and strategy.strategy_type == StrategyType.EXPLORATION:
            score += 0.2

        return score

    def _calculate_confidence(
        self,
        scored: List[tuple],
        best_score: float,
    ) -> float:
        """计算选择置信度"""
        if len(scored) < 2:
            return 0.9

        # 第二名得分
        second_score = scored[1][1]

        # 差距越大，置信度越高
        gap = best_score - second_score

        confidence = min(0.5 + gap, 1.0)
        return confidence

    def _generate_reasoning(
        self,
        strategy: Strategy,
        scored: List[tuple],
        context: Dict[str, Any],
    ) -> str:
        """生成推理说明"""
        reasons = []

        if strategy.success_rate > 0.7:
            reasons.append(f"高成功率 ({strategy.success_rate:.0%})")

        if strategy.usage_count > 10:
            reasons.append("经过多次验证")

        if strategy.strategy_type == StrategyType.EXPLORATION:
            reasons.append("适合探索模式")

        return f"选择 '{strategy.name}' 因为: {', '.join(reasons) if reasons else '无明显原因'}"

    def _create_default_selection(
        self,
        context: Dict[str, Any],
    ) -> StrategySelection:
        """创建默认选择"""
        default_strategy = Strategy(
            strategy_id="default",
            name="默认策略",
            strategy_type=StrategyType.BALANCED,
            description="当没有可用策略时的默认选择",
        )

        return StrategySelection(
            selected_strategy=default_strategy,
            alternatives=[],
            confidence=0.0,
            reasoning="没有匹配的策略，使用默认策略",
        )

    # =========================================================================
    # 策略切换
    # =========================================================================

    def should_switch(
        self,
        current_strategy_id: str,
        recent_results: List[StrategyResult],
        threshold: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        判断是否应该切换策略

        Args:
            current_strategy_id: 当前策略 ID
            recent_results: 最近结果
            threshold: 切换阈值

        Returns:
            (是否切换, 建议的新策略)
        """
        if threshold is None:
            threshold = self._config["switch_threshold"]

        if not recent_results:
            return False, None

        # 计算当前策略成功率
        current_results = [
            r for r in recent_results
            if r.strategy_id == current_strategy_id
        ]

        if len(current_results) < 3:
            return False, None

        current_rate = sum(1 for r in current_results if r.success) / len(current_results)

        # 成功率过低，考虑切换
        if current_rate < threshold:
            # 寻找更好的策略
            strategy_rates = defaultdict(lambda: {"success": 0, "total": 0})

            for r in recent_results:
                strategy_rates[r.strategy_id]["total"] += 1
                if r.success:
                    strategy_rates[r.strategy_id]["success"] += 1

            best_id = None
            best_rate = 0

            for sid, rates in strategy_rates.items():
                if sid == current_strategy_id:
                    continue
                rate = rates["success"] / rates["total"] if rates["total"] > 0 else 0
                if rate > best_rate and rate > current_rate:
                    best_rate = rate
                    best_id = sid

            if best_id:
                self._stats["switches_made"] += 1
                return True, best_id

        return False, None

    # =========================================================================
    # 结果记录
    # =========================================================================

    def record_result(self, result: StrategyResult) -> None:
        """
        记录策略执行结果

        Args:
            result: 执行结果
        """
        self._results.append(result)

        # 更新策略成功率
        strategy = self._strategies.get(result.strategy_id)
        if strategy:
            strategy.usage_count += 1
            old_rate = strategy.success_rate

            if result.success:
                strategy.success_rate = (
                    old_rate * (strategy.usage_count - 1) + 1.0
                ) / strategy.usage_count
            else:
                strategy.success_rate = (
                    old_rate * (strategy.usage_count - 1)
                ) / strategy.usage_count

            strategy.last_used = result.timestamp

        # 限制历史大小
        if len(self._results) > self._config["result_window"] * 10:
            self._results = self._results[-self._config["result_window"] * 5:]

        self._save_data()

    def get_recent_results(self, limit: int = 50) -> List[StrategyResult]:
        """获取最近结果"""
        return self._results[-limit:]

    def get_strategy_performance(
        self,
        strategy_id: str,
    ) -> Dict[str, Any]:
        """获取策略性能"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return {}

        results = [r for r in self._results if r.strategy_id == strategy_id]

        return {
            "strategy_id": strategy_id,
            "name": strategy.name,
            "success_rate": strategy.success_rate,
            "usage_count": strategy.usage_count,
            "total_results": len(results),
            "last_used": strategy.last_used.isoformat() if strategy.last_used else None,
        }

    # =========================================================================
    # 统计分析
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        strategies_by_type = defaultdict(list)
        for s in self._strategies.values():
            strategies_by_type[s.strategy_type.value].append(s.strategy_id)

        return {
            **self._stats,
            "total_strategies": len(self._strategies),
            "strategies_by_type": {
                k: len(v) for k, v in strategies_by_type.items()
            },
            "recent_results_count": len(self._results[-self._config["result_window"]:]),
        }

    def analyze_performance_trend(
        self,
        window_days: int = 7,
    ) -> Dict[str, Any]:
        """分析性能趋势"""
        cutoff = datetime.now() - timedelta(days=window_days)
        recent = [r for r in self._results if r.timestamp >= cutoff]

        if not recent:
            return {"trend": "insufficient_data"}

        success_count = sum(1 for r in recent if r.success)

        # 按策略分组
        by_strategy = defaultdict(lambda: {"success": 0, "total": 0})
        for r in recent:
            by_strategy[r.strategy_id]["total"] += 1
            if r.success:
                by_strategy[r.strategy_id]["success"] += 1

        # 计算每个策略的趋势
        trends = {}
        for sid, counts in by_strategy.items():
            rate = counts["success"] / counts["total"] if counts["total"] > 0 else 0
            trends[sid] = {
                "success_rate": rate,
                "count": counts["total"],
            }

        return {
            "period_days": window_days,
            "total_actions": len(recent),
            "overall_success_rate": success_count / len(recent),
            "strategy_trends": trends,
        }

    # =========================================================================
    # 持久化
    # =========================================================================

    def _get_data_path(self) -> Path:
        """获取数据文件路径"""
        data_dir = self.project_root / "workspace" / "strategy"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "strategy_data.json"

    def _load_data(self) -> None:
        """加载数据"""
        data_path = self._get_data_path()
        if not data_path.exists():
            return

        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 加载策略
            self._strategies = {
                s["strategy_id"]: Strategy(
                    strategy_id=s["strategy_id"],
                    name=s["name"],
                    strategy_type=StrategyType(s["strategy_type"]),
                    description=s.get("description", ""),
                    parameters=s.get("parameters", {}),
                    success_rate=s.get("success_rate", 0.0),
                    usage_count=s.get("usage_count", 0),
                    last_used=(
                        datetime.fromisoformat(s["last_used"])
                        if s.get("last_used") else None
                    ),
                    created_at=(
                        datetime.fromisoformat(s["created_at"])
                        if s.get("created_at") else datetime.now()
                    ),
                )
                for s in data.get("strategies", [])
            }

            self._stats = data.get("stats", self._stats)
            # 确保 strategy_usage 是 defaultdict
            if "strategy_usage" not in self._stats or not isinstance(self._stats["strategy_usage"], defaultdict):
                self._stats["strategy_usage"] = defaultdict(int, self._stats.get("strategy_usage", {}))

        except Exception:
            pass

    def _save_data(self) -> None:
        """保存数据"""
        data_path = self._get_data_path()

        data = {
            "strategies": [
                {
                    "strategy_id": s.strategy_id,
                    "name": s.name,
                    "strategy_type": s.strategy_type.value,
                    "description": s.description,
                    "parameters": s.parameters,
                    "success_rate": s.success_rate,
                    "usage_count": s.usage_count,
                    "last_used": s.last_used.isoformat() if s.last_used else None,
                    "created_at": s.created_at.isoformat(),
                }
                for s in self._strategies.values()
            ],
            "stats": dict(self._stats),
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================================
# 预设策略
# ============================================================================

DEFAULT_STRATEGIES = [
    Strategy(
        strategy_id="explore_exploit",
        name="探索-利用平衡",
        strategy_type=StrategyType.BALANCED,
        description="在探索新方法和利用已知方法之间平衡",
        parameters={"exploration_rate": 0.3},
    ),
    Strategy(
        strategy_id="aggressive_explore",
        name="激进探索",
        strategy_type=StrategyType.AGGRESSIVE,
        description="优先尝试新方法，快速学习",
        parameters={"preferred_tasks": ["research", "analysis"]},
    ),
    Strategy(
        strategy_id="conservative_exploit",
        name="保守利用",
        strategy_type=StrategyType.CONSERVATIVE,
        description="使用已知有效的方法，稳健完成任务",
        parameters={"min_confidence": 0.8},
    ),
]


def create_default_selector() -> StrategySelector:
    """创建默认策略选择器"""
    selector = StrategySelector()
    for strategy in DEFAULT_STRATEGIES:
        selector.add_strategy(strategy)
    return selector


# ============================================================================
# 全局单例
# ============================================================================

_strategy_selector: Optional[StrategySelector] = None


def get_strategy_selector(project_root: Optional[str] = None) -> StrategySelector:
    """获取策略选择器单例"""
    global _strategy_selector
    if _strategy_selector is None:
        _strategy_selector = StrategySelector(project_root)
    return _strategy_selector


def reset_strategy_selector() -> None:
    """重置策略选择器"""
    global _strategy_selector
    _strategy_selector = None