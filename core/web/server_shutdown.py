"""Own the product Uvicorn server and request bounded graceful shutdown."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

LOCAL_EXIT_RESPONSE_DELAY_SECONDS = 0.35
# Electron's retire caller gives the process 30 seconds to disappear. Keep a
# small margin for its final process/port readback after this fallback fires.
SERVER_HARD_EXIT_TIMEOUT_SECONDS = 29.0

_SERVER_LOCK = threading.RLock()
_ACTIVE_SERVER: Any | None = None
_EXIT_SCHEDULED_SERVER: Any | None = None
_CLEAN_SHUTDOWN_SERVER: Any | None = None


@contextmanager
def own_server(server: Any) -> Iterator[None]:
    """Publish the product server while it runs so local retire can stop it."""

    global _ACTIVE_SERVER, _CLEAN_SHUTDOWN_SERVER
    with _SERVER_LOCK:
        previous = _ACTIVE_SERVER
        _ACTIVE_SERVER = server
        _CLEAN_SHUTDOWN_SERVER = None
    try:
        yield
    finally:
        with _SERVER_LOCK:
            if _ACTIVE_SERVER is server:
                _ACTIVE_SERVER = previous


def request_server_shutdown(server: Any | None = None) -> bool:
    """Ask the active Uvicorn server to leave its normal serve loop."""

    with _SERVER_LOCK:
        target = server if server is not None else _ACTIVE_SERVER
    if target is None:
        return False
    target.should_exit = True
    return True


def mark_server_shutdown_clean(server: Any | None = None) -> None:
    """Release the hard-exit watchdog after every owned resource has joined."""

    global _CLEAN_SHUTDOWN_SERVER
    with _SERVER_LOCK:
        target = server if server is not None else _ACTIVE_SERVER
        if target is not None:
            _CLEAN_SHUTDOWN_SERVER = target


def schedule_server_shutdown(
    *,
    delay_seconds: float = LOCAL_EXIT_RESPONSE_DELAY_SECONDS,
    hard_exit_timeout_seconds: float = SERVER_HARD_EXIT_TIMEOUT_SECONDS,
    hard_exit: Callable[[int], Any] = os._exit,
) -> bool:
    """Request graceful exit, with one deadline-bound process-exit fallback."""

    global _EXIT_SCHEDULED_SERVER
    with _SERVER_LOCK:
        server = _ACTIVE_SERVER
        if server is None:
            return False
        if _EXIT_SCHEDULED_SERVER is server:
            return True
        _EXIT_SCHEDULED_SERVER = server

    def _request_exit_and_watch_deadline() -> None:
        global _EXIT_SCHEDULED_SERVER
        time.sleep(max(0.0, float(delay_seconds)))
        if not request_server_shutdown(server):
            return
        deadline = time.monotonic() + max(0.0, float(hard_exit_timeout_seconds))
        while time.monotonic() < deadline:
            with _SERVER_LOCK:
                shutdown_clean = _CLEAN_SHUTDOWN_SERVER is server
            if shutdown_clean:
                with _SERVER_LOCK:
                    if _EXIT_SCHEDULED_SERVER is server:
                        _EXIT_SCHEDULED_SERVER = None
                return
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

        logger.error("Uvicorn server or owned resources exceeded the graceful shutdown deadline; forcing process exit.")
        hard_exit(0)
        with _SERVER_LOCK:
            if _EXIT_SCHEDULED_SERVER is server:
                _EXIT_SCHEDULED_SERVER = None

    threading.Thread(
        target=_request_exit_and_watch_deadline,
        name="web-runtime-shutdown",
        daemon=True,
    ).start()
    return True
