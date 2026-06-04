# -*- coding: utf-8 -*-
"""Streaming protocol normalization for LLM providers.

Provider streams are delta-oriented: tool call names, ids, and JSON arguments
can arrive across multiple chunks. The agent loop should never see those
partials as executable tools. This module translates raw provider chunks into
stable internal stream events.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator, List

from .reasoning_extractor import ThinkTagStreamParser, extract_reasoning_text
from .types import StreamChunk, ToolCall, UsageStats


def extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def parse_tool_arguments(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            return {}
    if isinstance(raw_args, dict):
        return raw_args
    return {}


def extract_message_tool_calls(message: Dict[str, Any]) -> List[ToolCall]:
    items: List[ToolCall] = []
    for index, raw_tool in enumerate(message.get("tool_calls") or []):
        tool = _as_dict(raw_tool)
        if not isinstance(tool, dict):
            continue
        function = _as_dict(tool.get("function") or {})
        raw_args = function.get("arguments") or {}
        items.append(
            ToolCall(
                id=str(tool.get("id") or f"tool_{index}"),
                name=str(function.get("name") or ""),
                arguments=parse_tool_arguments(raw_args),
                raw_arguments=raw_args,
                provider_payload=tool,
            )
        )
    return items


class ToolCallAccumulator:
    """Accumulates provider tool-call deltas into executable calls."""

    def __init__(self) -> None:
        self._by_index: Dict[int, Dict[str, Any]] = {}

    def add_deltas(self, deltas: Iterable[Any]) -> None:
        for fallback_index, raw_tool in enumerate(deltas or []):
            tool = _as_dict(raw_tool)
            if not isinstance(tool, dict):
                continue
            index = _safe_int(tool.get("index"), fallback_index)
            state = self._by_index.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool.get("id"):
                state["id"] = str(tool.get("id"))
            function = _as_dict(tool.get("function") or {})
            if not isinstance(function, dict):
                continue
            if function.get("name"):
                state["name"] = str(function.get("name"))
            if "arguments" in function:
                self._append_arguments(state, function.get("arguments"))

    def final_calls(self) -> List[ToolCall]:
        calls = [
            self._to_tool_call(index, self._by_index[index])
            for index in sorted(self._by_index)
        ]
        return [call for call in calls if call.name]

    @staticmethod
    def _append_arguments(state: Dict[str, Any], part: Any) -> None:
        if isinstance(part, str):
            state["arguments"] = str(state.get("arguments") or "") + part
        elif isinstance(part, dict):
            state["arguments"] = part
        elif part is not None:
            state["arguments"] = str(state.get("arguments") or "") + str(part)

    @staticmethod
    def _to_tool_call(index: int, state: Dict[str, Any]) -> ToolCall:
        raw_args = state.get("arguments") or ""
        provider_payload = {
            "id": state.get("id") or f"tool_{index}",
            "type": "function",
            "function": {
                "name": state.get("name") or "",
                "arguments": raw_args,
            },
        }
        return ToolCall(
            id=str(state.get("id") or f"tool_{index}"),
            name=str(state.get("name") or ""),
            arguments=parse_tool_arguments(raw_args),
            raw_arguments=raw_args,
            provider_payload=provider_payload,
        )


class LiteLLMStreamNormalizer:
    """Normalizes LiteLLM/OpenAI-compatible chunks into internal events."""

    def __init__(self) -> None:
        self._tool_calls = ToolCallAccumulator()
        self._usage: UsageStats | None = None
        self._think_tags = ThinkTagStreamParser()

    def events(self, raw_chunks: Iterable[Any]) -> Iterator[StreamChunk]:
        for raw_chunk in raw_chunks:
            usage = self._extract_usage(raw_chunk)
            if usage is not None:
                self._usage = usage
            delta = self._extract_delta(raw_chunk)
            if not delta:
                continue
            reasoning = extract_reasoning_text(delta, extract_text_content, include_content_tags=False)
            if reasoning.text:
                yield StreamChunk(type="reasoning_delta", text=reasoning.text, provider_payload={**delta, "reasoning_source": reasoning.source})
            content_split = self._think_tags.feed(delta.get("content") or "", extract_text_content)
            if content_split.reasoning_text:
                yield StreamChunk(
                    type="reasoning_delta",
                    text=content_split.reasoning_text,
                    provider_payload={**delta, "reasoning_source": "think_tag"},
                )
            if content_split.visible_text:
                yield StreamChunk(type="text_delta", text=content_split.visible_text, provider_payload=delta)
            tool_deltas = delta.get("tool_calls") or []
            if tool_deltas:
                self._tool_calls.add_deltas(tool_deltas)
        flushed = self._think_tags.flush()
        if flushed.reasoning_text:
            yield StreamChunk(type="reasoning_delta", text=flushed.reasoning_text, provider_payload={"reasoning_source": "think_tag"})
        if flushed.visible_text:
            yield StreamChunk(type="text_delta", text=flushed.visible_text, provider_payload={})
        final_calls = self._tool_calls.final_calls()
        if final_calls:
            yield StreamChunk(type="tool_call_final", tool_calls=final_calls)
        yield StreamChunk(type="done", usage=self._usage)

    @staticmethod
    def _extract_delta(raw_chunk: Any) -> Dict[str, Any]:
        chunk = _as_dict(raw_chunk)
        choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(raw_chunk, "choices", None)
        choices = choices or []
        if not choices:
            return {}
        choice = _as_dict(choices[0])
        delta = choice.get("delta") if isinstance(choice, dict) else getattr(choices[0], "delta", None)
        delta = _as_dict(delta)
        return delta if isinstance(delta, dict) else {}

    @staticmethod
    def _extract_usage(raw_chunk: Any) -> UsageStats | None:
        chunk = _as_dict(raw_chunk)
        if not isinstance(chunk, dict):
            return None
        usage = chunk.get("usage") or chunk.get("usage_metadata")
        if usage is None:
            return None
        usage_dict = _usage_to_dict(usage)
        if not usage_dict:
            return None
        input_tokens = _read_usage_int(usage_dict, "prompt_tokens", "input_tokens", "input_token_count")
        output_tokens = _read_usage_int(usage_dict, "completion_tokens", "output_tokens", "output_token_count")
        total_tokens = _read_usage_int(usage_dict, "total_tokens") or (input_tokens + output_tokens)
        prompt_details = usage_dict.get("prompt_tokens_details")
        input_details = usage_dict.get("input_token_details")
        cached_tokens = max(
            _read_usage_int(usage_dict, "cached_tokens", "cached_input_tokens"),
            _read_usage_int(prompt_details, "cached_tokens", "cached_input_tokens"),
            _read_usage_int(input_details, "cached_tokens", "cached_input_tokens"),
        )
        return UsageStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=min(cached_tokens, input_tokens) if input_tokens else cached_tokens,
            provider_raw_usage=usage_dict,
        )


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_usage_int(container: Any, *keys: str) -> int:
    if not isinstance(container, dict):
        return 0
    for key in keys:
        value = container.get(key)
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


def _usage_to_dict(usage: Any) -> Dict[str, Any]:
    if isinstance(usage, dict):
        return usage
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            payload = usage.model_dump()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    payload: Dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "input_token_count",
        "output_token_count",
        "cached_tokens",
        "cached_input_tokens",
        "prompt_tokens_details",
        "input_token_details",
    ):
        if hasattr(usage, key):
            payload[key] = getattr(usage, key)
    return payload


__all__ = [
    "LiteLLMStreamNormalizer",
    "ToolCallAccumulator",
    "extract_message_tool_calls",
    "extract_text_content",
    "parse_tool_arguments",
]
