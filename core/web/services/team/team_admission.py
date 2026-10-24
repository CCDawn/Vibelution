"""Single-backend Team archive admission shared with native workflow commits.

The existing Team metadata lock protects only short checks/commits. An archive
lease freezes roster additions while its cascade runs without that global lock.
This follows the existing one-backend-per-instance authority, not a cross-process
data-root locking protocol. Never acquire workflow file locks under _TEAM_LOCK.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArchiveLease:
    member_agent_ids: frozenset[str]
    owner_thread_id: int


_LEASES: dict[tuple[str, str], ArchiveLease] = {}


def _service():
    from core.web.services import team_service
    return team_service


def _key(s, team_id: str) -> tuple[str, str]:
    return str(s._teams_root().resolve()), team_id


def _member_ids(team: dict[str, Any]) -> frozenset[str]:
    return frozenset(str(item.get("agentId") or "").strip() for item in team.get("members", [])
                     if isinstance(item, dict) and str(item.get("agentId") or "").strip())


def _workflow_records(team_id: str) -> list[dict]:
    from core.web.services.team_workflow.generic import store
    return store.records(team_id, "runs", limit=201)


def _require_settled_workflows(s, team_id: str) -> None:
    records = _workflow_records(team_id)
    if len(records) >= 201:
        raise s.TeamLockedError("Team workflow activity check is incomplete; archive is blocked.")
    for record in records:
        recovery = record.get("recovery")
        if (record.get("status") not in {"completed", "stopped"}
                or (recovery is not None and not isinstance(recovery, dict))
                or (isinstance(recovery, dict) and recovery and recovery.get("status") not in {"resolved", "cancelled"})):
            raise s.TeamLockedError("Team workflows must be completed or stopped with recovery settled before archive.")


@contextmanager
def archive_admission(team_id: str, *, protected_agent_ids: tuple[str, ...] = ()):
    """Reserve a canonical roster before any cascade; release even on failure."""
    s = _service()
    with s._TEAM_LOCK:
        key = _key(s, team_id)
        if key in _LEASES:
            raise s.TeamLockedError("Team archive is already in progress.")
        team = s._find_team(s._load_index(), team_id)
        if team is None:
            raise s.TeamNotFoundError("Team not found.")
        members = _member_ids(team)
        if members.intersection(protected_agent_ids):
            raise s.TeamLockedError("Protected caller Agent is a member of this Team.")
        _require_settled_workflows(s, team_id)
        lease = ArchiveLease(members, threading.get_ident())
        _LEASES[key] = lease
    try:
        yield lease
    finally:
        with s._TEAM_LOCK:
            if _LEASES.get(key) is lease:
                _LEASES.pop(key)


def assert_roster_mutation_allowed(team_id: str) -> None:
    """Call under the native metadata lock, before changing members/status."""
    s = _service()
    if _key(s, team_id) in _LEASES:
        raise s.TeamLockedError("Team archive is in progress; roster and status cannot change.")


def assert_restore_allowed(snapshot: dict) -> None:
    """Only this archive's synchronous compensation may restore frozen members.

    Removal remains allowed during cascade. A compensation from another Agent
    operation must not reintroduce a new member into the archived snapshot.
    Call while holding the same native metadata lock as the restore write.
    """
    s = _service()
    lease = _LEASES.get(_key(s, str(snapshot.get("teamId") or "")))
    if lease is not None and (lease.owner_thread_id != threading.get_ident()
                              or not _member_ids(snapshot).issubset(lease.member_agent_ids)):
        raise s.TeamLockedError("Team archive admission does not own this roster restore.")


@contextmanager
def workflow_commit_admission(team_id: str):
    """Caller already owns flow/run file locks; hold metadata through commit."""
    s = _service()
    with s._TEAM_LOCK:
        assert_roster_mutation_allowed(team_id)
        # Keep the existing workflow canonical-roster read seam (including
        # its instance/sandbox ownership) while holding that same Team lock.
        from core.web.services.team_workflow.generic import store
        team = store.team(team_id)
        if str(team.get("status") or "active") == "archived":
            raise s.TeamLockedError("Archived Team cannot admit workflow execution.")
        yield
