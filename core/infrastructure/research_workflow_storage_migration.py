"""Fail-closed migration for the historical research-workflow data root.

This module deliberately owns only ``research_workflows``.  It is an operator
tooling surface, not a runtime fallback: the operator Documents source is
read-only, the project canonical target is resolved through
``vibelution_storage``, and the global storage marker is never written here.

SQLite assets are copied through APSW's online backup API.  A SQLite ``-wal``
or ``-shm`` file is therefore part of the source stability fingerprint, but is
never copied as an independent destination asset.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path

import apsw

from config.paths import resolve_data_home
from core.research.workflow.ledger.schema import SCHEMA_VERSION as LEDGER_SCHEMA_VERSION
from vibelution_storage import (
    ProjectStoragePaths,
    resolve_active_project_storage_paths,
    resolve_project_storage_paths,
    storage_migration_complete,
    storage_migration_state_path,
)

RESEARCH_WORKFLOW_DIR = "research_workflows"
LEDGER_FILENAME = "workflow-ledger.sqlite"
CHECKPOINT_FILENAME = "checkpoints.sqlite"
LEGACY_PLACEHOLDER_FILENAME = "workflow-checkpoints.sqlite"
KEY_RUN_ID = "run-882610596ddb"
CURRENT_LEDGER_SCHEMA_VERSION = int(LEDGER_SCHEMA_VERSION)
MANIFEST_DIRNAME = "migration"
MANIFEST_PREFIX = "rwm-"
_BACKUP_DIRNAME = ".rwm-b"
_BACKUP_BEFORE_DIRNAME = "b"
_PROMOTION_JOURNAL_FILENAME = ".rwm-j.json"
_PROMOTION_JOURNAL_SCHEMA_VERSION = 1
_SCOPE_HYGIENE_SCHEMA_VERSION = 1
_MANUAL_REPLAY_TASK_ID = "stagetask-20260829040433-1b95a996"

_SQLITE_SUFFIXES = frozenset({".sqlite", ".sqlite3", ".db"})
_ALLOWED_ASSETS = (CHECKPOINT_FILENAME, "runs", LEDGER_FILENAME)
_EXCLUDED_PREFIXES = (
    "challenge_cup",
    "challenge-cup",
    "source_collection",
    "source-collection",
    "migration",  # legacy one-shot reports are not canonical workflow data
)
_EXCLUDED_NAMES = frozenset({"agent_config", "agents", "workspace"})
_ACTIVE_CLAIM_STATUSES = frozenset({"active", "claimed", "in_progress", "ready", "running"})
_REPARSE_POINT = 0x400
_CHECKPOINT_SCHEMA_CONTRACT = {
    "checkpoints": (
        ("thread_id", "TEXT", True, 1),
        ("checkpoint_ns", "TEXT", True, 2),
        ("checkpoint_id", "TEXT", True, 3),
        ("parent_checkpoint_id", "TEXT", False, 0),
        ("type", "TEXT", False, 0),
        ("checkpoint", "BLOB", False, 0),
        ("metadata", "BLOB", False, 0),
    ),
    "writes": (
        ("thread_id", "TEXT", True, 1),
        ("checkpoint_ns", "TEXT", True, 2),
        ("checkpoint_id", "TEXT", True, 3),
        ("task_id", "TEXT", True, 4),
        ("idx", "INTEGER", True, 5),
        ("channel", "TEXT", True, 0),
        ("type", "TEXT", False, 0),
        ("value", "BLOB", False, 0),
    ),
}


class ResearchWorkflowMigrationError(RuntimeError):
    """Raised when a migration cannot prove a safe, exact cutover."""


class _SQLiteBundleSnapshotError(ResearchWorkflowMigrationError):
    """Raised when a task-owned SQLite bundle snapshot cannot be proven exact."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        message = code if not detail else f"{code}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class SQLiteEvidence:
    schema_version: int | None
    schema_digest: str
    row_counts: dict[str, int]
    business_rows: int
    key_runs: dict[str, str]
    quick_check: str
    integrity_check: str
    foreign_key_errors: tuple[str, ...]
    known_schema: bool
    bundle_fingerprint: str
    bundle_members: tuple[dict[str, object], ...]

    @property
    def valid(self) -> bool:
        return (
            self.quick_check == "ok"
            and self.integrity_check == "ok"
            and not self.foreign_key_errors
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchWorkflowAsset:
    relative_path: str
    kind: str
    source_path: Path
    target_path: Path
    size: int
    sha256: str
    bundle_fingerprint: str = ""
    sqlite: SQLiteEvidence | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "relativePath": self.relative_path,
            "kind": self.kind,
            "sourcePath": str(self.source_path),
            "targetPath": str(self.target_path),
            "size": self.size,
            "sha256": self.sha256,
            "bundleFingerprint": self.bundle_fingerprint,
        }
        if self.sqlite is not None:
            payload["sqlite"] = self.sqlite.to_dict()
        return payload


@dataclass(frozen=True)
class ResearchWorkflowMigrationResult:
    source_root: Path
    target_root: Path
    allowed_assets: tuple[str, ...]
    excluded_assets: tuple[str, ...]
    entries: tuple[ResearchWorkflowAsset, ...]
    blockers: tuple[dict[str, object], ...] = ()
    warnings: tuple[dict[str, object], ...] = ()
    source_fingerprint: str = ""
    target_fingerprint: str = ""
    marker_path: Path | None = None
    active_root: Path | None = None
    status: str = "preview"
    scope_hygiene: dict[str, object] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ready,
            "status": self.status,
            "sourceRoot": str(self.source_root),
            "targetRoot": str(self.target_root),
            "allowedAssets": list(self.allowed_assets),
            "excludedAssets": list(self.excluded_assets),
            "entries": [item.to_dict() for item in self.entries],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "sourceFingerprint": self.source_fingerprint,
            "targetFingerprint": self.target_fingerprint,
            "markerPath": str(self.marker_path) if self.marker_path else "",
            "activeRoot": str(self.active_root) if self.active_root else "",
            "scopeHygiene": dict(self.scope_hygiene),
        }


@dataclass(frozen=True)
class _ResolvedRoots:
    project: ProjectStoragePaths
    source: Path
    target: Path
    marker: Path


@dataclass(frozen=True)
class _BeforeRecord:
    relative_path: str
    existed: bool
    kind: str
    archive_path: str
    sha256: str = ""
    bundle_fingerprint: str = ""
    archive_sha256: str = ""
    archive_bundle_fingerprint: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _RollbackPlan:
    entry: dict[str, object]
    before: _BeforeRecord
    target: Path
    after_archive: Path


QuiescenceProbe = Callable[[Path], dict[str, object]]
V5LedgerValidator = Callable[[apsw.Connection], object]

def _resolve_roots(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
) -> _ResolvedRoots:
    project = resolve_project_storage_paths(project_root, projects_home=projects_home)
    operator_data = resolve_data_home(config_path=config_path)
    canonical_source = (operator_data / RESEARCH_WORKFLOW_DIR).resolve()
    canonical_target = (project.data / RESEARCH_WORKFLOW_DIR).resolve()
    source = canonical_source if source_root is None else Path(source_root).expanduser().resolve()
    target = canonical_target if target_root is None else Path(target_root).expanduser().resolve()
    if source != canonical_source:
        raise ResearchWorkflowMigrationError(
            "source path must be the operator Documents data home research_workflows"
        )
    if target != canonical_target:
        raise ResearchWorkflowMigrationError(
            "target path must be the project canonical data research_workflows"
        )
    if source == target:
        raise ResearchWorkflowMigrationError("source and target research_workflows roots must differ")
    return _ResolvedRoots(
        project=project,
        source=source,
        target=target,
        marker=storage_migration_state_path(project),
    )


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        stat = path.lstat()
    except OSError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT)


def _check_reparse_tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    bad: list[str] = []
    if _is_reparse(root):
        return ["."]
    try:
        children = sorted(root.rglob("*"), key=lambda item: item.as_posix().lower())
    except OSError as exc:
        return [f"<scan-error:{type(exc).__name__}>"]
    for path in children:
        if _is_reparse(path):
            bad.append(path.relative_to(root).as_posix())
    return bad


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_bundle_paths(main: Path) -> tuple[Path, Path, Path]:
    return (
        main,
        main.with_name(main.name + "-wal"),
        main.with_name(main.name + "-shm"),
    )


def _path_entry_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse(path)


def _sqlite_bundle_snapshot(main: Path) -> tuple[str, tuple[dict[str, object], ...]]:
    members: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for role, path in zip(("main", "wal", "shm"), _sqlite_bundle_paths(main), strict=True):
        if _path_entry_exists(path) and (_is_reparse(path) or not path.is_file()):
            raise _SQLiteBundleSnapshotError("sqlite_bundle_member_unsafe", str(path))
        present = path.is_file()
        size = int(path.stat().st_size) if present else 0
        sha = _sha256_file(path) if present else ""
        member = {"role": role, "present": present, "size": size, "sha256": sha}
        members.append(member)
        for key in ("role", "present", "size", "sha256"):
            digest.update(str(member[key]).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest(), tuple(members)


def _remove_task_temp_tree(root: Path) -> None:
    """Remove one task-owned snapshot tree and prove that it is gone."""

    try:
        if root.exists():
            shutil.rmtree(root)
        if root.exists():
            raise OSError("snapshot directory still exists after cleanup")
    except Exception as exc:
        raise _SQLiteBundleSnapshotError(
            "sqlite_bundle_snapshot_cleanup_failed", type(exc).__name__
        ) from exc


def _copy_sqlite_bundle_to_temp(path: Path) -> tuple[Path, Path]:
    """Copy one stable SQLite main/WAL/SHM bundle into system temp.

    APSW is intentionally never opened against ``path`` when a sidecar is
    present.  The source is sampled before and after the byte copies; a
    mismatch means the operator root was not quiescent and the caller must
    fail closed.  Snapshot names are deliberately short because this helper
    also protects Windows callers from long project/data roots.
    """

    source = Path(path)
    before_fingerprint, before_members = _sqlite_bundle_snapshot(source)
    try:
        snapshot_root = Path(tempfile.mkdtemp(prefix="rwm-s-"))
    except Exception as exc:
        raise _SQLiteBundleSnapshotError(
            "sqlite_bundle_snapshot_copy_failed", type(exc).__name__
        ) from exc
    snapshot_main = snapshot_root / "db.sqlite"
    try:
        for suffix, source_member in zip(("", "-wal", "-shm"), _sqlite_bundle_paths(source), strict=True):
            if not source_member.is_file():
                continue
            shutil.copyfile(source_member, snapshot_root / f"db.sqlite{suffix}")

        after_fingerprint, after_members = _sqlite_bundle_snapshot(source)
        if before_fingerprint != after_fingerprint or before_members != after_members:
            raise _SQLiteBundleSnapshotError(
                "sqlite_bundle_changed_during_snapshot", source.name
            )
        snapshot_fingerprint, snapshot_members = _sqlite_bundle_snapshot(snapshot_main)
        if snapshot_fingerprint != before_fingerprint or snapshot_members != before_members:
            raise _SQLiteBundleSnapshotError(
                "sqlite_bundle_snapshot_mismatch", source.name
            )
        return snapshot_root, snapshot_main
    except _SQLiteBundleSnapshotError:
        _remove_task_temp_tree(snapshot_root)
        raise
    except Exception as exc:
        _remove_task_temp_tree(snapshot_root)
        raise _SQLiteBundleSnapshotError(
            "sqlite_bundle_snapshot_copy_failed", type(exc).__name__
        ) from exc


@contextmanager
def _sqlite_bundle_snapshot_context(path: Path):
    """Yield a short-lived exact SQLite bundle image and always clean it."""

    snapshot_root, snapshot_main = _copy_sqlite_bundle_to_temp(path)
    try:
        yield snapshot_main
    finally:
        _remove_task_temp_tree(snapshot_root)


def _source_tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or _is_reparse(path):
            continue
        rel = path.relative_to(root).as_posix()
        # The inventory and preview contracts deliberately share one exclusion
        # rule.  In particular, a hand-made ``index.json.bak-*`` must never
        # perturb the generation used by apply/verify.
        if _is_excluded(rel):
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_backup_path(relative_path: str) -> bool:
    return any(
        fnmatchcase(part, "*.bak-*")
        for part in (component.lower() for component in Path(relative_path).parts)
    )


def _is_excluded(relative_path: str) -> bool:
    parts = [part.lower() for part in Path(relative_path).parts]
    if _is_backup_path(relative_path):
        return True
    if any(part in _EXCLUDED_NAMES for part in parts):
        return True
    return any(
        part == prefix or part.startswith((prefix + "_", prefix + "-"))
        for part in parts
        for prefix in _EXCLUDED_PREFIXES
    )


def _scope_text(value: object) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()[:160]
    return ""


def _scope_dirs(path: Path) -> tuple[Path, ...]:
    if not path.is_dir() or _is_reparse(path):
        return ()
    try:
        return tuple(
            sorted(
                (
                    child
                    for child in path.iterdir()
                    if child.is_dir()
                    and not _is_reparse(child)
                    and not _is_backup_path(child.name)
                ),
                key=lambda child: child.name.lower(),
            )
        )
    except OSError:
        return ()


def _scope_backup_names(root: Path) -> set[str]:
    if not root.is_dir() or _is_reparse(root):
        return set()
    try:
        return {
            path.name
            for path in root.rglob("*")
            if not _is_reparse(path) and _is_backup_path(path.name)
        }
    except OSError:
        return set()


def _scope_store_rows(
    path: Path,
    workspace_root: Path,
    row_key: str,
) -> tuple[str, str, list[dict[str, object]]] | None:
    if not path.is_file() or _is_reparse(path):
        return None
    try:
        file_hash = _sha256_file(path)
        relative = path.relative_to(workspace_root).as_posix()
    except (OSError, ValueError):
        return None
    payload = _read_json_object(path)
    rows = payload.get(row_key) if payload else None
    if not isinstance(rows, list):
        return None
    return relative, file_hash, [raw for raw in rows if isinstance(raw, dict)]


def _candidate_scope_item(
    raw: dict[str, object],
    *,
    physical_project_id: str,
    relative: str,
    file_hash: str,
) -> dict[str, object] | None:
    entity_id = _scope_text(raw.get("candidateId") or raw.get("id"))
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    owner = _scope_text(raw.get("researchProjectId"))
    metadata_owner = _scope_text(metadata.get("researchProjectId"))
    if (
        not entity_id
        or not owner
        or not metadata_owner
        or owner != metadata_owner
        or owner == physical_project_id
    ):
        return None
    provenance = {
        "candidateType": _scope_text(raw.get("candidateType")),
        "researchProjectId": owner,
        "metadataResearchProjectId": metadata_owner,
    }
    for key in ("sourceCollectionRunId", "workflowRunId", "recordId"):
        value = _scope_text(raw.get(key) or metadata.get(key))
        if value:
            provenance[key] = value
    return {
        "entityId": entity_id,
        "classification": "manual_scope_stamp",
        "action": "canonical_migration",
        "owner": owner,
        "path": relative,
        "hash": file_hash,
        "provenance": provenance,
    }


def _stage_scope_item(
    raw: dict[str, object],
    *,
    physical_project_id: str,
    relative: str,
    file_hash: str,
) -> dict[str, object] | None:
    entity_id = _scope_text(raw.get("taskId") or raw.get("id"))
    owner = _scope_text(raw.get("researchProjectId"))
    manual_replay = entity_id == _MANUAL_REPLAY_TASK_ID
    if not entity_id or not (manual_replay or (owner and owner != physical_project_id)):
        return None
    turn = raw.get("turn") if isinstance(raw.get("turn"), dict) else {}
    item: dict[str, object] = {
        "entityId": entity_id,
        "classification": (
            "manual_replay" if manual_replay else "noncanonical_stage_task"
        ),
        "action": "alias/audit",
        "needsReview": True,
        "owner": owner,
        "path": relative,
        "hash": file_hash,
        "provenance": {
            key: value
            for key, value in {
                "runId": _scope_text(raw.get("runId")),
                "workflowRunId": _scope_text(raw.get("workflowRunId")),
                "researchProjectId": owner,
                "sessionId": _scope_text(raw.get("sessionId")),
                "turnId": _scope_text(turn.get("turnId") or turn.get("id")),
            }.items()
            if value
        },
    }
    if manual_replay:
        item["lineageClassification"] = "partial_noncanonical_lineage"
    return item


def _scope_hygiene(target_root: Path) -> dict[str, object]:
    workspace_root = target_root.parent / "workspace"
    excluded: set[str] = set()
    items: list[dict[str, object]] = []
    if workspace_root.is_dir() and not _is_reparse(workspace_root):
        for team in _scope_dirs(workspace_root / "teams"):
            bases = [(team, "legacy-default")]
            bases.extend(
                (project / "workspace", project.name)
                for project in _scope_dirs(team / "research_projects")
            )
            for base, physical_project_id in bases:
                candidate_root = base / "candidate_store"
                stage_root = base / "source_collection_runs"
                excluded.update(_scope_backup_names(candidate_root))
                excluded.update(_scope_backup_names(stage_root))
                stores: list[tuple[Path, str]] = [
                    (candidate_root / "index.json", "candidates")
                ]
                stores.extend(
                    (run / "stage_session_tasks.json", "tasks")
                    for run in _scope_dirs(stage_root)
                )
                for path, row_key in stores:
                    snapshot = _scope_store_rows(path, workspace_root, row_key)
                    if snapshot is None:
                        continue
                    relative, file_hash, rows = snapshot
                    for raw in rows:
                        builder = (
                            _candidate_scope_item
                            if row_key == "candidates"
                            else _stage_scope_item
                        )
                        item = builder(
                            raw,
                            physical_project_id=physical_project_id,
                            relative=relative,
                            file_hash=file_hash,
                        )
                        if item is not None:
                            items.append(item)
    items.sort(
        key=lambda item: (
            str(item.get("entityId") or ""),
            str(item.get("path") or ""),
        )
    )
    excluded_paths = sorted(excluded, key=str.lower)
    result = {
        "schemaVersion": _SCOPE_HYGIENE_SCHEMA_VERSION,
        "items": items,
        "excludedPaths": excluded_paths,
        "counts": {
            "items": len(items),
            "needsReview": sum(1 for item in items if item.get("needsReview") is True),
            "excludedPaths": len(excluded_paths),
        },
    }
    return result


def _allowed_kind(relative_path: str) -> str | None:
    rel = Path(relative_path)
    parts = rel.parts
    if len(parts) == 1 and rel.name in {LEDGER_FILENAME, CHECKPOINT_FILENAME}:
        return "sqlite"
    if len(parts) == 2 and parts[0] == "runs" and parts[1].startswith("run-") and parts[1].endswith(".json"):
        return "json"
    if rel.as_posix() == "runs/_index/idempotency.json":
        return "json"
    return None


def _sqlite_main_for_sidecar(relative_path: str) -> str | None:
    rel = Path(relative_path)
    if rel.name.endswith("-wal"):
        return rel.with_name(rel.name[:-4]).as_posix()
    if rel.name.endswith("-shm"):
        return rel.with_name(rel.name[:-4]).as_posix()
    return None


def _legacy_placeholder_is_empty(path: Path) -> bool:
    """Recognize only the exact historical zero-byte placeholder.

    The legacy filename is not part of the migration allowlist.  A byte-empty
    main with no SQLite sidecars is therefore safe to record as excluded
    evidence, while any content or sidecar remains an unknown asset and blocks
    the operator.  This helper deliberately does not open the file.
    """

    return (
        path.name == LEGACY_PLACEHOLDER_FILENAME
        and path.is_file()
        and path.stat().st_size == 0
        and not any(_path_entry_exists(member) for member in _sqlite_bundle_paths(path)[1:])
    )


def _open_readonly(path: Path) -> apsw.Connection:
    # SQLite may create a ``-shm`` file merely by opening a WAL-capable image.
    # For a bundle with no existing WAL/SHM members, immutable read-only mode
    # proves that this audit/backup operation cannot mutate the Documents
    # source.  Existing sidecars are opened normally so their committed WAL
    # state participates in the APSW backup snapshot.
    has_sidecar = any(member.is_file() for member in _sqlite_bundle_paths(path)[1:])
    database = str(path)
    if not has_sidecar:
        database = path.resolve().as_uri() + "?mode=ro&immutable=1"
    return apsw.Connection(
        database,
        flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI,
    )


def _schema_digest(connection: apsw.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master "
        "WHERE type IN ('table','index','trigger','view') ORDER BY type, name"
    )
    digest = hashlib.sha256()
    for row in rows:
        digest.update("\x1f".join(str(value) for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _ledger_schema_contract_digest(path: Path) -> str:
    """Hash the ledger schema contract after authority-owned SQL normalization."""

    try:
        from core.research.workflow.ledger.database import _normalize_sql
    except Exception as exc:
        raise _SQLiteBundleSnapshotError(
            "ledger_schema_contract_unavailable", type(exc).__name__
        ) from exc
    try:
        with _sqlite_bundle_snapshot_context(path) as snapshot:
            connection = _open_readonly(snapshot)
            try:
                rows = connection.execute(
                    "SELECT type, name, tbl_name, COALESCE(sql, '') "
                    "FROM sqlite_master "
                    "WHERE type IN ('table','index','trigger','view') "
                    "ORDER BY type, name"
                )
                digest = hashlib.sha256()
                for row in rows:
                    object_type, name, table_name, raw_sql = (str(value) for value in row)
                    digest.update(
                        "\x1f".join(
                            (object_type, name, table_name, _normalize_sql(raw_sql))
                        ).encode("utf-8")
                    )
                    digest.update(b"\n")
                return digest.hexdigest()
            finally:
                connection.close()
    except _SQLiteBundleSnapshotError:
        raise
    except Exception as exc:
        raise _SQLiteBundleSnapshotError(
            "ledger_schema_contract_unreadable", type(exc).__name__
        ) from exc


def _row_counts(connection: apsw.Connection) -> dict[str, int]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts: dict[str, int] = {}
    for table in tables:
        escaped = table.replace('"', '""')
        counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])
    return counts


def _sqlite_schema_version(connection: apsw.Connection) -> int | None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
    }
    if "schema_migrations" not in tables:
        return None
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _sqlite_key_runs(connection: apsw.Connection) -> dict[str, str]:
    names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_runs'"
        )
    }
    if "workflow_runs" not in names:
        return {}
    result: dict[str, str] = {}
    for run_id in (KEY_RUN_ID,):
        row = connection.execute(
            "SELECT status FROM workflow_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is not None:
            result[run_id] = str(row[0])
    return result


def _checkpoint_schema_complete(connection: apsw.Connection, names: set[str]) -> bool:
    """Accept only the configured SqliteSaver relation and key contract."""

    if not set(_CHECKPOINT_SCHEMA_CONTRACT).issubset(names):
        return False
    for table, expected in _CHECKPOINT_SCHEMA_CONTRACT.items():
        escaped = table.replace('"', '""')
        columns = tuple(
            (str(row[1]), str(row[2]).upper(), bool(int(row[3])), int(row[5]))
            for row in connection.execute(f'PRAGMA table_info("{escaped}")')
        )
        if columns != expected:
            return False
    return True


def _v5_validator(path: Path) -> V5LedgerValidator | None:
    """Bind the ledger's v5 schema authority without copying its DDL contract."""

    try:
        from core.research.workflow.ledger.database import WorkflowLedgerDatabase
    except ImportError:
        return None
    validator = getattr(
        WorkflowLedgerDatabase(path),
        "_validate_v5_catalog_schema",
        None,
    )
    return validator if callable(validator) else None


def _allowed_v5_checksums() -> frozenset[str] | None:
    """Read the current and legacy v5 checksums from the ledger authority."""

    try:
        from core.research.workflow.ledger.schema import MIGRATIONS, V5_LEGACY_CHECKSUM
    except ImportError:
        return None
    current = next((item.checksum for item in MIGRATIONS if item.version == 5), None)
    if not isinstance(current, str) or not current:
        return None
    return frozenset((current, V5_LEGACY_CHECKSUM))


def _validate_v5_ledger_open_path(path: Path) -> tuple[bool, str]:
    """Delegate v5 checksum and catalog-shape validation, or fail closed."""

    validator = _v5_validator(path)
    allowed_checksums = _allowed_v5_checksums()
    if validator is None or allowed_checksums is None:
        return False, "ledger_v5_validator_unavailable"
    connection: apsw.Connection | None = None
    try:
        connection = _open_readonly(path)
        checksum_row = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 5"
        ).fetchone()
        if checksum_row is None or str(checksum_row[0]) not in allowed_checksums:
            return False, "ledger_v5_checksum_rejected"
        validator(connection)
    except Exception as exc:  # noqa: BLE001 - external validator boundary must fail closed.
        return False, f"ledger_v5_validator_rejected:{type(exc).__name__}"
    finally:
        if connection is not None:
            connection.close()
    return True, ""


def _validate_v5_ledger(path: Path) -> tuple[bool, str]:
    """Validate a ledger image without opening a real source in place."""

    source = Path(path)
    if source.stat().st_size > 0:
        with _sqlite_bundle_snapshot_context(source) as snapshot:
            return _validate_v5_ledger_open_path(snapshot)
    return _validate_v5_ledger_open_path(source)


def _sqlite_evidence_open_path(path: Path, *, kind: str) -> SQLiteEvidence:
    bundle_fingerprint, bundle_members = _sqlite_bundle_snapshot(path)
    if path.stat().st_size == 0:
        return SQLiteEvidence(
            schema_version=None,
            schema_digest="",
            row_counts={},
            business_rows=0,
            key_runs={},
            quick_check="empty",
            integrity_check="empty",
            foreign_key_errors=(),
            known_schema=False,
            bundle_fingerprint=bundle_fingerprint,
            bundle_members=bundle_members,
        )
    connection: apsw.Connection | None = None
    try:
        connection = _open_readonly(path)
        quick_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        integrity_rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign_rows = [" | ".join(str(item) for item in row) for row in connection.execute("PRAGMA foreign_key_check")]
        counts = _row_counts(connection)
        version = _sqlite_schema_version(connection)
        names = set(counts)
        known = (
            (kind == "ledger" and version == CURRENT_LEDGER_SCHEMA_VERSION)
            or (kind == "checkpoint" and _checkpoint_schema_complete(connection, names))
        )
        if kind == "ledger" and version is not None and version > CURRENT_LEDGER_SCHEMA_VERSION:
            known = False
        return SQLiteEvidence(
            schema_version=version,
            schema_digest=_schema_digest(connection),
            row_counts=counts,
            business_rows=sum(count for name, count in counts.items() if name != "schema_migrations"),
            key_runs=_sqlite_key_runs(connection),
            quick_check=quick_rows[0] if quick_rows else "missing",
            integrity_check=integrity_rows[0] if integrity_rows else "missing",
            foreign_key_errors=tuple(foreign_rows),
            known_schema=known,
            bundle_fingerprint=bundle_fingerprint,
            bundle_members=bundle_members,
        )
    except apsw.Error as exc:
        return SQLiteEvidence(
            schema_version=None,
            schema_digest="",
            row_counts={},
            business_rows=0,
            key_runs={},
            quick_check=f"error:{type(exc).__name__}",
            integrity_check=f"error:{type(exc).__name__}",
            foreign_key_errors=(str(exc),),
            known_schema=False,
            bundle_fingerprint=bundle_fingerprint,
            bundle_members=bundle_members,
        )
    finally:
        if connection is not None:
            connection.close()


def _sqlite_evidence(path: Path, *, kind: str) -> SQLiteEvidence:
    """Inspect SQLite using only a task-owned bundle snapshot."""

    source = Path(path)
    if source.stat().st_size > 0:
        with _sqlite_bundle_snapshot_context(source) as snapshot:
            return _sqlite_evidence_open_path(snapshot, kind=kind)
    return _sqlite_evidence_open_path(source, kind=kind)


def _make_asset(source_root: Path, target_root: Path, relative: str, kind: str) -> ResearchWorkflowAsset:
    source = source_root / Path(relative)
    target = target_root / Path(relative)
    size = int(source.stat().st_size)
    sha = _sha256_file(source)
    if kind == "sqlite":
        bundle, _ = _sqlite_bundle_snapshot(source)
        sqlite_kind = "ledger" if source.name == LEDGER_FILENAME else "checkpoint"
        evidence = _sqlite_evidence(source, kind=sqlite_kind)
        return ResearchWorkflowAsset(
            relative_path=relative,
            kind=kind,
            source_path=source,
            target_path=target,
            size=size,
            sha256=sha,
            bundle_fingerprint=bundle,
            sqlite=evidence,
        )
    return ResearchWorkflowAsset(
        relative_path=relative,
        kind=kind,
        source_path=source,
        target_path=target,
        size=size,
        sha256=sha,
    )


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _positive_int(value: object) -> int:
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def _pid_is_alive(pid: object) -> bool:
    normalized = _positive_int(pid)
    if not normalized:
        return False
    try:
        from core.infrastructure.storage_migration import _pid_is_alive as probe

        return bool(probe(normalized))
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _runtime_manager_identity_matches(pid: int, identity: dict[str, object]) -> bool:
    if not pid or not identity:
        return False
    try:
        from core.runtime_manager.process_identity import inspect_process_identity

        expected = dict(identity)
        expected.setdefault("pid", pid)
        return inspect_process_identity(expected).get("status") == "match"
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _residual_processes_present(value: object) -> bool:
    if isinstance(value, list):
        return bool(value)
    if not isinstance(value, dict):
        return False
    if _positive_int(value.get("count")):
        return True
    items = value.get("items")
    return isinstance(items, list) and bool(items)


def _runtime_payload_has_backend_or_residual_activity(
    payload: dict[str, object],
) -> tuple[bool, dict[str, object]]:
    evidence: dict[str, object] = {}
    candidates = [payload]
    workbench = payload.get("workbench")
    if isinstance(workbench, dict):
        candidates.append(workbench)
    for candidate in candidates:
        if candidate.get("backendPortListening") is True:
            evidence["backendPortListening"] = True
        owner_pid = _positive_int(candidate.get("backendPortOwnerPid"))
        if owner_pid:
            evidence["backendPortOwnerPid"] = owner_pid
        if candidate.get("backendPortOwnerResidual") is True:
            evidence["backendPortOwnerResidual"] = True
        if _residual_processes_present(candidate.get("residualProcesses")):
            evidence["residualProcesses"] = candidate.get("residualProcesses")
    return bool(evidence), evidence


def _runtime_manager_live(project_root: Path, guard: dict[str, object]) -> tuple[bool, dict[str, object]]:
    """Return whether runtime-manager evidence still proves a live owner.

    A lock file is only a coordination artifact.  It remains a writer blocker
    when a matching daemon/manager/backend is live, but an idle runtime with
    dead PIDs is reported as stale evidence and left untouched.
    """

    evidence: dict[str, object] = {}
    runtime_meta = guard.get("runtimeManager")
    if not isinstance(runtime_meta, dict):
        runtime_meta = {}
    launcher = guard.get("launcher")
    if not isinstance(launcher, dict):
        launcher = {}
    for payload in (runtime_meta, launcher, guard):
        active, backend_evidence = _runtime_payload_has_backend_or_residual_activity(payload)
        if active:
            evidence.update(backend_evidence)
            return True, evidence
    if launcher.get("alive") is True or launcher.get("runtimeLive") is True:
        evidence["launcherLive"] = True
        return True, evidence
    if runtime_meta.get("live") is True or runtime_meta.get("runtimeLive") is True:
        evidence["runtimeManagerLive"] = True
        return True, evidence
    if str(runtime_meta.get("identityStatus") or "").strip().lower() in {"match", "live", "owned"}:
        evidence["identityStatus"] = str(runtime_meta.get("identityStatus"))
        return True, evidence

    try:
        runtime_root = resolve_project_storage_paths(project_root).runtime
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        runtime_root = None
    manager_dir = runtime_root / "runtime-manager" if runtime_root is not None else None
    state = _read_json_object(manager_dir / "state.json") if manager_dir is not None else None
    launcher_state = _read_json_object(runtime_root / "launcher" / "state.json") if runtime_root is not None else None
    for payload in (state, launcher_state):
        if isinstance(payload, dict):
            active, backend_evidence = _runtime_payload_has_backend_or_residual_activity(payload)
            if active:
                evidence.update(backend_evidence)
                return True, evidence
            nested = payload.get("workbench") if isinstance(payload.get("workbench"), dict) else {}
            if nested.get("backendPid") and _pid_is_alive(nested.get("backendPid")):
                evidence["backendPid"] = _positive_int(nested.get("backendPid"))
                return True, evidence
            for key in ("managerPid", "backendPid", "daemonPid"):
                pid = _positive_int(payload.get(key))
                if pid and _pid_is_alive(pid):
                    evidence[key] = pid
                    identity = payload.get("identity")
                    if isinstance(identity, dict) and _runtime_manager_identity_matches(pid, identity):
                        return True, evidence
                    try:
                        from core.runtime_manager.process_identity import (
                            is_runtime_manager_process,
                        )

                        if is_runtime_manager_process(pid):
                            return True, evidence
                    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                        pass
    if manager_dir is None:
        return False, evidence
    identity = _read_json_object(manager_dir / "daemon.identity.json") or {}
    for name in ("daemon.lock", "daemon.pid"):
        path = manager_dir / name
        try:
            pid = _positive_int(path.read_text(encoding="utf-8").strip()) if path.is_file() else 0
        except OSError:
            pid = 0
        if not pid or not _pid_is_alive(pid):
            continue
        evidence[name] = pid
        if _runtime_manager_identity_matches(pid, identity):
            return True, evidence
        try:
            from core.runtime_manager.process_identity import is_runtime_manager_process

            if is_runtime_manager_process(pid):
                return True, evidence
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            continue
    return False, evidence


def _source_collection_snapshot_may_be_live(
    snapshot: dict[str, object],
    *,
    runtime_live: bool,
) -> bool:
    if runtime_live:
        return True
    if any(snapshot.get(key) is True for key in ("live", "runtimeLive", "processAlive")):
        return True
    for key in ("processId", "pid", "backendPid", "workerPid", "agentPid", "managerPid"):
        pid = _positive_int(snapshot.get(key))
        if pid and _pid_is_alive(pid):
            return True
    return False


def _probe_source_collection_snapshots(project_root: Path) -> dict[str, object]:
    """Read source-collection snapshots without changing their lifecycle state."""

    try:
        runtime_root = resolve_project_storage_paths(project_root).runtime
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"blocking": True, "uncertain": True, "reasonCode": "runtime_root_unresolved", "detail": type(exc).__name__}
    kind_root = runtime_root / "runtime-manager" / "work_runs" / "source_collection_run"
    if not kind_root.exists():
        return {"blocking": False, "uncertain": False, "snapshots": [], "snapshotCount": 0}
    paths: list[Path] = []
    index_path = kind_root / "index.json"
    index = _read_json_object(index_path)
    if index_path.exists() and index is None:
        return {"blocking": True, "uncertain": True, "reasonCode": "source_collection_index_unreadable", "snapshots": []}
    active_id = str((index or {}).get("activeRunId") or "").strip()
    if active_id:
        paths.append(kind_root / "runs" / f"{active_id}.json")
    runs_dir = kind_root / "runs"
    if runs_dir.is_dir():
        paths.extend(sorted(runs_dir.glob("*.json"), key=lambda item: item.name.lower()))
    snapshots: list[dict[str, object]] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        payload = _read_json_object(path)
        if payload is None:
            return {"blocking": True, "uncertain": True, "reasonCode": "source_collection_snapshot_unreadable", "snapshots": []}
        if not str(payload.get("status") or payload.get("currentPhase") or payload.get("phase") or "").strip():
            continue
        snapshots.append({**payload, "snapshotPath": str(path)})
    return {
        "blocking": False,
        "uncertain": False,
        "snapshots": snapshots,
        "snapshotCount": len(snapshots),
    }


def _normalize_quiescence_guard(project_root: Path, guard: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Downgrade provably stale runtime artifacts to warnings only.

    Active claims, unreadable probes, live processes and live listeners remain
    blockers.  This function only removes a runtime lock/source snapshot
    blocker when the same guard proves the official runtime is idle and the
    corresponding owner PID/process is absent.
    """

    normalized = dict(guard)
    blockers = [item for item in (guard.get("blockers") or []) if isinstance(item, dict)]
    warnings = [item for item in (guard.get("warnings") or []) if isinstance(item, dict)]
    runtime_live, runtime_evidence = _runtime_manager_live(project_root, guard)
    runtime_writers = guard.get("runtimeWriters")
    if not isinstance(runtime_writers, dict):
        runtime_writers = {}
    raw_writers = runtime_writers.get("writers")
    writers = [item for item in raw_writers if isinstance(item, dict)] if isinstance(raw_writers, list) else []
    kept_writers: list[dict[str, object]] = []
    for writer in writers:
        kind = str(writer.get("kind") or "").strip().lower()
        run_kind = str(writer.get("runKind") or "").strip().lower()
        if kind == "runtime_manager_lock" and not runtime_live:
            warnings.append(
                {
                    "code": "stale_runtime_manager_lock",
                    "path": str(writer.get("path") or "runtime-manager/daemon.lock"),
                    "evidence": runtime_evidence,
                }
            )
            continue
        if run_kind == "source_collection_run" and not _source_collection_snapshot_may_be_live(
            writer,
            runtime_live=runtime_live,
        ):
            warnings.append(
                {
                    "code": "stale_source_collection_snapshot",
                    "runId": str(writer.get("runId") or ""),
                    "evidence": runtime_evidence,
                }
            )
            continue
        kept_writers.append(writer)
    source_collection = guard.get("sourceCollectionSnapshots")
    source_snapshots = [item for item in source_collection if isinstance(item, dict)] if isinstance(source_collection, list) else []
    for snapshot in source_snapshots:
        if _source_collection_snapshot_may_be_live(snapshot, runtime_live=runtime_live):
            kept_writers.append({"kind": "work_run", "runKind": "source_collection_run", **snapshot})
        else:
            warnings.append(
                {
                    "code": "stale_source_collection_snapshot",
                    "runId": str(snapshot.get("runId") or ""),
                    "snapshotPath": str(snapshot.get("snapshotPath") or ""),
                }
            )
    normalized_writers = dict(runtime_writers)
    normalized_writers.update(
        {
            "writers": kept_writers,
            "blocking": bool(kept_writers),
            "writerCount": len(kept_writers),
        }
    )
    normalized["runtimeWriters"] = normalized_writers
    normalized["warnings"] = warnings
    filtered_blockers: list[dict[str, object]] = []
    live_source_snapshots = any(
        str(item.get("runKind") or "").strip().lower() == "source_collection_run"
        for item in kept_writers
    )
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        if code == "runtime_writers_active" and not kept_writers and not bool(runtime_writers.get("uncertain")):
            continue
        if code == "source_collection_snapshot_active" and not live_source_snapshots and not bool(runtime_writers.get("uncertain")):
            continue
        filtered_blockers.append(blocker)
    active_work = guard.get("activeWork")
    if not isinstance(active_work, dict):
        active_work = {}
    raw_claims = active_work.get("claims")
    if isinstance(raw_claims, dict):
        claim_rows = [item for item in raw_claims.values() if isinstance(item, dict)]
    elif isinstance(raw_claims, list):
        claim_rows = [item for item in raw_claims if isinstance(item, dict)]
    else:
        claim_rows = []
    active_claims = [
        item
        for item in claim_rows
        if not str(item.get("status") or "").strip()
        or str(item.get("status") or "").strip().lower() in _ACTIVE_CLAIM_STATUSES
    ]
    if (active_work.get("blocking") or active_claims) and not any(
        str(item.get("code") or "") == "active_work_present"
        for item in filtered_blockers
    ):
        filtered_blockers.append({"code": "active_work_present", "claims": active_claims[:8]})
    if active_work.get("uncertain") and not any(
        str(item.get("code") or "") == "active_work_state_uncertain"
        for item in filtered_blockers
    ):
        filtered_blockers.append({"code": "active_work_state_uncertain", "evidence": active_work})
    if runtime_writers.get("uncertain") and not any(
        str(item.get("code") or "") == "runtime_writer_state_uncertain"
        for item in filtered_blockers
    ):
        filtered_blockers.append({"code": "runtime_writer_state_uncertain", "evidence": runtime_writers})
    launcher = guard.get("launcher")
    if not isinstance(launcher, dict):
        launcher = {}
    if (launcher.get("blocking") or launcher.get("uncertain")) and not any(
        str(item.get("code") or "") == "launcher_runtime_active"
        for item in filtered_blockers
    ):
        filtered_blockers.append({"code": "launcher_runtime_active", "evidence": launcher})
    if kept_writers and not any(str(item.get("code") or "") == "runtime_writers_active" for item in filtered_blockers):
        filtered_blockers.append({"code": "runtime_writers_active", "evidence": normalized_writers})
    if guard.get("ok") is not True and not any(
        str(item.get("code") or "") == "quiescence_guard_not_ready"
        for item in filtered_blockers
    ):
        filtered_blockers.append(
            {
                "code": "quiescence_guard_not_ready",
                "reasonCode": str(guard.get("reasonCode") or "raw_guard_not_ready"),
            }
        )
    normalized["blockers"] = filtered_blockers
    normalized["ok"] = guard.get("ok") is True and not filtered_blockers
    return normalized, warnings


def _default_quiescence(project_root: Path) -> dict[str, object]:
    """Reuse the project storage guard probes and fail closed on uncertainty."""

    try:
        from core.infrastructure.storage_migration import (
            _probe_active_work,
            _probe_launcher_state,
            _probe_runtime_writers,
        )

        active = _probe_active_work(project_root)
        writers = _probe_runtime_writers(project_root)
        launcher = _probe_launcher_state(project_root)
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "blockers": [{"code": "quiescence_probe_failed", "detail": type(exc).__name__}],
        }
    blockers: list[dict[str, object]] = []
    if active.get("blocking") or active.get("uncertain"):
        blockers.append({"code": "active_work_present", "evidence": active})
    if writers.get("blocking") or writers.get("uncertain"):
        blockers.append({"code": "runtime_writers_active", "evidence": writers})
    if launcher.get("blocking") or launcher.get("uncertain"):
        blockers.append({"code": "launcher_runtime_active", "evidence": launcher})
    source_snapshots = _probe_source_collection_snapshots(project_root)
    guard: dict[str, object] = {
        "ok": not blockers,
        "blockers": blockers,
        "activeWork": active,
        "runtimeWriters": writers,
        "launcher": launcher,
        "sourceCollectionSnapshots": source_snapshots.get("snapshots") or [],
    }
    if source_snapshots.get("uncertain"):
        guard["blockers"] = [*blockers, {"code": "source_collection_snapshot_probe_failed", "evidence": source_snapshots}]
        guard["ok"] = False
    normalized, _warnings = _normalize_quiescence_guard(project_root, guard)
    return normalized


def acknowledge_proven_stale_runtime_quiescence(project_root: Path) -> dict[str, object]:
    """Explicitly acknowledge only a fully explained stale-runtime guard.

    The default probe remains fail-closed. This operator-only adapter may
    promote it to ready only when every remaining blocker is the synthetic
    ``raw_guard_not_ready`` marker and the normalized evidence independently
    proves there are no claims, live writers, or Launcher process. Historical
    runtime files stay untouched and their warning evidence is retained for
    the migration journal and manifest.
    """

    guard = _default_quiescence(project_root)
    if guard.get("ok") is True:
        return guard
    blockers = [item for item in (guard.get("blockers") or []) if isinstance(item, dict)]
    if (
        len(blockers) != 1
        or blockers[0].get("code") != "quiescence_guard_not_ready"
        or blockers[0].get("reasonCode") != "raw_guard_not_ready"
    ):
        return guard
    active_work = guard.get("activeWork")
    runtime_writers = guard.get("runtimeWriters")
    launcher = guard.get("launcher")
    if (
        not isinstance(active_work, dict)
        or not isinstance(runtime_writers, dict)
        or not isinstance(launcher, dict)
    ):
        return guard
    raw_claims = active_work.get("claims")
    if isinstance(raw_claims, dict):
        claims = list(raw_claims.values())
    elif isinstance(raw_claims, list):
        claims = list(raw_claims)
    elif raw_claims is None:
        claims = []
    else:
        return guard
    if active_work.get("blocking") or active_work.get("uncertain") or claims:
        return guard
    raw_writers = runtime_writers.get("writers")
    if isinstance(raw_writers, list):
        writers = list(raw_writers)
    elif raw_writers is None:
        writers = []
    else:
        return guard
    if runtime_writers.get("blocking") or runtime_writers.get("uncertain") or writers:
        return guard
    if launcher.get("blocking") or launcher.get("uncertain") or launcher.get("alive"):
        return guard
    warnings = [item for item in (guard.get("warnings") or []) if isinstance(item, dict)]
    stale_codes = {"stale_runtime_manager_lock", "stale_source_collection_snapshot"}
    warning_codes = [str(item.get("code") or "") for item in warnings]
    if not warning_codes or any(code not in stale_codes for code in warning_codes):
        return guard
    acknowledged = dict(guard)
    acknowledged["ok"] = True
    acknowledged["blockers"] = []
    acknowledged["sourceCollectionSnapshots"] = []
    acknowledged["operatorAcknowledgement"] = {
        "kind": "proven_stale_runtime_only",
        "warningCodes": sorted(set(warning_codes)),
        "warningCount": len(warnings),
    }
    acknowledged["warnings"] = [
        *warnings,
        {
            "code": "proven_stale_runtime_operator_acknowledged",
            "warningCodes": sorted(set(warning_codes)),
            "warningCount": len(warnings),
        },
    ]
    return acknowledged


def _marker_blockers(roots: _ResolvedRoots) -> tuple[list[dict[str, object]], Path | None, Path | None]:
    blockers: list[dict[str, object]] = []
    marker = roots.marker
    if not marker.is_file():
        blockers.append({"code": "global_storage_marker_missing", "path": str(marker)})
    elif not storage_migration_complete(roots.project):
        blockers.append({"code": "global_storage_marker_invalid", "path": str(marker)})
    active_root: Path | None = None
    try:
        active = resolve_active_project_storage_paths(
            roots.project.project_root,
            projects_home=roots.project.projects_home,
        )
        active_root = active.data.resolve()
        if active_root != roots.project.data.resolve():
            blockers.append(
                {
                    "code": "canonical_active_root_mismatch",
                    "expected": str(roots.project.data),
                    "observed": str(active.data),
                }
            )
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        blockers.append({"code": "canonical_active_root_unreadable", "detail": type(exc).__name__})
    return blockers, marker if marker.exists() else None, active_root


def _enumerate_source(
    roots: _ResolvedRoots,
) -> tuple[list[ResearchWorkflowAsset], list[str], list[dict[str, object]], list[dict[str, object]]]:
    assets: list[ResearchWorkflowAsset] = []
    excluded: list[str] = []
    blockers: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    if not roots.source.exists():
        blockers.append({"code": "source_missing", "path": str(roots.source)})
        return assets, excluded, blockers, warnings
    bad_links = _check_reparse_tree(roots.source)
    blockers.extend({"code": "reparse_or_symlink", "path": item} for item in bad_links)
    files = sorted((item for item in roots.source.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower())
    for path in files:
        relative = path.relative_to(roots.source).as_posix()
        if _is_reparse(path):
            blockers.append({"code": "reparse_or_symlink", "relativePath": relative})
            continue
        if _is_excluded(relative):
            excluded.append(relative)
            continue
        if relative == LEGACY_PLACEHOLDER_FILENAME and _legacy_placeholder_is_empty(path):
            excluded.append(relative)
            warnings.append(
                {
                    "code": "legacy_placeholder_excluded",
                    "relativePath": relative,
                    "detail": "known zero-byte legacy placeholder with no SQLite sidecar",
                }
            )
            continue
            # Keep the generic unknown-asset blocker for non-empty legacy
            # files.  A sidecar is separately reported as an orphan source
            # bundle member below, so no unsafe legacy content is silently
            # accepted.
        kind = _allowed_kind(relative)
        if kind is None:
            sidecar_main = _sqlite_main_for_sidecar(relative)
            if sidecar_main is not None:
                main_path = roots.source / Path(sidecar_main)
                if _allowed_kind(sidecar_main) == "sqlite" and main_path.is_file():
                    # Included in the SQLite bundle fingerprint; never copied separately.
                    continue
                if sidecar_main:
                    blockers.append({"code": "orphan_source_sqlite_sidecar", "relativePath": relative})
                    continue
            blockers.append({"code": "unknown_asset", "relativePath": relative})
            continue
        try:
            assets.append(_make_asset(roots.source, roots.target, relative, kind))
        except _SQLiteBundleSnapshotError as exc:
            blockers.append(
                {
                    "code": exc.code,
                    "relativePath": relative,
                    "detail": exc.detail,
                }
            )
        except (OSError, apsw.Error) as exc:
            blockers.append({"code": "source_asset_unreadable", "relativePath": relative, "detail": type(exc).__name__})
    return assets, sorted(set(excluded)), blockers, warnings


def _target_asset_state(
    asset: ResearchWorkflowAsset,
    *,
    allow_replaceable_empty_target: bool = False,
) -> tuple[str, dict[str, object]]:
    target = asset.target_path
    sidecars = _sqlite_bundle_paths(target)[1:] if asset.kind == "sqlite" else ()
    if asset.kind == "sqlite":
        for role, member in zip(("main", "wal", "shm"), _sqlite_bundle_paths(target), strict=True):
            if _path_entry_exists(member) and (_is_reparse(member) or not member.is_file()):
                return "conflict", {
                    "code": "target_sqlite_bundle_member_unsafe",
                    "path": str(member),
                    "role": role,
                }
    if asset.kind == "sqlite" and target.is_file() and target.stat().st_size == 0:
        if target.name == CHECKPOINT_FILENAME and not any(_path_entry_exists(path) for path in sidecars):
            return "empty-placeholder", {
                "code": "target_empty_sqlite_main",
                "path": str(target),
                "replaceable": True,
            }
        return "conflict", {"code": "target_empty_sqlite_main", "path": str(target)}
    if asset.kind == "sqlite" and any(_path_entry_exists(path) for path in sidecars):
        if target.name == LEDGER_FILENAME and target.is_file() and allow_replaceable_empty_target:
            unsafe_sidecar = next((path for path in sidecars if _is_reparse(path)), None)
            wal_path = target.with_name(target.name + "-wal")
            wal_size = int(wal_path.stat().st_size) if wal_path.is_file() else 0
            if unsafe_sidecar is None and wal_size == 0:
                evidence = _sqlite_evidence(target, kind="ledger")
                target_ledger_valid, _target_ledger_detail = _validate_v5_ledger(target)
                source_schema_contract = _ledger_schema_contract_digest(asset.source_path)
                target_schema_contract = _ledger_schema_contract_digest(target)
                if (
                    evidence.valid
                    and evidence.known_schema
                    and evidence.business_rows == 0
                    and asset.sqlite is not None
                    and evidence.schema_version == asset.sqlite.schema_version
                    and target_ledger_valid
                    and target_schema_contract == source_schema_contract
                ):
                    return "empty-schema", {
                        "code": "replaceable_empty_target_bundle",
                        "path": str(target),
                        "sqlite": evidence.to_dict(),
                    }
        return "conflict", {"code": "orphan_or_active_target_sqlite_sidecar", "path": str(target)}
    if _is_reparse(target):
        return "conflict", {"code": "target_reparse_or_symlink", "path": str(target)}
    if not target.exists():
        return "missing", {}
    if target.is_dir():
        return "conflict", {"code": "target_asset_is_directory", "path": str(target)}
    target_sha = _sha256_file(target)
    if target_sha == asset.sha256 and asset.kind != "sqlite":
        return "same", {"sha256": target_sha}
    if asset.kind == "sqlite":
        kind = "ledger" if target.name == LEDGER_FILENAME else "checkpoint"
        evidence = _sqlite_evidence(target, kind=kind)
        if target_sha == asset.sha256:
            return "same", {"sha256": target_sha, "sqlite": evidence.to_dict()}
        if (
            asset.sqlite is not None
            and evidence.valid
            and evidence.known_schema
            and asset.sqlite.schema_version == evidence.schema_version
            and asset.sqlite.schema_digest == evidence.schema_digest
            and evidence.business_rows == 0
        ):
            return "empty-schema", {"sha256": target_sha, "sqlite": evidence.to_dict()}
        return "conflict", {
            "code": "target_sqlite_conflict",
            "path": str(target),
            "schemaVersion": evidence.schema_version,
            "businessRows": evidence.business_rows,
            "schemaDigest": evidence.schema_digest,
        }
    return "conflict", {"code": "target_json_hash_conflict", "path": str(target)}


def _source_asset_blockers(asset: ResearchWorkflowAsset) -> list[dict[str, object]]:
    if asset.kind != "sqlite" or asset.sqlite is None:
        return []
    evidence = asset.sqlite
    blockers: list[dict[str, object]] = []
    if asset.size == 0:
        blockers.append(
            {
                "code": "sqlite_empty_main",
                "relativePath": asset.relative_path,
                "bundle": evidence.to_dict(),
            }
        )
        return blockers
    if not evidence.valid:
        blockers.append({"code": "sqlite_integrity_failed", "relativePath": asset.relative_path, "sqlite": evidence.to_dict()})
    if asset.relative_path == LEDGER_FILENAME:
        # The v5 checksum row is part of the migration history of every
        # ledger at schema version >= 5; a tampered or unknown value must be
        # rejected regardless of how far the schema has advanced since.
        if evidence.schema_version is not None and evidence.schema_version >= 5:
            try:
                accepted, detail = _validate_v5_ledger(asset.source_path)
            except _SQLiteBundleSnapshotError as exc:
                blockers.append(
                    {
                        "code": exc.code,
                        "relativePath": asset.relative_path,
                        "detail": exc.detail,
                    }
                )
                accepted, detail = False, ""
            if not accepted and detail:
                blockers.append({"code": detail, "relativePath": asset.relative_path})
        if evidence.schema_version != CURRENT_LEDGER_SCHEMA_VERSION:
            blockers.append(
                {
                    "code": "ledger_schema_mismatch",
                    "relativePath": asset.relative_path,
                    "sourceSchemaVersion": evidence.schema_version,
                    "targetSchemaVersion": CURRENT_LEDGER_SCHEMA_VERSION,
                    "detail": "schema-aware conversion is not implicit",
                }
            )
        elif not evidence.known_schema:
            blockers.append({"code": "ledger_schema_unknown", "relativePath": asset.relative_path})
    elif not evidence.known_schema:
        blockers.append({"code": "checkpoint_schema_unknown", "relativePath": asset.relative_path})
    return blockers


def _observe_source_stability(
    roots: _ResolvedRoots,
    *,
    delay_seconds: float,
) -> tuple[str, str, bool]:
    before = _source_tree_fingerprint(roots.source)
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    after = _source_tree_fingerprint(roots.source)
    return before, after, before == after


def _build_preview(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
    sample_delay_seconds: float = 0.05,
    quiescence_probe: QuiescenceProbe | None = None,
) -> ResearchWorkflowMigrationResult:
    roots = _resolve_roots(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
    )
    blockers, marker, active_root = _marker_blockers(roots)
    blockers.extend(_promotion_journal_blockers(roots))
    blockers.extend(
        {"code": "source_reparse_or_symlink", "relativePath": item}
        for item in _check_reparse_tree(roots.source)
    )
    blockers.extend(
        {"code": "target_reparse_or_symlink", "relativePath": item}
        for item in _check_reparse_tree(roots.target)
    )
    if roots.target.is_dir():
        for path in roots.target.rglob("*"):
            # Keep the stale-stage guard for real migration leftovers, while
            # applying the same backup exclusion contract to hand-made
            # ``*.bak-*`` copies.  Checking only the filename is intentional:
            # the real staging directory is named ``migration`` and is itself
            # excluded from ordinary asset inventory.
            relative = path.relative_to(roots.target).as_posix()
            if _is_backup_path(relative):
                continue
            if path.is_file() and ".staging" in path.name and path.name.startswith("."):
                blockers.append(
                    {
                        "code": "stale_migration_staging_asset",
                        "relativePath": path.relative_to(roots.target).as_posix(),
                    }
                )
    raw_guard = quiescence_probe(roots.project.project_root) if quiescence_probe else _default_quiescence(roots.project.project_root)
    guard, guard_warnings = (
        _normalize_quiescence_guard(roots.project.project_root, raw_guard)
        if quiescence_probe
        else (raw_guard, [item for item in (raw_guard.get("warnings") or []) if isinstance(item, dict)])
    )
    if not guard.get("ok"):
        guard_blockers = guard.get("blockers")
        if isinstance(guard_blockers, list):
            blockers.extend(item for item in guard_blockers if isinstance(item, dict))
        else:
            blockers.append({"code": "runtime_quiescence_unknown", "evidence": guard})
    assets, excluded, source_blockers, source_warnings = _enumerate_source(roots)
    blockers.extend(source_blockers)
    for asset in assets:
        try:
            blockers.extend(_source_asset_blockers(asset))
            state, detail = _target_asset_state(
                asset,
                allow_replaceable_empty_target=bool(guard.get("ok")),
            )
            if state == "conflict":
                blockers.append(detail)
        except _SQLiteBundleSnapshotError as exc:
            blockers.append(
                {
                    "code": exc.code,
                    "relativePath": asset.relative_path,
                    "detail": exc.detail,
                }
            )
    before, after, stable = _observe_source_stability(roots, delay_seconds=sample_delay_seconds)
    if not stable:
        blockers.append({"code": "source_changed_during_sampling", "before": before, "after": after})
    scope_hygiene = _scope_hygiene(roots.target)
    return ResearchWorkflowMigrationResult(
        source_root=roots.source,
        target_root=roots.target,
        allowed_assets=_ALLOWED_ASSETS,
        excluded_assets=tuple(excluded),
        entries=tuple(assets),
        blockers=tuple(blockers),
        warnings=(*source_warnings, *guard_warnings),
        source_fingerprint=after,
        target_fingerprint=_source_tree_fingerprint(roots.target),
        marker_path=marker,
        active_root=active_root,
        scope_hygiene=scope_hygiene,
    )


def preview_research_workflow_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
    sample_delay_seconds: float = 0.05,
    quiescence_probe: QuiescenceProbe | None = None,
) -> ResearchWorkflowMigrationResult:
    """Read-only inventory and fail-closed readiness preview."""

    return _build_preview(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
        sample_delay_seconds=sample_delay_seconds,
        quiescence_probe=quiescence_probe,
    )


def _asset_target_observation(asset: ResearchWorkflowAsset) -> dict[str, object]:
    target = asset.target_path
    if asset.kind == "sqlite":
        bundle, members = _sqlite_bundle_snapshot(target)
        if not bool(members[0]["present"]):
            if any(bool(member["present"]) for member in members[1:]):
                raise ResearchWorkflowMigrationError(
                    f"target SQLite main disappeared with sidecar delta: {asset.relative_path}"
                )
            return {
                "exists": False,
                "sha256": "",
                "size": 0,
                "bundleFingerprint": bundle,
                "bundleMembers": list(members),
            }
    if not target.is_file():
        return {"exists": False, "sha256": "", "size": 0, "bundleFingerprint": ""}
    sha = _sha256_file(target)
    bundle = ""
    bundle_members: tuple[dict[str, object], ...] = ()
    sqlite: dict[str, object] | None = None
    if asset.kind == "sqlite":
        bundle, bundle_members = _sqlite_bundle_snapshot(target)
        sqlite_kind = "ledger" if target.name == LEDGER_FILENAME else "checkpoint"
        sqlite = _sqlite_evidence(target, kind=sqlite_kind).to_dict()
    observation: dict[str, object] = {
        "exists": True,
        "sha256": sha,
        "size": int(target.stat().st_size),
        "bundleFingerprint": bundle,
    }
    if sqlite is not None:
        observation["sqlite"] = sqlite
        observation["bundleMembers"] = list(bundle_members)
    return observation


def _target_excluded_snapshot(
    target_root: Path,
    excluded: Iterable[str],
    *,
    source_root: Path,
    source_fingerprint: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative in sorted(set(excluded)):
        path = target_root / Path(relative)
        if not path.is_file() or _is_reparse(path):
            row: dict[str, object] = {"relativePath": relative, "exists": False, "sha256": ""}
        else:
            row = {
                "relativePath": relative,
                "exists": True,
                "sha256": _sha256_file(path),
                "size": int(path.stat().st_size),
            }
        if relative == LEGACY_PLACEHOLDER_FILENAME:
            source = source_root / relative
            if not _legacy_placeholder_is_empty(source) or _is_reparse(source):
                raise ResearchWorkflowMigrationError("legacy placeholder changed before manifest write")
            row.update(
                {
                    "classification": "legacy_placeholder_excluded",
                    "sourceEvidence": {
                        "exists": True,
                        "size": 0,
                        "sha256": _sha256_file(source),
                        "noSidecars": True,
                        "sourceFingerprint": source_fingerprint,
                    },
                }
            )
        result.append(row)
    return result


def _manifest_excluded_evidence_failures(
    payload: dict[str, object],
    roots: _ResolvedRoots,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    raw = payload.get("excludedAssets")
    if not isinstance(raw, list):
        return [{"code": "excluded_asset_evidence_missing"}]
    for item in raw:
        if not isinstance(item, dict) or item.get("classification") != "legacy_placeholder_excluded":
            continue
        relative = str(item.get("relativePath") or "")
        evidence = item.get("sourceEvidence")
        source = roots.source / Path(relative)
        valid_shape = (
            relative == LEGACY_PLACEHOLDER_FILENAME
            and isinstance(evidence, dict)
            and evidence.get("exists") is True
            and evidence.get("size") == 0
            and evidence.get("noSidecars") is True
            and _is_sha256(evidence.get("sha256"))
            and str(evidence.get("sourceFingerprint") or "") == str(payload.get("sourceFingerprint") or "")
        )
        if (
            not valid_shape
            or not _legacy_placeholder_is_empty(source)
            or _is_reparse(source)
            or _sha256_file(source) != str(evidence.get("sha256") if isinstance(evidence, dict) else "")
        ):
            failures.append(
                {
                    "code": "excluded_legacy_placeholder_changed",
                    "relativePath": relative,
                }
            )
    warnings = payload.get("warnings")
    warning_rows = [item for item in warnings if isinstance(item, dict)] if isinstance(warnings, list) else []
    warned = any(str(item.get("code") or "") == "legacy_placeholder_excluded" for item in warning_rows)
    evidenced = any(
        isinstance(item, dict) and item.get("classification") == "legacy_placeholder_excluded"
        for item in raw
    )
    if warned != evidenced:
        failures.append({"code": "excluded_legacy_placeholder_evidence_inconsistent"})
    return failures


def _assert_manifest_excluded_evidence(payload: dict[str, object], roots: _ResolvedRoots) -> None:
    failures = _manifest_excluded_evidence_failures(payload, roots)
    if failures:
        raise ResearchWorkflowMigrationError(
            "legacy placeholder evidence changed: "
            + ", ".join(str(item.get("code") or "invalid") for item in failures)
        )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    if _is_reparse(path) or _is_reparse(path.parent):
        raise ResearchWorkflowMigrationError(f"atomic JSON path is unsafe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Windows' CRT rejects ``os.fsync`` on a read-only descriptor even
        # though the file can be opened successfully.  Reopen the promoted
        # journal read/write so the durability barrier works on every
        # supported platform.
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_persistent_file(path: Path) -> None:
    if not _path_entry_exists(path):
        return
    if _is_reparse(path) or not path.is_file():
        raise ResearchWorkflowMigrationError(f"persistent state path is unsafe: {path}")
    path.unlink()
    _fsync_directory(path.parent)


def _kind_member_paths(base: Path, kind: str) -> tuple[tuple[str, Path], ...]:
    if kind == "sqlite":
        return tuple(zip(("main", "wal", "shm"), _sqlite_bundle_paths(base), strict=True))
    return (("main", base),)


def _member_rows(base: Path, *, kind: str) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for role, path in _kind_member_paths(base, kind):
        if _path_entry_exists(path) and (_is_reparse(path) or not path.is_file()):
            raise ResearchWorkflowMigrationError(f"migration member is unsafe: {path}")
        present = path.is_file()
        rows.append(
            {
                "role": role,
                "present": present,
                "size": int(path.stat().st_size) if present else 0,
                "sha256": _sha256_file(path) if present else "",
            }
        )
    return tuple(rows)


def _member_rows_fingerprint(rows: Iterable[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        for key in ("role", "present", "size", "sha256"):
            digest.update(str(row.get(key, "")).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _member_rows_match(base: Path, *, kind: str, expected: Iterable[dict[str, object]]) -> bool:
    expected_rows = tuple(dict(item) for item in expected)
    return _member_rows(base, kind=kind) == expected_rows


def _promotion_journal_path(roots: _ResolvedRoots) -> Path:
    path = roots.target.parent / _PROMOTION_JOURNAL_FILENAME
    if path.parent.resolve() != roots.target.parent.resolve() or _is_reparse(path.parent):
        raise ResearchWorkflowMigrationError(f"promotion journal parent is unsafe: {path.parent}")
    return path


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _copy_sqlite_with_backup_open_path(source: Path, destination: Path) -> None:
    """Copy one already-isolated SQLite image with APSW's Backup API.

    ``destination`` must not exist.  The call creates a private staging or
    backup database and never copies ``-wal``/``-shm`` as ordinary files.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection: apsw.Connection | None = None
    destination_connection: apsw.Connection | None = None
    backup: apsw.Backup | None = None
    try:
        source_connection = _open_readonly(source)
        destination_connection = apsw.Connection(str(destination))
        backup = destination_connection.backup("main", source_connection, "main")
        while not backup.step(-1):
            time.sleep(0.005)
        backup.finish()
        backup = None
    except apsw.Error as exc:
        raise ResearchWorkflowMigrationError(
            f"APSW SQLite backup failed: {source} -> {destination}: {exc}"
        ) from exc
    finally:
        if backup is not None:
            try:
                backup.finish()
            except apsw.Error:
                pass
        if source_connection is not None:
            source_connection.close()
        if destination_connection is not None:
            destination_connection.close()


def _copy_sqlite_with_backup(source: Path, destination: Path) -> None:
    """Copy one SQLite bundle without opening a real source in place."""

    if source.stat().st_size == 0:
        raise ResearchWorkflowMigrationError(
            f"empty SQLite main is not migratable: {source}"
        )
    if source.stat().st_size > 0:
        with _sqlite_bundle_snapshot_context(source) as snapshot:
            _copy_sqlite_with_backup_open_path(snapshot, destination)
        return
    _copy_sqlite_with_backup_open_path(source, destination)


def _copy_asset(source: Path, destination: Path, *, kind: str) -> None:
    if destination.exists():
        raise ResearchWorkflowMigrationError(f"staging destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "sqlite" and source.stat().st_size == 0:
        raise ResearchWorkflowMigrationError(
            f"empty SQLite main is not migratable: {source}"
        )
    if kind == "sqlite" and source.stat().st_size > 0:
        _copy_sqlite_with_backup(source, destination)
    else:
        shutil.copy2(source, destination)


def _copy_sqlite_bundle_archive(
    source: Path,
    destination: Path,
    *,
    allow_empty_main: bool = False,
) -> None:
    """Copy a complete SQLite main/WAL/SHM image for a before/after archive."""

    if not source.is_file() or _is_reparse(source):
        raise ResearchWorkflowMigrationError(f"SQLite archive source is missing or unsafe: {source}")
    before_fingerprint, before_members = _sqlite_bundle_snapshot(source)
    if source.stat().st_size == 0 and not allow_empty_main:
        raise ResearchWorkflowMigrationError(f"empty SQLite main is not archivable: {source}")
    for destination_member in _sqlite_bundle_paths(destination):
        if _is_reparse(destination_member) or destination_member.exists():
            raise ResearchWorkflowMigrationError(f"SQLite archive destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Archives are byte-exact before/after images.  An APSW backup is correct
    # for producing a new canonical database, but it deliberately rewrites the
    # main image and can fold WAL pages into it.  That would lose the evidence
    # needed to restore the original bundle, so archive copies stay bytewise.
    shutil.copy2(source, destination)
    for source_member, destination_member in zip(
        _sqlite_bundle_paths(source)[1:],
        _sqlite_bundle_paths(destination)[1:],
        strict=True,
    ):
        if _is_reparse(source_member) or (source_member.exists() and not source_member.is_file()):
            raise ResearchWorkflowMigrationError(f"SQLite archive sidecar is missing or unsafe: {source_member}")
        if source_member.is_file():
            shutil.copy2(source_member, destination_member)
    after_fingerprint, after_members = _sqlite_bundle_snapshot(source)
    if before_fingerprint != after_fingerprint or before_members != after_members:
        raise _SQLiteBundleSnapshotError("sqlite_bundle_changed_during_archive", source.name)
    archive_fingerprint, archive_members = _sqlite_bundle_snapshot(destination)
    if archive_fingerprint != before_fingerprint or archive_members != before_members:
        raise ResearchWorkflowMigrationError(f"SQLite archive bundle mismatch: {source}")


def _finish_sqlite_bundle_promotion(stage: Path, target: Path) -> None:
    """Remove stale destination sidecars and promote staged sidecars."""

    _remove_sqlite_bundle_sidecars(target)
    for stage_sidecar in _sqlite_bundle_paths(stage)[1:]:
        if _is_reparse(stage_sidecar) or (stage_sidecar.exists() and not stage_sidecar.is_file()):
            raise ResearchWorkflowMigrationError(f"unsafe staged SQLite sidecar: {stage_sidecar}")
    for target_sidecar in _sqlite_bundle_paths(target)[1:]:
        if target_sidecar.exists():
            raise ResearchWorkflowMigrationError(f"SQLite target sidecar cleanup failed: {target_sidecar}")
    for stage_sidecar, target_sidecar in zip(
        _sqlite_bundle_paths(stage)[1:],
        _sqlite_bundle_paths(target)[1:],
        strict=True,
    ):
        if stage_sidecar.is_file():
            os.replace(stage_sidecar, target_sidecar)
    if any(path.exists() for path in _sqlite_bundle_paths(stage)[1:]):
        raise ResearchWorkflowMigrationError(f"staged SQLite sidecar cleanup failed: {stage}")


def _remove_sqlite_bundle_sidecars(target: Path) -> None:
    """Remove only regular task-governed SQLite sidecars from one target."""

    for target_sidecar in _sqlite_bundle_paths(target)[1:]:
        if not target_sidecar.exists() and not _is_reparse(target_sidecar):
            continue
        if _is_reparse(target_sidecar) or not target_sidecar.is_file():
            raise ResearchWorkflowMigrationError(f"unsafe SQLite target sidecar: {target_sidecar}")
        target_sidecar.unlink()


def _assert_under(path: Path, root: Path, *, label: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ResearchWorkflowMigrationError(f"{label} escapes its governed root: {path}") from exc


def _stage_path(path: Path, migration_id: str) -> Path:
    short_id = migration_id.rsplit("-", 1)[-1][:12]
    asset_id = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:6]
    return path.with_name(f".s-{short_id}-{asset_id}.staging")


def _archive_member_path(archive_root: Path, relative_path: str) -> Path:
    """Flatten one governed relative path into a short, collision-safe name."""

    relative = Path(relative_path)
    digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:12]
    basename = relative.name or "asset"
    suffix = relative.suffix
    if len(basename) > 32:
        basename = f"{basename[:24]}{suffix}"
    return archive_root / f"{digest}-{basename}"


def _archive_existing_target(asset: ResearchWorkflowAsset, archive_root: Path) -> _BeforeRecord:
    target = asset.target_path
    archive = _archive_member_path(archive_root, asset.relative_path)
    _assert_under(archive, archive_root, label="target-before archive")
    if not target.exists():
        return _BeforeRecord(
            relative_path=asset.relative_path,
            existed=False,
            kind=asset.kind,
            archive_path=str(archive),
        )
    if _is_reparse(target) or not target.is_file():
        raise ResearchWorkflowMigrationError(f"cannot archive unsafe target asset: {target}")
    if asset.kind == "sqlite":
        allow_empty = target.name == CHECKPOINT_FILENAME and target.stat().st_size == 0
        _copy_sqlite_bundle_archive(target, archive, allow_empty_main=allow_empty)
    else:
        _copy_asset(target, archive, kind=asset.kind)
    bundle = ""
    archive_bundle = ""
    if asset.kind == "sqlite":
        bundle, _ = _sqlite_bundle_snapshot(target)
        archive_bundle, _ = _sqlite_bundle_snapshot(archive)
    return _BeforeRecord(
        relative_path=asset.relative_path,
        existed=True,
        kind=asset.kind,
        archive_path=str(archive),
        sha256=_sha256_file(target),
        bundle_fingerprint=bundle,
        archive_sha256=_sha256_file(archive),
        archive_bundle_fingerprint=archive_bundle,
    )


def _cleanup_stages(staged: Iterable[Path]) -> None:
    for path in staged:
        candidates = (path, *_sqlite_bundle_paths(path)[1:])
        for candidate in candidates:
            try:
                if candidate.is_file() or candidate.is_symlink():
                    candidate.unlink()
            except OSError:
                continue


def _validate_staged_source_asset(asset: ResearchWorkflowAsset, stage: Path) -> None:
    if not stage.is_file():
        raise ResearchWorkflowMigrationError(f"staged asset missing: {asset.relative_path}")
    if asset.kind != "sqlite":
        if _sha256_file(stage) != asset.sha256:
            raise ResearchWorkflowMigrationError(f"staged asset hash mismatch: {asset.relative_path}")
        return
    if stage.stat().st_size == 0:
        raise ResearchWorkflowMigrationError(f"staged SQLite main is empty: {asset.relative_path}")
    kind = "ledger" if asset.relative_path == LEDGER_FILENAME else "checkpoint"
    evidence = _sqlite_evidence(stage, kind=kind)
    if not evidence.valid or not evidence.known_schema:
        raise ResearchWorkflowMigrationError(f"staged SQLite integrity failed: {asset.relative_path}")
    if asset.sqlite is not None and (
        evidence.schema_digest != asset.sqlite.schema_digest
        or evidence.row_counts != asset.sqlite.row_counts
        or evidence.key_runs != asset.sqlite.key_runs
    ):
        raise ResearchWorkflowMigrationError(f"staged SQLite evidence mismatch: {asset.relative_path}")


def _archive_path_for_before(before: _BeforeRecord, archive_root: Path) -> Path:
    raw_archive = str(before.archive_path or "")
    archive_candidate = Path(raw_archive).expanduser()
    if not raw_archive or not archive_candidate.is_absolute():
        raise ResearchWorkflowMigrationError(
            f"rollback archive evidence is not an absolute path: {before.relative_path}"
        )
    archive = archive_candidate.resolve()
    _assert_under(archive, archive_root, label="rollback archive")
    if not archive.is_file() or _is_reparse(archive):
        raise ResearchWorkflowMigrationError(f"rollback archive missing or unsafe: {archive}")
    if not before.archive_sha256:
        raise ResearchWorkflowMigrationError(f"rollback archive checksum missing: {before.relative_path}")
    if _sha256_file(archive) != before.archive_sha256:
        raise ResearchWorkflowMigrationError(f"rollback archive hash mismatch: {before.relative_path}")
    if before.kind == "sqlite":
        bundle, _ = _sqlite_bundle_snapshot(archive)
        if not before.archive_bundle_fingerprint or bundle != before.archive_bundle_fingerprint:
            raise ResearchWorkflowMigrationError(f"rollback archive bundle mismatch: {before.relative_path}")
        if archive.stat().st_size == 0:
            if before.relative_path != CHECKPOINT_FILENAME or any(
                path.exists() for path in _sqlite_bundle_paths(archive)[1:]
            ):
                raise ResearchWorkflowMigrationError(
                    f"rollback archive SQLite main is empty: {before.relative_path}"
                )
            return archive
        kind = "ledger" if before.relative_path == LEDGER_FILENAME else "checkpoint"
        evidence = _sqlite_evidence(archive, kind=kind)
        if not evidence.valid or not evidence.known_schema:
            raise ResearchWorkflowMigrationError(f"rollback archive SQLite integrity failed: {before.relative_path}")
    return archive


def _validate_staged_archive(archive: Path, stage: Path, *, kind: str, relative_path: str) -> None:
    if not stage.is_file():
        raise ResearchWorkflowMigrationError(f"rollback stage missing: {relative_path}")
    if kind != "sqlite":
        if _sha256_file(stage) != _sha256_file(archive):
            raise ResearchWorkflowMigrationError(f"rollback stage hash mismatch: {relative_path}")
        return
    expected_bundle, expected_members = _sqlite_bundle_snapshot(archive)
    observed_bundle, observed_members = _sqlite_bundle_snapshot(stage)
    if expected_bundle != observed_bundle or expected_members != observed_members:
        raise ResearchWorkflowMigrationError(f"rollback staged SQLite bundle mismatch: {relative_path}")
    if stage.stat().st_size == 0:
        if relative_path != CHECKPOINT_FILENAME or any(
            path.exists() for path in _sqlite_bundle_paths(stage)[1:]
        ):
            raise ResearchWorkflowMigrationError(f"rollback staged SQLite main is empty: {relative_path}")
        if _sha256_file(stage) != _sha256_file(archive):
            raise ResearchWorkflowMigrationError(f"rollback stage hash mismatch: {relative_path}")
        return
    sqlite_kind = "ledger" if relative_path == LEDGER_FILENAME else "checkpoint"
    expected = _sqlite_evidence(archive, kind=sqlite_kind)
    observed = _sqlite_evidence(stage, kind=sqlite_kind)
    if (
        not observed.valid
        or not observed.known_schema
        or observed.schema_digest != expected.schema_digest
        or observed.row_counts != expected.row_counts
        or observed.key_runs != expected.key_runs
    ):
        raise ResearchWorkflowMigrationError(f"rollback stage SQLite evidence mismatch: {relative_path}")


def _empty_member_rows(kind: str) -> tuple[dict[str, object], ...]:
    roles = ("main", "wal", "shm") if kind == "sqlite" else ("main",)
    return tuple(
        {"role": role, "present": False, "size": 0, "sha256": ""}
        for role in roles
    )


def _normalize_journal_member_rows(
    value: object,
    *,
    kind: str,
    label: str,
) -> tuple[dict[str, object], ...]:
    expected_roles = ("main", "wal", "shm") if kind == "sqlite" else ("main",)
    if not isinstance(value, list) or len(value) != len(expected_roles):
        raise ResearchWorkflowMigrationError(f"promotion journal {label} members are invalid")
    rows: list[dict[str, object]] = []
    for expected_role, raw in zip(expected_roles, value, strict=True):
        if not isinstance(raw, dict) or str(raw.get("role") or "") != expected_role:
            raise ResearchWorkflowMigrationError(f"promotion journal {label} member role is invalid")
        present = raw.get("present")
        size = raw.get("size")
        sha = raw.get("sha256")
        if not isinstance(present, bool) or type(size) is not int or int(size) < 0:
            raise ResearchWorkflowMigrationError(f"promotion journal {label} member metadata is invalid")
        if present:
            if not _is_sha256(sha):
                raise ResearchWorkflowMigrationError(f"promotion journal {label} member checksum is invalid")
        elif size != 0 or sha not in {"", None}:
            raise ResearchWorkflowMigrationError(f"promotion journal {label} absent member is inconsistent")
        rows.append(
            {
                "role": expected_role,
                "present": present,
                "size": int(size),
                "sha256": str(sha or ""),
            }
        )
    return tuple(rows)


def _journal_stage_path(raw_path: object, *, target: Path, target_root: Path) -> Path | None:
    text = str(raw_path or "")
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ResearchWorkflowMigrationError("promotion journal stage path is not absolute")
    stage = candidate.resolve(strict=False)
    _assert_under(stage, target_root, label="promotion journal stage")
    if stage.parent.resolve() != target.parent.resolve() or not stage.name.startswith(".s-") or not stage.name.endswith(".staging"):
        raise ResearchWorkflowMigrationError(f"promotion journal stage path is invalid: {stage}")
    return stage


def _read_promotion_journal(roots: _ResolvedRoots) -> dict[str, object]:
    path = _promotion_journal_path(roots)
    if not path.is_file() or _is_reparse(path):
        raise ResearchWorkflowMigrationError(f"promotion journal is missing or unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchWorkflowMigrationError(f"promotion journal is unreadable: {path}") from exc
    if not isinstance(payload, dict) or int(payload.get("schemaVersion") or 0) != _PROMOTION_JOURNAL_SCHEMA_VERSION:
        raise ResearchWorkflowMigrationError("promotion journal schema is unsupported")
    if str(payload.get("sourceRoot") or "") != str(roots.source) or str(payload.get("targetRoot") or "") != str(roots.target):
        raise ResearchWorkflowMigrationError("promotion journal root binding is invalid")
    operation = str(payload.get("operation") or "")
    if operation not in {"apply", "rollback"}:
        raise ResearchWorkflowMigrationError("promotion journal operation is invalid")
    migration_id = str(payload.get("migrationId") or "")
    if not migration_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in migration_id):
        raise ResearchWorkflowMigrationError("promotion journal migration id is invalid")
    if str(payload.get("status") or "") not in {"prepared", "recovered", "committed"}:
        raise ResearchWorkflowMigrationError("promotion journal status is invalid")
    manifest = Path(str(payload.get("manifestPath") or "")).expanduser()
    if not manifest.is_absolute():
        raise ResearchWorkflowMigrationError("promotion journal manifest path is invalid")
    _assert_under(manifest.resolve(strict=False), roots.target / MANIFEST_DIRNAME, label="promotion journal manifest")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ResearchWorkflowMigrationError("promotion journal entries are invalid")
    seen: set[str] = set()
    backup_root = roots.target.parent / _BACKUP_DIRNAME
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ResearchWorkflowMigrationError("promotion journal entry is invalid")
        relative = str(raw.get("relativePath") or "")
        kind = str(raw.get("kind") or "")
        if relative in seen or _allowed_kind(relative) != kind:
            raise ResearchWorkflowMigrationError(f"promotion journal entry is outside allowlist: {relative}")
        target = roots.target / Path(relative)
        _assert_under(target, roots.target, label="promotion journal target")
        _journal_stage_path(raw.get("stagePath"), target=target, target_root=roots.target)
        archive = Path(str(raw.get("recoveryArchivePath") or "")).expanduser()
        if not archive.is_absolute():
            raise ResearchWorkflowMigrationError(f"promotion journal recovery archive is invalid: {relative}")
        _assert_under(archive.resolve(strict=False), backup_root, label="promotion journal recovery archive")
        before = raw.get("targetBefore")
        staged_after = raw.get("stagedAfter")
        if not isinstance(before, dict) or not isinstance(staged_after, dict):
            raise ResearchWorkflowMigrationError(f"promotion journal member evidence is missing: {relative}")
        _normalize_journal_member_rows(before.get("members"), kind=kind, label="target-before")
        _normalize_journal_member_rows(staged_after.get("members"), kind=kind, label="staged-after")
        seen.add(relative)
    return payload


def _promotion_journal_blockers(roots: _ResolvedRoots) -> list[dict[str, object]]:
    try:
        path = _promotion_journal_path(roots)
    except ResearchWorkflowMigrationError as exc:
        return [{"code": "promotion_journal_path_unsafe", "detail": str(exc)}]
    if not _path_entry_exists(path):
        return []
    try:
        payload = _read_promotion_journal(roots)
    except ResearchWorkflowMigrationError as exc:
        return [{"code": "promotion_journal_unreadable", "path": str(path), "detail": str(exc)}]
    return [
        {
            "code": "unfinished_promotion_journal",
            "path": str(path),
            "operation": str(payload.get("operation") or ""),
            "migrationId": str(payload.get("migrationId") or ""),
            "status": str(payload.get("status") or ""),
        }
    ]


def _build_journal_entry(
    *,
    relative: str,
    kind: str,
    target: Path,
    stage: Path | None,
    recovery_archive: Path,
) -> dict[str, object]:
    target_before = _member_rows(target, kind=kind)
    archive_rows = _member_rows(recovery_archive, kind=kind)
    if archive_rows != target_before:
        raise ResearchWorkflowMigrationError(f"promotion recovery archive mismatch: {relative}")
    staged_after = _member_rows(stage, kind=kind) if stage is not None else _empty_member_rows(kind)
    return {
        "relativePath": relative,
        "kind": kind,
        "stagePath": str(stage) if stage is not None else "",
        "recoveryArchivePath": str(recovery_archive),
        "targetBefore": {
            "exists": bool(target_before[0]["present"]),
            "sha256": str(target_before[0]["sha256"]),
            "fingerprint": _member_rows_fingerprint(target_before),
            "members": list(target_before),
        },
        "stagedAfter": {
            "fingerprint": _member_rows_fingerprint(staged_after),
            "members": list(staged_after),
        },
    }


def _write_promotion_journal(
    roots: _ResolvedRoots,
    *,
    operation: str,
    migration_id: str,
    manifest_path: Path,
    entries: Iterable[dict[str, object]],
    guard: dict[str, object],
) -> dict[str, object]:
    path = _promotion_journal_path(roots)
    if _path_entry_exists(path):
        raise ResearchWorkflowMigrationError(f"unfinished promotion journal already exists: {path}")
    payload: dict[str, object] = {
        "schemaVersion": _PROMOTION_JOURNAL_SCHEMA_VERSION,
        "status": "prepared",
        "operation": operation,
        "migrationId": migration_id,
        "sourceRoot": str(roots.source),
        "targetRoot": str(roots.target),
        "manifestPath": str(manifest_path),
        "entries": list(entries),
        "guardEvidence": _json_safe(guard),
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }
    _atomic_json(path, payload)
    return payload


def _operation_stage_paths(payload: dict[str, object], roots: _ResolvedRoots) -> list[Path]:
    result: list[Path] = []
    for raw in payload.get("entries") or []:
        if not isinstance(raw, dict):
            continue
        relative = str(raw.get("relativePath") or "")
        target = roots.target / Path(relative)
        stage = _journal_stage_path(raw.get("stagePath"), target=target, target_root=roots.target)
        if stage is not None:
            result.append(stage)
    return result


def _journal_targets_match(payload: dict[str, object], roots: _ResolvedRoots, *, phase: str) -> bool:
    evidence_key = "targetBefore" if phase == "before" else "stagedAfter"
    for raw in payload.get("entries") or []:
        if not isinstance(raw, dict):
            return False
        relative = str(raw.get("relativePath") or "")
        kind = str(raw.get("kind") or "")
        evidence = raw.get(evidence_key)
        if not isinstance(evidence, dict):
            return False
        expected = _normalize_journal_member_rows(evidence.get("members"), kind=kind, label=evidence_key)
        if not _member_rows_match(roots.target / Path(relative), kind=kind, expected=expected):
            return False
    return True


def _journal_recovery_actions(
    payload: dict[str, object],
    roots: _ResolvedRoots,
) -> dict[str, bool]:
    """Classify every target before compensation writes begin.

    A target may still be the recorded before-image when the process crashed
    before promoting that entry, or it may be the exact staged after-image
    when promotion completed.  Any third state is an external/concurrent
    delta.  Recovery must then leave every target and the journal untouched.
    """

    actions: dict[str, bool] = {}
    for raw in payload.get("entries") or []:
        if not isinstance(raw, dict):
            raise ResearchWorkflowMigrationError("promotion journal entry is invalid")
        relative = str(raw.get("relativePath") or "")
        kind = str(raw.get("kind") or "")
        before = raw.get("targetBefore")
        after = raw.get("stagedAfter")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ResearchWorkflowMigrationError(f"journal recovery evidence is invalid: {relative}")
        before_rows = _normalize_journal_member_rows(
            before.get("members"),
            kind=kind,
            label="target-before",
        )
        after_rows = _normalize_journal_member_rows(
            after.get("members"),
            kind=kind,
            label="staged-after",
        )
        current_rows = _member_rows(roots.target / Path(relative), kind=kind)
        if current_rows == before_rows:
            actions[relative] = False
        elif current_rows == after_rows:
            actions[relative] = True
        else:
            raise ResearchWorkflowMigrationError(
                f"journal recovery target delta blocks compensation: {relative}"
            )
    return actions


def _completed_manifest_matches_journal(payload: dict[str, object], roots: _ResolvedRoots) -> bool:
    manifest = Path(str(payload.get("manifestPath") or ""))
    if not manifest.is_file() or _is_reparse(manifest):
        return False
    manifest_payload = _read_manifest(manifest)
    if str(manifest_payload.get("migrationId") or "") != str(payload.get("migrationId") or ""):
        return False
    operation = str(payload.get("operation") or "")
    status = str(manifest_payload.get("status") or "")
    expected_statuses = {"completed", "committed"} if operation == "apply" else {"rolled_back"}
    if status not in expected_statuses:
        return False
    _assert_manifest_root_binding(manifest_payload, roots)
    if operation == "apply":
        for item in _manifest_entries(manifest_payload, roots.target):
            _validate_post_cutover_target(item, roots.target / Path(str(item["relativePath"])))
        _assert_manifest_excluded_evidence(manifest_payload, roots)
    if not _journal_targets_match(payload, roots, phase="after"):
        raise ResearchWorkflowMigrationError(
            "completed migration manifest does not match journal target-after evidence"
        )
    return True


def _conditional_remove_operation_member(path: Path, expected_after: dict[str, object]) -> None:
    if not _path_entry_exists(path):
        return
    if _is_reparse(path) or not path.is_file():
        raise ResearchWorkflowMigrationError(f"journal recovery target member is unsafe: {path}")
    if not bool(expected_after.get("present")):
        raise ResearchWorkflowMigrationError(
            f"journal recovery refuses to delete a non-operation target member: {path}"
        )
    if int(path.stat().st_size) != int(expected_after.get("size") or 0) or _sha256_file(path) != str(
        expected_after.get("sha256") or ""
    ):
        raise ResearchWorkflowMigrationError(
            f"journal recovery target member identity changed: {path}"
        )
    path.unlink()


def _restore_entry_from_journal(
    raw: dict[str, object],
    *,
    roots: _ResolvedRoots,
    recovery_stage: Path | None,
) -> None:
    relative = str(raw["relativePath"])
    kind = str(raw["kind"])
    target = roots.target / Path(relative)
    before = raw["targetBefore"]
    after = raw["stagedAfter"]
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ResearchWorkflowMigrationError(f"journal recovery evidence is invalid: {relative}")
    before_rows = _normalize_journal_member_rows(before.get("members"), kind=kind, label="target-before")
    after_rows = _normalize_journal_member_rows(after.get("members"), kind=kind, label="staged-after")
    if _member_rows(target, kind=kind) != after_rows:
        raise ResearchWorkflowMigrationError(
            f"journal recovery target delta blocks compensation: {relative}"
        )
    before_by_role = {str(item["role"]): item for item in before_rows}
    after_by_role = {str(item["role"]): item for item in after_rows}
    if before_by_role["main"]["present"]:
        if recovery_stage is None:
            raise ResearchWorkflowMigrationError(f"journal recovery stage is missing: {relative}")
        os.replace(recovery_stage, target)
        for role, target_member in _kind_member_paths(target, kind):
            if role == "main":
                continue
            stage_member = dict(_kind_member_paths(recovery_stage, kind))[role]
            if before_by_role[role]["present"]:
                os.replace(stage_member, target_member)
            else:
                _conditional_remove_operation_member(target_member, after_by_role[role])
        return
    for role, target_member in _kind_member_paths(target, kind):
        _conditional_remove_operation_member(target_member, after_by_role[role])


def _recover_promotion_journal(payload: dict[str, object], roots: _ResolvedRoots) -> None:
    backup_root = roots.target.parent / _BACKUP_DIRNAME
    recovery_stages: dict[str, Path] = {}
    try:
        for raw in payload.get("entries") or []:
            if not isinstance(raw, dict):
                raise ResearchWorkflowMigrationError("promotion journal entry is invalid")
            relative = str(raw["relativePath"])
            kind = str(raw["kind"])
            target = roots.target / Path(relative)
            before = raw.get("targetBefore")
            if not isinstance(before, dict):
                raise ResearchWorkflowMigrationError(f"journal target-before evidence is invalid: {relative}")
            before_rows = _normalize_journal_member_rows(before.get("members"), kind=kind, label="target-before")
            archive = Path(str(raw.get("recoveryArchivePath") or "")).resolve(strict=False)
            _assert_under(archive, backup_root, label="journal recovery archive")
            if before_rows[0]["present"]:
                if not archive.is_file() or _is_reparse(archive):
                    raise ResearchWorkflowMigrationError(f"journal recovery archive is missing: {relative}")
                if _member_rows(archive, kind=kind) != before_rows:
                    raise ResearchWorkflowMigrationError(f"journal recovery archive changed: {relative}")
                stage = _stage_path(target, f"jr-{uuid.uuid4().hex[:12]}")
                if kind == "sqlite":
                    _copy_sqlite_bundle_archive(
                        archive,
                        stage,
                        allow_empty_main=relative == CHECKPOINT_FILENAME,
                    )
                else:
                    _copy_asset(archive, stage, kind=kind)
                if _member_rows(stage, kind=kind) != before_rows:
                    raise ResearchWorkflowMigrationError(f"journal recovery stage mismatch: {relative}")
                recovery_stages[relative] = stage
            elif any(bool(item["present"]) for item in before_rows):
                raise ResearchWorkflowMigrationError(f"journal recovery before-image is inconsistent: {relative}")
        recovery_actions = _journal_recovery_actions(payload, roots)
        for raw in payload.get("entries") or []:
            if not isinstance(raw, dict):
                continue
            relative = str(raw["relativePath"])
            if not recovery_actions[relative]:
                continue
            _restore_entry_from_journal(
                raw,
                roots=roots,
                recovery_stage=recovery_stages.get(relative),
            )
        if not _journal_targets_match(payload, roots, phase="before"):
            raise ResearchWorkflowMigrationError("journal recovery verification failed")
        recovered = dict(payload)
        recovered.update({"status": "recovered", "recoveredAt": _now_iso(), "updatedAt": _now_iso()})
        _atomic_json(_promotion_journal_path(roots), recovered)
        _cleanup_stages(_operation_stage_paths(payload, roots))
        _remove_persistent_file(_promotion_journal_path(roots))
    finally:
        _cleanup_stages(recovery_stages.values())


def _recover_existing_promotion_journal(
    roots: _ResolvedRoots,
    *,
    quiescence_probe: QuiescenceProbe | None,
) -> dict[str, object] | None:
    path = _promotion_journal_path(roots)
    if not _path_entry_exists(path):
        return None
    _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    payload = _read_promotion_journal(roots)
    if str(payload.get("status") or "") == "recovered":
        if not _journal_targets_match(payload, roots, phase="before"):
            raise ResearchWorkflowMigrationError("recovered promotion journal target verification failed")
        _cleanup_stages(_operation_stage_paths(payload, roots))
        _remove_persistent_file(path)
        return {"action": "recovered_cleanup"}
    if _completed_manifest_matches_journal(payload, roots):
        committed = dict(payload)
        committed.update({"status": "committed", "committedAt": _now_iso(), "updatedAt": _now_iso()})
        _atomic_json(path, committed)
        _cleanup_stages(_operation_stage_paths(payload, roots))
        _remove_persistent_file(path)
        return {"action": "committed_cleanup"}
    _recover_promotion_journal(payload, roots)
    return {"action": "recovered"}


def _finalize_successful_promotion_journal(payload: dict[str, object], roots: _ResolvedRoots) -> None:
    if not _completed_manifest_matches_journal(payload, roots):
        raise ResearchWorkflowMigrationError("promotion journal success verification failed")
    committed = dict(payload)
    committed.update({"status": "committed", "committedAt": _now_iso(), "updatedAt": _now_iso()})
    path = _promotion_journal_path(roots)
    _atomic_json(path, committed)
    _cleanup_stages(_operation_stage_paths(payload, roots))
    _remove_persistent_file(path)


def _stage_rollback_plans(
    plans: Iterable[_RollbackPlan],
    *,
    stage_id: str,
    backup_root: Path,
    before_archive_root: Path | None = None,
) -> dict[str, Path]:
    """Archive post-cutover targets and stage every before-image without writing targets."""

    plans = list(plans)
    stages: dict[str, Path] = {}
    try:
        for plan in plans:
            _assert_under(plan.after_archive, backup_root, label="rollback target-after archive")
            _copy_current_for_rollback(
                plan.target,
                plan.after_archive,
                kind=str(plan.entry["kind"]),
                relative_path=str(plan.entry["relativePath"]),
            )
        for plan in plans:
            if not plan.before.existed:
                continue
            archive = _archive_path_for_before(
                plan.before,
                before_archive_root if before_archive_root is not None else backup_root,
            )
            stage = _stage_path(plan.target, stage_id)
            kind = str(plan.entry["kind"])
            if kind == "sqlite":
                _copy_sqlite_bundle_archive(
                    archive,
                    stage,
                    allow_empty_main=str(plan.entry["relativePath"]) == CHECKPOINT_FILENAME,
                )
            else:
                _copy_asset(archive, stage, kind=kind)
            _validate_staged_archive(
                archive,
                stage,
                kind=kind,
                relative_path=str(plan.entry["relativePath"]),
            )
            stages[str(plan.entry["relativePath"])] = stage
    except Exception:
        _cleanup_stages(stages.values())
        raise
    return stages


def _entry_manifest(asset: ResearchWorkflowAsset, *, before: _BeforeRecord, target_after: dict[str, object]) -> dict[str, object]:
    return {
        "relativePath": asset.relative_path,
        "kind": asset.kind,
        "source": asset.to_dict(),
        "targetBefore": before.to_dict(),
        "targetAfter": target_after,
    }


def _find_manifest(target_root: Path, manifest_path: Path | None = None) -> Path:
    if manifest_path is not None:
        path = Path(manifest_path).expanduser().resolve()
        _assert_under(path, target_root / MANIFEST_DIRNAME, label="manifest")
        if not path.is_file():
            raise ResearchWorkflowMigrationError(f"manifest not found: {path}")
        return path
    candidates = [
        path
        for path in (target_root / MANIFEST_DIRNAME).glob(f"{MANIFEST_PREFIX}*.json")
        if path.is_file()
    ]
    if not candidates:
        raise ResearchWorkflowMigrationError("research workflow migration manifest not found")
    ranked: list[tuple[tuple[float, int, str, str], Path]] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchWorkflowMigrationError(
                f"migration manifest candidate unreadable: {path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchWorkflowMigrationError(
                f"migration manifest candidate is not an object: {path}"
            )
        status = str(payload.get("status") or "")
        if status not in {"committed", "completed"}:
            continue
        if int(payload.get("schemaVersion") or 0) != 1:
            raise ResearchWorkflowMigrationError(
                f"migration manifest candidate schema unsupported: {path}"
            )
        timestamp = _manifest_order_timestamp(payload)
        if timestamp is None:
            raise ResearchWorkflowMigrationError(
                f"migration manifest ordering evidence missing: {path}"
            )
        migration_id = str(payload.get("migrationId") or "")
        ranked.append(
            (
                (
                    timestamp.timestamp(),
                    1 if status == "completed" else 0,
                    migration_id,
                    path.name.lower(),
                ),
                path,
            )
        )
    if not ranked:
        raise ResearchWorkflowMigrationError(
            "research workflow migration committed manifest not found"
        )
    ranked.sort(key=lambda item: item[0])
    return ranked[-1][1]


def _manifest_order_timestamp(payload: dict[str, object]) -> datetime | None:
    values: list[object] = []
    for field_name in ("completedAt", "committedAt", "updatedAt", "createdAt", "timestamp"):
        values.append(payload.get(field_name))
    transitions = payload.get("statusTransitions")
    if isinstance(transitions, list):
        for item in transitions:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") in {"committed", "completed"}:
                values.append(item.get("at"))
    parsed: list[datetime] = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed.append(datetime.fromtimestamp(float(value), tz=UTC))
            continue
        text = str(value or "").strip()
        if not text:
            continue
        try:
            parsed_value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed.append(
            parsed_value.replace(tzinfo=UTC)
            if parsed_value.tzinfo is None
            else parsed_value.astimezone(UTC)
        )
    if parsed:
        return max(parsed)
    migration_id = str(payload.get("migrationId") or "")
    match = re.search(r"(\d{8}T\d{6}Z)", migration_id)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchWorkflowMigrationError(f"migration manifest unreadable: {path}") from exc
    if not isinstance(payload, dict) or int(payload.get("schemaVersion") or 0) != 1:
        raise ResearchWorkflowMigrationError(f"migration manifest schema unsupported: {path}")
    return payload


def _assert_manifest_root_binding(payload: dict[str, object], roots: _ResolvedRoots) -> None:
    """Require that a manifest belongs to the current canonical source/target pair."""

    if str(payload.get("targetRoot") or "") != str(roots.target):
        raise ResearchWorkflowMigrationError("manifest target root is not the canonical project root")
    if str(payload.get("sourceRoot") or "") != str(roots.source):
        raise ResearchWorkflowMigrationError("manifest source root is not the operator Documents root")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_manifest_target_after(
    item: dict[str, object],
    *,
    relative: str,
    kind: str,
) -> None:
    expected = item.get("targetAfter")
    if not isinstance(expected, dict) or expected.get("exists") is not True or not _is_sha256(expected.get("sha256")):
        raise ResearchWorkflowMigrationError(
            f"migration manifest target-after evidence is incomplete: {relative}"
        )
    if kind != "sqlite":
        return
    sqlite = expected.get("sqlite")
    row_counts = sqlite.get("row_counts") if isinstance(sqlite, dict) else None
    valid_row_counts = isinstance(row_counts, dict) and all(
        isinstance(name, str) and type(count) is int and count >= 0
        for name, count in row_counts.items()
    )
    if (
        not _is_sha256(expected.get("bundleFingerprint"))
        or not isinstance(sqlite, dict)
        or not _is_sha256(sqlite.get("schema_digest"))
        or not valid_row_counts
    ):
        raise ResearchWorkflowMigrationError(
            f"migration manifest target-after evidence is incomplete: {relative}"
        )


def _manifest_entries(payload: dict[str, object], target_root: Path) -> list[dict[str, object]]:
    raw = payload.get("assets")
    if not isinstance(raw, list):
        raise ResearchWorkflowMigrationError("migration manifest assets are missing")
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ResearchWorkflowMigrationError("migration manifest asset row is invalid")
        relative = str(item.get("relativePath") or "")
        kind = str(item.get("kind") or "")
        if not relative or kind not in {"sqlite", "json"} or _allowed_kind(relative) != kind:
            raise ResearchWorkflowMigrationError(f"migration manifest asset is outside allowlist: {relative}")
        if relative in seen:
            raise ResearchWorkflowMigrationError(f"migration manifest asset is duplicated: {relative}")
        _assert_under(target_root / Path(relative), target_root, label="manifest asset")
        _validate_manifest_target_after(item, relative=relative, kind=kind)
        entries.append(item)
        seen.add(relative)
    return entries


def _before_record_from_manifest(
    item: dict[str, object],
    *,
    archive_root: Path,
) -> _BeforeRecord:
    relative = str(item.get("relativePath") or "")
    kind = str(item.get("kind") or "")
    raw = item.get("targetBefore")
    if not isinstance(raw, dict):
        raise ResearchWorkflowMigrationError(f"rollback target-before row missing: {relative}")
    if str(raw.get("relative_path") or "") != relative or str(raw.get("kind") or "") != kind:
        raise ResearchWorkflowMigrationError(f"rollback target-before identity mismatch: {relative}")
    existed = raw.get("existed")
    if not isinstance(existed, bool):
        raise ResearchWorkflowMigrationError(f"rollback target-before existence is invalid: {relative}")
    record = _BeforeRecord(
        relative_path=relative,
        existed=existed,
        kind=kind,
        archive_path=str(raw.get("archive_path") or ""),
        sha256=str(raw.get("sha256") or ""),
        bundle_fingerprint=str(raw.get("bundle_fingerprint") or ""),
        archive_sha256=str(raw.get("archive_sha256") or ""),
        archive_bundle_fingerprint=str(raw.get("archive_bundle_fingerprint") or ""),
    )
    if record.existed:
        _archive_path_for_before(record, archive_root)
    elif record.sha256 or record.bundle_fingerprint or record.archive_sha256 or record.archive_bundle_fingerprint:
        raise ResearchWorkflowMigrationError(f"rollback missing-target record is inconsistent: {relative}")
    return record


def _manifest_archive_root(payload: dict[str, object], roots: _ResolvedRoots) -> Path:
    """Resolve the v1 recorded archive root without guessing a new layout."""

    raw_root = str(payload.get("targetBeforeArchive") or "")
    candidate = Path(raw_root).expanduser()
    if not raw_root or not candidate.is_absolute():
        raise ResearchWorkflowMigrationError(
            "migration manifest archive root evidence is missing or not absolute"
        )
    archive_root = candidate.resolve()
    _assert_under(archive_root, roots.target.parent, label="manifest archive root")
    return archive_root


def _validate_post_cutover_target(item: dict[str, object], target: Path) -> None:
    relative = str(item.get("relativePath") or "")
    expected = item.get("targetAfter")
    if not isinstance(expected, dict) or expected.get("exists") is not True:
        raise ResearchWorkflowMigrationError(f"rollback target-after evidence is invalid: {relative}")
    expected_sha = str(expected.get("sha256") or "")
    if not expected_sha:
        raise ResearchWorkflowMigrationError(f"rollback target-after checksum missing: {relative}")
    if not target.is_file() or _is_reparse(target):
        raise ResearchWorkflowMigrationError(f"rollback blocked by missing or unsafe post-cutover asset: {relative}")
    if _sha256_file(target) != expected_sha:
        raise ResearchWorkflowMigrationError(f"rollback blocked by post-cutover delta: {relative}")
    if str(item.get("kind") or "") == "sqlite":
        if target.stat().st_size == 0:
            raise ResearchWorkflowMigrationError(f"rollback blocked by empty SQLite main: {relative}")
        if any(sidecar.exists() for sidecar in _sqlite_bundle_paths(target)[1:]):
            raise ResearchWorkflowMigrationError(f"rollback blocked by SQLite sidecar delta: {relative}")
        expected_bundle = str(expected.get("bundleFingerprint") or "")
        actual_bundle, _ = _sqlite_bundle_snapshot(target)
        if not expected_bundle or actual_bundle != expected_bundle:
            raise ResearchWorkflowMigrationError(f"rollback blocked by SQLite bundle delta: {relative}")


def _manifest_key_run_status(payload: dict[str, object]) -> str:
    key_runs = payload.get("keyRuns")
    if not isinstance(key_runs, dict):
        return ""
    value = key_runs.get(KEY_RUN_ID)
    return str(value or "")


def _guard_or_raise(
    project_root: Path,
    *,
    quiescence_probe: QuiescenceProbe | None,
) -> dict[str, object]:
    raw_guard = quiescence_probe(project_root) if quiescence_probe else _default_quiescence(project_root)
    guard = (
        _normalize_quiescence_guard(project_root, raw_guard)[0]
        if quiescence_probe
        else raw_guard
    )
    if not guard.get("ok"):
        raise ResearchWorkflowMigrationError(
            "migration requires runtime and active-work quiescence: "
            + json.dumps(guard.get("blockers") or guard, ensure_ascii=False, sort_keys=True)
        )
    return guard


def apply_research_workflow_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
    sample_delay_seconds: float = 0.05,
    quiescence_probe: QuiescenceProbe | None = None,
) -> dict[str, object]:
    """Stage, validate, and atomically promote allowlisted assets.

    The source remains untouched even on failure.  The global storage marker is
    read only; this workflow does not change the project's broader storage
    cutover state.
    """

    roots = _resolve_roots(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
    )
    _recover_existing_promotion_journal(roots, quiescence_probe=quiescence_probe)
    preview = _build_preview(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
        sample_delay_seconds=sample_delay_seconds,
        quiescence_probe=quiescence_probe,
    )
    if not preview.ready:
        codes = ", ".join(str(item.get("code") or "blocked") for item in preview.blockers[:8])
        raise ResearchWorkflowMigrationError(f"research workflow migration readiness blocked: {codes}")
    guard = _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    # Keep generated path components short: the canonical project data root is
    # already deep on Windows, while the manifest retains the complete
    # relative-path and checksum evidence needed for rollback.
    migration_id = f"rwm-{uuid.uuid4().hex[:12]}"
    backup_base = roots.target.parent / _BACKUP_DIRNAME
    archive_root = backup_base / migration_id / _BACKUP_BEFORE_DIRNAME
    manifest_path = roots.target / MANIFEST_DIRNAME / f"{MANIFEST_PREFIX}{migration_id}.json"
    staged: dict[str, Path] = {}
    before_records: list[_BeforeRecord] = []
    target_before_observations: dict[str, dict[str, object]] = {}
    journal_payload: dict[str, object] | None = None
    try:
        # Preflight and archive every governed target before a single target is
        # staged or promoted.  The archive is the only allowed compensation
        # source if a later promotion or manifest write fails.
        for asset in preview.entries:
            _assert_under(asset.target_path, roots.target, label="target asset")
            before = _archive_existing_target(asset, archive_root)
            before_records.append(before)
            target_before_observations[asset.relative_path] = _asset_target_observation(asset)
        # Every changed asset is fully staged and semantically checked before
        # promotion begins.  No per-item copy is allowed in the commit phase.
        for asset in preview.entries:
            state, _detail = _target_asset_state(
                asset,
                allow_replaceable_empty_target=bool(guard.get("ok")),
            )
            if state == "same":
                continue
            stage = _stage_path(asset.target_path, migration_id)
            _copy_asset(asset.source_path, stage, kind=asset.kind)
            staged[asset.relative_path] = stage
            _validate_staged_source_asset(asset, stage)
        source_after = _source_tree_fingerprint(roots.source)
        if source_after != preview.source_fingerprint:
            raise ResearchWorkflowMigrationError("source changed during staging; no promotion performed")
        promotion_guard = _guard_or_raise(
            roots.project.project_root,
            quiescence_probe=quiescence_probe,
        )
        for asset in preview.entries:
            if _asset_target_observation(asset) != target_before_observations[asset.relative_path]:
                raise ResearchWorkflowMigrationError(f"target changed during staging: {asset.relative_path}")
        journal_entries: list[dict[str, object]] = []
        for asset, before in zip(preview.entries, before_records, strict=True):
            stage = staged.get(asset.relative_path)
            if stage is None:
                continue
            journal_entries.append(
                _build_journal_entry(
                    relative=asset.relative_path,
                    kind=asset.kind,
                    target=asset.target_path,
                    stage=stage,
                    recovery_archive=Path(before.archive_path),
                )
            )
        if journal_entries:
            journal_payload = _write_promotion_journal(
                roots,
                operation="apply",
                migration_id=migration_id,
                manifest_path=manifest_path,
                entries=journal_entries,
                guard=promotion_guard,
            )
        for asset in preview.entries:
            stage = staged.get(asset.relative_path)
            if stage is None:
                continue
            asset.target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, asset.target_path)
            if asset.kind == "sqlite":
                _finish_sqlite_bundle_promotion(stage, asset.target_path)
        assets_manifest: list[dict[str, object]] = []
        key_runs: dict[str, str] = {}
        for asset, before in zip(preview.entries, before_records, strict=True):
            after_observation = _asset_target_observation(asset)
            assets_manifest.append(_entry_manifest(asset, before=before, target_after=after_observation))
            sqlite = after_observation.get("sqlite")
            if isinstance(sqlite, dict):
                runs = sqlite.get("key_runs")
                if isinstance(runs, dict):
                    key_runs.update({str(key): str(value) for key, value in runs.items()})
        payload: dict[str, object] = {
            "schemaVersion": 1,
            "migrationId": migration_id,
            "status": "completed",
            "sourceRoot": str(roots.source),
            "targetRoot": str(roots.target),
            "globalStorageMarker": str(roots.marker),
            "sourceFingerprint": preview.source_fingerprint,
            "targetBeforeArchive": str(archive_root),
            "assets": assets_manifest,
            "excludedAssets": _target_excluded_snapshot(
                roots.target,
                preview.excluded_assets,
                source_root=roots.source,
                source_fingerprint=preview.source_fingerprint,
            ),
            "warnings": list(preview.warnings),
            "keyRuns": key_runs,
            "completedAt": _now_iso(),
            "statusTransitions": [
                {"status": "planned", "at": _now_iso()},
                {"status": "quiescent", "at": _now_iso()},
                {"status": "staged", "at": _now_iso()},
                {"status": "verified", "at": _now_iso()},
                {"status": "promoted", "at": _now_iso()},
                {"status": "completed", "at": _now_iso()},
            ],
        }
        _atomic_json(manifest_path, payload)
        for item in assets_manifest:
            _validate_post_cutover_target(
                item,
                roots.target / Path(str(item["relativePath"])),
            )
        _assert_manifest_excluded_evidence(payload, roots)
        if journal_payload is not None:
            _finalize_successful_promotion_journal(journal_payload, roots)
        return {"ok": True, "manifestPath": str(manifest_path), **payload}
    except Exception as exc:
        recovery_error: Exception | None = None
        if _path_entry_exists(_promotion_journal_path(roots)):
            try:
                _recover_existing_promotion_journal(
                    roots,
                    quiescence_probe=quiescence_probe,
                )
            except Exception as recovery_exc:  # noqa: BLE001 - preserve original failure as cause.
                recovery_error = recovery_exc
        _cleanup_stages(staged.values())
        if recovery_error is not None:
            raise ResearchWorkflowMigrationError(
                "migration failed and persistent journal recovery was incomplete: "
                + type(recovery_error).__name__
            ) from exc
        raise


def verify_research_workflow_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
    quiescence_probe: QuiescenceProbe | None = None,
) -> dict[str, object]:
    """Verify target assets and the preserved key run without writing them."""

    roots = _resolve_roots(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
    )
    journal_blockers = _promotion_journal_blockers(roots)
    if journal_blockers:
        return {
            "ok": False,
            "manifestPath": str(manifest_path or ""),
            "targetRoot": str(roots.target),
            "observed": [],
            "keyRuns": {},
            "failures": journal_blockers,
        }
    manifest = _find_manifest(roots.target, Path(manifest_path) if manifest_path else None)
    payload = _read_manifest(manifest)
    if str(payload.get("status") or "") not in {"committed", "completed"}:
        raise ResearchWorkflowMigrationError(
            "verification requires a committed or completed migration manifest"
        )
    _assert_manifest_root_binding(payload, roots)
    entries = _manifest_entries(payload, roots.target)
    _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    failures: list[dict[str, object]] = _manifest_excluded_evidence_failures(payload, roots)
    expected_source_fingerprint = str(payload.get("sourceFingerprint") or "")
    if expected_source_fingerprint and _source_tree_fingerprint(roots.source) != expected_source_fingerprint:
        failures.append({"code": "source_changed_after_cutover"})
    observed: list[dict[str, object]] = []
    key_runs: dict[str, str] = {}
    for item in entries:
        relative = str(item["relativePath"])
        target = roots.target / Path(relative)
        expected = item.get("targetAfter") if isinstance(item.get("targetAfter"), dict) else {}
        expected_sha = str(expected.get("sha256") or "")
        if not target.is_file():
            failures.append({"code": "target_missing", "relativePath": relative})
            continue
        actual_sha = _sha256_file(target)
        if expected_sha and actual_sha != expected_sha:
            failures.append({"code": "target_hash_mismatch", "relativePath": relative})
        item_observation: dict[str, object] = {"relativePath": relative, "sha256": actual_sha}
        if str(item.get("kind") or "") == "sqlite":
            kind = "ledger" if target.name == LEDGER_FILENAME else "checkpoint"
            evidence = _sqlite_evidence(target, kind=kind)
            item_observation["sqlite"] = evidence.to_dict()
            bundle, _ = _sqlite_bundle_snapshot(target)
            item_observation["bundleFingerprint"] = bundle
            if not evidence.valid:
                failures.append({"code": "target_sqlite_integrity_failed", "relativePath": relative, "sqlite": evidence.to_dict()})
            if not evidence.known_schema:
                failures.append({"code": "target_sqlite_schema_unknown", "relativePath": relative})
            expected_bundle = str(expected.get("bundleFingerprint") or "")
            if not expected_bundle or bundle != expected_bundle:
                failures.append({"code": "target_bundle_fingerprint_mismatch", "relativePath": relative})
            expected_sqlite = expected.get("sqlite") if isinstance(expected.get("sqlite"), dict) else {}
            expected_schema = str(expected_sqlite.get("schema_digest") or "") if isinstance(expected_sqlite, dict) else ""
            if expected_schema != evidence.schema_digest:
                failures.append({"code": "target_schema_digest_mismatch", "relativePath": relative})
            expected_rows = expected_sqlite.get("row_counts") if isinstance(expected_sqlite, dict) else {}
            if not isinstance(expected_rows, dict) or evidence.row_counts != expected_rows:
                failures.append({"code": "target_row_counts_mismatch", "relativePath": relative})
            key_runs.update(evidence.key_runs)
        observed.append(item_observation)
    if KEY_RUN_ID not in key_runs or key_runs.get(KEY_RUN_ID) != "blocked":
        failures.append({"code": "key_run_not_blocked", "runId": KEY_RUN_ID, "status": key_runs.get(KEY_RUN_ID, "")})
    expected_excluded = payload.get("excludedAssets")
    if isinstance(expected_excluded, list):
        for item in expected_excluded:
            if not isinstance(item, dict):
                continue
            relative = str(item.get("relativePath") or "")
            current = roots.target / Path(relative)
            exists = current.is_file()
            expected_exists = bool(item.get("exists"))
            current_sha = _sha256_file(current) if exists else ""
            if exists != expected_exists or (expected_exists and current_sha != str(item.get("sha256") or "")):
                failures.append({"code": "excluded_asset_changed", "relativePath": relative})
    return {
        "ok": not failures,
        "manifestPath": str(manifest),
        "targetRoot": str(roots.target),
        "observed": observed,
        "keyRuns": key_runs,
        "failures": failures,
    }


def _copy_current_for_rollback(
    target: Path,
    destination: Path,
    *,
    kind: str,
    relative_path: str,
) -> None:
    """Archive a quiescent post-cutover target byte-for-byte for compensation.

    SQLite copies retain the complete byte-exact main/WAL/SHM after-image.  The
    forward source path still uses APSW backup to create a fresh canonical main
    image; rollback compensation must preserve the post-cutover bundle exactly.
    """

    if not target.is_file() or _is_reparse(target):
        raise ResearchWorkflowMigrationError(f"rollback target is missing or unsafe: {relative_path}")
    if destination.exists():
        raise ResearchWorkflowMigrationError(f"rollback target-after archive already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "sqlite":
        _copy_sqlite_bundle_archive(target, destination)
        return
    shutil.copy2(target, destination)
    if _sha256_file(target) != _sha256_file(destination):
        raise ResearchWorkflowMigrationError(f"rollback target-after archive hash mismatch: {relative_path}")


def rollback_research_workflow_migration(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    target_root: str | os.PathLike[str] | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
    quiescence_probe: QuiescenceProbe | None = None,
) -> dict[str, object]:
    """Restore only target-before assets after a fresh quiescence/delta check."""

    roots = _resolve_roots(
        project_root,
        projects_home=projects_home,
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
    )
    _recover_existing_promotion_journal(roots, quiescence_probe=quiescence_probe)
    marker_blockers, _marker, _active_root = _marker_blockers(roots)
    if marker_blockers:
        raise ResearchWorkflowMigrationError(
            "rollback requires a valid canonical storage marker: "
            + ", ".join(str(item.get("code") or "blocked") for item in marker_blockers)
        )
    manifest = _find_manifest(roots.target, Path(manifest_path) if manifest_path else None)
    payload = _read_manifest(manifest)
    if str(payload.get("status") or "") not in {"committed", "completed"}:
        raise ResearchWorkflowMigrationError(
            "rollback requires a committed or completed migration manifest"
        )
    _assert_manifest_root_binding(payload, roots)
    _assert_manifest_excluded_evidence(payload, roots)
    _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    entries = _manifest_entries(payload, roots.target)
    before_archive_root = _manifest_archive_root(payload, roots)
    migration_id = str(payload.get("migrationId") or "")
    if not migration_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in migration_id):
        raise ResearchWorkflowMigrationError("rollback manifest migration id is invalid")
    backup_root = roots.target.parent / _BACKUP_DIRNAME
    rollback_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    after_archive = backup_root / migration_id / f"a-{rollback_stamp}"
    plans: list[_RollbackPlan] = []
    target_before_staging: dict[str, tuple[dict[str, object], ...]] = {}
    # Validate all manifest identities, archive checksums, post-cutover hashes,
    # and governed paths before creating a single rollback stage.
    for item in entries:
        relative = str(item["relativePath"])
        target = roots.target / Path(relative)
        before = _before_record_from_manifest(item, archive_root=before_archive_root)
        _validate_post_cutover_target(item, target)
        target_before_staging[relative] = _member_rows(target, kind=str(item["kind"]))
        plans.append(
            _RollbackPlan(
                entry=item,
                before=before,
                target=target,
                after_archive=_archive_member_path(after_archive, relative),
            )
        )
    rollback_stages = _stage_rollback_plans(
        plans,
        stage_id=f"rb-{uuid.uuid4().hex[:12]}",
        backup_root=backup_root,
        before_archive_root=before_archive_root,
    )
    journal_payload: dict[str, object] | None = None
    try:
        promotion_guard = _guard_or_raise(
            roots.project.project_root,
            quiescence_probe=quiescence_probe,
        )
        for plan in plans:
            relative = str(plan.entry["relativePath"])
            if _member_rows(plan.target, kind=str(plan.entry["kind"])) != target_before_staging[relative]:
                raise ResearchWorkflowMigrationError(
                    f"target changed during rollback staging: {relative}"
                )
        journal_entries = [
            _build_journal_entry(
                relative=str(plan.entry["relativePath"]),
                kind=str(plan.entry["kind"]),
                target=plan.target,
                stage=rollback_stages.get(str(plan.entry["relativePath"])),
                recovery_archive=plan.after_archive,
            )
            for plan in plans
        ]
        if journal_entries:
            journal_payload = _write_promotion_journal(
                roots,
                operation="rollback",
                migration_id=migration_id,
                manifest_path=manifest,
                entries=journal_entries,
                guard=promotion_guard,
            )
        rollback_expected_current: dict[str, tuple[dict[str, object], ...]] = {}
        if journal_payload is not None:
            if not _journal_targets_match(journal_payload, roots, phase="before"):
                raise ResearchWorkflowMigrationError(
                    "rollback target changed after promotion journal was persisted"
                )
            for raw in journal_payload.get("entries") or []:
                if not isinstance(raw, dict):
                    raise ResearchWorkflowMigrationError("rollback promotion journal entry is invalid")
                relative = str(raw.get("relativePath") or "")
                kind = str(raw.get("kind") or "")
                before = raw.get("targetBefore")
                if not isinstance(before, dict):
                    raise ResearchWorkflowMigrationError(
                        f"rollback promotion journal target-before is invalid: {relative}"
                    )
                rollback_expected_current[relative] = _normalize_journal_member_rows(
                    before.get("members"),
                    kind=kind,
                    label="target-before",
                )
        for plan in plans:
            relative = str(plan.entry["relativePath"])
            kind = str(plan.entry["kind"])
            expected_current = rollback_expected_current.get(relative)
            if expected_current is None or _member_rows(plan.target, kind=kind) != expected_current:
                raise ResearchWorkflowMigrationError(
                    f"rollback target changed before promotion: {relative}"
                )
            if plan.before.existed:
                plan.target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(rollback_stages[relative], plan.target)
                if kind == "sqlite":
                    _finish_sqlite_bundle_promotion(rollback_stages[relative], plan.target)
            elif plan.target.is_file() and not _is_reparse(plan.target):
                plan.target.unlink()
                if kind == "sqlite":
                    _remove_sqlite_bundle_sidecars(plan.target)
            else:
                raise ResearchWorkflowMigrationError(f"rollback target became unsafe: {relative}")
        if journal_payload is not None and not _journal_targets_match(
            journal_payload,
            roots,
            phase="after",
        ):
            raise ResearchWorkflowMigrationError("rollback target verification failed")
        next_payload = dict(payload)
        transitions = list(payload.get("statusTransitions") or []) if isinstance(payload.get("statusTransitions"), list) else []
        transitions.append({"status": "rollback_verified", "at": _now_iso()})
        transitions.append({"status": "rolled_back", "at": _now_iso()})
        next_payload.update(
            {
                "status": "rolled_back",
                "targetAfterRollbackArchive": str(after_archive),
                "statusTransitions": transitions,
            }
        )
        _atomic_json(manifest, next_payload)
        if journal_payload is not None:
            _finalize_successful_promotion_journal(journal_payload, roots)
        return {
            "ok": True,
            "manifestPath": str(manifest),
            "status": "rolled_back",
            "targetAfterRollbackArchive": str(after_archive),
        }
    except Exception as exc:
        recovery_error: Exception | None = None
        if _path_entry_exists(_promotion_journal_path(roots)):
            try:
                _recover_existing_promotion_journal(
                    roots,
                    quiescence_probe=quiescence_probe,
                )
            except Exception as recovery_exc:  # noqa: BLE001 - preserve original failure as cause.
                recovery_error = recovery_exc
        _cleanup_stages(rollback_stages.values())
        if recovery_error is not None:
            raise ResearchWorkflowMigrationError(
                "rollback failed and persistent journal recovery was incomplete: "
                + type(recovery_error).__name__
            ) from exc
        raise


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CHECKPOINT_FILENAME",
    "CURRENT_LEDGER_SCHEMA_VERSION",
    "KEY_RUN_ID",
    "LEDGER_FILENAME",
    "ResearchWorkflowAsset",
    "ResearchWorkflowMigrationError",
    "ResearchWorkflowMigrationResult",
    "SQLiteEvidence",
    "acknowledge_proven_stale_runtime_quiescence",
    "apply_research_workflow_migration",
    "preview_research_workflow_migration",
    "rollback_research_workflow_migration",
    "verify_research_workflow_migration",
]
