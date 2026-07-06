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
from .usage import usage_stats_from_payload


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
        self._reasoning_seen_by_source: Dict[str, str] = {}

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
                reasoning_delta = self._normalize_reasoning_delta(reasoning.source, reasoning.text)
                if reasoning_delta:
                    yield StreamChunk(
                        type="reasoning_delta",
                        text=reasoning_delta,
                        provider_payload={**delta, "reasoning_source": reasoning.source},
                    )
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

    def _normalize_reasoning_delta(self, source: str, text: str) -> str:
        """Return a stable delta even when a provider streams cumulative reasoning prefixes."""
        source_key = str(source or "reasoning").strip() or "reasoning"
        current = str(text or "")
        if not current:
            return ""
        previous = self._reasoning_seen_by_source.get(source_key, "")
        if not previous:
            self._reasoning_seen_by_source[source_key] = current
            return current
        if current == previous:
            return ""
        if current.startswith(previous):
            self._reasoning_seen_by_source[source_key] = current
            return current[len(previous):]
        self._reasoning_seen_by_source[source_key] = previous + current
        return current

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
        stats = usage_stats_from_payload(usage)
        if not stats.provider_raw_usage:
            return None
        return stats


class ResponsesStreamNormalizer:
    """Normalizes OpenAI Responses stream events into internal events."""

    def __init__(self) -> None:
        self._usage: UsageStats | None = None
        self._text_emitted = False
        self._tool_calls = ResponsesToolCallAccumulator()

    def events(self, raw_chunks: Iterable[Any]) -> Iterator[StreamChunk]:
        for raw_chunk in raw_chunks:
            event = _as_dict(raw_chunk)
            if not isinstance(event, dict):
                continue
            usage = self._extract_usage(event)
            if usage is not None:
                self._usage = usage
            event_type = str(event.get("type") or "").strip()
            reasoning_delta = self._extract_reasoning_delta(event_type, event)
            if reasoning_delta:
                yield StreamChunk(type="reasoning_delta", text=reasoning_delta, provider_payload=event)
            text_delta = self._extract_text_delta(event_type, event)
            if text_delta:
                self._text_emitted = True
                yield StreamChunk(type="text_delta", text=text_delta, provider_payload=event)
            tool_call = self._extract_tool_call(event_type, event)
            if tool_call is not None:
                yield StreamChunk(type="tool_call_final", tool_calls=[tool_call], provider_payload=event)
            if event_type in {"response.completed", "response.done"} and not self._text_emitted:
                completed_text = self._extract_completed_text(event)
                if completed_text:
                    self._text_emitted = True
                    yield StreamChunk(type="text_delta", text=completed_text, provider_payload=event)
        yield StreamChunk(type="done", usage=self._usage)

    @staticmethod
    def _extract_text_delta(event_type: str, event: Dict[str, Any]) -> str:
        if event_type in {"response.output_text.delta", "response.refusal.delta"}:
            return str(event.get("delta") or "")
        chat_delta = LiteLLMStreamNormalizer._extract_delta(event)
        if isinstance(chat_delta, dict) and chat_delta.get("content"):
            return extract_text_content(chat_delta.get("content"))
        delta = _as_dict(event.get("delta"))
        if isinstance(delta, dict):
            if isinstance(delta.get("text"), str):
                return delta.get("text") or ""
            if isinstance(delta.get("content"), str):
                return delta.get("content") or ""
        part = _as_dict(event.get("part"))
        if isinstance(part, dict) and str(part.get("type") or "") in {"output_text", "text"}:
            return str(part.get("text") or "")
        return ""

    @staticmethod
    def _extract_reasoning_delta(event_type: str, event: Dict[str, Any]) -> str:
        if event_type in {
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
            "response.output_text.annotation.added",
        }:
            return str(event.get("delta") or event.get("text") or "")
        return ""

    @staticmethod
    def _extract_completed_text(event: Dict[str, Any]) -> str:
        response = _as_dict(event.get("response"))
        if isinstance(response, dict) and isinstance(response.get("output_text"), str):
            return response.get("output_text") or ""
        return ""

    @staticmethod
    def _extract_usage(event: Dict[str, Any]) -> UsageStats | None:
        usage = event.get("usage")
        if usage is None:
            response = _as_dict(event.get("response"))
            usage = response.get("usage") if isinstance(response, dict) else None
        if usage is None:
            return None
        stats = usage_stats_from_payload(usage)
        if not stats.provider_raw_usage:
            return None
        return stats

    def _extract_tool_call(self, event_type: str, event: Dict[str, Any]) -> ToolCall | None:
        if event_type == "response.output_item.added":
            self._tool_calls.add_item(event.get("item"))
            return None
        if event_type in {
            "response.function_call_arguments.delta",
            "response.tool_call_arguments.delta",
            "response.custom_tool_call_input.delta",
        }:
            self._tool_calls.add_arguments_delta(event)
            return None
        if event_type in {
            "response.function_call_arguments.done",
            "response.tool_call_arguments.done",
            "response.custom_tool_call_input.done",
        }:
            self._tool_calls.add_arguments_done(event)
            return None
        if event_type == "response.output_item.done":
            return self._tool_calls.finalize_item(event.get("item"))
        return None


class ResponsesToolCallAccumulator:
    """Accumulates OpenAI Responses function-call item events."""

    _CALL_ITEM_TYPES = {"function_call", "tool_call", "custom_tool_call"}

    def __init__(self) -> None:
        self._by_item_id: Dict[str, Dict[str, Any]] = {}
        self._item_id_by_call_id: Dict[str, str] = {}
        self._active_item_id: str = ""

    def add_item(self, raw_item: Any) -> None:
        item = _as_dict(raw_item)
        if not self._is_call_item(item):
            return
        state = self._state_for_item(item)
        self._merge_item(state, item, replace_arguments=False)

    def add_arguments_delta(self, event: Dict[str, Any]) -> None:
        state = self._state_for_event(event)
        if state is None:
            return
        self._append_arguments(state, event.get("delta"))

    def add_arguments_done(self, event: Dict[str, Any]) -> None:
        state = self._state_for_event(event)
        if state is None:
            return
        if "arguments" in event:
            state["arguments"] = event.get("arguments") or ""
        elif "delta" in event:
            state["arguments"] = event.get("delta") or ""

    def finalize_item(self, raw_item: Any) -> ToolCall | None:
        item = _as_dict(raw_item)
        if not self._is_call_item(item):
            return None
        state = self._state_for_item(item)
        self._merge_item(state, item, replace_arguments=True)
        item_id = str(state.get("item_id") or "")
        if item_id:
            self._by_item_id.pop(item_id, None)
        call_id = str(state.get("call_id") or "")
        if call_id:
            self._item_id_by_call_id.pop(call_id, None)
        if self._active_item_id == item_id:
            self._active_item_id = ""
        name = str(state.get("name") or "")
        if not name:
            return None
        raw_args = state.get("arguments") or ""
        provider_payload = item if isinstance(item, dict) else {}
        return ToolCall(
            id=call_id or item_id or name,
            name=name,
            arguments=parse_tool_arguments(raw_args),
            raw_arguments=raw_args,
            provider_payload=provider_payload,
        )

    @classmethod
    def _is_call_item(cls, item: Any) -> bool:
        return isinstance(item, dict) and str(item.get("type") or "") in cls._CALL_ITEM_TYPES

    def _state_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        item_id = str(item.get("id") or item.get("item_id") or item.get("call_id") or "")
        call_id = str(item.get("call_id") or item.get("id") or item_id)
        if not item_id:
            item_id = call_id or f"responses_tool_{len(self._by_item_id)}"
        state = self._by_item_id.setdefault(
            item_id,
            {
                "item_id": item_id,
                "call_id": call_id,
                "name": "",
                "arguments": "",
            },
        )
        if call_id:
            state["call_id"] = call_id
            self._item_id_by_call_id[call_id] = item_id
        self._active_item_id = item_id
        return state

    def _state_for_event(self, event: Dict[str, Any]) -> Dict[str, Any] | None:
        item_id = str(event.get("item_id") or event.get("output_item_id") or "")
        call_id = str(event.get("call_id") or "")
        if not item_id and call_id:
            item_id = self._item_id_by_call_id.get(call_id, "")
        if not item_id:
            item_id = self._active_item_id
        if not item_id:
            return None
        state = self._by_item_id.setdefault(
            item_id,
            {
                "item_id": item_id,
                "call_id": call_id,
                "name": "",
                "arguments": "",
            },
        )
        if call_id:
            state["call_id"] = call_id
            self._item_id_by_call_id[call_id] = item_id
        return state

    def _merge_item(self, state: Dict[str, Any], item: Dict[str, Any], *, replace_arguments: bool) -> None:
        if item.get("call_id"):
            state["call_id"] = str(item.get("call_id"))
            self._item_id_by_call_id[str(item.get("call_id"))] = str(state.get("item_id") or "")
        if item.get("name"):
            state["name"] = str(item.get("name"))
        if "arguments" in item and (replace_arguments or not state.get("arguments")):
            state["arguments"] = item.get("arguments") or ""
        elif "input" in item and (replace_arguments or not state.get("arguments")):
            state["arguments"] = item.get("input") or ""

    @staticmethod
    def _append_arguments(state: Dict[str, Any], part: Any) -> None:
        if isinstance(part, str):
            state["arguments"] = str(state.get("arguments") or "") + part
        elif isinstance(part, dict):
            state["arguments"] = part
        elif part is not None:
            state["arguments"] = str(state.get("arguments") or "") + str(part)


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if value is not None and hasattr(value, "__dict__"):
        return dict(getattr(value, "__dict__", {}) or {})
    return value


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "LiteLLMStreamNormalizer",
    "ResponsesStreamNormalizer",
    "ToolCallAccumulator",
    "extract_message_tool_calls",
    "extract_text_content",
    "parse_tool_arguments",
]
