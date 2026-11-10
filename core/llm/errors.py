# -*- coding: utf-8 -*-
"""LLM 错误归一化。"""

from __future__ import annotations

import re
from typing import Tuple

from .types import LLMError, LLMOutputTruncatedError

__all__ = [
    "CHINESE_RATE_LIMIT_PHRASES",
    "CLASSIFIER_CATEGORIES",
    "GATEWAY_TRANSIENT_400_PHRASES",
    "LLMError",
    "LLMOutputTruncatedError",
    "classify_exception",
]

# classify_exception 自己能构造的全部 category 值域（LLMError 实例按原样透传，
# 其类别可以是任意值，见 core/llm/types.py 的 LLMError 子类）。这是单一事实
# 源：core/llm/recovery.py 在 import 时机器校验恢复动作表覆盖本集合，防止
# 「分类器产出 X、恢复表只认 Y」的键名漂移再次发生——2026-10-02 事件里，
# 协议类错误因恢复表键名漂移整轮 fail-fast、走不到任何恢复动作，只能靠
# 同类问题的事后修复兜底。
CLASSIFIER_CATEGORIES: Tuple[str, ...] = (
    "payload_protocol_error",
    "user_interrupt",
    "server_error",
    "rate_limit",
    "context_length_error",
    "quota_error",
    "tool_protocol_error",
    "empty_content_error",
    "network_error",
    "provider_protocol_error",
    "auth_error",
    "timeout",
    "capability_error",
    "configuration_error",
)

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


# 本地文件系统 errno：2 缺文件 / 13 无权限 / 28 磁盘满。这三个都只可能来自
# 本机环境（典型是 httpx 在构造 SSL 上下文时读取 certifi/cacert.pem，包正在
# 被重装时会以裸 "[Errno 2] No such file or directory" 抛出），请求根本没有
# 发到 provider。传输族 errno（104 connection reset / 110 timeout 等）不在
# 此列，继续由下方 network_error 关键词分支处理。
_LOCAL_FS_ERRNOS: Tuple[int, ...] = (2, 13, 28)
_LOCAL_FS_ERRNO_PATTERN = re.compile(r"\[Errno\s+(2|13|28)\]", re.IGNORECASE)
_LOCAL_FS_ERRNO_MESSAGES = {
    2: "本地运行时文件缺失（[Errno 2]）：本轮调用未到达 provider；请完成当前更新/安装后重试",
    13: "本地运行时文件访问被拒绝（[Errno 13]）：本轮调用未到达 provider；请检查文件权限后重试",
    28: "本地磁盘空间不足（[Errno 28]）：本轮调用未到达 provider；请释放磁盘空间后重试",
}


def _local_filesystem_errno(exc: Exception, message: str) -> int | None:
    """读取本地文件系统 errno；异常对象优先，消息里的 ``[Errno N]`` 为同源证据。"""

    raw = getattr(exc, "errno", None)
    try:
        errno_value = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        errno_value = None
    if errno_value in _LOCAL_FS_ERRNOS:
        return errno_value
    match = _LOCAL_FS_ERRNO_PATTERN.search(message)
    return int(match.group(1)) if match else None


# 结构化 HTTP 状态证据：只认 "HTTP 503" / '"status_code": 429' / "code=401"
# 形态（Error code: 400 属同族）。纯文本三位数（模型名、request id、trace
# 片段里的 "-403-"、"4013"）不是状态码证据——词边界要求三位数后紧跟非数字，
# "HTTP 1429"、"error_code=4013" 都不命中。
_UPSTREAM_HTTP_STATUS_PATTERN = re.compile(
    r"\bHTTP\s+([1-5][0-9]{2})\b"
    r"|['\"]?status_code['\"]?\s*[:=]\s*([1-5][0-9]{2})\b"
    r"|\bcode\s*[=:]\s*([1-5][0-9]{2})\b",
    re.IGNORECASE,
)

# 401/403 文案证据同样要求两侧数字边界："request id 4013"、"端口 1401" 不再
# 误判成认证失败；"401"/"403" 独立 token 或 "-403-" 这类非数字邻接仍命中。
_AUTH_STATUS_CODE_PATTERN = re.compile(r"(?<![0-9])40[13](?![0-9])")


def _upstream_http_status(exc: Exception, message: str) -> int | None:
    """读取上游异常对象携带的结构化状态码；缺失时回退消息里的结构化形态。"""

    for candidate in (exc, getattr(exc, "__cause__", None)):
        if candidate is None:
            continue
        raw = getattr(candidate, "status_code", None)
        if raw is None:
            response = getattr(candidate, "response", None)
            raw = getattr(response, "status_code", None)
        if raw is None:
            continue
        try:
            status = int(raw)
        except (TypeError, ValueError):
            continue
        if 100 <= status <= 599:
            return status
    match = _UPSTREAM_HTTP_STATUS_PATTERN.search(message)
    if match:
        return int(next(group for group in match.groups() if group))
    return None


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
    # 本地文件系统错误先于传输关键词判定：本机缺文件（典型是重装依赖期间缺失
    # certifi/cacert.pem）不是 provider 协议错误，调用从未到达上游。
    local_errno = _local_filesystem_errno(exc, exc_msg)
    if local_errno is not None:
        return LLMError(
            "configuration_error",
            _LOCAL_FS_ERRNO_MESSAGES[local_errno],
            retryable=False,
            details={"errno": local_errno, "exceptionType": exc_type},
        )
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
    # 结构化状态码优先于文案子串：异常对象携带的上游状态码或消息里的
    # "HTTP 401"/"code=400" 形态是硬证据，先按状态码定类。这样 "invalid
    # authorization header" + 上游 400 归 provider_protocol_error 而不是被
    # "authorization" 文案拖进 auth_error；真 401 消息里夹带 "400" 文案时
    # 仍归 auth_error，不被 bad_request 子串抢走。只覆盖 401/403/400 三类：
    # 429/5xx 仍走下方关键词表——litellm.RateLimitError 等异常对象自带
    # status_code=429 但依赖关键词表语义（类型证据提升归 error_classification
    # 管），这里抢先判定会漂移既有判例。
    upstream_status = _upstream_http_status(exc, exc_msg)
    if upstream_status in (401, 403):
        return LLMError(
            "auth_error",
            "认证失败，请检查 provider 凭据",
            retryable=False,
            details={"httpStatus": upstream_status},
        )
    if upstream_status == 400:
        return LLMError(
            "provider_protocol_error",
            exc_msg or "provider 请求参数错误",
            retryable=False,
            details={"httpStatus": 400},
        )
    if "bad_request" in lower or "bad request" in lower or "invalid params" in lower or "400" in lower:
        return LLMError("provider_protocol_error", exc_msg or "provider 请求参数错误", retryable=False)
    # auth 文案证据收紧为具体短语 + 独立 401/403 token：裸 "auth" 子串会误伤
    # "authorizer"，裸 "401" 会误伤 "4013"。常见厂商文案（unauthorized /
    # authentication / invalid api key / api key not valid）与独立状态码才
    # 构成认证失败证据。
    if (
        "unauthorized" in lower
        or "authentication" in lower
        or "invalid api key" in lower
        or "invalid_api_key" in lower
        or "api key not valid" in lower
        or "incorrect api key" in lower
        or bool(_AUTH_STATUS_CODE_PATTERN.search(lower))
    ):
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
