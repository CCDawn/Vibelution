#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理工具

从 agent.py 中提取的工具结果处理函数：
- truncate_result: 截断超长工具结果
- format_tool_message: 格式化工具消息

使用方式：
    from core.infrastructure.tool_result import truncate_result, format_tool_message
"""

from __future__ import annotations

from typing import Dict, Any, Optional


# 默认截断阈值
DEFAULT_MAX_CHARS = 4000


def truncate_result(result: Any, max_chars: int = DEFAULT_MAX_CHARS) -> tuple:
    """
    截断超长工具结果

    Args:
        result: 工具结果
        max_chars: 最大字符数

    Returns:
        (截断后的结果字符串, 是否被截断)
    """
    result_str = str(result)
    truncated = False
    if len(result_str) > max_chars:
        result_str = (
            result_str[:max_chars]
            + f"\n[...结果已截断，原长度 {len(result_str)} 字符...]"
        )
        truncated = True
    return result_str, truncated


def format_tool_message(
    tool_call: Dict,
    result: Any,
    action: Optional[str] = None,
) -> tuple:
    """
    格式化工具消息

    Args:
        tool_call: 工具调用信息
        result: 工具执行结果
        action: 特殊动作

    Returns:
        (ToolMessage 内容字符串, tool_call_id)
    """
    from langchain_core.messages import ToolMessage

    result_str, _ = truncate_result(result)

    # 安全获取 tool_call_id
    tool_call_id = str(tool_call.get('id', '')) if tool_call.get('id') is not None else ''

    return result_str, tool_call_id


__all__ = [
    "truncate_result",
    "format_tool_message",
    "DEFAULT_MAX_CHARS",
]
