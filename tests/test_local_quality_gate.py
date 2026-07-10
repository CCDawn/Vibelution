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
