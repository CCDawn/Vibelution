from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import claim_dormancy


NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
STALE_UPDATED_AT = "2026-10-19T16:02:47Z"


def _sibling_worktree(tmp_path: Path, name: str = "sibling") -> Path:
    worktree = tmp_path / name
    worktree.mkdir()
    (worktree / "hot.py").write_text("value = 1\n", encoding="utf-8")
    return worktree


def _age_tree(worktree: Path, *, minutes: int) -> None:
    stamp = (NOW - timedelta(minutes=minutes)).timestamp()
    for path in worktree.rglob("*"):
        os.utime(path, (stamp, stamp))


def _claim(agent_id: str = "worktree-sibling") -> dict[str, object]:
    return {
        "id": "claim-foreign",
        "agentId": agent_id,
        "status": "active",
        "updatedAt": STALE_UPDATED_AT,
    }


def _agents(worktree: Path) -> list[dict[str, object]]:
    return [
        {
            "id": "worktree-sibling",
            "state": "active",
            "branch": "codex/sibling-task",
            "worktree": str(worktree),
        }
    ]


def test_fresh_worktree_activity_keeps_claim_active(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=5)

    verdict = claim_dormancy.assess_claim_dormancy(
        _claim(),
        _agents(worktree),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is False
    assert "worktree file activity" in verdict.reason


def test_silent_worktree_beyond_threshold_is_dormant(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=45)

    verdict = claim_dormancy.assess_claim_dormancy(
        _claim(),
        _agents(worktree),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is True
    assert "no worktree file activity" in verdict.reason
    assert verdict.last_activity_at


def test_missing_worktree_is_dormant(tmp_path: Path) -> None:
    gone = tmp_path / "removed-worktree"

    verdict = claim_dormancy.assess_claim_dormancy(
        _claim(),
        _agents(gone),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is True
    assert "no longer exists" in verdict.reason


def test_recent_claim_coordination_activity_beats_quiet_worktree(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=90)
    claim = _claim()
    claim["updatedAt"] = (NOW - timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z"
    )

    verdict = claim_dormancy.assess_claim_dormancy(
        claim,
        _agents(worktree),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is False
    assert "coordination activity" in verdict.reason


def test_unregistered_owner_with_stale_claim_is_orphan_dormant() -> None:
    verdict = claim_dormancy.assess_claim_dormancy(
        _claim(agent_id="worktree-ghost"),
        [],
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is True
    assert "owner agent not registered" in verdict.reason


def test_git_internals_do_not_count_as_worktree_activity(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=45)
    git_dir = worktree / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/x\n", encoding="utf-8")

    verdict = claim_dormancy.assess_claim_dormancy(
        _claim(),
        _agents(worktree),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is True


def test_threshold_env_override_is_floored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(claim_dormancy._ENV_OVERRIDE, "1")
    assert claim_dormancy.dormancy_threshold_minutes() == 5
    monkeypatch.setenv(claim_dormancy._ENV_OVERRIDE, "90")
    assert claim_dormancy.dormancy_threshold_minutes() == 90
    monkeypatch.delenv(claim_dormancy._ENV_OVERRIDE, raising=False)
    assert claim_dormancy.dormancy_threshold_minutes() == 30


def test_missing_worktree_is_dormant_even_with_fresh_claim_timestamp(
    tmp_path: Path,
) -> None:
    """A cleaned-up worktree outranks a freshly refreshed heartbeat.

    The timestamp check used to run first, so a worktree that had already been
    deleted could keep holding its scopes for one more full threshold window.
    Nobody can be working inside a directory that no longer exists.
    """

    gone = tmp_path / "removed-but-freshly-claimed"
    claim = _claim()
    claim["updatedAt"] = (NOW - timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z"
    )

    verdict = claim_dormancy.assess_claim_dormancy(
        claim,
        _agents(gone),
        now=NOW,
        threshold_minutes=30,
    )

    assert verdict.dormant is True
    assert "no longer exists" in verdict.reason

def _stamp_new(path: Path) -> None:
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))


def test_dependency_trees_do_not_count_as_activity(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=120)
    for relative in ("node_modules/pkg/index.js", ".venv/lib/site.py", "venv/lib/site.py"):
        path = worktree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        _stamp_new(path)

    last = claim_dormancy.worktree_last_activity(worktree)

    assert last is not None
    assert last < NOW - timedelta(minutes=60)


def test_linked_directories_are_not_followed(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=120)
    outside = tmp_path / "outside"
    outside.mkdir()
    fresh = outside / "fresh.txt"
    fresh.write_text("x", encoding="utf-8")
    _stamp_new(fresh)
    try:
        os.symlink(outside, worktree / "vendor-link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    last = claim_dormancy.worktree_last_activity(worktree)

    assert last is not None
    assert last < NOW - timedelta(minutes=60)


def test_verification_output_still_counts_as_activity(tmp_path: Path) -> None:
    worktree = _sibling_worktree(tmp_path)
    _age_tree(worktree, minutes=120)
    bundle = worktree / "dist" / "bundle.js"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text("x", encoding="utf-8")
    _stamp_new(bundle)

    last = claim_dormancy.worktree_last_activity(worktree)

    assert last is not None
    assert last >= NOW - timedelta(minutes=1)
