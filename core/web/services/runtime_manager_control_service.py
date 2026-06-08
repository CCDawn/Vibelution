"""Lightweight runtime-manager control checks for web services."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from core.runtime_manager.constants import PROJECT_ROOT as RUNTIME_MANAGER_PROJECT_ROOT
from core.runtime_manager.state_store import load_pid

from .runtime_scene_service import record_runtime_scene_event


LIVE_CONTROL_CACHE_TTL_SECONDS = 1.0
LIVE_CONTROL_SLOW_PROBE_MS = 50.0
_LIVE_CONTROL_CACHE_LOCK = threading.Lock()
_LIVE_CONTROL_CACHE: dict[str, Any] = {
    "root": "",
    "expiresAt": 0.0,
    "enabled": False,
    "daemonPid": 0,
    "projectRootMatches": False,
}
_LIVE_CONTROL_LAST_EVENT_KEY: tuple[str, bool, int, bool] | None = None


def reset_runtime_manager_live_control_cache() -> None:
    """Clear the short-lived live-control cache for tests and explicit refreshes."""

    global _LIVE_CONTROL_LAST_EVENT_KEY
    with _LIVE_CONTROL_CACHE_LOCK:
        _LIVE_CONTROL_CACHE.update(
            {
                "root": "",
                "expiresAt": 0.0,
                "enabled": False,
                "daemonPid": 0,
                "projectRootMatches": False,
            }
        )
        _LIVE_CONTROL_LAST_EVENT_KEY = None


def runtime_manager_live_control_enabled(project_root: Path | str) -> bool:
    """Return whether the runtime manager can own evolution control for this project.

    This intentionally avoids ``load_runtime_snapshot()`` because that path performs
    full Workbench observation and process inventory scans. Evolution polling only
    needs to know whether the current repo's runtime-manager daemon is alive.
    """

    root = _resolve_root(project_root)
    if root is None:
        return False
    root_key = str(root)
    now = time.monotonic()
    with _LIVE_CONTROL_CACHE_LOCK:
        if _LIVE_CONTROL_CACHE["root"] == root_key and now < float(_LIVE_CONTROL_CACHE["expiresAt"] or 0.0):
            return bool(_LIVE_CONTROL_CACHE["enabled"])

    started = time.perf_counter()
    result = _probe_live_control(root)
    duration_ms = (time.perf_counter() - started) * 1000
    with _LIVE_CONTROL_CACHE_LOCK:
        _LIVE_CONTROL_CACHE.update(
            {
                "root": root_key,
                "expiresAt": now + LIVE_CONTROL_CACHE_TTL_SECONDS,
                "enabled": bool(result["enabled"]),
                "daemonPid": int(result["daemonPid"]),
                "projectRootMatches": bool(result["projectRootMatches"]),
            }
        )
    _record_live_control_probe(root_key, result, duration_ms=duration_ms)
    return bool(result["enabled"])


def current_runtime_manager_pid(project_root: Path | str) -> int:
    """Return the manager pid when it belongs to this project and is alive."""

    root = _resolve_root(project_root)
    if root is None or not _project_root_matches(root):
        return 0
    pid = _current_runtime_manager_pid()
    return pid if pid > 0 and _is_process_alive(pid) else 0


def _resolve_root(project_root: Path | str) -> Path | None:
    try:
        return Path(project_root).resolve()
    except OSError:
        return None


def _probe_live_control(project_root: Path) -> dict[str, Any]:
    project_root_matches = _project_root_matches(project_root)
    if not project_root_matches:
        return {"enabled": False, "daemonPid": 0, "projectRootMatches": False}
    daemon_pid = _current_runtime_manager_pid()
    return {
        "enabled": daemon_pid > 0 and _is_process_alive(daemon_pid),
        "daemonPid": daemon_pid,
        "projectRootMatches": True,
    }


def _project_root_matches(project_root: Path) -> bool:
    runtime_root = _resolve_root(RUNTIME_MANAGER_PROJECT_ROOT)
    return runtime_root is not None and runtime_root == project_root


def _current_runtime_manager_pid() -> int:
    try:
        return int(load_pid() or 0)
    except Exception:
        return 0


def _is_process_alive(pid: int) -> bool:
    normalized_pid = int(pid or 0)
    if normalized_pid <= 0:
        return False
    if os.name == "nt":
        return _is_process_alive_windows(normalized_pid)
    try:
        os.kill(normalized_pid, 0)
    except OSError:
        return False
    return True


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_information = 0x0400
    process_query_limited_information = 0x1000
    still_active = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (process_query_limited_information, process_query_information):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)


def _record_live_control_probe(root_key: str, result: dict[str, Any], *, duration_ms: float) -> None:
    global _LIVE_CONTROL_LAST_EVENT_KEY
    event_key = (
        root_key,
        bool(result["enabled"]),
        int(result["daemonPid"]),
        bool(result["projectRootMatches"]),
    )
    should_record = duration_ms >= LIVE_CONTROL_SLOW_PROBE_MS
    with _LIVE_CONTROL_CACHE_LOCK:
        if _LIVE_CONTROL_LAST_EVENT_KEY != event_key:
            should_record = True
            _LIVE_CONTROL_LAST_EVENT_KEY = event_key
    if not should_record:
        return
    try:
        record_runtime_scene_event(
            "runtime_manager_control",
            "live_control",
            "runtime_manager.live_control.probed",
            message="Runtime manager live-control state probed.",
            outcome="enabled" if bool(result["enabled"]) else "disabled",
            fields={
                "projectRoot": root_key,
                "enabled": bool(result["enabled"]),
                "daemonPid": int(result["daemonPid"]),
                "projectRootMatches": bool(result["projectRootMatches"]),
                "durationMs": round(duration_ms, 1),
                "cacheTtlSeconds": LIVE_CONTROL_CACHE_TTL_SECONDS,
            },
        )
    except Exception:
        return
