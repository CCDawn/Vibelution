"""Low-level workbench lifecycle helpers used by the runtime manager."""

from __future__ import annotations

import contextlib
import json
from core.logging import debug as _debug_logger
import locale
import os
import re
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
from uuid import uuid4

from config.workbench import configured_backend_port

from .constants import (
    DEFAULT_HOST,
    DEFAULT_URL,
    LAUNCHER_SCRIPT_PATH as LAUNCHER_SCRIPT_PATH,
    LAUNCHER_STATE_PATH,
    PROJECT_ROOT,
    PYTHON_LAUNCHER_SCRIPT_PATH,
)
from .process_inventory import managed_browser_process_payload, repo_runtime_process_for_pid
from .scene_logging import (
    append_runtime_manager_file_event,
    record_runtime_manager_scene_event,
    runtime_manager_event_phase,
    truncate_event_text,
)
from .window_provider_state import window_provider_projection, with_window_provider_projection

INTERNAL_LAUNCHER_ENV = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
INTERNAL_LAUNCHER_VALUE = "1"
ALLOW_DIRTY_LAUNCH_ENV = "VIBELUTION_ALLOW_DIRTY_LAUNCH"
ALLOW_DIRTY_LAUNCH_VALUE = "1"
LAUNCHER_ACTION_CANCELLED_RETURN_CODE = 130
_PACKAGED_ELECTRON_ENTRY = Path("dist") / "desktop" / "win-unpacked" / "Vibelution.exe"
_ELECTRON_SESSION_BOOTSTRAP_TIMEOUT_SECONDS = 20.0
_ELECTRON_WORKBENCH_OPEN_TIMEOUT_SECONDS = 30.0
_ELECTRON_DESKTOP_ACTION_ACK_TIMEOUT_SECONDS = 8.0
_ELECTRON_SESSION_PROCESS_RE = re.compile(r"-(\d+)-[a-z0-9]+$", re.IGNORECASE)


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


_WORKBENCH_TITLE_MARKERS = ("Vibelution", "工作台", "Workbench")
_WM_CLOSE = 0x0010
_SW_RESTORE = 9
_SW_SHOW = 5


def _browser_window_title_is_workbench(title: object) -> bool:
    text = str(title or "")
    return any(marker in text for marker in _WORKBENCH_TITLE_MARKERS)


def _score_browser_window(item: dict[str, int | bool | str]) -> int:
    """Rank managed Edge --app frames. Titled workbench always beats blank shells."""

    title = str(item.get("title") or "")
    score = 0
    if _browser_window_title_is_workbench(title):
        score += 10_000
    elif title.strip():
        score += 500
    # Untitled large black frames must lose to a small titled workbench window.
    if bool(item.get("visible")) and not bool(item.get("iconic")):
        score += 1_000
    elif bool(item.get("visible")):
        score += 400
    elif bool(item.get("iconic")):
        score += 200
    width = max(0, int(item.get("width") or 0))
    height = max(0, int(item.get("height") or 0))
    area = width * height
    if _browser_window_title_is_workbench(title):
        # Mild size preference among real workbench titles only.
        score += min(area // 40_000, 80)
        if width >= 640 and height >= 480:
            score += 40
    else:
        # Penalize blank shells so they are closed when a titled peer exists.
        score -= 2_000
        if not title.strip():
            score -= 500
    return score


def _iter_browser_candidate_windows(pid: int) -> list[dict[str, int | bool | str]]:
    """Return candidate top-level windows owned by ``pid`` (Windows only)."""

    if os.name != "nt" or int(pid or 0) <= 0:
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []

    user32 = ctypes.windll.user32
    found: list[dict[str, int | bool | str]] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):  # type: ignore[no-untyped-def]
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if int(owner_pid.value) != int(pid):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right) - int(rect.left)
        height = int(rect.bottom) - int(rect.top)
        visible = bool(user32.IsWindowVisible(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        # Windows reports a compact off-screen restore rectangle for minimized
        # Edge app windows. Keep those candidates so liveness can distinguish a
        # user-minimized workbench from a genuinely closed window.
        if (width < 160 or height < 120) and not (visible and iconic):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = str(buf.value or "")
        found.append(
            {
                "hwnd": int(hwnd),
                "visible": visible,
                "iconic": iconic,
                "width": width,
                "height": height,
                "title": title,
            }
        )
        return True

    try:
        user32.EnumWindows(callback, 0)
    except Exception:
        return []
    return found


def _close_browser_window_hwnd(hwnd: int) -> bool:
    """Post WM_CLOSE to a top-level Edge app frame without killing the process tree."""

    if os.name != "nt" or int(hwnd or 0) <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False
    user32 = ctypes.windll.user32
    try:
        return bool(
            user32.PostMessageW(
                wintypes.HWND(int(hwnd)),
                _WM_CLOSE,
                0,
                0,
            )
        )
    except Exception:
        return False


def _focus_browser_window_hwnd(hwnd: int) -> bool:
    if os.name != "nt" or int(hwnd or 0) <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False
    user32 = ctypes.windll.user32
    handle = wintypes.HWND(int(hwnd))
    try:
        user32.ShowWindow(handle, _SW_RESTORE)
        user32.ShowWindow(handle, _SW_SHOW)
        user32.SetForegroundWindow(handle)
        return bool(user32.IsWindowVisible(handle))
    except Exception:
        return False


def _converge_browser_windows(pid: int, *, focus_kept: bool = True) -> dict[str, Any]:
    """Keep the single best workbench HWND for ``pid``; close orphan Edge --app frames.

    Edge --app under one profile process can leave a large untitled black shell plus a
    small titled ``Vibelution 工作台`` window. Process-level MainWindowHandle checks
    cannot see that dual-window state; HWND enumeration + scoring is required.
    """

    if os.name != "nt" or int(pid or 0) <= 0:
        return {
            "pid": int(pid or 0),
            "keptHwnd": 0,
            "keptTitle": "",
            "closedHwnds": [],
            "candidateCount": 0,
            "changed": False,
        }

    candidates = list(_iter_browser_candidate_windows(int(pid)))
    if not candidates:
        return {
            "pid": int(pid),
            "keptHwnd": 0,
            "keptTitle": "",
            "closedHwnds": [],
            "candidateCount": 0,
            "changed": False,
        }

    ranked = sorted(
        candidates,
        key=lambda item: (
            _score_browser_window(item),
            int(item.get("width") or 0) * int(item.get("height") or 0),
            int(item.get("hwnd") or 0),
        ),
        reverse=True,
    )
    winner = ranked[0]
    kept_hwnd = int(winner.get("hwnd") or 0)
    kept_title = str(winner.get("title") or "")
    closed: list[int] = []
    for item in ranked[1:]:
        hwnd = int(item.get("hwnd") or 0)
        if hwnd <= 0 or hwnd == kept_hwnd:
            continue
        extra_title = str(item.get("title") or "")
        # Never close Edge DevTools / explicit debug surfaces under the profile.
        if any(marker in extra_title for marker in ("DevTools", "Developer Tools")):
            continue
        # Managed --app profile: blank shells and duplicate workbench frames are orphans.
        if _close_browser_window_hwnd(hwnd):
            closed.append(hwnd)

    if focus_kept and kept_hwnd > 0:
        if not (bool(winner.get("visible")) and not bool(winner.get("iconic"))):
            _focus_browser_window_hwnd(kept_hwnd)
        elif closed:
            # Re-assert foreground on the real workbench after closing a blank shell.
            _focus_browser_window_hwnd(kept_hwnd)

    return {
        "pid": int(pid),
        "keptHwnd": kept_hwnd,
        "keptTitle": kept_title,
        "closedHwnds": closed,
        "candidateCount": len(candidates),
        "changed": bool(closed),
    }


def _visible_top_level_window_handles(pid: int) -> list[int]:
    """Return visible top-level HWND values owned by ``pid`` (Windows only)."""

    return [
        int(item["hwnd"])
        for item in _iter_browser_candidate_windows(pid)
        if bool(item.get("visible")) and not bool(item.get("iconic"))
    ]


def _minimized_workbench_window_handles(pid: int) -> list[int]:
    """Return minimized, still-live managed workbench HWND values."""

    return [
        int(item["hwnd"])
        for item in _iter_browser_candidate_windows(pid)
        if bool(item.get("visible"))
        and bool(item.get("iconic"))
        and _browser_window_title_is_workbench(item.get("title"))
    ]


def _restore_hidden_browser_windows(pid: int) -> list[int]:
    """Show/restore the single best managed Edge app window when none are visible."""

    if os.name != "nt" or int(pid or 0) <= 0:
        return []
    candidates = list(_iter_browser_candidate_windows(int(pid)))
    if not candidates:
        return []

    visible = [
        item
        for item in candidates
        if bool(item.get("visible")) and not bool(item.get("iconic"))
    ]
    if visible:
        # Already visible: still collapse dual frames to one workbench HWND.
        result = _converge_browser_windows(int(pid), focus_kept=True)
        kept = int(result.get("keptHwnd") or 0)
        return [kept] if kept > 0 else [int(item["hwnd"]) for item in visible]

    ranked = sorted(candidates, key=_score_browser_window, reverse=True)
    for item in ranked:
        title = str(item.get("title") or "")
        # Prefer titled workbench windows; still accept large untitled app frames.
        if title and not _browser_window_title_is_workbench(title):
            continue
        hwnd = int(item.get("hwnd") or 0)
        if hwnd <= 0:
            continue
        if _focus_browser_window_hwnd(hwnd):
            # Close any remaining peers after the winner is shown.
            _converge_browser_windows(int(pid), focus_kept=True)
            return [hwnd]
    return []


def _is_browser_window_alive(pid: int) -> bool:
    """True only when the managed browser process still has a real user window.

    Chromium/Edge often leaves a process tree after the app window is closed, or
    keeps a hidden window after a bad ``--window-size``. Process-only checks then
    report Workbench as open while the user sees nothing.

    When multiple top-level frames exist under the same Edge process (blank shell +
    titled workbench), converge to a single kept HWND before reporting alive.
    """

    if not _is_process_alive(pid):
        return False
    if os.name != "nt":
        return True
    handles = _visible_top_level_window_handles(int(pid))
    if handles:
        _converge_browser_windows(int(pid), focus_kept=False)
        return bool(_visible_top_level_window_handles(int(pid)) or handles)
    if _minimized_workbench_window_handles(int(pid)):
        # Minimized is a valid user-controlled state. Do not restore or focus
        # the window from the runtime-manager observation loop.
        return True
    # Self-heal: restore the best hidden managed app window, then converge.
    return bool(_restore_hidden_browser_windows(int(pid)))


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
    payload.update(window_provider_projection(payload))
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


def _positive_tcp_port(value: object) -> int:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return port if 0 < port < 65536 else 0


def _workbench_url_for_port(port: int, *, host: str = "", source_url: str = "") -> str:
    resolved_host = str(host or "").strip()
    if not resolved_host:
        try:
            parsed = urllib.parse.urlparse(str(source_url or ""))
            resolved_host = str(parsed.hostname or "").strip()
        except ValueError:
            resolved_host = ""
    if not resolved_host:
        resolved_host = DEFAULT_HOST
    return f"http://{resolved_host}:{int(port)}"


def _reconcile_workbench_endpoint(
    url: str,
    port: int,
    launcher_state: dict[str, Any],
) -> tuple[str, int]:
    """Prefer a live backendPort / ports.json over a stale state.json url."""

    current_port = _positive_tcp_port(port) or _port_for_url(url)
    if current_port > 0 and _port_is_listening_socket(current_port):
        return (str(url or "").strip() or _workbench_url_for_port(current_port), current_port)

    candidates: list[int] = []
    for key in ("backendPort", "port", "preferredBackendPort"):
        candidate = _positive_tcp_port(launcher_state.get(key))
        if candidate > 0 and candidate not in candidates:
            candidates.append(candidate)
    configured = _positive_tcp_port(configured_backend_port())
    if configured > 0 and configured not in candidates:
        candidates.append(configured)

    host = str(launcher_state.get("host") or "").strip()
    for candidate in candidates:
        if candidate == current_port:
            continue
        if _port_is_listening_socket(candidate):
            return (
                _workbench_url_for_port(candidate, host=host, source_url=url),
                candidate,
            )
    return (str(url or "").strip() or DEFAULT_URL, current_port)


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
            # Waitable probe: CREATE_NO_WINDOW only (never with DETACHED_PROCESS).
            creationflags=_creation_flags(detach=False),
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
        item = repo_runtime_process_for_pid(pid, project_root=PROJECT_ROOT)
        if item is not None and item.kind in {"managed_workbench_backend", "unmanaged_workbench"}:
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
        for item in candidates:
            pid = int(item.get("pid") or 0)
            if pid > 0 and _is_browser_window_alive(pid):
                return pid
    return 0


def _with_active_electron_window_projection(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation)
    try:
        from core.launcher.desktop_session_store import latest_active_window_provider_projection

        projection = latest_active_window_provider_projection(workspace_root=str(PROJECT_ROOT))
    except (OSError, TypeError, ValueError):
        projection = {}
    if isinstance(projection, dict) and projection and _electron_session_process_is_live(projection):
        payload.update(projection)
    return with_window_provider_projection(payload)


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
    launcher_browser_launch_pid = int(launcher_state.get("launcherBrowserLaunchPid") or 0)
    launcher_browser_window_pid = int(launcher_state.get("launcherBrowserWindowPid") or 0)
    window_projection = window_provider_projection(
        {
            **launcher_state,
            "browserWindowPid": browser_window_pid,
            "browserProfileDir": browser_profile_dir,
        }
    )
    browser_profile_dir = str(window_projection.get("windowProfileDir") or browser_profile_dir)
    browser_managed = bool(window_projection.get("browserManaged"))

    port = _port_for_url(url)
    # state.json url can lag behind a relocated listener (e.g. :8000 url vs :8002 ports.json).
    url, port = _reconcile_workbench_endpoint(url, port, launcher_state)
    launcher_browser_window_alive = _is_browser_window_alive(launcher_browser_window_pid)
    if (
        session_role == "launcher_control_surface"
        and state_backend_pid <= 0
        and backend_launch_pid <= 0
        and browser_launch_pid <= 0
        and browser_window_pid <= 0
        and not _port_is_listening_socket(port)
    ):
        return _with_active_electron_window_projection({
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
        })

    state_backend_alive = _is_process_alive(state_backend_pid)
    browser_window_converge: dict[str, Any] = {
        "pid": int(browser_window_pid or 0),
        "keptHwnd": 0,
        "keptTitle": "",
        "closedHwnds": [],
        "candidateCount": 0,
        "changed": False,
    }
    browser_window_alive = _is_browser_window_alive(browser_window_pid)
    if (
        browser_window_alive
        and browser_window_pid > 0
        and os.name == "nt"
        and bool(_visible_top_level_window_handles(browser_window_pid))
    ):
        # observe re-converges so dual Edge frames are closed even when the
        # initial alive check used focus_kept=False. Only demote alive when we
        # actually saw top-level frames and none remain after close.
        browser_window_converge = _converge_browser_windows(browser_window_pid, focus_kept=True)
        if int(browser_window_converge.get("candidateCount") or 0) > 0:
            browser_window_alive = bool(
                int(browser_window_converge.get("keptHwnd") or 0) > 0
                or bool(_visible_top_level_window_handles(browser_window_pid))
            )
    if (
        session_role == "workbench"
        and not recover_browser_window
        and not state_backend_alive
        and not browser_window_alive
        and not _port_is_listening_socket(port)
    ):
        return _with_active_electron_window_projection({
            "launcherStatePresent": bool(launcher_state),
            "sessionId": str(launcher_state.get("sessionId") or "").strip(),
            "sessionRole": "launcher_control_surface" if launcher_browser_window_alive else session_role,
            "sourceSessionRole": session_role,
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
            "observationFastPath": "stale_workbench_pids_closed",
        })
    health_probe_url = url if launcher_state else DEFAULT_URL
    healthy = _is_backend_healthy(health_probe_url)
    port_owner_pid = _listening_pid_for_port(port)
    port_listening = bool(port_owner_pid) or _port_is_listening_socket(port)
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
            if os.name == "nt":
                browser_window_converge = _converge_browser_windows(browser_window_pid, focus_kept=True)
                if int(browser_window_converge.get("candidateCount") or 0) > 0:
                    browser_window_alive = bool(
                        int(browser_window_converge.get("keptHwnd") or 0) > 0
                        or bool(_visible_top_level_window_handles(browser_window_pid))
                    )
    launcher_browser_window_alive = _is_browser_window_alive(launcher_browser_window_pid)
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

    return _with_active_electron_window_projection({
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
        "browserWindowConverge": browser_window_converge,
        "browserWindowKeptHwnd": int(browser_window_converge.get("keptHwnd") or 0),
        "browserWindowClosedCount": len(browser_window_converge.get("closedHwnds") or []),
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
    })


def _creation_flag_names(*, detach: bool = False) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    # MSDN: CREATE_NO_WINDOW is ignored when combined with DETACHED_PROCESS.
    # Waitable console tools must use CREATE_NO_WINDOW alone.
    if detach:
        return ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP")
    return ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW")


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


def _explicit_workbench_port_env_value() -> str:
    """Return a valid explicit VIBELUTION_PORT override from the parent env, else ""."""
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return ""
    return raw_value if 0 < port < 65536 else ""


def _latest_active_electron_desktop_session() -> dict[str, Any]:
    """Return live Electron ownership evidence for this workspace, if present."""

    try:
        from core.launcher.desktop_session_store import latest_active_desktop_session

        session = latest_active_desktop_session(
            provider="electron",
            workspace_root=str(PROJECT_ROOT),
        )
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(session, dict) or not _electron_session_process_is_live(session):
        return {}
    return session


def _electron_session_process_is_live(session: dict[str, Any]) -> bool:
    """Reject canonical Electron leases whose owning process has already exited.

    Older/non-canonical session identifiers remain lease-compatible; only the
    canonical id embeds an authoritative process id.
    """

    session_id = str(session.get("desktopSessionId") or "").strip()
    match = _ELECTRON_SESSION_PROCESS_RE.search(session_id)
    if match is None:
        return True
    return _is_process_alive(int(match.group(1)))


def _instance_short_name_for_checkout(checkout: Path | str) -> str:
    try:
        from core.infrastructure.branch_workspace import list_branch_instances
        from core.infrastructure.instance_display_name import MAIN_SHORT_NAME, current_instance_display

        payload = list_branch_instances(checkout)
        return current_instance_display(payload.get("items") or []).get("shortName") or MAIN_SHORT_NAME
    except Exception:
        from core.infrastructure.instance_display_name import MAIN_SHORT_NAME

        return MAIN_SHORT_NAME


def _packaged_electron_desktop_executable() -> Path | None:
    """Return the supported packaged desktop entry when this host can run it."""

    if os.name != "nt":
        return None
    candidate = PROJECT_ROOT / _PACKAGED_ELECTRON_ENTRY
    return candidate if candidate.is_file() else None


def _electron_bootstrap_python_executable() -> str:
    """Prefer the project interpreter so Electron can bootstrap Launcher consistently."""

    candidate = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.is_file():
        return str(candidate)
    return _python_launcher_executable()


def _launch_packaged_electron_desktop(*, executable: Path, env: dict[str, str]) -> subprocess.Popen[Any]:
    """Launch the visible Electron package directly, never through a console shell."""

    desktop_env = dict(env)
    desktop_env["VIBELUTION_WORKSPACE_ROOT"] = str(PROJECT_ROOT)
    desktop_env["VIBELUTION_PYTHON_PATH"] = _electron_bootstrap_python_executable()
    desktop_env["VIBELUTION_INSTANCE_SHORT_NAME"] = _instance_short_name_for_checkout(PROJECT_ROOT)
    return subprocess.Popen(
        [str(executable), "--workspace", str(PROJECT_ROOT), "--open-workbench"],
        cwd=str(PROJECT_ROOT),
        env=desktop_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def _await_electron_desktop_session(
    process: subprocess.Popen[Any],
    *,
    timeout_seconds: float = _ELECTRON_SESSION_BOOTSTRAP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait for the newly started package to register its scoped desktop session."""

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while time.monotonic() < deadline:
        session = _latest_active_electron_desktop_session()
        if session:
            return session
        exit_code = process.poll()
        if exit_code is not None and int(exit_code) != 0:
            raise RuntimeError(
                f"Packaged Electron exited before registering a desktop session (exit code {exit_code})."
            )
        time.sleep(0.2)
    if process.poll() == 0:
        raise RuntimeError(
            "Packaged Electron handed off to an existing primary instance, but no desktop session "
            "was registered before the startup deadline."
        )
    raise RuntimeError("Packaged Electron did not register a desktop session before the startup deadline.")


def _await_electron_workbench_open(
    process: subprocess.Popen[Any],
    *,
    desktop_session_id: str,
    timeout_seconds: float = _ELECTRON_WORKBENCH_OPEN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait for the targeted desktop action to produce a real Electron Workbench window."""

    from core.launcher.desktop_session_store import get_desktop_session

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while time.monotonic() < deadline:
        session = get_desktop_session(desktop_session_id)
        windows = session.get("windows") if isinstance(session.get("windows"), dict) else {}
        workbench = windows.get("workbench") if isinstance(windows.get("workbench"), dict) else {}
        if bool(workbench.get("open", False)):
            return session
        exit_code = process.poll()
        if exit_code is not None and int(exit_code) != 0:
            raise RuntimeError(
                f"Packaged Electron exited before opening the Workbench window (exit code {exit_code})."
            )
        time.sleep(0.2)
    if process.poll() == 0:
        raise RuntimeError(
            "Packaged Electron handed off to an existing primary instance, but the Workbench window "
            "did not open before the startup deadline."
        )
    raise RuntimeError("Packaged Electron did not open the Workbench window before the startup deadline.")


def _terminate_packaged_electron_after_failed_bootstrap(process: subprocess.Popen[Any]) -> None:
    """Best-effort cleanup for the exact Electron process started by this action."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=4.0)
    except (OSError, subprocess.TimeoutExpired):
        with contextlib.suppress(OSError):
            process.kill()


def _startup_elapsed_ms(started_at: float) -> float:
    return round(max(0.0, (time.monotonic() - started_at) * 1000.0), 1)


def _bootstrap_packaged_electron_workbench(
    *,
    env: dict[str, str],
    action: str,
    no_browser: bool,
    startup_telemetry: dict[str, Any],
) -> dict[str, Any]:
    """Start the package and route the first Workbench open through desktop actions."""

    executable = _packaged_electron_desktop_executable()
    if executable is None:
        return {}
    timings = startup_telemetry.setdefault("timingsMs", {})
    total_started = time.monotonic()
    current_stage = "electron_process_spawn"
    current_timing_key = "electronProcessSpawnMs"
    stage_started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    try:
        startup_telemetry["failureStage"] = current_stage
        process = _launch_packaged_electron_desktop(executable=executable, env=env)
        timings[current_timing_key] = _startup_elapsed_ms(stage_started)

        current_stage = "desktop_session_registration"
        current_timing_key = "desktopSessionRegistrationMs"
        startup_telemetry["failureStage"] = current_stage
        stage_started = time.monotonic()
        session = _await_electron_desktop_session(process)
        timings[current_timing_key] = _startup_elapsed_ms(stage_started)
        startup_telemetry["desktopSessionRegistered"] = True

        current_stage = "desktop_action_submit"
        current_timing_key = "desktopActionSubmitMs"
        startup_telemetry["failureStage"] = current_stage
        stage_started = time.monotonic()
        intent = _submit_electron_window_action(
            action="open_workbench",
            reason=f"{action}:electron_first_start",
            session=session,
        )
        if str(intent.get("status") or "") != "accepted":
            raise RuntimeError(
                "Electron first-start Workbench action was not accepted by the Launcher: "
                f"{str(intent.get('rejectionReason') or intent.get('status') or 'unknown')}"
            )
        timings[current_timing_key] = _startup_elapsed_ms(stage_started)

        current_stage = "workbench_window_open"
        current_timing_key = "workbenchWindowOpenMs"
        startup_telemetry["failureStage"] = current_stage
        stage_started = time.monotonic()
        opened_session = _await_electron_workbench_open(
            process,
            desktop_session_id=str(session.get("desktopSessionId") or ""),
        )
        timings[current_timing_key] = _startup_elapsed_ms(stage_started)
        timings["electronFirstStartTotalMs"] = _startup_elapsed_ms(total_started)
        startup_telemetry["workbenchOpen"] = True
        startup_telemetry["failureStage"] = ""
        return {
            "electronLaunchPid": int(process.pid),
            "desktopSessionId": str(opened_session.get("desktopSessionId") or session.get("desktopSessionId") or ""),
            "desktopSessionRevision": int(opened_session.get("revision") or 0),
        }
    except Exception:
        timings.setdefault(current_timing_key, _startup_elapsed_ms(stage_started))
        timings["electronFirstStartTotalMs"] = _startup_elapsed_ms(total_started)
        startup_telemetry["failureStage"] = current_stage
        if process is not None:
            _terminate_packaged_electron_after_failed_bootstrap(process)
        raise


def _electron_window_action_for_launcher_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    if normalized in {"internal-start", "internal-restart", "start", "restart"}:
        return "open_workbench"
    if normalized in {"internal-focus", "focus"}:
        return "focus_workbench"
    return ""


def _can_reuse_backend_for_electron_window_open(*, action: str, session: dict[str, Any]) -> bool:
    if not session or str(action or "").strip().lower() not in {"internal-start", "start"}:
        return False
    try:
        observation = observe_workbench(
            recover_browser_window=False,
            recover_browser_window_for_backend_observed=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        observation.get("backendHealthy")
        and observation.get("backendObserved")
        and not observation.get("backendPortConflict")
    )


def _electron_desktop_action_payload(*, action: str, session: dict[str, Any]) -> dict[str, Any]:
    """Build Electron desktop-action payload, attaching live Workbench URL when known."""

    payload: dict[str, Any] = {
        "desktopSessionId": str(session.get("desktopSessionId") or ""),
    }
    if str(action or "").strip().lower() not in {"open_workbench"}:
        return payload

    try:
        observation = observe_workbench(
            recover_browser_window=False,
            recover_browser_window_for_backend_observed=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        # Never invent :8000 when observation fails; Electron falls back to bootstrap/env.
        return payload
    if not isinstance(observation, dict):
        return payload

    url = str(observation.get("url") or "").strip()
    port = _positive_tcp_port(observation.get("backendPort")) or _port_for_url(url)
    url_port = _port_for_url(url) or port
    listening = bool(observation.get("backendPortListening"))
    if url_port > 0 and url_port != port:
        # Observation url/port disagree — trust listening probes over the stale url.
        listening = False
    if not listening and url_port > 0:
        listening = _port_is_listening_socket(url_port)
        if listening:
            port = url_port
    if not listening:
        # Prefer live ports.json / configured port over a dead state.json url (:8000).
        for candidate in (port, _positive_tcp_port(configured_backend_port())):
            if candidate <= 0 or candidate == url_port:
                continue
            if _port_is_listening_socket(candidate):
                port = candidate
                url = _workbench_url_for_port(candidate, source_url=url)
                listening = True
                break
        else:
            # Do not hand Electron a URL whose port is not listening.
            url = ""
    live_backend = bool(
        observation.get("backendObserved")
        or listening
        or observation.get("backendHealthy")
    )
    if not url and live_backend and listening and 0 < port < 65536:
        url = _workbench_url_for_port(port)
    if url and listening:
        payload["workbenchUrl"] = url
    if 0 < port < 65536 and (listening or live_backend):
        payload["backendPort"] = port
    return payload


def _submit_electron_window_action(*, action: str, reason: str, session: dict[str, Any]) -> dict[str, Any]:
    """Submit a Python-owned Desktop Action for the active Electron shell."""

    from core.launcher.lifecycle_intent_store import submit_lifecycle_intent

    return submit_lifecycle_intent(
        {
            "action": action,
            "reason": reason,
            "idempotencyKey": f"runtime-manager-electron-window:{action}:{uuid4().hex}",
        },
        actor_context={
            "actorType": "runtime_manager",
            "actorId": str(os.getpid()),
            "sourceWorktree": str(PROJECT_ROOT),
            "sourceTaskId": str(session.get("desktopSessionId") or ""),
        },
        active_work_runs=[],
        desktop_action_payload=_electron_desktop_action_payload(action=action, session=session),
    )


def _await_electron_window_action_confirmed(
    *,
    intent: dict[str, Any],
    session: dict[str, Any],
    action: str,
    timeout_seconds: float = _ELECTRON_DESKTOP_ACTION_ACK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait for both the action ack and a newer live desktop-session snapshot."""

    from core.launcher.desktop_session_store import get_desktop_session
    from core.launcher.lifecycle_intent_store import get_lifecycle_intent

    intent_id = str(intent.get("intentId") or "").strip()
    desktop_session_id = str(session.get("desktopSessionId") or "").strip()
    baseline_revision = int(session.get("revision") or 0)
    if not intent_id or not desktop_session_id:
        raise RuntimeError(f"Electron window action {action} is missing confirmation identity.")
    deadline = time.monotonic() + max(0.05, float(timeout_seconds))
    while time.monotonic() < deadline:
        current_intent = get_lifecycle_intent(intent_id)
        status = str(current_intent.get("status") or "").strip().lower()
        if status in {"failed", "rejected", "cancelled", "expired"}:
            detail = str(current_intent.get("failureMessage") or current_intent.get("rejectionReason") or status)
            raise RuntimeError(f"Electron window action {action} failed: {detail}")
        if status == "succeeded":
            current_session = get_desktop_session(desktop_session_id)
            windows = current_session.get("windows") if isinstance(current_session.get("windows"), dict) else {}
            workbench = windows.get("workbench") if isinstance(windows.get("workbench"), dict) else {}
            if (
                int(current_session.get("revision") or 0) > baseline_revision
                and bool(workbench.get("open"))
                and _electron_session_process_is_live(current_session)
            ):
                return current_session
        time.sleep(0.05)
    raise RuntimeError(f"Electron window action {action} was not acknowledged before the bounded timeout.")


def _run_captured_launcher_process(
    args: list[str],
    *,
    env: dict[str, str],
    action: str,
    no_browser: bool,
    started_at: float,
    cancel_check: Callable[[], bool] | None,
) -> subprocess.CompletedProcess[str]:
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


def run_launcher_action(
    action: str,
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    allow_dirty_launch: bool = False,
) -> subprocess.CompletedProcess[str]:
    startup_trace_id = f"launcher-startup-{uuid4().hex}"
    startup_telemetry: dict[str, Any] = {
        "startupTraceId": startup_trace_id,
        "outcome": "failed",
        "failureStage": "launcher_control_plane_backend_ready",
        "timingsMs": {},
        "electronFirstStart": False,
        "backendReused": False,
        "desktopSessionRegistered": False,
        "workbenchOpen": False,
    }
    completed: subprocess.CompletedProcess[str] | None = None
    caught_error: Exception | None = None
    started_at = time.monotonic()
    electron_session = _latest_active_electron_desktop_session()
    electron_window_action = _electron_window_action_for_launcher_action(action)
    packaged_electron = _packaged_electron_desktop_executable()
    bootstrap_packaged_electron = bool(
        not no_browser and not electron_session and electron_window_action == "open_workbench" and packaged_electron is not None
    )
    effective_no_browser = bool(no_browser or electron_session or bootstrap_packaged_electron)
    reuse_electron_backend = _can_reuse_backend_for_electron_window_open(
        action=action,
        session=electron_session,
    )
    args = _launcher_command_args(action, no_browser=effective_no_browser)
    env = os.environ.copy()
    env["VIBELUTION_STARTUP_TRACE_ID"] = startup_trace_id
    env["VIBELUTION_PORT"] = _explicit_workbench_port_env_value() or str(configured_backend_port())
    env[INTERNAL_LAUNCHER_ENV] = INTERNAL_LAUNCHER_VALUE
    if allow_dirty_launch:
        # Tray rebuild-and-start intentionally runs with local dirty worktrees.
        env[ALLOW_DIRTY_LAUNCH_ENV] = ALLOW_DIRTY_LAUNCH_VALUE
    else:
        env.pop(ALLOW_DIRTY_LAUNCH_ENV, None)
    env["VIBELUTION_PROTECTED_PROCESS_IDS"] = ";".join(
        str(pid)
        for pid in (os.getpid(), os.getppid())
        if int(pid or 0) > 0
    )
    try:
        _record_launcher_action_event(
            "launcher.action.requested",
            action=action,
            no_browser=effective_no_browser,
            env=env,
        )
        control_plane_started = time.monotonic()
        if reuse_electron_backend:
            completed = subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="backendReady=true; launcherProcessSkipped=true",
                stderr="",
            )
            startup_telemetry["backendReused"] = True
            _record_launcher_action_event(
                "launcher.action.electron_backend_reused",
                action=action,
                no_browser=effective_no_browser,
                env=env,
                stdout=completed.stdout,
            )
        else:
            completed = _run_captured_launcher_process(
                args,
                env=env,
                action=action,
                no_browser=effective_no_browser,
                started_at=started_at,
                cancel_check=cancel_check,
            )
        startup_telemetry["timingsMs"]["launcherControlPlaneBackendReadyMs"] = _startup_elapsed_ms(
            control_plane_started
        )
        if completed.returncode == 0 and electron_window_action:
            if electron_session:
                startup_telemetry["failureStage"] = "desktop_action_submit"
                desktop_action_started = time.monotonic()
                intent = _submit_electron_window_action(
                    action=electron_window_action,
                    reason=f"{action}:electron_window_provider",
                    session=electron_session,
                )
                if str(intent.get("status") or "") != "accepted":
                    raise RuntimeError(
                        "Electron window action was not accepted by the Launcher: "
                        f"{str(intent.get('rejectionReason') or intent.get('status') or 'unknown')}"
                    )
                startup_telemetry["failureStage"] = "desktop_action_confirmation"
                confirmed_session = _await_electron_window_action_confirmed(
                    intent=intent,
                    session=electron_session,
                    action=electron_window_action,
                )
                startup_telemetry["timingsMs"]["desktopActionSubmitMs"] = _startup_elapsed_ms(
                    desktop_action_started
                )
                startup_telemetry["desktopSessionRegistered"] = True
                startup_telemetry["workbenchOpen"] = bool(
                    isinstance(confirmed_session.get("windows"), dict)
                    and isinstance(confirmed_session["windows"].get("workbench"), dict)
                    and confirmed_session["windows"]["workbench"].get("open")
                )
                _record_launcher_action_event(
                    "launcher.action.electron_desktop_action_submitted",
                    action=action,
                    no_browser=effective_no_browser,
                    env=env,
                    stdout=f"desktopAction={electron_window_action}",
                )
            elif bootstrap_packaged_electron:
                startup_telemetry["electronFirstStart"] = True
                bootstrap = _bootstrap_packaged_electron_workbench(
                    env=env,
                    action=action,
                    no_browser=effective_no_browser,
                    startup_telemetry=startup_telemetry,
                )
                _record_launcher_action_event(
                    "launcher.action.electron_first_start_succeeded",
                    action=action,
                    no_browser=effective_no_browser,
                    env=env,
                    stdout=(
                        f"electronLaunchPid={bootstrap['electronLaunchPid']};"
                        f"desktopSessionId={bootstrap['desktopSessionId']}"
                    ),
                )
            elif packaged_electron is None and not no_browser:
                _record_launcher_action_event(
                    "launcher.action.edge_fallback_package_missing",
                    action=action,
                    no_browser=effective_no_browser,
                    env=env,
                    stdout="Electron package unavailable; legacy Edge app window provider selected.",
                )
        if int(completed.returncode or 0) == 0:
            startup_telemetry["outcome"] = "succeeded"
            startup_telemetry["failureStage"] = ""
        else:
            startup_telemetry["failureStage"] = "launcher_control_plane_backend_ready"
        _record_launcher_action_event(
            "launcher.action.completed",
            action=action,
            no_browser=effective_no_browser,
            env=env,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=_startup_elapsed_ms(started_at),
        )
        return completed
    except Exception as exc:
        caught_error = exc
        raise
    finally:
        startup_telemetry["durationMs"] = _startup_elapsed_ms(started_at)
        if caught_error is not None:
            startup_telemetry["outcome"] = "failed"
            startup_telemetry["errorType"] = type(caught_error).__name__
        _record_launcher_action_event(
            "launcher.action.startup_summary",
            action=action,
            no_browser=effective_no_browser,
            env=env,
            duration_ms=startup_telemetry["durationMs"],
            error_type=str(startup_telemetry.get("errorType") or ""),
            startup_trace_id=startup_trace_id,
            outcome=str(startup_telemetry.get("outcome") or "failed"),
            failure_stage=str(startup_telemetry.get("failureStage") or ""),
            timings_ms=startup_telemetry.get("timingsMs"),
            electron_first_start=bool(startup_telemetry.get("electronFirstStart")),
            backend_reused=bool(startup_telemetry.get("backendReused")),
            desktop_session_registered=bool(startup_telemetry.get("desktopSessionRegistered")),
            workbench_open=bool(startup_telemetry.get("workbenchOpen")),
        )
        if completed is not None:
            completed.startup_telemetry = dict(startup_telemetry)


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
    startup_trace_id: str = "",
    outcome: str = "",
    failure_stage: str = "",
    timings_ms: dict[str, Any] | None = None,
    electron_first_start: bool | None = None,
    backend_reused: bool | None = None,
    desktop_session_registered: bool | None = None,
    workbench_open: bool | None = None,
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
    resolved_startup_trace_id = str(startup_trace_id or env.get("VIBELUTION_STARTUP_TRACE_ID") or "").strip()
    if resolved_startup_trace_id:
        payload["startupTraceId"] = truncate_event_text(resolved_startup_trace_id, limit=96)
    if outcome:
        payload["outcome"] = truncate_event_text(outcome, limit=32)
    if failure_stage or event_type == "launcher.action.startup_summary":
        payload["failureStage"] = truncate_event_text(failure_stage, limit=80)
    if isinstance(timings_ms, dict):
        payload["timingsMs"] = {
            truncate_event_text(str(key), limit=80): round(max(0.0, float(value)), 1)
            for key, value in list(timings_ms.items())[:16]
            if isinstance(value, (int, float))
        }
    for key, value in (
        ("electronFirstStart", electron_first_start),
        ("backendReused", backend_reused),
        ("desktopSessionRegistered", desktop_session_registered),
        ("workbenchOpen", workbench_open),
    ):
        if value is not None:
            payload[key] = bool(value)
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
        event_at = append_runtime_manager_file_event(event_type, payload, suppress_io_errors=True)
        record_runtime_manager_scene_event(
            event_type,
            payload,
            phase=runtime_manager_event_phase(event_type),
            occurred_at=event_at,
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record launcher action scene event: {exc}")


def open_workbench(
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    allow_dirty_launch: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run_launcher_action(
        "internal-start",
        no_browser=no_browser,
        cancel_check=cancel_check,
        allow_dirty_launch=allow_dirty_launch,
    )


def focus_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-focus", no_browser=False)


def close_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-stop")


def restart_workbench(
    *,
    no_browser: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    allow_dirty_launch: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = run_launcher_action(
        "internal-restart",
        no_browser=no_browser,
        cancel_check=cancel_check,
        allow_dirty_launch=allow_dirty_launch,
    )
    return result
