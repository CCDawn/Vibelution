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
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
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


def import_history(discovery: HistoryDiscovery, target_root: Path, migration_id: str, *, authority_verify=None, write_guard=None) -> dict:
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
            return _publish_history(discovery, root, migration_id, manifest, copies, authority_verify, guard)


def _publish_history(discovery, root, migration_id, manifest, copies, authority_verify=None, write_guard=nullcontext):
    """Caller holds the verified migrations parent chain and writer mutex."""
    final, pending = root / migration_id, root / ("." + migration_id + ".pending")
    if final.exists() or final.is_symlink():
        _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, existing=True)
        return {"migrationId": migration_id, "published": True, "idempotent": True,
                "historyCount": len(discovery.sessions), "readyForCutover": False}
    with ExitStack() as stack:
        with write_guard():
            pending = stack.enter_context(pinned_target_directory(pending, create=True))
        for relative, snapshot in copies:
            with write_guard():
                _write_new(pending / relative, snapshot.raw)
        with write_guard():
            _write_new(pending / "manifest.json", _encoded(manifest))
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
    _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, existing=False)
    return {"migrationId": migration_id, "published": True, "idempotent": False,
            "historyCount": len(discovery.sessions), "readyForCutover": False}


def _verify_and_confirm_final(final, discovery, manifest, authority_verify, write_guard, *, existing):
    # Keep the directory identity fixed until its confirmation is published.
    with pinned_target_directory(final):
        stored, _ = _load_archive(final)
        # v1 has no confirmation marker and cannot prove an old import finished.
        if stored != manifest and not (existing and stored == {**manifest, "schemaVersion": 1}):
            raise MigrationIOError("history_migration_id_conflict" if existing else "history_copy_mismatch")
        _verify_source(discovery)
        if authority_verify is not None:
            authority_verify()
        if stored["schemaVersion"] == 2:
            _confirm_archive(final, write_guard)


def _confirmation_exists(directory):
    marker = directory / ".confirmed"
    if not marker.exists() and not marker.is_symlink():
        return False
    check_path(marker)
    if not marker.is_dir() or any(marker.iterdir()):
        raise MigrationIOError("history_archive_invalid")
    return True


def _confirm_archive(directory, write_guard):
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
        publish_directory(pending, directory / ".confirmed", identity)


def _load_archive(directory, *, migration_id=None, budget=None, visible_only=False):
    budget = budget if budget is not None else _ArchiveBudget()
    check_path(directory)
    manifest_snapshot = budget.read(directory / "manifest.json")
    manifest = strict_json(manifest_snapshot.raw)
    mid = migration_id or directory.name
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") not in (1, 2)
            or manifest.get("migrationId") != mid or not _token(mid)
            or not isinstance(manifest.get("histories"), list) or len(manifest["histories"]) > 10000
            or manifest.get("readOnly") is not True or manifest.get("canContinue") is not False
            or manifest.get("untrustedContent") is not True):
        raise MigrationIOError("history_archive_invalid")
    if visible_only and manifest["schemaVersion"] == 2 and not _confirmation_exists(directory):
        return None
    budget.reserve("histories_left", len(manifest["histories"]))
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
        for entry in [journal, *row["assets"]]:
            if (not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
                    or not _HASH.fullmatch(entry["sha256"]) or type(entry.get("size")) is not int
                    or not 0 <= entry["size"] <= _FILE_CAP):
                raise MigrationIOError("history_archive_invalid")
            if entry is not journal:
                aid = entry.get("attachmentId")
                if not isinstance(aid, str) or not _HASH.fullmatch(aid) or entry.get("path") != prefix + "/assets/" + aid:
                    raise MigrationIOError("history_archive_invalid")
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
        events = _events(actual[row["journal"]["path"]].raw, row["sessionId"])
        watermark = {"eventCount": len(events), "sequence": events[-1].sequence if events else 0,
            "eventId": events[-1].event_id if events else "", "sha256": row["journal"]["sha256"]}
        if row.get("watermark") != watermark:
            raise MigrationIOError("history_archive_watermark_mismatch")
    verified = budget.read(manifest_snapshot.path, expected=manifest_snapshot.identity)
    if verified.sha256 != manifest_snapshot.sha256:
        raise MigrationIOError("source_changed")
    return manifest, actual


def _archives(target_root, *, budget):
    root = _archive_root(target_root)
    if not root.exists():
        return
    with os.scandir(root) as children:
        for child in children:
            budget.reserve("files_left")
            if child.name.startswith("."):
                continue
            if not _token(child.name):
                raise MigrationIOError("history_archive_invalid")
            budget.reserve("archives_left")
            # A generator keeps at most the current archive's bytes alive;
            # callers must not materialize this iterator before pagination.
            archive = _load_archive(Path(child.path), budget=budget, visible_only=True)
            if archive is not None:
                yield archive


def _summary(row, migration_id):
    return {key: row[key] for key in ("historyId", "sessionId", "sourceScope", "watermark")} | {
        "migrationId": migration_id, "assetCount": len(row["assets"]), "readOnly": True,
        "untrustedContent": True, "canContinue": False}


def list_history(target_root: Path, *, max_total_bytes: int = _ARCHIVE_BYTES_CAP,
                 max_files: int = _ARCHIVE_FILES_CAP, max_history_rows: int = 10000,
                 max_archives: int = _ARCHIVE_COUNT_CAP) -> list[dict]:
    budget = _ArchiveBudget(max_total_bytes, max_files, max_history_rows, max_archives)
    rows = {}
    for manifest, snapshots in _archives(target_root, budget=budget):
        for row in manifest["histories"]:
            summary = _summary(row, manifest["migrationId"])
            prior = rows.get(row["historyId"])
            if prior and prior["watermark"] != summary["watermark"]:
                raise MigrationIOError("history_archive_identity_conflict")
            rows[row["historyId"]] = summary
        del snapshots
    return sorted(rows.values(), key=lambda row: row["historyId"])


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


def history_detail(target_root: Path, history_id: str, *, max_total_bytes: int = _ARCHIVE_BYTES_CAP,
                   max_files: int = _ARCHIVE_FILES_CAP, max_history_rows: int = 10000,
                   max_archives: int = _ARCHIVE_COUNT_CAP) -> dict:
    if not isinstance(history_id, str) or not _HASH.fullmatch(history_id):
        raise MigrationIOError("history_id_invalid")
    found = None
    budget = _ArchiveBudget(max_total_bytes, max_files, max_history_rows, max_archives)
    for manifest, snapshots in _archives(target_root, budget=budget):
        for row in manifest["histories"]:
            if row["historyId"] != history_id:
                continue
            if found and found[0]["watermark"] != row["watermark"]:
                raise MigrationIOError("history_archive_identity_conflict")
            # Retain only the selected Journal, not all raw assets or other
            # sessions while checking later archives for identity conflicts.
            found = (row, manifest["migrationId"], {row["journal"]["path"]: snapshots[row["journal"]["path"]]})
        del snapshots
    if found is None:
        raise MigrationIOError("history_not_found")
    row, mid, snapshots = found
    events = _events(snapshots[row["journal"]["path"]].raw, row["sessionId"])
    try:
        projection = project_conversation_ledger(events, include_model_messages=False, include_visible_messages=True)
        items = conversation_turn_items_from_events(events)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise MigrationIOError("history_projection_invalid") from None
    return _summary(row, mid) | {"messages": _safe_projection(projection.visible_messages),
        "turnItems": _safe_projection(items), "events": _safe_projection([event.to_dict() for event in events]),
        "sourceBody": snapshots[row["journal"]["path"]].raw.decode("utf-8-sig"),
        "attachments": [{"attachmentId": asset["attachmentId"], "size": asset["size"],
                         "sha256": asset["sha256"], "untrustedContent": True} for asset in row["assets"]]}
