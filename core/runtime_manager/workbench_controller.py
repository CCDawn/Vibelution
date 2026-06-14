"""Low-level workbench lifecycle helpers used by the runtime manager."""

from __future__ import annotations

import json
import locale
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import http.client
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
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
from .process_inventory import list_repo_runtime_processes, managed_browser_process_payload
from .scene_logging import append_runtime_manager_file_event, truncate_event_text

INTERNAL_LAUNCHER_ENV = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
INTERNAL_LAUNCHER_VALUE = "1"
LAUNCHER_ACTION_CANCELLED_RETURN_CODE = 130


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


def _write_launcher_state(payload: dict[str, Any]) -> None:
    LAUNCHER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{LAUNCHER_STATE_PATH.name}.", dir=str(LAUNCHER_STATE_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, LAUNCHER_STATE_PATH)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _remove_launcher_state() -> None:
    try:
        LAUNCHER_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def clear_workbench_launcher_state_after_close() -> dict[str, Any]:
    """Clear stale Workbench PIDs while preserving the separate Launcher control surface."""

    previous_state = _load_launcher_state()
    if not previous_state:
        _remove_launcher_state()
        return {
            "statePath": str(LAUNCHER_STATE_PATH),
            "statePresent": False,
            "preservedLauncherControlState": False,
            "removedState": True,
            "reason": "missing_or_unreadable_state",
        }

    launcher_backend_pid = int(previous_state.get("launcherBackendPid") or 0)
    launcher_backend_launch_pid = int(previous_state.get("launcherBackendLaunchPid") or 0)
    launcher_browser_launch_pid = int(previous_state.get("launcherBrowserLaunchPid") or 0)
    launcher_browser_window_pid = int(previous_state.get("launcherBrowserWindowPid") or 0)
    launcher_alive = _is_process_alive(launcher_backend_pid) or _is_process_alive(launcher_browser_window_pid)
    if not launcher_alive:
        _remove_launcher_state()
        return {
            "statePath": str(LAUNCHER_STATE_PATH),
            "statePresent": True,
            "preservedLauncherControlState": False,
            "removedState": True,
            "reason": "no_launcher_control_process_alive",
            "launcherBackendPid": launcher_backend_pid,
            "launcherBrowserWindowPid": launcher_browser_window_pid,
        }

    payload = dict(previous_state)
    launcher_browser_profile_dir = str(previous_state.get("launcherBrowserProfileDir") or "").strip()
    workbench_browser_profile_dir = str(previous_state.get("workbenchBrowserProfileDir") or "").strip()
    launcher_control_started_at = str(
        previous_state.get("launcherControlStartedAt")
        or previous_state.get("startedAt")
        or ""
    )
    payload.update(
        {
            "sessionRole": "launcher_control_surface",
            "backendPid": 0,
            "backendLaunchPid": 0,
            "backendStdout": None,
            "backendStderr": None,
            "launcherBackendPid": launcher_backend_pid,
            "launcherBackendLaunchPid": launcher_backend_launch_pid or launcher_backend_pid,
            "browserManaged": True,
            "browserProfileDir": launcher_browser_profile_dir,
            "browserLaunchPid": launcher_browser_launch_pid,
            "browserWindowPid": launcher_browser_window_pid,
            "workbenchBrowserLaunchPid": 0,
            "workbenchBrowserWindowPid": 0,
            "workbenchBrowserProfileDir": workbench_browser_profile_dir,
            "launcherBrowserProfileDir": launcher_browser_profile_dir,
            "launcherBrowserLaunchPid": launcher_browser_launch_pid,
            "launcherBrowserWindowPid": launcher_browser_window_pid,
            "supervisorPid": 0,
            "supervisorStdout": None,
            "supervisorStderr": None,
            "runtimeSceneId": None,
            "runtimeSceneDir": None,
            "launcherControlStartedAt": launcher_control_started_at,
            "startedAt": launcher_control_started_at,
        }
    )
    _write_launcher_state(payload)
    return {
        "statePath": str(LAUNCHER_STATE_PATH),
        "statePresent": True,
        "preservedLauncherControlState": True,
        "removedState": False,
        "reason": "launcher_control_process_alive",
        "launcherBackendPid": launcher_backend_pid,
        "launcherBrowserWindowPid": launcher_browser_window_pid,
    }


def persist_workbench_launcher_state_after_open(
    observation: dict[str, Any],
    *,
    last_reason: str = "",
    last_source: str = "runtime_manager",
) -> dict[str, Any]:
    previous_state = _load_launcher_state()
    observed = observation if isinstance(observation, dict) else {}
    backend_pid = int(observed.get("backendPid") or 0)
    browser_window_pid = int(observed.get("browserWindowPid") or 0)
    if backend_pid <= 0 and browser_window_pid <= 0:
        return {
            "updatedState": False,
            "reason": "missing_workbench_process",
            "statePath": str(LAUNCHER_STATE_PATH),
        }

    browser_launch_pid = int(observed.get("browserLaunchPid") or browser_window_pid or 0)
    backend_launch_pid = int(observed.get("backendLaunchPid") or backend_pid or 0)
    backend_port = int(observed.get("backendPort") or configured_backend_port())
    workbench_profile_dir = str(
        observed.get("browserProfileDir")
        or previous_state.get("workbenchBrowserProfileDir")
        or ""
    ).strip()
    launcher_profile_dir = str(previous_state.get("launcherBrowserProfileDir") or "").strip()
    payload = dict(previous_state)
    payload.update(
        {
            "schemaVersion": int(previous_state.get("schemaVersion") or 1),
            "sessionRole": "workbench",
            "sessionId": str(observed.get("sessionId") or previous_state.get("sessionId") or "").strip(),
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "backendPid": backend_pid,
            "backendLaunchPid": backend_launch_pid,
            "browserManaged": bool(observed.get("browserManaged", previous_state.get("browserManaged", True))),
            "browserExecutable": str(observed.get("browserExecutable") or previous_state.get("browserExecutable") or ""),
            "browserProfileDir": workbench_profile_dir,
            "workbenchBrowserProfileDir": workbench_profile_dir,
            "launcherBrowserProfileDir": launcher_profile_dir,
            "browserLaunchPid": browser_launch_pid,
            "browserWindowPid": browser_window_pid,
            "workbenchBrowserLaunchPid": browser_launch_pid,
            "workbenchBrowserWindowPid": browser_window_pid,
            "url": str(observed.get("url") or previous_state.get("url") or DEFAULT_URL).strip() or DEFAULT_URL,
            "backendPort": backend_port,
            "port": backend_port,
            "statusLine": "Workbench is running.",
            "failureMessage": "",
            "lastReason": str(last_reason or previous_state.get("lastReason") or "runtime_manager_open").strip(),
            "lastSource": str(last_source or previous_state.get("lastSource") or "runtime_manager").strip(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        _write_launcher_state(payload)
    except Exception as exc:
        result = {
            "updatedState": False,
            "reason": "write_failed",
            "statePath": str(LAUNCHER_STATE_PATH),
            "errorType": type(exc).__name__,
            "message": str(exc),
        }
        append_runtime_manager_file_event(
            "launcher.state.workbench_open_persist_failed",
            result,
            suppress_io_errors=True,
        )
        return result

    result = {
        "updatedState": True,
        "reason": "workbench_open",
        "statePath": str(LAUNCHER_STATE_PATH),
        "backendPid": backend_pid,
        "browserWindowPid": browser_window_pid,
        "launcherBrowserWindowPid": int(payload.get("launcherBrowserWindowPid") or 0),
    }
    append_runtime_manager_file_event(
        "launcher.state.workbench_open_persisted",
        result,
        suppress_io_errors=True,
    )
    return result


def _health_url_for(url: str) -> str:
    normalized = str(url or DEFAULT_URL).rstrip("/")
    return f"{normalized}/api/health"


def _open_backend_health_url(url: str, *, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)


def _is_backend_healthy(url: str) -> bool:
    try:
        with _open_backend_health_url(_health_url_for(url), timeout=2.0) as response:
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
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2.0,
            creationflags=_creation_flags(detach=True),
            startupinfo=_hidden_startup_info(),
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


def _recover_managed_browser_window_pid(profile_dir: str) -> int:
    profile = str(profile_dir or "").strip()
    if not profile:
        return 0
    try:
        payload = managed_browser_process_payload(profile_dir=profile, command_preview_chars=420)
    except Exception:
        return 0
    if not bool(payload.get("supported")):
        return 0
    items = payload.get("items")
    if not isinstance(items, list):
        return 0

    browser_candidates: list[dict[str, Any]] = []
    fallback_candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = int(item.get("pid") or 0)
        if pid <= 0 or not _is_process_alive(pid):
            continue
        process_type = str(item.get("type") or "").strip().lower()
        command_preview = str(item.get("commandLinePreview") or "")
        if process_type == "browser":
            browser_candidates.append(item)
        if "--app=" in command_preview or process_type == "browser":
            fallback_candidates.append(item)

    for candidates in (browser_candidates, fallback_candidates):
        if candidates:
            return int(candidates[0].get("pid") or 0)
    return 0


def observe_workbench(
    *,
    recover_browser_window: bool = True,
    recover_browser_window_for_backend_observed: bool = True,
) -> dict[str, Any]:
    launcher_state = _load_launcher_state()
    url = str(launcher_state.get("url") or DEFAULT_URL).strip() or DEFAULT_URL
    state_backend_pid = int(launcher_state.get("backendPid") or 0)
    backend_launch_pid = int(launcher_state.get("backendLaunchPid") or 0)
    session_role = str(launcher_state.get("sessionRole") or "workbench").strip() or "workbench"
    if session_role == "launcher_control_surface":
        browser_launch_pid = int(launcher_state.get("workbenchBrowserLaunchPid") or 0)
        browser_window_pid = int(launcher_state.get("workbenchBrowserWindowPid") or 0)
    else:
        browser_launch_pid = int(launcher_state.get("workbenchBrowserLaunchPid") or launcher_state.get("browserLaunchPid") or 0)
        browser_window_pid = int(launcher_state.get("workbenchBrowserWindowPid") or launcher_state.get("browserWindowPid") or 0)
    browser_profile_dir = str(
        launcher_state.get("workbenchBrowserProfileDir")
        or launcher_state.get("browserProfileDir")
        or ""
    ).strip()
    browser_managed = bool(launcher_state.get("browserManaged", True))
    launcher_browser_launch_pid = int(launcher_state.get("launcherBrowserLaunchPid") or 0)
    launcher_browser_window_pid = int(launcher_state.get("launcherBrowserWindowPid") or 0)

    port = _port_for_url(url)
    if (
        session_role == "launcher_control_surface"
        and state_backend_pid <= 0
        and backend_launch_pid <= 0
        and browser_launch_pid <= 0
        and browser_window_pid <= 0
        and not _port_is_listening_socket(port)
    ):
        launcher_browser_window_alive = _is_process_alive(launcher_browser_window_pid)
        return {
            "launcherStatePresent": bool(launcher_state),
            "sessionId": str(launcher_state.get("sessionId") or "").strip(),
            "sessionRole": session_role,
            "backendPid": 0,
            "backendLaunchPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserWindowRecoveredPid": 0,
            "browserWindowRecoverySource": "",
            "browserProfileDir": browser_profile_dir,
            "launcherBrowserLaunchPid": launcher_browser_launch_pid,
            "launcherBrowserWindowPid": launcher_browser_window_pid,
            "launcherBrowserWindowAlive": launcher_browser_window_alive,
            "browserManaged": browser_managed,
            "url": url,
            "healthUrl": _health_url_for(url),
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": port,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerKind": "",
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "observedState": "closed",
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "observationFastPath": "launcher_control_surface_no_workbench_pids",
        }

    state_backend_alive = _is_process_alive(state_backend_pid)
    health_probe_url = url if launcher_state else DEFAULT_URL
    healthy = _is_backend_healthy(health_probe_url)
    port_owner_pid = _listening_pid_for_port(port)
    port_listening = bool(port_owner_pid) or _port_is_listening_socket(port)
    browser_window_alive = _is_process_alive(browser_window_pid)
    recovered_browser_window_pid = 0
    browser_window_recovery_source = ""
    port_owner_kind = _repo_workbench_backend_kind(port_owner_pid) if port_owner_pid > 0 else ""
    port_owner_alive = _is_process_alive(port_owner_pid) if port_owner_pid > 0 else False
    port_owner_trusted = bool(
        port_owner_pid > 0
        and (
            (state_backend_pid > 0 and port_owner_pid == state_backend_pid)
            or port_owner_kind == "managed_workbench_backend"
        )
    )
    backend_alive = bool(state_backend_alive or (port_owner_trusted and port_owner_alive))
    port_owner_residual = bool(port_owner_pid > 0 and not port_owner_trusted and port_owner_kind == "unmanaged_workbench")
    port_conflict = bool(port_owner_pid > 0 and not port_owner_trusted and not port_owner_residual)
    trusted_health = (
        healthy
        and not port_conflict
        and not port_owner_residual
        and (backend_alive or port_owner_trusted or port_owner_pid <= 0)
    )
    backend_observed = (backend_alive and not port_conflict) or port_owner_trusted or trusted_health
    backend_pid = state_backend_pid if state_backend_alive else port_owner_pid if port_owner_trusted else 0
    observed_session_role = (
        "workbench"
        if session_role == "launcher_control_surface" and (backend_observed or browser_window_alive)
        else session_role
    )
    should_recover_browser_window = bool(
        recover_browser_window
        and not browser_window_alive
        and browser_managed
        and observed_session_role != "launcher_control_surface"
        and (recover_browser_window_for_backend_observed or not backend_observed)
    )
    if should_recover_browser_window:
        recovered_browser_window_pid = _recover_managed_browser_window_pid(browser_profile_dir)
        if recovered_browser_window_pid > 0:
            browser_window_pid = recovered_browser_window_pid
            browser_window_alive = True
            browser_window_recovery_source = "managed_profile"
    launcher_browser_window_alive = _is_process_alive(launcher_browser_window_pid)
    managed_browser_missing = bool(
        observed_session_role != "launcher_control_surface"
        and browser_managed
        and backend_observed
        and not browser_window_alive
    )
    if observed_session_role == "launcher_control_surface":
        observed_state = "closed"
    elif not backend_observed and not browser_window_alive:
        observed_state = "closed"
    elif managed_browser_missing:
        observed_state = "partial"
    else:
        observed_state = "open"
    frontend_orphaned = bool(observed_session_role != "launcher_control_surface" and browser_managed and browser_window_alive and not backend_observed)
    backend_missing = bool(observed_state == "open" and not backend_observed)
    if port_owner_residual:
        lifecycle_consistency = "residual_backend"
    elif port_conflict:
        lifecycle_consistency = "port_conflict"
    elif frontend_orphaned:
        lifecycle_consistency = "orphaned_browser"
    elif backend_missing:
        lifecycle_consistency = "backend_missing"
    elif managed_browser_missing:
        lifecycle_consistency = "browser_missing"
    else:
        lifecycle_consistency = "consistent"

    return {
        "launcherStatePresent": bool(launcher_state),
        "sessionId": str(launcher_state.get("sessionId") or "").strip(),
        "sessionRole": observed_session_role,
        "sourceSessionRole": session_role,
        "backendPid": backend_pid,
        "backendLaunchPid": backend_launch_pid,
        "browserLaunchPid": browser_launch_pid,
        "browserWindowPid": browser_window_pid,
        "browserWindowRecoveredPid": recovered_browser_window_pid,
        "browserWindowRecoverySource": browser_window_recovery_source,
        "browserProfileDir": browser_profile_dir,
        "launcherBrowserLaunchPid": launcher_browser_launch_pid,
        "launcherBrowserWindowPid": launcher_browser_window_pid,
        "launcherBrowserWindowAlive": launcher_browser_window_alive,
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


def _creation_flag_names(*, detach: bool = False) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    names = ["CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"]
    if detach:
        names.insert(0, "DETACHED_PROCESS")
    return tuple(names)


def _creation_flags(*, detach: bool = False) -> int:
    flags = 0
    for name in _creation_flag_names(detach=detach):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _launcher_action_detached_process() -> bool:
    # Runtime Manager launcher actions stay waitable; console suppression comes
    # from the Python no-console adapter instead of DETACHED_PROCESS.
    return False


def _launcher_action_launch_api() -> str:
    if os.name == "nt":
        return "python_no_console_waitable_popen"
    return "waitable_popen"


def _python_launcher_executable() -> str:
    raw = str(os.environ.get("VIBELUTION_PYTHON_EXE") or sys.executable or "").strip()
    if os.name != "nt" or not raw:
        return raw or sys.executable
    candidate = Path(raw)
    if candidate.name.lower() == "pythonw.exe":
        return str(candidate)
    sibling = candidate.with_name("pythonw.exe")
    if sibling.exists():
        return str(sibling)
    return raw


def _read_capture_file(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return raw.decode(encoding, errors="replace")


def _launcher_command_args(action: str, *, no_browser: bool = False) -> list[str]:
    args = [
        _python_launcher_executable(),
        str(PYTHON_LAUNCHER_SCRIPT_PATH),
        "--action",
        str(action),
    ]
    if no_browser:
        args.append("--no-browser")
    return args


def _run_waitable_launcher_process(
    args: list[str],
    *,
    env: dict[str, str],
    stdout_handle: Any,
    stderr_handle: Any,
    action: str,
    no_browser: bool,
    started_at: float,
    cancel_check: Callable[[], bool] | None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=_creation_flags(detach=_launcher_action_detached_process()),
        startupinfo=_hidden_startup_info(),
        env=env,
    )
    if cancel_check is None:
        return_code = process.wait()
        return subprocess.CompletedProcess(args=args, returncode=int(return_code or 0))

    cancelled = False
    while process.poll() is None:
        if cancel_check():
            cancelled = True
            _record_launcher_action_event(
                "launcher.action.cancel_requested",
                action=action,
                no_browser=no_browser,
                env=env,
                duration_ms=(time.monotonic() - started_at) * 1000,
            )
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            break
        time.sleep(0.2)
    return_code = process.poll()
    if cancelled:
        return_code = LAUNCHER_ACTION_CANCELLED_RETURN_CODE
    return subprocess.CompletedProcess(args=args, returncode=int(return_code or 0))


def run_launcher_action(
    action: str,
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    args = _launcher_command_args(action, no_browser=no_browser)
    env = os.environ.copy()
    env["VIBELUTION_PORT"] = str(configured_backend_port())
    env[INTERNAL_LAUNCHER_ENV] = INTERNAL_LAUNCHER_VALUE
    env["VIBELUTION_PROTECTED_PROCESS_IDS"] = ";".join(
        str(pid)
        for pid in (os.getpid(), os.getppid())
        if int(pid or 0) > 0
    )
    _record_launcher_action_event(
        "launcher.action.requested",
        action=action,
        no_browser=no_browser,
        env=env,
    )
    started_at = time.monotonic()
    stdout_fd, stdout_path = tempfile.mkstemp(prefix="vibelution-launcher-stdout-", suffix=".log")
    stderr_fd, stderr_path = tempfile.mkstemp(prefix="vibelution-launcher-stderr-", suffix=".log")
    try:
        with os.fdopen(stdout_fd, "w+b") as stdout_handle, os.fdopen(stderr_fd, "w+b") as stderr_handle:
            try:
                result = _run_waitable_launcher_process(
                    args,
                    env=env,
                    stdout_handle=stdout_handle,
                    stderr_handle=stderr_handle,
                    action=action,
                    no_browser=no_browser,
                    started_at=started_at,
                    cancel_check=cancel_check,
                )
            except Exception as exc:
                _record_launcher_action_event(
                    "launcher.action.failed",
                    action=action,
                    no_browser=no_browser,
                    env=env,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
                raise
        completed = subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_read_capture_file(stdout_path),
            stderr=_read_capture_file(stderr_path),
        )
        _record_launcher_action_event(
            "launcher.action.completed",
            action=action,
            no_browser=no_browser,
            env=env,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=(time.monotonic() - started_at) * 1000,
        )
        return completed
    finally:
        for capture_path in (stdout_path, stderr_path):
            try:
                os.remove(capture_path)
            except OSError:
                pass


def _record_launcher_action_event(
    event_type: str,
    *,
    action: str,
    no_browser: bool,
    env: dict[str, str],
    return_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    duration_ms: float | None = None,
    error_type: str = "",
    message: str = "",
) -> None:
    internal_action = str(action or "").startswith("internal-")
    payload: dict[str, Any] = {
        "action": str(action or ""),
        "adapter": "python",
        "noBrowser": bool(no_browser),
        "internalAction": internal_action,
        "internalLauncherEnvName": INTERNAL_LAUNCHER_ENV,
        "internalLauncherEnvSet": str(env.get(INTERNAL_LAUNCHER_ENV) or "") == INTERNAL_LAUNCHER_VALUE,
        "protectedProcessIdsSet": bool(str(env.get("VIBELUTION_PROTECTED_PROCESS_IDS") or "").strip()),
        "portSet": bool(str(env.get("VIBELUTION_PORT") or "").strip()),
        "consoleWindowSuppressed": os.name == "nt",
        "creationFlagNames": list(_creation_flag_names(detach=_launcher_action_detached_process())),
        "launcherLaunchApi": _launcher_action_launch_api(),
        "hiddenStartupInfo": os.name == "nt" and hasattr(subprocess, "STARTUPINFO"),
    }
    if return_code is not None:
        payload["returnCode"] = int(return_code)
        payload["ok"] = int(return_code) == 0
    if duration_ms is not None:
        payload["durationMs"] = round(max(0.0, float(duration_ms)), 1)
    if stdout:
        payload["stdoutTail"] = truncate_event_text(stdout[-800:], limit=800)
    if stderr:
        payload["stderrTail"] = truncate_event_text(stderr[-800:], limit=800)
    if error_type:
        payload["errorType"] = truncate_event_text(error_type, limit=120)
    if message:
        payload["message"] = truncate_event_text(message, limit=400)
    try:
        append_runtime_manager_file_event(event_type, payload, suppress_io_errors=True)
    except Exception:
        pass


def open_workbench(
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-start", no_browser=no_browser, cancel_check=cancel_check)


def focus_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-focus", no_browser=False)


def close_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-stop")


def restart_workbench(
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = run_launcher_action("internal-restart", no_browser=no_browser, cancel_check=cancel_check)
    return result
