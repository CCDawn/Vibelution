#!/usr/bin/env python3
"""Native no-console bridge for the Windows desktop Launcher entry."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
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

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "launcher"
STATE_PATH = RUNTIME_DIR / "state.json"
PYTHON_BRIDGE_LOG_PATH = RUNTIME_DIR / "desktop-entry-python.log"
LAUNCHER_STDOUT_PATH = RUNTIME_DIR / "launcher-backend.stdout.log"
LAUNCHER_STDERR_PATH = RUNTIME_DIR / "launcher-backend.stderr.log"
LAUNCHER_BROWSER_PROFILE_DIR = RUNTIME_DIR / "launcher-control-profile"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_WORKBENCH_PORT = 8000
DEFAULT_LAUNCHER_CONTROL_PORT = 8765
MANAGED_LAUNCHER_MARKER = "--managed-launcher-control"
SOURCE_SIGNATURE_PATHS = (
    "core/launcher/app.py",
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
    taskkill = shutil.which("taskkill")
    if taskkill:
        subprocess.run(
            [taskkill, "/PID", str(int(pid)), "/T", "/F"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_hidden_creation_flags(),
            startupinfo=_hidden_startup_info(),
            check=False,
        )
        return
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
    return int(process.pid)


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the Vibelution Launcher without a console window.")
    parser.add_argument("--action", default="launcher")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--python-exe", default="")
    parser.add_argument("--run-id", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    action = str(args.action or "launcher").strip().lower()
    if action != "launcher":
        raise SystemExit(f"Unsupported desktop-entry Python bridge action: {action}")
    try:
        _append_log("desktop_entry_python.open.started", action=action, no_browser=bool(args.no_browser), run_id=args.run_id)
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
