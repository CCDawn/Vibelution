"""Product desktop tray owner lock.

Electron is the product shell owner. Native WinForms yields its NotifyIcon when
an alive Electron pid holds this file. Schema is duplicated in
desktop/electron/src/tray/desktopShellOwner.ts and VibelutionLauncher.cs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

OWNER_RELATIVE_PATH = Path(".runtime") / "launcher" / "desktop_shell_owner.json"
SCHEMA_VERSION = 1
DesktopShellOwnerKind = Literal["electron", "winforms"]


def desktop_shell_owner_path(project_root: Path) -> Path:
    return Path(project_root) / OWNER_RELATIVE_PATH


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


def read_desktop_shell_owner(project_root: Path) -> dict[str, Any] | None:
    path = desktop_shell_owner_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    owner = str(payload.get("owner") or "").strip()
    pid = int(payload.get("pid") or 0)
    if owner not in {"electron", "winforms"} or pid <= 0:
        return None
    return {
        "schemaVersion": int(payload.get("schemaVersion") or SCHEMA_VERSION),
        "owner": owner,
        "pid": pid,
    }


def write_desktop_shell_owner(
    project_root: Path,
    *,
    owner: DesktopShellOwnerKind,
    pid: int,
) -> dict[str, Any]:
    path = desktop_shell_owner_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "owner": owner,
        "pid": int(pid),
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def clear_desktop_shell_owner(
    project_root: Path,
    *,
    owner: DesktopShellOwnerKind,
    pid: int,
) -> None:
    current = read_desktop_shell_owner(project_root)
    if current is None:
        return
    if current["owner"] != owner or int(current["pid"]) != int(pid):
        return
    path = desktop_shell_owner_path(project_root)
    try:
        path.unlink()
    except OSError:
        return


def electron_owns_desktop_tray(project_root: Path) -> bool:
    current = read_desktop_shell_owner(project_root)
    if current is None or current["owner"] != "electron":
        return False
    return is_pid_alive(int(current["pid"]))


def should_show_winforms_tray(project_root: Path) -> bool:
    return not electron_owns_desktop_tray(project_root)
