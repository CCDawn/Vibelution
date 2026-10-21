#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from types import SimpleNamespace
from pathlib import Path
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import ast
import os

import pytest

from core.prompt_manager import codebase_map_builder as cmb


@pytest.fixture
def parse_counts(monkeypatch):
    counts = {}
    lock = Lock()
    real_parse = ast.parse

    def parse(source, filename="<unknown>", *args, **kwargs):
        with lock:
            counts[str(filename)] = counts.get(str(filename), 0) + 1
        return real_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", parse)
    return counts


def test_unchanged_source_is_parsed_once(tmp_path, parse_counts):
    path = tmp_path / "sample.py"
    path.write_text('"""sample"""\nimport core.chat\n', encoding="utf-8")
    first = cmb._scan_file(path)
    second = cmb._scan_file(path)
    assert first == second
    assert parse_counts[str(path)] == 1
    first["imports"].append("corruption")
    assert "corruption" not in cmb._scan_file(path)["imports"]


def test_source_cache_tracks_edits_replacement_deletion_and_parse_repair(tmp_path, parse_counts):
    path = tmp_path / "sample.py"
    path.write_text('"""before"""\n', encoding="utf-8")
    assert cmb._scan_file(path)["docstring"] == "before"
    path.write_text('"""edited source"""\n', encoding="utf-8")
    assert cmb._scan_file(path)["docstring"] == "edited source"
    before = path.stat()
    replacement = tmp_path / "replacement.py"
    replacement.write_text('"""new___ source"""\n', encoding="utf-8")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    assert cmb._scan_file(path)["docstring"] == "new___ source"
    path.unlink()
    assert cmb._scan_file(path) is None
    path.write_text("def broken(\n", encoding="utf-8")
    assert cmb._scan_file(path) is None
    before_repeated_invalid = parse_counts[str(path)]
    assert cmb._scan_file(path) is None
    assert parse_counts[str(path)] == before_repeated_invalid
    path.write_text('"""repaired"""\n', encoding="utf-8")
    assert cmb._scan_file(path)["docstring"] == "repaired"


def test_concurrent_source_reads_share_one_parse(tmp_path, monkeypatch, parse_counts):
    path = tmp_path / "sample.py"
    path.write_text('"""concurrent"""\n', encoding="utf-8")
    real_parse = ast.parse
    entered, release = Event(), Event()
    gate = Barrier(4)

    def parse(source, filename="<unknown>", *args, **kwargs):
        if str(filename) == str(path):
            entered.set()
            assert release.wait(5)
        return real_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", parse)
    def read(_):
        gate.wait(5)
        return cmb._scan_file(path)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read, i) for i in range(4)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        assert all(f.result()["docstring"] == "concurrent" for f in futures)
    assert parse_counts[str(path)] == 1


def test_source_changed_during_parse_is_not_cached(tmp_path, monkeypatch):
    path = tmp_path / "sample.py"
    path.write_text('"""before"""\n', encoding="utf-8")
    real_parse = ast.parse
    def change_during_parse(source, filename="<unknown>", *args, **kwargs):
        tree = real_parse(source, filename, *args, **kwargs)
        path.write_text('"""updated during read"""\n', encoding="utf-8")
        return tree
    with monkeypatch.context() as parsing:
        parsing.setattr(ast, "parse", change_during_parse)
        assert cmb._scan_file(path) is None
    assert cmb._scan_file(path)["docstring"] == "updated during read"


@pytest.fixture
def task_map_env(tmp_path, monkeypatch):
    path = tmp_path / "core" / "feature.py"
    path.parent.mkdir()
    path.write_text('"""first version"""\n', encoding="utf-8")
    monkeypatch.setattr(cmb, "_task_focused_view_cache", OrderedDict())
    monkeypatch.setattr(cmb, "_collect_python_files", lambda _root: [path])
    monkeypatch.setattr("core.infrastructure.agent_session.get_session_state",
                        lambda: SimpleNamespace(get_attention_snapshot=lambda: {}))
    monkeypatch.setattr("core.infrastructure.git_memory.get_git_memory_service",
                        lambda: SimpleNamespace(get_recent_project_changes=lambda **_: []))
    return tmp_path, path


def test_alternating_tasks_keep_their_own_map(task_map_env, monkeypatch):
    root, _ = task_map_env
    real_impact = cmb._build_impact_chain_view
    builds = []
    def impact(*args):
        builds.append(1)
        return real_impact(*args)
    monkeypatch.setattr(cmb, "_build_impact_chain_view", impact)
    first = cmb._build_task_focused_view(root, "", current_goal="feature alpha", state_memory="a")
    other = cmb._build_task_focused_view(root, "", current_goal="feature beta", state_memory="b")
    repeated = cmb._build_task_focused_view(root, "", current_goal="feature alpha", state_memory="a")
    assert first == repeated and first != other
    assert len(builds) == 2


def test_concurrent_task_views_share_one_build(task_map_env, monkeypatch):
    root, _ = task_map_env
    real_impact = cmb._build_impact_chain_view
    builds = []
    entered, release = Event(), Event()
    gate = Barrier(4)
    def impact(*args):
        builds.append(1)
        entered.set()
        assert release.wait(5)
        return real_impact(*args)
    monkeypatch.setattr(cmb, "_build_impact_chain_view", impact)
    def read(_):
        gate.wait(5)
        return cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read, i) for i in range(4)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        values = [future.result() for future in futures]
    assert all(value == values[0] for value in values)
    assert len(builds) == 1


def test_task_map_not_stale_when_source_changes(task_map_env):
    root, path = task_map_env
    assert "first version" in cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")
    path.write_text('"""second version"""\n', encoding="utf-8")
    assert "second version" in cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")


def test_source_metadata_cache_is_bounded(tmp_path, monkeypatch, parse_counts):
    from core.prompt_manager import codebase_file_index as index
    monkeypatch.setattr(index, "_cache", OrderedDict())
    monkeypatch.setattr(index, "_MAX_ENTRIES", 2)
    paths = [tmp_path / f"file_{i}.py" for i in range(3)]
    for path in paths:
        path.write_text('"""entry"""\n', encoding="utf-8")
        assert cmb._scan_file(path)["docstring"] == "entry"
    assert len(index._cache) == 2
    cmb._scan_file(paths[0])
    assert parse_counts[str(paths[0])] == 2


def test_task_map_cache_is_bounded(task_map_env, monkeypatch):
    root, _ = task_map_env
    monkeypatch.setattr(cmb, "_TASK_VIEW_CACHE_LIMIT", 2)
    for goal in ("one feature", "two feature", "three feature"):
        cmb._build_task_focused_view(root, "", current_goal=goal, state_memory="")
    assert len(cmb._task_focused_view_cache) == 2


def test_task_map_tracks_file_addition_and_deletion(task_map_env, monkeypatch):
    root, path = task_map_env
    monkeypatch.setattr(cmb, "_collect_python_files", lambda _root: sorted(root.rglob("*.py")))
    cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")
    added = path.with_name("second.py")
    added.write_text('"""added feature"""\n', encoding="utf-8")
    assert "added feature" in cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")
    path.unlink()
    assert "first version" not in cmb._build_task_focused_view(root, "", current_goal="feature", state_memory="")


def test_concurrent_cold_map_requests_build_once(tmp_path, monkeypatch):
    map_path = tmp_path / "map.md"
    entered, release = Event(), Event()
    gate = Barrier(4)
    builds = []
    monkeypatch.setattr(cmb, "_get_codebase_map_path", lambda: map_path)
    monkeypatch.setattr(cmb, "_resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr(cmb, "should_rescan", lambda: not map_path.exists())
    monkeypatch.setattr(cmb, "_build_task_focused_view", lambda *a, **kw: "")
    def build():
        builds.append(1)
        entered.set()
        assert release.wait(5)
        map_path.write_text("map", encoding="utf-8")
        return "map"
    monkeypatch.setattr(cmb, "scan_and_build_codebase_map", build)
    def read(_):
        gate.wait(5)
        return cmb.get_codebase_map(current_goal="feature", state_memory="")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read, i) for i in range(4)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        assert [f.result() for f in futures] == ["map"] * 4
    assert len(builds) == 1


def test_extract_markdown_section():
    content = "## A\n1\n\n## B\n2\n3\n\n## C\n4"
    assert cmb._extract_markdown_section(content, "B") == "## B\n2\n3"


def test_build_task_focused_view_prefers_goal_and_hot_paths(monkeypatch, tmp_path):
    (tmp_path / "core" / "prompt_manager").mkdir(parents=True)
    (tmp_path / "core" / "infrastructure").mkdir(parents=True)
    (tmp_path / "agent.py").write_text('"""entry"""\n', encoding="utf-8")
    pm_file = tmp_path / "core" / "prompt_manager" / "prompt_manager.py"
    pm_file.write_text('"""prompt orchestration"""\n', encoding="utf-8")
    infra_file = tmp_path / "core" / "infrastructure" / "tool_executor.py"
    infra_file.write_text('"""tool runtime"""\n', encoding="utf-8")

    monkeypatch.setattr(cmb, "_collect_python_files", lambda _root: [pm_file, infra_file, tmp_path / "agent.py"])
    monkeypatch.setattr(
        cmb,
        "_scan_file",
        lambda path: {
            "docstring": "prompt orchestration" if "prompt_manager.py" in str(path) else "tool runtime",
            "imports": ["core.prompt_manager"] if "prompt_manager.py" in str(path) else ["core.infrastructure"],
        },
    )
    monkeypatch.setattr(
        cmb,
        "_get_prompt_runtime_context",
        lambda: ("优化 prompt manager 的 section 选择", "## 延续约束\n- 先检查 tool executor"),
    )
    monkeypatch.setattr(
        "core.infrastructure.agent_session.get_session_state",
        lambda: SimpleNamespace(get_attention_snapshot=lambda: {
            "modified_paths": ["core/prompt_manager/prompt_manager.py"],
            "modified_entities": ["PromptManager._select_sections"],
            "last_validation_summary": "tests passed",
        }),
    )

    class DummyGitMemory:
        def get_recent_project_changes(self, limit=4):
            return [SimpleNamespace(path="core/prompt_manager/prompt_manager.py", change_type="modified", subject="prompt work")]

    monkeypatch.setattr("core.infrastructure.git_memory.get_git_memory_service", lambda: DummyGitMemory())

    full_content = (
        "## 子系统概览\n| 子系统 | 路径 | 文件 | 风险 |\n"
        "|--------|------|------|------|\n| 提示词引擎 | `core/prompt_manager/` | 5 | `core` |\n\n"
        "## 核心依赖 (被依赖最多的模块 Top-10)\n- `core/prompt_manager/prompt_manager.py` ← 3 文件\n"
        "- `core/infrastructure/tool_executor.py` ← 2 文件\n\n"
        "## 测试覆盖\n覆盖率: 80% (8/10) | 未覆盖: 2 个模块\n"
    )

    rendered = cmb._build_task_focused_view(tmp_path, full_content)

    assert "## 当前任务局部地图" in rendered
    assert "## 影响链路" in rendered
    assert "当前目标: 优化 prompt manager 的 section 选择" in rendered
    assert "`core/prompt_manager/prompt_manager.py`" in rendered
    assert "## 全局骨架摘要" in rendered
    assert "## 子系统概览" in rendered


def test_build_task_focused_view_prefers_explicit_agent_context(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cmb,
        "_get_prompt_runtime_context",
        lambda: ("你是监督进化 Judge Agent。当前只生成 rubric。", "judge state"),
    )
    monkeypatch.setattr(cmb, "_collect_python_files", lambda _root: [])
    monkeypatch.setattr(
        "core.infrastructure.agent_session.get_session_state",
        lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
    )
    monkeypatch.setattr(
        "core.infrastructure.git_memory.get_git_memory_service",
        lambda: SimpleNamespace(get_recent_project_changes=lambda limit=4: []),
    )

    rendered = cmb._build_task_focused_view(
        tmp_path,
        "## 子系统概览\n- prompt manager",
        current_goal="基线 Agent 在候选工作树中实施改进",
        state_memory="baseline self-edit",
    )

    assert "当前目标: 基线 Agent 在候选工作树中实施改进" in rendered
    assert "监督进化 Judge Agent" not in rendered


def test_build_impact_chain_view_shows_dependents_and_tests(monkeypatch, tmp_path):
    (tmp_path / "core" / "prompt_manager").mkdir(parents=True)
    (tmp_path / "core" / "infrastructure").mkdir(parents=True)
    target = tmp_path / "core" / "prompt_manager" / "prompt_manager.py"
    caller = tmp_path / "core" / "infrastructure" / "tool_executor.py"
    target.write_text('"""prompt orchestration"""\n', encoding="utf-8")
    caller.write_text('"""tool runtime"""\n', encoding="utf-8")

    monkeypatch.setattr(
        cmb,
        "_scan_file",
        lambda path: {
            "docstring": "prompt orchestration" if path == target else "tool runtime",
            "imports": [] if path == target else ["core.prompt_manager.prompt_manager"],
        },
    )

    rendered = cmb._build_impact_chain_view([target], [target, caller], tmp_path)

    assert "## 影响链路" in rendered
    assert "`core/prompt_manager/prompt_manager.py`" in rendered
    assert "`core/infrastructure/tool_executor.py`" in rendered
    assert "`tests/test_prompt_manager.py`" in rendered
