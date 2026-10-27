"""Isolated, read-only records for ambiguous legacy affairs changes.

The operator must authenticate and archive each source snapshot first.  Hashes
verify those bytes, not their authority.  No record here is an active affair,
and neither this module nor its readers change the native ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock

from .migration_affairs import _BYTE_CAP, _check_lease, _parse_rows, _token
from .migration_io import (MigrationIOError, check_path, migration_target_lock, pinned_mutable_file,
    pinned_target_directory, read_stable_file, strict_json, verify_snapshot)

_RECORD_CAP = 16 * 1024 * 1024


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


def _verify_record_sources(root, record):
    """Recheck the published archives and their baseline import binding."""
    scope = _scope(record["sourceScope"])
    before, before_hash = _archive(root, record.get("baselineMigrationId"), scope)
    after, after_hash = _archive(root, record.get("snapshotMigrationId"), scope)
    mid = record["baselineMigrationId"]
    receipt_path = root / "affairs_migrations" / (hashlib.sha256(mid.encode()).hexdigest() + ".json")
    receipt = strict_json(read_stable_file(receipt_path, 16 * 1024).raw)
    expected = {"schemaVersion": 1, "migrationId": mid, "sourceScope": scope,
        "sourceSha256": before_hash, "targetAgentId": record["targetAgentId"],
        "itemCount": len(before), "published": True}
    if (not isinstance(receipt, dict) or receipt != expected or type(receipt.get("published")) is not bool
            or type(receipt.get("schemaVersion")) is not int or type(receipt.get("itemCount")) is not int
            or before_hash != record.get("baselineSha256") or after_hash != record.get("snapshotSha256")):
        raise MigrationIOError("affairs_conflict_baseline_unbound")
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


def discover_affairs_conflicts(root, *, target_agent_id, offset=0, limit=6):
    """Discover conflict sets for the trusted native profile without user IDs."""
    if not _token(target_agent_id) or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12:
        raise MigrationIOError("affairs_conflict_query_invalid")
    root = Path(root)
    directory = root / "affairs_conflicts"
    if not directory.exists() and not directory.is_symlink():
        return {"sets": [], "total": 0, "nextOffset": None, "readOnly": True, "untrustedContent": True}
    rows = []
    check_path(directory)
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 64:
                raise MigrationIOError("affairs_conflict_record_limit")
            if entry.name.endswith(".json.lock"):
                check_path(Path(entry.path))
                continue
            if not entry.name.endswith(".json"):
                raise MigrationIOError("affairs_conflict_record_invalid")
            raw = strict_json(read_stable_file(Path(entry.path), _RECORD_CAP).raw)
            if not isinstance(raw, dict) or not _token(raw.get("syncId")) or Path(entry.path) != _record_path(root, raw["syncId"]):
                raise MigrationIOError("affairs_conflict_record_invalid")
            if raw.get("targetAgentId") != target_agent_id:
                raise MigrationIOError("affairs_conflict_target_invalid")
            scope = _scope(raw.get("sourceScope"))
            record = _load(root, raw["syncId"], scope, target_agent_id)
            _verify_record_sources(root, record)
            rows.append({"syncId": record["syncId"], "sourceScope": scope,
                         "conflictCount": len(record["conflicts"])})
    rows.sort(key=lambda row: row["syncId"])
    selected = rows[offset:offset + limit]
    end = offset + len(selected)
    return {"sets": selected, "total": len(rows), "nextOffset": end if end < len(rows) else None,
            "readOnly": True, "untrustedContent": True}


def resolve_affairs_conflict_scope(root, *, sync_id, target_agent_id):
    """Resolve one set's authenticated source scope for a native-profile reader."""
    root = Path(root)
    raw = strict_json(read_stable_file(_record_path(root, sync_id), _RECORD_CAP).raw)
    if not isinstance(raw, dict):
        raise MigrationIOError("affairs_conflict_record_invalid")
    scope = _scope(raw.get("sourceScope"))
    record = _load(root, sync_id, scope, target_agent_id)
    _verify_record_sources(root, record)
    return scope


def prepare_affairs_conflicts(lease, *, baseline_migration_id, snapshot_migration_id, sync_id, source_scope):
    """Record ambiguous source changes without modifying the active ledger.

    Both archives must have been published after independent source authority
    verification.  The old import receipt must bind the baseline and target.
    A retry reuses its first observation even if the target changed meanwhile.
    """
    _check_lease(lease)
    scope = _scope(source_scope)
    root = Path(lease.root)
    path = _record_path(root, sync_id)
    before, before_hash = _archive(root, baseline_migration_id, scope)
    after, after_hash = _archive(root, snapshot_migration_id, scope)
    receipt_path = root / "affairs_migrations" / (hashlib.sha256(baseline_migration_id.encode()).hexdigest() + ".json")
    receipt = strict_json(read_stable_file(receipt_path, 16 * 1024).raw)
    expected = {"schemaVersion": 1, "migrationId": baseline_migration_id, "sourceScope": scope,
        "sourceSha256": before_hash, "targetAgentId": lease.agent_id, "itemCount": len(before), "published": True}
    if (not isinstance(receipt, dict) or receipt != expected or type(receipt.get("published")) is not bool
            or type(receipt.get("schemaVersion")) is not int or type(receipt.get("itemCount")) is not int):
        raise MigrationIOError("affairs_conflict_baseline_unbound")
    from . import native
    from core.web.services import personal_affairs_service
    service = personal_affairs_service.get_personal_affairs_service()
    plugin = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != plugin:
        raise MigrationIOError("affairs_target_binding_invalid")
    ledger = plugin / "affairs/items.jsonl"
    with native._LOCK, pinned_target_directory(path.parent, create=True), migration_target_lock(path.parent):
        _check_lease(lease)
        if path.exists() or path.is_symlink():
            record = _load(root, sync_id, scope, lease.agent_id)
            if (record.get("baselineMigrationId") != baseline_migration_id
                    or record.get("snapshotMigrationId") != snapshot_migration_id
                    or record.get("baselineSha256") != before_hash or record.get("snapshotSha256") != after_hash):
                raise MigrationIOError("affairs_conflict_id_conflict")
            return {"syncId": sync_id, "conflictCount": len(record["conflicts"]), "reused": True,
                    "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}
        with pinned_target_directory(ledger.parent, create=True), \
                pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), cross_process_file_lock(ledger):
            _check_lease(lease)
            target = _parse_rows(read_stable_file(ledger, _BYTE_CAP).raw) if ledger.exists() or ledger.is_symlink() else []
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
            if _archive(root, baseline_migration_id, scope)[1] != before_hash or _archive(root, snapshot_migration_id, scope)[1] != after_hash:
                raise MigrationIOError("source_changed")
            _check_lease(lease)
            with pinned_mutable_file(path.with_name(path.name + ".lock")):
                atomic_write_json(path, record, strict_replace=True, sort_keys=True, indent=None)
            if _load(root, sync_id, scope, lease.agent_id) != record:
                raise MigrationIOError("affairs_conflict_readback_mismatch")
    return {"syncId": sync_id, "conflictCount": len(conflicts), "reused": False,
            "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}


def list_affairs_conflicts(root, *, sync_id, source_scope, target_agent_id, offset=0, limit=6, query=""):
    """List one authorized scope, with bounded pagination and no filesystem paths."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12 or not isinstance(query, str) or len(query) > 160:
        raise MigrationIOError("affairs_conflict_query_invalid")
    record = _load(Path(root), sync_id, _scope(source_scope), target_agent_id)
    _verify_record_sources(Path(root), record)
    needle = query.casefold()
    rows = [row for row in record["conflicts"] if not needle or needle in " ".join(
        (row.get("source") or row.get("baseline") or {}).get(k, "") for k in ("title", "note")).casefold()]
    result = {"conflicts": [], "total": len(rows), "nextOffset": None,
              "readOnly": True, "untrustedContent": True, "targetSnapshotOnly": True, "sourceSnapshotOnly": True,
              "sourceNotice": "来源未冻结；removed 仅表示后次快照未出现，不能据此删除或认定迁移完成。",
              "targetNotice": "目标状态为记录时快照；处理前请读取当前事务，不可据此直接覆盖。"}
    for row in rows[offset:offset + limit]:
        item = {"conflictId": row["conflictId"], "kind": row["kind"], "targetState": row["targetState"],
                "title": (row.get("source") or row.get("baseline"))["title"]}
        if len(json.dumps({**result, "conflicts": result["conflicts"] + [item]}, ensure_ascii=False)) > 3000:
            break
        result["conflicts"].append(item)
    end = offset + len(result["conflicts"])
    result["nextOffset"] = end if end < len(rows) else None
    return result


def read_affairs_conflict(root, *, sync_id, source_scope, target_agent_id, conflict_id,
                          character_offset=0, max_characters=1200):
    """Return a bounded JSON fragment; render the content as untrusted text."""
    if not isinstance(conflict_id, str) or len(conflict_id) != 64 or any(c not in "0123456789abcdef" for c in conflict_id):
        raise MigrationIOError("affairs_conflict_id_invalid")
    if type(character_offset) is not int or character_offset < 0 or type(max_characters) is not int or not 1 <= max_characters <= 1600:
        raise MigrationIOError("affairs_conflict_query_invalid")
    record = _load(Path(root), sync_id, _scope(source_scope), target_agent_id)
    _verify_record_sources(Path(root), record)
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
                if len(json.dumps(result, ensure_ascii=False)) <= 3300:
                    return result
                width //= 2
            raise MigrationIOError("affairs_conflict_query_invalid")
    raise MigrationIOError("affairs_conflict_not_found")


__all__ = ["prepare_affairs_conflicts", "discover_affairs_conflicts", "resolve_affairs_conflict_scope",
           "list_affairs_conflicts", "read_affairs_conflict"]
