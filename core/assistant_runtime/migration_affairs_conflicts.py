"""Isolated, read-only records for ambiguous legacy affairs changes.

The operator must authenticate and archive each source snapshot first.  Hashes
verify those bytes, not their authority.  No record here is an active affair,
and neither this module nor its readers change the native ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import DEFAULT_LOCK_TIMEOUT_SECONDS, cross_process_file_lock

from .migration_affairs import _BYTE_CAP, _parse_rows, _token
from .online_affairs_sync_lease import check_affairs_sync_lease
from .migration_io import (MigrationIOError, check_path, existing_migration_file_lock, migration_target_lock, pinned_mutable_file,
    path_identity, pinned_source_files, pinned_target_directory, read_stable_file, strict_json, verify_snapshot)

_RECORD_CAP = 16 * 1024 * 1024
_SYNC_RECEIPT_CAP = 1024 * 1024
_CHAIN_LIMIT = 256
_SYNC_RECORD_LIMIT = 4096
_CHAIN_BYTE_LIMIT = 64 * 1024 * 1024
_target_context = threading.local()


class _LockedAffairsTarget:
    def __init__(self, root, agent_id, session_id, ledger, snapshot, pins):
        self.root, self.agent_id, self.session_id = root, agent_id, session_id
        self.ledger, self.snapshot = ledger, snapshot
        self.pins, self.pinned_proofs = pins, set()
        self.thread_id = threading.get_ident()
        self.active = True

    def check(self, root, agent_id):
        from . import native
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services.session import directory_runtime
        if (not self.active or getattr(_target_context, "active", None) is not self
                or self.thread_id != threading.get_ident() or self.root != Path(root)
                or self.agent_id != agent_id or not native._LOCK._is_owned()
                or not native._STARTED or native._STOP_REQUESTED.is_set() or native._AGENT_ID != agent_id
                or native._SESSION_ID != self.session_id or assistant_native_root() != self.root
                or directory_runtime.directory_store_project_root() != self.root):
            raise MigrationIOError("affairs_target_lock_required")
        if self.snapshot is not None:
            verify_snapshot(self.snapshot)
        elif self.ledger.exists() or self.ledger.is_symlink():
            raise MigrationIOError("source_changed")

    def rows(self, root, agent_id):
        self.check(root, agent_id)
        return _parse_rows(self.snapshot.raw) if self.snapshot is not None else []

    def pin_proof(self, snapshot, marker):
        from core.web.services.personal_assistant_project.windows_read import lock_source_directory
        from .migration_history import _confirmation_exists
        self.check(self.root, self.agent_id)
        key = str(snapshot.path).casefold()
        if key not in self.pinned_proofs:
            self.pins.enter_context(pinned_source_files((snapshot,)))
            self.pins.enter_context(lock_source_directory(Path(marker.anchor), marker, allow_child_replacement=True))
            self.pinned_proofs.add(key)
        verify_snapshot(snapshot)
        if not _confirmation_exists(marker.parent):
            raise MigrationIOError("source_changed")


@contextmanager
def locked_affairs_target(root, *, target_agent_id, readonly=False):
    """Pin the bound ledger while caller already holds native._LOCK.

    Online callers must hold their generation/Turn guard first. Order is
    native lock -> receipts mutex -> ledger lock; callers already holding a
    conflict-directory mutex must acquire it before entering this helper.
    """
    from . import native
    from core.infrastructure.native_runtime import assistant_native_root
    from core.web.services import personal_affairs_service
    from core.web.services.session import directory_runtime
    root = Path(root)
    if (not native._LOCK._is_owned() or not native._STARTED or native._STOP_REQUESTED.is_set()
            or native._AGENT_ID != target_agent_id or assistant_native_root() != root
            or directory_runtime.directory_store_project_root() != root):
        raise MigrationIOError("affairs_target_lock_required")
    service = personal_affairs_service.get_personal_affairs_service()
    plugin = root / "agents" / target_agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(target_agent_id) != plugin:
        raise MigrationIOError("affairs_target_binding_invalid")
    ledger = plugin / "affairs/items.jsonl"
    receipts = root / "affairs_sync_receipts"
    lock = (existing_migration_file_lock(ledger, timeout=DEFAULT_LOCK_TIMEOUT_SECONDS if native._OFFLINE_MIGRATION else 0) if readonly else
            cross_process_file_lock(ledger) if native._OFFLINE_MIGRATION else cross_process_file_lock(ledger, timeout=0))
    if type(readonly) is not bool:
        raise MigrationIOError("affairs_target_lock_required")
    with ExitStack() as stack:
        stack.enter_context(pinned_target_directory(receipts, create=not readonly))
        stack.enter_context(migration_target_lock(receipts))
        stack.enter_context(pinned_target_directory(ledger.parent, create=not readonly))
        if not readonly:
            leaf = ledger.with_name(ledger.name + ".lock")
            stack.enter_context(pinned_mutable_file(leaf))
        stack.enter_context(lock)
        snapshot = read_stable_file(ledger, _BYTE_CAP) if ledger.exists() or ledger.is_symlink() else None
        if snapshot is not None:
            stack.enter_context(pinned_source_files((snapshot,)))
        token = _LockedAffairsTarget(root, target_agent_id, native._SESSION_ID, ledger, snapshot, stack)
        previous = getattr(_target_context, "active", None)
        _target_context.active = token
        try:
            token.check(root, target_agent_id)
            yield token
        finally:
            token.active = False
            _target_context.active = previous


def _scope(scope):
    if (not isinstance(scope, dict) or set(scope) != {"projectId", "instanceId", "agentId"}
            or any(not _token(value) for value in scope.values())):
        raise MigrationIOError("affairs_conflict_scope_invalid")
    return dict(scope)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _archive(root, migration_id, scope):
    if not _token(migration_id):
        raise MigrationIOError("affairs_conflict_id_invalid")
    directory = root / "history_sources" / "migrations" / migration_id
    from .migration_history import _confirmation_exists
    if not _confirmation_exists(directory):
        raise MigrationIOError("affairs_conflict_archive_unconfirmed")
    manifest = read_stable_file(directory / "manifest.json", _RECORD_CAP)
    data = strict_json(manifest.raw)
    if (not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data.get("schemaVersion") not in (1, 2)
            or data.get("migrationId") != migration_id or data.get("sourceScope") != scope
            or data.get("readOnly") is not True or data.get("untrustedContent") is not True
            or not isinstance(data.get("entries"), list)):
        raise MigrationIOError("affairs_conflict_archive_invalid")
    entries = [entry for entry in data["entries"] if isinstance(entry, dict)
        and entry.get("category") == "personal_affairs"
        and isinstance(entry.get("sourceRef"), str)
        and entry.get("path") == f"sources/{entry['sourceRef']}/affairs/items.jsonl"]
    if len(entries) != 1 or not _token(entries[0]["sourceRef"]):
        raise MigrationIOError("affairs_conflict_archive_invalid")
    entry = entries[0]
    source = read_stable_file(directory / "sources" / entry["sourceRef"] / "affairs" / "items.jsonl", _BYTE_CAP)
    if (entry.get("sha256") != source.sha256 or type(entry.get("size")) is not int
            or entry["size"] != len(source.raw)):
        raise MigrationIOError("affairs_conflict_archive_invalid")
    rows = _parse_rows(source.raw)
    verify_snapshot(manifest)
    verify_snapshot(source)
    if not _confirmation_exists(directory):
        raise MigrationIOError("affairs_conflict_archive_unconfirmed")
    return rows, source.sha256


def _record_path(root, sync_id):
    if not _token(sync_id):
        raise MigrationIOError("affairs_conflict_id_invalid")
    return root / "affairs_conflicts" / (hashlib.sha256(sync_id.encode()).hexdigest() + ".json")


def _load(root, sync_id, scope, target_agent_id):
    if not _token(target_agent_id):
        raise MigrationIOError("affairs_conflict_target_invalid")
    record = strict_json(read_stable_file(_record_path(root, sync_id), _RECORD_CAP).raw)
    if (not isinstance(record, dict) or type(record.get("schemaVersion")) is not int or record.get("schemaVersion") != 1
            or record.get("syncId") != sync_id or record.get("sourceScope") != scope
            or record.get("targetAgentId") != target_agent_id or record.get("readOnly") is not True
            or record.get("untrustedContent") is not True or not isinstance(record.get("conflicts"), list)
            or not _token(record.get("baselineMigrationId")) or not _token(record.get("snapshotMigrationId"))
            or any(not isinstance(record.get(key), str) or len(record[key]) != 64
                   or any(ch not in "0123456789abcdef" for ch in record[key])
                   for key in ("baselineSha256", "snapshotSha256"))
            or len(record["conflicts"]) > 4096):
        raise MigrationIOError("affairs_conflict_record_invalid")
    for row in record["conflicts"]:
        if (not isinstance(row, dict) or set(row) != {"conflictId", "itemId", "kind", "baseline", "source", "target", "targetState"}
                or row.get("kind") not in {"added", "changed", "removed"}
                or not _token(row.get("itemId")) or row.get("conflictId") != _digest({
                    "syncId": sync_id, "sourceScope": scope, "itemId": row["itemId"], "kind": row["kind"]})
                or row.get("targetState") not in {"present", "missing"}
                or (row.get("target") is None) != (row["targetState"] == "missing")):
            raise MigrationIOError("affairs_conflict_record_invalid")
        for key in ("baseline", "source", "target"):
            value = row.get(key)
            if value is not None and (_parse_rows(_encoded(value) + b"\n") != [value]
                                      or value["itemId"] != row["itemId"]):
                raise MigrationIOError("affairs_conflict_record_invalid")
    return record


def _verify_diff(record, before, after):
    old = {row["itemId"]: row for row in before}
    new = {row["itemId"]: row for row in after}
    changed = {item_id for item_id in old.keys() | new.keys() if old.get(item_id) != new.get(item_id)}
    if (len(record["conflicts"]) != len(changed)
            or {row["itemId"] for row in record["conflicts"]} != changed):
        raise MigrationIOError("affairs_conflict_record_invalid")
    for row in record["conflicts"]:
        item_id = row["itemId"]
        kind = "added" if item_id not in old else "removed" if item_id not in new else "changed"
        if row["kind"] != kind or row["baseline"] != old.get(item_id) or row["source"] != new.get(item_id):
            raise MigrationIOError("affairs_conflict_record_invalid")


def _sync_receipt(root, record):
    """Validate the receipt against this exact immutable diff; absence is not success."""
    sync_id = record["syncId"]
    path = root / "affairs_sync_receipts" / (hashlib.sha256(sync_id.encode()).hexdigest() + ".json")
    if not path.exists() and not path.is_symlink():
        return None, None
    snapshot = read_stable_file(path, _SYNC_RECEIPT_CAP)
    receipt = strict_json(snapshot.raw)
    binding = {"schemaVersion": 1, "syncId": sync_id, "sourceScope": record["sourceScope"],
               "targetAgentId": record["targetAgentId"], "recordSha256": _digest(record)}
    if (not isinstance(receipt, dict) or set(receipt) != set(binding) | {
            "published", "targetSha256", "appliedCount", "conflictCount", "decisions"}
            or any(receipt.get(key) != value for key, value in binding.items())
            or type(receipt.get("schemaVersion")) is not int or type(receipt.get("published")) is not bool
            or not isinstance(receipt.get("targetSha256"), str) or len(receipt["targetSha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in receipt["targetSha256"])
            or any(type(receipt.get(key)) is not int or receipt[key] < 0 for key in ("appliedCount", "conflictCount"))):
        raise MigrationIOError("affairs_sync_receipt_invalid")
    decisions = receipt.get("decisions")
    if (not isinstance(decisions, list) or len(decisions) != len(record["conflicts"])
            or any(not isinstance(row, dict) or set(row) != {"conflictId", "status"}
                   or row.get("status") not in {"applied", "already", "unresolved"} for row in decisions)
            or [row["conflictId"] for row in decisions] != [row["conflictId"] for row in record["conflicts"]]
            or sum(row["status"] == "applied" for row in decisions) != receipt["appliedCount"]
            or sum(row["status"] == "unresolved" for row in decisions) != receipt["conflictCount"]):
        raise MigrationIOError("affairs_sync_receipt_invalid")
    return receipt, snapshot


def _sync_candidates(root, scope, target_agent_id):
    directory = root / "affairs_sync_receipts"
    if not directory.exists() and not directory.is_symlink():
        return {}
    check_path(directory)
    candidates = {}
    observed_bytes, record_count = 0, 0
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 2 * _SYNC_RECORD_LIMIT:
                raise MigrationIOError("affairs_sync_receipt_limit")
            if entry.name.endswith(".json.lock"):
                check_path(Path(entry.path))
                continue
            if not entry.name.endswith(".json"):
                raise MigrationIOError("affairs_sync_receipt_invalid")
            record_count += 1
            if record_count > _SYNC_RECORD_LIMIT:
                raise MigrationIOError("affairs_sync_receipt_limit")
            probe = read_stable_file(Path(entry.path), _SYNC_RECEIPT_CAP)
            observed_bytes += len(probe.raw)
            if observed_bytes > _CHAIN_BYTE_LIMIT:
                raise MigrationIOError("affairs_sync_receipt_limit")
            raw = strict_json(probe.raw)
            if (not isinstance(raw, dict) or not _token(raw.get("syncId"))
                    or Path(entry.path) != directory / (hashlib.sha256(raw["syncId"].encode()).hexdigest() + ".json")):
                raise MigrationIOError("affairs_sync_receipt_invalid")
            try:
                _scope(raw.get("sourceScope"))
            except MigrationIOError:
                raise MigrationIOError("affairs_sync_receipt_invalid") from None
            if not _token(raw.get("targetAgentId")):
                raise MigrationIOError("affairs_sync_receipt_invalid")
            if raw.get("sourceScope") != scope or raw.get("targetAgentId") != target_agent_id:
                continue
            record_snapshot = read_stable_file(_record_path(root, raw["syncId"]), _RECORD_CAP)
            observed_bytes += 2 * len(record_snapshot.raw) + len(probe.raw)
            if observed_bytes > _CHAIN_BYTE_LIMIT:
                raise MigrationIOError("affairs_sync_receipt_limit")
            record = _load(root, raw["syncId"], scope, target_agent_id)
            if strict_json(record_snapshot.raw) != record:
                raise MigrationIOError("affairs_conflict_record_invalid")
            receipt, receipt_snapshot = _sync_receipt(root, record)
            if receipt is None:
                raise MigrationIOError("affairs_sync_receipt_invalid")
            candidates.setdefault(record.get("snapshotMigrationId"), []).append(
                (record, receipt, record_snapshot, receipt_snapshot))
    return candidates


class _BaselineVerifier:
    """Bounded per-query proof cache; final verification closes every cached read."""
    def __init__(self, root, scope, target_agent_id, *, target=None):
        self.root, self.scope, self.target_agent_id = root, scope, target_agent_id
        if target is not None:
            if not isinstance(target, _LockedAffairsTarget):
                raise MigrationIOError("affairs_target_lock_required")
            target.check(root, target_agent_id)
        self.target = target
        self.archives, self.depths, self.snapshots = {}, {}, []
        self.proof_markers = []
        self.candidates = None
        self.observed_bytes = 0

    def archive(self, mid):
        if mid not in self.archives:
            rows, digest = _archive(self.root, mid, self.scope)
            self.observed_bytes += sum(len(_encoded(row)) + 1 for row in rows)
            if self.observed_bytes > _CHAIN_BYTE_LIMIT:
                raise MigrationIOError("affairs_conflict_baseline_chain_limit")
            self.archives[mid] = (rows, digest)
        return self.archives[mid]

    def baseline(self, migration_id):
        seen, pending, current = set(), [], migration_id
        while True:
            if not _token(current) or current in seen:
                raise MigrationIOError("affairs_conflict_baseline_cycle")
            if current in self.depths:
                depth = self.depths[current]
                if len(pending) + depth > _CHAIN_LIMIT:
                    raise MigrationIOError("affairs_conflict_baseline_chain_limit")
                break
            if len(pending) >= _CHAIN_LIMIT:
                raise MigrationIOError("affairs_conflict_baseline_chain_limit")
            seen.add(current)
            rows, digest = self.archive(current)
            receipt_path = self.root / "affairs_migrations" / (hashlib.sha256(current.encode()).hexdigest() + ".json")
            if receipt_path.exists() or receipt_path.is_symlink():
                snapshot = read_stable_file(receipt_path, 16 * 1024)
                receipt = strict_json(snapshot.raw)
                expected = {"schemaVersion": 1, "migrationId": current, "sourceScope": self.scope,
                    "sourceSha256": digest, "targetAgentId": self.target_agent_id,
                    "itemCount": len(rows), "published": True}
                if (not isinstance(receipt, dict) or receipt != expected or type(receipt.get("published")) is not bool
                        or type(receipt.get("schemaVersion")) is not int or type(receipt.get("itemCount")) is not int):
                    raise MigrationIOError("affairs_conflict_baseline_unbound")
                self.snapshots.append(snapshot)
                self.depths[current] = depth = 1
                break
            if self.candidates is None:
                self.candidates = _sync_candidates(self.root, self.scope, self.target_agent_id)
            links = self.candidates.get(current, [])
            if len(links) != 1:
                raise MigrationIOError("affairs_conflict_baseline_unbound")
            record, receipt, record_snapshot, receipt_snapshot = links[0]
            if receipt["published"] is not True:
                raise MigrationIOError("affairs_conflict_baseline_unbound")
            prior = record.get("baselineMigrationId")
            before, before_hash = self.archive(prior)
            if record.get("baselineSha256") != before_hash or record.get("snapshotSha256") != digest:
                raise MigrationIOError("affairs_conflict_baseline_unbound")
            _verify_diff(record, before, rows)
            if receipt["conflictCount"] != 0 and not self.converged(record, receipt):
                raise MigrationIOError("affairs_conflict_baseline_unbound")
            self.snapshots.extend((record_snapshot, receipt_snapshot))
            pending.append(current)
            current = prior
        for mid in reversed(pending):
            depth += 1
            if depth > _CHAIN_LIMIT:
                raise MigrationIOError("affairs_conflict_baseline_chain_limit")
            self.depths[mid] = depth
        return self.archive(migration_id)

    def finish(self):
        if self.target is not None:
            self.target.check(self.root, self.target_agent_id)
        for snapshot in self.snapshots:
            verify_snapshot(snapshot)
        for mid, (_, digest) in self.archives.items():
            if _archive(self.root, mid, self.scope)[1] != digest:
                raise MigrationIOError("source_changed")
        if self.candidates is not None:
            def fingerprints(candidates):
                return sorted((mid, _digest(record), _digest(receipt)) for mid, links in candidates.items()
                              for record, receipt, _, _ in links)
            if fingerprints(self.candidates) != fingerprints(_sync_candidates(self.root, self.scope, self.target_agent_id)):
                raise MigrationIOError("source_changed")
        for marker, identity in self.proof_markers:
            from .migration_history import _confirmation_exists
            if not _confirmation_exists(marker.parent) or path_identity(marker) != identity:
                raise MigrationIOError("source_changed")
        if self.target is not None:
            self.target.check(self.root, self.target_agent_id)

    def converged(self, record, receipt):
        if self.target is None:
            return False
        from .migration_affairs_convergence import _proof_directory, _verified_historical_convergence_snapshot
        from .migration_history import _confirmation_exists
        self.target.check(self.root, self.target_agent_id)
        snapshot = _verified_historical_convergence_snapshot(self.root, record, receipt)
        if snapshot is None:
            return False
        marker = _proof_directory(self.root, record["syncId"]) / ".confirmed"
        if not _confirmation_exists(marker.parent):
            return False
        self.target.pin_proof(snapshot, marker)
        self.snapshots.append(snapshot)
        self.proof_markers.append((marker, path_identity(marker)))
        return True


def _verified_baseline(root, migration_id, scope, target_agent_id, *, target=None):
    """Follow a bounded, unambiguous chain to a confirmed initial import."""
    verifier = _BaselineVerifier(root, scope, target_agent_id, target=target)
    result = verifier.baseline(migration_id)
    verifier.finish()
    return result


def _verify_record_sources(root, record, verifier=None, *, target=None):
    """Recheck the source snapshots and the entire published baseline chain."""
    scope = _scope(record["sourceScope"])
    if record.get("baselineMigrationId") == record.get("snapshotMigrationId"):
        raise MigrationIOError("affairs_conflict_baseline_cycle")
    owned = verifier is None
    verifier = verifier or _BaselineVerifier(root, scope, record["targetAgentId"], target=target)
    before, before_hash = verifier.baseline(record.get("baselineMigrationId"))
    after, after_hash = verifier.archive(record.get("snapshotMigrationId"))
    if before_hash != record.get("baselineSha256") or after_hash != record.get("snapshotSha256"):
        raise MigrationIOError("affairs_conflict_baseline_unbound")
    _verify_diff(record, before, after)
    if owned:
        verifier.finish()


def _baseline_inventory(directory, invalid_code):
    """Bounded, read-only directory inventory, including lock names for race checks."""
    if not directory.exists() and not directory.is_symlink():
        return ()
    check_path(directory)
    names, record_count = [], 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) >= 2 * _SYNC_RECORD_LIMIT:
                raise MigrationIOError("affairs_baseline_inventory_limit")
            name = entry.name
            if name.endswith(".json.lock"):
                check_path(Path(entry.path))
            elif name.endswith(".json"):
                record_count += 1
                if record_count > _SYNC_RECORD_LIMIT:
                    raise MigrationIOError("affairs_baseline_inventory_limit")
            else:
                raise MigrationIOError(invalid_code)
            names.append(name)
    return tuple(sorted(names))


def _discover_affairs_baseline(root, *, source_scope, target_agent_id, ignore_sync_id=None, target=None):
    """Find a unique complete source lineage; this grants no sync or cutover authority.

    A missing receipt is pending, not an implicit success. All matching source
    records must form a single chain from exactly one confirmed import. The
    returned snapshot is read-only and must be revalidated under the writer's
    lease; it is not a statement about the target's current rows.
    """
    scope = _scope(source_scope)
    if not _token(target_agent_id):
        raise MigrationIOError("affairs_conflict_target_invalid")
    root = Path(root)
    imports = root / "affairs_migrations"
    records = root / "affairs_conflicts"
    receipts = root / "affairs_sync_receipts"
    directories = (imports, records, receipts)
    codes = ("affairs_conflict_baseline_unbound", "affairs_conflict_record_invalid", "affairs_sync_receipt_invalid")
    inventories = tuple(_baseline_inventory(path, code) for path, code in zip(directories, codes))
    captured, anchors, observed_bytes = [], [], 0
    for name in inventories[0]:
        if name.endswith(".json.lock"):
            continue
        path = imports / name
        snapshot = read_stable_file(path, 16 * 1024)
        observed_bytes += len(snapshot.raw)
        if observed_bytes > _CHAIN_BYTE_LIMIT:
            raise MigrationIOError("affairs_baseline_inventory_limit")
        receipt = strict_json(snapshot.raw)
        required = {"schemaVersion", "migrationId", "sourceScope", "sourceSha256", "targetAgentId", "itemCount", "published"}
        if (not isinstance(receipt, dict) or set(receipt) != required or type(receipt.get("schemaVersion")) is not int
                or receipt["schemaVersion"] != 1 or not _token(receipt.get("migrationId"))
                or name != hashlib.sha256(receipt["migrationId"].encode()).hexdigest() + ".json"
                or not _token(receipt.get("targetAgentId")) or type(receipt.get("itemCount")) is not int
                or receipt["itemCount"] < 0 or type(receipt.get("published")) is not bool
                or not isinstance(receipt.get("sourceSha256"), str) or len(receipt["sourceSha256"]) != 64
                or any(ch not in "0123456789abcdef" for ch in receipt["sourceSha256"])):
            raise MigrationIOError("affairs_conflict_baseline_unbound")
        receipt_scope = _scope(receipt.get("sourceScope"))
        captured.append(snapshot)
        if receipt_scope != scope or receipt["targetAgentId"] != target_agent_id:
            continue
        if receipt["published"] is not True:
            raise MigrationIOError("affairs_baseline_pending")
        anchors.append(receipt["migrationId"])
    if not anchors:
        raise MigrationIOError("affairs_baseline_not_found")
    if len(anchors) != 1:
        raise MigrationIOError("affairs_baseline_ambiguous")

    # Also pin the observations of unrelated receipts: one changing identity
    # during discovery must not silently become a second matching lineage.
    for name in inventories[2]:
        if name.endswith(".json.lock"):
            continue
        snapshot = read_stable_file(receipts / name, _SYNC_RECEIPT_CAP)
        observed_bytes += len(snapshot.raw)
        if observed_bytes > _CHAIN_BYTE_LIMIT:
            raise MigrationIOError("affairs_baseline_inventory_limit")
        captured.append(snapshot)

    verifier = _BaselineVerifier(root, scope, target_agent_id, target=target)
    verifier.baseline(anchors[0])
    verifier.candidates = _sync_candidates(root, scope, target_agent_id)
    candidates_by_sync = {record["syncId"] for links in verifier.candidates.values() for record, _, _, _ in links}
    if ignore_sync_id is not None:
        if not _token(ignore_sync_id):
            raise MigrationIOError("affairs_conflict_id_invalid")
        candidates_by_sync.discard(ignore_sync_id)
    seen_sync, outgoing, incoming = set(), {}, {}
    for name in inventories[1]:
        if name.endswith(".json.lock"):
            continue
        path = records / name
        snapshot = read_stable_file(path, _RECORD_CAP)
        observed_bytes += len(snapshot.raw)
        if observed_bytes > _CHAIN_BYTE_LIMIT:
            raise MigrationIOError("affairs_baseline_inventory_limit")
        raw = strict_json(snapshot.raw)
        if (not isinstance(raw, dict) or not _token(raw.get("syncId"))
                or path != _record_path(root, raw["syncId"]) or not _token(raw.get("targetAgentId"))):
            raise MigrationIOError("affairs_conflict_record_invalid")
        record_scope = _scope(raw.get("sourceScope"))
        captured.append(snapshot)
        if record_scope != scope or raw["targetAgentId"] != target_agent_id:
            continue
        record = _load(root, raw["syncId"], scope, target_agent_id)
        if strict_json(snapshot.raw) != record:
            raise MigrationIOError("affairs_conflict_record_invalid")
        receipt, receipt_snapshot = _sync_receipt(root, record)
        if record["syncId"] == ignore_sync_id:
            _verify_record_sources(root, record, verifier)
            if receipt_snapshot is not None:
                captured.append(receipt_snapshot)
            continue
        if receipt is None or receipt["published"] is not True:
            raise MigrationIOError("affairs_baseline_pending")
        _verify_record_sources(root, record, verifier)
        if receipt["conflictCount"] != 0 and not verifier.converged(record, receipt):
            raise MigrationIOError("affairs_baseline_unresolved")
        before, after = record["baselineMigrationId"], record["snapshotMigrationId"]
        if before in outgoing or after in incoming:
            raise MigrationIOError("affairs_baseline_ambiguous")
        outgoing[before], incoming[after] = after, before
        seen_sync.add(record["syncId"])
        captured.append(receipt_snapshot)
    if seen_sync != candidates_by_sync:
        raise MigrationIOError("affairs_baseline_ambiguous")
    current, visited = anchors[0], set()
    while current in outgoing:
        if current in visited:
            raise MigrationIOError("affairs_conflict_baseline_cycle")
        visited.add(current)
        current = outgoing[current]
        if len(visited) > _CHAIN_LIMIT:
            raise MigrationIOError("affairs_conflict_baseline_chain_limit")
    if current in visited:
        raise MigrationIOError("affairs_conflict_baseline_cycle")
    if len(visited) != len(outgoing):
        raise MigrationIOError("affairs_baseline_ambiguous")
    _, digest = verifier.baseline(current)
    verifier.finish()
    for snapshot in captured:
        verify_snapshot(snapshot)
    if tuple(_baseline_inventory(path, code) for path, code in zip(directories, codes)) != inventories:
        raise MigrationIOError("source_changed")
    return {"baselineMigrationId": current, "sourceSha256": digest, "sourceScope": scope,
            "targetAgentId": target_agent_id, "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}


def discover_affairs_baseline(root, *, source_scope, target_agent_id):
    return _discover_affairs_baseline(root, source_scope=source_scope, target_agent_id=target_agent_id)


def discover_affairs_baseline_locked(root, *, source_scope, target_agent_id, target):
    """Read a baseline with a live token from locked_affairs_target."""
    return _discover_affairs_baseline(root, source_scope=source_scope,
                                      target_agent_id=target_agent_id, target=target)


def verified_affairs_baseline_locked(root, migration_id, scope, target_agent_id, *, target):
    """Validate a specific baseline with a live token from locked_affairs_target."""
    if not isinstance(target, _LockedAffairsTarget):
        raise MigrationIOError("affairs_target_lock_required")
    target.check(root, target_agent_id)
    return _verified_baseline(root, migration_id, scope, target_agent_id, target=target)


def discover_affairs_conflicts(root, *, target_agent_id, offset=0, limit=6, target=None):
    """Discover conflict sets for the trusted native profile without user IDs."""
    if not _token(target_agent_id) or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12:
        raise MigrationIOError("affairs_conflict_query_invalid")
    root = Path(root)
    directory = root / "affairs_conflicts"
    if not directory.exists() and not directory.is_symlink():
        return {"sets": [], "total": 0, "nextOffset": None, "readOnly": True, "untrustedContent": True}
    rows, verifiers, captured = [], {}, []
    check_path(directory)
    with os.scandir(directory) as entries:
        observed_bytes, record_count = 0, 0
        for index, entry in enumerate(entries):
            if index >= 2 * _SYNC_RECORD_LIMIT:
                raise MigrationIOError("affairs_conflict_record_limit")
            if entry.name.endswith(".json.lock"):
                check_path(Path(entry.path))
                continue
            if not entry.name.endswith(".json"):
                raise MigrationIOError("affairs_conflict_record_invalid")
            record_count += 1
            if record_count > _SYNC_RECORD_LIMIT:
                raise MigrationIOError("affairs_conflict_record_limit")
            snapshot = read_stable_file(Path(entry.path), _RECORD_CAP)
            observed_bytes += len(snapshot.raw)
            if observed_bytes > _CHAIN_BYTE_LIMIT:
                raise MigrationIOError("affairs_conflict_record_limit")
            raw = strict_json(snapshot.raw)
            if not isinstance(raw, dict) or not _token(raw.get("syncId")) or Path(entry.path) != _record_path(root, raw["syncId"]):
                raise MigrationIOError("affairs_conflict_record_invalid")
            if raw.get("targetAgentId") != target_agent_id:
                raise MigrationIOError("affairs_conflict_target_invalid")
            scope = _scope(raw.get("sourceScope"))
            record = _load(root, raw["syncId"], scope, target_agent_id)
            if strict_json(snapshot.raw) != record:
                raise MigrationIOError("affairs_conflict_record_invalid")
            captured.append(snapshot)
            key = (scope["projectId"], scope["instanceId"], scope["agentId"])
            if key not in verifiers:
                verifiers[key] = _BaselineVerifier(root, scope, target_agent_id, target=target)
            _verify_record_sources(root, record, verifiers[key])
            item = {"syncId": record["syncId"], "sourceScope": scope,
                    "conflictCount": len(record["conflicts"])}
            receipt, snapshot = _sync_receipt(root, record)
            if receipt is not None:
                captured.append(snapshot)
                item.update({"syncStatus": "published" if receipt["published"] else "pending",
                             "differenceCount": len(record["conflicts"]),
                             "conflictCount": receipt["conflictCount"] if receipt["published"] else None})
            rows.append(item)
    for verifier in verifiers.values():
        verifier.finish()
    for snapshot in captured:
        verify_snapshot(snapshot)
    rows.sort(key=lambda row: row["syncId"])
    selected = rows[offset:offset + limit]
    end = offset + len(selected)
    return {"sets": selected, "total": len(rows), "nextOffset": end if end < len(rows) else None,
            "readOnly": True, "untrustedContent": True}


def resolve_affairs_conflict_scope(root, *, sync_id, target_agent_id, target=None):
    """Resolve one set's authenticated source scope for a native-profile reader."""
    root = Path(root)
    raw = strict_json(read_stable_file(_record_path(root, sync_id), _RECORD_CAP).raw)
    if not isinstance(raw, dict):
        raise MigrationIOError("affairs_conflict_record_invalid")
    scope = _scope(raw.get("sourceScope"))
    record = _load(root, sync_id, scope, target_agent_id)
    _verify_record_sources(root, record, target=target)
    return scope


def prepare_affairs_conflicts(lease, *, baseline_migration_id, snapshot_migration_id, sync_id, source_scope):
    """Record ambiguous source changes without modifying the active ledger.

    Both archives must have been published after independent source authority
    verification.  The old import receipt must bind the baseline and target.
    A retry reuses its first observation even if the target changed meanwhile.
    """
    scope = _scope(source_scope)
    def check_lease():
        check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id=baseline_migration_id)
    check_lease()
    root = Path(lease.root)
    path = _record_path(root, sync_id)
    if baseline_migration_id == snapshot_migration_id:
        raise MigrationIOError("affairs_conflict_baseline_cycle")
    # Only a source snapshot is read here; the actual lineage and target are
    # verified together below while the ledger lease is held.
    before, before_hash = _archive(root, baseline_migration_id, scope)
    after, after_hash = _archive(root, snapshot_migration_id, scope)
    from . import native
    from core.web.services import personal_affairs_service
    service = personal_affairs_service.get_personal_affairs_service()
    plugin = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != plugin:
        raise MigrationIOError("affairs_target_binding_invalid")
    with native._LOCK, pinned_target_directory(path.parent, create=True), migration_target_lock(path.parent):
        check_lease()
        with locked_affairs_target(root, target_agent_id=lease.agent_id) as target_lease:
            check_lease()
            before, before_hash = _verified_baseline(root, baseline_migration_id, scope, lease.agent_id,
                                                     target=target_lease)
            if path.exists() or path.is_symlink():
                record = _load(root, sync_id, scope, lease.agent_id)
                if (record.get("baselineMigrationId") != baseline_migration_id
                        or record.get("snapshotMigrationId") != snapshot_migration_id
                        or record.get("baselineSha256") != before_hash or record.get("snapshotSha256") != after_hash):
                    raise MigrationIOError("affairs_conflict_id_conflict")
                _verify_record_sources(root, record, target=target_lease)
                latest = _discover_affairs_baseline(root, source_scope=scope, target_agent_id=lease.agent_id,
                                                    ignore_sync_id=sync_id, target=target_lease)
                if latest["baselineMigrationId"] != baseline_migration_id or latest["sourceSha256"] != before_hash:
                    raise MigrationIOError("affairs_conflict_baseline_stale")
                return {"syncId": sync_id, "conflictCount": len(record["conflicts"]), "reused": True,
                        "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}
            latest = discover_affairs_baseline_locked(root, source_scope=scope, target_agent_id=lease.agent_id,
                                                       target=target_lease)
            if latest["baselineMigrationId"] != baseline_migration_id or latest["sourceSha256"] != before_hash:
                raise MigrationIOError("affairs_conflict_baseline_stale")
            target = target_lease.rows(root, lease.agent_id)
            old = {row["itemId"]: row for row in before}
            new = {row["itemId"]: row for row in after}
            current = {row["itemId"]: row for row in target}
            conflicts = []
            for item_id in sorted(old.keys() | new.keys()):
                if old.get(item_id) == new.get(item_id):
                    continue
                kind = "added" if item_id not in old else "removed" if item_id not in new else "changed"
                conflicts.append({"conflictId": _digest({"syncId": sync_id, "sourceScope": scope,
                    "itemId": item_id, "kind": kind}), "itemId": item_id, "kind": kind,
                    "baseline": old.get(item_id), "source": new.get(item_id), "target": current.get(item_id),
                    "targetState": "present" if item_id in current else "missing"})
            record = {"schemaVersion": 1, "syncId": sync_id, "sourceScope": scope,
                "targetAgentId": lease.agent_id, "baselineMigrationId": baseline_migration_id,
                "snapshotMigrationId": snapshot_migration_id, "baselineSha256": before_hash,
                "snapshotSha256": after_hash, "readOnly": True, "untrustedContent": True,
                "conflicts": conflicts}
            if len(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")) > _RECORD_CAP:
                raise MigrationIOError("affairs_conflict_record_limit")
            # Recheck source archive bytes immediately before the one atomic publication.
            if (_verified_baseline(root, baseline_migration_id, scope, lease.agent_id, target=target_lease)[1] != before_hash
                    or _archive(root, snapshot_migration_id, scope)[1] != after_hash):
                raise MigrationIOError("source_changed")
            check_lease()
            with pinned_mutable_file(path.with_name(path.name + ".lock")):
                atomic_write_json(path, record, strict_replace=True, sort_keys=True, indent=None)
            if _load(root, sync_id, scope, lease.agent_id) != record:
                raise MigrationIOError("affairs_conflict_readback_mismatch")
    return {"syncId": sync_id, "conflictCount": len(conflicts), "reused": False,
            "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}


def list_affairs_conflicts(root, *, sync_id, source_scope, target_agent_id, offset=0, limit=6, query="", target=None):
    """List one authorized scope, with bounded pagination and no filesystem paths."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12 or not isinstance(query, str) or len(query) > 160:
        raise MigrationIOError("affairs_conflict_query_invalid")
    record = _load(Path(root), sync_id, _scope(source_scope), target_agent_id)
    _verify_record_sources(Path(root), record, target=target)
    receipt, receipt_snapshot = _sync_receipt(Path(root), record)
    if receipt_snapshot is not None:
        verify_snapshot(receipt_snapshot)
    statuses = ({row["conflictId"]: "planned_apply" if row["status"] == "applied" else row["status"] for row in receipt["decisions"]}
                if receipt is not None and receipt["published"] else {})
    needle = query.casefold()
    rows = [row for row in record["conflicts"] if not needle or needle in " ".join(
        (row.get("source") or row.get("baseline") or {}).get(k, "") for k in ("title", "note")).casefold()]
    result = {"conflicts": [], "total": len(rows), "nextOffset": None,
              "readOnly": True, "untrustedContent": True, "targetSnapshotOnly": True, "sourceSnapshotOnly": True,
              "sourceNotice": "来源未冻结；removed 仅表示后次快照未出现，不能据此删除或认定迁移完成。",
              "targetNotice": "目标状态为记录时快照；处理前请读取当前事务，不可据此直接覆盖。"}
    if receipt is not None:
        result["syncStatus"] = "published" if receipt["published"] else "pending"
        result["unresolvedCount"] = receipt["conflictCount"] if receipt["published"] else None
        result["decisionNotice"] = "planned_apply 是历史计划，不证明该操作实际写入；处理前读取当前事务。"
    for row in rows[offset:offset + limit]:
        item = {"conflictId": row["conflictId"], "kind": row["kind"], "targetState": row["targetState"],
                "title": (row.get("source") or row.get("baseline"))["title"]}
        if receipt is not None:
            item["syncStatus"] = statuses.get(row["conflictId"], "unknown")
        if len(json.dumps({**result, "conflicts": result["conflicts"] + [item]}, ensure_ascii=False)) > 3000:
            break
        result["conflicts"].append(item)
    end = offset + len(result["conflicts"])
    result["nextOffset"] = end if end < len(rows) else None
    return result


def read_affairs_conflict(root, *, sync_id, source_scope, target_agent_id, conflict_id,
                          character_offset=0, max_characters=1200, target=None):
    """Return a bounded JSON fragment; render the content as untrusted text."""
    if not isinstance(conflict_id, str) or len(conflict_id) != 64 or any(c not in "0123456789abcdef" for c in conflict_id):
        raise MigrationIOError("affairs_conflict_id_invalid")
    if type(character_offset) is not int or character_offset < 0 or type(max_characters) is not int or not 1 <= max_characters <= 1600:
        raise MigrationIOError("affairs_conflict_query_invalid")
    record = _load(Path(root), sync_id, _scope(source_scope), target_agent_id)
    _verify_record_sources(Path(root), record, target=target)
    receipt, receipt_snapshot = _sync_receipt(Path(root), record)
    if receipt_snapshot is not None:
        verify_snapshot(receipt_snapshot)
    statuses = ({row["conflictId"]: "planned_apply" if row["status"] == "applied" else row["status"] for row in receipt["decisions"]}
                if receipt is not None and receipt["published"] else {})
    for row in record["conflicts"]:
        if row["conflictId"] == conflict_id:
            text = json.dumps({key: row[key] for key in ("baseline", "source", "target")}, ensure_ascii=False)
            if character_offset >= len(text):
                raise MigrationIOError("affairs_conflict_offset_invalid")
            width = max_characters
            while width:
                end = min(len(text), character_offset + width)
                result = {"conflictId": conflict_id, "kind": row["kind"], "targetState": row["targetState"],
                    "text": text[character_offset:end], "characterOffset": character_offset,
                    "nextCharacterOffset": end if end < len(text) else None,
                    "sourceScope": record["sourceScope"], "readOnly": True, "untrustedContent": True,
                    "targetSnapshotOnly": True, "sourceSnapshotOnly": True,
                    "sourceNotice": "来源未冻结；removed 仅表示后次快照未出现，不能据此删除或认定迁移完成。",
                    "targetNotice": "目标状态为记录时快照；处理前请读取当前事务，不可据此直接覆盖。"}
                if receipt is not None:
                    result["syncStatus"] = statuses.get(conflict_id, "unknown")
                    result["decisionNotice"] = "planned_apply 是历史计划，不证明该操作实际写入。"
                if len(json.dumps(result, ensure_ascii=False)) <= 3300:
                    return result
                width //= 2
            raise MigrationIOError("affairs_conflict_query_invalid")
    raise MigrationIOError("affairs_conflict_not_found")


__all__ = ["prepare_affairs_conflicts", "discover_affairs_baseline", "discover_affairs_conflicts", "resolve_affairs_conflict_scope",
           "list_affairs_conflicts", "read_affairs_conflict"]
