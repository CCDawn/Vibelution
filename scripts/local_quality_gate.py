#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

try:
    from scripts.windowless_subprocess import no_window_subprocess_kwargs
except ModuleNotFoundError:  # Direct execution sets sys.path[0] to scripts/.
    import importlib.util

    _windowless_spec = importlib.util.spec_from_file_location(
        "vibelution_windowless_subprocess",
        Path(__file__).with_name("windowless_subprocess.py"),
    )
    if _windowless_spec is None or _windowless_spec.loader is None:
        raise RuntimeError("Unable to load the windowless subprocess policy.")
    _windowless_module = importlib.util.module_from_spec(_windowless_spec)
    _windowless_spec.loader.exec_module(_windowless_module)
    no_window_subprocess_kwargs = _windowless_module.no_window_subprocess_kwargs

Outcome = Literal[
    "passed",
    "failed",
    "stale_main",
    "claim_conflict",
    "dirty_worktree",
    "merge_conflict",
    "unsupported_validation_command",
    "gate_definition_dirty",
    "reuse_research_missing",
    "reuse_research_invalid",
    "validation_toolchain_missing",
    "validation_toolchain_mismatch",
    "validation_toolchain_requirements_missing",
    "validation_toolchain_unhealthy",
]

FATAL_RUFF_RULES = "E9,F63,F7,F82"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import reuse_research_contract
from scripts.validation_toolchain import (
    ValidationToolchain,
    ValidationToolchainError,
    resolve_validation_toolchain,
)
from vibelution_storage import resolve_project_cache_home

GUARD_SCRIPT_CANDIDATES = (
    Path.home()
    / ".codex"
    / "skills"
    / "briefbound-project-memory"
    / "scripts"
    / "agent_coordination.py",
    Path.home()
    / ".codex"
    / "skills"
    / "ccdawn-dawn-agent-html-memory"
    / "scripts"
    / "agent_work_guard.py",
)
MANIFEST_SCHEMA_VERSION = 3
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
GATE_SELF_TEST_COMMANDS = (
    (
        ".\\.venv\\Scripts\\python.exe -m pytest "
        "tests/test_git_claim_guard.py tests/test_local_quality_gate.py tests/test_task_closeout.py tests/test_ci_workflow_contract.py "
        "tests/test_select_tests.py tests/test_reuse_research_contract.py tests/test_validation_toolchain.py "
        "tests/test_github_project_library_service.py -n 4 --dist load -m \"not serial\" -q --maxfail=0"
    ),
)
GATE_DEFINITION_FILES = frozenset(
    {
        ".githooks/pre-commit",
        ".githooks/reference-transaction",
        ".github/workflows/ci.yml",
        "scripts/doctor.ps1",
        "scripts/local_quality_gate.py",
        "scripts/git_claim_guard.py",
        "scripts/reuse_research_contract.py",
        "scripts/reuse_research_evidence.py",
        "scripts/task_closeout.py",
        "scripts/validation_toolchain.py",
        "tests/select_tests.py",
        "tests/test_matrix.yaml",
        "tests/test_task_closeout.py",
        "tests/test_git_claim_guard.py",
        "tests/test_validation_toolchain.py",
    }
)
SUPPORTED_RECORDED_COMMAND_KINDS = frozenset(
    {
        "bundle-check",
        "challenge-cup-build",
        "changed-python-ruff",
        "diff-check",
        "electron-test",
        "electron-vitest",
        "prompt-debugger",
        "pytest",
        "selector",
        "web-typecheck",
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
    if normalized == [
        "npm",
        "--prefix",
        "web",
        "exec",
        "--",
        "tsc",
        "-b",
        "--pretty",
        "false",
    ]:
        # ``npm --prefix web`` is an allowlisted manifest spelling.  Once the
        # command is bound to the frontend project root, retaining that prefix
        # would resolve ``web/web``.  Normalize it exactly like the Vitest
        # branch below: run the local npm executable from ``root/web`` while
        # preserving the allowlisted validation intent.
        return CommandSpec(
            "web-typecheck",
            [argv[0], "exec", "--", *argv[5:]],
            root / "web",
        )
    if normalized == [
        "node",
        "web/node_modules/typescript/bin/tsc",
        "-b",
        "web/tsconfig.json",
        "--pretty",
        "false",
    ]:
        # Root-cwd selector commands pin the TypeScript project explicitly.
        # Unlike the historical npm --prefix form above, this command is safe
        # to execute unchanged at the repository root.
        return CommandSpec("web-typecheck", argv, root)
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
    if normalized == ["npm", "--prefix", "desktop/electron", "test"]:
        return CommandSpec("electron-test", argv, root)
    if normalized[:3] == ["node", "web/node_modules/vitest/vitest.mjs", "run"]:
        if normalized[-2:] == ["--root", "web"]:
            # Current selector output is self-contained: Vitest receives the
            # frontend root even when the command is copied from repository
            # root, so it loads web/vite.config.ts and ignores sibling trees.
            return CommandSpec("web-test", argv, root)
        # Frontend selectors intentionally use paths relative to ``web`` (for example
        # ``src/routes/...``).  Running the node entrypoint from the repository root
        # skips web/vite.config.ts, so Vitest loses its project test plugins as well.
        # Preserve historic selector text by executing it in its declared frontend
        # project root; new selector commands use the explicit --root branch above.
        return CommandSpec(
            "web-test",
            [argv[0], "node_modules/vitest/vitest.mjs", *argv[2:]],
            root / "web",
        )
    if normalized[:3] == ["node", "desktop/electron/node_modules/vitest/vitest.mjs", "run"]:
        # The electron-main-shell selector pins the Electron project root
        # explicitly, so the command is self-contained at the repository root
        # (mirrors the root-bound web vitest branch above). Only the pinned
        # spelling is allowlisted; anything else stays unsupported.
        if normalized[-2:] == ["--root", "desktop/electron"]:
            return CommandSpec("electron-vitest", argv, root)
        raise UnsupportedValidationCommand(command)
    if normalized == ["node", "挑战杯/build_research_flow_site.mjs"]:
        return CommandSpec("challenge-cup-build", argv, root)
    raise UnsupportedValidationCommand(command)


def run_process(
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
        **no_window_subprocess_kwargs(),
    )


def git_hook_isolated_environment() -> dict[str, str]:
    """Remove repository-local Git variables before tests create fixture repos."""

    env = os.environ.copy()
    repository_local_names = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
    for name in repository_local_names:
        env.pop(name, None)
    return env


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
        **no_window_subprocess_kwargs(),
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
    raw = (completed.stderr or "").strip() or (completed.stdout or "").strip() or "command failed"
    return bounded_failure_summary(f"{subject}: {raw}")


def measured(
    kind: str,
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    subject: str,
) -> ProcessResult:
    started = time.monotonic()
    if env is None:
        completed = run_process(argv, cwd, input_text=input_text)
    else:
        completed = run_process(argv, cwd, input_text=input_text, env=env)
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


def execute_command(
    spec: CommandSpec,
    toolchain: ValidationToolchain | None = None,
) -> ProcessResult:
    materialized = materialize_command(spec, toolchain)
    return measured(
        materialized.kind,
        materialized.argv,
        materialized.cwd,
        subject=materialized.kind,
    )


def materialize_command(
    spec: CommandSpec,
    toolchain: ValidationToolchain | None = None,
) -> CommandSpec:
    argv = list(spec.argv)
    if Path(argv[0]) == PROJECT_PYTHON_NAME:
        resolved = toolchain or resolve_validation_toolchain(spec.cwd)
        argv[0] = str(resolved.python_executable)
    elif os.name == "nt" and str(argv[0]).strip().lower() == "npm":
        npm_launcher = shutil.which("npm.cmd") or shutil.which("npm")
        if npm_launcher:
            argv[0] = npm_launcher
    elif os.name == "nt" and str(argv[0]).strip().lower() == "node":
        node_launcher = shutil.which("node.exe") or shutil.which("node")
        if node_launcher:
            argv[0] = node_launcher
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


def resolve_guard_script(candidates: Sequence[Path] | None = None) -> Path:
    checked = tuple(candidates or GUARD_SCRIPT_CANDIDATES)
    for candidate in checked:
        if candidate.is_file():
            return candidate
    locations = ", ".join(str(candidate) for candidate in checked)
    raise RuntimeError(f"project coordination guard not found; checked: {locations}")


def read_guard_status(project_root: Path) -> dict[str, object]:
    guard_script = resolve_guard_script()
    completed = run_process(
        [sys.executable, str(guard_script), str(project_root), "status", "--json"],
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
            and item.get("status") in {"active", "ready"}
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
    project_root = str(PROJECT_ROOT.resolve())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from tests.select_tests import load_matrix, select_tests

    return select_tests(list(files), load_matrix())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bounded_failure_summary(summary: str) -> str:
    redacted = summary
    for pattern, replacement in FAILURE_SUMMARY_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted.splitlines()[0][:300] if redacted else ""


def load_reuse_research_for_closeout(
    root: Path,
    task_id: str,
    branch: str,
) -> dict[str, object] | None:
    return reuse_research_contract.load_and_validate_evidence(
        root,
        task_id=task_id,
        branch=branch,
        project_root=root,
    )


def validate_manifest_reuse_research(
    snapshot: object,
    root: Path,
) -> dict[str, object]:
    return reuse_research_contract.validate_manifest_snapshot(
        snapshot,
        root,
        project_root=root,
    )


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
    reuse_research_required: bool = False,
    reuse_research: dict[str, object] | None = None,
    validation_toolchain: dict[str, object] | None = None,
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
        "reuseResearchRequired": reuse_research_required,
        "reuseResearch": reuse_research,
        "validationToolchain": validation_toolchain,
        "outcome": outcome,
        "generatedAt": utc_now(),
    }


def quality_gate_manifest_path(root: Path, task_id: str) -> Path:
    cache_home = resolve_project_cache_home(root).resolve()
    try:
        cache_home.relative_to(root.resolve())
    except ValueError:
        manifest_home = cache_home
    else:
        completed = run_process(["git", "rev-parse", "--git-common-dir"], root)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "unable to resolve Git common dir")
        raw_common_dir = Path(completed.stdout.strip())
        common_dir = raw_common_dir if raw_common_dir.is_absolute() else root / raw_common_dir
        manifest_home = common_dir.resolve() / "vibelution-cache"
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-") or "task"
    return manifest_home / "quality_gates" / f"{safe_task_id}.json"


def write_manifest(root: Path, task_id: str, payload: dict[str, object]) -> Path:
    path = quality_gate_manifest_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    *,
    toolchain: ValidationToolchain | None = None,
) -> list[CommandSpec]:
    resolved_toolchain = toolchain or resolve_validation_toolchain(root)
    selection = selected_validation(files)
    raw_commands = selection.get("commands", [])
    if not isinstance(raw_commands, list):
        raise UnsupportedValidationCommand("selector commands must be a list")
    selected_commands = list(raw_commands)
    if GATE_DEFINITION_FILES.intersection(files):
        selected_commands.extend(
            command
            for command in GATE_SELF_TEST_COMMANDS
            if command not in selected_commands
        )

    specs: list[CommandSpec] = []
    python_files = changed_python_files(root, validated_main_sha, head_sha)
    if python_files:
        specs.append(
            CommandSpec(
                "changed-python-ruff",
                [
                    str(PROJECT_PYTHON_NAME),
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
    return [materialize_command(spec, resolved_toolchain) for spec in specs]


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
    reuse_research_required = False
    reuse_research: dict[str, object] | None = None
    validation_toolchain: ValidationToolchain | None = None
    checks = {
        "worktreeClean": False,
        "claimValid": False,
        "mergePreflight": False,
        "commandsAllowlisted": False,
        "reuseResearch": False,
        "validationToolchain": False,
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
            reuse_research_required=reuse_research_required,
            reuse_research=reuse_research,
            validation_toolchain=(
                validation_toolchain.snapshot()
                if validation_toolchain is not None
                else None
            ),
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

    reuse_research_required = reuse_research_contract.reuse_research_required(files)
    if reuse_research_required:
        try:
            reuse_research = load_reuse_research_for_closeout(root, task_id, branch)
        except reuse_research_contract.ReuseResearchEvidenceError:
            return finish("reuse_research_invalid")
        if reuse_research is None:
            return finish("reuse_research_missing")
    checks["reuseResearch"] = True

    try:
        validation_toolchain = resolve_validation_toolchain(root)
    except ValidationToolchainError as error:
        return finish(error.code)
    checks["validationToolchain"] = True

    try:
        specs = expected_closeout_commands(
            root,
            files,
            validated_main_sha,
            head_sha,
            toolchain=validation_toolchain,
        )
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
        "reuseResearch",
        "validationToolchain",
    )
    if not isinstance(checks, dict) or not all(
        checks.get(name) is True for name in required_checks
    ):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    reuse_research_required = reuse_research_contract.reuse_research_required(files)
    if payload.get("reuseResearchRequired") is not reuse_research_required:
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    snapshot = payload.get("reuseResearch")
    if reuse_research_required:
        try:
            validate_manifest_reuse_research(snapshot, root)
        except reuse_research_contract.ReuseResearchEvidenceError:
            return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    elif snapshot is not None:
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    try:
        validation_toolchain = resolve_validation_toolchain(root)
    except ValidationToolchainError as error:
        return GateResult(outcome=error.code, exit_code=1, manifest_path=path)
    if payload.get("validationToolchain") != validation_toolchain.snapshot():
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    try:
        expected_commands = expected_closeout_commands(
            root,
            files,
            str(payload["validatedMainSha"]),
            str(payload["headSha"]),
            toolchain=validation_toolchain,
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
    if current_branch(root) == "main":
        return GateResult(outcome="main_branch_direct_write_blocked", exit_code=1)
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

    validation_toolchain: ValidationToolchain | None = None
    for path in staged:
        if not path.endswith(".py"):
            continue
        if validation_toolchain is None:
            try:
                validation_toolchain = resolve_validation_toolchain(root)
            except ValidationToolchainError as error:
                return GateResult(outcome=error.code, exit_code=1, commands=commands)
        lint = measured(
            "ruff-staged",
            [
                str(validation_toolchain.python_executable),
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
    # Gate output is consumed by Windows shells and CI parsers, some of which
    # still use a legacy code page. Keep the machine-readable envelope ASCII.
    print(json.dumps(asdict(result), ensure_ascii=True, default=str))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
