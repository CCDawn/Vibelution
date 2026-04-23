# -*- coding: utf-8 -*-
"""
core/orchestration/response_parser.py - LLM 响应解析器

功能：
- 强制提取 <state_memory> XML 标签
- 强制提取 <active_rules> XML 标签
- 保留原有 tool_calls 解析能力
- 异常时返回空字符串，保证主循环健壮
"""

from __future__ import annotations

import re
import json
import uuid
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
    mood_content: str = ""
    state_memory: str = ""
    plan_content: str = ""
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
        result.thinking_content = self._extract_tag(content, "think")
        result.mood_content = self._extract_tag(content, "mood")

        result.state_memory = self._extract_tag(content, "state_memory")
        if result.state_memory:
            self.logger.debug(f"[ResponseParser] 提取 state_memory，长度={len(result.state_memory)}")

        result.plan_content = self._extract_tag(content, "plan")
        if result.plan_content:
            self.logger.debug(f"[ResponseParser] 提取 plan，长度={len(result.plan_content)}")

        result.active_rules = self._extract_active_rules(content)
        if result.active_rules:
            self.logger.debug(f"[ResponseParser] 提取 active_rules: {result.active_rules}")

        result.active_components = self._extract_active_components(content)
        if result.active_components:
            self.logger.debug(f"[ResponseParser] 提取 active_components: {result.active_components}")

        result.clean_content = self._strip_all_tags(content)
        return result

    # ------------------------------------------------------------------------
    # Tool Call 提取
    # ------------------------------------------------------------------------

    def _extract_tool_calls(self, response: Any, content: str) -> List[Dict[str, Any]]:
        tool_calls = getattr(response, 'tool_calls', None) or []

        if not tool_calls and content:
            text_tcs = re.findall(
                r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>',
                content
            )
            for tc_json in text_tcs:
                try:
                    tc = json.loads(tc_json)
                    self._normalize_tool_call(tc)
                    tool_calls.append(tc)
                except json.JSONDecodeError:
                    pass

            skill_patterns = [
                r'<invoke\s+name="([^"]+)"[^>]*>([\s\S]*?)</invoke>',
                r'<skill\s+name="([^"]+)"[^>]*>([\s\S]*?)</skill>',
            ]
            for pattern in skill_patterns:
                for match in re.finditer(pattern, content):
                    name = match.group(1)
                    body = match.group(2)
                    args = self._parse_skill_params(body)
                    tc = {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "name": name,
                        "args": args,
                    }
                    tool_calls.append(tc)

        return tool_calls

    def _normalize_tool_call(self, tc: Dict[str, Any]):
        if 'arguments' in tc and 'args' not in tc:
            tc['args'] = tc.pop('arguments')
        if 'args' not in tc:
            tc['args'] = {}
        if 'id' not in tc:
            tc['id'] = f"call_{uuid.uuid4().hex[:8]}"

    def _parse_skill_params(self, body: str) -> Dict[str, Any]:
        args = {}
        param_matches = re.findall(
            r'<param\s+name="([^"]+)"[^>]*>([\s\S]*?)</param>',
            body
        )
        for param_name, param_value in param_matches:
            try:
                args[param_name] = json.loads(param_value.strip())
            except (json.JSONDecodeError, ValueError):
                args[param_name] = param_value.strip()
        return args

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

        # thinking 专用：支持 Unicode 认真学习 和 ASCII 认真学习 两种格式
        if tag == "thinking":
            open_esc = re.escape(_THINK_OPEN)
            close_esc = re.escape(_THINK_CLOSE)
            for p in [
                open_esc + r'\s*([\s\S]*?)\s*' + close_esc,
                r'认真学习\s*([\s\S]*?)\s*认真学习',
            ]:
                m = re.search(p, content, re.IGNORECASE | re.DOTALL)
                if m:
                    return m.group(1).strip()

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
