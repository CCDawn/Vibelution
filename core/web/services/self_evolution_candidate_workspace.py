"""Owned Git worktree lifecycle for autonomous self-evolution candidates."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

from core.infrastructure import git_process


BRANCH_PREFIX = "codex/self-evolution-"
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class CandidateWorkspaceError(RuntimeError):
    """Raised when a candidate worktree cannot be managed safely."""


def create_candidate_workspace(
    project_root: Path,
    *,
    run_id: str,
    worktree_root: Path | None = None,
) -> dict[str, Any]:
    """Create one named candidate branch from a clean local main."""

    root = Path(project_root).resolve()
    normalized_run_id = _normalize_run_id(run_id)
    _require_git_root(root)
    branch = _git_text(root, "branch", "--show-current")
    if branch != "main":
        raise CandidateWorkspaceError(
            f"Candidate creation requires local main; current branch is {branch or 'detached'}."
        )
    if _git_bytes(root, "status", "--porcelain=v1", "-z"):
        raise CandidateWorkspaceError(
            "Candidate creation requires a completely clean main worktree."
        )
    base_commit = _git_text(root, "rev-parse", "HEAD")
    candidate_branch = f"{BRANCH_PREFIX}{normalized_run_id}"
    if _branch_exists(root, candidate_branch):
        raise CandidateWorkspaceError(
            f"Candidate branch already exists: {candidate_branch}"
        )

    candidates_root = Path(
        worktree_root or root.parent / f"{root.name}-worktrees"
    ).resolve()
    if candidates_root == root or _is_relative_to(candidates_root, root):
        raise CandidateWorkspaceError(
            "Candidate worktree root must stay outside the project root."
        )
    candidate_path = (candidates_root / f"self-evolution-{normalized_run_id}").resolve()
    if candidate_path.exists():
        raise CandidateWorkspaceError(
            f"Candidate worktree path already exists: {candidate_path}"
        )
    candidates_root.mkdir(parents=True, exist_ok=True)

    result = _run_git(
        root,
        "worktree",
        "add",
        "-b",
        candidate_branch,
        str(candidate_path),
        base_commit,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise CandidateWorkspaceError(
            f"Candidate worktree creation failed: {detail or 'unknown error'}"
        )
    if not candidate_path.is_dir():
        raise CandidateWorkspaceError(
            "Git reported success but candidate worktree is missing."
        )
    return {
        "branch": candidate_branch,
        "worktreePath": str(candidate_path),
        "baseCommit": base_commit,
    }


def inspect_candidate_workspace(
    project_root: Path,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the candidate file set and content-derived variant identity."""

    root = Path(project_root).resolve()
    candidate_path, branch = _require_owned_workspace(root, workspace)
    changed_files = _candidate_changes(candidate_path)
    head_commit = _git_text(candidate_path, "rev-parse", "HEAD")
    base_commit = str(workspace.get("baseCommit") or "").strip()
    digest = hashlib.sha256()
    digest.update(base_commit.encode("utf-8"))
    digest.update(b"\0")
    for item in changed_files:
        relative = str(item["path"])
        change_type = str(item["changeType"])
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(change_type.encode("utf-8"))
        digest.update(b"\0")
        if change_type != "deleted":
            source = _safe_candidate_path(candidate_path, relative)
            if source.is_symlink() or not source.is_file():
                raise CandidateWorkspaceError(
                    f"Candidate path is not a regular file: {relative}"
                )
            digest.update(source.read_bytes())
        digest.update(b"\0")
    return {
        "branch": branch,
        "headCommit": head_commit,
        "changedFiles": changed_files,
        "variantId": f"sha256:{digest.hexdigest()}" if changed_files else "",
    }


def cleanup_candidate_workspace(
    project_root: Path,
    workspace: dict[str, Any],
    *,
    integration: dict[str, Any],
) -> dict[str, Any]:
    """Remove only the locally owned candidate after a verified Git commit."""

    root = Path(project_root).resolve()
    if str(integration.get("status") or "").strip() != "committed":
        raise CandidateWorkspaceError(
            "Candidate cleanup requires a committed integration."
        )
    commit_sha = str(integration.get("commitSha") or "").strip()
    if not commit_sha or _git_text(root, "rev-parse", "HEAD") != commit_sha:
        raise CandidateWorkspaceError(
            "Candidate cleanup requires the integration commit at main HEAD."
        )
    if _git_text(root, "branch", "--show-current") != "main":
        raise CandidateWorkspaceError(
            "Candidate cleanup requires local main."
        )
    if _git_bytes(root, "status", "--porcelain=v1", "-z"):
        raise CandidateWorkspaceError(
            "Candidate cleanup requires a clean integrated main."
        )

    candidate_path, branch = _require_owned_workspace(root, workspace)
    remove_result = _run_git(
        root,
        "worktree",
        "remove",
        "--force",
        str(candidate_path),
    )
    if remove_result.returncode != 0:
        detail = str(remove_result.stderr or remove_result.stdout or "").strip()
        raise CandidateWorkspaceError(
            f"Candidate worktree removal failed: {detail or 'unknown error'}"
        )
    if candidate_path.exists():
        raise CandidateWorkspaceError(
            "Candidate worktree still exists after Git removal."
        )

    branch_result = _run_git(root, "branch", "-D", branch)
    if branch_result.returncode != 0:
        detail = str(branch_result.stderr or branch_result.stdout or "").strip()
        raise CandidateWorkspaceError(
            f"Candidate local branch deletion failed: {detail or 'unknown error'}"
        )
    if _branch_exists(root, branch):
        raise CandidateWorkspaceError(
            "Candidate local branch still exists after deletion."
        )
    return {
        "status": "cleaned",
        "worktreeRemoved": True,
        "localBranchDeleted": True,
    }


def _candidate_changes(candidate_path: Path) -> list[dict[str, str]]:
    raw = _git_bytes(
        candidate_path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    records = raw.split(b"\0")
    changes: dict[str, str] = {}
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", errors="replace")
        if len(text) < 4:
            raise CandidateWorkspaceError("Candidate Git status is malformed.")
        status = text[:2]
        path = _normalize_relative_path(text[3:])
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise CandidateWorkspaceError(
                    "Candidate rename status is missing its source path."
                )
            source_path = _normalize_relative_path(
                records[index].decode("utf-8", errors="replace")
            )
            index += 1
            changes[source_path] = "deleted"
            changes[path] = "added"
        elif status == "??" or "A" in status:
            changes[path] = "added"
        elif "D" in status:
            changes[path] = "deleted"
        else:
            changes[path] = "modified"
    return [
        {"path": path, "changeType": changes[path]}
        for path in sorted(changes)
    ]


def _require_owned_workspace(
    root: Path,
    workspace: dict[str, Any],
) -> tuple[Path, str]:
    branch = str(workspace.get("branch") or "").strip()
    if not branch.startswith(BRANCH_PREFIX):
        raise CandidateWorkspaceError(
            "Candidate cleanup and inspection require an owned local branch."
        )
    raw_path = str(workspace.get("worktreePath") or "").strip()
    if not raw_path:
        raise CandidateWorkspaceError("Candidate worktreePath is missing.")
    candidate_path = Path(raw_path).resolve()
    if candidate_path == root or _is_relative_to(candidate_path, root):
        raise CandidateWorkspaceError(
            "Candidate worktree must stay outside the project root."
        )
    registered = _registered_worktrees(root)
    registered_branch = registered.get(candidate_path)
    if registered_branch != branch:
        raise CandidateWorkspaceError(
            "Candidate worktree is not registered to the owned local branch."
        )
    if not candidate_path.is_dir():
        raise CandidateWorkspaceError("Candidate worktree directory is missing.")
    return candidate_path, branch


def _registered_worktrees(root: Path) -> dict[Path, str]:
    text = _git_text(root, "worktree", "list", "--porcelain")
    result: dict[Path, str] = {}
    current_path: Path | None = None
    current_branch = ""
    for line in [*text.splitlines(), ""]:
        if line.startswith("worktree "):
            if current_path is not None:
                result[current_path] = current_branch
            current_path = Path(line[len("worktree ") :]).resolve()
            current_branch = ""
        elif line.startswith("branch refs/heads/"):
            current_branch = line[len("branch refs/heads/") :]
        elif not line and current_path is not None:
            result[current_path] = current_branch
            current_path = None
            current_branch = ""
    return result


def _normalize_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not _SAFE_RUN_ID_RE.fullmatch(value):
        raise CandidateWorkspaceError("Invalid self-evolution run id.")
    return value


def _normalize_relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or raw.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CandidateWorkspaceError(
            f"Candidate path is unsafe: {raw or '<empty>'}"
        )
    return path.as_posix()


def _safe_candidate_path(root: Path, relative: str) -> Path:
    target = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if not _is_relative_to(target, root):
        raise CandidateWorkspaceError(
            f"Candidate path escapes worktree: {relative}"
        )
    return target


def _require_git_root(root: Path) -> None:
    git_root = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve()
    if not root.is_dir() or git_root != root:
        raise CandidateWorkspaceError(
            "Candidate project_root must be the Git worktree root."
        )


def _branch_exists(root: Path, branch: str) -> bool:
    return (
        _run_git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ).returncode
        == 0
    )


def _run_git(root: Path, *args: str):
    return git_process.run_git(
        list(args),
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_text(root: Path, *args: str) -> str:
    result = _run_git(root, *args)
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise CandidateWorkspaceError(
            f"Git {' '.join(args)} failed: {detail or 'unknown error'}"
        )
    return str(result.stdout or "").strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = git_process.run_git(
        list(args),
        cwd=str(root),
        capture_output=True,
        text=False,
        check=False,
    )
    if result.returncode != 0:
        detail = bytes(result.stderr or result.stdout or b"").decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise CandidateWorkspaceError(
            f"Git {' '.join(args)} failed: {detail or 'unknown error'}"
        )
    return bytes(result.stdout or b"")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
