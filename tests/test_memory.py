#!/usr/bin/env python3
"""
记忆系统测试套件

测试内容：
1. 记忆读写功能
2. 上下文压缩
3. 档案列表

运行：pytest tests/test_memory.py -v
"""

import pytest
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 导入被测模块
from tools.memory_tools import (
    read_memory_tool,
    commit_compressed_memory_tool,
    get_current_goal_tool,
    get_core_context_tool,
    _load_memory,
    _save_memory,
    _get_memory_index_path,
    _get_archives_path,
)


# ============================================================================
# Fixtures — 隔离工作空间
# ============================================================================

@pytest.fixture(autouse=True)
def isolate_memory_workspace(monkeypatch, tmp_path):
    """
    将记忆系统的读写路径重定向到临时目录，避免污染真实 workspace。
    每个测试自动生效（autouse）。
    """
    memory_dir = tmp_path / "workspace" / "memory"
    archives_dir = memory_dir / "archives"
    memory_dir.mkdir(parents=True, exist_ok=True)
    archives_dir.mkdir(parents=True, exist_ok=True)

    memory_file = memory_dir / "memory.json"

    # 初始化一个干净的 memory.json
    import json
    default_memory = {
        "core_wisdom": "",
        "current_goal": "Initial test goal",
    }
    memory_file.write_text(json.dumps(default_memory, ensure_ascii=False), encoding="utf-8")

    # Monkeypatch 路径函数
    monkeypatch.setattr(
        "tools.memory_tools._get_memory_index_path",
        lambda: str(memory_file),
    )
    monkeypatch.setattr(
        "tools.memory_tools._get_archives_path",
        lambda: str(archives_dir),
    )

    yield tmp_path


class TestMemoryBasics:
    """基础记忆功能测试"""

    def test_load_memory_returns_dict(self):
        """测试加载记忆返回字典"""
        memory = _load_memory()
        assert isinstance(memory, dict), "记忆应该是字典类型"

    def test_memory_has_required_keys(self):
        """测试记忆包含必需字段"""
        memory = _load_memory()
        required_keys = ["core_wisdom", "current_goal"]
        for key in required_keys:
            assert key in memory, f"记忆应包含字段: {key}"

    def test_get_current_goal_returns_string(self):
        """测试获取目标返回字符串"""
        goal = get_current_goal_tool()
        assert isinstance(goal, str), "目标应该是字符串"

    def test_get_core_context_returns_string(self):
        """测试获取核心上下文返回字符串"""
        context = get_core_context_tool()
        assert isinstance(context, str), "上下文应该是字符串"


class TestMemoryWrite:
    """记忆写入测试"""

    def test_commit_compressed_memory_updates_core_wisdom(self):
        """测试提交压缩记忆更新核心智慧"""
        new_context = "测试：这是新的核心智慧"
        new_goal = "测试：完成记忆写入测试"

        result = commit_compressed_memory_tool(new_context, new_goal)
        result_dict = json.loads(result)

        assert result_dict["status"] == "success", "提交应该成功"
        assert result_dict["core_wisdom"] == new_context, "核心智慧应该更新"

    def test_commit_compressed_memory_truncates_long_context(self):
        """测试长上下文被截断"""
        long_context = "A" * 500  # 超过 300 字符
        result = commit_compressed_memory_tool(long_context, "测试目标")
        result_dict = json.loads(result)

        assert result_dict["status"] == "success"
        assert len(result_dict["core_wisdom"]) <= 300




class TestMemoryIntegration:
    """记忆系统集成测试"""

    def test_full_memory_lifecycle(self):
        """测试完整记忆生命周期"""
        # 1. 读取初始状态
        goal_before = get_current_goal_tool()

        # 2. 更新记忆
        new_wisdom = "集成测试：完整生命周期测试"
        new_goal = "集成测试：目标"
        commit_compressed_memory_tool(new_wisdom, new_goal)

        # 3. 验证更新
        memory = _load_memory()
        assert memory["core_wisdom"] == new_wisdom
        assert memory["current_goal"] == new_goal

        # 恢复原状态
        memory["current_goal"] = goal_before
        _save_memory(memory)


# ============================================================================
# 测试运行器（供 Agent 调用）
# ============================================================================

def run_memory_tests() -> dict:
    """
    运行所有记忆测试，返回结果摘要。
    """
    results = {"total": 0, "passed": 0, "failed": 0, "details": []}

    # 简单的手动测试
    test_cases = [
        ("load_memory", lambda: isinstance(_load_memory(), dict)),
        ("get_goal", lambda: isinstance(get_current_goal_tool(), str)),
        ("get_context", lambda: isinstance(get_core_context_tool(), str)),
        ("read_memory", lambda: "core_wisdom" in _load_memory()),
    ]

    for name, fn in test_cases:
        results["total"] += 1
        try:
            if fn():
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["details"].append(f"{name}: FAILED")
        except Exception as e:
            results["failed"] += 1
            results["details"].append(f"{name}: ERROR: {e}")

    return results


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
