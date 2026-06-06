# -*- coding: utf-8 -*-
"""LLM 响应处理器。

负责把原始 LLM 响应整理成主循环更容易消费的结构：
- 标准 tool-calls 与 XML fallback 分流
- <state> / <active_components> 回显清洗
- 可见 thought 文本与 AIMessage 载荷构建
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from core.infrastructure.llm_utils import parse_state_block, parse_xml_tool_calls
from core.orchestration.output_boundary import strip_llm_protocol_artifacts


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

    def build_ai_message(self, response: Any) -> AIMessage:
        ai_kwargs = {
            "content": self.raw_content_with_state,
            "tool_calls": self.tool_calls,
        }
        additional_kwargs = getattr(response, "additional_kwargs", None)
        if additional_kwargs:
            ai_kwargs["additional_kwargs"] = additional_kwargs
        response_metadata = getattr(response, "response_metadata", None)
        if response_metadata:
            ai_kwargs["response_metadata"] = response_metadata
        return AIMessage(**ai_kwargs)


class ResponseProcessor:
    """将 LLM 响应压成稳定的协议结果。"""

    @staticmethod
    def coerce_content_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text not in (None, ""):
                        parts.append(str(text))
                elif item not in (None, ""):
                    parts.append(str(item))
            return "".join(parts)
        if isinstance(content, dict):
            text = content.get("text")
            if text not in (None, ""):
                return str(text)
        return str(content)

    @staticmethod
    def merge_stream_chunk(full: Any, chunk: Any) -> Any:
        if chunk is None:
            return full
        if full is None:
            return chunk
        return full + chunk

    @staticmethod
    def strip_state_echo(raw_content: str) -> str:
        return strip_llm_protocol_artifacts(raw_content)

    @staticmethod
    def extract_active_components(raw_content: str) -> List[str]:
        text = raw_content or ""
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

        raw_content = self.coerce_content_text(getattr(response, "content", ""))
        tool_calls = list(getattr(response, "tool_calls", []) or [])
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
        if state_block_str:
            raw_content_with_state = raw_content_clean + "\n\n" + state_block_str
            state_info = parse_state_block(state_block_str)
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
