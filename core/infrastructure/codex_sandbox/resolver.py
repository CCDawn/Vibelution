"""Codex CLI executable resolution for the cross-platform sandbox.

Resolution order:
1. explicit ``VIBELUTION_CODEX_PATH`` (an invalid explicit path fails closed);
2. Windows OpenAI local install directory (``%LOCALAPPDATA%\\OpenAI\\Codex\\bin``);
3. ``PATH`` lookup of ``codex.exe`` on Windows / ``codex`` on POSIX.

Returns a native file path or ``""`` when missing so callers fail closed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from core.infrastructure.codex_sandbox.platform import host_platform


CODEX_PATH_ENV = "VIBELUTION_CODEX_PATH"
_WINDOWS_BIN_RELATIVE = Path("OpenAI") / "Codex" / "bin"


def resolve_codex_executable(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> str:
    """Resolve a native Codex executable without shell wrappers or cmd shims."""
    system = (platform or host_platform()).lower()
    env = environ if environ is not None else os.environ
    lookup = which if which is not None else shutil.which

    explicit = str(env.get(CODEX_PATH_ENV) or "").strip()
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate.resolve())
        return ""

    if system == "windows":
        local_bin = Path(str(env.get("LOCALAPPDATA") or "").strip()) / _WINDOWS_BIN_RELATIVE
        if local_bin.is_dir():
            try:
                candidates = sorted(
                    local_bin.glob("*/codex.exe"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                candidates = []
            if candidates:
                return str(candidates[0].resolve())
        resolved = lookup("codex.exe")
    else:
        resolved = lookup("codex")

    if resolved and Path(resolved).is_file():
        return str(Path(resolved).resolve())
    return ""
