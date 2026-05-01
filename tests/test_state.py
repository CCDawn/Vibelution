#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态管理器测试 (test_state.py)

测试 core/infrastructure/state.py 中的：
- AgentState 枚举
- StateManager 单例模式与线程安全
- 状态转换与历史记录
- 全局操作历史（防重复）
- 世代管理
- 计数管理
- 状态持久化
- 事件总线集成
- 便捷函数
"""

import os
import json
import sys
import threading
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.infrastructure.state import (
    AgentState,
    StateRecord,
    StateManager,
    get_state_manager,
    get_current_state,
)


# ============================================================================
# AgentState 枚举测试
# ============================================================================

class TestAgentStateEnum:
    """AgentState 枚举测试"""

    def test_all_states_exist(self):
        """验证所有 10 个状态值存在"""
        expected = {
            "idle", "awakening", "thinking", "searching", "coding",
            "testing", "compressing", "hibernating", "restarting",
            "planning", "error",
        }
        actual = {s.value for s in AgentState}
        assert actual == expected

    def test_state_values_are_strings(self):
        """验证状态值都是字符串"""
        for state in AgentState:
            assert isinstance(state.value, str)

    def test_state_uniqueness(self):
        """验证所有状态值唯一"""
        values = [s.value for s in AgentState]
        assert len(values) == len(set(values))


# ============================================================================
# StateManager 单例模式测试
# ============================================================================

class TestStateManagerSingleton:
    """StateManager 单例模式测试"""

    def test_get_state_manager_returns_same_instance(self):
        """多次调用 get_state_manager 返回同一实例"""
        sm1 = get_state_manager()
        sm2 = get_state_manager()
        assert sm1 is sm2

    def test_direct_construction_returns_same_instance(self):
        """直接构造也返回同一实例"""
        sm1 = get_state_manager()
        sm2 = StateManager()
        assert sm1 is sm2

    def test_singleton_thread_safety(self):
        """多线程同时获取单例不产生多个实例"""
        instances = []

        def get_instance():
            instances.append(get_state_manager())

        threads = [threading.Thread(target=get_instance) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = instances[0]
        for inst in instances[1:]:
            assert inst is first

    def test_initial_state_is_idle(self):
        """初始状态为 IDLE"""
        sm = StateManager()
        sm.reset()
        assert sm.state == AgentState.IDLE
        assert sm.get_state() == AgentState.IDLE


# ============================================================================
# 状态转换测试
# ============================================================================

class TestStateTransitions:
    """状态转换测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前重置状态管理器"""
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_set_state_changes_current_state(self):
        """set_state 改变当前状态"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        assert sm.state == AgentState.THINKING

    def test_set_state_tracks_previous_state(self):
        """set_state 记录前一个状态"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        assert sm.previous_state == AgentState.IDLE  # 初始状态
        sm.set_state(AgentState.CODING)
        assert sm.previous_state == AgentState.THINKING

    def test_set_state_updates_action(self):
        """set_state 更新动作描述"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, action="开始思考")
        info = sm.get_state_info()
        assert info["action"] == "开始思考"

    def test_set_state_updates_iteration_count(self):
        """set_state 更新迭代计数"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, iteration_count=42)
        info = sm.get_state_info()
        assert info["iteration_count"] == 42

    def test_set_state_updates_tools_executed(self):
        """set_state 更新工具执行计数"""
        sm = get_state_manager()
        sm.set_state(AgentState.CODING, tools_executed=10)
        info = sm.get_state_info()
        assert info["tools_executed"] == 10

    def test_set_state_updates_generation(self):
        """set_state 更新世代"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, generation=5)
        info = sm.get_state_info()
        assert info["generation"] == 5

    def test_set_state_updates_current_goal(self):
        """set_state 更新当前目标"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, current_goal="测试目标")
        info = sm.get_state_info()
        assert info["current_goal"] == "测试目标"

    def test_set_state_stores_metadata(self):
        """set_state 存储额外元数据"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, reason="unit test", priority=1)
        history = sm.get_history(1)
        assert history[0].metadata.get("reason") == "unit test"
        assert history[0].metadata.get("priority") == 1

    def test_is_state_returns_true_for_current(self):
        """is_state 对当前状态返回 True"""
        sm = get_state_manager()
        sm.set_state(AgentState.SEARCHING)
        assert sm.is_state(AgentState.SEARCHING) is True
        assert sm.is_state(AgentState.CODING) is False

    def test_is_any_state_returns_true_for_match(self):
        """is_any_state 对匹配的状态返回 True"""
        sm = get_state_manager()
        sm.set_state(AgentState.CODING)
        assert sm.is_any_state(AgentState.CODING, AgentState.TESTING) is True
        assert sm.is_any_state(AgentState.IDLE, AgentState.ERROR) is False

    def test_optional_params_not_set_keep_old_values(self):
        """未传入的参数不覆盖旧值"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, action="第一次", generation=3)
        sm.set_state(AgentState.CODING, action="第二次")
        info = sm.get_state_info()
        assert info["action"] == "第二次"
        assert info["generation"] == 3  # 未传入，保留旧值


# ============================================================================
# 状态历史测试
# ============================================================================

class TestStateHistory:
    """状态历史测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_history_records_transitions(self):
        """每次状态转换记录到历史"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.set_state(AgentState.CODING)
        sm.set_state(AgentState.TESTING)
        history = sm.get_history(10)
        assert len(history) == 3

    def test_history_records_correct_state_values(self):
        """历史记录包含正确的状态值"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.set_state(AgentState.CODING)
        history = sm.get_history(10)
        assert history[0].state == "thinking"
        assert history[1].state == "coding"

    def test_history_records_timestamp(self):
        """历史记录包含时间戳"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        history = sm.get_history(1)
        assert history[0].timestamp is not None
        assert isinstance(history[0].timestamp, str)

    def test_history_respects_limit(self):
        """get_history 遵守 limit 参数"""
        sm = get_state_manager()
        for i in range(20):
            sm.set_state(AgentState.THINKING)
        assert len(sm.get_history(5)) == 5
        assert len(sm.get_history(15)) == 15

    def test_history_max_cap_enforced(self):
        """历史记录最多保留 100 条"""
        sm = get_state_manager()
        for i in range(150):
            sm.set_state(AgentState.THINKING, action=f"action_{i}")
        history = sm.get_history(200)
        assert len(history) == 100

    def test_history_max_cap_removes_oldest(self):
        """超出限制时删除最旧的记录"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, action="first")
        for i in range(100):
            sm.set_state(AgentState.CODING, action=f"filler_{i}")
        history = sm.get_history(200)
        # "first" 应该已被挤出
        actions = [r.action for r in history]
        assert "first" not in actions

    def test_empty_history_returns_empty_list(self):
        """reset 后历史为空"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.reset()
        history = sm.get_history(10)
        assert history == []

    def test_history_state_record_fields(self):
        """StateRecord 包含所有必要字段"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, action="test")
        record = sm.get_history(1)[0]
        assert record.state == "thinking"
        assert record.action == "test"
        assert record.timestamp is not None


# ============================================================================
# 全局操作历史（防重复）测试
# ============================================================================

class TestRecentActions:
    """全局操作历史测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_add_recent_action_appends(self):
        """add_recent_action 添加操作"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        assert sm._recent_actions == ["read_file"]

    def test_consecutive_same_action_increments_counter(self):
        """连续相同操作递增计数器"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        assert sm.get_consecutive_count() == 3

    def test_different_action_resets_counter(self):
        """不同操作重置计数器"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        sm.add_recent_action("edit_file")
        assert sm.get_consecutive_count() == 1

    def test_is_action_recent_below_threshold_false(self):
        """连续次数低于阈值返回 False"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        assert sm.is_action_recent("read_file", threshold=3) is False

    def test_is_action_recent_above_threshold_true(self):
        """连续次数达到阈值返回 True"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        sm.add_recent_action("read_file")
        assert sm.is_action_recent("read_file", threshold=3) is True

    def test_is_action_recent_different_action_false(self):
        """最近操作不同时返回 False"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        assert sm.is_action_recent("edit_file", threshold=3) is False

    def test_is_action_recent_empty_history_false(self):
        """历史为空返回 False"""
        sm = get_state_manager()
        assert sm.is_action_recent("any_action") is False

    def test_recent_actions_max_cap(self):
        """最近操作最多保留 50 条"""
        sm = get_state_manager()
        for i in range(60):
            sm.add_recent_action(f"action_{i}")
        assert len(sm._recent_actions) == 50

    def test_clear_recent_actions(self):
        """清除最近操作"""
        sm = get_state_manager()
        sm.add_recent_action("read_file")
        sm.add_recent_action("edit_file")
        sm.clear_recent_actions()
        assert sm._recent_actions == []
        assert sm.get_consecutive_count() == 0


# ============================================================================
# 世代管理测试
# ============================================================================

class TestGenerationManagement:
    """世代管理测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_generation_persists_after_reset(self):
        """reset 后世代保留原值（世代跨会话持久化）"""
        sm = get_state_manager()
        sm.set_generation(5)
        sm.reset()
        assert sm.get_generation() == 5

    def test_set_generation_updates_value(self):
        """set_generation 更新世代"""
        sm = get_state_manager()
        sm.set_generation(5)
        assert sm.get_generation() == 5

    def test_set_generation_negative(self):
        """允许设置负世代（不验证输入）"""
        sm = get_state_manager()
        sm.set_generation(-1)
        assert sm.get_generation() == -1


# ============================================================================
# 目标管理测试
# ============================================================================

class TestGoalManagement:
    """目标管理测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_goal_persists_after_reset(self):
        """reset 后目标保留原值（目标跨会话持久化）"""
        sm = get_state_manager()
        sm.set_current_goal("跨会话目标")
        sm.reset()
        assert sm.get_current_goal() == "跨会话目标"

    def test_set_current_goal(self):
        """设置当前目标"""
        sm = get_state_manager()
        sm.set_current_goal("完成单元测试")
        assert sm.get_current_goal() == "完成单元测试"

    def test_set_current_goal_empty_string(self):
        """允许空字符串目标"""
        sm = get_state_manager()
        sm.set_current_goal("")
        assert sm.get_current_goal() == ""


# ============================================================================
# 计数器管理测试
# ============================================================================

class TestCounterManagement:
    """计数器管理测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_initial_counters_are_zero(self):
        """初始计数器为 0"""
        sm = get_state_manager()
        sm.reset()
        info = sm.get_state_info()
        assert info["iteration_count"] == 0
        assert info["tools_executed"] == 0

    def test_increment_iteration(self):
        """递增迭代计数"""
        sm = get_state_manager()
        sm.increment_iteration()
        sm.increment_iteration()
        assert sm.get_state_info()["iteration_count"] == 2

    def test_increment_tools_executed(self):
        """递增工具执行计数"""
        sm = get_state_manager()
        sm.increment_tools_executed()
        sm.increment_tools_executed()
        sm.increment_tools_executed()
        assert sm.get_state_info()["tools_executed"] == 3

    def test_reset_counters(self):
        """重置计数器"""
        sm = get_state_manager()
        sm.increment_iteration()
        sm.increment_tools_executed()
        sm.reset_counters()
        info = sm.get_state_info()
        assert info["iteration_count"] == 0
        assert info["tools_executed"] == 0


# ============================================================================
# 状态持久化测试
# ============================================================================

class TestStatePersistence:
    """状态持久化测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_save_state_creates_file(self, tmp_path):
        """save_state 创建文件"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.set_generation(3)

        filepath = tmp_path / "test_state.json"
        result = sm.save_state(str(filepath))
        assert os.path.exists(result)

    def test_save_state_writes_correct_data(self, tmp_path):
        """save_state 写入正确的状态数据"""
        sm = get_state_manager()
        sm.set_state(AgentState.CODING)
        sm.set_generation(7)
        sm.set_current_goal("持久化测试")

        filepath = tmp_path / "test_state.json"
        sm.save_state(str(filepath))

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["state"] == "coding"
        assert data["generation"] == 7
        assert data["current_goal"] == "持久化测试"

    def test_save_state_includes_recent_actions(self, tmp_path):
        """save_state 包含最近操作（最多 10 条）"""
        sm = get_state_manager()
        for i in range(15):
            sm.add_recent_action(f"action_{i}")

        filepath = tmp_path / "test_state.json"
        sm.save_state(str(filepath))

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["recent_actions"]) == 10

    def test_load_state_restores_state(self, tmp_path):
        """load_state 恢复状态"""
        sm = get_state_manager()
        sm.set_state(AgentState.SEARCHING)
        sm.set_generation(4)
        sm.set_current_goal("恢复测试")

        filepath = tmp_path / "test_state.json"
        sm.save_state(str(filepath))

        sm.reset()
        result = sm.load_state(str(filepath))

        assert result is True
        assert sm.state == AgentState.SEARCHING
        assert sm.get_generation() == 4
        assert sm.get_current_goal() == "恢复测试"

    def test_load_state_nonexistent_file_returns_false(self):
        """加载不存在的文件返回 False"""
        sm = get_state_manager()
        result = sm.load_state("/nonexistent/path/state.json")
        assert result is False

    def test_save_and_load_roundtrip(self, tmp_path):
        """保存后加载往返一致"""
        sm = get_state_manager()
        sm.set_state(AgentState.TESTING)
        sm.set_generation(42)
        sm.set_current_goal("往返测试")
        sm.increment_iteration()
        sm.increment_iteration()
        sm.increment_tools_executed()
        for i in range(5):
            sm.add_recent_action(f"action_{i}")

        filepath = tmp_path / "roundtrip.json"
        sm.save_state(str(filepath))

        sm2 = StateManager()
        sm2.reset()
        sm2.load_state(str(filepath))

        assert sm2.state == AgentState.TESTING
        assert sm2.get_generation() == 42
        assert sm2.get_current_goal() == "往返测试"


# ============================================================================
# reset 测试
# ============================================================================

class TestReset:
    """reset 测试"""

    def test_reset_clears_state_to_idle(self):
        """reset 后状态恢复为 IDLE"""
        sm = get_state_manager()
        sm.set_state(AgentState.CODING)
        sm.reset()
        assert sm.state == AgentState.IDLE

    def test_reset_clears_previous_state(self):
        """reset 清除前一个状态"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.set_state(AgentState.CODING)
        sm.reset()
        assert sm.previous_state is None

    def test_reset_clears_history(self):
        """reset 清除历史"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        sm.set_state(AgentState.CODING)
        sm.reset()
        assert sm.get_history(10) == []

    def test_reset_clears_counters(self):
        """reset 清除计数器"""
        sm = get_state_manager()
        sm.increment_iteration()
        sm.increment_tools_executed()
        sm.reset()
        info = sm.get_state_info()
        assert info["iteration_count"] == 0
        assert info["tools_executed"] == 0

    def test_reset_clears_recent_actions(self):
        """reset 清除最近操作"""
        sm = get_state_manager()
        sm.add_recent_action("test")
        sm.reset()
        assert sm._recent_actions == []
        assert sm.get_consecutive_count() == 0

    def test_reset_clears_action(self):
        """reset 清除动作"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING, action="test")
        sm.reset()
        info = sm.get_state_info()
        assert info["action"] is None


# ============================================================================
# 便捷函数测试
# ============================================================================

class TestConvenienceFunctions:
    """便捷函数测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_get_current_state_returns_correct_state(self):
        """get_current_state 返回正确状态"""
        sm = get_state_manager()
        sm.set_state(AgentState.THINKING)
        assert get_current_state() == AgentState.THINKING

    def test_get_state_info_returns_all_fields(self):
        """get_state_info 返回所有字段"""
        sm = get_state_manager()
        info = sm.get_state_info()
        expected_keys = {
            "state", "previous_state", "action",
            "iteration_count", "tools_executed",
            "generation", "current_goal",
        }
        assert set(info.keys()) == expected_keys


# ============================================================================
# StateRecord 数据类测试
# ============================================================================

class TestStateRecord:
    """StateRecord 数据类测试"""

    def test_state_record_creation(self):
        """StateRecord 创建"""
        record = StateRecord(
            state="thinking",
            timestamp="2026-04-30T12:00:00",
            action="test",
        )
        assert record.state == "thinking"
        assert record.action == "test"

    def test_state_record_defaults(self):
        """StateRecord 默认值"""
        record = StateRecord(state="idle", timestamp="2026-04-30T12:00:00")
        assert record.action is None
        assert record.iteration_count is None
        assert record.metadata == {}


# ============================================================================
# 线程安全测试
# ============================================================================

class TestThreadSafety:
    """线程安全测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        sm = get_state_manager()
        sm.reset()
        yield
        sm.reset()

    def test_concurrent_state_transitions(self):
        """并发状态转换不会导致数据损坏"""
        sm = get_state_manager()
        errors = []

        def transition(i):
            try:
                sm.set_state(AgentState.THINKING, action=f"thread_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert sm.state == AgentState.THINKING

    def test_concurrent_counter_increments(self):
        """并发计数器递增不会丢失"""
        sm = get_state_manager()
        iterations = 100
        threads = [
            threading.Thread(target=sm.increment_iteration)
            for _ in range(iterations)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sm.get_state_info()["iteration_count"] == iterations

    def test_concurrent_add_recent_actions(self):
        """并发添加操作不会丢失数据"""
        sm = get_state_manager()

        def add_action(i):
            sm.add_recent_action(f"action_{i}")

        threads = [threading.Thread(target=add_action, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(sm._recent_actions) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
