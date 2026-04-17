#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
决策树 (DecisionTree) - 基于规则的决策系统

Phase 6 核心模块

功能：
- 决策节点管理
- 条件评估
- 决策路径执行
- 决策历史追踪
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import operator


# ============================================================================
# 决策定义
# ============================================================================

class DecisionType(Enum):
    """决策类型"""
    ACTION = "action"
    STRATEGY = "strategy"
    GOAL = "goal"
    PRIORITY = "priority"


@dataclass
class DecisionNode:
    """决策节点"""
    node_id: str
    name: str
    description: str
    decision_type: DecisionType
    condition: Optional[str] = None
    action: Optional[Callable] = None
    children: List[str] = field(default_factory=list)  # 子节点 ID 列表
    weight: float = 1.0  # 权重
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionContext:
    """决策上下文"""
    state: Dict[str, Any]
    history: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionResult:
    """决策结果"""
    decision_id: str
    decision_type: DecisionType
    selected_action: str
    confidence: float
    reasoning: str
    context: DecisionContext
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================================
# 条件评估器
# ============================================================================

class ConditionEvaluator:
    """条件评估器"""

    OPERATORS = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "in": lambda a, b: a in b,
        "not in": lambda a, b: a not in b,
        "and": lambda a, b: a and b,
        "or": lambda a, b: a or b,
    }

    @classmethod
    def evaluate(cls, condition: str, context: Dict[str, Any]) -> bool:
        """
        评估条件

        Args:
            condition: 条件表达式
            context: 上下文变量

        Returns:
            条件结果
        """
        if not condition:
            return True

        try:
            # 简单解析
            return cls._parse_condition(condition, context)
        except Exception:
            return False

    @classmethod
    def _parse_condition(cls, condition: str, context: Dict[str, Any]) -> bool:
        """解析条件表达式"""
        condition = condition.strip()

        # 处理逻辑运算符
        if " and " in condition:
            parts = condition.split(" and ")
            return all(cls._parse_condition(p, context) for p in parts)

        if " or " in condition:
            parts = condition.split(" or ")
            return any(cls._parse_condition(p, context) for p in parts)

        # 处理比较运算符
        for op in ["==", "!=", ">=", "<=", ">", "<"]:
            if op in condition:
                parts = condition.split(op)
                if len(parts) == 2:
                    left, right = parts[0].strip(), parts[1].strip()
                    left_val = cls._get_value(left, context)
                    right_val = cls._get_value(right, context)
                    return cls.OPERATORS[op](left_val, right_val)

        # 处理 in/not in
        if " in " in condition:
            parts = condition.split(" in ")
            if len(parts) == 2:
                left, right = parts[0].strip(), parts[1].strip()
                left_val = cls._get_value(left, context)
                right_val = cls._get_value(right, context)
                return left_val in right_val

        if " not in " in condition:
            parts = condition.split(" not in ")
            if len(parts) == 2:
                left, right = parts[0].strip(), parts[1].strip()
                left_val = cls._get_value(left, context)
                right_val = cls._get_value(right, context)
                return left_val not in right_val

        return False

    @classmethod
    def _get_value(cls, key: str, context: Dict[str, Any]) -> Any:
        """获取变量值"""
        # 移除引号
        if (key.startswith('"') and key.endswith('"')) or \
           (key.startswith("'") and key.endswith("'")):
            return key[1:-1]

        # 布尔值
        if key.lower() == "true":
            return True
        if key.lower() == "false":
            return False

        # 数字
        try:
            return int(key)
        except ValueError:
            try:
                return float(key)
            except ValueError:
                pass

        # 从上下文获取
        keys = key.split(".")
        value = context
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None
        return value


# ============================================================================
# 决策树
# ============================================================================

class DecisionTree:
    """
    决策树

    基于规则的决策系统：

    决策流程：
    1. 加载决策树配置
    2. 评估当前状态
    3. 选择匹配的决策路径
    4. 执行决策动作
    5. 记录决策历史

    使用方式：
        tree = DecisionTree()
        tree.load_from_config(config)
        result = tree.make_decision(context)
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化决策树

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 节点存储
        self._nodes: Dict[str, DecisionNode] = {}
        self._root_nodes: List[str] = []

        # 决策历史
        self._history: List[DecisionResult] = []

        # 统计
        self._stats = {
            "decisions_made": 0,
            "decisions_by_type": {},
        }

    # =========================================================================
    # 节点管理
    # =========================================================================

    def add_node(self, node: DecisionNode) -> None:
        """
        添加决策节点

        Args:
            node: 决策节点
        """
        self._nodes[node.node_id] = node

        # 检查是否是根节点
        if not node.children or node.node_id not in [
            child for n in self._nodes.values() for child in n.children
        ]:
            if node.node_id not in self._root_nodes:
                self._root_nodes.append(node.node_id)

    def get_node(self, node_id: str) -> Optional[DecisionNode]:
        """获取节点"""
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """移除节点"""
        if node_id in self._nodes:
            del self._nodes[node_id]
            if node_id in self._root_nodes:
                self._root_nodes.remove(node_id)
            return True
        return False

    # =========================================================================
    # 决策执行
    # =========================================================================

    def make_decision(
        self,
        context: DecisionContext,
        decision_type: Optional[DecisionType] = None,
    ) -> DecisionResult:
        """
        做决策

        Args:
            context: 决策上下文
            decision_type: 决策类型过滤

        Returns:
            决策结果
        """
        # 选择根节点
        candidates = self._select_candidate_nodes(decision_type)

        if not candidates:
            return self._create_default_result(context)

        # 评估并选择最佳节点
        best_node = self._evaluate_and_select(candidates, context)

        if not best_node:
            return self._create_default_result(context)

        # 创建决策结果
        result = DecisionResult(
            decision_id=best_node.node_id,
            decision_type=best_node.decision_type,
            selected_action=best_node.name,
            confidence=self._calculate_confidence(best_node, context),
            reasoning=self._generate_reasoning(best_node, context),
            context=context,
        )

        # 记录历史
        self._history.append(result)
        self._stats["decisions_made"] += 1
        type_key = result.decision_type.value
        self._stats["decisions_by_type"][type_key] = \
            self._stats["decisions_by_type"].get(type_key, 0) + 1

        return result

    def _select_candidate_nodes(
        self,
        decision_type: Optional[DecisionType],
    ) -> List[DecisionNode]:
        """选择候选节点"""
        candidates = []

        for node_id in self._root_nodes:
            node = self._nodes.get(node_id)
            if node:
                if decision_type is None or node.decision_type == decision_type:
                    candidates.append(node)

        # 也添加其他节点（如果有匹配条件）
        for node in self._nodes.values():
            if node.condition and node not in candidates:
                if decision_type is None or node.decision_type == decision_type:
                    candidates.append(node)

        return candidates

    def _evaluate_and_select(
        self,
        candidates: List[DecisionNode],
        context: DecisionContext,
    ) -> Optional[DecisionNode]:
        """评估并选择最佳节点"""
        best_node = None
        best_score = -1

        for node in candidates:
            score = self._evaluate_node(node, context)
            if score > best_score:
                best_score = score
                best_node = node

        return best_node

    def _evaluate_node(
        self,
        node: DecisionNode,
        context: DecisionContext,
    ) -> float:
        """评估节点得分"""
        score = 0.0

        # 条件匹配
        if node.condition:
            if ConditionEvaluator.evaluate(node.condition, context.state):
                score += 0.5
            else:
                return -1.0  # 条件不满足
        else:
            score += 0.3

        # 权重
        score += node.weight * 0.2

        # 历史奖励
        history_count = context.history.count(node.node_id)
        score -= history_count * 0.05  # 避免重复

        return score

    def _calculate_confidence(
        self,
        node: DecisionNode,
        context: DecisionContext,
    ) -> float:
        """计算置信度"""
        confidence = 0.5

        # 条件明确性
        if node.condition:
            confidence += 0.2

        # 权重
        confidence += min(node.weight * 0.1, 0.2)

        # 历史一致性
        if node.node_id in context.history[-3:]:
            confidence += 0.1

        return min(confidence, 1.0)

    def _generate_reasoning(
        self,
        node: DecisionNode,
        context: DecisionContext,
    ) -> str:
        """生成推理说明"""
        return f"选择 '{node.name}' 因为 {node.description}"

    def _create_default_result(
        self,
        context: DecisionContext,
    ) -> DecisionResult:
        """创建默认结果"""
        return DecisionResult(
            decision_id="default",
            decision_type=DecisionType.ACTION,
            selected_action="no_decision",
            confidence=0.0,
            reasoning="没有匹配的决策规则",
            context=context,
        )

    # =========================================================================
    # 决策路径追踪
    # =========================================================================

    def trace_decision_path(
        self,
        context: DecisionContext,
    ) -> List[Tuple[DecisionNode, float]]:
        """
        追踪决策路径

        Args:
            context: 决策上下文

        Returns:
            决策路径 [(节点, 得分), ...]
        """
        path = []
        candidates = self._select_candidate_nodes(None)

        for node in candidates:
            score = self._evaluate_node(node, context)
            if score >= 0:
                path.append((node, score))

        # 按得分排序
        path.sort(key=lambda x: x[1], reverse=True)

        return path

    # =========================================================================
    # 配置管理
    # =========================================================================

    def load_from_config(self, config: Dict[str, Any]) -> None:
        """
        从配置加载

        Args:
            config: 配置字典
        """
        self._nodes.clear()
        self._root_nodes.clear()

        for node_data in config.get("nodes", []):
            node = DecisionNode(
                node_id=node_data["node_id"],
                name=node_data["name"],
                description=node_data.get("description", ""),
                decision_type=DecisionType(node_data["decision_type"]),
                condition=node_data.get("condition"),
                children=node_data.get("children", []),
                weight=node_data.get("weight", 1.0),
                metadata=node_data.get("metadata", {}),
            )
            self.add_node(node)

    def load_from_file(self, file_path: str) -> None:
        """从文件加载"""
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        self.load_from_config(config)

    def save_to_file(self, file_path: str) -> None:
        """保存到文件"""
        config = self.to_config()
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def to_config(self) -> Dict[str, Any]:
        """转换为配置"""
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "name": node.name,
                    "description": node.description,
                    "decision_type": node.decision_type.value,
                    "condition": node.condition,
                    "children": node.children,
                    "weight": node.weight,
                    "metadata": node.metadata,
                }
                for node in self._nodes.values()
            ]
        }

    # =========================================================================
    # 统计和历史
    # =========================================================================

    def get_history(
        self,
        decision_type: Optional[DecisionType] = None,
        limit: int = 100,
    ) -> List[DecisionResult]:
        """获取决策历史"""
        history = self._history

        if decision_type:
            history = [h for h in history if h.decision_type == decision_type]

        return history[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "total_nodes": len(self._nodes),
            "root_nodes": len(self._root_nodes),
            "history_size": len(self._history),
        }

    def clear_history(self) -> None:
        """清除历史"""
        self._history.clear()
        self._stats["decisions_made"] = 0
        self._stats["decisions_by_type"] = {}


# ============================================================================
# 预设决策树
# ============================================================================

DEFAULT_DECISION_CONFIG = {
    "nodes": [
        {
            "node_id": "high_priority_task",
            "name": "执行高优先级任务",
            "description": "选择最高优先级的任务",
            "decision_type": "action",
            "condition": "task_count > 0 and priority == 'high'",
            "weight": 1.0,
        },
        {
            "node_id": "learn_from_error",
            "name": "从错误中学习",
            "description": "分析最近错误并改进",
            "decision_type": "action",
            "condition": "error_count > 0",
            "weight": 0.9,
        },
        {
            "node_id": "explore_new",
            "name": "探索新方法",
            "description": "尝试新的工具或方法",
            "decision_type": "strategy",
            "condition": "exploration_mode == true",
            "weight": 0.7,
        },
        {
            "node_id": "default_action",
            "name": "默认行动",
            "description": "执行标准工作流程",
            "decision_type": "action",
            "weight": 0.5,
        },
    ]
}


def create_default_decision_tree() -> DecisionTree:
    """创建默认决策树"""
    tree = DecisionTree()
    tree.load_from_config(DEFAULT_DECISION_CONFIG)
    return tree


# ============================================================================
# 全局单例
# ============================================================================

_decision_tree: Optional[DecisionTree] = None


def get_decision_tree(project_root: Optional[str] = None) -> DecisionTree:
    """获取决策树单例"""
    global _decision_tree
    if _decision_tree is None:
        _decision_tree = DecisionTree(project_root)
    return _decision_tree


def reset_decision_tree() -> None:
    """重置决策树"""
    global _decision_tree
    _decision_tree = None
