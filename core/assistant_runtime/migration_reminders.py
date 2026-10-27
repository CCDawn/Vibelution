"""Read-only reminder handoff evidence, never a scheduler or delivery receipt.

The current reminder owner is the legacy Workbench human-attention chain.
Neither affairs snapshots, localStorage seen IDs, a stopped backend, nor the
target's offline lease transfer that owner's notification authority. Launcher
has no reminder consumer yet. This preview therefore always fails closed.
Caller-side source authorization remains mandatory; hashes prove bytes only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.agent_plugins.personal_affairs.service import project_affairs

from .migration_affairs import _check_lease, _parse_rows, _source_bytes, _token
from .migration_io import FileSnapshot, MigrationIOError, read_stable_file, verify_snapshot

_BYTE_CAP = 4 * 1024 * 1024
_NATIVE_GAPS = (
    "source_notification_fence_unavailable",
    "delivery_watermark_unavailable",
    "target_reminder_consumer_unavailable",
)


def preview_reminder_handoff(lease, source: FileSnapshot, *, source_scope: dict,
                             now: datetime) -> dict:
    """Compare an authorized legacy ledger with the actual offline profile.

    A real target lease supplies identity and blocks native turn admission.
    Source and target bytes are checked again before returning. A concurrent
    edit rejects the observation, rather than marking an item delivered or
    copying browser dedup state. Even equal snapshots do not permit cutover.
    No source discovery, path-bearing result, mutation or public action exists.
    """
    _check_lease(lease)
    if (not isinstance(source_scope, dict)
            or set(source_scope) != {"projectId", "instanceId", "agentId"}
            or any(not _token(value) for value in source_scope.values())):
        raise MigrationIOError("reminders_source_scope_invalid")
    scope = dict(source_scope)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise MigrationIOError("reminders_aware_time_required")
    now = now.astimezone(timezone.utc)
    root = Path(lease.root)
    if (not isinstance(source, FileSnapshot)
            or tuple(source.path.parts[-6:]) != (
                "agents", scope["agentId"], "plugins", "personal-affairs", "affairs", "items.jsonl")
            or source.path.is_relative_to(root)):
        raise MigrationIOError("reminders_source_binding_invalid")
    source_rows = _parse_rows(_source_bytes(source, source.sha256))

    from . import native
    from core.web.services import personal_affairs_service

    service = personal_affairs_service.get_personal_affairs_service()
    expected = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != expected:
        raise MigrationIOError("reminders_target_binding_invalid")
    ledger = expected / "affairs/items.jsonl"
    # The lease excludes another host/migrator, but native ledger writers have
    # their own lock. Stable snapshots plus final verification reject races
    # without creating or changing even a lock file in this read-only preview.
    with native._LOCK:
        _check_lease(lease)
        target = (read_stable_file(ledger, _BYTE_CAP)
                  if ledger.exists() or ledger.is_symlink() else None)
        target_rows = _parse_rows(target.raw) if target is not None else []
        by_id = {row["itemId"]: row for row in target_rows}
        missing = sum(row["itemId"] not in by_id for row in source_rows)
        conflicting = sum(row["itemId"] in by_id and by_id[row["itemId"]] != row for row in source_rows)
        due = sum(item["dueState"] in {"overdue", "today"} for item in project_affairs(
            source_rows, agent_id=scope["agentId"], now=now)["items"])
        gaps = list(_NATIVE_GAPS)
        if target is None:
            gaps.append("target_affairs_missing")
        if missing or conflicting:
            gaps.append("affairs_snapshot_mismatch")
        verify_snapshot(source)
        if target is not None:
            verify_snapshot(target)
        elif ledger.exists() or ledger.is_symlink():
            raise MigrationIOError("reminders_target_changed")
        _check_lease(lease)
        return {
            "schemaVersion": 1, "stage": "reminder_handoff_preview",
            "sourceScope": scope, "targetAgentId": lease.agent_id,
            "targetSessionId": lease.session_id, "observedAt": now.isoformat(),
            "sourceSha256": source.sha256,
            "targetSha256": target.sha256 if target is not None else None,
            "sourceItemCount": len(source_rows), "targetItemCount": len(target_rows),
            "matchedItemCount": len(source_rows) - missing - conflicting,
            "missingItemCount": missing, "conflictingItemCount": conflicting,
            "sourceDueItemCount": due,
            "currentReminderOwner": "legacy_workbench_human_attention",
            "readOnly": True, "executionAttempted": False,
            "sourceQuiesced": False, "deliveryStateTransferred": False,
            "readyForCutover": False, "pendingChecks": gaps,
        }


__all__ = ["preview_reminder_handoff"]
