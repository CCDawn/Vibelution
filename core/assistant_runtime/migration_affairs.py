"""Offline, additive copies into the existing personal-affairs activity ledger.

Trust contract: an operator-side caller must independently authenticate and
authorize the legacy PA and bind ``source_scope`` to these exact snapshot or
read-only archive bytes. A content hash establishes integrity, not authority.
No public tool, source-path discovery, grant, queue or reminder state is added.
An immutable byte copy does not establish source quiescence or safe cutover.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.agent_plugins.personal_affairs.service import (
    AFFAIR_KINDS, AFFAIR_LEDGER_LIMIT, AFFAIR_STATUSES, _parse_datetime,
)
from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStorageError
from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock

from .migration_io import (
    FileSnapshot, MigrationIOError, pinned_mutable_file,
    pinned_target_directory, read_stable_file, strict_json, verify_snapshot,
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_BYTE_CAP = 4 * 1024 * 1024
_FIELDS = frozenset({"schemaVersion", "itemId", "kind", "title", "note", "status",
                     "dueAt", "createdAt", "updatedAt", "completedAt", "sourceTurnId"})
_REQUIRED = frozenset({"schemaVersion", "itemId", "kind", "title", "status", "createdAt"})


def _token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _parse_rows(raw: bytes) -> list[dict]:
    """Reject the whole input instead of inheriting the store's lenient reads."""
    if not isinstance(raw, bytes) or len(raw) > _BYTE_CAP:
        raise MigrationIOError("affairs_byte_limit")
    lines = raw.splitlines()
    if len(lines) > AFFAIR_LEDGER_LIMIT:
        raise MigrationIOError("affairs_row_limit")
    rows, seen = [], set()
    for line in lines:
        if not line.strip():
            continue
        row = strict_json(line)
        if (not isinstance(row, dict) or not _REQUIRED.issubset(row) or set(row) - _FIELDS
                or type(row.get("schemaVersion")) is not int or row["schemaVersion"] != 1
                or not _token(row.get("itemId")) or row.get("kind") not in AFFAIR_KINDS
                or row.get("status") not in AFFAIR_STATUSES):
            raise MigrationIOError("affairs_row_invalid")
        for key, maximum in (("title", 160), ("note", 600), ("sourceTurnId", 200)):
            value = row.get(key, "")
            if (not isinstance(value, str) or len(value) > maximum
                    or (key == "title" and not value.strip())):
                raise MigrationIOError("affairs_row_invalid")
        for key in ("createdAt", "updatedAt", "dueAt", "completedAt"):
            value = row.get(key, "")
            if (not isinstance(value, str) or len(value) > 64
                    or (value and _parse_datetime(value) is None)
                    or (key == "createdAt" and not value)):
                raise MigrationIOError("affairs_row_invalid")
        if row["itemId"] in seen:
            raise MigrationIOError("affairs_duplicate_item_id")
        seen.add(row["itemId"])
        rows.append(row)
    return rows


def _check_lease(lease):
    from .migration_profile import OfflineMigrationProfileLease
    if not isinstance(lease, OfflineMigrationProfileLease):
        raise MigrationIOError("affairs_profile_lease_required")
    try:
        lease.check()
    except RuntimeError:
        raise MigrationIOError("affairs_profile_lease_required") from None


def _source_bytes(source, source_sha256):
    if not isinstance(source_sha256, str) or not _HASH.fullmatch(source_sha256):
        raise MigrationIOError("affairs_source_hash_invalid")
    if isinstance(source, FileSnapshot):
        if not isinstance(source.raw, bytes) or len(source.raw) > _BYTE_CAP:
            raise MigrationIOError("affairs_byte_limit")
        if tuple(source.path.parts[-3:]) != ("personal-affairs", "affairs", "items.jsonl"):
            raise MigrationIOError("affairs_source_path_invalid")
        if source.sha256 != source_sha256:
            raise MigrationIOError("affairs_source_hash_mismatch")
        verify_snapshot(source)
        raw = source.raw
    elif isinstance(source, bytes):
        raw = source
    else:
        raise MigrationIOError("affairs_source_required")
    if len(raw) > _BYTE_CAP:
        raise MigrationIOError("affairs_byte_limit")
    if hashlib.sha256(raw).hexdigest() != source_sha256:
        raise MigrationIOError("affairs_source_hash_mismatch")
    return raw


def _write_receipt(path, receipt):
    # Shared strict atomic writer; both lock leaves are pinned by the caller.
    atomic_write_json(path, receipt, strict_replace=True, sort_keys=True)


def _result(binding, *, imported_count, idempotent):
    return {**binding, "importedCount": imported_count, "idempotent": idempotent,
            "sourceQuiesced": False, "readyForCutover": False}


def import_affairs(lease, source: FileSnapshot | bytes, *, source_scope: dict,
                   source_sha256: str, migration_id: str) -> dict:
    """Import only an authorized legacy PA's activity snapshot, preserving rows.

    ``lease`` must come from ``offline_migration_profile()`` before native
    bootstrap, never from an agent ID supplied by a tool. The persisted receipt
    binds migration ID, source scope, content hash and independently verified
    target identity before the ledger changes. A published receipt prevents
    replay over user changes. An unfinished receipt permits only that same
    request to recover; identical existing IDs are read back and conflicting
    IDs reject the complete request. No eviction at the native 2048-row limit.
    """
    _check_lease(lease)
    if not _token(migration_id):
        raise MigrationIOError("affairs_migration_id_invalid")
    if (not isinstance(source_scope, dict) or set(source_scope) != {"projectId", "instanceId", "agentId"}
            or any(not _token(value) for value in source_scope.values())):
        raise MigrationIOError("affairs_source_scope_invalid")
    raw = _source_bytes(source, source_sha256)
    rows = _parse_rows(raw)
    binding = {"schemaVersion": 1, "migrationId": migration_id, "sourceScope": dict(source_scope),
               "sourceSha256": source_sha256, "targetAgentId": lease.agent_id, "itemCount": len(rows)}
    from . import native
    from core.web.services import personal_affairs_service
    service = personal_affairs_service.get_personal_affairs_service()
    root = Path(lease.root)
    expected = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != expected:
        raise MigrationIOError("affairs_target_binding_invalid")
    ledger = expected / "affairs/items.jsonl"
    receipts = root / "affairs_migrations"
    receipt_path = receipts / (hashlib.sha256(migration_id.encode()).hexdigest() + ".json")
    try:
        # Native command admission and native ledger writers retain their own
        # locks. The outer lease already holds the non-reentrant host OS lock.
        with native._LOCK, pinned_target_directory(ledger.parent, create=True), \
                pinned_target_directory(receipts, create=True), \
                pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), \
                pinned_mutable_file(receipt_path.with_name(receipt_path.name + ".lock")), \
                cross_process_file_lock(ledger):
            _check_lease(lease)
            pending = False
            if receipt_path.exists() or receipt_path.is_symlink():
                receipt = strict_json(read_stable_file(receipt_path, 16 * 1024).raw)
                if (not isinstance(receipt, dict) or type(receipt.get("published")) is not bool
                        or type(receipt.get("schemaVersion")) is not int
                        or type(receipt.get("itemCount")) is not int
                        or receipt != {**binding, "published": receipt["published"]}):
                    raise MigrationIOError("affairs_migration_id_conflict")
                if receipt["published"]:
                    _check_lease(lease)
                    return _result(binding, imported_count=0, idempotent=True)
                pending = True
            if isinstance(source, FileSnapshot):
                verify_snapshot(source)
            existing = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw)
                        if ledger.exists() or ledger.is_symlink() else [])
            by_id = {row["itemId"]: row for row in existing}
            additions = []
            for row in rows:
                previous = by_id.get(row["itemId"])
                if previous is not None and previous != row:
                    raise MigrationIOError("affairs_target_item_conflict")
                if previous is None:
                    additions.append(row)
            if len(existing) + len(additions) > AFFAIR_LEDGER_LIMIT:
                raise MigrationIOError("affairs_target_row_limit")
            _check_lease(lease)
            if not pending:
                # Persist the request identity before its first ledger write.
                # A crash can leave partial publication, never an unbound ID.
                _write_receipt(receipt_path, {**binding, "published": False})
                _check_lease(lease)
            if additions:
                # Direct store write deliberately avoids _write_rows' tail
                # truncation; all native tools read this same activity ledger.
                service.store.write_jsonl(lease.agent_id, "affairs/items.jsonl", existing + additions)
            # Read back even on a crash-recovery retry before publishing the
            # receipt. No source content or item payload enters the receipt.
            actual = _parse_rows(read_stable_file(ledger, _BYTE_CAP).raw) if existing or additions else []
            if actual != existing + additions:
                raise MigrationIOError("affairs_target_readback_mismatch")
            _check_lease(lease)
            _write_receipt(receipt_path, {**binding, "published": True})
            _check_lease(lease)
            return _result(binding, imported_count=len(additions), idempotent=False)
    except (OSError, TimeoutError, VirtualHumanLifeStorageError):
        raise MigrationIOError("affairs_target_unavailable") from None


__all__ = ["import_affairs"]
