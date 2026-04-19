#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Orchestrator (LLM 调用协调器)

Phase 7 核心模块

功能：
- 统一的 LLM 调用接口
- Token 预算管理
- 自动压缩和上下文管理
- 多模型支持
- 策略驱动的参数调整
"""

from __future__ import annotations

import os
import sys
import time
import httpx
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============================================================================
# 配置定义
# ============================================================================


def _load_llm_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "model_name": cfg.llm.model_name,
            "temperature": cfg.llm.temperature,
            "api_timeout": cfg.llm.api_timeout,
            "connect_timeout": cfg.llm.connect_timeout,
        }
    except Exception:
        return {}


_llm_defaults = _load_llm_defaults()


@dataclass
class LLMConfig:
    """LLM 配置"""
    model_name: str = _llm_defaults.get("model_name", "gpt-4o")
    temperature: float = _llm_defaults.get("temperature", 0.7)
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    api_timeout: int = _llm_defaults.get("api_timeout", 600)
    connect_timeout: int = _llm_defaults.get("connect_timeout", 30)
    max_tokens: Optional[int] = None


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    raw_response: Any
    usage_metadata: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LLMCallOptions:
    """LLM 调用选项"""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[List[str]] = None
    tools: Optional[List[Any]] = None
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# LLM Orchestrator
# ============================================================================

class LLMOrchestrator:
    """
    LLM 调用协调器

    统一管理所有 LLM 调用：
    - 单一的 LLM 实例管理
    - Token 预算监控
    - 自动重试和错误处理
    - 策略驱动的参数调整

    使用方式：
        orchestrator = LLMOrchestrator(config)
        response = orchestrator.invoke(messages)
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        project_root: Optional[str] = None,
    ):
        """
        初始化 LLM Orchestrator

        Args:
            config: LLM 配置
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        self.config = config or self._load_default_config()

        # 创建 LLM 实例
        self._llm: Optional[ChatOpenAI] = None
        self._compression_llm: Optional[ChatOpenAI] = None

        # Token 统计
        self._stats = {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_duration": 0.0,
            "errors": 0,
        }

        # 调用历史
        self._call_history: List[LLMResponse] = []

    def _load_default_config(self) -> LLMConfig:
        """加载默认配置"""
        try:
            from config import Config, get_config
            cfg = get_config()
            return LLMConfig(
                model_name=cfg.llm.model_name,
                temperature=cfg.llm.temperature,
                api_key=cfg.get_api_key(),
                api_base=cfg.effective_api_base,
                api_timeout=getattr(cfg.llm, 'api_timeout', 600),
            )
        except Exception:
            return LLMConfig()

    def initialize(self) -> None:
        """初始化 LLM 实例"""
        if self._llm is not None:
            return

        # 获取实际 API 端点（provider=local 时使用 llm_local.url）
        api_base = self.config.effective_api_base

        llm_kwargs = {
            "model": self.config.model_name,
            "temperature": self.config.temperature,
            "api_key": self.config.api_key,
        }
        if api_base:
            llm_kwargs["base_url"] = api_base
        if self.config.max_tokens:
            llm_kwargs["max_tokens"] = self.config.max_tokens

        llm_kwargs["timeout"] = httpx.Timeout(self.config.api_timeout, connect=self.config.connect_timeout)

        self._llm = ChatOpenAI(**llm_kwargs)

        # 创建压缩用 LLM
        compression_kwargs = {
            "model": self.config.model_name,
            "temperature": 0.3,  # 压缩用模型温度固定为 0.3
            "api_key": self.config.api_key,
        }
        if api_base:
            compression_kwargs["base_url"] = api_base
        compression_kwargs["timeout"] = httpx.Timeout(self.config.api_timeout, connect=self.config.connect_timeout)

        self._compression_llm = ChatOpenAI(**compression_kwargs)

        from core.logging import debug_logger
        debug_logger.info(f"LLM Orchestrator 初始化完成，模型: {self.config.model_name}")

    def invoke(
        self,
        messages: List[Any],
        options: Optional[LLMCallOptions] = None,
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        """
        调用 LLM

        Args:
            messages: 消息列表
            options: 调用选项
            tools: 工具列表

        Returns:
            LLM 响应
        """
        if self._llm is None:
            self.initialize()

        start_time = time.time()
        self._stats["total_calls"] += 1

        try:
            # 绑定工具
            if tools:
                llm_with_tools = self._llm.bind_tools(tools)
            else:
                llm_with_tools = self._llm

            # 调用
            response = llm_with_tools.invoke(messages)

            # 记录统计
            duration = time.time() - start_time
            self._stats["total_duration"] += duration

            input_tokens = 0
            output_tokens = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = response.usage_metadata
                input_tokens = usage.get('input_tokens', 0)
                output_tokens = usage.get('output_tokens', 0)
                self._stats["total_input_tokens"] += input_tokens
                self._stats["total_output_tokens"] += output_tokens

            # 记录到宠物系统
            try:
                from core.pet_system import get_pet_system
                get_pet_system().record_tokens(input_tokens, output_tokens)
            except Exception:
                pass  # 宠物系统可能未初始化

            # 构建响应
            llm_response = LLMResponse(
                content=response.content or "",
                raw_response=response,
                usage_metadata=getattr(response, 'usage_metadata', {}),
                model=self.config.model_name,
                duration=duration,
            )

            self._call_history.append(llm_response)
            return llm_response

        except Exception as e:
            self._stats["errors"] += 1
            from core.logging import debug_logger
            debug_logger.error(f"LLM 调用失败: {type(e).__name__}: {e}")
            raise

    def invoke_with_retry(
        self,
        messages: List[Any],
        options: Optional[LLMCallOptions] = None,
        tools: Optional[List[Any]] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> LLMResponse:
        """
        带重试的 LLM 调用

        Args:
            messages: 消息列表
            options: 调用选项
            tools: 工具列表
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            LLM 响应
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.invoke(messages, options, tools)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    from core.logging import debug_logger
                    debug_logger.warning(
                        f"LLM 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    from core.logging import debug_logger
                    debug_logger.error(f"LLM 调用最终失败: {e}")

        raise last_error or RuntimeError("LLM 调用失败")

    def invoke_with_timeout(
        self,
        messages: List[Any],
        timeout: Optional[float] = None,
        options: Optional[LLMCallOptions] = None,
        tools: Optional[List[Any]] = None,
    ) -> Optional[LLMResponse]:
        """
        带超时的 LLM 调用

        Args:
            messages: 消息列表
            timeout: 超时时间（秒）
            options: 调用选项
            tools: 工具列表

        Returns:
            LLM 响应，如果超时则返回 None
        """
        if timeout is None:
            timeout = float(self.config.api_timeout)

        def _invoke():
            return self.invoke(messages, options, tools)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_invoke)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError:
                from core.logging import debug_logger
                debug_logger.error(f"LLM 调用超时 ({timeout}秒)")
                self._stats["errors"] += 1
                return None
            except Exception as e:
                from core.logging import debug_logger
                debug_logger.error(f"LLM 调用异常: {type(e).__name__}: {e}")
                return None

    def get_compression_llm(self) -> ChatOpenAI:
        """获取压缩用 LLM 实例"""
        if self._compression_llm is None:
            self.initialize()
        return self._compression_llm

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "average_duration": (
                self._stats["total_duration"] / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            ),
            "average_input_tokens": (
                self._stats["total_input_tokens"] / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            ),
            "average_output_tokens": (
                self._stats["total_output_tokens"] / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            ),
            "success_rate": (
                (self._stats["total_calls"] - self._stats["errors"]) / self._stats["total_calls"]
                if self._stats["total_calls"] > 0 else 0
            ),
            "call_history_size": len(self._call_history),
        }

    def get_call_history(self, limit: int = 100) -> List[LLMResponse]:
        """获取调用历史"""
        return self._call_history[-limit:]

    def clear_history(self) -> None:
        """清除调用历史"""
        self._call_history.clear()

    def reset_stats(self) -> None:
        """重置统计"""
        self._stats = {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_duration": 0.0,
            "errors": 0,
        }


# ============================================================================
# 全局单例
# ============================================================================

_llm_orchestrator: Optional[LLMOrchestrator] = None


def get_llm_orchestrator(
    config: Optional[LLMConfig] = None,
    project_root: Optional[str] = None,
) -> LLMOrchestrator:
    """获取 LLM Orchestrator 单例"""
    global _llm_orchestrator
    if _llm_orchestrator is None:
        _llm_orchestrator = LLMOrchestrator(config, project_root)
    return _llm_orchestrator


def reset_llm_orchestrator() -> None:
    """重置 LLM Orchestrator"""
    global _llm_orchestrator
    _llm_orchestrator = None
