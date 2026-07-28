"""Lifecycle hooks for the Web workbench FastAPI app."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI


def initialize_session_catalog_on_startup() -> object:
    """Start the optional catalog candidate without changing the legacy read path."""

    from config.settings import get_config

    from .services.session.catalog_runtime import initialize_session_catalog_runtime

    return initialize_session_catalog_runtime(
        project_root=Path(__file__).resolve().parents[2],
        catalog_config=get_config().session_catalog,
    )


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
async def web_workbench_lifespan(_: FastAPI):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_loop_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if is_windows_proactor_disconnect_noise(context):
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    from .services.cli_agent_terminal_service import reconcile_cli_agent_terminal_states_on_startup

    await asyncio.to_thread(reconcile_cli_agent_terminal_states_on_startup, reason="backend_startup")
    startup_cache_prewarm_task = asyncio.create_task(prewarm_ui_caches_on_startup())
    startup_catalog_task = asyncio.create_task(
        asyncio.to_thread(initialize_session_catalog_on_startup)
    )
    from .services.session_service import recover_wakeable_agent_inbox_messages_on_startup

    startup_agent_inbox_recovery_task = asyncio.create_task(
        asyncio.to_thread(recover_wakeable_agent_inbox_messages_on_startup)
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

    startup_cache_prewarm_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="UI cache prewarm failed during startup.")
    )
    startup_catalog_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Session catalog startup failed.")
    )
    startup_agent_inbox_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Agent inbox recovery failed during startup.")
    )
    try:
        yield
    finally:
        for startup_task in (
            startup_cache_prewarm_task,
            startup_catalog_task,
            startup_agent_inbox_recovery_task,
        ):
            if not startup_task.done():
                startup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await startup_task
        from .services.cli_agent_terminal_service import shutdown_cli_agent_terminal_sessions

        await asyncio.to_thread(shutdown_cli_agent_terminal_sessions)
        loop.set_exception_handler(previous_handler)


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
