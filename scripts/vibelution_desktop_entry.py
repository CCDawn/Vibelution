#!/usr/bin/env python3
"""Native no-console bridge for the Windows desktop Launcher entry."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "launcher"
STATE_PATH = RUNTIME_DIR / "state.json"
PYTHON_BRIDGE_LOG_PATH = RUNTIME_DIR / "desktop-entry-python.log"
LAUNCHER_STDOUT_PATH = RUNTIME_DIR / "launcher-backend.stdout.log"
LAUNCHER_STDERR_PATH = RUNTIME_DIR / "launcher-backend.stderr.log"
LAUNCHER_BROWSER_PROFILE_DIR = RUNTIME_DIR / "launcher-control-profile"
WORKBENCH_BROWSER_PROFILE_DIR = RUNTIME_DIR / "workbench-app-profile"
LAUNCHER_ICON_PATH = PROJECT_ROOT / "assets" / "icons" / "vibelution.ico"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_WORKBENCH_PORT = 8000
DEFAULT_LAUNCHER_CONTROL_PORT = 8765
MANAGED_LAUNCHER_MARKER = "--managed-launcher-control"
SOURCE_SIGNATURE_PATHS = (
    "core/launcher/app.py",
    "core/launcher/developer_mode.py",
    "core/launcher/service.py",
    "core/runtime_manager/__init__.py",
    "core/runtime_manager/constants.py",
    "core/runtime_manager/evolution_store.py",
    "core/runtime_manager/scene_logging.py",
    "core/runtime_manager/state_store.py",
    "core/runtime_manager/work_run_store.py",
    "core/runtime_manager/workbench_controller.py",
    "core/web/control.py",
    "core/version.py",
    "web/package.json",
    "web/package-lock.json",
    "web/vite.config.ts",
    "web/src/api/client.ts",
    "web/src/api/launcher.ts",
    "web/src/api/types.ts",
    "web/src/app/LauncherShell.tsx",
    "web/src/app/LauncherShell.module.css",
    "web/src/app/pollingPolicy.ts",
    "web/src/app/router.tsx",
    "web/src/routes/LauncherRoute.tsx",
    "web/src/routes/LauncherRoute.module.css",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(event: str, *, level: str = "info", **fields: object) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": _now_iso(),
        "level": level,
        "event": event,
        "fields": fields,
    }
    with PYTHON_BRIDGE_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _hidden_creation_flags() -> int:
    if os.name != "nt":
        return 0
    flags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _select_no_console_python(executable: str) -> str:
    raw = str(executable or "").strip() or sys.executable
    candidate = Path(raw)
    if os.name == "nt" and candidate.name.lower() != "pythonw.exe":
        sibling = candidate.with_name("pythonw.exe")
        if sibling.exists():
            return str(sibling)
    return str(candidate)


def _operator_config_path() -> Path:
    raw = os.environ.get("VIBELUTION_CONFIG_PATH", "").strip()
    if raw:
        return Path(raw)
    config_home = os.environ.get("VIBELUTION_CONFIG_HOME", "").strip()
    if not config_home:
        user_home = os.environ.get("USERPROFILE", str(Path.home()))
        config_home = str(Path(user_home) / "Documents" / "Vibelution" / "config")
    return Path(config_home) / "config.toml"


def _load_operator_config() -> dict[str, object]:
    if tomllib is None:
        return {}
    try:
        with _operator_config_path().open("rb") as handle:
            payload = tomllib.load(handle)
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_section(name: str) -> dict[str, object]:
    payload = _load_operator_config()
    section = payload.get(name)
    return section if isinstance(section, dict) else {}


def _normalize_port(value: object, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def _env_port(names: tuple[str, ...]) -> int | None:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        port = _normalize_port(raw, 0)
        if port:
            return port
    return None


def _workbench_port() -> int:
    config_port = _normalize_port(_config_section("workbench").get("backend_port"), DEFAULT_WORKBENCH_PORT)
    return _env_port(("VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT")) or config_port


def _launcher_control_port(workbench_port: int | None = None) -> int:
    workbench = int(workbench_port or _workbench_port())
    config_port = _normalize_port(_config_section("launcher").get("control_port"), DEFAULT_LAUNCHER_CONTROL_PORT)
    port = _env_port(("VIBELUTION_LAUNCHER_PORT", "AGENT_LAUNCHER_CONTROL_PORT")) or config_port
    if port == workbench:
        candidate = DEFAULT_LAUNCHER_CONTROL_PORT
        if candidate == workbench:
            candidate = workbench + 1
        while candidate < 65536 and candidate == workbench:
            candidate += 1
        port = candidate if 0 < candidate < 65536 else DEFAULT_LAUNCHER_CONTROL_PORT
    return port


def _launcher_base_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{int(port)}"


def _launcher_health_url(port: int) -> str:
    return f"{_launcher_base_url(port)}/api/health"


def _launcher_control_url(port: int) -> str:
    return f"{_launcher_base_url(port)}/launcher"


def _launcher_control_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(_launcher_health_url(port), timeout=1.2) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return False


def _wait_for_launcher_control(port: int, pid: int, *, timeout_seconds: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _launcher_control_healthy(port):
            return True
        if pid > 0 and not _pid_alive(pid):
            return False
        time.sleep(0.35)
    return False


def _wait_for_launcher_control_stopped(port: int, *, timeout_seconds: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _launcher_control_healthy(port):
            return True
        time.sleep(0.25)
    return not _launcher_control_healthy(port)


def _read_state() -> dict[str, object]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(state: dict[str, object]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def _source_signature() -> str:
    lines: list[str] = []
    for relative_path in SOURCE_SIGNATURE_PATHS:
        path = PROJECT_ROOT / relative_path
        if not path.exists() or not path.is_file():
            lines.append(f"{path}|MISSING|")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{path}|{path.stat().st_size}|{digest}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _terminate_pid(pid: int) -> None:
    if pid <= 0 or not _pid_alive(pid):
        return
    if os.name != "nt":
        with contextlib.suppress(OSError):
            os.kill(pid, 15)
        return
    if _terminate_pid_tree_with_psutil(int(pid)):
        return
    _terminate_pid_with_winapi(int(pid))


def _terminate_pid_tree_with_psutil(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import psutil  # type: ignore
    except Exception:
        return False
    try:
        root = psutil.Process(int(pid))
        processes = list(root.children(recursive=True))
        processes.reverse()
        processes.append(root)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except Exception:
        return False
    attempted = False
    for process in processes:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.terminate()
            attempted = True
    try:
        _gone, alive = psutil.wait_procs(processes, timeout=1.5)
    except Exception:
        alive = []
    for process in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.kill()
            attempted = True
    if alive:
        with contextlib.suppress(Exception):
            psutil.wait_procs(alive, timeout=1.0)
    return attempted


def _terminate_pid_with_winapi(pid: int) -> None:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0001, False, int(pid))
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)


def _edge_executable() -> str:
    env_value = os.environ.get("VIBELUTION_EDGE_EXE", "").strip()
    candidates: list[Path] = []
    if env_value:
        candidates.append(Path(env_value))
    for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(env_name, "").strip()
        if root:
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    resolved = shutil.which("msedge")
    if resolved:
        candidates.append(Path(resolved))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Microsoft Edge was not found.")


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = (
        ("fmtid", _GUID),
        ("pid", ctypes.c_ulong),
    )


class _PROPVARIANT(ctypes.Structure):
    _fields_ = (
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("p", ctypes.c_void_p),
        ("p2", ctypes.c_int),
    )


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _property_key(pid: int) -> _PROPERTYKEY:
    return _PROPERTYKEY(_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), int(pid))


PKEY_APPUSERMODEL_ID = _property_key(5)
PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME = _property_key(4)
PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE = _property_key(3)
IID_IPROPERTY_STORE = _guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010


def _window_process_id(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _visible_windows_for_process(pid: int) -> list[int]:
    if os.name != "nt" or pid <= 0:
        return []
    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and _window_process_id(int(hwnd)) == int(pid):
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return handles


def _managed_browser_profile_dir(role: str) -> Path:
    return LAUNCHER_BROWSER_PROFILE_DIR if role == "launcher" else WORKBENCH_BROWSER_PROFILE_DIR


def _managed_browser_pids_for_profile(profile_dir: Path) -> list[int]:
    if os.name != "nt":
        return []
    try:
        import psutil  # type: ignore
    except Exception:
        return []

    profile_text = str(profile_dir).lower()
    profile_text_alt = profile_text.replace("\\", "/")
    pids: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name not in {"msedge.exe", "msedgewebview2.exe"}:
                continue
            cmdline = proc.info.get("cmdline") or []
            command_text = " ".join(str(item) for item in cmdline).lower()
            command_text_alt = command_text.replace("\\", "/")
            if profile_text not in command_text and profile_text_alt not in command_text_alt:
                continue
            pid = int(proc.info.get("pid") or 0)
            if pid > 0 and pid not in pids:
                pids.append(pid)
        except Exception:
            continue
    return pids


def _managed_browser_window_candidates(browser_pid: int, role: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[int] = set()

    for hwnd in _visible_windows_for_process(int(browser_pid)):
        if hwnd in seen:
            continue
        seen.add(hwnd)
        candidates.append(
            {
                "hwnd": int(hwnd),
                "processId": _window_process_id(int(hwnd)),
                "resolvedBy": "launch_pid",
            }
        )

    profile_dir = _managed_browser_profile_dir(role)
    resolved_by = "launcher_control_profile" if role == "launcher" else "workbench_profile"
    for pid in _managed_browser_pids_for_profile(profile_dir):
        for hwnd in _visible_windows_for_process(int(pid)):
            if hwnd in seen:
                continue
            seen.add(hwnd)
            candidates.append(
                {
                    "hwnd": int(hwnd),
                    "processId": _window_process_id(int(hwnd)),
                    "resolvedBy": resolved_by,
                }
            )
    return candidates


def _repair_existing_launcher_browser_window(browser_pid: int) -> int:
    for candidate in _managed_browser_window_candidates(int(browser_pid), "launcher"):
        process_id = int(candidate.get("processId") or 0)
        if process_id <= 0:
            continue
        app_identity = _apply_managed_browser_app_identity(process_id, "launcher")
        resolved_pid = int(app_identity.get("windowPid") or process_id)
        _append_log(
            "desktop_entry_python.browser.identity_repaired",
            browser_pid=int(browser_pid),
            resolved_browser_pid=resolved_pid,
            resolved_by=str(candidate.get("resolvedBy") or ""),
            app_identity_applied=bool(app_identity.get("applied")),
            window_icon_applied=bool(app_identity.get("windowIconApplied")),
        )
        return resolved_pid
    return 0


def _set_property_store_string(store_ptr: int, key: _PROPERTYKEY, value: str) -> None:
    vtable = ctypes.cast(store_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(_PROPERTYKEY),
        ctypes.POINTER(_PROPVARIANT),
    )(vtable[6])
    variant = _PROPVARIANT()
    variant.vt = 31  # VT_LPWSTR
    buffer = ctypes.create_unicode_buffer(str(value or ""))
    variant.p = ctypes.cast(buffer, ctypes.c_void_p).value
    hr = int(set_value(store_ptr, ctypes.byref(key), ctypes.byref(variant)))
    if hr < 0:
        raise OSError(hr, "IPropertyStore.SetValue failed")


def _set_window_app_identity(hwnd: int, app_id: str, display_name: str, icon_resource: str) -> None:
    shell32 = ctypes.windll.shell32
    store_ptr = ctypes.c_void_p()
    shell32.SHGetPropertyStoreForWindow.argtypes = (
        ctypes.wintypes.HWND,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    hr = int(shell32.SHGetPropertyStoreForWindow(ctypes.wintypes.HWND(hwnd), ctypes.byref(IID_IPROPERTY_STORE), ctypes.byref(store_ptr)))
    if hr < 0 or not store_ptr.value:
        raise OSError(hr, "SHGetPropertyStoreForWindow failed")
    vtable = ctypes.cast(store_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    try:
        _set_property_store_string(store_ptr.value, PKEY_APPUSERMODEL_ID, app_id)
        _set_property_store_string(store_ptr.value, PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME, display_name)
        if icon_resource:
            _set_property_store_string(store_ptr.value, PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE, icon_resource)
        hr = int(commit(store_ptr.value))
        if hr < 0:
            raise OSError(hr, "IPropertyStore.Commit failed")
    finally:
        release(store_ptr.value)


def _apply_window_icon(hwnd: int, icon_path: Path) -> bool:
    if os.name != "nt" or not icon_path.exists():
        return False
    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = (
        ctypes.wintypes.HINSTANCE,
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.UINT,
    )
    user32.LoadImageW.restype = ctypes.wintypes.HANDLE
    user32.SendMessageW.argtypes = (
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )
    user32.SendMessageW.restype = ctypes.wintypes.LPARAM
    icon_text = str(icon_path)
    big_icon = user32.LoadImageW(None, icon_text, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
    small_icon = user32.LoadImageW(None, icon_text, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
    applied = False
    if big_icon:
        user32.SendMessageW(ctypes.wintypes.HWND(hwnd), WM_SETICON, ICON_BIG, int(big_icon))
        applied = True
    if small_icon:
        user32.SendMessageW(ctypes.wintypes.HWND(hwnd), WM_SETICON, ICON_SMALL, int(small_icon))
        applied = True
    return applied


def _apply_managed_browser_app_identity(browser_pid: int, role: str) -> dict[str, object]:
    app_id = "Vibelution.Launcher" if role == "launcher" else "Vibelution.Workbench"
    display_name = "Vibelution Launcher" if role == "launcher" else "Vibelution Workbench"
    icon_resource = f"{LAUNCHER_ICON_PATH},0" if LAUNCHER_ICON_PATH.exists() else ""
    if os.name != "nt":
        return {"applied": False, "windowPid": int(browser_pid), "appUserModelId": app_id, "iconResource": icon_resource, "reason": "non_windows"}
    deadline = time.monotonic() + 5.0
    last_error = ""
    last_candidates: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        candidates = _managed_browser_window_candidates(int(browser_pid), role)
        last_candidates = candidates
        for candidate in candidates:
            hwnd = int(candidate.get("hwnd") or 0)
            if hwnd <= 0:
                continue
            try:
                with contextlib.suppress(OSError):
                    ctypes.windll.ole32.CoInitialize(None)
                _set_window_app_identity(hwnd, app_id, display_name, icon_resource)
                window_icon_applied = _apply_window_icon(hwnd, LAUNCHER_ICON_PATH)
                result = {
                    "applied": True,
                    "windowIconApplied": bool(window_icon_applied),
                    "windowPid": _window_process_id(hwnd),
                    "appUserModelId": app_id,
                    "iconResource": icon_resource,
                    "hwnd": hwnd,
                    "resolvedBy": str(candidate.get("resolvedBy") or ""),
                    "candidateProcessId": int(candidate.get("processId") or 0),
                }
                _append_log("launcher.browser.window_app_identity.succeeded", **result)
                return result
            except Exception as exc:  # pragma: no cover - Windows shell integration is smoke-tested manually.
                last_error = str(exc)
        time.sleep(0.2)
    result = {
        "applied": False,
        "windowIconApplied": False,
        "windowPid": int(browser_pid),
        "appUserModelId": app_id,
        "iconResource": icon_resource,
        "reason": "window_not_found_or_identity_failed",
        "error": last_error,
        "candidateCount": len(last_candidates),
        "candidatePids": [int(item.get("processId") or 0) for item in last_candidates],
        "candidateSources": [str(item.get("resolvedBy") or "") for item in last_candidates],
    }
    _append_log("launcher.browser.window_app_identity.failed", level="warning", **result)
    return result


def _managed_edge_args(url: str) -> list[str]:
    return [
        f"--user-data-dir={LAUNCHER_BROWSER_PROFILE_DIR}",
        f"--app={url}",
        "--force-dark-mode",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-component-update",
        "--disable-extensions",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,msEdgeWallet,msEdgeShoppingAssistant,EdgeSearchIndexer,OptimizationGuideModelDownloading,OptimizationHintsFetching",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-service-autorun",
    ]


def _open_launcher_window(url: str) -> int:
    if os.name != "nt":
        return 0
    executable = _edge_executable()
    LAUNCHER_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [executable, *_managed_edge_args(url)],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_hidden_creation_flags(),
        startupinfo=_hidden_startup_info(),
    )
    app_identity = _apply_managed_browser_app_identity(int(process.pid), "launcher")
    return int(app_identity.get("windowPid") or process.pid)


def _start_launcher_backend(python_exe: str, port: int) -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    command_path = _select_no_console_python(python_exe)
    command = [
        command_path,
        "-c",
        f"import uvicorn; uvicorn.run('core.launcher.app:app', host='{DEFAULT_HOST}', port={int(port)}, reload=False)",
        MANAGED_LAUNCHER_MARKER,
        "--port",
        str(int(port)),
    ]
    stdout = LAUNCHER_STDOUT_PATH.open("ab")
    stderr = LAUNCHER_STDERR_PATH.open("ab")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=_hidden_creation_flags(),
            startupinfo=_hidden_startup_info(),
        )
    finally:
        stdout.close()
        stderr.close()
    if not _wait_for_launcher_control(port, int(process.pid)):
        _terminate_pid(int(process.pid))
        raise RuntimeError(f"Launcher control backend did not become healthy at {_launcher_health_url(port)}.")
    return int(process.pid)


def _launcher_backend_source_current(state: dict[str, object], backend_pid: int, current_signature: str) -> bool:
    if backend_pid <= 0:
        return False
    stored_signature = str(state.get("launcherControlSourceSignature") or "")
    if not stored_signature:
        return False
    tracked_pids = {
        int(state.get("launcherBackendPid") or 0),
        int(state.get("launcherBackendLaunchPid") or 0),
    }
    return backend_pid in tracked_pids and stored_signature == current_signature


def _launcher_pids_from_state(state: dict[str, object]) -> list[int]:
    keys = (
        "launcherBackendPid",
        "launcherBackendLaunchPid",
        "launcherBrowserWindowPid",
        "launcherBrowserLaunchPid",
    )
    pids: list[int] = []
    for key in keys:
        try:
            pid = int(state.get(key) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _replace_stale_launcher_control(state: dict[str, object], port: int, current_signature: str) -> bool:
    backend_pid = int(state.get("launcherBackendPid") or 0)
    if not _launcher_control_healthy(port):
        return False
    if _launcher_backend_source_current(state, backend_pid, current_signature):
        return False
    pids = _launcher_pids_from_state(state)
    if not pids:
        return False
    _append_log(
        "desktop_entry_python.stale_launcher_control.replacing",
        port=port,
        backend_pid=backend_pid,
        pids=pids,
    )
    for pid in pids:
        _terminate_pid(pid)
    _wait_for_launcher_control_stopped(port)
    return True


def _discard_orphaned_launcher_control_window(state: dict[str, object], port: int) -> bool:
    if _launcher_control_healthy(port):
        return False
    pids = [pid for pid in _launcher_pids_from_state(state) if _pid_alive(pid)]
    if not pids:
        return False
    _append_log(
        "desktop_entry_python.orphaned_launcher_control.replacing",
        level="warning",
        port=port,
        pids=pids,
    )
    for pid in pids:
        _terminate_pid(pid)
    return True


def _save_launcher_state(
    previous_state: dict[str, object],
    *,
    port: int,
    backend_pid: int,
    browser_pid: int,
    current_signature: str,
    python_exe: str,
) -> None:
    control_url = _launcher_control_url(port)
    next_state = dict(previous_state)
    if str(next_state.get("sessionRole") or "") != "workbench":
        session_id = str(next_state.get("sessionId") or uuid.uuid4())
        next_state.update(
            {
                "schemaVersion": int(next_state.get("schemaVersion") or 1),
                "launcherAdapter": "python_desktop_entry_native",
                "desiredState": str(next_state.get("desiredState") or "closed"),
                "observedState": str(next_state.get("observedState") or "closed"),
                "phase": str(next_state.get("phase") or "steady"),
                "sessionRole": "launcher_control_surface",
                "sessionId": session_id,
                "host": DEFAULT_HOST,
                "port": _workbench_port(),
                "url": f"http://{DEFAULT_HOST}:{_workbench_port()}",
                "backendPid": 0,
                "backendLaunchPid": 0,
                "workbenchBrowserLaunchPid": 0,
                "workbenchBrowserWindowPid": 0,
                "supervisorPid": 0,
            }
        )
    next_state.update(
        {
            "launcherBackendPid": int(backend_pid),
            "launcherBackendLaunchPid": int(backend_pid),
            "launcherControlPort": int(port),
            "launcherControlUrl": control_url,
            "launcherControlSourceSignature": current_signature,
            "launcherControlStartedAt": _now_iso(),
            "launcherBrowserProfileDir": str(LAUNCHER_BROWSER_PROFILE_DIR),
            "launcherBrowserLaunchPid": int(browser_pid),
            "launcherBrowserWindowPid": int(browser_pid),
            "browserManaged": True,
            "browserExecutable": str(next_state.get("browserExecutable") or ""),
            "pythonNoConsoleCommand": _select_no_console_python(python_exe),
            "pythonCommand": str(python_exe or sys.executable),
            "updatedAt": _now_iso(),
        }
    )
    if browser_pid:
        next_state["browserLaunchPid"] = int(browser_pid)
        next_state["browserWindowPid"] = int(browser_pid)
        next_state["browserProfileDir"] = str(LAUNCHER_BROWSER_PROFILE_DIR)
    _write_state(next_state)


@contextlib.contextmanager
def _single_launcher_open_lock(timeout_seconds: float = 20.0) -> Iterator[bool]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME_DIR / "desktop-entry-python.lock"
    handle = lock_path.open("a+b")
    locked = False
    try:
        if handle.tell() == 0 and lock_path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    time.sleep(0.1)
        else:  # pragma: no cover - desktop entry is Windows-only in production.
            locked = True
        yield locked
    finally:
        if locked and os.name == "nt":
            import msvcrt

            with contextlib.suppress(OSError):
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def _open_launcher(args: argparse.Namespace) -> None:
    port = _launcher_control_port()
    current_signature = _source_signature()
    with _single_launcher_open_lock() as has_lock:
        if not has_lock:
            _append_log("desktop_entry_python.open.skipped_lock_busy", level="warning", port=port)
            return
        state = _read_state()
        _replace_stale_launcher_control(state, port, current_signature)
        state = _read_state()
        backend_pid = int(state.get("launcherBackendPid") or 0)
        browser_pid = int(state.get("launcherBrowserWindowPid") or state.get("launcherBrowserLaunchPid") or 0)
        healthy = _launcher_control_healthy(port)
        if not healthy and _discard_orphaned_launcher_control_window(state, port):
            browser_pid = 0
        current = healthy and _launcher_backend_source_current(state, backend_pid, current_signature)
        if healthy:
            if current and backend_pid > 0:
                _append_log("desktop_entry_python.backend.reused", port=port, backend_pid=backend_pid)
            else:
                _append_log(
                    "desktop_entry_python.backend.reused_untracked_healthy_port",
                    level="warning",
                    port=port,
                    backend_pid=backend_pid,
                )
        else:
            backend_pid = _start_launcher_backend(str(args.python_exe or sys.executable), port)
            browser_pid = 0
            _append_log("desktop_entry_python.backend.started", port=port, backend_pid=backend_pid)
        if not args.no_browser:
            if browser_pid <= 0 or not _pid_alive(browser_pid):
                repaired_pid = _repair_existing_launcher_browser_window(browser_pid)
                if repaired_pid > 0:
                    browser_pid = repaired_pid
                    _append_log("desktop_entry_python.browser.reused_profile_window", port=port, browser_pid=browser_pid)
                else:
                    browser_pid = _open_launcher_window(_launcher_control_url(port))
                    _append_log("desktop_entry_python.browser.opened", port=port, browser_pid=browser_pid)
            else:
                _append_log("desktop_entry_python.browser.reused", port=port, browser_pid=browser_pid)
        _save_launcher_state(
            state,
            port=port,
            backend_pid=backend_pid,
            browser_pid=browser_pid,
            current_signature=current_signature,
            python_exe=str(args.python_exe or sys.executable),
        )


def _bootstrap_launcher(args: argparse.Namespace) -> dict[str, object]:
    before = _read_state()
    before_pid = int(before.get("launcherBackendPid") or 0)
    _open_launcher(args)
    after = _read_state()
    backend_pid = int(after.get("launcherBackendPid") or 0)
    port = int(after.get("launcherControlPort") or _launcher_control_port())
    mode = _launcher_bootstrap_mode(before_pid=before_pid, backend_pid=backend_pid)
    ready = _launcher_control_healthy(port)
    return {
        "schemaVersion": 1,
        "workspaceRoot": str(args.workspace or PROJECT_ROOT),
        "operatorConfigPath": str(args.config or ""),
        "workspaceId": str(after.get("workspaceId") or ""),
        "launcherInstanceId": str(after.get("sessionId") or ""),
        "mode": mode,
        "launcherBackendPid": backend_pid,
        "launcherUrl": _launcher_control_url(port),
        "workbenchUrl": str(after.get("url") or ""),
        "ready": ready,
        "protocolVersion": 1,
        "minDesktopProtocolVersion": 1,
        "maxDesktopProtocolVersion": 1,
        "capabilities": [
            "desktop_actions.claim",
            "desktop_sessions.heartbeat",
            "runtime_scene.electron_event",
        ],
    }


def _launcher_bootstrap_mode(*, before_pid: int, backend_pid: int) -> str:
    if backend_pid <= 0:
        return "attached"
    if before_pid > 0 and before_pid == backend_pid:
        return "attached"
    return "started"


def _stop_owned_launcher(args: argparse.Namespace) -> dict[str, object]:
    state = _read_state()
    expected_backend_pid = int(args.owned_backend_pid or 0)
    backend_pid = int(state.get("launcherBackendPid") or 0)
    backend_launch_pid = int(state.get("launcherBackendLaunchPid") or 0)
    port = int(state.get("launcherControlPort") or _launcher_control_port())
    if expected_backend_pid <= 0:
        _append_log(
            "desktop_entry_python.stop.skipped",
            level="warning",
            reason="owned_backend_pid_required",
            launcher_backend_pid=backend_pid,
            launcher_backend_launch_pid=backend_launch_pid,
        )
        return {
            "schemaVersion": 1,
            "status": "skipped",
            "reason": "owned_backend_pid_required",
            "expectedBackendPid": expected_backend_pid,
            "launcherBackendPid": backend_pid,
            "terminatedPids": [],
        }
    if expected_backend_pid > 0 and expected_backend_pid not in {backend_pid, backend_launch_pid}:
        _append_log(
            "desktop_entry_python.stop.skipped",
            level="warning",
            reason="owned_backend_pid_mismatch",
            expected_backend_pid=expected_backend_pid,
            launcher_backend_pid=backend_pid,
            launcher_backend_launch_pid=backend_launch_pid,
        )
        return {
            "schemaVersion": 1,
            "status": "skipped",
            "reason": "owned_backend_pid_mismatch",
            "expectedBackendPid": expected_backend_pid,
            "launcherBackendPid": backend_pid,
            "terminatedPids": [],
        }
    pids = _launcher_pids_from_state(state)
    for pid in pids:
        _terminate_pid(pid)
    if port > 0:
        _wait_for_launcher_control_stopped(port)
    next_state = dict(state)
    now = _now_iso()
    next_state.update(
        {
            "launcherBackendPid": 0,
            "launcherBackendLaunchPid": 0,
            "launcherBrowserWindowPid": 0,
            "launcherBrowserLaunchPid": 0,
            "browserManaged": False,
            "launcherControlStoppedAt": now,
            "updatedAt": now,
        }
    )
    _write_state(next_state)
    _append_log("desktop_entry_python.stop.succeeded", port=port, terminated_pids=pids)
    return {
        "schemaVersion": 1,
        "status": "stopped",
        "reason": "",
        "expectedBackendPid": expected_backend_pid,
        "launcherBackendPid": backend_pid,
        "terminatedPids": pids,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the Vibelution Launcher without a console window.")
    parser.add_argument("--action", default="launcher")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--python-exe", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--owned-backend-pid", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    action = str(args.action or "launcher").strip().lower()
    if action not in {"launcher", "bootstrap", "stop-launcher"}:
        raise SystemExit(f"Unsupported desktop-entry Python bridge action: {action}")
    try:
        _append_log("desktop_entry_python.open.started", action=action, no_browser=bool(args.no_browser), run_id=args.run_id)
        if action == "bootstrap":
            payload = _bootstrap_launcher(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Launcher bootstrap {payload['mode']} at {payload['launcherUrl']}")
        elif action == "stop-launcher":
            payload = _stop_owned_launcher(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Launcher stop {payload['status']}")
        else:
            _open_launcher(args)
        _append_log("desktop_entry_python.open.succeeded", action=action, run_id=args.run_id)
        return 0
    except Exception as exc:
        _append_log(
            "desktop_entry_python.open.failed",
            level="error",
            action=action,
            run_id=args.run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
