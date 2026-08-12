"""Resolve the portable in-repo branch workspace from any checkout.

The integration root is the Git common-dir parent. The only branch pool is
``<integration-root>/.worktrees``. Paths come from Git, never from a user
home directory or a hardcoded account name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.infrastructure import git_process

BRANCH_POOL_NAME = ".worktrees"
RETIRED_DIR_NAME = "_retired"
LEGACY_FIXED_SIBLING_NAME = "Vibelution-worktrees"

CheckoutRole = Literal["main", "task", "legacy_task", "retired", "unknown"]


class BranchWorkspaceError(RuntimeError):
    """Raised when a checkout cannot be resolved to a Git-backed workspace."""


@dataclass(frozen=True)
class BranchWorkspaceLayout:
    checkout: Path
    worktree_root: Path
    integration_root: Path
    git_common_dir: Path
    branch_pool: Path
    retired_pool: Path
    legacy_siblings: tuple[Path, ...]
    role: CheckoutRole
    slug: str

    @property
    def legacy_sibling(self) -> Path:
        return self.legacy_siblings[0]


def resolve_branch_workspace(checkout: Path | str) -> BranchWorkspaceLayout:
    """Resolve the branch-workspace layout for any path inside a checkout."""

    raw = Path(checkout)
    if not raw.exists():
        raise BranchWorkspaceError(f"checkout 不存在：{raw}")
    start = raw.resolve() if raw.is_dir() else raw.parent.resolve()
    worktree_root = _git_path(start, "rev-parse", "--show-toplevel")
    git_common_dir = _resolve_git_common_dir(start)
    integration_root = (
        git_common_dir.parent if git_common_dir.name == ".git" else git_common_dir
    )
    branch_pool = integration_root / BRANCH_POOL_NAME
    retired_pool = branch_pool / RETIRED_DIR_NAME
    legacy_siblings = _legacy_sibling_roots(integration_root)
    role, slug = _classify_checkout(
        worktree_root,
        integration_root=integration_root,
        branch_pool=branch_pool,
        retired_pool=retired_pool,
        legacy_siblings=legacy_siblings,
    )
    return BranchWorkspaceLayout(
        checkout=start,
        worktree_root=worktree_root,
        integration_root=integration_root,
        git_common_dir=git_common_dir,
        branch_pool=branch_pool,
        retired_pool=retired_pool,
        legacy_siblings=legacy_siblings,
        role=role,
        slug=slug,
    )


def branch_pool_path(checkout: Path | str) -> Path:
    return resolve_branch_workspace(checkout).branch_pool


def _legacy_sibling_roots(integration_root: Path) -> tuple[Path, ...]:
    parent = integration_root.parent
    roots = (
        parent / LEGACY_FIXED_SIBLING_NAME,
        parent / f"{integration_root.name}-worktrees",
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = _norm(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return tuple(unique)


def _classify_checkout(
    worktree_root: Path,
    *,
    integration_root: Path,
    branch_pool: Path,
    retired_pool: Path,
    legacy_siblings: tuple[Path, ...],
) -> tuple[CheckoutRole, str]:
    if _same_path(worktree_root, integration_root):
        return "main", ""
    if _is_relative_to(worktree_root, retired_pool):
        return "retired", _relative_slug(worktree_root, retired_pool)
    if _is_relative_to(worktree_root, branch_pool):
        return "task", _relative_slug(worktree_root, branch_pool)
    for sibling in legacy_siblings:
        if _is_relative_to(worktree_root, sibling):
            return "legacy_task", _relative_slug(worktree_root, sibling)
    return "unknown", ""


def _relative_slug(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_git_common_dir(checkout: Path) -> Path:
    raw = _git_text(checkout, "rev-parse", "--git-common-dir")
    common = Path(raw)
    if not common.is_absolute():
        common = checkout / common
    return common.resolve()


def _git_path(checkout: Path, *args: str) -> Path:
    return Path(_git_text(checkout, *args)).resolve()


def _git_text(checkout: Path, *args: str) -> str:
    result = git_process.run_git(
        list(args),
        cwd=str(checkout),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise BranchWorkspaceError(
            f"无法从 {checkout} 解析 Git 工作区：{detail or 'git command failed'}"
        )
    value = str(result.stdout or "").strip()
    if not value:
        raise BranchWorkspaceError(f"Git {' '.join(args)} 返回空路径：{checkout}")
    return value


def _same_path(left: Path, right: Path) -> bool:
    return _norm(left) == _norm(right)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _norm(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))
