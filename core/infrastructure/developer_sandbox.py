"""Global no-trace developer sandbox routing.

The external config flag remains under ``launcher.developer_mode`` because the
Launcher owns the control surface, but the behavior is global: product writes
can be routed into an ephemeral sandbox while formal state stays read-only.
"""

from __future__ import annotations

import json
import shutil
from threading import RLock
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.paths import resolve_workspace_home
from config.public_config import CONFIG_PATH, load_public_config, public_config_hash, save_public_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_SCHEMA_VERSION = 1
CONFIG_SECTION = "launcher"
CONFIG_KEY = "developer_mode"
RUNTIME_DIR = ".runtime/developer-mode"
SANDBOXES_DIR = "sandboxes"
ACTIVE_STATE_NAME = "active.json"
DEBUG_RECORD_KIND = "debug"
DEBUG_RETENTION = "diagnostic_only"
WRITE_POLICY_FORMAL_ONLY = "formal_only"
WRITE_POLICY_SANDBOXED = "sandboxed"
WRITE_POLICY_DEBUG_ONLY = "debug_only"
WRITE_POLICY_BLOCKED_IN_DEV = "blocked_in_dev"
WRITE_POLICY_OVERLAY = "overlay"
VALID_WRITE_POLICIES = {
    WRITE_POLICY_FORMAL_ONLY,
    WRITE_POLICY_SANDBOXED,
    WRITE_POLICY_DEBUG_ONLY,
    WRITE_POLICY_BLOCKED_IN_DEV,
    WRITE_POLICY_OVERLAY,
}

LEGACY_DIRECT_WORKSPACE_WRITE_SURFACES = {
    "core/infrastructure/workspace_manager.py": "memory",
    "core/web/services/memory_service.py": "memory",
    "core/web/services/team_knowledge_service.py": "team_knowledge",
    "core/web/services/rag_vector_index_service.py": "rag",
    "core/web/services/project_agent_bus_service.py": "project_agent_bus",
    "core/web/services/agent_directory_service.py": "agent_directory",
    "core/gym/promotion.py": "gym",
    "core/evaluation/dataset_registry.py": "evaluation_dataset",
}

_FORMAL_CONTROL_SURFACES = {
    "launcher",
    "launcher_state",
    "runtime_manager",
    "runtime_lifecycle",
}
_FORMAL_CONTROL_INTENTS = {
    "control",
    "control_state",
    "lifecycle",
    "lifecycle_state",
    "formal_save",
}
_OVERLAY_SURFACES = {"config", "llm_config", "model_config", "tool_config"}
_OVERLAY_INTENTS = {"draft", "experiment", "overlay", "probe", "model_probe"}
_BLOCKED_PROMOTION_INTENTS = {
    "activation",
    "advisory_activation",
    "apply_promotion",
    "central_promotion",
    "formal_dataset",
    "official_graph",
    "promotion",
    "promotion_activate",
    "promotion_apply",
    "promotion_rollback",
}
_BLOCKED_PROMOTION_SURFACES = {"gym", "knowledge", "rag", "team_knowledge"}
_DEBUG_ONLY_SURFACES = {"runtime_scene", "diagnostics", "logs"}
_SANDBOXED_SURFACE_DEFAULTS = {
    "agent_directory",
    "chat",
    "chat_dataset",
    "chat_room",
    "computer_use",
    "evaluation_dataset",
    "gym",
    "knowledge",
    "memory",
    "project_agent_bus",
    "prompt_manager",
    "rag",
    "session",
    "supervised_evolution",
    "team",
    "team_knowledge",
}
_CONFIG_CACHE_LOCK = RLock()
_CONFIG_CACHE: dict[tuple[str, int | None, int | None], tuple[dict[str, Any], str]] = {}


class DeveloperSandboxConfigConflict(ValueError):
    """Raised when the developer mode config changed under the caller."""

    def __init__(self, expected_hash: str, current_hash: str) -> None:
        super().__init__("Developer mode config changed before save.")
        self.expected_hash = expected_hash
        self.current_hash = current_hash


class DeveloperSandboxWriteBlocked(PermissionError):
    """Raised when developer mode blocks a formal write by policy."""

    def __init__(self, surface: str, intent: str, policy: str = WRITE_POLICY_BLOCKED_IN_DEV) -> None:
        message = f"Developer mode blocks formal write for surface={surface!r}, intent={intent!r}."
        super().__init__(message)
        self.surface = surface
        self.intent = intent
        self.policy = policy


def get_developer_mode_status(
    *,
    config_path: Path | None = None,
    project_root: Path | None = None,
    ensure_sandbox: bool = False,
) -> dict[str, Any]:
    """Return the global developer sandbox mode status."""

    root = _project_root(project_root)
    public_config, config_hash, resolved_config_path = _load_public_config_with_hash(config_path)
    setting = _raw_setting(public_config)
    enabled = bool(setting.get("enabled", False))
    state = _ensure_active_state(root) if enabled and ensure_sandbox else _read_active_state(root)
    sandbox_id = str(state.get("sandboxId") or "").strip() if enabled else ""
    sandbox_root = _sandbox_root(root, sandbox_id) if sandbox_id else None
    return {
        "schemaVersion": SANDBOX_SCHEMA_VERSION,
        "enabled": enabled,
        "defaulted": not bool(setting),
        "updatedAt": str(setting.get("updated_at") or ""),
        "updatedBy": str(setting.get("updated_by") or ""),
        "controller": "launcher",
        "scope": "global",
        "mode": "ephemeral_sandbox",
        "configPath": str(resolved_config_path),
        "configHash": config_hash,
        "sandbox": {
            "sandboxId": sandbox_id,
            "root": str(sandbox_root) if sandbox_root is not None else "",
            "statePath": str(_active_state_path(root)),
            "active": bool(enabled and sandbox_id),
            "createdAt": str(state.get("createdAt") or "") if sandbox_id else "",
            "persistedAcrossRestarts": True,
            "clearOnDisable": True,
            "clearOnReset": True,
        },
        "policy": {
            "settingsPageMutable": False,
            "requiresLauncher": True,
            "requiresPreview": True,
            "requiresPlanHash": True,
            "requiresConfirm": True,
            "defaultWhenMissing": False,
            "scope": "global",
            "noTrace": True,
            "readsFormalState": True,
            "writesSandboxedState": True,
            "logsDiagnosticRecords": True,
            "debugRecordKind": DEBUG_RECORD_KIND,
            "debugRetention": DEBUG_RETENTION,
            "sandboxSurvivesRestart": True,
        },
    }


def developer_write_policy(surface: str, intent: str = "state") -> str:
    """Return the developer-mode write policy for one product write surface."""

    surface_token = _policy_token(surface, default="runtime")
    intent_token = _policy_token(intent, default="state")
    if surface_token in _FORMAL_CONTROL_SURFACES or intent_token in _FORMAL_CONTROL_INTENTS:
        return WRITE_POLICY_FORMAL_ONLY
    if surface_token in _OVERLAY_SURFACES or intent_token in _OVERLAY_INTENTS:
        return WRITE_POLICY_OVERLAY
    if surface_token in _DEBUG_ONLY_SURFACES:
        return WRITE_POLICY_DEBUG_ONLY
    if surface_token in _BLOCKED_PROMOTION_SURFACES and intent_token in _BLOCKED_PROMOTION_INTENTS:
        return WRITE_POLICY_BLOCKED_IN_DEV
    if surface_token in _SANDBOXED_SURFACE_DEFAULTS:
        return WRITE_POLICY_SANDBOXED
    return WRITE_POLICY_SANDBOXED


def route_workspace_path(
    project_root: Path,
    surface: str,
    *parts: str,
    intent: str = "state",
    seed: bool = False,
) -> Path:
    """Route a product workspace path through the active developer policy."""

    root = _project_root(project_root)
    policy = developer_write_policy(surface, intent)
    if policy == WRITE_POLICY_BLOCKED_IN_DEV:
        if is_developer_mode_enabled():
            raise DeveloperSandboxWriteBlocked(
                _policy_token(surface, default="runtime"),
                _policy_token(intent, default="state"),
            )
        return formal_workspace_path(root, *parts)
    if policy in {WRITE_POLICY_SANDBOXED, WRITE_POLICY_OVERLAY, WRITE_POLICY_DEBUG_ONLY}:
        return seeded_sandbox_workspace_path(root, *parts) if seed else sandboxed_workspace_path(root, *parts)
    return formal_workspace_path(root, *parts)


def route_runtime_path(
    project_root: Path,
    surface: str,
    *parts: str,
    intent: str = "state",
) -> Path:
    """Route a runtime path while keeping formal lifecycle controls formal."""

    root = _project_root(project_root)
    policy = developer_write_policy(surface, intent)
    if policy == WRITE_POLICY_BLOCKED_IN_DEV:
        if is_developer_mode_enabled():
            raise DeveloperSandboxWriteBlocked(
                _policy_token(surface, default="runtime"),
                _policy_token(intent, default="state"),
            )
        return root.joinpath(".runtime", *parts)
    if policy in {WRITE_POLICY_SANDBOXED, WRITE_POLICY_OVERLAY, WRITE_POLICY_DEBUG_ONLY} and is_developer_mode_enabled():
        active_root = sandbox_root(root, ensure=True)
        if active_root is not None:
            return active_root.joinpath(".runtime", *parts)
    return root.joinpath(".runtime", *parts)


def update_developer_mode_status(
    enabled: object,
    *,
    base_hash: str = "",
    config_path: Path | None = None,
    project_root: Path | None = None,
    updated_by: str = "launcher",
) -> dict[str, Any]:
    """Persist the global developer mode flag and manage its active sandbox."""

    root = _project_root(project_root)
    public_config = load_public_config(config_path or CONFIG_PATH)
    current_hash = public_config_hash(public_config)
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != current_hash:
        raise DeveloperSandboxConfigConflict(expected_hash, current_hash)

    normalized = _parse_bool(enabled, label="enabled")
    launcher = _ensure_section(public_config, CONFIG_SECTION)
    launcher[CONFIG_KEY] = {
        "enabled": normalized,
        "updated_at": _utcnow(),
        "updated_by": str(updated_by or "launcher").strip() or "launcher",
    }
    save_public_config(public_config, config_path or CONFIG_PATH)
    if normalized:
        state = _ensure_active_state(root)
    else:
        state = _read_active_state(root)
        clear_active_sandbox(project_root=root)
    _clear_developer_mode_config_cache()
    status = get_developer_mode_status(
        config_path=config_path,
        project_root=root,
        ensure_sandbox=normalized,
    )
    if normalized and state:
        status["sandbox"]["createdAt"] = str(state.get("createdAt") or status["sandbox"].get("createdAt") or "")
    return status


def is_developer_mode_enabled(*, config_path: Path | None = None) -> bool:
    return bool(get_developer_mode_status(config_path=config_path).get("enabled"))


def active_sandbox_id(*, project_root: Path | None = None, config_path: Path | None = None) -> str:
    status = get_developer_mode_status(config_path=config_path, project_root=project_root, ensure_sandbox=True)
    if not status.get("enabled"):
        return ""
    sandbox = status.get("sandbox") if isinstance(status.get("sandbox"), dict) else {}
    return str(sandbox.get("sandboxId") or "").strip()


def sandbox_root(project_root: Path | None = None, *, ensure: bool = True) -> Path | None:
    root = _project_root(project_root)
    state = _ensure_active_state(root) if ensure else _read_active_state(root)
    sandbox_id = str(state.get("sandboxId") or "").strip()
    return _sandbox_root(root, sandbox_id) if sandbox_id else None


def sandbox_workspace_path(project_root: Path, *parts: str) -> Path | None:
    if not is_developer_mode_enabled():
        return None
    root = sandbox_root(project_root, ensure=True)
    if root is None:
        return None
    return root.joinpath("workspace", *parts)


def formal_workspace_path(project_root: Path, *parts: str) -> Path:
    _ = _project_root(project_root)
    return resolve_workspace_home().joinpath(*parts)


def sandboxed_workspace_path(project_root: Path, *parts: str) -> Path:
    return sandbox_workspace_path(project_root, *parts) or formal_workspace_path(project_root, *parts)


def seeded_sandbox_workspace_path(project_root: Path, *parts: str) -> Path:
    sandbox_path = sandbox_workspace_path(project_root, *parts)
    if sandbox_path is None:
        return formal_workspace_path(project_root, *parts)
    formal_path = formal_workspace_path(project_root, *parts)
    if not sandbox_path.exists() and formal_path.exists():
        sandbox_path.parent.mkdir(parents=True, exist_ok=True)
        if formal_path.is_dir():
            shutil.copytree(formal_path, sandbox_path)
        else:
            shutil.copy2(formal_path, sandbox_path)
    return sandbox_path


def sandboxed_project_root(project_root: Path) -> Path:
    if not is_developer_mode_enabled():
        return _project_root(project_root)
    return sandbox_root(project_root, ensure=True) or _project_root(project_root)


def clear_active_sandbox(*, project_root: Path | None = None) -> dict[str, Any]:
    root = _project_root(project_root)
    state = _read_active_state(root)
    sandbox_id = str(state.get("sandboxId") or "").strip()
    deleted_root = ""
    if sandbox_id:
        target = _sandbox_root(root, sandbox_id)
        deleted_root = str(target)
        if _is_relative_to(target, _sandboxes_root(root)) and target.exists():
            shutil.rmtree(target, ignore_errors=True)
    try:
        _active_state_path(root).unlink()
    except OSError:
        pass
    return {
        "ok": True,
        "sandboxId": sandbox_id,
        "deletedRoot": deleted_root,
    }


def reset_active_sandbox(*, project_root: Path | None = None) -> dict[str, Any]:
    clear_active_sandbox(project_root=project_root)
    root = _project_root(project_root)
    state = _ensure_active_state(root)
    return {
        "ok": True,
        "sandboxId": str(state.get("sandboxId") or ""),
        "root": str(_sandbox_root(root, str(state.get("sandboxId") or ""))),
    }


def sandbox_prompt_cache_partition(partition: str, *, surface: str, project_root: Path | None = None) -> str:
    normalized = str(partition or "").strip()
    sandbox_id = active_sandbox_id(project_root=project_root)
    if not sandbox_id:
        return normalized
    surface_token = _safe_token(surface, default="runtime")
    if normalized.startswith("dev-") and f"-{sandbox_id}-" in normalized:
        return normalized
    raw = normalized or "default"
    return f"dev-{surface_token}-{sandbox_id}-{raw}"


def enrich_debug_fields(fields: dict[str, Any] | None, *, project_root: Path | None = None) -> dict[str, Any]:
    payload = dict(fields or {})
    if not is_developer_mode_enabled():
        return payload
    sandbox_id = active_sandbox_id(project_root=project_root)
    if not sandbox_id:
        return payload
    payload.setdefault("developerMode", True)
    payload.setdefault("developerSandboxId", sandbox_id)
    payload.setdefault("recordKind", DEBUG_RECORD_KIND)
    payload.setdefault("retention", DEBUG_RETENTION)
    payload.setdefault("statePersistence", "sandbox_only")
    return payload


def _project_root(project_root: Path | None) -> Path:
    root = Path(project_root or PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _runtime_root(project_root: Path) -> Path:
    return project_root / RUNTIME_DIR


def _sandboxes_root(project_root: Path) -> Path:
    return _runtime_root(project_root) / SANDBOXES_DIR


def _active_state_path(project_root: Path) -> Path:
    return _runtime_root(project_root) / ACTIVE_STATE_NAME


def _sandbox_root(project_root: Path, sandbox_id: str) -> Path:
    return _sandboxes_root(project_root) / _safe_token(sandbox_id, default="sandbox")


def _read_active_state(project_root: Path) -> dict[str, Any]:
    path = _active_state_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_active_state(project_root: Path, payload: dict[str, Any]) -> None:
    path = _active_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_active_state(project_root: Path) -> dict[str, Any]:
    state = _read_active_state(project_root)
    sandbox_id = str(state.get("sandboxId") or "").strip()
    if not sandbox_id:
        sandbox_id = f"dev-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        state = {
            "schemaVersion": SANDBOX_SCHEMA_VERSION,
            "sandboxId": sandbox_id,
            "createdAt": _utcnow(),
            "updatedAt": _utcnow(),
        }
        _write_active_state(project_root, state)
    root = _sandbox_root(project_root, sandbox_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    return state


def _load_public_config(config_path: Path | None) -> dict[str, Any]:
    try:
        payload = load_public_config(config_path or CONFIG_PATH)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_public_config_with_hash(config_path: Path | None) -> tuple[dict[str, Any], str, Path]:
    resolved_path = _resolved_config_path(config_path)
    signature = _file_signature(resolved_path)
    with _CONFIG_CACHE_LOCK:
        cached = _CONFIG_CACHE.get(signature)
    if cached is not None:
        public_config, config_hash = cached
        return public_config, config_hash, resolved_path

    public_config = _load_public_config(resolved_path)
    config_hash = public_config_hash(public_config)
    refreshed_signature = _file_signature(resolved_path)
    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE[refreshed_signature] = (public_config, config_hash)
    return public_config, config_hash, resolved_path


def _clear_developer_mode_config_cache() -> None:
    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE.clear()


def _resolved_config_path(config_path: Path | None) -> Path:
    return Path(config_path or CONFIG_PATH).expanduser().resolve()


def _file_signature(path: Path) -> tuple[str, int | None, int | None]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _raw_setting(public_config: dict[str, Any]) -> dict[str, Any]:
    launcher = public_config.get(CONFIG_SECTION) if isinstance(public_config, dict) else {}
    if not isinstance(launcher, dict):
        return {}
    setting = launcher.get(CONFIG_KEY)
    return setting if isinstance(setting, dict) else {}


def _ensure_section(payload: dict[str, Any], section: str) -> dict[str, Any]:
    value = payload.get(section)
    if isinstance(value, dict):
        return value
    value = {}
    payload[section] = value
    return value


def _parse_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{label} must be a boolean")


def _safe_token(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in text).strip(".-_")
    return cleaned or default


def _policy_token(value: Any, *, default: str) -> str:
    return _safe_token(value, default=default).lower()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
