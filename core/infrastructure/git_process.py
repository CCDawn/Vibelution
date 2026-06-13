from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence


@lru_cache(maxsize=1)
def resolve_git_executable() -> str:
    """Resolve a Git executable that can run without the Git for Windows cmd wrapper."""

    discovered = shutil.which("git")
    candidates: list[Path] = []
    if discovered:
        discovered_path = Path(discovered)
        candidates.extend(_direct_git_candidates(discovered_path))
        candidates.append(discovered_path)

    if os.name == "nt":
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
    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if flags:
        kwargs["creationflags"] = flags

    startupinfo = _hidden_startup_info()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def run_git(args: Sequence[str], *, cwd: str | os.PathLike[str] | None = None, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    run_kwargs = dict(kwargs)
    run_kwargs.update(no_console_subprocess_kwargs())
    return subprocess.run(
        git_command(args),
        cwd=str(cwd) if cwd is not None else None,
        **run_kwargs,
    )


def _direct_git_candidates(discovered_path: Path) -> list[Path]:
    if os.name != "nt":
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
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path).lower() if os.name == "nt" else str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped
