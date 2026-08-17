"""Shared Windows subprocess policy for console-free project automation."""

from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NEW_PROCESS_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))


def no_window_subprocess_kwargs(*, creationflags: int = 0) -> dict[str, Any]:
    """Return waitable subprocess kwargs that never allocate a visible console."""

    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    flags = int(creationflags or 0) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if flags:
        kwargs["creationflags"] = flags

    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        kwargs["startupinfo"] = startupinfo
    return kwargs


def detached_no_console_popen_kwargs() -> dict[str, Any]:
    """Return Popen kwargs for a child that must outlive a short-lived parent CLI.

    Windows: DETACHED_PROCESS ignores CREATE_NO_WINDOW; keep hidden STARTUPINFO
    and break away from the parent's job so JSON CLI exit cannot reap the tree.
    """

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
        return kwargs
    kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        kwargs["startupinfo"] = startupinfo
    return kwargs
