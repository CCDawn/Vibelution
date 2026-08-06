from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Sequence

from core.infrastructure import no_console_git

DEFAULT_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_GIT_LOCK_RETRIES = 2


def resolve_git_executable() -> str:
    """Resolve a Git executable that can run without the Git for Windows cmd wrapper."""

    return no_console_git.resolve_git_executable()


def git_command(args: Sequence[str]) -> list[str]:
    return [resolve_git_executable(), *[str(arg) for arg in args]]


def no_console_subprocess_kwargs() -> dict[str, Any]:
    return no_console_git.no_console_subprocess_kwargs()


def run_git(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = DEFAULT_GIT_TIMEOUT_SECONDS,
    check: bool = False,
    retries: int = DEFAULT_GIT_LOCK_RETRIES,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    run_kwargs = dict(kwargs)
    # Always force no-console kwargs last so callers cannot strip CREATE_NO_WINDOW.
    run_kwargs.update(no_console_subprocess_kwargs())
    env = dict(run_kwargs.pop("env", None) or os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")
    env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    env.setdefault("GIT_PAGER", "cat")
    run_kwargs["env"] = env
    if "stdin" not in run_kwargs:
        run_kwargs["stdin"] = subprocess.DEVNULL
    command = git_command(args)
    attempts = max(0, int(retries or 0)) + 1
    for attempt in range(attempts):
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
            check=False,
            **run_kwargs,
        )
        if result.returncode != 0 and _is_git_lock_contention(result) and attempt < attempts - 1:
            time.sleep(0.2 * (attempt + 1))
            continue
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result
    raise RuntimeError("run_git retry loop exhausted unexpectedly")


def _is_git_lock_contention(result: subprocess.CompletedProcess[Any]) -> bool:
    text = " ".join(
        part
        for part in (
            _process_output_text(getattr(result, "stderr", "")),
            _process_output_text(getattr(result, "stdout", "")),
        )
        if part
    ).lower()
    return "index.lock" in text or "another git process" in text


def _process_output_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)
