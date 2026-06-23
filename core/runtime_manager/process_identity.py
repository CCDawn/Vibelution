"""Runtime Manager process identity checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def command_line_text(parts: Any) -> str:
    if isinstance(parts, str):
        return parts
    if isinstance(parts, (list, tuple)):
        return " ".join(str(part) for part in parts if part is not None)
    return ""


def runtime_manager_command_line_for_pid(pid: int) -> str:
    if int(pid or 0) <= 0:
        return ""
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            process = psutil.Process(int(pid))
            return command_line_text(process.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    proc_cmdline_path = Path("/proc") / str(int(pid)) / "cmdline"
    try:
        return proc_cmdline_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def command_line_is_runtime_manager_daemon(command_line: str) -> bool:
    normalized = str(command_line or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return (
        ("core.runtime_manager.cli" in normalized or "core/runtime_manager/cli.py" in normalized)
        and "daemon" in normalized.split()
    )


def is_runtime_manager_process(pid: int) -> bool:
    return command_line_is_runtime_manager_daemon(runtime_manager_command_line_for_pid(int(pid or 0)))
