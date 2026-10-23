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


@pytest.mark.parametrize("web,enabled,expects_gate", [(True, "1", True), (False, "1", False), (True, "0", False)])
def test_lifespan_only_defers_companion_heartbeat_for_gated_web_startup(monkeypatch, web, enabled, expects_gate):
    from core.web.services import virtual_human_life_service as life

    class IdleStartupJobs(StartupJobGroup):
        def start_thread(self, name, _callback, *_args, **_kwargs):
            return super().start_async(name, asyncio.sleep(0))

        def start_async(self, name, awaitable):
            awaitable.close()
            return super().start_async(name, asyncio.sleep(0))

    observed = []

    def runtime(**kwargs):
        observed.append(kwargs["initial_heartbeat_gate"])
        return asyncio.sleep(0)

    async def close_runtime(**_kwargs):
        return {"closed": False}

    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", enabled)
    monkeypatch.setattr(lifecycle, "StartupJobGroup", IdleStartupJobs)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_shutdown_owned_runtime_resources", close_runtime)
    monkeypatch.setattr(life, "run_virtual_human_life_runtime", runtime)

    async def exercise():
        async with lifecycle.web_workbench_lifespan(FastAPI() if web else None):
            assert len(observed) == 1
            assert (observed[0] is not None) is expects_gate

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_before_heartbeat", [False, True])
def test_companion_preparation_stays_immediate_while_automatic_heartbeat_waits(monkeypatch, cancel_before_heartbeat):
    from core.web.services import virtual_human_life_service as life

    monkeypatch.setattr(life, "_RUNTIME_STARTED", threading.Event())
    monkeypatch.setattr(life, "_RUNTIME_ACCEPTING", threading.Event())
    monkeypatch.setattr(life, "stop_virtual_human_life_runtime", lambda: life._RUNTIME_ACCEPTING.clear())
    calls = []

    async def exercise():
        entered_gate = asyncio.Event()
        release = asyncio.Event()
        initial_done = asyncio.Event()

        def heartbeat(**kwargs):
            calls.append(kwargs)
            if not kwargs.get("prepare_only"):
                initial_done.set()

        async def run_sync(_name, callback, **kwargs):
            return callback(**kwargs)

        async def gate():
            entered_gate.set()
            await release.wait()

        monkeypatch.setattr(life, "heartbeat_all_virtual_humans", heartbeat)
        task = asyncio.create_task(life.run_virtual_human_life_runtime(
            run_sync=run_sync, initial_heartbeat_gate=gate,
        ))
        await asyncio.wait_for(entered_gate.wait(), 1)
        assert calls == [{"coalesced": True, "prepare_only": True}]
        assert life._runtime_acceptance_allowed()
        if not cancel_before_heartbeat:
            release.set()
            await asyncio.wait_for(initial_done.wait(), 1)
            assert calls[-1] == {"coalesced": True}
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not life._RUNTIME_ACCEPTING.is_set()

    asyncio.run(exercise())
    assert len(calls) == (1 if cancel_before_heartbeat else 2)


def test_companion_preparation_repairs_visibility_without_life_or_transcript_recovery(monkeypatch):
    from core.agent_plugins.virtual_human_life import native_wakeup
    from core.web.services import virtual_human_life_service as life

    accepting = threading.Event()
    accepting.set()
    monkeypatch.setattr(life, "_RUNTIME_ACCEPTING", accepting)
    calls = []
    service = SimpleNamespace(
        agent_lister=lambda: [{"agentId": "companion"}, {"agentId": "ordinary"}],
        binding_for=lambda agent_id: {"enabled": True} if agent_id == "companion" else None,
        heartbeat_agent=lambda *args, **kwargs: pytest.fail("automatic life recovery ran during preparation"),
    )
    monkeypatch.setattr(life, "get_virtual_human_life_service", lambda: service)
    monkeypatch.setattr(native_wakeup, "recover_pending_purges", lambda: calls.append("purges"))
    monkeypatch.setattr(life, "_reconcile_enabled_companion_directory_visibility",
                        lambda _service, *, agent_id, binding: calls.append(("visibility", agent_id)) or binding)
    monkeypatch.setattr(life, "_default_agent_persona_initializer", lambda agent_id: calls.append(("persona", agent_id)))

    assert life.heartbeat_all_virtual_humans(coalesced=True, prepare_only=True) == []
    assert calls == ["purges", ("visibility", "companion"), ("persona", "companion")]


@pytest.mark.parametrize("web,enabled,delay", [(True, "1", 12.0), (False, "1", 0.0), (True, "0", 0.0)])
def test_only_bulk_hypothesis_recovery_yields_the_startup_budget(monkeypatch, web, enabled, delay):
    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", enabled)
    monkeypatch.delenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", raising=False)
    calls = []
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda **kwargs: calls.append(kwargs) or "ready")

    async def exercise():
        result = await lifecycle._start_workflow_runtime_job(StartupJobGroup(), app=FastAPI() if web else None)
        assert result == "ready"

    asyncio.run(exercise())
    assert calls == ([{"hypothesis_recovery_delay_s": delay}] if delay else [{}])


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


def test_session_recovery_waits_for_directory_and_first_request_window(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    monkeypatch.delenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", raising=False)
    calls = []
    loop_thread = threading.get_ident()

    async def exercise():
        app = FastAPI()
        app.state.web_routes_ready_event = asyncio.Event()
        directory_gate = asyncio.Event()
        directory = asyncio.create_task(directory_gate.wait())
        jobs = StartupJobGroup()

        def recover(*, should_stop):
            assert not should_stop()
            calls.append(threading.get_ident())
            return {"recovered": True}

        task = asyncio.create_task(lifecycle._run_session_recovery_after_first_frame(
            app, directory, jobs, recover, worker_name="test-recovery", stop_keyword="should_stop",
        ))
        await asyncio.sleep(0.02)
        assert calls == []
        directory_gate.set()
        await directory
        await asyncio.sleep(0.02)
        assert calls == []
        app.state.web_routes_ready_event.set()
        assert await asyncio.wait_for(task, 5) == {"recovered": True}

    asyncio.run(exercise())
    assert len(calls) == 1
    assert calls[0] != loop_thread


@pytest.mark.parametrize("cancel_during", ["directory", "settle"])
def test_cancelled_deferred_recovery_never_opens_a_second_store(monkeypatch, cancel_during):
    calls = []

    async def exercise():
        directory_gate = asyncio.Event()
        settle_gate = asyncio.Event()
        entered_settle = asyncio.Event()

        async def wait_for_first_requests(_app):
            entered_settle.set()
            await settle_gate.wait()

        monkeypatch.setattr(lifecycle, "_await_startup_prewarm_gate", wait_for_first_requests)
        monkeypatch.setattr(lifecycle, "_startup_cache_prewarm_gate_enabled", lambda: True)
        directory = asyncio.create_task(directory_gate.wait())
        task = asyncio.create_task(lifecycle._run_session_recovery_after_first_frame(
            FastAPI(), directory, StartupJobGroup(), lambda: calls.append("opened"),
            worker_name="test-cancelled-recovery",
        ))
        if cancel_during == "settle":
            directory_gate.set()
            await entered_settle.wait()
        else:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not directory.cancelled()
        directory_gate.set()
        await directory

    asyncio.run(exercise())
    assert calls == []


def test_disabling_optional_delay_still_reuses_the_directory_owner(monkeypatch):
    monkeypatch.setenv("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM", "0")
    calls = []

    async def exercise():
        directory_gate = asyncio.Event()
        directory = asyncio.create_task(directory_gate.wait())
        task = asyncio.create_task(lifecycle._run_session_recovery_after_first_frame(
            FastAPI(), directory, StartupJobGroup(), lambda: calls.append("recovered"),
            worker_name="test-recovery-no-delay",
        ))
        await asyncio.sleep(0.02)
        assert calls == []
        directory_gate.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(exercise())
    assert calls == ["recovered"]


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
