#!/usr/bin/env python3
"""Cross-platform headless launcher adapter for the Vibelution workbench."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes
import errno
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import tomllib


def _supervisor_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _workspace_root_from_env(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    raw = str(env.get("VIBELUTION_WORKSPACE_ROOT") or "").strip()
    if raw:
        try:
            return Path(raw).expanduser().resolve()
        except OSError:
            pass
    return _supervisor_root()


SUPERVISOR_ROOT = _supervisor_root()
PROJECT_ROOT = _workspace_root_from_env()
if str(SUPERVISOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR_ROOT))

from vibelution_storage import resolve_active_project_storage_paths


def _load_log_rotation_stdlib():
    """Load log_rotation.py without importing core.logging (pydantic / config)."""

    import importlib.util

    path = PROJECT_ROOT / "core" / "logging" / "log_rotation.py"
    spec = importlib.util.spec_from_file_location("_vibelution_launcher_log_rotation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LOG_ROTATION = _load_log_rotation_stdlib()
DEFAULT_LOG_BACKUP_COUNT = _LOG_ROTATION.DEFAULT_LOG_BACKUP_COUNT
DEFAULT_LOG_MAX_BYTES = _LOG_ROTATION.DEFAULT_LOG_MAX_BYTES
rotate_log_file = _LOG_ROTATION.rotate_log_file
append_rotating_text = _LOG_ROTATION.append_rotating_text
write_log_tail_copy = _LOG_ROTATION.write_log_tail_copy

PROJECT_STORAGE = resolve_active_project_storage_paths(PROJECT_ROOT)
RUNTIME_DIR = PROJECT_STORAGE.runtime / "launcher"
STATE_PATH = RUNTIME_DIR / "state.json"
PORTS_PATH = RUNTIME_DIR / "ports.json"
ACTIVE_RUNTIME_SCENE_PATH = RUNTIME_DIR / "active-runtime-scene.json"
RUNTIME_SCENE_ROOT = PROJECT_STORAGE.logs / "runtime_scenes"
BACKEND_STDOUT_PATH = RUNTIME_DIR / "backend.stdout.log"
BACKEND_STDERR_PATH = RUNTIME_DIR / "backend.stderr.log"
FRONTEND_BUILD_LOG_PATH = RUNTIME_DIR / "frontend-build.log"
FRONTEND_BUILD_PROVENANCE_NAME = ".vibelution-build.json"
WORKBENCH_BROWSER_PROFILE_DIR = RUNTIME_DIR / "workbench-app-profile"
LAUNCHER_ICON_PATH = PROJECT_ROOT / "assets" / "icons" / "vibelution.ico"
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
REQUIREMENT_IMPORT_NAME_OVERRIDES = {
    "pytest-xdist": "xdist",
    "pywinpty": "winpty",
    # Package installs under langgraph.checkpoint.sqlite (no top-level module).
    "langgraph-checkpoint-sqlite": "langgraph.checkpoint.sqlite",
    "langgraph-checkpoint": "langgraph.checkpoint",
    "langgraph-prebuilt": "langgraph.prebuilt",
    "langgraph-sdk": "langgraph_sdk",
}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
TRUSTED_WEB_HOSTS_ENV = "VIBELUTION_TRUSTED_WEB_HOSTS"
FRONTEND_PACKAGE_MANAGER_ENV = "VIBELUTION_FRONTEND_PM"
INTERNAL_LAUNCHER_ENV = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
INTERNAL_ACTIONS = {"internal-start", "internal-focus", "internal-stop", "internal-restart"}
RUNTIME_SAFE_UNTRACKED_PREFIXES = ("scripts/_tmp_stash_p3_manifest/",)

LAUNCHER_SCENE_RAW_MAP = (
    ("backend.stdout.log", "raw/backend.stdout.log"),
    ("backend.stderr.log", "raw/backend.stderr.log"),
    ("launcher-control.log", "raw/launcher-control.log"),
    ("frontend-build.log", "raw/frontend.build.log"),
)


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


def _start_runtime_scene(trigger: str) -> dict[str, str]:
    _seal_active_runtime_scene(
        "orphan_reconciled",
        "Previous active scene was superseded by a fresh Launcher start.",
    )
    started_at = datetime.now(timezone.utc)
    scene_id = uuid.uuid4().hex[:12]
    directory_name = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}__{scene_id}"
    scene_dir = RUNTIME_SCENE_ROOT / directory_name
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        (scene_dir / relative_dir).mkdir(parents=True, exist_ok=True)

    reference = {
        "runtimeSceneId": scene_id,
        "runtimeSceneDir": str(scene_dir.resolve()),
        "startedAt": started_at.isoformat(),
        "launcherPid": os.getpid(),
        "trigger": str(trigger or "python_launcher"),
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = ACTIVE_RUNTIME_SCENE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(ACTIVE_RUNTIME_SCENE_PATH)
    return reference


def _rotate_launcher_process_logs_before_start() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for name, _scene_relative in LAUNCHER_SCENE_RAW_MAP:
        rotate_log_file(
            RUNTIME_DIR / name,
            max_bytes=DEFAULT_LOG_MAX_BYTES,
            backup_count=DEFAULT_LOG_BACKUP_COUNT,
        )


def _sync_launcher_logs_to_scene_raw(scene_dir: Path) -> None:
    if not scene_dir.is_dir():
        return
    for launcher_name, scene_relative in LAUNCHER_SCENE_RAW_MAP:
        write_log_tail_copy(RUNTIME_DIR / launcher_name, scene_dir / scene_relative)


def _seal_active_runtime_scene(result: str, stop_reason: str) -> dict[str, object]:
    """Idempotently seal the active scene without clearing its current pointer."""
    try:
        reference = json.loads(ACTIVE_RUNTIME_SCENE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"sealed": False, "reason": "active_scene_unavailable"}
    if not isinstance(reference, dict):
        return {"sealed": False, "reason": "active_scene_invalid"}
    scene_dir_text = str(reference.get("runtimeSceneDir") or "").strip()
    if not scene_dir_text:
        return {"sealed": False, "reason": "scene_dir_missing"}
    try:
        scene_dir = Path(scene_dir_text).resolve()
        scene_dir.relative_to(RUNTIME_SCENE_ROOT.resolve())
    except (OSError, ValueError):
        return {"sealed": False, "reason": "scene_dir_outside_root"}
    if not scene_dir.is_dir():
        return {"sealed": False, "reason": "scene_dir_unavailable"}

    _sync_launcher_logs_to_scene_raw(scene_dir)
    manifest_path = scene_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if str(manifest.get("ended_at") or "").strip():
        return {"sealed": False, "reason": "already_sealed", "sceneDir": str(scene_dir)}

    ended_at = _now_iso()
    manifest.update(
        {
            "schema_version": int(manifest.get("schema_version") or 2),
            "runtime_scene_id": str(
                manifest.get("runtime_scene_id") or reference.get("runtimeSceneId") or scene_dir.name
            ),
            "started_at": str(manifest.get("started_at") or reference.get("startedAt") or ended_at),
            "ended_at": ended_at,
            "status": "stopped",
            "result": str(result or "orphan_reconciled"),
            "stop_reason": str(stop_reason or "Runtime scene reconciled closed."),
            "project_root": str(manifest.get("project_root") or PROJECT_ROOT),
        }
    )
    temp_path = manifest_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return {"sealed": True, "reason": manifest["result"], "sceneDir": str(scene_dir)}


def _pid_probe(pid: int) -> str:
    """Return "alive", "dead" or "unknown" for a pid.

    psutil.pid_exists checks the Windows exit status (STILL_ACTIVE), so it
    correctly reports "dead" for processes that are exiting but still hold
    a queryable handle. os.kill(pid, 0) is the fallback when psutil is
    unavailable: ProcessLookupError (POSIX) / WinError 87 (Windows) mean
    dead, access denial (WinError 5) means the process exists but cannot
    be inspected -> unknown.
    """
    if pid <= 0:
        return "dead"
    try:
        import psutil  # type: ignore
    except ImportError:
        pass
    else:
        try:
            if psutil.pid_exists(pid):
                return "alive"
            return "dead"
        except psutil.Error:
            return "unknown"
    try:
        os.kill(pid, 0)
        return "alive"
    except ProcessLookupError:
        return "dead"
    except OSError as exc:
        if getattr(exc, "winerror", None) == 87:
            return "dead"
        if getattr(exc, "errno", None) == errno.ESRCH:
            return "dead"
    return "unknown"


def _pid_alive(pid: int) -> bool:
    return _pid_probe(pid) == "alive"


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


def _listening_pid_for_port(port: int) -> int:
    """Return the listening TCP owner without trusting launcher state."""

    if int(port or 0) <= 0:
        return 0
    try:
        import psutil

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
        pass
    if os.name != "nt":
        return _posix_listening_pid_for_port(port)
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            timeout=3,
            check=False,
            creationflags=_windows_creation_flags(),
            startupinfo=_hidden_startup_info(),
            **_subprocess_text_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    pattern = re.compile(rf"^\s*TCP\s+\S+:{int(port)}\s+\S+\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
    for line in str(result.stdout or "").splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1))
    return 0


def _posix_listening_pid_for_port(port: int) -> int:
    """Return a Linux listener PID using ``ss`` when the launcher lacks psutil."""

    try:
        result = subprocess.run(
            ["ss", "-ltnp", f"sport = :{int(port)}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=3,
            check=False,
            **_subprocess_text_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    for raw_pid in re.findall(r"\bpid=(\d+)", str(result.stdout or "")):
        pid = int(raw_pid)
        if pid > 0:
            return pid
    return 0


def _posix_parent_pid(pid: int) -> int:
    """Read a process parent PID from procfs without importing optional packages."""

    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        fields = raw.rsplit(")", 1)[1].strip().split()
        return int(fields[1]) if len(fields) >= 2 else 0
    except (OSError, IndexError, TypeError, ValueError):
        return 0


def _posix_process_command_line(pid: int) -> str:
    """Read an argv vector from procfs without exposing environment values."""

    try:
        values = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except (OSError, TypeError, ValueError):
        return ""
    return " ".join(value.decode("utf-8", errors="replace") for value in values if value)


def _pid_belongs_to_process_tree(pid: int, root_pid: int) -> bool:
    if pid <= 0 or root_pid <= 0:
        return False
    if pid == root_pid:
        return True
    try:
        import psutil

        process = psutil.Process(pid)
        return any(int(parent.pid) == root_pid for parent in process.parents())
    except Exception:
        if os.name == "nt":
            return False
    current_pid = int(pid)
    seen: set[int] = set()
    while current_pid > 0 and current_pid not in seen:
        if current_pid == root_pid:
            return True
        seen.add(current_pid)
        current_pid = _posix_parent_pid(current_pid)
    return False


def _is_project_workbench_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        command_line = " ".join(psutil.Process(pid).cmdline())
    except Exception:
        if os.name == "nt":
            return False
        command_line = _posix_process_command_line(pid)
    if not command_line:
        return False
    expected_script = str(PROJECT_ROOT / "scripts" / "web_workbench.py")
    # Require this checkout's project root so sibling checkouts (e.g. live-acceptance)
    # are never treated as the same managed workbench.
    project_marker = str(PROJECT_ROOT).lower()
    command_lower = command_line.lower()
    return expected_script.lower() in command_lower and project_marker in command_lower


def _read_project_ports() -> dict:
    try:
        payload = json.loads(PORTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_project_ports(ports: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PORTS_PATH.write_text(json.dumps(ports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _saved_project_backend_port() -> int:
    ports = _read_project_ports()
    try:
        port = int(ports.get("backendPort") or 0)
    except (TypeError, ValueError):
        return 0
    return port if 0 < port < 65536 else 0


def _remember_project_backend_port(port: int, *, reason: str = "") -> None:
    if int(port or 0) <= 0:
        return
    payload = {
        **_read_project_ports(),
        "schemaVersion": 1,
        "backendPort": int(port),
        "projectRoot": str(PROJECT_ROOT),
        "updatedAt": _now_iso(),
    }
    if reason:
        payload["lastReason"] = str(reason)
    _write_project_ports(payload)


def _find_free_backend_port(preferred: int, *, max_tries: int = 48) -> int:
    """Pick a free TCP listen port starting at preferred, then preferred+1…"""

    base = int(preferred or DEFAULT_PORT)
    if base <= 0 or base >= 65536:
        base = DEFAULT_PORT
    for offset in range(max(1, int(max_tries))):
        candidate = base + offset
        if candidate >= 65536:
            candidate = DEFAULT_PORT + (offset % 1000)
        if candidate <= 0 or candidate >= 65536:
            continue
        if _listening_pid_for_port(candidate) <= 0:
            return int(candidate)
    raise RuntimeError(
        f"No free workbench backend port found near {base} "
        f"(scanned {max_tries} candidates). Stop the other project or set VIBELUTION_PORT."
    )


def _resolve_start_backend_port(preferred: int, host: str) -> tuple[int, str]:
    """
    Resolve a bindable backend port for this project checkout.

    Fresh-start policy: never reuse a live workbench. Callers must retire this
    project's managed handles before resolve. After retire:

    - Free preferred port → use it
    - Preferred still owned by this project's workbench → hard error (retire failed)
    - Preferred owned by another process/project → auto-pick a free port and remember it
    """

    preferred_port = int(preferred or DEFAULT_PORT)
    if preferred_port <= 0:
        preferred_port = DEFAULT_PORT
    owner_pid = _listening_pid_for_port(preferred_port)
    if owner_pid <= 0:
        return preferred_port, ""
    if _is_project_workbench_pid(owner_pid):
        raise RuntimeError(
            f"Workbench port {preferred_port} is still held by this project's process "
            f"pid {owner_pid} after instance retire; cannot start a fresh handle-aligned instance."
        )
    free_port = _find_free_backend_port(preferred_port + 1)
    _remember_project_backend_port(
        free_port,
        reason=f"auto_relocated_from_{preferred_port}_occupied_by_pid_{owner_pid}",
    )
    return free_port, (
        f"port {preferred_port} occupied by foreign pid {owner_pid}; "
        f"auto-bound this project to {free_port}"
    )


def _collect_project_workbench_handles(state: dict, port: int | None = None) -> list[int]:
    """Collect OS process handles (PIDs) owned by this project's workbench instance."""
    handles: set[int] = set()
    for key in (
        "backendPid",
        "backendLaunchPid",
        "browserLaunchPid",
        "browserWindowPid",
        "workbenchBrowserLaunchPid",
        "workbenchBrowserWindowPid",
    ):
        pid = int(state.get(key) or 0)
        if pid > 0:
            handles.add(pid)
    resolved_port = int(
        port
        if port is not None
        else (state.get("backendPort") or state.get("port") or 0)
        or 0
    )
    if resolved_port > 0:
        owner_pid = _listening_pid_for_port(resolved_port)
        if owner_pid > 0 and _is_project_workbench_pid(owner_pid):
            handles.add(owner_pid)
    return sorted(pid for pid in handles if pid > 0)


def _retire_project_workbench_instance(state: dict, port: int | None = None) -> list[int]:
    """Terminate every managed handle for this project's previous workbench instance.

    Returns the retired handle list (PIDs that were targeted). Fresh start must not
    attach to any of these handles afterwards.
    """
    resolved_port = int(
        port
        if port is not None
        else (state.get("backendPort") or state.get("port") or DEFAULT_PORT)
        or DEFAULT_PORT
    )
    handles = _collect_project_workbench_handles(state, resolved_port)
    termination_failures: list[str] = []
    for pid in sorted(handles, reverse=True):
        reason = _terminate_pid(pid)
        if reason:
            termination_failures.append(reason)
    # Port may still be TIME_WAIT or a slow child — wait for this project's listener to leave.
    if resolved_port > 0:
        owner = _listening_pid_for_port(resolved_port)
        if owner > 0 and _is_project_workbench_pid(owner):
            reason = _terminate_pid(owner)
            if reason:
                termination_failures.append(reason)
            if not _wait_for_port_release(resolved_port):
                still = _listening_pid_for_port(resolved_port)
                if still > 0 and _is_project_workbench_pid(still):
                    detail = (
                        f" Termination failures: {'; '.join(termination_failures)}."
                        if termination_failures
                        else ""
                    )
                    raise RuntimeError(
                        f"Failed to retire previous workbench on port {resolved_port} "
                        f"(still held by project pid {still}).{detail}"
                    )
    return handles


def _wait_for_port_release(port: int, timeout_seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _listening_pid_for_port(port) <= 0:
            return True
        time.sleep(0.2)
    return _listening_pid_for_port(port) <= 0


def _wait_for_started_backend(process: subprocess.Popen[bytes], port: int, host: str, timeout_seconds: float = 45.0) -> int:
    """Wait for health only when this launch owns the listening port."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return 0
        if not _backend_healthy(port, host):
            time.sleep(0.35)
            continue
        owner_pid = _listening_pid_for_port(port)
        if owner_pid > 0:
            if _pid_belongs_to_process_tree(owner_pid, int(process.pid)):
                return owner_pid
            time.sleep(0.35)
            continue
        # Fresh Linux clones often run the launcher with system Python: no
        # psutil, and `ss` may be absent. Health is already 200 and this spawn
        # is still alive, so treat it as the owner instead of killing it.
        return int(process.pid)
    return 0


def _windows_creation_flag_names(*, detach: bool = False) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    # MSDN: CREATE_NO_WINDOW is ignored when combined with DETACHED_PROCESS.
    # Waitable children (tsc/vite/npm-cli/git): CREATE_NO_WINDOW only.
    # True background pythonw services: DETACHED + CREATE_NEW_PROCESS_GROUP.
    if detach:
        return ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP")
    return ("CREATE_NO_WINDOW",)


def _windows_creation_flags(*, detach: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = 0
    for name in _windows_creation_flag_names(detach=detach):
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
        # Waitable + no console: never DETACHED, never npm.cmd shell.
        creationflags=_windows_creation_flags(detach=False),
        startupinfo=_hidden_startup_info(),
        check=False,
        **_subprocess_text_kwargs(),
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


def _resolve_git_executable() -> str:
    """Prefer Git mingw64 git.exe; avoid Git\\cmd trampoline console flash."""
    try:
        from core.infrastructure.no_console_git import resolve_git_executable

        return resolve_git_executable()
    except Exception:
        if os.name == "nt":
            for root in (
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramW6432"),
                os.environ.get("ProgramFiles(x86)"),
                r"C:\Program Files",
            ):
                if not root:
                    continue
                mingw = Path(root) / "Git" / "mingw64" / "bin" / "git.exe"
                try:
                    if mingw.is_file() and mingw.stat().st_size > 200_000:
                        return str(mingw.resolve())
                except OSError:
                    continue
        return shutil.which("git.exe" if os.name == "nt" else "git") or shutil.which("git") or "git"


def _run_capture(args: list[str], *, cwd: Path, label: str, timeout: float = 15.0) -> str:
    env = os.environ.copy()
    first = Path(str(args[0] if args else "")).name.lower()
    if first in {"git", "git.exe"} or first.endswith("git.exe"):
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GCM_INTERACTIVE", "never")
        env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    result = subprocess.run(
        args,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        env=env,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
        check=False,
        **_subprocess_text_kwargs(),
    )
    if result.returncode != 0:
        detail = _process_output_tail(result.stderr or result.stdout, max_lines=8, max_chars=1200)
        raise RuntimeError(f"{label} failed with exit code {result.returncode}{f': {detail}' if detail else '.'}")
    return str(result.stdout or "").strip()


ALLOW_DIRTY_LAUNCH_ENV = "VIBELUTION_ALLOW_DIRTY_LAUNCH"
ALLOW_NON_MAIN_LAUNCH_ENV = "VIBELUTION_ALLOW_NON_MAIN_LAUNCH"


def _subprocess_text_kwargs() -> dict[str, object]:
    """Decode child stdout/stderr without crashing the reader thread on Windows.

    Hidden console processes often emit locale bytes (e.g. GBK/cp936). Using
    strict utf-8 with text=True raises UnicodeDecodeError inside
    subprocess._readerthread; errors=replace keeps the launcher stable.
    """

    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


def _allow_non_main_launch() -> bool:
    raw = str(os.environ.get(ALLOW_NON_MAIN_LAUNCH_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _path_looks_like_task_worktree(root: Path) -> bool:
    """True when project path is under the fixed task-worktree roots."""

    parts = [part.lower() for part in Path(root).resolve().parts]
    for index, part in enumerate(parts):
        if part == ".worktrees" and index + 1 < len(parts) and parts[index + 1] != "_retired":
            return True
        if part in {"vibelution-worktrees", ".claude"} and index + 1 < len(parts):
            if part == "vibelution-worktrees":
                return True
            if part == ".claude" and parts[index + 1] == "worktrees":
                return True
    return False


def _is_linked_git_worktree(cwd: Path, git_command: str) -> bool:
    """True when cwd is a secondary git worktree (git-dir != common-dir)."""

    try:
        git_dir = _run_capture(
            [git_command, "rev-parse", "--git-dir"],
            cwd=cwd,
            label="git dir identity",
            timeout=8.0,
        )
        common_dir = _run_capture(
            [git_command, "rev-parse", "--git-common-dir"],
            cwd=cwd,
            label="git common-dir identity",
            timeout=8.0,
        )
    except RuntimeError:
        return False
    try:
        git_path = Path(git_dir)
        common_path = Path(common_dir)
        if not git_path.is_absolute():
            git_path = (cwd / git_path).resolve()
        else:
            git_path = git_path.resolve()
        if not common_path.is_absolute():
            common_path = (cwd / common_path).resolve()
        else:
            common_path = common_path.resolve()
        return git_path != common_path
    except OSError:
        return False


def _assert_launcher_branch_allowed(branch: str, *, resolved_root: Path, git_command: str) -> None:
    """Integration root must stay on main; task worktrees may use task branches."""

    if branch == "main":
        return
    if _allow_non_main_launch():
        return
    if _path_looks_like_task_worktree(resolved_root) or _is_linked_git_worktree(resolved_root, git_command):
        return
    raise RuntimeError(
        "Launcher start/restart requires the integration checkout on local main, "
        f"but current branch is {branch or '<detached>'}. "
        "Restore root with `git checkout main`, or launch a task worktree via "
        "`--project <...\\.worktrees\\<slug>>`. "
        f"Emergency override: set {ALLOW_NON_MAIN_LAUNCH_ENV}=1."
    )


def _allow_dirty_launch() -> bool:
    """Permit dirty worktrees for explicit tray rebuild/start local-dev launches."""

    return str(os.environ.get(ALLOW_DIRTY_LAUNCH_ENV) or "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _runtime_relevant_worktree_status(worktree_status: str) -> tuple[list[str], int]:
    """Keep runtime source checks strict while ignoring the preserved user-scene manifest."""

    relevant: list[str] = []
    ignored_user_scene_entries = 0
    for raw_line in str(worktree_status or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("?? "):
            relevant.append(raw_line)
            continue
        path = line[3:].replace("\\", "/")
        if any(path.startswith(prefix) for prefix in RUNTIME_SAFE_UNTRACKED_PREFIXES):
            ignored_user_scene_entries += 1
            continue
        relevant.append(raw_line)
    return relevant, ignored_user_scene_entries


def _runtime_source_identity(*, allow_dirty: bool | None = None) -> dict[str, object]:
    allow_dirty_worktree = _allow_dirty_launch() if allow_dirty is None else bool(allow_dirty)
    git_command = _resolve_git_executable()
    root_text = _run_capture(
        [git_command, "rev-parse", "--show-toplevel"],
        cwd=PROJECT_ROOT,
        label="git root identity",
    )
    resolved_root = Path(root_text).resolve()
    if resolved_root != PROJECT_ROOT.resolve():
        raise RuntimeError(
            f"Launcher project root mismatch: expected {PROJECT_ROOT.resolve()}, got {resolved_root}."
        )

    branch = _run_capture(
        [git_command, "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        label="git branch identity",
    )
    _assert_launcher_branch_allowed(branch, resolved_root=resolved_root, git_command=git_command)

    commit = _run_capture(
        [git_command, "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        label="git commit identity",
    )
    worktree_status = _run_capture(
        [git_command, "status", "--porcelain", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
        label="git worktree identity",
    )
    relevant_worktree_status, ignored_user_scene_entries = _runtime_relevant_worktree_status(worktree_status)
    tracked_clean = not bool(relevant_worktree_status)
    if relevant_worktree_status and not allow_dirty_worktree:
        preview = " | ".join(relevant_worktree_status[:8])
        raise RuntimeError(
            "Launcher restart requires a clean local main so runtime code cannot drift from HEAD"
            f": {preview}"
        )

    frontend_tree = _run_capture(
        [git_command, "rev-parse", "HEAD:web"],
        cwd=PROJECT_ROOT,
        label="frontend tree identity",
    )
    return {
        "projectRoot": str(resolved_root),
        "branch": branch,
        "commit": commit,
        "frontendTree": frontend_tree,
        "trackedClean": tracked_clean,
        "allowDirty": allow_dirty_worktree,
        "ignoredUserSceneEntries": ignored_user_scene_entries,
    }


def _runtime_source_identity_light(*, allow_dirty: bool | None = None) -> dict[str, object]:
    """Cheap mid-start recheck: branch/commit/frontend tree only (no porcelain scan)."""

    allow_dirty_worktree = _allow_dirty_launch() if allow_dirty is None else bool(allow_dirty)
    git_command = _resolve_git_executable()
    root_text = _run_capture(
        [git_command, "rev-parse", "--show-toplevel"],
        cwd=PROJECT_ROOT,
        label="git root identity",
    )
    resolved_root = Path(root_text).resolve()
    branch = _run_capture(
        [git_command, "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        label="git branch identity",
    )
    commit = _run_capture(
        [git_command, "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        label="git commit identity",
    )
    frontend_tree = _run_capture(
        [git_command, "rev-parse", "HEAD:web"],
        cwd=PROJECT_ROOT,
        label="frontend tree identity",
    )
    return {
        "projectRoot": str(resolved_root),
        "branch": branch,
        "commit": commit,
        "frontendTree": frontend_tree,
        "trackedClean": True,
        "allowDirty": allow_dirty_worktree,
        "ignoredUserSceneEntries": [],
        "light": True,
    }


def _assert_runtime_source_identity(
    expected: dict[str, object],
    *,
    light: bool = False,
) -> dict[str, object]:
    allow_dirty = bool(expected.get("allowDirty"))
    if light:
        current = _runtime_source_identity_light(allow_dirty=allow_dirty)
    elif allow_dirty:
        current = _runtime_source_identity(allow_dirty=True)
    else:
        current = _runtime_source_identity()
    for field in ("projectRoot", "branch", "commit", "frontendTree"):
        if str(current.get(field) or "") != str(expected.get(field) or ""):
            raise RuntimeError(
                "Local main changed while Launcher was refreshing; refusing to start a mixed runtime"
                f" ({field}: {expected.get(field)!r} -> {current.get(field)!r})."
            )
    return current


def _read_frontend_build_provenance(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_frontend_build_provenance(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _append_frontend_build_log(payload: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": _now_iso(),
        **payload,
    }
    result = append_rotating_text(
        FRONTEND_BUILD_LOG_PATH,
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n",
    )
    if result.get("errorType"):
        raise OSError(str(result.get("errorMessage") or "frontend build log append failed"))


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
    resolved = shutil.which("node")
    if resolved:
        return resolved
    if os.name == "nt":
        candidates: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name, "").strip()
            if root:
                candidates.append(Path(root) / "nodejs" / "node.exe")
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "nodejs" / "node.exe")
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return "node"


def _npm_cli_script_for_node(node_command: str) -> str:
    """Resolve npm-cli.js so we never invoke npm.cmd (console flash on Windows)."""
    candidates: list[Path] = []
    for which_name in ("npm", "npm.cmd"):
        npm_command = shutil.which(which_name)
        if not npm_command:
            continue
        npm_path = Path(npm_command)
        resolved = npm_path.resolve()
        if resolved.is_file() and resolved.name == "npm-cli.js":
            return str(resolved)
        candidates.extend([npm_path.parent, npm_path.parent.parent])
    node_path = Path(node_command)
    candidates.extend([node_path.parent, node_path.parent.parent])
    relative_cli_paths = (
        Path("node_modules") / "npm" / "bin" / "npm-cli.js",
        Path("lib") / "node_modules" / "npm" / "bin" / "npm-cli.js",
    )
    for root in candidates:
        for relative in relative_cli_paths:
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError(
        "npm-cli.js was not found next to Node.js/npm. "
        "Install Node.js with npm, or repair the Node installation. "
        "Refusing to run npm.cmd (it opens a visible console on Windows)."
    )


def _npm_install_command() -> tuple[list[str], str]:
    node_command = _node_command()
    npm_cli_script = _npm_cli_script_for_node(node_command)
    # ci keeps package-lock.json untouched so the clean-worktree launch guard
    # does not fail on a first-run clone after frontend bootstrap.
    return [node_command, npm_cli_script, "ci"], "node npm-cli.js ci"


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
        # Reject unusable chrome sizes (e.g. 320x240) so startup falls back to auto.
        if 960 <= width <= 7680 and 600 <= height <= 4320:
            return raw
    return "auto"


def _configured_window_position() -> str:
    env_value = os.environ.get("VIBELUTION_WORKBENCH_WINDOW_POSITION") or os.environ.get(
        "AGENT_WORKBENCH_WINDOW_POSITION"
    )
    raw = str(env_value or _workbench_config().get("window_position") or "auto").strip().lower()
    if raw == "auto":
        return raw
    parts = raw.split(",", 1)
    if len(parts) == 2:
        try:
            x = int(parts[0].strip())
            y = int(parts[1].strip())
        except ValueError:
            return "auto"
        # Reject extreme sentinels (e.g. -20000,-20000) that open fully off-screen.
        if -8000 <= x <= 8000 and -8000 <= y <= 8000:
            return f"{x},{y}"
    return "auto"


def _edge_window_size_argument(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "auto" or "x" not in normalized:
        return ""
    return normalized.replace("x", ",")


def _edge_window_position_argument(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "auto" or "," not in normalized:
        return ""
    parts = normalized.split(",", 1)
    try:
        x = int(parts[0].strip())
        y = int(parts[1].strip())
    except ValueError:
        return ""
    if -8000 <= x <= 8000 and -8000 <= y <= 8000:
        return f"{x},{y}"
    return ""


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
_MANAGED_BROWSER_IDENTITY_TIMEOUT_SECONDS = 0.8
_MANAGED_BROWSER_IDENTITY_POLL_SECONDS = 0.1


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


def _managed_browser_pids_for_profile(profile_dir: Path) -> list[int]:
    """Return Edge processes that explicitly belong to this managed profile.

    Chromium commonly hands the app window to a child PID rather than the PID
    returned by ``Popen``. Restrict the fallback to the dedicated workbench
    profile so another Edge window can never receive Vibelution identity.
    """

    if os.name != "nt":
        return []
    try:
        import psutil  # type: ignore
    except ImportError:
        return []

    profile_text = str(profile_dir).lower()
    profile_text_alt = profile_text.replace("\\", "/")
    pids: list[int] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(process.info.get("name") or "").lower()
            if name not in {"msedge.exe", "msedgewebview2.exe"}:
                continue
            command_line = " ".join(str(item) for item in (process.info.get("cmdline") or [])).lower()
            command_line_alt = command_line.replace("\\", "/")
            if profile_text not in command_line and profile_text_alt not in command_line_alt:
                continue
            pid = int(process.info.get("pid") or 0)
            if pid > 0 and pid not in pids:
                pids.append(pid)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return pids


def _managed_browser_window_candidates(browser_pid: int, role: str) -> list[dict[str, object]]:
    """Find only visible windows owned by this exact managed browser profile."""

    candidates: list[dict[str, object]] = []
    seen: set[int] = set()

    for hwnd in _visible_windows_for_process(int(browser_pid)):
        if hwnd in seen:
            continue
        seen.add(hwnd)
        candidates.append({
            "hwnd": int(hwnd),
            "processId": _window_process_id(int(hwnd)),
            "resolvedBy": "launch_pid",
        })

    # Common case: Edge retained the initial app process as its window owner.
    # Do not scan every system Edge process after this exact match succeeds.
    if candidates:
        return candidates

    profile_dir = WORKBENCH_BROWSER_PROFILE_DIR
    for pid in _managed_browser_pids_for_profile(profile_dir):
        for hwnd in _visible_windows_for_process(int(pid)):
            if hwnd in seen:
                continue
            seen.add(hwnd)
            candidates.append({
                "hwnd": int(hwnd),
                "processId": _window_process_id(int(hwnd)),
                "resolvedBy": "workbench_profile",
            })
    return candidates


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


def _apply_managed_browser_app_identity(
    browser_pid: int,
    role: str,
    *,
    app_id: str = "",
    display_name: str = "",
) -> dict[str, object]:
    resolved_app_id = str(app_id or "").strip() or (
        "Vibelution.Launcher" if role == "launcher" else "Vibelution.Workbench"
    )
    resolved_display_name = str(display_name or "").strip() or (
        "Vibelution Launcher" if role == "launcher" else "Vibelution Workbench"
    )
    app_id = resolved_app_id
    display_name = resolved_display_name
    icon_resource = f"{LAUNCHER_ICON_PATH},0" if LAUNCHER_ICON_PATH.exists() else ""
    if os.name != "nt":
        return {"applied": False, "windowPid": int(browser_pid), "appUserModelId": app_id, "iconResource": icon_resource, "reason": "non_windows"}
    deadline = time.monotonic() + _MANAGED_BROWSER_IDENTITY_TIMEOUT_SECONDS
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
                window_icon_applied = _apply_window_icon(int(hwnd), LAUNCHER_ICON_PATH)
                _set_window_title(hwnd, display_name)
                return {
                    "applied": True,
                    "windowIconApplied": bool(window_icon_applied),
                    "windowPid": _window_process_id(hwnd),
                    "appUserModelId": app_id,
                    "iconResource": icon_resource,
                    "hwnd": hwnd,
                    "resolvedBy": str(candidate.get("resolvedBy") or ""),
                }
            except Exception as exc:  # pragma: no cover - Windows shell integration is smoke-tested manually.
                last_error = str(exc)
        time.sleep(_MANAGED_BROWSER_IDENTITY_POLL_SECONDS)
    return {
        "applied": False,
        "windowIconApplied": False,
        "windowPid": int(browser_pid),
        "appUserModelId": app_id,
        "iconResource": icon_resource,
        "reason": "window_not_found_or_identity_failed",
        "error": last_error,
        "candidateCount": len(last_candidates),
        "candidateSources": [str(candidate.get("resolvedBy") or "") for candidate in last_candidates],
    }


def _managed_edge_args(url: str, profile_dir: Path) -> list[str]:
    window_mode = _configured_window_mode()
    window_size = _configured_window_size()
    window_position = _configured_window_position()
    args = [
        f"--user-data-dir={profile_dir}",
        f"--app={url}",
        # Do not pass --force-dark-mode: it forces Chromium auto-dark against the
        # workbench's own data-theme / custom background and causes whole-window flicker.
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
        position_arg = _edge_window_position_argument(window_position)
        if position_arg:
            args.append(f"--window-position={position_arg}")
    return args


def _set_window_title(hwnd: int, title: str) -> bool:
    text = str(title or "").strip()
    if os.name != "nt" or int(hwnd or 0) <= 0 or not text:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowTextW.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR)
        user32.SetWindowTextW.restype = ctypes.wintypes.BOOL
        return bool(user32.SetWindowTextW(ctypes.wintypes.HWND(int(hwnd)), text))
    except Exception:
        return False


def start_named_workbench_browser(
    url: str,
    *,
    profile_dir: Path | None = None,
    app_id: str = "",
    display_name: str = "",
) -> dict[str, object]:
    """Open a visible Edge --app window with a caller-chosen taskbar identity."""

    if os.name != "nt":
        return {
            "browserManaged": False,
            "browserExecutable": "",
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserProfileDir": str(profile_dir or ""),
        }
    resolved_profile = Path(profile_dir) if profile_dir is not None else WORKBENCH_BROWSER_PROFILE_DIR
    executable = _edge_executable()
    resolved_profile.mkdir(parents=True, exist_ok=True)
    # Edge is the user-visible Workbench surface.  The no-console policy applies
    # to background service children, not this GUI process.
    process = subprocess.Popen(
        [executable, *_managed_edge_args(url, resolved_profile)],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    app_identity = _apply_managed_browser_app_identity(
        int(process.pid),
        "workbench",
        app_id=app_id,
        display_name=display_name,
    )
    window_pid = int(app_identity.get("windowPid") or process.pid)
    # Collapse dual Edge --app frames (blank shell + titled workbench) under the
    # same profile process. Import is local to avoid circular import at module load.
    converge: dict[str, object] = {}
    try:
        from core.runtime_manager.workbench_controller import _converge_browser_windows

        converge = dict(_converge_browser_windows(int(window_pid), focus_kept=True) or {})
        kept_hwnd = int(converge.get("keptHwnd") or 0)
        if kept_hwnd > 0 and display_name:
            _set_window_title(kept_hwnd, display_name)
    except Exception:
        converge = {}
    return {
        "browserManaged": True,
        "browserExecutable": executable,
        "browserLaunchPid": int(process.pid),
        "browserWindowPid": int(window_pid),
        "browserProfileDir": str(resolved_profile),
        "browserAppUserModelId": str(app_identity.get("appUserModelId") or ""),
        "browserIconResource": str(app_identity.get("iconResource") or ""),
        "browserAppIdentityApplied": bool(app_identity.get("applied")),
        "browserWindowIconApplied": bool(app_identity.get("windowIconApplied")),
        "browserWindowKeptHwnd": int(converge.get("keptHwnd") or 0),
        "browserWindowClosedCount": len(list(converge.get("closedHwnds") or [])),
    }


def _start_managed_browser(_url: str) -> dict[str, object]:
    raise RuntimeError(
        "Electron desktop shell is unavailable. Refusing Edge fallback. "
        "Start or rebuild dist/desktop/win-unpacked/Vibelution.exe."
    )


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


def _venv_python_for(venv_dir: Path) -> Path:
    """Interpreter inside a virtualenv directory (POSIX: .venv/bin/python)."""

    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_python_executable() -> Path:
    """Project-local virtual environment interpreter (POSIX: .venv/bin/python)."""

    return _venv_python_for(VENV_DIR)


def _isolated_workspace() -> bool:
    try:
        return PROJECT_ROOT.resolve() != SUPERVISOR_ROOT.resolve()
    except OSError:
        return False


def _is_supervisor_venv_python(python_executable: str) -> bool:
    raw = str(python_executable or "").strip()
    if not raw:
        return False
    try:
        resolved = Path(raw).resolve()
        supervisor_venv = (SUPERVISOR_ROOT / ".venv").resolve()
        return resolved == supervisor_venv or supervisor_venv in resolved.parents
    except OSError:
        return False


def _dependency_stamp_path() -> Path:
    return RUNTIME_DIR / "python-deps.stamp"


def _requirements_runtime_modules() -> list[str]:
    """Map requirements.txt declarations to importable module names (best effort).

    Direct URL / local path / editable lines and markers that cannot be evaluated
    cheaply are skipped so the readiness probe stays deterministic.
    """

    try:
        lines = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    modules: list[str] = []
    for raw in lines:
        line = str(raw).strip()
        if not line or line.startswith(("#", "-")):
            continue
        marker = ""
        if ";" in line:
            line, marker = line.split(";", 1)
        if not _requirements_marker_applies(marker):
            continue
        name_part = line.strip()
        if not name_part:
            continue
        if "@" in name_part:
            name_part = name_part.split("@", 1)[0].strip()
        elif name_part.lower().startswith(("http://", "https://", "file:", "git+")) or name_part.startswith(
            ("./", "../")
        ):
            continue
        name = re.split(r"[<>=!\[~ ]", name_part, maxsplit=1)[0].strip()
        module = REQUIREMENT_IMPORT_NAME_OVERRIDES.get(name.lower(), name.replace("-", "_"))
        # Allow dotted import paths (e.g. langgraph.checkpoint.sqlite).
        if (
            module
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", module)
            and module not in modules
        ):
            modules.append(module)
    return modules


def _requirements_marker_applies(marker: str) -> bool:
    """Cheap platform marker evaluation (only platform_system/sys_platform)."""

    marker = str(marker or "").strip()
    if not marker:
        return True
    if "platform_system" not in marker and "sys_platform" not in marker:
        # Markers we cannot evaluate cheaply (e.g. python_version) are treated as applicable.
        return True
    if "Windows" not in marker and "win32" not in marker:
        return True
    is_windows = os.name == "nt"
    if "!=" in marker:
        return not is_windows
    return is_windows


def _requirements_fingerprint_at(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _requirements_fingerprint() -> str:
    return _requirements_fingerprint_at(REQUIREMENTS_PATH)


def _read_dependency_stamp() -> str:
    try:
        return _dependency_stamp_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_dependency_stamp(fingerprint: str) -> None:
    if not fingerprint:
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _dependency_stamp_path().write_text(fingerprint, encoding="utf-8")


_CORE_RUNTIME_IMPORT_MODULES = ("fastapi", "uvicorn")


def _probe_python_imports(python_executable: str, modules: list[str], *, timeout: float = 30.0) -> bool:
    if not str(python_executable or "").strip() or not modules:
        return False
    try:
        result = subprocess.run(
            [str(python_executable), "-c", "import " + ", ".join(modules)],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            creationflags=_windows_creation_flags(),
            startupinfo=_hidden_startup_info(),
            check=False,
            **_subprocess_text_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return int(result.returncode) == 0


def _runtime_core_imports_available(python_executable: str) -> bool:
    """Cheap readiness probe used when requirements fingerprint already matches."""

    return _probe_python_imports(python_executable, list(_CORE_RUNTIME_IMPORT_MODULES), timeout=15.0)


def _runtime_imports_available(python_executable: str) -> bool:
    """True when the interpreter can import the runtime dependencies in one probe."""

    modules = _requirements_runtime_modules() or list(_CORE_RUNTIME_IMPORT_MODULES)
    return _probe_python_imports(python_executable, modules, timeout=45.0)


def _missing_runtime_modules(python_executable: str, modules: list[str]) -> list[str]:
    if not modules:
        return []
    # One subprocess for all modules first; only fan out when the batch fails.
    if _probe_python_imports(python_executable, list(modules), timeout=45.0):
        return []
    missing: list[str] = []
    for module in modules:
        if not _probe_python_imports(python_executable, [module], timeout=15.0):
            missing.append(module)
    return missing


def _ensure_langgraph_checkpoint_sqlite_shim(python_executable: str) -> None:
    """Write a tiny top-level alias so legacy probes can import the package name.

    Pip package ``langgraph-checkpoint-sqlite`` only exposes
    ``langgraph.checkpoint.sqlite``. Older stamps / external tools still do
    ``import langgraph_checkpoint_sqlite``.
    """

    if not str(python_executable or "").strip():
        return
    try:
        result = subprocess.run(
            [
                str(python_executable),
                "-c",
                (
                    "import pathlib, sys\n"
                    "try:\n"
                    "    import langgraph_checkpoint_sqlite  # noqa: F401\n"
                    "    raise SystemExit(0)\n"
                    "except Exception:\n"
                    "    pass\n"
                    "paths = [pathlib.Path(p) for p in sys.path if p and 'site-packages' in p.replace('\\\\','/')]\n"
                    "if not paths:\n"
                    "    raise SystemExit(2)\n"
                    "target = paths[0] / 'langgraph_checkpoint_sqlite.py'\n"
                    "target.write_text("
                    "'''Compatibility alias for langgraph-checkpoint-sqlite.\\n"
                    "from langgraph.checkpoint.sqlite import SqliteSaver\\n"
                    "from langgraph.checkpoint import sqlite as sqlite\\n"
                    "__all__ = [\"SqliteSaver\", \"sqlite\"]\\n'''"
                    ", encoding='utf-8')\n"
                    "import langgraph_checkpoint_sqlite  # noqa: F401\n"
                ),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=20.0,
            creationflags=_windows_creation_flags(),
            startupinfo=_hidden_startup_info(),
            check=False,
            **_subprocess_text_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return
    if int(result.returncode) != 0:
        return


def _bootstrap_python_executable() -> str:
    """Pick the interpreter used to create the project venv (current interpreter first)."""

    current = str(getattr(sys, "executable", "") or "").strip()
    if current and Path(current).is_file():
        return current
    for name in ("python3", "python"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError(
        "Project virtual environment is missing and no Python interpreter was found. "
        "Install Python 3.11 or 3.12 first."
    )


def _create_project_virtualenv() -> None:
    bootstrap_python = _bootstrap_python_executable()
    result = subprocess.run(
        [bootstrap_python, "-m", "venv", str(VENV_DIR)],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
        check=False,
        **_subprocess_text_kwargs(),
    )
    if result.returncode != 0 or not _venv_python_executable().exists():
        detail = _process_output_tail(result.stderr or result.stdout, max_lines=15, max_chars=2000)
        raise RuntimeError(
            f"Creating project virtual environment at {VENV_DIR} with {bootstrap_python} "
            f"failed with exit code {result.returncode}{f': {detail}' if detail else '.'}"
        )


def _install_project_dependencies(python_executable: str) -> None:
    if _isolated_workspace() and _is_supervisor_venv_python(python_executable):
        raise RuntimeError(
            "Refusing to install isolated-instance dependencies into the supervisor venv."
        )
    result = subprocess.run(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(REQUIREMENTS_PATH),
        ],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        creationflags=_windows_creation_flags(),
        startupinfo=_hidden_startup_info(),
        check=False,
        **_subprocess_text_kwargs(),
    )
    if result.returncode != 0:
        detail = _process_output_tail(result.stderr or result.stdout, max_lines=15, max_chars=2000)
        raise RuntimeError(
            f"Installing Python dependencies into {python_executable} failed with exit code "
            f"{result.returncode}{f': {detail}' if detail else '.'}"
        )


def _try_reuse_supervisor_python_runtime() -> str:
    """Reuse the supervisor .venv when an isolated workspace has the same requirements.

    Isolated start must never pip-install into the shared supervisor environment.
    """

    if not _isolated_workspace():
        return ""
    supervisor_python = _venv_python_for(SUPERVISOR_ROOT / ".venv")
    if not supervisor_python.is_file():
        return ""
    worktree_fingerprint = _requirements_fingerprint()
    supervisor_fingerprint = _requirements_fingerprint_at(SUPERVISOR_ROOT / "requirements.txt")
    if not worktree_fingerprint or worktree_fingerprint != supervisor_fingerprint:
        return ""
    python = str(supervisor_python)
    if _runtime_core_imports_available(python):
        return python
    return ""


def _local_venv_stamp_ready_python() -> str:
    """Return the workspace .venv interpreter when stamp and core imports already match."""

    venv_python_path = _venv_python_executable()
    if not venv_python_path.exists():
        return ""
    fingerprint = _requirements_fingerprint()
    stored_fingerprint = _read_dependency_stamp()
    if not (fingerprint and stored_fingerprint == fingerprint):
        return ""
    # Fast path: stamp already matches requirements.txt → skip heavy full-import probe.
    venv_python = str(venv_python_path)
    _ensure_langgraph_checkpoint_sqlite_shim(venv_python)
    if _runtime_core_imports_available(venv_python):
        return venv_python
    return ""


def _local_venv_full_ready_python() -> str:
    """Return the workspace .venv interpreter after a full import probe."""

    venv_python_path = _venv_python_executable()
    if not venv_python_path.exists():
        return ""
    venv_python = str(venv_python_path)
    _ensure_langgraph_checkpoint_sqlite_shim(venv_python)
    fingerprint = _requirements_fingerprint()
    stored_fingerprint = _read_dependency_stamp()
    runtime_ready = _runtime_imports_available(venv_python)
    if runtime_ready and (not fingerprint or stored_fingerprint == fingerprint):
        if fingerprint and not stored_fingerprint:
            _write_dependency_stamp(fingerprint)
        return venv_python
    return ""


def _ensure_project_python_runtime() -> str:
    """Bootstrap the project venv and return its interpreter, installing requirements when needed.

    - Uses the project-local .venv interpreter when present and ready.
    - Isolated workspaces reuse the supervisor .venv when requirements.txt matches
      and that interpreter can import fastapi/uvicorn; they do not create or pip-install
      a private venv in that case.
    - Creates a workspace .venv from the current interpreter when missing and reuse
      is not available (including when isolated requirements differ).
    - Installs requirements.txt only when the runtime imports are incomplete or the
      requirements fingerprint changed; a ready venv is never reinstalled.
    - When the stamp matches, only a cheap fastapi/uvicorn probe runs (not a full
      langchain/litellm import of every requirements module).
    """

    local = _local_venv_stamp_ready_python()
    if local:
        return local
    reused = _try_reuse_supervisor_python_runtime()
    if reused:
        _append_frontend_build_log(
            {
                "event": "python_runtime.reused_supervisor",
                "pythonExecutable": reused,
                "reason": "requirements_fingerprint_match",
            }
        )
        return reused
    local = _local_venv_full_ready_python()
    if local:
        return local
    venv_python = str(_venv_python_executable())
    if not _venv_python_executable().exists():
        _create_project_virtualenv()
        venv_python = str(_venv_python_executable())
    # Heal known pip-name vs import-name mismatches (safe no-op if already present).
    _ensure_langgraph_checkpoint_sqlite_shim(venv_python)
    fingerprint = _requirements_fingerprint()
    if not REQUIREMENTS_PATH.exists():
        raise RuntimeError(
            f"Project virtual environment at {VENV_DIR} is not usable and requirements.txt "
            f"is missing at {REQUIREMENTS_PATH}; cannot install backend dependencies."
        )
    _install_project_dependencies(venv_python)
    # After install: heal known package/import name mismatches before probing.
    _ensure_langgraph_checkpoint_sqlite_shim(venv_python)
    missing = _missing_runtime_modules(venv_python, _requirements_runtime_modules())
    if missing:
        raise RuntimeError(
            "Python dependency install completed, but backend imports still failed for: "
            f"{', '.join(missing)}. Inspect the install output and requirements.txt to repair the venv."
        )
    if fingerprint:
        _write_dependency_stamp(fingerprint)
    return venv_python


def _select_background_python(executable: str) -> dict[str, object]:
    raw = str(executable or "").strip()
    creation_flag_names = list(_windows_creation_flag_names(detach=True))
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


def _frontend_dist_is_servable(web_dir: Path) -> bool:
    """True when a non-empty production index exists. Does not scan source mtimes."""

    dist_index = web_dir / "dist" / "index.html"
    try:
        return dist_index.is_file() and dist_index.stat().st_size > 0
    except OSError:
        return False


def _reuse_existing_frontend_build(
    identity: dict[str, object],
    *,
    web_dir: Path,
    skip_reason: str,
) -> dict[str, object]:
    """Serve current dist without rebuilding or rewriting artifact identity."""

    provenance_path = web_dir / "dist" / FRONTEND_BUILD_PROVENANCE_NAME
    previous_provenance = _read_frontend_build_provenance(provenance_path)
    provenance: dict[str, object] = {
        "schemaVersion": 1,
        "projectRoot": identity.get("projectRoot"),
        "sourceBranch": identity.get("branch"),
        "sourceCommit": previous_provenance.get("sourceCommit") or identity.get("commit"),
        "frontendTree": previous_provenance.get("frontendTree") or "",
        "builtFromCommit": previous_provenance.get("builtFromCommit") or "",
        "reusedArtifactFromCommit": previous_provenance.get("builtFromCommit")
        or previous_provenance.get("sourceCommit")
        or "",
        "lastValidatedCommit": previous_provenance.get("lastValidatedCommit") or identity.get("commit"),
        "lastValidatedFrontendTree": previous_provenance.get("lastValidatedFrontendTree")
        or previous_provenance.get("frontendTree")
        or "",
        "rebuilt": False,
        "skipped": True,
        "skipReason": skip_reason,
        "validatedAt": _now_iso(),
    }
    _append_frontend_build_log(
        {
            "event": "frontend_build.ensure",
            "packageManager": _frontend_package_manager(),
            "needsInstall": False,
            "needsBuild": False,
            "skipped": True,
            "skipReason": skip_reason,
            "sourceCommit": identity.get("commit"),
            "frontendTree": identity.get("frontendTree"),
            "previousFrontendTree": previous_provenance.get("frontendTree"),
            "sourcesNewer": False,
            "treeMismatch": False,
        }
    )
    _append_frontend_build_log(
        {
            "event": "frontend_build.verified",
            "sourceCommit": provenance["sourceCommit"],
            "frontendTree": provenance["frontendTree"],
            "builtFromCommit": provenance["builtFromCommit"],
            "rebuilt": False,
            "skipped": True,
            "skipReason": skip_reason,
        }
    )
    return provenance


def _ensure_frontend_build(
    source_identity: dict[str, object] | None = None,
    *,
    require_current: bool = True,
) -> dict[str, object]:
    web_dir = PROJECT_ROOT / "web"
    if not web_dir.exists():
        return {}
    identity = source_identity or _runtime_source_identity()
    # Open/start rebuilds when the artifact is missing or not current.
    # Restart/force uses the same check; missing dist always falls through to build.
    if not require_current and _frontend_dist_is_servable(web_dir):
        return _reuse_existing_frontend_build(
            identity,
            web_dir=web_dir,
            skip_reason="start_reuses_existing_dist",
        )
    package_manager = _frontend_package_manager()
    node_modules = web_dir / "node_modules"
    needs_install = not node_modules.exists()
    dist_index = web_dir / "dist" / "index.html"
    provenance_path = web_dir / "dist" / FRONTEND_BUILD_PROVENANCE_NAME
    previous_provenance = _read_frontend_build_provenance(provenance_path)
    sources_newer = _frontend_sources_are_newer_than_dist(web_dir, dist_index)
    previous_tree = str(previous_provenance.get("frontendTree") or "")
    identity_tree = str(identity.get("frontendTree") or "")
    tree_matches = bool(previous_provenance) and previous_tree == identity_tree
    # Provenance ``frontendTree`` is the tree that *produced* dist. Mismatch means
    # main moved (even when git commit did not bump file mtimes). Missing stamp with
    # a live identity tree requires one rebuild so skip-stamps stay honest.
    tree_mismatch = bool(identity_tree) and (
        (bool(previous_provenance) and previous_tree != identity_tree)
        or (not previous_provenance and bool(identity_tree) and dist_index.exists())
    )
    # Exception: empty previous provenance + dist fresher than sources was allowed
    # to avoid double-build after preflight. Keep that only when identity tree is
    # empty (no git). When git identity is available, require a stamped tree match.
    if (not previous_provenance) and dist_index.exists() and (not sources_newer) and (not identity_tree):
        tree_mismatch = False
    needs_build = (not dist_index.exists()) or sources_newer or tree_mismatch
    _append_frontend_build_log(
        {
            "event": "frontend_build.ensure",
            "packageManager": package_manager,
            "needsInstall": needs_install,
            "needsBuild": needs_build,
            "sourceCommit": identity.get("commit"),
            "frontendTree": identity.get("frontendTree"),
            "previousFrontendTree": previous_provenance.get("frontendTree"),
            "sourcesNewer": sources_newer,
            "treeMismatch": tree_mismatch,
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
    _assert_runtime_source_identity(identity)
    if needs_build:
        artifact_tree = identity.get("frontendTree")
        built_from = identity.get("commit")
        reused_from: object = ""
    else:
        # Never rewrite artifact identity to HEAD on a skip — that blocked rebuilds.
        artifact_tree = previous_provenance.get("frontendTree") or identity.get("frontendTree")
        built_from = previous_provenance.get("builtFromCommit") or identity.get("commit")
        reused_from = previous_provenance.get("builtFromCommit") or built_from
    provenance: dict[str, object] = {
        "schemaVersion": 1,
        "projectRoot": identity.get("projectRoot"),
        "sourceBranch": identity.get("branch"),
        "sourceCommit": identity.get("commit"),
        "frontendTree": artifact_tree,
        "builtFromCommit": built_from,
        "reusedArtifactFromCommit": reused_from,
        "lastValidatedCommit": identity.get("commit"),
        "lastValidatedFrontendTree": identity.get("frontendTree"),
        "rebuilt": needs_build,
        "validatedAt": _now_iso(),
    }
    _write_frontend_build_provenance(provenance_path, provenance)
    _append_frontend_build_log(
        {
            "event": "frontend_build.verified",
            "sourceCommit": provenance["sourceCommit"],
            "frontendTree": provenance["frontendTree"],
            "builtFromCommit": provenance["builtFromCommit"],
            "rebuilt": needs_build,
        }
    )
    return provenance


def _frontend_sources_are_newer_than_dist(web_dir: Path, dist_index: Path) -> bool:
    if not dist_index.exists():
        return True
    try:
        newest_source_mtime = 0.0
        for source in (web_dir / "src", web_dir / "public"):
            if source.is_dir():
                newest_source_mtime = max(
                    newest_source_mtime,
                    *(path.stat().st_mtime for path in source.rglob("*") if path.is_file()),
                )
        for name in ("index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts"):
            candidate = web_dir / name
            if candidate.is_file():
                newest_source_mtime = max(newest_source_mtime, candidate.stat().st_mtime)
        return newest_source_mtime > dist_index.stat().st_mtime
    except OSError:
        return True


def _start_backend(port: int, host: str, *, no_browser: bool) -> dict:
    """Always start a **fresh** workbench instance for this project.

    Previous project-owned process handles (backend + managed browser) are retired
    first. Start never attaches to an already-running workbench PID.
    Visible windows belong to Electron; this adapter must not spawn Edge.
    """
    if not no_browser:
        raise RuntimeError(
            "Electron desktop shell is unavailable. Refusing Edge fallback. "
            "Start or rebuild dist/desktop/win-unpacked/Vibelution.exe."
        )
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    previous_state = _read_state()
    preferred_port = int(port or DEFAULT_PORT)
    # 1) Retire previous instance by handle — never take over old PIDs.
    retired_handles = _retire_project_workbench_instance(previous_state, preferred_port)
    # 2) Bind port (foreign occupancy may auto-relocate; project occupancy is an error).
    resolved_port, resolve_note = _resolve_start_backend_port(preferred_port, host)
    port = int(resolved_port)
    # Foreign occupancy is resolved by auto-binding another free port (multi-checkout safe).
    open_started = time.monotonic()
    open_timings_ms: dict[str, float] = {}
    identity_started = time.monotonic()
    source_identity = _runtime_source_identity()
    open_timings_ms["sourceIdentityMs"] = round((time.monotonic() - identity_started) * 1000.0, 1)
    frontend_started = time.monotonic()
    # Open/start must serve the current checkout. Skip tsc/vite only when dist
    # already matches this frontend tree; stale artifacts are rebuilt first.
    frontend_provenance = _ensure_frontend_build(source_identity, require_current=True)
    open_timings_ms["frontendEnsureMs"] = round((time.monotonic() - frontend_started) * 1000.0, 1)
    # Mid-flight checks only need commit/tree drift detection (full porcelain already done).
    _assert_runtime_source_identity(source_identity, light=True)
    runtime_scene = _start_runtime_scene("python_launcher_fresh_start")
    _rotate_launcher_process_logs_before_start()
    _sync_launcher_logs_to_scene_raw(Path(str(runtime_scene.get("runtimeSceneDir") or "")))
    stdout = BACKEND_STDOUT_PATH.open("ab")
    stderr = BACKEND_STDERR_PATH.open("ab")
    python_started = time.monotonic()
    python_runtime = _select_background_python(_ensure_project_python_runtime())
    open_timings_ms["pythonRuntimeEnsureMs"] = round((time.monotonic() - python_started) * 1000.0, 1)
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
    backend_spawn_started = time.monotonic()
    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        env=_backend_environment(host),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
        creationflags=_windows_creation_flags(detach=True),
        startupinfo=_hidden_startup_info(),
    )
    stdout.close()
    stderr.close()
    backend_pid = _wait_for_started_backend(process, port, host)
    open_timings_ms["backendSpawnAndHealthMs"] = round((time.monotonic() - backend_spawn_started) * 1000.0, 1)
    if backend_pid <= 0:
        _terminate_pid(process.pid)
        raise RuntimeError(f"New backend did not own a healthy listener at {_health_url(port, host)}.")
    retired_set = set(int(pid) for pid in retired_handles)
    if int(backend_pid) in retired_set or int(process.pid) in retired_set:
        _terminate_pid(process.pid)
        raise RuntimeError(
            "Fresh start produced process handles that collide with the retired instance; "
            f"retired={sorted(retired_set)} backendPid={backend_pid} launchPid={process.pid}."
        )
    try:
        _assert_runtime_source_identity(source_identity, light=True)
    except Exception:
        _terminate_pid(process.pid)
        raise
    url = f"http://{host}:{int(port)}"
    browser_info: dict[str, object] = {
        "browserManaged": False,
        "browserExecutable": "",
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "browserProfileDir": "",
    }
    try:
        _assert_runtime_source_identity(source_identity, light=True)
    except Exception:
        _terminate_pid(int(browser_info.get("browserLaunchPid") or 0))
        _terminate_pid(process.pid)
        raise
    open_timings_ms["totalOpenMs"] = round((time.monotonic() - open_started) * 1000.0, 1)
    open_timings_ms["retiredHandleCount"] = float(len(retired_handles))
    _append_frontend_build_log(
        {
            "event": "workbench.open.timings",
            "timingsMs": open_timings_ms,
            "rebuiltFrontend": bool(frontend_provenance.get("rebuilt")),
            "port": int(port),
            "noBrowser": bool(no_browser),
            "freshStart": True,
            "retiredHandles": list(retired_handles),
        }
    )
    previous_generation = int(previous_state.get("instanceGeneration") or 0)
    state = {
        **_preserved_launcher_control_state(previous_state),
        "schemaVersion": 1,
        "launcherAdapter": "python_headless",
        "desiredState": "open",
        "observedState": "open",
        "phase": "steady",
        "sessionRole": "workbench",
        "sessionId": str(uuid.uuid4()),
        "instanceGeneration": previous_generation + 1,
        "previousInstanceHandles": list(retired_handles),
        "runtimeSceneId": str(runtime_scene["runtimeSceneId"]),
        "runtimeSceneDir": str(runtime_scene["runtimeSceneDir"]),
        "runtimeSceneStartedAt": str(runtime_scene["startedAt"]),
        "backendPid": int(backend_pid),
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
        "preferredBackendPort": int(preferred_port),
        "portRelocationNote": str(resolve_note or ""),
        "statusLine": (
            f"Workbench is running on port {int(port)}."
            if resolve_note and "auto-bound" in resolve_note
            else "Workbench is running."
        ),
        "failureMessage": "",
        "lastReason": "python_launcher_fresh_start",
        "lastSource": "python_launcher",
        "pythonExecutable": python_command,
        "sourcePythonExecutable": str(python_runtime["sourcePythonExecutable"]),
        "noConsolePythonExecutable": str(python_runtime["noConsolePythonExecutable"]),
        "consoleWindowSuppressed": bool(python_runtime["consoleWindowSuppressed"]),
        "consoleSuppressionMode": str(python_runtime["consoleSuppressionMode"]),
        "consoleFallbackReason": str(python_runtime["consoleFallbackReason"]),
        "pythonLaunchPolicy": str(python_runtime["pythonLaunchPolicy"]),
        "creationFlagNames": list(python_runtime["creationFlagNames"]),
        "runtimeProjectRoot": str(source_identity["projectRoot"]),
        "runtimeSourceBranch": str(source_identity["branch"]),
        "runtimeSourceCommit": str(source_identity["commit"]),
        "runtimeSourceTrackedClean": bool(source_identity["trackedClean"]),
        "frontendSourceCommit": str(frontend_provenance.get("sourceCommit") or ""),
        "frontendTree": str(frontend_provenance.get("frontendTree") or ""),
        "frontendBuiltFromCommit": str(frontend_provenance.get("builtFromCommit") or ""),
        "frontendRebuilt": bool(frontend_provenance.get("rebuilt")),
        "updatedAt": _now_iso(),
    }
    _remember_project_backend_port(port, reason=resolve_note or "python_launcher_fresh_start")
    _write_state(state)
    return state


def _terminate_pid(pid: int) -> str:
    """Terminate a pid with SIGTERM/SIGKILL escalation and native fallbacks.

    Returns an empty string when the pid is confirmed dead (or was already
    gone); otherwise returns a short reason so callers can surface why a
    retire/cleanup could not complete instead of failing silently.
    """
    if pid <= 0:
        return ""
    probe = _pid_probe(pid)
    if probe == "dead":
        return ""
    if probe == "unknown":
        # The process exists but cannot be inspected (access denied). Do not
        # skip termination: native fallbacks may still be permitted even when
        # OpenProcess inspection was rejected.
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            return _terminate_pid_with_fallbacks(pid, probe, primary_error=exc, still_alive=False)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if _pid_probe(pid) == "dead":
                return ""
            time.sleep(0.2)
        if not hasattr(signal, "SIGKILL"):
            return _terminate_pid_with_fallbacks(pid, probe, primary_error=None, still_alive=True)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as exc:
            return _terminate_pid_with_fallbacks(pid, probe, primary_error=exc, still_alive=False)
        if _pid_probe(pid) == "dead":
            return ""
        return _terminate_pid_with_fallbacks(pid, probe, primary_error=None, still_alive=True)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return _terminate_pid_with_fallbacks(pid, probe, primary_error=exc, still_alive=False)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return ""
        time.sleep(0.2)
    if not hasattr(signal, "SIGKILL"):
        # Windows has no SIGKILL; escalate through native fallbacks instead.
        return _terminate_pid_with_fallbacks(pid, probe, primary_error=None, still_alive=True)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as exc:
        return _terminate_pid_with_fallbacks(pid, probe, primary_error=exc, still_alive=False)
    if not _pid_alive(pid):
        return ""
    return _terminate_pid_with_fallbacks(pid, probe, primary_error=None, still_alive=True)


def _terminate_pid_with_fallbacks(
    pid: int,
    probe: str,
    *,
    primary_error: OSError | None,
    still_alive: bool,
) -> str:
    """Fallback termination: psutil process tree, then winapi TerminateProcess."""
    reasons: list[str] = []
    if primary_error is not None:
        reasons.append(f"os.kill failed: {primary_error}")
    if probe != "alive":
        reasons.append(f"pid probe: {probe}")
    if still_alive:
        reasons.append("still alive after SIGTERM and SIGKILL")
    tree_killed = _terminate_pid_tree_with_psutil(pid) if os.name == "nt" else False
    if tree_killed and _pid_probe(pid) == "dead":
        return ""
    winapi_killed = False
    if tree_killed:
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if _pid_probe(pid) == "dead":
                return ""
            time.sleep(0.2)
    if _pid_probe(pid) == "dead":
        return ""
    if os.name == "nt":
        winapi_killed = _terminate_pid_with_winapi(pid)
        if winapi_killed:
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                if _pid_probe(pid) == "dead":
                    return ""
                time.sleep(0.2)
    if _pid_probe(pid) == "dead":
        return ""
    detail = "; ".join(reasons)
    return (
        f"pid {pid} survived os.kill, psutil tree ({tree_killed}) "
        f"and winapi TerminateProcess ({winapi_killed})"
        + (f" ({detail})" if detail else "")
    )


def _terminate_pid_tree_with_psutil(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import psutil  # type: ignore
    except ImportError:
        return False
    try:
        root = psutil.Process(int(pid))
        processes = list(root.children(recursive=True))
        processes.reverse()
        processes.append(root)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except (OSError, psutil.Error):
        return False
    attempted = False
    for process in processes:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.terminate()
            attempted = True
    try:
        _gone, alive = psutil.wait_procs(processes, timeout=1.5)
    except (OSError, psutil.Error):
        alive = []
    for process in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.kill()
            attempted = True
    if alive:
        with contextlib.suppress(psutil.Error, OSError):
            psutil.wait_procs(alive, timeout=1.0)
    return attempted


def _terminate_pid_with_winapi(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0001, False, int(pid))
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    except OSError:
        return False
    finally:
        kernel32.CloseHandle(handle)


def _stop_backend() -> dict:
    state = _read_state()
    port = int(state.get("backendPort") or state.get("port") or DEFAULT_PORT)
    retired = _retire_project_workbench_instance(state, port)
    if _listening_pid_for_port(port) > 0 and not _wait_for_port_release(port):
        owner_pid = _listening_pid_for_port(port)
        # Foreign occupant is fine to leave (multi-checkout); project occupant is not.
        if _is_project_workbench_pid(owner_pid):
            raise RuntimeError(
                f"Workbench stop left port {port} occupied by project pid {owner_pid}; "
                "state was preserved for recovery."
            )
    next_state = {
        **state,
        "desiredState": "closed",
        "observedState": "closed",
        "phase": "steady",
        "backendPid": 0,
        "backendLaunchPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "workbenchBrowserLaunchPid": 0,
        "workbenchBrowserWindowPid": 0,
        "browserManaged": False,
        "previousInstanceHandles": list(retired),
        "statusLine": "Workbench is closed.",
        "failureMessage": "",
        "lastReason": "python_launcher_stop",
        "lastSource": "python_launcher",
        "updatedAt": _now_iso(),
    }
    _write_state(next_state)
    _seal_active_runtime_scene("explicit_stop", "Workbench processes confirmed closed.")
    return next_state


def _focus_backend(port: int, host: str) -> dict:
    """Non-destructive focus: require a healthy workbench backend, recover stale state.

    Runtime-manager "already open" short-circuit calls internal-focus. Launcher state can
    lag (backendPid=0 or a dead pid) while the project backend is still healthy on the
    bound port — treat live health as source of truth so start does not hard-fail.
    """
    state = _read_state()
    port = int(port or state.get("backendPort") or state.get("port") or DEFAULT_PORT)
    host = str(host or state.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST
    pid = int(state.get("backendPid") or 0)
    if pid > 0 and _pid_alive(pid) and _backend_healthy(port, host):
        return state
    if not _backend_healthy(port, host):
        raise RuntimeError("Workbench focus requested but no running workbench backend is available.")
    owner_pid = _listening_pid_for_port(port)
    recovered_pid = 0
    if owner_pid > 0 and (_is_project_workbench_pid(owner_pid) or pid <= 0 or not _pid_alive(pid)):
        recovered_pid = owner_pid
    elif pid > 0 and _pid_alive(pid):
        recovered_pid = pid
    next_state = {
        **state,
        "backendPid": int(recovered_pid or pid or 0),
        "backendPort": port,
        "port": port,
        "host": host,
        "desiredState": "open",
        "observedState": "open",
        "phase": "steady",
        "failureMessage": "",
        "statusLine": "Workbench is running.",
        "lastReason": str(state.get("lastReason") or "python_launcher_focus"),
        "lastSource": "python_launcher",
        "updatedAt": _now_iso(),
    }
    _write_state(next_state)
    return next_state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vibelution cross-platform launcher adapter")
    parser.add_argument("-Action", "--action", default="start")
    parser.add_argument("-NoBrowser", "--no-browser", action="store_true")
    parser.add_argument("--host", default=os.environ.get("VIBELUTION_HOST", DEFAULT_HOST))
    default_port = int(os.environ.get("VIBELUTION_PORT") or _saved_project_backend_port() or DEFAULT_PORT)
    parser.add_argument("--port", type=int, default=default_port)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _assert_internal_action_authorized(args.action)
        action = _normalize_action(args.action)
        if action == "start":
            # Always fresh-start: retire previous project handles, spawn new PIDs.
            # Never "already running" short-circuit / take over old workbench.
            state = _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            retired = state.get("previousInstanceHandles") or []
            print(
                "Workbench started (fresh instance"
                f"{f', retired handles {retired}' if retired else ''})."
            )
            return 0
        if action == "stop":
            _stop_backend()
            print("Workbench stopped.")
            return 0
        if action == "focus":
            # Focus is the only non-destructive attach path (no start takeover).
            _focus_backend(args.port, args.host)
            print("Workbench already running.")
            return 0
        if action == "restart":
            # restart == stop + fresh start (start itself also retires handles).
            restart_source_identity = _runtime_source_identity()
            _ensure_frontend_build(restart_source_identity)
            _assert_runtime_source_identity(restart_source_identity)
            _stop_backend()
            state = _start_backend(args.port, args.host, no_browser=bool(args.no_browser))
            print(
                "Workbench restarted (fresh instance"
                f", generation={state.get('instanceGeneration')})."
            )
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
