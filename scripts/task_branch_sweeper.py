"""List unmerged codex/* task branches with claim and dormancy evidence.

Read-only diagnostic for the gap where a committed-but-unmerged task branch
sits silently (owner session cut off mid-task): the sweeper surfaces each
branch's ahead-count, last commit, owning worktree activity, and the state
of its coordination claim, so stale work is visible without manual git +
coordination archaeology.

Usage:
    python scripts/task_branch_sweeper.py [--repo PATH] [--stale-minutes N] [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import claim_dormancy  # noqa: E402
from scripts import git_claim_guard as guard  # noqa: E402


def _git_lines(root: Path, *arguments: str) -> list[str]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _codex_branches(root: Path) -> list[str]:
    return [
        branch
        for branch in _git_lines(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        if branch.startswith("codex/")
    ]


def _merged_into_main(root: Path, branches: Sequence[str]) -> set[str]:
    merged: set[str] = set()
    for branch in branches:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            merged.add(branch)
    return merged


def _worktrees_by_branch(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    current_path = ""
    current_branch = ""
    for line in _git_lines(root, "worktree", "list", "--porcelain"):
        if line.startswith("worktree "):
            current_path = line.removeprefix("worktree ").strip()
            current_branch = ""
        elif line.startswith("branch "):
            current_branch = line.removeprefix("branch ").strip().removeprefix(
                "refs/heads/"
            )
            if current_path and current_branch:
                mapping[current_branch] = current_path
    return mapping


def _claims_for_lanes(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lanes: dict[str, dict[str, Any]] = {}
    claims = status.get("claims") if isinstance(status.get("claims"), list) else []
    for item in claims:
        if not isinstance(item, dict):
            continue
        lane = str(item.get("laneId") or "").strip()
        if not lane:
            continue
        existing = lanes.get(lane)
        if existing is None or str(item.get("createdAt") or "") > str(
            existing.get("createdAt") or ""
        ):
            lanes[lane] = item
    return lanes


def _agents_by_branch(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    agents = status.get("agents") if isinstance(status.get("agents"), list) else []
    for item in agents:
        if isinstance(item, dict):
            branch = str(item.get("branch") or "").strip()
            if branch:
                mapping[branch] = item
    return mapping


def sweep(
    root: Path | str,
    *,
    stale_minutes: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    root_path = guard.repository_root(root)
    current_time = now or datetime.now(timezone.utc)
    branches = _codex_branches(root_path)
    merged = _merged_into_main(root_path, branches)
    worktrees = _worktrees_by_branch(root_path)
    try:
        status: dict[str, Any] = guard.coordination_call(root_path, "status")
        coordination_available = True
    except guard.ClaimGuardError as error:
        status = {}
        coordination_available = False
        print(
            f"[task-branch-sweeper] coordination unavailable ({error}); "
            "reporting branch evidence only",
            file=sys.stderr,
        )
    lanes = _claims_for_lanes(status)
    agents_by_branch = _agents_by_branch(status)

    rows: list[dict[str, Any]] = []
    for branch in sorted(branches):
        if branch in merged:
            continue
        slug = branch.removeprefix("codex/")
        worktree = worktrees.get(branch, "")
        claim = lanes.get(f"development/{slug}")
        agent = agents_by_branch.get(branch)
        row: dict[str, Any] = {
            "branch": branch,
            "aheadCount": int(
                (_git_lines(root_path, "rev-list", "--count", f"main..{branch}") or ["0"])[0]
            ),
            "lastCommitAt": (
                _git_lines(root_path, "log", "-1", "--format=%cI", branch) or [""]
            )[0],
            "worktree": worktree,
            "claimId": str(claim.get("id") or "") if claim else "",
            "claimStatus": str(claim.get("status") or "") if claim else "",
            "claimTask": str(claim.get("task") or "") if claim else "",
            "state": "",
            "reason": "",
            "lastActivityAt": "",
        }
        if not coordination_available:
            row["state"] = "unverified"
            row["reason"] = "coordination status unavailable"
        elif not worktree:
            row["state"] = "no-worktree"
            row["reason"] = "branch has no active checkout"
        else:
            # Prefer the git-registered checkout; fall back to the claim owner
            # so dormancy is judged from the worktree, never from a missing
            # coordination entry alone.
            probe = dict(agent) if isinstance(agent, dict) else {}
            probe_id = str(probe.get("id") or (claim or {}).get("agentId") or "probe")
            probe["id"] = probe_id
            probe["worktree"] = worktree
            synthetic = {
                "id": row["claimId"] or "probe",
                "agentId": probe_id,
                "updatedAt": str((claim or {}).get("updatedAt") or ""),
            }
            verdict = claim_dormancy.assess_claim_dormancy(
                synthetic,
                [probe],
                now=current_time,
                threshold_minutes=stale_minutes,
            )
            row["state"] = "dormant" if verdict.dormant else "active"
            row["reason"] = verdict.reason
            row["lastActivityAt"] = verdict.last_activity_at
        rows.append(row)
    return rows


def _print_table(rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        print("No unmerged codex/* task branches.")
        return
    headers = ("branch", "ahead", "lastCommit", "state", "claim", "reason")
    widths = [
        max(len(headers[0]), *(len(str(row["branch"])) for row in rows)),
        len(headers[1]),
        19,
        max(len(headers[3]), *(len(str(row["state"])) for row in rows)),
        16,
        40,
    ]
    print("  ".join(head.ljust(widths[index]) for index, head in enumerate(headers)))
    for row in rows:
        cells = (
            str(row["branch"])[: widths[0]],
            str(row["aheadCount"]).ljust(widths[1]),
            str(row["lastCommitAt"])[:19],
            str(row["state"]).ljust(widths[3]),
            str(row["claimId"])[:16],
            str(row["reason"])[:40],
        )
        print("  ".join(cells))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--stale-minutes", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = sweep(args.repo, stale_minutes=args.stale_minutes)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
