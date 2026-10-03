"""Cold-start prewarm workers: config workspace cache and freshness cache.

Pins the cold-start prewarm wirings added to the web lifespan:

- ``_run_config_workspace_prewarm_after_routes_ready``: gates the heavy alias
  scan behind web route readiness plus a settle window (the scan's pure-Python
  rglob pass used to hold the GIL against the route mount and the frontend's
  first request volley), then waits for the session directory startup, builds
  the config workspace payload once (single-flight shared with early
  requests), records a lifecycle runtime-scene event, and skips under pytest
  like the directory runtime itself.
- ``_prewarm_git_memory_on_startup``: fills the code-freshness verdict cache
  (45s fast-path TTL) BEFORE the long git memory refresh so the frontend's
  first delayed poll is a cache hit and the verdict is not computed twice; a
  freshness failure is best effort and never fails the git prewarm result.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import FastAPI

from core.web import lifecycle
from core.web.services import code_freshness
from core.web.services import config_service
from core.web.services.session import directory_runtime

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def _reset_freshness_caches():
    code_freshness.reset_freshness_caches_for_tests()
    yield
    code_freshness.reset_freshness_caches_for_tests()


def test_prewarm_config_workspace_waits_builds_and_records(monkeypatch):
    sequence: list[str] = []
    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: False,
    )

    def fake_wait(*, timeout=None):
        sequence.append("wait")
        return "idle"

    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", fake_wait)
    monkeypatch.setattr(
        config_service,
        "prewarm_config_workspace",
        lambda: sequence.append("build"),
    )
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = lifecycle._prewarm_config_workspace_on_startup()

    # 目录启动等待必须先于构建（serving root 对齐后才扫别名引用）。
    assert sequence == ["wait", "build"]
    assert result["totalMs"] >= 0
    assert len(events) == 1
    args, kwargs = events[0]
    assert args[:3] == ("config", "startup_prewarm", "config.workspace_prewarmed")
    assert kwargs["outcome"] == "completed"
    assert kwargs["fields"] == {"totalMs": result["totalMs"]}
    assert kwargs["lifecycle"] is True


def test_prewarm_config_workspace_skips_under_pytest(monkeypatch):
    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: True,
    )
    touched: list[str] = []
    monkeypatch.setattr(
        directory_runtime,
        "wait_for_directory_startup",
        lambda *a, **kw: touched.append("wait"),
    )
    monkeypatch.setattr(
        config_service,
        "prewarm_config_workspace",
        lambda: touched.append("build"),
    )

    result = lifecycle._prewarm_config_workspace_on_startup()

    assert result == {"skipped": "pytest"}
    assert touched == []


def test_gated_config_workspace_prewarm_waits_for_routes_ready_then_builds(monkeypatch):
    """未 set 路由 ready 事件前不构建；set + settle 后按序构建并照常发事件。"""

    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: False,
    )
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0.01")
    sequence: list[str] = []
    monkeypatch.setattr(
        directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout=None: sequence.append("dir_wait"),
    )
    monkeypatch.setattr(
        config_service,
        "prewarm_config_workspace",
        lambda: sequence.append("build"),
    )
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    app = FastAPI()
    app.state.web_routes_ready_event = asyncio.Event()

    async def exercise():
        worker = asyncio.create_task(
            lifecycle._run_config_workspace_prewarm_after_routes_ready(app)
        )
        await asyncio.sleep(0.05)
        assert sequence == [], "routes-ready 事件 set 前不得启动目录等待或构建"
        app.state.web_routes_ready_event.set()
        await asyncio.wait_for(worker, timeout=5)

    asyncio.run(exercise())

    # 顺序固定：routes ready → settle → 目录等待 → 扫描。
    assert sequence == ["dir_wait", "build"]
    assert len(events) == 1
    args, kwargs = events[0]
    assert args[:3] == ("config", "startup_prewarm", "config.workspace_prewarmed")
    assert kwargs["outcome"] == "completed"
    assert kwargs["fields"]["totalMs"] >= 0
    assert kwargs["fields"]["staggerMs"] == 10
    assert kwargs["fields"]["waitedForRoutesMs"] >= 0
    assert kwargs["lifecycle"] is True


def test_gated_config_workspace_prewarm_with_zero_stagger_only_waits_ready(monkeypatch):
    """stagger=0：只等 ready（无事件则零等待），不额外 sleep。"""

    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: False,
    )
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.setattr(
        directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout=None: "idle",
    )
    monkeypatch.setattr(config_service, "prewarm_config_workspace", lambda: None)
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = asyncio.run(lifecycle._run_config_workspace_prewarm_after_routes_ready(None))

    # app=None（无 ready 事件）时等待耗时为 0，且没有 settle 额外等待。
    assert result["totalMs"] >= 0
    assert result["waitedForRoutesMs"] == 0
    assert result["staggerMs"] == 0
    assert events[0][1]["fields"]["waitedForRoutesMs"] == 0
    assert events[0][1]["fields"]["staggerMs"] == 0


def test_gated_config_workspace_prewarm_skips_under_pytest_before_waiting(monkeypatch):
    """pytest 跳过必须在 ready 等待之前：事件永不 set 也必须立即返回。"""

    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: True,
    )

    def fail_build(*args, **kwargs):
        raise AssertionError("pytest skip must not build the workspace cache")

    monkeypatch.setattr(
        directory_runtime,
        "wait_for_directory_startup",
        fail_build,
    )
    monkeypatch.setattr(config_service, "prewarm_config_workspace", fail_build)

    app = FastAPI()
    app.state.web_routes_ready_event = asyncio.Event()  # 永不 set

    async def exercise():
        return await asyncio.wait_for(
            lifecycle._run_config_workspace_prewarm_after_routes_ready(app),
            timeout=2,
        )

    assert asyncio.run(exercise()) == {"skipped": "pytest"}


def test_startup_prewarm_gate_and_stagger_env_parsing(monkeypatch):
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    monkeypatch.delenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", raising=False)

    # 默认开启门控。
    assert lifecycle._startup_cache_prewarm_gate_enabled() is True
    for off_value in ("0", "false", "no", "off"):
        monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", off_value)
        assert lifecycle._startup_cache_prewarm_gate_enabled() is False
    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", "1")
    assert lifecycle._startup_cache_prewarm_gate_enabled() is True

    assert lifecycle._startup_prewarm_stagger_seconds() == 12.0
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    assert lifecycle._startup_prewarm_stagger_seconds() == 0.0
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "3.5")
    assert lifecycle._startup_prewarm_stagger_seconds() == 3.5
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "-5")
    assert lifecycle._startup_prewarm_stagger_seconds() == 0.0
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "bogus")
    assert lifecycle._startup_prewarm_stagger_seconds() == 12.0


def test_git_memory_prewarm_fills_freshness_cache(monkeypatch, tmp_path):
    # Minimal fake repo so the zero-process HEAD observation is non-empty:
    # the verdict cache only stores when the file-read HEAD agrees with the
    # resolved disk HEAD (the module's trust rule for the fast path).
    head_sha = "abc123def456abc123def456abc123def456abcd"
    refs_dir = tmp_path / ".git" / "refs" / "heads"
    refs_dir.mkdir(parents=True)
    (refs_dir / "main").write_text(head_sha + "\n", encoding="utf-8")
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    monkeypatch.setattr(
        "core.infrastructure.git_memory.refresh_git_memory",
        lambda force=False, **kwargs: {"ok": True},
    )
    # The worker resolves PROJECT_ROOT from the runtime routes module at call
    # time; rebind it to the tmp root so the real (patched-collaborator)
    # freshness resolution runs hermetically.
    monkeypatch.setattr("core.web.routes.runtime.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        code_freshness,
        "_throttled_dirty_summary",
        lambda project_root, *, head_text, fingerprint_stamp: {"available": False},
    )
    backend_calls: list[int] = []

    def fake_backend(*, project_root, fallback_snapshot=None, dirty_summary=None):
        backend_calls.append(1)
        return {"available": True, "behind": False, "disk": {"head": head_sha}}

    monkeypatch.setattr(code_freshness, "resolve_backend_freshness", fake_backend)
    monkeypatch.setattr(
        code_freshness,
        "resolve_frontend_freshness",
        lambda *, project_root: {"available": False, "stale": False},
    )

    state, duration_ms = lifecycle._prewarm_git_memory_on_startup()

    assert state == {"ok": True}
    assert duration_ms >= 0
    # Prewarm paid the full git-backed resolution exactly once and the verdict
    # landed in the fast-path cache.
    assert backend_calls == [1]
    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "unknown"
    # Same root, unchanged HEAD/fingerprint observation, TTL not elapsed: the
    # user's first poll replays the cached verdict without resolving again.
    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert backend_calls == [1]
    assert second == first


def test_git_memory_prewarm_survives_freshness_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "core.infrastructure.git_memory.refresh_git_memory",
        lambda force=False, **kwargs: {"ok": True},
    )
    monkeypatch.setattr("core.web.routes.runtime.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        code_freshness,
        "resolve_code_freshness",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    state, duration_ms = lifecycle._prewarm_git_memory_on_startup()

    # Freshness 预热是 best effort：失败不影响 git 预热结果与返回签名。
    assert state == {"ok": True}
    assert duration_ms >= 0


def test_git_memory_prewarm_resolves_freshness_before_git_refresh(monkeypatch, tmp_path):
    """freshness 预热必须先于 git memory refresh：前端 ~20s 就来首次轮询，
    而 refresh 子进程链要跑几十秒；顺序颠倒会让首次请求全价扫描 + 预热重复扫描。"""

    order: list[str] = []
    real_resolve = code_freshness.resolve_code_freshness

    def tracking_resolve(**kwargs):
        order.append("freshness")
        return real_resolve(**kwargs)

    def fake_refresh(force=False, **kwargs):
        order.append("git_refresh")
        return {"ok": True}

    monkeypatch.setattr("core.infrastructure.git_memory.refresh_git_memory", fake_refresh)
    monkeypatch.setattr(code_freshness, "resolve_code_freshness", tracking_resolve)
    monkeypatch.setattr("core.web.routes.runtime.PROJECT_ROOT", tmp_path)
    # 隔离真实 git 调用：只需要验证调用顺序，不需要真实 verdict。
    monkeypatch.setattr(
        code_freshness,
        "_throttled_dirty_summary",
        lambda project_root, *, head_text, fingerprint_stamp: {"dirty": False, "dirtyTreeDigest": "0" * 64},
    )
    monkeypatch.setattr(
        code_freshness,
        "resolve_backend_freshness",
        lambda *, project_root, fallback_snapshot=None, dirty_summary=None: {
            "available": False,
            "behind": False,
            "reason": "no_running_fingerprint",
            "disk": {"head": "", "branch": ""},
        },
    )
    monkeypatch.setattr(
        code_freshness,
        "resolve_frontend_freshness",
        lambda *, project_root: {"available": False, "stale": False},
    )

    state, duration_ms = lifecycle._prewarm_git_memory_on_startup()

    assert order == ["freshness", "git_refresh"]
    assert state == {"ok": True}
    # durationMs 口径保持「git memory refresh 自身」。
    assert duration_ms >= 0


def test_lifespan_prewarm_gate_disabled_starts_prewarm_immediately(monkeypatch):
    """VIBELUTION_DEFER_STARTUP_CACHE_PREWARM 关闭时恢复立即跑（不经 ready 包装器）。"""

    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", "0")
    entered = threading.Event()
    config_built = threading.Event()
    observed: dict = {}

    def record_ready_event(**fields) -> None:
        observed.update(fields)

    async def fail_wrapper(app):
        raise AssertionError("gate disabled must not route through the routes-ready wrapper")

    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", record_ready_event)
    monkeypatch.setattr(lifecycle, "_run_config_workspace_prewarm_after_routes_ready", fail_wrapper)
    monkeypatch.setattr(lifecycle, "_run_agent_registry_prewarm_after_routes_ready", fail_wrapper)
    monkeypatch.setattr(
        lifecycle,
        "_prewarm_config_workspace_on_startup",
        lambda *args, **kwargs: config_built.set() or {},
    )
    monkeypatch.setattr(lifecycle, "_prewarm_agent_registry_on_startup", lambda *a, **kw: {})
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    from core.web.services import cli_agent_terminal_service, session_service

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: None)
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        dict,
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            entered.set()
            assert await asyncio.to_thread(config_built.wait, 1)

    asyncio.run(exercise())

    assert entered.is_set()
    assert "config_workspace_prewarm" in observed["background_tasks"]
