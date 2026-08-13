"""Bootstrap-safe external storage paths for project-scoped mutable state.

This module deliberately lives outside application packages so Launcher and
Runtime Manager bootstrap code can resolve paths without importing the full
configuration or infrastructure graph.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECTS_HOME_ENV = "VIBELUTION_PROJECTS_HOME"
PROJECT_IDENTITY_RELATIVE_PATH = Path(".vibelution") / "project.json"
PROJECT_IDENTITY_SCHEMA_VERSION = 1
STORAGE_MIGRATION_SCHEMA_VERSION = 1
STORAGE_MIGRATION_STATE_NAME = "storage-migration.json"
PROJECT_MEMORY_MIGRATION_STATE_NAME = "project-memory-migration.json"
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_FNV32_OFFSET = 2166136261
_FNV32_PRIME = 16777619


class ProjectIdentityError(ValueError):
    """Raised when a checkout has no valid tracked project identity."""


@dataclass(frozen=True)
class ProjectIdentity:
    schema_version: int
    project_id: str
    source_path: Path


@dataclass(frozen=True)
class ProjectStoragePaths:
    project_root: Path
    project_id: str
    instance_id: str
    projects_home: Path
    project_home: Path
    instance_home: Path
    data: Path
    runtime: Path
    logs: Path
    memory: Path
    cache: Path
    migrated: bool = True

    @property
    def workspace(self) -> Path:
        return self.data / "workspace"

    def as_dict(self) -> dict[str, str]:
        return {
            "projectRoot": str(self.project_root),
            "projectId": self.project_id,
            "instanceId": self.instance_id,
            "projectsHome": str(self.projects_home),
            "projectHome": str(self.project_home),
            "instanceHome": str(self.instance_home),
            "data": str(self.data),
            "workspace": str(self.workspace),
            "runtime": str(self.runtime),
            "logs": str(self.logs),
            "memory": str(self.memory),
            "cache": str(self.cache),
            "migrated": str(self.migrated).lower(),
        }


def default_projects_home() -> Path:
    raw = str(os.environ.get("LOCALAPPDATA") or "").strip()
    local_app_data = Path(raw) if raw else Path.home() / "AppData" / "Local"
    return (local_app_data / "Vibelution" / "projects").resolve()


def resolve_projects_home(value: str | os.PathLike[str] | None = None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    raw = str(os.environ.get(PROJECTS_HOME_ENV) or "").strip()
    if raw:
        return Path(os.path.expandvars(raw)).expanduser().resolve()
    return default_projects_home()


def load_project_identity(project_root: str | os.PathLike[str]) -> ProjectIdentity:
    root = _resolve_project_root(project_root)
    source_path = root / PROJECT_IDENTITY_RELATIVE_PATH
    try:
        payload: Any = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectIdentityError(f"missing tracked project identity: {source_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectIdentityError(f"invalid project identity: {source_path}") from exc
    if not isinstance(payload, dict):
        raise ProjectIdentityError(f"project identity must be an object: {source_path}")
    schema_version = int(payload.get("schemaVersion") or 0)
    project_id = str(payload.get("projectId") or "").strip().lower()
    if schema_version != PROJECT_IDENTITY_SCHEMA_VERSION:
        raise ProjectIdentityError(
            f"unsupported project identity schema {schema_version}: {source_path}"
        )
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ProjectIdentityError(f"invalid projectId in {source_path}")
    return ProjectIdentity(
        schema_version=schema_version,
        project_id=project_id,
        source_path=source_path,
    )


def normalize_instance_key(project_root: str | os.PathLike[str]) -> str:
    return os.path.normcase(str(_resolve_project_root(project_root)))


def instance_id_for_project(project_root: str | os.PathLike[str]) -> str:
    digest = _FNV32_OFFSET
    for byte in normalize_instance_key(project_root).encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV32_PRIME) & 0xFFFFFFFF
    return f"{digest:08x}"


def resolve_project_storage_paths(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
) -> ProjectStoragePaths:
    root = _resolve_project_root(project_root)
    identity = load_project_identity(root)
    resolved_projects_home = resolve_projects_home(projects_home)
    project_home = resolved_projects_home / identity.project_id
    instance_id = instance_id_for_project(root)
    instance_home = project_home / "instances" / instance_id
    return ProjectStoragePaths(
        project_root=root,
        project_id=identity.project_id,
        instance_id=instance_id,
        projects_home=resolved_projects_home,
        project_home=project_home,
        instance_home=instance_home,
        data=instance_home / "data",
        runtime=instance_home / "runtime",
        logs=instance_home / "logs",
        memory=project_home / "memory",
        cache=instance_home / "cache",
    )


def storage_migration_state_path(paths: ProjectStoragePaths) -> Path:
    return paths.instance_home / STORAGE_MIGRATION_STATE_NAME


def project_memory_migration_state_path(paths: ProjectStoragePaths) -> Path:
    return paths.project_home / PROJECT_MEMORY_MIGRATION_STATE_NAME


def project_memory_migration_complete(paths: ProjectStoragePaths) -> bool:
    try:
        payload = json.loads(project_memory_migration_state_path(paths).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schemaVersion") == STORAGE_MIGRATION_SCHEMA_VERSION
        and payload.get("status") == "completed"
        and str(payload.get("projectId") or "") == paths.project_id
    )


def storage_migration_complete(paths: ProjectStoragePaths) -> bool:
    path = storage_migration_state_path(paths)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schemaVersion") == STORAGE_MIGRATION_SCHEMA_VERSION
        and payload.get("status") == "completed"
        and str(payload.get("projectId") or "") == paths.project_id
        and str(payload.get("instanceId") or "") == paths.instance_id
    )


def legacy_project_storage_paths(
    project_root: str | os.PathLike[str],
    *,
    target: ProjectStoragePaths | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> ProjectStoragePaths:
    """Describe pre-governance locations without creating or modifying them."""

    root = _resolve_project_root(project_root)
    target_paths = target or resolve_project_storage_paths(root)
    from config.paths import resolve_data_home

    return ProjectStoragePaths(
        project_root=root,
        project_id=target_paths.project_id,
        instance_id=target_paths.instance_id,
        projects_home=target_paths.projects_home,
        project_home=target_paths.project_home,
        instance_home=target_paths.instance_home,
        data=resolve_data_home(config_path=config_path),
        runtime=root / ".runtime",
        logs=root / "logs",
        memory=_integration_project_root(root) / ".docs" / "project-memory",
        cache=root / ".cache",
        migrated=False,
    )


def legacy_project_state_present(paths: ProjectStoragePaths) -> bool:
    """Return whether the primary checkout still owns legacy mutable state."""

    root = paths.project_root
    if not (root / ".git").is_dir():
        return False
    legacy = legacy_project_storage_paths(root, target=paths)
    candidates = (
        legacy.runtime,
        legacy.logs,
        legacy.memory,
        root / "workspace",
        root / "log_info",
        root / "backups",
    )
    if any(_directory_has_entries(path) for path in candidates):
        return True
    return _directory_has_entries(legacy.data)


def resolve_active_project_storage_paths(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> ProjectStoragePaths:
    """Use legacy state until verified migration makes the external root active."""

    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    if storage_migration_complete(target) or not legacy_project_state_present(target):
        return target
    return legacy_project_storage_paths(project_root, target=target, config_path=config_path)


def resolve_project_data_home(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve active project data while preserving explicit operator overrides."""

    root = _resolve_project_root(project_root)
    try:
        load_project_identity(root)
    except ProjectIdentityError:
        return root

    from config.paths import DATA_HOME_ENV, resolve_configured_data_home, resolve_data_home

    if str(os.environ.get(DATA_HOME_ENV) or "").strip():
        return resolve_data_home(config_path=config_path)
    if resolve_configured_data_home(config_path=config_path) is not None:
        return resolve_data_home(config_path=config_path)
    return resolve_active_project_storage_paths(
        root,
        projects_home=projects_home,
        config_path=config_path,
    ).data


def resolve_project_workspace_home(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    return (
        resolve_project_data_home(
            project_root,
            projects_home=projects_home,
            config_path=config_path,
        )
        / "workspace"
    ).resolve()


def resolve_project_runtime_home(project_root: str | os.PathLike[str]) -> Path:
    root = _resolve_project_root(project_root)
    try:
        return resolve_active_project_storage_paths(root).runtime
    except ProjectIdentityError:
        return root / ".runtime"


def resolve_project_logs_home(project_root: str | os.PathLike[str]) -> Path:
    root = _resolve_project_root(project_root)
    try:
        return resolve_active_project_storage_paths(root).logs
    except ProjectIdentityError:
        return root / "logs"


def resolve_project_memory_home(project_root: str | os.PathLike[str]) -> Path:
    root = _resolve_project_root(project_root)
    try:
        target = resolve_project_storage_paths(root)
    except ProjectIdentityError:
        return root / ".docs" / "project-memory"
    legacy = _integration_project_root(root) / ".docs" / "project-memory"
    if project_memory_migration_complete(target) or not _directory_has_entries(legacy):
        return target.memory
    return legacy


def resolve_project_cache_home(project_root: str | os.PathLike[str]) -> Path:
    root = _resolve_project_root(project_root)
    try:
        return resolve_active_project_storage_paths(root).cache
    except ProjectIdentityError:
        return root / ".cache"


def ensure_project_storage(paths: ProjectStoragePaths) -> ProjectStoragePaths:
    """Create external state directories without writing to the checkout."""

    for path in (paths.data, paths.runtime, paths.logs, paths.memory, paths.cache):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _resolve_project_root(project_root: str | os.PathLike[str]) -> Path:
    raw = str(project_root or "").strip()
    if not raw:
        raise ValueError("project_root must not be empty")
    return Path(raw).expanduser().resolve()


def _directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
    except (FileNotFoundError, NotADirectoryError, StopIteration, OSError):
        return False
    return True


def _integration_project_root(project_root: Path) -> Path:
    git_entry = project_root / ".git"
    if git_entry.is_dir():
        return project_root
    if not git_entry.is_file():
        return project_root
    try:
        text = git_entry.read_text(encoding="utf-8").strip()
    except OSError:
        return project_root
    if not text.lower().startswith("gitdir:"):
        return project_root
    git_dir = Path(text.split(":", 1)[1].strip()).expanduser()
    if not git_dir.is_absolute():
        git_dir = project_root / git_dir
    git_dir = git_dir.resolve()
    for candidate in (git_dir, *git_dir.parents):
        if candidate.name.lower() == ".git":
            return candidate.parent.resolve()
    return project_root


__all__ = [
    "PROJECTS_HOME_ENV",
    "PROJECT_IDENTITY_RELATIVE_PATH",
    "PROJECT_IDENTITY_SCHEMA_VERSION",
    "PROJECT_MEMORY_MIGRATION_STATE_NAME",
    "STORAGE_MIGRATION_SCHEMA_VERSION",
    "STORAGE_MIGRATION_STATE_NAME",
    "ProjectIdentity",
    "ProjectIdentityError",
    "ProjectStoragePaths",
    "default_projects_home",
    "ensure_project_storage",
    "instance_id_for_project",
    "load_project_identity",
    "legacy_project_state_present",
    "legacy_project_storage_paths",
    "normalize_instance_key",
    "resolve_project_data_home",
    "resolve_project_cache_home",
    "resolve_project_logs_home",
    "resolve_project_memory_home",
    "resolve_project_runtime_home",
    "resolve_active_project_storage_paths",
    "resolve_project_storage_paths",
    "resolve_project_workspace_home",
    "resolve_projects_home",
    "storage_migration_complete",
    "storage_migration_state_path",
    "project_memory_migration_complete",
    "project_memory_migration_state_path",
]
