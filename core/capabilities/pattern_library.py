#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经验模式库 (Experience Pattern Library) - Phase 8 核心模块

包含：
- pattern_miner.py - 从历史中挖掘模式
- pattern_library.py - 存储和管理模式
- pattern_matcher.py - 匹配新任务的适用模式

Phase 8.2 模块
"""

from __future__ import annotations

import os
import json
import ast
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from collections import defaultdict
import statistics


# ============================================================================
# 枚举和数据结构
# ============================================================================

class PatternType(Enum):
    """模式类型"""
    SUCCESS = "success"           # 成功模式
    FAILURE = "failure"           # 失败模式
    OPTIMIZATION = "optimization"  # 优化模式
    BEST_PRACTICE = "best_practice"  # 最佳实践
    ANTI_PATTERN = "anti_pattern"  # 反模式


class TaskCategory(Enum):
    """任务类别"""
    CODE_ANALYSIS = "code_analysis"
    CODE_MODIFICATION = "code_modification"
    TEST_WRITING = "test_writing"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    DEBUGGING = "debugging"
    OPTIMIZATION = "optimization"
    UNKNOWN = "unknown"


@dataclass
class ExecutionContext:
    """执行上下文"""
    task_type: TaskCategory
    task_description: str
    file_paths: List[str]
    tools_used: List[str]
    complexity: float = 0.0  # 0-10
    estimated_hours: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    duration_seconds: float
    tools_used: List[str]
    errors: List[str] = field(default_factory=list)
    output_summary: str = ""
    quality_score: float = 0.0  # 0-10


@dataclass
class ExperiencePattern:
    """
    经验模式

    表示从历史执行中提取的可复用模式
    """
    pattern_id: str
    pattern_type: PatternType
    name: str
    description: str

    # 触发条件
    context: ExecutionContext

    # 执行序列
    action_sequence: List[str]  # 工具调用序列

    # 效果评估
    success_rate: float  # 0-1
    avg_duration_seconds: float
    quality_score: float  # 0-10

    # 适用性
    applicability_score: float  # 0-1
    similar_tasks: int = 0  # 相似任务数
    positive_feedback: int = 0
    negative_feedback: int = 0

    # 元数据
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    use_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "name": self.name,
            "description": self.description,
            "context": {
                "task_type": self.context.task_type.value,
                "task_description": self.context.task_description,
                "file_paths": self.context.file_paths,
                "tools_used": self.context.tools_used,
                "complexity": self.context.complexity,
            },
            "action_sequence": self.action_sequence,
            "success_rate": self.success_rate,
            "avg_duration_seconds": self.avg_duration_seconds,
            "quality_score": self.quality_score,
            "applicability_score": self.applicability_score,
            "similar_tasks": self.similar_tasks,
            "positive_feedback": self.positive_feedback,
            "negative_feedback": self.negative_feedback,
            "tags": self.tags,
            "examples": self.examples,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "use_count": self.use_count,
        }


@dataclass
class PatternMatch:
    """模式匹配结果"""
    pattern: ExperiencePattern
    match_score: float  # 0-1
    confidence: float  # 0-1
    matched_attributes: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


# ============================================================================
# 模式挖掘器
# ============================================================================

class PatternMiner:
    """
    模式挖掘器

    功能：
    - 分析任务执行历史
    - 识别成功/失败模式
    - 提取可复用的动作序列
    - 计算模式统计信息
    """

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = Path(project_root) if project_root else Path(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._pattern_counter = 0
        self._execution_history: List[Tuple[ExecutionContext, ExecutionResult]] = []

    def add_execution(
        self,
        context: ExecutionContext,
        result: ExecutionResult,
    ) -> None:
        """
        添加执行记录

        Args:
            context: 执行上下文
            result: 执行结果
        """
        self._execution_history.append((context, result))

    def mine_patterns(
        self,
        min_success_rate: float = 0.6,
        min_samples: int = 2,
    ) -> List[ExperiencePattern]:
        """
        从执行历史中挖掘模式

        Args:
            min_success_rate: 最小成功率阈值
            min_samples: 最小样本数

        Returns:
            挖掘出的模式列表
        """
        patterns = []

        # 按工具序列分组
        by_sequence = self._group_by_sequence()

        for sequence, executions in by_sequence.items():
            if len(executions) < min_samples:
                continue

            # 计算统计信息
            successes = sum(1 for _, r in executions if r.success)
            success_rate = successes / len(executions)

            if success_rate < min_success_rate and len(executions) < min_samples + 2:
                continue

            # 提取上下文特征
            avg_complexity = statistics.mean(c.complexity for c, _ in executions)
            all_tools = set()
            for c, _ in executions:
                all_tools.update(c.tools_used)

            # 创建模式
            pattern = self._create_pattern(
                sequence=sequence,
                executions=executions,
                success_rate=success_rate,
                avg_complexity=avg_complexity,
                tools_used=list(all_tools),
            )
            patterns.append(pattern)

        return patterns

    def _group_by_sequence(
        self,
    ) -> Dict[str, List[Tuple[ExecutionContext, ExecutionResult]]]:
        """按工具序列分组"""
        by_sequence = defaultdict(list)

        for context, result in self._execution_history:
            # 标准化序列
            sequence_key = tuple(sorted(context.tools_used))
            by_sequence[sequence_key].append((context, result))

        return {str(k): v for k, v in by_sequence.items()}

    def _create_pattern(
        self,
        sequence: str,
        executions: List[Tuple[ExecutionContext, ExecutionResult]],
        success_rate: float,
        avg_complexity: float,
        tools_used: List[str],
    ) -> ExperiencePattern:
        """创建模式"""
        self._pattern_counter += 1

        # 分析结果
        durations = [r.duration_seconds for _, r in executions]
        quality_scores = [r.quality_score for _, r in executions if r.quality_score > 0]

        # 确定模式类型
        if success_rate >= 0.8:
            pattern_type = PatternType.SUCCESS
            name_prefix = "成功模式"
        elif success_rate <= 0.3:
            pattern_type = PatternType.FAILURE
            name_prefix = "失败模式"
        else:
            pattern_type = PatternType.OPTIMIZATION
            name_prefix = "优化模式"

        # 获取上下文
        sample_context = executions[0][0]

        # 创建任务类别描述
        task_descriptions = [c.task_description for c, _ in executions]
        most_common_desc = max(set(task_descriptions), key=task_descriptions.count)

        pattern = ExperiencePattern(
            pattern_id=f"pattern_{self._pattern_counter:03d}",
            pattern_type=pattern_type,
            name=f"{name_prefix} - {sample_context.task_type.value}",
            description=f"使用工具 {tools_used} 完成任务的成功模式",
            context=ExecutionContext(
                task_type=sample_context.task_type,
                task_description=most_common_desc[:200],
                file_paths=sample_context.file_paths,
                tools_used=tools_used,
                complexity=avg_complexity,
            ),
            action_sequence=tools_used,
            success_rate=success_rate,
            avg_duration_seconds=statistics.mean(durations) if durations else 0,
            quality_score=statistics.mean(quality_scores) if quality_scores else 5.0,
            applicability_score=min(0.5 + success_rate * 0.5, 1.0),
            similar_tasks=len(executions),
            tags=[sample_context.task_type.value],
        )

        return pattern

    def clear_history(self) -> None:
        """清除执行历史"""
        self._execution_history = []


# ============================================================================
# 模式库
# ============================================================================

class PatternLibrary:
    """
    模式库

    功能：
    - 持久化存储模式
    - 模式分类和检索
    - 模式评分和排序
    - 模式更新和删除
    """

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            storage_path = os.path.join(project_root, "workspace", "patterns", "library.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._patterns: Dict[str, ExperiencePattern] = {}
        self._load()

    def add(self, pattern: ExperiencePattern) -> str:
        """添加模式"""
        self._patterns[pattern.pattern_id] = pattern
        self._save()
        return pattern.pattern_id

    def get(self, pattern_id: str) -> Optional[ExperiencePattern]:
        """获取模式"""
        return self._patterns.get(pattern_id)

    def remove(self, pattern_id: str) -> bool:
        """删除模式"""
        if pattern_id in self._patterns:
            del self._patterns[pattern_id]
            self._save()
            return True
        return False

    def get_all(
        self,
        pattern_type: Optional[PatternType] = None,
        min_success_rate: float = 0.0,
    ) -> List[ExperiencePattern]:
        """获取所有模式"""
        patterns = list(self._patterns.values())

        if pattern_type:
            patterns = [p for p in patterns if p.pattern_type == pattern_type]

        if min_success_rate > 0:
            patterns = [p for p in patterns if p.success_rate >= min_success_rate]

        return sorted(patterns, key=lambda p: p.success_rate, reverse=True)

    def update(self, pattern: ExperiencePattern) -> bool:
        """更新模式"""
        if pattern.pattern_id in self._patterns:
            self._patterns[pattern.pattern_id] = pattern
            self._save()
            return True
        return False

    def record_feedback(
        self,
        pattern_id: str,
        positive: bool,
    ) -> bool:
        """记录反馈"""
        pattern = self.get(pattern_id)
        if pattern:
            if positive:
                pattern.positive_feedback += 1
            else:
                pattern.negative_feedback += 1

            # 更新成功率
            total = pattern.positive_feedback + pattern.negative_feedback
            if total > 0:
                pattern.success_rate = pattern.positive_feedback / total

            pattern.last_updated = datetime.now().isoformat()
            self._save()
            return True
        return False

    def increment_use_count(self, pattern_id: str) -> bool:
        """增加使用计数"""
        pattern = self.get(pattern_id)
        if pattern:
            pattern.use_count += 1
            pattern.last_updated = datetime.now().isoformat()
            self._save()
            return True
        return False

    def search_by_tag(self, tag: str) -> List[ExperiencePattern]:
        """按标签搜索"""
        return [p for p in self._patterns.values() if tag in p.tags]

    def search_by_tool(self, tool_name: str) -> List[ExperiencePattern]:
        """按工具搜索"""
        return [
            p for p in self._patterns.values()
            if tool_name in p.context.tools_used
        ]

    def _load(self) -> None:
        """从文件加载"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            patterns = data.get("patterns", [])
            for p_data in patterns:
                try:
                    pattern = self._deserialize_pattern(p_data)
                    self._patterns[pattern.pattern_id] = pattern
                except Exception:
                    continue
        except Exception:
            pass

    def _save(self) -> None:
        """保存到文件"""
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "patterns": [p.to_dict() for p in self._patterns.values()],
        }

        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _deserialize_pattern(self, data: Dict) -> ExperiencePattern:
        """反序列化模式"""
        return ExperiencePattern(
            pattern_id=data["pattern_id"],
            pattern_type=PatternType(data["pattern_type"]),
            name=data["name"],
            description=data["description"],
            context=ExecutionContext(
                task_type=TaskCategory(data["context"]["task_type"]),
                task_description=data["context"]["task_description"],
                file_paths=data["context"]["file_paths"],
                tools_used=data["context"]["tools_used"],
                complexity=data["context"].get("complexity", 0.0),
            ),
            action_sequence=data["action_sequence"],
            success_rate=data["success_rate"],
            avg_duration_seconds=data["avg_duration_seconds"],
            quality_score=data["quality_score"],
            applicability_score=data["applicability_score"],
            similar_tasks=data.get("similar_tasks", 0),
            positive_feedback=data.get("positive_feedback", 0),
            negative_feedback=data.get("negative_feedback", 0),
            tags=data.get("tags", []),
            examples=data.get("examples", []),
            first_seen=data.get("first_seen", datetime.now().isoformat()),
            last_updated=data.get("last_updated", datetime.now().isoformat()),
            use_count=data.get("use_count", 0),
        )


# ============================================================================
# 模式匹配器
# ============================================================================

class PatternMatcher:
    """
    模式匹配器

    功能：
    - 根据上下文检索相似模式
    - 推荐适用的成功模式
    - 避免失败的模式
    """

    def __init__(self, pattern_library: PatternLibrary):
        self.pattern_library = pattern_library

    def find_similar(
        self,
        context: ExecutionContext,
        top_k: int = 5,
    ) -> List[PatternMatch]:
        """
        查找相似的模式

        Args:
            context: 执行上下文
            top_k: 返回前 k 个结果

        Returns:
            匹配结果列表
        """
        matches = []

        for pattern in self.pattern_library.get_all():
            score, confidence, matched_attrs = self._calculate_similarity(
                pattern, context
            )

            if score > 0.3:  # 阈值
                matches.append(PatternMatch(
                    pattern=pattern,
                    match_score=score,
                    confidence=confidence,
                    matched_attributes=matched_attrs,
                    suggestions=self._generate_suggestions(pattern, context),
                ))

        # 按匹配分数排序
        matches.sort(key=lambda m: m.match_score, reverse=True)

        return matches[:top_k]

    def recommend(
        self,
        context: ExecutionContext,
        avoid_failures: bool = True,
    ) -> List[PatternMatch]:
        """
        推荐适用的模式

        Args:
            context: 执行上下文
            avoid_failures: 是否避免失败模式

        Returns:
            推荐模式列表
        """
        matches = self.find_similar(context)

        if avoid_failures:
            matches = [
                m for m in matches
                if m.pattern.pattern_type != PatternType.FAILURE
            ]

        # 只返回高成功率的模式
        matches = [
            m for m in matches
            if m.pattern.success_rate >= 0.6
        ]

        return matches

    def _calculate_similarity(
        self,
        pattern: ExperiencePattern,
        context: ExecutionContext,
    ) -> Tuple[float, float, List[str]]:
        """计算相似度"""
        matched_attrs = []
        total_score = 0.0

        # 任务类型匹配
        if pattern.context.task_type == context.task_type:
            total_score += 0.3
            matched_attrs.append("task_type")

        # 工具重叠度
        pattern_tools = set(pattern.context.tools_used)
        context_tools = set(context.tools_used)
        if pattern_tools and context_tools:
            overlap = len(pattern_tools & context_tools) / len(pattern_tools | context_tools)
            total_score += overlap * 0.3
            if overlap > 0.5:
                matched_attrs.append("tools_overlap")

        # 复杂度相似度
        complexity_diff = abs(pattern.context.complexity - context.complexity)
        complexity_sim = max(0, 1 - complexity_diff / 10)
        total_score += complexity_sim * 0.2

        # 标签匹配
        if any(tag in context.task_description for tag in pattern.tags):
            total_score += 0.1
            matched_attrs.append("tag")

        # 置信度
        confidence = pattern.success_rate * 0.7 + pattern.applicability_score * 0.3

        return total_score, confidence, matched_attrs

    def _generate_suggestions(
        self,
        pattern: ExperiencePattern,
        context: ExecutionContext,
    ) -> List[str]:
        """生成建议"""
        suggestions = []

        if pattern.pattern_type == PatternType.SUCCESS:
            suggestions.append(
                f"成功模式: 使用 {', '.join(pattern.action_sequence[:3])} 可获得好的结果"
            )
            suggestions.append(
                f"平均执行时间: {pattern.avg_duration_seconds / 60:.1f} 分钟"
            )
        elif pattern.pattern_type == PatternType.FAILURE:
            suggestions.append(
                "警告: 这个模式在类似任务中失败率较高，请谨慎使用"
            )

        # 建议添加的工具
        pattern_tools = set(pattern.context.tools_used)
        context_tools = set(context.tools_used)
        missing_tools = pattern_tools - context_tools

        if missing_tools:
            suggestions.append(
                f"建议添加工具: {', '.join(list(missing_tools)[:3])}"
            )

        return suggestions


# ============================================================================
# 单例和工具函数
# ============================================================================

_pattern_miner_instance: Optional[PatternMiner] = None
_pattern_library_instance: Optional[PatternLibrary] = None
_pattern_matcher_instance: Optional[PatternMatcher] = None


def get_pattern_miner(project_root: Optional[str] = None) -> PatternMiner:
    """获取模式挖掘器单例"""
    global _pattern_miner_instance
    if _pattern_miner_instance is None:
        _pattern_miner_instance = PatternMiner(project_root)
    return _pattern_miner_instance


def get_pattern_library(storage_path: Optional[str] = None) -> PatternLibrary:
    """获取模式库单例"""
    global _pattern_library_instance
    if _pattern_library_instance is None:
        _pattern_library_instance = PatternLibrary(storage_path)
    return _pattern_library_instance


def get_pattern_matcher() -> PatternMatcher:
    """获取模式匹配器单例"""
    global _pattern_matcher_instance
    if _pattern_matcher_instance is None:
        library = get_pattern_library()
        _pattern_matcher_instance = PatternMatcher(library)
    return _pattern_matcher_instance


def reset_pattern_modules() -> None:
    """重置所有单例"""
    global _pattern_miner_instance, _pattern_library_instance, _pattern_matcher_instance
    _pattern_miner_instance = None
    _pattern_library_instance = None
    _pattern_matcher_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def mine_and_store_patterns(
    project_root: Optional[str] = None,
    min_success_rate: float = 0.6,
) -> List[ExperiencePattern]:
    """
    快捷函数：挖掘模式并存储

    Args:
        project_root: 项目根目录
        min_success_rate: 最小成功率

    Returns:
        挖掘出的模式列表
    """
    miner = get_pattern_miner(project_root)
    library = get_pattern_library()

    patterns = miner.mine_patterns(min_success_rate=min_success_rate)

    for pattern in patterns:
        library.add(pattern)

    return patterns


def recommend_patterns(
    context: ExecutionContext,
) -> List[PatternMatch]:
    """
    快捷函数：推荐适用的模式

    Args:
        context: 执行上下文

    Returns:
        推荐模式列表
    """
    matcher = get_pattern_matcher()
    return matcher.recommend(context)
