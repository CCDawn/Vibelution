"""Resolve the portable in-repo branch workspace from any checkout.

The integration root is the Git common-dir parent. The only branch pool is
``<integration-root>/.worktrees``. Paths come from Git, never from a user
home directory or a hardcoded account name.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


def branch_pool_write_root(checkout: Path | str) -> Path:
    """Return the in-repo pool even when the checkout is not a Git worktree."""

    start = Path(checkout).resolve()
    if _nearest_git_dir(start) is None:
        pool = start / BRANCH_POOL_NAME
    else:
        try:
            pool = resolve_branch_workspace(start).branch_pool
        except BranchWorkspaceError:
            pool = start / BRANCH_POOL_NAME
    pool.mkdir(parents=True, exist_ok=True)
    return pool


def allowed_worktree_roots(checkout: Path | str) -> list[Path]:
    """Writable/legacy roots that may host task worktrees."""

    start = Path(checkout).resolve()
    if _nearest_git_dir(start) is None:
        roots = [
            start / BRANCH_POOL_NAME,
            start.parent / LEGACY_FIXED_SIBLING_NAME,
            start.parent / f"{start.name}-worktrees",
        ]
    else:
        try:
            layout = resolve_branch_workspace(start)
            roots = [layout.branch_pool, *layout.legacy_siblings]
        except BranchWorkspaceError:
            roots = [
                start / BRANCH_POOL_NAME,
                start.parent / LEGACY_FIXED_SIBLING_NAME,
                start.parent / f"{start.name}-worktrees",
            ]
    unique: list[Path] = []
    seen: set[str] = set()
    for item in roots:
        key = _norm(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def allocate_worktree_path(checkout: Path | str, slug: str) -> Path:
    pool = branch_pool_write_root(checkout)
    return (pool / _safe_slug(slug)).resolve()


def migrate_legacy_branch_workspaces(
    checkout: Path | str,
    *,
    skip_alive: bool = True,
) -> dict[str, Any]:
    """Move legacy sibling worktrees into ``.worktrees``; leftover shells go to ``_retired``."""

    layout = resolve_branch_workspace(checkout)
    layout.branch_pool.mkdir(parents=True, exist_ok=True)
    layout.retired_pool.mkdir(parents=True, exist_ok=True)
    moved: list[dict[str, str]] = []
    retired: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    registered_paths = {
        _norm(Path(str(entry.get("worktree") or "")))
        for entry in _registered_worktrees(layout.integration_root)
        if str(entry.get("worktree") or "").strip()
    }

    for entry in _registered_worktrees(layout.integration_root):
        source = Path(str(entry.get("worktree") or "")).resolve()
        if not str(source) or _same_path(source, layout.integration_root):
            continue
        if _is_relative_to(source, layout.branch_pool):
            continue
        if not any(_is_relative_to(source, sibling) for sibling in layout.legacy_siblings):
            skipped.append({"path": str(source), "reason": "not_legacy_sibling"})
            continue
        if skip_alive and bool(_runtime_observation(source).get("alive")):
            skipped.append({"path": str(source), "reason": "instance_alive"})
            continue
        slug = source.name
        destination = (layout.branch_pool / slug).resolve()
        if destination.exists():
            skipped.append({"path": str(source), "reason": "destination_exists", "destination": str(destination)})
            continue
        try:
            _run_git(
                layout.integration_root,
                "worktree",
                "move",
                str(source),
                str(destination),
            )
        except BranchWorkspaceError as exc:
            errors.append({"path": str(source), "reason": str(exc)})
            continue
        moved.append({"from": str(source), "to": str(destination), "slug": slug})

    for sibling in layout.legacy_siblings:
        if not sibling.is_dir():
            continue
        for child in sorted(sibling.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir() or child.name == RETIRED_DIR_NAME:
                continue
            if _norm(child) in registered_paths:
                continue
            if (child / ".git").exists():
                continue
            destination = (layout.retired_pool / child.name).resolve()
            if destination.exists():
                skipped.append({"path": str(child), "reason": "retired_destination_exists"})
                continue
            try:
                shutil.move(str(child), str(destination))
            except OSError as exc:
                errors.append({"path": str(child), "reason": str(exc)})
                continue
            retired.append({"from": str(child), "to": str(destination)})
        _write_legacy_pointer(sibling, layout.branch_pool)

    return {
        "schemaVersion": 1,
        "integrationRoot": str(layout.integration_root),
        "branchPool": str(layout.branch_pool),
        "moved": moved,
        "retired": retired,
        "skipped": skipped,
        "errors": errors,
    }


def list_branch_instances(checkout: Path | str) -> dict[str, Any]:
    """List Git-governed branch instances for the Launcher first screen."""

    layout = resolve_branch_workspace(checkout)
    current_root = layout.worktree_root
    worktrees = _registered_worktrees(layout.integration_root)
    checked_out_branches: set[str] = set()
    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()

    for entry in worktrees:
        path = Path(str(entry.get("worktree") or "")).resolve()
        if not str(path) or _norm(path) in seen_paths:
            continue
        seen_paths.add(_norm(path))
        role, slug = _classify_checkout(
            path,
            integration_root=layout.integration_root,
            branch_pool=layout.branch_pool,
            retired_pool=layout.retired_pool,
            legacy_siblings=layout.legacy_siblings,
        )
        branch = _display_branch(str(entry.get("branch") or ""))
        if str(entry.get("detached") or "") == "true" or not branch:
            branch = "detached"
        if branch != "detached":
            checked_out_branches.add(branch)
        head = _short_sha(str(entry.get("HEAD") or ""))
        kind = _instance_kind(role)
        instance_id = _instance_id(kind, slug=slug or path.name, branch=branch)
        dirty = _worktree_is_dirty(path)
        observation = _runtime_observation(path)
        item = _instance_payload(
            instance_id=instance_id,
            kind=kind,
            branch=branch,
            path=path,
            display_path=_display_path(path, layout.integration_root),
            head=head,
            current=_same_path(path, current_root),
            legacy=role == "legacy_task",
            dirty=dirty,
            checked_out=True,
            observation=observation,
        )
        items.append(item)
        seen_ids.add(instance_id)

    for branch, head in _local_branch_refs(layout.integration_root):
        if branch in checked_out_branches:
            continue
        instance_id = _instance_id("local_branch", branch=branch)
        if instance_id in seen_ids:
            continue
        items.append(
            _instance_payload(
                instance_id=instance_id,
                kind="local_branch",
                branch=branch,
                path=None,
                display_path="",
                head=head,
                current=False,
                legacy=False,
                dirty=False,
                checked_out=False,
                observation={},
            )
        )
        seen_ids.add(instance_id)

    for leftover in _unregistered_pool_dirs(layout):
        if _norm(leftover) in seen_paths:
            continue
        slug = leftover.name
        instance_id = _instance_id("retired", slug=slug)
        if instance_id in seen_ids:
            continue
        items.append(
            _instance_payload(
                instance_id=instance_id,
                kind="retired",
                branch="",
                path=leftover,
                display_path=_display_path(leftover, layout.integration_root),
                head="",
                current=False,
                legacy=_is_legacy_path(leftover, layout.legacy_siblings),
                dirty=False,
                checked_out=False,
                observation={},
            )
        )
        seen_ids.add(instance_id)

    items.sort(key=_instance_sort_key)
    current_id = next((item["id"] for item in items if item["current"]), "main")
    return {
        "schemaVersion": 1,
        "integrationRoot": str(layout.integration_root),
        "branchPool": str(layout.branch_pool),
        "currentId": current_id,
        "items": items,
    }


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


def _nearest_git_dir(start: Path) -> Path | None:
    current = Path(start).resolve()
    for _ in range(12):
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _norm(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _safe_slug(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or any(part in {"", ".", "..", RETIRED_DIR_NAME} for part in Path(raw).parts)
    ):
        raise BranchWorkspaceError(f"非法 worktree slug：{value or '<empty>'}")
    return Path(*Path(raw).parts).as_posix()


def _run_git(checkout: Path, *args: str) -> str:
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
            f"无法从 {checkout} 执行 Git {' '.join(args)}：{detail or 'git command failed'}"
        )
    return str(result.stdout or "").strip()


def _write_legacy_pointer(sibling: Path, branch_pool: Path) -> None:
    remaining = [item for item in sibling.iterdir() if item.name not in {"MOVED.txt", "README.txt"}]
    if remaining:
        return
    notice = (
        "This legacy sibling worktree folder is no longer the write target.\n"
        f"New checkouts belong in: {branch_pool}\n"
    )
    (sibling / "MOVED.txt").write_text(notice, encoding="utf-8")


def _registered_worktrees(integration_root: Path) -> list[dict[str, str]]:
    result = git_process.run_git(
        ["worktree", "list", "--porcelain"],
        cwd=str(integration_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise BranchWorkspaceError(f"无法列出 worktree：{detail or 'git worktree list failed'}")
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if " " not in line:
            current[line] = "true"
            continue
        key, value = line.split(" ", 1)
        current[key] = value.strip()
    if current:
        entries.append(current)
    return entries


def _local_branch_refs(integration_root: Path) -> list[tuple[str, str]]:
    result = git_process.run_git(
        ["for-each-ref", "--format=%(refname:short)%09%(objectname:short)", "refs/heads"],
        cwd=str(integration_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise BranchWorkspaceError(f"无法列出本地分支：{detail or 'git for-each-ref failed'}")
    refs: list[tuple[str, str]] = []
    for raw_line in str(result.stdout or "").splitlines():
        name, separator, head = raw_line.partition("\t")
        if not separator:
            name, _, head = raw_line.partition(" ")
        name = name.strip()
        head = head.strip()
        if name:
            refs.append((name, head))
    return refs


def _unregistered_pool_dirs(layout: BranchWorkspaceLayout) -> list[Path]:
    leftovers: list[Path] = []
    roots = [layout.branch_pool, *layout.legacy_siblings]
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            if child.name == RETIRED_DIR_NAME:
                for retired in sorted(child.iterdir(), key=lambda item: item.name.lower()):
                    if retired.is_dir() and not (retired / ".git").exists():
                        leftovers.append(retired.resolve())
                continue
            if (child / ".git").exists():
                continue
            leftovers.append(child.resolve())
    return leftovers


def _worktree_is_dirty(path: Path) -> bool:
    result = git_process.run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=no"],
        cwd=str(path),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return True
    return bool(result.stdout)


def _runtime_observation(path: Path) -> dict[str, Any]:
    launcher_state = _read_json(path / ".runtime" / "launcher" / "state.json")
    manager_state = _read_json(path / ".runtime" / "runtime-manager" / "state.json")
    workbench = launcher_state.get("workbench") if isinstance(launcher_state.get("workbench"), dict) else {}
    observed_state = str(
        workbench.get("observedState")
        or launcher_state.get("observedState")
        or manager_state.get("runtimeState")
        or ""
    ).strip()
    backend_port = _positive_int(
        workbench.get("backendPort") or launcher_state.get("backendPort") or launcher_state.get("launcherControlPort")
    )
    pids = {
        "backend": _positive_int(workbench.get("backendPid") or launcher_state.get("backendPid")),
        "window": _positive_int(
            workbench.get("browserWindowPid")
            or launcher_state.get("browserWindowPid")
            or launcher_state.get("windowPid")
        ),
        "manager": _positive_int(manager_state.get("managerPid") or launcher_state.get("managerPid")),
    }
    alive = observed_state.lower() in {"open", "running", "healthy"} or any(pids.values())
    return {
        "observedState": observed_state,
        "port": backend_port,
        "pids": pids,
        "alive": alive,
    }


def _instance_payload(
    *,
    instance_id: str,
    kind: str,
    branch: str,
    path: Path | None,
    display_path: str,
    head: str,
    current: bool,
    legacy: bool,
    dirty: bool,
    checked_out: bool,
    observation: dict[str, Any],
) -> dict[str, Any]:
    pids = observation.get("pids") if isinstance(observation.get("pids"), dict) else {}
    alive = bool(observation.get("alive"))
    return {
        "id": instance_id,
        "kind": kind,
        "branch": branch,
        "path": str(path) if path is not None else "",
        "displayPath": display_path,
        "head": head,
        "current": current,
        "legacy": legacy,
        "dirty": dirty,
        "checkedOut": checked_out,
        "alive": alive,
        "observedState": str(observation.get("observedState") or ""),
        "port": int(observation.get("port") or 0),
        "pids": {
            "backend": int(pids.get("backend") or 0),
            "window": int(pids.get("window") or 0),
            "manager": int(pids.get("manager") or 0),
        },
        "promotable": kind == "worktree" and checked_out and bool(head) and not dirty,
    }


def _instance_id(kind: str, *, slug: str = "", branch: str = "") -> str:
    if kind == "main":
        return "main"
    if kind == "worktree":
        return f"worktree:{slug or branch or 'detached'}"
    if kind == "retired":
        return f"retired:{slug or 'unknown'}"
    return f"branch:{branch or 'unnamed'}"


def _instance_kind(role: CheckoutRole) -> str:
    if role == "main":
        return "main"
    if role == "retired":
        return "retired"
    return "worktree"


def _display_branch(branch_ref: str) -> str:
    text = str(branch_ref or "").strip()
    if text.startswith("refs/heads/"):
        return text.removeprefix("refs/heads/")
    return text


def _display_path(path: Path, integration_root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(integration_root.resolve())
        return "." if str(relative) == "." else relative.as_posix()
    except ValueError:
        pass
    try:
        relative = resolved.relative_to(integration_root.parent.resolve())
        return f"../{relative.as_posix()}"
    except ValueError:
        return resolved.as_posix()


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def _positive_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_legacy_path(path: Path, legacy_siblings: tuple[Path, ...]) -> bool:
    return any(_is_relative_to(path, sibling) for sibling in legacy_siblings)


def _instance_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    kind_rank = {"main": 0, "worktree": 1, "local_branch": 2, "retired": 3}.get(str(item.get("kind") or ""), 9)
    alive_rank = 0 if item.get("alive") else 1
    return (kind_rank, alive_rank, str(item.get("branch") or item.get("id") or "").lower())
