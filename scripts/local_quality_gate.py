#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Sequence

Outcome = Literal[
    "passed",
    "failed",
    "stale_main",
    "claim_conflict",
    "dirty_worktree",
    "merge_conflict",
    "unsupported_validation_command",
    "gate_definition_dirty",
]

FATAL_RUFF_RULES = "E9,F63,F7,F82"
PROJECT_PYTHON_NAME = Path(".venv") / "Scripts" / "python.exe"
SHELL_META = re.compile(r"[|&;<>\r\n]|\$\(|`")
GATE_DEFINITION_FILES = frozenset(
    {
        ".githooks/pre-commit",
        ".github/workflows/ci.yml",
        "scripts/doctor.ps1",
        "scripts/local_quality_gate.py",
        "tests/select_tests.py",
        "tests/test_matrix.yaml",
    }
)


@dataclass(frozen=True)
class ProcessResult:
    kind: str
    argv: list[str]
    cwd: str
    exit_code: int
    duration_ms: int
    status: Literal["passed", "failed"]
    failure_summary: str = ""


@dataclass
class GateResult:
    outcome: Outcome
    exit_code: int
    commands: list[ProcessResult] = field(default_factory=list)
    manifest_path: Path | None = None


class UnsupportedValidationCommand(ValueError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    kind: str
    argv: list[str]
    cwd: Path


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def split_command(command: str) -> list[str]:
    if SHELL_META.search(command):
        raise UnsupportedValidationCommand(command)
    tokens = shlex.split(command, posix=False)
    return [
        token[1:-1]
        if len(token) >= 2
        and token[0] == token[-1]
        and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]


def parse_allowed_command(command: str, root: Path) -> CommandSpec:
    argv = split_command(command)
    normalized = [normalize_path(token) for token in argv]
    python_tokens = {
        normalize_path(str(PROJECT_PYTHON_NAME)),
        ".venv/Scripts/python.exe",
    }
    if normalized == ["git", "diff", "--check"]:
        return CommandSpec("diff-check", argv, root)
    if normalized and normalized[0] in python_tokens:
        canonical = [str(PROJECT_PYTHON_NAME), *argv[1:]]
        if argv[1:3] == ["-m", "pytest"]:
            return CommandSpec("pytest", canonical, root)
        if len(argv) >= 2 and normalized[1] == "tests/select_tests.py":
            return CommandSpec("selector", canonical, root)
        if len(argv) >= 2 and normalized[1] == "tests/prompt_debugger.py":
            return CommandSpec("prompt-debugger", canonical, root)
    if normalized[:4] == ["npm", "--prefix", "web", "run"] and len(argv) >= 5:
        npm_kinds = {
            "test": "web-test",
            "build": "web-build",
            "check:bundle": "bundle-check",
        }
        if argv[4] in npm_kinds:
            return CommandSpec(npm_kinds[argv[4]], argv, root)
    if normalized == ["node", "挑战杯/build_research_flow_site.mjs"]:
        return CommandSpec("challenge-cup-build", argv, root)
    raise UnsupportedValidationCommand(command)


def run_process(
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def repository_root(start: Path) -> Path:
    completed = run_process(["git", "rev-parse", "--show-toplevel"], start)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "not a Git repository")
    return Path(completed.stdout.strip()).resolve()


def git_lines(root: Path, *args: str) -> list[str]:
    completed = run_process(["git", *args], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return [line for line in completed.stdout.splitlines() if line]


def git_paths(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error or "git command failed")
    return [
        normalize_path(os.fsdecode(raw_path))
        for raw_path in completed.stdout.split(b"\0")
        if raw_path
    ]


def staged_paths(root: Path) -> list[str]:
    return git_paths(
        root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
    )


def staged_blob(root: Path, path: str) -> str:
    completed = run_process(["git", "show", f":{path}"], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"cannot read staged blob: {path}")
    return completed.stdout


def summarize_failure(completed: subprocess.CompletedProcess[str], subject: str) -> str:
    raw = completed.stderr.strip() or completed.stdout.strip() or "command failed"
    first_line = raw.splitlines()[0][:300]
    return f"{subject}: {first_line}"


def measured(
    kind: str,
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    subject: str,
) -> ProcessResult:
    started = time.monotonic()
    completed = run_process(argv, cwd, input_text=input_text)
    duration_ms = round((time.monotonic() - started) * 1000)
    return ProcessResult(
        kind=kind,
        argv=list(argv),
        cwd=str(cwd),
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        status="passed" if completed.returncode == 0 else "failed",
        failure_summary="" if completed.returncode == 0 else summarize_failure(completed, subject),
    )


def execute_command(spec: CommandSpec) -> ProcessResult:
    argv = list(spec.argv)
    if Path(argv[0]) == PROJECT_PYTHON_NAME:
        argv[0] = str((spec.cwd / PROJECT_PYTHON_NAME).resolve())
    return measured(spec.kind, argv, spec.cwd, subject=spec.kind)


def gate_definition_is_dirty(root: Path, staged: Sequence[str]) -> bool:
    unstaged = set(
        git_paths(root, "diff", "--name-only", "--diff-filter=ACMRD", "-z")
    )
    return bool(GATE_DEFINITION_FILES.intersection(staged).intersection(unstaged))


def run_commit_gate(root: Path) -> GateResult:
    root = repository_root(root)
    staged = staged_paths(root)
    if not staged:
        return GateResult(outcome="passed", exit_code=0)
    if gate_definition_is_dirty(root, staged):
        return GateResult(outcome="gate_definition_dirty", exit_code=1)

    commands: list[ProcessResult] = []
    diff_check = measured(
        "diff-check",
        ["git", "diff", "--cached", "--check"],
        root,
        subject="staged diff",
    )
    commands.append(diff_check)
    if diff_check.status == "failed":
        return GateResult(outcome="failed", exit_code=1, commands=commands)

    for path in staged:
        if not path.endswith(".py"):
            continue
        lint = measured(
            "ruff-staged",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                FATAL_RUFF_RULES,
                "--stdin-filename",
                path,
                "-",
            ],
            root,
            input_text=staged_blob(root, path),
            subject=path,
        )
        commands.append(lint)
        if lint.status == "failed":
            return GateResult(outcome="failed", exit_code=1, commands=commands)
    if GATE_DEFINITION_FILES.intersection(staged):
        self_test = measured(
            "gate-self-test",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_local_quality_gate.py",
                "-q",
                "-k",
                "commit_mode or pre_commit",
            ],
            root,
            subject="gate self-test",
        )
        commands.append(self_test)
        if self_test.status == "failed":
            return GateResult(outcome="failed", exit_code=1, commands=commands)
    return GateResult(outcome="passed", exit_code=0, commands=commands)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vibelution local quality gate")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "commit":
        result = run_commit_gate(Path.cwd())
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
        return result.exit_code
    raise AssertionError(f"unhandled mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
