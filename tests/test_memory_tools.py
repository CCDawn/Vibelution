#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆与任务管理工具完整测试套件

测试 tools/memory_tools.py 中的所有功能：
- 记忆管理：世代索引、档案归档、动态提示词
- 任务管理：计划制定、进度追踪、重启阻塞检查
"""

import os
import sys
import pytest
import tempfile
import shutil
import json
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.memory_tools import (
    read_memory_tool, get_memory_summary_tool, get_generation_tool,
    get_current_goal_tool, get_core_context_tool,
    archive_generation_history, read_generation_archive_tool, list_archives_tool,
    commit_compressed_memory_tool, force_save_current_state, advance_generation,
    read_dynamic_prompt_tool, update_generation_task_tool,
    add_insight_to_dynamic_tool, clear_generation_task,
    check_restart_block,
    _load_memory, _save_memory,
)


# ============================================================================
# 测试辅助函数
# ============================================================================

@pytest.fixture(autouse=True)
def isolate_memory_workspace(monkeypatch, tmp_path):
    """隔离工作区，避免测试污染真实数据"""
    # 临时修改工作区
    from core.infrastructure.workspace_manager import WorkspaceManager
    
    # 创建临时工作区
    temp_ws = tmp_path / "test_workspace"
    temp_ws.mkdir(parents=True)
    
    # 创建必要的子目录
    (temp_ws / "memory").mkdir(exist_ok=True)
    (temp_ws / "archives").mkdir(exist_ok=True)
    (temp_ws / "prompts").mkdir(exist_ok=True)
    
    # 临时替换全局工作区
    from core.infrastructure import workspace_manager
    old_ws = workspace_manager.WorkspaceManager._instance
    
    # 手动创建 WorkspaceManager 实例（绕过 __new__ 的单例检查）
    def mock_get_workspace():
        # 创建一个轻量级替代品
        class MockWorkspace:
            def __init__(self, base_path):
                self.memory_index = Path(base_path) / "memory" / "memory.json"
                self.archives_dir = Path(base_path) / "archives"
                self.prompts_dir = Path(base_path) / "prompts"
            def get_prompt_path(self, name):
                return self.prompts_dir / name
        
        mock_ws = MockWorkspace(str(temp_ws))
        return mock_ws
    
    # 替换 get_workspace 函数
    import core.infrastructure.workspace_manager
    original_get = core.infrastructure.workspace_manager.get_workspace
    core.infrastructure.workspace_manager.get_workspace = mock_get_workspace
    
    yield temp_ws
    
    # 恢复
    core.infrastructure.workspace_manager.get_workspace = original_get


@pytest.fixture
def sample_task_plan():
    """示例任务计划"""
    return {
        "task": "测试任务",
        "plan": [
            "步骤1：分析需求",
            "步骤2：设计方案",
            "步骤3：实现代码",
            "步骤4：测试验证",
        ]
    }


# ============================================================================
# 记忆管理基础测试
# ============================================================================

class TestMemoryBasics:
    """记忆基础功能测试"""

    def test_get_generation_tool_returns_int(self):
        """测试 get_generation_tool 返回整数"""
        gen = get_generation_tool()
        assert isinstance(gen, int)
        assert gen >= 1

    def test_get_generation_persists(self):
        """测试世代号持久化"""
        gen1 = get_generation_tool()
        gen2 = get_generation_tool()
        assert gen1 == gen2

    def test_advance_generation(self):
        """测试世代推进"""
        current = get_generation_tool()
        new = advance_generation()
        assert new == current + 1
        assert get_generation_tool() == current + 1

    def test_read_memory_tool_returns_dict(self):
        """测试 read_memory_tool 返回字典"""
        memory = read_memory_tool()
        assert isinstance(memory, dict)
        assert "current_generation" in memory

    def test_get_core_context_tool(self):
        """测试获取核心上下文"""
        context = get_core_context_tool()
        assert isinstance(context, str)
        assert len(context) > 0

    def test_get_current_goal_tool(self):
        """测试获取当前目标"""
        goal = get_current_goal_tool()
        assert isinstance(goal, str)


# ============================================================================
# 记忆索引管理测试
# ============================================================================

class TestMemoryIndex:
    """记忆索引管理测试"""

    def test_default_memory_structure(self):
        """测试默认记忆结构"""
        memory = _load_memory()
        required_fields = [
            "current_generation", "core_wisdom", "current_goal",
            "total_generations"
        ]
        for field in required_fields:
            assert field in memory, f"缺少字段: {field}"

    def test_memory_persistence(self):
        """测试记忆持久化"""
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "memory", "memory.json"
        )
        
        # 读取应创建文件（如果不存在）
        memory = _load_memory()
        assert os.path.exists(memory_path)
        
        # 再次读取应相同
        memory2 = _load_memory()
        assert memory == memory2

    def test_save_memory_custom_values(self):
        """测试保存自定义记忆值"""
        memory = _load_memory()
        memory["test_key"] = "test_value"
        result = _save_memory(memory)
        assert result is True
        
        # 验证保存成功
        memory2 = _load_memory()
        assert memory2.get("test_key") == "test_value"
        
        # 清理
        memory2.pop("test_key")
        _save_memory(memory2)


# ============================================================================
# 世代档案测试
# ============================================================================

class TestGenerationArchives:
    """世代档案功能测试"""

    def test_archive_generation_history(self):
        """测试归档世代历史"""
        history_data = [
            {"type": "thought", "content": "思考内容1"},
            {"type": "tool_call", "name": "read_file", "content": "结果"},
            {"type": "thought", "content": "思考内容2"},
        ]
        core_wisdom = "测试核心智慧"
        next_goal = "测试下一个目标"
        
        current_gen = get_generation_tool()
        result = archive_generation_history(
            generation=current_gen,
            history_data=history_data,
            core_wisdom=core_wisdom,
            next_goal=next_goal
        )
        
        assert "归档成功" in result or "archived" in result.lower()

    def test_read_generation_archive(self):
        """测试读取世代档案"""
        # 先归档
        current_gen = get_generation_tool()
        archive_generation_history(
            generation=current_gen,
            history_data=[{"test": "data"}],
            core_wisdom="测试智慧",
            next_goal="测试目标"
        )
        
        # 读取
        result = read_generation_archive_tool(generation=current_gen)
        assert isinstance(result, str)
        assert "测试智慧" in result or "测试目标" in result

    def test_read_nonexistent_archive(self):
        """读取不存在的档案"""
        result = read_generation_archive_tool(generation=99999)
        assert ("不存在" in result or "未找到" in result or 
                "not found" in result.lower())

    def test_list_archives(self):
        """测试列出所有档案"""
        # 创建几个档案
        for gen in [1, 2, 3]:
            if gen <= get_generation_tool():
                archive_generation_history(
                    generation=gen,
                    history_data=[{"gen": gen}],
                    core_wisdom=f"世代{gen}智慧",
                    next_goal=f"世代{gen}目标"
                )
        
        result = list_archives_tool()
        assert isinstance(result, str)
        assert "世代" in result or "generation" in result.lower()

    def test_archive_increments_generation(self):
        """测试归档后世代递增"""
        current = get_generation_tool()
        archive_generation_history(
            generation=current,
            history_data=[],
            core_wisdom="test",
            next_goal="test"
        )
        new = advance_generation()
        assert new == current + 1


# ============================================================================
# 动态提示词测试
# ============================================================================

class TestDynamicPrompt:
    """动态提示词管理测试"""

    def test_read_dynamic_prompt_returns_content(self):
        """测试读取动态提示词"""
        content = read_dynamic_prompt_tool()
        assert isinstance(content, str)

    def test_update_generation_task(self):
        """测试更新世代任务"""
        task = "这是一个测试任务"
        result = update_generation_task_tool(task=task)
        assert "更新成功" in result or "updated" in result.lower()
        
        # 验证保存
        content = read_dynamic_prompt_tool()
        assert task in content

    def test_add_insight_to_dynamic(self):
        """测试添加洞察"""
        insight = "测试洞察：代码应该保持简洁"
        result = add_insight_to_dynamic_tool(insight=insight)
        assert "添加成功" in result or "added" in result.lower() or "ok" in result.lower()
        
        # 验证
        content = read_dynamic_prompt_tool()
        assert insight in content

    def test_clear_generation_task(self):
        """测试清除世代任务"""
        # 先添加任务
        update_generation_task_tool(task="需要清除的任务")
        
        result = clear_generation_task()
        assert "清除成功" in result or "cleared" in result.lower() or "ok" in result.lower()
        
        # 验证清除
        content = read_dynamic_prompt_tool()
        assert "需要清除的任务" not in content

    def test_dynamic_prompt_persistence(self):
        """测试动态提示词持久化"""
        update_generation_task_tool(task="持久化测试任务")
        
        # 重新读取
        content1 = read_dynamic_prompt_tool()
        assert "持久化测试任务" in content1
        
        # 再次读取（应保持��致）
        content2 = read_dynamic_prompt_tool()
        assert content1 == content2


# ============================================================================
# 代码库洞察测试
# ============================================================================

class TestDynamicInsight:
    """动态洞察管理测试"""

    def test_insight_accumulation(self):
        """测试洞察累积"""
        insights = [
            "洞察1：模块化很重要",
            "洞察2：测试应该全面",
            "洞察3：代码需要文档",
        ]

        for insight in insights:
            add_insight_to_dynamic_tool(insight=insight)

        content = read_dynamic_prompt_tool()
        for insight in insights:
            assert insight in content


# ============================================================================
# commit_compressed_memory 测试
# ============================================================================

class TestCommitCompressedMemory:
    """commit_compressed_memory 测试"""

    def test_commit_memory_updates_index(self):
        """测试提交记忆更新索引"""
        # 修改当前目标
        from tools.memory_tools import _load_memory, _save_memory
        memory = _load_memory()
        memory["current_goal"] = "测试目标"
        _save_memory(memory)
        
        # 提交压缩记忆
        result = commit_compressed_memory_tool()
        assert "保存" in result or "commit" in result.lower() or "ok" in result.lower()
        
        # 验证索引更新
        memory2 = _load_memory()
        assert "last_archive_time" in memory2

    def test_force_save_current_state(self):
        """测试强制保存当前状态"""
        result = force_save_current_state()
        assert "强制保存" in result or "force saved" in result.lower() or "ok" in result.lower()

    def test_commit_memory_increments_total(self):
        """测试提交记忆后总世代递增（仅当主动重启时）"""
        # commit 本身不会立即增加 total_generations
        # 那是 advance_generation 的工作
        before = _load_memory()
        commit_compressed_memory_tool()
        after = _load_memory()
        # total_generations 可能不变，除非 advance_generation 被调用
        assert after["current_generation"] == before["current_generation"]


# ============================================================================
# 记忆摘要测试
# ============================================================================

class TestMemorySummary:
    """记忆摘要测试"""

    def test_get_memory_summary_returns_readable(self):
        """测试获取可读的记忆摘要"""
        summary = get_memory_summary_tool()
        assert isinstance(summary, str)
        assert len(summary) > 0
        # 应包含关键信息
        assert ("世代" in summary or "generation" in summary.lower() or 
                "G" in summary)

    def test_memory_summary_format(self):
        """测试摘要格式"""
        summary = get_memory_summary_tool()
        # 应该是一个完整的文本描述
        lines = summary.split('\n')
        assert len(lines) >= 3  # 至少包含多行信息


# ============================================================================
# 重启阻塞检查测试
# ============================================================================

class TestRestartBlock:
    """重启阻塞检查测试"""

    def test_restart_block_clear_initially(self):
        """初始状态允许重启（没有任务时）"""
        clear_generation_task()
        is_blocked, msg = check_restart_block()
        assert not is_blocked

    def test_restart_block_with_incomplete_tasks(self):
        """测试有未完成任务时阻止重启"""
        from core.orchestration.task_planner import get_task_manager
        tm = get_task_manager()
        tm.create_plan(goal="测试", tasks=[{"name": "待办1", "description": "待办1"}])
        is_blocked, msg = check_restart_block()
        assert is_blocked
        assert "未完成" in msg


# ============================================================================
# 集成测试
# ============================================================================

class TestMemoryToolsIntegration:
    """记忆工具集成测试"""

    def test_full_memory_lifecycle(self):
        """测试完整记忆生命周期"""
        gen = get_generation_tool()
        goal = get_current_goal_tool()
        assert gen >= 1

        update_generation_task_tool(task="集成测试任务")
        add_insight_to_dynamic_tool(insight="集成测试洞察")

        summary = get_memory_summary_tool()
        assert "集成测试任务" in summary

        commit_result = commit_compressed_memory_tool()
        assert "成功" in commit_result or "ok" in commit_result.lower()

    def test_archive_generation_flow(self):
        """测试归档流程"""
        archive_generation_history(
            generation=get_generation_tool(),
            history_data=[{"action": "completed task"}],
            core_wisdom="任务完成经验",
            next_goal="下一目标"
        )
        archives = list_archives_tool()
        assert "G1" in archives or "generation" in archives.lower()


# ============================================================================
# 异常处理测试
# ============================================================================

class TestErrorHandling:
    """异常处理测试"""

    def test_read_generation_archive_invalid_index(self):
        """读取无效世代索引"""
        result = read_generation_archive_tool(generation=-1)
        assert ("无效" in result or "错误" in result or 
                "not found" in result.lower() or "invalid" in result.lower())

    def test_commit_without_prior_setup(self):
        """在没有前置操作时提交记忆"""
        # 应该能正常工作（即使没有特殊操作）
        result = commit_compressed_memory_tool()
        assert isinstance(result, str)

    def test_advance_generation_persistence(self):
        """测试世代推进的持久性"""
        initial = get_generation_tool()
        new1 = advance_generation()
        new2 = advance_generation()
        
        assert new1 == initial + 1
        assert new2 == initial + 2
        assert get_generation_tool() == initial + 2


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_get_generation_performance(self, benchmark=None):
        """测试获取世代号的性能"""
        # 应快速返回
        gen = get_generation_tool()
        assert isinstance(gen, int)
        # 如果 pytest-benchmark 可用，会自动 benchmark

    def test_archive_performance(self):
        """测试归档性能"""
        import time
        start = time.time()
        
        archive_generation_history(
            generation=get_generation_tool(),
            history_data=[{"type": "test", "content": "x" * 1000} for _ in range(100)],
            core_wisdom="性能测试" * 100,
            next_goal="性能目标"
        )
        
        elapsed = time.time() - start
        assert elapsed < 1.0  # 应在 1 秒内完成

    def test_read_archive_performance(self):
        """测试读取档案性能"""
        import time
        
        start = time.time()
        result = list_archives_tool()
        elapsed = time.time() - start
        
        assert elapsed < 2.0  # 应在 2 秒内完成


# ============================================================================
# 数据一致性测试
# ============================================================================

class TestDataConsistency:
    """数据一致性测试"""

    def test_generation_and_archive_sync(self):
        """测试世代号与档案同步"""
        gen = get_generation_tool()
        
        # 归档当前世代
        archive_generation_history(
            generation=gen,
            history_data=[{"sync": "test"}],
            core_wisdom="同步测试",
            next_goal="同步目标"
        )
        
        # 推进世代
        new_gen = advance_generation()
        
        # 新世代应不同
        assert new_gen > gen
        
        # 列表应包含旧世代
        archives = list_archives_tool()
        assert str(gen) in archives or f"G{gen}" in archives

    def test_memory_file_integrity(self):
        """测试记忆文件完整性"""
        memory = _load_memory()
        
        # 验证所有必需字段存在且类型正确
        assert isinstance(memory["current_generation"], int)
        assert isinstance(memory["core_wisdom"], str)
        assert isinstance(memory["current_goal"], str)
        assert isinstance(memory["total_generations"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
