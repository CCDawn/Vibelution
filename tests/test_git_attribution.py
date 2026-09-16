from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate


@pytest.mark.parametrize(
    ("trailer", "allowed"),
    [
        ("", True),
        ("Co-authored-by: Human <human@example.com>", True),
        ("Co-authored-by: Cursor <cursoragent@cursor.com>", False),
        ("Co-authored-by: CommandCodeBot <noreply@commandcode.ai>", False),
        ("co-authored-by: CURSOR <CURSORAGENT@CURSOR.COM>", False),
    ],
)
def test_commit_hook_preserves_humans_and_rejects_observed_ai(
    tmp_path: Path, trailer: str, allowed: bool
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    target = hooks / "commit-msg"
    shutil.copyfile(Path(__file__).parents[1] / ".githooks" / "commit-msg", target)
    target.chmod(0o755)
    env = gate.git_hook_isolated_environment()

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, capture_output=True, text=True
        )

    assert git("init").returncode == 0
    result = git(
        "-c", "user.name=Human", "-c", "user.email=human@example.com",
        "-c", f"core.hooksPath={hooks.as_posix()}",
        "commit", "--allow-empty", "-m", f"test attribution\n\n{trailer}",
    )
    assert (result.returncode == 0) == allowed, result.stderr
    if not allowed:
        assert "AI co-author attribution is disabled" in result.stderr


def test_validation_child_cannot_change_parent_git_identity(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "parent"
    fixture = tmp_path / "fixture"
    parent.mkdir()
    fixture.mkdir()
    env = gate.git_hook_isolated_environment()
    for root in (parent, fixture):
        subprocess.run(["git", "init", str(root)], env=env, check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(parent), "config", "user.name", "Real Owner"],
        env=env, check=True,
    )
    monkeypatch.setenv("GIT_DIR", str(parent / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(parent))
    subprocess.run(
        ["git", "config", "user.name", "Quality Gate Test"],
        cwd=fixture, env=gate.validation_environment(), check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(parent), "config", "user.name"],
        env=env, check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "Real Owner"
