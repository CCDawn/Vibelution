"""Bootstrap-safe external storage paths for project-scoped mutable state.

This module deliberately lives outside application packages so Launcher and
Runtime Manager bootstrap code can resolve paths without importing the full
configuration or infrastructure graph.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECTS_HOME_ENV = "VIBELUTION_PROJECTS_HOME"
PROJECT_IDENTITY_RELATIVE_PATH = Path(".vibelution") / "project.json"
PROJECT_IDENTITY_SCHEMA_VERSION = 1
STORAGE_MIGRATION_SCHEMA_VERSION = 1
STORAGE_MIGRATION_STATE_NAME = "storage-migration.json"
PROJECT_MEMORY_MIGRATION_STATE_NAME = "project-memory-migration.json"
# 迁移完成后由运维落在 legacy 目录内的墓碑文件：存在即宣告该目录退役，
# 任何解析分支都不得再把它当作可写的活跃记忆位置。
PROJECT_MEMORY_TOMBSTONE_NAME = "MIGRATED-DO-NOT-WRITE.txt"
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_FNV32_OFFSET = 2166136261
_FNV32_PRIME = 16777619
_CONFIG_PATHS_MODULE: ModuleType | None = None

# 进程内缓存：路径解析在 Windows 上每次 resolve()/stat 都是内核调用，
# 热路径单请求可达数万次。缓存一律以「输入参数 + 环境变量」为 key、
# 以依赖文件签名 (path, exists, mtime_ns, size) 为校验值，失效正确性优先于命中率。
_STORAGE_CACHE_LOCK = threading.RLock()
_CACHE_ENTRY_LIMIT = 256
_RESOLVED_ROOT_CACHE: dict[str, Path] = {}
_IDENTITY_CACHE: dict[
    str, tuple[tuple[str, bool, int, int], ProjectIdentity | ProjectIdentityError]
] = {}
_STORAGE_PATHS_CACHE: dict[
    tuple[object, ...], tuple[tuple[str, bool, int, int], ProjectStoragePaths]
] = {}
_ACTIVE_PATHS_CACHE: dict[
    tuple[object, ...],
    tuple[
        tuple[str, bool, int, int],
        tuple[str, bool, int, int],
        ProjectStoragePaths | ProjectStorageMigrationStateError,
    ],
] = {}
_RESOLVED_CONFIG_PATH_CACHE: dict[tuple[object, ...], Path] = {}
_DATA_HOME_CACHE: dict[tuple[object, ...], tuple[tuple[object, ...], Path]] = {}
_WORKSPACE_HOME_CACHE: dict[tuple[object, ...], tuple[tuple[object, ...], Path]] = {}


def _file_signature(path: Path) -> tuple[str, bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


def _cache_put(cache: dict[Any, Any], key: Any, value: Any) -> None:
    if len(cache) >= _CACHE_ENTRY_LIMIT:
        cache.clear()
    cache[key] = value


def _env_fingerprint(*names: str) -> tuple[str, ...]:
    return tuple(str(os.environ.get(name) or "") for name in names)


class ProjectIdentityError(ValueError):
    """Raised when a checkout has no valid tracked project identity."""


class ProjectStorageMigrationStateError(RuntimeError):
    """Raised when a present migration marker cannot authorize external storage."""


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
    signature = _file_signature(source_path)
    cache_key = str(root)
    with _STORAGE_CACHE_LOCK:
        cached = _IDENTITY_CACHE.get(cache_key)
        if cached is not None and cached[0] == signature:
            outcome = cached[1]
            if isinstance(outcome, ProjectIdentityError):
                raise outcome
            return outcome
    try:
        outcome: ProjectIdentity | ProjectIdentityError = _load_project_identity(
            root, source_path
        )
    except ProjectIdentityError as exc:
        outcome = exc
    with _STORAGE_CACHE_LOCK:
        _cache_put(_IDENTITY_CACHE, cache_key, (signature, outcome))
    if isinstance(outcome, ProjectIdentityError):
        raise outcome
    return outcome


def _load_project_identity(root: Path, source_path: Path) -> ProjectIdentity:
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
    cache_key = (
        str(project_root),
        None if projects_home is None else str(projects_home),
        _env_fingerprint(PROJECTS_HOME_ENV, "LOCALAPPDATA"),
    )
    root = _resolve_project_root(project_root)
    identity_signature = _file_signature(root / PROJECT_IDENTITY_RELATIVE_PATH)
    with _STORAGE_CACHE_LOCK:
        cached = _STORAGE_PATHS_CACHE.get(cache_key)
        if cached is not None and cached[0] == identity_signature:
            return cached[1]
    paths = _resolve_project_storage_paths(root, projects_home=projects_home)
    with _STORAGE_CACHE_LOCK:
        _cache_put(_STORAGE_PATHS_CACHE, cache_key, (identity_signature, paths))
    return paths


def _resolve_project_storage_paths(
    root: Path,
    *,
    projects_home: str | os.PathLike[str] | None = None,
) -> ProjectStoragePaths:
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
    payload = _valid_project_memory_migration_marker(paths)
    if payload is None:
        return False
    current_source = _integration_project_root(paths.project_root) / ".docs" / "project-memory"
    sources = payload.get("sources")
    return bool(
        isinstance(sources, list)
        and any(
            isinstance(item, dict)
            and _marker_path_matches(item.get("sourceRoot"), current_source)
            for item in sources
        )
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


def _load_config_paths_stdlib() -> ModuleType:
    """Load config/paths.py without executing config/__init__.py.

    Launcher bootstrap on a fresh clone has no project venv yet. Importing the
    ``config`` package pulls pydantic models and crashes before ``.venv`` can
    be created.
    """

    global _CONFIG_PATHS_MODULE
    if _CONFIG_PATHS_MODULE is not None:
        return _CONFIG_PATHS_MODULE
    paths_file = Path(__file__).resolve().parent / "config" / "paths.py"
    spec = importlib.util.spec_from_file_location("_vibelution_storage_config_paths", paths_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load stdlib config paths from {paths_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CONFIG_PATHS_MODULE = module
    return module


def legacy_project_storage_paths(
    project_root: str | os.PathLike[str],
    *,
    target: ProjectStoragePaths | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> ProjectStoragePaths:
    """Describe pre-governance locations without creating or modifying them."""

    root = _resolve_project_root(project_root)
    target_paths = target or resolve_project_storage_paths(root)
    resolve_data_home = _load_config_paths_stdlib().resolve_data_home

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
    """Use legacy state only before a migration marker exists.

    A present marker is a cutover boundary. Invalid marker contents therefore
    fail closed instead of silently routing writes back into checkout storage.
    """

    root = _resolve_project_root(project_root)
    identity_signature = _file_signature(root / PROJECT_IDENTITY_RELATIVE_PATH)
    target = resolve_project_storage_paths(root, projects_home=projects_home)
    marker_signature = _file_signature(storage_migration_state_path(target))
    if marker_signature[1]:
        # marker 存在即迁移定界：结果只依赖 identity/marker 内容，可安全缓存。
        cache_key = (
            str(project_root),
            None if projects_home is None else str(projects_home),
            _env_fingerprint(PROJECTS_HOME_ENV, "LOCALAPPDATA"),
        )
        with _STORAGE_CACHE_LOCK:
            cached = _ACTIVE_PATHS_CACHE.get(cache_key)
            if (
                cached is not None
                and cached[0] == identity_signature
                and cached[1] == marker_signature
            ):
                outcome = cached[2]
                if isinstance(outcome, ProjectStorageMigrationStateError):
                    raise outcome
                return outcome
        if storage_migration_complete(target):
            outcome = target
        else:
            outcome = ProjectStorageMigrationStateError("storage_migration_marker_invalid")
        with _STORAGE_CACHE_LOCK:
            _cache_put(
                _ACTIVE_PATHS_CACHE,
                cache_key,
                (identity_signature, marker_signature, outcome),
            )
        if isinstance(outcome, ProjectStorageMigrationStateError):
            raise outcome
        return outcome
    # marker 缺失：可能处于迁移前/迁移中，legacy 判定保持实时，不缓存。
    if not legacy_project_state_present(target):
        return target
    return legacy_project_storage_paths(root, target=target, config_path=config_path)


def _resolve_config_path_cached(
    paths_mod: ModuleType,
    config_path: str | os.PathLike[str] | None,
) -> Path:
    raw_value = (
        config_path
        if config_path is not None
        else str(os.environ.get(paths_mod.CONFIG_PATH_ENV) or "")
    )
    cacheable = True
    if raw_value:
        raw_text = str(raw_value).strip()
        # 相对路径依赖 cwd、~ 依赖 HOME/USERPROFILE，保守起见不缓存。
        cacheable = not raw_text.startswith("~") and Path(raw_text).expanduser().is_absolute()
    cache_key = (
        None if config_path is None else str(config_path),
        _env_fingerprint(paths_mod.CONFIG_PATH_ENV, paths_mod.CONFIG_HOME_ENV, "USERPROFILE"),
    )
    if cacheable:
        with _STORAGE_CACHE_LOCK:
            cached = _RESOLVED_CONFIG_PATH_CACHE.get(cache_key)
            if cached is not None:
                return cached
    resolved = paths_mod.resolve_config_path(config_path)
    if cacheable:
        with _STORAGE_CACHE_LOCK:
            _cache_put(_RESOLVED_CONFIG_PATH_CACHE, cache_key, resolved)
    return resolved


def _data_home_fingerprint(
    root: Path,
    paths_mod: ModuleType,
    *,
    projects_home: str | os.PathLike[str] | None,
    config_path: str | os.PathLike[str] | None,
) -> tuple[object, ...]:
    identity_signature = _file_signature(root / PROJECT_IDENTITY_RELATIVE_PATH)
    config_signature = _file_signature(_resolve_config_path_cached(paths_mod, config_path))
    try:
        target = resolve_project_storage_paths(root, projects_home=projects_home)
    except ProjectIdentityError:
        marker_signature: tuple[str, bool, int, int] | None = None
    else:
        marker_signature = _file_signature(storage_migration_state_path(target))
    return (identity_signature, config_signature, marker_signature)


def resolve_project_data_home(
    project_root: str | os.PathLike[str],
    *,
    projects_home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve active project data while preserving explicit operator overrides."""

    paths_mod = _load_config_paths_stdlib()
    cache_key = (
        str(project_root),
        None if projects_home is None else str(projects_home),
        None if config_path is None else str(config_path),
        _env_fingerprint(
            paths_mod.DATA_HOME_ENV,
            PROJECTS_HOME_ENV,
            "LOCALAPPDATA",
            "USERPROFILE",
            paths_mod.CONFIG_PATH_ENV,
            paths_mod.CONFIG_HOME_ENV,
        ),
    )
    root = _resolve_project_root(project_root)
    fingerprint = _data_home_fingerprint(
        root, paths_mod, projects_home=projects_home, config_path=config_path
    )
    with _STORAGE_CACHE_LOCK:
        cached = _DATA_HOME_CACHE.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    result = _resolve_project_data_home(
        root, paths_mod, projects_home=projects_home, config_path=config_path
    )
    with _STORAGE_CACHE_LOCK:
        _cache_put(_DATA_HOME_CACHE, cache_key, (fingerprint, result))
    return result


def _resolve_project_data_home(
    root: Path,
    paths_mod: ModuleType,
    *,
    projects_home: str | os.PathLike[str] | None,
    config_path: str | os.PathLike[str] | None,
) -> Path:
    try:
        load_project_identity(root)
    except ProjectIdentityError:
        return root

    if str(os.environ.get(paths_mod.DATA_HOME_ENV) or "").strip():
        return paths_mod.resolve_data_home(config_path=config_path)
    if paths_mod.resolve_configured_data_home(config_path=config_path) is not None:
        return paths_mod.resolve_data_home(config_path=config_path)
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
    paths_mod = _load_config_paths_stdlib()
    cache_key = (
        str(project_root),
        None if projects_home is None else str(projects_home),
        None if config_path is None else str(config_path),
        _env_fingerprint(
            paths_mod.DATA_HOME_ENV,
            PROJECTS_HOME_ENV,
            "LOCALAPPDATA",
            "USERPROFILE",
            paths_mod.CONFIG_PATH_ENV,
            paths_mod.CONFIG_HOME_ENV,
        ),
    )
    root = _resolve_project_root(project_root)
    fingerprint = _data_home_fingerprint(
        root, paths_mod, projects_home=projects_home, config_path=config_path
    )
    with _STORAGE_CACHE_LOCK:
        cached = _WORKSPACE_HOME_CACHE.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    result = (
        resolve_project_data_home(
            root,
            projects_home=projects_home,
            config_path=config_path,
        )
        / "workspace"
    ).resolve()
    with _STORAGE_CACHE_LOCK:
        _cache_put(_WORKSPACE_HOME_CACHE, cache_key, (fingerprint, result))
    return result


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
        _raise_if_legacy_memory_retired(root / ".docs" / "project-memory")
        return root / ".docs" / "project-memory"
    legacy = _integration_project_root(root) / ".docs" / "project-memory"
    marker_path = project_memory_migration_state_path(target)
    if marker_path.exists():
        payload = _valid_project_memory_migration_marker(target)
        if payload is None:
            raise ProjectStorageMigrationStateError(
                "project_memory_migration_marker_invalid"
            )
        current_source = _integration_project_root(root) / ".docs" / "project-memory"
        if any(
            _marker_path_matches(item.get("sourceRoot"), current_source)
            for item in payload["sources"]
        ):
            return target.memory
    if not _directory_has_entries(legacy):
        return target.memory
    _raise_if_legacy_memory_retired(legacy)
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
    path = Path(raw).expanduser()
    if not path.is_absolute() or raw.startswith("~"):
        # 相对路径依赖进程 cwd、~ 依赖 HOME/USERPROFILE，不进缓存。
        return path.resolve()
    with _STORAGE_CACHE_LOCK:
        cached = _RESOLVED_ROOT_CACHE.get(raw)
        if cached is not None:
            return cached
        resolved = path.resolve()
        _cache_put(_RESOLVED_ROOT_CACHE, raw, resolved)
        return resolved


def _directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
    except (FileNotFoundError, NotADirectoryError, StopIteration, OSError):
        return False
    return True


def _raise_if_legacy_memory_retired(legacy: Path) -> None:
    if (legacy / PROJECT_MEMORY_TOMBSTONE_NAME).is_file():
        raise ProjectStorageMigrationStateError(
            "project_memory_legacy_retired: "
            f"{legacy} carries {PROJECT_MEMORY_TOMBSTONE_NAME}; this legacy memory "
            "location is retired and must not resolve as the active memory home. "
            "Restore the projects home / tracked identity, or deliberately remove "
            "the tombstone."
        )


def _valid_project_memory_migration_marker(
    paths: ProjectStoragePaths,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(
            project_memory_migration_state_path(paths).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not (
        isinstance(payload, dict)
        and payload.get("schemaVersion") == STORAGE_MIGRATION_SCHEMA_VERSION
        and payload.get("status") == "completed"
        and str(payload.get("projectId") or "") == paths.project_id
        and _marker_path_matches(payload.get("targetRoot"), paths.memory)
    ):
        return None
    sources = payload.get("sources")
    if not (
        isinstance(sources, list)
        and sources
        and all(
            isinstance(item, dict) and str(item.get("sourceRoot") or "").strip()
            for item in sources
        )
    ):
        return None
    return payload


def _marker_path_matches(value: object, expected: Path) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        actual = Path(raw).expanduser().resolve()
        target = expected.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return os.path.normcase(str(actual)) == os.path.normcase(str(target))


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
    "ProjectStorageMigrationStateError",
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
