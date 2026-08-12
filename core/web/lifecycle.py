"""Lifecycle hooks for the Web workbench FastAPI app."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def initialize_session_catalog_on_startup() -> object:
    """Start the optional catalog candidate without changing the legacy read path."""

    from config.settings import get_config

    from .services.session.catalog_runtime import initialize_session_catalog_runtime

    return initialize_session_catalog_runtime(
        project_root=Path(__file__).resolve().parents[2],
        catalog_config=get_config().session_catalog,
    )


def shutdown_session_catalog_on_shutdown() -> None:
    """Cancel opt-in catalog-only work before web shutdown completes."""

    from .services.session.catalog_runtime import shutdown_session_catalog_runtime

    shutdown_session_catalog_runtime()


def reconcile_external_agent_tasks_once() -> list[dict[str, Any]]:
    """Recover and reconcile durable external task projections once."""

    from .services.external_agent.service import get_default_service

    project_root = Path(__file__).resolve().parents[2]
    return list(get_default_service(project_root).reconcile())


async def reconcile_external_agent_tasks_forever(*, interval_seconds: float = 5.0) -> None:
    """Keep lease expiry and stop acknowledgement live without a child process."""

    interval = max(0.01, float(interval_seconds))
    while True:
        try:
            await asyncio.to_thread(reconcile_external_agent_tasks_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad pass must not disable leases
            logger.warning(
                "External Agent task reconciliation iteration failed (%s); retrying.",
                type(exc).__name__,
            )
        await asyncio.sleep(interval)


def is_windows_proactor_disconnect_noise(context: dict[str, Any]) -> bool:
    if os.name != "nt":
        return False
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False
    fragments = [
        str(context.get("message") or ""),
        repr(context.get("handle")),
        repr(context.get("transport")),
        repr(context.get("protocol")),
    ]
    haystack = " ".join(fragment for fragment in fragments if fragment).lower()
    return "proactorbasepipetransport._call_connection_lost" in haystack


@asynccontextmanager
async def web_workbench_lifespan(app: FastAPI | None):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    lifespan_started = time.perf_counter()

    def handle_loop_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if is_windows_proactor_disconnect_noise(context):
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    from .route_bootstrap import warm_web_routes_in_background
    from .services.cli_agent_terminal_service import (
        reconcile_cli_agent_terminal_states_on_startup,
    )
    from .services.session_service import (
        recover_wakeable_agent_inbox_messages_on_startup,
    )

    startup_routes_task: asyncio.Task[Any] | None = None
    if app is not None:
        # Enable async waiters for non-health requests while routes mount in background.
        app.state.web_routes_ready_event = asyncio.Event()
        # Route import/mount is the cold-start bulk cost — do not await before yield so
        # /api/health can pass and Launcher can open the window early.
        startup_routes_task = asyncio.create_task(warm_web_routes_in_background(app))
    # Snapshot the git commit this backend was started from (best effort, never
    # blocks health). The UI compares it with disk HEAD to flag stale instances.
    startup_code_fingerprint_task = asyncio.create_task(asyncio.to_thread(_write_running_code_fingerprint_on_startup))
    # Do not await terminal reconcile before yield — it blocked /api/health readiness
    # and stretched launcher open_launcher_action by the full reconcile cost.
    startup_cli_reconcile_task = asyncio.create_task(
        asyncio.to_thread(reconcile_cli_agent_terminal_states_on_startup, reason="backend_startup")
    )
    startup_cache_prewarm_task = asyncio.create_task(prewarm_ui_caches_on_startup())
    startup_catalog_task = asyncio.create_task(
        asyncio.to_thread(initialize_session_catalog_on_startup)
    )
    startup_agent_inbox_recovery_task = asyncio.create_task(
        asyncio.to_thread(recover_wakeable_agent_inbox_messages_on_startup)
    )
    startup_external_agent_reconcile_task = asyncio.create_task(
        reconcile_external_agent_tasks_forever()
    )
    startup_workflow_runtime_task = asyncio.create_task(
        asyncio.to_thread(_start_research_workflow_runtime)
    )

    def consume_startup_task_result(task: asyncio.Task[Any], *, message: str) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            loop.call_exception_handler(
                {
                    "message": message,
                    "exception": exc,
                }
            )

    if startup_routes_task is not None:
        startup_routes_task.add_done_callback(
            lambda task: consume_startup_task_result(task, message="Web route bootstrap failed during startup.")
        )
    startup_cli_reconcile_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="CLI agent terminal reconcile failed during startup."
        )
    )
    startup_cache_prewarm_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="UI cache prewarm failed during startup.")
    )
    startup_catalog_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Session catalog startup failed.")
    )
    startup_agent_inbox_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Agent inbox recovery failed during startup.")
    )
    startup_external_agent_reconcile_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="External Agent task reconciliation stopped unexpectedly."
        )
    )
    startup_code_fingerprint_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Running-code fingerprint snapshot failed during startup."
        )
    )
    startup_workflow_runtime_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Research workflow Ledger runtime failed during startup."
        )
    )
    try:
        # Emit after tasks are scheduled so open-path diagnosis can see pre-yield cost.
        try:
            from .services.runtime_scene_service import record_runtime_scene_event

            record_runtime_scene_event(
                "backend",
                "startup",
                "backend.lifespan.ready_to_serve",
                message="Workbench lifespan yielded; health is up while routes mount in background.",
                outcome="started",
                fields={
                    "preYieldMs": max(0, int((time.perf_counter() - lifespan_started) * 1000)),
                    "routesReady": bool(
                        app is not None and getattr(app.state, "web_routes_registered", False)
                    ),
                    "backgroundTasks": [
                        *(["web_routes_bootstrap"] if startup_routes_task is not None else []),
                        "cli_terminal_reconcile",
                        "ui_cache_prewarm",
                        "session_catalog",
                        "agent_inbox_recovery",
                        "external_agent_task_reconcile",
                    ],
                },
                lifecycle=True,
            )
        except Exception:
            pass
        yield
    finally:
        shutdown_session_catalog_on_shutdown()
        for startup_task in (
            startup_routes_task,
            startup_cli_reconcile_task,
            startup_cache_prewarm_task,
            startup_catalog_task,
            startup_agent_inbox_recovery_task,
            startup_external_agent_reconcile_task,
            startup_code_fingerprint_task,
            startup_workflow_runtime_task,
        ):
            if startup_task is None:
                continue
            if not startup_task.done():
                startup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await startup_task
        from .services.cli_agent_terminal_service import (
            shutdown_cli_agent_terminal_sessions,
        )

        await asyncio.to_thread(shutdown_cli_agent_terminal_sessions)
        await asyncio.to_thread(_stop_research_workflow_runtime)
        loop.set_exception_handler(previous_handler)


def _start_research_workflow_runtime() -> str:
    from .services.team_workflow.research_runtime.runtime_factory import (
        start_production_workflow_runtime,
    )

    return start_production_workflow_runtime()


def _stop_research_workflow_runtime() -> None:
    from .services.team_workflow.research_runtime.runtime_factory import (
        stop_production_workflow_runtime,
    )

    stop_production_workflow_runtime()


def _write_running_code_fingerprint_on_startup() -> None:
    from .services.code_freshness import write_running_code_fingerprint

    project_root = Path(__file__).resolve().parents[2]
    write_running_code_fingerprint(project_root=project_root, source="web_workbench_lifespan")


def _prewarm_git_memory_on_startup() -> tuple[Any, int]:
    from core.infrastructure import git_memory

    started = time.perf_counter()
    state = git_memory.refresh_git_memory(force=True)
    return state, max(0, int((time.perf_counter() - started) * 1000))


async def prewarm_ui_caches_on_startup() -> None:
    from tools import Key_Tools, web_search_tool

    started = time.perf_counter()
    results = await asyncio.gather(
        asyncio.to_thread(Key_Tools.prewarm_key_tool_definitions),
        asyncio.to_thread(web_search_tool.autoglm_search_tool_availability, force=True),
        asyncio.to_thread(_prewarm_git_memory_on_startup),
    )
    git_state, git_duration_ms = results[2]
    from .services.runtime_scene_service import record_runtime_scene_event

    record_runtime_scene_event(
        "runtime_manager",
        "startup_prewarm",
        "runtime.startup.git_memory_prewarmed",
        message="Git memory was prewarmed before the first chat turn.",
        outcome="completed",
        fields={
            "durationMs": git_duration_ms,
            "totalPrewarmMs": max(0, int((time.perf_counter() - started) * 1000)),
            "available": bool(getattr(git_state, "available", False)),
            "dirty": bool(getattr(git_state, "dirty", False)),
            "headPresent": bool(getattr(git_state, "head_rev", None)),
            "indexedHeadPresent": bool(getattr(git_state, "indexed_head_rev", None)),
        },
        lifecycle=True,
    )
