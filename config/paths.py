"""Resolve and initialize Vibelution's local operator config paths."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH_ENV = "VIBELUTION_CONFIG_PATH"
CONFIG_HOME_ENV = "VIBELUTION_CONFIG_HOME"
CONFIG_FILENAME = "config.toml"
EXAMPLE_CONFIG_FILENAME = "config.example.toml"
CONFIG_META_FILENAME = "config.meta.json"
CONFIG_META_SCHEMA_VERSION = 3
CONFIG_STARTER_TEXT = """# Vibelution operator config
# Active operator config is stored outside the project repository.
# Edit this file through the Launcher or Config page so runtime processes reload it safely.
"""
EXAMPLE_CONFIG_STARTER_TEXT = """# Vibelution example operator config
# This example belongs to the external config home, not to the project repository.
"""


def default_config_home() -> Path:
    user_root = Path(os.environ.get("USERPROFILE") or Path.home()).expanduser()
    return user_root / "Documents" / "Vibelution" / "config"


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

    created_config = _write_if_missing(
        target,
        fallback_text=CONFIG_STARTER_TEXT,
        source_type="external_starter",
    )
    created_example = _write_if_missing(
        example_target,
        fallback_text=EXAMPLE_CONFIG_STARTER_TEXT,
        source_type="external_example_starter",
    )
    meta_path = target.with_name(CONFIG_META_FILENAME)
    existing_meta = _read_existing_meta(meta_path)
    config_created_now = bool(created_config.get("created"))
    example_created_now = bool(created_example.get("created"))
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
        "configSource": (
            str(created_config.get("sourceType") or "existing")
            if config_created_now
            else str(existing_meta.get("configSource") or "existing")
        ),
        "exampleConfigSource": (
            str(created_example.get("sourceType") or "existing")
            if example_created_now
            else str(existing_meta.get("exampleConfigSource") or "existing")
        ),
    }
    if _should_write_meta(meta_path, existing_meta, meta):
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "CONFIG_FILENAME",
    "CONFIG_HOME_ENV",
    "CONFIG_META_FILENAME",
    "CONFIG_META_SCHEMA_VERSION",
    "CONFIG_PATH_ENV",
    "EXAMPLE_CONFIG_FILENAME",
    "PROJECT_ROOT",
    "default_config_home",
    "ensure_global_config_initialized",
    "resolve_config_backup_dir",
    "resolve_config_home",
    "resolve_config_lock_path",
    "resolve_config_meta_path",
    "resolve_config_path",
    "resolve_example_config_path",
]
