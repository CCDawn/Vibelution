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
from datetime import datetime, timezone
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
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARD_SCRIPT = (
    Path.home()
    / ".codex"
    / "skills"
    / "ccdawn-dawn-agent-html-memory"
    / "scripts"
    / "agent_work_guard.py"
)
MANIFEST_SCHEMA_VERSION = 1
PROJECT_PYTHON_NAME = Path(".venv") / "Scripts" / "python.exe"
SHELL_META = re.compile(r"[|&;<>\r\n]|\$\(|`")
FAILURE_SUMMARY_REDACTIONS = (
    (
        re.compile(r"\bAuthorization\s*:\s*Bearer\s+[^\s,;]+", re.IGNORECASE),
        "Authorization: Bearer [REDACTED]",
    ),
    (
        re.compile(r"\b(https?://)[^\s/:@]+:[^\s/@]+@", re.IGNORECASE),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(
            r"\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*[^\s,;]+",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9_-]+"),
        "[REDACTED]",
    ),
)
GATE_SELF_TEST_COMMAND = (
    ".\\.venv\\Scripts\\python.exe -m pytest "
    "tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py "
    "tests/test_environment_doctor.py tests/test_select_tests.py -q"
)
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
SUPPORTED_RECORDED_COMMAND_KINDS = frozenset(
    {
        "bundle-check",
        "challenge-cup-build",
        "changed-python-ruff",
        "diff-check",
        "prompt-debugger",
        "pytest",
        "selector",
        "web-build",
        "web-test",
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
    return bounded_failure_summary(f"{subject}: {raw}")


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


def materialize_command(spec: CommandSpec) -> CommandSpec:
    argv = list(spec.argv)
    if Path(argv[0]) == PROJECT_PYTHON_NAME:
        argv[0] = str((spec.cwd / PROJECT_PYTHON_NAME).resolve())
    return CommandSpec(spec.kind, argv, spec.cwd)


def bind_closeout_command(
    spec: CommandSpec,
    validated_main_sha: str,
    head_sha: str,
) -> CommandSpec:
    if spec.kind != "diff-check":
        return spec
    return CommandSpec(
        spec.kind,
        [*spec.argv, f"{validated_main_sha}...{head_sha}"],
        spec.cwd,
    )


def current_branch(root: Path) -> str:
    branches = git_lines(root, "branch", "--show-current")
    return branches[0] if branches else ""


def rev_parse(root: Path, revision: str) -> str:
    return git_lines(root, "rev-parse", revision)[0]


def changed_files(root: Path, base: str) -> list[str]:
    return [
        normalize_path(path)
        for path in git_lines(root, "diff", "--name-only", f"{base}...HEAD")
    ]


def changed_python_files(root: Path, base_sha: str, head_sha: str) -> list[str]:
    return [
        path
        for path in git_paths(
            root,
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
            f"{base_sha}...{head_sha}",
        )
        if path.endswith(".py")
    ]


def main_worktree(root: Path, base: str) -> Path:
    completed = run_process(["git", "worktree", "list", "--porcelain"], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "cannot list worktrees")
    blocks = completed.stdout.strip().split("\n\n")
    expected_branch = f"branch refs/heads/{base}"
    for block in blocks:
        lines = block.splitlines()
        if expected_branch in lines:
            path_line = next(line for line in lines if line.startswith("worktree "))
            return Path(path_line.removeprefix("worktree ")).resolve()
    return root.resolve()


def read_guard_status(project_root: Path) -> dict[str, object]:
    completed = run_process(
        [sys.executable, str(GUARD_SCRIPT), str(project_root), "status", "--json"],
        project_root,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "guard status failed")
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, dict):
        raise RuntimeError("guard status must be an object")
    return loaded


def normalize_scope(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    return normalized.lower() or "."


def is_repository_scope(scope: str) -> bool:
    return scope in {"*", ".", "repo", "repository", "project", "project-root"}


def scope_covers(scope: str, changed_path: str) -> bool:
    normalized_scope = normalize_scope(scope)
    normalized_path = normalize_scope(changed_path)
    if is_repository_scope(normalized_scope):
        return True
    return normalized_path == normalized_scope or normalized_path.startswith(
        f"{normalized_scope}/"
    )


def validate_claim(project_root: Path, claim_id: str, files: Sequence[str]) -> bool:
    status = read_guard_status(project_root)
    claims = status.get("claims", [])
    if not isinstance(claims, list):
        return False
    claim = next(
        (
            item
            for item in claims
            if isinstance(item, dict)
            and item.get("id") == claim_id
            and item.get("status") == "active"
        ),
        None,
    )
    if claim is None:
        return False
    scopes = claim.get("scopes", [])
    return isinstance(scopes, list) and all(
        any(scope_covers(str(scope), path) for scope in scopes) for path in files
    )


def selected_validation(files: Sequence[str]) -> dict[str, object]:
    from tests.select_tests import load_matrix, select_tests

    return select_tests(list(files), load_matrix())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bounded_failure_summary(summary: str) -> str:
    redacted = summary
    for pattern, replacement in FAILURE_SUMMARY_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted.splitlines()[0][:300] if redacted else ""


def manifest_payload(
    *,
    task_id: str,
    branch: str,
    root: Path,
    claim_id: str,
    validated_main_sha: str,
    head_sha: str,
    files: Sequence[str],
    commands: Sequence[ProcessResult],
    checks: dict[str, bool],
    outcome: Outcome,
) -> dict[str, object]:
    return {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "taskId": task_id,
        "branch": branch,
        "worktree": str(root),
        "claimId": claim_id,
        "validatedMainSha": validated_main_sha,
        "headSha": head_sha,
        "changedFiles": list(files),
        "commands": [
            {
                "kind": command.kind,
                "argv": command.argv,
                "cwd": command.cwd,
                "exitCode": command.exit_code,
                "durationMs": command.duration_ms,
                "status": command.status,
                "failureSummary": bounded_failure_summary(command.failure_summary),
            }
            for command in commands
        ],
        "checks": checks,
        "outcome": outcome,
        "generatedAt": utc_now(),
    }


def write_manifest(root: Path, task_id: str, payload: dict[str, object]) -> Path:
    directory = root / ".runtime" / "quality_gates"
    directory.mkdir(parents=True, exist_ok=True)
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-") or "task"
    path = directory / f"{safe_task_id}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def merge_preflight(root: Path, base: str, head: str) -> bool:
    completed = run_process(["git", "merge-tree", "--write-tree", base, head], root)
    return completed.returncode == 0


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = run_process(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        root,
    )
    return completed.returncode == 0


def expected_closeout_commands(
    root: Path,
    files: Sequence[str],
    validated_main_sha: str,
    head_sha: str,
) -> list[CommandSpec]:
    selection = selected_validation(files)
    raw_commands = selection.get("commands", [])
    if not isinstance(raw_commands, list):
        raise UnsupportedValidationCommand("selector commands must be a list")
    selected_commands = list(raw_commands)
    if (
        GATE_DEFINITION_FILES.intersection(files)
        and GATE_SELF_TEST_COMMAND not in selected_commands
    ):
        selected_commands.append(GATE_SELF_TEST_COMMAND)

    specs: list[CommandSpec] = []
    python_files = changed_python_files(root, validated_main_sha, head_sha)
    if python_files:
        specs.append(
            CommandSpec(
                "changed-python-ruff",
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--select",
                    FATAL_RUFF_RULES,
                    *python_files,
                ],
                root,
            )
        )
    specs.extend(
        bind_closeout_command(
            parse_allowed_command(str(command), root),
            validated_main_sha,
            head_sha,
        )
        for command in selected_commands
    )
    return [materialize_command(spec) for spec in specs]


def manifest_commands_are_valid(
    commands: object,
    expected: Sequence[CommandSpec],
) -> bool:
    if not isinstance(commands, list) or len(commands) != len(expected):
        return False
    return all(
        isinstance(command, dict)
        and command.get("status") == "passed"
        and type(command.get("exitCode")) is int
        and command["exitCode"] == 0
        and isinstance(command.get("argv"), list)
        and all(isinstance(argument, str) for argument in command["argv"])
        and isinstance(command.get("cwd"), str)
        and isinstance(command.get("kind"), str)
        and command.get("kind") in SUPPORTED_RECORDED_COMMAND_KINDS
        and command["kind"] == spec.kind
        and command["argv"] == spec.argv
        and command["cwd"] == str(spec.cwd)
        for command, spec in zip(commands, expected, strict=True)
    )


def run_closeout(root: Path, base: str, claim_id: str) -> GateResult:
    root = repository_root(root)
    branch = current_branch(root)
    task_id = branch.removeprefix("codex/") if branch else "unknown-task"
    commands: list[ProcessResult] = []
    files: list[str] = []
    validated_main_sha = ""
    head_sha = rev_parse(root, "HEAD")
    checks = {
        "worktreeClean": False,
        "claimValid": False,
        "mergePreflight": False,
        "commandsAllowlisted": False,
    }

    def finish(outcome: Outcome) -> GateResult:
        payload = manifest_payload(
            task_id=task_id,
            branch=branch,
            root=root,
            claim_id=claim_id,
            validated_main_sha=validated_main_sha,
            head_sha=head_sha,
            files=files,
            commands=commands,
            checks=checks,
            outcome=outcome,
        )
        path = write_manifest(root, task_id, payload)
        return GateResult(
            outcome=outcome,
            exit_code=0 if outcome == "passed" else 1,
            commands=commands,
            manifest_path=path,
        )

    if not branch or branch == base or not branch.startswith("codex/"):
        return finish("failed")
    if git_lines(root, "status", "--porcelain"):
        return finish("dirty_worktree")
    checks["worktreeClean"] = True

    main_root = main_worktree(root, base)
    main_revision = "HEAD" if current_branch(main_root) == base else base
    validated_main_sha = rev_parse(main_root, main_revision)
    files = changed_files(root, base)
    checks["claimValid"] = validate_claim(main_root, claim_id, files)
    if not checks["claimValid"]:
        return finish("claim_conflict")

    try:
        specs = expected_closeout_commands(root, files, validated_main_sha, head_sha)
    except UnsupportedValidationCommand:
        return finish("unsupported_validation_command")
    checks["commandsAllowlisted"] = True

    def main_is_fresh() -> bool:
        return rev_parse(main_root, main_revision) == validated_main_sha

    for spec in specs:
        if not main_is_fresh():
            return finish("stale_main")
        result = execute_command(spec)
        commands.append(result)
        if result.status == "failed":
            return finish("failed")
        if not main_is_fresh():
            return finish("stale_main")

    if not main_is_fresh():
        return finish("stale_main")
    ancestry_valid = is_ancestor(root, validated_main_sha, head_sha)
    if not main_is_fresh():
        return finish("stale_main")
    if not ancestry_valid:
        return finish("stale_main")
    merge_tree_valid = merge_preflight(root, validated_main_sha, head_sha)
    if not main_is_fresh():
        return finish("stale_main")
    if not merge_tree_valid:
        return finish("merge_conflict")
    checks["mergePreflight"] = True
    if rev_parse(root, "HEAD") != head_sha:
        return finish("failed")
    if not validate_claim(main_root, claim_id, files):
        checks["claimValid"] = False
        return finish("claim_conflict")
    return finish("passed")


def verify_manifest(path: Path, root: Path, base: str) -> GateResult:
    root = repository_root(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if not isinstance(payload, dict):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if (
        type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != MANIFEST_SCHEMA_VERSION
    ):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if payload.get("outcome") != "passed":
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    main_root = main_worktree(root, base)
    main_revision = "HEAD" if current_branch(main_root) == base else base
    if payload.get("validatedMainSha") != rev_parse(main_root, main_revision):
        return GateResult(outcome="stale_main", exit_code=1, manifest_path=path)
    branch = current_branch(root)
    payload_branch = payload.get("branch")
    if (
        not branch
        or branch == base
        or not branch.startswith("codex/")
        or payload_branch != branch
    ):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if payload.get("taskId") != branch.removeprefix("codex/"):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    payload_worktree = payload.get("worktree")
    if not isinstance(payload_worktree, str) or Path(payload_worktree).resolve() != root:
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if payload.get("headSha") != rev_parse(root, "HEAD"):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if not is_ancestor(
        root,
        str(payload["validatedMainSha"]),
        str(payload["headSha"]),
    ):
        return GateResult(outcome="stale_main", exit_code=1, manifest_path=path)
    payload_files = payload.get("changedFiles")
    if not isinstance(payload_files, list) or not all(
        isinstance(item, str) for item in payload_files
    ):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    files = [normalize_path(item) for item in payload_files]
    if files != changed_files(root, base):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    checks = payload.get("checks")
    required_checks = (
        "worktreeClean",
        "claimValid",
        "mergePreflight",
        "commandsAllowlisted",
    )
    if not isinstance(checks, dict) or not all(
        checks.get(name) is True for name in required_checks
    ):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    try:
        expected_commands = expected_closeout_commands(
            root,
            files,
            str(payload["validatedMainSha"]),
            str(payload["headSha"]),
        )
    except UnsupportedValidationCommand:
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if not manifest_commands_are_valid(payload.get("commands"), expected_commands):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    claim_id = payload.get("claimId")
    if not isinstance(claim_id, str) or not claim_id.strip():
        return GateResult(outcome="claim_conflict", exit_code=1, manifest_path=path)
    if git_lines(root, "status", "--porcelain"):
        return GateResult(outcome="dirty_worktree", exit_code=1, manifest_path=path)
    try:
        claim_valid = validate_claim(main_root, claim_id, files)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        claim_valid = False
    if not claim_valid:
        return GateResult(outcome="claim_conflict", exit_code=1, manifest_path=path)
    return GateResult(outcome="passed", exit_code=0, manifest_path=path)


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
    closeout = subparsers.add_parser("closeout")
    closeout.add_argument("--base", default="main")
    closeout.add_argument("--claim-id", required=True)
    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--base", default="main")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "commit":
        result = run_commit_gate(Path.cwd())
    elif args.mode == "closeout":
        result = run_closeout(Path.cwd(), args.base, args.claim_id)
    elif args.mode == "verify-manifest":
        result = verify_manifest(args.manifest, Path.cwd(), args.base)
    else:
        raise AssertionError(f"unhandled mode: {args.mode}")
    print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
