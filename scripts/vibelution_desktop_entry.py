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
import re
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

try:
    from scripts.windowless_subprocess import no_window_subprocess_kwargs
except ModuleNotFoundError:  # Direct execution sets sys.path[0] to scripts/.
    import importlib.util

    _windowless_spec = importlib.util.spec_from_file_location(
        "vibelution_windowless_subprocess",
        Path(__file__).with_name("windowless_subprocess.py"),
    )
    if _windowless_spec is None or _windowless_spec.loader is None:
        raise RuntimeError("Unable to load the windowless subprocess policy.")
    _windowless_module = importlib.util.module_from_spec(_windowless_spec)
    _windowless_spec.loader.exec_module(_windowless_module)
    no_window_subprocess_kwargs = _windowless_module.no_window_subprocess_kwargs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vibelution_storage import resolve_active_project_storage_paths, resolve_project_runtime_home

PROJECT_STORAGE = resolve_active_project_storage_paths(PROJECT_ROOT)
RUNTIME_DIR = PROJECT_STORAGE.runtime / "launcher"
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
    "web/src/app/LauncherShell.styles.ts",
    "web/src/app/pollingPolicy.ts",
    "web/src/app/router.tsx",
    "web/src/routes/LauncherRoute.tsx",
    "web/src/routes/LauncherRoute.styles.ts",
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


def _desktop_process_group_flag() -> int:
    """Return CREATE_NEW_PROCESS_GROUP on Windows; shared helper adds CREATE_NO_WINDOW + hidden startup info."""
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


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


def _project_local_backend_port() -> int | None:
    """Read checkout-local port assignment written by the launcher on multi-project conflict."""

    ports_path = resolve_project_runtime_home(PROJECT_ROOT) / "launcher" / "ports.json"
    try:
        raw = json.loads(ports_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    port = _normalize_port(raw.get("backendPort"), 0)
    return port or None


def _workbench_port() -> int:
    # Match config.workbench.configured_backend_port precedence:
    # env → .runtime/launcher/ports.json → operator config → DEFAULT.
    env_port = _env_port(("VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT"))
    if env_port:
        return env_port
    project_port = _project_local_backend_port()
    if project_port is not None:
        return project_port
    return _normalize_port(_config_section("workbench").get("backend_port"), DEFAULT_WORKBENCH_PORT)


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


def _launcher_freshness_url(port: int) -> str:
    return f"{_launcher_base_url(port)}/api/launcher/freshness"


def _launcher_control_url(port: int) -> str:
    return f"{_launcher_base_url(port)}/launcher"


def _launcher_control_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(_launcher_health_url(port), timeout=1.2) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return False


def _launcher_control_git_current(port: int) -> bool | None:
    """Return whether the live control plane matches disk HEAD.

    ``None`` means the probe failed or the running identity is unknown; callers
    must not treat that as stale, or a downed freshness endpoint would kill a
    healthy backend.
    """

    request = urllib.request.Request(
        _launcher_freshness_url(port),
        headers={"X-Vibelution-Launcher-Trigger": "desktop_entry_python"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            status = int(getattr(response, "status", 0) or 0)
            raw = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return None
    if status != 200:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    current = payload.get("current")
    if current is True:
        return True
    if current is False:
        return False
    return None


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


def _managed_launcher_process_snapshot_matches(
    snapshot: dict[str, object],
    *,
    port: int,
    workspace_root: Path,
) -> bool:
    name = str(snapshot.get("name") or "").strip().lower()
    if name not in {"python.exe", "pythonw.exe"}:
        return False
    try:
        process_cwd = Path(str(snapshot.get("cwd") or "")).resolve()
        requested_root = workspace_root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if process_cwd != requested_root:
        return False
    cmdline = snapshot.get("cmdline")
    if not isinstance(cmdline, (list, tuple)):
        return False
    args = [str(item).strip() for item in cmdline]
    command_text = " ".join(args).lower()
    if "core.launcher.app:app" not in command_text or "--managed-launcher-control" not in args:
        return False
    try:
        port_index = args.index("--port")
    except ValueError:
        return False
    return port_index + 1 < len(args) and args[port_index + 1] == str(int(port))


def _managed_launcher_listener_pid(port: int, workspace_root: Path) -> int:
    try:
        import psutil  # type: ignore
    except Exception:
        return 0
    try:
        connections = psutil.net_connections(kind="tcp")
    except Exception:
        return 0
    for connection in connections:
        local_address = getattr(connection, "laddr", None)
        local_port = int(getattr(local_address, "port", 0) or 0)
        if local_port != int(port) or str(getattr(connection, "status", "")).upper() != "LISTEN":
            continue
        pid = int(getattr(connection, "pid", 0) or 0)
        if pid <= 0:
            continue
        try:
            process = psutil.Process(pid)
            snapshot = {
                "name": process.name(),
                "cwd": process.cwd(),
                "cmdline": process.cmdline(),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
        if _managed_launcher_process_snapshot_matches(
            snapshot,
            port=port,
            workspace_root=workspace_root,
        ):
            return pid
    return 0


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


if os.name == "nt":
    # Windows shell property-store identity (AppUserModelID + relaunch icon).
    # These ctypes structures are Windows-layout-specific (c_ulong is 4 bytes
    # on Windows but 8 bytes on POSIX, which would make _GUID 24 bytes and
    # break _GUID.from_buffer_copy for 16-byte GUID buffers). They are
    # therefore only constructed on Windows; off-Windows paths short-circuit
    # in _apply_managed_browser_app_identity before any of them is used.

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
else:
    # Safe placeholders for non-Windows imports: the shell identity helpers are
    # guarded by os.name checks and never dereference these off-Windows.
    PKEY_APPUSERMODEL_ID = None
    PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME = None
    PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE = None
    IID_IPROPERTY_STORE = None
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
        # Avoid --force-dark-mode: conflicts with workbench data-theme and flickers Edge --app chrome.
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
        **no_window_subprocess_kwargs(creationflags=_desktop_process_group_flag()),
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
            **no_window_subprocess_kwargs(creationflags=_desktop_process_group_flag()),
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
    source_current = _launcher_backend_source_current(state, backend_pid, current_signature)
    if source_current:
        git_current = _launcher_control_git_current(port)
        if git_current is not False:
            return False
        stale_reason = "git_freshness"
    else:
        git_current = None
        stale_reason = "source_signature"
    pids = _launcher_pids_from_state(state)
    if not pids:
        return False
    _append_log(
        "desktop_entry_python.stale_launcher_control.replacing",
        port=port,
        backend_pid=backend_pid,
        pids=pids,
        reason=stale_reason,
        source_current=source_current,
        git_current=git_current,
    )
    for pid in pids:
        _terminate_pid(pid)
    _wait_for_launcher_control_stopped(port)
    return True


def _active_electron_desktop_session_for_workspace(workspace_root: Path) -> dict[str, object]:
    """Return the live Electron lease that makes control-plane rekey unsafe."""

    project_path = str(PROJECT_ROOT)
    added_project_path = project_path not in sys.path
    if added_project_path:
        sys.path.insert(0, project_path)
    try:
        from core.launcher.desktop_session_store import latest_active_desktop_session

        session = latest_active_desktop_session(
            provider="electron",
            workspace_root=str(workspace_root.resolve()),
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return {}
    finally:
        if added_project_path:
            with contextlib.suppress(ValueError):
                sys.path.remove(project_path)
    if not isinstance(session, dict):
        return {}
    session_id = str(session.get("desktopSessionId") or "").strip()
    match = re.search(r"-(\d+)-[a-z0-9]+$", session_id, re.IGNORECASE)
    if match is not None and not _pid_alive(int(match.group(1))):
        return {}
    return session


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
            "runtimeProjectRoot": str(PROJECT_ROOT),
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
        workspace_root = Path(str(args.workspace or PROJECT_ROOT)).resolve()
        active_electron_session = _active_electron_desktop_session_for_workspace(workspace_root)
        attached_active_electron = bool(active_electron_session and _launcher_control_healthy(port))
        if attached_active_electron:
            _assert_managed_launcher_attachment(state, args=args, port=port)
            _append_log(
                "desktop_entry_python.backend.attached_active_electron",
                port=port,
                backend_pid=int(state.get("launcherBackendPid") or 0),
                desktop_session_id=str(active_electron_session.get("desktopSessionId") or ""),
                source_signature_policy="preserved_until_controlled_restart",
            )
        else:
            _replace_stale_launcher_control(state, port, current_signature)
        state = _read_state()
        backend_pid = int(state.get("launcherBackendPid") or 0)
        browser_pid = int(state.get("launcherBrowserWindowPid") or state.get("launcherBrowserLaunchPid") or 0)
        healthy = _launcher_control_healthy(port)
        attached_active_electron = bool(attached_active_electron and healthy)
        if not healthy and _discard_orphaned_launcher_control_window(state, port):
            browser_pid = 0
        current = healthy and (
            attached_active_electron
            or _launcher_backend_source_current(state, backend_pid, current_signature)
        )
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
            current_signature=(
                str(state.get("launcherControlSourceSignature") or current_signature)
                if attached_active_electron
                else current_signature
            ),
            python_exe=str(args.python_exe or sys.executable),
        )


def _bootstrap_launcher(args: argparse.Namespace) -> dict[str, object]:
    before = _read_state()
    before_pid = int(before.get("launcherBackendPid") or 0)
    attach_healthy_launcher = bool(getattr(args, "attach_healthy_launcher", False))
    attached_existing = False
    port = _launcher_control_port()
    if attach_healthy_launcher and _launcher_control_healthy(port):
        attached_pid = _assert_managed_launcher_attachment(before, args=args, port=port)
        attached_existing = True
        after = dict(before)
        if attached_pid != before_pid or int(before.get("launcherControlPort") or 0) != port:
            after["launcherBackendPid"] = attached_pid
            after["launcherBackendLaunchPid"] = attached_pid
            after["launcherControlPort"] = port
            after["launcherControlUrl"] = _launcher_control_url(port)
            _write_state(after)
            _append_log(
                "desktop_entry_python.backend.attachment_pid_recovered",
                level="warning",
                port=port,
                backend_pid=attached_pid,
                reason="shared_state_pid_missing",
            )
        _append_log(
            "desktop_entry_python.backend.attached_managed_healthy",
            port=port,
            backend_pid=attached_pid,
            reason="electron_bootstrap",
            source_signature_policy="ignored_for_attach",
        )
    else:
        _open_launcher(args)
        after = _read_state()
    backend_pid = int(after.get("launcherBackendPid") or 0)
    port = int(after.get("launcherControlPort") or _launcher_control_port())
    mode = "attached" if attached_existing else _launcher_bootstrap_mode(before_pid=before_pid, backend_pid=backend_pid)
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
        "workbenchUrl": str(after.get("url") or "").strip() or f"http://{DEFAULT_HOST}:{_workbench_port()}",
        "ready": ready,
        "protocolVersion": 1,
        "minDesktopProtocolVersion": 1,
        "maxDesktopProtocolVersion": 1,
        "capabilities": [
            "desktop_actions.claim",
            "desktop_sessions.heartbeat",
            "runtime_scene.electron_event",
            "workbench_close.transaction.v1",
        ],
    }


def _assert_managed_launcher_attachment(
    state: dict[str, object],
    *,
    args: argparse.Namespace,
    port: int,
) -> int:
    backend_pid = int(state.get("launcherBackendPid") or 0)
    state_port = int(state.get("launcherControlPort") or 0)
    adapter = str(state.get("launcherAdapter") or "").strip()
    state_root = str(state.get("runtimeProjectRoot") or "").strip()
    requested_root = Path(str(args.workspace or PROJECT_ROOT)).resolve()
    if adapter not in {"python_headless", "python_desktop_entry_native"}:
        raise RuntimeError("Healthy Launcher control port is not owned by a supported managed adapter.")
    if state_port > 0 and state_port != int(port):
        raise RuntimeError("Healthy Launcher control port does not match the managed Launcher state.")
    if not state_root or Path(state_root).resolve() != requested_root:
        raise RuntimeError("Healthy Launcher control port does not belong to this workspace.")
    if state_port == int(port) and backend_pid > 0 and _pid_alive(backend_pid):
        return backend_pid
    recovered_pid = _managed_launcher_listener_pid(port, requested_root)
    if recovered_pid <= 0:
        raise RuntimeError("Healthy Launcher control port has no live managed backend PID.")
    return recovered_pid


def _launcher_bootstrap_mode(*, before_pid: int, backend_pid: int) -> str:
    if backend_pid <= 0:
        return "attached"
    if before_pid > 0 and before_pid == backend_pid:
        return "attached"
    return "started"


def _same_workspace_root(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


def _resolve_stop_owned_backend_pid(args: argparse.Namespace, state: dict[str, object]) -> tuple[int, str]:
    expected_backend_pid = int(getattr(args, "owned_backend_pid", 0) or 0)
    if expected_backend_pid > 0:
        return expected_backend_pid, ""
    if not bool(getattr(args, "use_state_owned_backend_pid", False)):
        return 0, "owned_backend_pid_required"
    state_root_raw = str(state.get("runtimeProjectRoot") or "").strip()
    if not state_root_raw:
        return 0, "workspace_root_missing"
    try:
        state_root = Path(state_root_raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return 0, "workspace_root_invalid"
    if not _same_workspace_root(state_root, _workspace_root(args)):
        return 0, "workspace_mismatch"
    state_pid = int(state.get("launcherBackendPid") or 0)
    if state_pid <= 0:
        return 0, "owned_backend_pid_required"
    return state_pid, ""


def _stop_owned_launcher(args: argparse.Namespace) -> dict[str, object]:
    state = _read_state()
    expected_backend_pid, skip_reason = _resolve_stop_owned_backend_pid(args, state)
    backend_pid = int(state.get("launcherBackendPid") or 0)
    backend_launch_pid = int(state.get("launcherBackendLaunchPid") or 0)
    port = int(state.get("launcherControlPort") or _launcher_control_port())
    if skip_reason:
        _append_log(
            "desktop_entry_python.stop.skipped",
            level="warning",
            reason=skip_reason,
            launcher_backend_pid=backend_pid,
            launcher_backend_launch_pid=backend_launch_pid,
        )
        return {
            "schemaVersion": 1,
            "status": "skipped",
            "reason": skip_reason,
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


def _run_lifecycle_bridge(args: argparse.Namespace) -> dict[str, object]:
    """Run a managed workbench lifecycle operation in-process on behalf of Electron main."""
    operation = str(args.lifecycle_operation or "").strip().lower()
    if operation not in _LIFECYCLE_OPERATIONS:
        raise ValueError(f"Unsupported lifecycle operation: {operation}")
    from core.launcher import service as launcher_service

    _append_log("desktop_entry_python.lifecycle.started", operation=operation)
    try:
        if operation == "start":
            response = launcher_service.request_launcher_start()
        elif operation == "stop":
            response = launcher_service.request_launcher_stop()
        elif operation == "force-stop":
            response = launcher_service.request_launcher_force_stop()
        elif operation == "restart":
            response = launcher_service.request_launcher_restart(
                reason="electron_main_restart", source="electron_main"
            )
        elif operation == "shutdown":
            response = launcher_service.request_launcher_runtime_shutdown()
        else:
            response = launcher_service.request_launcher_rebuild_and_start()
    except launcher_service.LauncherActiveWorkBlocked as exc:
        _append_log(
            "desktop_entry_python.lifecycle.blocked",
            level="warning",
            operation=operation,
            message=exc.message,
        )
        return {
            "schemaVersion": 1,
            "accepted": False,
            "code": "active_work_blocked",
            "operation": operation,
            "message": str(exc.message),
            "activeWorkRuns": list(getattr(exc, "active_work_runs", []) or []),
        }
    _append_log(
        "desktop_entry_python.lifecycle.succeeded",
        operation=operation,
        command_id=str(response.get("commandId") or ""),
    )
    return {"schemaVersion": 1, **response}


_LIFECYCLE_OPERATIONS = {"start", "stop", "force-stop", "restart", "rebuild-and-start", "shutdown"}


_BRANCH_INSTANCE_OPERATIONS = {"start", "stop", "force-stop", "restart"}


def _run_branch_instance_bridge(args: argparse.Namespace) -> dict[str, object]:
    """Run a branch-instance lifecycle operation in-process on behalf of Electron main."""
    operation = str(args.branch_instance_operation or "").strip().lower()
    instance_id = str(args.instance_id or "").strip()
    if operation not in _BRANCH_INSTANCE_OPERATIONS:
        raise ValueError(f"Unsupported branch instance operation: {operation}")
    if not instance_id:
        raise ValueError("branch instance id is required")
    from core.launcher import service as launcher_service

    _append_log("desktop_entry_python.branch_instance.started", operation=operation, instance_id=instance_id)
    try:
        response = launcher_service.request_branch_instance_operation(instance_id, operation)
    except launcher_service.LauncherActiveWorkBlocked as exc:
        _append_log(
            "desktop_entry_python.branch_instance.blocked",
            level="warning",
            operation=operation,
            instance_id=instance_id,
            message=exc.message,
        )
        return {
            "schemaVersion": 1,
            "accepted": False,
            "code": "active_work_blocked",
            "operation": operation,
            "instanceId": instance_id,
            "message": str(exc.message),
            "activeWorkRuns": list(getattr(exc, "active_work_runs", []) or []),
        }
    except Exception as exc:
        _append_log(
            "desktop_entry_python.branch_instance.failed",
            level="error",
            operation=operation,
            instance_id=instance_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "schemaVersion": 1,
            "accepted": False,
            "code": "branch_instance_operation_failed",
            "operation": operation,
            "instanceId": instance_id,
            "message": str(exc),
        }
    _append_log(
        "desktop_entry_python.branch_instance.succeeded",
        operation=operation,
        instance_id=instance_id,
    )
    return {"schemaVersion": 1, **response}


def _split_launcher_api_path(path: str) -> tuple[str, dict[str, str]]:
    raw = str(path or "").strip()
    route, _, query = raw.partition("?")
    params: dict[str, str] = {}
    if query:
        from urllib.parse import parse_qs

        parsed = parse_qs(query, keep_blank_values=False)
        params = {key: (values[-1] if values else "") for key, values in parsed.items()}
    return route, params


def _query_flag(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _run_launcher_api_bridge(args: argparse.Namespace) -> dict[str, object]:
    """Serve settings/developer-mode/maintenance through a no-console JSON CLI."""
    raw_path = str(args.launcher_api_path or "").strip()
    path, query = _split_launcher_api_path(raw_path)
    method = str(args.launcher_api_method or "GET").strip().upper()
    body: dict[str, object] = {}
    if args.launcher_api_body:
        body = json.loads(args.launcher_api_body) if isinstance(args.launcher_api_body, str) else dict(args.launcher_api_body)
    if not isinstance(body, dict):
        body = {}
    from core.launcher import service as launcher_service

    _append_log("desktop_entry_python.launcher_api.started", method=method, path=raw_path)
    try:
        if path == "settings/workbench-window" and method == "GET":
            response = launcher_service.get_workbench_window_mode_setting()
        elif path == "settings/workbench-window" and method == "PUT":
            response = launcher_service.update_workbench_window_mode(
                str(body.get("mode") or ""), base_hash=str(body.get("baseHash") or "")
            )
        elif path == "settings/startup" and method == "GET":
            response = launcher_service.get_launcher_startup_settings()
        elif path == "settings/startup" and method == "PUT":
            response = launcher_service.update_launcher_startup_settings(body)
        elif path == "developer-mode" and method == "GET":
            response = launcher_service.get_launcher_developer_mode_setting()
        elif path == "developer-mode" and method == "PUT":
            response = launcher_service.update_launcher_developer_mode(
                body.get("enabled"), base_hash=str(body.get("baseHash") or "")
            )
        elif path == "developer-mode/reset-sandbox" and method == "POST":
            response = launcher_service.reset_launcher_developer_sandbox()
        elif path == "developer-mode/noise-overview" and method == "GET":
            response = launcher_service.get_launcher_developer_noise_overview()
        elif path == "developer-mode/cleanup/preview" and method == "POST":
            response = launcher_service.preview_launcher_developer_cleanup(str(body.get("action") or ""))
        elif path == "developer-mode/cleanup/apply" and method == "POST":
            response = launcher_service.apply_launcher_developer_cleanup(body)
        elif path == "maintenance/reset/summary" and method == "GET":
            response = launcher_service.get_launcher_maintenance_summary()
        elif path == "maintenance/reset/preview" and method == "POST":
            response = launcher_service.preview_launcher_maintenance_plan(body)
        elif path == "maintenance/reset/apply" and method == "POST":
            response = launcher_service.apply_launcher_maintenance_plan(body)
        elif path == "status" and method == "GET":
            response = launcher_service.get_launcher_status()
        elif path == "freshness" and method == "GET":
            response = launcher_service.get_launcher_freshness()
        elif path == "branch-instances" and method == "GET":
            if _query_flag(query.get("cleanupMetadata", "")):
                response = launcher_service.list_launcher_branch_instances(include_cleanup_metadata=True)
            else:
                response = launcher_service.list_launcher_branch_instances()
        elif path == "branch-instances/cleanup" and method == "POST":
            instance_ids = body.get("instanceIds")
            if not isinstance(instance_ids, list):
                instance_ids = []
            response = launcher_service.cleanup_launcher_branch_instances(
                [str(item) for item in instance_ids],
                confirm=bool(body.get("confirm")),
            )
        else:
            raise RuntimeError(f"Unsupported launcher api path: {method} {path}")
    except Exception as exc:
        _append_log(
            "desktop_entry_python.launcher_api.failed",
            level="error",
            method=method,
            path=path,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "schemaVersion": 1,
            "ok": False,
            "code": "launcher_api_bridge_failed",
            "message": str(exc),
        }
    _append_log("desktop_entry_python.launcher_api.succeeded", method=method, path=path)
    return {"schemaVersion": 1, "ok": True, "payload": response}


def _resolve_workbench_bridge(_args: argparse.Namespace) -> dict[str, object]:
    """Resolve the managed workbench URL without a Python Launcher control plane."""
    port = _workbench_port()
    url = str(_read_state().get("url") or "").strip()
    if not url.startswith("http://127.0.0.1:") and not url.startswith("http://localhost:"):
        url = f"http://{DEFAULT_HOST}:{port}/"
    _append_log("desktop_entry_python.resolve_workbench.succeeded", backend_port=port, url=url)
    return {
        "schemaVersion": 1,
        "workbenchUrl": url,
        "backendPort": port,
    }


def _workspace_root(args: argparse.Namespace) -> Path:
    requested = str(getattr(args, "workspace", "") or "").strip()
    return Path(requested or PROJECT_ROOT).resolve()


def _desktop_shell_status_bridge(args: argparse.Namespace) -> dict[str, object]:
    from core.launcher.desktop_shell import inspect_desktop_shell

    payload = inspect_desktop_shell(_workspace_root(args))
    _append_log(
        "desktop_entry_python.desktop_shell.status",
        stale=bool(payload.get("stale")),
        reason=str(payload.get("reason") or ""),
    )
    return payload


def _schedule_desktop_shell_refresh_bridge(args: argparse.Namespace) -> dict[str, object]:
    from core.launcher.desktop_shell import schedule_desktop_shell_refresh

    payload = schedule_desktop_shell_refresh(
        wait_pid=int(args.wait_pid or 0),
        then_lifecycle=str(args.then_lifecycle or ""),
        project_root=_workspace_root(args),
        python_executable=str(args.python_exe or sys.executable),
        force=bool(getattr(args, "force_refresh", False)),
    )
    _append_log(
        "desktop_entry_python.desktop_shell.refresh_scheduled",
        helper_pid=int(payload.get("helperPid") or 0),
        wait_pid=int(payload.get("waitPid") or 0),
        then_lifecycle=str(payload.get("thenLifecycle") or ""),
    )
    return payload


def _refresh_desktop_shell_bridge(args: argparse.Namespace) -> dict[str, object]:
    from core.launcher.desktop_shell import run_desktop_shell_refresh

    payload = run_desktop_shell_refresh(
        wait_pid=int(args.wait_pid or 0),
        then_lifecycle=str(args.then_lifecycle or ""),
        project_root=_workspace_root(args),
    )
    _append_log(
        "desktop_entry_python.desktop_shell.refreshed",
        then_lifecycle=str(args.then_lifecycle or ""),
        wait_pid=int(args.wait_pid or 0),
    )
    return payload


def _launch_desktop_shell_bridge(args: argparse.Namespace) -> dict[str, object]:
    from core.launcher.desktop_shell import launch_desktop_shell

    payload = launch_desktop_shell(
        project_root=_workspace_root(args),
        then_lifecycle=str(args.then_lifecycle or ""),
        open_workbench=bool(getattr(args, "open_workbench", False)),
    )
    _append_log(
        "desktop_entry_python.desktop_shell.launched",
        kind=str(payload.get("kind") or ""),
        pid=int(payload.get("pid") or 0),
        then_lifecycle=str(payload.get("thenLifecycle") or ""),
        open_workbench=bool(payload.get("openWorkbench")),
    )
    return payload


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
    parser.add_argument(
        "--use-state-owned-backend-pid",
        action="store_true",
        help=(
            "Allow stop-launcher to use launcherBackendPid from this workspace's "
            "state.json when --owned-backend-pid is omitted. Native tray restart/exit "
            "uses this; Electron still passes an explicit pid."
        ),
    )
    parser.add_argument("--attach-healthy-launcher", action="store_true")
    parser.add_argument("--lifecycle-operation", default="")
    parser.add_argument("--branch-instance-operation", default="")
    parser.add_argument("--instance-id", default="")
    parser.add_argument("--launcher-api-path", default="")
    parser.add_argument("--launcher-api-method", default="GET")
    parser.add_argument("--launcher-api-body", default="")
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--then-lifecycle", default="")
    parser.add_argument(
        "--open-workbench",
        action="store_true",
        help="Ask Electron main to open or focus the workbench window after launch.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Clear recent desktop shell refresh failure cooldown before scheduling.",
    )
    return parser.parse_args(argv)


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    action = str(args.action or "launcher").strip().lower()
    if action not in {
        "launcher",
        "bootstrap",
        "stop-launcher",
        "lifecycle",
        "branch-instance",
        "launcher-api",
        "resolve-workbench",
        "desktop-shell-status",
        "schedule-desktop-shell-refresh",
        "refresh-desktop-shell",
        "launch-desktop-shell",
    }:
        raise SystemExit(f"Unsupported desktop-entry Python bridge action: {action}")
    if str(args.output or "").strip().lower() == "json":
        _configure_utf8_stdio()
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
        elif action == "lifecycle":
            payload = _run_lifecycle_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Lifecycle {payload.get('operation')} accepted={payload.get('accepted')}")
        elif action == "branch-instance":
            payload = _run_branch_instance_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Branch instance {payload.get('operation')} accepted={payload.get('accepted')}")
        elif action == "launcher-api":
            payload = _run_launcher_api_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Launcher api ok={payload.get('ok')}")
        elif action == "resolve-workbench":
            payload = _resolve_workbench_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Workbench {payload.get('workbenchUrl')}")
        elif action == "desktop-shell-status":
            payload = _desktop_shell_status_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Desktop shell stale={payload.get('stale')} reason={payload.get('reason')}")
        elif action == "schedule-desktop-shell-refresh":
            payload = _schedule_desktop_shell_refresh_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"Desktop shell refresh scheduled helperPid={payload.get('helperPid')}")
        elif action == "refresh-desktop-shell":
            payload = _refresh_desktop_shell_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print("Desktop shell refreshed")
        elif action == "launch-desktop-shell":
            payload = _launch_desktop_shell_bridge(args)
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            else:
                print(
                    f"Desktop shell launched kind={payload.get('kind')} pid={payload.get('pid')}"
                )
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
