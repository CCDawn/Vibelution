from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.web.services.self_evolution_candidate_workspace import (
    CandidateWorkspaceError,
    cleanup_candidate_workspace,
    create_candidate_workspace,
    inspect_candidate_workspace,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Self Evolution Test")
    _git(root, "config", "user.email", "self-evolution@example.invalid")
    (root / "kept.txt").write_text("before\n", encoding="utf-8")
    (root / "deleted.txt").write_text("remove\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def test_candidate_workspace_is_named_branch_from_clean_main(tmp_path):
    root = _repo(tmp_path)

    workspace = create_candidate_workspace(
        root,
        run_id="self-loop-001",
        worktree_root=tmp_path / "candidates",
    )

    candidate = Path(workspace["worktreePath"])
    assert candidate.is_dir()
    assert workspace["branch"] == "codex/self-evolution-self-loop-001"
    assert workspace["baseCommit"] == _git(root, "rev-parse", "HEAD")
    assert _git(candidate, "branch", "--show-current") == workspace["branch"]
    assert _git(candidate, "status", "--short") == ""


def test_candidate_inspection_freezes_added_modified_and_deleted_files(tmp_path):
    root = _repo(tmp_path)
    workspace = create_candidate_workspace(
        root,
        run_id="self-loop-002",
        worktree_root=tmp_path / "candidates",
    )
    candidate = Path(workspace["worktreePath"])
    (candidate / "kept.txt").write_text("after\n", encoding="utf-8")
    (candidate / "added.txt").write_text("new\n", encoding="utf-8")
    (candidate / "deleted.txt").unlink()

    first = inspect_candidate_workspace(root, workspace)
    second = inspect_candidate_workspace(root, workspace)

    assert first == second
    assert first["headCommit"] == workspace["baseCommit"]
    assert first["variantId"].startswith("sha256:")
    assert first["changedFiles"] == [
        {"path": "added.txt", "changeType": "added"},
        {"path": "deleted.txt", "changeType": "deleted"},
        {"path": "kept.txt", "changeType": "modified"},
    ]


def test_candidate_inspection_includes_agent_commits_on_owned_branch(tmp_path):
    root = _repo(tmp_path)
    workspace = create_candidate_workspace(
        root,
        run_id="self-loop-committed",
        worktree_root=tmp_path / "candidates",
    )
    candidate = Path(workspace["worktreePath"])
    (candidate / "kept.txt").write_text("committed candidate\n", encoding="utf-8")
    _git(candidate, "add", "kept.txt")
    _git(candidate, "commit", "-m", "candidate implementation")

    inspection = inspect_candidate_workspace(root, workspace)

    assert inspection["headCommit"] != workspace["baseCommit"]
    assert inspection["changedFiles"] == [
        {"path": "kept.txt", "changeType": "modified"},
    ]
    assert inspection["variantId"].startswith("sha256:")


def test_candidate_creation_rejects_dirty_or_non_main_target(tmp_path):
    root = _repo(tmp_path)
    (root / "kept.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError, match="clean"):
        create_candidate_workspace(
            root,
            run_id="self-loop-003",
            worktree_root=tmp_path / "candidates",
        )

    _git(root, "restore", "kept.txt")
    _git(root, "switch", "-c", "feature")

    with pytest.raises(CandidateWorkspaceError, match="main"):
        create_candidate_workspace(
            root,
            run_id="self-loop-003",
            worktree_root=tmp_path / "candidates",
        )


def test_cleanup_requires_committed_integration_and_deletes_only_local_candidate(tmp_path):
    root = _repo(tmp_path)
    workspace = create_candidate_workspace(
        root,
        run_id="self-loop-004",
        worktree_root=tmp_path / "candidates",
    )
    candidate = Path(workspace["worktreePath"])
    (candidate / "kept.txt").write_text("after\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError, match="committed integration"):
        cleanup_candidate_workspace(
            root,
            workspace,
            integration={"status": "failed"},
        )

    assert candidate.exists()
    assert _git(root, "branch", "--list", workspace["branch"])

    (root / "kept.txt").write_text("after\n", encoding="utf-8")
    _git(root, "add", "kept.txt")
    _git(root, "commit", "-m", "integrate candidate")
    commit_sha = _git(root, "rev-parse", "HEAD")

    cleanup = cleanup_candidate_workspace(
        root,
        workspace,
        integration={"status": "committed", "commitSha": commit_sha},
    )

    assert cleanup == {
        "status": "cleaned",
        "worktreeRemoved": True,
        "localBranchDeleted": True,
    }
    assert not candidate.exists()
    assert _git(root, "branch", "--list", workspace["branch"]) == ""


def test_cleanup_refuses_unowned_branch_or_unregistered_worktree(tmp_path):
    root = _repo(tmp_path)
    workspace = {
        "branch": "feature/unowned",
        "worktreePath": str(tmp_path / "not-a-worktree"),
        "baseCommit": _git(root, "rev-parse", "HEAD"),
    }

    with pytest.raises(CandidateWorkspaceError, match="owned"):
        cleanup_candidate_workspace(
            root,
            workspace,
            integration={
                "status": "committed",
                "commitSha": _git(root, "rev-parse", "HEAD"),
            },
        )
