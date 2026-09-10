# -*- coding: utf-8 -*-
"""Provider-agnostic reasoning extraction for LLM responses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


TextExtractor = Callable[[Any], str]


@dataclass(frozen=True)
class ReasoningExtraction:
    text: str
    source: str = "none"


@dataclass(frozen=True)
class ThinkTagStreamResult:
    reasoning_text: str = ""
    visible_text: str = ""


REASONING_FIELD_CANDIDATES = (
    "reasoning_content_delta",
    "reasoning_delta",
    "reasoning_content",
    "reasoning",
    "thinking",
    "thought",
)

REASONING_DELTA_FIELD_CANDIDATES = (
    "reasoning_content_delta",
    "reasoning_delta",
)


_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking)\b[^>]*>([\s\S]*?)</(?:think|thinking)\s*>",
    flags=re.IGNORECASE,
)
_OPEN_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking)\b[^>]*>([\s\S]*)$",
    flags=re.IGNORECASE,
)
_THINK_TAG_RE = re.compile(r"</?(?:think|thinking)\b[^>]*>", flags=re.IGNORECASE)


REASONING_TEXT_DETAIL_TYPE = "reasoning.text"
REASONING_SUMMARY_DETAIL_TYPE = "reasoning.summary"
REASONING_ENCRYPTED_DETAIL_TYPE = "reasoning.encrypted"
THINKING_BLOCK_DETAIL_TYPE = "thinking"


def extract_reasoning_details_text(value: Any) -> str:
    """Flatten an OpenRouter-style ``reasoning_details`` array into text.

    Detail items arrive as ``{type, id?, text|summary|data, signature?, format?,
    index?}`` and are appended in arrival order. ``reasoning.text`` carries the
    full payload (``text``); ``reasoning.summary`` is only a digest
    (``summary``); ``reasoning.encrypted`` has no readable text (``data``).
    Text items win; summaries are used only when no text item exists.
    Encrypted and unknown types are skipped. Returns ``""`` when nothing is
    readable.
    """
    text_parts: list[str] = []
    summary_parts: list[str] = []
    for item in _detail_item_dicts(value):
        item_type = str(item.get("type") or "")
        if item_type == REASONING_TEXT_DETAIL_TYPE:
            text_parts.append(_detail_str(item.get("text")))
        elif item_type == REASONING_SUMMARY_DETAIL_TYPE:
            summary_parts.append(_detail_str(item.get("summary")))
    combined = "".join(text_parts)
    if combined:
        return combined
    return "".join(summary_parts)


def extract_thinking_blocks_text(value: Any) -> str:
    """Flatten a litellm-style ``thinking_blocks`` array into text.

    Elements look like ``{type: "thinking", thinking, signature}``; only the
    ``thinking`` field of ``type == "thinking"`` items is readable.
    """
    parts: list[str] = []
    for item in _detail_item_dicts(value):
        if str(item.get("type") or "") == THINKING_BLOCK_DETAIL_TYPE:
            parts.append(_detail_str(item.get("thinking")))
    return "".join(parts)


def extract_reasoning_text(
    payload: Any,
    text_extractor: TextExtractor,
    *,
    include_content_tags: bool = True,
) -> ReasoningExtraction:
    """Extract provider reasoning text from common response shapes.

    This keeps provider-specific field drift in one place. It deliberately
    avoids treating normal assistant content as reasoning unless the provider
    wrapped it in an explicit think/thinking tag.
    """
    payload_dict = _as_dict(payload)
    if not isinstance(payload_dict, dict):
        return ReasoningExtraction("")

    details_text = extract_reasoning_details_text(payload_dict.get("reasoning_details"))
    if details_text:
        return ReasoningExtraction(details_text, "reasoning_details")

    additional = payload_dict.get("additional_kwargs")
    if isinstance(additional, dict):
        details_text = extract_reasoning_details_text(additional.get("reasoning_details"))
        if details_text:
            return ReasoningExtraction(details_text, "additional_kwargs.reasoning_details")

    for key in REASONING_FIELD_CANDIDATES:
        extracted = _extract_field(payload_dict, key, text_extractor)
        if extracted:
            return ReasoningExtraction(extracted, key)

    if isinstance(additional, dict):
        for key in REASONING_FIELD_CANDIDATES:
            extracted = _extract_field(additional, key, text_extractor)
            if extracted:
                return ReasoningExtraction(extracted, f"additional_kwargs.{key}")

    thinking_blocks_text = extract_thinking_blocks_text(payload_dict.get("thinking_blocks"))
    if thinking_blocks_text:
        return ReasoningExtraction(thinking_blocks_text, "thinking_blocks")

    if isinstance(additional, dict):
        thinking_blocks_text = extract_thinking_blocks_text(additional.get("thinking_blocks"))
        if thinking_blocks_text:
            return ReasoningExtraction(thinking_blocks_text, "additional_kwargs.thinking_blocks")

    if include_content_tags:
        content = text_extractor(payload_dict.get("content") or "")
        think_text = extract_think_tag_reasoning(content)
        if think_text:
            return ReasoningExtraction(think_text, "think_tag")

    return ReasoningExtraction("")


def strip_think_tag_reasoning(content: Any, text_extractor: TextExtractor) -> str:
    """Return visible content with explicit think/thinking blocks removed."""
    text = text_extractor(content)
    if not text:
        return ""
    text = _THINK_BLOCK_RE.sub("", text)
    if re.search(r"<(?:think|thinking)\b[^>]*>", text, flags=re.IGNORECASE):
        text = _OPEN_THINK_BLOCK_RE.sub("", text)
    text = re.sub(r"</?(?:think|thinking)[^>]*>", "", text, flags=re.IGNORECASE)
    return text


def extract_think_tag_reasoning(text: str) -> str:
    if not text:
        return ""
    matches = [match.strip() for match in _THINK_BLOCK_RE.findall(text) if match.strip()]
    if matches:
        return "\n".join(matches).strip()
    open_match = _OPEN_THINK_BLOCK_RE.search(text)
    if open_match:
        return open_match.group(1).strip()
    return ""


class ThinkTagStreamParser:
    """Statefully split streamed think/thinking tags from visible content."""

    def __init__(self) -> None:
        self._inside_think = False
        self._pending = ""

    def feed(self, content: Any, text_extractor: TextExtractor) -> ThinkTagStreamResult:
        text = self._pending + text_extractor(content)
        self._pending = ""
        if not text:
            return ThinkTagStreamResult()

        reasoning_parts: list[str] = []
        visible_parts: list[str] = []
        index = 0
        while index < len(text):
            tag_start = text.find("<", index)
            if tag_start < 0:
                self._append_segment(text[index:], reasoning_parts, visible_parts)
                break
            if tag_start > index:
                self._append_segment(text[index:tag_start], reasoning_parts, visible_parts)

            tag_match = _THINK_TAG_RE.match(text, tag_start)
            if tag_match:
                tag = tag_match.group(0).lower()
                self._inside_think = not tag.startswith("</")
                index = tag_match.end()
                continue

            candidate = text[tag_start:]
            if _looks_like_partial_think_tag(candidate):
                self._pending = candidate
                break

            self._append_segment("<", reasoning_parts, visible_parts)
            index = tag_start + 1

        return ThinkTagStreamResult(
            reasoning_text="".join(reasoning_parts),
            visible_text="".join(visible_parts),
        )

    def flush(self) -> ThinkTagStreamResult:
        pending = self._pending
        self._pending = ""
        if not pending or _looks_like_partial_think_tag(pending):
            return ThinkTagStreamResult()
        if self._inside_think:
            return ThinkTagStreamResult(reasoning_text=pending)
        return ThinkTagStreamResult(visible_text=pending)

    def _append_segment(
        self,
        segment: str,
        reasoning_parts: list[str],
        visible_parts: list[str],
    ) -> None:
        if not segment:
            return
        if self._inside_think:
            reasoning_parts.append(segment)
        else:
            visible_parts.append(segment)


def _looks_like_partial_think_tag(fragment: str) -> bool:
    if not fragment.startswith("<"):
        return False
    lowered = fragment.lower()
    complete_prefixes = ("<think", "<thinking", "</think", "</thinking")
    if any(prefix.startswith(lowered) for prefix in complete_prefixes):
        return True
    return any(lowered.startswith(prefix) for prefix in complete_prefixes) and ">" not in fragment


def _extract_field(payload: dict[str, Any], key: str, text_extractor: TextExtractor) -> str:
    if key not in payload:
        return ""
    text = text_extractor(payload.get(key))
    if key in REASONING_DELTA_FIELD_CANDIDATES:
        return text
    return text.strip()


def _detail_item_dicts(value: Any) -> list[dict[str, Any]]:
    """Coerce a structured-detail value into a list of item dicts.

    Accepts the raw list, a single detail object/dict, or a container dict
    holding the list under ``reasoning_details``; elements may be dicts or
    objects exposing ``dict()``/``model_dump()``.
    """
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for entry in value:
            converted = _as_dict(entry)
            if isinstance(converted, dict):
                items.append(converted)
        return items
    converted = _as_dict(value)
    if not isinstance(converted, dict):
        return []
    nested = converted.get("reasoning_details")
    if isinstance(nested, list):
        return _detail_item_dicts(nested)
    return [converted]


def _detail_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "dict"):
        try:
            result = value.dict()
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            result = value.model_dump()
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    return None


__all__ = [
    "REASONING_DELTA_FIELD_CANDIDATES",
    "REASONING_FIELD_CANDIDATES",
    "ReasoningExtraction",
    "ThinkTagStreamParser",
    "ThinkTagStreamResult",
    "extract_reasoning_details_text",
    "extract_reasoning_text",
    "extract_think_tag_reasoning",
    "extract_thinking_blocks_text",
    "strip_think_tag_reasoning",
]
