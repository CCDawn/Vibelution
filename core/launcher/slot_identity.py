"""Per-checkout slot identity and isolated data home.

Slot identity is the normalized checkout path, not a branch slug. Vibelution
checkouts with a tracked project identity use the canonical external project
storage root. The historical ``slots`` root remains a compatibility fallback
for third-party or fixture checkouts that do not yet carry that identity.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from config.paths import CONFIG_HOME_ENV, DATA_HOME_ENV, resolve_config_home
from vibelution_storage import (
    ProjectIdentityError,
    instance_id_for_project,
    resolve_active_project_storage_paths,
)

WORKSPACE_ROOT_ENV = "VIBELUTION_WORKSPACE_ROOT"
_FNV32_OFFSET = 2166136261
_FNV32_PRIME = 16777619


def normalize_slot_key(project_root: str | os.PathLike[str]) -> str:
    raw = str(project_root or "").strip()
    if not raw:
        raise ValueError("project_root must not be empty")
    return os.path.normcase(str(Path(raw).expanduser().resolve()))


def slot_id_for_key(slot_key: str) -> str:
    digest = _FNV32_OFFSET
    for byte in str(slot_key or "").encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV32_PRIME) & 0xFFFFFFFF
    return f"{digest:08x}"


def slot_id_for_project(project_root: str | os.PathLike[str]) -> str:
    return instance_id_for_project(project_root)


def slots_root() -> Path:
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return (root / "Vibelution" / "slots").resolve()


def slot_data_home(slot_id: str) -> Path:
    safe_id = str(slot_id or "").strip()
    if not safe_id:
        raise ValueError("slot_id must not be empty")
    return (slots_root() / safe_id / "data").resolve()


def data_home_for_project(project_root: str | os.PathLike[str]) -> Path:
    try:
        return resolve_active_project_storage_paths(project_root).data.resolve()
    except ProjectIdentityError:
        return slot_data_home(slot_id_for_project(project_root))


def apply_slot_spawn_environment(
    env: dict[str, str] | None,
    project_root: str | os.PathLike[str],
    *,
    backend_port: int | None = None,
    control_port: int | None = None,
    mkdir: bool = True,
) -> dict[str, str]:
    """Inject per-slot data home and shared operator config into a child env."""

    next_env = {str(key): str(value) for key, value in dict(env or {}).items()}
    resolved_root = Path(str(project_root).strip()).expanduser().resolve()
    data_home = data_home_for_project(resolved_root)
    if mkdir:
        data_home.mkdir(parents=True, exist_ok=True)
    next_env[WORKSPACE_ROOT_ENV] = str(resolved_root)
    next_env[DATA_HOME_ENV] = str(data_home)
    next_env[CONFIG_HOME_ENV] = str(resolve_config_home())
    if int(backend_port or 0) > 0:
        next_env["VIBELUTION_PORT"] = str(int(backend_port))
        next_env["AGENT_WORKBENCH_BACKEND_PORT"] = str(int(backend_port))
    if int(control_port or 0) > 0:
        next_env["VIBELUTION_LAUNCHER_PORT"] = str(int(control_port))
        next_env["AGENT_LAUNCHER_CONTROL_PORT"] = str(int(control_port))
    return next_env


def slot_fields_for_project(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    slot_key = normalize_slot_key(project_root)
    slot_id = slot_id_for_key(slot_key)
    return {
        "slotKey": slot_key,
        "slotId": slot_id,
        "dataHome": str(data_home_for_project(project_root)),
    }
