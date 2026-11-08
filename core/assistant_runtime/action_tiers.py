"""Operator-tier visibility set for the Launcher platform action catalog.

The personal assistant's platform actions split into two tiers. The default
tier keeps read-only and everyday-safe writes visible; the operator tier adds
destructive, lifecycle, permission-reducing, one-shot migration and cleanup
actions that stay hidden until the operator explicitly opens the switch in the
active operator config. This module is purely declarative: it owns the action
name set and the config reader, and never mutates anything. Approval semantics
of the actions themselves are unchanged in both tiers.
"""

from __future__ import annotations

# Actions hidden from the catalog (index/describe/execute) until the operator
# turns on ``[assistant] operator_tier_enabled`` in the active operator config.
# Grouped by the boundary rule: default tier = read-only + everyday-safe
# writes; operator tier = irreversible deletion, lifecycle and archival, team/
# flow orchestration writes, permission reduction, one-shot migration writes
# and cleanup execution. Read-only reconciliation/preview counterparts
# (*_receipt, *_preview, branch_cleanup_plan, affairs_conflict_*,
# episodic_conflict_review, legacy_*) deliberately stay in the default tier.
OPERATOR_TIER_ACTIONS: frozenset[str] = frozenset({
    # Irreversible deletion.
    "agent_purge", "agent_purge_batch", "model_remove", "provider_remove",
    # Lifecycle and archival.
    "agent_archive", "team_archive", "team_member_remove", "team_member_add",
    "session_stop", "session_delete", "project_lifecycle", "runtime_command",
    # Team / flow orchestration writes.
    "team_create", "team_update", "team_run", "flow_save", "flow_start",
    "team_recovery_confirm_deployment", "research_command",
    # Permission reduction and ACL writes.
    "authorization_reduce", "authorization_revoke",
    "knowledge_acl_grant", "knowledge_acl_revoke", "agent_dispatch_access_set",
    # One-shot migration writes.
    "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue",
    "knowledge_sync_queue", "knowledge_sync_recover",
    "reminder_handoff_queue", "reminder_handoff_recover",
    # Cleanup execution.
    "branch_cleanup_execute",
})

# The config key this module reads. Only the operator may flip it by editing
# the active operator config file; no assistant action surface exposes it.
_OPERATOR_TIER_CONFIG_SECTION = "assistant"
_OPERATOR_TIER_CONFIG_KEY = "operator_tier_enabled"


def read_operator_config_snapshot() -> dict:
    """Read the live operator config with the host's bounded snapshot chain.

    Same source as the host's operator profile: ``resolve_config_path()`` plus
    ``read_existing_config_snapshot``. Called on every catalog assembly so a
    manual config edit takes effect on the next tool call; there is no
    process-level cache.
    """
    from config.paths import resolve_config_path
    from config.public_config import read_existing_config_snapshot

    return read_existing_config_snapshot(resolve_config_path())


def operator_tier_enabled(config: dict | None = None) -> bool:
    """Whether the operator tier is currently open.

    ``config=None`` reads the live operator config; a read failure keeps the
    tier closed (the switch can only widen visibility through an explicit
    operator edit, never through a missing or broken config file). A passed
    ``config`` mapping is used verbatim. Only the strict boolean ``True``
    opens the tier.
    """
    if config is None:
        try:
            config = read_operator_config_snapshot()
        except ValueError:
            return False
    section = config.get(_OPERATOR_TIER_CONFIG_SECTION)
    return isinstance(section, dict) and section.get(_OPERATOR_TIER_CONFIG_KEY) is True
