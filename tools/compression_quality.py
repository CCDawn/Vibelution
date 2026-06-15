#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 压缩质量评估器

评估压缩前后的质量：
- 计算压缩比
- 评估信息保留率
- 生成质量报告
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Set


@dataclass
class QualityReport:
    """压缩质量报告"""
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float  # 压缩比例 (0.0 - 1.0)
    saved_tokens: int
    info_preservation_rate: float = 0.0  # 0.0 - 1.0
    key_info_preserved: List[str] = field(default_factory=list)
    key_info_lost: List[str] = field(default_factory=list)
    quality_score: float = 0.0  # 0.0 - 1.0
    warnings: List[str] = field(default_factory=list)

    def is_effective(self, threshold: float = 0.3) -> bool:
        """
        判断压缩是否有效

        Args:
            threshold: 最低压缩比阈值

        Returns:
            压缩是否有效
        """
        return self.compression_ratio >= threshold

    def is_quality_acceptable(self, threshold: float = 0.7) -> bool:
        """
        判断质量是否可接受

        Args:
            threshold: 最低质量分阈值

        Returns:
            质量是否可接受
        """
        return self.quality_score >= threshold

    def to_summary(self) -> str:
        """
        生成质量报告摘要

        Returns:
            格式化的摘要字符串
        """
        lines = [
            "## 压缩质量报告",
            f"- 原始 Token: {self.original_tokens}",
            f"- 压缩后 Token: {self.compressed_tokens}",
            f"- 压缩比: {self.compression_ratio:.1%}",
            f"- 节省 Token: {self.saved_tokens}",
            f"- 信息保留率: {self.info_preservation_rate:.1%}",
            f"- 质量评分: {self.quality_score:.1%}",
        ]
        if self.warnings:
            lines.append(f"- 警告: {', '.join(self.warnings)}")
        return "\n".join(lines)


class CompressionQualityEvaluator:
    """
    压缩质量评估器

    评估压缩前后的信息损失和质量。
    """

    # 关键信息关键词
    KEY_INFO_KEYWORDS = [
        'error', 'exception', 'failed', 'warning', 'critical',
        '错误', '异常', '失败', '警告', '关键',
        'decision', 'decision', '决定', '选择',
        'conclusion', 'conclusion', '结论', '总结',
        'important', 'important', '重要', '关键',
        'must', 'should', '必须', '应该',
        'task', 'goal', '任务', '目标',
        'result', 'result', '结果', '成功',
    ]

    def __init__(self, effectiveness_threshold: float = 0.3):
        """
        初始化压缩质量评估器

        Args:
            effectiveness_threshold: 最低压缩比阈值
        """
        self.effectiveness_threshold = effectiveness_threshold

    def evaluate(
        self,
        original: List[Any],
        compressed: List[Any],
        original_tokens: int,
        compressed_tokens: int,
    ) -> QualityReport:
        """
        评估压缩质量

        Args:
            original: 原始消息列表
            compressed: 压缩后消息列表
            original_tokens: 原始 Token 数
            compressed_tokens: 压缩后 Token 数

        Returns:
            质量报告
        """
        # 计算压缩比
        compression_ratio = self._calculate_compression_ratio(original_tokens, compressed_tokens)
        saved_tokens = original_tokens - compressed_tokens

        # 提取关键信息
        key_info_original = self._extract_key_info(original)
        key_info_compressed = self._extract_key_info(compressed)

        # 计算信息保留
        preserved = key_info_compressed & key_info_original
        lost = key_info_original - key_info_compressed
        info_preservation_rate = len(preserved) / len(key_info_original) if key_info_original else 1.0

        # 计算质量评分
        quality_score = self._calculate_quality_score(
            compression_ratio,
            info_preservation_rate,
            len(lost),
        )

        # 生成警告
        warnings = self._generate_warnings(
            compression_ratio,
            info_preservation_rate,
            saved_tokens,
        )

        return QualityReport(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            saved_tokens=saved_tokens,
            info_preservation_rate=info_preservation_rate,
            key_info_preserved=list(preserved)[:10],
            key_info_lost=list(lost)[:10],
            quality_score=quality_score,
            warnings=warnings,
        )

    def is_compression_effective(
        self,
        original_tokens: int,
        compressed_tokens: int,
    ) -> bool:
        """
        快速判断压缩是否有效

        Args:
            original_tokens: 原始 Token 数
            compressed_tokens: 压缩后 Token 数

        Returns:
            压缩是否有效
        """
        if original_tokens <= 0:
            return False

        ratio = (original_tokens - compressed_tokens) / original_tokens
        return ratio >= self.effectiveness_threshold

    def _calculate_compression_ratio(
        self,
        original_tokens: int,
        compressed_tokens: int,
    ) -> float:
        """
        计算压缩比例

        Args:
            original_tokens: 原始 Token 数
            compressed_tokens: 压缩后 Token 数

        Returns:
            压缩比例 (0.0 - 1.0)
        """
        if original_tokens <= 0:
            return 0.0
        return max(0.0, min(1.0, (original_tokens - compressed_tokens) / original_tokens))

    def _extract_key_info(self, messages: List[Any]) -> Set[str]:
        """
        从消息列表中提取关键信息关键词

        Args:
            messages: 消息列表

        Returns:
            关键信息关键词集合
        """
        key_info = set()

        for msg in messages:
            content = getattr(msg, 'content', '')
            if not content:
                continue

            content_lower = content.lower()
            for keyword in self.KEY_INFO_KEYWORDS:
                if keyword.lower() in content_lower:
                    key_info.add(keyword.lower())

        return key_info

    def _calculate_quality_score(
        self,
        compression_ratio: float,
        info_preservation_rate: float,
        lost_count: int,
    ) -> float:
        """
        计算质量评分

        Args:
            compression_ratio: 压缩比例
            info_preservation_rate: 信息保留率
            lost_count: 丢失的关键信息数量

        Returns:
            质量评分 (0.0 - 1.0)
        """
        # 压缩效果权重 30%
        compression_score = min(1.0, compression_ratio / 0.5) if compression_ratio > 0 else 0.0

        # 信息保留权重 50%
        preservation_score = info_preservation_rate

        # 丢失惩罚权重 20%
        lost_penalty = min(1.0, lost_count / 5)  # 最多5条关键信息丢失
        lost_score = 1.0 - (lost_penalty * 0.5)

        # 综合评分
        score = (
            compression_score * 0.3 +
            preservation_score * 0.5 +
            lost_score * 0.2
        )

        return max(0.0, min(1.0, score))

    def _generate_warnings(
        self,
        compression_ratio: float,
        info_preservation_rate: float,
        saved_tokens: int,
    ) -> List[str]:
        """
        生成警告信息

        Args:
            compression_ratio: 压缩比例
            info_preservation_rate: 信息保留率
            saved_tokens: 节省的 Token 数

        Returns:
            警告信息列表
        """
        warnings = []

        # 压缩比过低
        if compression_ratio < 0.2:
            warnings.append("压缩比过低，可能需要更强的压缩策略")

        # 信息丢失过多
        if info_preservation_rate < 0.5:
            warnings.append("关键信息保留率过低，可能影响后续处理")

        # Token 节省过少
        if saved_tokens < 1000:
            warnings.append("Token 节省过少，可能不值得压缩")

        return warnings


# 全局单例
_evaluator_instance: Optional[CompressionQualityEvaluator] = None


def get_compression_quality_evaluator(
    effectiveness_threshold: float = 0.3,
) -> CompressionQualityEvaluator:
    """
    获取压缩质量评估器单例

    Args:
        effectiveness_threshold: 最低压缩比阈值

    Returns:
        压缩质量评估器实例
    """
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = CompressionQualityEvaluator(effectiveness_threshold)
    return _evaluator_instance


def reset_compression_quality_evaluator() -> None:
    """重置压缩质量评估器单例"""
    global _evaluator_instance
    _evaluator_instance = None
