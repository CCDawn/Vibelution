"""Conservative three-way merge for native episodic synchronization.

This module makes no authorization, persistence, or baseline claims. Callers
must hold the native ledger transaction and validate both archived snapshots.
"""
from __future__ import annotations

import json

from .migration_episodic import _parse_rows
from .migration_io import MigrationIOError


def _validated(rows, actor):
    if not isinstance(rows, list):
        raise MigrationIOError("episodic_sync_rows_invalid")
    raw = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                   for row in rows)
    return _parse_rows(raw, actor)


def plan_episodic_sync(baseline, source, target, *, source_agent_id, target_agent_id, known_source_ids=frozenset()):
    """Return an atomic merge plan; a conflict leaves the entire target intact.

    A source snapshot is not deletion authority. In particular, unresolved
    removals must prevent baseline advancement or a later reappearance could
    resurrect an episode that the user deleted from the target.
    """
    old = [{**row, "agentId": target_agent_id}
           for row in _validated(baseline, source_agent_id)]
    new = [{**row, "agentId": target_agent_id}
           for row in _validated(source, source_agent_id)]
    current = _validated(target, target_agent_id)
    before = {row["episodeId"]: row for row in old}
    after = {row["episodeId"]: row for row in new}
    actual = {row["episodeId"]: row for row in current}
    merged = dict(actual)
    conflicts = []
    applied = 0
    for episode_id in sorted(before.keys() | after.keys()):
        previous, incoming = before.get(episode_id), after.get(episode_id)
        if previous == incoming:
            continue
        present = actual.get(episode_id)
        if incoming is None:
            conflicts.append(episode_id)
        elif present == incoming:
            continue
        elif previous is None and episode_id in known_source_ids:
            # A previously seen source row can reappear after an accepted
            # absence. Treat it as a conflict, never as a fresh addition.
            conflicts.append(episode_id)
        elif present != previous:
            conflicts.append(episode_id)
        else:
            merged[episode_id] = incoming
            applied += 1
    if conflicts:
        return {"rows": current, "appliedCount": 0, "conflictCount": len(conflicts)}
    result = [merged.pop(row["episodeId"]) for row in current]
    result.extend(merged.values())
    try:
        _validated(result, target_agent_id)
    except MigrationIOError:
        # A mixed local/source successor graph or colliding event ID cannot be
        # published safely even when each individual row is well formed.
        return {"rows": current, "appliedCount": 0, "conflictCount": 1}
    return {"rows": result, "appliedCount": applied, "conflictCount": 0}


__all__ = ["plan_episodic_sync"]
