from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate


@pytest.fixture
def attribution_git(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("commit-msg", "pre-push"):
        source = Path(__file__).parents[1] / ".githooks" / name
        if source.exists():
            target = hooks / name
            shutil.copyfile(source, target)
            target.chmod(0o755)
    env = gate.git_hook_isolated_environment()
    for role in ("AUTHOR", "COMMITTER"):
        for field in ("NAME", "EMAIL", "DATE"):
            env.pop(f"GIT_{role}_{field}", None)

    def git(
        *args: str, env_overrides: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git", "-c", "user.name=Human", "-c", "user.email=human@example.com",
                "-c", f"core.hooksPath={hooks.as_posix()}", *args,
            ],
            cwd=tmp_path, env={**env, **(env_overrides or {})},
            capture_output=True, text=True,
        )

    assert git("init").returncode == 0
    return git


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
    attribution_git: Callable[..., subprocess.CompletedProcess[str]],
    trailer: str,
    allowed: bool,
) -> None:
    result = attribution_git(
        "commit", "--allow-empty", "-m", f"test attribution\n\n{trailer}",
    )
    assert (result.returncode == 0) == allowed, result.stderr
    if not allowed:
        assert "AI co-author attribution is disabled" in result.stderr


@pytest.mark.parametrize("email", [
    "cursoragent@cursor.com", "noreply@commandcode.ai", "CURSORAGENT@CURSOR.COM",
])
@pytest.mark.parametrize("source", ["author_option", "AUTHOR", "COMMITTER"])
def test_commit_hook_rejects_ai_author_and_committer(
    attribution_git: Callable[..., subprocess.CompletedProcess[str]],
    source: str,
    email: str,
) -> None:
    args = ["commit", "--allow-empty", "-m", "test identity attribution"]
    env: dict[str, str] = {}
    if source == "author_option":
        args.extend(["--author", f"Tool identity <{email}>"])
    else:
        env = {f"GIT_{source}_NAME": "Tool identity", f"GIT_{source}_EMAIL": email}
    result = attribution_git(*args, env_overrides=env)
    assert result.returncode != 0, result.stdout
    assert "AI author/committer attribution is disabled" in result.stderr
    assert attribution_git("rev-parse", "--verify", "HEAD").returncode != 0


def test_commit_hook_preserves_distinct_human_author_and_committer(
    attribution_git: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = attribution_git(
        "commit", "--allow-empty", "--author", "Other Human <other@example.com>",
        "-m", "human collaboration\n\nCo-authored-by: Third Human <third@example.com>",
    )
    assert result.returncode == 0, result.stderr
    result = attribution_git("log", "-1", "--format=%an <%ae>%n%cn <%ce>%n%B")
    assert "Other Human <other@example.com>" in result.stdout
    assert "Human <human@example.com>" in result.stdout
    assert "Co-authored-by: Third Human <third@example.com>" in result.stdout


def test_amend_rejects_inherited_ai_author(
    attribution_git: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    seed = attribution_git(
        "-c", "core.hooksPath=", "commit", "--allow-empty",
        "--author", "Cursor Agent <cursoragent@cursor.com>", "-m", "legacy identity",
    )
    assert seed.returncode == 0, seed.stderr
    old_head = attribution_git("rev-parse", "HEAD").stdout.strip()
    result = attribution_git("commit", "--amend", "--allow-empty", "--no-edit")
    assert result.returncode != 0, result.stdout
    assert "AI author/committer attribution is disabled" in result.stderr
    assert attribution_git("rev-parse", "HEAD").stdout.strip() == old_head
    repaired = attribution_git(
        "commit", "--amend", "--allow-empty", "--no-edit", "--reset-author",
    )
    assert repaired.returncode == 0, repaired.stderr


@pytest.mark.parametrize("legacy_source", ["author", "committer", "coauthor", "coauthor_nonterminal"])
def test_push_rejects_ai_attribution_reintroduced_by_legacy_merge(
    attribution_git: Callable[..., subprocess.CompletedProcess[str]],
    tmp_path: Path,
    legacy_source: str,
) -> None:
    remote = str(tmp_path / "remote.git")
    assert attribution_git("init", "--bare", remote).returncode == 0
    assert attribution_git("commit", "--allow-empty", "-m", "human base").returncode == 0
    base = attribution_git("rev-parse", "HEAD").stdout.strip()
    branch = attribution_git("branch", "--show-current").stdout.strip()
    first_push = attribution_git("push", remote, "HEAD:refs/heads/main")
    assert first_push.returncode == 0, first_push.stderr
    assert attribution_git("switch", "-c", "legacy").returncode == 0
    args = ["-c", "core.hooksPath=", "commit", "--allow-empty", "-m", "legacy work"]
    env: dict[str, str] = {}
    if legacy_source == "author":
        args.extend(["--author", "Cursor Agent <cursoragent@cursor.com>"])
    elif legacy_source == "committer":
        env = {"GIT_COMMITTER_NAME": "CommandCodeBot", "GIT_COMMITTER_EMAIL": "noreply@commandcode.ai"}
    else:
        args[-1] += "\n\nCo-authored-by: CommandCodeBot <noreply@commandcode.ai>"
        if legacy_source == "coauthor_nonterminal":
            args[-1] += "\n\nExtra migration notes after attribution."
    seed = attribution_git(*args, env_overrides=env)
    assert seed.returncode == 0, seed.stderr
    assert attribution_git("switch", branch).returncode == 0
    assert attribution_git("commit", "--allow-empty", "-m", "current work").returncode == 0
    merged = attribution_git("merge", "--no-ff", "legacy", "-m", "merge prior work")
    assert merged.returncode == 0, merged.stderr
    result = attribution_git("push", remote, "HEAD:refs/heads/main")
    assert result.returncode != 0, result.stderr
    assert "AI attribution found in outgoing history" in result.stderr
    assert attribution_git("ls-remote", remote, "refs/heads/main").stdout.split()[0] == base


def test_push_preserves_human_authors_and_coauthors(
    attribution_git: Callable[..., subprocess.CompletedProcess[str]], tmp_path: Path,
) -> None:
    remote = str(tmp_path / "remote.git")
    assert attribution_git("init", "--bare", remote).returncode == 0
    commit = attribution_git(
        "commit", "--allow-empty", "--author", "Other Human <other@example.com>",
        "-m", "human work\n\nMigration note: <cursoragent@cursor.com> is blocked.\n\nCo-authored-by: Third Human <third@example.com>",
    )
    assert commit.returncode == 0, commit.stderr
    result = attribution_git("push", remote, "HEAD:refs/heads/main")
    assert result.returncode == 0, result.stderr
    assert attribution_git("ls-remote", remote, "refs/heads/main").stdout.split()[0] == attribution_git("rev-parse", "HEAD").stdout.strip()


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
