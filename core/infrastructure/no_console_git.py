"""Resolve and run Git without visible console flash on Windows.

Prefer Git for Windows *mingw64* ``git.exe`` over the small ``Git\\cmd\\git.exe``
and ``Git\\bin\\git.exe`` trampolines (they allocate a console host flash).
All waitable probes use CREATE_NO_WINDOW only (AGENTS.md / development-standard §8.0).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Sequence

# Real mingw64 git.exe is multi-MB; cmd/bin wrappers are ~45KB.
_MIN_REAL_GIT_BYTES = 200_000


def _is_windows() -> bool:
    return os.name == "nt"


def _is_real_git_binary(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > _MIN_REAL_GIT_BYTES
    except OSError:
        return False


def _mingw_candidates_from_install_root(install_root: Path) -> list[Path]:
    return [
        install_root / "mingw64" / "bin" / "git.exe",
        install_root / "mingw64" / "libexec" / "git-core" / "git.exe",
    ]


def _install_root_from_wrapper(path: Path) -> Path | None:
    """Map Git\\cmd\\git.exe or Git\\bin\\git.exe -> Git install root."""

    name = path.name.lower()
    if name not in {"git", "git.exe"}:
        return None
    parent = path.parent
    if parent.name.lower() in {"cmd", "bin"}:
        return parent.parent
    if parent.name.lower() == "git-core" and parent.parent.name.lower() == "libexec":
        # .../mingw64/libexec/git-core/git.exe
        return parent.parent.parent.parent
    if parent.name.lower() == "bin" and parent.parent.name.lower() == "mingw64":
        return parent.parent.parent
    return None


@lru_cache(maxsize=1)
def resolve_git_executable() -> str:
    if _is_windows():
        preferred: list[Path] = []
        # Prefer env roots only (no hardcoded Program Files) so tests can isolate
        # and machines without Git still fall through to shutil.which rewrite.
        program_files = [
            root
            for root in (
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramW6432"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("LocalAppData"),
            )
            if root
        ]
        for root in program_files:
            base = Path(root)
            # Standard: ProgramFiles/Git/...
            preferred.extend(_mingw_candidates_from_install_root(base / "Git"))
            # Some layouts: LocalAppData/Programs/Git/...
            preferred.extend(_mingw_candidates_from_install_root(base / "Programs" / "Git"))
            # Test/mock layout: ProgramFiles env points at a fake Git root
            # containing mingw64/bin directly (no extra Git/ segment).
            preferred.extend(_mingw_candidates_from_install_root(base))

        for candidate in preferred:
            if _is_real_git_binary(candidate):
                try:
                    return str(candidate.resolve())
                except OSError:
                    return str(candidate)

        which_names = ("git.exe", "git")
        for name in which_names:
            which_exe = shutil.which(name)
            if not which_exe:
                continue
            path = Path(which_exe)
            if _is_real_git_binary(path):
                try:
                    return str(path.resolve())
                except OSError:
                    return str(path)
            install_root = _install_root_from_wrapper(path)
            if install_root is not None:
                for candidate in _mingw_candidates_from_install_root(install_root):
                    if _is_real_git_binary(candidate):
                        try:
                            return str(candidate.resolve())
                        except OSError:
                            return str(candidate)
            # Last resort: still return which (better than bare "git"),
            # but run_git will keep CREATE_NO_WINDOW.
            return which_exe

    return shutil.which("git") or "git"


def clear_git_executable_cache() -> None:
    resolve_git_executable.cache_clear()


def _creation_flags_waitable() -> int:
    if not _is_windows():
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if not _is_windows() or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def no_console_subprocess_kwargs() -> dict:
    """Kwargs for waitable, windowless subprocesses on Windows."""

    if not _is_windows():
        return {}
    kwargs: dict = {
        "creationflags": _creation_flags_waitable(),
    }
    startupinfo = _hidden_startupinfo()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _git_install_root(git_exe: str) -> Path | None:
    try:
        path = Path(git_exe).resolve()
    except OSError:
        path = Path(git_exe)
    # .../mingw64/bin/git.exe -> Git root
    if path.parent.name.lower() == "bin" and path.parent.parent.name.lower() == "mingw64":
        return path.parent.parent.parent
    root = _install_root_from_wrapper(path)
    return root


def _no_op_editor(git_exe: str) -> str:
    """Editor that never allocates a visible console (overrides cmd.exe-based GIT_EDITOR)."""

    root = _git_install_root(git_exe)
    if root is not None:
        true_exe = root / "usr" / "bin" / "true.exe"
        if true_exe.is_file():
            return str(true_exe)
    # Last resort: builtin no-op accepted by Git for Windows.
    return ":"


def apply_no_console_git_env(env: dict | None = None, *, git_exe: str | None = None) -> dict:
    """Force non-interactive, no-pager, no-editor env for product Git.

    Uses assignment (not setdefault): empty-string or cmd.exe-based values in the
    process environment otherwise keep flashing consoles (e.g. GIT_EDITOR=cmd.exe).
    """

    merged = dict(env or os.environ)
    exe = str(git_exe or resolve_git_executable())
    editor = _no_op_editor(exe)
    # Overwrite — never leave empty GIT_PAGER / interactive GCM / cmd GIT_EDITOR.
    merged["GIT_TERMINAL_PROMPT"] = "0"
    merged["GCM_INTERACTIVE"] = "never"
    merged["GIT_OPTIONAL_LOCKS"] = "0"
    merged["GIT_PAGER"] = "cat"
    merged["PAGER"] = "cat"
    merged["TERM"] = "dumb"
    merged["GIT_EDITOR"] = editor
    merged["EDITOR"] = editor
    merged["VISUAL"] = editor
    # Avoid less.exe / more.com when a helper ignores GIT_PAGER.
    merged["LESS"] = "FRX"
    merged["LV"] = "-c"
    return merged


def run_git(
    args: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float = 15.0,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` with no console window on Windows."""

    git_exe = resolve_git_executable()
    env = apply_no_console_git_env(env=env, git_exe=git_exe)
    kwargs = no_console_subprocess_kwargs()
    return subprocess.run(
        [git_exe, *list(args)],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
        **kwargs,
    )
