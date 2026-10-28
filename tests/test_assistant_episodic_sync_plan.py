"""Three-way episode merge preserves user state and successor integrity."""
from core.assistant_runtime.episodic_sync_plan import plan_episodic_sync
from tests.test_assistant_migration_episodic import episode


def plan(old, new, current):
    return plan_episodic_sync(old, new, current, source_agent_id="old-pa", target_agent_id="new-pa")


def target(row):
    return {**row, "agentId": "new-pa"}


def test_add_and_supersede_are_committed_as_one_valid_graph():
    old = episode("one")
    successor = episode("two", validFrom="2025-02-02T00:00:00Z")
    updated = {**old, "validUntil": "2025-02-02T00:00:00Z", "supersededByEpisodeId": "two"}
    result = plan([old], [updated, successor], [target(old)])
    assert result == {"rows": [target(updated), target(successor)], "appliedCount": 2, "conflictCount": 0}


def test_user_edit_or_removal_blocks_every_change():
    old = episode("one")
    edited = target({**old, "text": "user edit"})
    new = {**old, "text": "source edit"}
    for current in ([edited], []):
        result = plan([old], [new, episode("two")], current)
        assert result == {"rows": current, "appliedCount": 0, "conflictCount": 1}


def test_missing_source_never_advances_baseline_even_if_target_also_missing():
    old = episode("one")
    for current in ([target(old)], []):
        result = plan([old], [], current)
        assert result == {"rows": current, "appliedCount": 0, "conflictCount": 1}


def test_unchanged_source_does_not_restore_target_deletion():
    old = episode("one")
    assert plan([old], [old], []) == {"rows": [], "appliedCount": 0, "conflictCount": 0}


def test_event_id_collision_cannot_publish_invalid_target():
    local = target(episode("local", eventId="shared"))
    incoming = episode("incoming", eventId="shared")
    assert plan([], [incoming], [local]) == {"rows": [local], "appliedCount": 0, "conflictCount": 1}


def test_union_can_exceed_a_single_snapshot_row_limit():
    old = [episode(f"old-{i}") for i in range(4096)]
    new = [episode(f"new-{i}") for i in range(4096)]
    current = [target({**row, "text": "user version"}) for row in new]
    assert plan(old, new, current)["conflictCount"] == 8192
