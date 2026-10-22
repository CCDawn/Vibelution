#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CODEBASE_MAP 启动预热回归：缓存命中/失效、字节等价、并发合并、线程守护与生命周期挂点。"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime as _real_datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from core.prompt_manager import codebase_file_index
from core.prompt_manager import codebase_map_builder as cmb
from core.web import lifecycle
from core.web.startup_jobs import StartupJobGroup


class _FrozenDatetime(_real_datetime):
    """冻结时间戳，使两次独立构建的地图逐字节可比。"""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 - 与 datetime.now 签名对齐
        return _real_datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def map_project(tmp_path, monkeypatch):
    """隔离 project root / workspace home / 会话与 git 依赖，并冻结时间戳。"""

    project = tmp_path / "proj"
    (project / "core").mkdir(parents=True)
    (project / "agent.py").write_text('"""agent root"""\n', encoding="utf-8")
    (project / "core" / "alpha.py").write_text(
        '"""alpha module"""\nimport core.beta\n', encoding="utf-8"
    )
    (project / "core" / "beta.py").write_text('"""beta module"""\n', encoding="utf-8")

    prompts_dir = tmp_path / "home" / "workspace" / "prompts"
    prompts_dir.mkdir(parents=True)
    map_path = prompts_dir / "CODEBASE_MAP.md"

    monkeypatch.setattr(cmb, "_resolve_project_root", lambda: project)
    monkeypatch.setattr(cmb, "_get_codebase_map_path", lambda: map_path)
    monkeypatch.setattr(
        "core.infrastructure.agent_session.get_session_state",
        lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
    )
    monkeypatch.setattr(
        "core.infrastructure.git_memory.get_git_memory_service",
        lambda: SimpleNamespace(get_recent_project_changes=lambda **_: []),
    )
    monkeypatch.setattr(cmb, "datetime", _FrozenDatetime)
    monkeypatch.setattr(cmb, "_task_focused_view_cache", OrderedDict())
    cmb.reset_warmup_state_for_tests()
    yield project, map_path
    cmb.reset_warmup_state_for_tests()


def _reset_derived_caches() -> None:
    """清空进程内 AST 缓存与任务视图缓存，回到冷态。"""

    codebase_file_index._cache.clear()
    cmb._task_focused_view_cache.clear()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def test_warm_hits_same_content_as_immediate_compute(map_project):
    _project, map_path = map_project
    summary = cmb.warm_codebase_map_cache()
    assert summary["warmed"] is True
    assert summary["contentChars"] > 0
    assert map_path.exists()

    direct = cmb.get_codebase_map(current_goal="", state_memory="")
    assert _sha1(direct) == summary["contentSha1"]


def test_warm_disk_map_byte_identical_to_direct_full_build(map_project):
    project, map_path = map_project

    # 直接全量构建（无预热参与）产出基准
    direct_content = cmb.scan_and_build_codebase_map(project, force=True)
    on_disk_baseline = map_path.read_text(encoding="utf-8")
    assert on_disk_baseline == direct_content

    # 回到冷态：删盘上产物、清进程内缓存与预热标记，重走预热路径
    map_path.unlink()
    map_path.with_suffix(".meta").unlink(missing_ok=True)
    _reset_derived_caches()
    cmb.reset_warmup_state_for_tests()

    summary = cmb.warm_codebase_map_cache()
    assert summary["warmed"] is True
    assert map_path.read_text(encoding="utf-8") == on_disk_baseline  # 同样输入产出同样地图


def test_warm_is_idempotent_per_process(map_project, monkeypatch):
    calls = {"count": 0}
    real_get = cmb.get_codebase_map

    def counting_get(*args, **kwargs):
        calls["count"] += 1
        return real_get(*args, **kwargs)

    monkeypatch.setattr(cmb, "get_codebase_map", counting_get)
    first = cmb.warm_codebase_map_cache()
    second = cmb.warm_codebase_map_cache()
    assert first["warmed"] is True
    assert second == {"warmed": False, "skipped": "already_warmed"}
    assert calls["count"] == 1


def test_warm_swallows_errors_and_compute_still_works(map_project, monkeypatch):
    real_get = cmb.get_codebase_map
    flaky = {"raise": True}

    def flaky_get(*args, **kwargs):
        if flaky["raise"]:
            raise RuntimeError("warm exploded")
        return real_get(*args, **kwargs)

    monkeypatch.setattr(cmb, "get_codebase_map", flaky_get)
    summary = cmb.warm_codebase_map_cache()
    assert summary["warmed"] is False
    assert summary["skipped"] == "error"
    assert summary["errorType"] == "RuntimeError"

    flaky["raise"] = False
    content = cmb.get_codebase_map(current_goal="", state_memory="")
    assert content  # 预热失败不影响正式构建照常冷跑


def test_warm_and_concurrent_compute_coalesce_to_same_content(map_project):
    started = threading.Event()
    release = threading.Event()
    results: dict[str, str] = {}
    errors: list[BaseException] = []

    def warm_worker():
        started.set()
        assert release.wait(5)
        try:
            summary = cmb.warm_codebase_map_cache()
            results["warm"] = str(summary.get("contentSha1", ""))
        except BaseException as exc:  # noqa: BLE001 - 测试收集断言
            errors.append(exc)

    def direct_worker():
        try:
            content = cmb.get_codebase_map(current_goal="", state_memory="")
            results["direct"] = _sha1(content)
        except BaseException as exc:  # noqa: BLE001 - 测试收集断言
            errors.append(exc)

    warm_thread = threading.Thread(target=warm_worker, daemon=True)
    warm_thread.start()
    assert started.wait(5)
    direct_thread = threading.Thread(target=direct_worker, daemon=True)
    direct_thread.start()
    release.set()
    warm_thread.join(10)
    direct_thread.join(10)

    assert errors == []
    assert results["warm"]
    assert results["warm"] == results["direct"]


def test_lifecycle_warmup_waits_for_routes_ready_and_runs_on_daemon_worker(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.setattr(
        "core.web.services.session.directory_runtime.should_skip_directory_runtime_for_pytest",
        lambda: False,
    )
    calls: list[tuple[int, bool, dict]] = []

    def fake_worker(gate_timings=None):
        calls.append(
            (threading.get_ident(), threading.current_thread().daemon, dict(gate_timings or {}))
        )
        return {"warmed": True}

    monkeypatch.setattr(lifecycle, "_codebase_map_warmup_worker", fake_worker)
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        jobs = StartupJobGroup()
        worker = jobs.start_async(
            "codebase-map-warmup-test",
            lifecycle._run_codebase_map_warmup_after_routes_ready(app, startup_jobs=jobs),
        )
        await asyncio.sleep(0.02)
        assert calls == []  # routes 未就绪时预热被门挡住
        app.state.web_routes_ready_event.set()
        await asyncio.wait_for(worker, timeout=5)

    loop_thread = threading.get_ident()
    asyncio.run(exercise())
    assert len(calls) == 1
    worker_thread_id, worker_is_daemon, gate = calls[0]
    assert worker_thread_id != loop_thread  # 预热不在事件循环/提交链路上执行
    assert worker_is_daemon is True  # 预热线程必须守护，不阻塞进程退出
    assert gate["staggerMs"] == 0


def test_lifecycle_warmup_never_runs_under_pytest(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        lifecycle, "_codebase_map_warmup_worker", lambda *_a, **_k: calls.append("ran")
    )

    async def exercise():
        return await lifecycle._run_codebase_map_warmup_after_routes_ready(None)

    assert asyncio.run(exercise()) == {"skipped": "pytest"}
    assert calls == []
