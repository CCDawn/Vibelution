#!/usr/bin/env python3
"""Run Vibelution tests on an SSH-accessible Linux worker.

The runner intentionally avoids a local rsync dependency. It creates a bounded
source archive, uploads it through scp, prepares a remote virtualenv, runs the
requested test command, and copies the remote log back as an artifact.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "bossai-server-b"
DEFAULT_REMOTE_ROOT = "/home/enrigin/Vibelution-test"
DEFAULT_WORKERS = 8
DEFAULT_DISTRIBUTED_REMOTE_WORKERS = 16
DEFAULT_LOCAL_WORKERS = 8
DEFAULT_BACKEND = "venv"
DEFAULT_DOCKER_IMAGE = "vibelution-test"
DEFAULT_APT_MIRROR = "http://mirrors.aliyun.com/debian"
DEFAULT_PIP_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple"
DEFAULT_PIP_TRUSTED_HOST = "mirrors.aliyun.com"
DOCKER_SPEC_VERSION = "git2"
REMOTE_TEST_CONFIG = ".remote-test/config.toml"

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
    local_workers: int
    suite: str
    backend: str
    docker_image: str
    rebuild_image: bool
    remote_command: str | None
    no_install: bool
    distributed: bool
    apt_mirror: str
    pip_index_url: str
    pip_trusted_host: str
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


def create_source_archive(project_root: Path, archive_path: Path, extra_files: dict[str, str] | None = None) -> int:
    """Create a gzipped tar archive and return the number of included files."""
    file_count = 0
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in iter_archive_members(project_root):
            if path.is_dir():
                continue
            relative = path.relative_to(project_root)
            archive.add(path, arcname=relative.as_posix(), recursive=False)
            file_count += 1
        for arcname, content in sorted((extra_files or {}).items()):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            file_count += 1
    return file_count


def discover_test_targets(project_root: Path) -> list[Path]:
    """Return project-relative pytest file targets suitable for distributed runs."""
    test_dir = project_root / "tests"
    return [
        path.relative_to(project_root)
        for path in sorted(test_dir.glob("test_*.py"))
        if path.name != "test_runner.py"
        and not test_file_has_module_serial_marker(path)
    ]


def test_file_has_module_serial_marker(path: Path) -> bool:
    """Return whether a test file is explicitly module-level serial."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            return pytestmark_value_contains_serial(value)
    return False


def pytestmark_value_contains_serial(node: ast.AST) -> bool:
    if _is_pytest_mark_serial(node):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(pytestmark_value_contains_serial(item) for item in node.elts)
    return False


def _is_pytest_mark_serial(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return _is_pytest_mark_serial(node.func)
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "serial"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _target_weight(project_root: Path, target: Path) -> int:
    path = project_root / target
    try:
        return max(1, path.stat().st_size)
    except OSError:
        return 1


def split_targets_by_capacity(
    targets: Sequence[Path],
    *,
    project_root: Path,
    local_workers: int,
    remote_workers: int,
) -> tuple[list[Path], list[Path]]:
    """Split file targets by approximate work while honoring worker capacity."""
    if local_workers < 1 or remote_workers < 1:
        raise ValueError("worker counts must be >= 1")

    buckets = {
        "local": {"workers": local_workers, "weight": 0, "targets": []},
        "remote": {"workers": remote_workers, "weight": 0, "targets": []},
    }
    weighted_targets = sorted(
        ((target, _target_weight(project_root, target)) for target in targets),
        key=lambda item: item[1],
        reverse=True,
    )
    for target, weight in weighted_targets:
        local_load = buckets["local"]["weight"] / buckets["local"]["workers"]
        remote_load = buckets["remote"]["weight"] / buckets["remote"]["workers"]
        if local_load < remote_load:
            bucket_name = "local"
        elif remote_load < local_load:
            bucket_name = "remote"
        else:
            bucket_name = "remote" if remote_workers >= local_workers else "local"
        bucket = buckets[bucket_name]
        bucket["targets"].append(target)
        bucket["weight"] += weight

    if not buckets["remote"]["targets"] and len(buckets["local"]["targets"]) > 1:
        target = buckets["local"]["targets"].pop()
        weight = _target_weight(project_root, target)
        buckets["local"]["weight"] -= weight
        buckets["remote"]["targets"].append(target)
        buckets["remote"]["weight"] += weight
    if not buckets["local"]["targets"] and len(buckets["remote"]["targets"]) > 1:
        target = buckets["remote"]["targets"].pop()
        weight = _target_weight(project_root, target)
        buckets["remote"]["weight"] -= weight
        buckets["local"]["targets"].append(target)
        buckets["local"]["weight"] += weight

    return buckets["local"]["targets"], buckets["remote"]["targets"]


def format_targets_for_command(targets: Sequence[Path]) -> list[str]:
    return [target.as_posix() for target in targets]


def build_distributed_correctness_summary(
    *,
    local_targets: Sequence[Path],
    remote_targets: Sequence[Path],
    local_workers: int,
    remote_workers: int,
) -> str:
    """Describe the correctness scope of the distributed pytest lane."""
    total_targets = len(local_targets) + len(remote_targets)
    return (
        "correctness_scope="
        "python_pytest:not_serial "
        f"targets:{total_targets} "
        f"local_targets:{len(local_targets)} "
        f"remote_targets:{len(remote_targets)} "
        f"workers:{local_workers}+{remote_workers} "
        "excluded:serial_pytest,frontend_vitest,frontend_build "
        "gate_hint:run_serial_and_frontend_for_release_or_matching_changes"
    )


def build_parallel_pytest_command(
    targets: Sequence[Path | str],
    *,
    workers: int,
    python_executable: str,
) -> list[str]:
    target_args = [target.as_posix() if isinstance(target, Path) else target for target in targets]
    return [
        python_executable,
        "-m",
        "pytest",
        *target_args,
        "-q",
        "--tb=short",
        "--no-header",
        "-p",
        "no:warnings",
        "-n",
        str(workers),
        "--dist",
        "loadfile",
        "-m",
        "not serial",
    ]


def build_parallel_pytest_shell_command_from_manifest(
    manifest_path: str,
    *,
    workers: int,
    python_executable: str = "python",
) -> str:
    manifest_expansion = f"$(cat {shlex.quote(manifest_path)})"
    parts = [
        shlex.quote(python_executable),
        "-m",
        "pytest",
        manifest_expansion,
        "-q",
        "--tb=short",
        "--no-header",
        "-p",
        "no:warnings",
        "-n",
        str(workers),
        "--dist",
        "loadfile",
        "-m",
        shlex.quote("not serial"),
    ]
    return " ".join(parts)


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
        f"APT_MIRROR={shlex.quote(config.apt_mirror)}",
        f"PIP_INDEX_URL={shlex.quote(config.pip_index_url)}",
        f"PIP_TRUSTED_HOST={shlex.quote(config.pip_trusted_host)}",
        'PY_VERSION="$(python3 -c \'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")\')"',
        'mkdir -p "$REMOTE_SOURCE" "$REMOTE_ARTIFACTS" "$CACHE_ROOT"',
        'exec > >(tee "$REMOTE_ARTIFACTS/remote-test.log") 2>&1',
        'tar -xzf "$REMOTE_ARCHIVE" -C "$REMOTE_SOURCE"',
        'cd "$REMOTE_SOURCE"',
        'mkdir -p "$REMOTE_SOURCE/.remote-test"',
        'cat > "$REMOTE_SOURCE/' + REMOTE_TEST_CONFIG + '" <<\'EOF_REMOTE_TEST_CONFIG\'',
        "[runtime]",
        'profile = "safe_remote"',
        "preflight_doctor = true",
        "require_venv = true",
        "",
        "[llm.model_library.relay_openai_gpt_5_5]",
        'model = "gpt-5.5"',
        'label = "GPT-5.5 Remote Test"',
        'transport = "responses"',
        'contract = "tool_chat"',
        "strict_compatibility = false",
        "temperature = 0.7",
        "max_output_tokens = 128000",
        "timeout = 120",
        "connect_timeout = 20",
        "streaming = true",
        'tool_calling_mode = "auto"',
        "discovery_enabled = true",
        'api_key_env = "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY"',
        "",
        "[llm.model_library.relay_openai_gpt_5_5.prompt_cache]",
        'mode = "automatic"',
        "",
        "[llm.model_library.relay_openai_gpt_5_5.provider]",
        'kind = "relay"',
        'api_key_env = "OPENAI_API_KEY"',
        'base_url = "https://ai-pixel.online"',
        'compat_mode = "openai"',
        "requires_api_key = true",
        "context_window = 1000000",
        "",
        "[[prompt.sections]]",
        'name = "SOUL"',
        'path = "core/core_prompt/SOUL.md"',
        "priority = 10",
        "required = true",
        'description = "Core identity and external input discipline"',
        "",
        "[[prompt.sections]]",
        'name = "SPEC"',
        'path = "core/core_prompt/SPEC.md"',
        "priority = 20",
        "required = true",
        'description = "Runtime specification"',
        "EOF_REMOTE_TEST_CONFIG",
        'export VIBELUTION_CONFIG_PATH="$REMOTE_SOURCE/' + REMOTE_TEST_CONFIG + '"',
        f"echo remote_root={remote_root}",
        f"echo run_id={shlex.quote(run_id)}",
        f"echo backend={shlex.quote(config.backend)}",
        'echo config_path="$VIBELUTION_CONFIG_PATH"',
        f"echo command={shlex.quote(test_command)}",
        'echo apt_mirror="${APT_MIRROR:-default}"',
        'echo pip_index_url="${PIP_INDEX_URL:-default}"',
    ]
    if config.backend == "docker":
        setup_lines.extend(build_remote_docker_lines(config, test_command))
    else:
        setup_lines.extend(build_remote_venv_lines(config, test_command))
    return "\n".join(setup_lines)


def build_remote_venv_lines(config: RemoteTestConfig, test_command: str) -> list[str]:
    setup_lines = [
        'VENV="$CACHE_ROOT/venv-py${PY_VERSION}"',
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
                '    PIP_ARGS=""',
                '    if [ -n "$PIP_INDEX_URL" ]; then PIP_ARGS="$PIP_ARGS --index-url $PIP_INDEX_URL"; fi',
                '    if [ -n "$PIP_TRUSTED_HOST" ]; then PIP_ARGS="$PIP_ARGS --trusted-host $PIP_TRUSTED_HOST"; fi',
                "    python -m pip install $PIP_ARGS --upgrade pip",
                "    python -m pip install $PIP_ARGS -r requirements.txt",
                '    printf "%s" "$REQ_HASH" > "$REQ_MARKER"',
                "  fi",
                "fi",
            ]
        )
    setup_lines.extend(
        [
            f"({test_command})",
        ]
    )
    return setup_lines


def build_remote_docker_lines(config: RemoteTestConfig, test_command: str) -> list[str]:
    image_base = shlex.quote(config.docker_image)
    rebuild_flag = "1" if config.rebuild_image else "0"
    quoted_command = shlex.quote(test_command)
    return [
        f"DOCKER_IMAGE_BASE={image_base}",
        f"REBUILD_IMAGE={rebuild_flag}",
        f"DOCKER_SPEC_VERSION={shlex.quote(DOCKER_SPEC_VERSION)}",
        "if ! command -v docker >/dev/null 2>&1; then echo 'docker executable not found on remote host' >&2; exit 127; fi",
        "if [ -f requirements.txt ]; then",
        "  REQ_HASH=\"$(python3 -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path(\"requirements.txt\").read_bytes()).hexdigest()[:12])')\"",
        "else",
        "  REQ_HASH=no-requirements",
        "fi",
        'DOCKER_IMAGE="${DOCKER_IMAGE_BASE}:py${PY_VERSION}-${REQ_HASH}-${DOCKER_SPEC_VERSION}"',
        'DOCKER_BUILD_CONTEXT="$CACHE_ROOT/docker-build/py${PY_VERSION}-${REQ_HASH}-${DOCKER_SPEC_VERSION}"',
        'DOCKERFILE="$DOCKER_BUILD_CONTEXT/Dockerfile"',
        'mkdir -p "$DOCKER_BUILD_CONTEXT"',
        'if [ -f requirements.txt ]; then cp requirements.txt "$DOCKER_BUILD_CONTEXT/requirements.txt"; else : > "$DOCKER_BUILD_CONTEXT/requirements.txt"; fi',
        'cat > "$DOCKERFILE" <<\'EOF_DOCKERFILE\'',
        "# syntax=docker/dockerfile:1",
        "FROM python:3.11-slim",
        "ARG APT_MIRROR",
        "ARG PIP_INDEX_URL",
        "ARG PIP_TRUSTED_HOST",
        "ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \\",
        "    PYTHONDONTWRITEBYTECODE=1 \\",
        "    PYTHONUNBUFFERED=1 \\",
        "    NO_PROXY=localhost,127.0.0.1 \\",
        "    no_proxy=localhost,127.0.0.1 \\",
        "    TERM=xterm-256color \\",
        "    COLUMNS=120 \\",
        "    HOME=/tmp/vibelution-home \\",
        "    XDG_CACHE_HOME=/tmp/vibelution-cache",
        "WORKDIR /workspace",
        "COPY requirements.txt /tmp/vibelution-requirements.txt",
        "RUN if [ -n \"$APT_MIRROR\" ]; then \\",
        "      sed -i \"s|http://deb.debian.org/debian|$APT_MIRROR|g; s|https://deb.debian.org/debian|$APT_MIRROR|g\" /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \\",
        "    fi \\",
        "    && if [ -n \"$PIP_INDEX_URL\" ]; then python -m pip config set global.index-url \"$PIP_INDEX_URL\"; fi \\",
        "    && if [ -n \"$PIP_TRUSTED_HOST\" ]; then python -m pip config set global.trusted-host \"$PIP_TRUSTED_HOST\"; fi \\",
        "    && apt-get update \\",
        "    && apt-get install -y --no-install-recommends git \\",
        "    && rm -rf /var/lib/apt/lists/* \\",
        "    && python -m pip install --upgrade pip \\",
        "    && python -m pip install -r /tmp/vibelution-requirements.txt",
        "EOF_DOCKERFILE",
        'if [ "$REBUILD_IMAGE" = "1" ] || ! docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then',
        '  docker build --build-arg APT_MIRROR="$APT_MIRROR" --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" --build-arg PIP_TRUSTED_HOST="$PIP_TRUSTED_HOST" -t "$DOCKER_IMAGE" -f "$DOCKERFILE" "$DOCKER_BUILD_CONTEXT"',
        "fi",
        'echo docker_image="$DOCKER_IMAGE"',
        "docker run --rm \\",
        '  -v "$REMOTE_SOURCE:/workspace" \\',
        "  -w /workspace \\",
        "  -e NO_PROXY=localhost,127.0.0.1 \\",
        "  -e no_proxy=localhost,127.0.0.1 \\",
        "  -e TERM=xterm-256color \\",
        "  -e COLUMNS=120 \\",
        "  -e HOME=/tmp/vibelution-home \\",
        "  -e XDG_CACHE_HOME=/tmp/vibelution-cache \\",
        "  -e PYTHONUNBUFFERED=1 \\",
        "  -e VIBELUTION_CONFIG_PATH=/workspace/" + REMOTE_TEST_CONFIG + " \\",
        '  "$DOCKER_IMAGE" bash -lc ' + quoted_command,
    ]


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

    def _popen_command(
        self,
        command: Sequence[str],
        *,
        stdout=None,
        stderr=None,
        text: bool = True,
    ) -> subprocess.Popen | None:
        print(command_to_display(command))
        if self.config.dry_run:
            return None
        return subprocess.Popen(
            list(command),
            cwd=str(self.project_root),
            stdout=stdout,
            stderr=stderr,
            text=text,
        )

    def run(self) -> int:
        if self.config.distributed:
            return self.run_distributed()
        return self.run_remote_only()

    def run_remote_only(self) -> int:
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

    def run_distributed(self) -> int:
        targets = discover_test_targets(self.project_root)
        if not targets:
            print("No test targets discovered for distributed run.", file=sys.stderr)
            return 1

        local_targets, remote_targets = split_targets_by_capacity(
            targets,
            project_root=self.project_root,
            local_workers=self.config.local_workers,
            remote_workers=self.config.workers,
        )
        local_weight = sum(_target_weight(self.project_root, target) for target in local_targets)
        remote_weight = sum(_target_weight(self.project_root, target) for target in remote_targets)
        print(
            "distributed_split="
            f"local:{len(local_targets)} files/{local_weight} bytes/{self.config.local_workers} workers "
            f"remote:{len(remote_targets)} files/{remote_weight} bytes/{self.config.workers} workers"
        )
        print(
            build_distributed_correctness_summary(
                local_targets=local_targets,
                remote_targets=remote_targets,
                local_workers=self.config.local_workers,
                remote_workers=self.config.workers,
            )
        )

        run_id = utc_run_id()
        local_artifacts = self.config.local_artifacts_dir / run_id
        local_artifacts.mkdir(parents=True, exist_ok=True)
        local_log_path = local_artifacts / "local-test.log"
        remote_run_root = f"{self.config.remote_root}/runs/{run_id}"
        remote_archive = f"{remote_run_root}/source.tar.gz"
        remote_command = build_parallel_pytest_shell_command_from_manifest(
            ".remote-test/remote-targets.txt",
            workers=self.config.workers,
            python_executable="python",
        )
        remote_config = replace(self.config, remote_command=remote_command)
        remote_test_command = ["ssh", self.config.host, f"bash -lc {shlex.quote(build_remote_script(remote_config, run_id))}"]

        with tempfile.TemporaryDirectory(prefix="vibelution-remote-test-") as tmp:
            archive_path = Path(tmp) / "source.tar.gz"
            file_count = create_source_archive(
                self.project_root,
                archive_path,
                extra_files={
                    ".remote-test/remote-targets.txt": "\n".join(format_targets_for_command(remote_targets)) + "\n",
                },
            )
            print(f"archive={archive_path} files={file_count}")

            self._execute(["ssh", self.config.host, f"mkdir -p {shlex.quote(remote_run_root)}"])
            self._execute(["scp", str(archive_path), f"{self.config.host}:{remote_archive}"])

            local_command = build_parallel_pytest_command(
                local_targets,
                workers=self.config.local_workers,
                python_executable=sys.executable,
            )
            print("local " + command_to_display(local_command))
            local_log = local_log_path.open("w", encoding="utf-8", errors="replace") if not self.config.dry_run else None
            local_process = self._popen_command(
                local_command,
                stdout=local_log,
                stderr=subprocess.STDOUT,
            )
            remote_process = self._popen_command(remote_test_command)
            remote_returncode = 0
            local_returncode = 0
            try:
                remote_returncode, local_returncode = self._wait_distributed_processes(
                    remote_process,
                    local_process,
                )
            except BaseException:
                self._terminate_processes(remote_process, local_process)
                raise
            finally:
                if local_log is not None:
                    local_log.close()

            artifact_command = ["scp", "-r", f"{self.config.host}:{remote_run_root}/artifacts/.", str(local_artifacts)]
            artifact_returncode = self._run_command(artifact_command)

            if artifact_returncode != 0 and remote_returncode == 0:
                raise CommandFailed(artifact_command, artifact_returncode)
            if remote_returncode != 0:
                raise CommandFailed(remote_test_command, remote_returncode)
            if local_returncode != 0:
                raise CommandFailed(local_command, local_returncode)

        print(f"artifacts={local_artifacts}")
        return 0

    def _wait_distributed_processes(
        self,
        remote_process: subprocess.Popen | None,
        local_process: subprocess.Popen | None,
    ) -> tuple[int, int]:
        if remote_process is None or local_process is None:
            return 0, 0

        remote_returncode: int | None = None
        local_returncode: int | None = None
        while remote_returncode is None or local_returncode is None:
            if remote_returncode is None:
                remote_returncode = remote_process.poll()
            if local_returncode is None:
                local_returncode = local_process.poll()

            if remote_returncode not in (None, 0) and local_returncode is None:
                local_process.terminate()
            if local_returncode not in (None, 0) and remote_returncode is None:
                remote_process.terminate()

            if remote_returncode is None or local_returncode is None:
                try:
                    if remote_returncode is None:
                        remote_returncode = remote_process.wait(timeout=0.5)
                    if local_returncode is None:
                        local_returncode = local_process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass

        return remote_returncode, local_returncode

    def _terminate_processes(self, *processes: subprocess.Popen | None) -> None:
        for process in processes:
            if process is not None and process.poll() is None:
                process.terminate()


def parse_args(argv: Sequence[str]) -> RemoteTestConfig:
    parser = argparse.ArgumentParser(description="Run Vibelution tests on a remote Linux SSH worker.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"SSH host alias, default: {DEFAULT_HOST}")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT, help=f"Remote workspace root, default: {DEFAULT_REMOTE_ROOT}")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            f"Remote pytest worker count, default: {DEFAULT_WORKERS}; "
            f"with --distributed default: {DEFAULT_DISTRIBUTED_REMOTE_WORKERS}"
        ),
    )
    parser.add_argument(
        "--local-workers",
        type=int,
        default=DEFAULT_LOCAL_WORKERS,
        help=f"Local pytest worker count for --distributed, default: {DEFAULT_LOCAL_WORKERS}",
    )
    parser.add_argument(
        "--backend",
        choices=("venv", "docker"),
        default=DEFAULT_BACKEND,
        help=f"Remote execution backend, default: {DEFAULT_BACKEND}",
    )
    parser.add_argument(
        "--docker-image",
        default=DEFAULT_DOCKER_IMAGE,
        help=f"Docker image repository/base name for --backend docker, default: {DEFAULT_DOCKER_IMAGE}",
    )
    parser.add_argument("--rebuild-image", action="store_true", help="Force rebuild of the remote Docker test image.")
    parser.add_argument(
        "--suite",
        choices=("environment-smoke", "parallel", "hybrid"),
        default="parallel",
        help="Built-in test suite to run when --remote-command is not provided.",
    )
    parser.add_argument("--remote-command", help="Custom command to run in the remote source directory.")
    parser.add_argument("--no-install", action="store_true", help="Skip remote pip install step.")
    parser.add_argument(
        "--distributed",
        action="store_true",
        help="Split test files between local pytest and the remote worker, then run both sides concurrently.",
    )
    parser.add_argument(
        "--apt-mirror",
        default=os.environ.get("VIBELUTION_REMOTE_APT_MIRROR", DEFAULT_APT_MIRROR),
        help=f"APT mirror used while building Docker images, default: {DEFAULT_APT_MIRROR}",
    )
    parser.add_argument(
        "--pip-index-url",
        default=os.environ.get("VIBELUTION_REMOTE_PIP_INDEX_URL", DEFAULT_PIP_INDEX_URL),
        help=f"pip index URL used by remote installs, default: {DEFAULT_PIP_INDEX_URL}",
    )
    parser.add_argument(
        "--pip-trusted-host",
        default=os.environ.get("VIBELUTION_REMOTE_PIP_TRUSTED_HOST", DEFAULT_PIP_TRUSTED_HOST),
        help=f"pip trusted host used by remote installs, default: {DEFAULT_PIP_TRUSTED_HOST}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned ssh/scp commands without executing them.")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=PROJECT_ROOT / "logs" / "remote_test_runs",
        help="Local directory for copied remote artifacts.",
    )
    args = parser.parse_args(argv)

    workers = args.workers or (DEFAULT_DISTRIBUTED_REMOTE_WORKERS if args.distributed else DEFAULT_WORKERS)
    if workers < 1:
        parser.error("--workers must be >= 1")
    if args.local_workers < 1:
        parser.error("--local-workers must be >= 1")
    if args.distributed and args.remote_command:
        parser.error("--distributed cannot be combined with --remote-command because the runner owns test sharding")
    if args.distributed and args.suite != "parallel":
        parser.error("--distributed currently supports --suite parallel only")
    if not shutil.which("ssh"):
        parser.error("ssh executable was not found on PATH")
    if not shutil.which("scp"):
        parser.error("scp executable was not found on PATH")

    return RemoteTestConfig(
        host=args.host,
        remote_root=args.remote_root.rstrip("/"),
        workers=workers,
        local_workers=args.local_workers,
        suite=args.suite,
        backend=args.backend,
        docker_image=args.docker_image,
        rebuild_image=args.rebuild_image,
        remote_command=args.remote_command,
        no_install=args.no_install,
        distributed=args.distributed,
        apt_mirror=args.apt_mirror,
        pip_index_url=args.pip_index_url,
        pip_trusted_host=args.pip_trusted_host,
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
