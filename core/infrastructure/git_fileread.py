"""Pure file-read Git identity and layout, spawning no git process.

Short-lived launcher bridge processes pay four git children per state refresh
just to learn HEAD, the current branch, the worktree root and the common dir.
All four facts are plain files under the Git directory: ``.git/HEAD`` names the
checked-out ref (or the detached commit), loose ``refs/heads/<name>`` files
hold the commit, and a linked worktree's ``.git`` pointer plus ``commondir``
file locate the shared Git directory.

Semantics follow ``core.web.services.code_freshness._read_git_head_text``;
this module adds the branch name and the worktree-root/common-dir layout on
top of the same file-reading rules, without importing the web service stack
(launcher bridge processes must stay dependency-light).

Every function returns ``None`` instead of raising: any state that cannot be
derived with confidence (refs that only exist in ``packed-refs``, a missing or
invalid ``.git`` pointer, a read racing a ref update, GIT_DIR-style env
overrides, cwd inside a Git dir) sends the caller back to the authoritative
``git`` command path.  A ``None`` is "unknown", never an error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# These env overrides change Git's repository discovery; a filesystem walk can
# disagree with ``git rev-parse`` under them, so the fast path steps aside.
_DISCOVERY_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
_SHA_LENGTHS = (40, 64)
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class GitFileLayout:
    """Worktree layout derived from ``.git`` entries alone."""

    worktree_root: Path  # ``git rev-parse --show-toplevel``
    git_dir: Path  # ``git rev-parse --git-dir`` (per-worktree)
    git_common_dir: Path  # ``git rev-parse --git-common-dir``


def read_git_identity(workspace_root: Path | str) -> dict[str, str] | None:
    """Return ``{"headCommit", "branchName"}`` with zero git processes.

    ``branchName`` is ``""`` on a detached HEAD (the caller decides how to
    render it, e.g. launcher freshness keeps its existing "HEAD" mapping).
    ``None`` means "cannot be derived from files" — callers fall back to their
    git-command path; this never raises and never returns a partial answer.
    """

    layout = read_git_layout(workspace_root)
    if layout is None:
        return None
    head = _read_git_text(layout.git_dir / "HEAD")
    if not head:
        return None
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        commit = _read_loose_ref(ref, layout) if ref.startswith("refs/") else None
        if commit is None:
            return None
        branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ""
        return {"headCommit": commit, "branchName": branch}
    if not _is_commit_sha(head):
        return None
    return {"headCommit": head, "branchName": ""}


def read_git_layout(start: Path | str) -> GitFileLayout | None:
    """Walk up from ``start`` to the enclosing checkout, reading ``.git`` entries.

    ``None`` when the layout cannot be derived: no ``.git`` entry above
    ``start``, ``start`` sits inside a Git dir, or an entry fails validation —
    the caller then falls back to ``git rev-parse`` for the authoritative
    answer (including its error, when git itself cannot resolve the path).
    """

    if any(os.environ.get(name) for name in _DISCOVERY_ENV_OVERRIDES):
        return None
    try:
        current = Path(start).resolve()
    except OSError:
        return None
    while True:
        if current.name == ".git":
            # Inside a Git dir (or a nested checkout metadata path): git
            # reports no work tree here, so a parent-based answer would lie.
            return None
        found, git_dir = _git_dir_at(current)
        if found:
            if git_dir is None:
                return None
            common_dir = _common_dir_of(git_dir)
            if common_dir is None:
                return None
            return GitFileLayout(
                worktree_root=current,
                git_dir=git_dir,
                git_common_dir=common_dir,
            )
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _git_dir_at(worktree_root: Path) -> tuple[bool, Path | None]:
    """Classify the ``.git`` entry of ``worktree_root``.

    ``(False, None)``: no ``.git`` entry here — keep walking up.
    ``(True, git_dir)``: a validated per-worktree Git directory.
    ``(True, None)``: an entry exists but cannot be validated — give up so the
    caller falls back to git (which may still resolve it or report its own
    error), instead of trusting a partially read state.
    """

    entry = worktree_root / ".git"
    try:
        if entry.is_dir():
            git_dir = entry
        elif entry.is_file():
            text = _read_git_text(entry)
            if text is None or not text.lower().startswith("gitdir:"):
                return True, None
            pointer = text.split(":", 1)[1].strip()
            if not pointer:
                return True, None
            git_dir = Path(pointer)
            if not git_dir.is_absolute():
                git_dir = worktree_root / git_dir
        else:
            return False, None
        git_dir = git_dir.resolve()
        if not (git_dir / "HEAD").is_file():
            return True, None
        return True, git_dir
    except OSError:
        return True, None


def _common_dir_of(git_dir: Path) -> Path | None:
    """Resolve the shared Git directory (``commondir`` pointer in linked worktrees)."""

    pointer = git_dir / "commondir"
    try:
        if not pointer.is_file():
            return git_dir
        text = _read_git_text(pointer)
        if not text:
            return None
        common = Path(text)
        if not common.is_absolute():
            common = git_dir / common
        common = common.resolve()
        if not common.is_dir():
            return None
        return common
    except OSError:
        return None


def _read_loose_ref(ref: str, layout: GitFileLayout) -> str | None:
    """Resolve a full ref name against loose ref files only.

    Linked worktrees keep shared refs (``refs/heads/...``) in the common dir
    while per-worktree refs (``refs/bisect``, ``refs/worktree``) live in the
    per-worktree Git dir; both candidates are tried, Git dir first.  A ref that
    only exists in ``packed-refs`` — or whose file content is not a plain
    commit (symbolic ref chain, ref update racing the read) — is not
    resolvable here and returns ``None``.
    """

    for base in (layout.git_dir, layout.git_common_dir):
        candidate = base.joinpath(*ref.split("/"))
        try:
            if not candidate.is_file():
                continue
        except OSError:
            return None
        text = _read_git_text(candidate)
        if not _is_commit_sha(text or ""):
            return None
        return text
    return None


def _read_git_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _is_commit_sha(text: str) -> bool:
    return len(text) in _SHA_LENGTHS and set(text) <= _HEX_DIGITS
