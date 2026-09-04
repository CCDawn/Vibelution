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


def classify_error(exc: Exception) -> ErrorClassification:
    """集中错误分类入口：category 沿用现状，disposition 三值判恢复。

    显式规则层：非 LLMError 的裸异常消息携带 HTTP 408 时按请求超时处理，
    与 ``timeout`` 同族可重试——``classify_exception`` 的关键词表目前没有
    408，会把它误归不可重试的 ``provider_protocol_error``。该规则只作用于
    裸异常路径；provider 后端透传的 LLMError 仍完全尊重其 ``retryable``
    标志，保证 client 重试判定平价（未知错误不放宽）。
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
    return ErrorClassification(
        category=error.category,
        disposition=disposition,
        error=error,
    )
