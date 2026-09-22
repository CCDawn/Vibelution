# -*- coding: utf-8 -*-
"""Micro-compaction tier: pressure-triggered read-time tool-result clearing.

Design borrowed from ZCode ``apps/zcode-cli/packages/core/src/compact/microcompact.ts``
(Apache-2.0; design, not code): when the token estimate enters the band between
the micro-compaction trigger and the full-compression trigger, old tool results
from whitelisted read-only tools are replaced by stable reference+preview
placeholders before the full summary compression is allowed to run.

Semantics (v1):

- trigger line: ``min(full_trigger * 0.9, full_trigger - 2000)``;
- keep the most recent N tool-call groups (default 5), clear older ones;
- groups with error results, media payloads, non-whitelisted tools or
  unresolved tool calls are skipped entirely;
- projected savings below ``min_savings_tokens`` roll the whole projection
  back (no partial replacement);
- ``tool_call``/``tool_result`` pairing structure is never altered: only tool
  message *content* is replaced and call ids stay intact.

The projection is read-time only. The ConversationLedger is never touched;
the next assembly rebuilds history from the ledger and re-derives the
projection, so the persisted transcript stays the single source of truth.
"""

from __future__ import annotations

from typing import Any, Iterable

from .tool_result_replacement import (
    TOOL_RESULT_PLACEHOLDER_HEADER,
    build_tool_result_placeholder,
)


MICRO_COMPACT_SCHEMA_VERSION = 1
DEFAULT_KEEP_RECENT_GROUPS = 5
DEFAULT_MIN_SAVINGS_TOKENS = 256
DEFAULT_PREVIEW_CHAR_LIMIT = 800

# Error-preservation convention shared with tools/token_manager.py
# (``_ERROR_KEYWORDS``): results carrying these markers are retention
# surface, never micro-compaction filler.
_ERROR_KEYWORDS: tuple[str, ...] = (
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

_MEDIA_MARKERS: tuple[str, ...] = (
    "data:image",
    "data:audio",
    "data:video",
    ";base64,",
    "![",
    "[图片",
    "[图像",
    "[截图",
    "[screenshot]",
)

_PLACEHOLDER_METADATA_KEYS = ("toolResultMicroCompact", "toolResultReplacement")


def micro_compact_trigger_tokens(full_trigger_tokens: int) -> int:
    """Return the micro-compaction trigger line for one full-compression line.

    ``min(full * 0.9, full - 2000)`` mirrors the ZCode microcompact trigger.
    Degenerate windows (full trigger at or below 2,000 tokens) disable the
    tier by returning 0.
    """

    full = max(0, int(full_trigger_tokens or 0))
    if full <= 0:
        return 0
    return max(0, min(int(full * 0.9), full - 2000))


def micro_compact_band_contains(
    current_tokens: int,
    *,
    full_trigger_tokens: int,
    micro_trigger_tokens: int | None = None,
) -> bool:
    """Return whether the estimate sits inside [micro line, full line]."""

    full = max(0, int(full_trigger_tokens or 0))
    micro = (
        micro_compact_trigger_tokens(full)
        if micro_trigger_tokens is None
        else max(0, int(micro_trigger_tokens or 0))
    )
    current = max(0, int(current_tokens or 0))
    if micro <= 0:
        return False
    return micro <= current <= full


def normalize_micro_compact_whitelist(
    whitelist: Iterable[str] | None,
) -> tuple[str, ...]:
    """Normalize an operator whitelist; empty input falls back to the default."""

    from config.models import MICRO_COMPACT_DEFAULT_TOOL_WHITELIST

    names = tuple(
        str(name or "").strip()
        for name in list(whitelist or [])
        if str(name or "").strip()
    )
    return names or tuple(MICRO_COMPACT_DEFAULT_TOOL_WHITELIST)


def empty_micro_compact_state() -> dict[str, Any]:
    return {
        "schemaVersion": MICRO_COMPACT_SCHEMA_VERSION,
        "mode": "micro_compact",
        "applied": False,
        "clearedGroups": 0,
        "clearedResults": 0,
        "tokensSaved": 0,
        "keptRecentGroups": 0,
        "skippedRecentGroups": 0,
        "skippedWhitelistGroups": 0,
        "skippedUnresolvedGroups": 0,
        "skippedErrorOrMediaGroups": 0,
        "rollbackReason": "",
        "replacements": [],
    }


def apply_micro_compact_projection(
    messages: Iterable[Any] | None,
    *,
    session_id: str = "",
    keep_recent_groups: int = DEFAULT_KEEP_RECENT_GROUPS,
    min_savings_tokens: int = DEFAULT_MIN_SAVINGS_TOKENS,
    tool_whitelist: Iterable[str] | None = None,
    preview_char_limit: int = DEFAULT_PREVIEW_CHAR_LIMIT,
    estimate_tokens: Any = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Project old whitelisted tool results onto reference+preview placeholders.

    Returns ``(projected_messages, state)``. When the projection is skipped or
    rolled back the original list contents are returned unchanged (new list
    object, same message objects) and ``state["applied"]`` stays ``False``.
    """

    source = list(messages or [])
    state = empty_micro_compact_state()
    bounded_keep = max(0, int(keep_recent_groups if keep_recent_groups is not None else DEFAULT_KEEP_RECENT_GROUPS))
    bounded_min_savings = max(0, int(min_savings_tokens if min_savings_tokens is not None else DEFAULT_MIN_SAVINGS_TOKENS))
    whitelist = normalize_micro_compact_whitelist(tool_whitelist)
    whitelist_set = set(whitelist)
    state["keptRecentGroups"] = bounded_keep

    estimator = estimate_tokens or _default_estimate_tokens
    if estimator is None:
        state["rollbackReason"] = "estimate_unavailable"
        return source, state

    groups = _pair_preserving_groups(source)
    tool_group_indexes = [index for index, group in enumerate(groups) if _is_tool_call_group(group)]
    total_tool_groups = len(tool_group_indexes)
    # Only groups strictly older than the last N tool groups are eligible.
    recent_boundary = max(0, total_tool_groups - bounded_keep)

    clearable: list[tuple[int, list[Any], list[dict[str, Any]]]] = []
    for position, group_index in enumerate(tool_group_indexes):
        group = groups[group_index]
        if position >= recent_boundary:
            state["skippedRecentGroups"] += 1
            continue
        call_entries = _message_tool_call_entries(group[0])
        if not call_entries:
            continue
        if any(entry["name"] not in whitelist_set for entry in call_entries):
            state["skippedWhitelistGroups"] += 1
            continue
        results = [message for message in group[1:] if _is_tool_result(message)]
        if not results:
            state["skippedUnresolvedGroups"] += 1
            continue
        if any(_result_is_error(message) or _result_is_media(message) or _result_is_placeholder(message) for message in results):
            state["skippedErrorOrMediaGroups"] += 1
            continue
        clearable.append((group_index, group, results))

    if not clearable:
        state["rollbackReason"] = "no_clearable_groups"
        return source, state

    replacements: list[dict[str, Any]] = []
    projected = list(source)
    replaced_indexes: set[int] = set()
    for _group_index, group, results in clearable:
        call_entries = _message_tool_call_entries(group[0])
        for result in results:
            result_index = _identity_index(projected, result)
            if result_index < 0:
                continue
            tool_call_id = _message_tool_call_id(result) or _matching_call_id(call_entries, result)
            tool_name = _resolve_tool_name(call_entries, result, tool_call_id)
            content = _message_content(result)
            placeholder, reference, digest = build_tool_result_placeholder(
                content=content,
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                preview_limit=preview_char_limit,
            )
            projected[result_index] = _with_placeholder_content(
                result,
                placeholder,
                reference=reference,
                digest=digest,
            )
            replaced_indexes.add(result_index)
            replacements.append(
                {
                    "reference": reference,
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "messageIndex": result_index,
                    "originalChars": len(content),
                    "sha256": digest,
                }
            )

    if not replacements:
        state["rollbackReason"] = "no_clearable_groups"
        return source, state

    tokens_before = _safe_estimate(estimator, source)
    tokens_after = _safe_estimate(estimator, projected)
    if tokens_before is None or tokens_after is None:
        state["rollbackReason"] = "estimate_unavailable"
        return source, state
    savings = max(0, int(tokens_before) - int(tokens_after))
    if savings < bounded_min_savings:
        state["rollbackReason"] = "min_savings_not_met"
        state["tokensSaved"] = savings
        return source, state

    state.update(
        {
            "applied": True,
            "clearedGroups": len(clearable),
            "clearedResults": len(replacements),
            "tokensSaved": savings,
            "rollbackReason": "",
            "replacements": replacements,
        }
    )
    return projected, state


def _pair_preserving_groups(messages: list[Any]) -> list[list[Any]]:
    """Group an assistant tool call with its immediately following results.

    Same pairing convention as tools/token_manager.py ``_pair_preserving_groups``
    and context_assembler.py ``_provider_history_tail_start_index``: a cut can
    never split a call from its results, so content-only projection inside one
    group keeps the provider payload structurally valid.
    """

    groups: list[list[Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        call_ids = [entry["id"] for entry in _message_tool_call_entries(message) if entry["id"]]
        if call_ids:
            group = [message]
            index += 1
            remaining = set(call_ids)
            while index < len(messages):
                candidate = messages[index]
                if not _is_tool_result(candidate):
                    break
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


def _is_tool_call_group(group: list[Any]) -> bool:
    return bool(group) and bool(_message_tool_call_entries(group[0]))


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").strip().lower()
    role = str(getattr(message, "type", "") or getattr(message, "role", "") or "").strip().lower()
    if role == "ai":
        return "assistant"
    return role


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content or "")


def _message_tool_call_entries(message: Any) -> list[dict[str, Any]]:
    """Return ``{id, name}`` entries for an assistant message's tool calls."""

    if isinstance(message, dict):
        raw = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw = getattr(message, "tool_calls", None) or []
    entries: list[dict[str, Any]] = []
    for item in list(raw or []):
        if not isinstance(item, dict):
            continue
        call_id = str(
            item.get("id")
            or item.get("tool_call_id")
            or item.get("toolCallId")
            or ""
        ).strip()
        function_block = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(
            item.get("name")
            or item.get("toolName")
            or item.get("tool_name")
            or function_block.get("name")
            or ""
        ).strip()
        entries.append({"id": call_id, "name": name})
    return entries


def _is_tool_result(message: Any) -> bool:
    return _message_role(message) == "tool" and bool(_message_tool_call_id(message))


def _message_tool_call_id(message: Any) -> str:
    if isinstance(message, dict):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        return str(
            message.get("tool_call_id")
            or message.get("toolCallId")
            or metadata.get("toolCallId")
            or metadata.get("tool_call_id")
            or ""
        ).strip()
    return str(getattr(message, "tool_call_id", "") or "").strip()


def _message_metadata(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        metadata = message.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        return metadata
    additional = getattr(message, "additional_kwargs", None)
    return additional if isinstance(additional, dict) else {}


def _matching_call_id(call_entries: list[dict[str, Any]], result: Any) -> str:
    result_id = _message_tool_call_id(result)
    if result_id:
        return result_id
    return str(call_entries[0]["id"]) if call_entries and call_entries[0]["id"] else ""


def _resolve_tool_name(
    call_entries: list[dict[str, Any]],
    result: Any,
    tool_call_id: str,
) -> str:
    metadata = _message_metadata(result)
    for key in ("toolName", "tool_name"):
        name = str(metadata.get(key) or "").strip()
        if name:
            return name
    for entry in call_entries:
        if tool_call_id and entry["id"] == tool_call_id and entry["name"]:
            return entry["name"]
    for entry in call_entries:
        if entry["name"]:
            return entry["name"]
    return ""


def _result_is_error(message: Any) -> bool:
    status = str(getattr(message, "status", "") or "").strip().lower()
    if status == "error":
        return True
    metadata = _message_metadata(message)
    for key in ("semanticStatus", "semantic_status", "transportStatus", "transport_status", "status"):
        value = str(metadata.get(key) or "").strip().lower()
        if value in {"error", "failed", "timeout", "blocked"}:
            return True
    lowered = _message_content(message).lower()
    if lowered.startswith("[错误]") or lowered.startswith("error:"):
        return True
    return any(keyword in lowered for keyword in _ERROR_KEYWORDS)


def _result_is_media(message: Any) -> bool:
    lowered = _message_content(message).lower()
    return any(marker in lowered for marker in _MEDIA_MARKERS)


def _result_is_placeholder(message: Any) -> bool:
    if _message_content(message).lstrip().startswith(TOOL_RESULT_PLACEHOLDER_HEADER):
        return True
    metadata = _message_metadata(message)
    return any(key in metadata for key in _PLACEHOLDER_METADATA_KEYS)


def _with_placeholder_content(
    message: Any,
    placeholder: str,
    *,
    reference: str,
    digest: str,
) -> Any:
    if isinstance(message, dict):
        updated = dict(message)
        metadata = dict(updated.get("metadata") or {}) if isinstance(updated.get("metadata"), dict) else {}
        metadata["toolResultMicroCompact"] = {
            "reference": reference,
            "mode": "micro_compact",
            "sha256": digest,
        }
        updated["metadata"] = metadata
        updated["content"] = placeholder
        return updated
    if _message_role(message) == "tool":
        try:
            from langchain_core.messages import ToolMessage

            kwargs: dict[str, Any] = {}
            for attr in ("name", "status", "artifact"):
                value = getattr(message, attr, None)
                if value not in (None, ""):
                    kwargs[attr] = value
            return ToolMessage(
                content=placeholder,
                tool_call_id=_message_tool_call_id(message) or "tool_message",
                **kwargs,
            )
        except Exception:
            return message
    return message


def _identity_index(messages: list[Any], item: Any) -> int:
    for index, candidate in enumerate(messages):
        if candidate is item:
            return index
    return -1


def _safe_estimate(estimator: Any, messages: list[Any]) -> int | None:
    try:
        value = estimator(messages)
    except Exception:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _default_estimate_tokens(messages: list[Any]) -> int:
    from tools.token_manager import estimate_messages_tokens

    return int(estimate_messages_tokens(messages))


__all__ = [
    "DEFAULT_KEEP_RECENT_GROUPS",
    "DEFAULT_MIN_SAVINGS_TOKENS",
    "MICRO_COMPACT_SCHEMA_VERSION",
    "apply_micro_compact_projection",
    "empty_micro_compact_state",
    "micro_compact_band_contains",
    "micro_compact_trigger_tokens",
    "normalize_micro_compact_whitelist",
]
