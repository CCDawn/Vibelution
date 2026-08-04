"""Cross-platform sandbox process start and termination without console shells."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any

from core.infrastructure.codex_sandbox.platform import host_platform
from core.runtime_manager.process_inventory import terminate_process_descendants
from scripts.windowless_subprocess import no_window_subprocess_kwargs


def sandbox_popen_kwargs(*, platform: str | None = None) -> dict[str, Any]:
    """Popen kwargs: no visible console on Windows, own process group on POSIX."""
    system = (platform or host_platform()).lower()
    kwargs = dict(no_window_subprocess_kwargs())
    if system != "windows":
        kwargs["start_new_session"] = True
    return kwargs


def terminate_process_tree(process: Any, *, platform: str | None = None) -> None:
    """Terminate a sandbox process and its children for the current host."""
    system = (platform or host_platform()).lower()
    if process.poll() is not None:
        return
    if system == "windows":
        _terminate_windows_tree(process)
    else:
        _terminate_posix_tree(process)


def _terminate_windows_tree(process: Any) -> None:
    pid = int(getattr(process, "pid", 0) or 0)
    if pid > 0:
        terminate_process_descendants(pid, timeout_seconds=1.0)
    try:
        process.terminate()
    except (AttributeError, OSError):
        pass
    try:
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except (AttributeError, OSError):
            pass


def _terminate_posix_tree(process: Any) -> None:
    pid = int(getattr(process, "pid", 0) or 0)
    if pid > 0:
        try:
            from core.runtime_manager.process_inventory import (
                terminate_process_descendants,
            )

            terminate_process_descendants(pid, timeout_seconds=1.0)
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
