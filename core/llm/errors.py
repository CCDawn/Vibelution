# -*- coding: utf-8 -*-
"""LLM 错误归一化。"""

from __future__ import annotations

from typing import Tuple

from .types import LLMError, LLMOutputTruncatedError

__all__ = ["LLMError", "LLMOutputTruncatedError", "classify_exception"]


def classify_exception(exc: Exception) -> LLMError:
    exc_type = type(exc).__name__
    exc_msg = str(exc or "")
    lower = exc_msg.lower()
    lower_type = exc_type.lower()

    if isinstance(exc, LLMError):
        return exc
    if "payload_protocol_error" in lower:
        return LLMError("payload_protocol_error", exc_msg or "本地 payload 协议校验失败", retryable=False)
    if exc_type == "KeyboardInterrupt":
        return LLMError("user_interrupt", "用户主动中断", retryable=False)
    if "context_length" in lower or "context length" in lower or "maximum context" in lower or "too many tokens" in lower:
        return LLMError("context_length_error", "上下文长度超过模型限制", retryable=False)
    if "quota" in lower or "insufficient_quota" in lower or "billing" in lower:
        return LLMError("quota_error", "provider 额度不足或计费受限", retryable=False)
    if "duplicate tool_call id" in lower or ("tool" in lower and "schema" in lower):
        return LLMError("tool_protocol_error", exc_msg or "tool calling 协议错误", retryable=False)
    if "chat content is empty" in lower or "content is empty" in lower:
        return LLMError("empty_content_error", "provider 拒绝空消息内容", retryable=False)
    if (
        "unexpected_eof_while_reading" in lower
        or "eof occurred in violation of protocol" in lower
        or "peer closed connection" in lower
        or "incomplete chunked read" in lower
        or "midstreamfallbackerror" in lower_type
        or "midstreamfallbackerror" in lower
        or ("ssl" in lower and "eof" in lower)
        or "remoteprotocolerror" in lower
        or "connection reset" in lower
        or "connection aborted" in lower
        or "apiconnectionerror" in lower_type
        or "apiconnectionerror" in lower
        or "api connection error" in lower
        or "connecterror" in lower_type
        or "connecterror" in lower
        or "connection error" in lower
        or "connection refused" in lower
        or "failed to connect" in lower
        or "connect tcp" in lower
        or "winerror 10061" in lower
        or "actively refused" in lower
        or "目标计算机积极拒绝" in lower
        or "无法连接" in lower
    ):
        return LLMError("network_error", exc_msg or "provider 传输连接异常", retryable=True)
    if (
        "badgateway" in lower_type
        or "badgateway" in lower
        or "bad gateway" in lower
        or "internalservererror" in lower_type
        or "internalservererror" in lower
        or "serviceunavailableerror" in lower_type
        or "serviceunavailableerror" in lower
        or "upstream_error" in lower
        or "upstream request failed" in lower
        or "service unavailable" in lower
        or "temporarily unavailable" in lower
        or "gateway timeout" in lower
        or "api_error" in lower
    ):
        return LLMError("server_error", exc_msg or "provider 服务异常", retryable=True)
    if "bad_request" in lower or "bad request" in lower or "invalid params" in lower or "400" in lower:
        return LLMError("provider_protocol_error", exc_msg or "provider 请求参数错误", retryable=False)
    if "duplicate tool_call id" in lower or ("tool" in lower and "schema" in lower):
        return LLMError("tool_protocol_error", exc_msg or "tool calling 协议错误", retryable=False)
    if "chat content is empty" in lower or "content is empty" in lower:
        return LLMError("empty_content_error", "provider 拒绝空消息内容", retryable=False)
    if "bad_request" in lower or "bad request" in lower or "invalid params" in lower or "400" in lower:
        return LLMError("provider_protocol_error", exc_msg or "provider 请求参数错误", retryable=False)
    if "auth" in lower or "401" in lower or "403" in lower:
        return LLMError("auth_error", "认证失败，请检查 provider 凭据", retryable=False)
    if "429" in lower or "rate limit" in lower:
        return LLMError("rate_limit", "请求频率受限", retryable=True)
    if "timeout" in lower:
        return LLMError("timeout", "LLM 响应超时", retryable=True)
    if "connect" in exc_type.lower() or "network" in lower or "remoteprotocolerror" in lower:
        return LLMError("network_error", "网络连接异常", retryable=True)
    if any(code in lower for code in ("500", "502", "503", "504")):
        return LLMError("server_error", "provider 服务异常", retryable=True)
    if "tool" in lower and "support" in lower:
        return LLMError("capability_error", "当前模型不支持所需 tool calling 能力", retryable=False)
    if "config" in lower or "missing profile" in lower or "missing provider" in lower:
        return LLMError("configuration_error", exc_msg or "LLM 配置错误", retryable=False)
    return LLMError("provider_protocol_error", exc_msg or exc_type, retryable=False)


def classify_for_legacy(exc: Exception) -> Tuple[str, bool, str]:
    normalized = classify_exception(exc)
    return normalized.category, normalized.retryable, str(normalized)
