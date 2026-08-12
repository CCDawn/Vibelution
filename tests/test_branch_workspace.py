from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from core.infrastructure import branch_workspace as workspace
from core.infrastructure.branch_workspace import (
    BranchWorkspaceError,
    resolve_branch_workspace,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "workspace@example.local")
    _git(root, "config", "user.name", "Workspace Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    nested = root / "pkg"
    nested.mkdir()
    (nested / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def test_resolve_from_main_uses_in_repo_pool(tmp_path):
    project = _init_repo(tmp_path / "OtherApp")

    layout = resolve_branch_workspace(project)

    assert layout.role == "main"
    assert layout.slug == ""
    assert layout.integration_root == project.resolve()
    assert layout.branch_pool == project.resolve() / ".worktrees"
    assert layout.retired_pool == project.resolve() / ".worktrees" / "_retired"
    assert layout.legacy_sibling == tmp_path / "Vibelution-worktrees"


def test_three_checkouts_share_the_same_branch_pool(tmp_path):
    project = _init_repo(tmp_path / "OtherApp")
    in_pool = project / ".worktrees" / "feat-task"
    legacy_fixed = tmp_path / "Vibelution-worktrees" / "legacy-fixed"
    legacy_named = tmp_path / "OtherApp-worktrees" / "legacy-named"
    in_pool.parent.mkdir(parents=True)
    legacy_fixed.parent.mkdir(parents=True)
    legacy_named.parent.mkdir(parents=True)
    _git(project, "worktree", "add", "-b", "codex/feat-task", str(in_pool))
    _git(project, "worktree", "add", "-b", "codex/legacy-fixed", str(legacy_fixed))
    _git(project, "worktree", "add", "-b", "codex/legacy-named", str(legacy_named))

    from_main = resolve_branch_workspace(project)
    from_nested = resolve_branch_workspace(project / "pkg")
    from_task = resolve_branch_workspace(in_pool)
    from_legacy_fixed = resolve_branch_workspace(legacy_fixed)
    from_legacy_named = resolve_branch_workspace(legacy_named)

    pools = {
        from_main.branch_pool,
        from_nested.branch_pool,
        from_task.branch_pool,
        from_legacy_fixed.branch_pool,
        from_legacy_named.branch_pool,
    }
    roots = {
        from_main.integration_root,
        from_nested.integration_root,
        from_task.integration_root,
        from_legacy_fixed.integration_root,
        from_legacy_named.integration_root,
    }
    assert pools == {project.resolve() / ".worktrees"}
    assert roots == {project.resolve()}
    assert from_main.role == "main"
    assert from_nested.role == "main"
    assert from_task.role == "task"
    assert from_task.slug == "feat-task"
    assert from_legacy_fixed.role == "legacy_task"
    assert from_legacy_fixed.slug == "legacy-fixed"
    assert from_legacy_named.role == "legacy_task"
    assert from_legacy_named.slug == "legacy-named"


def test_retired_checkout_is_classified_but_not_a_task(tmp_path):
    project = _init_repo(tmp_path / "OtherApp")
    retired = project / ".worktrees" / "_retired" / "old-task"
    retired.parent.mkdir(parents=True)
    _git(project, "worktree", "add", "-b", "codex/old-task", str(retired))

    layout = resolve_branch_workspace(retired)

    assert layout.role == "retired"
    assert layout.slug == "old-task"
    assert layout.branch_pool == project.resolve() / ".worktrees"


def test_clone_without_extra_worktrees_still_points_at_in_repo_pool(tmp_path):
    project = _init_repo(tmp_path / "portable-clone")

    layout = resolve_branch_workspace(project)

    assert layout.branch_pool == project.resolve() / ".worktrees"
    assert not any(
        part.lower() == "desktop" for part in layout.branch_pool.parts
    )
    assert "Vibelution-worktrees" not in layout.branch_pool.parts


def test_missing_or_non_git_checkout_raises(tmp_path):
    missing = tmp_path / "missing"
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(BranchWorkspaceError, match="checkout 不存在"):
        resolve_branch_workspace(missing)
    with pytest.raises(BranchWorkspaceError, match="无法从"):
        resolve_branch_workspace(plain)


def test_resolver_source_does_not_hardcode_user_or_desktop_paths():
    source = inspect.getsource(workspace)
    assert "Path.home" not in source
    assert "expanduser" not in source
    assert "Desktop" not in source
    assert "Users\\" not in source
    assert "Users/" not in source
    assert "USERPROFILE" not in source
