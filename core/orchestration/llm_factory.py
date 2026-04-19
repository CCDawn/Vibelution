#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 工厂模块 - 负责 LLM 创建和 Provider 适配

职责：
- 根据配置创建 ChatOpenAI 或 MiniMax 适配器
- Provider 自动切换（local/minimax/openai）
- LLM 连接测试

使用方式：
    from core.orchestration.llm_factory import create_llm

    llm, compression_llm = create_llm(config)
"""

from __future__ import annotations

import httpx
from typing import Tuple, Optional, Any
from langchain_openai import ChatOpenAI

from config import Config


def create_llm(config: Config) -> Tuple[Any, Any]:
    """
    根据配置创建 LLM 实例

    Args:
        config: Agent 配置对象

    Returns:
        (llm, compression_llm) 元组
    """
    api_timeout = getattr(config.llm, 'api_timeout', 600)
    provider = getattr(config.llm, 'provider', 'local')
    effective_max_tokens = config.llm.max_tokens

    # 获取压缩模型
    compression_llm_kwargs = {
        "model": config.context_compression.compression_model,
        "temperature": 0.3,
        "api_key": config.get_api_key(),
    }
    if config.llm.api_base:
        compression_llm_kwargs["base_url"] = config.llm.api_base
    compression_llm_kwargs["timeout"] = httpx.Timeout(api_timeout, connect=30)

    compression_llm = ChatOpenAI(**compression_llm_kwargs)

    # 确保 MiniMax 适配器已初始化
    global MiniMaxOpenAIAdapter
    if MiniMaxOpenAIAdapter is None:
        _init_minimax_adapter()

    if provider == "minimax":
        api_key = config.get_api_key() or ""
        llm = MiniMaxOpenAIAdapter(
            model=config.llm.model_name,
            api_key=api_key,
            base_url=config.llm.api_base or "https://api.minimaxi.com/v1",
            timeout=httpx.Timeout(api_timeout, connect=30),
            max_tokens=effective_max_tokens,
            temperature=config.llm.temperature,
        )
    else:
        llm_kwargs = {
            "model": config.llm.model_name,
            "temperature": config.llm.temperature,
            "api_key": config.get_api_key(),
            "max_tokens": effective_max_tokens,
        }
        if config.llm.api_base:
            llm_kwargs["base_url"] = config.llm.api_base
        llm_kwargs["timeout"] = httpx.Timeout(api_timeout, connect=30)
        llm = ChatOpenAI(**llm_kwargs)

    return llm, compression_llm


def test_llm_connection(llm: Any, model_name: str) -> bool:
    """
    测试 LLM 连接

    Args:
        llm: LLM 实例
        model_name: 模型名称

    Returns:
        True: 连接成功, False: 连接失败
    """
    from core.logging.logger import debug as _debug_logger

    _debug_logger.info("正在测试 LLM 连接...", tag="LLM")
    try:
        test_response = llm.invoke("你好，请回复 OK")
        _debug_logger.success(
            f"LLM 连接测试成功: {test_response.content[:50]}...",
            tag="LLM"
        )
        return True
    except Exception as e:
        _debug_logger.error(f"LLM 连接测试失败: {type(e).__name__}: {e}", tag="LLM")
        return False


def get_llm_info(llm: Any, provider: str, model_name: str) -> dict:
    """
    获取 LLM 信息用于日志

    Args:
        llm: LLM 实例
        provider: Provider 类型
        model_name: 模型名称

    Returns:
        信息字典
    """
    return {
        "provider": provider,
        "model": model_name,
        "mode": "MiniMax Anthropic" if provider == "minimax" else "OpenAI 兼容",
    }


# MiniMax 适配器占位，延迟导入避免循环依赖
MiniMaxOpenAIAdapter = None


def _init_minimax_adapter():
    """延迟初始化 MiniMax 适配器"""
    global MiniMaxOpenAIAdapter
    if MiniMaxOpenAIAdapter is None:
        try:
            from config.adapters import MiniMaxOpenAIAdapter as _Adapter
            MiniMaxOpenAIAdapter = _Adapter
        except ImportError:
            MiniMaxOpenAIAdapter = ChatOpenAI  # fallback


__all__ = [
    "create_llm",
    "test_llm_connection",
    "get_llm_info",
]
