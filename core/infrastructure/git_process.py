from __future__ import annotations

import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence


DEFAULT_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_GIT_LOCK_RETRIES = 2


def _is_windows_platform() -> bool:
    return os.name == "nt"


@lru_cache(maxsize=1)
def resolve_git_executable() -> str:
    """Resolve a Git executable that can run without the Git for Windows cmd wrapper."""

    discovered = shutil.which("git")
    candidates: list[Path] = []
    if discovered:
        discovered_path = Path(discovered)
        candidates.extend(_direct_git_candidates(discovered_path))
        candidates.append(discovered_path)

    if _is_windows_platform():
        for root_env in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
            root = os.environ.get(root_env)
            if not root:
                continue
            root_path = Path(root)
            candidates.extend(
                [
                    root_path / "Git" / "mingw64" / "bin" / "git.exe",
                    root_path / "Git" / "bin" / "git.exe",
                    root_path / "Programs" / "Git" / "mingw64" / "bin" / "git.exe",
                    root_path / "Programs" / "Git" / "bin" / "git.exe",
                ]
            )

    for candidate in _dedupe_paths(candidates):
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return discovered or "git"


def git_command(args: Sequence[str]) -> list[str]:
    return [resolve_git_executable(), *[str(arg) for arg in args]]


def no_console_subprocess_kwargs() -> dict[str, Any]:
    if not _is_windows_platform():
        return {}

    kwargs: dict[str, Any] = {}
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if flags:
        kwargs["creationflags"] = flags

    startupinfo = _hidden_startup_info()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


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
    run_kwargs.update(no_console_subprocess_kwargs())
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


def _direct_git_candidates(discovered_path: Path) -> list[Path]:
    if not _is_windows_platform():
        return []

    path = discovered_path
    if path.name.lower() != "git.exe":
        return []

    candidates: list[Path] = []
    if path.parent.name.lower() == "cmd":
        install_root = path.parent.parent
        candidates.extend(
            [
                install_root / "mingw64" / "bin" / "git.exe",
                install_root / "bin" / "git.exe",
            ]
        )
    return candidates


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if not _is_windows_platform() or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path).lower() if _is_windows_platform() else str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped
