"""Aggressive local cleanup for Launcher branch instances.

This is the product cleanup path for the first-screen instance table. It is
intentionally broader than developer-mode ``worktree_cleanup``: dirty trees,
unmerged local commits, and running isolated instances may be removed after
an explicit confirm. ``main`` and the current checkout stay protected. Remote
refs are never deleted.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.infrastructure import git_process
from core.runtime_manager import instances_registry as registry
from core.runtime_manager.constants import PROJECT_ROOT

logger = logging.getLogger(__name__)

RISK_DISCARD_DIRTY = "discard_dirty"
RISK_STOP_THEN_REMOVE = "stop_then_remove"
RISK_DELETE_UNMERGED = "delete_unmerged"

PROTECTED_BRANCHES = frozenset({"main"})

StopRunner = Callable[[dict[str, Any]], dict[str, Any]]


class BranchInstanceCleanupError(RuntimeError):
    """Raised when a cleanup request is invalid before any instance is touched."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = str(code or "instance_cleanup_failed")
        self.message = str(message)
        self.status_code = int(status_code or 400)


def annotate_cleanup_metadata(
    payload: dict[str, Any],
    *,
    integration_root: Path | str | None = None,
    git_timeout: float = 15.0,
) -> dict[str, Any]:
    """Attach cleanup eligibility and risk codes to a branch-instance list."""

    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    root = Path(integration_root or payload.get("integrationRoot") or PROJECT_ROOT)
    heads = [str(item.get("head") or "").strip() for item in items if isinstance(item, dict)]
    merged_by_head = _merged_to_main_lookup(root, heads, timeout=git_timeout)
    for item in items:
        if not isinstance(item, dict):
            continue
        head = str(item.get("head") or "").strip()
        merged = bool(merged_by_head.get(head)) if head else False
        item["mergedToMain"] = merged
        item["cleanupEligible"] = cleanup_eligible(item)
        item["cleanupRisks"] = cleanup_risks(item, merged_to_main=merged)
    return payload


def cleanup_eligible(item: dict[str, Any]) -> bool:
    kind = str(item.get("kind") or "").strip()
    instance_id = str(item.get("id") or "").strip()
    branch = _normalize_branch(item.get("branch"))
    if instance_id == "main" or kind == "main":
        return False
    if item.get("current"):
        return False
    return branch not in PROTECTED_BRANCHES


def cleanup_risks(item: dict[str, Any], *, merged_to_main: bool) -> list[str]:
    risks: list[str] = []
    if item.get("dirty"):
        risks.append(RISK_DISCARD_DIRTY)
    if item.get("alive"):
        risks.append(RISK_STOP_THEN_REMOVE)
    has_local_commits = bool(str(item.get("head") or "").strip() or str(item.get("branch") or "").strip())
    if has_local_commits and not merged_to_main and str(item.get("kind") or "") != "retired":
        risks.append(RISK_DELETE_UNMERGED)
    return risks


def cleanup_branch_instances(
    instance_ids: Iterable[str],
    *,
    confirm: bool,
    stop_runner: StopRunner | None = None,
    list_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stop, detach, and delete the selected local instances after confirm."""

    if not confirm:
        raise BranchInstanceCleanupError("confirm_required", "清理需要确认。")
    wanted = [str(item).strip() for item in instance_ids if str(item or "").strip()]
    if not wanted:
        raise BranchInstanceCleanupError("instance_ids_required", "未指定要清理的分支实例。")

    # The list endpoint already computes optional cleanup metadata when the
    # caller asks for it.  Re-running the Git ancestry scan here is both
    # redundant and can exceed the native bridge's bounded request budget.
    payload = dict(list_payload or _list_instances())
    by_id = {
        str(item.get("id") or ""): dict(item)
        for item in payload.get("items") or []
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    root = Path(str(payload.get("integrationRoot") or PROJECT_ROOT))
    cleaned: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for instance_id in wanted:
        item = by_id.get(instance_id)
        if item is None:
            failed.append(_issue(instance_id, "instance_not_found", f"找不到分支实例：{instance_id}"))
            continue
        if not cleanup_eligible(item):
            skipped.append(_issue(instance_id, "instance_protected", "主分支和当前工作区不能清理。", item=item))
            continue
        try:
            result = _cleanup_one(item, root=root, stop_runner=stop_runner)
        except (OSError, RuntimeError) as exc:
            logger.warning("branch instance cleanup failed id=%s err=%s", instance_id, exc)
            failed.append(_issue(instance_id, "instance_cleanup_failed", str(exc), item=item))
            continue
        cleaned.append(result)

    logger.info(
        "branch instance cleanup confirm=%s cleaned=%s failed=%s skipped=%s",
        confirm,
        len(cleaned),
        len(failed),
        len(skipped),
    )
    return {
        "ok": not failed,
        "cleaned": cleaned,
        "failed": failed,
        "skipped": skipped,
    }


def _cleanup_one(
    item: dict[str, Any],
    *,
    root: Path,
    stop_runner: StopRunner | None,
) -> dict[str, Any]:
    actions: list[str] = []
    instance_id = str(item.get("id") or "")
    if item.get("alive"):
        runner = stop_runner or _default_stop_runner
        runner(item)
        actions.append("stopped")

    path_text = str(item.get("path") or "").strip()
    worktree = Path(path_text) if path_text else None
    if worktree is not None and (item.get("checkedOut") or worktree.exists()):
        _remove_worktree(root, worktree)
        actions.append("worktree_removed")

    branch = _normalize_branch(item.get("branch"))
    if (
        branch
        and branch not in PROTECTED_BRANCHES
        and not _branch_still_checked_out(root, branch)
        and _local_branch_exists(root, branch)
    ):
        _delete_local_branch(root, branch)
        actions.append("branch_deleted")

    if not _drop_registry_instance(instance_id):
        raise RuntimeError(f"清理实例注册表条目失败：{instance_id}")
    return {
        "id": instance_id,
        "branch": branch,
        "shortName": str(item.get("shortName") or branch or instance_id),
        "path": path_text,
        "actions": actions,
    }


def _default_stop_runner(item: dict[str, Any]) -> dict[str, Any]:
    from core.launcher.branch_instance_lifecycle import (
        BranchInstanceLifecycleError,
        run_isolated_operation,
    )

    try:
        return run_isolated_operation(item, "stop")
    except BranchInstanceLifecycleError:
        return run_isolated_operation(item, "force-stop")


def _remove_worktree(root: Path, worktree: Path) -> None:
    # A junction/symlink is a directory entry, not the checkout it targets.
    # Never resolve it before removal: resolving would make rmtree delete data
    # outside the managed pool and leave the link itself behind.
    if _is_reparse_point(worktree):
        _remove_directory(worktree)
        return
    resolved = worktree.resolve() if worktree.exists() else worktree
    if _is_registered_worktree(root, resolved):
        result = _run_git(root, "worktree", "remove", "--force", str(resolved), timeout=60.0)
        if result.returncode != 0 and _looks_locked(result):
            result = _run_git(
                root,
                "worktree",
                "remove",
                "--force",
                "--force",
                str(resolved),
                timeout=60.0,
            )
        if result.returncode != 0:
            detail = _git_detail(result)
            raise RuntimeError(f"拆除 worktree 失败：{detail or resolved}")
    if resolved.exists():
        _remove_directory(resolved)
    if resolved.exists():
        raise RuntimeError(f"worktree 目录仍存在：{resolved}")


def _remove_directory(path: Path) -> None:
    """Remove leftover checkout dirs, including Windows paths longer than MAX_PATH."""

    if _is_reparse_point(path):
        _remove_reparse_point(path)
        return
    target = path.resolve() if path.exists() else path
    if not os.path.lexists(str(target)):
        return
    shutil.rmtree(_os_remove_target(target), onexc=_clear_readonly)
    if os.path.lexists(str(target)):
        raise RuntimeError(f"worktree 目录仍存在：{target}")


def _is_reparse_point(path: Path) -> bool:
    """Return true for links/junctions without following their target."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and bool(is_junction()):
            return True
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def _remove_reparse_point(path: Path) -> None:
    """Remove only a symlink/junction entry, never its target."""

    if not os.path.lexists(str(path)):
        return
    raw_target = _os_remove_target(path, resolve=False)
    try:
        if path.is_symlink():
            path.unlink()
        else:
            os.rmdir(raw_target)
    except (FileNotFoundError, NotADirectoryError):
        path.unlink(missing_ok=True)
    except OSError:
        # Some Windows reparse points expose as a file to unlink rather than a
        # directory to rmdir. Either operation removes only the link itself.
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if os.path.lexists(str(path)):
        raise RuntimeError(f"无法移除 worktree 链接：{path}")


def _os_remove_target(path: Path, *, resolve: bool = True) -> str:
    text = str(path)
    if os.name != "nt":
        return text
    resolved = str(path.resolve()) if resolve else text
    if resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _clear_readonly(func, target: str, exc: BaseException) -> None:
    del exc
    try:
        os.chmod(target, stat.S_IWRITE)
        func(target)
    except OSError:
        return


def _delete_local_branch(root: Path, branch: str) -> None:
    result = _run_git(root, "branch", "-d", branch)
    if result.returncode == 0:
        return
    result = _run_git(root, "branch", "-D", branch)
    if result.returncode != 0:
        raise RuntimeError(f"删除本地分支失败：{_git_detail(result) or branch}")


def _drop_registry_instance(instance_id: str) -> bool:
    if not instance_id:
        return True

    def mutator(payload: dict[str, Any]) -> bool:
        instances = payload.get("instances")
        if isinstance(instances, dict):
            instances.pop(instance_id, None)
        return True

    try:
        # Registry updates must use the lock/CAS writer.  A load -> mutate ->
        # save sequence can race an Electron lifecycle observation and restore
        # a stale instance entry after it has been stopped.
        return bool(registry.mutate_registry(mutator))
    except (OSError, TimeoutError, TypeError, ValueError):
        logger.warning("failed to drop instance registry entry id=%s", instance_id)
        return False


def _list_instances() -> dict[str, Any]:
    from core.launcher.branch_instance_lifecycle import list_overlayed_branch_instances

    return list_overlayed_branch_instances()


def _merged_to_main(root: Path, head: str) -> bool:
    commit = str(head or "").strip()
    if not commit:
        return False
    return bool(_merged_to_main_lookup(root, [commit]).get(commit))


def _merged_to_main_lookup(
    root: Path,
    heads: Iterable[str],
    *,
    timeout: float = 15.0,
) -> dict[str, bool]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in heads:
        commit = str(raw or "").strip()
        if not commit or commit in seen:
            continue
        seen.add(commit)
        unique.append(commit)
    if not unique:
        return {}
    if not root.exists():
        return {commit: False for commit in unique}

    deadline = time.monotonic() + max(0.0, float(timeout))
    remaining_timeout = deadline - time.monotonic()
    if remaining_timeout <= 0:
        return {commit: False for commit in unique}
    merged_tips = _merged_main_tip_names(root, timeout=remaining_timeout)
    found: dict[str, bool] = {}
    remaining: list[str] = []
    for commit in unique:
        if _head_matches_merged_tip(commit, merged_tips):
            found[commit] = True
        else:
            remaining.append(commit)
    remaining_timeout = deadline - time.monotonic()
    if remaining and remaining_timeout > 0:
        found.update(
            _unique_commits_merged_to_main(
                root,
                remaining,
                timeout=remaining_timeout,
            )
        )
    else:
        for commit in remaining:
            found.setdefault(commit, False)
    return found


def _merged_main_tip_names(root: Path, *, timeout: float = 15.0) -> set[str]:
    result = _run_git(
        root,
        "for-each-ref",
        "--format=%(objectname)%09%(objectname:short)",
        "--merged=main",
        "refs/heads",
        timeout=timeout,
    )
    names: set[str] = set()
    if result.returncode != 0:
        return names
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        full, _, short = line.partition("\t")
        if full:
            names.add(full.casefold())
        if short:
            names.add(short.casefold())
    return names


def _head_matches_merged_tip(head: str, names: set[str]) -> bool:
    needle = str(head or "").strip().casefold()
    if not needle or len(needle) < 7:
        return needle in names
    if needle in names:
        return True
    for name in names:
        if len(name) < 7:
            continue
        if name.startswith(needle) or needle.startswith(name):
            return True
    return False


def _commit_is_ancestor_of_main(root: Path, commit: str, *, timeout: float = 15.0) -> bool:
    try:
        result = _run_git(root, "merge-base", "--is-ancestor", commit, "main", timeout=timeout)
    except Exception:
        return False
    return result.returncode == 0


def _unique_commits_merged_to_main(
    root: Path,
    commits: list[str],
    *,
    timeout: float = 15.0,
) -> dict[str, bool]:
    if len(commits) <= 1:
        return {commit: _commit_is_ancestor_of_main(root, commit, timeout=timeout) for commit in commits}

    found: dict[str, bool] = {}
    workers = min(8, len(commits))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_commit_is_ancestor_of_main, root, commit, timeout=timeout): commit
            for commit in commits
        }
        for future in as_completed(futures):
            commit = futures[future]
            try:
                found[commit] = bool(future.result())
            except Exception:
                found[commit] = False
    return found


def _local_branch_exists(root: Path, branch: str) -> bool:
    result = _run_git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return result.returncode == 0


def _branch_still_checked_out(root: Path, branch: str) -> bool:
    wanted = _normalize_branch(branch)
    for item in _worktree_entries(root):
        if _normalize_branch(item.get("branch")) == wanted:
            return True
    return False


def _is_registered_worktree(root: Path, worktree: Path) -> bool:
    wanted = _norm(worktree)
    return any(_norm(item.get("path")) == wanted for item in _worktree_entries(root))


def _worktree_entries(root: Path) -> list[dict[str, str]]:
    result = _run_git(root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                items.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                items.append(current)
            current = {"path": value.strip()}
        elif key == "HEAD":
            current["head"] = value.strip()
        elif key == "branch":
            current["branch"] = value.strip()
    if current:
        items.append(current)
    return items


def _run_git(root: Path, *args: str, timeout: float = 30.0):
    return git_process.run_git(
        list(args),
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )


def _looks_locked(result: Any) -> bool:
    text = _git_detail(result).lower()
    return "locked" in text or "is locked" in text


def _git_detail(result: Any) -> str:
    return str(getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()


def _normalize_branch(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("refs/heads/"):
        return text.removeprefix("refs/heads/")
    return text


def _norm(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).resolve()).replace("\\", "/").casefold()
    except OSError:
        return text.replace("\\", "/").casefold()


def _issue(instance_id: str, code: str, message: str, *, item: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "id": instance_id,
        "code": code,
        "message": message,
    }
    if item is not None:
        payload["branch"] = str(item.get("branch") or "")
        payload["shortName"] = str(item.get("shortName") or item.get("branch") or instance_id)
    return payload
