# -*- coding: utf-8 -*-
"""Composer "next prompt" suggestions for Vibelution sessions.

Mirrors Claude Code's prompt-suggestion design (leaked v2.1.88
``promptSuggestion.ts``): after an assistant turn the composer may ask for one
short prediction of what the user would naturally type next. The generation is
a fork of the last real turn request: same client/profile/model/tools and the
same provider cache partition, with only the inherited provider prefix marked
for cache reads and two messages appended (the assistant reply plus the
suggestion instruction). Nothing is written to the conversation ledger.

Cost guard mirrors the upstream ``MAX_PARENT_UNCACHED_TOKENS`` check: when the
parent turn still has too many uncached tokens the fork is skipped instead of
paying for a cold prefix.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from core.llm.invocation import invoke_llm_outcome
from core.llm.invocation_context import LLMInvocationContext
from core.llm.turn_request_capture import PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY

_logger = logging.getLogger("vibelution.prompt_suggestion")

MAX_PARENT_UNCACHED_TOKENS = 10_000
MAX_SUGGESTION_CHARS = 100
MAX_REGISTRY_ENTRIES = 64
_UNSET = object()

PROMPT_SUGGESTION_TEXT = (
    "[SUGGESTION MODE: 预测用户接下来最可能输入什么。]\n"
    "\n"
    "先看用户最近的消息和最初的请求。\n"
    "\n"
    "你的任务是预测「用户」会输入什么，而不是你认为用户应该做什么。\n"
    "\n"
    "判断标准：用户看到后会觉得「我正想这么说」。\n"
    "\n"
    "示例：\n"
    "用户要求“修 bug 并跑测试”，bug 已修 → “跑一下测试”\n"
    "代码写完后 → “试一下”\n"
    "助手给出多个选项 → 建议用户最可能采纳的那个\n"
    "助手问是否继续 → “是” 或 “继续”\n"
    "任务完成且后续明显 → “提交” 或 “推送”\n"
    "出现错误或误解之后 → 保持沉默（让用户自己判断）\n"
    "\n"
    "要具体：“跑测试”好过“继续”。\n"
    "\n"
    "不要建议：\n"
    "- 评价类（“看起来不错”“谢谢”）\n"
    "- 提问（“那……呢？”）\n"
    "- 助手口吻（“让我……”“我会……”“这是……”）\n"
    "- 用户没有提过的新主意\n"
    "- 多句话\n"
    "\n"
    "如果下一步不明显，保持沉默。\n"
    "\n"
    "格式：2-12 个词（中文约 4-30 字），匹配用户的语言和习惯。\n"
    "只回复建议本身，不要引号、不要解释；没有建议就回复空。"
)

_ALLOWED_SINGLE_WORDS = {
    "yes",
    "yeah",
    "yep",
    "yea",
    "yup",
    "sure",
    "ok",
    "okay",
    "push",
    "commit",
    "deploy",
    "stop",
    "continue",
    "check",
    "exit",
    "quit",
    "no",
    "是",
    "好",
    "行",
    "继续",
    "停",
    "提交",
    "推送",
    "部署",
}

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_SEGMENT_SPLIT_RE = re.compile(r"\s+")


class PromptSuggestionError(RuntimeError):
    """Raised when the suggestion service cannot process the request."""


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _uncached_parent_tokens(usage: Any) -> int:
    if usage is None:
        return 0
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    cached_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    cache_creation = max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    return max(0, input_tokens - cached_tokens) + cache_creation + output_tokens


def _assistant_turn_count(session_id: str) -> int:
    from core.chat.conversation_ledger import conversation_model_messages_from_events
    from core.web.services import session_service as s

    events = s._load_session_conversation_events_cached(session_id)
    messages = conversation_model_messages_from_events(events)
    count = 0
    for message in messages:
        role = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", "")
        )
        if str(role or "").strip().lower() == "assistant":
            count += 1
    return count


def _suggestion_word_count(text: str) -> int:
    """Count CJK characters individually and latin tokens by whitespace."""

    stripped = text.strip()
    if not stripped:
        return 0
    tokens = [token for token in _SEGMENT_SPLIT_RE.split(stripped) if token]
    count = 0
    for token in tokens:
        cjk = _CJK_RE.findall(token)
        if cjk:
            count += len(cjk)
            latin = _CJK_RE.sub("", token).strip()
            if latin:
                count += 1
        else:
            count += 1
    return count


def clean_prompt_suggestion(value: Any) -> str:
    """Normalize model output into one bounded suggestion line."""

    text = _coerce_text(value).strip()
    if not text:
        return ""
    text = text.strip("\"'“”‘’`").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def suggestion_suppression_reason(suggestion: str) -> str:
    """Mirror the upstream filter list; return "" when the suggestion passes."""

    if not suggestion:
        return "empty"
    lower = suggestion.lower()
    word_count = _suggestion_word_count(suggestion)

    if lower == "done":
        return "done"
    if (
        lower in {"nothing found", "nothing found.", "没有建议", "无建议", "沉默"}
        or lower.startswith("nothing to suggest")
        or lower.startswith("no suggestion")
        or "没有建议" in lower
        or "无建议" in lower
        or re.search(r"\bsilence is\b|\bstay(s|ing)? silent\b", lower)
        or re.match(r"^\W*silence\W*$", lower)
    ):
        return "meta_text"
    if re.match(r"^\(.*\)$|^\[.*\]$", suggestion):
        return "meta_wrapped"
    if (
        lower.startswith("api error:")
        or lower.startswith("prompt is too long")
        or lower.startswith("request timed out")
        or lower.startswith("invalid api key")
        or lower.startswith("image was too large")
    ):
        return "error_message"
    if re.match(r"^\w{1,12}\s*[:：]\s*", suggestion):
        return "prefixed_label"
    if word_count < 2:
        if suggestion.startswith("/") or lower in _ALLOWED_SINGLE_WORDS:
            return ""
        return "too_few_words"
    if word_count > 12:
        return "too_many_words"
    if len(suggestion) >= MAX_SUGGESTION_CHARS:
        return "too_long"
    if re.search(r"[.!?。！？]\s*[A-Z\u4e00-\u9fff]", suggestion):
        return "multiple_sentences"
    if re.search(r"[\n*]|\*\*", suggestion):
        return "has_formatting"
    if re.search(
        r"thanks|thank you|looks good|sounds good|that works|that worked|that's all|nice|great|perfect|makes sense|awesome|excellent|谢谢|感谢|看起来不错|看起来很好|不错|很好|太好了|没问题|可以了|完美",
        lower,
    ):
        return "evaluative"
    if re.match(
        r"^(let me|i'll|i've|i'm|i can|i would|i think|i notice|here's|here is|here are|that's|this is|this will|you can|you should|you could|sure,|of course|certainly|让我|我来|我会|我认为|这是|这里是|你可以|你应该|当然)",
        suggestion,
        re.IGNORECASE,
    ):
        return "claude_voice"
    return ""


# ---------------------------------------------------------------------------
# Per-session capture registry
# ---------------------------------------------------------------------------

_CAPTURES: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_CAPTURE_LOCK = threading.RLock()


def register_prompt_suggestion_capture(
    *,
    session_id: str,
    turn_id: str,
    capture: dict[str, Any],
    reply: str,
) -> None:
    """Keep the last turn's fork material for a later on-demand request."""

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    client = capture.get("client") if isinstance(capture, dict) else None
    messages = capture.get("messages") if isinstance(capture, dict) else None
    if not normalized_session_id or not normalized_turn_id or client is None or not messages:
        return
    record = {
        "turnId": normalized_turn_id,
        "client": client,
        "messages": list(messages),
        "invocationContext": capture.get("invocationContext"),
        "providerMessageCount": int(capture.get("providerMessageCount") or 0),
        "usage": capture.get("usage"),
        "outcomeKind": str(capture.get("outcomeKind") or ""),
        "reply": str(reply or "").strip(),
        "suggestion": _UNSET,
        "reason": "",
        "createdAt": time.time(),
    }
    with _CAPTURE_LOCK:
        _CAPTURES[normalized_session_id] = record
        _CAPTURES.move_to_end(normalized_session_id)
        while len(_CAPTURES) > MAX_REGISTRY_ENTRIES:
            _CAPTURES.popitem(last=False)


def clear_prompt_suggestion_capture(session_id: str) -> None:
    with _CAPTURE_LOCK:
        _CAPTURES.pop(str(session_id or "").strip(), None)


def _get_capture(session_id: str) -> dict[str, Any] | None:
    with _CAPTURE_LOCK:
        return _CAPTURES.get(str(session_id or "").strip())


def _record_result(
    session_id: str,
    record: dict[str, Any],
    *,
    suggestion: str | None,
    reason: str,
) -> dict[str, Any]:
    with _CAPTURE_LOCK:
        current = _CAPTURES.get(str(session_id or "").strip())
        if current is record:
            record["suggestion"] = suggestion
            record["reason"] = reason
    return {
        "turnId": str(record.get("turnId") or ""),
        "suggestion": suggestion,
        "reason": reason,
    }


def _build_fork_context(session_id: str, record: dict[str, Any]) -> LLMInvocationContext:
    parent_context = record.get("invocationContext")
    provider_count = max(0, int(record.get("providerMessageCount") or 0))
    metadata = {
        PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY: provider_count,
        "turnId": str(record.get("turnId") or ""),
        "promptSuggestion": True,
    }
    return LLMInvocationContext(
        surface=str(getattr(parent_context, "surface", "") or "chat_turn"),
        run_kind="composer_suggestion",
        session_id=str(session_id or "").strip(),
        agent_id=str(getattr(parent_context, "agent_id", "") or ""),
        llm_slot=str(getattr(parent_context, "llm_slot", "") or "dialogue"),
        model_id=str(getattr(parent_context, "model_id", "") or ""),
        cache_scope=str(getattr(parent_context, "cache_scope", "") or ""),
        cache_partition=str(getattr(parent_context, "cache_partition", "") or ""),
        prompt_purpose="main_reply",
        conversation_bound=True,
        metadata=metadata,
    )


def generate_prompt_suggestion(
    session_id: str,
    *,
    after_turn_id: str = "",
) -> dict[str, Any]:
    """Return one composer suggestion for the session's last finished turn."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise PromptSuggestionError("session id is required")
    record = _get_capture(normalized_session_id)
    if record is None:
        return {"turnId": str(after_turn_id or ""), "suggestion": None, "reason": "no_capture"}
    expected_turn_id = str(after_turn_id or "").strip()
    if expected_turn_id and expected_turn_id != str(record.get("turnId") or ""):
        return {"turnId": expected_turn_id, "suggestion": None, "reason": "stale_turn"}
    if record.get("suggestion") is not _UNSET:
        return {
            "turnId": str(record.get("turnId") or ""),
            "suggestion": record.get("suggestion"),
            "reason": str(record.get("reason") or "cached"),
        }
    if str(record.get("outcomeKind") or "") != "final_answer":
        return _record_result(
            normalized_session_id,
            record,
            suggestion=None,
            reason="incomplete_turn",
        )
    if _uncached_parent_tokens(record.get("usage")) > MAX_PARENT_UNCACHED_TOKENS:
        return _record_result(normalized_session_id, record, suggestion=None, reason="cache_cold")
    if not str(record.get("reply") or "").strip():
        return _record_result(normalized_session_id, record, suggestion=None, reason="empty_reply")
    try:
        if _assistant_turn_count(normalized_session_id) < 2:
            return _record_result(
                normalized_session_id,
                record,
                suggestion=None,
                reason="early_conversation",
            )
    except Exception as exc:
        _logger.warning("assistant turn count failed: %s: %s", type(exc).__name__, exc)
        return _record_result(
            normalized_session_id,
            record,
            suggestion=None,
            reason="ledger_unavailable",
        )

    fork_messages = list(record.get("messages") or [])
    fork_messages.append(AIMessage(content=str(record.get("reply") or "")))
    fork_messages.append(HumanMessage(content=PROMPT_SUGGESTION_TEXT))
    context = _build_fork_context(normalized_session_id, record)
    try:
        outcome = invoke_llm_outcome(record["client"], fork_messages, context=context)
    except Exception as exc:
        _logger.warning(
            "prompt suggestion generation failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return _record_result(
            normalized_session_id,
            record,
            suggestion=None,
            reason="generation_failed",
        )
    suggestion = clean_prompt_suggestion(getattr(outcome, "final_text", ""))
    reason = suggestion_suppression_reason(suggestion)
    if reason:
        return _record_result(
            normalized_session_id,
            record,
            suggestion=None,
            reason=f"filtered:{reason}",
        )
    return _record_result(normalized_session_id, record, suggestion=suggestion, reason="ok")


__all__ = [
    "MAX_PARENT_UNCACHED_TOKENS",
    "MAX_SUGGESTION_CHARS",
    "PROMPT_SUGGESTION_TEXT",
    "PromptSuggestionError",
    "clean_prompt_suggestion",
    "clear_prompt_suggestion_capture",
    "generate_prompt_suggestion",
    "register_prompt_suggestion_capture",
    "suggestion_suppression_reason",
]
