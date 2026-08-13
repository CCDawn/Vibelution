"""Copy-and-verify migration from legacy checkout storage to project state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from vibelution_storage import (
    STORAGE_MIGRATION_SCHEMA_VERSION,
    ProjectStoragePaths,
    legacy_project_storage_paths,
    project_memory_migration_state_path,
    resolve_project_storage_paths,
    storage_migration_state_path,
)


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
        }
        if include_entries:
            payload["entries"] = [asdict(entry) for entry in self.entries]
        return payload


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
    for category, source_root, destination_root in mappings:
        if _same_path(source_root, destination_root) or not source_root.exists():
            continue
        for source in _iter_source_files(source_root):
            relative = source.relative_to(source_root)
            destination = (destination_root / relative).resolve()
            entry = StorageMigrationEntry(
                source=str(source.resolve()),
                destination=str(destination),
                category=category,
                relative_path=relative.as_posix(),
                size=source.stat().st_size,
                sha256=_sha256_file(source),
            )
            key = os.path.normcase(str(destination))
            existing = entries_by_destination.get(key)
            if existing is not None and (
                existing.size != entry.size or existing.sha256 != entry.sha256
            ):
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
    )


def apply_storage_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Copy, verify, then atomically activate external storage.

    No legacy file is modified or deleted. A conflict or changing source leaves
    the completion marker absent, so all current readers stay on legacy paths.
    """

    plan = plan_storage_migration(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
    )
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    _assert_destinations_within_target(plan.entries, target)
    conflicts = _destination_conflicts(plan.entries)
    if conflicts:
        raise StorageMigrationError("destination conflicts: " + "; ".join(conflicts[:8]))

    copied = 0
    reused = 0
    for entry in plan.entries:
        source = Path(entry.source)
        destination = Path(entry.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            reused += 1
        else:
            shutil.copy2(source, destination)
            copied += 1
        _verify_entry(entry)

    refreshed = plan_storage_migration(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
    )
    if _plan_signature(refreshed) != _plan_signature(plan):
        raise StorageMigrationError("legacy sources changed during migration; completion marker not written")

    completed_at = _now_iso()
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
        "manifestPath": str(manifest_path),
        "legacyDeleteAllowed": False,
    }
    memory_entries = tuple(entry for entry in plan.entries if entry.category == "project_memory")
    memory_marker = {
        "schemaVersion": STORAGE_MIGRATION_SCHEMA_VERSION,
        "status": "completed",
        "projectId": target.project_id,
        "activatedByInstanceId": target.instance_id,
        "projectRoot": str(target.project_root),
        "sourceRoot": str(legacy_project_storage_paths(target.project_root, target=target).memory),
        "targetRoot": str(target.memory),
        "completedAt": completed_at,
        "totalFiles": len(memory_entries),
        "totalBytes": sum(entry.size for entry in memory_entries),
        "aggregateSha256": _aggregate_digest(memory_entries),
        "legacyDeleteAllowed": False,
    }
    _atomic_write_json(project_memory_migration_state_path(target), memory_marker)
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = marker_path.with_name(f"storage-migration.rolled-back-{stamp}.json")
    os.replace(marker_path, archived)
    archived_memory_marker: Path | None = None
    try:
        memory_marker = json.loads(memory_marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        memory_marker = {}
    if (
        isinstance(memory_marker, dict)
        and memory_marker.get("status") == "completed"
        and str(memory_marker.get("projectId") or "") == target.project_id
        and str(memory_marker.get("activatedByInstanceId") or "") == target.instance_id
        and _same_path(Path(str(memory_marker.get("projectRoot") or target.project_root)), target.project_root)
    ):
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
        "copiedDataRetained": True,
    }


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
            if candidate.is_file():
                yield candidate.resolve()


def _destination_conflicts(entries: Iterable[StorageMigrationEntry]) -> list[str]:
    conflicts: list[str] = []
    for entry in entries:
        destination = Path(entry.destination)
        if not destination.exists():
            continue
        if not destination.is_file():
            conflicts.append(f"not a file: {destination}")
            continue
        if destination.stat().st_size != entry.size or _sha256_file(destination) != entry.sha256:
            conflicts.append(f"different content: {destination}")
    return conflicts


def _verify_entry(entry: StorageMigrationEntry) -> None:
    source = Path(entry.source)
    destination = Path(entry.destination)
    if not source.is_file() or not destination.is_file():
        raise StorageMigrationError(f"migration file disappeared: {entry.relative_path}")
    if source.stat().st_size != entry.size or _sha256_file(source) != entry.sha256:
        raise StorageMigrationError(f"legacy source changed during copy: {source}")
    if destination.stat().st_size != entry.size or _sha256_file(destination) != entry.sha256:
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
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate_digest(entries: Iterable[StorageMigrationEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.destination.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _plan_signature(plan: StorageMigrationPlan) -> tuple[tuple[str, str, int, str], ...]:
    return tuple(
        (entry.source, entry.destination, entry.size, entry.sha256)
        for entry in plan.entries
    )


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "StorageMigrationEntry",
    "StorageMigrationError",
    "StorageMigrationPlan",
    "apply_storage_migration",
    "plan_storage_migration",
    "rollback_storage_switch",
]
