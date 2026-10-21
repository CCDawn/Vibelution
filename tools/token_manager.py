#!/usr/bin/env python3
"""
增强型 Token 压缩与记忆管理模块

在 OpenCLAW 风格基础上进行优化：

核心优化：
1. 预压缩机制 - 在 Token 耗尽前主动压缩
2. 消息优先级 - 区分不同类型消息的重要性
3. 智能截断 - 根据消息类型采用不同策略
4. 动态阈值 - 根据对话阶段调整压缩时机
5. 层级摘要 - 多级压缩，保留关键信息
6. 预算感知 - 实时追踪 Token 消耗

设计原则：
- 预防优于治疗：在接近限制前就压缩
- 保留决策上下文：压缩时保留意图而非细节
- 渐进式压缩：分多次小压缩而非一次性大压缩
"""

import json
import logging
import os
import time
from typing import Optional, List, Dict, Any, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque, OrderedDict
from datetime import datetime
from enum import IntEnum

from core.infrastructure.runtime_input import (
    build_runtime_notice_message,
    is_external_request_message,
)
from core.infrastructure.llm_utils import build_cacheable_system_message
from core.infrastructure.feature_gate import resolve_feature_decision


# ============================================================================
# 配置常量 - 从配置文件加载
# ============================================================================


def _load_token_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "DEFAULT_TOKEN_BUDGET": cfg.context_compression.max_token_limit,
            "MAX_SYSTEM_PROMPT_TOKENS": 2000,
            "MAX_TOOL_RESULT_TOKENS": 400,
            "MAX_HISTORY_PAIRS": cfg.context_compression.keep_recent_steps,
            "MAX_AI_RESPONSE_CHARS": 300,
            "MAX_TOOL_NAME_CHARS": 40,
            "MAX_EXTERNAL_REQUEST_CHARS": 400,
            "COMPRESSION_TRIGGER_RATIO": cfg.context_compression.levels.light,
            "COMPRESSION_WARNING_RATIO": 0.5,
            "COMPRESSION_CRITICAL_RATIO": cfg.context_compression.levels.standard,
            "COMPRESSION_TARGET_RATIO": 0.45,
            "LIGHT_SUMMARY_CHARS": cfg.context_compression.summary_chars.light,
            "STANDARD_SUMMARY_CHARS": cfg.context_compression.summary_chars.standard,
            "DEEP_SUMMARY_CHARS": cfg.context_compression.summary_chars.deep,
        }
    except Exception:
        return {}


_token_defaults = _load_token_defaults()

# Token 预算配置
DEFAULT_TOKEN_BUDGET = _token_defaults.get("DEFAULT_TOKEN_BUDGET", 8000)
MAX_SYSTEM_PROMPT_TOKENS = _token_defaults.get("MAX_SYSTEM_PROMPT_TOKENS", 2000)
MAX_TOOL_RESULT_TOKENS = _token_defaults.get("MAX_TOOL_RESULT_TOKENS", 400)
MAX_HISTORY_PAIRS = _token_defaults.get("MAX_HISTORY_PAIRS", 3)

# 压缩阈值（优化 - 更激进的阈值以避免超限）
# 基于模型 32768 context window，配置 max_token_limit = 16000
COMPRESSION_TRIGGER_RATIO = _token_defaults.get("COMPRESSION_TRIGGER_RATIO", 0.60)
COMPRESSION_WARNING_RATIO = _token_defaults.get("COMPRESSION_WARNING_RATIO", 0.50)
COMPRESSION_CRITICAL_RATIO = _token_defaults.get("COMPRESSION_CRITICAL_RATIO", 0.80)
COMPRESSION_TARGET_RATIO = _token_defaults.get("COMPRESSION_TARGET_RATIO", 0.45)

# 摘要配置
MINIMAL_SUMMARY_CHARS = 80
CORE_SUMMARY_CHARS = 200
DETAILED_SUMMARY_CHARS = 500
LIGHT_SUMMARY_CHARS = _token_defaults.get("LIGHT_SUMMARY_CHARS", 500)
STANDARD_SUMMARY_CHARS = _token_defaults.get("STANDARD_SUMMARY_CHARS", 1000)
DEEP_SUMMARY_CHARS = _token_defaults.get("DEEP_SUMMARY_CHARS", 2000)

# 截断配置
MAX_AI_RESPONSE_CHARS = _token_defaults.get("MAX_AI_RESPONSE_CHARS", 300)
MAX_TOOL_NAME_CHARS = _token_defaults.get("MAX_TOOL_NAME_CHARS", 40)
MAX_EXTERNAL_REQUEST_CHARS = _token_defaults.get("MAX_EXTERNAL_REQUEST_CHARS", 400)

# 预压缩 Buffer（百分比）
PRECOMPRESSION_BUFFER = 0.10


# ============================================================================
# 消息优先级枚举
# ============================================================================

class MessagePriority(IntEnum):
    """消息优先级（数值越低越重要）"""
    CRITICAL = 1      # 系统提示词、记忆
    HIGH = 2          # 最近的工具结果
    MEDIUM = 3        # AI 思考过程
    LOW = 4           # 早期历史（可压缩）
    TRIVIAL = 5       # 重复的搜索结果等


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TokenBudget:
    """Token 预算追踪器（增强版）"""
    total_budget: int = 8000
    system_prompt_tokens: int = 0
    reserved_tokens: int = 0  # 预留空间
    
    @property
    def effective_budget(self) -> int:
        """有效预算（减去预留）"""
        return self.total_budget - self.reserved_tokens
    
    @property
    def available_tokens(self) -> int:
        """可用 Token"""
        return self.effective_budget - self.system_prompt_tokens

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget == other
        return super().__eq__(other)

    def __gt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget > other
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget < other
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget >= other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, (int, float)):
            return self.total_budget <= other
        return NotImplemented


@dataclass
class CompressionRecord:
    """压缩记录"""
    timestamp: float
    before_tokens: int
    after_tokens: int
    compression_ratio: float
    pairs_compressed: int
    summary_preview: str
    compression_type: str = "incremental"  # incremental, forced, emergency

    def __post_init__(self) -> None:
        self.compression_ratio = (
            (self.before_tokens - self.after_tokens) / max(self.before_tokens, 1)
        )


@dataclass
class CompressionResult:
    """单次压缩结果；兼容旧调用方把它当摘要字符串使用。"""
    summary: str
    tokens_before: int
    tokens_after: int
    pairs_compressed: int = 0
    compression_type: str = "none"

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def compression_ratio(self) -> float:
        return self.tokens_saved / max(self.tokens_before, 1)

    def __str__(self) -> str:
        return self.summary

    def __bool__(self) -> bool:
        return bool(self.summary)

    def __contains__(self, item: object) -> bool:
        return item in self.summary

    def __len__(self) -> int:
        return len(self.summary)


@dataclass
class CompressionOutput:
    """压缩返回值；支持 `(messages, stats)` 解包，也支持直接读取统计字段。

    ``summarized_messages`` 是本次真正被折叠进摘要的消息集（保留区/错误保留
    组除外）。压缩 checkpoint 用它把 covered 事件域约束在摘要实际折叠的
    事件上，避免把 kept 窗口标成已覆盖导致重放丢历史。
    """
    messages: List[Any]
    result: CompressionResult
    summarized_messages: List[Any] = field(default_factory=list)

    def __iter__(self):
        yield self.messages
        yield self.result

    def __getitem__(self, index: int):
        return (self.messages, self.result)[index]

    def __len__(self) -> int:
        return 2

    @property
    def tokens_before(self) -> int:
        return self.result.tokens_before

    @property
    def tokens_after(self) -> int:
        return self.result.tokens_after

    @property
    def tokens_saved(self) -> int:
        return self.result.tokens_saved

    @property
    def compression_ratio(self) -> float:
        return self.result.compression_ratio

    @property
    def summary(self) -> str:
        return self.result.summary


@dataclass
class MessageMeta:
    """消息元数据"""
    priority: MessagePriority = MessagePriority.MEDIUM
    is_essential: bool = False      # 是否必须保留
    can_truncate: bool = True       # 是否可截断
    token_cost: int = 0             # Token 消耗估算
    content_preview: str = ""       # 内容预览


class TokenCompressionStats:
    """Token 压缩统计（增强版）"""
    def __init__(self):
        self.compressions: List[CompressionRecord] = []
        self.total_tokens_saved = 0
        self.compression_count = 0
        self.last_compression_time = None
        self.emergency_compressions = 0
        self.preemptive_compressions = 0
        
        # Token 使用趋势
        self.token_history: deque = deque(maxlen=50)
        self.peak_tokens = 0
    
    def record(self, before: int, after: int, pairs: int, summary: str, 
               compression_type: str = "incremental") -> None:
        """记录一次压缩"""
        ratio = (before - after) / max(before, 1)
        record = CompressionRecord(
            timestamp=time.time(),
            before_tokens=before,
            after_tokens=after,
            compression_ratio=ratio,
            pairs_compressed=pairs,
            summary_preview=summary[:80] if summary else "",
            compression_type=compression_type,
        )
        self.compressions.append(record)
        self.total_tokens_saved += (before - after)
        self.compression_count += 1
        self.last_compression_time = time.time()
        
        # 统计特殊压缩类型
        if compression_type == "emergency":
            self.emergency_compressions += 1
        elif compression_type == "preemptive":
            self.preemptive_compressions += 1
        
        # 更新峰值
        if before > self.peak_tokens:
            self.peak_tokens = before
    
    def record_usage(self, tokens: int) -> None:
        """记录 Token 使用"""
        self.token_history.append({
            'timestamp': time.time(),
            'tokens': tokens
        })
    
    def get_stats(self) -> Dict[str, Any]:
        """获取详细统计"""
        if not self.compressions:
            return {"status": "no_compressions"}
        
        recent = self.compressions[-5:]
        return {
            "total_compressions": self.compression_count,
            "total_tokens_saved": self.total_tokens_saved,
            "avg_ratio": sum(c.compression_ratio for c in self.compressions) / len(self.compressions),
            "last_compression": datetime.fromtimestamp(self.compressions[-1].timestamp).isoformat(),
            "emergency_count": self.emergency_compressions,
            "preemptive_count": self.preemptive_compressions,
            "peak_tokens": self.peak_tokens,
            "recent_savings": [c.before_tokens - c.after_tokens for c in recent],
            "compression_types": {
                t: sum(1 for c in self.compressions if c.compression_type == t)
                for t in set(c.compression_type for c in self.compressions)
            }
        }


# ============================================================================
# 核心工具函数
# ============================================================================

def estimate_tokens_precise(text: str) -> int:
    """
    精确的 Token 估算（考虑中英文差异）。
    
    改进：增加安全系数 1.2，避免低估导致超限。
    """
    if not text:
        return 0
    if not isinstance(text, str):
        return 0

    if text.isascii() and not any(c in text for c in "\v\f\x1c\x1d\x1e\x1f"):
        whitespace = (
            text.count(" ")
            + text.count("\t")
            + text.count("\n")
            + text.count("\r")
        )
        ascii_text = len(text) - whitespace
        base_tokens = ascii_text / 4 + whitespace / 6
        return int(base_tokens * 1.2) + 50

    chinese = 0
    cjk_ext = 0
    ascii_text = 0
    whitespace = 0
    other = 0

    for c in text:
        if '\u4e00' <= c <= '\u9fff':
            chinese += 1
        elif '\u3400' <= c <= '\u4dbf':
            cjk_ext += 1
        elif c.isascii() and not c.isspace():
            ascii_text += 1
        elif c in ' \t\n\r':
            whitespace += 1
        else:
            other += 1
    
    # 估算（中文约1.5字符=1 token，英文约4字符=1 token）
    # 增加 1.2x 安全系数，避免低估
    base_tokens = chinese / 1.5 + cjk_ext / 1.5 + ascii_text / 4 + whitespace / 6 + other / 2
    
    return int(base_tokens * 1.2) + 50  # 额外加50作为消息结构开销


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        value = message.get("role")
    else:
        value = getattr(message, "type", None) or getattr(message, "role", None)
    normalized = str(value or "").strip().lower()
    return {"human": "user", "ai": "assistant"}.get(normalized, normalized)


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _message_content_text(message: Any) -> str:
    content = _message_content(message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content or "")


def _message_tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, dict):
        raw = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw = getattr(message, "tool_calls", None) or []
    return [item for item in list(raw or []) if isinstance(item, dict)]


def _message_tool_call_id(message: Any) -> str:
    if isinstance(message, dict):
        value = message.get("tool_call_id") or message.get("toolCallId")
    else:
        value = getattr(message, "tool_call_id", None)
    return str(value or "").strip()


_ERROR_KEYWORDS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "错误",
    "异常",
    "失败",
    "超时",
    "权限",
)


def _message_contains_error_marker(message: Any) -> bool:
    content = _message_content_text(message)
    if not isinstance(content, str):
        return False
    lowered = content.lower()
    return any(keyword in lowered for keyword in _ERROR_KEYWORDS)


def _pair_preserving_groups(messages: list) -> list[list]:
    """Group an assistant tool call with its immediately following tool results.

    Error-preserving cuts must move whole groups so a preserved tool result
    always travels with the assistant tool call that produced it; keeping one
    side of a pair would leave an orphan tool result or an unresolved call in
    the provider payload (codex keeps call/result as one unit).
    """
    groups: list[list] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        call_ids = [
            str(item.get("id") or "").strip()
            for item in _message_tool_calls(message)
            if str(item.get("id") or "").strip()
        ]
        if call_ids:
            group = [message]
            index += 1
            remaining = set(call_ids)
            while index < len(messages):
                candidate = messages[index]
                result_id = _message_tool_call_id(candidate)
                if not result_id or result_id not in remaining:
                    break
                group.append(candidate)
                remaining.discard(result_id)
                index += 1
            groups.append(group)
        else:
            groups.append([message])
            index += 1
    return groups


def _is_provider_user_message(message: Any) -> bool:
    return _message_role(message) == "user"


# 历史摘要 notice 的载体标记：compress() 把上一代摘要写回为 runtime notice
# （SystemMessage，正文以「历史摘要:」开头）。下一轮压缩必须能识别它，
# 否则前代摘要既不进摘要输入也不被保留，压缩链在第二代断裂。
HISTORY_SUMMARY_NOTICE_MARKER = "历史摘要:"


def _is_history_summary_notice(message: Any) -> bool:
    """判断一条消息是否是前代压缩写回的历史摘要载体。

    等价判据：system 角色且正文携带历史摘要标记；外部任务输入永远不算
    历史摘要（它们有独立的保留语义）。
    """
    if is_external_request_message(message):
        return False
    if _message_role(message) != "system":
        return False
    content = _message_content_text(message)
    return HISTORY_SUMMARY_NOTICE_MARKER in content


def _history_summary_notice_payload(message: Any) -> str:
    """提取历史摘要 notice 携带的上一代摘要正文（去掉载体标记头）。"""
    content = _message_content_text(message)
    if not content:
        return ""
    marker_index = content.find(HISTORY_SUMMARY_NOTICE_MARKER)
    if marker_index < 0:
        return ""
    return content[marker_index + len(HISTORY_SUMMARY_NOTICE_MARKER):].strip()


def _estimate_message_content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return estimate_tokens_precise(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict) and "text" in block:
                total += estimate_tokens_precise(block["text"])
            elif isinstance(block, dict) and str(block.get("type") or "").lower() in {"image_url", "input_image"}:
                total += 256
            elif isinstance(block, str):
                total += estimate_tokens_precise(block)
        return total
    if content is None:
        return 0
    return estimate_tokens_precise(str(content)[:10000])


def _estimate_messages_tokens_uncached(messages: list) -> int:
    return sum(
        _estimate_message_content_tokens(_message_content(message))
        for message in messages
    )


def _content_char_upper_bound(content: Any) -> int:
    """Conservative char budget used as a token upper bound (never below precise)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict) and "text" in block:
                total += len(str(block.get("text") or ""))
            elif isinstance(block, dict) and str(block.get("type") or "").lower() in {
                "image_url",
                "input_image",
            }:
                total += 256
            elif isinstance(block, str):
                total += len(block)
            elif block is not None:
                total += min(len(str(block)), 10000)
        return total
    if content is None:
        return 0
    return min(len(str(content)), 10000)


def rough_upper_bound_messages_tokens(messages: list) -> int:
    """Fast, conservative upper bound (chars + per-message overhead).

    Always >= the precise estimator for the same content, so it is safe for
    "definitely under threshold → skip precise scan" gates.
    """
    if not messages:
        return 0
    total = 0
    for message in messages:
        total += _content_char_upper_bound(_message_content(message))
        total += 50  # matches estimate_tokens_precise structure overhead floor
    return int(total)


# 内容签名键控的小 LRU：典型 agent iteration 会连续多次询问同一 messages 的
# token 数（UI 显示 / 压缩触发 / 微压缩 gate / 错误诊断），且 compression、
# micro-compact 会整表重建消息列表（id(messages) 变化但消息对象共享），旧的
# 单槽按列表 id 键控的缓存在重建后立即 miss。新键控按每条消息的
# (id(message), id(content), len(content)) 生成内容签名，重建列表只要共享
# 消息对象即命中；条目同时钉住首尾消息对象（与 core.chat.context_assembler
# 的 _IdentityListMemo 同一惯例），排除 id 复用碰撞。条目同时缓存 rough 上
# 界与 precise 估值，热轮里 rough 与 precise 共享一次扫描结果（见
# _scan_messages_tokens），重复查询完全免扫描。签名/命中为 O(N) 的 id+len
# 组装，远低于 per-character 的 precise 扫描。单进程内多线程并发与旧实现
# 一样不加锁；dict.get 原子返回完整条目，不会出现旧实现两个全局变量之间的
# 撕裂读。
_ESTIMATE_CACHE_MAX_ENTRIES = 8
_PRECISE_UNSET = object()  # rough-only 条目的 precise 占位（precise 可合法为 0）
_estimate_cache: "OrderedDict[tuple, tuple]" = OrderedDict()


def _messages_token_signature(messages: list) -> tuple:
    """Cheap content signature of the message list (ids + lengths, no char scan)."""
    parts = []
    for message in messages:
        content = _message_content(message)
        parts.append((
            id(message),
            id(content),
            len(content) if isinstance(content, (str, list)) else 0,
        ))
    return (len(messages), tuple(parts))


def _estimate_cache_lookup(messages: list):
    """Return (signature, entry|None); entry is (first, last, rough, precise)."""
    signature = _messages_token_signature(messages)
    entry = _estimate_cache.get(signature)
    if entry is None:
        return signature, None
    first = messages[0] if messages else None
    last = messages[-1] if messages else None
    if entry[0] is not first or entry[1] is not last:
        return signature, None
    _estimate_cache.move_to_end(signature)
    return signature, entry


def _estimate_cache_store(signature: tuple, messages: list, rough: int, precise) -> None:
    _estimate_cache[signature] = (
        messages[0] if messages else None,
        messages[-1] if messages else None,
        int(rough),
        precise,
    )
    _estimate_cache.move_to_end(signature)
    while len(_estimate_cache) > _ESTIMATE_CACHE_MAX_ENTRIES:
        _estimate_cache.popitem(last=False)


def _scan_messages_tokens(messages: list) -> tuple[int, int]:
    """One pass over contents returning (precise_tokens, rough_upper_bound).

    rough 与 precise 共享这次遍历：需要 precise 时 rough 免费得到，避免
    同一列表在一次判定里被完整走两遍。
    """
    precise_total = 0
    rough_total = 0
    for message in messages:
        content = _message_content(message)
        precise_total += _estimate_message_content_tokens(content)
        rough_total += _content_char_upper_bound(content) + 50  # matches precise structure floor
    return precise_total, int(rough_total)


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的总 Token（内容签名键控的小 LRU 缓存）。"""
    signature, entry = _estimate_cache_lookup(messages)
    if entry is not None:
        rough, precise = entry[2], entry[3]
        if precise is not _PRECISE_UNSET:
            return precise
        # rough-only 条目（此前 far-under-threshold 只缓存了 rough），阈值
        # 收紧后按需补齐 precise。
        precise = _estimate_messages_tokens_uncached(messages)
        _estimate_cache_store(signature, messages, rough, precise)
        return precise
    precise, rough = _scan_messages_tokens(messages)
    _estimate_cache_store(signature, messages, rough, precise)
    return precise


def estimate_messages_tokens_for_threshold(messages: list, threshold: int) -> int:
    """Estimate tokens for compress/UI gates.

    When a conservative char upper bound is still <= threshold, skip the
    expensive per-character precise walk. Near/over the threshold, fall back to
    the precise cached estimator so compress decisions stay correct. Rough 和
    precise 都按内容签名缓存：同一列表重复判定不重扫。
    """
    limit = max(0, int(threshold or 0))
    signature, entry = _estimate_cache_lookup(messages)
    if entry is not None:
        rough, precise = entry[2], entry[3]
    else:
        rough = rough_upper_bound_messages_tokens(messages)
        if rough <= limit:
            _estimate_cache_store(signature, messages, rough, _PRECISE_UNSET)
            return rough
        precise, rough = _scan_messages_tokens(messages)
        _estimate_cache_store(signature, messages, rough, precise)
        return precise
    if rough <= limit:
        return rough
    if precise is _PRECISE_UNSET:
        precise = _estimate_messages_tokens_uncached(messages)
        _estimate_cache_store(signature, messages, rough, precise)
    return precise


_TOOL_PAYLOAD_TEXT_KEYS = (
    "result",
    "resultPreview",
    "result_preview",
    "summary",
    "error",
)


def _message_tool_payload_parts(message: Any) -> list:
    """Text-bearing tool payload pieces of one message.

    Seed/ledger replay messages carry the tool call name/arguments and the
    tool result under ``tool_calls``/``toolCalls`` while ``content`` stays
    empty, so a content-only estimate collapses to the text-only tail for
    tool-heavy sessions. Both shapes are supported:

    - ledger shape: ``{"name", "arguments", "result", "summary", ...}``
    - provider shape: ``{"function": {"name", "arguments"}}``
    """
    if not isinstance(message, dict):
        return []
    raw = message.get("tool_calls")
    if not isinstance(raw, list) or not raw:
        raw = message.get("toolCalls")
    if not isinstance(raw, list):
        return []
    parts: list = []
    for item in raw:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        function_block = item.get("function") if isinstance(item.get("function"), dict) else {}
        for key in ("name", "tool_name", "toolName"):
            value = item.get(key)
            if value is None:
                value = function_block.get("name")
            text = str(value or "").strip()
            if text:
                parts.append(text)
        for key in ("arguments", "args", *_TOOL_PAYLOAD_TEXT_KEYS):
            value = item.get(key)
            if value is None:
                value = function_block.get(key)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, str):
                text = value
            else:
                try:
                    text = json.dumps(value, ensure_ascii=False)
                except (TypeError, ValueError):
                    text = str(value)
            if text:
                parts.append(text)
    return parts


def estimate_messages_tokens_with_tool_payloads(messages: list, threshold: int) -> int:
    """Threshold estimate that also counts tool-call/result payloads.

    Same contract as :func:`estimate_messages_tokens_for_threshold` (cheap
    conservative char bound when clearly under the threshold, precise walk
    otherwise), but messages whose tool payloads sit in
    ``tool_calls``/``toolCalls`` (seed/ledger replay shape) are metered as if
    the payloads sat in ``content`` — keeping the estimate on the same basis
    as the assembled model input so seed-path gates see real pressure.
    """
    limit = max(0, int(threshold or 0))
    rough = rough_upper_bound_messages_tokens(messages)
    payload_bound = 0
    for message in list(messages or []):
        payload_bound += sum(len(part) for part in _message_tool_payload_parts(message))
    if rough + payload_bound <= limit:
        return rough + payload_bound
    total = 0
    for message in list(messages or []):
        text_parts: list = [_message_content_text(message)]
        text_parts.extend(_message_tool_payload_parts(message))
        total += estimate_tokens_precise("\n".join(part for part in text_parts if part))
    return total


def estimate_messages_tokens_uncached(messages: list) -> int:
    """直接计算，跳过缓存。用于校验或测试。"""
    return _estimate_messages_tokens_uncached(messages)


def get_message_priority(msg: Any) -> MessagePriority:
    """
    根据消息内容推断优先级。
    """
    content = getattr(msg, 'content', '')
    msg_type = getattr(msg, 'type', '')
    
    # 外部任务输入（协议头标记）
    if is_external_request_message(msg):
        return MessagePriority.MEDIUM

    # 系统消息最高优先级
    if msg_type == 'system':
        return MessagePriority.CRITICAL
    
    # 包含关键信息的工具结果
    if msg_type == 'tool':
        if any(kw in content for kw in ['错误', 'Error', '成功', 'OK', 'Syntax']):
            return MessagePriority.HIGH
        if any(kw in content for kw in ['edit_local_file', 'check_syntax', 'restart']):
            return MessagePriority.HIGH
        return MessagePriority.MEDIUM
    
    # AI 思考过程
    if msg_type == 'ai':
        # 有工具调用的通常更重要
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            return MessagePriority.MEDIUM
        return MessagePriority.MEDIUM
    
    return MessagePriority.MEDIUM


# ============================================================================
# 增强型截断函数
# ============================================================================

def truncate_tool_result(result: str, max_chars: int = None) -> str:
    """
    智能截断工具结果。
    
    采用保守策略，优先保留开头和结尾。
    """
    if result is None:
        return ""
    if not isinstance(result, str):
        result = str(result)
    if max_chars is None:
        max_chars = MAX_TOOL_RESULT_TOKENS
    if max_chars <= 0:
        return ""
    
    if len(result) <= max_chars:
        return result
    
    # 智能截断：保留开头、重要结尾
    marker = "\n[...已截断...]\n"
    if max_chars <= len(marker) + 2:
        return result[:max_chars]

    available = max_chars - len(marker)
    end_chars = int(available * 0.4)
    start_chars = available - end_chars
    
    return (result[:start_chars] + marker + result[-end_chars:])[:max_chars]


def truncate_ai_response(response: str, max_chars: int = None) -> str:
    """截断 AI 响应"""
    if response is None:
        return ""
    if not isinstance(response, str):
        response = str(response)
    if max_chars is None:
        max_chars = MAX_AI_RESPONSE_CHARS
    if max_chars <= 0:
        return ""
    
    if len(response) <= max_chars:
        return response
    
    # AI 响应通常开头是结论，保留开头
    marker = "\n[...已截断]"
    if max_chars <= len(marker):
        return response[:max_chars]
    return response[:max_chars - len(marker)] + marker


def smart_compress_message(msg: Any, max_chars: int = CORE_SUMMARY_CHARS) -> str:
    """
    根据消息类型智能压缩。
    """
    content = getattr(msg, 'content', str(msg))
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)
    msg_type = getattr(msg, 'type', '')
    
    if len(content) <= max_chars:
        return content
    
    # 不同类型采用不同策略
    if msg_type == 'tool':
        # 工具结果：保留开头和结尾
        return truncate_tool_result(content, max_chars)
    elif msg_type == 'ai':
        # AI 思考：保留开头（通常是结论）
        return truncate_ai_response(content, max_chars)
    else:
        # 其他：直接截断
        return content[:max_chars] + "\n[...已截断]"


# ============================================================================
# 增强型增量压缩器
# ============================================================================

class EnhancedTokenCompressor:
    """
    增强型 Token 压缩器。
    
    优化点：
    1. 预压缩机制 - 在达到警告阈值时就压缩
    2. 多级压缩 - 根据紧急程度选择压缩强度
    3. 智能摘要 - 用 LLM 生成高质量摘要
    4. 消息优先级 - 优先保留重要消息
    """
    
    def __init__(
        self,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_history_pairs: int = MAX_HISTORY_PAIRS,
        compression_llm: Any = None,
        enable_preemptive: bool = True,
        summary_prompt_path: str = None,
        preemptive_threshold: float = None,
        forced_threshold: float = None,
    ):
        self.token_budget = TokenBudget(
            total_budget=token_budget,
            reserved_tokens=int(token_budget * PRECOMPRESSION_BUFFER)
        )
        self.max_history_pairs = max_history_pairs
        self.compression_llm = compression_llm
        self.enable_preemptive = enable_preemptive
        self.preemptive_threshold = preemptive_threshold
        self.forced_threshold = forced_threshold
        self.stats = TokenCompressionStats()
        
        # 压缩历史
        self.compression_history: deque = deque(maxlen=20)
        
        # 当前压缩状态
        self._compression_level = 0  # 0=正常, 1=警告, 2=紧急
        
        # 摘要提示词
        self.summary_prompt_path = summary_prompt_path
        self._summary_prompt_cache = None
    
    @property
    def warning_threshold(self) -> int:
        """警告阈值"""
        ratio = self.preemptive_threshold if self.preemptive_threshold is not None else COMPRESSION_WARNING_RATIO
        return int(self.token_budget.effective_budget * ratio)
    
    @property
    def trigger_threshold(self) -> int:
        """触发阈值"""
        ratio = self.forced_threshold if self.forced_threshold is not None else COMPRESSION_TRIGGER_RATIO
        return int(self.token_budget.effective_budget * ratio)
    
    @property
    def critical_threshold(self) -> int:
        """紧急阈值"""
        return int(self.token_budget.effective_budget * COMPRESSION_CRITICAL_RATIO)
    
    @property
    def target_tokens(self) -> int:
        """目标 Token 数"""
        return int(self.token_budget.effective_budget * COMPRESSION_TARGET_RATIO)
    
    def get_compression_level(self, current_tokens: int) -> str:
        """获取当前压缩级别"""
        if current_tokens > self.critical_threshold:
            return "emergency"
        elif current_tokens > self.trigger_threshold:
            return "active"
        elif current_tokens > self.warning_threshold:
            return "warning"
        return "normal"
    
    def should_compress(self, messages: List[Any]) -> Tuple[bool, str, str]:
        """
        判断是否需要压缩。
        
        Returns:
            (是否需要压缩, 原因, 压缩类型)
        """
        current_tokens = estimate_messages_tokens(messages)
        self.stats.record_usage(current_tokens)
        
        level = self.get_compression_level(current_tokens)
        
        if level == "emergency":
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"紧急: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "emergency"
        
        if level == "active":
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"触发: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "active"
        
        if level == "warning" and self.enable_preemptive:
            ratio = current_tokens / self.token_budget.effective_budget
            return True, f"预压缩: {current_tokens}/{self.token_budget.effective_budget} ({ratio:.0%})", "preemptive"
        
        return False, "", "none"
    
    def compress(
        self,
        messages: List[Any],
        max_chars: int = CORE_SUMMARY_CHARS,
        reason: str = "",
        keep_count: int = 3,
        preserve_errors: bool = True,
        use_llm_summary: bool = True,
        llm_summary_reporter: Any = None,
    ) -> CompressionOutput:
        """
        执行压缩：保留最近 N 条原始AI回复 + 压缩旧消息为摘要。

        策略：
        - 最近 N 条 AI 消息及其上下文保持原始不变
        - N 条之前的消息压缩成一条摘要
        - 包含错误信息的消息始终保留（不受 keep_count 限制）

        Args:
            messages: 消息列表
            max_chars: 摘要最大字符数
            reason: 压缩原因
            keep_count: 保留的最近 AI 消息数量
            preserve_errors: 是否强制保留错误消息
            use_llm_summary: 是否使用 LLM 生成摘要（False 时用规则提取）
            llm_summary_reporter: 可选的 LLM 摘要成败上报钩子（on_failure/on_success）；
                仅在真实尝试了 LLM 摘要时回调，供熔断与显式降级事件使用

        Returns:
            (压缩后的消息, 压缩统计/摘要对象)
        """
        from langchain_core.messages import SystemMessage, AIMessage
        
        current_tokens = estimate_messages_tokens(messages)
        compression_type = self.get_compression_level(current_tokens)
        
        # 分离消息类型
        system_msgs = [
            m for m in messages
            if isinstance(m, SystemMessage)
            and not is_external_request_message(m)
            and not _is_history_summary_notice(m)
        ]
        external_request_indices = [
            index for index, message in enumerate(messages)
            if is_external_request_message(message)
        ]
        provider_user_indices = [
            index for index, message in enumerate(messages)
            if _is_provider_user_message(message)
        ]
        protected_request_indices = sorted(
            {*external_request_indices, *provider_user_indices}
        )
        latest_request_index = (
            protected_request_indices[-1] if protected_request_indices else None
        )
        latest_request = (
            messages[latest_request_index]
            if latest_request_index is not None
            else None
        )
        latest_request_is_provider_user = bool(
            latest_request is not None and _is_provider_user_message(latest_request)
        )

        # Only the current external request is protected verbatim. Prior user
        # requests remain compactable and therefore enter the summary instead
        # of disappearing silently.
        #
        # 历史摘要 notice（上一代压缩写回的 SystemMessage）也必须进入可摘要
        # 输入：压缩链的单调累积依赖「第 N 代摘要在第 N+1 次压缩时被折叠进
        # 新摘要」。把它们排除会让前代上下文从模型视野消失（多代断裂）。
        other_msgs = [
            message
            for index, message in enumerate(messages)
            if (
                not isinstance(message, SystemMessage)
                or is_external_request_message(message)
                or _is_history_summary_notice(message)
            )
            and index != latest_request_index
        ]
        
        # 找出所有 AI 消息（带 tool_calls 或纯文本回复）
        ai_indices = []
        for i, msg in enumerate(other_msgs):
            if isinstance(msg, AIMessage) or _message_role(msg) == "assistant":
                ai_indices.append(i)
        
        if not ai_indices and keep_count > 0:
            return CompressionOutput(
                messages,
                CompressionResult("", current_tokens, current_tokens, 0, "none"),
            )

        if keep_count <= 0:
            kept_msgs = []
            old_msgs = list(other_msgs)
        elif len(ai_indices) <= keep_count:
            kept_msgs = list(other_msgs)
            old_msgs = []
        else:
            cutoff_idx = ai_indices[-keep_count]
            kept_msgs = list(other_msgs[cutoff_idx:])
            old_msgs = list(other_msgs[:cutoff_idx])

        # 错误消息强制保留：按「tool call + 其 tool 结果」整组保留，避免只把错误
        # tool 结果插回保留区、配对的 tool_call 已进摘要，形成孤儿结果或未决调用。
        if preserve_errors:
            preserved: list = []
            still_old: list = []
            for group in _pair_preserving_groups(old_msgs):
                if any(_message_contains_error_marker(msg) for msg in group):
                    preserved.extend(group)
                else:
                    still_old.extend(group)
            if preserved:
                kept_msgs = preserved + kept_msgs
            old_msgs = still_old

        summary = ""
        if old_msgs:
            summary = self._generate_summary(
                old_msgs,
                max_chars,
                use_llm=use_llm_summary,
                llm_summary_reporter=llm_summary_reporter,
            )
            # 摘要链保真：上一代摘要正文显式并入新摘要（LLM 路径已在输入里
            # 看得到 notice，规则路径完全忽略 system 消息，必须在这里兜底）。
            summary = self._merge_prior_history_summary(old_msgs, summary, max_chars)
        if not old_msgs and not summary:
            return CompressionOutput(
                messages,
                CompressionResult("", current_tokens, current_tokens, 0, compression_type),
            )
        # 重建消息结构
        compressed = []
        
        # 1. SystemMessage（只保留一个）
        if system_msgs:
            compressed.append(system_msgs[0])
        
        # 2. 旧式外部任务 SystemMessage 保持原有前置顺序。
        if latest_request is not None and not latest_request_is_provider_user:
            compressed.append(latest_request)
        
        # 3. 历史摘要（如果有）
        if summary:
            compressed.append(build_runtime_notice_message(f"历史摘要:\n{summary}"))
        
        # 4. 保留的最近 3 条 AI 及上下文（原始不变）
        compressed.extend(kept_msgs)

        # 5. 当前 chat user 输入必须保持 provider user role 且位于历史之后。
        if latest_request_is_provider_user:
            compressed.append(latest_request)
        
        # 记录压缩统计
        old_tokens = current_tokens
        new_tokens = estimate_messages_tokens(compressed)
        self.stats.record(
            old_tokens, new_tokens, 
            len(old_msgs), summary,
            compression_type
        )
        
        return CompressionOutput(
            compressed,
            CompressionResult(
                summary=summary,
                tokens_before=old_tokens,
                tokens_after=new_tokens,
                pairs_compressed=len(old_msgs),
                compression_type=compression_type,
            ),
            summarized_messages=list(old_msgs),
        )
    
    def _pair_messages(self, messages: List[Any]) -> List[List[Any]]:
        """将消息配对"""
        pairs = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                pair = [msg]
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    if hasattr(next_msg, 'tool_calls') and next_msg.tool_calls:
                        break
                    pair.append(next_msg)
                    j += 1
                pairs.append(pair)
                i = j
            else:
                pairs.append([msg])
                i += 1
        return pairs
    
    def _get_summary_prompt(self) -> str:
        """获取摘要提示词（带缓存）"""
        if self._summary_prompt_cache is not None:
            return self._summary_prompt_cache
        
        if self.summary_prompt_path and os.path.exists(self.summary_prompt_path):
            with open(self.summary_prompt_path, 'r', encoding='utf-8') as f:
                self._summary_prompt_cache = f.read()
        else:
            self._summary_prompt_cache = self._get_default_summary_prompt()
        
        return self._summary_prompt_cache
    
    def _get_default_summary_prompt(self) -> str:
        """获取默认摘要提示词"""
        return """你是一个专门用于压缩对话历史的 AI 助手。

生成一个结构化摘要，包含：
1. 核心任务目标
2. 关键决策
3. 工具使用
4. 重要结果
5. 保留上下文

格式要求：
- 使用简洁的短句
- 用 `|` 分隔不同部分
- 总长度不超过 {max_chars} 字符
- 使用中文输出"""
    
    def _merge_prior_history_summary(self, old_msgs: List[Any], summary: str, max_chars: int) -> str:
        """把上一代摘要正文并入新摘要，保证压缩链单调累积（输出单条、不叠多条）。

        超预算时保留头部（上一代摘要是密度更高的既有压缩产物），新提取内容
        尾部截断；LLM 已携带前代内容时去重跳过。
        """
        prior_notices = [
            message for message in old_msgs if _is_history_summary_notice(message)
        ]
        if not prior_notices:
            return summary
        prior_text = _history_summary_notice_payload(prior_notices[-1])
        if not prior_text:
            return summary
        new_text = str(summary or "").strip()
        if not new_text:
            return prior_text[:max_chars]
        if prior_text in new_text:
            return new_text
        combined = f"{prior_text}\n{new_text}"
        if len(combined) <= max_chars:
            return combined
        return combined[: max(0, max_chars - 3)] + "..."

    def _generate_summary(
        self,
        messages: List[Any],
        max_chars: int,
        reason: str = "",
        use_llm: bool = True,
        llm_summary_reporter: Any = None,
    ) -> str:
        """生成摘要。use_llm=False 时跳过 LLM，直接用规则提取。

        llm_summary_reporter 仅在真实尝试 LLM 摘要时回调：失败传 on_failure
        （含错误摘要文本），成功传 on_success；未尝试时不回调，避免把
        「没有 LLM 尝试」误计成熔断的成败。
        """
        if not messages:
            return ""

        if self.compression_llm and use_llm:
            try:
                summary = self._generate_llm_summary(messages, max_chars, reason)
            except Exception as e:
                if llm_summary_reporter is not None:
                    try:
                        llm_summary_reporter.on_failure(str(e))
                    except Exception:
                        pass
                logging.warning(f"LLM 摘要生成失败，回退到规则摘要: {e}")
                return self._rule_based_summary(messages, max_chars)
            if llm_summary_reporter is not None:
                try:
                    llm_summary_reporter.on_success()
                except Exception:
                    pass
            return summary

        # 回退到基于规则的摘要
        return self._rule_based_summary(messages, max_chars)

    def _rule_based_summary(self, messages: List[Any], max_chars: int) -> str:
        """基于规则的简单摘要生成（增强版：集成关键信息提取）"""
        if not messages:
            return ""

        # 尝试导入并使用关键信息提取器
        try:
            from tools.key_info_extractor import get_key_info_extractor
            extractor = get_key_info_extractor()
            key_info_summary = extractor.extract_key_info_summary(messages)
            if key_info_summary:
                # 关键信息摘要
                summary = key_info_summary
                if len(summary) <= max_chars:
                    return summary
        except ImportError:
            pass

        # 回退到原有的摘要生成逻辑
        summary_parts = []
        remaining = max_chars - 50  # 留空间给前缀和省略号

        # 收集工具调用
        tool_calls = []
        for msg in messages:
            for tool_call in _message_tool_calls(msg):
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                name = str(tool_call.get("name") or function.get("name") or "unknown")
                tool_calls.append(name)

        if tool_calls:
            unique_tools = list(dict.fromkeys(tool_calls))[:10]  # 去重，最多10个
            summary_parts.append(f"使用的工具: {', '.join(unique_tools)}")

        # 收集外部任务输入
        external_request_msgs = []
        for msg in messages:
            content_text = _message_content_text(msg)
            if is_external_request_message(msg) or _is_provider_user_message(msg):
                content = content_text[:100]
                if content:
                    external_request_msgs.append(content)

        if external_request_msgs:
            summary_parts.append(f"外部任务: {external_request_msgs[-1][:80]}")

        # 收集 AI 消息
        ai_contents = []
        for msg in messages:
            if _message_role(msg) == "assistant":
                content = _message_content_text(msg)
                if content and not _message_tool_calls(msg):
                    ai_contents.append(content[:80])

        if ai_contents:
            summary_parts.append(f"AI响应数: {len(ai_contents)}")

        # 组合摘要
        summary = " | ".join(summary_parts)
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."

        return summary
    
    def _generate_llm_summary(
        self,
        messages: List[Any],
        max_chars: int,
        reason: str = "",
    ) -> str:
        """使用 LLM 生成摘要"""
        compression_decision = resolve_feature_decision("context_compression")
        if not compression_decision.effective_enabled:
            raise RuntimeError(
                "context_compression is disabled by trusted operator config; "
                "compression summary LLM invocation is blocked"
            )

        # 构建消息历史文本
        history_text = self._format_messages_for_summary(messages)
        
        # 获取提示词模板
        prompt_template = self._get_summary_prompt()
        
        # 构造提示词
        prompt = prompt_template.format(max_chars=max_chars)
        runtime_input = f"## 对话历史\n\n{history_text}"
        
        if reason:
            runtime_input += f"\n\n## 压缩原因\n{reason}"
        
        # 调用 LLM
        from core.llm import LLMInvocationContext, invoke_llm

        response = invoke_llm(
            self.compression_llm,
            [
                build_cacheable_system_message(prompt),
                build_runtime_notice_message(runtime_input),
            ],
            context=LLMInvocationContext(
                surface="agent_turn",
                run_kind="agent_auxiliary",
                prompt_purpose="compression_summary",
                conversation_bound=True,
            ),
        )
        
        summary = response.content if hasattr(response, 'content') else str(response)
        
        # 截断到最大长度
        if len(summary) > max_chars:
            summary = summary[:max_chars - 3] + "..."
        
        return summary
    
    def _format_messages_for_summary(self, messages: List[Any]) -> str:
        """将消息列表格式化为摘要输入文本"""
        lines = []
        for i, msg in enumerate(messages):
            msg_type = _message_role(msg) or "unknown"
            content = _message_content_text(msg)
            
            if is_external_request_message(msg) or _is_provider_user_message(msg):
                lines.append(f"[外部输入] {content[:300]}...")
            elif msg_type == 'system':
                lines.append(f"[系统] {content[:200]}...")
            elif msg_type == 'assistant':
                tool_calls = _message_tool_calls(msg)
                if tool_calls:
                    for tc in tool_calls:
                        function = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                        name = str(tc.get("name") or function.get("name") or "unknown")
                        args = tc.get('args', tc.get("arguments", function.get("arguments", {})))
                        lines.append(f"[AI 工具调用] {name}({args})")
                else:
                    lines.append(f"[AI] {content[:300]}...")
            elif msg_type == 'tool':
                lines.append(f"[工具结果] {content[:200]}...")
            else:
                lines.append(f"[{msg_type}] {content[:150]}...")
        
        return "\n".join(lines)
    
    def get_status_report(self, messages: List[Any] = None) -> Dict[str, Any]:
        """获取状态报告"""
        current = estimate_messages_tokens(messages) if messages else 0
        return {
            "budget": self.token_budget.total_budget,
            "current_tokens": current,
            "usage_ratio": current / self.token_budget.effective_budget if current else 0,
            "compression_level": self.get_compression_level(current),
            "thresholds": {
                "warning": self.warning_threshold,
                "trigger": self.trigger_threshold,
                "critical": self.critical_threshold,
            },
            "stats": self.stats.get_stats(),
        }


# ============================================================================
# 便捷函数
# ============================================================================

def create_compressor(
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    max_history_pairs: int = MAX_HISTORY_PAIRS,
    compression_llm: Any = None,
    enable_preemptive: bool = True,
) -> EnhancedTokenCompressor:
    """创建压缩器"""
    return EnhancedTokenCompressor(
        token_budget=token_budget,
        max_history_pairs=max_history_pairs,
        compression_llm=compression_llm,
        enable_preemptive=enable_preemptive,
    )


def truncate_by_priority(
    content: Any,
    priority: MessagePriority = None,
    max_chars: int = None,
) -> str:
    """根据优先级截断内容"""
    if isinstance(content, list) and priority is None:
        if not content:
            return ""
        budget = max_chars if max_chars is not None else 1000
        ordered = sorted(content, key=lambda item: item[0])
        parts: List[str] = []
        used = 0
        for item_priority, item_content in ordered:
            text = "" if item_content is None else str(item_content)
            separator = "\n" if parts else ""
            remaining = budget - used - len(separator)
            if remaining <= 0:
                break
            if len(text) > remaining:
                if item_priority <= MessagePriority.HIGH and remaining > 0:
                    parts.append(separator + text[:remaining])
                    used = budget
                continue
            parts.append(separator + text)
            used += len(separator) + len(text)
        return "".join(parts)[:budget]

    if content is None:
        return ""
    content = str(content)
    if priority is None:
        priority = MessagePriority.MEDIUM
    if max_chars is None:
        max_chars = {
            MessagePriority.CRITICAL: 99999,  # 几乎不截断
            MessagePriority.HIGH: 800,
            MessagePriority.MEDIUM: 400,
            MessagePriority.LOW: 200,
            MessagePriority.TRIVIAL: 100,
        }.get(priority, 300)
    if max_chars <= 0:
        return ""
    
    if len(content) <= max_chars:
        return content
    
    marker = "\n[...已截断]"
    if max_chars <= len(marker):
        return content[:max_chars]
    return content[:max_chars - len(marker)] + marker


def format_compression_report(compressor: Any) -> str:
    """格式化压缩报告"""
    if isinstance(compressor, TokenCompressionStats):
        stats_obj = compressor
        stats = stats_obj.get_stats()
        total_budget = DEFAULT_TOKEN_BUDGET
        effective_budget = DEFAULT_TOKEN_BUDGET
        warning_threshold = trigger_threshold = critical_threshold = 0
    else:
        stats_obj = compressor.stats
        stats = stats_obj.get_stats()
        total_budget = compressor.token_budget.total_budget
        effective_budget = compressor.token_budget.effective_budget
        warning_threshold = compressor.warning_threshold
        trigger_threshold = compressor.trigger_threshold
        critical_threshold = compressor.critical_threshold
    
    lines = [
        "=" * 50,
        "[Token压缩] 状态报告",
        "=" * 50,
        f"总预算: {total_budget}",
        f"有效预算: {effective_budget}",
        f"阈值: 警告={warning_threshold} 触发={trigger_threshold} 紧急={critical_threshold}",
        "",
        f"压缩次数: {stats.get('total_compressions', 0)}",
        f"节省Token: {stats.get('total_tokens_saved', 0)}",
        f"紧急压缩: {stats.get('emergency_count', 0)}",
        f"预压缩: {stats.get('preemptive_count', 0)}",
        f"峰值: {stats.get('peak_tokens', 0)}",
        "=" * 50,
    ]
    records = getattr(stats_obj, "compressions", [])
    if records:
        latest = records[-1]
        lines.insert(-1, f"最近: {latest.before_tokens} -> {latest.after_tokens}")
        compression_types = ", ".join(dict.fromkeys(record.compression_type for record in records))
        lines.insert(-1, f"类型: {compression_types}")

    return "\n".join(lines)


# ============================================================================
# 主动检查点/压缩请求工具 — 模型感知到上下文拥挤时可主动调用
# ============================================================================

# 模块级标志：工具设置，agent 主循环检查并执行
_compression_requested: bool = False
_compression_reason: str = ""
_compression_source: str = ""


def request_compression(reason: str = "主动压缩", *, source: str = "manual") -> str:
    """请求上下文检查点或压缩 fallback（由 compress_context_tool 调用）"""
    global _compression_requested, _compression_reason, _compression_source
    _compression_requested = True
    _compression_reason = reason
    _compression_source = str(source or "manual").strip() or "manual"
    return f"已请求上下文检查点/压缩 fallback: {reason}。原始会话历史不会被删除或改写。"


def is_compression_requested() -> bool:
    """检查是否有待执行的压缩请求（由 agent 主循环调用）"""
    return _compression_requested


def compression_request_source() -> str:
    """返回当前压缩请求的来源（provider_limit / manual），未请求时为空。"""
    return _compression_source


def consume_compression_request() -> str:
    """消费压缩请求并返回原因（由 agent 主循环调用）"""
    global _compression_requested, _compression_reason, _compression_source
    reason = _compression_reason
    _compression_requested = False
    _compression_reason = ""
    _compression_source = ""
    return reason


def compress_context_tool(reason: str = "主动压缩") -> str:
    """
    请求上下文检查点或压缩 fallback。

    当你感到上下文过长或需要整理旧证据时调用。原始会话历史不会被删除或改写；
    旧证据应通过 history_search_tool / history_fetch_tool 精确查询。

    Args:
        reason: 压缩原因（如"上下文太长"、"需要更多空间"）

    Returns:
        确认信息
    """
    return request_compression(reason)
