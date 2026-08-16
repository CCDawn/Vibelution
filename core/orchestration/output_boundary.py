# -*- coding: utf-8 -*-
"""Shared boundary for LLM protocol text before UI or persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_NAMED_PROTOCOL_TAGS = (
    "state",
    "active_components",
    "invoke",
    "parameter",
)

_COMPLETE_PROTOCOL_TAG_NAMES = _NAMED_PROTOCOL_TAGS + (
    "tool_call",
    "think",
    "thinking",
)

_BRACKET_CONTROL_MARKER_RE = re.compile(
    r"(?im)^[ \t]*\[(?:outcome|task_outcome|status)\s*=\s*[^\]\r\n]*\][ \t]*(?:\r?\n|$)"
)
_BARE_CONTROL_MARKER_RE = re.compile(
    r"(?im)^[ \t]*(?:outcome|task_outcome|status)\s*=\s*(?:done|success|failed|ready|blocked|needs_input|progress)[ \t]*(?:\r?\n|$)"
)
_EMPTY_CONTENT_SANITISED_RE = re.compile(
    r"(?im)^[ \t]*\[System:\s*Empty message content saniti[sz]ed to satisfy protocol\][ \t]*(?:\r?\n|$)"
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in (
            "content",
            "text",
            "delta",
            "visible",
            "thought",
            "visibleText",
            "thoughtText",
        ):
            nested = value.get(key)
            if nested is not None and nested is not value:
                return _coerce_text(nested)
        return ""
    if isinstance(value, (list, tuple)):
        return "".join(_coerce_text(item) for item in value)
    content = getattr(value, "content", None)
    if content is not None and content is not value:
        return _coerce_text(content)
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _coerce_name_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Mapping):
        return ()
    try:
        names = tuple(
            text for text in (_coerce_text(item).strip() for item in value) if text
        )
        return names
    except TypeError:
        text = _coerce_text(value).strip()
        return (text,) if text else ()


def _strip_think_blocks(text: str) -> str:
    cleaned = re.sub(
        r"<(?:think|thinking)\b[^>]*>[\s\S]*?</(?:think|thinking)\s*>",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<(?:think|thinking)\b[^>]*(?:>[\s\S]*)?$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", cleaned, flags=re.IGNORECASE)
    return _strip_trailing_partial_protocol_tag(cleaned, extra_prefixes=("thi", "think", "thinking"))


def _strip_think_tags_keep_body(text: str) -> str:
    cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", text or "", flags=re.IGNORECASE)
    return _strip_trailing_partial_protocol_tag(cleaned, extra_prefixes=("thi", "think", "thinking"))


def strip_llm_protocol_artifacts(value: Any, *, trim: bool = True) -> str:
    """Remove internal protocol/control markup while preserving normal text."""

    text = _coerce_text(value)
    if not text:
        return ""

    for tag in _NAMED_PROTOCOL_TAGS:
        text = re.sub(
            rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>",
            "",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"<[\w:.-]*tool_call\b[^>]*>[\s\S]*?</[\w:.-]*tool_call\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<[^>\n]*DSML[^>]*>[\s\S]*?</[^>\n]*DSML[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    for tag in _NAMED_PROTOCOL_TAGS:
        text = re.sub(
            rf"<{tag}\b[^>]*(?:>[\s\S]*)?$",
            "",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"<[\w:.-]*tool_call\b[^>]*(?:>[\s\S]*)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<[^>\n]*DSML[^>\n]*(?:>[\s\S]*)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"</?(?:state|active_components|invoke|parameter)[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"</?[\w:.-]*tool_call[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[^>\n]*DSML[^>]*>", "", text, flags=re.IGNORECASE)
    text = _EMPTY_CONTENT_SANITISED_RE.sub("", text)
    text = _BRACKET_CONTROL_MARKER_RE.sub("", text)
    text = _BARE_CONTROL_MARKER_RE.sub("", text)

    text = _strip_trailing_partial_protocol_tag(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() if _coerce_bool(trim, default=True) else text


def sanitize_assistant_visible_text(value: Any) -> str:
    """Return assistant text safe for UI display and chat-state persistence."""

    text = _strip_think_blocks(_coerce_text(value))
    return strip_llm_protocol_artifacts(text)


def sanitize_assistant_visible_delta_text(value: Any) -> str:
    """Return streamed visible text without trimming token-boundary spaces."""

    text = _strip_think_blocks(_coerce_text(value))
    return strip_llm_protocol_artifacts(text, trim=False)


def sanitize_assistant_thought_text(value: Any) -> str:
    """Return thought text with protocol blocks removed but thought body kept."""

    text = _strip_think_tags_keep_body(_coerce_text(value))
    return strip_llm_protocol_artifacts(text)


def sanitize_assistant_thought_delta_text(value: Any) -> str:
    """Return streamed thought text without trimming token-boundary spaces."""

    text = _strip_think_tags_keep_body(_coerce_text(value))
    return strip_llm_protocol_artifacts(text, trim=False)


def _is_trailing_protocol_fragment(normalized: str, extra_names: tuple[str, ...] = ()) -> bool:
    if "dsml" in normalized:
        return True
    token = normalized.split()[0].strip().lstrip("/").strip()
    if not token:
        return True
    names = _COMPLETE_PROTOCOL_TAG_NAMES + _coerce_name_tuple(extra_names)
    return any(name.startswith(token) for name in names)


def _strip_trailing_partial_protocol_tag(text: str, *, extra_prefixes: tuple[str, ...] = ()) -> str:
    extra_prefixes = _coerce_name_tuple(extra_prefixes)
    cleaned = text or ""
    while True:
        match = re.search(r"<[^<>\n]*$", cleaned)
        if not match:
            return cleaned
        fragment = match.group(0)
        normalized = fragment[1:].strip().lower()
        if not normalized or _is_trailing_protocol_fragment(normalized, extra_prefixes):
            cleaned = cleaned[: match.start()]
            continue
        return cleaned


__all__ = [
    "sanitize_assistant_thought_delta_text",
    "sanitize_assistant_thought_text",
    "sanitize_assistant_visible_delta_text",
    "sanitize_assistant_visible_text",
    "strip_llm_protocol_artifacts",
]
