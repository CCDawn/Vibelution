from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import task_branch_sweeper as sweeper


def _git(root: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def multi_branch_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Sweeper Test")
    _git(root, "config", "user.email", "sweeper@test.local")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")

    # Unmerged branch with a live checkout.
    _git(root, "switch", "-c", "codex/dormant-task")
    (root / "stale.py").write_text("stale = 1\n", encoding="utf-8")
    _git(root, "add", "stale.py")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "stale work")
    _git(root, "switch", "-c", "codex/active-task")
    (root / "fresh.py").write_text("fresh = 1\n", encoding="utf-8")
    _git(root, "add", "fresh.py")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "fresh work")

    # Unmerged branch without a checkout.
    _git(root, "switch", "-c", "codex/bare-task", "main")
    (root / "bare.py").write_text("bare = 1\n", encoding="utf-8")
    _git(root, "add", "bare.py")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "bare work")

    # Branch already merged into main must not appear.
    _git(root, "switch", "-c", "codex/merged-task", "main")
    (root / "merged.py").write_text("merged = 1\n", encoding="utf-8")
    _git(root, "add", "merged.py")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "merged work")
    _git(root, "switch", "main")
    _git(root, "-c", "core.hooksPath=", "merge", "--ff-only", "codex/merged-task")

    _git(
        root,
        "worktree",
        "add",
        str(tmp_path / "dormant-checkout"),
        "codex/dormant-task",
    )
    _git(
        root,
        "worktree",
        "add",
        str(tmp_path / "active-checkout"),
        "codex/active-task",
    )

    stale_stamp = (
        datetime.now(timezone.utc) - timedelta(minutes=120)
    ).timestamp()
    for path in (tmp_path / "dormant-checkout").rglob("*"):
        os.utime(path, (stale_stamp, stale_stamp))
    return root


def _fake_coordination(root: Path, *arguments: str) -> dict[str, object]:
    assert arguments[0] == "status"
    return {
        "agents": [
            {
                "id": "worktree-dormant",
                "state": "active",
                "branch": "codex/dormant-task",
                "worktree": "",
            }
        ],
        "claims": [
            {
                "id": "claim-dormant",
                "agentId": "worktree-dormant",
                "status": "active",
                "laneId": "development/dormant-task",
                "createdAt": "2026-10-19T16:02:47Z",
                "updatedAt": "2026-10-19T16:02:47Z",
            }
        ],
    }


def test_sweeper_classifies_unmerged_branches_by_dormancy(
    multi_branch_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import git_claim_guard as guard

    monkeypatch.setattr(guard, "coordination_call", _fake_coordination)

    rows = sweeper.sweep(multi_branch_repo, stale_minutes=30)

    by_branch = {row["branch"]: row for row in rows}
    assert set(by_branch) == {
        "codex/dormant-task",
        "codex/active-task",
        "codex/bare-task",
    }
    assert by_branch["codex/dormant-task"]["state"] == "dormant"
    assert "no worktree file activity" in by_branch["codex/dormant-task"]["reason"]
    assert by_branch["codex/dormant-task"]["claimId"] == "claim-dormant"
    assert by_branch["codex/active-task"]["state"] == "active"
    assert by_branch["codex/bare-task"]["state"] == "no-worktree"
    assert by_branch["codex/bare-task"]["worktree"] == ""
    assert {row["branch"]: row["aheadCount"] for row in rows} == {
        "codex/dormant-task": 1,
        "codex/active-task": 2,
        "codex/bare-task": 1,
    }
    assert all(row["lastCommitAt"] for row in rows)


def test_sweeper_survives_coordination_outage(
    multi_branch_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import git_claim_guard as guard

    def unavailable(_root: Path, *arguments: str) -> dict[str, object]:
        raise guard.ClaimGuardError("coordination_failed")

    monkeypatch.setattr(guard, "coordination_call", unavailable)

    rows = sweeper.sweep(multi_branch_repo)

    assert rows
    assert all(row["state"] == "unverified" for row in rows)
    assert all(row["reason"] == "coordination status unavailable" for row in rows)
