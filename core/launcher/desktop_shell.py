"""Keep the packaged desktop shell aligned with the current checkout.

Launcher owns this. Operators should not have to run ``package:dir`` by hand:
a stale ``app.asar`` is rebuilt after the live ``Vibelution.exe`` exits, then
the current checkout's shell is relaunched.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.no_console_git import run_git
from core.infrastructure.owned_process import OwnedProcess
from core.infrastructure.native_runtime import resolve_native_project_root
from core.infrastructure.windows_process_job import WindowsProcessJob
from core.launcher.frontend_build import (
    frontend_releases_dir,
    inspect_frontend_build,
    resolve_active_frontend_dist,
)
from config.paths import PROJECT_ROOT as SOURCE_PROJECT_ROOT
from scripts.windowless_subprocess import no_window_subprocess_kwargs

PROJECT_ROOT = resolve_native_project_root(SOURCE_PROJECT_ROOT)

PACKAGED_EXE_RELATIVE = Path("dist") / "desktop" / "win-unpacked" / "Vibelution.exe"
PROVENANCE_RELATIVE = (
    Path("dist") / "desktop" / "win-unpacked" / "resources" / "app.asar.unpacked" / "package-provenance.json"
)
ASAR_RELATIVE = Path("dist") / "desktop" / "win-unpacked" / "resources" / "app.asar"
PACKAGED_FRONTEND_RELATIVE = Path("dist") / "desktop" / "win-unpacked" / "resources" / "web-dist"
ELECTRON_SRC_RELATIVE = Path("desktop") / "electron" / "src"
ELECTRON_PACKAGE_DIR = Path("desktop") / "electron"
UNPACKAGED_MAIN_RELATIVE = Path("desktop") / "electron" / "dist" / "main.js"
UNPACKAGED_PROVENANCE_RELATIVE = Path("desktop") / "electron" / "dist" / "unpackaged-provenance.json"
UNPACKAGED_STAGING_RELATIVE = Path("dist") / "desktop-unpackaged-staging"
UNPACKAGED_ELECTRON_EXE_RELATIVE = (
    Path("desktop") / "electron" / "node_modules" / "electron" / "dist" / "electron.exe"
)
UNPACKAGED_ELECTRON_BIN_RELATIVE = Path("desktop") / "electron" / "node_modules" / "electron" / "dist" / "electron"
REFRESH_FAILURE_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-refresh-failure.json"
REFRESH_LOCK_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-refresh.lock"
REFRESH_COOLDOWN_SECONDS = 900.0
# Post-merge staging builds run in the background where nobody is waiting, so a
# longer cooldown than refresh is fine: half an hour keeps a persistently
# failing prebuild from spinning while a healthy closeout still retries it.
PREBUILD_COOLDOWN_SECONDS = 1800.0
PREBUILD_FAILURE_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-prebuild-failure.json"
PREBUILD_LOCK_RELATIVE = Path(".runtime") / "launcher" / "desktop-shell-prebuild.lock"
DESKTOP_SHELL_BUILD_DEADLINE_SECONDS = 15 * 60
DESKTOP_SHELL_BUILD_CLEANUP_RESERVE_SECONDS = 5.0
DESKTOP_SHELL_BUILD_LOCK_POLL_SECONDS = 0.1
DESKTOP_SHELL_BUILD_CLOSE_RETRIES = 3
# Launch confirmation: Electron is single-instance per shared userData, so a
# spawned shell that finds a live owner forwards its argv and exits 0 within a
# second. ``launched`` is therefore only true once the child is observed holding
# the owner lock (or publishing its CDP record), not merely because Popen worked.
LAUNCH_CONFIRMATION_TIMEOUT_SECONDS = 5.0
LAUNCH_CONFIRMATION_POLL_SECONDS = 0.5
DESKTOP_DEBUG_FILE_NAME = "desktop_debug.json"
LAUNCH_ERROR_BOWED_OUT_TO_LIVE_OWNER = "BOWED_OUT_TO_LIVE_OWNER"
LAUNCH_ERROR_LAUNCH_CRASHED = "LAUNCH_CRASHED"
LAUNCH_ERROR_LIVE_OWNER_HOLDING_LOCK = "LIVE_OWNER_HOLDING_LOCK"
# PID reuse guard: a create-time drift beyond this means the pid now names a
# different process. Mirrors desktop_shell_owner.CREATE_TIME_TOLERANCE_SECONDS.
PID_IDENTITY_CREATE_TIME_TOLERANCE_SECONDS = 2.0


class BuildProcessRetirementError(RuntimeError):
    """A build process tree could not be confirmed closed; keep its lock and files."""

    def __init__(self, message: str, owner: OwnedProcess) -> None:
        super().__init__(message)
        self.owner = owner


@dataclass
class _PendingBuildRetirement:
    owner: OwnedProcess
    project_root: Path
    cleanup_paths: tuple[Path, ...]
    lock_relative: Path
    lock_snapshot: tuple[int, int, int, bytes] | None


_PENDING_BUILD_RETIREMENTS: list[_PendingBuildRetirement] = []


def _pending_build_retirement_for(
    project_root: Path,
    *,
    cleanup_path: Path | None = None,
) -> bool:
    root = project_root.resolve()
    target = cleanup_path.resolve() if cleanup_path is not None else None
    return any(
        item.project_root == root and (target is None or target in item.cleanup_paths)
        for item in _PENDING_BUILD_RETIREMENTS
    )


# The prebuild target: electron-builder writes win-unpacked below this output
# dir, exactly like the live package below dist/desktop. Promotion renames it
# over the live tree, so the layout must match.
STAGING_OUTPUT_DIR_RELATIVE = Path("dist") / "desktop-staging"
STAGING_WIN_UNPACKED_RELATIVE = STAGING_OUTPUT_DIR_RELATIVE / "win-unpacked"
STAGING_PROVENANCE_RELATIVE = (
    STAGING_WIN_UNPACKED_RELATIVE / "resources" / "app.asar.unpacked" / "package-provenance.json"
)
PREVIOUS_WIN_UNPACKED_RELATIVE = Path("dist") / "desktop" / ".win-unpacked-previous"
# A lock without a trustworthy live holder must not block refresh forever after
# a helper crash. Live holders remain authoritative even when a rebuild is
# longer than this grace period.
REFRESH_LOCK_MALFORMED_GRACE_SECONDS = 30.0
# A recycled PID is created after the lock it now fronts. Allow a few seconds
# of clock jitter before judging the live holder to be an impostor, so a
# holder that started in the same second as its lock is never evicted.
REFRESH_LOCK_PID_REUSE_TOLERANCE_SECONDS = 3.0

CREATE_NEW_PROCESS_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
CREATE_SUSPENDED = 0x00000004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS = 1.0
SCHEDULED_HELPER_LOCK_CLAIM_RETRY_SECONDS = 0.5
SCHEDULED_HELPER_LOCK_CLAIM_POLL_SECONDS = 0.025


def packaged_desktop_exe(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / PACKAGED_EXE_RELATIVE


def packaged_provenance_path(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / PROVENANCE_RELATIVE


def packaged_asar_path(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / ASAR_RELATIVE


def packaged_frontend_dist(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / PACKAGED_FRONTEND_RELATIVE


def unpackaged_electron_executable(project_root: Path | str = PROJECT_ROOT) -> Path | None:
    root = Path(project_root)
    windows_exe = root / UNPACKAGED_ELECTRON_EXE_RELATIVE
    if windows_exe.is_file():
        return windows_exe
    posix_bin = root / UNPACKAGED_ELECTRON_BIN_RELATIVE
    return posix_bin if posix_bin.is_file() else None


def unpackaged_main_js(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / UNPACKAGED_MAIN_RELATIVE


def unpackaged_provenance_path(project_root: Path | str = PROJECT_ROOT) -> Path:
    return Path(project_root) / UNPACKAGED_PROVENANCE_RELATIVE


def _refresh_failure_path(project_root: Path | str) -> Path:
    return Path(project_root) / REFRESH_FAILURE_RELATIVE


def _refresh_lock_path(project_root: Path | str, lock_relative: Path = REFRESH_LOCK_RELATIVE) -> Path:
    return Path(project_root) / lock_relative


def _prebuild_failure_path(project_root: Path | str) -> Path:
    return Path(project_root) / PREBUILD_FAILURE_RELATIVE


def _record_shell_failure_marker(path: Path, *, reason: str, detail: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "failedAt": datetime.now(timezone.utc).isoformat(),
        "reason": str(reason or "failed"),
        "detail": str(detail or "")[:800],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_shell_failure_marker(path: Path) -> None:
    if not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        return


def _recent_shell_failure_marker(path: Path, *, cooldown_seconds: float) -> dict[str, Any] | None:
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


def record_desktop_shell_refresh_failure(
    project_root: Path | str,
    *,
    reason: str,
    detail: str,
) -> None:
    _record_shell_failure_marker(
        _refresh_failure_path(project_root),
        reason=str(reason or "refresh_failed"),
        detail=detail,
    )


def clear_desktop_shell_refresh_failure(project_root: Path | str) -> None:
    _clear_shell_failure_marker(_refresh_failure_path(project_root))


def recent_desktop_shell_refresh_failure(
    project_root: Path | str,
    *,
    cooldown_seconds: float = REFRESH_COOLDOWN_SECONDS,
) -> dict[str, Any] | None:
    return _recent_shell_failure_marker(
        _refresh_failure_path(project_root),
        cooldown_seconds=cooldown_seconds,
    )


def _acquire_desktop_shell_refresh_lock(
    project_root: Path | str,
    lock_relative: Path = REFRESH_LOCK_RELATIVE,
) -> bool:
    path = _refresh_lock_path(project_root, lock_relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(3):
        with _refresh_lock_breaker(path) as acquired:
            if not acquired:
                return False
            try:
                started_at = datetime.now(timezone.utc).isoformat()
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "pid": os.getpid(),
                                "startedAt": started_at,
                                "ownerToken": uuid4().hex,
                            }
                        )
                    )
                return True
            except FileExistsError:
                # Do not unlink after a separate stale check. Moving the observed
                # lock to a unique quarantine name is one filesystem operation,
                # while this process keeps the breaker for the whole check.
                if not _quarantine_stale_refresh_lock_locked(path):
                    return False
            except OSError:
                return False
    return False


def _assign_desktop_shell_refresh_helper(
    project_root: Path | str,
    helper_pid: int,
    lock_relative: Path = REFRESH_LOCK_RELATIVE,
    *,
    lock_token: str,
) -> tuple[int, int, int, bytes] | None:
    """Transfer refresh-lock ownership from the scheduler to its helper."""

    path = _refresh_lock_path(project_root, lock_relative)
    with _refresh_lock_breaker(path) as acquired:
        if not acquired:
            raise OSError(f"desktop shell refresh lock is busy: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise OSError(f"desktop shell refresh lock could not be read: {path}") from exc
        if not isinstance(payload, dict):
            raise OSError(f"desktop shell refresh lock is invalid: {path}")
        if not lock_token or payload.get("ownerToken") != lock_token:
            raise OSError(f"desktop shell refresh lock owner changed before handoff: {path}")
        started_at = str(payload.get("startedAt") or "").strip() or datetime.now(timezone.utc).isoformat()
        payload.update({"pid": int(helper_pid), "startedAt": started_at})
        atomic_write_json(path, payload)
        snapshot = _refresh_lock_snapshot(path)
        if snapshot is None:
            raise OSError(f"desktop shell refresh lock handoff could not be verified: {path}")
        return snapshot


def _claim_scheduled_desktop_shell_helper_lock(
    project_root: Path | str,
    *,
    lock_relative: Path,
    lock_token: str,
) -> bool:
    """Transfer the wrapper's lock to its real Python helper process.

    The venv ``pythonw.exe`` launcher may remain alive as the helper's parent,
    so the lock starts at ``Popen.pid`` and must be claimed by its direct child
    before any prebuild ownership checks or refresh work begin.
    """

    token = str(lock_token or "")
    if not token:
        return False
    path = _refresh_lock_path(project_root, lock_relative)
    current_pid = os.getpid()
    parent_pid = os.getppid()
    deadline = time.monotonic() + max(0.0, SCHEDULED_HELPER_LOCK_CLAIM_RETRY_SECONDS)
    while True:
        with _refresh_lock_breaker(path) as acquired:
            if acquired:
                snapshot = _refresh_lock_snapshot(path)
                if snapshot is None:
                    return False
                try:
                    payload = json.loads(snapshot[3].decode("utf-8"))
                    holder_pid = int(payload.get("pid") or 0) if isinstance(payload, dict) else 0
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    return False
                if not isinstance(payload, dict) or payload.get("ownerToken") != token:
                    return False
                if holder_pid not in {current_pid, parent_pid}:
                    return False

                # The lock timestamp represents the actual worker lifetime after
                # handoff, so stale-lock recovery never inherits wrapper startup delay.
                started_at = datetime.now(timezone.utc).isoformat()
                payload.update({"pid": current_pid, "startedAt": started_at})
                try:
                    atomic_write_json(path, payload)
                except OSError:
                    return False
                claimed = _refresh_lock_snapshot(path)
                if claimed is None:
                    return False
                try:
                    verified = json.loads(claimed[3].decode("utf-8"))
                    verified_pid = int(verified.get("pid") or 0) if isinstance(verified, dict) else 0
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    return False
                return (
                    isinstance(verified, dict)
                    and verified.get("ownerToken") == token
                    and verified_pid == current_pid
                    and verified.get("startedAt") == started_at
                )

        # Another short stale-lock inspection may own the nonblocking breaker.
        # Retry only that transient condition; an identity/token mismatch exits above.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(SCHEDULED_HELPER_LOCK_CLAIM_POLL_SECONDS, remaining))


def _refresh_lock_is_stale(path: Path) -> bool:
    """Return whether a refresh lock can be reclaimed after helper loss."""

    payload: dict[str, Any] | None = None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            payload = parsed
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        payload = None

    pid = 0
    started_at: datetime | None = None
    if payload is not None:
        try:
            pid = int(payload.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        raw_started_at = str(payload.get("startedAt") or "").strip()
        if raw_started_at:
            try:
                started_at = datetime.fromisoformat(raw_started_at.replace("Z", "+00:00"))
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                else:
                    started_at = started_at.astimezone(timezone.utc)
            except ValueError:
                started_at = None

    if pid > 0:
        # A dead holder is definitive even when its lock file is young. A live
        # PID remains authoritative: a long rebuild is not stale merely due to
        # age.
        if not _pid_alive(pid):
            return True
        # PID reuse: an OS can hand the holder's PID to an unrelated process
        # after a hard kill, which would keep a leaked lock alive forever. The
        # recycled process is created after the lock's startedAt, so it cannot
        # be the holder. When the holder's creation time cannot be determined
        # (no psutil or access denied), stay conservative and keep treating
        # the live PID as authoritative so a long rebuild is never evicted.
        if started_at is None:
            return False
        try:
            started_epoch = started_at.timestamp()
        except (OSError, OverflowError, ValueError):
            return False
        create_time = _process_create_time(pid)
        if create_time is None:
            return False
        return create_time > started_epoch + REFRESH_LOCK_PID_REUSE_TOLERANCE_SECONDS

    try:
        age_anchor = started_at.timestamp() if started_at is not None else path.stat().st_mtime
        age_seconds = datetime.now(timezone.utc).timestamp() - age_anchor
    except OSError:
        return False
    return age_seconds >= REFRESH_LOCK_MALFORMED_GRACE_SECONDS


def _refresh_lock_snapshot(path: Path) -> tuple[int, int, int, bytes] | None:
    try:
        stat = path.stat()
        return (int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns), path.read_bytes())
    except OSError:
        return None


@dataclass
class _ScheduledHelperOwner:
    process: subprocess.Popen[Any]
    job: WindowsProcessJob | None


@dataclass
class _PendingScheduledHelperRetirement:
    owner: _ScheduledHelperOwner
    project_root: Path
    lock_relative: Path
    lock_token: str


_PENDING_SCHEDULED_HELPER_RETIREMENTS: list[_PendingScheduledHelperRetirement] = []
# Refresh and prebuild use different lock files but share process and Job owners.
_PENDING_SCHEDULED_HELPER_RETIREMENTS_LOCK = threading.RLock()


class ScheduledHelperRetirementError(RuntimeError):
    """A failed helper handoff could not yet be retired safely."""

    def __init__(self, message: str, owner: _ScheduledHelperOwner) -> None:
        super().__init__(message)
        self.owner = owner


def _scheduled_helper_lock_token(snapshot: tuple[int, int, int, bytes] | None) -> str:
    if snapshot is None:
        return ""
    try:
        payload = json.loads(snapshot[3].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return ""
    return str(payload.get("ownerToken") or "").strip() if isinstance(payload, dict) else ""


def _release_scheduled_helper_lock(
    project_root: Path,
    *,
    lock_relative: Path,
    lock_token: str,
) -> bool:
    """Release this handoff by token, allowing its PID to change at claim time."""

    path = _refresh_lock_path(project_root, lock_relative)
    with _refresh_lock_breaker(path) as acquired:
        if not acquired:
            return False
        current = _refresh_lock_snapshot(path)
        if current is None:
            return not path.exists()
        try:
            payload = json.loads(current[3].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("ownerToken") != lock_token:
            # A later claimant replaced the lock. Its lock is untouched, and
            # cleanup for this already-retired helper is complete.
            return True
        try:
            path.unlink()
        except OSError:
            return False
        return True


def _new_scheduled_helper_job() -> WindowsProcessJob | None:
    return WindowsProcessJob() if os.name == "nt" else None


def _resume_scheduled_helper(process: subprocess.Popen[Any]) -> None:
    """Resume the Windows venv launcher only after it owns the refresh lock."""

    if os.name != "nt":
        return
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required to resume a suspended desktop helper") from exc
    try:
        psutil.Process(int(process.pid)).resume()
    except psutil.Error as exc:
        raise OSError(f"desktop helper could not be resumed: {exc}") from exc


def _wait_scheduled_helper_process_exit(process: subprocess.Popen[Any], *, timeout: float) -> bool:
    try:
        process.wait(timeout=max(0.0, float(timeout)))
    except (subprocess.TimeoutExpired, OSError):
        return False
    try:
        return process.poll() is not None
    except OSError:
        return False


def _retire_scheduled_helper_owner(owner: _ScheduledHelperOwner, *, timeout: float) -> bool:
    """Stop and confirm the helper process tree within a bounded deadline."""

    deadline = time.monotonic() + max(0.0, float(timeout))
    process = owner.process
    job = owner.job
    if job is not None:
        try:
            # Pending failures must still die with the scheduler if it exits
            # before a later retry can retire the retained owner.
            job.set_kill_on_job_close(True)
            if job.active_count() > 0:
                job.terminate()
        except OSError:
            try:
                job.terminate()
            except OSError:
                pass

    try:
        already_exited = process.poll() is not None
    except OSError:
        already_exited = False
    if not already_exited:
        try:
            process.terminate()
        except OSError:
            pass
        first_wait = min(0.2, max(0.0, deadline - time.monotonic()))
        if not _wait_scheduled_helper_process_exit(process, timeout=first_wait):
            if job is not None:
                try:
                    job.terminate()
                except OSError:
                    pass
            try:
                process.kill()
            except OSError:
                pass
            if not _wait_scheduled_helper_process_exit(
                process,
                timeout=max(0.0, deadline - time.monotonic()),
            ):
                return False

    if job is None:
        return True
    while time.monotonic() < deadline:
        try:
            if job.active_count() == 0:
                return True
        except OSError:
            return False
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    return False


def _close_scheduled_helper_owner(owner: _ScheduledHelperOwner) -> bool:
    try:
        if owner.job is not None:
            owner.job.close()
            owner.job = None
        process_handle = getattr(owner.process, "_handle", None)
        close_handle = getattr(process_handle, "Close", None)
        if callable(close_handle):
            close_handle()
            owner.process._handle = None  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def _register_pending_scheduled_helper_retirement(
    project_root: Path,
    owner: _ScheduledHelperOwner,
    *,
    lock_relative: Path,
    lock_token: str,
) -> None:
    with _PENDING_SCHEDULED_HELPER_RETIREMENTS_LOCK:
        if any(item.owner is owner for item in _PENDING_SCHEDULED_HELPER_RETIREMENTS):
            return
        _PENDING_SCHEDULED_HELPER_RETIREMENTS.append(
            _PendingScheduledHelperRetirement(
                owner=owner,
                project_root=project_root.resolve(),
                lock_relative=lock_relative,
                lock_token=lock_token,
            )
        )


def _retry_pending_scheduled_helper_retirements(project_root: Path) -> bool:
    with _PENDING_SCHEDULED_HELPER_RETIREMENTS_LOCK:
        root = project_root.resolve()
        for item in tuple(_PENDING_SCHEDULED_HELPER_RETIREMENTS):
            if item.project_root != root:
                continue
            retired = _retire_scheduled_helper_owner(
                item.owner,
                timeout=SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS,
            )
            if not retired:
                return False
            if not _release_scheduled_helper_lock(
                item.project_root,
                lock_relative=item.lock_relative,
                lock_token=item.lock_token,
            ):
                return False
            if not _close_scheduled_helper_owner(item.owner):
                return False
            _PENDING_SCHEDULED_HELPER_RETIREMENTS.remove(item)
        return True


def _start_scheduled_desktop_shell_helper(
    args: list[str],
    *,
    project_root: Path,
    lock_relative: Path,
    label: str,
) -> int:
    lock_path = _refresh_lock_path(project_root, lock_relative)
    initial_lock_snapshot = _refresh_lock_snapshot(lock_path)
    lock_token = _scheduled_helper_lock_token(initial_lock_snapshot)
    if initial_lock_snapshot is None or not lock_token:
        _release_desktop_shell_refresh_lock(project_root, lock_relative=lock_relative)
        raise RuntimeError(f"desktop shell {label} lock ownership could not be verified")

    job: WindowsProcessJob | None = None
    try:
        job = _new_scheduled_helper_job()
    except OSError as exc:
        _release_scheduled_helper_lock(
            project_root,
            lock_relative=lock_relative,
            lock_token=lock_token,
        )
        raise RuntimeError(f"desktop shell {label} helper ownership could not be created: {exc}") from exc

    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    if os.name == "nt":
        flags |= CREATE_SUSPENDED
    kwargs = no_window_subprocess_kwargs(creationflags=flags)
    try:
        process = subprocess.Popen(
            [*args, "--scheduled-owner-token", lock_token],
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError as exc:
        if job is not None:
            try:
                job.close()
            except OSError:
                pass
        released = _release_scheduled_helper_lock(
            project_root,
            lock_relative=lock_relative,
            lock_token=lock_token,
        )
        if not released:
            raise RuntimeError(f"desktop shell {label} helper did not start and its lock cleanup is pending") from exc
        raise RuntimeError(f"desktop shell {label} helper did not start: {exc}") from exc

    helper_pid = int(getattr(process, "pid", 0) or 0)
    owner = _ScheduledHelperOwner(process=process, job=job)
    try:
        if helper_pid <= 0:
            raise OSError("desktop shell helper returned an invalid process id")
        if job is not None:
            job.assign_handle(process._handle)
        assigned_snapshot = _assign_desktop_shell_refresh_helper(
            project_root,
            helper_pid,
            lock_relative=lock_relative,
            lock_token=lock_token,
        )
        if assigned_snapshot is None:
            assigned_snapshot = _refresh_lock_snapshot(lock_path)
        if assigned_snapshot is None or _scheduled_helper_lock_token(assigned_snapshot) != lock_token:
            raise OSError(f"desktop shell {label} lock handoff could not be verified")
        _resume_scheduled_helper(process)
        if owner.job is not None:
            owner.job.set_kill_on_job_close(False)
            owner.job.close()
            owner.job = None
        return helper_pid
    except BaseException as exc:
        retired = _retire_scheduled_helper_owner(
            owner,
            timeout=SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS,
        )
        if retired and _release_scheduled_helper_lock(
            project_root,
            lock_relative=lock_relative,
            lock_token=lock_token,
        ):
            if not _close_scheduled_helper_owner(owner):
                _register_pending_scheduled_helper_retirement(
                    project_root,
                    owner,
                    lock_relative=lock_relative,
                    lock_token=lock_token,
                )
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ScheduledHelperRetirementError(
                    f"desktop shell {label} helper exited but owner handles remain open",
                    owner,
                ) from exc
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise RuntimeError(f"desktop shell {label} helper could not be started safely: {exc}") from exc
        _register_pending_scheduled_helper_retirement(
            project_root,
            owner,
            lock_relative=lock_relative,
            lock_token=lock_token,
        )
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise ScheduledHelperRetirementError(
            f"desktop shell {label} helper retirement is unconfirmed; its lock remains held for retry",
            owner,
        ) from exc


@contextmanager
def _refresh_lock_breaker(path: Path) -> Iterator[bool]:
    """Serialize stale-lock inspection and quarantine across refresh claimants.

    The breaker file is persistent, but its OS-level advisory lock is released
    automatically when a process exits. That avoids introducing a second stale
    PID lock while still preventing a check-then-replace race between helpers.
    """

    breaker_path = path.with_name(f"{path.name}.break")
    breaker_path.parent.mkdir(parents=True, exist_ok=True)
    handle = breaker_path.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
        acquired = True
        yield True
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _quarantine_stale_refresh_lock_locked(path: Path) -> bool:
    """Atomically move a stale lock aside while the breaker is already held."""

    if not path.exists():
        return True
    before = _refresh_lock_snapshot(path)
    if before is None or not _refresh_lock_is_stale(path):
        return False
    # A claimant can replace the lock while a stale check is running. Do
    # not move it unless the exact observed bytes and metadata still match.
    if _refresh_lock_snapshot(path) != before:
        return False
    quarantine = path.with_name(f"{path.name}.stale-{os.getpid()}-{uuid4().hex}")
    try:
        os.replace(path, quarantine)
    except FileNotFoundError:
        # Another claimant won the race; retry the exclusive create.
        return True
    except OSError:
        return False
    try:
        quarantine.unlink()
    except OSError:
        # The original lock was moved out of the way. Leaving uniquely named
        # residue is safer than deleting an unknown target.
        pass
    return True


def _quarantine_stale_refresh_lock(path: Path) -> bool:
    """Atomically move a stale lock aside, then let acquisition retry."""

    with _refresh_lock_breaker(path) as acquired:
        if not acquired:
            return False
        return _quarantine_stale_refresh_lock_locked(path)


def _release_desktop_shell_refresh_lock(
    project_root: Path | str,
    lock_relative: Path = REFRESH_LOCK_RELATIVE,
) -> None:
    path = _refresh_lock_path(project_root, lock_relative)
    with _refresh_lock_breaker(path) as acquired:
        if not acquired or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            holder_pid = int(payload.get("pid") or 0) if isinstance(payload, dict) else 0
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            holder_pid = 0
        # A parent creates the lock and then hands ownership to the detached
        # helper. Never let late cleanup from an older process remove a newer
        # helper's lock.
        if holder_pid > 0 and holder_pid != os.getpid():
            return
        try:
            path.unlink()
        except OSError:
            return


def _desktop_shell_lock_owned_by_current_process(
    project_root: Path,
    *,
    lock_relative: Path = PREBUILD_LOCK_RELATIVE,
) -> bool:
    path = _refresh_lock_path(project_root, lock_relative)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict) and int(payload.get("pid") or 0) == os.getpid()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _ensure_desktop_shell_build_lock(root: Path, *, deadline: float) -> None:
    _retry_pending_build_retirements(root, deadline=deadline)
    if _desktop_shell_lock_owned_by_current_process(root, lock_relative=PREBUILD_LOCK_RELATIVE):
        return
    _wait_for_desktop_shell_build_lock(root, deadline=deadline)


def _register_pending_build_retirement(
    project_root: Path,
    owner: OwnedProcess,
    *,
    cleanup_paths: tuple[Path, ...],
    lock_relative: Path = PREBUILD_LOCK_RELATIVE,
) -> None:
    """Retain build artifacts and the exact lock until an owner can be closed."""

    if any(item.owner is owner for item in _PENDING_BUILD_RETIREMENTS):
        return
    root = project_root.resolve()
    lock_path = _refresh_lock_path(root, lock_relative)
    _PENDING_BUILD_RETIREMENTS.append(
        _PendingBuildRetirement(
            owner=owner,
            project_root=root,
            cleanup_paths=tuple(path.resolve() for path in cleanup_paths),
            lock_relative=lock_relative,
            lock_snapshot=_refresh_lock_snapshot(lock_path),
        )
    )


def _release_pending_build_lock(item: _PendingBuildRetirement) -> bool:
    """Release only the lock snapshot captured for this unretired owner."""

    if item.lock_snapshot is None:
        return True
    lock_path = _refresh_lock_path(item.project_root, item.lock_relative)
    with _refresh_lock_breaker(lock_path) as acquired:
        if not acquired:
            return False
        current = _refresh_lock_snapshot(lock_path)
        if current is None or current != item.lock_snapshot:
            return True
        try:
            lock_path.unlink()
        except OSError:
            return False
        return True


def _retry_pending_build_retirements(project_root: Path, *, deadline: float) -> None:
    """Retire a previously unconfirmed build tree before allowing new work."""

    root = project_root.resolve()
    for item in tuple(_PENDING_BUILD_RETIREMENTS):
        if item.project_root != root:
            continue
        _close_owned_process(item.owner, deadline=deadline)
        for path in item.cleanup_paths:
            _remove_owned_shell_tree(path, within=item.project_root)
            if path.exists():
                raise RuntimeError(f"desktop build stage cleanup could not be confirmed: {path}")
        if not _release_pending_build_lock(item):
            raise RuntimeError("desktop build lock cleanup could not be confirmed")
        _PENDING_BUILD_RETIREMENTS.remove(item)


FRONTEND_ONLY_STALE_REASONS = {
    "missing_frontend_provenance",
    "frontend_package_content_mismatch",
    "frontend_source_stale",
    "frontend_inspection_failed",
    "current_frontend_tree_unavailable",
    "frontend_release_mismatch",
    "frontend_source_mismatch",
}


def _usable_active_frontend_release(root: Path) -> bool:
    """Whether the workspace active frontend release can serve the launcher.

    Aligned with the Electron fallback chain in
    ``desktop/electron/src/protocol/launcherAppProtocol.ts``
    ``resolveWorkspaceActiveRelease``: the active release is usable only when
    the ``active.json`` pointer resolves to a real release under the releases
    directory (a valid, complete release) and its ``index.html`` is readable.
    A legacy ``web/dist`` fallback does not count: with no active release the
    packaged launcher window would serve the packaged snapshot, so frontend
    staleness must block again.
    """

    try:
        dist = resolve_active_frontend_dist(root)
        if dist.parent != frontend_releases_dir(root):
            return False
        index = dist / "index.html"
        return index.is_file() and bool(index.read_text(encoding="utf-8", errors="replace").strip())
    except Exception:
        # Freshness inspection must never raise over release resolution.
        return False


def _electron_package_block_reason(
    root: Path, *, current_tree: str, packaged_tree: str, source_newer: bool,
    package_root: Path | None = None,
) -> str:
    exe = packaged_desktop_exe(root) if package_root is None else package_root / "Vibelution.exe"
    asar = packaged_asar_path(root) if package_root is None else package_root / "resources/app.asar"
    if not exe.is_file() or not asar.is_file():
        return "missing_package"
    if not packaged_tree:
        return "missing_provenance"
    if not current_tree:
        return "current_electron_tree_unavailable"
    if packaged_tree != current_tree:
        return "provenance_mismatch"
    if source_newer:
        return "source_newer_than_asar"
    return ""


def _assistant_payload_builder() -> Any:
    # Ordinary unpackaged/bootstrap reads must not import build dependencies.
    from scripts import build_assistant_runtime

    return build_assistant_runtime


def _assistant_source_content_sha256(root: Path) -> str:
    """Use the payload owner's exact source selection and content-hash domain."""
    assistant_payload = _assistant_payload_builder()
    root = assistant_payload._trusted_root(root)
    entries = []
    for path in assistant_payload._source_files(root):
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        entries.append({"path": "source/" + path.relative_to(root).as_posix(),
                        "size": path.stat().st_size, "sha256": digest})
    return assistant_payload._content_hash(entries, "source/")


def _assistant_package_block_reason(root: Path, package: Path, *, full: bool = False) -> str:
    evidence = _read_json(package / "resources/app.asar.unpacked/package-provenance.json").get("assistant")
    hashes = ("manifestSha256", "contentSha256", "sourceContentSha256", "runtimeContentSha256", "requirementsSha256",
              "contractsSha256")
    if not isinstance(evidence, dict) or any(not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key, ""))) for key in hashes):
        return "missing_assistant_provenance"
    try:
        assistant_payload = _assistant_payload_builder()
        payload = assistant_payload._trusted_root(package / "resources/launcher-assistant")
        manifest_path = assistant_payload._checked(payload, "manifest.json")
        if not manifest_path.is_file() or manifest_path.stat().st_size > 32 * 1024 * 1024:
            return "missing_assistant_payload"
        content = manifest_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != evidence["manifestSha256"]:
            return "assistant_manifest_mismatch"
        manifest = json.loads(content)
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != evidence.get(key) for key in (*hashes[2:], "pythonVersion")
        ) or not re.fullmatch(r"3\.[0-9]+\.[0-9]+", str(evidence.get("pythonVersion", ""))):
            return "assistant_manifest_mismatch"
        if _assistant_source_content_sha256(root) != evidence["sourceContentSha256"]:
            return "assistant_source_mismatch"
        if full:
            try:
                assistant_payload.verify_launcher_assistant_payload(
                    payload, expected_manifest_sha256=evidence["manifestSha256"],
                    expected_content_sha256=evidence["contentSha256"],
                )
            except assistant_payload.AssistantPayloadContentMismatch:
                return "assistant_package_content_mismatch"
            # Workspace edits are not serialized by the package build lock.
            # Keep the original post-verification source proof as well as the
            # fast rejection above, so a long payload read cannot admit drift.
            if _assistant_source_content_sha256(root) != evidence["sourceContentSha256"]:
                return "assistant_source_mismatch"
    except (OSError, ValueError, TypeError):
        return "assistant_payload_invalid"
    return ""


def _assert_assistant_package(root: Path, package: Path, *, deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("assistant validation exceeded the desktop build deadline")
    reason = _assistant_package_block_reason(root, package, full=True)
    if reason:
        raise RuntimeError(f"desktop package assistant refused: {reason}")
    if time.monotonic() >= deadline:
        raise TimeoutError("assistant validation exceeded the desktop build deadline")


def inspect_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return whether the packaged Electron shell and Launcher frontend are current."""

    return _inspect_desktop_shell_package(Path(project_root))


def _inspect_desktop_shell_package(
    root: Path, package_root: Path | None = None, *, for_reuse: bool = False,
) -> dict[str, Any]:
    """Inspect live or staged bytes using the same source and frontend owners.

    Reuse requires full assistant verification and clean Electron sources: the
    existing provenance cannot prove which dirty source bytes a build consumed.
    Live inspection retains its timestamp compatibility and public payload.
    """

    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    current_commit = _git_tree_hash(root, "HEAD")
    provenance_path = packaged_provenance_path(root) if package_root is None else package_root / "resources/app.asar.unpacked/package-provenance.json"
    provenance = _read_json(provenance_path)
    packaged_tree = str(provenance.get("electronTreeHash") or "").strip()
    exe_path = packaged_desktop_exe(root) if package_root is None else package_root / "Vibelution.exe"
    asar_path = packaged_asar_path(root) if package_root is None else package_root / "resources/app.asar"
    source_newer = _electron_sources_newer_than_asar(root) if package_root is None else _electron_sources_newer_than(root, asar_path)
    packaged_frontend_path = packaged_frontend_dist(root) if package_root is None else package_root / "resources/web-dist"
    packaged_frontend_hash = _frontend_directory_content_sha256(packaged_frontend_path)
    expected_frontend_hash = str(provenance.get("frontendContentSha256") or "").strip().lower()
    packaged_frontend_tree = str(provenance.get("frontendTreeHash") or "").strip()
    packaged_source_commit = str(provenance.get("sourceCommit") or "").strip()
    packaged_frontend_build_key = str(provenance.get("frontendBuildKey") or "").strip()
    current_frontend_hash = ""
    current_frontend_tree = ""
    current_frontend_source_commit = ""
    current_frontend_build_key = ""
    current_frontend_dist = ""
    frontend_provenance: dict[str, Any] = {}
    frontend_build_current: bool | None = None
    if exe_path.is_file() and asar_path.is_file():
        try:
            frontend_status = inspect_frontend_build(root)
            frontend_build_current = bool(frontend_status.get("current"))
            current_frontend_dist = str(frontend_status.get("dist") or resolve_active_frontend_dist(root))
            frontend_provenance = frontend_status.get("provenance")
            if not isinstance(frontend_provenance, dict):
                frontend_provenance = {}
            frontend_inputs = frontend_status.get("buildInputs")
            if not isinstance(frontend_inputs, dict):
                frontend_inputs = {}
            current_frontend_tree = str(
                frontend_inputs.get("frontendTree")
                or frontend_provenance.get("frontendTree")
                or ""
            ).strip()
            current_frontend_source_commit = str(
                frontend_inputs.get("sourceCommit")
                or frontend_provenance.get("sourceCommit")
                or ""
            ).strip()
            current_frontend_build_key = str(frontend_status.get("buildKey") or "").strip()
            current_frontend_hash = _frontend_directory_content_sha256(Path(current_frontend_dist))
        except Exception:
            # A failure to inspect current source cannot establish package freshness.
            frontend_build_current = None

    def frontend_block_reason() -> str:
        if not packaged_frontend_path.is_dir() or not expected_frontend_hash or not packaged_frontend_tree:
            return "missing_frontend_provenance"
        if not packaged_frontend_hash or packaged_frontend_hash != expected_frontend_hash:
            return "frontend_package_content_mismatch"
        if frontend_build_current is not True:
            return "frontend_source_stale" if frontend_build_current is False else "frontend_inspection_failed"
        if not current_frontend_tree:
            return "current_frontend_tree_unavailable"
        if not current_frontend_hash or current_frontend_hash != packaged_frontend_hash:
            return "frontend_release_mismatch"
        if current_frontend_tree and packaged_frontend_tree != current_frontend_tree:
            return "frontend_source_mismatch"
        if for_reuse and (
            not re.fullmatch(r"[0-9a-f]{64}", current_frontend_build_key)
            or packaged_frontend_build_key != current_frontend_build_key
            or frontend_provenance.get("buildKey") != current_frontend_build_key
        ):
            return "frontend_build_key_mismatch"
        if for_reuse and (
            frontend_provenance.get("frontendTree") != current_frontend_tree
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(frontend_provenance.get("sourceCommit") or ""))
            or provenance.get("frontendSourceCommit") != frontend_provenance.get("sourceCommit")
        ):
            return "frontend_source_commit_mismatch"
        return ""

    package_block_reason = _electron_package_block_reason(
        root, current_tree=current_tree, packaged_tree=packaged_tree, source_newer=source_newer,
        package_root=package_root,
    )
    if not package_block_reason and for_reuse:
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", current_commit) or packaged_source_commit != current_commit:
            package_block_reason = "source_commit_mismatch"
        elif not _electron_package_sources_clean(root):
            package_block_reason = "electron_source_unverified"
    if not package_block_reason and for_reuse:
        # Already-stale frontend inputs cannot become reusable by reading the
        # assistant payload. This early rejection never establishes freshness.
        package_block_reason = frontend_block_reason()
    if not package_block_reason:
        package_block_reason = _assistant_package_block_reason(root, exe_path.parent, full=for_reuse)
    if not package_block_reason:
        # Preserve the live inspection order and the post-verification checks;
        # package directories and the active release can change during reads.
        package_block_reason = frontend_block_reason()
    if package_block_reason:
        reason = package_block_reason
        stale = True
    elif for_reuse and (
        not _usable_active_frontend_release(root)
        or Path(current_frontend_dist).resolve() != resolve_active_frontend_dist(root).resolve()
    ):
        reason = "frontend_release_mismatch"
        stale = True
    else:
        reason = "current"
        stale = False
    refresh_block = recent_desktop_shell_refresh_failure(root)
    active_release_usable = _usable_active_frontend_release(root)
    # launchBlocking answers one question: can the packaged exe safely serve
    # the current checkout's first window? Electron-tree/package reasons always
    # block. Frontend-only staleness is advisory while a usable workspace
    # active release exists, because both shell forms' launcher windows prefer
    # that release (launcherAppProtocol.ts resolveLauncherDistRoot) and the
    # workbench window is served by the backend regardless of shell form; with
    # no usable active release the packaged snapshot is what would be served,
    # so frontend staleness blocks again. Full `stale`/`reason` stay
    # authoritative for status display and background snapshot convergence.
    launch_blocking = bool(stale and not (reason in FRONTEND_ONLY_STALE_REASONS and active_release_usable))
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "stale": stale,
        "reason": reason,
        "activeFrontendReleaseUsable": active_release_usable,
        "launchBlocking": launch_blocking,
        "packagedElectronTree": packaged_tree,
        "currentElectronTree": current_tree,
        "packagedSourceCommit": packaged_source_commit,
        "currentCommit": current_commit,
        "packagedFrontendTree": packaged_frontend_tree,
        "currentFrontendTree": current_frontend_tree,
        "packagedFrontendContentSha256": packaged_frontend_hash,
        "expectedFrontendContentSha256": expected_frontend_hash,
        "currentFrontendContentSha256": current_frontend_hash,
        "packagedFrontendBuildKey": packaged_frontend_build_key,
        "currentFrontendBuildKey": current_frontend_build_key,
        "packagedFrontendSourceCommit": str(provenance.get("frontendSourceCommit") or "").strip(),
        "currentFrontendSourceCommit": current_frontend_source_commit,
        "currentFrontendDist": current_frontend_dist,
        "frontendBuildCurrent": frontend_build_current,
        "packagedFrontendDist": str(packaged_frontend_path),
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


def inspect_desktop_shell_launch_readiness(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return only the launch blocker, never a full freshness observation.

    With a usable workspace release, frontend-only problems are already advisory
    in inspect_desktop_shell. Its source is verified again at backend admission;
    neither hashing the packaged snapshot nor rescanning sources can change this
    shell gate. Without that release the packaged frontend is used, so retain the
    complete inspection and its content proof.
    """
    root = Path(project_root)
    if not _usable_active_frontend_release(root):
        status = inspect_desktop_shell(root)
        return {
            "schemaVersion": 1, "launchBlocking": status["launchBlocking"], "reason": status["reason"],
            "currentElectronTree": str(status.get("currentElectronTree") or ""),
        }
    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    provenance = _read_json(packaged_provenance_path(root))
    reason = _electron_package_block_reason(
        root,
        current_tree=current_tree,
        packaged_tree=str(provenance.get("electronTreeHash") or "").strip(),
        source_newer=_electron_sources_newer_than_asar(root),
    )
    if not reason:
        reason = _assistant_package_block_reason(root, packaged_desktop_exe(root).parent)
    # Admission may outlive an active-pointer change. Do not skip the packaged
    # frontend proof if the workspace release disappeared during the shell read.
    if not reason and not _usable_active_frontend_release(root):
        status = inspect_desktop_shell(root)
        return {
            "schemaVersion": 1, "launchBlocking": status["launchBlocking"], "reason": status["reason"],
            "currentElectronTree": str(status.get("currentElectronTree") or ""),
        }
    return {
        "schemaVersion": 1, "launchBlocking": bool(reason), "reason": reason or "active_frontend_release",
        "currentElectronTree": current_tree,
    }


def schedule_desktop_shell_refresh(
    *,
    wait_pid: int,
    then_lifecycle: str = "",
    project_root: Path | str = PROJECT_ROOT,
    python_executable: str | None = None,
    force: bool = False,
    shell_kind: str = "",
    launch_request_id: str = "",
    launch_request_operation: str = "",
) -> dict[str, Any]:
    """Start a detached helper that rebuilds the shell after ``wait_pid`` exits."""

    root = Path(project_root)
    request_args = _desktop_launch_request_args(launch_request_id, launch_request_operation)
    if not _retry_pending_scheduled_helper_retirements(root):
        return {
            "schemaVersion": 1,
            "scheduled": False,
            "helperPid": 0,
            "waitPid": int(wait_pid),
            "thenLifecycle": str(then_lifecycle or "").strip().lower(),
            "reason": "helper_retirement_pending",
        }
    if force:
        clear_desktop_shell_refresh_failure(root)
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
    kind = str(shell_kind or "").strip().lower()
    if kind:
        args.extend(["--shell-kind", kind])
    args.extend(request_args)
    helper_pid = _start_scheduled_desktop_shell_helper(
        args,
        project_root=root,
        lock_relative=REFRESH_LOCK_RELATIVE,
        label="refresh",
    )
    return {
        "schemaVersion": 1,
        "scheduled": True,
        "helperPid": helper_pid,
        "waitPid": int(wait_pid),
        "thenLifecycle": lifecycle,
    }


def run_desktop_shell_refresh(
    *,
    wait_pid: int = 0,
    then_lifecycle: str = "",
    project_root: Path | str = PROJECT_ROOT,
    wait_timeout_seconds: float = 180.0,
    shell_kind: str = "",
    launch_request_id: str = "",
    launch_request_operation: str = "",
) -> dict[str, Any]:
    """Wait for the old shell to exit, verify the owner lock is free, rebuild, relaunch.

    Every launch here must become the new primary. The owner lock is checked
    after the pid wait (or immediately with ``wait_pid`` 0) before any build,
    and again inside each launch (``expect_primary``) so neither the normal
    relaunch, the rebuild-failure fallback nor the unpackaged relaunch can spawn
    an instance that would only bow out to a still-live shell. ``refreshed`` is
    true only when the launch was confirmed (see ``_launch_result_replaces_shell``).
    """

    root = Path(project_root)
    request_options = ({"launch_request_id": launch_request_id,
        "launch_request_operation": launch_request_operation,
        "launch_request_handoff_pid": int(wait_pid)} if launch_request_id else {})
    try:
        _append_refresh_log(root, "refresh.started", wait_pid=int(wait_pid), then_lifecycle=str(then_lifecycle or ""))
        if int(wait_pid) > 0:
            _wait_for_pid_exit(
                int(wait_pid),
                timeout_seconds=wait_timeout_seconds,
                expected_create_time=_expected_create_time_for_pid(root, int(wait_pid)),
            )
        holder = _verified_live_desktop_shell_owner(root)
        if holder is not None:
            return _refresh_blocked_by_live_owner(root, holder, wait_pid=int(wait_pid))
        kind = str(shell_kind or "").strip().lower()
        try:
            if kind == "unpackaged":
                rebuilt = ensure_unpackaged_electron(root)
                launched = launch_desktop_shell(
                    project_root=root,
                    then_lifecycle=then_lifecycle,
                    open_workbench=True,
                    prefer="unpackaged",
                    expect_primary=True,
                    **request_options,
                )
                return _finish_refresh_launch(root, launched, wait_pid=int(wait_pid), kind="unpackaged", rebuilt=rebuilt)
            current = inspect_desktop_shell(root) if kind == "packaged" else None
            if current is not None and not current["stale"]:
                # Preparation can legitimately find an already-current package
                # (for example on retry). Do not compile again after exit.
                rebuilt = {"rebuilt": False, "reason": current["reason"]}
            else:
                rebuilt = rebuild_desktop_shell(project_root=root)
        except Exception as exc:
            detail = str(exc)
            record_desktop_shell_refresh_failure(root, reason="rebuild_failed", detail=detail)
            _append_refresh_log(root, "refresh.aborted", wait_pid=int(wait_pid), detail=detail[-800:])
            # The old shell has already exited, so a failed rebuild must not
            # leave the workspace without one: relaunch whatever packaged exe
            # still exists (even a stale package). Only a missing exe aborts.
            # The launch still demands a primary: a shell that came up during
            # the build must not receive a bow-out instance.
            fallback: dict[str, Any] | None = None
            fallback_error = ""
            if packaged_desktop_exe(root).is_file():
                try:
                    fallback = launch_packaged_desktop_shell(
                        project_root=root,
                        then_lifecycle=then_lifecycle,
                        open_workbench=True,
                        expect_primary=True,
                        **request_options,
                    )
                except Exception as launch_exc:
                    fallback_error = str(launch_exc)
            if fallback is not None:
                _append_refresh_log(
                    root,
                    "refresh.fallback_launch",
                    wait_pid=int(wait_pid),
                    detail=detail[-800:],
                    **_launch_log_fields(fallback),
                )
                return {
                    "schemaVersion": 1,
                    "refreshed": False,
                    "reason": "rebuild_failed",
                    "message": detail[-800:],
                    "fallbackLaunch": fallback,
                    **_launch_pid_fields(fallback),
                }
            _append_refresh_log(
                root,
                "refresh.aborted_no_shell",
                wait_pid=int(wait_pid),
                detail=detail[-800:],
                fallback_detail=fallback_error[-800:],
            )
            return {
                "schemaVersion": 1,
                "refreshed": False,
                "reason": "rebuild_failed",
                "message": detail[-800:],
            }
        try:
            launched = launch_packaged_desktop_shell(
                project_root=root,
                then_lifecycle=then_lifecycle,
                open_workbench=True,
                expect_primary=True,
                **request_options,
            )
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
        return _finish_refresh_launch(root, launched, wait_pid=int(wait_pid), kind="", rebuilt=rebuilt)
    finally:
        _release_desktop_shell_refresh_lock(root)


def _launch_pid_fields(launched: dict[str, Any]) -> dict[str, Any]:
    """Explicit pid semantics for refresh results: the spawn vs. the lock owner."""

    return {
        "launchPid": int(launched.get("launchPid") or launched.get("pid") or 0),
        "ownerPid": int(launched.get("ownerPid") or 0),
    }


def _launch_log_fields(launched: dict[str, Any]) -> dict[str, Any]:
    pids = _launch_pid_fields(launched)
    confirmation = launched.get("confirmation")
    state = str(confirmation.get("state") or "") if isinstance(confirmation, dict) else ""
    fields: dict[str, Any] = {
        "helper_launch_pid": pids["launchPid"],
        "owner_pid": pids["ownerPid"],
        "launch_confirmed": _launch_result_replaces_shell(launched),
    }
    if state:
        fields["confirmation_state"] = state
    if launched.get("errorCode"):
        fields["error_code"] = str(launched["errorCode"])
    return fields


def _launch_result_replaces_shell(launched: dict[str, Any]) -> bool:
    """True when a launch result stands for a new primary shell.

    ``launched`` false (bow-out, crash, refused) is not a replacement; neither
    is a child that is alive while a different process verifiably holds the
    owner lock. Results without the confirmation fields (legacy callers) keep
    their historical "spawned means launched" reading.
    """

    if "launched" in launched and not launched["launched"]:
        return False
    pids = _launch_pid_fields(launched)
    if pids["ownerPid"] and pids["launchPid"] and pids["ownerPid"] != pids["launchPid"]:
        return False
    return True


def _finish_refresh_launch(
    root: Path,
    launched: dict[str, Any],
    *,
    wait_pid: int,
    kind: str,
    rebuilt: dict[str, Any],
) -> dict[str, Any]:
    pids = _launch_pid_fields(launched)
    kind_fields = {"kind": kind} if kind else {}
    if not _launch_result_replaces_shell(launched):
        code = str(launched.get("errorCode") or "launch_not_confirmed")
        confirmation = launched.get("confirmation")
        state = str(confirmation.get("state") or "") if isinstance(confirmation, dict) else ""
        detail = f"{code}: launchPid={pids['launchPid']} ownerPid={pids['ownerPid']} state={state or 'unknown'}"
        # A cooldown marker here is what breaks the idle restart loop: the
        # shell was not replaced, so the next automatic refresh must not
        # immediately spawn another bow-out.
        record_desktop_shell_refresh_failure(root, reason="launch_not_confirmed", detail=detail)
        _append_refresh_log(root, "refresh.launch_not_confirmed", wait_pid=wait_pid, **_launch_log_fields(launched))
        return {
            "schemaVersion": 1,
            "refreshed": False,
            "reason": "launch_not_confirmed",
            "errorCode": code,
            "message": detail,
            **kind_fields,
            "rebuild": rebuilt,
            "launch": launched,
            **pids,
        }
    clear_desktop_shell_refresh_failure(root)
    _append_refresh_log(root, "refresh.finished", wait_pid=wait_pid, **_launch_log_fields(launched))
    return {
        "schemaVersion": 1,
        "refreshed": True,
        **kind_fields,
        "rebuild": rebuilt,
        "launch": launched,
        **pids,
    }


def _refresh_blocked_by_live_owner(root: Path, holder: dict[str, Any], *, wait_pid: int) -> dict[str, Any]:
    """The pre-launch lock gate: a verifiably live owner means nothing to replace.

    Records the cooldown marker so a scheduler that still believes the shell is
    stale cannot spin helpers against a shell that never exited.
    """

    owner_pid = int(holder.get("pid") or 0)
    detail = (
        f"owner pid={owner_pid} identity={holder.get('identityStatus', '')} "
        f"executable={holder.get('executable', '')}"
    )
    record_desktop_shell_refresh_failure(root, reason="live_owner_holding_lock", detail=detail)
    _append_refresh_log(
        root,
        "refresh.blocked_live_owner",
        wait_pid=wait_pid,
        owner_pid=owner_pid,
        identity_status=str(holder.get("identityStatus") or ""),
        detail=detail,
    )
    return {
        "schemaVersion": 1,
        "refreshed": False,
        "reason": "live_owner_holding_lock",
        "errorCode": LAUNCH_ERROR_LIVE_OWNER_HOLDING_LOCK,
        "message": detail,
        "owner": holder,
        "launchPid": 0,
        "ownerPid": owner_pid,
    }


def schedule_desktop_shell_prebuild(
    project_root: Path | str = PROJECT_ROOT,
    *,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Start a detached helper that stages the next packaged shell build.

    The staged build lands in ``dist/desktop-staging`` and never touches the
    live ``win-unpacked``; the next ``rebuild_desktop_shell`` promotes it via
    rename instead of running the minute-long npm build.
    """

    root = Path(project_root)
    if not _retry_pending_scheduled_helper_retirements(root):
        return {"schemaVersion": 1, "scheduled": False, "helperPid": 0, "reason": "helper_retirement_pending"}
    if (
        _recent_shell_failure_marker(_prebuild_failure_path(root), cooldown_seconds=PREBUILD_COOLDOWN_SECONDS)
        is not None
    ):
        return {"schemaVersion": 1, "scheduled": False, "helperPid": 0, "reason": "prebuild_cooldown"}
    if _refresh_lock_path(root).is_file():
        # A scheduled-or-running refresh rebuilds the final package anyway, so
        # a staging build started now would race the very rebuild it exists
        # to speed up.
        return {"schemaVersion": 1, "scheduled": False, "helperPid": 0, "reason": "refresh_in_progress"}
    if not _acquire_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE):
        return {"schemaVersion": 1, "scheduled": False, "helperPid": 0, "reason": "prebuild_in_progress"}
    helper_python = _pythonw(python_executable or sys.executable)
    entry = root / "scripts" / "vibelution_desktop_entry.py"
    args = [
        helper_python,
        str(entry),
        "--action",
        "prebuild-desktop-shell",
        "--output",
        "json",
        "--workspace",
        str(root),
    ]
    helper_pid = _start_scheduled_desktop_shell_helper(
        args,
        project_root=root,
        lock_relative=PREBUILD_LOCK_RELATIVE,
        label="prebuild",
    )
    return {"schemaVersion": 1, "scheduled": True, "helperPid": helper_pid}


def run_desktop_shell_prebuild(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Stage the current checkout's packaged shell into ``dist/desktop-staging``."""

    root = Path(project_root)
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    try:
        if _refresh_lock_path(root).is_file():
            # Refresh owns the final package; a staging build would only race it.
            return {"schemaVersion": 1, "ok": True, "skipped": "refresh_in_progress"}
        _ensure_desktop_shell_build_lock(root, deadline=deadline)
        status = inspect_desktop_shell(root)
        if not status["stale"]:
            return {"schemaVersion": 1, "ok": True, "skipped": "current"}
        try:
            staged_status = _inspect_desktop_shell_package(root, root / STAGING_WIN_UNPACKED_RELATIVE, for_reuse=True)
        except Exception:
            # Missing or unreadable proof cannot justify reusing the old tree.
            staged_status = {"stale": True, "reason": "inspection_failed"}
        if not staged_status["stale"]:
            staged_tree = str(staged_status["packagedElectronTree"])
            _clear_shell_failure_marker(_prebuild_failure_path(root))
            _append_refresh_log(root, "prebuild.reused", electronTreeHash=staged_tree)
            return {"schemaVersion": 1, "ok": True, "staged": True, "electronTreeHash": staged_tree}
        _append_refresh_log(
            root, "prebuild.reuse_rejected", reason=str(staged_status.get("reason") or "inspection_failed")[:120],
        )
        try:
            staged = _stage_desktop_shell(root, deadline=deadline)
        except Exception as exc:
            detail = str(exc)
            _record_shell_failure_marker(
                _prebuild_failure_path(root),
                reason="prebuild_failed",
                detail=detail,
            )
            _append_refresh_log(root, "prebuild.aborted", detail=detail[-800:])
            return {
                "schemaVersion": 1,
                "ok": False,
                "reason": "prebuild_failed",
                "message": detail[-800:],
            }
        _clear_shell_failure_marker(_prebuild_failure_path(root))
        _append_refresh_log(root, "prebuild.finished", electronTreeHash=str(staged.get("electronTreeHash") or ""))
        return {"schemaVersion": 1, "ok": True, "staged": True, **staged}
    finally:
        if not _pending_build_retirement_for(root):
            _release_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE)


def _npm_failure_detail(result: subprocess.CompletedProcess) -> str:
    """Combine both captured npm output streams for a failure detail line.

    npm script chains interleave stdout and stderr (esbuild prints its summary
    to stderr while the actually failing step usually reports on stdout), so a
    single-stream tail can hide the real error behind benign output.
    """

    stderr_tail = str(result.stderr or "").strip().replace("\r", "")[-400:]
    stdout_tail = str(result.stdout or "").strip().replace("\r", "")[-400:]
    return "\n--\n".join(part for part in (stderr_tail, stdout_tail) if part)


def _read_log_tail(handle: Any, *, limit: int = 1200) -> str:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - limit * 4), os.SEEK_SET)
    raw = handle.read()
    return raw.decode("utf-8", errors="replace")[-limit:].strip().replace("\r", "")


def _close_owned_process(owner: OwnedProcess, *, deadline: float) -> None:
    last_error: BaseException | None = None
    for attempt in range(DESKTOP_SHELL_BUILD_CLOSE_RETRIES):
        try:
            owner.close(timeout=max(0.0, deadline - time.monotonic()))
            return
        except BaseException as exc:
            last_error = exc
            if attempt + 1 < DESKTOP_SHELL_BUILD_CLOSE_RETRIES:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.05, remaining))
    raise BuildProcessRetirementError(
        "desktop build process retirement could not be confirmed; keeping its lock and stage for recovery",
        owner,
    ) from last_error


def _run_owned_process(
    command: list[str],
    *,
    cwd: Path,
    deadline: float,
    label: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a bounded, console-free process tree with disk-backed output tails."""

    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= DESKTOP_SHELL_BUILD_CLEANUP_RESERVE_SECONDS:
        raise TimeoutError(f"{label} could not start within the desktop build deadline")
    owner: OwnedProcess | None = None
    with tempfile.TemporaryFile(mode="w+b") as stdout_log, tempfile.TemporaryFile(mode="w+b") as stderr_log:
        try:
            owner = OwnedProcess.spawn(
                command,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_log,
                stderr=stderr_log,
                close_fds=True,
                **no_window_subprocess_kwargs(),
            )
            wait_timeout = max(
                0.0,
                deadline - time.monotonic() - DESKTOP_SHELL_BUILD_CLEANUP_RESERVE_SECONDS,
            )
            try:
                owner.process.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired as exc:
                remaining = max(0.0, deadline - time.monotonic())
                if not owner.terminate(timeout=remaining):
                    raise RuntimeError(f"{label} timed out and its process tree could not be retired") from exc
                owner.process.wait(timeout=max(0.0, deadline - time.monotonic()))
                detail = _npm_failure_detail(
                    subprocess.CompletedProcess(
                        command,
                        returncode=int(owner.process.returncode or 0),
                        stdout=_read_log_tail(stdout_log),
                        stderr=_read_log_tail(stderr_log),
                    )
                )
                raise TimeoutError(f"{label} exceeded the desktop build deadline: {detail}") from exc

            result = subprocess.CompletedProcess(
                command,
                returncode=int(owner.process.returncode or 0),
                stdout=_read_log_tail(stdout_log),
                stderr=_read_log_tail(stderr_log),
            )
            if result.returncode != 0:
                detail = _npm_failure_detail(result)
                raise RuntimeError(f"{label} failed with exit code {result.returncode}: {detail}")
            return result
        finally:
            if owner is not None:
                _close_owned_process(owner, deadline=deadline)


def _wait_for_desktop_shell_build_lock(root: Path, *, deadline: float) -> None:
    _retry_pending_build_retirements(root, deadline=deadline)
    while True:
        if _acquire_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("desktop shell build lock was not available before the build deadline")
        time.sleep(min(DESKTOP_SHELL_BUILD_LOCK_POLL_SECONDS, remaining))


def _project_venv_python(root: Path) -> Path:
    """Return the project-local venv interpreter, matching boot_pipeline.project_venv_python.

    boot_pipeline is deliberately not imported here: it drags in the supervised
    evaluation stack, and desktop shell helpers must stay cheap to import.
    """

    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _assistant_payload_builder_python(root: Path) -> str:
    """Interpreter for the payload packaging subprocess: project .venv first.

    build_assistant_runtime's RECORD safety check only accepts venv-layout
    site-packages, so a helper running on a bare system Python must still
    package through the project venv interpreter when one exists; without a
    venv the running interpreter keeps today's behavior.
    """

    candidate = _project_venv_python(root)
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def _build_assistant_payload(root: Path, payload: Path, *, deadline: float, env: dict[str, str]) -> str:
    builder_python = _assistant_payload_builder_python(root)
    command = [builder_python, "-B", "-c",
               ("import sys; from scripts.build_assistant_runtime import build_launcher_assistant_payload; "
                "build_launcher_assistant_payload(sys.argv[1], sys.argv[2])"), str(root), str(payload)]
    _run_owned_process(command, cwd=root, deadline=deadline, label="desktop assistant payload", env=env)
    assistant_payload = _assistant_payload_builder()
    path = assistant_payload._checked(assistant_payload._trusted_root(payload), "manifest.json")
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise RuntimeError("desktop assistant builder did not produce a complete manifest")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_desktop_shell_package_build(root: Path, *, mode: str, deadline: float) -> Path:
    if mode == "linux-arm64" or sys.platform != "win32":
        raise ValueError("Launcher assistant packages currently require a native Windows build")
    session = root / "dist" / f".desktop-shell-build-{uuid4().hex}"
    electron_dir = root / ELECTRON_PACKAGE_DIR
    node_command = _node_command()
    command = [node_command, str(electron_dir / "scripts" / "buildDesktopPackage.js"), "--mode", mode]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_BUILD_ROOT"] = str(session)
    env["VIBELUTION_DESKTOP_BUILD_MANAGED"] = "1"
    try:
        payload = session / "launcher-assistant"
        env["VIBELUTION_ASSISTANT_PAYLOAD_ROOT"] = str(payload)
        env["VIBELUTION_ASSISTANT_MANIFEST_SHA256"] = _build_assistant_payload(root, payload, deadline=deadline, env=env)
        _run_owned_process(
            command,
            cwd=electron_dir,
            deadline=deadline,
            label=f"desktop shell package:{mode}",
            env=env,
        )
        return session
    except BuildProcessRetirementError as exc:
        _register_pending_build_retirement(
            root,
            exc.owner,
            cleanup_paths=(session,),
            lock_relative=PREBUILD_LOCK_RELATIVE,
        )
        raise
    except Exception:
        _remove_owned_shell_tree(session, within=root / "dist")
        raise


def build_desktop_shell_package(
    project_root: Path | str = PROJECT_ROOT,
    *,
    mode: str = "dir",
) -> dict[str, Any]:
    """Build and publish a package through the shared project build owner."""

    if mode not in {"dir", "staging", "linux-arm64"}:
        raise ValueError(f"unsupported desktop package mode: {mode}")
    if mode == "linux-arm64" or sys.platform != "win32":
        raise ValueError("Launcher assistant packages currently require a native Windows build")
    root = Path(project_root).resolve()
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _wait_for_desktop_shell_build_lock(root, deadline=deadline)
    session: Path | None = None
    try:
        session = _run_desktop_shell_package_build(root, mode=mode, deadline=deadline)
        output = session / "builder-output"
        if mode == "linux-arm64":
            published_output = root / "dist" / "desktop-linux-arm64"
            _publish_built_shell_tree(
                output,
                published_output,
                previous=root / "dist" / ".desktop-linux-arm64-previous",
            )
        else:
            built = output / "win-unpacked"
            built_provenance = built / "resources" / "app.asar.unpacked" / "package-provenance.json"
            packaged_tree = str(_read_json(built_provenance).get("electronTreeHash") or "").strip()
            current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
            if not packaged_tree or not current_tree or packaged_tree != current_tree:
                raise RuntimeError(
                    "desktop package provenance does not match HEAD:desktop/electron "
                    f"(packaged={packaged_tree!r} current={current_tree!r})"
                )
            _assert_assistant_package(root, built, deadline=deadline)
            published_output = (
                root / STAGING_WIN_UNPACKED_RELATIVE
                if mode == "staging"
                else root / PACKAGED_EXE_RELATIVE.parent
            )
            previous = root / STAGING_OUTPUT_DIR_RELATIVE / ".win-unpacked-previous" if mode == "staging" else root / PREVIOUS_WIN_UNPACKED_RELATIVE
            _publish_built_shell_tree(built, published_output, previous=previous)
        return {"built": True, "mode": mode, "output": str(published_output)}
    finally:
        if session is not None and not _pending_build_retirement_for(root, cleanup_path=session):
            _remove_owned_shell_tree(session, within=root / "dist")
        if not _pending_build_retirement_for(root):
            _release_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE)


def _stage_desktop_shell(root: Path, *, deadline: float | None = None) -> dict[str, Any]:
    """Build to a unique app/output tree, then publish verified staging bytes."""

    deadline = deadline or (time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS)
    session = _run_desktop_shell_package_build(root, mode="staging", deadline=deadline)
    built = session / "builder-output" / "win-unpacked"
    built_provenance = built / "resources" / "app.asar.unpacked" / "package-provenance.json"
    try:
        staged_tree = str(_read_json(built_provenance).get("electronTreeHash") or "").strip()
        current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
        if not staged_tree or not current_tree or staged_tree != current_tree:
            raise RuntimeError(
                "staged desktop shell provenance does not match HEAD:desktop/electron "
                f"(staged={staged_tree!r} current={current_tree!r})"
            )
        _assert_assistant_package(root, built, deadline=deadline)
        _publish_built_shell_tree(
            built,
            root / STAGING_WIN_UNPACKED_RELATIVE,
            previous=root / STAGING_OUTPUT_DIR_RELATIVE / ".win-unpacked-previous",
        )
        return {"electronTreeHash": staged_tree}
    finally:
        if not _pending_build_retirement_for(root, cleanup_path=session):
            _remove_owned_shell_tree(session, within=root / "dist")


def _try_promote_staged_desktop_shell(root: Path) -> bool:
    """Swap a valid staged build into the live ``win-unpacked`` via rename.

    Serialized on the prebuild lock: a running prebuild helper is mid-write on
    the staging tree (electron-builder's copy order is unspecified, so a
    half-written package can already expose exe and provenance), and renaming
    it in would ship a broken shell. Lock contention therefore yields to the
    helper and the caller falls back to the real rebuild. Only the Electron
    tree hash and verified assistant payload gate the swap; the caller still runs the full
    ``inspect_desktop_shell`` afterwards and falls back to the real npm rebuild
    when the promoted package does not pass. Any rename failure restores the
    previous layout and returns False so the slow path stays safe.
    """

    if not _acquire_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE):
        return False
    try:
        return _try_promote_staged_desktop_shell_locked(root)
    finally:
        _release_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE)


def _try_promote_staged_desktop_shell_locked(root: Path, *, deadline: float | None = None) -> bool:
    staging_unpacked = root / STAGING_WIN_UNPACKED_RELATIVE
    if not (staging_unpacked / "Vibelution.exe").is_file():
        return False
    staged_tree = str(_read_json(staging_unpacked / "resources" / "app.asar.unpacked" / "package-provenance.json").get("electronTreeHash") or "").strip()
    if not staged_tree:
        return False
    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    if not current_tree or staged_tree != current_tree:
        # Leave the staging in place; the next successful prebuild replaces it.
        return False
    try:
        _assert_assistant_package(root, staging_unpacked,
                                  deadline=deadline or time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS)
    except (OSError, ValueError, RuntimeError):
        return False
    live = root / "dist" / "desktop" / "win-unpacked"
    previous = root / PREVIOUS_WIN_UNPACKED_RELATIVE
    try:
        _publish_built_shell_tree(staging_unpacked, live, previous=previous)
    except OSError:
        # A sharing violation here means something still holds the live tree
        # open; leave staging and the old package untouched for a later retry.
        return False
    _remove_owned_shell_tree(root / STAGING_OUTPUT_DIR_RELATIVE, within=root / "dist")
    return True


def _remove_owned_shell_tree(path: Path, *, within: Path) -> None:
    """Retire only the named owner tree, including Windows paths over 260 chars."""
    assistant_payload = _assistant_payload_builder()
    boundary = assistant_payload._trusted_root(within)
    target = assistant_payload._trusted_root(path)
    if target == boundary or not target.is_relative_to(boundary):
        raise ValueError("desktop shell cleanup target is outside its owner boundary")
    shutil.rmtree(target, ignore_errors=True)


def _publish_built_shell_tree(source: Path, destination: Path, *, previous: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous.parent.mkdir(parents=True, exist_ok=True)
    moved_previous = False
    try:
        if previous.exists():
            _remove_owned_shell_tree(previous, within=destination.parent)
        if destination.exists():
            _rename_dir(destination, previous)
            moved_previous = True
        _rename_dir(source, destination)
    except OSError:
        if moved_previous and not destination.exists():
            try:
                _rename_dir(previous, destination)
            except OSError:
                pass
        raise
    if moved_previous:
        _remove_owned_shell_tree(previous, within=destination.parent)


def rebuild_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Rebuild ``win-unpacked`` from the current ``desktop/electron`` checkout."""

    root = Path(project_root)
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _wait_for_desktop_shell_build_lock(root, deadline=deadline)
    try:
        if _try_promote_staged_desktop_shell_locked(root, deadline=deadline):
            status = inspect_desktop_shell(root)
            if not status["stale"]:
                _append_refresh_log(root, "rebuild.promoted_from_staging", reason=status["reason"])
                return {
                    "rebuilt": True,
                    "promotedFromStaging": True,
                    "reason": status["reason"],
                    "currentElectronTree": status["currentElectronTree"],
                }
            # The staged tree hash matched but the full freshness inspection does
            # not. Keep the old package until the independent build is complete.
            _append_refresh_log(root, "rebuild.promote_rejected", reason=status["reason"])

        session = _run_desktop_shell_package_build(root, mode="dir", deadline=deadline)
        try:
            built = session / "builder-output" / "win-unpacked"
            _assert_assistant_package(root, built, deadline=deadline)
            _publish_built_shell_tree(
                built,
                root / PACKAGED_EXE_RELATIVE.parent,
                previous=root / PREVIOUS_WIN_UNPACKED_RELATIVE,
            )
        finally:
            if not _pending_build_retirement_for(root, cleanup_path=session):
                _remove_owned_shell_tree(session, within=root / "dist")

        status = inspect_desktop_shell(root)
        if status["stale"]:
            raise RuntimeError(f"desktop shell is still stale after rebuild: {status['reason']}")
        return {
            "rebuilt": True,
            "reason": status["reason"],
            "currentElectronTree": status["currentElectronTree"],
        }
    except Exception as exc:
        detail = str(exc)
        _append_refresh_log(root, "rebuild.failed", detail=detail)
        raise
    finally:
        if not _pending_build_retirement_for(root):
            _release_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE)


def inspect_unpackaged_electron(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return whether checkout Electron main matches current desktop/electron."""

    root = Path(project_root)
    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    provenance = _read_json(unpackaged_provenance_path(root))
    bundled_tree = str(provenance.get("electronTreeHash") or "").strip()
    electron_bin = unpackaged_electron_executable(root)
    main_js = unpackaged_main_js(root)
    source_newer = _electron_sources_newer_than(root, main_js)
    if electron_bin is None:
        reason = "missing_binary"
        stale = True
    elif not main_js.is_file():
        reason = "missing_bundle"
        stale = True
    elif not bundled_tree:
        reason = "missing_provenance"
        stale = True
    elif current_tree and bundled_tree != current_tree:
        reason = "provenance_mismatch"
        stale = True
    elif source_newer:
        reason = "source_newer_than_bundle"
        stale = True
    else:
        reason = "current"
        stale = False
    return {
        "schemaVersion": 1,
        "stale": stale,
        "reason": reason,
        "bundledElectronTree": bundled_tree,
        "currentElectronTree": current_tree,
        "electronExecutable": str(electron_bin or ""),
        "mainJs": str(main_js),
        "sourceNewerThanBundle": source_newer,
    }


def ensure_unpackaged_electron(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Compile checkout Electron main when it is behind HEAD:desktop/electron."""

    root = Path(project_root)
    status = inspect_unpackaged_electron(root)
    if not status["stale"]:
        return {"ensured": True, "rebuilt": False, **status}
    if status["reason"] == "missing_binary":
        raise RuntimeError(
            "Unpackaged Electron binary was not found at "
            "desktop/electron/node_modules/electron/dist/electron.exe. "
            "Install desktop/electron dependencies, then retry."
        )
    if not _promote_prepared_unpackaged_electron(root):
        _rebuild_unpackaged_electron(root)
    status = inspect_unpackaged_electron(root)
    if status["stale"]:
        raise RuntimeError(f"checkout Electron main is still stale after build: {status['reason']}")
    return {"ensured": True, "rebuilt": True, **status}


def _unpackaged_electron_dist_is_complete(stage: Path) -> bool:
    required = [stage / "main.js", stage / "preload.cjs"]
    if os.name == "nt":
        required.append(stage / "native" / "workbench_job.node")
    return all(path.is_file() for path in required)


def _prepared_unpackaged_electron_is_current(root: Path) -> bool:
    stage = root / UNPACKAGED_STAGING_RELATIVE
    tree = _git_tree_hash(root, "HEAD:desktop/electron")
    provenance = _read_json(stage / "unpackaged-provenance.json")
    return bool(
        tree and provenance.get("electronTreeHash") == tree
        and _unpackaged_electron_dist_is_complete(stage)
        and not _electron_sources_newer_than(root, stage / "main.js")
    )


def _promote_prepared_unpackaged_electron(root: Path) -> bool:
    if not (root / UNPACKAGED_STAGING_RELATIVE).is_dir():
        return False
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _ensure_desktop_shell_build_lock(root, deadline=deadline)
    try:
        if not _prepared_unpackaged_electron_is_current(root):
            return False
        stage = root / UNPACKAGED_STAGING_RELATIVE
        tree = str(_read_json(stage / "unpackaged-provenance.json")["electronTreeHash"])
        _publish_staged_electron_dist(stage, root / ELECTRON_PACKAGE_DIR / "dist")
        shutil.rmtree(stage, ignore_errors=True)
        _append_refresh_log(root, "unpackaged.promoted_from_staging", electronTreeHash=tree)
        return True
    finally:
        _release_desktop_shell_refresh_lock(root, lock_relative=PREBUILD_LOCK_RELATIVE)


def prepare_unpackaged_electron(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Prepare a complete replacement without touching the live Electron dist."""

    root = Path(project_root)
    status = inspect_unpackaged_electron(root)
    if not status["stale"]:
        return {"rebuilt": False, **status}
    if status["reason"] == "missing_binary":
        raise RuntimeError("Unpackaged Electron binary is missing; install desktop/electron dependencies.")
    if _prepared_unpackaged_electron_is_current(root):
        return {"rebuilt": False, "prepared": True, "reason": "prepared"}
    return _rebuild_unpackaged_electron(root, prepare_only=True)


def ensure_latest_launcher(
    project_root: Path | str = PROJECT_ROOT, *, shell_kind: str = "unpackaged"
) -> dict[str, Any]:
    """Prepare Electron and the frontend while the old shell remains usable.

    The refresh helper publishes the prepared Electron tree after wait_pid exits.
    """

    root = Path(project_root)
    if shell_kind not in {"packaged", "unpackaged"}:
        raise ValueError("Unsupported desktop shell kind.")
    electron = prepare_unpackaged_electron(root) if shell_kind == "unpackaged" else {}
    from core.runtime_manager.daemon import _preflight_frontend_build_for_restart

    frontend = _preflight_frontend_build_for_restart("ensure-latest-launcher", project_root=root)
    if not bool(frontend.get("ok", True)):
        raise RuntimeError(str(frontend.get("reason") or "frontend ensure failed"))
    if shell_kind == "packaged":
        staged = run_desktop_shell_prebuild(root)
        if staged.get("ok") is not True or not (
            staged.get("staged") is True or staged.get("skipped") == "current"
        ):
            raise RuntimeError(str(staged.get("message") or "Launcher 更新准备未完成，当前窗口保持打开。"))
        electron = {
            "rebuilt": False,
            "prepared": staged.get("staged") is True,
            "reason": "prepared" if staged.get("staged") else str(staged.get("skipped") or "current"),
        }
    return {
        "schemaVersion": 1,
        "ok": True,
        "electron": {
            "rebuilt": bool(electron.get("rebuilt")),
            "prepared": bool(electron.get("prepared")),
            "reason": str(electron.get("reason") or ""),
        },
        "frontend": {
            "skipped": bool(frontend.get("skipped")),
            "ok": True,
            "reason": str(frontend.get("reason") or ""),
        },
    }


def resolve_desktop_shell_launch_roots(project_root: Path | str) -> tuple[Path, Path | None]:
    """Map a requested --project path onto the integration shell and optional slot.

    Task worktrees do not own packaged/unpackaged Electron. The desktop shell
    always launches from the Git integration root; the worktree is forwarded as
    ``--project`` so an existing shell can apply the isolated slot.
    """

    requested = Path(project_root)
    from core.infrastructure.branch_workspace import (
        BranchWorkspaceError,
        resolve_branch_workspace,
    )

    try:
        layout = resolve_branch_workspace(requested)
    except (OSError, BranchWorkspaceError):
        return requested, None
    shell_root = Path(layout.integration_root)
    slot_root = Path(layout.worktree_root)
    try:
        if slot_root.resolve() != shell_root.resolve():
            return shell_root, slot_root
    except OSError:
        if str(slot_root) != str(shell_root):
            return shell_root, slot_root
    return shell_root, None


def _desktop_shell_electron_args(
    executable: str,
    prefix: list[str],
    *,
    shell_root: Path,
    slot_root: Path | None,
    open_workbench: bool,
    lifecycle: str,
    hidden_presentation: bool = False,
) -> list[str]:
    args = [executable, *prefix, "--workspace", str(shell_root), "--local-debugging"]
    # A bare Launcher/shortcut request opens the resident assistant only. A
    # slot without an explicit action otherwise makes Electron start or focus
    # that project's workbench, even though open_workbench is false.
    if slot_root is not None and (open_workbench or lifecycle):
        args.extend(["--project", str(slot_root)])
    if open_workbench:
        args.append("--open-workbench")
    if lifecycle:
        args.append(lifecycle)
    if hidden_presentation:
        # Branch instance workbench windows load without show/focus (e2e
        # lanes); the argv switch is the transport into the already-running
        # shared shell, where env vars of this spawn would never reach it.
        args.append("--hidden-presentation")
    return args


def resolve_desktop_shell_launch(
    project_root: Path | str = PROJECT_ROOT,
    *,
    then_lifecycle: str = "",
    open_workbench: bool = False,
    hidden_presentation: bool = False,
    prefer: str = "",
) -> dict[str, Any]:
    """Choose the current checkout's Electron main: packaged if current, else unpackaged."""

    shell_root, slot_root = resolve_desktop_shell_launch_roots(project_root)
    lifecycle = str(then_lifecycle or "").strip().lower()
    if str(prefer or "").strip().lower() == "unpackaged":
        unpackaged = ensure_unpackaged_electron(shell_root)
        electron_bin = unpackaged_electron_executable(shell_root)
        main_js = unpackaged_main_js(shell_root)
        if electron_bin is None or not main_js.is_file():
            raise RuntimeError("checkout Electron main is not launchable after ensure")
        args = _desktop_shell_electron_args(
            str(electron_bin),
            [str(main_js)],
            shell_root=shell_root,
            slot_root=slot_root,
            open_workbench=open_workbench,
            lifecycle=lifecycle,
            hidden_presentation=hidden_presentation,
        )
        return {
            "schemaVersion": 1,
            "kind": "unpackaged",
            "args": args,
            "cwd": str(shell_root),
            "reason": str(unpackaged.get("reason") or "current"),
            "currentElectronTree": str(unpackaged.get("currentElectronTree") or ""),
            "rebuilt": bool(unpackaged.get("rebuilt")),
        }
    # A live main owns freshness and guarded relaunch. Every supported lifecycle
    # command must reach it before a build; even stop/status can otherwise block
    # on stale artifacts. Rebuilding here also consumes its `rebuilt` signal.
    if (not lifecycle and not open_workbench) or lifecycle in {
        "start", "stop", "force-stop", "restart", "rebuild-and-start",
        "toggle", "status", "open", "close-window",
    }:
        from core.launcher.desktop_shell_owner import _identity_status, read_desktop_shell_owner

        owner = read_desktop_shell_owner(shell_root)
        electron_bin = unpackaged_electron_executable(shell_root)
        main_js = unpackaged_main_js(shell_root)
        if (owner and owner.get("owner") == "electron" and electron_bin and main_js.is_file()
                and Path(str(owner.get("executable", ""))).resolve() == electron_bin.resolve()
                and _identity_status(owner) == "match"):
            return {
                "schemaVersion": 1, "kind": "unpackaged", "reason": "forward_to_live_shell",
                "cwd": str(shell_root), "rebuilt": False,
                "args": _desktop_shell_electron_args(str(electron_bin), [str(main_js)],
                    shell_root=shell_root, slot_root=slot_root, open_workbench=open_workbench,
                    lifecycle=lifecycle, hidden_presentation=hidden_presentation),
            }
    packaged_status = inspect_desktop_shell_launch_readiness(shell_root)
    # Admission only needs the launch blocker. The active workspace release
    # serves the launcher, while full freshness remains a separate observation.
    if not packaged_status.get("launchBlocking"):
        args = _desktop_shell_electron_args(
            str(packaged_desktop_exe(shell_root)),
            [],
            shell_root=shell_root,
            slot_root=slot_root,
            open_workbench=open_workbench,
            lifecycle=lifecycle,
            hidden_presentation=hidden_presentation,
        )
        return {
            "schemaVersion": 1,
            "kind": "packaged",
            "args": args,
            "cwd": str(shell_root),
            "reason": str(packaged_status.get("reason") or "current"),
            "currentElectronTree": str(packaged_status.get("currentElectronTree") or ""),
        }
    unpackaged = ensure_unpackaged_electron(shell_root)
    electron_bin = unpackaged_electron_executable(shell_root)
    main_js = unpackaged_main_js(shell_root)
    if electron_bin is None or not main_js.is_file():
        raise RuntimeError("checkout Electron main is not launchable after ensure")
    args = _desktop_shell_electron_args(
        str(electron_bin),
        [str(main_js)],
        shell_root=shell_root,
        slot_root=slot_root,
        open_workbench=open_workbench,
        lifecycle=lifecycle,
        hidden_presentation=hidden_presentation,
    )
    return {
        "schemaVersion": 1,
        "kind": "unpackaged",
        "args": args,
        "cwd": str(shell_root),
        "reason": str(unpackaged.get("reason") or "current"),
        "currentElectronTree": str(unpackaged.get("currentElectronTree") or ""),
        "rebuilt": bool(unpackaged.get("rebuilt")),
    }


def _desktop_launch_request_args(request_id: str, operation: str = "", handoff_pid: int = 0) -> list[str]:
    if not request_id:
        return []
    if not re.fullmatch(r"launch_[a-f0-9]{32}", request_id):
        raise ValueError("invalid desktop launch request id")
    args = ["--launch-request-id", request_id]
    if operation:
        if operation not in {"start", "restart", "rebuild-and-start", "stop", "force-stop"}:
            raise ValueError("invalid desktop launch request operation")
        args.extend(["--launch-request-operation", operation])
    if handoff_pid > 0:
        args.extend(["--launch-request-handoff-pid", str(int(handoff_pid))])
    return args


def launch_desktop_shell(
    *,
    project_root: Path | str = PROJECT_ROOT,
    then_lifecycle: str = "",
    open_workbench: bool = False,
    hidden_presentation: bool = False,
    prefer: str = "",
    launch_request_id: str = "",
    launch_request_operation: str = "",
    launch_request_handoff_pid: int = 0,
    expect_primary: bool = False,
) -> dict[str, Any]:
    """Start Electron main for the current checkout without hiding the GUI.

    The result reports what the spawn actually became (see
    ``_confirm_desktop_shell_launch``): ``launched`` is true only once the child
    holds the shell owner lock or kept running without any owner record;
    ``launchPid`` is the spawned process and ``ownerPid`` the confirmed holder.
    A second instance that bowed out to a live owner is reported as
    ``BOWED_OUT_TO_LIVE_OWNER`` (``forwarded`` when that owner was already live
    before the spawn, i.e. a lifecycle forward). With ``expect_primary`` the
    caller needs a replacement primary, so a verifiably live owner refuses the
    spawn with ``LIVE_OWNER_HOLDING_LOCK`` instead of launching a bow-out.
    """

    spec = resolve_desktop_shell_launch(
        project_root,
        then_lifecycle=then_lifecycle,
        open_workbench=open_workbench,
        hidden_presentation=hidden_presentation,
        prefer=prefer,
    )
    args = list(spec["args"])
    args.extend(_desktop_launch_request_args(launch_request_id, launch_request_operation, launch_request_handoff_pid))
    shell_root = Path(str(spec["cwd"]))
    base = {
        **spec,
        "thenLifecycle": str(then_lifecycle or "").strip().lower(),
        "openWorkbench": bool(open_workbench),
        **({"launchRequestId": launch_request_id} if launch_request_id else {}),
    }
    pre_owner = _verified_live_desktop_shell_owner(shell_root)
    if expect_primary and pre_owner is not None:
        return {**base, **_refused_launch_payload(pre_owner)}
    process = _spawn_visible_electron(args, cwd=shell_root)
    confirmation = _confirm_desktop_shell_launch(process, shell_root=shell_root)
    return {**base, **_launch_result_payload(process, confirmation, pre_owner=pre_owner)}


def launch_packaged_desktop_shell(
    *,
    project_root: Path | str = PROJECT_ROOT,
    then_lifecycle: str = "",
    open_workbench: bool = False,
    expect_primary: bool = False,
    launch_request_id: str = "",
    launch_request_operation: str = "",
    launch_request_handoff_pid: int = 0,
) -> dict[str, Any]:
    """Spawn the packaged exe; same confirmation contract as launch_desktop_shell."""

    root = Path(project_root)
    exe = packaged_desktop_exe(root)
    if not exe.is_file():
        raise FileNotFoundError(f"packaged desktop shell was not found: {exe}")
    args = [str(exe), "--workspace", str(root), "--local-debugging"]
    lifecycle = str(then_lifecycle or "").strip().lower()
    if open_workbench:
        # Align with the unpackaged refresh launch: a replacement shell must
        # come up serving the workbench, not only the tray.
        args.append("--open-workbench")
    if lifecycle:
        args.append(lifecycle)
    args.extend(_desktop_launch_request_args(launch_request_id, launch_request_operation, launch_request_handoff_pid))
    base = {"thenLifecycle": lifecycle, "openWorkbench": bool(open_workbench)}
    pre_owner = _verified_live_desktop_shell_owner(root)
    if expect_primary and pre_owner is not None:
        return {**base, **_refused_launch_payload(pre_owner)}
    process = _spawn_visible_electron(args, cwd=root)
    confirmation = _confirm_desktop_shell_launch(process, shell_root=root)
    return {**base, **_launch_result_payload(process, confirmation, pre_owner=pre_owner)}


def _owner_identity_payload(record: dict[str, Any], status: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "owner": str(record.get("owner") or ""),
        "pid": int(record.get("pid") or 0),
        "identityStatus": status,
    }
    for key in ("createTime", "executable", "updatedAt"):
        if record.get(key):
            payload[key] = record[key]
    return payload


def _verified_live_desktop_shell_owner(shell_root: Path) -> dict[str, Any] | None:
    """Return the owner record only when the recorded process is verifiably alive.

    A ``dead`` or recycled-pid (``mismatch``) record is residue, not a holder,
    and must never block or misclassify a launch. ``unknown`` (record without
    createTime/executable) falls back to pid existence, as
    ``electron_owns_desktop_tray`` does.
    """

    from core.launcher.desktop_shell_owner import _identity_status, is_pid_alive, read_desktop_shell_owner

    record = read_desktop_shell_owner(shell_root)
    if not record:
        return None
    status = _identity_status(record)
    if status == "match":
        return _owner_identity_payload(record, status)
    if status == "unknown" and is_pid_alive(int(record.get("pid") or 0)):
        return _owner_identity_payload(record, status)
    return None


def _desktop_debug_record_path(shell_root: Path) -> Path:
    from core.launcher.desktop_shell_owner import desktop_shell_owner_path

    return desktop_shell_owner_path(shell_root).with_name(DESKTOP_DEBUG_FILE_NAME)


def _read_desktop_debug_identity(shell_root: Path) -> dict[str, Any] | None:
    """Only the primary instance publishes desktop_debug.json with its identity."""

    record = _read_json(_desktop_debug_record_path(shell_root))
    try:
        pid = int(record.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        create_time = float(record.get("createTime") or 0)
    except (TypeError, ValueError):
        create_time = 0.0
    return {"pid": pid, "createTime": create_time, "executable": str(record.get("executable") or "")}


def _create_times_align(first: Any, second: Any) -> bool:
    try:
        left = float(first or 0)
        right = float(second or 0)
    except (TypeError, ValueError):
        return True
    if left <= 0 or right <= 0:
        # One side has no identity to compare; do not fabricate a mismatch.
        return True
    return abs(left - right) <= PID_IDENTITY_CREATE_TIME_TOLERANCE_SECONDS


def _capture_launch_identity(pid: int) -> dict[str, Any]:
    from core.runtime_manager.process_identity import capture_process_identity

    try:
        return dict(capture_process_identity(int(pid)) or {})
    except Exception:
        return {}


def _launched_process_alive(process: Any, identity: dict[str, Any]) -> bool:
    """Liveness of our own child: the Popen handle first, then pid identity.

    ``poll`` on a handle we own cannot be fooled by pid reuse (Windows keeps the
    pid reserved while the handle is open), so its answer is final. The
    create-time identity check only serves objects that expose a bare pid.
    """

    poll = getattr(process, "poll", None)
    if callable(poll):
        try:
            return poll() is None
        except Exception:
            pass
    pid = int(getattr(process, "pid", 0) or 0)
    try:
        expected = float(identity.get("createTime") or 0)
    except (TypeError, ValueError):
        expected = 0.0
    return _pid_alive_with_identity(pid, expected or None)


def _launched_process_exit_code(process: Any) -> int | None:
    code = getattr(process, "returncode", None)
    return int(code) if isinstance(code, int) else None


def _confirm_desktop_shell_launch(
    process: Any,
    *,
    shell_root: Path,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> dict[str, Any]:
    """Watch a freshly spawned shell until it is the owner, bowed out, or crashed.

    Three outcomes, polled every ``poll_seconds`` for at most ``timeout_seconds``:

    * ``confirmed``: the owner file (preferred) or desktop_debug.json names the
      child pid -> ``launched`` true, ``ownerPid`` = child.
    * ``bowed_out``: the child exited while another verified-live process holds
      the owner lock -> ``BOWED_OUT_TO_LIVE_OWNER`` with that owner's identity.
    * ``crashed``: the child exited and nobody live holds the lock ->
      ``LAUNCH_CRASHED`` with the exit code.

    Without any owner record the protocol degrades to "child still alive at the
    deadline" (``weak_alive``, ``degraded`` true) so a shell build that predates
    owner publication is never reported as permanently failed. A child alive at
    the deadline while a different live owner holds the lock is
    ``alive_unconfirmed`` (``degraded`` true, foreign ``ownerPid``).
    """

    timeout = LAUNCH_CONFIRMATION_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds)
    interval = LAUNCH_CONFIRMATION_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    pid = int(getattr(process, "pid", 0) or 0)
    identity = _capture_launch_identity(pid)
    started = time.monotonic()
    deadline = started + max(0.0, timeout)

    def _finish(state: str, **fields: Any) -> dict[str, Any]:
        return {"state": state, "elapsedSeconds": round(time.monotonic() - started, 3), **fields}

    owner: dict[str, Any] | None = None
    while True:
        owner = _verified_live_desktop_shell_owner(shell_root)
        if owner is not None and int(owner.get("pid") or 0) == pid:
            return _finish("confirmed", launched=True, degraded=False, ownerPid=pid, evidence="owner_file", owner=owner)
        debug = _read_desktop_debug_identity(shell_root)
        if debug is not None and debug["pid"] == pid and _create_times_align(debug.get("createTime"), identity.get("createTime")):
            return _finish("confirmed", launched=True, degraded=False, ownerPid=pid, evidence="desktop_debug", owner=owner)
        if not _launched_process_alive(process, identity):
            exit_code = _launched_process_exit_code(process)
            if owner is not None and int(owner.get("pid") or 0) != pid:
                return _finish(
                    "bowed_out",
                    launched=False,
                    degraded=False,
                    errorCode=LAUNCH_ERROR_BOWED_OUT_TO_LIVE_OWNER,
                    ownerPid=int(owner.get("pid") or 0),
                    owner=owner,
                    exitCode=exit_code,
                    evidence="child_exited_owner_live",
                )
            return _finish(
                "crashed",
                launched=False,
                degraded=False,
                errorCode=LAUNCH_ERROR_LAUNCH_CRASHED,
                ownerPid=0,
                owner=None,
                exitCode=exit_code,
                evidence="child_exited_no_owner",
            )
        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(max(0.0, min(interval, deadline - now)))
    if owner is not None and int(owner.get("pid") or 0) != pid:
        return _finish(
            "alive_unconfirmed",
            launched=True,
            degraded=True,
            ownerPid=int(owner.get("pid") or 0),
            owner=owner,
            evidence="child_alive_foreign_owner",
        )
    return _finish("weak_alive", launched=True, degraded=True, ownerPid=0, owner=None, evidence="child_alive_no_owner_record")


def _confirmation_summary(confirmation: dict[str, Any]) -> dict[str, Any]:
    summary = {key: confirmation[key] for key in ("state", "evidence", "degraded", "elapsedSeconds") if key in confirmation}
    if confirmation.get("exitCode") is not None:
        summary["exitCode"] = confirmation["exitCode"]
    return summary


def _launch_result_payload(process: Any, confirmation: dict[str, Any], *, pre_owner: dict[str, Any] | None) -> dict[str, Any]:
    launch_pid = int(getattr(process, "pid", 0) or 0)
    owner_pid = int(confirmation.get("ownerPid") or 0)
    launched = bool(confirmation.get("launched"))
    payload: dict[str, Any] = {
        "launched": launched,
        "launchPid": launch_pid,
        "ownerPid": owner_pid,
        # Legacy readers log ``pid``; it has always been the spawned process and
        # never implied ownership. Prefer launchPid/ownerPid.
        "pid": launch_pid,
        "confirmation": _confirmation_summary(confirmation),
    }
    if confirmation.get("degraded"):
        payload["degraded"] = True
    owner = confirmation.get("owner")
    if owner:
        payload["owner"] = owner
    if not launched:
        payload["errorCode"] = str(confirmation.get("errorCode") or LAUNCH_ERROR_LAUNCH_CRASHED)
        payload["exitCode"] = confirmation.get("exitCode")
        if (
            payload["errorCode"] == LAUNCH_ERROR_BOWED_OUT_TO_LIVE_OWNER
            and pre_owner is not None
            and int(pre_owner.get("pid") or 0) == owner_pid
        ):
            # The owner was already live before we spawned: this instance was a
            # lifecycle forward, not an unexpected loss of the primary.
            payload["forwarded"] = True
    return payload


def _refused_launch_payload(owner: dict[str, Any]) -> dict[str, Any]:
    return {
        "launched": False,
        "launchPid": 0,
        "ownerPid": int(owner.get("pid") or 0),
        "pid": 0,
        "errorCode": LAUNCH_ERROR_LIVE_OWNER_HOLDING_LOCK,
        "owner": owner,
        "confirmation": {"state": "refused", "evidence": "owner_file", "degraded": False},
    }


def _spawn_visible_electron(args: list[str], *, cwd: Path) -> subprocess.Popen[Any]:
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        # GUI Electron must not inherit STARTUPINFO SW_HIDE / CREATE_NO_WINDOW
        # from the no-console helper policy, or the new shell can come up invisible.
        popen_kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
        popen_kwargs["close_fds"] = True
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_kwargs,
    )


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


def _frontend_directory_content_sha256(path: Path) -> str:
    """Hash every packaged frontend path and its bytes in deterministic order."""

    if not path.is_dir() or path.is_symlink():
        return ""
    try:
        files = sorted(
            (entry for entry in path.rglob("*") if entry.is_file() and not entry.is_symlink()),
            key=lambda entry: entry.relative_to(path).as_posix().encode("utf-8"),
        )
        if any(entry.is_symlink() for entry in path.rglob("*")):
            return ""
        digest = hashlib.sha256()
        for entry in files:
            relative_path = entry.relative_to(path).as_posix().encode("utf-8")
            content = entry.read_bytes()
            digest.update(len(relative_path).to_bytes(4, "big"))
            digest.update(relative_path)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()
    except OSError:
        return ""


def _electron_sources_newer_than_asar(project_root: Path) -> bool:
    return _electron_sources_newer_than(project_root, packaged_asar_path(project_root))


def _electron_package_sources_clean(project_root: Path) -> bool:
    """Prove all Electron package inputs match HEAD without relying on mtimes."""

    try:
        result = run_git(
            ["status", "--porcelain", "--untracked-files=all", "--", ELECTRON_PACKAGE_DIR.as_posix()],
            cwd=project_root, timeout=10.0,
        )
        return result.returncode == 0 and not str(result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return False


def _electron_worktree_dirty(project_root: Path) -> bool | None:
    """Whether ``desktop/electron/src`` differs from HEAD.

    A checkout refreshes file timestamps without changing bytes. Those
    timestamps must not schedule a shell rebuild. ``None`` means git could
    not answer, so the caller keeps the timestamp fallback.
    """

    result = run_git(
        ["status", "--porcelain", "--untracked-files=normal", "--", ELECTRON_SRC_RELATIVE.as_posix()],
        cwd=project_root,
        timeout=10.0,
    )
    if int(result.returncode or 0) != 0:
        return None
    return bool(str(result.stdout or "").strip())


def _electron_sources_newer_than(project_root: Path, artifact: Path) -> bool:
    src_root = project_root / ELECTRON_SRC_RELATIVE
    if not artifact.is_file() or not src_root.is_dir():
        return False
    try:
        artifact_mtime = artifact.stat().st_mtime
    except OSError:
        return _electron_worktree_dirty(project_root) is not False
    # No newer timestamp can block launch, even for a dirty worktree. Only
    # query Git when it can dismiss a timestamp-only change (for example checkout).
    scan_error: OSError | None = None
    try:
        for path in src_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime > artifact_mtime:
                    break
            except OSError:
                continue
        else:
            return False
    except OSError as error:
        scan_error = error
    if _electron_worktree_dirty(project_root) is False:
        return False
    if scan_error is not None:
        raise scan_error
    return True


class UnpackagedElectronPublishBusy(RuntimeError):
    """The live shell still has dist open, so the staged build was not published."""


def _sharing_violation(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror in {5, 32, 33}:
        return True
    text_busy = getattr(errno, "ETXTBSY", None)
    return exc.errno in {errno.EBUSY, errno.EACCES, errno.EPERM, text_busy}


def _rename_dir(src: Path, dest: Path) -> None:
    os.rename(src, dest)


def _retire_previous_electron_dists(parent: Path) -> None:
    """Retry only our backup directories; loaded Windows images remain owned."""

    for previous in parent.glob(".dist-previous*"):
        suffix = previous.name.removeprefix(".dist-previous")
        if suffix and not (
            len(suffix) == 33 and suffix[0] == "-"
            and all(char in "0123456789abcdef" for char in suffix[1:])
        ):
            continue
        try:
            if (
                previous.is_symlink()
                or getattr(previous, "is_junction", lambda: False)()
                or previous.resolve().parent != parent.resolve()
            ):
                continue
            shutil.rmtree(previous)
        except OSError:
            # Cleanup is retryable and must not undo a successfully published
            # replacement. A mapped .node can outlive its original directory.
            continue


def _publish_staged_electron_dist(stage: Path, dist: Path) -> None:
    """Swap a finished stage into dist. A locked live dist is left untouched."""

    if not (stage / "main.js").is_file():
        raise RuntimeError(f"staged Electron build is missing main.js: {stage}")
    parent = dist.parent
    parent.mkdir(parents=True, exist_ok=True)
    incoming = parent / ".dist-incoming"
    previous = parent / f".dist-previous-{uuid4().hex}"
    if incoming.exists():
        shutil.rmtree(incoming)
    shutil.copytree(stage, incoming)
    busy = UnpackagedElectronPublishBusy(
        "桌面壳正在使用 workbench_job.node，这次没有替换正在运行的壳，也没有改动已经装好的 dist。"
    )
    try:
        if dist.exists():
            try:
                _rename_dir(dist, previous)
            except OSError as exc:
                shutil.rmtree(incoming, ignore_errors=True)
                if _sharing_violation(exc):
                    raise busy from exc
                raise
        try:
            _rename_dir(incoming, dist)
        except OSError as exc:
            if previous.exists() and not dist.exists():
                _rename_dir(previous, dist)
            shutil.rmtree(incoming, ignore_errors=True)
            if _sharing_violation(exc):
                raise busy from exc
            raise
    finally:
        if dist.exists():
            _retire_previous_electron_dists(parent)


def build_unpackaged_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Compile and publish checkout dist through the shared build owner."""
    return _rebuild_unpackaged_electron(Path(project_root).resolve())


def _rebuild_unpackaged_electron(project_root: Path, *, prepare_only: bool = False) -> dict[str, Any]:
    """Build Electron main beside dist, then publish only after the stage is complete."""

    electron_dir = project_root / ELECTRON_PACKAGE_DIR
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _wait_for_desktop_shell_build_lock(project_root, deadline=deadline)
    stage = electron_dir / f".build-stage-{uuid4().hex}"
    try:
        stage.mkdir(parents=True)
        current_tree = _git_tree_hash(project_root, "HEAD:desktop/electron")
        node_command = _node_command()
        env = os.environ.copy()
        env["VIBELUTION_DESKTOP_BUILD_MANAGED"] = "1"
        env["VIBELUTION_DESKTOP_BUILD_ROOT"] = str(stage)
        env["VIBELUTION_ELECTRON_DIST"] = str(stage)
        env["VIBELUTION_WORKBENCH_JOB_BUILD_ROOT"] = str(stage / ".workbench-job-build")
        commands = [
            [
                node_command,
                str(electron_dir / "node_modules" / "typescript" / "lib" / "tsc.js"),
                "-p",
                "tsconfig.json",
                "--outDir",
                str(stage),
            ],
            [
                node_command,
                str(electron_dir / "node_modules" / "esbuild" / "bin" / "esbuild"),
                "src/preload.ts",
                "--bundle",
                "--platform=node",
                "--format=cjs",
                f"--outfile={stage / 'preload.cjs'}",
                "--external:electron",
            ],
            [node_command, str(electron_dir / "scripts" / "buildWorkbenchJob.js")],
        ]
        for command in commands:
            try:
                _run_owned_process(
                    command,
                    cwd=electron_dir,
                    env=env,
                    deadline=deadline,
                    label="checkout Electron main build",
                )
            except BuildProcessRetirementError as exc:
                _register_pending_build_retirement(
                    project_root,
                    exc.owner,
                    cleanup_paths=(stage,),
                    lock_relative=PREBUILD_LOCK_RELATIVE,
                )
                raise
        if _git_tree_hash(project_root, "HEAD:desktop/electron") != current_tree:
            raise RuntimeError("Electron sources changed during the build; retry Launcher update.")
        if not _unpackaged_electron_dist_is_complete(stage):
            raise RuntimeError("Staged Electron build is incomplete; retry Launcher update.")
        _write_unpackaged_provenance(project_root, current_tree, dist=stage)
        destination = project_root / UNPACKAGED_STAGING_RELATIVE if prepare_only else electron_dir / "dist"
        _publish_staged_electron_dist(stage, destination)
        if not prepare_only:
            shutil.rmtree(project_root / UNPACKAGED_STAGING_RELATIVE, ignore_errors=True)
    except Exception as exc:
        _append_refresh_log(project_root, "unpackaged.build.failed", detail=str(exc)[-800:])
        raise
    finally:
        if not _pending_build_retirement_for(project_root, cleanup_path=stage):
            shutil.rmtree(stage, ignore_errors=True)
        if not _pending_build_retirement_for(project_root):
            _release_desktop_shell_refresh_lock(project_root, lock_relative=PREBUILD_LOCK_RELATIVE)
    main_js = (
        project_root / UNPACKAGED_STAGING_RELATIVE / "main.js"
        if prepare_only else unpackaged_main_js(project_root)
    )
    if not main_js.is_file():
        raise RuntimeError(f"checkout Electron main was not produced: {main_js}")
    return {
        "rebuilt": True,
        "prepared": prepare_only,
        "reason": "prepared" if prepare_only else "current",
        "currentElectronTree": current_tree,
    }


def _write_unpackaged_provenance(project_root: Path, tree_hash: str, *, dist: Path | None = None) -> None:
    path = dist / "unpackaged-provenance.json" if dist is not None else unpackaged_provenance_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "electronTreeHash": str(tree_hash or "").strip(),
        "sourceCommit": _git_tree_hash(project_root, "HEAD"),
        "builtAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _wait_for_pid_exit(
    pid: int,
    *,
    timeout_seconds: float,
    expected_create_time: float | None = None,
) -> None:
    """Block until ``pid`` (as the process it names now) has exited.

    The identity is pinned at entry (caller-supplied create time, usually from
    the owner record, else captured now) so a pid recycled by an unrelated
    process is treated as "exited", not as the shell still running.
    """

    expected = float(expected_create_time or 0) or _process_create_time(pid)
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        if not _pid_alive_with_identity(pid, expected):
            time.sleep(1.2)
            return
        time.sleep(0.2)
    if _pid_alive_with_identity(pid, expected):
        raise TimeoutError(f"desktop shell pid {pid} did not exit before rebuild")


def _pid_alive_with_identity(pid: int, expected_create_time: float | None) -> bool:
    """Existence plus create-time identity: a recycled pid is not the original.

    Falls back to bare existence when no expected create time is known or the
    current one cannot be read (psutil missing, access denied).
    """

    if not _pid_alive(pid):
        return False
    try:
        expected = float(expected_create_time or 0)
    except (TypeError, ValueError):
        expected = 0.0
    if expected > 0:
        actual = _process_create_time(pid)
        if actual is not None and abs(actual - expected) > PID_IDENTITY_CREATE_TIME_TOLERANCE_SECONDS:
            return False
    return True


def _expected_create_time_for_pid(project_root: Path, pid: int) -> float | None:
    """Prefer the owner record's create time for the shell pid we wait on."""

    from core.launcher.desktop_shell_owner import read_desktop_shell_owner

    try:
        record = read_desktop_shell_owner(project_root)
    except Exception:
        record = None
    if record and int(record.get("pid") or 0) == int(pid):
        try:
            create_time = float(record.get("createTime") or 0)
        except (TypeError, ValueError):
            create_time = 0.0
        if create_time > 0:
            return create_time
    return _process_create_time(pid)


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


def _process_create_time(pid: int) -> float | None:
    """Return when the PID's current process was created, as epoch seconds.

    ``None`` means unknown: psutil is missing, the process vanished, or the
    query was denied. Callers treat ``None`` conservatively instead of
    claiming a recycled PID.
    """

    if pid <= 0:
        return None
    try:
        import psutil
    except Exception:
        return None
    try:
        return float(psutil.Process(int(pid)).create_time())
    except Exception:
        return None


def _append_refresh_log(project_root: Path, event: str, **fields: Any) -> None:
    try:
        from vibelution_storage import resolve_active_project_storage_paths

        path = resolve_active_project_storage_paths(project_root).runtime / "launcher" / "desktop-shell-refresh.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"event": event, **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Structured logging is strictly best-effort: a missing project
        # identity or an unwritable runtime tree must never break the refresh
        # or prebuild flows it observes.
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
