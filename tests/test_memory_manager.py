#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Memory Manager 测试
"""

import pytest
from datetime import datetime


class TestShortTermMemory:
    """测试短期记忆"""

    def test_create_short_term_memory(self):
        """测试创建短期记忆"""
        from core.orchestration.memory_manager import ShortTermMemory
        memory = ShortTermMemory(session_id="test_session")
        assert memory.session_id == "test_session"
        assert len(memory.tool_calls) == 0
        assert len(memory.thoughts) == 0


class TestMidTermMemory:
    """测试中期记忆"""

    def test_create_mid_term_memory(self):
        """测试创建中期记忆"""
        from core.orchestration.memory_manager import MidTermMemory
        memory = MidTermMemory(generation=1)
        assert memory.generation == 1
        assert memory.current_task == ""
        assert len(memory.completed_tasks) == 0


class TestLongTermMemory:
    """测试长期记忆"""

    def test_create_long_term_memory(self):
        """测试创建长期记忆"""
        from core.orchestration.memory_manager import LongTermMemory
        memory = LongTermMemory()
        assert memory.current_generation == 1
        assert memory.total_generations == 1


class TestMemorySummary:
    """测试记忆摘要"""

    def test_create_summary(self):
        """测试创建摘要"""
        from core.orchestration.memory_manager import MemorySummary
        summary = MemorySummary(generation=1)
        assert summary.generation == 1


class TestMemoryManager:
    """测试记忆管理器"""

    def test_init(self):
        """测试初始化"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        assert manager.short_term is not None
        assert manager.mid_term is not None
        assert manager.long_term is not None

    def test_record_tool_call(self):
        """测试记录工具调用"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.record_tool_call(
            tool_name="read_file",
            args={"path": "test.py"},
            result="file content",
            success=True,
        )
        assert len(manager.short_term.tool_calls) == 1
        assert manager.short_term.tool_calls[0]["tool"] == "read_file"

    def test_record_thought(self):
        """测试记录思考"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.record_thought("Testing thought")
        assert len(manager.short_term.thoughts) == 1

    def test_record_user_input(self):
        """测试记录用户输入"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.record_user_input("Hello world")
        assert len(manager.short_term.user_inputs) == 1

    def test_set_current_task(self):
        """测试设置当前任务"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.set_current_task("Test task")
        assert manager.get_current_task() == "Test task"

    def test_add_insight(self):
        """测试添加洞察"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.add_insight("Important insight", category="test")
        insights = manager.get_insights(category="test")
        assert len(insights) == 1
        assert insights[0]["content"] == "Important insight"

    def test_add_code_insight(self):
        """测试添加代码洞察"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.add_code_insight("agent.py", "Code understanding")
        insights = manager.get_code_insights(module="agent.py")
        assert len(insights) == 1

    def test_get_insights_no_filter(self):
        """测试获取洞察（无过滤）"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.add_insight("Insight 1", category="a")
        manager.add_insight("Insight 2", category="b")
        insights = manager.get_insights()
        assert len(insights) == 2

    def test_set_core_wisdom(self):
        """测试设置核心智慧"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.set_core_wisdom("Be helpful")
        assert manager.get_core_wisdom() == "Be helpful"

    def test_update_skills_profile(self):
        """测试更新能力画像"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.update_skills_profile({"coding": 0.8})
        profile = manager.get_skills_profile()
        assert "coding" in profile
        assert profile["coding"] == 0.8

    def test_add_evolution_record(self):
        """测试添加进化记录"""
        from core.orchestration.memory_manager import MemoryManager, reset_memory_manager
        reset_memory_manager()  # 重置单例，避免测试间干扰
        manager = MemoryManager()
        manager.add_evolution_record({"gen": 1, "focus": "test"})
        assert len(manager.long_term.evolution_history) >= 1

    def test_get_summary(self):
        """测试获取摘要"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        summary = manager.get_summary()
        assert summary.generation >= 1

    def test_get_full_memory(self):
        """测试获取完整记忆"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        memory = manager.get_full_memory()
        assert "short_term" in memory
        assert "mid_term" in memory
        assert "long_term" in memory

    def test_get_statistics(self):
        """测试获取统计"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        stats = manager.get_statistics()
        assert "tool_calls_recorded" in stats

    def test_clear_short_term(self):
        """测试清除短期记忆"""
        from core.orchestration.memory_manager import MemoryManager
        manager = MemoryManager()
        manager.record_tool_call("test_tool", {}, "result")
        manager.clear_short_term()
        assert len(manager.short_term.tool_calls) == 0


class TestMemoryManagerIntegration:
    """集成测试"""

    def test_full_memory_lifecycle(self):
        """测试完整记忆生命周期"""
        from core.orchestration.memory_manager import MemoryManager

        manager = MemoryManager()

        # 短期记忆
        manager.record_tool_call("read_file", {"path": "a.py"}, "content")
        manager.record_thought("Thinking about the file")
        manager.record_user_input("User said hello")

        # 中期记忆
        manager.set_current_task("Refactoring task")
        manager.add_insight("Code can be simplified", category="code")
        manager.add_code_insight("a.py", "Simple module")

        # 长期记忆
        manager.set_core_wisdom("Write clean code")
        manager.update_skills_profile({"refactoring": 0.9})
        manager.add_evolution_record({"gen": 1, "focus": "init"})

        # 获取摘要
        summary = manager.get_summary()
        assert summary.generation >= 1

        # 获取完整记忆
        memory = manager.get_full_memory()
        assert memory["short_term"]["tool_call_count"] == 1
        assert memory["mid_term"]["current_task"] == "Refactoring task"
        assert memory["long_term"]["core_wisdom"] == "Write clean code"

        # 获取统计
        stats = manager.get_statistics()
        assert stats["tool_calls_recorded"] == 1
        assert stats["mid_term_insights"] == 1
