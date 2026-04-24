# -*- coding: utf-8 -*-
"""
core/orchestration/response_parser.py - LLM 响应解析器

功能：
- 提取 <state> XML 标签（状态记忆）
- 提取 <active_rules> XML 标签（激活规则）
- 提取 <active_components> XML 标签（激活组件）
- 仅依赖 LangChain 原生 tool_calls 属性
- 异常时返回空字符串，保证主循环健壮
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from core.logging.setup import setup_logging
import logging

setup_logging()

# thinking 标签（两种格式）
# 格式1: <thinking>...</thinking>  (标准 XML)
# 格式2: 认真学习...认真学习  (Unicode XML)
_THINK_OPEN = "\u300a\u5c0f\u8bb0"
_THINK_CLOSE = "\u300a\u5c0f\u8bb1"

@dataclass
class LLMParserResult:
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thinking_content: str = ""
    state: str = ""
    active_rules: List[str] = field(default_factory=list)
    active_components: List[str] = field(default_factory=list)
    raw_content: str = ""
    clean_content: str = ""


class ResponseParser:
    def __init__(self):
        self.logger = logging.getLogger("ResponseParser")
        self._strip_tags: List[str] = []
        self._strip_thinking_alias: bool = True

    def _ensure_config(self):
        """从配置加载标签列表（延迟加载，避免循环导入）"""
        if self._strip_tags:
            return
        try:
            from config import get_parser_config
            cfg = get_parser_config()
            self._strip_tags = cfg.strip_tags
            self._strip_thinking_alias = cfg.strip_thinking_alias
        except Exception:
            self._strip_tags = [
                _THINK_OPEN,
                "tool_call", "invoke", "skill",
                "thinking", "state_memory",
                "active_rules", "active_components",
                "plan",
            ]
            self._strip_thinking_alias = True

    def parse(self, response: Any) -> LLMParserResult:
        result = LLMParserResult()

        try:
            content = getattr(response, 'content', '') or ""
        except Exception:
            content = ""

        self._ensure_config()
        result.raw_content = content

        result.tool_calls = self._extract_tool_calls(response, content)
        result.state = self._extract_tag(content, "state")
        result.active_rules = self._extract_active_rules(content)
        result.active_components = self._extract_active_components(content)

        result.clean_content = self._strip_all_tags(content)
        return result

    # ------------------------------------------------------------------------
    # Tool Call 提取
    # ------------------------------------------------------------------------

    def _extract_tool_calls(self, response: Any, content: str) -> List[Dict[str, Any]]:
        return getattr(response, 'tool_calls', None) or []

    # ------------------------------------------------------------------------
    # XML 标签提取
    # ------------------------------------------------------------------------

    def _extract_tag(self, content: str, tag: str) -> str:
        """
        提取指定 XML 标签的内容

        支持格式：
        - <tag>content</tag>
        - <tag attr="value">content</tag>
        - 认真学习 认真学习  (thinking 专用)
        """
        if not content:
            return ""

        tag_esc = re.escape(tag)
        patterns = [
            rf'<{tag_esc}\s[^>]*>\s*([\s\S]*?)\s*</{tag_esc}>',
            rf'<{tag_esc}>\s*([\s\S]*?)\s*</{tag_esc}>',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_active_rules(self, content: str) -> List[str]:
        if not content:
            return []

        tag_content = self._extract_tag(content, "active_rules")
        if tag_content:
            return [r.strip() for r in tag_content.split(",") if r.strip()]

        pattern = r'<active_rules\s+names="([^"]+)"[^/]*/>'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            names = match.group(1)
            return [r.strip() for r in names.split(",") if r.strip()]

        return []

    def _extract_active_components(self, content: str) -> List[str]:
        if not content:
            return []

        tag_content = self._extract_tag(content, "active_components")
        if tag_content:
            return [c.strip() for c in tag_content.split(",") if c.strip()]

        pattern = r'<active_components\s+names="([^"]+)"[^/]*/>'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            names = match.group(1)
            return [c.strip() for c in names.split(",") if c.strip()]

        return []

    # ------------------------------------------------------------------------
    # 标签去除
    # ------------------------------------------------------------------------

    def _strip_all_tags(self, content: str) -> str:
        """
        去掉 content 中所有已知 XML 标签，返回干净文本。
        支持 <thinking> / 认真学习 / 认真学习 三种格式。
        """
        if not content:
            return ""
        self._ensure_config()
        result = content

        for tag in self._strip_tags:
            tag_esc = re.escape(tag)
            patterns = [
                rf'<{tag_esc}\s[^>]*>.*?</{tag_esc}>',
                rf'<{tag_esc}>.*?</{tag_esc}>',
            ]
            for pattern in patterns:
                result = re.sub(pattern, "", result, flags=re.IGNORECASE | re.DOTALL)

        if self._strip_thinking_alias:
            open_esc = re.escape(_THINK_OPEN)
            close_esc = re.escape(_THINK_CLOSE)
            for p in [
                open_esc + r'(?:\s|(?!' + open_esc + r').)*?' + close_esc,
                r'认真学习(?:\s|(?!认真学习).)*?认真学习',
            ]:
                result = re.sub(p, "", result, flags=re.IGNORECASE | re.DOTALL)

        result = re.sub(r'\n{3,}', '\n\n', result).strip()
        return result


# ============================================================================
# 全局单例
# ============================================================================

_parser: Optional[ResponseParser] = None


def get_response_parser() -> ResponseParser:
    global _parser
    if _parser is None:
        _parser = ResponseParser()
    return _parser


def parse_llm_response(response: Any) -> LLMParserResult:
    return get_response_parser().parse(response)


__all__ = [
    "LLMParserResult",
    "ResponseParser",
    "get_response_parser",
    "parse_llm_response",
]
