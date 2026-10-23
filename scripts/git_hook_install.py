"""Install a shared, versioned ref guard without changing task-local hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


def snapshot_files(source_root: Path) -> dict[str, bytes]:
    reference = (source_root / ".githooks/reference-transaction").read_text(encoding="utf-8")
    old_target = '"$repo_root/scripts/git_claim_guard.py"'
    if reference.count(old_target) != 1:
        raise RuntimeError("unsupported_reference_hook_template")
    reference = reference.replace(
        "set -eu\n", 'set -eu\nruntime_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n', 1
    ).replace(old_target, '"$runtime_root/scripts/git_claim_guard.py"')
    files = {
        "scripts/__init__.py": b"",
        "scripts/git_claim_guard.py": (source_root / "scripts/git_claim_guard.py").read_bytes(),
        "scripts/claim_dormancy.py": (source_root / "scripts/claim_dormancy.py").read_bytes(),
        "hooks/reference-transaction": reference.encode("utf-8"),
    }
    for name in ("pre-commit", "commit-msg", "pre-push", "post-merge"):
        # exec preserves the checkout hook's shebang, stdin, arguments and exit status.
        files[f"hooks/{name}"] = (
            '#!/bin/sh\nset -eu\nrepo_root=$(git rev-parse --show-toplevel)\n'
            f'hook="$repo_root/.githooks/{name}"\n'
            '[ -f "$hook" ] || exit 0\nexec "$hook" "$@"\n'
        ).encode("utf-8")
    return files


def expected_installation(root: Path, source_root: Path = SOURCE_ROOT) -> tuple[Path, dict[str, bytes]]:
    files = snapshot_files(source_root)
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + data + b"\0")
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common / "vibelution-cache/git-hooks" / digest.hexdigest()[:24], files


def _matches(directory: Path, files: dict[str, bytes]) -> bool:
    try:
        return all(
            (directory / name).read_bytes() == data
            and (os.name == "nt" or not name.startswith("hooks/") or (directory / name).stat().st_mode & 0o111)
            for name, data in files.items()
        )
    except OSError:
        return False


def _write_atomic(path: Path, data: bytes, *, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.chmod(0o755 if executable else 0o644)
        try:
            os.replace(temporary, path)
        except PermissionError:
            # Another installer may have published this identical file while
            # Windows still holds its read handle; never overwrite different data.
            if not path.is_file() or path.read_bytes() != data:
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_hooks(root: Path, source_root: Path = SOURCE_ROOT) -> Path:
    directory, files = expected_installation(root, source_root)
    for name, data in files.items():
        path = directory / name
        if not _matches(directory, {name: data}):
            _write_atomic(path, data, executable=name.startswith("hooks/"))
    if not _matches(directory, files):
        raise RuntimeError("shared_hook_snapshot_incomplete")
    hooks = directory / "hooks"
    # Only publish a complete snapshot. All worktrees in this repository share it.
    for attempt in range(5):
        try:
            _git(root, "config", "--local", "core.hooksPath", hooks.as_posix())
            break
        except subprocess.CalledProcessError as error:
            if attempt == 4 or "could not lock config file" not in (error.stderr or "").lower():
                raise
            time.sleep(0.02)
    if _git(root, "config", "--get", "core.hooksPath") != hooks.as_posix():
        raise RuntimeError("shared_hook_configuration_overridden")
    return hooks


def check_installation(root: Path, source_root: Path = SOURCE_ROOT) -> dict[str, object]:
    directory, files = expected_installation(root, source_root)
    try:
        configured = _git(root, "config", "--get", "core.hooksPath")
    except subprocess.CalledProcessError:
        configured = ""
    expected = (directory / "hooks").as_posix()
    return {
        "ok": configured == expected and _matches(directory, files),
        "expected": expected, "configured": configured,
        "repair": "python scripts/git_hook_install.py",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        install_hooks(args.project)
    result = check_installation(args.project)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
