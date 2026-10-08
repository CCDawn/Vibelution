# -*- coding: utf-8 -*-
"""Recover a failed model stream from the last committed tool result.

A retryable stream failure starts a new model request. Tool results that
already landed — including tool errors — stay in history and are not run
again. Text and reasoning that never committed after that anchor are dropped.
When nothing was committed, the uncommitted assistant tail is dropped and the
next request starts from the previous message. This is the session fact, not
a second transcript.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Iterable, Mapping


STREAM_RECOVERY_MAX_RETRIES = 10
PREVIOUS_MESSAGE_ANCHOR_SUFFIX = "previous-message-anchor"
REASON_LATEST_TOOL = "latest_committed_tool_result"
REASON_NO_TOOL = "no_tool_committed"

_COMMITTED_TOOL_RESULTS: ContextVar[dict[str, str] | None] = ContextVar(
    "vibelution_stream_recovery_committed_tools",
    default=None,
)


def bind_committed_tool_results(results: Mapping[str, str] | None) -> None:
    """Remember tool results the current turn must not execute again."""

    cleaned: dict[str, str] = {}
    for key, value in dict(results or {}).items():
        call_id = str(key or "").strip()
        if call_id:
            cleaned[call_id] = str(value if value is not None else "")
    _COMMITTED_TOOL_RESULTS.set(cleaned)


def committed_tool_result(call_id: str) -> str | None:
    """Return the stored result for a committed call, if this turn recovered."""

    mapping = _COMMITTED_TOOL_RESULTS.get()
    if not mapping:
        return None
    key = str(call_id or "").strip()
    if not key or key not in mapping:
        return None
    return mapping[key]


def plan_stream_recovery(
    events: Iterable[Any],
    *,
    assistant_message_id: str,
    discarded_text: str = "",
    discarded_reasoning: str = "",
    retryable: bool = False,
    retry_count: int = 0,
    user_stopped: bool = False,
    failure_kind: str = "",
    category: str = "",
    message: str = "",
) -> dict[str, Any] | None:
    """Choose the recovery anchor, or return None when this failure stays put.

    Committed tool results recover even when the provider marks the error
    non-retryable: the side effect already happened. A tail with no committed
    tool recovers only when the failure itself is retryable and some
    uncommitted text or reasoning was produced. A user stop never recovers.
    """

    if user_stopped:
        return None
    used = _nonnegative(retry_count)
    if used >= STREAM_RECOVERY_MAX_RETRIES:
        return None
    assistant_id = str(assistant_message_id or "").strip() or "assistant"
    committed = committed_tool_results_from_events(events)
    text_bytes = _utf8_len(discarded_text)
    reasoning_bytes = _utf8_len(discarded_reasoning)
    if not committed and (not retryable or text_bytes + reasoning_bytes <= 0):
        return None
    ordered_ids = list(committed)
    if ordered_ids:
        latest = ordered_ids[-1]
        anchor_id = f"{assistant_id}:{latest}:tool-result"
        reason = REASON_LATEST_TOOL
    else:
        anchor_id = f"{assistant_id}:{PREVIOUS_MESSAGE_ANCHOR_SUFFIX}"
        reason = REASON_NO_TOOL
    retry_number = used + 1
    return {
        "attemptId": f"{assistant_id}:end-of-stream",
        "anchorId": anchor_id,
        "reason": reason,
        "assistantMessageId": assistant_id,
        "committedToolCallIds": ordered_ids,
        "committedResults": dict(committed),
        "discardedTextBytes": text_bytes,
        "discardedReasoningBytes": reasoning_bytes,
        "discardedToolCallIds": [],
        "retryNumber": retry_number,
        "maxRetries": STREAM_RECOVERY_MAX_RETRIES,
        "failureKind": str(failure_kind or "").strip() or classify_stream_failure(category, message),
    }


def committed_tool_results_from_events(events: Iterable[Any]) -> dict[str, str]:
    """Tool results in journal order. A tool error is committed too."""

    ordered: dict[str, str] = {}
    for event in list(events or []):
        if str(getattr(event, "event_type", "") or "").strip() != "tool_result":
            continue
        call_id = _tool_call_id(event)
        if not call_id:
            continue
        # Reinsert so the latest write of a repeated id is the anchor.
        if call_id in ordered:
            del ordered[call_id]
        ordered[call_id] = _tool_result_text(event)
    return ordered


def classify_stream_failure(category: str = "", message: str = "") -> str:
    text = f"{category} {message}".lower()
    if "timeout" in text or "timed_out" in text:
        return "provider_timeout"
    if "network" in text or "connection" in text:
        return "provider_network_error"
    if str(category or "").strip() or str(message or "").strip():
        return "provider_stream_error"
    return "unknown"


def turns_with_stream_recovery(events: Iterable[Any]) -> set[str]:
    recovered: set[str] = set()
    for event in list(events or []):
        if str(getattr(event, "event_type", "") or "").strip() != "llm_resilience":
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("stage") or "").strip() != "stream_recovery":
            continue
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if turn_id:
            recovered.add(turn_id)
    return recovered


def omit_discarded_stream_tail(messages: Iterable[Any], events: Iterable[Any]) -> list[Any]:
    """Drop the uncommitted assistant tail covered by a stream-recovery fact.

    Committed assistant items and tool results stay. The open-turn replay of
    the failed partial is not appended onto the next model request.
    """

    recovered = turns_with_stream_recovery(events)
    if not recovered:
        return list(messages or [])
    kept: list[Any] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            kept.append(message)
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        turn_id = str(metadata.get("turnId") or "").strip()
        if turn_id not in recovered:
            kept.append(message)
            continue
        kind = str(metadata.get("kind") or "").strip()
        reason = str(metadata.get("reason") or "").strip()
        if kind == "journal_assistant_partial":
            continue
        if kind == "turn_interrupted" and reason == "open_turn_replay":
            continue
        kept.append(message)
    return kept


def _tool_call_id(event: Any) -> str:
    direct = str(getattr(event, "tool_call_id", "") or "").strip()
    if direct:
        return direct
    payload = getattr(event, "payload", None)
    if not isinstance(payload, Mapping):
        return ""
    tool_call = payload.get("toolCall") or payload.get("tool_call") or payload
    if not isinstance(tool_call, Mapping):
        return ""
    return str(
        tool_call.get("id")
        or tool_call.get("toolCallId")
        or tool_call.get("tool_call_id")
        or ""
    ).strip()


def _tool_result_text(event: Any) -> str:
    payload = getattr(event, "payload", None)
    if not isinstance(payload, Mapping):
        return ""
    tool_call = payload.get("toolCall") or payload.get("tool_call") or payload
    if not isinstance(tool_call, Mapping):
        tool_call = {}
    for key in ("result", "summary", "error", "content"):
        text = tool_call.get(key)
        if text is None:
            text = payload.get(key)
        if str(text or "").strip():
            return str(text)
    return str(tool_call.get("result") or payload.get("result") or "")


def _utf8_len(value: Any) -> int:
    return len(str(value or "").encode("utf-8"))


def _nonnegative(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0
