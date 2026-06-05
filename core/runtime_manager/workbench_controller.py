"""Low-level workbench lifecycle helpers used by the runtime manager."""

from __future__ import annotations

import json
import locale
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import http.client
from typing import Any

from config.workbench import configured_backend_port

from .constants import (
    DEFAULT_HEALTH_URL,
    DEFAULT_URL,
    LAUNCHER_SCRIPT_PATH,
    LAUNCHER_STATE_PATH,
    PROJECT_ROOT,
    PYTHON_LAUNCHER_SCRIPT_PATH,
)
from .process_inventory import list_repo_runtime_processes


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _is_process_alive_windows(int(pid))
        except OSError:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _load_launcher_state() -> dict[str, Any]:
    if not LAUNCHER_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _health_url_for(url: str) -> str:
    normalized = str(url or DEFAULT_URL).rstrip("/")
    return f"{normalized}/api/health"


def _is_backend_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(_health_url_for(url), timeout=2.0) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return False


def _port_for_url(url: str) -> int:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except ValueError:
        return 0
    if parsed.port:
        return int(parsed.port)
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return 0


def _listening_pid_for_port_windows(port: int) -> int:
    if port <= 0:
        return 0
    command = (
        "Get-NetTCPConnection -LocalPort "
        f"{int(port)} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty OwningProcess"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2.0,
            creationflags=_creation_flags(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(str(result.stdout or "").strip().splitlines()[0])
    except (IndexError, ValueError):
        return 0


def _port_is_listening_socket(port: int) -> bool:
    if port <= 0:
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        return probe.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        probe.close()


def _listening_pid_for_port(port: int) -> int:
    if port <= 0:
        return 0
    psutil_pid = _listening_pid_for_port_psutil(port)
    if psutil_pid > 0:
        return psutil_pid
    if os.name == "nt":
        return _listening_pid_for_port_windows(port)
    return 0


def _listening_pid_for_port_psutil(port: int) -> int:
    if port <= 0:
        return 0
    try:
        import psutil
    except Exception:
        return 0
    try:
        for connection in psutil.net_connections(kind="tcp"):
            local = getattr(connection, "laddr", None)
            if not local or int(getattr(local, "port", 0) or 0) != int(port):
                continue
            if str(getattr(connection, "status", "") or "").upper() != "LISTEN":
                continue
            pid = int(getattr(connection, "pid", 0) or 0)
            if pid > 0:
                return pid
    except Exception:
        return 0
    return 0


def _repo_workbench_backend_kind(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        for item in list_repo_runtime_processes(project_root=PROJECT_ROOT):
            if item.pid == int(pid) and item.kind in {"managed_workbench_backend", "unmanaged_workbench"}:
                return item.kind
    except Exception:
        return ""
    return ""


def _pid_is_repo_workbench_backend(pid: int) -> bool:
    return _repo_workbench_backend_kind(pid) == "managed_workbench_backend"


def observe_workbench() -> dict[str, Any]:
    launcher_state = _load_launcher_state()
    url = str(launcher_state.get("url") or DEFAULT_URL).strip() or DEFAULT_URL
    state_backend_pid = int(launcher_state.get("backendPid") or 0)
    backend_launch_pid = int(launcher_state.get("backendLaunchPid") or 0)
    browser_launch_pid = int(launcher_state.get("browserLaunchPid") or 0)
    browser_window_pid = int(launcher_state.get("browserWindowPid") or 0)
    browser_managed = bool(launcher_state.get("browserManaged", True))
    session_role = str(launcher_state.get("sessionRole") or "workbench").strip() or "workbench"

    backend_alive = _is_process_alive(state_backend_pid)
    health_probe_url = url if launcher_state else DEFAULT_URL
    healthy = _is_backend_healthy(health_probe_url)
    port = _port_for_url(url)
    port_owner_pid = _listening_pid_for_port(port)
    port_listening = bool(port_owner_pid) or _port_is_listening_socket(port)
    browser_window_alive = _is_process_alive(browser_window_pid)
    port_owner_kind = _repo_workbench_backend_kind(port_owner_pid) if port_owner_pid > 0 else ""
    port_owner_trusted = bool(
        port_owner_pid > 0
        and (
            (state_backend_pid > 0 and port_owner_pid == state_backend_pid)
            or port_owner_kind == "managed_workbench_backend"
        )
    )
    port_owner_residual = bool(port_owner_pid > 0 and not port_owner_trusted and port_owner_kind == "unmanaged_workbench")
    port_conflict = bool(port_owner_pid > 0 and not port_owner_trusted and not port_owner_residual)
    trusted_health = (
        healthy
        and not port_conflict
        and not port_owner_residual
        and (backend_alive or port_owner_trusted or port_owner_pid <= 0)
    )
    backend_observed = (backend_alive and not port_conflict) or port_owner_trusted or trusted_health
    backend_pid = state_backend_pid if backend_alive else port_owner_pid if port_owner_trusted else 0
    if session_role == "launcher_control_surface":
        observed_state = "closed"
    elif not backend_observed and not browser_window_alive:
        observed_state = "closed"
    else:
        observed_state = "open"
    frontend_orphaned = bool(session_role != "launcher_control_surface" and browser_managed and browser_window_alive and not backend_observed)
    backend_missing = bool(observed_state == "open" and not backend_observed)
    if port_owner_residual:
        lifecycle_consistency = "residual_backend"
    elif port_conflict:
        lifecycle_consistency = "port_conflict"
    elif frontend_orphaned:
        lifecycle_consistency = "orphaned_browser"
    elif backend_missing:
        lifecycle_consistency = "backend_missing"
    elif observed_state == "open" and browser_managed and not browser_window_alive:
        lifecycle_consistency = "browser_missing"
    else:
        lifecycle_consistency = "consistent"

    return {
        "launcherStatePresent": bool(launcher_state),
        "sessionId": str(launcher_state.get("sessionId") or "").strip(),
        "sessionRole": session_role,
        "backendPid": backend_pid,
        "backendLaunchPid": backend_launch_pid,
        "browserLaunchPid": browser_launch_pid,
        "browserWindowPid": browser_window_pid,
        "browserManaged": browser_managed,
        "url": url,
        "healthUrl": _health_url_for(health_probe_url),
        "backendAlive": backend_alive,
        "backendHealthy": healthy,
        "backendObserved": backend_observed,
        "backendPort": port,
        "backendPortListening": port_listening,
        "backendPortOwnerPid": port_owner_pid,
        "backendPortOwnerKind": port_owner_kind,
        "backendPortOwnerTrusted": port_owner_trusted,
        "backendPortOwnerResidual": port_owner_residual,
        "backendPortConflict": port_conflict,
        "browserWindowAlive": browser_window_alive,
        "observedState": observed_state,
        "backendMissing": backend_missing,
        "frontendOrphaned": frontend_orphaned,
        "lifecycleConsistency": lifecycle_consistency,
    }


def _creation_flags() -> int:
    flags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _read_capture_file(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return raw.decode(encoding, errors="replace")


def _launcher_command_args(action: str, *, no_browser: bool = False) -> list[str]:
    if os.name == "nt":
        args = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCHER_SCRIPT_PATH),
            "-Action",
            str(action),
        ]
        if no_browser:
            args.append("-NoBrowser")
        return args
    args = [
        sys.executable,
        str(PYTHON_LAUNCHER_SCRIPT_PATH),
        "--action",
        str(action),
    ]
    if no_browser:
        args.append("--no-browser")
    return args


def run_launcher_action(action: str, *, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    args = _launcher_command_args(action, no_browser=no_browser)
    env = os.environ.copy()
    env["VIBELUTION_PORT"] = str(configured_backend_port())
    env["VIBELUTION_PROTECTED_PROCESS_IDS"] = ";".join(
        str(pid)
        for pid in (os.getpid(), os.getppid())
        if int(pid or 0) > 0
    )
    stdout_fd, stdout_path = tempfile.mkstemp(prefix="vibelution-launcher-stdout-", suffix=".log")
    stderr_fd, stderr_path = tempfile.mkstemp(prefix="vibelution-launcher-stderr-", suffix=".log")
    try:
        with os.fdopen(stdout_fd, "w+b") as stdout_handle, os.fdopen(stderr_fd, "w+b") as stderr_handle:
            result = subprocess.run(
                args,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=_creation_flags(),
                env=env,
                check=False,
            )
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_read_capture_file(stdout_path),
            stderr=_read_capture_file(stderr_path),
        )
    finally:
        for capture_path in (stdout_path, stderr_path):
            try:
                os.remove(capture_path)
            except OSError:
                pass


def open_workbench(*, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-start", no_browser=no_browser)


def close_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-stop")


def restart_workbench(*, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    result = run_launcher_action("internal-restart", no_browser=no_browser)
    return result
