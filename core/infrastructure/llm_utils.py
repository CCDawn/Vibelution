# -*- coding: utf-8 -*-
"""
core/infrastructure/llm_utils.py — LLM 辅助工具

职责：
- LLM 错误分类与重试策略
- 系统提示词消息构建

从 agent.py 下沉，遵循 Core First 原则。
"""

from __future__ import annotations

from typing import Optional, Any, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.prompt_manager import to_string, split_sys_prompt_prefix


MAX_CONSECUTIVE_FAILURES = 5


def classify_llm_error(e: Exception) -> Tuple[str, bool, str]:
    """分类 LLM 异常，返回 (category, is_retryable, user_message)。

    Args:
        e: LLM 调用异常

    Returns:
        (错误类别, 是否可重试, 用户友好消息)
    """
    exc_type = type(e).__name__
    exc_msg = str(e)

    if "HTTPStatusError" in exc_type or "429" in exc_msg or "500" in exc_msg:
        if "429" in exc_msg:
            return ("rate_limit", True, "API 速率超限（429），等待后重试")
        if "500" in exc_msg:
            return ("server_error", True, "API 服务器错误（500），等待后重试")
        if "502" in exc_msg or "503" in exc_msg or "504" in exc_msg:
            return ("server_error", True, f"API 服务不可用（{exc_msg[:30]}），等待后重试")
        if "401" in exc_msg or "403" in exc_msg:
            return ("auth_error", False, "API 认证失败（401/403），请检查 API Key")
        return ("http_error", False, f"HTTP 错误：{exc_msg[:60]}")

    if "Timeout" in exc_type or "timeout" in exc_msg.lower():
        return ("timeout", True, "LLM 响应超时，等待后重试")

    if "ConnectError" in exc_type or "Connect" in exc_type:
        return ("network_error", True, "网络连接失败，等待后重试")

    if "ReadError" in exc_type or "RemoteProtocolError" in exc_type:
        return ("network_error", True, "连接读取异常，等待后重试")

    if "RequestError" in exc_type:
        return ("network_error", True, "网络请求异常，等待后重试")

    if "auth" in exc_msg.lower() or "401" in exc_msg or "403" in exc_msg:
        return ("auth_error", False, "认证失败，请检查 API Key 配置")

    if exc_type == "KeyboardInterrupt":
        return ("user_interrupt", False, "用户主动中断")

    return ("unknown_error", False, f"未知错误：{exc_type}: {exc_msg[:60]}")


def parse_tool_args(tool_args: Any) -> dict:
    """将工具参数解析为 dict。

    支持传入 str（JSON）、dict 或其他类型。

    Args:
        tool_args: 原始工具参数

    Returns:
        解析后的 dict，失败返回空 dict
    """
    if isinstance(tool_args, dict):
        return tool_args
    if isinstance(tool_args, str):
        try:
            import json
            return json.loads(tool_args)
        except (json.JSONDecodeError, TypeError):
            return {}
    try:
        import json
        return json.loads(str(tool_args))
    except (json.JSONDecodeError, TypeError):
        return {}


def build_system_message(sp) -> Any:
    """将 SystemPrompt 元组转为 API 消息格式，静态前缀标记 cache_control。

    利用 split_sys_prompt_prefix 分离静态/动态部分：
    - 静态前缀附加 cache_control: {"type": "ephemeral"}，供 API 缓存复用
    - 动态后缀不标记缓存，每轮重新计算
    - 无静态前缀时回退为普通 SystemMessage

    Args:
        sp: SystemPrompt 元组

    Returns:
        SystemMessage 或 dict 格式的消息
    """
    static_parts, dynamic_parts = split_sys_prompt_prefix(sp)
    if not static_parts:
        return SystemMessage(content=to_string(sp))
    content_blocks = [{
        "type": "text",
        "text": "\n\n".join(static_parts),
        "cache_control": {"type": "ephemeral"},
    }]
    if dynamic_parts:
        content_blocks.append({
            "type": "text",
            "text": "\n\n".join(dynamic_parts),
        })
    return {"role": "system", "content": content_blocks}
