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

When the projection applies, the working-set re-injection stage (borrowed
from ZCode ``runtime/helpers/compact-post-reminders.ts``; design, not code)
rebuilds the most recently read working-set files from the cleared
``read_file_tool`` groups as synthetic system-role Read reminders appended to
the projected list: at most 5 files, one file capped at 5k estimated tokens
and the whole batch at 50k; anything over the limits degrades to a one-line
"re-read with read_file_tool" pointer. Files whose reads are still live in
the preserved tail are skipped, ``.git`` paths are excluded, and paths are
deduplicated keeping the latest read. The reminders carry the shared
reference + sha256 + tool_call_id recoverability contract, contain no
wall-clock data, and are therefore deterministic per input: the next
assembly rebuilds the same view.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .tool_result_replacement import (
    TOOL_RESULT_PLACEHOLDER_HEADER,
    build_tool_result_placeholder,
)


MICRO_COMPACT_SCHEMA_VERSION = 1
DEFAULT_KEEP_RECENT_GROUPS = 5
DEFAULT_MIN_SAVINGS_TOKENS = 256
DEFAULT_PREVIEW_CHAR_LIMIT = 800

DEFAULT_REINJECTION_MAX_FILES = 5
DEFAULT_REINJECTION_MAX_FILE_TOKENS = 5_000
DEFAULT_REINJECTION_MAX_TOTAL_TOKENS = 50_000
# Working-set re-injection restores *file* reads; search/list results carry
# no single-file content, so only the file-reading tool re-enters context.
WORKING_SET_REINJECTION_TOOL = "read_file_tool"
WORKING_SET_REINJECTION_HEADER = "[工作集文件重注入]"

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
        "reinjection": empty_working_set_reinjection_state(),
        "tokenMetering": {"tokenSource": "estimate"},
    }


def empty_working_set_reinjection_state() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mode": "working_set_reinjection",
        "injectedFiles": [],
        "downgradedFiles": [],
        "skippedPreservedPaths": [],
        "skippedGitPathCount": 0,
        "totalTokens": 0,
        "entries": [],
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
    reinjection_enabled: bool = True,
    reinjection_max_files: int = DEFAULT_REINJECTION_MAX_FILES,
    reinjection_max_file_tokens: int = DEFAULT_REINJECTION_MAX_FILE_TOKENS,
    reinjection_max_total_tokens: int = DEFAULT_REINJECTION_MAX_TOTAL_TOKENS,
) -> tuple[list[Any], dict[str, Any]]:
    """Project old whitelisted tool results onto reference+preview placeholders.

    Returns ``(projected_messages, state)``. When the projection is skipped or
    rolled back the original list contents are returned unchanged (new list
    object, same message objects) and ``state["applied"]`` stays ``False``.
    When it applies, the working-set re-injection stage appends synthetic
    system-role Read reminders for the cleared ``read_file_tool`` groups
    (deterministic per input; see module docstring).
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
    if reinjection_enabled:
        cleared_group_indexes = {
            group_index for group_index, _group, _results in clearable
        }
        preserved_paths = _preserved_working_set_paths(
            groups,
            tool_group_indexes,
            cleared_group_indexes,
        )
        reinjection_state = build_working_set_reinjection(
            clearable,
            preserved_paths=preserved_paths,
            session_id=session_id,
            max_files=reinjection_max_files,
            max_file_tokens=reinjection_max_file_tokens,
            max_total_tokens=reinjection_max_total_tokens,
        )
        state["reinjection"] = reinjection_state
        projected.extend(reinjection_state["entries"])
    return projected, state


def build_working_set_reinjection(
    clearable: list[tuple[int, list[Any], list[dict[str, Any]]]],
    *,
    preserved_paths: set[str],
    session_id: str = "",
    max_files: int = DEFAULT_REINJECTION_MAX_FILES,
    max_file_tokens: int = DEFAULT_REINJECTION_MAX_FILE_TOKENS,
    max_total_tokens: int = DEFAULT_REINJECTION_MAX_TOTAL_TOKENS,
) -> dict[str, Any]:
    """Build the deterministic working-set re-injection for cleared file reads.

    ``clearable`` carries the pre-replacement groups, so the original file
    contents are still available here. Candidates come from cleared
    ``read_file_tool`` calls only; paths still live in the preserved tail
    (``preserved_paths``) are skipped, ``.git`` paths are excluded, and a path
    read several times keeps only its latest content. Selection is
    most-recent-first, capped at ``max_files``; a file over
    ``max_file_tokens`` estimated tokens, or that would push the batch over
    ``max_total_tokens``, degrades to a one-line re-read pointer.
    """

    state = empty_working_set_reinjection_state()
    bounded_max_files = max(
        0, int(max_files if max_files is not None else DEFAULT_REINJECTION_MAX_FILES)
    )
    bounded_file_limit = max(
        0,
        int(
            max_file_tokens
            if max_file_tokens is not None
            else DEFAULT_REINJECTION_MAX_FILE_TOKENS
        ),
    )
    bounded_total_limit = max(
        0,
        int(
            max_total_tokens
            if max_total_tokens is not None
            else DEFAULT_REINJECTION_MAX_TOTAL_TOKENS
        ),
    )

    candidates: dict[str, dict[str, Any]] = {}
    for group_index, group, results in clearable:
        for entry in _message_tool_call_args(group[0]):
            if str(entry.get("name") or "").strip() != WORKING_SET_REINJECTION_TOOL:
                continue
            args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
            path = str(args.get("file_path") or args.get("path") or "").strip()
            if not path:
                continue
            normalized = _normalize_reinjection_path(path)
            if "/.git/" in f"/{normalized}":
                state["skippedGitPathCount"] += 1
                continue
            if normalized in preserved_paths:
                if normalized not in state["skippedPreservedPaths"]:
                    state["skippedPreservedPaths"].append(normalized)
                continue
            content = _cleared_group_result_content(entry, group, results)
            if not str(content or "").strip():
                continue
            # Later reads of the same path win: the dict is overwritten in
            # group order, so the last (most recent) read is kept.
            candidates[normalized] = {
                "path": path,
                "normalizedPath": normalized,
                "content": str(content or ""),
                "toolCallId": str(entry.get("id") or ""),
                "order": group_index,
            }

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-int(item["order"]), str(item["normalizedPath"])),
    )
    total_tokens = 0
    for candidate in ordered[:bounded_max_files]:
        content = candidate["content"]
        approx_tokens = _estimate_content_tokens(content)
        if (
            approx_tokens > bounded_file_limit
            or total_tokens + approx_tokens > bounded_total_limit
        ):
            state["downgradedFiles"].append(candidate["path"])
            state["entries"].append(_build_reinjection_pointer_message(candidate))
            continue
        total_tokens += approx_tokens
        state["injectedFiles"].append(candidate["path"])
        state["entries"].append(
            _build_reinjection_message(
                candidate,
                session_id=session_id,
            )
        )
    state["totalTokens"] = int(total_tokens)
    return state


def append_working_set_reminders(
    messages: list[Any],
    entries: Iterable[Any],
) -> list[Any]:
    """Append reminder entries, skipping files whose reads are live again.

    Deterministic post-filter for call sites that re-derive the message list
    between projection and send (chat-mode ledger replay restores original
    tool results): an entry whose ``toolCallId`` is present on a
    non-placeholder tool result in ``messages`` is dropped instead of
    duplicating live content. Entries are plain data, so re-running on the
    same inputs yields the same list.
    """

    live_call_ids: set[str] = set()
    for message in list(messages or []):
        if _message_role(message) != "tool" or _result_is_placeholder(message):
            continue
        call_id = _message_tool_call_id(message)
        if call_id:
            live_call_ids.add(call_id)
    result = list(messages or [])
    for entry in list(entries or []):
        metadata = entry.get("metadata") if isinstance(entry, dict) else {}
        payload = (
            metadata.get("workingSetReinjection")
            if isinstance(metadata, dict)
            else {}
        )
        call_id = (
            str(payload.get("toolCallId") or "") if isinstance(payload, dict) else ""
        )
        if call_id and call_id in live_call_ids:
            continue
        result.append(entry)
    return result


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


def _message_tool_call_args(message: Any) -> list[dict[str, Any]]:
    """Return ``{id, name, args}`` entries; ``args`` is parsed lazily.

    Covers both shapes the projection sees: OpenAI-style dicts with
    ``function.arguments`` JSON strings and LangChain ``AIMessage.tool_calls``
    with an ``args`` mapping. Malformed arguments degrade to an empty mapping
    so the candidate is skipped, never raised.
    """

    if isinstance(message, dict):
        raw_items = list(message.get("tool_calls") or message.get("toolCalls") or [])
    else:
        raw_items = list(getattr(message, "tool_calls", None) or [])
    entries: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        function_block = (
            raw.get("function") if isinstance(raw.get("function"), dict) else {}
        )
        call_id = str(
            raw.get("id")
            or raw.get("tool_call_id")
            or raw.get("toolCallId")
            or ""
        ).strip()
        name = str(
            raw.get("name")
            or raw.get("toolName")
            or raw.get("tool_name")
            or function_block.get("name")
            or ""
        ).strip()
        raw_args = raw.get("args")
        if raw_args is None:
            raw_args = function_block.get("arguments")
        if raw_args is None:
            raw_args = raw.get("arguments")
        entries.append(
            {
                "id": call_id,
                "name": name,
                "args": _coerce_args_mapping(raw_args),
            }
        )
    return entries


def _coerce_args_mapping(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _cleared_group_result_content(
    entry: dict[str, Any],
    group: list[Any],
    results: list[Any],
) -> str:
    """Original content of the cleared result belonging to one call entry."""

    call_id = str(entry.get("id") or "").strip()
    for message in results:
        if call_id and _message_tool_call_id(message) == call_id:
            return _message_content(message)
    for message in group[1:]:
        if _is_tool_result(message) and (
            not call_id or _message_tool_call_id(message) == call_id
        ):
            return _message_content(message)
    return ""


def _preserved_working_set_paths(
    groups: list[list[Any]],
    tool_group_indexes: list[int],
    cleared_group_indexes: set[int],
) -> set[str]:
    """Normalized paths whose read results are still live (never cleared).

    Covers both "still inside the kept recent tail" and "older but skipped
    from clearing (whitelist/error/media)": in both cases the original
    content stays in the projection output, so a synthetic reminder would
    duplicate live context.
    """

    preserved: set[str] = set()
    for group_index in tool_group_indexes:
        if group_index in cleared_group_indexes:
            continue
        for entry in _message_tool_call_args(groups[group_index][0]):
            if str(entry.get("name") or "").strip() != WORKING_SET_REINJECTION_TOOL:
                continue
            args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
            path = str(args.get("file_path") or args.get("path") or "").strip()
            if path:
                preserved.add(_normalize_reinjection_path(path))
    return preserved


def _normalize_reinjection_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _estimate_content_tokens(content: str) -> int:
    """Estimated tokens under the shared token-manager convention."""

    from tools.token_manager import estimate_tokens_precise

    try:
        return max(0, int(estimate_tokens_precise(str(content or ""))))
    except Exception:
        return max(0, len(str(content or "")) // 4)


def _build_reinjection_message(
    candidate: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    content = candidate["content"]
    _placeholder, reference, digest = build_tool_result_placeholder(
        content=content,
        session_id=session_id,
        tool_call_id=candidate["toolCallId"],
        tool_name=WORKING_SET_REINJECTION_TOOL,
        preview_limit=0,
    )
    body = "\n".join(
        [
            WORKING_SET_REINJECTION_HEADER,
            f"文件: {candidate['path']}",
            f"引用: {reference}",
            f"工具调用ID: {candidate['toolCallId']}",
            f"原始SHA256: {digest}",
            "说明: 以下为微压缩前最近一次读取的文件内容；"
            "需要完整重读时用 read_file_tool。",
            "文件内容:",
            content,
        ]
    )
    return {
        "role": "system",
        "content": body,
        "metadata": {
            "workingSetReinjection": {
                "mode": "full",
                "path": candidate["path"],
                "reference": reference,
                "sha256": digest,
                "toolCallId": candidate["toolCallId"],
            }
        },
    }


def _build_reinjection_pointer_message(candidate: dict[str, Any]) -> dict[str, Any]:
    body = (
        f"{WORKING_SET_REINJECTION_HEADER} 文件 {candidate['path']} 在微压缩前被读取，"
        "内容过大未随上下文恢复；需要时用 read_file_tool 重读。"
    )
    return {
        "role": "system",
        "content": body,
        "metadata": {
            "workingSetReinjection": {
                "mode": "pointer",
                "path": candidate["path"],
                "toolCallId": candidate["toolCallId"],
            }
        },
    }


__all__ = [
    "DEFAULT_KEEP_RECENT_GROUPS",
    "DEFAULT_MIN_SAVINGS_TOKENS",
    "DEFAULT_PREVIEW_CHAR_LIMIT",
    "DEFAULT_REINJECTION_MAX_FILES",
    "DEFAULT_REINJECTION_MAX_FILE_TOKENS",
    "DEFAULT_REINJECTION_MAX_TOTAL_TOKENS",
    "MICRO_COMPACT_SCHEMA_VERSION",
    "WORKING_SET_REINJECTION_HEADER",
    "WORKING_SET_REINJECTION_TOOL",
    "append_working_set_reminders",
    "apply_micro_compact_projection",
    "build_working_set_reinjection",
    "empty_micro_compact_state",
    "empty_working_set_reinjection_state",
    "micro_compact_band_contains",
    "micro_compact_trigger_tokens",
    "normalize_micro_compact_whitelist",
]
