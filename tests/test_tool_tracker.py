#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具效果追踪器测试

测试 core/tool_tracker.py 的功能
"""

import pytest
import sys
import os
import json

from core.logging.tool_tracker import (
    ToolTracker,
    ToolStats,
    ToolCallRecord,
    ToolAnalysisReport,
)


class TestToolTracker:
    """工具追踪器测试类"""

    @pytest.fixture
    def tracker(self, tmp_path):
        """创建追踪器实例"""
        return ToolTracker(project_root=str(tmp_path))

    # =========================================================================
    # 初始化测试
    # =========================================================================

    def test_init(self, tracker):
        """测试初始化"""
        assert tracker is not None
        assert tracker._stats == {}
        assert tracker._recent_calls == []

    def test_init_creates_directory(self, tmp_path):
        """测试初始化创建目录"""
        ToolTracker(project_root=str(tmp_path))
        data_dir = tmp_path / "workspace" / "analytics"
        assert data_dir.exists()

    # =========================================================================
    # 记录接口测试
    # =========================================================================

    def test_record_call_success(self, tracker):
        """测试记录成功调用"""
        tracker.record_success(
            tool_name="read_file",
            duration_ms=50.0,
            args={"path": "test.py"},
        )

        assert "read_file" in tracker._stats
        stats = tracker._stats["read_file"]
        assert stats.total_calls == 1
        assert stats.successful_calls == 1
        assert stats.failed_calls == 0
        assert stats.success_rate == 1.0

    def test_record_call_failure(self, tracker):
        """测试记录失败调用"""
        tracker.record_failure(
            tool_name="read_file",
            duration_ms=100.0,
            error="File not found",
            args={"path": "nonexistent.py"},
        )

        stats = tracker._stats["read_file"]
        assert stats.total_calls == 1
        assert stats.successful_calls == 0
        assert stats.failed_calls == 1
        assert stats.success_rate == 0.0

    def test_record_call_updates_stats(self, tracker):
        """测试记录更新统计"""
        # 多次调用
        tracker.record_success("read_file", 10.0)
        tracker.record_success("read_file", 20.0)
        tracker.record_failure("read_file", 30.0, "error")

        stats = tracker._stats["read_file"]
        assert stats.total_calls == 3
        assert stats.successful_calls == 2
        assert stats.failed_calls == 1
        assert stats.min_duration_ms == 10.0
        assert stats.max_duration_ms == 30.0
        assert abs(stats.avg_duration_ms - 20.0) < 0.1

    def test_record_call_multiple_tools(self, tracker):
        """测试记录多个工具"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("edit_file", 20.0)
        tracker.record_success("create_file", 30.0)

        assert len(tracker._stats) == 3

    # =========================================================================
    # 查询接口测试
    # =========================================================================

    def test_get_tool_stats(self, tracker):
        """测试获取工具统计"""
        tracker.record_success("read_file", 50.0)

        stats = tracker.get_tool_stats("read_file")
        assert stats is not None
        assert stats.tool_name == "read_file"
        assert stats.total_calls == 1

    def test_get_tool_stats_nonexistent(self, tracker):
        """测试获取不存在的工具统计"""
        stats = tracker.get_tool_stats("nonexistent")
        assert stats is None

    def test_get_all_stats(self, tracker):
        """测试获取所有统计"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("edit_file", 20.0)

        all_stats = tracker.get_all_stats()
        assert len(all_stats) == 2

    def test_get_usage_stats(self, tracker):
        """测试获取使用统计"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("read_file", 20.0)
        tracker.record_failure("edit_file", 30.0, "error")

        stats = tracker.get_usage_stats()

        assert stats["total_tools"] == 2
        assert stats["total_calls"] == 3
        assert stats["total_successful"] == 2
        assert stats["total_failed"] == 1
        assert stats["overall_success_rate"] == 2/3

    def test_get_most_used_tools(self, tracker):
        """测试获取最常用工具"""
        for _ in range(5):
            tracker.record_success("read_file", 10.0)
        for _ in range(3):
            tracker.record_success("edit_file", 20.0)
        tracker.record_success("create_file", 30.0)

        most_used = tracker.get_most_used_tools(limit=2)
        assert len(most_used) == 2
        assert most_used[0].tool_name == "read_file"
        assert most_used[1].tool_name == "edit_file"

    def test_get_fastest_tools(self, tracker):
        """测试获取最快工具"""
        tracker.record_success("slow_tool", 200.0)
        tracker.record_success("slow_tool", 300.0)
        tracker.record_success("fast_tool", 5.0)
        tracker.record_success("fast_tool", 10.0)
        tracker.record_success("medium_tool", 50.0)

        fastest = tracker.get_fastest_tools(limit=2, min_calls=2)
        assert fastest[0].tool_name == "fast_tool"

    def test_get_slowest_tools(self, tracker):
        """测试获取最慢工具"""
        tracker.record_success("slow_tool", 200.0)
        tracker.record_success("slow_tool", 300.0)
        tracker.record_success("fast_tool", 5.0)

        slowest = tracker.get_slowest_tools(limit=1, min_calls=2)
        assert slowest[0].tool_name == "slow_tool"

    def test_get_most_reliable_tools(self, tracker):
        """测试获取最可靠工具"""
        # 高成功率
        for _ in range(10):
            tracker.record_success("reliable", 10.0)
        # 低成功率
        tracker.record_success("unreliable", 10.0)
        tracker.record_failure("unreliable", 10.0, "error")
        tracker.record_failure("unreliable", 10.0, "error")

        reliable = tracker.get_most_reliable_tools(limit=1, min_calls=2)
        assert reliable[0].tool_name == "reliable"

    def test_get_problematic_tools(self, tracker):
        """测试获取问题工具"""
        tracker.record_success("good", 10.0)
        tracker.record_failure("bad", 10.0, "error")
        tracker.record_failure("bad", 10.0, "error")
        tracker.record_failure("bad", 10.0, "error")

        problematic = tracker.get_problematic_tools(min_calls=2)
        assert len(problematic) == 1
        assert problematic[0].tool_name == "bad"

    def test_get_tools_by_category(self, tracker):
        """测试按类别分组工具"""
        tracker.record_success("read_file_tool", 10.0)
        tracker.record_success("read_memory_tool", 10.0)
        tracker.record_success("grep_search_tool", 10.0)
        tracker.record_success("some_tool", 10.0)

        categories = tracker.get_tools_by_category()

        # 验证至少有 memory 和 search 类别的工具
        assert len(categories["memory"]) >= 1
        assert len(categories["search"]) >= 1

    def test_get_recent_calls(self, tracker):
        """测试获取最近调用"""
        for i in range(10):
            tracker.record_success("read_file", 10.0)

        recent = tracker.get_recent_calls(limit=5)
        assert len(recent) == 5

    def test_get_recent_calls_by_tool(self, tracker):
        """测试按工具获取最近调用"""
        for _ in range(5):
            tracker.record_success("read_file", 10.0)
        for _ in range(3):
            tracker.record_success("edit_file", 10.0)

        recent = tracker.get_recent_calls(tool_name="read_file", limit=10)
        assert all(c.tool_name == "read_file" for c in recent)

    # =========================================================================
    # 分析测试
    # =========================================================================

    def test_analyze_tools(self, tracker):
        """测试分析工具"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("edit_file", 20.0)

        report = tracker.analyze_tools()

        assert isinstance(report, ToolAnalysisReport)
        assert report.total_tools == 2
        assert report.total_calls == 2
        assert 0.0 <= report.overall_success_rate <= 1.0

    def test_generate_report(self, tracker):
        """测试生成报告"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("edit_file", 20.0)

        report = tracker.generate_report()

        assert "# 工具使用效果报告" in report
        assert "概览" in report

    # =========================================================================
    # 持久化测试
    # =========================================================================

    def test_stats_persisted(self, tmp_path):
        """测试统计持久化"""
        # 第一次记录
        tracker1 = ToolTracker(project_root=str(tmp_path))
        tracker1.record_success("read_file", 50.0)

        # 重新创建实例
        tracker2 = ToolTracker(project_root=str(tmp_path))
        assert "read_file" in tracker2._stats

        stats = tracker2.get_tool_stats("read_file")
        assert stats.total_calls == 1

    # =========================================================================
    # 清除测试
    # =========================================================================

    def test_clear_stats(self, tracker):
        """测试清除统计"""
        tracker.record_success("read_file", 10.0)
        tracker.record_success("edit_file", 20.0)

        tracker.clear_stats()

        assert len(tracker._stats) == 0
        assert len(tracker._recent_calls) == 0

    # =========================================================================
    # 错误分类测试
    # =========================================================================

    def test_classify_error_timeout(self, tracker):
        """测试分类超时错误"""
        assert tracker._classify_error("timeout error") == "超时"
        assert tracker._classify_error("请求超时") == "超时"

    def test_classify_error_syntax(self, tracker):
        """测试分类语法错误"""
        assert tracker._classify_error("syntax error") == "语法错误"
        assert tracker._classify_error("语法错误") == "语法错误"

    def test_classify_error_permission(self, tracker):
        """测试分类权限错误"""
        assert tracker._classify_error("permission denied") == "权限错误"
        assert tracker._classify_error("权限被拒绝") == "权限错误"

    def test_classify_error_not_found(self, tracker):
        """测试分类不存在错误"""
        assert tracker._classify_error("file not found") == "文件不存在"
        assert tracker._classify_error("找不到文件") == "文件不存在"

    def test_classify_error_other(self, tracker):
        """测试分类其他错误"""
        assert tracker._classify_error("some random error") == "其他错误"


class TestToolStats:
    """工具统计测试"""

    def test_tool_stats_to_dict(self):
        """测试工具统计转字典"""
        stats = ToolStats(
            tool_name="read_file",
            total_calls=10,
            successful_calls=8,
            failed_calls=2,
            total_duration_ms=100.0,
            min_duration_ms=5.0,
            max_duration_ms=20.0,
            success_rate=0.8,
            avg_duration_ms=10.0,
        )

        data = stats.to_dict()

        assert data["tool_name"] == "read_file"
        assert data["total_calls"] == 10
        assert data["success_rate"] == 0.8


class TestToolCallRecord:
    """工具调用记录测试"""

    def test_call_record_creation(self):
        """测试创建调用记录"""
        record = ToolCallRecord(
            tool_name="read_file",
            timestamp="2026-04-16",
            duration_ms=50.0,
            success=True,
        )

        assert record.tool_name == "read_file"
        assert record.success is True
        assert record.error is None
