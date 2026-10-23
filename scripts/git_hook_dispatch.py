"""Run a checkout's hook with the shared claim guard after a history rewrite."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _shell() -> str:
    found = shutil.which("sh")
    if found:
        return found
    git = shutil.which("git")
    candidate = Path(git).parent.parent / "bin/sh.exe" if git else Path("")
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("git_hook_shell_missing")


def dispatch(root: Path, runtime: Path, arguments: list[str]) -> int:
    hook = root / ".githooks/pre-commit"
    if not hook.is_file():
        return 0
    data = hook.read_bytes()
    token = b'"$repo_root/scripts/git_claim_guard.py"'
    if token not in data:
        # A custom hook keeps its original interpreter, arguments and stdin.
        return subprocess.run([_shell(), "-c", 'exec "$@"', "vibelution-hook", str(hook), *arguments], cwd=root, check=False).returncode
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
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        return subprocess.run([_shell(), str(temporary), *arguments], cwd=root, check=False, **kwargs).returncode
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    return dispatch(root, Path(__file__).resolve().parents[1], sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
