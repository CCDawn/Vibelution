"""Offline three-way reconciliation of an authenticated legacy affairs snapshot.

The baseline import and both source archives must already be confirmed. This
does not establish source quiescence or transfer reminder execution authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json, _write_temp_file, _replace_with_retry
from core.infrastructure.file_lock import DEFAULT_LOCK_TIMEOUT_SECONDS, cross_process_file_lock
from core.agent_plugins.personal_affairs.service import AFFAIR_LEDGER_LIMIT

from .migration_affairs import _BYTE_CAP, _HASH, _parse_rows
from .migration_affairs_conflicts import _load, _record_path, _scope, _verify_record_sources, locked_affairs_target
from .migration_io import (MigrationIOError, migration_target_lock, pinned_mutable_file,
                           pinned_target_directory, read_stable_file, strict_json)
from .online_affairs_sync_lease import OnlineAffairsSyncLease, check_affairs_sync_lease


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _replace_ledger(ledger, encoded):
    # The native store resolves its target before replacement. Use the pinned
    # lexical parent instead: a swapped final symlink is replaced as an entry,
    # never resolved to another file inside the profile.
    pending = _write_temp_file(ledger, encoded.decode("utf-8"), ensure_fsync=True)
    if pending is None:
        raise MigrationIOError("affairs_target_unavailable")
    try:
        _replace_with_retry(ledger, pending, timeout_seconds=5, on_retry=None)
    finally:
        if pending.exists():
            os.unlink(pending)


def reconcile_affairs(lease, *, sync_id, source_scope, confirmation_only=False):
    """Apply non-conflicting changes once; leave divergent rows untouched.

    A pending receipt never initiates another write. If a crash occurs before
    publication, only an exact match to the planned result can be confirmed.
    The target lease and native ledger lock serialize native writers.
    """
    if type(confirmation_only) is not bool:
        raise MigrationIOError("affairs_sync_request_invalid")
    scope = _scope(source_scope)
    check_affairs_sync_lease(lease, source_scope=scope,
                            baseline_migration_id=getattr(lease, "baseline_migration_id", None))
    root = Path(lease.root)
    record = _load(root, sync_id, scope, lease.agent_id)
    def check_lease():
        check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id=record["baselineMigrationId"])
    check_lease()
    from . import native
    def verify_sources():
        with locked_affairs_target(root, target_agent_id=lease.agent_id) as target:
            _verify_record_sources(root, record, target=target)
    with native._LOCK:
        check_lease()
        verify_sources()
    from core.web.services import personal_affairs_service
    service = personal_affairs_service.get_personal_affairs_service()
    plugin = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != plugin:
        raise MigrationIOError("affairs_target_binding_invalid")
    ledger = plugin / "affairs/items.jsonl"
    receipts = root / "affairs_sync_receipts"
    receipt_path = receipts / (hashlib.sha256(sync_id.encode()).hexdigest() + ".json")
    lock_timeout = 0 if isinstance(lease, OnlineAffairsSyncLease) else DEFAULT_LOCK_TIMEOUT_SECONDS
    with native._LOCK, pinned_target_directory(receipts, create=True), \
            migration_target_lock(receipts), pinned_target_directory(ledger.parent, create=True), \
            pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), cross_process_file_lock(ledger, timeout=lock_timeout), \
            pinned_mutable_file(receipt_path.with_name(receipt_path.name + ".lock")):
        check_lease()
        # Rebind after locks: the archive or conflict record may have changed.
        record = _load(root, sync_id, scope, lease.agent_id)
        check_lease()
        verify_sources()
        binding = {"schemaVersion": 1, "syncId": sync_id, "sourceScope": scope,
                   "targetAgentId": lease.agent_id, "recordSha256": _digest(record)}
        current = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw)
                   if ledger.exists() or ledger.is_symlink() else [])
        if receipt_path.exists() or receipt_path.is_symlink():
            receipt = strict_json(read_stable_file(receipt_path, 1024 * 1024).raw)
            if (not isinstance(receipt, dict) or set(receipt) != set(binding) | {
                    "published", "targetSha256", "appliedCount", "conflictCount", "decisions"}
                    or any(receipt.get(k) != v for k, v in binding.items())
                    or type(receipt.get("schemaVersion")) is not int
                    or type(receipt.get("published")) is not bool
                    or not isinstance(receipt.get("targetSha256"), str)
                    or not _HASH.fullmatch(receipt["targetSha256"])
                    or any(type(receipt.get(k)) is not int or receipt[k] < 0
                           for k in ("appliedCount", "conflictCount"))):
                raise MigrationIOError("affairs_sync_receipt_invalid")
            decisions = receipt.get("decisions")
            if (not isinstance(decisions, list) or len(decisions) != len(record["conflicts"])
                    or any(not isinstance(row, dict) or set(row) != {"conflictId", "status"}
                           or row.get("status") not in {"applied", "already", "unresolved"} for row in decisions)
                    or [row["conflictId"] for row in decisions] != [row["conflictId"] for row in record["conflicts"]]
                    or sum(row["status"] == "applied" for row in decisions) != receipt["appliedCount"]
                    or sum(row["status"] == "unresolved" for row in decisions) != receipt["conflictCount"]):
                raise MigrationIOError("affairs_sync_receipt_invalid")
            if not receipt["published"]:
                if _digest(current) != receipt["targetSha256"]:
                    raise MigrationIOError("affairs_sync_outcome_unknown")
                check_lease()
                atomic_write_json(receipt_path, {**receipt, "published": True}, strict_replace=True, sort_keys=True,
                                  lock_timeout_seconds=lock_timeout)
            return {"syncId": sync_id, "appliedCount": receipt["appliedCount"],
                    "conflictCount": receipt["conflictCount"], "reused": True,
                    "sourceQuiesced": False, "readyForCutover": False}

        if confirmation_only:
            # A recovery request may only confirm a matching existing receipt.
            # It must never issue the original ledger write for the first time.
            raise MigrationIOError("affairs_sync_outcome_unknown")

        by_id = {row["itemId"]: row for row in current}
        applied, conflicts, decisions = 0, 0, []
        for row in record["conflicts"]:
            item_id, old, new = row["itemId"], row["baseline"], row["source"]
            actual = by_id.get(item_id)
            # Absence from a non-quiesced snapshot is not proof of deletion.
            # Even if the target is also absent, advancing the baseline would
            # later treat a reappearing source row as a new item and resurrect
            # a user deletion. Keep this difference unresolved in both cases.
            if new is None:
                conflicts += 1
                decisions.append({"conflictId": row["conflictId"], "status": "unresolved"})
                continue
            if actual == new:
                decisions.append({"conflictId": row["conflictId"], "status": "already"})
                continue
            if actual != old:
                conflicts += 1
                decisions.append({"conflictId": row["conflictId"], "status": "unresolved"})
                continue
            by_id[item_id] = new
            applied += 1
            decisions.append({"conflictId": row["conflictId"], "status": "applied"})
        result_rows = [by_id.pop(row["itemId"]) for row in current if row["itemId"] in by_id]
        result_rows.extend(by_id.values())
        encoded = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                           for row in result_rows)
        if len(result_rows) > AFFAIR_LEDGER_LIMIT or len(encoded) > _BYTE_CAP:
            raise MigrationIOError("affairs_target_row_limit")
        _parse_rows(encoded)
        verify_sources()
        receipt = {**binding, "published": False, "targetSha256": _digest(result_rows),
                   "appliedCount": applied, "conflictCount": conflicts, "decisions": decisions}
        check_lease()
        atomic_write_json(receipt_path, receipt, strict_replace=True, sort_keys=True, lock_timeout_seconds=lock_timeout)
        if applied:
            _replace_ledger(ledger, encoded)
        actual = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw)
                  if ledger.exists() or ledger.is_symlink() else [])
        if actual != result_rows:
            raise MigrationIOError("affairs_sync_outcome_unknown")
        check_lease()
        atomic_write_json(receipt_path, {**receipt, "published": True}, strict_replace=True, sort_keys=True,
                          lock_timeout_seconds=lock_timeout)
        return {"syncId": sync_id, "appliedCount": applied, "conflictCount": conflicts,
                "reused": False, "sourceQuiesced": False, "readyForCutover": False}
