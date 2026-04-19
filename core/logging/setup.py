#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志设置工具 - 配置全局日志系统

从 agent.py 中提取的日志配置功能：
- print_evolution_time(): 打印当前系统时间
- setup_logging(): 配置第三方库日志抑制

使用方式：
    from core.logging.setup import setup_logging, print_evolution_time

    setup_logging()
    print_evolution_time()
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from core.logging.logger import debug


def print_evolution_time():
    """打印当前系统时间"""
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    debug.system(f"系统时间: {current_time}", tag="EVOLVE")


def setup_logging(level: str = "INFO", log_format: Optional[str] = None) -> logging.Logger:
    """
    配置全局日志系统

    设置日志级别并抑制第三方库的 DEBUG 日志，避免刷屏。

    Args:
        level: 日志级别，默认为 "INFO"
        log_format: 日志格式，默认为 '%(asctime)s | %(levelname)-8s | %(message)s'

    Returns:
        配置好的 logger 实例
    """
    import os

    # 设置环境变量抑制第三方库调试日志
    os.environ.setdefault("HTTPX_LOG_LEVEL", "warning")
    os.environ.setdefault("LANGCHAIN_VERBOSE", "false")

    if log_format is None:
        log_format = '%(asctime)s | %(levelname)-8s | %(message)s'

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout
    )

    # 抑制第三方库的 DEBUG 日志，避免刷屏
    # httpx: HTTP 客户端库，会打印大量请求/响应日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # httpcore: httpx 的底层依赖
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # langchain: 打印工具调用和 Chain 日志
    logging.getLogger("langchain").setLevel(logging.WARNING)
    # openai: OpenAI API 客户端
    logging.getLogger("openai").setLevel(logging.WARNING)
    # anthropic: Anthropic API 客户端
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    # urllib3: HTTP 库
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # litellm: LLM 调用库
    logging.getLogger("litellm").setLevel(logging.WARNING)
    # langchain_community: LangChain 社区模块
    logging.getLogger("langchain_community").setLevel(logging.WARNING)
    # langchain_openai: LangChain OpenAI 集成
    logging.getLogger("langchain_openai").setLevel(logging.WARNING)

    # 抑制 rich 库的详细日志
    logging.getLogger("rich").setLevel(logging.WARNING)

    return logging.getLogger("SelfEvolvingAgent")


# 需要 datetime，但已在 agent.py 顶层导入
from datetime import datetime

__all__ = [
    "print_evolution_time",
    "setup_logging",
]
