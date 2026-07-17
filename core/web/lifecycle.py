"""Lifecycle hooks for the Web workbench FastAPI app."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI


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

    def consume_startup_cache_prewarm_result(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            loop.call_exception_handler(
                {
                    "message": "UI cache prewarm failed during startup.",
                    "exception": exc,
                }
            )

    startup_cache_prewarm_task.add_done_callback(consume_startup_cache_prewarm_result)
    try:
        yield
    finally:
        if not startup_cache_prewarm_task.done():
            startup_cache_prewarm_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_cache_prewarm_task
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
