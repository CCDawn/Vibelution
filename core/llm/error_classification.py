# -*- coding: utf-8 -*-
"""LLM 调用域集中错误分类器：统一 category + 三值 disposition。

LangGraph/Prefect 区分 failed（可重跑）与 crashed（进程级失败），Temporal 把
错误分为可重试传输失败与不可重试 ApplicationError。本模块把同样的三值语义
集中到 LLM 调用域，作为 client 重试判定、review 门恢复判断与 receipt 失败
标注的唯一权威：

- ``transient_retryable``：同一请求原样重发有机会成功（连接重置、读超时、
  429/408、5xx、闸门超时）。
- ``permanent``：重发同一请求必然复现（鉴权、schema/协议拒绝、capability、
  配置）。未知错误 fail-closed 落在这里，绝不放宽为可重试。
- ``budget_or_context``：token 预算/上下文长度族（context_length、quota、
  输出截断）；重发无意义，恢复动作是压缩上下文或调整输出上限。

``category`` 沿用 ``errors.classify_exception`` 的既有字符串值域（含 provider
后端透传的原生类别，如 Anthropic 的 ``rate_limit_error``），保证对现状零漂
移；disposition 是新增的规范化视图。``classify_exception`` 本身的语义由
``tests/test_llm_client.py`` 锁定，本模块只做加法，不改变旧函数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import classify_exception
from .types import LLMError

__all__ = [
    "BUDGET_OR_CONTEXT",
    "PERMANENT",
    "TRANSIENT_RETRYABLE",
    "ErrorClassification",
    "classify_error",
]

# 三值 disposition。用字符串常量而不是 Enum：事件 fields 与 JSON payload
# 直接消费字符串值，省掉到处写 .value。
TRANSIENT_RETRYABLE = "transient_retryable"
PERMANENT = "permanent"
BUDGET_OR_CONTEXT = "budget_or_context"

# retryable=False 但不属于"永久失败"的预算/上下文家族：恢复动作是压缩上下文
# 或调整输出上限，而不是改配置或放弃。
_BUDGET_OR_CONTEXT_CATEGORIES = frozenset(
    {"context_length_error", "quota_error", "output_truncated"}
)

# HTTP 408（请求超时）以独立 token 形式出现才命中，避免 "14085" 这类子串误报。
_HTTP_408_PATTERN = re.compile(r"(?:^|\D)408(?:\D|$)")

# HTTP 429（请求频率受限）同样以独立 token 形式出现才命中，避免 "1429" 这类
# 子串误报把无关数字当成限流信号。
_HTTP_429_PATTERN = re.compile(r"(?:^|\D)429(?:\D|$)")

# 类型证据：litellm.RateLimitError / openai.RateLimitError 等异常的类名或
# 消息里携带的无空格 ``ratelimit`` 形式（关键词表只认带空格的 "rate limit"）。
_RATE_LIMIT_TOKEN_PATTERN = re.compile(r"ratelimit", re.IGNORECASE)


@dataclass(frozen=True)
class ErrorClassification:
    """一次 LLM 调用错误的集中分类结果。

    ``error`` 是归一化后的 :class:`LLMError`（输入本身是 LLMError 时就是原
    异常对象），调用方可以继续用它 raise、发事件而不必二次分类。
    """

    category: str
    disposition: str
    error: LLMError

    @property
    def retryable(self) -> bool:
        """与 ``errors.classify_exception`` 的 retryable 判定保持同源。"""
        return bool(self.error.retryable)

    @property
    def is_transient_retryable(self) -> bool:
        return self.disposition == TRANSIENT_RETRYABLE


def _disposition_for(error: LLMError) -> str:
    """从归一化 LLMError 推导 disposition。

    ``retryable=True`` 一律 ``transient_retryable``（与既有重试判定逐一对
    齐）；``retryable=False`` 时先认预算/上下文家族，其余 fail-closed 归
    ``permanent``——包括未知错误与 provider 原生类别（如
    ``authentication_error``）。
    """

    if error.retryable:
        return TRANSIENT_RETRYABLE
    if error.category in _BUDGET_OR_CONTEXT_CATEGORIES:
        return BUDGET_OR_CONTEXT
    return PERMANENT


def _looks_like_http_request_timeout(exc: Exception) -> bool:
    return bool(_HTTP_408_PATTERN.search(str(exc or "")))


def _has_independent_429_token(exc: Exception) -> bool:
    return bool(_HTTP_429_PATTERN.search(str(exc or "")))


def _has_rate_limit_phrase(exc: Exception) -> bool:
    return "rate limit" in str(exc or "").lower()


def _has_rate_limit_type_token(exc: Exception) -> bool:
    # 类名（litellm.RateLimitError → "ratelimiterror"）与消息里的无空格
    # 形式都算类型证据；带空格的 "rate limit" 由关键词表与上面的短语检查
    # 负责。
    haystack = f"{type(exc).__name__} {exc or ''}"
    return bool(_RATE_LIMIT_TOKEN_PATTERN.search(haystack))


def classify_error(exc: Exception) -> ErrorClassification:
    """集中错误分类入口：category 沿用现状，disposition 三值判恢复。

    显式规则层（只作用于裸异常路径；provider 后端透传的 LLMError 仍完全
    尊重其 ``retryable`` 标志，保证 client 重试判定平价）：

    - HTTP 408：``classify_exception`` 的关键词表没有 408，会把裸异常消息
      携带的 408 误归不可重试的 ``provider_protocol_error``；这里按请求超
      时处理，与 ``timeout`` 同族可重试。
    - HTTP 429 收紧：关键词表用 ``"429" in message`` 子串判定，"1429" 这类
      无关数字会被误报成 ``rate_limit``；要求 429 是独立 token（或消息里有
      "rate limit" 短语）才成立，否则降级回 ``provider_protocol_error``
      fail-closed——review 冷却、client 退避都不应被无关数字触发。
    - HTTP 429 补漏：``litellm.RateLimitError`` 等类型异常消息不带
      "429"/"rate limit" 关键词时同样被误归不可重试的
      ``provider_protocol_error``（生产通道走 litellm）；类型证据把它提升
      为 ``rate_limit`` 同族可重试。
    """

    error = classify_exception(exc)
    disposition = _disposition_for(error)
    if (
        disposition == PERMANENT
        and not isinstance(exc, LLMError)
        and _looks_like_http_request_timeout(exc)
    ):
        message = str(exc or "HTTP 408 request timeout")
        return ErrorClassification(
            category="timeout",
            disposition=TRANSIENT_RETRYABLE,
            error=LLMError(
                "timeout",
                message,
                retryable=True,
                details={"httpStatus": 408},
            ),
        )
    if not isinstance(exc, LLMError) and error.category == "rate_limit":
        # 关键词路径命中的 rate_limit 必须有真 429 证据：独立 token 的 429
        # 或 "rate limit" 短语。纯子串命中（如 "HTTP 1429"）降级回
        # provider_protocol_error，绝不放宽也绝不触发限流冷却。
        if not _has_rate_limit_phrase(exc) and not _has_independent_429_token(exc):
            message = str(exc or "")
            return ErrorClassification(
                category="provider_protocol_error",
                disposition=PERMANENT,
                error=LLMError(
                    "provider_protocol_error",
                    message,
                    retryable=False,
                    details={"suspectedSubstring429": True},
                ),
            )
    elif (
        disposition == PERMANENT
        and not isinstance(exc, LLMError)
        and _has_rate_limit_type_token(exc)
    ):
        # litellm.RateLimitError 类型证据补漏：消息缺关键词时提升为
        # rate_limit 同族可重试，client 退避与 review 冷却据此生效。
        message = str(exc or "provider rate limit")
        return ErrorClassification(
            category="rate_limit",
            disposition=TRANSIENT_RETRYABLE,
            error=LLMError(
                "rate_limit",
                message,
                retryable=True,
                details={"httpStatus": 429},
            ),
        )
    return ErrorClassification(
        category=error.category,
        disposition=disposition,
        error=error,
    )
