"""Optional startup caches yield priority to functional route readiness."""

from __future__ import annotations

import asyncio
import builtins
import threading
from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from core.web import lifecycle
from core.web.startup_jobs import StartupJobGroup


def _stub_prewarm(monkeypatch):
    calls: list[tuple[str, int]] = []
    events: list[dict] = []

    def touch(name):
        calls.append((name, threading.get_ident()))

    monkeypatch.setattr(lifecycle, "_prewarm_key_tool_definitions", lambda: touch("tools"))
    monkeypatch.setattr(lifecycle, "_prewarm_web_search_availability", lambda: touch("search"))

    def git():
        touch("git")
        return SimpleNamespace(available=True, dirty=False, head_rev="head", indexed_head_rev="head"), 0

    monkeypatch.setattr(lifecycle, "_prewarm_git_memory_on_startup", git)
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: events.append(kwargs),
    )
    return calls, events


def test_optional_caches_wait_for_routes_and_run_outside_event_loop(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    calls, events = _stub_prewarm(monkeypatch)
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        jobs = StartupJobGroup()
        worker = jobs.start_async("optional-cache-test", lifecycle.prewarm_ui_caches_on_startup(app=app, startup_jobs=jobs))
        await asyncio.sleep(0.02)
        assert calls == []
        app.state.web_routes_ready_event.set()
        await asyncio.wait_for(worker, timeout=5)

    loop_thread = threading.get_ident()
    asyncio.run(exercise())
    assert sorted(name for name, _ in calls) == ["git", "search", "tools"]
    assert all(thread_id != loop_thread for _, thread_id in calls)
    assert events[0]["fields"]["waitedForRoutesMs"] >= 0
    assert events[0]["fields"]["staggerMs"] == 0


def test_cancelled_route_wait_never_starts_optional_workers(monkeypatch):
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    calls, events = _stub_prewarm(monkeypatch)
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        worker = asyncio.create_task(lifecycle.prewarm_ui_caches_on_startup(app=app))
        await asyncio.sleep(0)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(exercise())
    assert calls == []
    assert events == []


def test_operator_can_disable_optional_cache_gate(monkeypatch):
    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", "0")
    calls, _events = _stub_prewarm(monkeypatch)
    app = FastAPI()

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        await asyncio.wait_for(lifecycle.prewarm_ui_caches_on_startup(app=app), timeout=5)
        assert not app.state.web_routes_ready_event.is_set()

    asyncio.run(exercise())
    assert len(calls) == 3


@pytest.mark.parametrize("worker", ["_prewarm_key_tool_definitions", "_prewarm_web_search_availability"])
def test_tool_imports_execute_in_owned_worker_not_on_event_loop(monkeypatch, worker):
    loop_thread = threading.get_ident()
    import_threads = []
    original_import = builtins.__import__

    def observed_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tools":
            import_threads.append(threading.get_ident())
            return SimpleNamespace(
                Key_Tools=SimpleNamespace(prewarm_key_tool_definitions=lambda: None),
                web_search_tool=SimpleNamespace(autoglm_search_tool_availability=lambda **kwargs: None),
            )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", observed_import)

    async def exercise():
        jobs = StartupJobGroup()
        await jobs.run_sync("tool-import-test", getattr(lifecycle, worker))

    asyncio.run(exercise())
    assert import_threads
    assert all(thread_id != loop_thread for thread_id in import_threads)
