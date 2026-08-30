from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import validation_toolchain


@pytest.fixture(autouse=True)
def _healthy_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation_toolchain, "_pip_check", lambda _python: None)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def linked_worktrees(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "project"
    main.mkdir()
    _git(main, "init")
    _git(main, "config", "user.email", "toolchain@example.invalid")
    _git(main, "config", "user.name", "Validation Toolchain Test")
    (main / "requirements.txt").write_text("pytest>=7\nruff>=0.6\n", encoding="utf-8")
    _git(main, "add", "requirements.txt")
    _git(main, "commit", "-m", "seed")
    _git(main, "branch", "-M", "main")
    task = tmp_path / "task"
    _git(main, "worktree", "add", "-b", "codex/task", str(task), "main")
    return main, task


def _identity() -> validation_toolchain.PythonIdentity:
    return validation_toolchain.PythonIdentity(
        implementation="cpython",
        version="3.12.10",
        cache_tag="cpython-312",
        architecture="AMD64",
        distributions_sha256="d" * 64,
    )


def test_task_without_local_venv_reuses_matching_integration_venv(
    linked_worktrees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main, task = linked_worktrees
    python = validation_toolchain.venv_python(main / ".venv")
    python.parent.mkdir(parents=True)
    python.write_text("probe", encoding="utf-8")
    monkeypatch.setattr(validation_toolchain, "_probe_python", lambda _python: _identity())

    resolved = validation_toolchain.resolve_validation_toolchain(task)

    assert resolved.integration_root == main.resolve()
    assert resolved.checkout_root == task.resolve()
    assert resolved.python_executable == python.resolve()
    assert resolved.source == "integration_venv"
    assert not (task / ".venv").exists()
    assert resolved.snapshot()["fingerprint"] == resolved.fingerprint


def test_task_requirements_mismatch_is_explicit(
    linked_worktrees: tuple[Path, Path],
) -> None:
    main, task = linked_worktrees
    (task / "requirements.txt").write_text(
        "pytest>=7\nruff>=0.6\ntzdata>=2025.2\n",
        encoding="utf-8",
    )

    with pytest.raises(validation_toolchain.ValidationToolchainError) as raised:
        validation_toolchain.resolve_validation_toolchain(task)

    assert raised.value.code == "validation_toolchain_mismatch"
    assert "requirements.txt" in str(raised.value)


def test_matching_task_reports_missing_integration_python(
    linked_worktrees: tuple[Path, Path],
) -> None:
    _main, task = linked_worktrees

    with pytest.raises(validation_toolchain.ValidationToolchainError) as raised:
        validation_toolchain.resolve_validation_toolchain(task)

    assert raised.value.code == "validation_toolchain_missing"


def test_unhealthy_integration_python_is_not_accepted(
    linked_worktrees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main, task = linked_worktrees
    python = validation_toolchain.venv_python(main / ".venv")
    python.parent.mkdir(parents=True)
    python.write_text("probe", encoding="utf-8")

    def fail_probe(_python: Path) -> validation_toolchain.PythonIdentity:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(validation_toolchain, "_probe_python", fail_probe)

    with pytest.raises(validation_toolchain.ValidationToolchainError) as raised:
        validation_toolchain.resolve_validation_toolchain(task)

    assert raised.value.code == "validation_toolchain_unhealthy"
    assert "probe failed" in str(raised.value)


def test_broken_environment_dependencies_are_not_accepted(
    linked_worktrees: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main, task = linked_worktrees
    python = validation_toolchain.venv_python(main / ".venv")
    python.parent.mkdir(parents=True)
    python.write_text("probe", encoding="utf-8")
    monkeypatch.setattr(validation_toolchain, "_probe_python", lambda _python: _identity())
    monkeypatch.setattr(
        validation_toolchain,
        "_pip_check",
        lambda _python: (_ for _ in ()).throw(RuntimeError("broken requirements")),
    )

    with pytest.raises(validation_toolchain.ValidationToolchainError) as raised:
        validation_toolchain.resolve_validation_toolchain(task)

    assert raised.value.code == "validation_toolchain_unhealthy"
    assert "broken requirements" in str(raised.value)
