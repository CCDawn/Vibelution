#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略学习器 (Strategy Learner) - Phase 8 核心模块

包含：
- strategy_learner.py - 策略学习机制
- reward_calculator.py - 策略回报计算
- policy_optimizer.py - 策略参数优化

Phase 8.3 模块
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from collections import defaultdict
import statistics


# ============================================================================
# 枚举和数据结构
# ============================================================================

class StrategyType(Enum):
    """策略类型"""
    DIRECT = "direct"                 # 直接执行
    EXPLORATORY = "exploratory"     # 探索性
    CONSERVATIVE = "conservative"    # 保守型
    AGGRESSIVE = "aggressive"        # 激进型
    ADAPTIVE = "adaptive"            # 自适应


class ExecutionOutcome(Enum):
    """执行结果"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class StrategyContext:
    """策略上下文"""
    task_type: str
    task_complexity: float  # 0-10
    time_constraint: float  # 小时
    risk_level: float  # 0-10
    resource_availability: float  # 0-10
    historical_success_rate: float = 0.5
    similar_task_count: int = 0


@dataclass
class StrategyResult:
    """策略执行结果"""
    strategy_id: str
    outcome: ExecutionOutcome
    execution_time: float  # 秒
    quality_score: float  # 0-10
    resource_usage: float  # 资源使用量
    error_message: str = ""


@dataclass
class StrategyReward:
    """策略回报"""
    strategy_id: str
    total_reward: float
    success_component: float  # 成功奖励
    time_component: float  # 时间效率奖励
    quality_component: float  # 质量奖励
    penalty: float = 0.0  # 惩罚项
    details: Dict[str, float] = field(default_factory=dict)


@dataclass
class StrategyPolicy:
    """策略策略（参数）"""
    strategy_id: str
    strategy_type: StrategyType
    weights: Dict[str, float]  # 各因素权重
    thresholds: Dict[str, float]  # 决策阈值
    success_count: int = 0
    failure_count: int = 0
    total_reward: float = 0.0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type.value,
            "weights": self.weights,
            "thresholds": self.thresholds,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_reward": self.total_reward,
            "last_updated": self.last_updated,
        }


# ============================================================================
# 回报计算器
# ============================================================================

class RewardCalculator:
    """
    回报计算器

    计算策略执行的回报值，用于策略优化
    """

    def __init__(
        self,
        success_weight: float = 0.4,
        time_weight: float = 0.2,
        quality_weight: float = 0.3,
        resource_weight: float = 0.1,
    ):
        """
        初始化回报计算器

        Args:
            success_weight: 成功权重
            time_weight: 时间效率权重
            quality_weight: 质量权重
            resource_weight: 资源使用权重
        """
        self.weights = {
            "success": success_weight,
            "time": time_weight,
            "quality": quality_weight,
            "resource": resource_weight,
        }

    def calculate(
        self,
        result: StrategyResult,
        context: StrategyContext,
    ) -> StrategyReward:
        """
        计算策略回报

        Args:
            result: 策略执行结果
            context: 策略上下文

        Returns:
            StrategyReward: 策略回报
        """
        # 1. 成功奖励
        success_reward = self._calculate_success_reward(result, context)

        # 2. 时间效率奖励
        time_reward = self._calculate_time_reward(result, context)

        # 3. 质量奖励
        quality_reward = self._calculate_quality_reward(result)

        # 4. 资源使用惩罚
        resource_penalty = self._calculate_resource_penalty(result, context)

        # 总回报
        total_reward = (
            self.weights["success"] * success_reward +
            self.weights["time"] * time_reward +
            self.weights["quality"] * quality_reward
        ) - resource_penalty

        return StrategyReward(
            strategy_id=result.strategy_id,
            total_reward=total_reward,
            success_component=success_reward,
            time_component=time_reward,
            quality_component=quality_reward,
            penalty=resource_penalty,
            details={
                "success_reward": success_reward,
                "time_reward": time_reward,
                "quality_reward": quality_reward,
                "resource_penalty": resource_penalty,
            },
        )

    def _calculate_success_reward(
        self,
        result: StrategyResult,
        context: StrategyContext,
    ) -> float:
        """计算成功奖励"""
        if result.outcome == ExecutionOutcome.SUCCESS:
            base = 1.0
            # 根据上下文难度调整
            if context.task_complexity > 7:
                base *= 1.2  # 困难任务成功奖励更高
            return base
        elif result.outcome == ExecutionOutcome.PARTIAL:
            return 0.5
        elif result.outcome == ExecutionOutcome.FAILURE:
            return -0.5
        elif result.outcome == ExecutionOutcome.TIMEOUT:
            return -0.3
        else:
            return -1.0

    def _calculate_time_reward(
        self,
        result: StrategyResult,
        context: StrategyContext,
    ) -> float:
        """计算时间效率奖励"""
        if context.time_constraint <= 0:
            return 0.5

        # 计算时间比率
        time_ratio = result.execution_time / (context.time_constraint * 3600)

        if time_ratio <= 0.5:
            return 1.0  # 提前完成
        elif time_ratio <= 1.0:
            return 0.8  # 按时完成
        elif time_ratio <= 1.5:
            return 0.3  # 稍微超时
        else:
            return -0.5  # 严重超时

    def _calculate_quality_reward(self, result: StrategyResult) -> float:
        """计算质量奖励"""
        # 质量分数已经归一化到 0-10
        return result.quality_score / 10.0

    def _calculate_resource_penalty(
        self,
        result: StrategyResult,
        context: StrategyContext,
    ) -> float:
        """计算资源使用惩罚"""
        if context.resource_availability <= 0:
            return 0.0

        # 资源使用率超过可用资源时惩罚
        usage_ratio = result.resource_usage / context.resource_availability

        if usage_ratio > 1.0:
            return (usage_ratio - 1.0) * 0.5
        return 0.0


# ============================================================================
# 策略优化器
# ============================================================================

class PolicyOptimizer:
    """
    策略优化器

    基于历史数据优化策略参数
    """

    def __init__(
        self,
        learning_rate: float = 0.1,
        exploration_rate: float = 0.2,
    ):
        """
        初始化策略优化器

        Args:
            learning_rate: 学习率
            exploration_rate: 探索概率
        """
        self.learning_rate = learning_rate
        self.exploration_rate = exploration_rate

    def update_policy(
        self,
        policy: StrategyPolicy,
        reward: StrategyReward,
    ) -> StrategyPolicy:
        """
        更新策略

        Args:
            policy: 当前策略
            reward: 获得的回报

        Returns:
            更新后的策略
        """
        # 更新统计
        if reward.success_component > 0:
            policy.success_count += 1
        else:
            policy.failure_count += 1

        policy.total_reward += reward.total_reward
        policy.last_updated = datetime.now().isoformat()

        # 更新权重（简单的强化学习更新）
        reward_normalized = reward.total_reward

        for key in policy.weights:
            if key in reward.details:
                delta = self.learning_rate * reward_normalized * reward.details[key]
                policy.weights[key] = max(0.1, min(1.0, policy.weights[key] + delta))

        # 归一化权重
        total = sum(policy.weights.values())
        if total > 0:
            policy.weights = {k: v / total for k, v in policy.weights.items()}

        return policy

    def should_explore(self, iteration: int) -> bool:
        """
        决定是否探索

        Args:
            iteration: 当前迭代次数

        Returns:
            是否应该探索
        """
        # 探索概率随时间衰减
        decay = 1.0 / (1.0 + iteration * 0.01)
        current_rate = self.exploration_rate * decay
        import random
        return random.random() < current_rate

    def suggest_weight_adjustment(
        self,
        policy: StrategyPolicy,
        outcome: ExecutionOutcome,
    ) -> Dict[str, float]:
        """
        建议权重调整

        Args:
            policy: 当前策略
            outcome: 执行结果

        Returns:
            建议的权重调整
        """
        adjustments = {}

        if outcome == ExecutionOutcome.SUCCESS:
            # 成功时略微增加权重
            for key in policy.weights:
                adjustments[key] = 0.05
        elif outcome == ExecutionOutcome.PARTIAL:
            # 部分成功时保持不变
            for key in policy.weights:
                adjustments[key] = 0.0
        elif outcome == ExecutionOutcome.FAILURE:
            # 失败时检查各因素贡献
            if policy.weights.get("time", 0) > 0.3:
                adjustments["time"] = -0.1
            if policy.weights.get("quality", 0) < 0.3:
                adjustments["quality"] = 0.1
        else:
            # 严重失败时大范围调整
            for key in policy.weights:
                adjustments[key] = -0.1

        return adjustments


# ============================================================================
# 策略学习器
# ============================================================================

class StrategyLearner:
    """
    策略学习器

    功能：
    - 追踪策略执行历史
    - 计算策略回报
    - 优化策略参数
    - 选择最佳策略
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        learning_rate: float = 0.1,
        exploration_rate: float = 0.2,
    ):
        """
        初始化策略学习器

        Args:
            project_root: 项目根目录
            learning_rate: 学习率
            exploration_rate: 探索概率
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.project_root = Path(project_root)
        self.storage_path = self.project_root / "workspace" / "strategy" / "learner_data.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.reward_calculator = RewardCalculator()
        self.policy_optimizer = PolicyOptimizer(learning_rate, exploration_rate)

        self._policies: Dict[str, StrategyPolicy] = {}
        self._history: List[Tuple[StrategyContext, StrategyResult, StrategyReward]] = []
        self._iteration = 0

        self._load()

    def select_strategy(
        self,
        context: StrategyContext,
        available_strategies: List[StrategyType],
    ) -> Tuple[StrategyType, bool]:
        """
        选择策略

        Args:
            context: 策略上下文
            available_strategies: 可用策略列表

        Returns:
            (选择的策略, 是否是探索)
        """
        self._iteration += 1

        # 探索模式
        if self.policy_optimizer.should_explore(self._iteration):
            import random
            chosen = random.choice(available_strategies)
            return chosen, True

        # 利用模式：选择预期回报最高的策略
        best_strategy = None
        best_score = float('-inf')

        for strategy_type in available_strategies:
            policy = self._get_or_create_policy(strategy_type)
            score = self._estimate_policy_score(policy, context)

            if score > best_score:
                best_score = score
                best_strategy = strategy_type

        if best_strategy is None:
            best_strategy = available_strategies[0]

        return best_strategy, False

    def record_execution(
        self,
        context: StrategyContext,
        result: StrategyResult,
    ) -> StrategyReward:
        """
        记录策略执行

        Args:
            context: 策略上下文
            result: 执行结果

        Returns:
            计算的回报
        """
        # 计算回报
        reward = self.reward_calculator.calculate(result, context)

        # 记录历史
        self._history.append((context, result, reward))

        # 更新策略
        policy = self._get_or_create_policy(
            self._infer_strategy_type(result.strategy_id)
        )
        self.policy_optimizer.update_policy(policy, reward)

        # 保存
        self._save()

        return reward

    def get_policy(self, strategy_type: StrategyType) -> Optional[StrategyPolicy]:
        """获取策略"""
        strategy_id = strategy_type.value
        return self._policies.get(strategy_id)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_executions = len(self._history)
        successful = sum(
            1 for _, r, _ in self._history
            if r.outcome == ExecutionOutcome.SUCCESS
        )

        avg_reward = statistics.mean([rew.total_reward for _, _, rew in self._history]) if self._history else 0.0

        return {
            "total_executions": total_executions,
            "successful_executions": successful,
            "success_rate": successful / total_executions if total_executions > 0 else 0.0,
            "average_reward": avg_reward,
            "policies_count": len(self._policies),
            "current_iteration": self._iteration,
            "policy_stats": {
                pid: {
                    "success_rate": p.success_rate,
                    "total_reward": p.total_reward,
                }
                for pid, p in self._policies.items()
            },
        }

    def _get_or_create_policy(self, strategy_type: StrategyType) -> StrategyPolicy:
        """获取或创建策略"""
        strategy_id = strategy_type.value

        if strategy_id not in self._policies:
            self._policies[strategy_id] = StrategyPolicy(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                weights=self._get_default_weights(strategy_type),
                thresholds=self._get_default_thresholds(strategy_type),
            )

        return self._policies[strategy_id]

    def _estimate_policy_score(
        self,
        policy: StrategyPolicy,
        context: StrategyContext,
    ) -> float:
        """估计策略评分"""
        # 综合历史成功率和上下文匹配度
        base_score = policy.success_rate * 0.7

        # 上下文匹配度
        complexity_match = 1.0 - abs(context.task_complexity / 10 - 0.5)
        context_score = complexity_match * 0.3

        return base_score + context_score

    def _infer_strategy_type(self, strategy_id: str) -> StrategyType:
        """推断策略类型"""
        try:
            return StrategyType(strategy_id)
        except ValueError:
            return StrategyType.DIRECT

    def _get_default_weights(self, strategy_type: StrategyType) -> Dict[str, float]:
        """获取默认权重"""
        defaults = {
            StrategyType.DIRECT: {"success": 0.4, "time": 0.3, "quality": 0.2, "resource": 0.1},
            StrategyType.EXPLORATORY: {"success": 0.3, "time": 0.2, "quality": 0.3, "resource": 0.2},
            StrategyType.CONSERVATIVE: {"success": 0.5, "time": 0.1, "quality": 0.3, "resource": 0.1},
            StrategyType.AGGRESSIVE: {"success": 0.2, "time": 0.4, "quality": 0.2, "resource": 0.2},
            StrategyType.ADAPTIVE: {"success": 0.35, "time": 0.25, "quality": 0.25, "resource": 0.15},
        }
        return defaults.get(strategy_type, defaults[StrategyType.DIRECT])

    def _get_default_thresholds(self, strategy_type: StrategyType) -> Dict[str, float]:
        """获取默认阈值"""
        return {
            "min_confidence": 0.6,
            "max_time_hours": 2.0,
            "max_retries": 3,
        }

    def _load(self) -> None:
        """从文件加载"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            policies_data = data.get("policies", {})
            for pid, pdata in policies_data.items():
                self._policies[pid] = StrategyPolicy(
                    strategy_id=pdata["strategy_id"],
                    strategy_type=StrategyType(pdata["strategy_type"]),
                    weights=pdata["weights"],
                    thresholds=pdata["thresholds"],
                    success_count=pdata.get("success_count", 0),
                    failure_count=pdata.get("failure_count", 0),
                    total_reward=pdata.get("total_reward", 0.0),
                    last_updated=pdata.get("last_updated", datetime.now().isoformat()),
                )

            self._iteration = data.get("iteration", 0)
        except Exception:
            pass

    def _save(self) -> None:
        """保存到文件"""
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "iteration": self._iteration,
            "policies": {
                pid: p.to_dict()
                for pid, p in self._policies.items()
            },
        }

        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================================
# 单例和工具函数
# ============================================================================

_strategy_learner_instance: Optional[StrategyLearner] = None


def get_strategy_learner(
    project_root: Optional[str] = None,
    learning_rate: float = 0.1,
    exploration_rate: float = 0.2,
) -> StrategyLearner:
    """获取策略学习器单例"""
    global _strategy_learner_instance

    if _strategy_learner_instance is None:
        _strategy_learner_instance = StrategyLearner(
            project_root, learning_rate, exploration_rate
        )

    return _strategy_learner_instance


def reset_strategy_learner() -> None:
    """重置策略学习器单例"""
    global _strategy_learner_instance
    _strategy_learner_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def select_best_strategy(
    context: StrategyContext,
) -> Tuple[StrategyType, bool]:
    """
    快捷函数：选择最佳策略

    Args:
        context: 策略上下文

    Returns:
        (选择的策略, 是否是探索)
    """
    learner = get_strategy_learner()
    available = list(StrategyType)
    return learner.select_strategy(context, available)


def record_strategy_result(
    context: StrategyContext,
    result: StrategyResult,
) -> StrategyReward:
    """
    快捷函数：记录策略执行结果

    Args:
        context: 策略上下文
        result: 执行结果

    Returns:
        计算的回报
    """
    learner = get_strategy_learner()
    return learner.record_execution(context, result)
