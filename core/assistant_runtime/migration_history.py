"""Read-only legacy PA history discovery and immutable, isolated archives.

Only pure native Journal projections are used. No Session loader, repair,
admission, queue, runtime-state import, or execution capability lives here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path

from core.assistant_runtime.migration_inventory import declared_assistant_identities
from core.assistant_runtime.migration_io import (
    FileSnapshot, MigrationIOError, check_path, fingerprint_tree, path_identity,
    migration_target_lock, pinned_target_directory, publish_directory, read_stable_file, strict_json,
    validate_path, verify_snapshot,
)
from core.chat.conversation_ledger import (
    conversation_turn_items_from_events, project_conversation_ledger,
)
from core.chat.turn_journal import TERMINAL_EVENTS, TurnJournalEvent

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_FILE_CAP = 16 * 1024 * 1024
_TOTAL_CAP = 128 * 1024 * 1024
_ROW_CAP = 100000
_ARCHIVE_BYTES_CAP = _TOTAL_CAP + 3 * _FILE_CAP
_ARCHIVE_FILES_CAP = 20000
_ARCHIVE_COUNT_CAP = 1000
_HISTORY_CHAIN_CAP = 32


def _token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


@dataclass(frozen=True)
class HistorySession:
    session_id: str
    journal: FileSnapshot
    assets: tuple[FileSnapshot, ...]
    watermark: dict


@dataclass(frozen=True)
class HistoryDiscovery:
    report: dict
    sessions: tuple[HistorySession, ...] = ()
    snapshots: tuple[FileSnapshot, ...] = ()
    source_roots: tuple[Path, ...] = ()
    directories: tuple[tuple[Path, tuple], ...] = ()
    absent: tuple[Path, ...] = ()
    asset_trees: tuple[tuple[Path, tuple[FileSnapshot, ...]], ...] = ()


@dataclass
class _ArchiveBudget:
    """One operation's aggregate I/O and metadata budget across all archives.

    Repeated integrity reads also consume the byte/file budget. Never reset
    this object between manifests, and reserve metadata before building rows.
    """
    bytes_left: int = _ARCHIVE_BYTES_CAP
    files_left: int = _ARCHIVE_FILES_CAP
    histories_left: int = 10000
    archives_left: int = _ARCHIVE_COUNT_CAP

    def __post_init__(self):
        for value, ceiling in ((self.bytes_left, _ARCHIVE_BYTES_CAP),
                (self.files_left, _ARCHIVE_FILES_CAP), (self.histories_left, 10000),
                (self.archives_left, _ARCHIVE_COUNT_CAP)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise MigrationIOError("history_archive_limit")
        # Per-operation only: cached bytes have already been charged to this
        # budget, including when a later version references the same parent.
        self.archive_cache = {}
        self.resolving = set()
        self.quarantined_archives = 0
        self.history_charged = set()

    def reserve(self, field, amount=1):
        if amount > getattr(self, field):
            raise MigrationIOError("history_archive_limit")
        setattr(self, field, getattr(self, field) - amount)

    def read(self, path, *, expected=None):
        self.reserve("files_left")
        try:
            snapshot = read_stable_file(path, min(_FILE_CAP, self.bytes_left), expected=expected)
        except MigrationIOError as error:
            if str(error) in {"file_byte_limit", "invalid_source_budget"}:
                raise MigrationIOError("history_archive_limit") from None
            raise
        self.reserve("bytes_left", len(snapshot.raw))
        return snapshot

    def tree(self, root):
        if self.files_left < 1 or self.bytes_left < 1:
            raise MigrationIOError("history_archive_limit")
        try:
            snapshots = fingerprint_tree(root, max_files=self.files_left,
                                         max_total_bytes=self.bytes_left)
        except MigrationIOError as error:
            if str(error) in {"file_limit", "file_byte_limit", "invalid_source_budget"}:
                raise MigrationIOError("history_archive_limit") from None
            raise
        self.reserve("files_left", getattr(snapshots, "visited_entries", len(snapshots)))
        self.reserve("bytes_left", sum(len(s.raw) for s in snapshots))
        return snapshots


def _alias(row, keys, *, required=False):
    values = [row[key] for key in keys if key in row and row[key] not in (None, "")]
    if any(not _token(value) for value in values) or len(set(values)) > 1:
        raise MigrationIOError("history_identity_conflict")
    if required and not values:
        raise MigrationIOError("history_identity_missing")
    return values[0] if values else ""


def _events(raw, sid, *, max_rows=_ROW_CAP, max_line_bytes=1024 * 1024):
    if raw and not raw.endswith(b"\n"):
        raise MigrationIOError("truncated_history_jsonl")
    result, ids, previous, open_turns = [], set(), 0, set()
    for line in raw.splitlines(keepends=True):
        if len(result) >= max_rows or len(line) > max_line_bytes:
            raise MigrationIOError("history_event_limit")
        row = strict_json(line)
        if not isinstance(row, dict) or not isinstance(row.get("payload", {}), dict):
            raise MigrationIOError("history_event_invalid")
        eid = _alias(row, ("eventId", "event_id"), required=True)
        session = _alias(row, ("sessionId", "session_id"), required=True)
        _alias(row, ("turnId", "turn_id"))
        sequence = row.get("sequence")
        if session != sid or eid in ids or type(sequence) is not int or sequence <= previous:
            raise MigrationIOError("history_event_identity_invalid")
        # Required identity is checked before native from_dict, whose missing
        # eventId fallback deliberately creates a UUID for ordinary callers.
        event = TurnJournalEvent.from_dict(row)
        if event is None:
            raise MigrationIOError("history_event_invalid")
        if event.event_type == "turn_started" and event.turn_id:
            if event.turn_id in open_turns:
                raise MigrationIOError("history_turn_identity_conflict")
            open_turns.add(event.turn_id)
        elif event.event_type in TERMINAL_EVENTS:
            open_turns.discard(event.turn_id)
        ids.add(eid)
        previous = sequence
        result.append(event)
    projection = project_conversation_ledger(result, include_model_messages=False)
    if open_turns or projection.open_turn_id:
        raise MigrationIOError("history_import_not_quiescent")
    return result


def _database_rows(snapshot, max_sessions):
    """Parse a stable byte copy with the canonical APSW readonly runtime."""
    from core.chat.conversation_store import runtime

    with tempfile.TemporaryDirectory(prefix="pa-history-db-") as temporary:
        isolated = Path(temporary) / "source.sqlite3"
        isolated.write_bytes(snapshot.raw)
        connection = None
        try:
            connection = runtime.connect(isolated.as_uri() + "?mode=ro", uri=True)
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 128").fetchall()}
            root = (connection.execute("SELECT id FROM workspace_chat_state WHERE id=1").fetchone()
                    if "workspace_chat_state" in tables else None)
            if root is not None and not {"sessions", "session_runtime_state"}.issubset(tables):
                raise MigrationIOError("history_database_schema_incomplete")
            records = {}
            if "sessions" in tables:
                for row in connection.execute(
                        "SELECT session_id, agent_id, parent_session_id FROM sessions LIMIT ?",
                        (max_sessions + 1,)):
                    sid = row["session_id"]
                    if sid in records or not _token(sid):
                        raise MigrationIOError("history_identity_conflict")
                    records[sid] = {"id": sid, "agent_id": row["agent_id"],
                                    "parent_session_id": row["parent_session_id"]}
            if "session_runtime_state" in tables:
                for row in connection.execute(
                        "SELECT session_id, payload_json FROM session_runtime_state LIMIT ?",
                        (max_sessions + 1,)):
                    sid, raw = row["session_id"], row["payload_json"]
                    if not _token(sid) or not isinstance(raw, str) or len(raw.encode("utf-8")) > _FILE_CAP:
                        raise MigrationIOError("history_runtime_identity_invalid")
                    payload = strict_json(raw)
                    if not isinstance(payload, dict):
                        raise MigrationIOError("history_runtime_invalid")
                    declared = _alias(payload, ("id", "sessionId", "session_id", "conversation_id", "conversationId"))
                    if declared and declared != sid:
                        raise MigrationIOError("history_identity_conflict")
                    # Keep aliases separate so conflicts cannot be hidden by a
                    # dict update from the canonical sessions table.
                    old = records.get(sid, {})
                    for keys in (("agent_id", "agentId"), ("parent_session_id", "parentSessionId")):
                        before, after = _alias(old, keys), _alias(payload, keys)
                        if before and after and before != after:
                            raise MigrationIOError("history_ownership_conflict")
                    records[sid] = {**old, **payload, "id": sid}
            if len(records) > max_sessions:
                raise MigrationIOError("history_session_limit")
            return root is not None, list(records.values())
        except runtime.Error:
            raise MigrationIOError("history_database_invalid") from None
        finally:
            if connection is not None:
                connection.close()


def _owned_sessions(rows, agent_id, direct_id, registry):
    """Pure explicit ownership plus parent/root closure; never Journal guesses."""
    records = {}
    direct_owners = {row["directSessionId"]: row["agentId"] for row in registry}
    for row in rows:
        if not isinstance(row, dict):
            raise MigrationIOError("history_authority_invalid")
        sid = _alias(row, ("id", "sessionId", "session_id", "conversation_id", "conversationId"), required=True)
        if sid in records:
            raise MigrationIOError("history_identity_conflict")
        owner = _alias(row, ("agent_id", "agentId"))
        parent = _alias(row, ("parent_session_id", "parentSessionId"))
        root = _alias(row, ("root_session_id", "rootSessionId"))
        declared = direct_owners.get(sid, "")
        if declared and owner and declared != owner:
            raise MigrationIOError("history_ownership_conflict")
        records[sid] = (owner or declared, parent, root)
    owners = {sid: row[0] for sid, row in records.items()}
    for _ in range(len(records) + 1):
        changed = False
        for sid, (owner, parent, root) in records.items():
            inherited = {owners.get(ref) or direct_owners.get(ref) for ref in (parent, root) if ref and ref != sid}
            inherited.discard(None)
            inherited.discard("")
            candidates = inherited | ({owners[sid]} if owners[sid] else set())
            if len(candidates) > 1:
                raise MigrationIOError("history_ownership_conflict")
            if candidates and not owners[sid]:
                owners[sid] = next(iter(candidates))
                changed = True
        if not changed:
            break
    return sorted(sid for sid, owner in owners.items() if owner == agent_id), len([v for v in owners.values() if not v])


def discover_history(*, project_root: Path, workspace: Path, project_id: str,
                     instance_id: str, assistant_agent_id: str, max_sessions: int = 10000,
                     max_files: int = 10000, max_file_bytes: int = _FILE_CAP,
                     max_total_bytes: int = _TOTAL_CAP, max_rows: int = _ROW_CAP,
                     max_line_bytes: int = 1024 * 1024) -> HistoryDiscovery:
    report = {"schemaVersion": 1, "stage": "history_discovery", "historyComplete": False,
              "readyForCutover": False, "sourceQuiesced": False, "issues": [],
              "sessions": [], "counts": {"sessions": 0, "orphanSessions": 0, "deletedSessions": 0}}
    snapshots, directories, absent, sessions, trees = [], [], [], [], []
    event_ids = set()
    roots = (Path(workspace),)
    total = event_count = visited_entries = 0

    def remember_directory(path):
        check_path(path)
        directories.append((path, path_identity(path)))

    def read(path):
        nonlocal total, visited_entries
        if visited_entries >= max_files or total >= max_total_bytes:
            raise MigrationIOError("history_source_limit")
        visited_entries += 1
        snap = read_stable_file(path, min(max_file_bytes, max_total_bytes - total))
        snapshots.append(snap)
        total += len(snap.raw)
        return snap

    def optional(path):
        if path.exists() or path.is_symlink():
            return True
        absent.append(path)
        return False

    try:
        if (not all(isinstance(p, Path) and p.is_absolute() for p in (project_root, workspace))
                or not all(_token(v) for v in (project_id, instance_id, assistant_agent_id))):
            raise MigrationIOError("history_scope_invalid")
        if (any(type(n) is not int or n < 1 for n in
                (max_sessions, max_files, max_file_bytes, max_total_bytes, max_rows, max_line_bytes))
                or max_file_bytes > _FILE_CAP or max_sessions > 10000 or max_rows > _ROW_CAP
                or max_files > 10000 or max_total_bytes > _TOTAL_CAP):
            raise MigrationIOError("history_limits_invalid")
        check_path(project_root)
        remember_directory(workspace)
        registry = read(workspace / "agents/agents.json")
        value = strict_json(registry.raw)
        rows = value.get("agents") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) > max_sessions:
            raise MigrationIOError("history_registry_invalid")
        aids, sids = set(), set()
        for row in rows:
            if (not isinstance(row, dict) or not _token(row.get("agentId"))
                    or not _token(row.get("directSessionId")) or row["agentId"] in aids
                    or row["directSessionId"] in sids):
                raise MigrationIOError("history_registry_invalid")
            aids.add(row["agentId"])
            sids.add(row["directSessionId"])
        selected = [row for row in declared_assistant_identities(rows) if row["agentId"] == assistant_agent_id]
        if len(selected) != 1:
            raise MigrationIOError("assistant_identity_unavailable")
        report["sourceScope"] = {"projectId": project_id, "instanceId": instance_id,
            "projectRoot": str(project_root), "workspace": str(workspace), "agentId": assistant_agent_id}
        report["registrySha256"] = registry.sha256
        db = workspace / "chat/conversations.sqlite3"
        root_exists, authority = False, []
        if optional(db):
            for suffix in ("-wal", "-journal"):
                sidecar = Path(str(db) + suffix)
                if optional(sidecar) and read(sidecar).raw:
                    raise MigrationIOError("history_import_not_quiescent")
            root_exists, authority = _database_rows(read(db), max_sessions)
        if not root_exists:
            legacy = workspace / "chat/chat_state.json"
            if not optional(legacy):
                raise MigrationIOError("history_authority_unavailable")
            value = strict_json(read(legacy).raw)
            authority = value.get("conversations") if isinstance(value, dict) else None
            if not isinstance(authority, list) or len(authority) > max_sessions:
                raise MigrationIOError("history_authority_invalid")
        report["authority"] = "sqlite" if root_exists else "legacy_json"
        owned, orphans = _owned_sessions(authority, assistant_agent_id, selected[0]["sessionId"], rows)
        report["counts"]["orphanSessions"] = orphans
        session_root = workspace / "sessions"
        if optional(session_root):
            remember_directory(session_root)
            # Directory names only count unknown workspaces; they confer no
            # ownership and their transcripts are never opened.
            with os.scandir(session_root) as children:
                entries = 0
                known = {_alias(row, ("id", "sessionId", "session_id", "conversation_id", "conversationId")) for row in authority}
                for child in children:
                    entries += 1
                    visited_entries += 1
                    if entries > max_files or visited_entries > max_files:
                        raise MigrationIOError("history_source_limit")
                    if child.name not in known:
                        report["counts"]["orphanSessions"] += 1
        for sid in owned:
            directory = session_root / sid
            remember_directory(directory)
            marker = directory / ".session_deleted"
            if optional(marker):
                read(marker)
                report["counts"]["deletedSessions"] += 1
                continue
            journal = read(directory / "turn_journal.jsonl")
            events = _events(journal.raw, sid, max_rows=max_rows - event_count, max_line_bytes=max_line_bytes)
            event_count += len(events)
            current_ids = {event.event_id for event in events}
            if event_ids.intersection(current_ids):
                raise MigrationIOError("history_event_identity_invalid")
            event_ids.update(current_ids)
            assets = []
            asset_root = directory / "artifacts"
            if optional(asset_root):
                remember_directory(asset_root)
                assets = fingerprint_tree(asset_root, max_file_bytes=max_file_bytes,
                    max_files=max_files - visited_entries, max_total_bytes=max_total_bytes - total)
                visited_entries += getattr(assets, "visited_entries", len(assets))
                snapshots.extend(assets)
                total += sum(len(s.raw) for s in assets)
                trees.append((asset_root, tuple(assets)))
            watermark = {"eventCount": len(events), "sequence": events[-1].sequence if events else 0,
                         "eventId": events[-1].event_id if events else "", "sha256": journal.sha256}
            sessions.append(HistorySession(sid, journal, tuple(assets), watermark))
            report["sessions"].append({"sessionId": sid, "watermark": watermark, "assetCount": len(assets)})
        unresolved = report["counts"]["orphanSessions"]
        if unresolved:
            report["issues"].append({"code": "history_orphan_ownership_unknown", "count": unresolved})
        discovery = HistoryDiscovery(report, tuple(sessions), tuple(snapshots), roots, tuple(directories), tuple(absent), tuple(trees))
        _verify_source(discovery)
        report["counts"]["sessions"] = len(sessions)
        report["historyComplete"] = not unresolved
        # Stable snapshots prove this observed history, not a global source
        # lifecycle stop; retirement still needs the parent's quiescence gate.
        report["historySettled"] = not unresolved
        return discovery
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
        code = str(error) if isinstance(error, MigrationIOError) else "history_source_invalid"
        report["issues"].append({"code": code})
        return HistoryDiscovery(report, (), tuple(snapshots), roots, tuple(directories), tuple(absent), tuple(trees))


def _verify_source(discovery):
    for snapshot in discovery.snapshots:
        verify_snapshot(snapshot)
    for path, identity in discovery.directories:
        check_path(path)
        if path_identity(path) != identity:
            raise MigrationIOError("source_changed")
    for path in discovery.absent:
        if path.exists() or path.is_symlink():
            raise MigrationIOError("source_changed")
    for root, expected in discovery.asset_trees:
        actual = fingerprint_tree(root)
        if [(s.path, s.sha256, s.identity) for s in actual] != [(s.path, s.sha256, s.identity) for s in expected]:
            raise MigrationIOError("source_changed")


def _canonical_target(target_root):
    target = validate_path(Path(target_root))
    ancestor = target
    while not ancestor.exists() and not ancestor.is_symlink():
        ancestor = ancestor.parent
    check_path(ancestor)
    return target.resolve()


def _archive_root(target_root):
    target = _canonical_target(target_root)
    if not target.exists():
        return target / "history_archive/migrations"
    check_path(target)
    root = target / "history_archive/migrations"
    if root.exists() or root.is_symlink():
        check_path(root)
    return root


def _manifest(discovery, migration_id):
    scope = discovery.report["sourceScope"]
    scope_id = _digest(scope)
    rows, copies = [], []
    for session in discovery.sessions:
        sid = session.session_id
        hid = _digest({"sourceScope": scope, "sessionId": sid})
        prefix = f"{scope_id}/{hid}"
        journal_path = prefix + "/turn_journal.jsonl"
        copies.append((journal_path, session.journal))
        assets = []
        for snapshot in session.assets:
            relative = snapshot.path.relative_to(session.journal.path.parent / "artifacts").as_posix()
            logical_id = _digest({"historyId": hid, "asset": relative})
            destination = prefix + "/assets/" + logical_id
            copies.append((destination, snapshot))
            assets.append({"attachmentId": logical_id, "path": destination,
                           "sha256": snapshot.sha256, "size": len(snapshot.raw)})
        rows.append({"historyId": hid, "sessionId": sid, "sourceScope": scope,
            "watermark": session.watermark, "journal": {"path": journal_path,
                "sha256": session.journal.sha256, "size": len(session.journal.raw)}, "assets": assets})
    manifest = {"schemaVersion": 2, "migrationId": migration_id, "readOnly": True,
        "untrustedContent": True, "canContinue": False, "histories": rows,
        "sourceFingerprint": _digest([{ "path": str(s.path), "sha256": s.sha256} for s in discovery.snapshots])}
    return manifest, copies


def _write_new(path, raw):
    # Restart may reuse only exactly matching files. Existing archives and
    # partially copied files are never overwritten or repaired in place.
    with pinned_target_directory(path.parent, create=True) as parent:
        path = parent / path.name
        if path.exists() or path.is_symlink():
            if read_stable_file(path, _FILE_CAP).raw != raw:
                raise MigrationIOError("history_target_conflict")
            return
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if read_stable_file(path, _FILE_CAP).raw != raw:
            raise MigrationIOError("history_copy_mismatch")


def _parent_chain(root, row, mid, snapshot, budget):
    chain = [(row, mid, snapshot)]
    while row.get("base") is not None:
        mid = row["base"]["migrationId"]
        loaded = budget.archive_cache.get(mid)
        if loaded is None:
            loaded = _load_physical_archive(root / mid, budget=budget, visible_only=True)
        if loaded is None:
            raise MigrationIOError("history_archive_reference_invalid")
        parent_manifest, physical = loaded
        matches = [item for item in parent_manifest["histories"] if item["historyId"] == row["historyId"]]
        if len(matches) != 1:
            raise MigrationIOError("history_archive_reference_invalid")
        row = matches[0]
        snapshot = (_LazyJournal(root, parent_manifest, row, physical, budget)
                    if parent_manifest["schemaVersion"] == 3 and "base" in row
                    else physical[row["journal"]["path"]])
        chain.append((row, mid, snapshot))
        if len(chain) > _HISTORY_CHAIN_CAP + 1:
            raise MigrationIOError("history_archive_reference_invalid")
    return chain


def _incremental_manifest(root, manifest, copies, *, saved=None):
    """Freeze each parent while the publish lock is held."""
    source = dict(copies)
    selection_budget = _ArchiveBudget()
    selected, conflicts = _select_history_versions(root.parent.parent, selection_budget, retain_raw=False)
    saved_rows = {row["historyId"]: row for row in saved["histories"]} if saved else {}
    rows, physical, used_parent = [], [], False
    for original in manifest["histories"]:
        hid = original["historyId"]
        if hid in conflicts:
            raise MigrationIOError("history_archive_identity_conflict")
        saved_row = saved_rows.get(hid)
        binding = saved_row.get("base") if saved_row else None
        if saved is not None and saved_row is None:
            raise MigrationIOError("history_migration_id_conflict")
        previous = selected.get(hid) if saved is None else None
        if previous is not None:
            chain = _parent_chain(root, *previous, selection_budget)
            if len(chain) - 1 >= _HISTORY_CHAIN_CAP:
                # Rebase onto a verified ancestor, preserving all archives.
                previous = chain[max(1, len(chain) // 2)]
            previous = (previous[0], previous[1], previous[2].raw)
        if binding is not None:
            if not isinstance(binding, dict) or not _token(binding.get("migrationId")):
                raise MigrationIOError("history_archive_reference_invalid")
            parent_dir = root / binding["migrationId"]
            if not _confirmation_exists(parent_dir):
                raise MigrationIOError("history_archive_reference_invalid")
            loaded = _load_archive(parent_dir, visible_only=True)
            if loaded is None or loaded[0]["schemaVersion"] not in (2, 3):
                raise MigrationIOError("history_archive_reference_invalid")
            parent_rows = [row for row in loaded[0]["histories"] if row["historyId"] == hid]
            if len(parent_rows) != 1:
                raise MigrationIOError("history_archive_reference_invalid")
            parent = parent_rows[0]
            previous = (parent, binding["migrationId"], loaded[1][parent["journal"]["path"]].raw)
        if saved is not None and binding is None:
            previous = None
        parent_manifest = selection_budget.archive_cache.get(previous[1], (None,))[0] if previous else None
        if (previous is not None and parent_manifest is not None
                and parent_manifest["schemaVersion"] in (2, 3)
                and _confirmation_exists(root / previous[1])):
            old, mid, old_raw = previous
            raw = source[original["journal"]["path"]].raw
            if not _extends_history(old, old_raw, original, raw):
                raise MigrationIOError("history_archive_identity_conflict")
            base = {"migrationId": mid, "historyId": hid, "journalSize": len(old_raw),
                    "journalSha256": hashlib.sha256(old_raw).hexdigest()}
            if binding is not None and base != binding:
                raise MigrationIOError("history_archive_reference_invalid")
            delta_path = original["journal"]["path"].removesuffix("turn_journal.jsonl") + "journal.delta"
            delta_raw = raw[len(old_raw):]
            snapshot = source[original["journal"]["path"]]
            physical.append((delta_path, FileSnapshot(snapshot.path, delta_raw, hashlib.sha256(delta_raw).hexdigest(), snapshot.identity)))
            old_ids = {asset["attachmentId"] for asset in old["assets"]}
            assets = []
            for asset in original["assets"]:
                if asset["attachmentId"] in old_ids:
                    assets.append({**asset, "inherited": True})
                else:
                    assets.append(asset)
                    physical.append((asset["path"], source[asset["path"]]))
            rows.append({**original, "base": base, "delta": {"path": delta_path,
                "sha256": hashlib.sha256(delta_raw).hexdigest(), "size": len(delta_raw)}, "assets": assets})
            used_parent = True
        else:
            rows.append(original)
            physical.extend((entry["path"], source[entry["path"]]) for entry in [original["journal"], *original["assets"]])
    result = {**manifest, "schemaVersion": 3 if used_parent else 2, "histories": rows}
    if saved is not None and result != saved:
        raise MigrationIOError("history_migration_id_conflict")
    return result, physical


def _unchanged_archive(root, manifest, copies):
    if not manifest["histories"]:
        return None
    selected, conflicts = _select_history_versions(root.parent.parent, _ArchiveBudget(), retain_raw=False)
    source = dict(copies)
    mids = set()
    for row in manifest["histories"]:
        hid = row["historyId"]
        previous = selected.get(hid)
        if hid in conflicts or previous is None:
            return None
        old, mid, journal = previous
        raw = source[row["journal"]["path"]].raw
        if journal.raw != raw or not _extends_history(old, raw, row, raw):
            return None
        mids.add(mid)
    if len(mids) != 1:
        return None
    mid = next(iter(mids))
    loaded = _load_archive(root / mid, visible_only=True)
    if loaded is None or loaded[0]["schemaVersion"] not in (2, 3):
        return None
    if loaded[0].get("sourceFingerprint") != manifest.get("sourceFingerprint"):
        return None
    if {row["historyId"] for row in loaded[0]["histories"]} != {row["historyId"] for row in manifest["histories"]}:
        return None
    return mid


def import_history(discovery: HistoryDiscovery, target_root: Path, migration_id: str, *, authority_verify=None, write_guard=None, confirmation_guard=None) -> dict:
    if not _token(migration_id) or not discovery.report.get("historyComplete"):
        raise MigrationIOError("history_discovery_incomplete")
    target = _canonical_target(target_root)
    for source in discovery.source_roots:
        source = check_path(source).resolve()
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise MigrationIOError("history_target_overlaps_source")
    if authority_verify is not None:
        authority_verify()
    _verify_source(discovery)
    manifest, copies = _manifest(discovery, migration_id)
    guard = write_guard or nullcontext
    with ExitStack() as stack:
        with guard():
            target = stack.enter_context(pinned_target_directory(target, create=True))
            root = stack.enter_context(pinned_target_directory(target / "history_archive/migrations", create=True))
        with migration_target_lock(root / ".publish"):
            return _publish_history(discovery, root, migration_id, manifest, copies, authority_verify, guard, confirmation_guard)


def _publish_history(discovery, root, migration_id, manifest, copies, authority_verify=None, write_guard=nullcontext, confirmation_guard=None):
    """Caller holds the verified migrations parent chain and writer mutex."""
    final, pending = root / migration_id, root / ("." + migration_id + ".pending")
    saved = None
    for directory in (final, pending):
        if (directory / "manifest.json").exists():
            saved = strict_json(read_stable_file(directory / "manifest.json", _FILE_CAP).raw)
            if not isinstance(saved, dict) or saved.get("migrationId") != migration_id:
                raise MigrationIOError("history_migration_id_conflict")
            break
    if saved is None and not (final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink()):
        unchanged = _unchanged_archive(root, manifest, copies)
        if unchanged is not None:
            with confirmation_guard() if confirmation_guard is not None else nullcontext():
                reused = _load_archive(root / unchanged, visible_only=True)
                if reused is None:
                    raise MigrationIOError("history_archive_reference_invalid")
                reused_manifest = reused[0]
                with _pin_parent_archives(root / unchanged, reused_manifest, include_self=True):
                    _verify_source(discovery)
                    if authority_verify is not None:
                        authority_verify()
            return {"migrationId": unchanged, "published": True, "idempotent": True,
                    "historyCount": len(discovery.sessions), "readyForCutover": False}
    if saved is None or saved.get("schemaVersion") == 3:
        manifest, copies = _incremental_manifest(root, manifest, copies, saved=saved)
    if final.exists() or final.is_symlink():
        _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, confirmation_guard, existing=True)
        return {"migrationId": migration_id, "published": True, "idempotent": True,
                "historyCount": len(discovery.sessions), "readyForCutover": False}
    # Reject an unreadable combined archive before creating a new root entry.
    logical_manifest, logical_copies = _manifest(discovery, migration_id)
    _validate_history_extension(root.parent.parent, logical_manifest, dict(logical_copies), pending=pending,
                                physical_manifest=manifest, physical_copies=dict(copies))
    with ExitStack() as stack:
        with write_guard():
            pending = stack.enter_context(pinned_target_directory(pending, create=True))
        with write_guard():
            _write_new(pending / "manifest.json", _encoded(manifest))
        for relative, snapshot in copies:
            with write_guard():
                _write_new(pending / relative, snapshot.raw)
        stored, _ = _load_archive(pending, migration_id=migration_id)
        if stored != manifest:
            raise MigrationIOError("history_copy_mismatch")
        _verify_source(discovery)
        if authority_verify is not None:
            authority_verify()
        pending_identity = path_identity(pending)
    # The generic no-delete lease closes for publication. The helper acquires
    # a verified DELETE handle, checks that this is still the same directory,
    # and renames that object while the destination parent chain stays pinned.
    with write_guard():
        publish_directory(pending, final, pending_identity)
    _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, confirmation_guard, existing=False)
    return {"migrationId": migration_id, "published": True, "idempotent": False,
            "historyCount": len(discovery.sessions), "readyForCutover": False}


def _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, confirmation_guard, *, existing):
    # Keep the directory identity fixed until its confirmation is published.
    with pinned_target_directory(final):
        stored, snapshots = _load_archive(final)
        # v1 has no confirmation marker and cannot prove an old import finished.
        if stored != manifest and not (existing and stored == {**manifest, "schemaVersion": 1}):
            raise MigrationIOError("history_migration_id_conflict" if existing else "history_copy_mismatch")
        _verify_source(discovery)
        if authority_verify is not None:
            authority_verify()
        if stored["schemaVersion"] in (2, 3):
            if not _confirmation_exists(final):
                logical_manifest, logical_copies = _manifest(discovery, manifest["migrationId"])
                physical = {path: snapshot for path, snapshot in snapshots.items()
                            if path != "manifest.json" and (final / path).is_file()}
                _validate_history_extension(final.parent.parent.parent, logical_manifest, dict(logical_copies),
                    pending=final, physical_manifest=stored, physical_copies=physical)
            _confirm_archive(final, write_guard, confirmation_guard, discovery, authority_verify, stored)


def _confirmation_exists(directory):
    marker = directory / ".confirmed"
    if not marker.exists() and not marker.is_symlink():
        return False
    check_path(marker)
    if not marker.is_dir() or any(marker.iterdir()):
        raise MigrationIOError("history_archive_invalid")
    return True


@contextmanager
def _pin_parent_archives(directory, manifest, *, include_self=False):
    if manifest is None or (manifest["schemaVersion"] != 3 and not include_self):
        yield
        return
    from core.web.services.personal_assistant_project.windows_read import _locked_source, lock_source_directory
    budget = _ArchiveBudget()
    _load_archive(directory, budget=budget)
    root = directory.parent
    with ExitStack() as stack:
        for mid in sorted(budget.archive_cache):
            if mid == manifest["migrationId"] and not include_self:
                continue
            parent = root / mid
            marker = parent / ".confirmed"
            stack.enter_context(lock_source_directory(Path(marker.anchor), marker, allow_child_replacement=True))
            for relative in sorted(budget.archive_cache[mid][1]):
                path = parent / relative
                stack.enter_context(_locked_source(Path(path.anchor), path, directory=False, allow_child_replacement=True))
        # Fresh reads after acquiring leases, without trusting the discovery cache.
        _load_archive(directory, budget=_ArchiveBudget())
        yield


def _confirm_archive(directory, write_guard, confirmation_guard=None, discovery=None, authority_verify=None, manifest=None):
    # Publish an empty directory by verified handle as the visibility commit.
    # A crash before the rename leaves only the hidden pending marker.
    if _confirmation_exists(directory):
        return
    pending = directory / ".confirmation.pending"
    with ExitStack() as stack:
        with write_guard():
            stack.enter_context(pinned_target_directory(directory))
            pending = stack.enter_context(pinned_target_directory(pending, create=True))
        if any(pending.iterdir()):
            raise MigrationIOError("history_archive_invalid")
        identity = path_identity(pending)
        stack.pop_all().close()
    with write_guard():
        with confirmation_guard() if confirmation_guard is not None else nullcontext():
            with _pin_parent_archives(directory, manifest):
                if discovery is not None:
                    _verify_source(discovery)
                if authority_verify is not None:
                    authority_verify()
                publish_directory(pending, directory / ".confirmed", identity)


def _load_physical_archive(directory, *, migration_id=None, budget=None, visible_only=False):
    budget = budget if budget is not None else _ArchiveBudget()
    mid = migration_id or directory.name
    cached = budget.archive_cache.get(mid)
    if cached is not None:
        if visible_only and cached[0]["schemaVersion"] in (2, 3) and not _confirmation_exists(directory):
            return None
        return cached
    check_path(directory)
    manifest_snapshot = budget.read(directory / "manifest.json")
    manifest = strict_json(manifest_snapshot.raw)
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") not in (1, 2, 3)
            or manifest.get("migrationId") != mid or not _token(mid)
            or not isinstance(manifest.get("histories"), list) or len(manifest["histories"]) > 10000
            or manifest.get("readOnly") is not True or manifest.get("canContinue") is not False
            or manifest.get("untrustedContent") is not True):
        raise MigrationIOError("history_archive_invalid")
    if visible_only and manifest["schemaVersion"] in (2, 3) and not _confirmation_exists(directory):
        return None
    budget.reserve("histories_left", len(manifest["histories"]))
    budget.history_charged.add(mid)
    expected, ids, snapshots = {"manifest.json"}, set(), {}
    for row in manifest["histories"]:
        if not isinstance(row, dict) or not _token(row.get("sessionId")) or not isinstance(row.get("sourceScope"), dict):
            raise MigrationIOError("history_archive_invalid")
        hid = _digest({"sourceScope": row["sourceScope"], "sessionId": row["sessionId"]})
        if hid != row.get("historyId") or hid in ids or not isinstance(row.get("assets"), list):
            raise MigrationIOError("history_archive_invalid")
        if len(expected) + 1 + len(row["assets"]) > budget.files_left:
            raise MigrationIOError("history_archive_limit")
        ids.add(hid)
        prefix = _digest(row["sourceScope"]) + "/" + hid
        journal = row.get("journal", {})
        if not isinstance(journal, dict) or journal.get("path") != prefix + "/turn_journal.jsonl":
            raise MigrationIOError("history_archive_invalid")
        base = row.get("base") if manifest["schemaVersion"] == 3 else None
        if manifest["schemaVersion"] == 3 and "base" in row and not isinstance(base, dict):
            raise MigrationIOError("history_archive_invalid")
        if base is not None:
            if (not isinstance(base, dict) or set(base) != {"migrationId", "historyId", "journalSize", "journalSha256"}
                    or not _token(base["migrationId"]) or base["historyId"] != hid
                    or type(base["journalSize"]) is not int or not 0 <= base["journalSize"] <= _FILE_CAP
                    or not isinstance(base["journalSha256"], str) or not _HASH.fullmatch(base["journalSha256"])):
                raise MigrationIOError("history_archive_invalid")
            delta = row.get("delta")
            if not isinstance(delta, dict) or delta.get("path") != prefix + "/journal.delta":
                raise MigrationIOError("history_archive_invalid")
        else:
            delta = None
        for entry in [journal, *row["assets"], *([delta] if delta is not None else [])]:
            if (not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
                    or not _HASH.fullmatch(entry["sha256"]) or type(entry.get("size")) is not int
                    or not 0 <= entry["size"] <= _FILE_CAP):
                raise MigrationIOError("history_archive_invalid")
            if entry is not journal and entry is not delta:
                aid = entry.get("attachmentId")
                if not isinstance(aid, str) or not _HASH.fullmatch(aid) or entry.get("path") != prefix + "/assets/" + aid:
                    raise MigrationIOError("history_archive_invalid")
                if "inherited" in entry and (base is None or entry["inherited"] is not True):
                    raise MigrationIOError("history_archive_invalid")
            if entry is journal and base is not None:
                continue
            if entry is not journal and entry is not delta and entry.get("inherited") is True:
                continue
            relative = entry["path"]
            if relative in expected:
                raise MigrationIOError("history_archive_invalid")
            expected.add(relative)
            snapshots[relative] = entry
    tree = budget.tree(directory)
    actual = {snap.path.relative_to(directory).as_posix(): snap for snap in tree}
    if set(actual) != expected:
        raise MigrationIOError("history_archive_file_mismatch")
    for relative, entry in snapshots.items():
        snap = actual[relative]
        if snap.sha256 != entry["sha256"] or len(snap.raw) != entry["size"]:
            raise MigrationIOError("history_archive_hash_mismatch")
    for row in manifest["histories"]:
        if row.get("base") is not None and manifest["schemaVersion"] == 3:
            continue
        events = _events(actual[row["journal"]["path"]].raw, row["sessionId"])
        watermark = {"eventCount": len(events), "sequence": events[-1].sequence if events else 0,
            "eventId": events[-1].event_id if events else "", "sha256": row["journal"]["sha256"]}
        if row.get("watermark") != watermark:
            raise MigrationIOError("history_archive_watermark_mismatch")
    verified = budget.read(manifest_snapshot.path, expected=manifest_snapshot.identity)
    if verified.sha256 != manifest_snapshot.sha256:
        raise MigrationIOError("source_changed")
    # Attachment bytes are verified, but navigation exposes only metadata.
    # Do not retain their bodies in the per-operation reference cache.
    for row in manifest["histories"]:
        for asset in row["assets"]:
            if asset.get("inherited") is not True:
                snap = actual[asset["path"]]
                actual[asset["path"]] = FileSnapshot(snap.path, b"", snap.sha256, snap.identity)
    budget.archive_cache[mid] = (manifest, actual)
    return manifest, actual


def _resolve_history(root, manifest, row, actual, budget, depth=0):
    key = (manifest["migrationId"], row["historyId"])
    if key in budget.resolving or depth > _HISTORY_CHAIN_CAP:
        raise MigrationIOError("history_archive_reference_invalid")
    if manifest["schemaVersion"] != 3 or "base" not in row:
        return actual[row["journal"]["path"]], {a["attachmentId"]: actual[a["path"]] for a in row["assets"]}
    budget.resolving.add(key)
    try:
        base = row["base"]
        parent_dir = root / base["migrationId"]
        if not _confirmation_exists(parent_dir):
            raise MigrationIOError("history_archive_reference_invalid")
        loaded = _load_physical_archive(parent_dir, budget=budget, visible_only=True)
        if loaded is None or loaded[0]["schemaVersion"] not in (2, 3):
            raise MigrationIOError("history_archive_reference_invalid")
        parent_manifest, parent_actual = loaded
        matches = [item for item in parent_manifest["histories"] if item["historyId"] == row["historyId"]]
        if len(matches) != 1:
            raise MigrationIOError("history_archive_reference_invalid")
        parent = matches[0]
        if parent["sessionId"] != row["sessionId"] or parent["sourceScope"] != row["sourceScope"]:
            raise MigrationIOError("history_archive_reference_invalid")
        previous, parent_assets = _resolve_history(root, parent_manifest, parent, parent_actual, budget, depth + 1)
        if len(previous.raw) != base["journalSize"] or previous.sha256 != base["journalSha256"]:
            raise MigrationIOError("history_archive_reference_invalid")
        raw = previous.raw + actual[row["delta"]["path"]].raw
        if (len(raw) > _FILE_CAP or len(raw) != row["journal"]["size"]
                or hashlib.sha256(raw).hexdigest() != row["journal"]["sha256"]):
            raise MigrationIOError("history_archive_hash_mismatch")
        old = {asset["attachmentId"]: asset for asset in parent["assets"]}
        current = {asset["attachmentId"]: asset for asset in row["assets"]}
        if len(current) != len(row["assets"]) or not set(old).issubset(current):
            raise MigrationIOError("history_archive_reference_invalid")
        assets = {}
        for aid, asset in current.items():
            if aid in old:
                if (asset.get("inherited") is not True or asset["sha256"] != old[aid]["sha256"]
                        or asset["size"] != old[aid]["size"]):
                    raise MigrationIOError("history_archive_reference_invalid")
                assets[aid] = parent_assets[aid]
            else:
                if asset.get("inherited") is True:
                    raise MigrationIOError("history_archive_reference_invalid")
                assets[aid] = actual[asset["path"]]
        events = _events(raw, row["sessionId"])
        watermark = {"eventCount": len(events), "sequence": events[-1].sequence if events else 0,
                     "eventId": events[-1].event_id if events else "", "sha256": row["journal"]["sha256"]}
        if watermark != row["watermark"]:
            raise MigrationIOError("history_archive_watermark_mismatch")
        return FileSnapshot(root / row["journal"]["path"], raw, row["journal"]["sha256"], ()), assets
    finally:
        budget.resolving.remove(key)


def _load_archive(directory, *, migration_id=None, budget=None, visible_only=False):
    budget = budget if budget is not None else _ArchiveBudget()
    loaded = _load_physical_archive(directory, migration_id=migration_id, budget=budget, visible_only=visible_only)
    if loaded is None or loaded[0]["schemaVersion"] != 3:
        return loaded
    manifest, physical = loaded
    actual = dict(physical)
    for row in manifest["histories"]:
        journal, assets = _resolve_history(directory.parent, manifest, row, physical, budget)
        # Verify each logical history now, then resolve its bounded Journal
        # on demand; do not retain all reconstructed versions at once.
        actual[row["journal"]["path"]] = _LazyJournal(directory.parent, manifest, row, physical, budget)
        for asset in row["assets"]:
            actual[asset["path"]] = assets[asset["attachmentId"]]
        del journal, assets
    return manifest, actual


class _LazyJournal:
    def __init__(self, root, manifest, row, physical, budget):
        self.root, self.manifest, self.row, self.physical, self.budget = root, manifest, row, physical, budget

    @property
    def raw(self):
        journal, _ = _resolve_history(self.root, self.manifest, self.row, self.physical, self.budget)
        return journal.raw


def _quarantined_v3(directory, budget, failure):
    # Only confirmed v3 archives with a parseable manifest can be isolated.
    # Unknown or legacy corruption retains the existing fail-closed behavior.
    allowed = {"history_archive_invalid", "history_archive_file_mismatch", "history_archive_hash_mismatch",
               "history_archive_reference_invalid", "history_archive_watermark_mismatch", "history_event_invalid",
               "history_event_identity_invalid", "history_turn_identity_conflict", "history_identity_conflict",
               "history_identity_missing", "history_import_not_quiescent", "truncated_history_jsonl",
               "invalid_source_json"}
    if str(failure) not in allowed:
        raise failure
    cached = budget.archive_cache.get(directory.name)
    manifest = cached[0] if cached is not None else strict_json(budget.read(directory / "manifest.json").raw)
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 3
            or manifest.get("migrationId") != directory.name or not _confirmation_exists(directory)):
        raise failure
    rows = manifest.get("histories")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise failure
    if directory.name not in budget.history_charged:
        budget.reserve("histories_left", len(rows))
        budget.history_charged.add(directory.name)
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or not _token(row.get("sessionId"))
                or not isinstance(row.get("sourceScope"), dict)):
            raise failure
        hid = _digest({"sourceScope": row["sourceScope"], "sessionId": row["sessionId"]})
        if hid != row.get("historyId") or hid in ids:
            raise failure
        ids.add(hid)
    budget.quarantined_archives += 1
    return {"migrationId": directory.name, "histories": [], "quarantinedHistoryIds": ids}, {}


def _archives(target_root, *, budget, exclude_migration_id=None, isolate_errors=False):
    root = _archive_root(target_root)
    if not root.exists():
        return
    with os.scandir(root) as children:
        for child in children:
            budget.reserve("files_left")
            if child.name.startswith("."):
                continue
            if child.name == exclude_migration_id:
                continue
            if not _token(child.name):
                raise MigrationIOError("history_archive_invalid")
            budget.reserve("archives_left")
            # A generator keeps at most the current archive's bytes alive;
            # callers must not materialize this iterator before pagination.
            try:
                archive = _load_archive(Path(child.path), budget=budget, visible_only=True)
            except MigrationIOError as error:
                if not isolate_errors:
                    raise
                archive = _quarantined_v3(Path(child.path), budget, error)
            if archive is not None:
                yield archive


def _summary(row, migration_id):
    return {key: row[key] for key in ("historyId", "sessionId", "sourceScope", "watermark")} | {
        "migrationId": migration_id, "assetCount": len(row["assets"]), "readOnly": True,
        "untrustedContent": True, "canContinue": False}


def _extends_history(old_row, old_raw, new_row, new_raw):
    """Prove retained history and attachment identities survive a new snapshot."""
    old_assets = {asset["attachmentId"]: (asset["sha256"], asset["size"])
                  for asset in old_row["assets"]}
    new_assets = {asset["attachmentId"]: (asset["sha256"], asset["size"])
                  for asset in new_row["assets"]}
    if not new_raw.startswith(old_raw):
        return False
    if any(new_assets.get(key) != value for key, value in old_assets.items()):
        return False
    # Without a Journal append there is no evidence of a new history version.
    return len(new_raw) > len(old_raw) or old_assets == new_assets


def _reserve_candidate_budget(budget, candidate, snapshots, *, root_entry_exists):
    """Account for the prospective confirmed archive exactly as a reader does."""
    snapshots = {path: snapshot for path, snapshot in snapshots.items() if path != "manifest.json"}
    if not root_entry_exists:
        budget.reserve("files_left")
    budget.reserve("archives_left")
    manifest_raw = _encoded(candidate)
    budget.reserve("files_left")  # initial manifest read
    budget.reserve("bytes_left", len(manifest_raw))
    budget.reserve("histories_left", len(candidate["histories"]))
    expected_count = 1
    for row in candidate["histories"]:
        if expected_count + 1 + len(row["assets"]) > budget.files_left:
            raise MigrationIOError("history_archive_limit")
        expected_count += 1 + sum(asset.get("inherited") is not True for asset in row["assets"])
    paths = ["manifest.json", *snapshots.keys()]
    directories = {".confirmed"}
    for path in paths:
        parts = path.split("/")
        directories.update("/".join(parts[:i]) for i in range(1, len(parts)))
    budget.reserve("files_left", len(paths) + len(directories))
    physical_sizes = {}
    for row in candidate["histories"]:
        entry = row.get("delta") if "base" in row else row["journal"]
        physical_sizes[entry["path"]] = entry["size"]
        physical_sizes.update({asset["path"]: asset["size"] for asset in row["assets"]
                               if asset.get("inherited") is not True})
    if set(snapshots) != set(physical_sizes):
        raise MigrationIOError("history_archive_invalid")
    budget.reserve("bytes_left", len(manifest_raw) + sum(physical_sizes.values()))
    budget.reserve("files_left")  # verified manifest reread
    budget.reserve("bytes_left", len(manifest_raw))


def _validate_history_extension(target_root, candidate, snapshots, *, pending=None,
                                physical_manifest=None, physical_copies=None):
    incoming = {row["historyId"]: row for row in candidate["histories"]}
    versions = {hid: [row] for hid, row in incoming.items()}
    budget = _ArchiveBudget()
    for manifest, prior_snapshots in _archives(target_root, budget=budget,
                                               exclude_migration_id=candidate["migrationId"]):
        for old in manifest["histories"]:
            new = incoming.get(old["historyId"])
            if new is not None:
                old_raw = prior_snapshots[old["journal"]["path"]].raw
                if not _extends_history(old, old_raw, new, snapshots[new["journal"]["path"]].raw):
                    raise MigrationIOError("history_archive_identity_conflict")
                versions[old["historyId"]].append(old)
    if any(not _proven_asset_chain(items) for items in versions.values()):
        raise MigrationIOError("history_archive_identity_conflict")
    _reserve_candidate_budget(budget, physical_manifest or candidate,
                              physical_copies if physical_copies is not None else snapshots,
                              root_entry_exists=pending is not None and pending.exists())


def _proven_asset_chain(rows):
    # All Journal bytes are already proven prefixes of the same candidate.
    rows.sort(key=lambda row: row["journal"]["size"])
    for old, new in zip(rows, rows[1:]):
        before = {asset["attachmentId"]: (asset["sha256"], asset["size"]) for asset in old["assets"]}
        after = {asset["attachmentId"]: (asset["sha256"], asset["size"]) for asset in new["assets"]}
        if (any(after.get(key) != value for key, value in before.items())
                or (old["journal"]["size"] == new["journal"]["size"] and before != after)):
            return False
    return True


def _select_history_versions(target_root, budget, *, history_id=None, retain_raw=True, isolate_errors=False):
    selected, versions, conflicts = {}, {}, set()
    for manifest, snapshots in _archives(target_root, budget=budget, isolate_errors=isolate_errors):
        conflicts.update(manifest.get("quarantinedHistoryIds", ()))
        for row in manifest["histories"]:
            hid = row["historyId"]
            if history_id is not None and hid != history_id:
                continue
            versions.setdefault(hid, []).append((row, manifest["migrationId"], snapshots[row["journal"]["path"]]))
    for hid, history_versions in versions.items():
        if hid in conflicts:
            continue
        history_versions.sort(key=lambda item: item[0]["journal"]["size"])
        largest = history_versions[-1][0]["journal"]["size"]
        tied = [item for item in history_versions if item[0]["journal"]["size"] == largest]
        root = _archive_root(target_root)
        def parent_priority(item):
            row, mid, snapshot = item
            stored = budget.archive_cache[mid][0]
            confirmed = stored["schemaVersion"] in (2, 3) and _confirmation_exists(root / mid)
            depth = len(_parent_chain(root, row, mid, snapshot, budget)) if confirmed else _HISTORY_CHAIN_CAP + 2
            return (not confirmed, depth, mid)
        latest_row, latest_mid, latest_snapshot = min(tied, key=parent_priority)
        raw = latest_snapshot.raw
        # Each journal has already passed its archive hash verification. A
        # matching prefix hash proves its relationship to the longest version
        # without retaining one full Journal per historical version.
        view = memoryview(raw)
        if any(hashlib.sha256(view[:row["journal"]["size"]]).hexdigest() != row["journal"]["sha256"]
               for row, _, _ in history_versions):
            conflicts.add(hid)
            continue
        for (old, _, _), (new, _, _) in zip(history_versions, history_versions[1:]):
            old_assets = {asset["attachmentId"]: (asset["sha256"], asset["size"]) for asset in old["assets"]}
            new_assets = {asset["attachmentId"]: (asset["sha256"], asset["size"]) for asset in new["assets"]}
            if (any(new_assets.get(key) != value for key, value in old_assets.items())
                    or (old["journal"]["size"] == new["journal"]["size"] and old_assets != new_assets)):
                conflicts.add(hid)
                break
        else:
            selected[hid] = (latest_row, latest_mid, raw if retain_raw else latest_snapshot)
    return selected, conflicts


def list_history(target_root: Path, *, max_total_bytes: int = _ARCHIVE_BYTES_CAP,
                 max_files: int = _ARCHIVE_FILES_CAP, max_history_rows: int = 10000,
                 max_archives: int = _ARCHIVE_COUNT_CAP) -> list[dict]:
    return list_history_with_status(target_root, max_total_bytes=max_total_bytes, max_files=max_files,
                                    max_history_rows=max_history_rows, max_archives=max_archives)["histories"]


def list_history_with_status(target_root: Path, *, max_total_bytes: int = _ARCHIVE_BYTES_CAP,
                             max_files: int = _ARCHIVE_FILES_CAP, max_history_rows: int = 10000,
                             max_archives: int = _ARCHIVE_COUNT_CAP) -> dict:
    budget = _ArchiveBudget(max_total_bytes, max_files, max_history_rows, max_archives)
    selected, conflicts = _select_history_versions(target_root, budget, retain_raw=False, isolate_errors=True)
    rows = sorted((_summary(row, mid) for row, mid, _ in selected.values()),
                  key=lambda row: row["historyId"])
    return {"histories": rows, "partial": bool(conflicts) or bool(budget.quarantined_archives),
            "conflictCount": len(conflicts), "unavailableArchiveCount": budget.quarantined_archives}



def _history_visible_messages(events):
    """Project archive messages after removing structured non-text payloads.

    The ordinary Journal projection stringifies arbitrary payloads. Archive
    navigation keeps only explicitly typed text parts before invoking it, so
    both search indexes and read indexes use the same safe projection.
    """
    fields = {"user_message": "content", "assistant_message": "content",
              "assistant_partial": "content", "assistant_delta_committed": "content",
              "assistant_item_committed": "text"}
    source_roles = {"user_message": "user", "assistant_message": "assistant",
                    "assistant_partial": "assistant", "assistant_delta_committed": "assistant",
                    "assistant_item_committed": "assistant"}
    sources = {event.event_id: source_roles.get(event.event_type) for event in events}
    sanitized = []
    for event in events:
        key = fields.get(event.event_type)
        if key is None:
            sanitized.append(event)
            continue
        payload = dict(event.payload)
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            # The Journal projection normally lets payload metadata override
            # its generated eventId. Restore the verified source identity while
            # keeping legitimate kinds such as user_guidance intact.
            payload["metadata"] = {**metadata, "eventId": event.event_id}
        if key in payload and not isinstance(payload[key], str):
            value = payload[key]
            text = ""
            if isinstance(value, list):
                text = "\n".join(part["text"] for part in value
                                 if isinstance(part, dict) and isinstance(part.get("type"), str)
                                 and part["type"] in {"text", "input_text", "output_text"}
                                 and isinstance(part.get("text"), str))
            payload[key] = text
        sanitized.append(replace(event, payload=payload))
    try:
        messages = project_conversation_ledger(sanitized, include_model_messages=False,
                                               include_visible_messages=True).visible_messages
        # Only source Journal message events contribute text. Tool lifecycle
        # and recovery rows can also be projected with an assistant role.
        safe = []
        for message in messages:
            metadata = message.get("metadata")
            event_id = metadata.get("eventId") if isinstance(metadata, dict) else None
            role = message.get("role")
            if not isinstance(event_id, str) or sources.get(event_id) != role or role not in ("user", "assistant"):
                message = {**message, "content": ""}
            safe.append(message)
        return safe
    except (ValueError, TypeError, KeyError, RecursionError):
        raise MigrationIOError("history_projection_invalid") from None


def search_history(target_root: Path, query: str, *, cursor: str = "", limit: int = 6) -> dict:
    """Search a bounded, verified visible-message projection; never return content."""
    normalized = unicodedata.normalize("NFKC", query).strip().casefold()
    if not normalized or len(normalized) > 256:
        raise MigrationIOError("history_search_query_invalid")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError:
        raise MigrationIOError("history_search_query_invalid") from None
    budget = _ArchiveBudget()
    selected, conflicts = _select_history_versions(target_root, budget, retain_raw=False, isolate_errors=True)
    # Verified manifests commit to every physical and logical archive object.
    # Partial/quarantined corpora cannot offer a stable archive snapshot.
    incomplete = bool(conflicts) or bool(budget.quarantined_archives)
    snapshot = _digest({"archives": sorted((mid, _digest(entry[0])) for mid, entry in budget.archive_cache.items()),
                        "selected": sorted((hid, row["journal"]["sha256"], mid)
                                           for hid, (row, mid, _) in selected.items()),
                        "conflicts": sorted(conflicts), "unavailable": budget.quarantined_archives})
    binding = _digest({"query": normalized, "snapshot": snapshot})
    offset = 0
    if cursor:
        match = re.fullmatch(r"v1\.([a-f0-9]{64})\.([0-9]{1,6})", cursor)
        if not match or match.group(1) != binding or incomplete:
            raise MigrationIOError("history_search_cursor_invalidated")
        offset = int(match.group(2))
    results, seen, scanned_messages, scanned_characters = [], 0, 0, 0
    scan_limited = False
    for hid in sorted(selected):
        row, _, journal = selected[hid]
        events = _events(journal.raw, row["sessionId"])
        messages = _history_visible_messages(events)
        searchable = {event.event_id: event.event_type for event in events
                      if event.event_type in {"user_message", "assistant_message", "assistant_item_committed"}
                      and not (event.event_type == "assistant_message" and event.status.lower() in
                               {"aborted", "cancelled", "canceled", "interrupted", "stopped", "stopped_by_user"})}
        for index, message in enumerate(messages):
            role, content = message.get("role"), message.get("content")
            metadata = message.get("metadata")
            event_id = metadata.get("eventId") if isinstance(metadata, dict) else None
            if (role not in ("user", "assistant") or not isinstance(event_id, str)
                    or event_id not in searchable or not isinstance(content, str) or not content):
                continue
            if scanned_messages >= 10000 or scanned_characters + len(content) > 2000000:
                scan_limited = True
                break
            scanned_messages += 1
            scanned_characters += len(content)
            if normalized in unicodedata.normalize("NFKC", content).casefold():
                if offset <= seen < offset + limit:
                    results.append({"historyId": hid, "messageIndex": index, "role": role,
                                    "journalSha256": row["journal"]["sha256"]})
                seen += 1
        if scan_limited:
            break
    next_offset = offset + len(results)
    # An incomplete corpus cannot guarantee snapshot stability, so expose its
    # first page only and report that additional results may be omitted.
    next_cursor = f"v1.{binding}.{next_offset}" if seen > next_offset and not incomplete else None
    return {"matches": results, "nextCursor": next_cursor,
            "searchScope": "user_and_final_assistant; excludes timeline-only commentary and deltas",
            "partial": incomplete or scan_limited,
            "scanLimited": scan_limited, "conflictCount": len(conflicts),
            "unavailableArchiveCount": budget.quarantined_archives,
            "readOnly": True, "untrustedContent": True}


def _safe_projection(value):
    # URLs and paths from transcript/tool data are untrusted text, never a
    # directly loadable src. Dedicated archive attachments have logical IDs.
    if isinstance(value, list):
        return [_safe_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {"url", "src", "href", "path", "localpath", "filepath", "image_url", "imageurl", "dataurl", "thumbnailurl"}
    result = {key: _safe_projection(item) for key, item in value.items() if key.lower() not in blocked}
    if any(key.lower() in blocked for key in value):
        result["untrustedAttachmentReference"] = True
    return result


def history_detail(target_root: Path, history_id: str, *, expected_journal_sha256: str | None = None,
                   max_total_bytes: int = _ARCHIVE_BYTES_CAP,
                   max_files: int = _ARCHIVE_FILES_CAP, max_history_rows: int = 10000,
                   max_archives: int = _ARCHIVE_COUNT_CAP) -> dict:
    if not isinstance(history_id, str) or not _HASH.fullmatch(history_id):
        raise MigrationIOError("history_id_invalid")
    if expected_journal_sha256 is not None and (not isinstance(expected_journal_sha256, str)
                                                   or not _HASH.fullmatch(expected_journal_sha256)):
        raise MigrationIOError("history_journal_digest_invalid")
    budget = _ArchiveBudget(max_total_bytes, max_files, max_history_rows, max_archives)
    selected, conflicts = _select_history_versions(target_root, budget, history_id=history_id, isolate_errors=True)
    if history_id in conflicts:
        raise MigrationIOError("history_archive_identity_conflict")
    if history_id not in selected:
        raise MigrationIOError("history_not_found")
    row, mid, raw = selected[history_id]
    if expected_journal_sha256 is not None and row["journal"]["sha256"] != expected_journal_sha256:
        raise MigrationIOError("history_version_changed")
    events = _events(raw, row["sessionId"])
    try:
        messages = _history_visible_messages(events)
        items = conversation_turn_items_from_events(events)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise MigrationIOError("history_projection_invalid") from None
    return _summary(row, mid) | {"messages": _safe_projection(messages),
        "turnItems": _safe_projection(items), "events": _safe_projection([event.to_dict() for event in events]),
        "sourceBody": raw.decode("utf-8-sig"),
        "attachments": [{"attachmentId": asset["attachmentId"], "size": asset["size"],
                         "sha256": asset["sha256"], "untrustedContent": True} for asset in row["assets"]]}
