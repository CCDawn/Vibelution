#!/usr/bin/env python3
"""Cross-platform headless launcher adapter for the Vibelution workbench."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback for developer shells.
    tomllib = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "launcher"
STATE_PATH = RUNTIME_DIR / "state.json"
BACKEND_STDOUT_PATH = RUNTIME_DIR / "backend.stdout.log"
BACKEND_STDERR_PATH = RUNTIME_DIR / "backend.stderr.log"
FRONTEND_BUILD_LOG_PATH = RUNTIME_DIR / "frontend-build.log"
WORKBENCH_BROWSER_PROFILE_DIR = RUNTIME_DIR / "workbench-app-profile"
LAUNCHER_ICON_PATH = PROJECT_ROOT / "assets" / "icons" / "vibelution.ico"
DEFAULT_HOST = "127.0.0.1"
TRUSTED_WEB_HOSTS_ENV = "VIBELUTION_TRUSTED_WEB_HOSTS"
FRONTEND_PACKAGE_MANAGER_ENV = "VIBELUTION_FRONTEND_PM"
INTERNAL_LAUNCHER_ENV = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
INTERNAL_ACTIONS = {"internal-start", "internal-focus", "internal-stop", "internal-restart"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_action(action: str) -> str:
    value = str(action or "start").strip().lower()
    aliases = {
        "internal-start": "start",
        "internal-focus": "focus",
        "internal-stop": "stop",
        "internal-restart": "restart",
        "open": "start",
        "close": "stop",
    }
    return aliases.get(value, value)


def _is_internal_action(action: str) -> bool:
    return str(action or "").strip().lower() in INTERNAL_ACTIONS


def _assert_internal_action_authorized(action: str) -> None:
    if not _is_internal_action(action):
        return
    if os.environ.get(INTERNAL_LAUNCHER_ENV, "").strip() == "1":
        return
    raise RuntimeError(
        f"Launcher internal action '{action}' can only be called by Runtime Manager. "
        "Use start, stop, or restart instead."
    )


def _read_state() -> dict:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _health_url(port: int, host: str = DEFAULT_HOST) -> str:
    return f"http://{host}:{int(port)}/api/health"


def _backend_healthy(port: int, host: str = DEFAULT_HOST) -> bool:
    try:
        with urllib.request.urlopen(_health_url(port, host), timeout=1.5) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _wait_for_health(port: int, host: str, timeout_seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _backend_healthy(port, host):
            return True
        time.sleep(0.35)
    return False


def _windows_creation_flag_names() -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    return ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW")


def _windows_creation_flags() -> int:
    if os.name != "nt":
        return 0
    flags = 0
    for name in _windows_creation_flag_names():
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _process_output_tail(value: str, *, max_lines: int = 20, max_chars: int = 4000) -> str:
    lines = [line.rstrip() for line in str(value or "").splitlines() if line.strip()]
    text = "\n".join(lines[-max_lines:])
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def _run_checked(args: list[str], *, cwd: Path, label: str) -> None:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
        check=False,
    )
    if result.returncode != 0:
        _append_frontend_build_log(
            {
                "event": "frontend_build.command_failed",
                "command": label,
                "exitCode": int(result.returncode),
                "stdoutTail": _process_output_tail(result.stdout),
                "stderrTail": _process_output_tail(result.stderr),
            }
        )
        raise RuntimeError(f"{label} failed with exit code {result.returncode}.")


def _append_frontend_build_log(payload: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": _now_iso(),
        **payload,
    }
    with FRONTEND_BUILD_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _host_is_wildcard(host: str) -> bool:
    return str(host or "").strip() in {"0.0.0.0", "::"}


def _local_lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            address = str(info[4][0] or "").strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = str(probe.getsockname()[0] or "").strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def _backend_environment(host: str) -> dict[str, str]:
    env = os.environ.copy()
    if _host_is_wildcard(host):
        existing = [item.strip() for item in env.get(TRUSTED_WEB_HOSTS_ENV, "").replace(";", ",").split(",") if item.strip()]
        merged = sorted({*existing, *_local_lan_addresses()})
        if merged:
            env[TRUSTED_WEB_HOSTS_ENV] = ",".join(merged)
    return env


def _frontend_package_manager() -> str:
    value = os.environ.get(FRONTEND_PACKAGE_MANAGER_ENV, "").strip().lower()
    return "bun" if value == "bun" else "npm"


def _node_command() -> str:
    return shutil.which("node") or "node"


def _npm_cli_script_for_node(node_command: str) -> str:
    npm_command = shutil.which("npm")
    if npm_command:
        npm_path = Path(npm_command)
        candidate_roots = [npm_path.parent, npm_path.parent.parent]
        for root in candidate_roots:
            candidate = root / "node_modules" / "npm" / "bin" / "npm-cli.js"
            if candidate.exists():
                return str(candidate)
    node_path = Path(node_command)
    candidate_roots = [node_path.parent, node_path.parent.parent]
    for root in candidate_roots:
        candidate = root / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if candidate.exists():
            return str(candidate)
    return "npm"


def _npm_install_command() -> tuple[list[str], str]:
    node_command = _node_command()
    npm_cli_script = _npm_cli_script_for_node(node_command)
    if npm_cli_script != "npm":
        return [node_command, npm_cli_script, "install"], "node npm-cli.js install"
    return ["npm", "install"], "npm install"


def _frontend_build_commands(package_manager: str, web_dir: Path) -> list[tuple[list[str], str]]:
    if package_manager == "bun":
        return [(["bun", "run", "bun:build"], "bun run bun:build")]
    node_command = _node_command()
    return [
        ([node_command, str(web_dir / "node_modules" / "typescript" / "bin" / "tsc"), "-b"], "node tsc -b"),
        ([node_command, str(web_dir / "node_modules" / "vite" / "bin" / "vite.js"), "build"], "node vite build"),
    ]


def _operator_config_path() -> Path:
    raw = os.environ.get("VIBELUTION_CONFIG_PATH", "").strip()
    if raw:
        return Path(raw)
    config_home = os.environ.get("VIBELUTION_CONFIG_HOME", "").strip()
    if not config_home:
        user_home = os.environ.get("USERPROFILE", str(Path.home()))
        config_home = str(Path(user_home) / "Documents" / "Vibelution" / "config")
    return Path(config_home) / "config.toml"


def _load_operator_config() -> dict:
    if tomllib is None:
        return {}
    config_path = _operator_config_path()
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _workbench_config() -> dict:
    payload = _load_operator_config()
    workbench = payload.get("workbench") if isinstance(payload, dict) else {}
    return workbench if isinstance(workbench, dict) else {}


def _configured_window_mode() -> str:
    env_value = os.environ.get("VIBELUTION_WORKBENCH_WINDOW_MODE") or os.environ.get("AGENT_WORKBENCH_WINDOW_MODE")
    raw = str(env_value or _workbench_config().get("window_mode") or "fullscreen").strip().lower()
    return raw if raw in {"fullscreen", "windowed"} else "fullscreen"


def _configured_window_size() -> str:
    env_value = os.environ.get("VIBELUTION_WORKBENCH_WINDOW_SIZE") or os.environ.get("AGENT_WORKBENCH_WINDOW_SIZE")
    raw = str(env_value or _workbench_config().get("window_size") or "auto").strip().lower()
    if raw == "auto":
        return raw
    parts = raw.split("x", 1)
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        width = int(parts[0])
        height = int(parts[1])
        if 320 <= width <= 7680 and 240 <= height <= 4320:
            return raw
    return "auto"


def _edge_window_size_argument(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "auto" or "x" not in normalized:
        return ""
    return normalized.replace("x", ",")


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


def _window_process_id(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = int(user32.GetWindowTextLengthW(ctypes.wintypes.HWND(hwnd)))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(ctypes.wintypes.HWND(hwnd), buffer, length + 1)
    return str(buffer.value or "")


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


def _visible_vibelution_windows() -> list[int]:
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and "Vibelution" in _window_text(int(hwnd)):
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return handles


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


def _apply_managed_browser_app_identity(browser_pid: int, role: str) -> dict[str, object]:
    app_id = "Vibelution.Launcher" if role == "launcher" else "Vibelution.Workbench"
    display_name = "Vibelution Launcher" if role == "launcher" else "Vibelution Workbench"
    icon_resource = f"{LAUNCHER_ICON_PATH},0" if LAUNCHER_ICON_PATH.exists() else ""
    if os.name != "nt":
        return {"applied": False, "windowPid": int(browser_pid), "appUserModelId": app_id, "iconResource": icon_resource, "reason": "non_windows"}
    deadline = time.monotonic() + 5.0
    last_error = ""
    while time.monotonic() < deadline:
        candidates = _visible_windows_for_process(int(browser_pid)) or _visible_vibelution_windows()
        for hwnd in candidates:
            try:
                with contextlib.suppress(OSError):
                    ctypes.windll.ole32.CoInitialize(None)
                _set_window_app_identity(int(hwnd), app_id, display_name, icon_resource)
                return {
                    "applied": True,
                    "windowPid": _window_process_id(int(hwnd)),
                    "appUserModelId": app_id,
                    "iconResource": icon_resource,
                    "hwnd": int(hwnd),
                }
            except Exception as exc:  # pragma: no cover - Windows shell integration is smoke-tested manually.
                last_error = str(exc)
        time.sleep(0.2)
    return {
        "applied": False,
        "windowPid": int(browser_pid),
        "appUserModelId": app_id,
        "iconResource": icon_resource,
        "reason": "window_not_found_or_identity_failed",
        "error": last_error,
    }


def _managed_edge_args(url: str, profile_dir: Path) -> list[str]:
    window_mode = _configured_window_mode()
    window_size = _configured_window_size()
    args = [
        f"--user-data-dir={profile_dir}",
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
    if window_mode == "fullscreen":
        args.append("--start-fullscreen")
    else:
        size_arg = _edge_window_size_argument(window_size)
        if size_arg:
            args.append(f"--window-size={size_arg}")
    return args


def _start_managed_browser(url: str) -> dict[str, object]:
    if os.name != "nt":
        return {
            "browserManaged": False,
            "browserExecutable": "",
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserProfileDir": "",
        }
    executable = _edge_executable()
    WORKBENCH_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [executable, *_managed_edge_args(url, WORKBENCH_BROWSER_PROFILE_DIR)],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
    )
    app_identity = _apply_managed_browser_app_identity(int(process.pid), "workbench")
    return {
        "browserManaged": True,
        "browserExecutable": executable,
        "browserLaunchPid": int(process.pid),
        "browserWindowPid": int(app_identity.get("windowPid") or process.pid),
        "browserProfileDir": str(WORKBENCH_BROWSER_PROFILE_DIR),
        "browserAppUserModelId": str(app_identity.get("appUserModelId") or ""),
        "browserIconResource": str(app_identity.get("iconResource") or ""),
        "browserAppIdentityApplied": bool(app_identity.get("applied")),
    }


def _preserved_launcher_control_state(state: dict) -> dict[str, object]:
    keys = (
        "launcherBackendPid",
        "launcherBackendLaunchPid",
        "launcherBrowserLaunchPid",
        "launcherBrowserWindowPid",
        "launcherBrowserProfileDir",
        "launcherControlPort",
        "launcherControlUrl",
    )
    return {key: state[key] for key in keys if key in state}


def _select_background_python(executable: str) -> dict[str, object]:
    raw = str(executable or "").strip()
    creation_flag_names = list(_windows_creation_flag_names())
    result: dict[str, object] = {
        "pythonExecutable": raw,
        "sourcePythonExecutable": raw,
        "noConsolePythonExecutable": "",
        "consoleWindowSuppressed": bool(creation_flag_names),
        "consoleSuppressionMode": "creation_flags" if creation_flag_names else "native",
        "consoleFallbackReason": "empty_python_executable",
        "pythonLaunchPolicy": "pythonw_no_console_background_service",
        "creationFlagNames": creation_flag_names,
    }
    if not raw:
        result["consoleWindowSuppressed"] = False
        result["consoleSuppressionMode"] = "none"
        result["pythonLaunchPolicy"] = "missing_python_executable"
        return result
    if os.name != "nt":
        result["consoleFallbackReason"] = "non_windows"
        result["pythonLaunchPolicy"] = "source_python_native_process"
        return result

    candidate = Path(raw)
    if candidate.name.lower() == "pythonw.exe":
        result["pythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["noConsolePythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["consoleFallbackReason"] = "" if candidate.exists() else "pythonw_executable_missing"
        return result

    sibling = candidate.with_name("pythonw.exe")
    if sibling.exists():
        resolved_sibling = str(sibling.resolve())
        result["pythonExecutable"] = resolved_sibling
        result["noConsolePythonExecutable"] = resolved_sibling
        result["consoleFallbackReason"] = ""
        return result

    if candidate.exists():
        result["pythonExecutable"] = str(candidate.resolve())
        result["consoleFallbackReason"] = "pythonw_missing"
        result["pythonLaunchPolicy"] = "source_python_hidden_creation_flags_fallback"
    else:
        result["consoleFallbackReason"] = "python_executable_missing"
        result["pythonLaunchPolicy"] = "missing_python_executable"
    return result


def _ensure_frontend_build() -> None:
    web_dir = PROJECT_ROOT / "web"
    if not web_dir.exists():
        return
    package_manager = _frontend_package_manager()
    node_modules = web_dir / "node_modules"
    needs_install = not node_modules.exists()
    dist_index = web_dir / "dist" / "index.html"
    needs_build = not dist_index.exists()
    _append_frontend_build_log(
        {
            "event": "frontend_build.ensure",
            "packageManager": package_manager,
            "needsInstall": needs_install,
            "needsBuild": needs_build,
        }
    )
    if needs_install:
        if package_manager == "bun":
            _run_checked(["bun", "install"], cwd=web_dir, label="bun install")
        else:
            install_command, install_label = _npm_install_command()
            _run_checked(install_command, cwd=web_dir, label=install_label)
    if needs_build:
        for build_command, build_label in _frontend_build_commands(package_manager, web_dir):
            _run_checked(build_command, cwd=web_dir, label=build_label)


def _start_backend(port: int, host: str, *, no_browser: bool) -> dict:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    previous_state = _read_state()
    _ensure_frontend_build()
    stdout = BACKEND_STDOUT_PATH.open("ab")
    stderr = BACKEND_STDERR_PATH.open("ab")
    python_runtime = _select_background_python(sys.executable)
    python_command = str(python_runtime["pythonExecutable"])
    args = [
        python_command,
        str(PROJECT_ROOT / "scripts" / "web_workbench.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--no-browser",
        "--managed-by-launcher",
    ]
    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        env=_backend_environment(host),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
    )
    stdout.close()
    stderr.close()
    if not _wait_for_health(port, host):
        _terminate_pid(process.pid)
        raise RuntimeError(f"Backend did not become healthy at {_health_url(port, host)}.")
    url = f"http://{host}:{int(port)}"
    browser_info: dict[str, object] = {
        "browserManaged": False,
        "browserExecutable": "",
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "browserProfileDir": "",
    }
    if not no_browser:
        try:
            browser_info = _start_managed_browser(url)
        except Exception:
            _terminate_pid(process.pid)
            raise
    state = {
        **_preserved_launcher_control_state(previous_state),
        "schemaVersion": 1,
        "launcherAdapter": "python_headless",
        "desiredState": "open",
        "observedState": "open",
        "phase": "steady",
        "sessionRole": "workbench",
        "sessionId": str(uuid.uuid4()),
        "backendPid": int(process.pid),
        "backendLaunchPid": int(process.pid),
        "browserLaunchPid": int(browser_info["browserLaunchPid"]),
        "browserWindowPid": int(browser_info["browserWindowPid"]),
        "workbenchBrowserLaunchPid": int(browser_info["browserLaunchPid"]),
        "workbenchBrowserWindowPid": int(browser_info["browserWindowPid"]),
        "browserManaged": bool(browser_info["browserManaged"]),
        "browserExecutable": str(browser_info["browserExecutable"]),
        "browserProfileDir": str(browser_info["browserProfileDir"]),
        "workbenchBrowserProfileDir": str(browser_info["browserProfileDir"]),
        "url": url,
        "host": host,
        "backendPort": int(port),
        "port": int(port),
        "statusLine": "Workbench is running.",
        "failureMessage": "",
        "lastReason": "python_launcher_start",
        "lastSource": "python_launcher",
        "pythonExecutable": python_command,
        "sourcePythonExecutable": str(python_runtime["sourcePythonExecutable"]),
        "noConsolePythonExecutable": str(python_runtime["noConsolePythonExecutable"]),
        "consoleWindowSuppressed": bool(python_runtime["consoleWindowSuppressed"]),
        "consoleSuppressionMode": str(python_runtime["consoleSuppressionMode"]),
        "consoleFallbackReason": str(python_runtime["consoleFallbackReason"]),
        "pythonLaunchPolicy": str(python_runtime["pythonLaunchPolicy"]),
        "creationFlagNames": list(python_runtime["creationFlagNames"]),
        "updatedAt": _now_iso(),
    }
    _write_state(state)
    return state


def _terminate_pid(pid: int) -> None:
    if pid <= 0 or not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _stop_backend() -> dict:
    state = _read_state()
    pid = int(state.get("backendPid") or 0)
    browser_pid = int(state.get("browserWindowPid") or state.get("browserLaunchPid") or 0)
    _terminate_pid(pid)
    _terminate_pid(browser_pid)
    next_state = {
        **state,
        "desiredState": "closed",
        "observedState": "closed",
        "phase": "steady",
        "backendPid": 0,
        "backendLaunchPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "browserManaged": False,
        "statusLine": "Workbench is closed.",
        "failureMessage": "",
        "lastReason": "python_launcher_stop",
        "lastSource": "python_launcher",
        "updatedAt": _now_iso(),
    }
    _write_state(next_state)
    return next_state


def _focus_backend(port: int, host: str) -> dict:
    state = _read_state()
    pid = int(state.get("backendPid") or 0)
    if pid > 0 and _pid_alive(pid) and _backend_healthy(port, host):
        return state
    raise RuntimeError("Workbench focus requested but no running workbench backend is available.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vibelution cross-platform launcher adapter")
    parser.add_argument("-Action", "--action", default="start")
    parser.add_argument("-NoBrowser", "--no-browser", action="store_true")
    parser.add_argument("--host", default=os.environ.get("VIBELUTION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VIBELUTION_PORT", "8000")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _assert_internal_action_authorized(args.action)
        action = _normalize_action(args.action)
        if action == "start":
            current = _read_state()
            current_pid = int(current.get("backendPid") or 0)
            if current_pid > 0 and _pid_alive(current_pid) and _backend_healthy(args.port, args.host):
                print("Workbench already running.")
                return 0
            _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            print("Workbench started.")
            return 0
        if action == "stop":
            _stop_backend()
            print("Workbench stopped.")
            return 0
        if action == "focus":
            _focus_backend(args.port, args.host)
            print("Workbench already running.")
            return 0
        if action == "restart":
            _stop_backend()
            _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            print("Workbench restarted.")
            return 0
        raise RuntimeError(f"Unsupported launcher action: {args.action}")
    except Exception as exc:
        state = _read_state()
        _write_state(
            {
                **state,
                "phase": "failed",
                "failureMessage": f"{type(exc).__name__}: {exc}",
                "lastSource": "python_launcher",
                "updatedAt": _now_iso(),
            }
        )
        print(f"Launcher failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
