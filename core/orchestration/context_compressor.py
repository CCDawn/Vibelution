#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上下文压缩模块

职责：
- Token 预算检查
- 自动触发上下文压缩
- 压缩级别管理

使用方式：
    from core.orchestration.context_compressor import ContextCompressor

    compressor = ContextCompressor(token_compressor, config, model_info)
    messages = compressor.check_and_compress(messages, iteration)
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from core.infrastructure.model_discovery import DiscoveryStatus
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger


@dataclass
class CompressionThresholds:
    """压缩阈值配置"""
    preemptive: float = 0.6      # 60% 开始考虑压缩
    forced: float = 0.8          # 80% 必须压缩
    critical: float = 0.95       # 95% 紧急压缩


class ContextCompressor:
    """上下文压缩管理器"""

    def __init__(
        self,
        token_compressor: Any,
        config: Any,
        model_info: Optional[Any] = None,
        effective_max_token_limit: Optional[int] = None,
    ):
        """
        初始化压缩管理器

        Args:
            token_compressor: EnhancedTokenCompressor 实例
            config: 配置对象
            model_info: 模型发现信息（可选）
            effective_max_token_limit: 有效的最大 token 限制（可选）
        """
        self.token_compressor = token_compressor
        self.config = config
        self.model_info = model_info
        self._effective_max_token_limit = effective_max_token_limit
        self._compression_count = 0

    def _get_thresholds(self) -> tuple:
        """获取 Token 阈值"""
        max_budget = self._effective_max_token_limit
        if max_budget is None:
            if self.model_info and self.model_info.status == DiscoveryStatus.SUCCESS:
                max_budget = self.model_info.compression_thresholds.max_token_limit
            else:
                max_budget = getattr(
                    self.config.context_compression,
                    'max_token_limit',
                    16000
                )

        preemptive = int(max_budget * 0.6)
        forced = int(max_budget * 0.8)
        critical = int(max_budget * 0.95)
        return preemptive, forced, critical, max_budget

    def _select_compression_level(
        self,
        current_tokens: int,
        preemptive: int,
        forced: int,
        critical: int,
        iteration: int,
    ) -> Optional[str]:
        """
        选择压缩级别

        Args:
            current_tokens: 当前 token 数
            preemptive: 预防性阈值
            forced: 强制阈值
            critical: 紧急阈值
            iteration: 当前迭代

        Returns:
            压缩级别或 None（不需要压缩）
        """
        if current_tokens > critical:
            return "emergency"
        elif current_tokens > forced:
            compression_count = getattr(self, '_compression_count', 0)
            return "deep" if compression_count < 2 else "standard"
        elif current_tokens > preemptive and iteration > 1:
            return "standard"
        elif current_tokens > preemptive * 0.8 and iteration > 1:
            return "light"
        return None

    def check_and_compress(self, messages: List, iteration: int) -> List:
        """
        检查 Token 预算并在必要时压缩

        Args:
            messages: 消息列表
            iteration: 当前迭代数

        Returns:
            处理后的消息列表
        """
        from tools.token_manager import estimate_messages_tokens

        current_tokens = estimate_messages_tokens(messages)
        preemptive, forced, critical, max_budget = self._get_thresholds()

        # 检查压缩次数限制
        compression_count = getattr(self, '_compression_count', 0)
        max_compressions = getattr(
            self.config.context_compression,
            'max_compressions_per_session',
            20
        )
        is_emergency = current_tokens > critical

        if compression_count >= max_compressions and not is_emergency:
            _debug_logger.warning(
                f"[Token] 压缩次数已达上限 ({compression_count}/{max_compressions})，跳过",
                tag="TOKEN"
            )
            return messages

        # 选择压缩级别
        level = self._select_compression_level(
            current_tokens, preemptive, forced, critical, iteration
        )

        if not level:
            return messages

        ratio = current_tokens / max_budget if max_budget > 0 else 0
        _debug_logger.info(
            f"[压缩-{level}] Token {current_tokens}/{max_budget} = {ratio:.1%}",
            tag="TOKEN"
        )

        # 执行压缩
        messages = self._compress_context(messages, level)
        new_tokens = estimate_messages_tokens(messages)

        if new_tokens >= current_tokens:
            _debug_logger.warning(
                f"[Token] 压缩无效 ({current_tokens} -> {new_tokens})，回退原始",
                tag="TOKEN"
            )
            return messages

        self._compression_count = compression_count + 1
        _debug_logger.info(
            f"[Token] 压缩完成 ({current_tokens} -> {new_tokens})，节省 {current_tokens - new_tokens} Token",
            tag="TOKEN"
        )
        return messages

    def _compress_context(self, messages: List, level: str = "standard") -> List:
        """
        压缩对话上下文

        Args:
            messages: 消息列表
            level: 压缩级别

        Returns:
            压缩后的消息列表
        """
        from tools.token_manager import estimate_messages_tokens

        old_tokens = estimate_messages_tokens(messages)

        summary_chars_map = {
            "light": 500,
            "standard": 1000,
            "deep": 2000,
            "emergency": 3000,
        }
        summary_chars = summary_chars_map.get(level, 1000)

        compressed, _ = self.token_compressor.compress(messages, max_chars=summary_chars)
        new_tokens = estimate_messages_tokens(compressed)

        _debug_logger.info(f"[Token压缩-{level}] {old_tokens} -> {new_tokens}", tag="TOKEN")
        logger.log_compression(old_tokens, new_tokens, old_tokens - new_tokens)
        return compressed

    def reset_compression_count(self):
        """重置压缩计数"""
        self._compression_count = 0


__all__ = [
    "ContextCompressor",
    "CompressionThresholds",
]
