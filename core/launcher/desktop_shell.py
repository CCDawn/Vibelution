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
from core.infrastructure.windows_process_job import WindowsProcessJob
from core.launcher.frontend_build import (
    frontend_releases_dir,
    inspect_frontend_build,
    resolve_active_frontend_dist,
)
from core.runtime_manager.constants import PROJECT_ROOT
from scripts.windowless_subprocess import no_window_subprocess_kwargs

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
            shutil.rmtree(path, ignore_errors=True)
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


def inspect_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return whether the packaged Electron shell and Launcher frontend are current."""

    root = Path(project_root)
    current_tree = _git_tree_hash(root, "HEAD:desktop/electron")
    current_commit = _git_tree_hash(root, "HEAD")
    provenance = _read_json(packaged_provenance_path(root))
    packaged_tree = str(provenance.get("electronTreeHash") or "").strip()
    exe_path = packaged_desktop_exe(root)
    asar_path = packaged_asar_path(root)
    source_newer = _electron_sources_newer_than_asar(root)
    packaged_frontend_path = packaged_frontend_dist(root)
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
    if not exe_path.is_file() or not asar_path.is_file():
        reason = "missing_package"
        stale = True
    elif not packaged_tree:
        reason = "missing_provenance"
        stale = True
    elif not current_tree:
        reason = "current_electron_tree_unavailable"
        stale = True
    elif packaged_tree != current_tree:
        reason = "provenance_mismatch"
        stale = True
    elif source_newer:
        reason = "source_newer_than_asar"
        stale = True
    elif not packaged_frontend_path.is_dir() or not expected_frontend_hash or not packaged_frontend_tree:
        reason = "missing_frontend_provenance"
        stale = True
    elif not packaged_frontend_hash or packaged_frontend_hash != expected_frontend_hash:
        reason = "frontend_package_content_mismatch"
        stale = True
    elif frontend_build_current is not True:
        reason = "frontend_source_stale" if frontend_build_current is False else "frontend_inspection_failed"
        stale = True
    elif not current_frontend_tree:
        reason = "current_frontend_tree_unavailable"
        stale = True
    elif not current_frontend_hash or current_frontend_hash != packaged_frontend_hash:
        reason = "frontend_release_mismatch"
        stale = True
    elif current_frontend_tree and packaged_frontend_tree != current_frontend_tree:
        reason = "frontend_source_mismatch"
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


def schedule_desktop_shell_refresh(
    *,
    wait_pid: int,
    then_lifecycle: str = "",
    project_root: Path | str = PROJECT_ROOT,
    python_executable: str | None = None,
    force: bool = False,
    shell_kind: str = "",
) -> dict[str, Any]:
    """Start a detached helper that rebuilds the shell after ``wait_pid`` exits."""

    root = Path(project_root)
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
) -> dict[str, Any]:
    """Wait for the old shell to exit, rebuild from checkout, then relaunch."""

    root = Path(project_root)
    try:
        _append_refresh_log(root, "refresh.started", wait_pid=int(wait_pid), then_lifecycle=str(then_lifecycle or ""))
        if int(wait_pid) > 0:
            _wait_for_pid_exit(int(wait_pid), timeout_seconds=wait_timeout_seconds)
        kind = str(shell_kind or "").strip().lower()
        try:
            if kind == "unpackaged":
                rebuilt = ensure_unpackaged_electron(root)
                launched = launch_desktop_shell(
                    project_root=root,
                    then_lifecycle=then_lifecycle,
                    open_workbench=True,
                    prefer="unpackaged",
                )
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
                    "kind": "unpackaged",
                    "rebuild": rebuilt,
                    "launch": launched,
                }
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


def _run_desktop_shell_package_build(root: Path, *, mode: str, deadline: float) -> Path:
    session = root / "dist" / f".desktop-shell-build-{uuid4().hex}"
    electron_dir = root / ELECTRON_PACKAGE_DIR
    node_command = _node_command()
    command = [node_command, str(electron_dir / "scripts" / "buildDesktopPackage.js"), "--mode", mode]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_BUILD_ROOT"] = str(session)
    env["VIBELUTION_DESKTOP_BUILD_MANAGED"] = "1"
    try:
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
        shutil.rmtree(session, ignore_errors=True)
        raise


def build_desktop_shell_package(
    project_root: Path | str = PROJECT_ROOT,
    *,
    mode: str = "dir",
) -> dict[str, Any]:
    """Build and publish a package through the shared project build owner."""

    if mode not in {"dir", "staging", "linux-arm64"}:
        raise ValueError(f"unsupported desktop package mode: {mode}")
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
            shutil.rmtree(session, ignore_errors=True)
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
        _publish_built_shell_tree(
            built,
            root / STAGING_WIN_UNPACKED_RELATIVE,
            previous=root / STAGING_OUTPUT_DIR_RELATIVE / ".win-unpacked-previous",
        )
        return {"electronTreeHash": staged_tree}
    finally:
        if not _pending_build_retirement_for(root, cleanup_path=session):
            shutil.rmtree(session, ignore_errors=True)


def _try_promote_staged_desktop_shell(root: Path) -> bool:
    """Swap a valid staged build into the live ``win-unpacked`` via rename.

    Serialized on the prebuild lock: a running prebuild helper is mid-write on
    the staging tree (electron-builder's copy order is unspecified, so a
    half-written package can already expose exe and provenance), and renaming
    it in would ship a broken shell. Lock contention therefore yields to the
    helper and the caller falls back to the real rebuild. Only the Electron
    tree hash gates the swap; the caller still runs the full
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


def _try_promote_staged_desktop_shell_locked(root: Path) -> bool:
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
    live = root / "dist" / "desktop" / "win-unpacked"
    previous = root / PREVIOUS_WIN_UNPACKED_RELATIVE
    try:
        _publish_built_shell_tree(staging_unpacked, live, previous=previous)
    except OSError:
        # A sharing violation here means something still holds the live tree
        # open; leave staging and the old package untouched for a later retry.
        return False
    shutil.rmtree(root / STAGING_OUTPUT_DIR_RELATIVE, ignore_errors=True)
    return True


def _publish_built_shell_tree(source: Path, destination: Path, *, previous: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous.parent.mkdir(parents=True, exist_ok=True)
    moved_previous = False
    try:
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
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
        shutil.rmtree(previous, ignore_errors=True)


def rebuild_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Rebuild ``win-unpacked`` from the current ``desktop/electron`` checkout."""

    root = Path(project_root)
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _wait_for_desktop_shell_build_lock(root, deadline=deadline)
    try:
        if _try_promote_staged_desktop_shell_locked(root):
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
            _publish_built_shell_tree(
                built,
                root / PACKAGED_EXE_RELATIVE.parent,
                previous=root / PREVIOUS_WIN_UNPACKED_RELATIVE,
            )
        finally:
            if not _pending_build_retirement_for(root, cleanup_path=session):
                shutil.rmtree(session, ignore_errors=True)

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
    rebuilt = _rebuild_unpackaged_electron(root)
    current_tree = str(rebuilt.get("currentElectronTree") or _git_tree_hash(root, "HEAD:desktop/electron"))
    status = inspect_unpackaged_electron(root)
    if status["stale"]:
        raise RuntimeError(f"checkout Electron main is still stale after build: {status['reason']}")
    return {"ensured": True, "rebuilt": True, **status}


def ensure_latest_launcher(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Rebuild unpackaged Electron and ensure the active frontend release is current.

    Tray "启动最新 Launcher" on an unpackaged shell relaunches the same process;
    without this step it keeps serving a stale frontend release after local sources move.
    """

    root = Path(project_root)
    electron = ensure_unpackaged_electron(root)
    from core.runtime_manager.daemon import _preflight_frontend_build_for_restart

    frontend = _preflight_frontend_build_for_restart("ensure-latest-launcher", project_root=root)
    if not bool(frontend.get("ok", True)):
        raise RuntimeError(str(frontend.get("reason") or "frontend ensure failed"))
    return {
        "schemaVersion": 1,
        "ok": True,
        "electron": {
            "rebuilt": bool(electron.get("rebuilt")),
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
    if slot_root is not None:
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
    # A live main owns freshness and guarded relaunch. Rebuilding here first
    # consumes its `rebuilt` signal and leaves old main code running indefinitely.
    if lifecycle in {"start", "restart", "rebuild-and-start"}:
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
    packaged_status = inspect_desktop_shell(shell_root)
    # launchBlocking, not stale: advisory frontend staleness still launches the
    # packaged exe because the launcher window follows the workspace active
    # release, and reporting the real reason keeps downstream status honest.
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


def launch_desktop_shell(
    *,
    project_root: Path | str = PROJECT_ROOT,
    then_lifecycle: str = "",
    open_workbench: bool = False,
    hidden_presentation: bool = False,
    prefer: str = "",
) -> dict[str, Any]:
    """Start Electron main for the current checkout without hiding the GUI."""

    spec = resolve_desktop_shell_launch(
        project_root,
        then_lifecycle=then_lifecycle,
        open_workbench=open_workbench,
        hidden_presentation=hidden_presentation,
        prefer=prefer,
    )
    process = _spawn_visible_electron(list(spec["args"]), cwd=Path(str(spec["cwd"])))
    return {
        **spec,
        "launched": True,
        "pid": int(getattr(process, "pid", 0) or 0),
        "thenLifecycle": str(then_lifecycle or "").strip().lower(),
        "openWorkbench": bool(open_workbench),
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
    args = [str(exe), "--workspace", str(root), "--local-debugging"]
    lifecycle = str(then_lifecycle or "").strip().lower()
    if lifecycle:
        args.append(lifecycle)
    process = _spawn_visible_electron(args, cwd=root)
    return {
        "launched": True,
        "pid": int(getattr(process, "pid", 0) or 0),
        "thenLifecycle": lifecycle,
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


def _electron_sources_newer_than(project_root: Path, artifact: Path) -> bool:
    src_root = project_root / ELECTRON_SRC_RELATIVE
    if not artifact.is_file() or not src_root.is_dir():
        return False
    try:
        artifact_mtime = artifact.stat().st_mtime
    except OSError:
        return True
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime > artifact_mtime:
                return True
        except OSError:
            continue
    return False


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


def _publish_staged_electron_dist(stage: Path, dist: Path) -> None:
    """Swap a finished stage into dist. A locked live dist is left untouched."""

    if not (stage / "main.js").is_file():
        raise RuntimeError(f"staged Electron build is missing main.js: {stage}")
    parent = dist.parent
    incoming = parent / ".dist-incoming"
    previous = parent / ".dist-previous"
    if incoming.exists():
        shutil.rmtree(incoming)
    if previous.exists():
        shutil.rmtree(previous)
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
        if previous.exists() and dist.exists():
            shutil.rmtree(previous, ignore_errors=True)


def build_unpackaged_desktop_shell(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Compile and publish checkout dist through the shared build owner."""
    return _rebuild_unpackaged_electron(Path(project_root).resolve())


def _rebuild_unpackaged_electron(project_root: Path) -> dict[str, Any]:
    """Build Electron main beside dist, then publish only after the stage is complete."""

    electron_dir = project_root / ELECTRON_PACKAGE_DIR
    deadline = time.monotonic() + DESKTOP_SHELL_BUILD_DEADLINE_SECONDS
    _wait_for_desktop_shell_build_lock(project_root, deadline=deadline)
    stage = electron_dir / f".build-stage-{uuid4().hex}"
    try:
        stage.mkdir(parents=True)
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
        _publish_staged_electron_dist(stage, electron_dir / "dist")
        current_tree = _git_tree_hash(project_root, "HEAD:desktop/electron")
        _write_unpackaged_provenance(project_root, current_tree)
    except Exception as exc:
        _append_refresh_log(project_root, "unpackaged.build.failed", detail=str(exc)[-800:])
        raise
    finally:
        if not _pending_build_retirement_for(project_root, cleanup_path=stage):
            shutil.rmtree(stage, ignore_errors=True)
        if not _pending_build_retirement_for(project_root):
            _release_desktop_shell_refresh_lock(project_root, lock_relative=PREBUILD_LOCK_RELATIVE)
    main_js = unpackaged_main_js(project_root)
    if not main_js.is_file():
        raise RuntimeError(f"checkout Electron main was not produced: {main_js}")
    return {"rebuilt": True, "currentElectronTree": current_tree}


def _write_unpackaged_provenance(project_root: Path, tree_hash: str) -> None:
    path = unpackaged_provenance_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "electronTreeHash": str(tree_hash or "").strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
