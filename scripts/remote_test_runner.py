#!/usr/bin/env python3
"""Run Vibelution tests on an SSH-accessible Linux worker.

The runner intentionally avoids a local rsync dependency. It creates a bounded
source archive, uploads it through scp, prepares a remote virtualenv, runs the
requested test command, and copies the remote log back as an artifact.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "bossai-server-b"
DEFAULT_REMOTE_ROOT = "/home/enrigin/Vibelution-test"
DEFAULT_WORKERS = 8

EXCLUDED_NAMES = {
    ".git",
    ".cache",
    ".coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "target",
}
EXCLUDED_SUFFIXES = {".db", ".key", ".log", ".p12", ".pem", ".pyc", ".pyo", ".sqlite"}


@dataclass(frozen=True)
class RemoteTestConfig:
    host: str
    remote_root: str
    workers: int
    suite: str
    remote_command: str | None
    no_install: bool
    dry_run: bool
    local_artifacts_dir: Path


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def should_include(relative_path: Path) -> bool:
    """Return whether a project-relative path should be included in the upload."""
    parts = set(relative_path.parts)
    if parts & EXCLUDED_NAMES:
        return False
    name = relative_path.name
    if name == ".env" or name.startswith(".env."):
        return False
    if relative_path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def iter_archive_members(project_root: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(project_root):
        root_path = Path(root)
        relative_root = root_path.relative_to(project_root)
        dirs[:] = sorted(name for name in dirs if should_include(relative_root / name))
        for filename in sorted(files):
            path = root_path / filename
            relative = path.relative_to(project_root)
            if should_include(relative):
                yield path


def create_source_archive(project_root: Path, archive_path: Path) -> int:
    """Create a gzipped tar archive and return the number of included files."""
    file_count = 0
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in iter_archive_members(project_root):
            if path.is_dir():
                continue
            relative = path.relative_to(project_root)
            archive.add(path, arcname=relative.as_posix(), recursive=False)
            file_count += 1
    return file_count


def build_test_command(config: RemoteTestConfig) -> str:
    if config.remote_command:
        return config.remote_command
    if config.suite == "environment-smoke":
        return "python tests/test_runner.py --environment-smoke"
    if config.suite == "parallel":
        return f"python tests/test_runner.py --parallel --workers {config.workers}"
    if config.suite == "hybrid":
        return f"python tests/test_runner.py --hybrid --workers {config.workers}"
    raise ValueError(f"Unsupported suite: {config.suite}")


def build_remote_script(config: RemoteTestConfig, run_id: str) -> str:
    remote_root = shlex.quote(config.remote_root)
    remote_source = shlex.quote(f"{config.remote_root}/runs/{run_id}/source")
    remote_artifacts = shlex.quote(f"{config.remote_root}/runs/{run_id}/artifacts")
    remote_archive = shlex.quote(f"{config.remote_root}/runs/{run_id}/source.tar.gz")
    test_command = build_test_command(config)

    setup_lines = [
        "set -euo pipefail",
        f"REMOTE_ROOT={remote_root}",
        f"REMOTE_SOURCE={remote_source}",
        f"REMOTE_ARTIFACTS={remote_artifacts}",
        f"REMOTE_ARCHIVE={remote_archive}",
        'CACHE_ROOT="$REMOTE_ROOT/cache"',
        'PY_VERSION="$(python3 -c \'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")\')"',
        'VENV="$CACHE_ROOT/venv-py${PY_VERSION}"',
        'mkdir -p "$REMOTE_SOURCE" "$REMOTE_ARTIFACTS" "$CACHE_ROOT"',
        'exec > >(tee "$REMOTE_ARTIFACTS/remote-test.log") 2>&1',
        'tar -xzf "$REMOTE_ARCHIVE" -C "$REMOTE_SOURCE"',
        'cd "$REMOTE_SOURCE"',
        'if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi',
        '. "$VENV/bin/activate"',
    ]
    if not config.no_install:
        setup_lines.extend(
            [
                'REQ_MARKER="$VENV/.vibelution-requirements.sha256"',
                "if [ -f requirements.txt ]; then",
                "  REQ_HASH=\"$(python -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path(\"requirements.txt\").read_bytes()).hexdigest())')\"",
                '  if [ ! -f "$REQ_MARKER" ] || [ "$(cat "$REQ_MARKER")" != "$REQ_HASH" ]; then',
                "    python -m pip install --upgrade pip",
                "    python -m pip install -r requirements.txt",
                '    printf "%s" "$REQ_HASH" > "$REQ_MARKER"',
                "  fi",
                "fi",
            ]
        )
    setup_lines.extend(
        [
            f"echo remote_root={remote_root}",
            f"echo run_id={shlex.quote(run_id)}",
            f"echo command={shlex.quote(test_command)}",
            f"({test_command})",
        ]
    )
    return "\n".join(setup_lines)


def command_to_display(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


class CommandFailed(RuntimeError):
    def __init__(self, command: Sequence[str], returncode: int):
        super().__init__(f"Command failed with exit code {returncode}: {command_to_display(command)}")
        self.command = list(command)
        self.returncode = returncode


class RemoteTestRunner:
    def __init__(
        self,
        config: RemoteTestConfig,
        *,
        project_root: Path = PROJECT_ROOT,
        run: Callable[[Sequence[str]], int] | None = None,
    ) -> None:
        self.config = config
        self.project_root = project_root
        self._run = run or self._subprocess_run

    def _subprocess_run(self, command: Sequence[str]) -> int:
        completed = subprocess.run(command, cwd=str(self.project_root), check=False)
        return completed.returncode

    def _execute(self, command: Sequence[str]) -> None:
        returncode = self._run_command(command)
        if returncode != 0:
            raise CommandFailed(command, returncode)

    def _run_command(self, command: Sequence[str]) -> int:
        print(command_to_display(command))
        if self.config.dry_run:
            return 0
        return self._run(command)

    def run(self) -> int:
        run_id = utc_run_id()
        local_artifacts = self.config.local_artifacts_dir / run_id
        local_artifacts.mkdir(parents=True, exist_ok=True)
        remote_run_root = f"{self.config.remote_root}/runs/{run_id}"
        remote_archive = f"{remote_run_root}/source.tar.gz"
        remote_test_command = ["ssh", self.config.host, f"bash -lc {shlex.quote(build_remote_script(self.config, run_id))}"]
        remote_test_returncode: int | None = None

        with tempfile.TemporaryDirectory(prefix="vibelution-remote-test-") as tmp:
            archive_path = Path(tmp) / "source.tar.gz"
            file_count = create_source_archive(self.project_root, archive_path)
            print(f"archive={archive_path} files={file_count}")

            self._execute(["ssh", self.config.host, f"mkdir -p {shlex.quote(remote_run_root)}"])
            self._execute(["scp", str(archive_path), f"{self.config.host}:{remote_archive}"])
            remote_test_returncode = self._run_command(remote_test_command)
            artifact_command = ["scp", "-r", f"{self.config.host}:{remote_run_root}/artifacts/.", str(local_artifacts)]
            artifact_returncode = self._run_command(artifact_command)
            if artifact_returncode != 0 and remote_test_returncode == 0:
                raise CommandFailed(artifact_command, artifact_returncode)
            if remote_test_returncode != 0:
                raise CommandFailed(remote_test_command, remote_test_returncode)

        print(f"artifacts={local_artifacts}")
        return 0


def parse_args(argv: Sequence[str]) -> RemoteTestConfig:
    parser = argparse.ArgumentParser(description="Run Vibelution tests on a remote Linux SSH worker.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"SSH host alias, default: {DEFAULT_HOST}")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT, help=f"Remote workspace root, default: {DEFAULT_REMOTE_ROOT}")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"pytest worker count, default: {DEFAULT_WORKERS}")
    parser.add_argument(
        "--suite",
        choices=("environment-smoke", "parallel", "hybrid"),
        default="parallel",
        help="Built-in test suite to run when --remote-command is not provided.",
    )
    parser.add_argument("--remote-command", help="Custom command to run in the remote source directory.")
    parser.add_argument("--no-install", action="store_true", help="Skip remote pip install step.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned ssh/scp commands without executing them.")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=PROJECT_ROOT / "logs" / "remote_test_runs",
        help="Local directory for copied remote artifacts.",
    )
    args = parser.parse_args(argv)

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if not shutil.which("ssh"):
        parser.error("ssh executable was not found on PATH")
    if not shutil.which("scp"):
        parser.error("scp executable was not found on PATH")

    return RemoteTestConfig(
        host=args.host,
        remote_root=args.remote_root.rstrip("/"),
        workers=args.workers,
        suite=args.suite,
        remote_command=args.remote_command,
        no_install=args.no_install,
        dry_run=args.dry_run,
        local_artifacts_dir=args.artifacts_dir,
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return RemoteTestRunner(config).run()
    except CommandFailed as exc:
        print(str(exc), file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
