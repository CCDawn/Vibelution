"""Product desktop tray owner lock.

Electron is the product shell owner. Native WinForms yields its NotifyIcon when
an alive Electron pid holds this file. Schema is duplicated in
desktop/electron/src/tray/desktopShellOwner.ts and VibelutionLauncher.cs.
Writes always go to the canonical project runtime path; checkout `.runtime`
is read-only compatibility.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from vibelution_storage import ProjectIdentityError, resolve_project_storage_paths

OWNER_FILE_NAME = "desktop_shell_owner.json"
OWNER_RELATIVE_PATH = Path(".runtime") / "launcher" / OWNER_FILE_NAME
SCHEMA_VERSION = 1
CREATE_TIME_TOLERANCE_SECONDS = 2.0
DesktopShellOwnerKind = Literal["electron", "winforms"]


def checkout_desktop_shell_owner_path(project_root: Path) -> Path:
    return Path(project_root) / OWNER_RELATIVE_PATH


def canonical_desktop_shell_owner_path(project_root: Path) -> Path | None:
    try:
        paths = resolve_project_storage_paths(project_root)
    except (ProjectIdentityError, OSError, ValueError):
        return None
    return paths.runtime / "launcher" / OWNER_FILE_NAME


def desktop_shell_owner_path(project_root: Path) -> Path:
    return canonical_desktop_shell_owner_path(project_root) or checkout_desktop_shell_owner_path(project_root)


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_exists(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_exists(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def _read_owner_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    owner = str(payload.get("owner") or "").strip()
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if owner not in {"electron", "winforms"} or pid <= 0:
        return None
    record: dict[str, Any] = {
        "schemaVersion": int(payload.get("schemaVersion") or SCHEMA_VERSION),
        "owner": owner,
        "pid": pid,
    }
    try:
        create_time = float(payload.get("createTime") or 0)
    except (TypeError, ValueError):
        create_time = 0.0
    executable = str(payload.get("executable") or "").strip()
    updated_at = str(payload.get("updatedAt") or "").strip()
    if create_time > 0:
        record["createTime"] = create_time
    if executable:
        record["executable"] = executable
    if updated_at:
        record["updatedAt"] = updated_at
    return record


def read_desktop_shell_owner(project_root: Path) -> dict[str, Any] | None:
    canonical = canonical_desktop_shell_owner_path(project_root)
    if canonical is not None:
        record = _read_owner_file(canonical)
        if record is not None:
            return record
    return _read_owner_file(checkout_desktop_shell_owner_path(project_root))


def _has_complete_identity(record: dict[str, Any]) -> bool:
    try:
        create_time = float(record.get("createTime") or 0)
    except (TypeError, ValueError):
        create_time = 0.0
    return create_time > 0 and bool(str(record.get("executable") or "").strip())


def _identity_status(record: dict[str, Any]) -> str:
    if not _has_complete_identity(record):
        return "unknown"
    from core.runtime_manager.process_identity import capture_process_identity, inspect_process_identity

    result = inspect_process_identity(record)
    status = str(result.get("status") or "unknown")
    if status != "mismatch" or str(result.get("reason") or "") != "create_time_mismatch":
        return status
    captured = capture_process_identity(int(record.get("pid") or 0))
    if not captured:
        return status
    try:
        expected = float(record.get("createTime") or 0)
        actual = float(captured.get("createTime") or 0)
    except (TypeError, ValueError):
        return status
    if abs(actual - expected) > CREATE_TIME_TOLERANCE_SECONDS:
        return status
    expected_exe = os.path.normcase(os.path.normpath(str(record.get("executable") or "")))
    actual_exe = os.path.normcase(os.path.normpath(str(captured.get("executable") or "")))
    return "match" if expected_exe and expected_exe == actual_exe else status


def _can_replace_owner(current: dict[str, Any] | None, *, owner: str, pid: int, identity: dict[str, Any]) -> bool:
    if current is None:
        return True
    if current.get("owner") == owner and int(current.get("pid") or 0) == int(pid):
        if not _has_complete_identity(current) or _identities_align(current, identity):
            return True
    if not is_pid_alive(int(current.get("pid") or 0)):
        return True
    status = _identity_status(current)
    if status == "unknown":
        return False
    return status in {"dead", "mismatch"}


def _identities_align(current: dict[str, Any], identity: dict[str, Any]) -> bool:
    try:
        same_pid = int(current.get("pid") or 0) == int(identity.get("pid") or 0)
        same_time = abs(float(current.get("createTime") or 0) - float(identity.get("createTime") or 0)) <= CREATE_TIME_TOLERANCE_SECONDS
    except (TypeError, ValueError):
        return False
    current_exe = os.path.normcase(os.path.normpath(str(current.get("executable") or "")))
    identity_exe = os.path.normcase(os.path.normpath(str(identity.get("executable") or "")))
    return bool(same_pid and same_time and current_exe and current_exe == identity_exe)


def _capture_identity(pid: int) -> dict[str, Any]:
    from core.runtime_manager.process_identity import capture_process_identity

    captured = capture_process_identity(int(pid))
    return captured if captured else {"pid": int(pid)}


def write_desktop_shell_owner(
    project_root: Path,
    *,
    owner: DesktopShellOwnerKind,
    pid: int,
) -> dict[str, Any] | None:
    path = canonical_desktop_shell_owner_path(project_root)
    if path is None:
        return None
    identity = _capture_identity(pid)
    current = read_desktop_shell_owner(project_root)
    if not _can_replace_owner(current, owner=owner, pid=int(pid), identity=identity):
        return current
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "owner": owner,
        "pid": int(pid),
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if float(identity.get("createTime") or 0) > 0:
        record["createTime"] = float(identity["createTime"])
    if str(identity.get("executable") or "").strip():
        record["executable"] = str(identity["executable"]).strip()
    from core.infrastructure.atomic_io import atomic_write_json

    atomic_write_json(path, record)
    checkout = checkout_desktop_shell_owner_path(project_root)
    if checkout != path:
        try:
            checkout.unlink()
        except OSError:
            pass
    return record


def clear_desktop_shell_owner(
    project_root: Path,
    *,
    owner: DesktopShellOwnerKind,
    pid: int,
) -> None:
    current = read_desktop_shell_owner(project_root)
    if current is None or current.get("owner") != owner or int(current.get("pid") or 0) != int(pid):
        return
    identity = _capture_identity(pid)
    if _has_complete_identity(current) and not _identities_align(current, identity):
        return
    for path in (canonical_desktop_shell_owner_path(project_root), checkout_desktop_shell_owner_path(project_root)):
        if path is None:
            continue
        try:
            path.unlink()
        except OSError:
            continue


def electron_owns_desktop_tray(project_root: Path) -> bool:
    current = read_desktop_shell_owner(project_root)
    if current is None or current["owner"] != "electron":
        return False
    status = _identity_status(current)
    if status == "match":
        return True
    if status == "unknown":
        return is_pid_alive(int(current["pid"]))
    return False


def should_show_winforms_tray(project_root: Path) -> bool:
    return not electron_owns_desktop_tray(project_root)
