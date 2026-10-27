"""Immutable copies of approved legacy data sources, never live plugin state."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .migration_history import _canonical_target, _write_new
from .migration_io import (
    MigrationIOError, check_path, fingerprint_tree, migration_target_lock, path_identity,
    pinned_target_directory, publish_directory, read_stable_file, validate_path, verify_snapshot,
)

# Session history has its own native parser. Mailboxes, generic plugins and
# runtime/approval queues are evidence only and never imported as runnable data.
_CATEGORIES = frozenset({"memory", "episodic_memory", "private_knowledge", "mental_model",
    "personal_affairs", "agent_assets", "memory_summaries", "group_context_events",
    "tool_observations", "project_memory_updates"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


def import_source_snapshots(resolved, target_root: Path, migration_id: str, *, source_roots,
                            authority_snapshots=(), authority_verify=None) -> dict:
    if not isinstance(migration_id, str) or not _ID.fullmatch(migration_id):
        raise MigrationIOError("migration_id_invalid")
    target = validate_path(target_root)
    if not source_roots:
        raise MigrationIOError("source_scope_required")
    target = _canonical_target(target)
    for root in (*source_roots, *resolved.paths.values()):
        root = check_path(root).resolve()
        if target.is_relative_to(root) or root.is_relative_to(target):
            raise MigrationIOError("history_source_target_overlap")
    copies, entries = {}, []
    for row in resolved.report["sources"]:
        ref = row["sourceRef"]
        if row["category"] not in _CATEGORIES or ref not in resolved.snapshots:
            continue
        root = resolved.paths[ref]
        base = root if root.is_dir() else root.parent
        for snapshot in resolved.snapshots[ref]:
            relative = snapshot.path.relative_to(base).as_posix()
            destination = f"sources/{ref}/{relative}"
            copies[destination] = snapshot.raw
            entries.append({"sourceRef": ref, "category": row["category"], "path": destination,
                            "sha256": snapshot.sha256, "size": len(snapshot.raw)})
    if not entries:
        raise MigrationIOError("no_approved_data_sources")
    manifest = {"schemaVersion": 1, "migrationId": migration_id, "sourceScope": resolved.report["sourceScope"],
        "readOnly": True, "untrustedContent": True, "activePluginStateImported": False,
        "sourceComplete": resolved.report.get("snapshotComplete") is True,
        "entries": entries, "readyForCutover": False}
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    def verify_sources():
        if authority_verify is not None:
            authority_verify()
        for snapshot in authority_snapshots:
            verify_snapshot(snapshot)
        for snapshots in resolved.snapshots.values():
            for snapshot in snapshots:
                verify_snapshot(snapshot)
        for proofs in resolved.directoryproofs.values():
            for path, identity in proofs:
                check_path(path)
                if path_identity(path) != identity:
                    raise MigrationIOError("source_changed")

    def verify_target(directory):
        expected_files = {"manifest.json", *copies}
        expected_directories = {Path(".")}
        for relative in expected_files:
            expected_directories.update(Path(relative).parents)
        tree = fingerprint_tree(directory, max_files=len(expected_files) + len(expected_directories) - 1,
            max_total_bytes=sum(entry["size"] for entry in entries) + len(encoded))
        if ({snapshot.path.relative_to(directory).as_posix() for snapshot in tree} != expected_files
                or {path.relative_to(directory) for path, _ in tree.directories} != expected_directories):
            raise MigrationIOError("history_target_conflict")
        if read_stable_file(directory / "manifest.json", 16 * 1024 * 1024).raw != encoded:
            raise MigrationIOError("history_target_conflict")
        for entry in entries:
            current = read_stable_file(directory / entry["path"], entry["size"])
            if current.sha256 != entry["sha256"]:
                raise MigrationIOError("history_target_conflict")

    verify_sources()
    with pinned_target_directory(target, create=True):
        root = target / "history_sources/migrations"
        with pinned_target_directory(root, create=True), migration_target_lock(root):
            final, pending = root / migration_id, root / (".pending-" + migration_id)
            if final.exists():
                verify_target(final)
                verify_sources()
                return {"published": True, "reused": True, "files": len(entries),
                        "sourceComplete": manifest["sourceComplete"], "readyForCutover": False}
            with pinned_target_directory(pending, create=True):
                for relative, raw in copies.items():
                    _write_new(pending / relative, raw)
                _write_new(pending / "manifest.json", encoded)
                verify_target(pending)
                verify_sources()
                identity = path_identity(pending)
            publish_directory(pending, final, identity)
            verify_target(final)
            verify_sources()
    return {"published": True, "reused": False, "files": len(entries),
            "manifestSha256": hashlib.sha256(encoded).hexdigest(),
            "sourceComplete": manifest["sourceComplete"], "readyForCutover": False}
