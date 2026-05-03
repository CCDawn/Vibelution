#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务计划器测试 (test_task_planner.py)

测试 core/orchestration/task_planner.py 中的：
- Singleton 模式
- Plan / PlanTask 数据模型
- TaskPlanner 风格 API (create_plan / get_current_plan / complete_task / update_task / create_task / get_task)
- TaskManager 风格 API (task_create / task_update / task_list / task_breakdown / task_prioritize)
- 双向同步一致性 (Plan API + TaskManager API 混用后 _plan.tasks 与 _task_list 必须同步)
- JSON 持久化往返
- 边界与异常处理
"""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def isolated_task_manager(tmp_path, monkeypatch):
    """
    创建隔离的 TaskManager 实例，所有持久化在 tmp_path 中进行。
    绕过单例模式，直接构造新实例。
    """
    tasks_dir = tmp_path / "workspace"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_file = tasks_dir / "tasks.json"

    # 重写 _tasks_json_path 指向 tmp_path
    monkeypatch.setattr(
        "core.orchestration.task_planner._tasks_json_path",
        lambda: str(tasks_file),
    )

    from core.orchestration.task_planner import TaskManager

    # 绕过单例
    old_instance = TaskManager._instance
    TaskManager._instance = None
    tm = TaskManager()
    yield tm
    TaskManager._instance = old_instance


# ============================================================================
# Singleton 测试
# ============================================================================

class TestTaskManagerSingleton:
    """Singleton 模式测试"""

    def test_get_task_manager_returns_instance(self):
        """get_task_manager 返回实例"""
        from core.orchestration.task_planner import get_task_manager
        tm = get_task_manager()
        assert tm is not None

    def test_get_task_manager_same_instance(self):
        """多次调用返回同一实例"""
        from core.orchestration.task_planner import get_task_manager
        tm1 = get_task_manager()
        tm2 = get_task_manager()
        assert tm1 is tm2


# ============================================================================
# Plan / PlanTask 数据模型测试
# ============================================================================

class TestDataModels:
    """Plan 和 PlanTask 数据模型测试"""

    def test_plan_task_defaults(self):
        """PlanTask 默认值"""
        from core.orchestration.task_planner import PlanTask
        from core.prompt_manager.task_analyzer import TaskStatus

        pt = PlanTask(id="1", name="Test", description="Desc")
        assert pt.id == "1"
        assert pt.name == "Test"
        assert pt.description == "Desc"
        assert pt.status == TaskStatus.PENDING
        assert pt.result_summary == ""
        assert pt.substeps == []

    def test_plan_defaults(self):
        """Plan 默认值"""
        from core.orchestration.task_planner import Plan

        p = Plan()
        assert p.goal == ""
        assert p.tasks == {}
        assert p.created_at == ""

    def test_plan_with_goal(self):
        """带 goal 的 Plan"""
        from core.orchestration.task_planner import Plan

        p = Plan(goal="Test goal")
        assert p.goal == "Test goal"


# ============================================================================
# TaskPlanner 风格 API 测试
# ============================================================================

class TestTaskPlannerAPI:
    """TaskPlanner 风格 API 测试"""

    def test_create_plan_sets_goal(self, isolated_task_manager):
        """create_plan 设置目标"""
        isolated_task_manager.create_plan("Build feature X", [
            {"name": "Task 1", "description": "Do something"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert plan is not None
        assert plan.goal == "Build feature X"

    def test_create_plan_creates_tasks(self, isolated_task_manager):
        """create_plan 创建任务"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "A", "description": "Task A"},
            {"name": "B", "description": "Task B"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert len(plan.tasks) == 2
        assert "1" in plan.tasks
        assert "2" in plan.tasks
        assert plan.tasks["1"].name == "A"
        assert plan.tasks["2"].name == "B"

    def test_create_plan_syncs_to_task_list(self, isolated_task_manager):
        """create_plan 同步到 _task_list"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc 1"},
        ])
        task_list = isolated_task_manager.task_list()
        assert len(task_list) == 1
        assert task_list[0]["id"] == 1
        assert task_list[0]["description"] == "Desc 1"
        assert task_list[0]["is_completed"] is False

    def test_create_plan_overwrites_previous(self, isolated_task_manager):
        """create_plan 覆盖旧计划"""
        isolated_task_manager.create_plan("First", [
            {"name": "Old", "description": "Old task"},
        ])
        isolated_task_manager.create_plan("Second", [
            {"name": "New", "description": "New task"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert plan.goal == "Second"
        assert len(plan.tasks) == 1
        assert "1" in plan.tasks
        assert plan.tasks["1"].name == "New"

    def test_create_plan_empty_tasks(self, isolated_task_manager):
        """create_plan 空任务列表"""
        isolated_task_manager.create_plan("Empty goal", [])
        plan = isolated_task_manager.get_current_plan()
        assert plan.goal == "Empty goal"
        assert len(plan.tasks) == 0
        assert isolated_task_manager.task_list() == []

    def test_create_plan_task_without_name(self, isolated_task_manager):
        """create_plan 任务无 name 时回退到 description"""
        isolated_task_manager.create_plan("Goal", [
            {"description": "Only desc"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert plan.tasks["1"].name == "Only desc"

    def test_get_current_plan_initially_none(self, isolated_task_manager):
        """初始无计划时返回 None"""
        assert isolated_task_manager.get_current_plan() is None

    def test_complete_task_marks_completed(self, isolated_task_manager):
        """complete_task 标记完成"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Do it"},
        ])
        result = isolated_task_manager.complete_task("1", "Done!")
        assert result is True
        plan = isolated_task_manager.get_current_plan()
        from core.prompt_manager.task_analyzer import TaskStatus
        assert plan.tasks["1"].status == TaskStatus.COMPLETED
        assert plan.tasks["1"].result_summary == "Done!"

    def test_complete_task_syncs_to_task_list(self, isolated_task_manager):
        """complete_task 同步到 _task_list"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Do it"},
        ])
        isolated_task_manager.complete_task("1", "All done")
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["is_completed"] is True
        assert task_list[0]["result_summary"] == "All done"

    def test_complete_task_nonexistent_returns_false(self, isolated_task_manager):
        """complete_task 不存在的任务返回 False"""
        assert isolated_task_manager.complete_task("nonexistent", "summary") is False

    def test_complete_task_no_plan_returns_false(self, isolated_task_manager):
        """无计划时 complete_task 返回 False"""
        assert isolated_task_manager.complete_task("1", "summary") is False

    def test_update_task_changes_description(self, isolated_task_manager):
        """update_task 修改描述"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Original"},
        ])
        result = isolated_task_manager.update_task("1", description="Updated")
        assert result is True
        plan = isolated_task_manager.get_current_plan()
        assert plan.tasks["1"].description == "Updated"

    def test_update_task_syncs_to_task_list(self, isolated_task_manager):
        """update_task 同步到 _task_list"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Original"},
        ])
        isolated_task_manager.update_task("1", description="Updated")
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["description"] == "Updated"

    def test_update_task_nonexistent_returns_false(self, isolated_task_manager):
        """update_task 不存在的任务返回 False"""
        assert isolated_task_manager.update_task("nonexistent", description="X") is False

    def test_update_task_no_plan_returns_false(self, isolated_task_manager):
        """无计划时 update_task 返回 False"""
        assert isolated_task_manager.update_task("1", description="X") is False

    def test_update_task_description_none_no_change(self, isolated_task_manager):
        """update_task 传 None 不修改描述"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Original"},
        ])
        isolated_task_manager.update_task("1", description=None)
        plan = isolated_task_manager.get_current_plan()
        assert plan.tasks["1"].description == "Original"

    def test_create_task_adds_single_task(self, isolated_task_manager):
        """create_task 添加单个任务"""
        tid = isolated_task_manager.create_task("New Task", "Do something new")
        assert tid == "1"
        plan = isolated_task_manager.get_current_plan()
        assert plan.tasks["1"].name == "New Task"

    def test_create_task_increments_counter(self, isolated_task_manager):
        """create_task 递增计数器"""
        tid1 = isolated_task_manager.create_task("First", "Desc")
        tid2 = isolated_task_manager.create_task("Second", "Desc")
        assert tid1 == "1"
        assert tid2 == "2"

    def test_create_task_initializes_plan_when_none(self, isolated_task_manager):
        """create_task 在无计划时自动创建 Plan"""
        tid = isolated_task_manager.create_task("Auto", "Auto desc")
        plan = isolated_task_manager.get_current_plan()
        assert plan is not None
        assert plan.tasks[tid].name == "Auto"

    def test_create_task_syncs_to_task_list(self, isolated_task_manager):
        """create_task 同步到 _task_list"""
        isolated_task_manager.create_task("Task", "Description")
        task_list = isolated_task_manager.task_list()
        assert len(task_list) == 1
        assert task_list[0]["description"] == "Description"

    def test_get_task_returns_plan_task(self, isolated_task_manager):
        """get_task 返回 PlanTask"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc"},
        ])
        pt = isolated_task_manager.get_task("1")
        assert pt is not None
        assert pt.name == "T1"

    def test_get_task_nonexistent_returns_none(self, isolated_task_manager):
        """get_task 不存在返回 None"""
        assert isolated_task_manager.get_task("999") is None

    def test_get_task_no_plan_returns_none(self, isolated_task_manager):
        """get_task 无计划返回 None"""
        assert isolated_task_manager.get_task("1") is None


# ============================================================================
# TaskManager 风格 API 测试
# ============================================================================

class TestTaskManagerAPI:
    """TaskManager 风格 API 测试"""

    def test_task_create_basic(self, isolated_task_manager):
        """task_create 基本使用"""
        result = isolated_task_manager.task_create([
            {"description": "Task A"},
            {"description": "Task B"},
        ], goal="Gen 1 goal")
        assert "2" in result
        assert isolated_task_manager._goal == "Gen 1 goal"

    def test_task_create_sets_plan(self, isolated_task_manager):
        """task_create 设置 Plan"""
        isolated_task_manager.task_create([
            {"description": "Only task"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert plan.goal == ""
        assert len(plan.tasks) == 1

    def test_task_create_with_goal(self, isolated_task_manager):
        """task_create 带目标"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ], goal="Learn the codebase")
        plan = isolated_task_manager.get_current_plan()
        assert plan.goal == "Learn the codebase"

    def test_task_update_mark_completed(self, isolated_task_manager):
        """task_update 标记完成"""
        isolated_task_manager.task_create([
            {"description": "Task to complete"},
        ])
        result = isolated_task_manager.task_update(1, is_completed=True)
        assert "完成" in result
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["is_completed"] is True

    def test_task_update_mark_incomplete(self, isolated_task_manager):
        """task_update 标记未完成"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        isolated_task_manager.task_update(1, is_completed=True)
        isolated_task_manager.task_update(1, is_completed=False)
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["is_completed"] is False

    def test_task_update_result_summary(self, isolated_task_manager):
        """task_update 更新结果摘要"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        isolated_task_manager.task_update(1, result_summary="Fixed the bug")
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["result_summary"] == "Fixed the bug"

    def test_task_update_description(self, isolated_task_manager):
        """task_update 更新描述"""
        isolated_task_manager.task_create([
            {"description": "Old desc"},
        ])
        isolated_task_manager.task_update(1, description="New desc")
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["description"] == "New desc"

    def test_task_update_nonexistent(self, isolated_task_manager):
        """task_update 不存在的任务"""
        result = isolated_task_manager.task_update(999, is_completed=True)
        assert "不存在" in result

    def test_task_update_syncs_to_plan(self, isolated_task_manager):
        """task_update 同步到 Plan"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        isolated_task_manager.task_update(1, is_completed=True, result_summary="Done")
        plan = isolated_task_manager.get_current_plan()
        from core.prompt_manager.task_analyzer import TaskStatus
        assert plan.tasks["1"].status == TaskStatus.COMPLETED
        assert plan.tasks["1"].result_summary == "Done"

    def test_task_list_returns_copy(self, isolated_task_manager):
        """task_list 返回列表"""
        isolated_task_manager.task_create([
            {"description": "T1"},
            {"description": "T2"},
        ])
        result = isolated_task_manager.task_list()
        assert len(result) == 2

    def test_task_list_empty_initially(self, isolated_task_manager):
        """初始空任务列表"""
        result = isolated_task_manager.task_list()
        assert result == []


# ============================================================================
# task_breakdown 测试
# ============================================================================

class TestTaskBreakdown:
    """task_breakdown 子步骤拆分测试"""

    def test_breakdown_analysis_keyword(self, isolated_task_manager):
        """分析类关键词生成分析步骤"""
        isolated_task_manager.task_create([
            {"description": "分析性能瓶颈"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert steps is not None
        assert len(steps) == 4
        assert any("通读" in s["description"] for s in steps)

    def test_breakdown_implement_keyword(self, isolated_task_manager):
        """实现类关键词生成实现步骤"""
        isolated_task_manager.task_create([
            {"description": "实现缓存层"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert steps is not None
        assert any("编写核心实现" in s["description"] for s in steps)

    def test_breakdown_fix_keyword(self, isolated_task_manager):
        """修复类关键词生成实现步骤"""
        isolated_task_manager.task_create([
            {"description": "修复登录超时 bug"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert steps is not None
        assert any("编写核心实现" in s["description"] for s in steps)

    def test_breakdown_add_keyword(self, isolated_task_manager):
        """添加类关键词"""
        isolated_task_manager.task_create([
            {"description": "添加单元测试"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert steps is not None
        assert any("编写核心实现" in s["description"] for s in steps)

    def test_breakdown_generic_keyword(self, isolated_task_manager):
        """通用关键词生成默认步骤"""
        isolated_task_manager.task_create([
            {"description": "随便做点什么"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert steps is not None
        assert len(steps) == 4
        assert any("分析需求" in s["description"] for s in steps)

    def test_breakdown_already_has_substeps(self, isolated_task_manager):
        """已有子步骤时直接返回不重新生成"""
        isolated_task_manager.task_create([
            {"description": "分析问题"},
        ])
        steps1 = isolated_task_manager.task_breakdown(1)
        # Modify a step to verify we get the cached version
        isolated_task_manager._task_list[0]["substeps"][0]["description"] = "CUSTOM"
        steps2 = isolated_task_manager.task_breakdown(1)
        assert steps2[0]["description"] == "CUSTOM"

    def test_breakdown_nonexistent_task(self, isolated_task_manager):
        """拆分不存在的任务返回 None"""
        assert isolated_task_manager.task_breakdown(999) is None


# ============================================================================
# task_prioritize 测试
# ============================================================================

class TestTaskPrioritize:
    """task_prioritize 优先级排序测试"""

    def test_prioritize_reorders_tasks(self, isolated_task_manager):
        """重新排序任务"""
        isolated_task_manager.task_create([
            {"description": "First"},
            {"description": "Second"},
            {"description": "Third"},
        ])
        result = isolated_task_manager.task_prioritize([3, 1, 2])
        assert result == [3, 1, 2]
        task_list = isolated_task_manager.task_list()
        assert task_list[0]["id"] == 3
        assert task_list[1]["id"] == 1
        assert task_list[2]["id"] == 2

    def test_prioritize_filters_nonexistent_ids(self, isolated_task_manager):
        """过滤不存在的 ID"""
        isolated_task_manager.task_create([
            {"description": "Only task"},
        ])
        result = isolated_task_manager.task_prioritize([999, 1, 888])
        assert result == [1]

    def test_prioritize_all_nonexistent_returns_none(self, isolated_task_manager):
        """全部 ID 不存在返回 None"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        result = isolated_task_manager.task_prioritize([999, 888])
        assert result is None

    def test_prioritize_empty_list_returns_none(self, isolated_task_manager):
        """空列表返回 None"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        result = isolated_task_manager.task_prioritize([])
        assert result is None


# ============================================================================
# 双向同步一致性测试 (最关键)
# ============================================================================

class TestBidirectionalSync:
    """双向同步一致性测试"""

    def test_create_plan_readable_via_task_list(self, isolated_task_manager):
        """create_plan 创建的任务可通过 task_list 读取"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc 1"},
            {"name": "T2", "description": "Desc 2"},
        ])
        tl = isolated_task_manager.task_list()
        assert len(tl) == 2
        assert tl[0]["description"] == "Desc 1"
        assert tl[1]["description"] == "Desc 2"

    def test_task_create_readable_via_get_current_plan(self, isolated_task_manager):
        """task_create 创建的任务可通过 get_current_plan 读取"""
        isolated_task_manager.task_create([
            {"description": "Desc A"},
            {"description": "Desc B"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert len(plan.tasks) == 2
        assert plan.tasks["1"].description == "Desc A"
        assert plan.tasks["2"].description == "Desc B"

    def test_complete_task_syncs_both_ways(self, isolated_task_manager):
        """complete_task 后两边状态一致"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc"},
        ])
        isolated_task_manager.complete_task("1", "Done")
        # Plan side
        from core.prompt_manager.task_analyzer import TaskStatus
        assert isolated_task_manager.get_current_plan().tasks["1"].status == TaskStatus.COMPLETED
        # Task list side
        assert isolated_task_manager.task_list()[0]["is_completed"] is True

    def test_task_update_syncs_to_plan_status(self, isolated_task_manager):
        """task_update(is_completed=True) 同步到 Plan 状态"""
        isolated_task_manager.task_create([
            {"description": "Task"},
        ])
        isolated_task_manager.task_update(1, is_completed=True)
        from core.prompt_manager.task_analyzer import TaskStatus
        plan = isolated_task_manager.get_current_plan()
        assert plan.tasks["1"].status == TaskStatus.COMPLETED

    def test_mixed_api_usage_consistent(self, isolated_task_manager):
        """混用两种 API 后状态一致"""
        # Start with TaskManager API
        isolated_task_manager.task_create([
            {"description": "Task A"},
        ])
        # Add via TaskPlanner API
        isolated_task_manager.create_task("Task B", "Added via Plan API")
        # Complete via TaskPlanner API
        isolated_task_manager.complete_task("1", "A done")
        # Update via TaskManager API
        isolated_task_manager.task_update(2, description="Updated B")

        plan = isolated_task_manager.get_current_plan()
        tl = isolated_task_manager.task_list()

        # 两边任务数量一致
        assert len(plan.tasks) == len(tl) == 2
        # 任务 1 完成状态一致
        assert plan.tasks["1"].result_summary == "A done"
        assert tl[0]["is_completed"] is True
        # 任务 2 描述一致
        assert plan.tasks["2"].description == "Updated B"
        assert tl[1]["description"] == "Updated B"

    def test_create_task_after_task_create_preserves_ids(self, isolated_task_manager):
        """task_create 后用 create_task 追加，ID 自增正确"""
        isolated_task_manager.task_create([
            {"description": "First batch"},
        ])
        tid = isolated_task_manager.create_task("Extra", "Added later")
        assert tid == "2"
        plan = isolated_task_manager.get_current_plan()
        assert "1" in plan.tasks
        assert "2" in plan.tasks


# ============================================================================
# JSON 持久化测试
# ============================================================================

class TestPersistence:
    """JSON 持久化往返测试"""

    def test_create_plan_persists_to_file(self, isolated_task_manager, tmp_path):
        """create_plan 写入文件"""
        isolated_task_manager.create_plan("Persist goal", [
            {"name": "P1", "description": "Persist desc"},
        ])
        tasks_file = tmp_path / "workspace" / "tasks.json"
        assert tasks_file.exists()
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
        assert data["goal"] == "Persist goal"
        assert len(data["tasks"]) == 1

    def test_load_restores_state(self, isolated_task_manager, tmp_path, monkeypatch):
        """加载恢复完整状态"""
        # 先创建并保存
        isolated_task_manager.create_plan("Restore test", [
            {"name": "R1", "description": "Restore me"},
        ])
        isolated_task_manager.complete_task("1", "Restored done")

        # 创建新实例加载同一文件
        from core.orchestration.task_planner import TaskManager
        old = TaskManager._instance
        TaskManager._instance = None
        tm2 = TaskManager()
        try:
            plan = tm2.get_current_plan()
            assert plan is not None
            assert plan.goal == "Restore test"
            assert len(plan.tasks) == 1
            from core.prompt_manager.task_analyzer import TaskStatus
            assert plan.tasks["1"].status == TaskStatus.COMPLETED
            assert plan.tasks["1"].result_summary == "Restored done"
        finally:
            TaskManager._instance = old

    def test_load_corrupted_json_handled(self, isolated_task_manager, tmp_path, monkeypatch):
        """损坏的 JSON 文件不崩溃"""
        tasks_file = tmp_path / "workspace" / "tasks.json"
        tasks_file.write_text("not valid json {{{", encoding="utf-8")

        from core.orchestration.task_planner import TaskManager
        old = TaskManager._instance
        TaskManager._instance = None
        tm = TaskManager()
        try:
            assert tm.get_current_plan() is None
            assert tm.task_list() == []
        finally:
            TaskManager._instance = old

    def test_load_missing_file_no_error(self, isolated_task_manager, tmp_path, monkeypatch):
        """文件不存在时不报错"""
        # isolated_task_manager 已经初始化且无文件（tmp_path 中没有 pre-created tasks.json）
        assert isolated_task_manager.get_current_plan() is None
        assert isolated_task_manager.task_list() == []

    def test_save_creates_directory(self, isolated_task_manager, tmp_path):
        """_save 自动创建目录"""
        tasks_dir = tmp_path / "workspace"
        # 删除目录
        import shutil
        shutil.rmtree(tasks_dir)
        # save 应该重新创建
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc"},
        ])
        assert (tasks_dir / "tasks.json").exists()

    def test_save_includes_saved_at(self, isolated_task_manager, tmp_path):
        """保存包含 saved_at 时间戳"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T1", "description": "Desc"},
        ])
        tasks_file = tmp_path / "workspace" / "tasks.json"
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
        assert "saved_at" in data

    def test_task_breakdown_persists_substeps(self, isolated_task_manager, tmp_path):
        """task_breakdown 的子步骤持久化到文件"""
        isolated_task_manager.task_create([
            {"description": "分析内存泄漏"},
        ])
        isolated_task_manager.task_breakdown(1)
        tasks_file = tmp_path / "workspace" / "tasks.json"
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
        assert len(data["tasks"][0]["substeps"]) == 4

    def test_task_prioritize_persists_order(self, isolated_task_manager, tmp_path):
        """task_prioritize 的顺序持久化到文件"""
        isolated_task_manager.task_create([
            {"description": "A"},
            {"description": "B"},
            {"description": "C"},
        ])
        isolated_task_manager.task_prioritize([3, 1, 2])
        tasks_file = tmp_path / "workspace" / "tasks.json"
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
        assert data["tasks"][0]["id"] == 3


# ============================================================================
# 边界与异常测试
# ============================================================================

class TestEdgeCases:
    """边界与异常测试"""

    def test_id_counter_starts_at_zero(self, isolated_task_manager):
        """初始 _id_counter 为 0"""
        assert isolated_task_manager._id_counter == 0

    def test_id_counter_increases_with_task_create(self, isolated_task_manager):
        """task_create 后计数器正确"""
        isolated_task_manager.task_create([
            {"description": "T1"},
            {"description": "T2"},
            {"description": "T3"},
        ])
        assert isolated_task_manager._id_counter == 3

    def test_task_update_none_values_no_change(self, isolated_task_manager):
        """task_update 传 None 不改变值"""
        isolated_task_manager.task_create([
            {"description": "Original"},
        ])
        isolated_task_manager.task_update(1, result_summary=None, description=None)
        tl = isolated_task_manager.task_list()
        assert tl[0]["result_summary"] == ""
        assert tl[0]["description"] == "Original"

    def test_task_breakdown_check_keyword(self, isolated_task_manager):
        """检查类关键词"""
        isolated_task_manager.task_create([
            {"description": "检查配置文件"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert any("通读" in s["description"] for s in steps)

    def test_task_breakdown_locate_keyword(self, isolated_task_manager):
        """定位类关键词"""
        isolated_task_manager.task_create([
            {"description": "定位内存泄漏点"},
        ])
        steps = isolated_task_manager.task_breakdown(1)
        assert any("通读" in s["description"] for s in steps)

    def test_plan_tasks_use_string_ids(self, isolated_task_manager):
        """Plan.tasks 的 key 是字符串"""
        isolated_task_manager.create_plan("Goal", [
            {"name": "T", "description": "D"},
        ])
        plan = isolated_task_manager.get_current_plan()
        assert isinstance(list(plan.tasks.keys())[0], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
