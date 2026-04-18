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
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LLMParserResult:
    """
    LLM 响应解析结果

    Attributes:
        tool_calls:       结构化的工具调用列表
        thinking_content: <thinking> 标签中的思考过程
        state_memory:     <state_memory> 标签中的状态记忆文本
        active_rules:     <active_rules> 标签中的规则集名称列表
        raw_content:      原始文本内容（去除标签后）
    """
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thinking_content: str = ""
    state_memory: str = ""
    active_rules: List[str] = field(default_factory=list)
    raw_content: str = ""


class ResponseParser:
    """
    LLM 响应解析器

    职责：
    - 提取 tool_calls（结构化 + 文本 XML 格式）
    - 提取 <thinking> 思考内容
    - 强制提取 <state_memory> 状态记忆（回写给 PromptManager → 落盘）
    - 强制提取 <active_rules> 规则集切换（回写给 PromptManager）
    """

    def __init__(self):
        self.logger = logging.getLogger("ResponseParser")

    def parse(self, response: Any) -> LLMParserResult:
        """
        解析 LLM 响应

        Args:
            response: LangChain AIMessage 或兼容对象

        Returns:
            LLMParserResult 结构化解析结果
        """
        result = LLMParserResult()

        try:
            content = getattr(response, 'content', '') or ""
        except Exception:
            content = ""

        # 保留原始内容（去除标签后）
        result.raw_content = content

        # 1. 提取 tool_calls
        result.tool_calls = self._extract_tool_calls(response, content)

        # 2. 提取 <thinking> 标签
        result.thinking_content = self._extract_tag(content, "thinking")

        # 3. 强制提取 <state_memory> 标签
        result.state_memory = self._extract_tag(content, "state_memory")
        if result.state_memory:
            self.logger.debug(f"[ResponseParser] 提取 state_memory，长度={len(result.state_memory)}")

        # 4. 强制提取 <active_rules> 标签
        result.active_rules = self._extract_active_rules(content)
        if result.active_rules:
            self.logger.debug(f"[ResponseParser] 提取 active_rules: {result.active_rules}")

        return result

    # ------------------------------------------------------------------------
    # Tool Call 提取（从 agent.py _parse_tool_calls 迁移）
    # ------------------------------------------------------------------------

    def _extract_tool_calls(self, response: Any, content: str) -> List[Dict[str, Any]]:
        """提取工具调用（支持多种格式）"""
        tool_calls = getattr(response, 'tool_calls', None) or []

        if not tool_calls and content:
            # 格式1: <tool_call>{JSON}</tool_call>
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

            # 格式2: <invoke name="xxx"> 或 <skill name="xxx">
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
        """标准化 tool_call 字段"""
        if 'arguments' in tc and 'args' not in tc:
            tc['args'] = tc.pop('arguments')
        if 'args' not in tc:
            tc['args'] = {}
        if 'id' not in tc:
            tc['id'] = f"call_{uuid.uuid4().hex[:8]}"

    def _parse_skill_params(self, body: str) -> Dict[str, Any]:
        """解析 skill/invoke 标签中的参数"""
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

        支持两种格式：
        - <tag>content</tag>
        - <tag name="xxx">content</tag>
        """
        if not content:
            return ""

        patterns = [
            rf'<{tag}>\s*([\s\S]*?)\s*</{tag}>',
            rf'<{tag}\s[^>]*>\s*([\s\S]*?)\s*</{tag}>',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return ""

    def _extract_active_rules(self, content: str) -> List[str]:
        """
        提取 <active_rules> 标签中的规则集名称列表

        支持格式：
        - <active_rules>code_review, creative</active_rules>
        - <active_rules names="code_review,creative" />
        """
        if not content:
            return []

        # 格式1: <active_rules>rule1, rule2</active_rules>
        tag_content = self._extract_tag(content, "active_rules")
        if tag_content:
            return [r.strip() for r in tag_content.split(",") if r.strip()]

        # 格式2: <active_rules names="rule1,rule2" />
        pattern = r'<active_rules\s+names="([^"]+)"[^/]*/>'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            names = match.group(1)
            return [r.strip() for r in names.split(",") if r.strip()]

        return []


# ============================================================================
# 全局单例
# ============================================================================

_parser: Optional[ResponseParser] = None


def get_response_parser() -> ResponseParser:
    """获取全局 ResponseParser 单例"""
    global _parser
    if _parser is None:
        _parser = ResponseParser()
    return _parser


def parse_llm_response(response: Any) -> LLMParserResult:
    """便捷函数：解析 LLM 响应"""
    return get_response_parser().parse(response)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "LLMParserResult",
    "ResponseParser",
    "get_response_parser",
    "parse_llm_response",
]
