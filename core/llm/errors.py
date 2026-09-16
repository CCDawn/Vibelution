# -*- coding: utf-8 -*-
"""LLM 错误归一化。"""

from __future__ import annotations

from typing import Tuple

from .types import LLMError, LLMOutputTruncatedError

__all__ = [
    "CHINESE_RATE_LIMIT_PHRASES",
    "GATEWAY_TRANSIENT_400_PHRASES",
    "LLMError",
    "LLMOutputTruncatedError",
    "classify_exception",
]

# one-api/new-api 系聚合网关把上游路由失败包成 HTTP 400（"Error code: 400 -
# 当前分组 default 下对于模型 xxx 无可用渠道"）：渠道耗尽、分组负载是网关侧
# 调度状态，等调度器恢复后同体重放即可成功，不是客户端参数错误。模式保持
# 高特异性（渠道/分组调度词汇），"invalid params"/schema 类真参数错误仍由
# 下方 bad_request 分支 fail-closed。
GATEWAY_TRANSIENT_400_PHRASES: Tuple[str, ...] = (
    "无可用渠道",
    "no available channel",
    "当前分组",
)
# "渠道被禁用 / 渠道已被禁用 / 渠道被管理员禁用 / 渠道已停用" 等变体：要求
# "渠道" 与禁用/停用词同时出现才命中，避免裸 "渠道" 误伤。
_GATEWAY_CHANNEL_DISABLED_TOKENS: Tuple[str, ...] = ("禁用", "停用")

# 中文限流文案（不含 "429"/"rate limit" 字样）：one-api/new-api 系中转的
# "当前令牌每分钟最多请求 X 次" / "请求过于频繁" / "令牌额度已耗尽" 等。
# 列表保守列举；error_classification 的 429 证据门引用 CHINESE_RATE_LIMIT_
# PHRASES 把这些短语视为真限流证据，不被降级回 permanent。
CHINESE_RATE_LIMIT_PHRASES: Tuple[str, ...] = (
    "令牌每分钟",
    "每分钟最多",
    "每分钟只能",
    "过于频繁",
    "频率超限",
    "额度已耗尽",
    "额度已用尽",
)


def _is_gateway_transient_400(message: str) -> bool:
    if any(phrase in message for phrase in GATEWAY_TRANSIENT_400_PHRASES):
        return True
    return "渠道" in message and any(token in message for token in _GATEWAY_CHANNEL_DISABLED_TOKENS)


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
    # DeepSeek 思考模式回传 400（"The `reasoning_content` in the thinking mode
    # must be passed back to the API"）：实测同一 body 原样重放必过（raw 直连、
    # litellm、产品全链路均 200，含 4 连发），是聚合网关按内部路由的非确定性
    # 拒绝而非载荷缺陷；wire 层占位符保证已杜绝客户端侧真实缺 rc。按服务端
    # 瞬态处理，同体重试是实证有效的恢复手段。
    if "reasoning_content" in lower and "thinking mode" in lower and "passed back" in lower:
        return LLMError(
            "server_error",
            exc_msg or "provider 思考模式回传校验瞬时拒绝",
            retryable=True,
            details={"httpStatus": 400, "reasoningRoundtripRejection": True},
        )
    # 聚合网关瞬态 400：渠道耗尽/被禁用/分组调度失败（见上方 pattern 注释）。
    # 必须在下方 bad_request 分支之前判定——网关文案通常携带 "Error code: 400"
    # 前缀，先到 bad_request 就会被确定性判死。
    if _is_gateway_transient_400(lower):
        return LLMError(
            "server_error",
            exc_msg or "聚合网关渠道调度瞬态拒绝",
            retryable=True,
            details={"httpStatus": 400, "gatewayChannelTransient": True},
        )
    # 中文限流文案：不含 "429"/"rate limit" 关键词的网关限流（见上方 pattern
    # 注释），按限流同族可重试。
    if any(phrase in lower for phrase in CHINESE_RATE_LIMIT_PHRASES):
        return LLMError(
            "rate_limit",
            exc_msg or "provider 限流（网关中文文案）",
            retryable=True,
            details={"chineseRateLimitPhrase": True},
        )
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
