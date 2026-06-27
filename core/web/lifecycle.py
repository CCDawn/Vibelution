"""Lifecycle hooks for the Web workbench FastAPI app."""

from __future__ import annotations

import asyncio
import os
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


async def prewarm_ui_caches_on_startup() -> None:
    from .services import chat_room_service, memory_service, session_service

    await asyncio.to_thread(session_service.prewarm_session_list_cache, reason="startup")
    await asyncio.to_thread(chat_room_service.prewarm_chat_room_participant_indexes, reason="startup")
    await asyncio.to_thread(memory_service.prewarm_memory_overview_cache, reason="startup")
