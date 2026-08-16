# -*- coding: utf-8 -*-
"""LLM 响应处理器。

负责把原始 LLM 响应整理成主循环更容易消费的结构：
- 标准 tool-calls 与 XML fallback 分流
- <state> / <active_components> 兼容回显清洗与诊断提取
- 可见 thought 文本与 AIMessage 载荷构建
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from core.infrastructure.llm_utils import parse_state_block, parse_xml_tool_calls
from core.orchestration.cache_diagnostics import compact_repeated_metadata_text
from core.orchestration.output_boundary import strip_llm_protocol_artifacts


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_tool_call_list(value: Any) -> List[Dict[str, Any]]:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        return [dict(value)] if value else []
    try:
        items = list(value)
    except TypeError:
        return []
    calls: List[Dict[str, Any]] = []
    for item in items:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            calls.append(dict(item))
    return calls


def _response_field(response: Any, *names: str, default: Any = None) -> Any:
    if isinstance(response, Mapping):
        for name in names:
            if name in response:
                return response[name]
        return default
    for name in names:
        if hasattr(response, name):
            return getattr(response, name)
    return default


def _tool_call_name(call: Mapping[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), Mapping) else {}
    return _coerce_text(
        call.get("name") or call.get("toolName") or function.get("name")
    ).strip()


def _optional_mapping(value: Any) -> Any:
    if value in (None, "", {}, []):
        return None
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        mapped = _as_mapping(value)
        return mapped or None
    if isinstance(value, Mapping):
        return dict(value)
    return value


@dataclass
class ResponsePreview:
    """LLM 响应的轻量预解析结果。

    主循环用它判断 XML fast-path / 构造 state_block，再传给 finalize() 拿到
    含 state_block 注入的完整结果。两步共享解析结果，避免重复 coerce/regex/XML parse。
    """

    raw_content: str
    tool_calls: List[Dict[str, Any]]
    xml_tool_calls: List[Dict[str, Any]]
    tool_call_count: int
    has_tool_calls: bool


@dataclass
class ResponseProcessingResult:
    raw_content: str
    raw_content_clean: str
    raw_content_with_state: str
    tool_calls: List[Dict[str, Any]]
    xml_tool_calls: List[Dict[str, Any]]
    active_components: List[str]
    tool_call_count: int
    has_tool_calls: bool
    state_info: Dict[str, Any]

    @property
    def visible_text(self) -> str:
        return self.raw_content_clean

    @staticmethod
    def _tool_call_args(call: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(call, Mapping):
            return {}
        raw = call.get("args")
        if raw in (None, ""):
            raw = call.get("arguments")
        if raw in (None, ""):
            function = call.get("function") if isinstance(call.get("function"), Mapping) else {}
            raw = function.get("arguments")
            if raw in (None, ""):
                raw = function.get("args")
        return _as_mapping(raw)

    def build_ai_message(
        self,
        response: Any,
        *,
        tool_calls_override: List[Dict[str, Any]] | None = None,
    ) -> AIMessage:
        selected_tool_calls = self.tool_calls
        if tool_calls_override is not None:
            selected_tool_calls = [
                {
                    "id": _coerce_text(
                        call.get("id") or call.get("toolCallId") or call.get("tool_call_id")
                    ).strip(),
                    "name": _tool_call_name(call),
                    "args": self._tool_call_args(call),
                }
                for call in _coerce_tool_call_list(tool_calls_override)
            ]
        ai_kwargs = {
            "content": self.raw_content_with_state,
            "tool_calls": selected_tool_calls,
        }
        additional_kwargs = _optional_mapping(
            _response_field(response, "additional_kwargs", "additionalKwargs")
        )
        if additional_kwargs:
            ai_kwargs["additional_kwargs"] = additional_kwargs
        response_metadata = _optional_mapping(
            _response_field(response, "response_metadata", "responseMetadata")
        )
        if response_metadata:
            ai_kwargs["response_metadata"] = response_metadata
        return AIMessage(**ai_kwargs)


def _merge_response_metadata_without_duplication(
    previous: Any,
    current: Any,
    merged: Any,
) -> Dict[str, Any] | None:
    previous_map = _as_mapping(previous)
    current_map = _as_mapping(current)
    merged_map = _as_mapping(merged)
    if not previous_map and not current_map and not merged_map:
        return None
    keys = set(previous_map) | set(current_map) | set(merged_map)
    return {
        key: _stable_metadata_value(
            previous_map.get(key),
            current_map.get(key),
            merged_map.get(key),
        )
        for key in keys
    }


def _stable_metadata_value(previous: Any, current: Any, merged: Any) -> Any:
    if isinstance(previous, Mapping) or isinstance(current, Mapping) or isinstance(merged, Mapping):
        return _merge_response_metadata_without_duplication(previous, current, merged) or {}
    if current not in (None, ""):
        if isinstance(current, str):
            return compact_repeated_metadata_text(current)
        return current
    if merged not in (None, ""):
        if isinstance(merged, str):
            return compact_repeated_metadata_text(merged)
        return merged
    if isinstance(previous, str):
        return compact_repeated_metadata_text(previous)
    return previous


class ResponseProcessor:
    """将 LLM 响应压成稳定的协议结果。"""

    @staticmethod
    def coerce_content_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, (bytes, bytearray, memoryview)):
            return bytes(content).decode("utf-8", errors="replace")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, Mapping):
                    text = item.get("text")
                    if text in (None, ""):
                        text = item.get("content")
                    if text not in (None, ""):
                        parts.append(_coerce_text(text))
                elif item not in (None, ""):
                    parts.append(_coerce_text(item))
            return "".join(parts)
        if isinstance(content, Mapping):
            text = content.get("text")
            if text in (None, ""):
                text = content.get("content")
            if text not in (None, ""):
                return _coerce_text(text)
        return _coerce_text(content)

    @staticmethod
    def merge_stream_chunk(full: Any, chunk: Any) -> Any:
        if chunk is None:
            return full
        if full is None:
            return chunk
        merged = full + chunk
        metadata = _merge_response_metadata_without_duplication(
            getattr(full, "response_metadata", None),
            getattr(chunk, "response_metadata", None),
            getattr(merged, "response_metadata", None),
        )
        if metadata is not None:
            try:
                merged.response_metadata = metadata
            except Exception:
                object.__setattr__(merged, "response_metadata", metadata)
        return merged

    @staticmethod
    def strip_state_echo(raw_content: str) -> str:
        return strip_llm_protocol_artifacts(raw_content)

    @staticmethod
    def extract_active_components(raw_content: str) -> List[str]:
        text = _coerce_text(raw_content)
        matches = re.findall(r"<active_components>([\s\S]*?)</active_components>", text, flags=re.IGNORECASE)
        if not matches:
            return []
        components: List[str] = []
        for block in matches:
            for item in re.split(r"[\s,|/]+", block.strip()):
                normalized = item.strip().upper()
                if normalized and normalized not in components:
                    components.append(normalized)
        return components

    @classmethod
    def strip_active_components_echo(cls, raw_content: str) -> str:
        return strip_llm_protocol_artifacts(raw_content)

    def preview(self, response: Any) -> ResponsePreview:
        """轻量预解析：拿到 raw_content / tool_calls / XML fallback。

        主循环用这个判断 XML fast-path 或构造 state_block，再把同一份 preview
        传给 finalize() 拿完整结果，避免一轮 LLM 响应被解析两遍。
        """

        raw_content = self.coerce_content_text(
            _response_field(response, "content", "text", default="")
        )
        tool_calls = _coerce_tool_call_list(
            _response_field(response, "tool_calls", "toolCalls", default=[])
        )
        tool_call_count = len(tool_calls)
        has_tool_calls = tool_call_count > 0
        xml_tool_calls = [] if has_tool_calls else parse_xml_tool_calls(raw_content)
        return ResponsePreview(
            raw_content=raw_content,
            tool_calls=tool_calls,
            xml_tool_calls=xml_tool_calls,
            tool_call_count=tool_call_count,
            has_tool_calls=has_tool_calls,
        )

    def finalize(
        self,
        response: Any,
        preview: ResponsePreview,
        state_block_str: str = "",
    ) -> ResponseProcessingResult:
        """基于已存在的 preview 完成重活：active_components / state_info / clean。"""

        raw_content = preview.raw_content
        active_components = self.extract_active_components(raw_content)
        raw_content_clean = self.strip_active_components_echo(self.strip_state_echo(raw_content))
        state_block = _coerce_text(state_block_str).strip()
        if state_block:
            raw_content_with_state = raw_content_clean + "\n\n" + state_block
            state_info = parse_state_block(state_block)
        else:
            raw_content_with_state = raw_content_clean
            state_info = parse_state_block(raw_content)
        return ResponseProcessingResult(
            raw_content=raw_content,
            raw_content_clean=raw_content_clean,
            raw_content_with_state=raw_content_with_state,
            tool_calls=preview.tool_calls,
            xml_tool_calls=preview.xml_tool_calls,
            active_components=active_components,
            tool_call_count=preview.tool_call_count,
            has_tool_calls=preview.has_tool_calls,
            state_info=state_info,
        )

    def process(self, response: Any, state_block_str: str = "") -> ResponseProcessingResult:
        """preview + finalize 的组合便捷入口，保留以兼容旧调用方。"""

        return self.finalize(response, self.preview(response), state_block_str)
