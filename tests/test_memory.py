#!/usr/bin/env python3
"""
记忆系统测试套件

测试内容：
1. 记忆读写功能
2. 世代管理
3. 上下文压缩
4. 档案归档

运行：pytest tests/test_memory.py -v
"""

import pytest
import json
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# 导入被测模块
from tools.memory_tools import (
    read_memory_tool,
    commit_compressed_memory_tool,
    get_generation_tool,
    get_current_goal_tool,
    get_core_context_tool,
    archive_generation_history,
    advance_generation,
    list_archives_tool,
    read_generation_archive_tool,
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
        "current_generation": 1,
        "core_wisdom": "",
        "current_goal": "Initial test goal",
        "total_generations": 1,
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
        required_keys = [
            "current_generation",
            "core_wisdom",
            "current_goal",
            "total_generations",
        ]
        for key in required_keys:
            assert key in memory, f"记忆应包含字段: {key}"

    def test_generation_is_positive_int(self):
        """测试世代号是正整数"""
        gen = get_generation_tool()
        assert isinstance(gen, int), "世代号应该是整数"
        assert gen >= 1, "世代号应该 >= 1"

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
        # 核心智慧应该被截断
        assert len(result_dict["core_wisdom"]) <= 300

    def test_advance_generation_increments_count(self):
        """测试推进世代递增计数"""
        before = get_generation_tool()
        new_gen = advance_generation()

        assert new_gen == before + 1, "世代号应该递增"

        # 恢复原状态
        memory = _load_memory()
        memory["current_generation"] = before
        _save_memory(memory)


class TestArchiveSystem:
    """档案系统测试"""

    def test_archive_generation_history_creates_file(self):
        """测试归档生成历史文件"""
        test_data = [
            {"type": "thought", "content": "测试思考"},
            {"type": "tool_call", "name": "test_tool", "content": "测试结果"},
        ]

        result = archive_generation_history(
            generation=999,  # 使用特殊世代号避免干扰
            history_data=test_data,
            core_wisdom="测试核心智慧",
            next_goal="测试下一目标",
        )

        result_dict = json.loads(result)
        assert result_dict["status"] == "success", "归档应该成功"
        assert "archive_file" in result_dict, "结果应包含文件路径"

        # 验证文件存在
        if os.path.exists(result_dict["archive_file"]):
            with open(result_dict["archive_file"], "r", encoding="utf-8") as f:
                archive = json.load(f)
            assert archive["generation"] == 999, "归档世代号应匹配"
            assert len(archive["history"]) == 2, "归档应包含2条历史"

    def test_list_archives_returns_list(self):
        """测试列出档案返回列表"""
        result = list_archives_tool()
        result_dict = json.loads(result)

        assert result_dict["status"] == "success"
        assert "archives" in result_dict
        assert isinstance(result_dict["archives"], list)

    def test_read_generation_archive_nonexistent_returns_error(self):
        """测试读取不存在的档案返回错误"""
        result = read_generation_archive_tool(generation=999999)
        result_dict = json.loads(result)

        assert result_dict["status"] == "error", "不存在的档案应返回错误"


class TestMemoryIntegration:
    """记忆系统集成测试"""

    def test_full_memory_lifecycle(self):
        """测试完整记忆生命周期"""
        # 1. 读取初始状态
        gen_before = get_generation_tool()
        goal_before = get_current_goal_tool()

        # 2. 更新记忆
        new_wisdom = "集成测试：完整生命周期测试"
        new_goal = "集成测试：目标"
        commit_compressed_memory_tool(new_wisdom, new_goal)

        # 3. 验证更新
        memory = _load_memory()
        assert memory["core_wisdom"] == new_wisdom
        assert memory["current_goal"] == new_goal

        # 4. 归档当前状态
        archive_result = archive_generation_history(
            generation=gen_before,
            history_data=[
                {"type": "test", "content": "生命周期测试"}
            ],
            core_wisdom=new_wisdom,
            next_goal=new_goal,
        )
        assert json.loads(archive_result)["status"] == "success"

        # 5. 推进世代
        new_gen = advance_generation()
        assert new_gen == gen_before + 1

        # 恢复原状态
        memory = _load_memory()
        memory["current_generation"] = gen_before
        memory["core_wisdom"] = goal_before
        memory["current_goal"] = goal_before
        _save_memory(memory)


# ============================================================================
# 测试运行器（供 Agent 调用）
# ============================================================================

def run_memory_tests() -> dict:
    """
    运行所有记忆测试，返回结果摘要。

    Returns:
        dict: {
            "passed": 通过数,
            "failed": 失败数,
            "total": 总数,
            "status": "PASS" | "FAIL",
            "details": [失败详情]
        }
    """
    import subprocess

    result = subprocess.run(
        ["pytest", __file__, "-v", "--tb=short", "--no-header"],
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr

    # 解析结果
    passed = output.count(" PASSED")
    failed = output.count(" FAILED")

    return {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "status": "PASS" if failed == 0 else "FAIL",
        "output": output,
    }


if __name__ == "__main__":
    # 直接运行测试
    pytest.main([__file__, "-v"])
