"""Copy-and-verify migration from legacy checkout storage to project state."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from vibelution_storage import (
    STORAGE_MIGRATION_SCHEMA_VERSION,
    ProjectStoragePaths,
    legacy_project_storage_paths,
    project_memory_migration_state_path,
    resolve_project_memory_home,
    resolve_project_storage_paths,
    storage_migration_state_path,
)

CACHE_POLICY_COLD_REBUILD = "cold_rebuild"
SQLITE_BUNDLE_CHANGED_DURING_COPY = "sqlite_bundle_changed_during_copy"
SQLITE_BUNDLE_DESTINATION_CONFLICT = "sqlite_bundle_destination_conflict"
_ACTIVE_CLAIM_STATUSES = frozenset({"active", "claimed", "in_progress", "running"})
_SQLITE_MAIN_SUFFIXES = (".sqlite", ".sqlite3", ".db")
_SQLITE_INTEGRITY_EVIDENCE_BOUND = 240
_DEFAULT_QUIESCENCE_WINDOW_SECONDS = 0.05


class StorageMigrationError(RuntimeError):
    """Raised when copying cannot prove an exact, conflict-free migration."""


@dataclass(frozen=True)
class StorageMigrationEntry:
    source: str
    destination: str
    category: str
    relative_path: str
    size: int
    sha256: str
    bundle_fingerprint: str = ""
    bundle_members: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _PromotedSqliteMember:
    path: str
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class _SqliteBundleMember:
    role: str
    present: bool
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "present": self.present,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class _SqliteBundleSnapshot:
    main_path: Path
    members: tuple[_SqliteBundleMember, ...]

    @classmethod
    def from_main(cls, main: Path) -> "_SqliteBundleSnapshot":
        members: list[_SqliteBundleMember] = []
        for role, path in (
            ("main", main),
            ("wal", main.with_name(main.name + "-wal")),
            ("shm", main.with_name(main.name + "-shm")),
        ):
            path_io = _io_path(path)
            if path_io.is_file():
                members.append(
                    _SqliteBundleMember(
                        role=role,
                        present=True,
                        size=int(path_io.stat().st_size),
                        sha256=_sha256_file(path),
                    )
                )
            else:
                members.append(_SqliteBundleMember(role=role, present=False, size=0, sha256=""))
        return cls(main_path=main, members=tuple(members))

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for member in self.members:
            digest.update(member.role.encode("ascii"))
            digest.update(b"\0")
            digest.update(str(member.present).lower().encode("ascii"))
            digest.update(b"\0")
            digest.update(str(member.size).encode("ascii"))
            digest.update(b"\0")
            digest.update(member.sha256.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def member_dicts(self) -> tuple[dict[str, object], ...]:
        return tuple(member.as_dict() for member in self.members)

    def main_member(self) -> _SqliteBundleMember:
        return self.members[0]


def _bundle_snapshot_for_entry(entry: StorageMigrationEntry) -> _SqliteBundleSnapshot | None:
    destination = Path(entry.destination)
    if entry.bundle_members:
        members: list[_SqliteBundleMember] = []
        for raw in entry.bundle_members:
            if not isinstance(raw, dict):
                continue
            members.append(
                _SqliteBundleMember(
                    role=str(raw.get("role") or ""),
                    present=bool(raw.get("present")),
                    size=int(raw.get("size") or 0),
                    sha256=str(raw.get("sha256") or ""),
                )
            )
        if members:
            return _SqliteBundleSnapshot(main_path=destination, members=tuple(members))
    return None


def _manifest_expected_bundle_snapshot(entry: StorageMigrationEntry) -> _SqliteBundleSnapshot:
    stored = _bundle_snapshot_for_entry(entry)
    if stored is not None:
        return stored
    destination = Path(entry.destination)
    return _SqliteBundleSnapshot(
        main_path=destination,
        members=(
            _SqliteBundleMember(
                role="main",
                present=True,
                size=entry.size,
                sha256=entry.sha256,
            ),
            _SqliteBundleMember(role="wal", present=False, size=0, sha256=""),
            _SqliteBundleMember(role="shm", present=False, size=0, sha256=""),
        ),
    )


def _sqlite_bundle_member_paths(main: Path) -> tuple[Path, Path, Path]:
    return (
        main,
        main.with_name(main.name + "-wal"),
        main.with_name(main.name + "-shm"),
    )


def _sqlite_destination_has_any_member(main: Path) -> bool:
    return any(_io_path(path).is_file() for path in _sqlite_bundle_member_paths(main))


def _sqlite_destination_has_orphan_sidecars(main: Path) -> bool:
    main_io = _io_path(main)
    if main_io.is_file():
        return False
    wal_io = _io_path(main.with_name(main.name + "-wal"))
    shm_io = _io_path(main.with_name(main.name + "-shm"))
    return wal_io.is_file() or shm_io.is_file()


def _expected_destination_bundle_fingerprint(entry: StorageMigrationEntry) -> str:
    if entry.bundle_fingerprint:
        return entry.bundle_fingerprint
    return _SqliteBundleSnapshot.from_main(Path(entry.source)).fingerprint()


def _destination_bundle_fingerprint(entry: StorageMigrationEntry) -> str:
    return _SqliteBundleSnapshot.from_main(Path(entry.destination)).fingerprint()


def _bundle_snapshots_equal(left: _SqliteBundleSnapshot, right: _SqliteBundleSnapshot) -> bool:
    return left.fingerprint() == right.fingerprint()


def _entry_from_source_path(
    *,
    source: Path,
    destination: Path,
    category: str,
    relative_path: str,
) -> StorageMigrationEntry:
    if _is_sqlite_main(source):
        bundle = _SqliteBundleSnapshot.from_main(source)
        main = bundle.main_member()
        return StorageMigrationEntry(
            source=str(source.resolve()),
            destination=str(destination),
            category=category,
            relative_path=relative_path,
            size=main.size,
            sha256=main.sha256,
            bundle_fingerprint=bundle.fingerprint(),
            bundle_members=bundle.member_dicts(),
        )
    return StorageMigrationEntry(
        source=str(source.resolve()),
        destination=str(destination),
        category=category,
        relative_path=relative_path,
        size=_io_path(source).stat().st_size,
        sha256=_sha256_file(source),
    )


@dataclass(frozen=True)
class StorageMigrationPlan:
    project_root: str
    project_id: str
    instance_id: str
    target_root: str
    entries: tuple[StorageMigrationEntry, ...]
    total_files: int
    total_bytes: int
    aggregate_sha256: str
    archived_conflicts: int = 0
    skipped_ephemeral_files: int = 0

    def to_dict(self, *, include_entries: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": STORAGE_MIGRATION_SCHEMA_VERSION,
            "projectRoot": self.project_root,
            "projectId": self.project_id,
            "instanceId": self.instance_id,
            "targetRoot": self.target_root,
            "totalFiles": self.total_files,
            "totalBytes": self.total_bytes,
            "aggregateSha256": self.aggregate_sha256,
            "archivedConflicts": self.archived_conflicts,
            "skippedEphemeralFiles": self.skipped_ephemeral_files,
        }
        if include_entries:
            payload["entries"] = [asdict(entry) for entry in self.entries]
        return payload


def assess_storage_migration_readiness(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    action: str = "apply",
    quiescence_window_seconds: float = _DEFAULT_QUIESCENCE_WINDOW_SECONDS,
) -> dict[str, object]:
    """Fail-closed readiness gate for apply, reapply, and rollback."""

    project = Path(project_root).expanduser().resolve()
    plan = plan_storage_migration(
        project,
        projects_home=projects_home,
        config_path=config_path,
    )
    target = resolve_project_storage_paths(project, projects_home=projects_home)
    active_work = _probe_active_work(project)
    runtime_writers = _probe_runtime_writers(project)
    launcher_state = _probe_launcher_state(project)
    destination_conflicts = _destination_conflicts(plan.entries)
    sqlite_bundles = _discover_sqlite_bundles(plan)
    sqlite_integrity = _verify_sqlite_integrity(sqlite_bundles, phase="source")
    rollback_eligibility = assess_rollback_eligibility(
        project,
        projects_home=projects_home,
    )
    source_signature = {
        "aggregateSha256": plan.aggregate_sha256,
        "totalFiles": plan.total_files,
        "totalBytes": plan.total_bytes,
        "entryCount": len(plan.entries),
    }
    quiescence = _observe_source_quiescence(
        project,
        _plan_signature(plan),
        projects_home=projects_home,
        config_path=config_path,
        window_seconds=quiescence_window_seconds,
    )
    blockers: list[dict[str, object]] = []
    if active_work.get("blocking"):
        blockers.append(
            {
                "code": "active_work_present",
                "claims": active_work.get("claims", [])[:8],
            }
        )
    if runtime_writers.get("uncertain"):
        blockers.append(
            {
                "code": "runtime_writer_state_uncertain",
                "reasonCode": runtime_writers.get("reasonCode", "unknown"),
            }
        )
    elif runtime_writers.get("blocking"):
        blockers.append(
            {
                "code": "runtime_writers_active",
                "writers": runtime_writers.get("writers", [])[:8],
            }
        )
    if launcher_state.get("uncertain"):
        blockers.append(
            {
                "code": "launcher_state_uncertain",
                "reasonCode": launcher_state.get("reasonCode", "unknown"),
            }
        )
    elif launcher_state.get("blocking"):
        blockers.append(
            {
                "code": "launcher_runtime_active",
                "observedState": launcher_state.get("observedState", ""),
            }
        )
    if destination_conflicts:
        blockers.append(
            {
                "code": "destination_conflict",
                "conflicts": destination_conflicts[:8],
            }
        )
    if not sqlite_integrity.get("ok"):
        blockers.append(
            {
                "code": "sqlite_integrity_failed",
                "failures": sqlite_integrity.get("failures", [])[:8],
            }
        )
    if not quiescence.get("ok"):
        blockers.append(
            {
                "code": "source_changed_during_quiescence_window",
                "windowSeconds": quiescence.get("windowSeconds"),
            }
        )
    normalized_action = str(action or "apply").strip().lower()
    if normalized_action == "rollback":
        if not rollback_eligibility.get("eligible"):
            blockers.append(
                {
                    "code": str(rollback_eligibility.get("reasonCode") or "rollback_blocked"),
                    "delta": rollback_eligibility.get("delta"),
                }
            )
    ready = not blockers
    payload: dict[str, object] = {
        "ready": ready,
        "blockers": blockers,
        "activeWork": active_work,
        "runtimeWriters": runtime_writers,
        "launcherState": launcher_state,
        "sourceSignature": source_signature,
        "destinationConflicts": destination_conflicts,
        "sqliteBundles": sqlite_bundles,
        "sqliteIntegrity": sqlite_integrity,
        "quiescence": quiescence,
        "cachePolicy": CACHE_POLICY_COLD_REBUILD,
        "rollbackEligibility": rollback_eligibility,
    }
    if not ready:
        _log_readiness_blocked(project, payload, action=normalized_action)
    return payload


def assess_rollback_eligibility(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    marker_path = storage_migration_state_path(target)
    if not marker_path.exists():
        return {
            "eligible": False,
            "reasonCode": "completion_marker_missing",
            "delta": None,
        }
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "eligible": False,
            "reasonCode": "completion_marker_unreadable",
            "delta": {"error": type(exc).__name__},
        }
    if not isinstance(marker, dict):
        return {
            "eligible": False,
            "reasonCode": "completion_marker_invalid",
            "delta": None,
        }
    delta = assess_post_cutover_delta(target, marker)
    if delta.get("detected"):
        return {
            "eligible": False,
            "reasonCode": "reverse_delta_reconcile_required",
            "delta": delta,
        }
    return {
        "eligible": True,
        "reasonCode": "rollback_allowed",
        "delta": delta,
    }


def assess_post_cutover_delta(
    target: ProjectStoragePaths,
    marker: dict[str, object],
) -> dict[str, object]:
    manifest_path = Path(str(marker.get("manifestPath") or "")).expanduser()
    if not manifest_path.is_file():
        return {
            "detected": True,
            "reasonCode": "manifest_missing",
            "changedCount": 0,
            "extraCount": 0,
        }
    try:
        entries = _read_manifest_entries(manifest_path)
    except StorageMigrationError as exc:
        return {
            "detected": True,
            "reasonCode": "manifest_unreadable",
            "error": str(exc),
        }
    manifest_paths = _manifest_tracked_paths(entries)
    changed: list[str] = []
    for entry in entries:
        if _manifest_entry_bundle_changed(entry):
            changed.append(entry.relative_path)
    extra: list[str] = []
    completed_at = _parse_iso_timestamp(marker.get("completedAt"))
    for root in (target.data, target.runtime, target.logs, target.memory):
        if not root.exists():
            continue
        for path in _iter_persistent_domain_files(root):
            key = os.path.normcase(str(path))
            if key in manifest_paths:
                continue
            relative = _relative_under_root(path, root)
            if _is_ephemeral_source_file(relative):
                continue
            if completed_at is not None:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if modified <= completed_at:
                    continue
            extra.append(relative.as_posix())
    detected = bool(changed or extra)
    return {
        "detected": detected,
        "reasonCode": "reverse_delta_reconcile_required" if detected else "none",
        "changedCount": len(changed),
        "extraCount": len(extra),
        "changedSample": changed[:8],
        "extraSample": extra[:8],
    }


def _require_readiness_for_apply(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    quiescence_window_seconds: float = _DEFAULT_QUIESCENCE_WINDOW_SECONDS,
) -> dict[str, object]:
    readiness = assess_storage_migration_readiness(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        action="apply",
        quiescence_window_seconds=quiescence_window_seconds,
    )
    if readiness.get("ready"):
        return readiness
    blockers = readiness.get("blockers")
    first_code = "readiness_blocked"
    if isinstance(blockers, list) and blockers:
        first = blockers[0]
        if isinstance(first, dict) and first.get("code"):
            first_code = str(first["code"])
    raise StorageMigrationError(f"storage migration readiness blocked: {first_code}")


def plan_storage_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> StorageMigrationPlan:
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    legacy = legacy_project_storage_paths(project_root, target=target, config_path=config_path)
    mappings = (
        ("operator_data", legacy.data, target.data),
        ("project_workspace", target.project_root / "workspace", target.data / "workspace"),
        ("runtime", legacy.runtime, target.runtime),
        ("logs", legacy.logs, target.logs),
        ("legacy_log_info", target.project_root / "log_info", target.logs / "legacy-log_info"),
        ("project_memory", legacy.memory, target.memory),
        ("project_backups", target.project_root / "backups", target.data / "backups" / "legacy-project-root"),
    )
    entries_by_destination: dict[str, StorageMigrationEntry] = {}
    archived_conflicts = 0
    skipped_ephemeral_files = 0
    for category, source_root, destination_root in mappings:
        if _same_path(source_root, destination_root) or not source_root.exists():
            continue
        for source in _iter_source_files(source_root):
            relative = source.relative_to(source_root)
            if _is_ephemeral_source_file(relative):
                skipped_ephemeral_files += 1
                continue
            destination = (destination_root / relative).resolve()
            try:
                entry = _entry_from_source_path(
                    source=source,
                    destination=destination,
                    category=category,
                    relative_path=relative.as_posix(),
                )
            except OSError as exc:
                raise StorageMigrationError(
                    f"cannot read legacy source during migration inventory: {source}"
                ) from exc
            key = os.path.normcase(str(destination))
            existing = entries_by_destination.get(key)
            if existing is not None and (
                existing.size != entry.size
                or existing.sha256 != entry.sha256
                or existing.bundle_fingerprint != entry.bundle_fingerprint
            ):
                if existing.category == "operator_data" and category == "project_workspace":
                    destination = (
                        target.data
                        / "backups"
                        / "storage-source-conflicts"
                        / "project_workspace"
                        / relative
                    ).resolve()
                    entry = _entry_from_source_path(
                        source=source,
                        destination=destination,
                        category="project_workspace_conflict_archive",
                        relative_path=entry.relative_path,
                    )
                    key = os.path.normcase(str(destination))
                    if key in entries_by_destination:
                        raise StorageMigrationError(
                            "legacy conflict archive destination is not unique: "
                            f"{entry.source} -> {entry.destination}"
                        )
                    archived_conflicts += 1
                else:
                    raise StorageMigrationError(
                        "legacy sources map different content to the same destination: "
                        f"{existing.source} and {entry.source} -> {entry.destination}"
                    )
            entries_by_destination.setdefault(key, entry)
    entries = tuple(sorted(entries_by_destination.values(), key=lambda item: item.destination.lower()))
    return StorageMigrationPlan(
        project_root=str(target.project_root),
        project_id=target.project_id,
        instance_id=target.instance_id,
        target_root=str(target.instance_home),
        entries=entries,
        total_files=len(entries),
        total_bytes=sum(entry.size for entry in entries),
        aggregate_sha256=_aggregate_digest(entries),
        archived_conflicts=archived_conflicts,
        skipped_ephemeral_files=skipped_ephemeral_files,
    )


def apply_storage_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    quiescence_window_seconds: float = _DEFAULT_QUIESCENCE_WINDOW_SECONDS,
) -> dict[str, object]:
    """Copy, verify, then atomically activate external storage.

    No legacy file is modified or deleted. A conflict or changing source leaves
    the completion marker absent, so all current readers stay on legacy paths.
    """

    _require_readiness_for_apply(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        quiescence_window_seconds=quiescence_window_seconds,
    )
    plan = plan_storage_migration(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
    )
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    _assert_destinations_within_target(plan.entries, target)
    memory_entries = tuple(entry for entry in plan.entries if entry.category == "project_memory")
    instance_entries = tuple(entry for entry in plan.entries if entry.category != "project_memory")
    conflicts = _destination_conflicts(instance_entries)
    if conflicts:
        raise StorageMigrationError("destination conflicts: " + "; ".join(conflicts[:8]))

    copied, reused = _copy_and_verify_entries(instance_entries)
    with _project_memory_marker_lock(target):
        memory_conflicts = _destination_conflicts(memory_entries)
        if memory_conflicts:
            raise StorageMigrationError("destination conflicts: " + "; ".join(memory_conflicts[:8]))
        memory_copied, memory_reused = _copy_and_verify_entries(memory_entries)
        copied += memory_copied
        reused += memory_reused
        refreshed = plan_storage_migration(
            project_root,
            projects_home=projects_home,
            config_path=config_path,
        )
        if _plan_signature(refreshed) != _plan_signature(plan):
            raise StorageMigrationError("legacy sources changed during migration; completion marker not written")
        completed_at = _now_iso()
        _register_project_memory_source(
            target,
            source_root=legacy_project_storage_paths(target.project_root, target=target).memory,
            memory_entries=memory_entries,
            completed_at=completed_at,
        )

    migrations_dir = target.instance_home / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = migrations_dir / f"manifest-{completed_at.replace(':', '').replace('-', '')}.jsonl"
    _write_manifest(manifest_path, plan.entries)
    marker = {
        "schemaVersion": STORAGE_MIGRATION_SCHEMA_VERSION,
        "status": "completed",
        "projectId": target.project_id,
        "instanceId": target.instance_id,
        "projectRoot": str(target.project_root),
        "targetRoot": str(target.instance_home),
        "completedAt": completed_at,
        "totalFiles": plan.total_files,
        "totalBytes": plan.total_bytes,
        "aggregateSha256": plan.aggregate_sha256,
        "archivedConflicts": plan.archived_conflicts,
        "skippedEphemeralFiles": plan.skipped_ephemeral_files,
        "manifestPath": str(manifest_path),
        "legacyDeleteAllowed": False,
        "cachePolicy": CACHE_POLICY_COLD_REBUILD,
    }
    _atomic_write_json(storage_migration_state_path(target), marker)
    return {**marker, "copiedFiles": copied, "reusedFiles": reused}


def rollback_storage_switch(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Deactivate the switch by archiving its marker; copied data is retained."""

    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    marker_path = storage_migration_state_path(target)
    memory_marker_path = project_memory_migration_state_path(target)
    if not marker_path.exists():
        return {"rolledBack": False, "reason": "completion_marker_missing", "markerPath": str(marker_path)}

    eligibility = assess_rollback_eligibility(project_root, projects_home=projects_home)
    if not eligibility.get("eligible"):
        reason = str(eligibility.get("reasonCode") or "rollback_blocked")
        raise StorageMigrationError(f"storage migration rollback blocked: {reason}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = marker_path.with_name(f"storage-migration.rolled-back-{stamp}.json")
    archived_memory_marker: Path | None = None
    registration_removed = False
    remaining_memory_sources = 0
    source_root = legacy_project_storage_paths(target.project_root, target=target).memory
    with _project_memory_marker_lock(target):
        memory_marker = _load_project_memory_marker(target, required=False)
        os.replace(marker_path, archived)
        if memory_marker:
            sources = list(memory_marker["sources"])
            retained = [
                item
                for item in sources
                if not _same_path(Path(str(item["sourceRoot"])), source_root)
            ]
            registration_removed = len(retained) != len(sources)
            remaining_memory_sources = len(retained)
            if registration_removed and retained:
                memory_marker["sources"] = retained
                memory_marker["sourceCount"] = len(retained)
                memory_marker["updatedAt"] = _now_iso()
                _atomic_write_json(memory_marker_path, memory_marker)
            elif registration_removed:
                archived_memory_marker = memory_marker_path.with_name(
                    f"project-memory-migration.rolled-back-{stamp}.json"
                )
                os.replace(memory_marker_path, archived_memory_marker)
    return {
        "rolledBack": True,
        "markerPath": str(marker_path),
        "archivedMarkerPath": str(archived),
        "archivedProjectMemoryMarkerPath": (
            str(archived_memory_marker) if archived_memory_marker is not None else None
        ),
        "projectMemoryRegistrationRemoved": registration_removed,
        "remainingProjectMemorySources": remaining_memory_sources,
        "copiedDataRetained": True,
    }


def _copy_and_verify_entries(entries: Iterable[StorageMigrationEntry]) -> tuple[int, int]:
    copied = 0
    reused = 0
    for entry in entries:
        source = Path(entry.source)
        if _is_sqlite_main(source):
            entry_copied, entry_reused = _copy_sqlite_bundle_entry(entry)
            copied += entry_copied
            reused += entry_reused
            continue
        destination = Path(entry.destination)
        destination_io = _io_path(destination)
        destination_io.parent.mkdir(parents=True, exist_ok=True)
        if destination_io.exists():
            reused += 1
        else:
            try:
                shutil.copy2(_io_path(source), destination_io)
            except OSError as exc:
                raise StorageMigrationError(
                    "failed to copy legacy source during storage migration: "
                    f"{source} -> {destination}"
                ) from exc
            copied += 1
        _verify_entry(entry)
    return copied, reused


def _copy_sqlite_bundle_entry(entry: StorageMigrationEntry) -> tuple[int, int]:
    source = Path(entry.source)
    destination = Path(entry.destination)
    destination_io = _io_path(destination)
    destination_io.parent.mkdir(parents=True, exist_ok=True)
    expected_fingerprint = _expected_destination_bundle_fingerprint(entry)
    source_before = _SqliteBundleSnapshot.from_main(source)
    if source_before.fingerprint() != expected_fingerprint:
        raise StorageMigrationError(
            f"legacy source changed during copy: {source} ({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
        )
    ok, detail = _sqlite_full_integrity(source)
    if not ok:
        raise StorageMigrationError(f"sqlite integrity check failed before copy: {source} ({detail})")

    if destination_io.exists():
        destination_bundle = _SqliteBundleSnapshot.from_main(destination)
        if destination_bundle.fingerprint() == expected_fingerprint:
            _verify_sqlite_bundle_entry(entry, source_before, destination_bundle)
            ok, detail = _sqlite_full_integrity(destination)
            if not ok:
                raise StorageMigrationError(
                    f"sqlite integrity check failed after reuse: {destination} ({detail})"
                )
            return 0, 1
        raise StorageMigrationError(
            f"destination conflicts with sqlite bundle: {destination} "
            f"({SQLITE_BUNDLE_DESTINATION_CONFLICT})"
        )

    if _sqlite_destination_has_orphan_sidecars(destination):
        raise StorageMigrationError(
            f"destination has orphan sqlite sidecars: {destination} "
            f"({SQLITE_BUNDLE_DESTINATION_CONFLICT})"
        )

    staging_dir = destination.parent / f".migration-staging-{os.getpid()}-{time.time_ns()}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    staging_main = staging_dir / destination.name
    promoted_members: tuple[_PromotedSqliteMember, ...] = ()
    try:
        for bundle_source in _sqlite_bundle_paths(source):
            bundle_source_io = _io_path(bundle_source)
            if not bundle_source_io.is_file():
                continue
            try:
                shutil.copy2(bundle_source_io, staging_dir / bundle_source.name)
            except OSError as exc:
                raise StorageMigrationError(
                    "failed to copy legacy sqlite bundle during storage migration: "
                    f"{source} -> {destination}"
                ) from exc
        staging_bundle = _SqliteBundleSnapshot.from_main(staging_main)
        if staging_bundle.fingerprint() != source_before.fingerprint():
            raise StorageMigrationError(
                f"sqlite bundle changed during staging copy: {source} "
                f"({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
            )
        source_after = _SqliteBundleSnapshot.from_main(source)
        if source_after.fingerprint() != source_before.fingerprint():
            raise StorageMigrationError(
                f"legacy sqlite bundle changed during copy: {source} "
                f"({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
            )
        ok, detail = _sqlite_full_integrity(staging_main)
        if not ok:
            raise StorageMigrationError(
                f"sqlite integrity check failed on staged bundle: {staging_main} ({detail})"
            )
        promoted_members = _promote_sqlite_bundle(staging_dir, destination)
        destination_bundle = _SqliteBundleSnapshot.from_main(destination)
        if destination_bundle.fingerprint() != expected_fingerprint:
            _cleanup_attempt_sqlite_members(promoted_members)
            raise StorageMigrationError(
                f"destination sqlite bundle verification failed: {destination} "
                f"({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
            )
        _verify_sqlite_bundle_entry(entry, source_after, destination_bundle)
        ok, detail = _sqlite_full_integrity(destination)
        if not ok:
            _cleanup_attempt_sqlite_members(promoted_members)
            raise StorageMigrationError(
                f"sqlite integrity check failed after copy: {destination} ({detail})"
            )
        return 1, 0
    except Exception:
        _cleanup_attempt_sqlite_members(promoted_members)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _promote_sqlite_bundle(
    staging_dir: Path,
    destination: Path,
) -> tuple[_PromotedSqliteMember, ...]:
    promoted: list[_PromotedSqliteMember] = []
    try:
        for bundle_path in _sqlite_bundle_paths(staging_dir / destination.name):
            staged = staging_dir / bundle_path.name
            staged_io = _io_path(staged)
            if not staged_io.is_file():
                continue
            final_path = destination.parent / bundle_path.name
            final_io = _io_path(final_path)
            promoted.append(_atomic_promote_staged_member(staged_io, final_io))
        return tuple(promoted)
    except Exception:
        _cleanup_attempt_sqlite_members(promoted)
        raise


def _atomic_promote_staged_member(staged_io: Path, final_io: Path) -> _PromotedSqliteMember:
    final_io.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(staged_io, final_io)
    except FileExistsError as exc:
        raise _sqlite_destination_member_conflict(final_io) from exc
    except OSError as exc:
        if exc.errno in (errno.EEXIST, getattr(errno, "EALREADY", None)):
            raise _sqlite_destination_member_conflict(final_io) from exc
        raise StorageMigrationError(
            f"failed to promote staged sqlite bundle member: {final_io}"
        ) from exc
    try:
        staged_io.unlink()
    except OSError as exc:
        _rollback_linked_promotion(staged_io, final_io)
        raise StorageMigrationError(
            f"failed to finalize staged sqlite bundle member: {final_io}"
        ) from exc
    stat = final_io.stat()
    return _PromotedSqliteMember(
        path=str(final_io.resolve()),
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
        size=int(stat.st_size),
        sha256=_sha256_file(final_io),
    )


def _sqlite_destination_member_conflict(final_io: Path) -> StorageMigrationError:
    return StorageMigrationError(
        f"destination sqlite bundle member already exists: {final_io} "
        f"({SQLITE_BUNDLE_DESTINATION_CONFLICT})"
    )


def _rollback_linked_promotion(staged_io: Path, final_io: Path) -> None:
    try:
        if final_io.exists() and staged_io.exists():
            final_stat = final_io.stat()
            staged_stat = staged_io.stat()
            if final_stat.st_dev == staged_stat.st_dev and final_stat.st_ino == staged_stat.st_ino:
                final_io.unlink()
                return
        if final_io.exists():
            final_io.unlink()
    except OSError:
        return


def _cleanup_attempt_sqlite_members(members: Iterable[_PromotedSqliteMember]) -> None:
    for member in members:
        member_io = _io_path(Path(member.path))
        if not member_io.is_file():
            continue
        try:
            stat = member_io.stat()
        except OSError:
            continue
        if int(stat.st_dev) != member.device or int(stat.st_ino) != member.inode:
            continue
        if int(stat.st_size) != member.size:
            continue
        if _sha256_file(member_io) != member.sha256:
            continue
        member_io.unlink(missing_ok=True)


def _verify_sqlite_bundle_entry(
    entry: StorageMigrationEntry,
    source_bundle: _SqliteBundleSnapshot,
    destination_bundle: _SqliteBundleSnapshot,
) -> None:
    expected_fingerprint = _expected_destination_bundle_fingerprint(entry)
    if source_bundle.fingerprint() != expected_fingerprint:
        raise StorageMigrationError(
            f"legacy source changed during copy: {entry.source} ({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
        )
    if destination_bundle.fingerprint() != expected_fingerprint:
        raise StorageMigrationError(
            f"destination verification failed: {entry.destination} "
            f"({SQLITE_BUNDLE_CHANGED_DURING_COPY})"
        )


def _register_project_memory_source(
    target: ProjectStoragePaths,
    *,
    source_root: Path,
    memory_entries: tuple[StorageMigrationEntry, ...],
    completed_at: str,
) -> None:
    marker = _load_project_memory_marker(target, required=False)
    existing_sources = list(marker.get("sources") or []) if marker else []
    retained = [
        item
        for item in existing_sources
        if not _same_path(Path(str(item["sourceRoot"])), source_root)
    ]
    retained.append(
        {
            "sourceRoot": str(source_root.resolve()),
            "projectRoot": str(target.project_root),
            "activatedByInstanceId": target.instance_id,
            "completedAt": completed_at,
            "totalFiles": len(memory_entries),
            "totalBytes": sum(entry.size for entry in memory_entries),
            "aggregateSha256": _aggregate_digest(memory_entries),
        }
    )
    retained.sort(key=lambda item: os.path.normcase(str(item["sourceRoot"])))
    payload = {
        "schemaVersion": STORAGE_MIGRATION_SCHEMA_VERSION,
        "status": "completed",
        "projectId": target.project_id,
        "targetRoot": str(target.memory),
        "sources": retained,
        "sourceCount": len(retained),
        "updatedAt": completed_at,
        "legacyDeleteAllowed": False,
    }
    _atomic_write_json(project_memory_migration_state_path(target), payload)


def _load_project_memory_marker(
    target: ProjectStoragePaths,
    *,
    required: bool,
) -> dict[str, object]:
    marker_path = project_memory_migration_state_path(target)
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise StorageMigrationError(f"project memory marker is missing: {marker_path}")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageMigrationError(f"invalid project memory marker: {marker_path}") from exc
    sources = payload.get("sources") if isinstance(payload, dict) else None
    valid_sources = bool(
        isinstance(sources, list)
        and all(
            isinstance(item, dict) and str(item.get("sourceRoot") or "").strip()
            for item in sources
        )
    )
    if not (
        isinstance(payload, dict)
        and payload.get("schemaVersion") == STORAGE_MIGRATION_SCHEMA_VERSION
        and payload.get("status") == "completed"
        and str(payload.get("projectId") or "") == target.project_id
        and _same_path(Path(str(payload.get("targetRoot") or "")), target.memory)
        and valid_sources
    ):
        raise StorageMigrationError(f"project memory marker does not match target: {marker_path}")
    return payload


@contextmanager
def _project_memory_marker_lock(target: ProjectStoragePaths, *, timeout_seconds: float = 10.0):
    lock_path = target.project_home / "project-memory-migration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while not _try_lock_handle(handle):
            if time.monotonic() >= deadline:
                raise StorageMigrationError(f"timed out acquiring project memory marker lock: {lock_path}")
            time.sleep(0.01)
        try:
            yield
        finally:
            _unlock_handle(handle)


def _try_lock_handle(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _iter_persistent_domain_files(root: Path) -> Iterable[Path]:
    root = root.resolve()
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory_name in list(directory_names):
            candidate = current_path / directory_name
            if candidate.is_symlink():
                raise StorageMigrationError(f"symlinked directory is not migrated: {candidate}")
        for file_name in file_names:
            candidate = current_path / file_name
            if candidate.is_symlink():
                raise StorageMigrationError(f"symlinked file is not migrated: {candidate}")
            if candidate.is_file():
                yield candidate.resolve()


def _manifest_tracked_paths(entries: Iterable[StorageMigrationEntry]) -> set[str]:
    tracked: set[str] = set()
    for entry in entries:
        destination = Path(entry.destination)
        tracked.add(os.path.normcase(str(destination.resolve())))
        if _is_sqlite_main(destination) or entry.bundle_members or entry.bundle_fingerprint:
            for member in _manifest_bundle_member_paths(destination, entry):
                tracked.add(os.path.normcase(str(member.resolve())))
    return tracked


def _manifest_bundle_member_paths(
    destination: Path,
    entry: StorageMigrationEntry,
) -> tuple[Path, ...]:
    if entry.bundle_members:
        paths: list[Path] = [destination]
        for raw in entry.bundle_members:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "")
            if role == "wal":
                paths.append(destination.with_name(destination.name + "-wal"))
            elif role == "shm":
                paths.append(destination.with_name(destination.name + "-shm"))
        return tuple(dict.fromkeys(paths))
    return _sqlite_bundle_paths(destination)


def _manifest_entry_bundle_changed(entry: StorageMigrationEntry) -> bool:
    destination = Path(entry.destination)
    if _is_sqlite_main(destination) or entry.bundle_fingerprint or entry.bundle_members:
        expected = _manifest_expected_bundle_snapshot(entry)
        actual = _SqliteBundleSnapshot.from_main(destination)
        return not _bundle_snapshots_equal(expected, actual)
    destination_io = _io_path(destination)
    if not destination_io.is_file():
        return True
    return destination_io.stat().st_size != entry.size or _sha256_file(destination) != entry.sha256


def _iter_source_files(root: Path) -> Iterable[Path]:
    root = root.resolve()
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory_name in list(directory_names):
            candidate = current_path / directory_name
            if candidate.is_symlink():
                raise StorageMigrationError(f"symlinked directory is not migrated: {candidate}")
        for file_name in file_names:
            candidate = current_path / file_name
            if candidate.is_symlink():
                raise StorageMigrationError(f"symlinked file is not migrated: {candidate}")
            if _is_sqlite_sidecar(candidate):
                continue
            if candidate.is_file():
                yield candidate.resolve()


def _is_ephemeral_source_file(relative_path: Path) -> bool:
    return relative_path.name.lower().endswith(".lock")


def _destination_conflicts(entries: Iterable[StorageMigrationEntry]) -> list[str]:
    conflicts: list[str] = []
    for entry in entries:
        destination = Path(entry.destination)
        destination_io = _io_path(destination)
        if _is_sqlite_main(Path(entry.source)) or entry.bundle_fingerprint:
            if _sqlite_destination_has_orphan_sidecars(destination):
                conflicts.append(
                    f"orphan sqlite sidecar: {destination} ({SQLITE_BUNDLE_DESTINATION_CONFLICT})"
                )
                continue
            if not _sqlite_destination_has_any_member(destination):
                continue
            expected = _expected_destination_bundle_fingerprint(entry)
            actual = _destination_bundle_fingerprint(entry)
            if actual != expected:
                conflicts.append(
                    f"different sqlite bundle: {destination} ({SQLITE_BUNDLE_DESTINATION_CONFLICT})"
                )
            continue
        if not destination_io.exists():
            continue
        if not destination_io.is_file():
            conflicts.append(f"not a file: {destination}")
            continue
        if destination_io.stat().st_size != entry.size or _sha256_file(destination) != entry.sha256:
            conflicts.append(f"different content: {destination}")
    return conflicts


def _verify_entry(entry: StorageMigrationEntry) -> None:
    source = Path(entry.source)
    destination = Path(entry.destination)
    source_io = _io_path(source)
    destination_io = _io_path(destination)
    if not source_io.is_file() or not destination_io.is_file():
        raise StorageMigrationError(f"migration file disappeared: {entry.relative_path}")
    if _is_sqlite_main(source) or entry.bundle_fingerprint:
        source_bundle = _SqliteBundleSnapshot.from_main(source)
        destination_bundle = _SqliteBundleSnapshot.from_main(destination)
        _verify_sqlite_bundle_entry(entry, source_bundle, destination_bundle)
        return
    if source_io.stat().st_size != entry.size or _sha256_file(source) != entry.sha256:
        raise StorageMigrationError(f"legacy source changed during copy: {source}")
    if destination_io.stat().st_size != entry.size or _sha256_file(destination) != entry.sha256:
        raise StorageMigrationError(f"destination verification failed: {destination}")


def _assert_destinations_within_target(
    entries: Iterable[StorageMigrationEntry],
    target: ProjectStoragePaths,
) -> None:
    allowed_roots = tuple(
        path.resolve() for path in (target.data, target.runtime, target.logs, target.memory, target.cache)
    )
    for entry in entries:
        destination = Path(entry.destination).resolve()
        if not any(destination == root or destination.is_relative_to(root) for root in allowed_roots):
            raise StorageMigrationError(f"destination escapes project state root: {destination}")


def _write_manifest(path: Path, entries: Iterable[StorageMigrationEntry]) -> None:
    rows = [json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True) for entry in entries]
    _atomic_write_text(path, "\n".join(rows) + ("\n" if rows else ""))


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _io_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _io_path(path: Path) -> Path:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved
    text = str(resolved)
    if text.startswith("\\\\?\\"):
        return resolved
    if text.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{text[2:]}")
    return Path(f"\\\\?\\{text}")


def _aggregate_digest(entries: Iterable[StorageMigrationEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.destination.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.bundle_fingerprint.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _plan_signature(plan: StorageMigrationPlan) -> tuple[tuple[str, str, int, str, str], ...]:
    return tuple(
        (entry.source, entry.destination, entry.size, entry.sha256, entry.bundle_fingerprint)
        for entry in plan.entries
    )


def _quiescence_sleep(seconds: float) -> None:
    time.sleep(max(0.0, seconds))


def _observe_source_quiescence(
    project_root: Path,
    before_signature: tuple[tuple[str, str, int, str, str], ...],
    *,
    projects_home: str | os.PathLike[str] | None,
    config_path: str | os.PathLike[str] | None,
    window_seconds: float,
) -> dict[str, object]:
    """Machine-verifiable source quiescence decision across the readiness window.

    A source write or state change anywhere in the legacy tree is detected by
    comparing the pre-window and post-window plan signatures, so the decision
    never depends on wall-clock performance assertions.
    """
    window = max(0.0, window_seconds)
    if window <= 0.0:
        return {
            "ok": True,
            "stable": True,
            "reasonCode": "quiescence_window_disabled",
            "windowSeconds": 0.0,
            "sampleCount": 1,
        }
    _quiescence_sleep(window)
    after = plan_storage_migration(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
    )
    stable = before_signature == _plan_signature(after)
    return {
        "ok": stable,
        "stable": stable,
        "reasonCode": "source_changed_during_quiescence_window" if not stable else "none",
        "windowSeconds": window,
        "sampleCount": 2,
    }


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _relative_under_root(path: Path, root: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _coordination_registry_paths(project_root: Path) -> list[Path]:
    paths = [resolve_project_memory_home(project_root) / "agent-registry.json"]
    try:
        from core.infrastructure.branch_workspace import resolve_branch_workspace

        layout = resolve_branch_workspace(project_root)
        paths.append(layout.git_common_dir / "briefbound" / "coordination" / "registry.json")
    except Exception:
        pass
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_active_claims(project_root: Path) -> tuple[list[dict[str, str]], bool]:
    claims: list[dict[str, str]] = []
    uncertain = False
    for registry_path in _coordination_registry_paths(project_root):
        if not registry_path.exists():
            continue
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            uncertain = True
            continue
        raw_claims = payload.get("workClaims") or payload.get("claims") or {}
        if not isinstance(raw_claims, dict):
            uncertain = True
            continue
        for claim_id, raw in raw_claims.items():
            if not isinstance(raw, dict):
                continue
            status = str(raw.get("status") or "").strip().lower()
            if status not in _ACTIVE_CLAIM_STATUSES:
                continue
            claims.append(
                {
                    "claimId": str(claim_id),
                    "status": status,
                    "branch": str(raw.get("branch") or ""),
                }
            )
    return claims, uncertain


def _probe_active_work(project_root: Path) -> dict[str, object]:
    claims, uncertain = _load_active_claims(project_root)
    if uncertain:
        return {
            "blocking": True,
            "uncertain": True,
            "reasonCode": "active_work_registry_unreadable",
            "claims": claims[:8],
        }
    return {
        "blocking": bool(claims),
        "uncertain": False,
        "reasonCode": "active_work_present" if claims else "none",
        "claims": claims[:8],
        "claimCount": len(claims),
    }


def _probe_launcher_state(project_root: Path) -> dict[str, object]:
    try:
        from core.infrastructure.branch_workspace import _runtime_observation

        observation = _runtime_observation(project_root)
    except Exception:
        return {
            "blocking": False,
            "uncertain": True,
            "reasonCode": "launcher_observation_failed",
        }
    observed_state = str(observation.get("observedState") or "")
    alive = bool(observation.get("alive"))
    return {
        "blocking": alive,
        "uncertain": False,
        "reasonCode": "launcher_runtime_active" if alive else "idle",
        "observedState": observed_state,
        "alive": alive,
        "port": observation.get("port"),
    }


def _probe_runtime_writers(project_root: Path) -> dict[str, object]:
    writers: list[dict[str, object]] = []
    try:
        runtime_root = resolve_project_storage_paths(project_root).runtime
    except Exception:
        return {
            "blocking": False,
            "uncertain": True,
            "reasonCode": "runtime_root_unresolved",
            "writers": [],
        }
    manager_state_path = runtime_root / "runtime-manager" / "state.json"
    manager_state = _read_json_object(manager_state_path)
    if manager_state_path.exists() and manager_state is None:
        return {
            "blocking": False,
            "uncertain": True,
            "reasonCode": "runtime_manager_state_unreadable",
            "writers": [],
        }
    manager_pid = _positive_int(manager_state.get("managerPid") if manager_state else 0)
    if manager_pid and _pid_is_alive(manager_pid):
        writers.append({"kind": "runtime_manager", "pid": manager_pid})
    daemon_lock = runtime_root / "runtime-manager" / "daemon.lock"
    if daemon_lock.exists():
        writers.append({"kind": "runtime_manager_lock", "path": "runtime-manager/daemon.lock"})
    try:
        from core.runtime_manager.work_run_store import (
            WorkRunStore,
            active_work_payload_blocks_lifecycle,
        )

        store = WorkRunStore(root=runtime_root / "runtime-manager" / "work_runs")
        if store.root.exists():
            for kind_dir in store.root.iterdir():
                if not kind_dir.is_dir():
                    continue
                for snapshot in store.list_lifecycle_candidate_snapshots(kind_dir.name):
                    if active_work_payload_blocks_lifecycle(snapshot):
                        writers.append(
                            {
                                "kind": "work_run",
                                "runKind": kind_dir.name,
                                "runId": str(snapshot.get("runId") or ""),
                                "status": str(snapshot.get("status") or ""),
                            }
                        )
    except Exception:
        return {
            "blocking": False,
            "uncertain": True,
            "reasonCode": "work_run_store_unreadable",
            "writers": writers[:8],
        }
    return {
        "blocking": bool(writers),
        "uncertain": False,
        "reasonCode": "runtime_writers_active" if writers else "none",
        "writers": writers[:8],
        "writerCount": len(writers),
    }


def _discover_sqlite_bundles(plan: StorageMigrationPlan) -> list[dict[str, object]]:
    bundles: list[dict[str, object]] = []
    for entry in plan.entries:
        source = Path(entry.source)
        if not _is_sqlite_main(source):
            continue
        bundle_paths = _sqlite_bundle_paths(source)
        bundles.append(
            {
                "mainPath": entry.relative_path,
                "mainSource": entry.source,
                "members": [
                    {
                        "name": path.name,
                        "present": _io_path(path).is_file(),
                        "size": path.stat().st_size if path.is_file() else 0,
                    }
                    for path in bundle_paths
                ],
            }
        )
    return bundles


def _verify_sqlite_integrity(
    bundles: list[dict[str, object]],
    *,
    phase: str,
) -> dict[str, object]:
    failures: list[dict[str, str]] = []
    checks: list[dict[str, object]] = []
    for bundle in bundles:
        main_source = Path(str(bundle.get("mainSource") or ""))
        main_path = str(bundle.get("mainPath") or "")
        if not main_source.is_file():
            failures.append(
                {
                    "path": main_path,
                    "phase": phase,
                    "detail": "missing_main",
                }
            )
            continue
        integrity = _sqlite_bundle_integrity_check(main_source)
        quick_ok = bool(integrity["quickOk"])
        quick_detail = str(integrity["quickDetail"])
        checks.append(
            {
                "path": main_path,
                "pragma": "quick_check",
                "ok": quick_ok,
                "detail": quick_detail,
            }
        )
        integrity_ok = bool(integrity["integrityOk"])
        integrity_detail = str(integrity["integrityDetail"])
        checks.append(
            {
                "path": main_path,
                "pragma": "integrity_check",
                "ok": integrity_ok,
                "detail": integrity_detail,
            }
        )
        bundle_stable = bool(integrity["bundleStable"])
        checks.append(
            {
                "path": main_path,
                "pragma": "bundle_stable",
                "ok": bundle_stable,
                "detail": "ok" if bundle_stable else "bundle_changed_during_check",
            }
        )
        if not quick_ok:
            failures.append(
                {
                    "path": main_path,
                    "phase": phase,
                    "detail": f"quick_check: {quick_detail}",
                }
            )
        if not integrity_ok:
            failures.append(
                {
                    "path": main_path,
                    "phase": phase,
                    "detail": f"integrity_check: {integrity_detail}",
                }
            )
        if not bundle_stable:
            failures.append(
                {
                    "path": main_path,
                    "phase": phase,
                    "detail": "bundle_changed_during_check",
                }
            )
    return {"ok": not failures, "phase": phase, "checks": checks, "failures": failures}


def _read_manifest_entries(path: Path) -> tuple[StorageMigrationEntry, ...]:
    entries: list[StorageMigrationEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise StorageMigrationError(f"invalid manifest row: {path}")
        entries.append(
            StorageMigrationEntry(
                source=str(raw.get("source") or ""),
                destination=str(raw.get("destination") or ""),
                category=str(raw.get("category") or ""),
                relative_path=str(raw.get("relative_path") or ""),
                size=int(raw.get("size") or 0),
                sha256=str(raw.get("sha256") or ""),
                bundle_fingerprint=str(raw.get("bundle_fingerprint") or ""),
                bundle_members=tuple(
                    item for item in (raw.get("bundle_members") or []) if isinstance(item, dict)
                ),
            )
        )
    return tuple(entries)


def _log_readiness_blocked(
    project_root: Path,
    payload: dict[str, object],
    *,
    action: str,
) -> None:
    blockers = payload.get("blockers")
    codes: list[str] = []
    if isinstance(blockers, list):
        for item in blockers:
            if isinstance(item, dict) and item.get("code"):
                codes.append(str(item["code"]))
    project_id = ""
    try:
        target = resolve_project_storage_paths(project_root)
        project_id = target.project_id
    except Exception:
        project_id = ""
    try:
        from core.runtime_manager.scene_logging import append_runtime_manager_file_event

        append_runtime_manager_file_event(
            "storage_migration.readiness_blocked",
            {
                "action": action,
                "reasonCodes": codes[:8],
                "blockerCount": len(codes),
                "projectId": project_id,
            },
            suppress_io_errors=True,
        )
    except Exception:
        return


def _is_sqlite_sidecar(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith("-wal") or name.endswith("-shm")


def _is_sqlite_main(path: Path) -> bool:
    if _is_sqlite_sidecar(path):
        return False
    lowered = path.name.lower()
    return lowered.endswith(_SQLITE_MAIN_SUFFIXES)


def _sqlite_bundle_paths(main: Path) -> tuple[Path, ...]:
    return (
        main,
        main.with_name(main.name + "-wal"),
        main.with_name(main.name + "-shm"),
    )


def _sqlite_quick_check(path: Path) -> tuple[bool, str]:
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=1.0,
        )
    except sqlite3.Error as exc:
        return False, str(exc)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
        detail = str(row[0]) if row else ""
        return detail.lower() == "ok", detail
    except sqlite3.Error as exc:
        return False, str(exc)
    finally:
        connection.close()


def _bounded_sqlite_detail(rows: Iterable[str]) -> str:
    preview = " | ".join(
        str(row).strip() for row in tuple(rows)[:5] if str(row).strip()
    )
    return preview[:_SQLITE_INTEGRITY_EVIDENCE_BOUND] or "sqlite_check_failed"


def _sqlite_integrity_check(path: Path) -> tuple[bool, str]:
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=1.0,
        )
    except sqlite3.Error as exc:
        return False, _bounded_sqlite_detail((str(exc),))
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        return False, _bounded_sqlite_detail((str(exc),))
    finally:
        connection.close()
    if rows and str(rows[0][0]).strip().lower() == "ok":
        return True, "ok"
    return False, _bounded_sqlite_detail(tuple(str(row[0]) for row in rows))


def _sqlite_bundle_integrity_check(path: Path) -> dict[str, object]:
    """Run SQLite checks on a private bundle snapshot without touching the source."""

    source_before = _SqliteBundleSnapshot.from_main(path)
    if not source_before.main_member().present:
        return {
            "quickOk": False,
            "quickDetail": "missing_main",
            "integrityOk": False,
            "integrityDetail": "missing_main",
            "bundleStable": False,
        }
    quick_ok = False
    quick_detail = "snapshot_not_checked"
    integrity_ok = False
    integrity_detail = "snapshot_not_checked"
    snapshot_matches = False
    try:
        with tempfile.TemporaryDirectory(prefix="vibelution-sqlite-integrity-") as temp_dir:
            snapshot_main = Path(temp_dir) / path.name
            for source_member in _sqlite_bundle_paths(path):
                source_member_io = _io_path(source_member)
                if source_member_io.is_file():
                    shutil.copy2(source_member_io, snapshot_main.parent / source_member.name)
            source_after_copy = _SqliteBundleSnapshot.from_main(path)
            snapshot = _SqliteBundleSnapshot.from_main(snapshot_main)
            snapshot_matches = _bundle_snapshots_equal(source_before, source_after_copy) and (
                _bundle_snapshots_equal(source_before, snapshot)
            )
            if snapshot_matches:
                quick_ok, quick_detail = _sqlite_quick_check(snapshot_main)
                integrity_ok, integrity_detail = _sqlite_integrity_check(snapshot_main)
    except OSError as exc:
        detail = _bounded_sqlite_detail((str(exc),))
        quick_detail = detail
        integrity_detail = detail
    source_after = _SqliteBundleSnapshot.from_main(path)
    bundle_stable = snapshot_matches and _bundle_snapshots_equal(source_before, source_after)
    if not bundle_stable and quick_detail == "snapshot_not_checked":
        quick_detail = "bundle_changed_during_snapshot"
        integrity_detail = "bundle_changed_during_snapshot"
    return {
        "quickOk": quick_ok,
        "quickDetail": quick_detail,
        "integrityOk": integrity_ok,
        "integrityDetail": integrity_detail,
        "bundleStable": bundle_stable,
    }


def _sqlite_full_integrity(path: Path) -> tuple[bool, str]:
    integrity = _sqlite_bundle_integrity_check(path)
    if not integrity["bundleStable"]:
        return False, "bundle_stable: bundle_changed_during_check"
    if not integrity["quickOk"]:
        return False, f"quick_check: {integrity['quickDetail']}"
    if not integrity["integrityOk"]:
        return False, f"integrity_check: {integrity['integrityDetail']}"
    return True, "ok"


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = None
        for access in (0x1000, 0x0400):
            handle = kernel32.OpenProcess(access, False, int(pid))
            if handle:
                break
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                return False
            return int(exit_code.value) == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


__all__ = [
    "CACHE_POLICY_COLD_REBUILD",
    "StorageMigrationEntry",
    "StorageMigrationError",
    "StorageMigrationPlan",
    "apply_storage_migration",
    "assess_post_cutover_delta",
    "assess_rollback_eligibility",
    "assess_storage_migration_readiness",
    "plan_storage_migration",
    "rollback_storage_switch",
]
