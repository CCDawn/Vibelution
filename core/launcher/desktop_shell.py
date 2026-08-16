"""Keep the packaged desktop shell aligned with the current checkout.

Launcher owns this. Operators should not have to run ``package:dir`` by hand:
a stale ``app.asar`` is rebuilt after the live ``Vibelution.exe`` exits, then
the current checkout's shell is relaunched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.no_console_git import run_git
from core.runtime_manager.constants import PROJECT_ROOT
from scripts.windowless_subprocess import no_window_subprocess_kwargs

PACKAGED_EXE_RELATIVE = Path("dist") / "desktop" / "win-unpacked" / "Vibelution.exe"
PROVENANCE_RELATIVE = (
    Path("dist") / "desktop" / "win-unpacked" / "resources" / "app.asar.unpacked" / "package-provenance.json"
)
ASAR_RELATIVE = Path("dist") / "desktop" / "win-unpacked" / "resources" / "app.asar"
ELECTRON_SRC_RELATIVE = Path("desktop") / "electron" / "src"
ELECTRON_PACKAGE_DIR = Path("desktop") / "electron"
REFRESH_FAILURE_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-refresh-failure.json"
REFRESH_LOCK_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-refresh.lock"
REFRESH_COOLDOWN_SECONDS = 900.0

CREATE_NEW_PROCESS_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def packaged_desktop_exe(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / PACKAGED_EXE_RELATIVE


def packaged_provenance_path(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / PROVENANCE_RELATIVE


def packaged_asar_path(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / ASAR_RELATIVE


def _refresh_failure_path(project_root: Path | str) -> Path:
    return Path(project_root) / REFRESH_FAILURE_RELATIVE


def _refresh_lock_path(project_root: Path | str) -> Path:
    return Path(project_root) / REFRESH_LOCK_RELATIVE


def record_desktop_shell_refresh_failure(
    project_root: Path | str,
    *,
    reason: str,
    detail: str,
) -> None:
    path = _refresh_failure_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "failedAt": datetime.now(timezone.utc).isoformat(),
        "reason": str(reason or "refresh_failed"),
        "detail": str(detail or "")[:800],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_desktop_shell_refresh_failure(project_root: Path | str) -> None:
    path = _refresh_failure_path(project_root)
    if not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        return


def recent_desktop_shell_refresh_failure(
    project_root: Path | str,
    *,
    cooldown_seconds: float = REFRESH_COOLDOWN_SECONDS,
) -> dict[str, Any] | None:
    path = _refresh_failure_path(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        return None
    failed_at = str(payload.get("failedAt") or "").strip()
    if not failed_at:
        return payload
    try:
        failed_time = datetime.fromisoformat(failed_at.replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - failed_time.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        return payload
    if age_seconds > max(1.0, float(cooldown_seconds)):
        return None
    return payload


def _acquire_desktop_shell_refresh_lock(project_root: Path | str) -> bool:
    path = _refresh_lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "startedAt": datetime.now(timezone.utc).isoformat()}))
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _release_desktop_shell_refresh_lock(project_root: Path | str) -> None:
    path = _refresh_lock_path(project_root)
    if not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        return


def inspect_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return whether the live packaged Electron shell matches current desktop/electron."""

    root = Path(project_root)
    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    provenance = _read_json(packaged_provenance_path(root))
    packaged_tree = str(provenance.get("electronTreeHash") or "").strip()
    exe_path = packaged_desktop_exe(root)
    asar_path = packaged_asar_path(root)
    source_newer = _electron_sources_newer_than_asar(root)
    if not exe_path.is_file() or not asar_path.is_file():
        reason = "missing_package"
        stale = True
    elif not packaged_tree:
        reason = "missing_provenance"
        stale = True
    elif current_tree and packaged_tree != current_tree:
        reason = "provenance_mismatch"
        stale = True
    elif source_newer:
        reason = "source_newer_than_asar"
        stale = True
    else:
        reason = "current"
        stale = False
    refresh_block = recent_desktop_shell_refresh_failure(root)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "stale": stale,
        "reason": reason,
        "packagedElectronTree": packaged_tree,
        "currentElectronTree": current_tree,
        "packagedExe": str(exe_path),
        "sourceNewerThanAsar": source_newer,
        "refreshBlocked": refresh_block is not None,
    }
    if refresh_block is not None:
        payload.update(
            {
                "refreshBlockedReason": str(refresh_block.get("reason") or ""),
                "refreshBlockedDetail": str(refresh_block.get("detail") or "")[:220],
                "refreshBlockedAt": str(refresh_block.get("failedAt") or ""),
            }
        )
    return payload


def schedule_desktop_shell_refresh(
    *,
    wait_pid: int,
    then_lifecycle: str = "",
    project_root: Path | str = PROJECT_ROOT,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Start a detached helper that rebuilds the shell after ``wait_pid`` exits."""

    root = Path(project_root)
    if recent_desktop_shell_refresh_failure(root) is not None:
        return {
            "schemaVersion": 1,
            "scheduled": False,
            "helperPid": 0,
            "waitPid": int(wait_pid),
            "thenLifecycle": str(then_lifecycle or "").strip().lower(),
            "reason": "refresh_cooldown",
        }
    if not _acquire_desktop_shell_refresh_lock(root):
        return {
            "schemaVersion": 1,
            "scheduled": False,
            "helperPid": 0,
            "waitPid": int(wait_pid),
            "thenLifecycle": str(then_lifecycle or "").strip().lower(),
            "reason": "refresh_in_progress",
        }
    helper_python = _pythonw(python_executable or sys.executable)
    entry = root / "scripts" / "vibelution_desktop_entry.py"
    args = [
        helper_python,
        str(entry),
        "--action",
        "refresh-desktop-shell",
        "--output",
        "json",
        "--workspace",
        str(root),
        "--wait-pid",
        str(int(wait_pid)),
    ]
    lifecycle = str(then_lifecycle or "").strip().lower()
    if lifecycle:
        args.extend(["--then-lifecycle", lifecycle])
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    kwargs = no_window_subprocess_kwargs(creationflags=flags)
    try:
        process = subprocess.Popen(
            args,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError as exc:
        _release_desktop_shell_refresh_lock(root)
        raise RuntimeError(f"desktop shell refresh helper did not start: {exc}") from exc
    return {
        "schemaVersion": 1,
        "scheduled": True,
        "helperPid": int(getattr(process, "pid", 0) or 0),
        "waitPid": int(wait_pid),
        "thenLifecycle": lifecycle,
    }


def run_desktop_shell_refresh(
    *,
    wait_pid: int = 0,
    then_lifecycle: str = "",
    project_root: Path | str = PROJECT_ROOT,
    wait_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Wait for the old shell to exit, rebuild from checkout, then relaunch."""

    root = Path(project_root)
    try:
        _append_refresh_log(root, "refresh.started", wait_pid=int(wait_pid), then_lifecycle=str(then_lifecycle or ""))
        if int(wait_pid) > 0:
            _wait_for_pid_exit(int(wait_pid), timeout_seconds=wait_timeout_seconds)
        try:
            rebuilt = rebuild_desktop_shell(project_root=root)
        except Exception as exc:
            detail = str(exc)
            record_desktop_shell_refresh_failure(root, reason="rebuild_failed", detail=detail)
            _append_refresh_log(root, "refresh.aborted", wait_pid=int(wait_pid), detail=detail[-800:])
            return {
                "schemaVersion": 1,
                "refreshed": False,
                "reason": "rebuild_failed",
                "message": detail[-800:],
            }
        try:
            launched = launch_packaged_desktop_shell(project_root=root, then_lifecycle=then_lifecycle)
        except Exception as exc:
            detail = str(exc)
            record_desktop_shell_refresh_failure(root, reason="launch_failed", detail=detail)
            _append_refresh_log(root, "refresh.aborted", wait_pid=int(wait_pid), detail=detail[-800:])
            return {
                "schemaVersion": 1,
                "refreshed": False,
                "reason": "launch_failed",
                "message": detail[-800:],
                "rebuild": rebuilt,
            }
        clear_desktop_shell_refresh_failure(root)
        _append_refresh_log(
            root,
            "refresh.finished",
            wait_pid=int(wait_pid),
            helper_launch_pid=int(launched.get("pid") or 0),
        )
        return {
            "schemaVersion": 1,
            "refreshed": True,
            "rebuild": rebuilt,
            "launch": launched,
        }
    finally:
        _release_desktop_shell_refresh_lock(root)


def rebuild_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Rebuild ``win-unpacked`` from the current ``desktop/electron`` checkout."""

    root = Path(project_root)
    electron_dir = root / ELECTRON_PACKAGE_DIR
    node_command = _node_command()
    npm_cli = _npm_cli_script_for_node(node_command)
    command = [node_command, npm_cli, "run", "package:dir"]
    result = subprocess.run(
        command,
        cwd=str(electron_dir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **no_window_subprocess_kwargs(),
    )
    if int(result.returncode or 0) != 0:
        detail = (result.stderr or result.stdout or "").strip().replace("\r", "")[-800:]
        _append_refresh_log(root, "rebuild.failed", exit_code=int(result.returncode or 0), detail=detail)
        raise RuntimeError(f"desktop shell package:dir failed with exit code {result.returncode}: {detail}")
    status = inspect_desktop_shell(root)
    if status["stale"]:
        raise RuntimeError(f"desktop shell is still stale after rebuild: {status['reason']}")
    return {
        "rebuilt": True,
        "reason": status["reason"],
        "currentElectronTree": status["currentElectronTree"],
    }


def launch_packaged_desktop_shell(
    *,
    project_root: Path | str = PROJECT_ROOT,
    then_lifecycle: str = "",
) -> dict[str, Any]:
    root = Path(project_root)
    exe = packaged_desktop_exe(root)
    if not exe.is_file():
        raise FileNotFoundError(f"packaged desktop shell was not found: {exe}")
    args = [str(exe), "--workspace", str(root)]
    lifecycle = str(then_lifecycle or "").strip().lower()
    if lifecycle:
        args.append(lifecycle)
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        # GUI Electron must not inherit STARTUPINFO SW_HIDE / CREATE_NO_WINDOW
        # from the no-console helper policy, or the new shell can come up invisible.
        popen_kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
        popen_kwargs["close_fds"] = True
    process = subprocess.Popen(
        args,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_kwargs,
    )
    return {
        "launched": True,
        "pid": int(getattr(process, "pid", 0) or 0),
        "thenLifecycle": lifecycle,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_tree_hash(project_root: Path, spec: str) -> str:
    result = run_git(["rev-parse", spec], cwd=project_root, timeout=10.0)
    if int(result.returncode or 0) != 0:
        return ""
    return str(result.stdout or "").strip()


def _electron_sources_newer_than_asar(project_root: Path) -> bool:
    asar_path = packaged_asar_path(project_root)
    src_root = project_root / ELECTRON_SRC_RELATIVE
    if not asar_path.is_file() or not src_root.is_dir():
        return False
    try:
        asar_mtime = asar_path.stat().st_mtime
    except OSError:
        return True
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime > asar_mtime:
                return True
        except OSError:
            continue
    return False


def _wait_for_pid_exit(pid: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            time.sleep(1.2)
            return
        time.sleep(0.2)
    if _pid_alive(pid):
        raise TimeoutError(f"desktop shell pid {pid} did not exit before rebuild")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            return bool(psutil.pid_exists(pid))
        except Exception:
            return False
    if os.name == "nt":
        return _windows_pid_exists(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except SystemError:
        return False
    return True


def _windows_pid_exists(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def _append_refresh_log(project_root: Path, event: str, **fields: Any) -> None:
    try:
        from vibelution_storage import resolve_active_project_storage_paths

        path = resolve_active_project_storage_paths(project_root).runtime / "launcher" / "desktop-shell-refresh.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"event": event, **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return


def _pythonw(python_executable: str) -> str:
    path = Path(python_executable)
    if path.name.lower() in {"python.exe", "python"}:
        candidate = path.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return python_executable


def _node_command() -> str:
    resolved = shutil.which("node")
    if resolved:
        return resolved
    if os.name == "nt":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name, "").strip()
            if root:
                candidate = Path(root) / "nodejs" / "node.exe"
                if candidate.is_file():
                    return str(candidate)
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "nodejs" / "node.exe"
            if candidate.is_file():
                return str(candidate)
    return "node"


def _npm_cli_script_for_node(node_command: str) -> str:
    candidates: list[Path] = []
    for which_name in ("npm", "npm.cmd"):
        npm_command = shutil.which(which_name)
        if not npm_command:
            continue
        npm_path = Path(npm_command)
        candidates.extend([npm_path.parent, npm_path.parent.parent])
    node_path = Path(node_command)
    candidates.extend([node_path.parent, node_path.parent.parent])
    for root in candidates:
        candidate = root / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "npm-cli.js was not found next to Node.js/npm. "
        "Refusing to run npm.cmd (it opens a visible console on Windows)."
    )
