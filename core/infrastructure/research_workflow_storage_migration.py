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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
KEY_RUN_ID = "run-882610596ddb"
CURRENT_LEDGER_SCHEMA_VERSION = int(LEDGER_SCHEMA_VERSION)
MANIFEST_DIRNAME = "migration"
MANIFEST_PREFIX = "rwm-"
_BACKUP_DIRNAME = ".rwm-b"
_BACKUP_BEFORE_DIRNAME = "b"

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
    source_fingerprint: str = ""
    target_fingerprint: str = ""
    marker_path: Path | None = None
    active_root: Path | None = None
    status: str = "preview"

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
            "sourceFingerprint": self.source_fingerprint,
            "targetFingerprint": self.target_fingerprint,
            "markerPath": str(self.marker_path) if self.marker_path else "",
            "activeRoot": str(self.active_root) if self.active_root else "",
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


def _sqlite_bundle_snapshot(main: Path) -> tuple[str, tuple[dict[str, object], ...]]:
    members: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for role, path in zip(("main", "wal", "shm"), _sqlite_bundle_paths(main), strict=True):
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
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_excluded(relative_path: str) -> bool:
    parts = [part.lower() for part in Path(relative_path).parts]
    if any(part in _EXCLUDED_NAMES for part in parts):
        return True
    return any(
        part == prefix or part.startswith((prefix + "_", prefix + "-"))
        for part in parts
        for prefix in _EXCLUDED_PREFIXES
    )


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
    return {"ok": not blockers, "blockers": blockers, "activeWork": active, "runtimeWriters": writers, "launcher": launcher}


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
) -> tuple[list[ResearchWorkflowAsset], list[str], list[dict[str, object]]]:
    assets: list[ResearchWorkflowAsset] = []
    excluded: list[str] = []
    blockers: list[dict[str, object]] = []
    if not roots.source.exists():
        blockers.append({"code": "source_missing", "path": str(roots.source)})
        return assets, excluded, blockers
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
    return assets, sorted(set(excluded)), blockers


def _target_asset_state(asset: ResearchWorkflowAsset) -> tuple[str, dict[str, object]]:
    target = asset.target_path
    sidecars = _sqlite_bundle_paths(target)[1:] if asset.kind == "sqlite" else ()
    if asset.kind == "sqlite" and target.is_file() and target.stat().st_size == 0:
        return "conflict", {
            "code": "target_empty_sqlite_main",
            "path": str(target),
        }
    if any(path.exists() for path in sidecars):
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
        if evidence.schema_version == 5:
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
            if path.is_file() and ".staging" in path.name and path.name.startswith("."):
                blockers.append(
                    {
                        "code": "stale_migration_staging_asset",
                        "relativePath": path.relative_to(roots.target).as_posix(),
                    }
                )
    guard = quiescence_probe(roots.project.project_root) if quiescence_probe else _default_quiescence(roots.project.project_root)
    if not guard.get("ok"):
        guard_blockers = guard.get("blockers")
        if isinstance(guard_blockers, list):
            blockers.extend(item for item in guard_blockers if isinstance(item, dict))
        else:
            blockers.append({"code": "runtime_quiescence_unknown", "evidence": guard})
    assets, excluded, source_blockers = _enumerate_source(roots)
    blockers.extend(source_blockers)
    for asset in assets:
        try:
            blockers.extend(_source_asset_blockers(asset))
            state, detail = _target_asset_state(asset)
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
    return ResearchWorkflowMigrationResult(
        source_root=roots.source,
        target_root=roots.target,
        allowed_assets=_ALLOWED_ASSETS,
        excluded_assets=tuple(excluded),
        entries=tuple(assets),
        blockers=tuple(blockers),
        source_fingerprint=after,
        target_fingerprint=_source_tree_fingerprint(roots.target),
        marker_path=marker,
        active_root=active_root,
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
    if not target.is_file():
        return {"exists": False, "sha256": "", "size": 0, "bundleFingerprint": ""}
    sha = _sha256_file(target)
    bundle = ""
    sqlite: dict[str, object] | None = None
    if asset.kind == "sqlite":
        bundle, _ = _sqlite_bundle_snapshot(target)
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
    return observation


def _target_excluded_snapshot(target_root: Path, excluded: Iterable[str]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative in sorted(set(excluded)):
        path = target_root / Path(relative)
        if not path.is_file() or _is_reparse(path):
            result.append({"relativePath": relative, "exists": False, "sha256": ""})
            continue
        result.append(
            {
                "relativePath": relative,
                "exists": True,
                "sha256": _sha256_file(path),
                "size": int(path.stat().st_size),
            }
        )
    return result


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
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
        if archive.stat().st_size == 0:
            raise ResearchWorkflowMigrationError(
                f"rollback archive SQLite main is empty: {before.relative_path}"
            )
        bundle, _ = _sqlite_bundle_snapshot(archive)
        if not before.archive_bundle_fingerprint or bundle != before.archive_bundle_fingerprint:
            raise ResearchWorkflowMigrationError(f"rollback archive bundle mismatch: {before.relative_path}")
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
    if stage.stat().st_size == 0:
        raise ResearchWorkflowMigrationError(f"rollback staged SQLite main is empty: {relative_path}")
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


def _restore_promoted_targets(
    promoted: Iterable[ResearchWorkflowAsset],
    before_records: dict[str, _BeforeRecord],
    *,
    target_root: Path,
    backup_root: Path,
    restore_id: str,
) -> list[str]:
    """Best-effort compensation after a failed forward promotion.

    All required before-images are verified and staged before any target is
    restored, so a staging failure cannot leave an earlier target reverted.
    The returned diagnostics preserve the original failure as the primary
    exception while making an incomplete compensation explicit.
    """

    assets = list(promoted)
    stages: dict[str, Path] = {}
    errors: list[str] = []
    try:
        for asset in assets:
            _assert_under(asset.target_path, target_root, label="compensation target")
            before = before_records[asset.relative_path]
            if not before.existed:
                continue
            archive = _archive_path_for_before(before, backup_root)
            stage = _stage_path(asset.target_path, restore_id)
            _copy_asset(archive, stage, kind=asset.kind)
            _validate_staged_archive(archive, stage, kind=asset.kind, relative_path=asset.relative_path)
            stages[asset.relative_path] = stage
    except Exception as exc:  # noqa: BLE001 - recovery must report every normal failure.
        _cleanup_stages(stages.values())
        return [f"compensation_stage_failed:{type(exc).__name__}"]
    for asset in reversed(assets):
        before = before_records[asset.relative_path]
        try:
            if before.existed:
                os.replace(stages[asset.relative_path], asset.target_path)
            elif asset.target_path.is_file() and not _is_reparse(asset.target_path):
                asset.target_path.unlink()
            elif asset.target_path.exists():
                raise ResearchWorkflowMigrationError(
                    f"compensation target became unsafe: {asset.relative_path}"
                )
        except Exception as exc:  # noqa: BLE001 - preserve all failed compensation diagnostics.
            errors.append(f"compensation_promote_failed:{asset.relative_path}:{type(exc).__name__}")
    _cleanup_stages(stages.values())
    return errors


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
            _copy_asset(archive, stage, kind=str(plan.entry["kind"]))
            _validate_staged_archive(
                archive,
                stage,
                kind=str(plan.entry["kind"]),
                relative_path=str(plan.entry["relativePath"]),
            )
            stages[str(plan.entry["relativePath"])] = stage
    except Exception:
        _cleanup_stages(stages.values())
        raise
    return stages


def _restore_post_cutover_targets(
    plans: Iterable[_RollbackPlan],
    *,
    target_root: Path,
    backup_root: Path,
    restore_id: str,
) -> list[str]:
    """Compensate a failed rollback from the independently archived after-image."""

    plans = list(plans)
    stages: dict[str, Path] = {}
    try:
        for plan in plans:
            _assert_under(plan.target, target_root, label="rollback compensation target")
            _assert_under(plan.after_archive, backup_root, label="rollback compensation archive")
            if not plan.after_archive.is_file() or _is_reparse(plan.after_archive):
                raise ResearchWorkflowMigrationError(
                    f"rollback compensation archive missing: {plan.entry['relativePath']}"
                )
            stage = _stage_path(plan.target, restore_id)
            kind = str(plan.entry["kind"])
            _copy_asset(plan.after_archive, stage, kind=kind)
            _validate_staged_archive(
                plan.after_archive,
                stage,
                kind=kind,
                relative_path=str(plan.entry["relativePath"]),
            )
            stages[str(plan.entry["relativePath"])] = stage
    except Exception as exc:  # noqa: BLE001 - recovery must retain the full diagnostic.
        _cleanup_stages(stages.values())
        return [f"rollback_compensation_stage_failed:{type(exc).__name__}"]
    errors: list[str] = []
    for plan in plans:
        try:
            os.replace(stages[str(plan.entry["relativePath"])], plan.target)
        except Exception as exc:  # noqa: BLE001 - continue attempting every post-cutover restore.
            errors.append(
                f"rollback_compensation_promote_failed:{plan.entry['relativePath']}:{type(exc).__name__}"
            )
    _cleanup_stages(stages.values())
    return errors


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
    for field in ("completedAt", "committedAt", "updatedAt", "createdAt", "timestamp"):
        values.append(payload.get(field))
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
    guard = quiescence_probe(project_root) if quiescence_probe else _default_quiescence(project_root)
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
    _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    # Keep generated path components short: the canonical project data root is
    # already deep on Windows, while the manifest retains the complete
    # relative-path and checksum evidence needed for rollback.
    migration_id = f"rwm-{uuid.uuid4().hex[:12]}"
    backup_base = roots.target.parent / _BACKUP_DIRNAME
    archive_root = backup_base / migration_id / _BACKUP_BEFORE_DIRNAME
    staged: dict[str, Path] = {}
    before_records: list[_BeforeRecord] = []
    before_by_relative: dict[str, _BeforeRecord] = {}
    promoted: list[ResearchWorkflowAsset] = []
    target_before_observations: dict[str, dict[str, object]] = {}
    try:
        # Preflight and archive every governed target before a single target is
        # staged or promoted.  The archive is the only allowed compensation
        # source if a later promotion or manifest write fails.
        for asset in preview.entries:
            _assert_under(asset.target_path, roots.target, label="target asset")
            before = _archive_existing_target(asset, archive_root)
            before_records.append(before)
            before_by_relative[asset.relative_path] = before
            target_before_observations[asset.relative_path] = _asset_target_observation(asset)
        # Every changed asset is fully staged and semantically checked before
        # promotion begins.  No per-item copy is allowed in the commit phase.
        for asset in preview.entries:
            state, _detail = _target_asset_state(asset)
            if state == "same":
                continue
            stage = _stage_path(asset.target_path, migration_id)
            _copy_asset(asset.source_path, stage, kind=asset.kind)
            staged[asset.relative_path] = stage
            _validate_staged_source_asset(asset, stage)
        source_after = _source_tree_fingerprint(roots.source)
        if source_after != preview.source_fingerprint:
            raise ResearchWorkflowMigrationError("source changed during staging; no promotion performed")
        _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
        for asset in preview.entries:
            if _asset_target_observation(asset) != target_before_observations[asset.relative_path]:
                raise ResearchWorkflowMigrationError(f"target changed during staging: {asset.relative_path}")
        for asset in preview.entries:
            stage = staged.get(asset.relative_path)
            if stage is None:
                continue
            asset.target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, asset.target_path)
            promoted.append(asset)
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
        manifest_path = roots.target / MANIFEST_DIRNAME / f"{MANIFEST_PREFIX}{migration_id}.json"
        payload: dict[str, object] = {
            "schemaVersion": 1,
            "migrationId": migration_id,
            "status": "committed",
            "sourceRoot": str(roots.source),
            "targetRoot": str(roots.target),
            "globalStorageMarker": str(roots.marker),
            "sourceFingerprint": preview.source_fingerprint,
            "targetBeforeArchive": str(archive_root),
            "assets": assets_manifest,
            "excludedAssets": _target_excluded_snapshot(roots.target, preview.excluded_assets),
            "keyRuns": key_runs,
            "statusTransitions": [
                {"status": "planned", "at": _now_iso()},
                {"status": "quiescent", "at": _now_iso()},
                {"status": "staged", "at": _now_iso()},
                {"status": "verified", "at": _now_iso()},
                {"status": "promoted", "at": _now_iso()},
                {"status": "committed", "at": _now_iso()},
            ],
        }
        _atomic_json(manifest_path, payload)
        return {"ok": True, "manifestPath": str(manifest_path), **payload}
    except Exception as exc:
        recovery_errors = _restore_promoted_targets(
            promoted,
            before_by_relative,
            target_root=roots.target,
            backup_root=backup_base,
            restore_id=f"rr-{uuid.uuid4().hex[:12]}",
        )
        _cleanup_stages(staged.values())
        if recovery_errors:
            raise ResearchWorkflowMigrationError(
                "migration failed and target compensation was incomplete: " + ", ".join(recovery_errors)
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
    manifest = _find_manifest(roots.target, Path(manifest_path) if manifest_path else None)
    payload = _read_manifest(manifest)
    if str(payload.get("status") or "") not in {"committed", "completed"}:
        raise ResearchWorkflowMigrationError(
            "verification requires a committed or completed migration manifest"
        )
    _assert_manifest_root_binding(payload, roots)
    entries = _manifest_entries(payload, roots.target)
    _guard_or_raise(roots.project.project_root, quiescence_probe=quiescence_probe)
    failures: list[dict[str, object]] = []
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

    Rollback preflight has already rejected SQLite sidecars, so this copy has a
    stable main image and avoids creating an unnecessarily deep APSW backup
    destination on Windows.  Source copies still use APSW backup exclusively.
    """

    if not target.is_file() or _is_reparse(target):
        raise ResearchWorkflowMigrationError(f"rollback target is missing or unsafe: {relative_path}")
    if kind == "sqlite" and target.stat().st_size == 0:
        raise ResearchWorkflowMigrationError(f"rollback target SQLite main is empty: {relative_path}")
    if kind == "sqlite" and any(sidecar.exists() for sidecar in _sqlite_bundle_paths(target)[1:]):
        raise ResearchWorkflowMigrationError(f"rollback blocked by SQLite sidecar delta: {relative_path}")
    if destination.exists():
        raise ResearchWorkflowMigrationError(f"rollback target-after archive already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
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
    # Validate all manifest identities, archive checksums, post-cutover hashes,
    # and governed paths before creating a single rollback stage.
    for item in entries:
        relative = str(item["relativePath"])
        target = roots.target / Path(relative)
        before = _before_record_from_manifest(item, archive_root=before_archive_root)
        _validate_post_cutover_target(item, target)
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
    promoted: list[_RollbackPlan] = []
    try:
        for plan in plans:
            relative = str(plan.entry["relativePath"])
            if plan.before.existed:
                plan.target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(rollback_stages[relative], plan.target)
            elif plan.target.is_file() and not _is_reparse(plan.target):
                plan.target.unlink()
            else:
                raise ResearchWorkflowMigrationError(f"rollback target became unsafe: {relative}")
            promoted.append(plan)
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
        return {
            "ok": True,
            "manifestPath": str(manifest),
            "status": "rolled_back",
            "targetAfterRollbackArchive": str(after_archive),
        }
    except Exception as exc:
        recovery_errors = _restore_post_cutover_targets(
            plans,
            target_root=roots.target,
            backup_root=backup_root,
            restore_id=f"rb-restore-{migration_id}-{uuid.uuid4().hex[:6]}",
        )
        _cleanup_stages(rollback_stages.values())
        if recovery_errors:
            raise ResearchWorkflowMigrationError(
                "rollback failed and post-cutover compensation was incomplete: " + ", ".join(recovery_errors)
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
    "apply_research_workflow_migration",
    "preview_research_workflow_migration",
    "rollback_research_workflow_migration",
    "verify_research_workflow_migration",
]
