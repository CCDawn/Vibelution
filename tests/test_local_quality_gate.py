from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "quality-gate@example.invalid")
    git(tmp_path, "config", "user.name", "Quality Gate Test")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(tmp_path, "add", "seed.txt")
    git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def commit_file(root: Path, path: str, content: str, message: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-m", message)


def active_claim(claim_id: str, scopes: list[str]) -> dict[str, object]:
    return {
        "claims": [
            {
                "id": claim_id,
                "status": "active",
                "scopes": scopes,
            }
        ]
    }


def test_commit_mode_lints_staged_blob_instead_of_worktree(git_repo: Path) -> None:
    target = git_repo / "broken.py"
    target.write_text("def broken(:\n", encoding="utf-8")
    git(git_repo, "add", "broken.py")
    target.write_text("def fixed() -> int:\n    return 1\n", encoding="utf-8")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "failed"
    assert result.exit_code == 1
    assert result.commands[0].kind == "diff-check"
    assert result.commands[1].kind == "ruff-staged"
    assert "broken.py" in result.commands[1].failure_summary


def test_commit_mode_lints_non_ascii_staged_python_path(git_repo: Path) -> None:
    target = git_repo / "挑战杯" / "broken.py"
    target.parent.mkdir()
    target.write_text("def broken(:\n", encoding="utf-8")
    git(git_repo, "add", "挑战杯/broken.py")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "failed"
    assert any(command.kind == "ruff-staged" for command in result.commands)


def test_commit_mode_ignores_deleted_python(git_repo: Path) -> None:
    target = git_repo / "removed.py"
    target.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    git(git_repo, "add", "removed.py")
    git(git_repo, "commit", "-m", "add python")
    target.unlink()
    git(git_repo, "add", "removed.py")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "passed"
    assert all(command.kind != "ruff-staged" for command in result.commands)


def test_commit_mode_rejects_partially_staged_gate_definition(git_repo: Path) -> None:
    hook = git_repo / ".githooks" / "pre-commit"
    hook.parent.mkdir()
    hook.write_text("first\n", encoding="utf-8")
    git(git_repo, "add", ".githooks/pre-commit")
    hook.write_text("first\nsecond\n", encoding="utf-8")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "gate_definition_dirty"
    assert result.exit_code == 1


def test_commit_mode_rejects_staged_gate_definition_deleted_from_worktree(
    git_repo: Path,
) -> None:
    hook = git_repo / ".githooks" / "pre-commit"
    hook.parent.mkdir()
    hook.write_text("first\n", encoding="utf-8")
    git(git_repo, "add", ".githooks/pre-commit")
    hook.unlink()

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "gate_definition_dirty"
    assert result.exit_code == 1


def test_commit_mode_without_relevant_staged_files_passes(git_repo: Path) -> None:
    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "passed"
    assert result.commands == []


@pytest.mark.parametrize(
    ("command", "kind", "argv_prefix"),
    [
        ("git diff --check", "diff-check", ["git", "diff", "--check"]),
        (
            ".\\.venv\\Scripts\\python.exe -m pytest tests/test_select_tests.py -q",
            "pytest",
            [str(gate.PROJECT_PYTHON_NAME), "-m", "pytest"],
        ),
        (
            ".\\.venv\\Scripts\\python.exe tests/select_tests.py "
            "--changed-file README.md --json",
            "selector",
            [str(gate.PROJECT_PYTHON_NAME), "tests/select_tests.py"],
        ),
        (
            ".\\.venv\\Scripts\\python.exe tests/prompt_debugger.py --suite",
            "prompt-debugger",
            [str(gate.PROJECT_PYTHON_NAME), "tests/prompt_debugger.py"],
        ),
        (
            "npm --prefix web run test",
            "web-test",
            ["npm", "--prefix", "web", "run", "test"],
        ),
        (
            "npm --prefix web run build",
            "web-build",
            ["npm", "--prefix", "web", "run", "build"],
        ),
        (
            "npm --prefix web run check:bundle",
            "bundle-check",
            ["npm", "--prefix", "web", "run", "check:bundle"],
        ),
        (
            "node 挑战杯/build_research_flow_site.mjs",
            "challenge-cup-build",
            ["node", "挑战杯/build_research_flow_site.mjs"],
        ),
    ],
)
def test_parse_allowed_command(
    git_repo: Path,
    command: str,
    kind: str,
    argv_prefix: list[str],
) -> None:
    spec = gate.parse_allowed_command(command, git_repo)

    assert spec.kind == kind
    assert spec.argv[: len(argv_prefix)] == argv_prefix
    assert spec.cwd == git_repo


@pytest.mark.parametrize(
    "command",
    [
        "python -c print(1)",
        "git status",
        "npm install",
        "pytest tests",
        "git diff --check; git status",
        "npm --prefix web run test | more",
        "node -e process.exit(0)",
        "pwsh -Command Get-ChildItem",
    ],
)
def test_parse_allowed_command_rejects_arbitrary_or_shell_commands(
    git_repo: Path,
    command: str,
) -> None:
    with pytest.raises(gate.UnsupportedValidationCommand):
        gate.parse_allowed_command(command, git_repo)


def test_execute_command_runs_allowed_argv_without_a_shell(git_repo: Path) -> None:
    spec = gate.parse_allowed_command("git diff --check", git_repo)

    result = gate.execute_command(spec)

    assert result.kind == "diff-check"
    assert result.argv == ["git", "diff", "--check"]
    assert result.cwd == str(git_repo)
    assert result.status == "passed"


def test_main_worktree_falls_back_to_single_repository(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")

    assert gate.main_worktree(git_repo, "main") == git_repo.resolve()


def test_main_worktree_finds_linked_main_worktree(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    git(git_repo, "branch", "-M", "main")
    task_worktree = tmp_path / "task-worktree"
    git(git_repo, "worktree", "add", str(task_worktree), "-b", "codex/test-task")

    assert gate.main_worktree(task_worktree, "main") == git_repo.resolve()


def test_closeout_writes_bounded_passed_manifest(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 1
    assert manifest["taskId"] == "test-task"
    assert manifest["branch"] == "codex/test-task"
    assert manifest["claimId"] == "claim-test"
    assert manifest["changedFiles"] == ["README.md"]
    assert manifest["checks"]["worktreeClean"] is True
    assert manifest["checks"]["claimValid"] is True
    assert manifest["checks"]["mergePreflight"] is True
    assert manifest["checks"]["commandsAllowlisted"] is True
    assert manifest["outcome"] == "passed"
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "environment" not in serialized.lower()
    assert "prompt" not in serialized.lower()
    assert "stdout" not in serialized.lower()
    assert "stderr" not in serialized.lower()


def test_closeout_rejects_main_branch(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "failed"


def test_closeout_reports_dirty_worktree(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "dirty_worktree"


def test_closeout_reports_claim_conflict(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(gate, "read_guard_status", lambda root: {"claims": []})

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "claim_conflict"


def test_closeout_reports_unsupported_validation_command(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["pwsh -Command Get-ChildItem"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "unsupported_validation_command"


def test_verify_manifest_detects_stale_main(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    manifest = git_repo / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "outcome": "passed",
                "validatedMainSha": "0" * 40,
                "headSha": git(git_repo, "rev-parse", "HEAD").stdout.strip(),
            }
        ),
        encoding="utf-8",
    )

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "stale_main"


def test_closeout_detects_main_moving_during_commands(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    original_execute = gate.execute_command

    def execute_and_move_main(spec: gate.CommandSpec) -> gate.ProcessResult:
        result = original_execute(spec)
        git(git_repo, "update-ref", "refs/heads/main", "HEAD")
        return result

    monkeypatch.setattr(gate, "execute_command", execute_and_move_main)

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_reports_merge_conflict(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = git_repo / "conflict.txt"
    conflict.write_text("base\n", encoding="utf-8")
    git(git_repo, "add", "conflict.txt")
    git(git_repo, "commit", "-m", "add conflict base")
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "conflict.txt", "task\n", "task side")
    git(git_repo, "switch", "main")
    commit_file(git_repo, "conflict.txt", "main\n", "main side")
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["conflict.txt"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "merge_conflict"
    assert manifest["outcome"] == "merge_conflict"


def test_closeout_reads_claim_from_linked_main_worktree(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    task_worktree = tmp_path / "linked-task"
    git(git_repo, "worktree", "add", str(task_worktree), "-b", "codex/test-task")
    commit_file(task_worktree, "README.md", "changed\n", "docs change")
    guard_roots: list[Path] = []

    def guard_status(root: Path) -> dict[str, object]:
        guard_roots.append(root)
        return active_claim("claim-test", ["README.md"])

    monkeypatch.setattr(gate, "read_guard_status", guard_status)

    result = gate.run_closeout(task_worktree, "main", "claim-test")

    assert result.outcome == "passed"
    assert guard_roots == [git_repo.resolve(), git_repo.resolve()]


def test_closeout_appends_gate_self_tests_when_gate_definition_changes(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(
        git_repo,
        "scripts/local_quality_gate.py",
        "VALUE = 1\n",
        "change gate",
    )
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["scripts/local_quality_gate.py"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )
    monkeypatch.setattr(
        gate,
        "measured",
        lambda kind, argv, cwd, **kwargs: gate.ProcessResult(
            kind=kind,
            argv=list(argv),
            cwd=str(cwd),
            exit_code=0,
            duration_ms=1,
            status="passed",
        ),
    )
    monkeypatch.setattr(
        gate,
        "execute_command",
        lambda spec: gate.ProcessResult(
            kind=spec.kind,
            argv=spec.argv,
            cwd=str(spec.cwd),
            exit_code=0,
            duration_ms=1,
            status="passed",
        ),
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert [command.kind for command in result.commands] == [
        "changed-python-ruff",
        "diff-check",
        "pytest",
    ]


def test_manifest_payload_bounds_failure_summary_to_first_300_characters(
    git_repo: Path,
) -> None:
    payload = gate.manifest_payload(
        task_id="test-task",
        branch="codex/test-task",
        root=git_repo,
        claim_id="claim-test",
        validated_main_sha="a" * 40,
        head_sha="b" * 40,
        files=["README.md"],
        commands=[
            gate.ProcessResult(
                kind="pytest",
                argv=["python", "-m", "pytest"],
                cwd=str(git_repo),
                exit_code=1,
                duration_ms=1,
                status="failed",
                failure_summary="x" * 400 + "\nsecret second line",
            )
        ],
        checks={
            "worktreeClean": True,
            "claimValid": True,
            "mergePreflight": False,
            "commandsAllowlisted": True,
        },
        outcome="failed",
    )

    assert payload["commands"][0]["failureSummary"] == "x" * 300
