"""Resolve and initialize Vibelution's local operator config paths."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH_ENV = "VIBELUTION_CONFIG_PATH"
CONFIG_HOME_ENV = "VIBELUTION_CONFIG_HOME"
DATA_HOME_ENV = "VIBELUTION_DATA_HOME"
CONFIG_FILENAME = "config.toml"
MODEL_CATALOG_STATE_FILENAME = "model-catalog-state.json"
EXAMPLE_CONFIG_FILENAME = "config.example.toml"
CONFIG_META_FILENAME = "config.meta.json"
CONFIG_META_SCHEMA_VERSION = 3
_CONFIGURED_DATA_HOME_CACHE: dict[str, tuple[int, int, Path | None]] = {}

# Auto-advance (activation) policy document resolution: operator config.toml
# first, the historical env var second, then a default file in the operator
# config home.  Keyed by ``[research_workflow].auto_advance_policy_path``.
AUTO_ADVANCE_POLICY_PATH_ENV = "VIBELUTION_AUTO_ADVANCE_POLICY_PATH"
AUTO_ADVANCE_POLICY_FILENAME = "auto-advance-policy.active.json"
AUTO_ADVANCE_POLICY_CONFIG_SECTION = "research_workflow"
AUTO_ADVANCE_POLICY_CONFIG_KEY = "auto_advance_policy_path"
_AUTO_ADVANCE_POLICY_PATH_CACHE: dict[str, tuple[int, int, Path | None]] = {}

if TYPE_CHECKING:
    # Runtime access stays lazy through __getattr__ to avoid the
    # paths -> operator_bootstrap -> public_config import cycle.
    CONFIG_STARTER_TEXT: str
    EXAMPLE_CONFIG_STARTER_TEXT: str


def _render_starter_text(*, example: bool = False) -> str:
    """Materialize starter TOML from project-fixed vendor templates."""

    from config.operator_bootstrap import render_default_operator_config_text

    return render_default_operator_config_text(example=example)


def _get_config_starter_text() -> str:
    return _render_starter_text(example=False)


def _get_example_config_starter_text() -> str:
    return _render_starter_text(example=True)


def __getattr__(name: str) -> Any:
    """Expose generated starter text under the historical constant names."""

    if name == "CONFIG_STARTER_TEXT":
        return _get_config_starter_text()
    if name == "EXAMPLE_CONFIG_STARTER_TEXT":
        return _get_example_config_starter_text()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_config_home() -> Path:
    user_root = Path(os.environ.get("USERPROFILE") or Path.home()).expanduser()
    return user_root / "Documents" / "Vibelution" / "config"


def default_data_home() -> Path:
    user_root = Path(os.environ.get("USERPROFILE") or Path.home()).expanduser()
    return user_root / "Documents" / "Vibelution" / "data"


def resolve_config_home() -> Path:
    raw = str(os.environ.get(CONFIG_HOME_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_config_home().resolve()


def resolve_config_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    raw = str(os.environ.get(CONFIG_PATH_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (resolve_config_home() / CONFIG_FILENAME).resolve()


def resolve_model_catalog_state_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    return resolve_config_path(config_path).with_name(MODEL_CATALOG_STATE_FILENAME)


def resolve_data_home(
    data_home: str | os.PathLike[str] | None = None,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    if data_home is not None:
        return _resolve_operator_path(data_home)
    raw = str(os.environ.get(DATA_HOME_ENV) or "").strip()
    if raw:
        return _resolve_operator_path(raw)
    configured = _configured_data_home(config_path=config_path)
    if configured:
        return configured
    return default_data_home().resolve()


def resolve_configured_data_home(
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Return only an explicit ``[storage].data_home`` operator override."""

    return _configured_data_home(config_path=config_path)


def resolve_workspace_home(
    data_home: str | os.PathLike[str] | None = None,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    return (resolve_data_home(data_home, config_path=config_path) / "workspace").resolve()


def resolve_example_config_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    config = resolve_config_path(config_path)
    return config.with_name(EXAMPLE_CONFIG_FILENAME)


def resolve_config_meta_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    config = resolve_config_path(config_path)
    return config.with_name(CONFIG_META_FILENAME)


def resolve_config_backup_dir(config_path: str | os.PathLike[str] | None = None) -> Path:
    config = resolve_config_path(config_path)
    return config.parent / "backups"


def resolve_config_lock_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    config = resolve_config_path(config_path)
    return config.parent / "config-edit.lock"


def resolve_data_backup_dir(
    data_home: str | os.PathLike[str] | None = None,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> Path:
    return resolve_data_home(data_home, config_path=config_path) / "backups"


def ensure_global_config_initialized(
    config_path: str | os.PathLike[str] | None = None,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Create the external operator config once without reading project-local config."""

    _ = project_root  # Kept for older callers; project-local config is no longer a migration source.
    target = resolve_config_path(config_path)
    example_target = target.with_name(EXAMPLE_CONFIG_FILENAME)
    backup_dir = target.parent / "backups"
    lock_path = target.parent / "config-edit.lock"
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    starter_text = _get_config_starter_text()
    example_text = _get_example_config_starter_text()
    created_config = _write_if_missing(
        target,
        fallback_text=starter_text,
        source_type="external_starter",
    )
    upgraded_config = {"created": False, "sourceType": "existing", "sourcePath": str(target)}
    if not created_config.get("created"):
        upgraded_config = _maybe_upgrade_thin_local_starter(
            target,
            backup_dir=backup_dir,
            starter_text=starter_text,
        )
    created_example = _write_if_missing(
        example_target,
        fallback_text=example_text,
        source_type="external_example_starter",
    )
    meta_path = target.with_name(CONFIG_META_FILENAME)
    existing_meta = _read_existing_meta(meta_path)
    config_created_now = bool(created_config.get("created"))
    config_upgraded_now = bool(upgraded_config.get("created"))
    example_created_now = bool(created_example.get("created"))
    if config_created_now:
        config_source = str(created_config.get("sourceType") or "external_starter")
    elif config_upgraded_now:
        config_source = str(upgraded_config.get("sourceType") or "external_starter_upgrade")
    else:
        config_source = str(existing_meta.get("configSource") or "existing")
    if target.exists():
        from config.llm_schema_upgrader import upgrade_persisted_llm_schema_if_needed

        upgrade_persisted_llm_schema_if_needed(target)
    meta = {
        "schemaVersion": CONFIG_META_SCHEMA_VERSION,
        "configHome": str(target.parent),
        "configPath": str(target),
        "exampleConfigPath": str(example_target),
        "backupDir": str(backup_dir),
        "lockPath": str(lock_path),
        "configPathEnv": str(os.environ.get(CONFIG_PATH_ENV) or ""),
        "configHomeEnv": str(os.environ.get(CONFIG_HOME_ENV) or ""),
        "createdAt": str(existing_meta.get("createdAt") or _now_iso()),
        "createdConfig": bool(existing_meta.get("createdConfig")) or config_created_now,
        "createdExampleConfig": bool(existing_meta.get("createdExampleConfig")) or example_created_now,
        "upgradedThinStarter": bool(existing_meta.get("upgradedThinStarter")) or config_upgraded_now,
        "configSource": config_source,
        "exampleConfigSource": (
            str(created_example.get("sourceType") or "existing")
            if example_created_now
            else str(existing_meta.get("exampleConfigSource") or "existing")
        ),
    }
    if _should_write_meta(meta_path, existing_meta, meta):
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def _maybe_upgrade_thin_local_starter(
    target: Path,
    *,
    backup_dir: Path,
    starter_text: str,
) -> dict[str, Any]:
    """Upgrade legacy local-only starter once; never overwrite customized configs."""

    if not target.exists():
        return {"created": False, "sourceType": "missing", "sourcePath": str(target)}
    try:
        import tomllib

        current_text = target.read_text(encoding="utf-8")
        current = tomllib.loads(current_text)
    except (OSError, ValueError):
        return {"created": False, "sourceType": "existing", "sourcePath": str(target)}

    from config.operator_bootstrap import (
        is_legacy_thin_local_only_starter_text,
        is_thin_local_only_starter,
    )

    if not is_thin_local_only_starter(
        current
    ) or not is_legacy_thin_local_only_starter_text(current_text):
        return {"created": False, "sourceType": "existing", "sourcePath": str(target)}

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"operator-config-thin-starter-before-{stamp}.toml"
    try:
        backup_path.write_text(current_text, encoding="utf-8")
        target.write_text(starter_text, encoding="utf-8")
    except OSError:
        return {"created": False, "sourceType": "existing", "sourcePath": str(target)}
    return {
        "created": True,
        "sourceType": "external_starter_upgrade",
        "sourcePath": str(backup_path),
    }


def _write_if_missing(
    target: Path,
    *,
    fallback_text: str,
    source_type: str,
) -> dict[str, Any]:
    if target.exists():
        return {"created": False, "sourceType": "existing", "sourcePath": str(target)}
    target.write_text(fallback_text, encoding="utf-8")
    return {"created": True, "sourceType": source_type, "sourcePath": ""}


def _read_existing_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _should_write_meta(meta_path: Path, existing_meta: dict[str, Any], next_meta: dict[str, Any]) -> bool:
    if not meta_path.exists():
        return True
    return any(existing_meta.get(key) != value for key, value in next_meta.items())


def _configured_data_home(*, config_path: str | os.PathLike[str] | None = None) -> Path | None:
    path = resolve_config_path(config_path)
    try:
        stat = path.stat()
    except OSError:
        _CONFIGURED_DATA_HOME_CACHE.pop(str(path), None)
        return None
    cache_key = str(path)
    cached = _CONFIGURED_DATA_HOME_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    try:
        import tomllib

        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        _CONFIGURED_DATA_HOME_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, None)
        return None
    storage = payload.get("storage") if isinstance(payload, dict) else None
    if not isinstance(storage, dict):
        _CONFIGURED_DATA_HOME_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, None)
        return None
    raw = str(storage.get("data_home") or "").strip()
    if not raw:
        _CONFIGURED_DATA_HOME_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, None)
        return None
    resolved = _resolve_operator_path(raw, base_dir=path.parent)
    _CONFIGURED_DATA_HOME_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, resolved)
    return resolved


def _resolve_operator_path(value: str | os.PathLike[str], *, base_dir: Path | None = None) -> Path:
    raw = os.path.expandvars(str(value)).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def configured_auto_advance_policy_path(
    *, config_path: str | os.PathLike[str] | None = None
) -> Path | None:
    """Return only an explicit ``[research_workflow]`` policy path override."""

    path = resolve_config_path(config_path)
    try:
        stat = path.stat()
    except OSError:
        _AUTO_ADVANCE_POLICY_PATH_CACHE.pop(str(path), None)
        return None
    cache_key = str(path)
    cached = _AUTO_ADVANCE_POLICY_PATH_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    resolved: Path | None = None
    try:
        import tomllib

        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        section = (
            payload.get(AUTO_ADVANCE_POLICY_CONFIG_SECTION)
            if isinstance(payload, dict)
            else None
        )
        raw = (
            str(section.get(AUTO_ADVANCE_POLICY_CONFIG_KEY) or "").strip()
            if isinstance(section, dict)
            else ""
        )
        if raw:
            resolved = _resolve_operator_path(raw, base_dir=path.parent)
    except (OSError, ValueError):
        resolved = None
    _AUTO_ADVANCE_POLICY_PATH_CACHE[cache_key] = (
        stat.st_mtime_ns,
        stat.st_size,
        resolved,
    )
    return resolved


def resolve_auto_advance_policy_path(
    *, config_path: str | os.PathLike[str] | None = None
) -> Path:
    """Activation policy document precedence: config.toml -> env -> default.

    ``[research_workflow].auto_advance_policy_path`` in the operator config
    wins (env propagation into backend processes is unreliable), then
    ``VIBELUTION_AUTO_ADVANCE_POLICY_PATH``, then
    ``<config-home>/auto-advance-policy.active.json``.  The caller decides
    whether the resolved file must exist (a missing default behaves like no
    policy configured).
    """

    configured = configured_auto_advance_policy_path(config_path=config_path)
    if configured is not None:
        return configured
    raw = str(os.environ.get(AUTO_ADVANCE_POLICY_PATH_ENV) or "").strip()
    if raw:
        return _resolve_operator_path(raw)
    return (resolve_config_home() / AUTO_ADVANCE_POLICY_FILENAME).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AUTO_ADVANCE_POLICY_CONFIG_KEY",
    "AUTO_ADVANCE_POLICY_CONFIG_SECTION",
    "AUTO_ADVANCE_POLICY_FILENAME",
    "AUTO_ADVANCE_POLICY_PATH_ENV",
    "CONFIG_FILENAME",
    "CONFIG_STARTER_TEXT",
    "DATA_HOME_ENV",
    "CONFIG_HOME_ENV",
    "CONFIG_META_FILENAME",
    "CONFIG_META_SCHEMA_VERSION",
    "CONFIG_PATH_ENV",
    "EXAMPLE_CONFIG_FILENAME",
    "EXAMPLE_CONFIG_STARTER_TEXT",
    "MODEL_CATALOG_STATE_FILENAME",
    "PROJECT_ROOT",
    "configured_auto_advance_policy_path",
    "default_config_home",
    "default_data_home",
    "ensure_global_config_initialized",
    "resolve_auto_advance_policy_path",
    "resolve_config_backup_dir",
    "resolve_config_home",
    "resolve_config_lock_path",
    "resolve_config_meta_path",
    "resolve_model_catalog_state_path",
    "resolve_config_path",
    "resolve_configured_data_home",
    "resolve_data_backup_dir",
    "resolve_data_home",
    "resolve_example_config_path",
    "resolve_workspace_home",
]
