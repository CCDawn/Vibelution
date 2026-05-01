#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理测试 (test_tool_result.py)

测试 core/infrastructure/tool_result.py 中的：
- truncate_result: 超长结果截断
- format_tool_message: 工具消息格式化
- DEFAULT_MAX_CHARS 常量
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.infrastructure.tool_result import (
    truncate_result,
    format_tool_message,
    DEFAULT_MAX_CHARS,
)


class TestTruncateResult:
    """truncate_result 测试"""

    def test_short_result_not_truncated(self):
        """短结果不截断"""
        result, truncated = truncate_result("hello", max_chars=100)
        assert result == "hello"
        assert truncated is False

    def test_result_at_limit_not_truncated(self):
        """等于限制长度不截断"""
        s = "A" * 10
        result, truncated = truncate_result(s, max_chars=10)
        assert result == s
        assert truncated is False

    def test_result_over_limit_truncated(self):
        """超过限制被截断"""
        s = "A" * 100
        result, truncated = truncate_result(s, max_chars=50)
        assert len(result) < len(s)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_truncation_preserves_prefix(self):
        """截断保留前缀"""
        result, _ = truncate_result("ABCDEFGHIJ", max_chars=5)
        assert result.startswith("ABCDE")

    def test_default_max_chars(self):
        """使用默认限制值"""
        assert DEFAULT_MAX_CHARS == 4000

    def test_non_string_result_converted(self):
        """非字符串结果被转为字符串"""
        result, _ = truncate_result(12345)
        assert isinstance(result, str)
        assert "12345" in result

    def test_empty_string(self):
        """空字符串"""
        result, truncated = truncate_result("")
        assert result == ""
        assert truncated is False

    def test_max_chars_zero(self):
        """max_chars=0 时截断所有内容"""
        result, truncated = truncate_result("hello", max_chars=0)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_list_result_converted(self):
        """列表结果被转为字符串"""
        result, _ = truncate_result([1, 2, 3], max_chars=100)
        assert isinstance(result, str)
        assert "1" in result


class TestFormatToolMessage:
    """format_tool_message 测试"""

    def test_returns_string_and_call_id(self):
        """返回 (result_str, tool_call_id) 元组"""
        result_str, call_id = format_tool_message(
            {"id": "call_123"}, "result text", None
        )
        assert isinstance(result_str, str)
        assert isinstance(call_id, str)
        assert "result text" in result_str

    def test_none_id_handled(self):
        """None ID 被安全处理"""
        result_str, call_id = format_tool_message(
            {"id": None}, "result"
        )
        assert call_id == ""

    def test_missing_id_handled(self):
        """缺少 id 被安全处理"""
        result_str, call_id = format_tool_message({}, "result")
        assert call_id == ""

    def test_long_result_truncated_in_format(self):
        """长结果在格式化时被截断"""
        long_result = "X" * 5000
        result_str, _ = format_tool_message(
            {"id": "call_1"}, long_result
        )
        assert len(result_str) <= DEFAULT_MAX_CHARS + 100  # 截断标记约 +50

    def test_action_param_accepted(self):
        """action 参数被接受（当前未使用）"""
        result_str, call_id = format_tool_message(
            {"id": "call_1"}, "result", action="restart"
        )
        assert result_str is not None
        assert call_id is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
