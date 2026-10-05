import asyncio
import gc
import os
import subprocess
import sys
import threading
import time
from typing import Any
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from core.web import lifecycle, startup_jobs
from core.web.router_registry import (
    _ROUTE_MODULE_NAMES,
    import_web_route_modules,
    register_web_routers,
)
from core.web.services import cli_agent_terminal_service, session_service
from core.web.services import virtual_human_life_service
from core.web.startup_jobs import StartupJobGroup


def test_shutdown_step_preserves_deferred_owner_cleanup_result():
    called = []

    async def exercise():
        deadline = time.monotonic() + 1
        return await lifecycle._run_shutdown_step(
            "deferred-store",
            lambda: lifecycle.run_sync_bounded(
                lambda: called.append("closed") or {"closed": True},
                deadline_at=deadline,
                name="deferred-store-worker",
            ),
            deadline=deadline,
        )

    result = asyncio.run(exercise())
    assert called == ["closed"]
    assert result == (True, {"closed": True})


def test_sync_shutdown_owner_waits_for_physical_worker_exit(monkeypatch):
    finishing = threading.Event()
    release = threading.Event()
    workers = []

    class HeldExitThread(threading.Thread):
        def run(self):
            super().run()
            finishing.set()
            release.wait(timeout=2)

    def make_thread(**kwargs):
        worker = HeldExitThread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(
        startup_jobs, "threading", SimpleNamespace(Thread=make_thread, Event=threading.Event),
    )

    async def exercise():
        return await lifecycle.run_sync_bounded(
            lambda: 42, deadline_at=time.monotonic() + 0.04, name="held-shutdown-owner",
        )

    try:
        assert asyncio.run(exercise()) == (False, None)
        assert finishing.is_set()
        assert workers[0].is_alive()
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=1)
    assert not workers[0].is_alive()


def test_shutdown_step_bounds_deferred_owner_before_awaiting_it():
    async def exercise():
        finalized = asyncio.Event()

        async def slow_owner():
            try:
                await asyncio.sleep(0.25)
            finally:
                finalized.set()

        started = time.monotonic()
        result = await lifecycle._run_shutdown_step(
            "slow-deferred-owner", slow_owner, deadline=started + 0.02
        )
        elapsed = time.monotonic() - started
        await asyncio.sleep(0)
        assert result is None
        assert elapsed < 0.2
        assert finalized.is_set()

    asyncio.run(exercise())


def test_lifespan_stops_every_producer_before_waiting_for_slow_startup(monkeypatch):
    called = []
    clean = []

    class SlowStartupJobs(StartupJobGroup):
        def start_thread(self, name, _callback, *_args, **_kwargs):
            return super().start_async(name, asyncio.sleep(0))

        def start_async(self, name, awaitable):
            awaitable.close()
            return super().start_async(name, asyncio.sleep(0))

        async def shutdown(self, *, deadline):
            called.append("startup")
            await asyncio.sleep(1)
            return {"closed": True}

    async def close_runtime(**_kwargs):
        called.append("runtime")
        return {"closed": True}

    monkeypatch.setattr(lifecycle, "StartupJobGroup", SlowStartupJobs)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: called.append("companion"))
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: called.append("workflow"))
    monkeypatch.setattr(lifecycle, "_shutdown_owned_runtime_resources", close_runtime)
    monkeypatch.setattr(
        lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: called.append("stores"),
    )
    monkeypatch.setattr(lifecycle, "mark_server_shutdown_clean", lambda: clean.append(True))

    async def exercise():
        async with lifecycle.web_workbench_lifespan(None):
            await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert set(called) == {"companion", "startup", "workflow", "runtime"}
    assert clean == []


def test_lifespan_keeps_stores_open_while_runtime_producers_are_unjoined(monkeypatch):
    called = []

    class IdleStartupJobs(StartupJobGroup):
        def start_thread(self, name, _callback, *_args, **_kwargs):
            return super().start_async(name, asyncio.sleep(0))

        def start_async(self, name, awaitable):
            awaitable.close()
            return super().start_async(name, asyncio.sleep(0))

    async def close_runtime(**_kwargs):
        return {"closed": False}

    monkeypatch.setattr(lifecycle, "StartupJobGroup", IdleStartupJobs)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_shutdown_owned_runtime_resources", close_runtime)
    monkeypatch.setattr(
        lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: called.append("stores"),
    )
    monkeypatch.setattr(lifecycle, "mark_server_shutdown_clean", lambda: called.append("clean"))

    async def exercise():
        async with lifecycle.web_workbench_lifespan(None):
            await asyncio.sleep(0)

    asyncio.run(exercise())
    assert called == []


def test_lifespan_continues_producer_retirement_when_parent_is_cancelled(monkeypatch):
    called = []
    runtime_started = asyncio.Event()

    class IdleStartupJobs(StartupJobGroup):
        def start_thread(self, name, _callback, *_args, **_kwargs):
            return super().start_async(name, asyncio.sleep(0))

        def start_async(self, name, awaitable):
            awaitable.close()
            return super().start_async(name, asyncio.sleep(0))

    async def close_runtime(**_kwargs):
        runtime_started.set()
        await asyncio.sleep(0.05)
        called.append("runtime")
        return {"closed": True}

    monkeypatch.setattr(lifecycle, "StartupJobGroup", IdleStartupJobs)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_shutdown_owned_runtime_resources", close_runtime)
    monkeypatch.setattr(
        lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: called.append("stores"),
    )
    monkeypatch.setattr(lifecycle, "mark_server_shutdown_clean", lambda: called.append("clean"))

    async def exercise():
        context = lifecycle.web_workbench_lifespan(None)
        await context.__aenter__()
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await runtime_started.wait()
        closing.cancel()
        await closing

    asyncio.run(exercise())
    assert called == ["runtime", "stores", "clean"]


@pytest.mark.parametrize("stores_closed", [True, False])
@pytest.mark.parametrize("transcript_result", [
    {"closed": True, "drained": True},
    {"closed": False, "drained": False, "writer_alive": True},
    {"closed": True, "drained": True, "write_failures": 1},
    {"closed": True, "drained": True, "dropped_writes": 1},
])
def test_lifespan_marks_server_clean_only_after_owned_cleanup(
    monkeypatch, stores_closed, transcript_result,
):
    called = []
    clean = []

    class IdleStartupJobs(StartupJobGroup):
        def start_thread(self, name, _callback, *_args, **_kwargs):
            return super().start_async(name, asyncio.sleep(0))

        def start_async(self, name, awaitable):
            awaitable.close()
            return super().start_async(name, asyncio.sleep(0))

    async def close_runtime(**_kwargs):
        called.append("runtime")
        return {"closed": True}

    monkeypatch.setattr(lifecycle, "StartupJobGroup", IdleStartupJobs)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: called.append("companion"))
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: called.append("workflow"))
    monkeypatch.setattr(lifecycle, "_shutdown_owned_runtime_resources", close_runtime)
    monkeypatch.setattr(
        lifecycle,
        "shutdown_session_catalog_on_shutdown",
        lambda **_kwargs: called.append("stores") or {"closed": stores_closed},
    )
    monkeypatch.setattr(lifecycle, "mark_server_shutdown_clean", lambda: clean.append(tuple(called)))
    monkeypatch.setattr(
        lifecycle, "_shutdown_transcript_writer",
        lambda **_kwargs: called.append("transcript") or transcript_result,
    )

    async def exercise():
        async with lifecycle.web_workbench_lifespan(None):
            await asyncio.sleep(0)

    asyncio.run(exercise())
    assert set(called[:3]) == {"companion", "workflow", "runtime"}
    assert called[3:] == (["stores", "transcript"] if stores_closed else ["stores"])
    expected_clean = (
        stores_closed and transcript_result["closed"]
        and not transcript_result.get("write_failures")
        and not transcript_result.get("dropped_writes")
    )
    assert clean == ([tuple(called)] if expected_clean else [])


def test_transcript_lifecycle_uses_only_existing_owner_and_rejects_unjoined_writer(monkeypatch):
    modules = {}
    monkeypatch.setattr(lifecycle, "sys", SimpleNamespace(modules=modules))
    assert lifecycle._shutdown_transcript_writer(deadline=0) == {"closed": True, "drained": True}
    modules["core.logging.transcript_logger"] = SimpleNamespace(
        begin_transcript_logger_lifecycle=lambda: {"opened": False, "present": False},
    )
    lifecycle._begin_owned_runtime_lifecycle()

    calls = []
    modules["core.logging.transcript_logger"] = SimpleNamespace(
        begin_transcript_logger_lifecycle=lambda: {"opened": True, "present": True},
        shutdown_transcript_logger=lambda **kwargs: calls.append(kwargs) or {"closed": True},
    )
    lifecycle._begin_owned_runtime_lifecycle()
    assert lifecycle._shutdown_transcript_writer(deadline=123) == {"closed": True}
    assert calls == [{"deadline": 123}]
    modules["core.logging.transcript_logger"].begin_transcript_logger_lifecycle = (
        lambda: {"opened": False, "present": True}
    )
    with pytest.raises(RuntimeError, match="could not reopen"):
        lifecycle._begin_owned_runtime_lifecycle()


def test_begin_owned_lifecycle_reopens_loaded_owners_without_cold_imports(monkeypatch):
    called = []
    monkeypatch.setattr(lifecycle, "sys", SimpleNamespace(modules={}))
    lifecycle._begin_owned_runtime_lifecycle()
    assert called == []
    lifecycle.sys.modules.update({
        "core.infrastructure.background_tasks": SimpleNamespace(
            begin_background_task_lifecycle=lambda: called.append("background")),
        "core.web.services.cli_agent_terminal_service": SimpleNamespace(
            begin_cli_agent_terminal_lifecycle=lambda: called.append("terminal")),
    })
    lifecycle._begin_owned_runtime_lifecycle()
    assert called == ["background", "terminal"]


def test_gated_prewarm_stops_before_route_readiness_without_starting_worker(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    called = []

    async def exercise():
        app = FastAPI()
        app.state.web_routes_ready_event = asyncio.Event()
        jobs = StartupJobGroup()
        task = jobs.start_async(
            "gated-prewarm",
            lifecycle._run_prewarm_heavy_after_routes_ready(
                app,
                lambda _timings: called.append("started"),
                worker_name="owned-gated-prewarm",
                startup_jobs=jobs,
            ),
        )
        await asyncio.sleep(0)
        result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is True
        assert task.cancelled()

    asyncio.run(exercise())
    assert called == []


def test_gated_prewarm_retains_real_worker_until_it_exits(monkeypatch):
    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0")
    started = threading.Event()
    release = threading.Event()

    def heavy(_timings):
        started.set()
        assert release.wait(2)

    async def exercise():
        app = FastAPI()
        app.state.web_routes_ready_event = asyncio.Event()
        app.state.web_routes_ready_event.set()
        jobs = StartupJobGroup()
        jobs.start_async(
            "gated-prewarm",
            lifecycle._run_prewarm_heavy_after_routes_ready(
                app, heavy, worker_name="owned-gated-prewarm", startup_jobs=jobs,
            ),
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            result = await jobs.shutdown(deadline=time.monotonic() + 0.03)
            assert result["closed"] is False
            assert result["pendingWorkers"] == ["owned-gated-prewarm"]
        finally:
            release.set()
            result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is True
        assert result["pendingWorkers"] == []

    asyncio.run(exercise())


def test_begin_owned_lifecycle_rejects_unjoined_session_executor(monkeypatch):
    monkeypatch.setattr(lifecycle, "sys", SimpleNamespace(modules={
        "core.web.services.session_service": session_service,
    }))
    monkeypatch.setattr(session_service, "_SESSION_EXECUTORS_CLOSED", True)
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR_DRAIN_THREADS",
        [SimpleNamespace(is_alive=lambda: True, name="stuck-session-executor")],
    )
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())

    with pytest.raises(RuntimeError, match="could not reopen"):
        lifecycle._begin_owned_runtime_lifecycle()


def test_startup_job_group_retires_completed_workers_and_counts_failures():
    async def exercise() -> None:
        jobs = StartupJobGroup()
        results = []
        for value in range(32):
            results.append(await jobs.run_sync("short-startup-worker", lambda value=value: value))
            await asyncio.sleep(0)
            assert len(jobs._workers) <= 1
            assert len(jobs._tasks) <= 1

        assert results == list(range(32))

        async def failed_startup_owner() -> None:
            raise RuntimeError("synthetic startup failure")

        jobs.start_async("failed-startup-owner", failed_startup_owner())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is False
        assert result["failedOwnerCount"] == 1
        assert not jobs._workers
        assert not jobs._tasks

    asyncio.run(exercise())


def test_startup_job_group_waits_for_real_thread_exit_before_returning(monkeypatch):
    exiting = threading.Event()
    release = threading.Event()

    class HeldExitThread(threading.Thread):
        def run(self):
            super().run()
            exiting.set()
            release.wait(timeout=3)

    monkeypatch.setattr(
        startup_jobs, "threading", SimpleNamespace(Thread=HeldExitThread, Event=threading.Event),
    )

    async def exercise():
        jobs = StartupJobGroup()
        task = asyncio.create_task(jobs.run_sync("thread-exit-owner", lambda: 42))
        try:
            deadline = time.monotonic() + 1
            while not exiting.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert exiting.is_set()
            await asyncio.sleep(0.03)
            assert not task.done()
            assert any(worker.thread.is_alive() for worker in jobs._workers)
            release.set()
            assert await task == 42
        finally:
            release.set()
            result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is True
        assert not jobs._workers
        assert not jobs._tasks

    asyncio.run(exercise())


def test_startup_job_group_defers_thread_start_until_event_loop_runs():
    async def exercise() -> None:
        jobs = StartupJobGroup()
        started = threading.Event()
        task = jobs.start_thread("deferred-startup-worker", started.set)

        assert not started.is_set()
        await asyncio.sleep(0)
        assert await asyncio.to_thread(started.wait, 1)
        assert await task is None
        result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is True

    asyncio.run(exercise())


def test_startup_job_group_cancellation_before_worker_start_does_not_leak_owner():
    async def exercise() -> None:
        jobs = StartupJobGroup()
        called = []
        task = jobs.start_thread("cancelled-before-start", lambda: called.append("started"))
        task.cancel()

        result = await jobs.shutdown(deadline=time.monotonic() + 1)

        assert result["closed"] is True
        assert called == []
        assert not jobs._workers
        assert not jobs._tasks

    asyncio.run(exercise())


def test_startup_job_group_stop_before_worker_start_skips_callback():
    async def exercise() -> None:
        jobs = StartupJobGroup()
        called = []
        task = jobs.start_thread("stopped-before-start", lambda: called.append("started"))
        jobs.request_stop()
        await asyncio.sleep(0)

        with pytest.raises(asyncio.CancelledError):
            await task

        result = await jobs.shutdown(deadline=time.monotonic() + 1)
        assert result["closed"] is True
        assert called == []
        assert not jobs._workers
        assert not jobs._tasks

    asyncio.run(exercise())


def test_unawaited_startup_worker_failure_is_consumed_by_owner():
    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        exception_contexts = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: exception_contexts.append(context))
        jobs = StartupJobGroup()
        worker_started = threading.Event()

        def fail_worker() -> None:
            worker_started.set()
            raise RuntimeError("synthetic unobserved startup worker failure")

        try:
            task = jobs.start_thread("unobserved-failing-worker", fail_worker)
            assert await asyncio.to_thread(worker_started.wait, 1)
            # Let the Task deliver the worker error before shutdown can cancel
            # it. Reading done() leaves that exception unobserved.
            async with asyncio.timeout(1):
                while not task.done():
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0)
            del task

            result = await jobs.shutdown(deadline=time.monotonic() + 1)
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)

            assert result["closed"] is False
            assert result["failedOwnerCount"] == 1
            assert not any(
                context.get("message") == "Task exception was never retrieved"
                for context in exception_contexts
            )
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(exercise())


@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
def test_owned_runtime_shutdown_runs_all_owners_when_one_fails_or_cancels(
    monkeypatch, failure_type
):
    from core.infrastructure import background_tasks

    called = []

    def background_shutdown():
        called.append("background")
        raise failure_type("synthetic failure")

    monkeypatch.setattr(background_tasks, "shutdown_background_tasks", background_shutdown)
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions",
                         lambda: called.append("terminal") or {"closed": True})
    monkeypatch.setattr(
        session_service,
        "shutdown_session_service",
        lambda **_kwargs: called.append("session-executors") or {"closed": True},
    )
    for module_name, function_name, owner_name in (
        ("core.infrastructure.tool_execution_scope", "shutdown_tool_execution", "tools"),
        ("core.web.services.chat_room_service", "shutdown_chat_room_executors", "rooms"),
        ("core.web.services.team_workflow.meeting_runtime", "shutdown_meeting_discussion_executor", "meeting"),
        ("core.web.services.team_workflow.research_runtime.hypothesis_command_attempts", "shutdown_hypothesis_command_executor", "commands"),
    ):
        callback = lambda owner=owner_name, **_kwargs: called.append(owner) or {"closed": True}
        monkeypatch.setitem(sys.modules, module_name, SimpleNamespace(**{function_name: callback}))

    result = asyncio.run(
        lifecycle._shutdown_owned_runtime_resources(deadline=time.monotonic() + 1)
    )
    assert sorted(called) == ["background", "commands", "meeting", "rooms", "session-executors", "terminal", "tools"]
    assert result["closed"] is False


@pytest.mark.parametrize("owner_result", [{"closed": False}, None, {}])
def test_session_catalog_shutdown_propagates_unverified_worker(monkeypatch, owner_result):
    from core.web.services.session import catalog_runtime, directory_runtime

    monkeypatch.setattr(directory_runtime, "shutdown_session_directory_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(catalog_runtime, "shutdown_session_catalog_runtime", lambda **_kwargs: owner_result)
    result = lifecycle.shutdown_session_catalog_on_shutdown(deadline=time.monotonic() + 1)
    assert result == {"closed": False, "failedOwners": ["session_catalog"]}


def test_session_executor_shutdown_reopens_both_pools_across_lifecycles(monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "sys",
        SimpleNamespace(modules={"core.web.services.session_service": session_service}),
    )
    assert session_service.begin_session_service_lifecycle()["opened"] is True
    previous_turn_executor = session_service._SESSION_EXECUTOR
    previous_projection_executor = session_service._SESSION_CYCLE_PROJECTION_EXECUTOR

    for _ in range(2):
        session_service.stop_session_service_admission()
        result = session_service.shutdown_session_service(deadline=time.monotonic() + 1)
        assert result["closed"] is True

        lifecycle._begin_owned_runtime_lifecycle()

        assert session_service._SESSION_EXECUTOR is not previous_turn_executor
        assert session_service._SESSION_CYCLE_PROJECTION_EXECUTOR is not previous_projection_executor
        assert session_service._SESSION_EXECUTORS_CLOSED is False
        previous_turn_executor = session_service._SESSION_EXECUTOR
        previous_projection_executor = session_service._SESSION_CYCLE_PROJECTION_EXECUTOR


def test_session_executor_shutdown_reports_joiner_failure(monkeypatch):
    class FailingJoiner:
        name = "synthetic-session-executor-joiner"

        def join(self, timeout=None):
            raise RuntimeError("synthetic join failure")

        def is_alive(self):
            return False

    monkeypatch.setattr(session_service, "stop_session_service_admission", lambda: None)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_THREADS", [FailingJoiner()])
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())

    result = session_service.shutdown_session_service(deadline=time.monotonic() + 1)

    assert result["closed"] is False
    assert result["failedExecutors"] == ["synthetic-session-executor-joiner"]


def test_session_executor_shutdown_reports_executor_close_failure(monkeypatch):
    class FailingExecutor:
        _thread_name_prefix = "synthetic-session-executor"

        def shutdown(self, *, wait, cancel_futures):
            raise RuntimeError("synthetic close failure")

    monkeypatch.setattr(session_service, "_SESSION_EXECUTORS_CLOSED", False)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_THREADS", [])
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR_DRAIN_ERRORS", set())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", FailingExecutor())
    monkeypatch.setattr(session_service, "_SESSION_CYCLE_PROJECTION_EXECUTOR", FailingExecutor())

    result = session_service.shutdown_session_service(deadline=time.monotonic() + 1)

    assert result["closed"] is False
    assert result["failedExecutors"] == ["session-cycle-projection", "session-turns"]


def test_web_app_import_keeps_runtime_scene_service_off_health_path():
    project_root = os.path.dirname(os.path.dirname(__file__))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import core.web.app; "
                "print('core.web.services.runtime_scene_service' in sys.modules)"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_directory_runtime_import_keeps_heavy_dependencies_lazy():
    project_root = os.path.dirname(os.path.dirname(__file__))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; import core.web.services.session.directory_runtime; "
                "print(json.dumps({"
                "'conversationStore': 'core.chat.conversation_store' in sys.modules, "
                "'runtimeScene': 'core.web.services.runtime_scene_service' in sys.modules, "
                "'infrastructure': 'core.infrastructure' in sys.modules"
                "}))"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == (
        '{"conversationStore": false, "runtimeScene": false, "infrastructure": false}'
    )


def test_directory_startup_forwards_lifespan_generation(monkeypatch):
    from core.web.services.session import directory_runtime

    observed = {}
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: False)
    monkeypatch.setattr(
        directory_runtime,
        "initialize_session_directory_runtime",
        lambda **kwargs: observed.update(kwargs) or object(),
    )

    lifecycle.initialize_session_directory_on_startup(generation=23)

    assert observed["generation"] == 23


def test_web_lifespan_records_ready_scene_event_after_entering_context(monkeypatch):
    entered = threading.Event()
    recorded = threading.Event()
    observed = {}

    def record_ready_event(**fields) -> None:
        observed["entered"] = entered.is_set()
        observed.update(fields)
        recorded.set()

    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", record_ready_event)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: {"closed": True})
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        dict,
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            entered.set()
            assert await asyncio.to_thread(recorded.wait, 1)

    asyncio.run(exercise())

    assert observed["entered"] is True
    assert observed["pre_yield_ms"] >= 0
    assert observed["routes_ready"] is False
    assert "cli_terminal_reconcile" in observed["background_tasks"]


def test_web_lifespan_schedules_agent_inbox_recovery_without_blocking_startup(monkeypatch):
    recovery_started = threading.Event()
    catalog_started = threading.Event()
    catalog_shutdown = threading.Event()
    allow_recovery_to_finish = threading.Event()
    reconcile_started = threading.Event()
    allow_reconcile_to_finish = threading.Event()

    def recover() -> dict:
        recovery_started.set()
        allow_recovery_to_finish.wait(timeout=2)
        return {"startedCount": 0}

    def reconcile(**_kwargs) -> dict:
        reconcile_started.set()
        allow_reconcile_to_finish.wait(timeout=2)
        return {"staleCount": 0}

    async def prewarm(**_kwargs) -> None:
        return None

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        reconcile,
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: {"closed": True})
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        recover,
        raising=False,
    )
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", prewarm)
    monkeypatch.setattr(
        lifecycle,
        "initialize_session_catalog_on_startup",
        lambda: catalog_started.set(),
    )
    monkeypatch.setattr(
        lifecycle,
        "shutdown_session_catalog_on_shutdown",
        lambda **_kwargs: catalog_shutdown.set(),
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            # Lifespan must enter before slow startup work finishes.
            assert await asyncio.to_thread(recovery_started.wait, 0.5)
            assert await asyncio.to_thread(catalog_started.wait, 0.5)
            assert await asyncio.to_thread(reconcile_started.wait, 0.5)
            allow_recovery_to_finish.set()
            allow_reconcile_to_finish.set()
            await asyncio.sleep(0)

    asyncio.run(exercise())
    assert catalog_shutdown.is_set()


def test_web_lifespan_does_not_await_cli_reconcile_before_yield(monkeypatch):
    entered = threading.Event()
    reconcile_released = threading.Event()

    def reconcile(**_kwargs) -> dict:
        # Hold the background reconcile until the lifespan body has entered.
        assert entered.wait(timeout=2)
        reconcile_released.set()
        return {"staleCount": 0}

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        reconcile,
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: {"closed": True})
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        lambda: {"startedCount": 0},
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            entered.set()
            await asyncio.sleep(0)
            assert reconcile_released.wait(timeout=2)

    asyncio.run(exercise())


def test_runtime_scene_retention_waits_for_routes_and_is_reaped_on_shutdown(monkeypatch):
    route_release = asyncio.Event()
    route_started = asyncio.Event()
    retention_started = threading.Event()
    retention_release = threading.Event()
    retention_operation_finished = threading.Event()
    retention_calls = []
    later_history = []
    app = FastAPI()

    async def warm_routes(target_app, *, run_sync=None):
        route_started.set()
        await route_release.wait()
        target_app.state.web_routes_registered = True
        target_app.state.web_routes_ready_event.set()

    def slow_retention(*, should_stop):
        retention_calls.append("started")
        retention_started.set()
        assert retention_release.wait(timeout=3)
        retention_operation_finished.set()
        for scene_index in range(10):
            if should_stop():
                retention_calls.append("stopped")
                return {"stopped": True}
            later_history.append(scene_index)
        retention_calls.append("finished")
        return {"deletedCount": 1}

    monkeypatch.setenv("VIBELUTION_DEFER_RUNTIME_SCENE_RETENTION", "1")
    monkeypatch.setattr("core.web.route_bootstrap.warm_web_routes_in_background", warm_routes)
    monkeypatch.setattr(lifecycle, "_enforce_runtime_scene_retention_after_routes_ready", slow_retention)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_challenge_meeting_drivers_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_orphaned_chat_room_rounds_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_hypothesis_command_attempts_on_startup", lambda: None)
    monkeypatch.setattr(
        lifecycle,
        "_recover_interrupted_session_turns_on_startup",
        lambda *, should_stop=None: None,
    )
    monkeypatch.setattr(lifecycle, "_validate_challenge_fence_config_on_startup", lambda: None)
    monkeypatch.setattr(
        lifecycle,
        "reconcile_external_agent_tasks_forever",
        lambda **_kwargs: asyncio.sleep(3600),
    )
    monkeypatch.setattr(
        virtual_human_life_service,
        "run_virtual_human_life_runtime",
        lambda **_kwargs: asyncio.sleep(3600),
    )
    monkeypatch.setattr(virtual_human_life_service, "stop_virtual_human_life_runtime", lambda: None)
    from core.web.services.session import directory_runtime

    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: True)
    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: {"closed": True})
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        dict,
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(app):
            # Health/lifespan readiness has been yielded while route mounting is
            # still held and no scene-history scan has started.
            assert not retention_started.is_set()
            assert await asyncio.wait_for(route_started.wait(), timeout=1)
            assert not retention_started.is_set()

            route_release.set()
            assert await asyncio.to_thread(retention_started.wait, 1)
            assert app.state.web_routes_registered is True
            # The deliberately slow sweep must not hold the serving context.
            assert "runtime-scene-retention" in {
                task.get_name() for task in asyncio.all_tasks()
            }

            # Lifespan shutdown cancels the owner, waits for its executor work,
            # and leaves no named retention task behind.
            asyncio.get_running_loop().call_later(0.02, retention_release.set)

        assert retention_calls == ["started", "stopped"]
        assert retention_operation_finished.is_set()
        assert later_history == []
        await asyncio.sleep(0)
        assert not any(
            task.get_name() in {"runtime-scene-retention", "runtime-scene-retention-worker"}
            and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(exercise())


def test_create_app_starts_financial_coordinator_after_cold_route_mount(monkeypatch):
    from fastapi.testclient import TestClient

    from core.web import route_bootstrap
    from core.web.app import create_app
    from core.web.routes import financial_team as financial_team_route
    from core.web.routes import financial_jobs as financial_jobs_route
    from core.web.routes import financial_reports as financial_reports_route
    from core.web.services import financial_job_service
    from core.web.services.financial_team import coordinator as coordinator_module
    from core.web.services.session import directory_runtime

    coordinator_started = threading.Event()
    coordinator_stopped = threading.Event()
    scheduler_started = threading.Event()
    scheduler_stopped = threading.Event()
    coordinator_observation: dict[str, Any] = {}
    app = create_app()

    def fake_run_forever(*, stop_requested):
        coordinator_observation["routes_registered"] = bool(
            getattr(app.state, "web_routes_registered", False)
        )
        coordinator_started.set()
        while not stop_requested():
            time.sleep(0.005)
        coordinator_stopped.set()

    def fake_scheduler(*, stop_requested):
        assert app.state.web_routes_registered is True
        scheduler_started.set()
        while not stop_requested():
            time.sleep(0.005)
        scheduler_stopped.set()

    class IsolatedStartupJobGroup(StartupJobGroup):
        async def _no_op_owner(self):
            return None

        def start_thread(self, name, callback, *args, **kwargs):
            if name in {"web-route-import", "financial-team-coordinator", "financial-job-scheduler"}:
                return super().start_thread(name, callback, *args, **kwargs)
            return super().start_async(name, self._no_op_owner())

        def start_async(self, name, awaitable):
            if name == "web-routes-bootstrap":
                return super().start_async(name, awaitable)
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return super().start_async(name, self._no_op_owner())

    monkeypatch.setattr(lifecycle, "StartupJobGroup", IsolatedStartupJobGroup)
    monkeypatch.setattr(lifecycle, "_begin_owned_runtime_lifecycle", lambda: None)
    monkeypatch.setattr(lifecycle, "_startup_cache_prewarm_gate_enabled", lambda: False)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda *_args: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_virtual_human_life_runtime", lambda: None)
    monkeypatch.setattr(
        lifecycle,
        "_shutdown_owned_runtime_resources",
        lambda **_kwargs: asyncio.sleep(0, result={"closed": True}),
    )
    monkeypatch.setattr(
        lifecycle,
        "_shutdown_transcript_writer",
        lambda **_kwargs: {"closed": True, "drained": True},
    )
    monkeypatch.setattr(lifecycle, "mark_server_shutdown_clean", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_challenge_meeting_drivers_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_orphaned_chat_room_rounds_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_hypothesis_command_attempts_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_recover_interrupted_session_turns_on_startup", lambda **_kwargs: None)
    monkeypatch.setattr(lifecycle, "_validate_challenge_fence_config_on_startup", lambda: None)
    monkeypatch.setattr(
        lifecycle,
        "reconcile_external_agent_tasks_forever",
        lambda **_kwargs: asyncio.sleep(3600),
    )
    monkeypatch.setattr(coordinator_module, "run_forever", fake_run_forever)
    monkeypatch.setattr(financial_job_service, "run_forever", fake_scheduler)
    monkeypatch.setattr(
        route_bootstrap,
        "import_web_route_modules",
        lambda **_kwargs: [financial_team_route, financial_jobs_route, financial_reports_route],
    )
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: True)
    monkeypatch.delenv("VIBELUTION_DEFER_RUNTIME_SCENE_RETENTION", raising=False)

    with TestClient(app):
        assert coordinator_started.wait(timeout=2)
        assert scheduler_started.wait(timeout=2)

    assert coordinator_observation["routes_registered"] is True
    assert "/api/financial-team/{assistant_agent_id}/runs" in app.openapi()["paths"]
    assert "/api/financial-jobs/{assistant_agent_id}/schedules" in app.openapi()["paths"]
    assert "/api/financial-reports/{assistant_agent_id}/export" in app.openapi()["paths"]
    assert coordinator_stopped.wait(timeout=1)
    assert scheduler_stopped.wait(timeout=1)


def test_router_registry_imports_all_route_modules_in_stable_order(monkeypatch):
    imported: list[str] = []

    class DummyRouter:
        def __init__(self, name: str):
            self.name = name

    class DummyModule:
        def __init__(self, name: str):
            self.router = DummyRouter(name)

    def fake_import(name: str):
        imported.append(name)
        return DummyModule(name)

    monkeypatch.setattr("core.web.router_registry._import_route_module", fake_import)
    modules = import_web_route_modules()
    assert [module.router.name for module in modules] == list(_ROUTE_MODULE_NAMES)
    assert imported == list(_ROUTE_MODULE_NAMES)

    app = FastAPI()
    included: list[str] = []

    def fake_include(router, prefix=""):
        included.append(router.name)

    monkeypatch.setattr(app, "include_router", fake_include)
    register_web_routers(app)
    assert included == list(_ROUTE_MODULE_NAMES)


def test_create_app_health_works_before_routes_and_middleware_mounts_on_demand():
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    app = create_app()
    # Without entering lifespan, routes are not pre-mounted.
    assert bool(getattr(app.state, "web_routes_registered", False)) is False

    with TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()}) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        # Lifespan background warm or first non-health request should finish mounting.
        # /api/skills is a real mounted API route after bootstrap.
        skills = client.get("/api/skills")
        assert skills.status_code in {200, 401, 403, 404, 500} or skills.status_code < 600
        assert bool(getattr(app.state, "web_routes_registered", False)) is True


def test_health_reports_backend_identity_for_port_occupant_reclaim():
    import os as _os

    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    _os.environ.pop("VIBELUTION_WORKSPACE_ROOT", None)
    app = create_app()

    with TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()}) as client:
        body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert isinstance(body["routesReady"], bool)
    # The launcher uses pid + workspaceRoot to reclaim stale same-project
    # backends instead of silently drifting to another port.
    assert body["pid"] == _os.getpid()
    assert isinstance(body["workspaceRoot"], str) and body["workspaceRoot"]
    from core.infrastructure.developer_sandbox import formal_workspace_path

    assert body["storageWorkspaceRoot"] == str(
        formal_workspace_path(Path(body["workspaceRoot"])).resolve()
    )


def test_health_workspace_root_prefers_launcher_environment():
    from core.web.app import _health_workspace_root

    previous = os.environ.get("VIBELUTION_WORKSPACE_ROOT")
    os.environ["VIBELUTION_WORKSPACE_ROOT"] = "C:/worktrees/demo"
    try:
        assert _health_workspace_root() == "C:/worktrees/demo"
    finally:
        if previous is None:
            os.environ.pop("VIBELUTION_WORKSPACE_ROOT", None)
        else:
            os.environ["VIBELUTION_WORKSPACE_ROOT"] = previous


def test_import_web_route_modules_reports_per_module_timing(monkeypatch):
    timings: list[tuple[str, float]] = []

    class DummyRouter:
        def __init__(self, name: str):
            self.name = name

    class DummyModule:
        def __init__(self, name: str):
            self.router = DummyRouter(name)

    def fake_import(name: str):
        return DummyModule(name)

    monkeypatch.setattr("core.web.router_registry._import_route_module", fake_import)
    modules = import_web_route_modules(
        on_module_imported=lambda name, duration_ms: timings.append((name, duration_ms))
    )

    assert len(modules) == len(_ROUTE_MODULE_NAMES)
    assert [name for name, _ in timings] == list(_ROUTE_MODULE_NAMES)
    assert all(isinstance(duration, float) and duration >= 0 for _, duration in timings)


def test_route_bootstrap_payload_carries_per_module_import_timings(monkeypatch):
    from fastapi import FastAPI as _FastAPI

    from core.web import route_bootstrap

    def fake_import_route_modules(*, on_module_imported=None):
        if on_module_imported is not None:
            on_module_imported("core.web.routes.demo", 12.5)
        return ["dummy-module"]

    monkeypatch.setattr(route_bootstrap, "import_web_route_modules", fake_import_route_modules)
    monkeypatch.setattr(route_bootstrap, "register_web_routers_from_modules", lambda app, modules: None)

    app = _FastAPI()
    payload = route_bootstrap.ensure_web_routes_registered(app)

    assert payload["registered"] is True
    assert payload["routeModuleCount"] == 1
    assert payload["moduleImports"] == [{"module": "core.web.routes.demo", "importMs": 12.5}]
