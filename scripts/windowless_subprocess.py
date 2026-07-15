"""Shared Windows subprocess policy for console-free project automation."""

from __future__ import annotations

import os
import subprocess
from typing import Any


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
