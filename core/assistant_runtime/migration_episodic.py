"""Operator-only legacy episode import into the native PA's existing ledger.

The trusted caller must authorize the source principal and bind the closed
source scope to the supplied bytes. A digest proves integrity, not authority.
Session/path refs remain historical data; no Session or Turn is admitted and
no source quiescence or cutover claim is made by this adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.agent_directory import episodic_memory as episodes

from .migration_io import (
    FileSnapshot, MigrationIOError, check_path, pinned_mutable_file, pinned_target_directory,
    read_stable_file, strict_json, verify_snapshot,
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_BYTE_CAP = 4 * 1024 * 1024
_ROW_CAP = 4096
_FIELDS = frozenset({"schemaVersion", "episodeId", "eventId", "agentId", "occurredAt",
                     "kind", "text", "refs", "validFrom", "validUntil", "supersededByEpisodeId"})


def _token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _time(value, *, optional=False):
    if not isinstance(value, str) or len(value) > 64:
        raise MigrationIOError("episodic_row_invalid")
    if optional and value == "":
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result
    except ValueError:
        raise MigrationIOError("episodic_row_invalid") from None


def _parse_rows(raw: bytes, actor: str) -> list[dict]:
    """Strict bounded JSONL; preserve every supported source field verbatim."""
    if not isinstance(raw, bytes) or len(raw) > _BYTE_CAP:
        raise MigrationIOError("episodic_byte_limit")
    lines = raw.splitlines()
    if len(lines) > _ROW_CAP:
        raise MigrationIOError("episodic_row_limit")
    rows, episode_ids, event_ids, owners = [], set(), set(), {}
    for line in lines:
        if not line.strip():
            continue
        row = strict_json(line)
        if (not isinstance(row, dict) or set(row) != _FIELDS
                or type(row.get("schemaVersion")) is not int or row["schemaVersion"] != 1
                or not _token(row.get("episodeId")) or not _token(row.get("eventId"))
                or not isinstance(row.get("kind"), str) or row["kind"] not in episodes.EPISODE_KINDS):
            raise MigrationIOError("episodic_row_invalid")
        if row.get("agentId") != actor:
            raise MigrationIOError("episodic_actor_mismatch")
        text, refs = row["text"], row["refs"]
        if (not isinstance(text, str) or not text.strip() or len(text) > 65536
                or len(text.splitlines()) > episodes.MAX_TEXT_LINES
                or not isinstance(refs, list) or len(refs) > episodes.MAX_REFS):
            raise MigrationIOError("episodic_row_invalid")
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != {"type", "id"}
                    or not isinstance(ref.get("type"), str) or ref["type"] not in episodes.REF_TYPES
                    or not isinstance(ref.get("id"), str) or not ref["id"].strip()
                    or len(ref["id"]) > 2048):
                raise MigrationIOError("episodic_row_invalid")
        _time(row["occurredAt"])
        start, end = _time(row["validFrom"]), _time(row["validUntil"], optional=True)
        successor = row["supersededByEpisodeId"]
        if (not isinstance(successor, str) or (successor and not _token(successor))
                or (end is not None and end < start)):
            raise MigrationIOError("episodic_row_invalid")
        eid, event = row["episodeId"], row["eventId"]
        if eid in episode_ids or event in event_ids:
            raise MigrationIOError("episodic_duplicate_id")
        for identifier in {eid, event}:
            if identifier in owners:
                raise MigrationIOError("episodic_duplicate_id")
            owners[identifier] = eid
        episode_ids.add(eid)
        event_ids.add(event)
        rows.append(row)
    by_id = {row["episodeId"]: row for row in rows}
    for row in rows:
        successor = row["supersededByEpisodeId"]
        if successor and (not row["validUntil"] or successor not in by_id
                          or successor == row["episodeId"]
                          or _time(by_id[successor]["validFrom"]) > _time(row["validUntil"])):
            raise MigrationIOError("episodic_succession_invalid")
    # Each node has at most one outgoing edge. Iterative coloring stays bounded
    # for a full 4096-row chain and does not inherit Python's recursion limit.
    done = set()
    for row in rows:
        pending, current = set(), row["episodeId"]
        while current and current not in done:
            if current in pending:
                raise MigrationIOError("episodic_succession_invalid")
            pending.add(current)
            current = by_id[current]["supersededByEpisodeId"]
        done.update(pending)
    return rows


def _check_lease(lease):
    from .migration_profile import OfflineMigrationProfileLease
    if type(lease) is not OfflineMigrationProfileLease:
        raise MigrationIOError("episodic_profile_lease_required")
    try:
        lease.check()
    except RuntimeError:
        raise MigrationIOError("episodic_profile_lease_required") from None


def _source_bytes(source, source_sha256):
    if not isinstance(source_sha256, str) or not _HASH.fullmatch(source_sha256):
        raise MigrationIOError("episodic_source_hash_invalid")
    if isinstance(source, FileSnapshot):
        if source.sha256 != source_sha256:
            raise MigrationIOError("episodic_source_hash_mismatch")
        verify_snapshot(source)
        raw = source.raw
    elif isinstance(source, bytes):
        raw = source
    else:
        raise MigrationIOError("episodic_source_required")
    if len(raw) > _BYTE_CAP:
        raise MigrationIOError("episodic_byte_limit")
    if hashlib.sha256(raw).hexdigest() != source_sha256:
        raise MigrationIOError("episodic_source_hash_mismatch")
    return raw


def _verify_workspace(state):
    try:
        state.verify_workspace()
    except (OSError, ValueError, TypeError):
        raise MigrationIOError("episodic_workspace_changed") from None


def _target(lease, state):
    from core.web.services import agent_directory_service as directory
    from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path
    root = Path(lease.root)
    _verify_workspace(state)
    relative = f"workspace/agents/{lease.agent_id}"
    agent = directory.get_agent(lease.agent_id, include_archived=True)
    policy = directory.resolve_memory_policy_for_agent(lease.agent_id)
    if not bool(policy.get("enabled", True)):
        raise MigrationIOError("episodic_memory_disabled")
    if (not _token(lease.agent_id) or directory._project_root() != root or not agent
            or agent.get("workspacePath") != relative
            or policy.get("episodicEventsPath") != relative + "/events/episodic_events.jsonl"):
        raise MigrationIOError("episodic_target_binding_invalid")
    # Check the lexical canonical storage path *before* a native resolver could
    # erase a reparse point from its spelling, including links within this root.
    try:
        workspace = existing_sandboxed_workspace_path(root, public_config=state.config)
    except (OSError, ValueError, TypeError):
        raise MigrationIOError("episodic_workspace_changed") from None
    if not workspace.is_relative_to(root):
        raise MigrationIOError("episodic_target_binding_invalid")
    check_path(workspace)
    if not workspace.resolve().is_relative_to(root):
        raise MigrationIOError("episodic_target_binding_invalid")
    canonical = workspace / "agents" / lease.agent_id / "events" / "episodic_events.jsonl"
    ancestor = canonical
    while not ancestor.exists() and not ancestor.is_symlink():
        ancestor = ancestor.parent
    check_path(ancestor)
    ledger = episodes._episodic_events_path(agent)
    if ledger != canonical:
        raise MigrationIOError("episodic_target_binding_invalid")
    _verify_workspace(state)
    return ledger


def _write_receipt(path, receipt):
    atomic_write_json(path, receipt, strict_replace=True, sort_keys=True)


def _result(binding, *, imported_count, idempotent):
    return {**binding, "importedCount": imported_count, "idempotent": idempotent,
            "sourceQuiesced": False, "readyForCutover": False}


def import_episodic(lease, source: FileSnapshot | bytes, *, source_scope: dict,
                    source_sha256: str, migration_id: str) -> dict:
    """Add authorized legacy episodes using only the native transaction writer.

    Internal operator adapter: use only a live offline migration profile lease.
    A metadata-only pending receipt binds a request before ledger publication;
    matching rows recover a ledger/receipt interruption, conflicting rows fail.
    Completed requests never replay over later native edits.
    """
    _check_lease(lease)
    if not _token(migration_id):
        raise MigrationIOError("episodic_migration_id_invalid")
    if (not isinstance(source_scope, dict) or set(source_scope) != {"projectId", "instanceId", "agentId"}
            or any(not _token(value) for value in source_scope.values())):
        raise MigrationIOError("episodic_source_scope_invalid")
    raw = _source_bytes(source, source_sha256)
    rows = [{**row, "agentId": lease.agent_id} for row in _parse_rows(raw, source_scope["agentId"])]
    binding = {"schemaVersion": 1, "migrationId": migration_id, "sourceScope": dict(source_scope),
               "sourceSha256": source_sha256, "targetAgentId": lease.agent_id, "episodeCount": len(rows)}
    from . import native
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    try:
        state = ExistingStateSnapshot(Path(lease.root), directory, pin_workspace=True)
    except (OSError, ValueError, TypeError):
        raise MigrationIOError("episodic_workspace_changed") from None
    ledger = _target(lease, state)
    receipts = Path(lease.root) / "episodic_migrations"
    receipt_path = receipts / (hashlib.sha256(migration_id.encode()).hexdigest() + ".json")
    try:
        with native._LOCK, pinned_target_directory(ledger.parent, create=True), \
                pinned_target_directory(receipts, create=True), \
                pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), \
                pinned_mutable_file(receipt_path.with_name(receipt_path.name + ".lock")), \
                cross_process_file_lock(ledger):
            _check_lease(lease)
            if _target(lease, state) != ledger:
                raise MigrationIOError("episodic_target_binding_invalid")
            receipt = None
            if receipt_path.exists() or receipt_path.is_symlink():
                receipt = strict_json(read_stable_file(receipt_path, 16384).raw)
                allowed = [json.dumps({**binding, "published": flag}, sort_keys=True) for flag in (False, True)]
                if json.dumps(receipt, sort_keys=True) not in allowed:
                    raise MigrationIOError("episodic_migration_id_conflict")
                if receipt["published"]:
                    # The receipt records historical completion, not ownership
                    # of current user state. A retry must not inspect/replay
                    # the original rows over later supersede/remove operations.
                    _check_lease(lease)
                    _verify_workspace(state)
                    return _result(binding, imported_count=0, idempotent=True)
            # Prevalidate bytes before the native lenient reader opens them.
            existing = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw, lease.agent_id)
                        if ledger.exists() or ledger.is_symlink() else [])
            with episodes.episodic_transaction(lease.agent_id) as transaction:
                if transaction.path != ledger or transaction.events != existing:
                    raise MigrationIOError("episodic_target_changed")
                if isinstance(source, FileSnapshot):
                    verify_snapshot(source)
                by_id = {row["episodeId"]: row for row in existing}
                ids = {row[key] for row in existing for key in ("episodeId", "eventId")}
                additions = []
                for row in rows:
                    previous = by_id.get(row["episodeId"])
                    if previous is not None and previous != row:
                        raise MigrationIOError("episodic_target_id_conflict")
                    if previous is None:
                        if row["episodeId"] in ids or row["eventId"] in ids:
                            raise MigrationIOError("episodic_target_id_conflict")
                        additions.append(row)
                merged = existing + additions
                serialized = b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n" for row in merged)
                _parse_rows(serialized, lease.agent_id)
                if receipt is None:
                    _write_receipt(receipt_path, {**binding, "published": False})
                _check_lease(lease)
                if isinstance(source, FileSnapshot):
                    verify_snapshot(source)
                if _target(lease, state) != ledger:
                    raise MigrationIOError("episodic_target_binding_invalid")
                if additions:
                    # The native transaction remains the only ledger writer.
                    # append() would create fresh IDs, so this internal adapter
                    # installs validated events under the same transaction lock.
                    transaction.events.extend(additions)
                    transaction._dirty = True
            actual = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw, lease.agent_id) if merged else [])
            if actual != merged:
                raise MigrationIOError("episodic_target_readback_mismatch")
            _check_lease(lease)
            _verify_workspace(state)
            _write_receipt(receipt_path, {**binding, "published": True})
            _check_lease(lease)
            _verify_workspace(state)
            return _result(binding, imported_count=len(additions), idempotent=False)
    except (OSError, TimeoutError):
        raise MigrationIOError("episodic_target_unavailable") from None


__all__ = ["import_episodic"]
