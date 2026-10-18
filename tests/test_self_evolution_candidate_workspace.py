from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core.web.services import self_evolution_candidate_workspace as candidate_workspace
from core.web.services.self_evolution_candidate_workspace import (
    CandidateWorkspaceError,
    cleanup_candidate_workspace,
    create_candidate_workspace,
    inspect_candidate_workspace,
)


@pytest.fixture(autouse=True)
def isolate_git_environment(monkeypatch):
    # Real temporary repositories must never inherit this checkout's Git state.
    for key in list(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


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


def test_candidate_workspace_defaults_to_in_repo_branch_pool(tmp_path):
    root = _repo(tmp_path)

    workspace = create_candidate_workspace(root, run_id="self-loop-pool")

    candidate = Path(workspace["worktreePath"])
    assert candidate == (root / ".worktrees" / "self-evolution-self-loop-pool").resolve()
    assert candidate.is_dir()


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

    _git(candidate, "add", "kept.txt")
    _git(candidate, "commit", "-m", "candidate implementation")
    _git(root, "merge", "--ff-only", workspace["branch"])
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


def _integrated_candidate(tmp_path):
    root = _repo(tmp_path)
    workspace = create_candidate_workspace(
        root, run_id="cleanup", worktree_root=tmp_path / "candidates"
    )
    candidate = Path(workspace["worktreePath"])
    (candidate / "kept.txt").write_text("candidate\n", encoding="utf-8")
    _git(candidate, "add", "kept.txt")
    _git(candidate, "commit", "-m", "candidate")
    _git(root, "merge", "--ff-only", workspace["branch"])
    integration = {"status": "committed", "commitSha": _git(root, "rev-parse", "HEAD")}
    return root, workspace, candidate, integration


def test_cleanup_allows_main_to_advance_and_is_idempotent(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    _git(root, "commit", "--allow-empty", "-m", "later main work")

    for _ in range(2):
        assert cleanup_candidate_workspace(root, workspace, integration=integration) == {
            "status": "cleaned", "worktreeRemoved": True, "localBranchDeleted": True,
        }
    assert not candidate.exists()
    assert not _git(root, "branch", "--list", workspace["branch"])


def test_cleanup_retries_after_branch_deletion_fails(tmp_path, monkeypatch):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    real_run_git = candidate_workspace._run_git

    def fail_branch_deletion(path, *args):
        if args[:1] == ("branch",) and args[1:2] in (("-d",), ("-D",)):
            return subprocess.CompletedProcess(args, 1, "", "transient branch failure")
        return real_run_git(path, *args)

    with monkeypatch.context() as patch:
        patch.setattr(candidate_workspace, "_run_git", fail_branch_deletion)
        with pytest.raises(CandidateWorkspaceError, match="branch deletion failed"):
            cleanup_candidate_workspace(root, workspace, integration=integration)

    assert not candidate.exists()
    assert _git(root, "branch", "--list", workspace["branch"])
    assert cleanup_candidate_workspace(root, workspace, integration=integration)["status"] == "cleaned"


@pytest.mark.parametrize("change", ["tracked", "untracked", "ignored", "commit", "merged_later_commit"])
def test_cleanup_preserves_candidate_changes(tmp_path, change):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    if change in {"untracked", "ignored"}:
        if change == "ignored":
            excludes = tmp_path / "excludes"
            excludes.write_text("new.txt\n", encoding="utf-8")
            _git(root, "config", "core.excludesFile", str(excludes))
        (candidate / "new.txt").write_text("new work\n", encoding="utf-8")
    else:
        (candidate / "kept.txt").write_text("new work\n", encoding="utf-8")
        if "commit" in change:
            _git(candidate, "add", "kept.txt")
            _git(candidate, "commit", "-m", "later candidate work")
            if change == "merged_later_commit":
                _git(root, "merge", "--ff-only", workspace["branch"])

    with pytest.raises(CandidateWorkspaceError):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert candidate.is_dir()
    assert _git(root, "branch", "--list", workspace["branch"])
    assert (candidate / ("new.txt" if change in {"untracked", "ignored"} else "kept.txt")).read_text() == "new work\n"


def test_cleanup_retry_preserves_branch_advanced_after_worktree_removal(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    _git(root, "worktree", "remove", str(candidate))
    _git(root, "commit", "--allow-empty", "-m", "later main work")
    _git(root, "branch", "-f", workspace["branch"], "HEAD")

    with pytest.raises(CandidateWorkspaceError, match="outside the verified integration"):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert _git(root, "rev-parse", workspace["branch"]) == _git(root, "rev-parse", "HEAD")


def test_cleanup_refuses_integration_not_in_main_history(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    _git(candidate, "commit", "--allow-empty", "-m", "unmerged")
    integration["commitSha"] = _git(candidate, "rev-parse", "HEAD")

    with pytest.raises(CandidateWorkspaceError, match="main history"):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert candidate.is_dir()
    assert _git(root, "branch", "--list", workspace["branch"])


def test_cleanup_preserves_replaced_worktree_registration(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    _git(candidate, "switch", "-c", "foreign")

    with pytest.raises(CandidateWorkspaceError, match="registered"):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert candidate.is_dir()
    assert _git(candidate, "branch", "--show-current") == "foreign"
    assert _git(root, "branch", "--list", workspace["branch"])


def test_cleanup_preserves_branch_checked_out_elsewhere(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    relocated = tmp_path / "relocated"
    _git(root, "worktree", "move", str(candidate), str(relocated))

    with pytest.raises(CandidateWorkspaceError):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert relocated.is_dir()
    assert _git(root, "branch", "--list", workspace["branch"])


def test_cleanup_preserves_unregistered_directory_at_old_path(tmp_path):
    root, workspace, candidate, integration = _integrated_candidate(tmp_path)
    _git(root, "worktree", "remove", str(candidate))
    candidate.mkdir()
    (candidate / "foreign.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError):
        cleanup_candidate_workspace(root, workspace, integration=integration)

    assert (candidate / "foreign.txt").read_text() == "keep\n"
    assert _git(root, "branch", "--list", workspace["branch"])


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
