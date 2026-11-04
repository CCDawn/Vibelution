"""Run a checkout's hook with the shared claim guard after a history rewrite."""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TextIO


@functools.lru_cache(maxsize=1)
def _resolve_git_executable() -> str:
    """Resolve a real git.exe, avoiding console-allocating cmd/bin trampolines.

    Minimal in-place equivalent of
    core.infrastructure.no_console_git.resolve_git_executable: this script also
    runs from the self-contained hook cache snapshot without the core package.
    """

    found = shutil.which("git")
    if not found:
        return "git"
    if os.name != "nt":
        return found
    path = Path(found)
    if path.parent.name.lower() in {"cmd", "bin"}:
        mingw = path.parent.parent / "mingw64" / "bin" / "git.exe"
        if mingw.is_file():
            return str(mingw)
    return found


def _no_window_kwargs() -> dict[str, object]:
    """Subprocess kwargs that never allocate a visible console (development-standard 8.0)."""

    if os.name != "nt":
        return {}
    kwargs: dict[str, object] = {
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    }
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _shell() -> str:
    found = shutil.which("sh")
    if found:
        return found
    git = shutil.which("git")
    candidate = Path(git).parent.parent / "bin/sh.exe" if git else Path("")
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("git_hook_shell_missing")


def _echo_raw(stream: TextIO, payload: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(payload.decode("utf-8", errors="replace"))
    else:
        buffer.write(payload)
    stream.flush()


def _run_hook_with_passthrough(command: list[str], root: Path) -> int:
    """Run a hook body without a console window while preserving its streams.

    On Windows, a console-subsystem child spawned with CREATE_NO_WINDOW and
    non-redirected stdout/stderr loses those handles (observed with MSYS2 sh:
    exit code and side effects survive while printed output vanishes), so
    stdout/stderr are captured on fresh pipes and echoed back to the real
    streams. stdin stays inherited so a custom hook still reads the caller's
    input.
    """

    if os.name == "nt":
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            check=False,
            **_no_window_kwargs(),
        )
        _echo_raw(sys.stdout, completed.stdout)
        _echo_raw(sys.stderr, completed.stderr)
        return completed.returncode
    return subprocess.run(command, cwd=root, check=False, **_no_window_kwargs()).returncode


def dispatch(root: Path, runtime: Path, arguments: list[str]) -> int:
    hook = root / ".githooks/pre-commit"
    if not hook.is_file():
        return 0
    data = hook.read_bytes()
    token = b'"$repo_root/scripts/git_claim_guard.py"'
    if token not in data:
        # A custom hook keeps its original interpreter, arguments and stdin.
        return _run_hook_with_passthrough(
            [_shell(), "-c", 'exec "$@"', "vibelution-hook", str(hook), *arguments], root
        )
    if data.count(token) != 1 or not data.startswith(b"#!/bin/sh"):
        raise RuntimeError("unsupported_checkout_claim_hook")
    # The body remains the owning checkout's hook. Only the claim calculator
    # uses the immutable shared version, without editing the checkout file.
    guard = (runtime / "scripts/git_claim_guard.py").as_posix()
    if any(character in guard for character in ('"', '`', '$', '\n')):
        raise RuntimeError("unsupported_shared_hook_path")
    data = data.replace(token, ('"' + guard + '"').encode("utf-8"))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="vibelution-hook-", suffix=".sh", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        return _run_hook_with_passthrough([_shell(), str(temporary), *arguments], root)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    root = Path(
        subprocess.check_output(
            [_resolve_git_executable(), "rev-parse", "--show-toplevel"],
            text=True,
            **_no_window_kwargs(),
        ).strip()
    )
    return dispatch(root, Path(__file__).resolve().parents[1], sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
