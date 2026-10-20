"""Evidence-based dormancy detection for development claims.

The coordination layer has no liveness heartbeat: a claim's updatedAt only
moves on coordination operations, and a session cut off mid-task (locked
machine, closed client window) never releases its claim — the claim then
blocks sibling commits for its full TTL. This module derives dormancy from
what the owning worktree can actually prove: a worktree with no file
activity for longer than the threshold is not being worked on, whatever the
claim record says. Verifying sessions stay "active" because gates and edits
keep writing files (edits, .pytest_cache, node caches) inside the worktree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_DORMANCY_MINUTES = 30
_HARD_FLOOR_MINUTES = 5
_ENV_OVERRIDE = "VIBELUTION_CLAIM_DORMANCY_MINUTES"
_EXCLUDED_DIRECTORY_NAMES = frozenset({".git"})


@dataclass(frozen=True)
class DormancyVerdict:
    claim_id: str
    agent_id: str
    dormant: bool
    reason: str
    worktree: str
    last_activity_at: str


def dormancy_threshold_minutes() -> int:
    raw = str(os.environ.get(_ENV_OVERRIDE) or "").strip()
    if not raw:
        return DEFAULT_DORMANCY_MINUTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_DORMANCY_MINUTES
    return max(value, _HARD_FLOOR_MINUTES)


def _parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_age(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    return f"{minutes}min"


def worktree_last_activity(
    worktree: Path,
    *,
    exclude_directories: frozenset[str] = _EXCLUDED_DIRECTORY_NAMES,
) -> datetime | None:
    """Newest file mtime under the worktree, ignoring .git internals.

    Test caches (.pytest_cache, node tooling caches) count as activity on
    purpose: a session running verification gates keeps them fresh.
    """

    newest: float | None = None
    for dirpath, dirnames, filenames in os.walk(worktree):
        dirnames[:] = [name for name in dirnames if name not in exclude_directories]
        for name in filenames:
            try:
                mtime = os.stat(os.path.join(dirpath, name)).st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    if newest is None:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc)


def assess_claim_dormancy(
    claim: Mapping[str, Any],
    agents: Sequence[Any],
    *,
    now: datetime,
    threshold_minutes: int | None = None,
) -> DormancyVerdict:
    """Classify one active claim as dormant or active from hard evidence."""

    threshold = (
        dormancy_threshold_minutes() if threshold_minutes is None else threshold_minutes
    )
    claim_id = str(claim.get("id") or "")
    agent_id = str(claim.get("agentId") or "")

    def verdict(dormant: bool, reason: str, worktree: str, last_activity: str = "") -> DormancyVerdict:
        return DormancyVerdict(
            claim_id=claim_id,
            agent_id=agent_id,
            dormant=dormant,
            reason=reason,
            worktree=worktree,
            last_activity_at=last_activity,
        )

    updated = _parse_iso(claim.get("updatedAt"))
    if updated is not None and now - updated <= timedelta(minutes=threshold):
        return verdict(
            False,
            f"claim coordination activity {_format_age(now - updated)} ago",
            "",
        )

    worktree = ""
    for agent in agents:
        if isinstance(agent, dict) and str(agent.get("id") or "") == agent_id:
            worktree = str(agent.get("worktree") or "").strip()
            break
    if not worktree:
        return verdict(
            True,
            f"owner agent not registered and claim silent for >{threshold}min (orphan claim)",
            "",
        )

    worktree_path = Path(worktree)
    if not worktree_path.is_dir():
        return verdict(
            True,
            "owner worktree no longer exists (cleaned up or abandoned checkout)",
            worktree,
        )

    last_activity = worktree_last_activity(worktree_path)
    if last_activity is None:
        return verdict(True, "owner worktree exists but holds no files", worktree)
    age = now - last_activity
    if age > timedelta(minutes=threshold):
        return verdict(
            True,
            f"no worktree file activity for {_format_age(age)} (threshold {threshold}min)",
            worktree,
            last_activity.isoformat(),
        )
    return verdict(
        False,
        f"worktree file activity {_format_age(age)} ago",
        worktree,
        last_activity.isoformat(),
    )
