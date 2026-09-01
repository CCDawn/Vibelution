"""Standalone Launcher service for the managed Vibelution project bundle."""

from __future__ import annotations

import json
from core.logging import debug as _debug_logger
import os
import re
import stat as stat_module
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from config.paths import resolve_config_backup_dir
from config.public_config import (
    CONFIG_PATH,
    HEADER_LINES,
    _canonicalize_public_config,
    _config_edit_lock,
    _legacy_v1_public_payload,
    _replace_config_file_atomically,
    load_public_config,
    public_config_hash,
    strip_runtime_model_capability_fields,
)
from config.toml_writer import dumps_public_config
from core.runtime_manager import command_queue, ensure_daemon_running, is_daemon_running
from core.runtime_manager.constants import (
    EVENTS_PATH,
    INBOX_DIR,
    LAUNCHER_STATE_PATH,
    PROCESSING_DIR,
    PROJECT_ROOT,
    RESULTS_DIR,
    STATE_PATH,
)
from core.runtime_manager.evolution_store import load_active_run_snapshot
from core.runtime_manager.process_identity import is_runtime_manager_process
from core.runtime_manager.scene_logging import (
    append_runtime_manager_file_event,
    record_runtime_manager_scene_event,
    runtime_manager_event_phase,
)
from core.web.services.runtime_scene.record import (
    _append_scene_log_line,
    _resolve_current_runtime_scene_dir,
)
from core.runtime_manager.state_store import load_pid, load_state
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_store import WorkRunStore
from core.runtime_manager.workbench_controller import _is_process_alive, observe_workbench
from core.runtime_manager.window_provider_state import window_provider_projection
from . import desktop_session_store, lifecycle_action_dispatcher, lifecycle_intent_store
from . import developer_mode as launcher_developer_mode
from .branch_instance_cleanup import BranchInstanceCleanupError as BranchInstanceCleanupError  # noqa: F401
from .branch_instance_lifecycle import BranchInstanceLifecycleError as BranchInstanceLifecycleError  # noqa: F401
from . import maintenance_reset as launcher_maintenance_reset


LauncherOperation = Literal["start", "stop", "restart", "force-stop", "shutdown"]
LauncherSupervisorOperation = Literal["supervisor_reattach"]
RuntimeProfile = Literal["safe_local", "safe_remote", "debug", "ci"]
UiLanguage = Literal["zh", "en"]
WorkbenchWindowMode = Literal["fullscreen", "windowed"]
WorkbenchWindowSize = str
WorkbenchWindowPosition = str

_ACTIVE_WORK_KINDS = (
    "chat_turn",
    "chat_room_round",
    "self_evolution_run",
    "supervised_evolution_run",
    "supervised_worktree_evolution_run",
)
_RUNTIME_PROFILES: tuple[RuntimeProfile, ...] = ("safe_local", "safe_remote", "debug", "ci")
_UI_LANGUAGES: tuple[UiLanguage, ...] = ("zh", "en")
_WORKBENCH_WINDOW_MODES: tuple[WorkbenchWindowMode, ...] = ("fullscreen", "windowed")
_WORKBENCH_WINDOW_SIZE_DEFAULT = "auto"
_WORKBENCH_WINDOW_SIZE_RE = re.compile(r"^([1-9][0-9]{2,4})x([1-9][0-9]{2,4})$", re.IGNORECASE)
_WORKBENCH_WINDOW_SIZE_PRESETS: tuple[str, ...] = ("auto", "1280x800", "1600x900", "1920x1080")
_WORKBENCH_WINDOW_POSITION_DEFAULT = "auto"
_WORKBENCH_WINDOW_POSITION_RE = re.compile(r"^(-?\d{1,5}),(-?\d{1,5})$")
_WORKBENCH_WINDOW_MODE_LABELS = {
    "fullscreen": {"zh": "全屏", "en": "Fullscreen"},
    "windowed": {"zh": "窗口化", "en": "Windowed"},
}
_WORKBENCH_WINDOW_MODE_DETAILS = {
    "fullscreen": {
        "zh": "下次启动工作台时铺满屏幕。",
        "en": "Open the workbench fullscreen on the next start.",
    },
    "windowed": {
        "zh": "下次启动工作台时保留系统窗口边框。",
        "en": "Open the workbench in a normal desktop window on the next start.",
    },
}
_RUNTIME_MANAGER_STATUS_FAST_PATH_MAX_AGE_SECONDS = 15.0
_STATUS_OPEN_RECOVERY_MIN_AGE_SECONDS = 8.0
_IN_FLIGHT_OPEN_PHASES = frozenset({"opening", "starting", "restarting", "restart"})


def _launcher_elapsed_ms(started_at: float) -> float:
    return round(max(0.0, (time.monotonic() - started_at) * 1000.0), 1)


def _save_public_config_under_edit_lock(public_config: dict[str, Any], config_path: Path) -> None:
    """Persist config while the caller holds the cross-process edit lock."""

    payload = public_config
    if _legacy_v1_public_payload(public_config):
        from config.llm_schema_upgrader import convert_legacy_llm_config

        payload = convert_legacy_llm_config(public_config, allow_missing_credentials=True)
    cleaned_public_config = strip_runtime_model_capability_fields(
        _canonicalize_public_config(payload)
    )
    backup_dir = resolve_config_backup_dir(config_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{config_path.name}.bak"
    backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    try:
        temp_path.write_text(dumps_public_config(cleaned_public_config, HEADER_LINES), encoding="utf-8")
        _replace_config_file_atomically(temp_path, config_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass



class LauncherActiveWorkBlocked(Exception):
    """Raised when a Launcher lifecycle command would interrupt active work."""

    def __init__(self, message: str, active_work_runs: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.message = message
        self.active_work_runs = active_work_runs


class LauncherSettingsConflict(ValueError):
    """Raised when Launcher startup settings are saved from a stale config snapshot."""


DeveloperModeDisabled = launcher_developer_mode.DeveloperModeDisabled
DeveloperCleanupPlanError = launcher_developer_mode.DeveloperCleanupPlanError
LauncherMaintenancePlanError = launcher_maintenance_reset.LauncherMaintenancePlanError


class LauncherCommandResponse(TypedDict, total=False):
    accepted: bool
    mode: str
    launcherMode: str
    commandId: str
    operation: LauncherOperation
    message: str
    code: str
    activeWorkRuns: list[dict[str, str]]
    closeId: str
    windowOwner: str
    instanceId: str
    port: int
    controlPort: int
    url: str
    generation: int


class LauncherRequestAudit(TypedDict, total=False):
    operation: str
    trigger: str
    endpoint: str
    method: str
    clientHost: str
    refererPath: str
    originHost: str
    userAgent: str


class LauncherSupervisorCommandResponse(TypedDict, total=False):
    accepted: bool
    mode: str
    launcherMode: str
    commandId: str
    operation: LauncherSupervisorOperation
    message: str
    blockedReason: str
    blockers: list[str]


def get_launcher_freshness() -> dict[str, Any]:
    """Return whether this Launcher process still matches local Git HEAD."""

    from core.launcher.freshness import get_launcher_freshness as _freshness

    return _freshness()


def list_launcher_branch_instances(*, include_cleanup_metadata: bool = False) -> dict[str, Any]:
    """Return Git-governed branch instances for the Launcher first screen.

    Tray refresh and the status table only need worktree identity plus runtime
    overlay. ``merge-base --is-ancestor`` cleanup annotation is opt-in because
    it is only required when the user filters unmerged rows or confirms cleanup.
    """

    from core.launcher.branch_instance_lifecycle import list_overlayed_branch_instances

    current_bundle = _current_project_bundle_for_branch_list()
    payload = list_overlayed_branch_instances(current_bundle=current_bundle)
    if not include_cleanup_metadata:
        return payload
    from core.launcher.branch_instance_cleanup import annotate_cleanup_metadata

    # Electron status refresh uses a 5s JSON-bridge timeout and Promise.all.
    # A 15s merge-base / for-each-ref here times out the whole snapshot.
    return annotate_cleanup_metadata(payload, git_timeout=2.0)


def _current_project_bundle_for_branch_list() -> dict[str, Any]:
    """Overlay the current checkout from on-disk launcher/runtime-manager state.

    The instance table must not wait on live ``observe_workbench`` probes used by
    ``get_launcher_status``. Settings, guardian, and control-plane evidence stay
    on the status poll path. Leftover disk flags are reconciled against a live
    daemon or a listening backend port before they reach the table.
    """

    runtime_state = _runtime_manager_state()
    launcher_state = _load_launcher_state()
    workbench = _workbench_payload(runtime_state=runtime_state, observed_workbench={})
    runtime_manager = _runtime_manager_payload(runtime_state)
    lifecycle_proof = _lifecycle_proof(
        runtime_manager=runtime_manager,
        workbench=workbench,
        active_work_runs=[],
        runtime_state=runtime_state,
    )
    bundle = _project_bundle_from_workbench(
        workbench,
        lifecycle_proof=lifecycle_proof,
        launcher_state=launcher_state,
    )
    if not isinstance(bundle, dict):
        return {}
    return _reconcile_stale_disk_bundle_for_branch_list(bundle, runtime_state)


def _live_backend_port_listening(port: int) -> bool:
    if port <= 0:
        return False
    try:
        from core.runtime_manager.workbench_controller import _port_is_listening_socket

        return bool(_port_is_listening_socket(int(port)))
    except Exception:
        return False


def _positive_backend_port(value: object) -> int:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return port if port > 0 else 0


def _branch_list_backend_ports_to_probe(
    bundle: dict[str, Any],
    runtime_state: dict[str, Any],
) -> list[int]:
    """Disk ``backend.port`` can lag behind ports.json (``:8000`` vs live ``:8002``)."""

    ports: list[int] = []

    def add(value: object) -> None:
        port = _positive_backend_port(value)
        if port and port not in ports:
            ports.append(port)

    backend = bundle.get("backend") if isinstance(bundle.get("backend"), dict) else {}
    add(backend.get("port"))
    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    add(workbench.get("backendPort"))
    launcher_state = _load_launcher_state()
    add(launcher_state.get("backendPort") or launcher_state.get("port"))
    launcher_workbench = (
        launcher_state.get("workbench") if isinstance(launcher_state.get("workbench"), dict) else {}
    )
    add(launcher_workbench.get("backendPort"))
    for raw_url in (
        launcher_workbench.get("url"),
        launcher_state.get("url"),
        bundle.get("url"),
    ):
        url = str(raw_url or "").strip()
        if not url:
            continue
        try:
            add(urlparse(url).port)
        except ValueError:
            continue
    try:
        from config.workbench import configured_backend_port

        add(configured_backend_port())
    except Exception:
        pass
    return ports


def _first_listening_backend_port(ports: list[int]) -> int:
    for port in ports:
        if _live_backend_port_listening(port):
            return port
    return 0


def _adopt_live_backend_port(bundle: dict[str, Any], live_port: int) -> dict[str, Any]:
    bundle = dict(bundle)
    backend = dict(bundle.get("backend") if isinstance(bundle.get("backend"), dict) else {})
    backend["port"] = int(live_port)
    backend["portListening"] = True
    backend["alive"] = True
    backend["healthy"] = True
    backend["portConflict"] = False
    bundle["backend"] = backend
    return bundle


def _reconcile_stale_disk_bundle_for_branch_list(
    bundle: dict[str, Any],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    """Drop leftover on-disk open/partial flags when the daemon and port are dead.

    The instance table skips live ``observe_workbench``. Disk RM state can keep
    ``observedState=open`` / ``phase=opening`` / healthy backend flags after the
    processes are gone. A live daemon, or any listening backend port from disk,
    ports.json, or startup config, counts. Stale ``:8000`` must not hide ``:8002``.
    """

    live_port = _first_listening_backend_port(
        _branch_list_backend_ports_to_probe(bundle, runtime_state)
    )
    if live_port > 0:
        return _adopt_live_backend_port(bundle, live_port)
    if bool(runtime_state.get("daemonRunning")):
        return bundle

    bundle = dict(bundle)
    backend = dict(bundle.get("backend") if isinstance(bundle.get("backend"), dict) else {})
    backend["alive"] = False
    backend["healthy"] = False
    backend["portListening"] = False
    bundle["backend"] = backend
    phase = str(bundle.get("phase") or "").strip().lower()
    if phase in {"opening", "starting"}:
        bundle["phase"] = "steady"
    browser = bundle.get("browser") if isinstance(bundle.get("browser"), dict) else {}
    window_open = bool(browser.get("alive"))
    if not window_open:
        bundle["observedState"] = "closed"
        if str(bundle.get("desiredState") or "").strip().lower() == "open":
            bundle["desiredState"] = "closed"
        bundle["failureMessage"] = ""
    return bundle


def cleanup_launcher_branch_instances(
    instance_ids: list[str],
    *,
    confirm: bool,
) -> dict[str, Any]:
    """Stop and delete selected local branch instances after explicit confirm."""

    from core.launcher.branch_instance_cleanup import cleanup_branch_instances

    return cleanup_branch_instances(instance_ids, confirm=confirm)


def migrate_launcher_branch_workspaces() -> dict[str, Any]:
    """Move legacy sibling worktrees into the in-repo branch pool."""

    from core.infrastructure.branch_workspace import migrate_legacy_branch_workspaces

    return migrate_legacy_branch_workspaces(PROJECT_ROOT)


def get_launcher_status() -> dict[str, Any]:
    """Return standalone Launcher status without importing the Web service layer."""

    runtime_state = _runtime_manager_state()
    if _recover_stale_open_command_when_manager_offline(runtime_state):
        runtime_state = _runtime_manager_state()
    elif _recover_stale_close_commands_when_manager_offline(runtime_state):
        runtime_state = _runtime_manager_state()
    launcher_state = _load_launcher_state()
    observed_workbench = _status_observed_workbench(runtime_state)
    workbench = _workbench_payload(runtime_state=runtime_state, observed_workbench=observed_workbench)
    active_work_runs = launcher_active_work_runs()
    runtime_manager = _runtime_manager_payload(runtime_state)
    lifecycle_proof = _lifecycle_proof(
        runtime_manager=runtime_manager,
        workbench=workbench,
        active_work_runs=active_work_runs,
        runtime_state=runtime_state,
    )
    last_error = runtime_state.get("lastError") if isinstance(runtime_state.get("lastError"), dict) else {}
    last_error_message = str(last_error.get("message") or "").strip()
    last_error_scope = str(last_error.get("scope") or "").strip()
    last_error_at = str(last_error.get("at") or "").strip()
    workbench_confirms_open = bool(
        workbench.get("observedState") == "open"
        and workbench.get("backendHealthy")
        and workbench.get("backendPortListening")
        and not workbench.get("backendPortConflict")
        and not workbench.get("frontendOrphaned")
    )
    failure_message = str(workbench.get("failureMessage") or "").strip()
    if not failure_message and not workbench_confirms_open:
        failure_message = last_error_message
    # Flat string fields for native tray JSON extractors (regex string matcher only).
    return {
        "launcher": {
            "mode": "standalone_control_plane",
            "phase": "phase_2a",
            "stableControlPlane": True,
            "controlPlane": {
                "independent": True,
                "adapter": "runtime_manager",
                "nextPhase": "standalone_launcher_frontend",
                "url": str(launcher_state.get("launcherControlUrl") or "").strip(),
                "port": int(launcher_state.get("launcherControlPort") or 0),
                "pid": os.getpid(),
            },
            "message": "Launcher 已作为独立控制面运行；项目工作台前后端现在是被管理对象。",
        },
        "projectBundle": _project_bundle_from_workbench(workbench, lifecycle_proof=lifecycle_proof, launcher_state=launcher_state),
        "controlPlaneEvidence": _control_plane_evidence(),
        "guardianAdapter": _guardian_adapter_from_workbench(runtime_manager=runtime_manager, workbench=workbench),
        "runtimeManager": runtime_manager,
        "lifecycleProof": lifecycle_proof,
        "settings": {
            "startup": get_launcher_startup_settings(),
            "workbenchWindow": get_workbench_window_mode_setting(),
            "developerMode": get_launcher_developer_mode_setting(),
        },
        # Tray / lightweight clients: prefer these top-level string fields.
        "overallState": str(lifecycle_proof.get("overallState") or ""),
        "observedState": str(workbench.get("observedState") or "closed"),
        "phase": str(workbench.get("phase") or "steady"),
        "lifecycleConsistency": str(workbench.get("lifecycleConsistency") or "consistent"),
        "failureMessage": failure_message,
        "lastErrorMessage": last_error_message,
        "lastErrorScope": last_error_scope,
        "lastErrorAt": last_error_at,
        "stateVersion": str(int(runtime_manager.get("stateVersion") or 0)),
    }


def get_launcher_developer_mode_setting() -> dict[str, Any]:
    """Return Launcher-owned developer mode state."""

    return launcher_developer_mode.get_developer_mode_setting(config_path=CONFIG_PATH)


def update_launcher_developer_mode(enabled: object, *, base_hash: str = "") -> dict[str, Any]:
    """Persist Launcher-owned developer mode state."""

    return launcher_developer_mode.update_developer_mode_setting(
        enabled,
        base_hash=base_hash,
        config_path=CONFIG_PATH,
    )


def get_launcher_developer_noise_overview() -> dict[str, Any]:
    """Return a read-only developer noise overview."""

    return launcher_developer_mode.get_noise_overview(config_path=CONFIG_PATH, project_root=PROJECT_ROOT)


def reset_launcher_developer_sandbox() -> dict[str, Any]:
    """Reset the active global developer sandbox."""

    return launcher_developer_mode.reset_developer_sandbox(config_path=CONFIG_PATH, project_root=PROJECT_ROOT)


def preview_launcher_developer_cleanup(action: str) -> dict[str, Any]:
    """Preview a guarded developer cleanup plan."""

    return launcher_developer_mode.preview_cleanup_plan(
        action,
        config_path=CONFIG_PATH,
        project_root=PROJECT_ROOT,
    )


def apply_launcher_developer_cleanup(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a previously previewed developer cleanup plan."""

    if not isinstance(payload, dict):
        raise ValueError("cleanup apply payload must be an object")
    return launcher_developer_mode.apply_cleanup_plan(
        str(payload.get("action") or ""),
        plan_id=str(payload.get("planId") or ""),
        plan_hash=str(payload.get("planHash") or ""),
        confirm=bool(payload.get("confirm", False)),
        config_path=CONFIG_PATH,
        project_root=PROJECT_ROOT,
    )


def get_launcher_maintenance_summary() -> dict[str, Any]:
    """Return Launcher-owned reset and initialization maintenance inventory."""

    return launcher_maintenance_reset.get_launcher_maintenance_summary()


def preview_launcher_maintenance_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview a Launcher-owned project reset/initialization plan."""

    if not isinstance(payload, dict):
        raise ValueError("maintenance preview payload must be an object")
    return launcher_maintenance_reset.preview_launcher_maintenance_plan(payload)


def apply_launcher_maintenance_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Launcher-owned project reset/initialization plan."""

    if not isinstance(payload, dict):
        raise ValueError("maintenance apply payload must be an object")
    return launcher_maintenance_reset.apply_launcher_maintenance_plan(
        payload,
        active_work_runs=launcher_active_work_runs(),
    )


def get_launcher_startup_settings() -> dict[str, Any]:
    """Return Launcher-owned startup settings that affect the next workbench start."""

    public_config = _load_launcher_public_config()
    runtime = _read_config_section(public_config, "runtime")
    launcher = _read_config_section(public_config, "launcher")
    workbench = _read_config_section(public_config, "workbench")
    ui = _read_config_section(public_config, "ui")
    configured_window_mode = _normalize_workbench_window_mode(workbench.get("window_mode"), default="fullscreen")
    window_env_override = _read_workbench_window_mode_env_override() or ""
    configured_window_size = _normalize_workbench_window_size(workbench.get("window_size"))
    window_size_env_override = _read_workbench_window_size_env_override() or ""
    configured_window_position = _normalize_workbench_window_position(workbench.get("window_position"))
    window_position_env_override = _read_workbench_window_position_env_override() or ""
    configured_backend_port = _normalize_port(workbench.get("backend_port"), default=8000)
    configured_frontend_port = _normalize_port(workbench.get("frontend_port"), default=5173)
    backend_port_override = _read_port_env_override(("VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT"))
    frontend_port_override = _read_port_env_override(("VIBELUTION_FRONTEND_PORT", "AGENT_WORKBENCH_FRONTEND_PORT"))
    configured_control_port = _normalize_port(launcher.get("control_port"), default=8765)
    control_port_override = _read_port_env_override(("VIBELUTION_LAUNCHER_PORT", "AGENT_LAUNCHER_CONTROL_PORT"))
    effective_backend_port = backend_port_override or configured_backend_port
    effective_control_port = _resolve_launcher_control_port(
        control_port_override or configured_control_port,
        workbench_port=effective_backend_port,
    )
    return {
        "launcher": {
            "controlPort": configured_control_port,
            "effectiveControlPort": effective_control_port,
            "controlPortEnvOverride": control_port_override or 0,
        },
        "runtime": {
            "profile": _normalize_runtime_profile(runtime.get("profile")),
            "preflightDoctor": bool(runtime.get("preflight_doctor", True)),
            "requireVenv": bool(runtime.get("require_venv", True)),
            "profileOptions": list(_RUNTIME_PROFILES),
        },
        "workbench": {
            "backendPort": configured_backend_port,
            "frontendPort": configured_frontend_port,
            "effectiveBackendPort": effective_backend_port,
            "effectiveFrontendPort": frontend_port_override or configured_frontend_port,
            "backendPortEnvOverride": backend_port_override or 0,
            "frontendPortEnvOverride": frontend_port_override or 0,
            "windowMode": configured_window_mode,
            "effectiveWindowMode": window_env_override or configured_window_mode,
            "windowModeEnvOverride": window_env_override,
            "windowSize": configured_window_size,
            "effectiveWindowSize": window_size_env_override or configured_window_size,
            "windowSizeEnvOverride": window_size_env_override,
            "windowSizeOptions": _workbench_window_size_options(
                configured_window_size,
                window_size_env_override or configured_window_size,
            ),
            "windowPosition": configured_window_position,
            "effectiveWindowPosition": window_position_env_override or configured_window_position,
            "windowPositionEnvOverride": window_position_env_override,
            "windowModeOptions": [
                {
                    "mode": mode,
                    "label": _WORKBENCH_WINDOW_MODE_LABELS[mode],
                    "detail": _WORKBENCH_WINDOW_MODE_DETAILS[mode],
                }
                for mode in _WORKBENCH_WINDOW_MODES
            ],
        },
        "interface": {
            "language": _normalize_ui_language(ui.get("language")),
            "languageOptions": list(_UI_LANGUAGES),
        },
        "configPath": str(CONFIG_PATH),
        "configHash": public_config_hash(public_config),
        "restartRequired": True,
    }


def get_workbench_window_mode_setting() -> dict[str, Any]:
    """Return the configured and effective Workbench window mode."""

    public_config = _load_launcher_public_config()
    workbench = _read_config_section(public_config, "workbench")
    configured = _normalize_workbench_window_mode(workbench.get("window_mode"), default="fullscreen")
    env_override = _read_workbench_window_mode_env_override() or ""
    effective = env_override or configured
    return {
        "mode": configured,
        "effectiveMode": effective,
        "envOverride": env_override,
        "configPath": str(CONFIG_PATH),
        "configHash": public_config_hash(public_config),
        "restartRequired": True,
        "options": [
            {
                "mode": mode,
                "label": _WORKBENCH_WINDOW_MODE_LABELS[mode],
                "detail": _WORKBENCH_WINDOW_MODE_DETAILS[mode],
            }
            for mode in _WORKBENCH_WINDOW_MODES
        ],
    }


def update_workbench_window_mode(mode: str, *, base_hash: str = "") -> dict[str, Any]:
    """Persist the Workbench window mode used by subsequent Launcher starts."""

    normalized = _parse_workbench_window_mode(mode)
    expected_hash = str(base_hash or "").strip()
    with _config_edit_lock(CONFIG_PATH):
        public_config = load_public_config(CONFIG_PATH)
        current_hash = public_config_hash(public_config)
        if not expected_hash:
            _record_launcher_event(
                "launcher.settings.workbench_window_mode.conflict",
                phase="settings",
                message="Launcher Workbench window mode update missing config base hash.",
                outcome="conflict",
                level="warning",
                fields={
                    "requestedMode": normalized,
                    "baseHash": "",
                    "currentHash": current_hash,
                    "configPath": str(CONFIG_PATH),
                },
            )
            raise LauncherSettingsConflict("窗口模式保存请求缺少配置版本，请刷新 Launcher 后重试。")
        if expected_hash != current_hash:
            _record_launcher_event(
                "launcher.settings.workbench_window_mode.conflict",
                phase="settings",
                message="Launcher Workbench window mode update rejected because the config snapshot is stale.",
                outcome="conflict",
                level="warning",
                fields={
                    "requestedMode": normalized,
                    "baseHash": expected_hash,
                    "currentHash": current_hash,
                    "configPath": str(CONFIG_PATH),
                },
            )
            raise LauncherSettingsConflict("窗口模式保存前配置已被其他页面或进程改动，请刷新 Launcher 后重试。")
        workbench = public_config.setdefault("workbench", {})
        if not isinstance(workbench, dict):
            workbench = {}
            public_config["workbench"] = workbench
        previous = _normalize_workbench_window_mode(workbench.get("window_mode"), default="fullscreen")
        workbench["window_mode"] = normalized
        _save_public_config_under_edit_lock(public_config, CONFIG_PATH)
        setting = get_workbench_window_mode_setting()
        _record_launcher_event(
            "launcher.settings.workbench_window_mode.updated",
            phase="settings",
            message="Launcher Workbench window mode setting updated.",
            outcome="succeeded",
            fields={
                "previousMode": previous,
                "mode": normalized,
                "effectiveMode": setting["effectiveMode"],
                "envOverride": setting["envOverride"],
                "configPath": str(CONFIG_PATH),
                "previousHash": current_hash,
                "configHash": setting.get("configHash"),
            },
        )
        return {
            "ok": True,
            "mode": normalized,
            "setting": setting,
            "message": "工作台启动窗口模式已保存；下次启动或重启工作台生效。",
        }


def update_launcher_startup_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist Launcher startup settings used by subsequent workbench starts."""

    if not isinstance(payload, dict):
        raise ValueError("startup settings payload must be an object")
    with _config_edit_lock(CONFIG_PATH):
        return _update_launcher_startup_settings_locked(payload)


def _update_launcher_startup_settings_locked(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply startup settings while the caller owns the config edit lock."""

    if not isinstance(payload, dict):
        raise ValueError("startup settings payload must be an object")
    public_config = load_public_config(CONFIG_PATH)
    current_hash = public_config_hash(public_config)
    base_hash = str(payload.get("baseHash") or "").strip()
    if not base_hash:
        _record_launcher_event(
            "launcher.settings.startup.conflict",
            phase="settings",
            message="Launcher startup settings update missing config base hash.",
            outcome="conflict",
            level="warning",
            fields={
                "baseHash": "",
                "currentHash": current_hash,
                "configPath": str(CONFIG_PATH),
            },
        )
        raise LauncherSettingsConflict("启动设置保存请求缺少配置版本，请刷新 Launcher 后重试。")
    if base_hash != current_hash:
        _record_launcher_event(
            "launcher.settings.startup.conflict",
            phase="settings",
            message="Launcher startup settings update rejected because the config snapshot is stale.",
            outcome="conflict",
            level="warning",
            fields={
                "baseHash": base_hash,
                "currentHash": current_hash,
                "configPath": str(CONFIG_PATH),
            },
        )
        raise LauncherSettingsConflict("启动设置保存前配置已被其他页面或进程改动，请刷新 Launcher 后重试。")

    launcher = _ensure_config_section(public_config, "launcher")
    runtime = _ensure_config_section(public_config, "runtime")
    workbench = _ensure_config_section(public_config, "workbench")
    ui = _ensure_config_section(public_config, "ui")

    launcher_payload = payload.get("launcher", {})
    runtime_payload = payload.get("runtime", {})
    workbench_payload = payload.get("workbench", {})
    interface_payload = payload.get("interface", {})
    if (
        not isinstance(launcher_payload, dict)
        or not isinstance(runtime_payload, dict)
        or not isinstance(workbench_payload, dict)
        or not isinstance(interface_payload, dict)
    ):
        raise ValueError("startup settings groups must be objects")

    previous = get_launcher_startup_settings()
    if "controlPort" in launcher_payload:
        launcher["control_port"] = _parse_port(launcher_payload.get("controlPort"), label="launcher.controlPort")
    if "profile" in runtime_payload:
        runtime["profile"] = _parse_runtime_profile(runtime_payload.get("profile"))
    if "preflightDoctor" in runtime_payload:
        runtime["preflight_doctor"] = _parse_bool(runtime_payload.get("preflightDoctor"), label="runtime.preflightDoctor")
    if "requireVenv" in runtime_payload:
        runtime["require_venv"] = _parse_bool(runtime_payload.get("requireVenv"), label="runtime.requireVenv")
    if "backendPort" in workbench_payload:
        workbench["backend_port"] = _parse_port(workbench_payload.get("backendPort"), label="workbench.backendPort")
    if "frontendPort" in workbench_payload:
        workbench["frontend_port"] = _parse_port(workbench_payload.get("frontendPort"), label="workbench.frontendPort")
    if "windowMode" in workbench_payload:
        workbench["window_mode"] = _parse_workbench_window_mode(workbench_payload.get("windowMode"))
    if "windowSize" in workbench_payload:
        workbench["window_size"] = _parse_workbench_window_size(workbench_payload.get("windowSize"))
    if "windowPosition" in workbench_payload:
        workbench["window_position"] = _parse_workbench_window_position(workbench_payload.get("windowPosition"))
    if "language" in interface_payload:
        ui["language"] = _parse_ui_language(interface_payload.get("language"))

    _save_public_config_under_edit_lock(public_config, CONFIG_PATH)
    setting = get_launcher_startup_settings()
    _record_launcher_event(
        "launcher.settings.startup.updated",
        phase="settings",
        message="Launcher startup settings updated.",
        outcome="succeeded",
        fields={
            "previous": _startup_settings_event_fields(previous),
            "current": _startup_settings_event_fields(setting),
            "configPath": str(CONFIG_PATH),
            "previousHash": current_hash,
            "configHash": setting.get("configHash"),
        },
    )
    return {
        "ok": True,
        "setting": setting,
        "message": "启动设置已保存；下次启动或重启工作台生效。",
    }


def _normalize_workbench_window_mode(value: object, *, default: WorkbenchWindowMode | str = "fullscreen") -> WorkbenchWindowMode:
    normalized = str(value or "").strip().lower()
    if normalized in _WORKBENCH_WINDOW_MODES:
        return normalized  # type: ignore[return-value]
    fallback = str(default or "fullscreen").strip().lower()
    return fallback if fallback in _WORKBENCH_WINDOW_MODES else "fullscreen"  # type: ignore[return-value]


def _parse_workbench_window_mode(value: object) -> WorkbenchWindowMode:
    normalized = str(value or "").strip().lower()
    if normalized in _WORKBENCH_WINDOW_MODES:
        return normalized  # type: ignore[return-value]
    allowed = ", ".join(_WORKBENCH_WINDOW_MODES)
    raise ValueError(f"Unsupported Workbench window mode '{value}'. Allowed values: {allowed}.")


def _normalize_workbench_window_size(value: object, *, default: str = _WORKBENCH_WINDOW_SIZE_DEFAULT) -> WorkbenchWindowSize:
    raw = str(value or "").strip().lower()
    if raw == "auto":
        return "auto"
    match = _WORKBENCH_WINDOW_SIZE_RE.match(raw)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        if _workbench_window_size_in_range(width, height):
            return f"{width}x{height}"
    fallback = str(default or _WORKBENCH_WINDOW_SIZE_DEFAULT).strip().lower()
    if fallback == "auto":
        return "auto"
    fallback_match = _WORKBENCH_WINDOW_SIZE_RE.match(fallback)
    if fallback_match:
        width = int(fallback_match.group(1))
        height = int(fallback_match.group(2))
        if _workbench_window_size_in_range(width, height):
            return f"{width}x{height}"
    return _WORKBENCH_WINDOW_SIZE_DEFAULT


def _parse_workbench_window_size(value: object) -> WorkbenchWindowSize:
    raw = str(value or "").strip().lower()
    if raw == "auto":
        return "auto"
    match = _WORKBENCH_WINDOW_SIZE_RE.match(raw)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        if _workbench_window_size_in_range(width, height):
            return f"{width}x{height}"
    raise ValueError("workbench.windowSize must be 'auto' or a size like '1600x900'")


def _workbench_window_size_in_range(width: int, height: int) -> bool:
    # Floor is a usable workbench chrome size (not Edge minimum 320x240).
    return 960 <= width <= 7680 and 600 <= height <= 4320


def _normalize_workbench_window_position(
    value: object,
    *,
    default: str = _WORKBENCH_WINDOW_POSITION_DEFAULT,
) -> WorkbenchWindowPosition:
    raw = str(value or "").strip().lower()
    if raw == "auto":
        return "auto"
    match = _WORKBENCH_WINDOW_POSITION_RE.match(raw)
    if match:
        x = int(match.group(1))
        y = int(match.group(2))
        if _workbench_window_position_in_range(x, y):
            return f"{x},{y}"
    fallback = str(default or _WORKBENCH_WINDOW_POSITION_DEFAULT).strip().lower()
    if fallback == "auto":
        return "auto"
    fallback_match = _WORKBENCH_WINDOW_POSITION_RE.match(fallback)
    if fallback_match:
        x = int(fallback_match.group(1))
        y = int(fallback_match.group(2))
        if _workbench_window_position_in_range(x, y):
            return f"{x},{y}"
    return _WORKBENCH_WINDOW_POSITION_DEFAULT


def _parse_workbench_window_position(value: object) -> WorkbenchWindowPosition:
    raw = str(value or "").strip().lower()
    if raw == "auto":
        return "auto"
    match = _WORKBENCH_WINDOW_POSITION_RE.match(raw)
    if match:
        x = int(match.group(1))
        y = int(match.group(2))
        if _workbench_window_position_in_range(x, y):
            return f"{x},{y}"
    raise ValueError("workbench.windowPosition must be 'auto' or a position like '120,80'")


def _workbench_window_position_in_range(x: int, y: int) -> bool:
    # Multi-monitor virtual desktop, but reject extreme sentinels (e.g. -20000,-20000)
    # that place the next Edge --app start fully off-screen.
    return -8000 <= x <= 8000 and -8000 <= y <= 8000


def _workbench_window_size_options(*extra_sizes: object) -> list[dict[str, Any]]:
    sizes: list[str] = list(_WORKBENCH_WINDOW_SIZE_PRESETS)
    seen = set(sizes)
    for extra in extra_sizes:
        normalized = str(extra or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        if normalized != "auto" and not _WORKBENCH_WINDOW_SIZE_RE.match(normalized):
            continue
        if normalized != "auto":
            match = _WORKBENCH_WINDOW_SIZE_RE.match(normalized)
            if match is None or not _workbench_window_size_in_range(int(match.group(1)), int(match.group(2))):
                continue
        sizes.append(normalized)
        seen.add(normalized)
    return [
        {
            "size": size,
            "label": {"zh": _workbench_window_size_label(size, "zh"), "en": _workbench_window_size_label(size, "en")},
        }
        for size in sizes
    ]


def _workbench_window_size_label(size: str, lang: UiLanguage) -> str:
    if size == "auto":
        return "自动" if lang == "zh" else "Auto"
    return size


def _normalize_runtime_profile(value: object) -> RuntimeProfile:
    normalized = str(value or "safe_remote").strip().lower()
    return normalized if normalized in _RUNTIME_PROFILES else "safe_remote"  # type: ignore[return-value]


def _parse_runtime_profile(value: object) -> RuntimeProfile:
    normalized = str(value or "").strip().lower()
    if normalized in _RUNTIME_PROFILES:
        return normalized  # type: ignore[return-value]
    allowed = ", ".join(_RUNTIME_PROFILES)
    raise ValueError(f"Unsupported runtime profile '{value}'. Allowed values: {allowed}.")


def _normalize_ui_language(value: object) -> UiLanguage:
    normalized = str(value or "zh").strip().lower()
    return normalized if normalized in _UI_LANGUAGES else "zh"  # type: ignore[return-value]


def _parse_ui_language(value: object) -> UiLanguage:
    normalized = str(value or "").strip().lower()
    if normalized in _UI_LANGUAGES:
        return normalized  # type: ignore[return-value]
    allowed = ", ".join(_UI_LANGUAGES)
    raise ValueError(f"Unsupported interface language '{value}'. Allowed values: {allowed}.")


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


def _normalize_port(value: object, *, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def _parse_port(value: object, *, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer port") from exc
    if not 0 < port < 65536:
        raise ValueError(f"{label} must be between 1 and 65535")
    return port


def _resolve_launcher_control_port(port: int, *, workbench_port: int, default: int = 8765) -> int:
    resolved = port
    if resolved == workbench_port:
        candidate = default
        if candidate == workbench_port:
            candidate = workbench_port + 1
        while candidate < 65536 and candidate == workbench_port:
            candidate += 1
        resolved = candidate if 0 < candidate < 65536 else default
    return resolved


def _read_config_section(public_config: dict[str, Any], section: str) -> dict[str, Any]:
    value = public_config.get(section) if isinstance(public_config, dict) else {}
    return value if isinstance(value, dict) else {}


def _ensure_config_section(public_config: dict[str, Any], section: str) -> dict[str, Any]:
    value = public_config.get(section)
    if isinstance(value, dict):
        return value
    value = {}
    public_config[section] = value
    return value


def _load_launcher_public_config() -> dict[str, Any]:
    try:
        public_config = load_public_config(CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001 - invalid operator config must not crash launcher
        _record_launcher_config_load_failed(
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            config_type="",
        )
        return {}
    if isinstance(public_config, dict):
        return public_config
    _record_launcher_config_load_failed(
        exception_type="TypeError",
        exception_message="Public config is not a dict.",
        config_type=type(public_config).__name__,
    )
    return {}


def _record_launcher_config_load_failed(
    *,
    exception_type: str,
    exception_message: str,
    config_type: str,
) -> None:
    message = f"Launcher public config load failed: {exception_type}"
    _debug_logger.warning(message, tag="LAUNCHER")
    payload = {
        "phase": "config",
        "message": message[:240],
        "outcome": "failed",
        "level": "warning",
        "exceptionType": exception_type,
        "exceptionMessage": str(exception_message or "")[:240],
        "configType": config_type,
    }
    try:
        event_at = append_runtime_manager_file_event(
            "launcher.config.load_failed",
            payload,
            suppress_io_errors=True,
        )
        record_runtime_manager_scene_event(
            "launcher.config.load_failed",
            payload,
            phase="config",
            occurred_at=event_at,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail launcher startup
        _debug_logger.warning(f"Failed to record launcher config load failure: {exc}")


def _read_port_env_override(env_names: tuple[str, ...]) -> int | None:
    for env_name in env_names:
        raw_value = str(os.environ.get(env_name) or "").strip()
        if not raw_value:
            continue
        try:
            port = _parse_port(raw_value, label=env_name)
        except ValueError:
            continue
        return port
    return None


def _read_workbench_window_size_env_override() -> WorkbenchWindowSize | None:
    for env_name in ("VIBELUTION_WORKBENCH_WINDOW_SIZE", "AGENT_WORKBENCH_WINDOW_SIZE"):
        raw_value = str(os.environ.get(env_name) or "").strip()
        if not raw_value:
            continue
        try:
            return _parse_workbench_window_size(raw_value)
        except ValueError:
            continue
    return None


def _read_workbench_window_position_env_override() -> WorkbenchWindowPosition | None:
    for env_name in ("VIBELUTION_WORKBENCH_WINDOW_POSITION", "AGENT_WORKBENCH_WINDOW_POSITION"):
        raw_value = str(os.environ.get(env_name) or "").strip()
        if not raw_value:
            continue
        try:
            return _parse_workbench_window_position(raw_value)
        except ValueError:
            continue
    return None


def _startup_settings_event_fields(setting: dict[str, Any]) -> dict[str, Any]:
    launcher = _read_config_section(setting, "launcher")
    runtime = _read_config_section(setting, "runtime")
    workbench = _read_config_section(setting, "workbench")
    interface = _read_config_section(setting, "interface")
    return {
        "controlPort": launcher.get("controlPort"),
        "effectiveControlPort": launcher.get("effectiveControlPort"),
        "runtimeProfile": runtime.get("profile"),
        "preflightDoctor": runtime.get("preflightDoctor"),
        "requireVenv": runtime.get("requireVenv"),
        "backendPort": workbench.get("backendPort"),
        "frontendPort": workbench.get("frontendPort"),
        "windowMode": workbench.get("windowMode"),
        "windowSize": workbench.get("windowSize"),
        "effectiveWindowSize": workbench.get("effectiveWindowSize"),
        "windowPosition": workbench.get("windowPosition"),
        "effectiveWindowPosition": workbench.get("effectiveWindowPosition"),
        "language": interface.get("language"),
    }


def _read_configured_workbench_window_mode() -> WorkbenchWindowMode:
    try:
        public_config = load_public_config(CONFIG_PATH)
    except Exception:
        return "fullscreen"
    workbench = public_config.get("workbench", {}) if isinstance(public_config, dict) else {}
    raw_mode = workbench.get("window_mode") if isinstance(workbench, dict) else ""
    return _normalize_workbench_window_mode(raw_mode)


def _read_workbench_window_mode_env_override() -> WorkbenchWindowMode | None:
    for env_name in ("VIBELUTION_WORKBENCH_WINDOW_MODE", "AGENT_WORKBENCH_WINDOW_MODE"):
        raw_value = str(os.environ.get(env_name) or "").strip()
        if not raw_value:
            continue
        normalized = raw_value.lower()
        if normalized in _WORKBENCH_WINDOW_MODES:
            return normalized  # type: ignore[return-value]
    return None


def launcher_active_work_runs() -> list[dict[str, str]]:
    """Return active project work from runtime-manager-owned files only."""

    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    store = WorkRunStore(root=work_run_store.WORK_RUNS_DIR)
    for kind in ("chat_turn", "chat_room_round"):
        active_run_id = str(store.load_run_index(kind).get("activeRunId") or "").strip()
        for payload in store.list_snapshots(kind):
            _append_active_work_run(
                items,
                seen,
                kind=kind,
                payload=payload,
                force_current=str(payload.get("runId") or "").strip() == active_run_id,
            )

    for payload in store.list_snapshots("formal_run"):
        _append_active_work_run(
            items,
            seen,
            kind="formal_run",
            payload=payload,
        )

    worktree_run = store.load_active_snapshot("supervised_worktree_evolution_run")
    _append_active_work_run(
        items,
        seen,
        kind="supervised_worktree_evolution_run",
        payload=worktree_run,
        force_current=True,
    )

    for kind, storage_kind in (
        ("self_evolution_run", "self"),
        ("supervised_evolution_run", "supervised"),
    ):
        try:
            payload = load_active_run_snapshot(storage_kind)
        except Exception:
            payload = None
        _append_active_work_run(items, seen, kind=kind, payload=payload)

    return items



def ensure_runtime_manager_daemon_alive() -> dict[str, Any]:
    """Watchdog: keep the runtime-manager daemon alive on the current checkout.

    A live daemon is reused only when ``ensure_daemon_running`` confirms its
    source signature still matches disk. Stale source is recycled so the next
    start/restart cannot attach to yesterday's pythonw.
    """

    started = time.monotonic()
    was_running = is_daemon_running()
    recovered_commands: list[str] = []
    if not was_running:
        try:
            recovered_commands = command_queue.recover_processing_queue()
        except Exception as exc:  # pragma: no cover - defensive watchdog boundary
            _record_launcher_event(
                "launcher.daemon.watchdog.recovery_failed",
                phase="runtime_manager",
                message="Runtime-manager queue recovery failed before daemon restart.",
                outcome="failed",
                level="warning",
                fields={"errorType": type(exc).__name__, "errorMessage": str(exc)},
            )

    ensured = False
    try:
        ensured = bool(ensure_daemon_running())
    except Exception as exc:  # pragma: no cover - defensive watchdog boundary
        _record_launcher_event(
            "launcher.daemon.watchdog.restart_failed",
            phase="runtime_manager",
            message="Runtime-manager daemon restart attempt failed.",
            outcome="failed",
            level="error",
            fields={"errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        return {
            "action": "restart_failed",
            "daemonRunning": False,
            "ensured": False,
            "recoveredCommandCount": len(recovered_commands),
            "elapsedMs": _launcher_elapsed_ms(started),
        }

    if was_running and not ensured:
        return {"action": "already_running", "daemonRunning": True, "elapsedMs": _launcher_elapsed_ms(started)}

    # A replacement daemon recovers the processing queue before entering its
    # command loop. Recovering here after it reports alive can race a fresh
    # claim and move that active command back to the inbox.

    action = "restarted" if ensured else "restart_failed"
    _record_launcher_event(
        "launcher.daemon.watchdog.restarted" if ensured else "launcher.daemon.watchdog.restart_failed",
        phase="runtime_manager",
        message="Runtime-manager daemon recovered by watchdog."
        if ensured
        else "Runtime-manager daemon restart attempt failed.",
        outcome="succeeded" if ensured else "failed",
        level="info" if ensured else "error",
        fields={
            "action": action,
            "recoveredCommandCount": len(recovered_commands),
            "recoveredCommands": recovered_commands[:8],
            "elapsedMs": _launcher_elapsed_ms(started),
            "recycledStaleDaemon": bool(was_running and ensured),
        },
    )
    return {
        "action": action,
        "daemonRunning": False,
        "ensured": ensured,
        "recoveredCommandCount": len(recovered_commands),
        "elapsedMs": _launcher_elapsed_ms(started),
    }


def trusted_lifecycle_actor_context() -> dict[str, str]:
    return {
        "actorType": "launcher_api",
        "actorId": "launcher-control-plane",
        "sourceRunId": "",
        "sourceTaskId": "",
        "sourceWorktree": "",
    }


def submit_lifecycle_intent(payload: dict[str, Any], *, actor_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = actor_context or trusted_lifecycle_actor_context()
    result, created = lifecycle_intent_store.submit_lifecycle_intent_with_created(
        payload,
        actor_context=context,
        active_work_runs=launcher_active_work_runs(),
    )
    if (
        created
        and result.get("status") == "accepted"
        and result.get("action") in lifecycle_intent_store.RUNTIME_EFFECT_ACTIONS
    ):
        dispatch_result = lifecycle_action_dispatcher.dispatch_runtime_effect_intent({**context, **payload, **result})
        if dispatch_result.get("commandId"):
            result = lifecycle_intent_store.record_runtime_dispatch(
                str(result.get("intentId") or ""),
                command_id=str(dispatch_result.get("commandId") or ""),
            )
        result["dispatch"] = dispatch_result
    return result



def get_lifecycle_intent(intent_id: str) -> dict[str, Any]:
    intent = lifecycle_intent_store.get_lifecycle_intent(intent_id)
    if not intent.get("intentId"):
        return {}
    return reconcile_lifecycle_intent(intent)


def reconcile_lifecycle_intent(intent: dict[str, Any]) -> dict[str, Any]:
    command_id = str(intent.get("commandId") or "").strip()
    if not command_id or str(intent.get("status") or "") in lifecycle_intent_store.TERMINAL_INTENT_STATUSES:
        return intent
    result = _load_runtime_manager_command_result(command_id)
    if not result:
        return intent
    terminal_status = _lifecycle_status_for_runtime_result(result)
    if terminal_status == "":
        return intent
    result_summary = _lifecycle_result_summary(result)
    completed = lifecycle_intent_store.complete_lifecycle_intent(
        str(intent.get("intentId") or ""),
        status=terminal_status,
        result=result_summary,
    )
    _record_lifecycle_terminal_event(intent, status=terminal_status, result=result_summary)
    return completed


def _load_runtime_manager_command_result(command_id: str) -> dict[str, Any]:
    normalized_command_id = str(command_id or "").strip()
    if not normalized_command_id:
        return {}
    result_path = RESULTS_DIR / f"{normalized_command_id}.json"
    result = _load_json_file(result_path)
    result_command_id = str(result.get("commandId") or normalized_command_id).strip() or normalized_command_id
    if result_command_id != normalized_command_id or result.get("completed") is not True:
        return {}
    return result


def _lifecycle_status_for_runtime_result(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").strip().lower()
    if status == "superseded" or result.get("supersededByCommandId"):
        return "superseded"
    if result.get("ok") is False or status in {"failed", "error", "cancelled"}:
        return "failed"
    if result.get("completed") is True:
        return "succeeded"
    return ""


def _lifecycle_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "commandId": str(result.get("commandId") or "").strip(),
        "completed": bool(result.get("completed")),
        "ok": bool(result.get("ok")),
    }
    status = str(result.get("status") or "").strip()
    if status:
        summary["status"] = _truncate(status, 80)
    message = str(result.get("message") or "").strip()
    if message:
        summary["message"] = _truncate(message, 500)
    error_type = str(result.get("errorType") or "").strip()
    if error_type:
        summary["errorType"] = _truncate(error_type, 160)
    superseded_by = str(result.get("supersededByCommandId") or "").strip()
    if superseded_by:
        summary["supersededByCommandId"] = _truncate(superseded_by, 160)
    return summary


def _record_lifecycle_terminal_event(intent: dict[str, Any], *, status: str, result: dict[str, Any]) -> None:
    fields: dict[str, object] = {
        "action": str(intent.get("action") or ""),
        "commandId": str(result.get("commandId") or intent.get("commandId") or ""),
        "intentId": str(intent.get("intentId") or ""),
        "ok": bool(result.get("ok")),
        "sourceRunId": str(intent.get("sourceRunId") or ""),
        "sourceTaskId": str(intent.get("sourceTaskId") or ""),
        "status": str(status or ""),
    }
    error_type = str(result.get("errorType") or "").strip()
    if error_type:
        fields["errorType"] = _truncate(error_type, 160)
    superseded_by = str(result.get("supersededByCommandId") or "").strip()
    if superseded_by:
        fields["supersededByCommandId"] = _truncate(superseded_by, 160)
    _record_launcher_event(
        "launcher.lifecycle_intent.runtime_terminal",
        phase="lifecycle_intent",
        message="Launcher reconciled lifecycle intent terminal runtime result.",
        outcome="failed" if status == "failed" else status,
        level="error" if status == "failed" else "info",
        fields=fields,
    )


def claim_desktop_action(
    desktop_session_id: str,
    *,
    lease_seconds: int = 30,
    wait_ms: int = 0,
) -> dict[str, Any]:
    return lifecycle_intent_store.claim_desktop_action(
        desktop_session_id=desktop_session_id,
        lease_seconds=lease_seconds,
        wait_ms=wait_ms,
    )


def ack_desktop_action(action_id: str, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    finished = lifecycle_intent_store.ack_desktop_action(
        action_id,
        desktop_session_id=desktop_session_id,
        result=result,
    )
    from core.launcher.isolated_workbench_window import persist_instance_window_from_desktop_action

    persist_instance_window_from_desktop_action(finished)
    return finished


def fail_desktop_action(action_id: str, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return lifecycle_intent_store.fail_desktop_action(
        action_id,
        desktop_session_id=desktop_session_id,
        result=result,
    )


def register_desktop_session(payload: dict[str, Any]) -> dict[str, Any]:
    return desktop_session_store.register_desktop_session(payload)


def update_desktop_session_window(desktop_session_id: str, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return desktop_session_store.update_desktop_session_window(desktop_session_id, role, payload)


def heartbeat_desktop_session(desktop_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return desktop_session_store.heartbeat_desktop_session(desktop_session_id, payload)


def close_desktop_session(desktop_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return desktop_session_store.close_desktop_session(desktop_session_id, payload)


def submit_workbench_close_transaction(
    payload: dict[str, Any],
    *,
    defer_backend_dispatch: bool = False,
    request_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    desktop_session_id = str(payload.get("desktopSessionId") or "").strip()
    desktop_session = desktop_session_store.get_desktop_session(desktop_session_id)
    transaction = lifecycle_intent_store.submit_workbench_close_transaction(
        payload,
        desktop_session=desktop_session,
        active_work_runs=launcher_active_work_runs(),
    )
    _record_workbench_close_event(
        "confirmation_required" if transaction.get("phase") == "confirmation_required" else "persisted",
        transaction,
    )
    if transaction.get("phase") != "backend_closing" or transaction.get("commandId") or defer_backend_dispatch:
        return transaction
    return _dispatch_persisted_workbench_close_transaction(transaction, request_audit=request_audit)


def _dispatch_persisted_workbench_close_transaction(
    transaction: dict[str, Any],
    *,
    request_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch only a durable backend-closing transaction after its window handoff exists."""

    if transaction.get("phase") != "backend_closing" or transaction.get("commandId"):
        return transaction
    dispatch_payload = {
        "closeId": str(transaction.get("closeId") or ""),
        "desktopSessionId": str(transaction.get("desktopSessionId") or ""),
        "expectedDesktopSessionRevision": int(transaction.get("expectedDesktopSessionRevision") or 0),
        "mode": str(transaction.get("mode") or "normal"),
        "reason": str(transaction.get("reason") or ""),
        "confirmationCloseId": str(transaction.get("confirmationCloseId") or ""),
    }
    try:
        if request_audit:
            dispatch = lifecycle_action_dispatcher.dispatch_workbench_close_transaction(
                dispatch_payload,
                request_audit=request_audit,
            )
        else:
            dispatch = lifecycle_action_dispatcher.dispatch_workbench_close_transaction(dispatch_payload)
    except Exception as exc:  # noqa: BLE001 - command queue is an external persistence boundary.
        failed = lifecycle_intent_store.fail_workbench_close_transaction(
            str(transaction.get("closeId") or ""),
            code="backend_dispatch_failed",
            message=str(exc),
        )
        _record_workbench_close_event("failed", failed)
        return failed
    command_id = str(dispatch.get("commandId") or "")
    if not dispatch.get("accepted", True) or not command_id:
        failed = lifecycle_intent_store.fail_workbench_close_transaction(
            str(transaction.get("closeId") or ""),
            code="backend_dispatch_rejected",
            message="Runtime Manager did not accept the workbench close command.",
            result={"accepted": bool(dispatch.get("accepted")), "commandId": command_id},
        )
        _record_workbench_close_event("failed", failed)
        return failed
    dispatched = lifecycle_intent_store.record_workbench_close_dispatch(
        str(transaction.get("closeId") or ""),
        command_id=command_id,
    )
    _record_workbench_close_event("persisted", dispatched)
    return dispatched


def get_workbench_close_transaction(close_id: str) -> dict[str, Any]:
    transaction = lifecycle_intent_store.get_workbench_close_transaction(close_id)
    if not transaction:
        return {}
    if transaction.get("phase") != "backend_closing" or not transaction.get("commandId"):
        return transaction
    runtime_result = _load_runtime_manager_command_result(str(transaction.get("commandId") or ""))
    if not runtime_result:
        return transaction
    terminal_status = _lifecycle_status_for_runtime_result(runtime_result)
    if not terminal_status:
        return transaction
    result_summary = _lifecycle_result_summary(runtime_result)
    if terminal_status == "succeeded":
        authorized = lifecycle_intent_store.authorize_workbench_close_window(
            str(transaction.get("closeId") or ""),
            result=result_summary,
        )
        _record_workbench_close_event("backend_closed", authorized)
        return authorized
    failed = lifecycle_intent_store.fail_workbench_close_transaction(
        str(transaction.get("closeId") or ""),
        code="backend_close_failed",
        message=str(result_summary.get("message") or "Runtime Manager close command failed."),
        result=result_summary,
    )
    _record_workbench_close_event("failed", failed)
    return failed


def ack_workbench_close_transaction_window_closed(close_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    transaction = lifecycle_intent_store.get_workbench_close_transaction(close_id)
    if not transaction:
        raise ValueError("workbench close transaction was not found")
    desktop_session_id = str(payload.get("desktopSessionId") or "").strip()
    if desktop_session_id != str(transaction.get("desktopSessionId") or ""):
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "desktop_session_mismatch",
            "workbench close transaction acknowledgement came from another desktop session",
        )
    desktop_session = desktop_session_store.get_desktop_session(desktop_session_id)
    actual_revision = int(desktop_session.get("revision") or 0)
    acknowledged_revision = _positive_int(payload.get("desktopSessionRevision"))
    if acknowledged_revision != actual_revision:
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "desktop_session_revision_conflict",
            "workbench close transaction acknowledgement desktop session revision does not match",
            expectedDesktopSessionRevision=acknowledged_revision,
            actualDesktopSessionRevision=actual_revision,
        )
    if actual_revision < int(transaction.get("expectedDesktopSessionRevision") or 0):
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "desktop_session_revision_too_old",
            "workbench close transaction acknowledgement predates the requested desktop session revision",
            expectedDesktopSessionRevision=int(transaction.get("expectedDesktopSessionRevision") or 0),
            actualDesktopSessionRevision=actual_revision,
        )
    if str(desktop_session.get("status") or "") != "active":
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "desktop_session_unavailable",
            "workbench close transaction acknowledgement requires an active desktop session",
            actualDesktopSessionRevision=actual_revision,
        )
    workbench_window = desktop_session.get("windows", {}).get("workbench", {})
    if not isinstance(workbench_window, dict) or bool(workbench_window.get("open", False)):
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "workbench_window_still_open",
            "workbench window is still open; close acknowledgement is not accepted",
            actualDesktopSessionRevision=actual_revision,
        )
    phase = str(transaction.get("phase") or "")
    if phase == "succeeded":
        return transaction
    if phase != "window_close_authorized":
        raise lifecycle_intent_store.WorkbenchCloseTransactionConflict(
            "window_close_not_authorized",
            "workbench close transaction is not authorized for Electron window completion",
        )
    completed = lifecycle_intent_store.complete_workbench_close_transaction(
        str(transaction.get("closeId") or ""),
        completion_source="electron_window_closed_ack",
    )
    _record_workbench_close_event("completed", completed)
    return completed


def _record_workbench_close_event(event_suffix: str, transaction: dict[str, Any]) -> None:
    phase = str(transaction.get("phase") or "")
    _record_launcher_event(
        f"launcher.workbench_close.{event_suffix}",
        phase="workbench_close_transaction",
        message="Workbench close transaction state changed.",
        outcome="failed" if phase == "failed" else phase or "observed",
        level="error" if phase == "failed" else "info",
        fields={
            "closeId": str(transaction.get("closeId") or ""),
            "desktopSessionId": str(transaction.get("desktopSessionId") or ""),
            "expectedDesktopSessionRevision": int(transaction.get("expectedDesktopSessionRevision") or 0),
            "commandId": str(transaction.get("commandId") or ""),
            "mode": str(transaction.get("mode") or ""),
            "phase": phase,
        },
    )


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)



def launcher_request_audit(
    *,
    operation: str,
    trigger: str = "",
    endpoint: str = "",
    method: str = "",
    client_host: str = "",
    referer: str = "",
    origin: str = "",
    user_agent: str = "",
) -> LauncherRequestAudit:
    audit: LauncherRequestAudit = {
        "operation": _audit_value(operation, 48),
        "trigger": _audit_value(trigger, 80),
        "endpoint": _audit_path(endpoint, 120),
        "method": _audit_value(method, 16).upper(),
        "clientHost": _audit_value(client_host, 80),
        "refererPath": _audit_url_path(referer, 160),
        "originHost": _audit_url_host(origin, 120),
        "userAgent": _audit_value(user_agent, 160),
    }
    return {key: value for key, value in audit.items() if value}



def _runtime_manager_state() -> dict[str, Any]:
    try:
        state = load_state()
    except Exception:
        state = {}
    payload = dict(state) if isinstance(state, dict) else {}
    try:
        manager_pid = load_pid()
        manager_running = _is_process_alive(manager_pid) and is_runtime_manager_process(manager_pid)
    except Exception:
        manager_pid = 0
        manager_running = False
    if not manager_running:
        manager_pid = 0
        payload["runtimeState"] = "idle"
    payload["daemonRunning"] = manager_running
    payload["managerPid"] = int(manager_pid or 0)
    payload.setdefault("projectRoot", str(PROJECT_ROOT))
    return payload


def _recover_stale_open_command_when_manager_offline(runtime_state: dict[str, Any]) -> bool:
    """Resume an accepted open/restart command if its daemon exited mid-flight.

    Launcher status polling is the one component guaranteed to remain alive
    while the Workbench overlay waits.  Recovery is restricted to commands
    already moved into ``processing`` so a passive status read never invents a
    new lifecycle intent.
    """

    if bool(runtime_state.get("daemonRunning")):
        return False
    try:
        processing = _recent_command_files(PROCESSING_DIR, limit=20)
    except Exception:
        processing = []
    recoverable_types = {"open_workbench", "restart_workbench", "hot_restart_workbench"}
    if not any(
        str(command.get("type") or "").strip() in recoverable_types
        and _open_command_is_old_enough_to_recover(command)
        for command in processing
    ):
        return False
    result = ensure_runtime_manager_daemon_alive()
    return str(result.get("action") or "") in {"restarted", "already_running"}


def _recover_stale_close_commands_when_manager_offline(runtime_state: dict[str, Any]) -> bool:
    if bool(runtime_state.get("daemonRunning")):
        return False
    try:
        processing = _recent_command_files(PROCESSING_DIR, limit=20)
    except Exception:
        processing = []
    if not processing:
        return False
    if any(str(command.get("type") or "").strip() not in {"close_workbench", "force_close_workbench"} for command in processing):
        return False
    # The daemon watchdog restarts (e.g. after a source change) leave a short
    # offline window; recovering commands from that window re-queues closes
    # that are still being processed and fed the restart-command storms. Only
    # recover commands old enough that the daemon genuinely vanished on them.
    if not all(_open_command_is_old_enough_to_recover(command) for command in processing):
        return False
    try:
        command_queue.recover_processing_queue()
    except Exception as exc:
        append_runtime_manager_file_event(
            "launcher.status.stale_close_recovery_failed",
            {"errorType": type(exc).__name__, "message": _truncate(str(exc), 180)},
            suppress_io_errors=True,
        )
        return False
    append_runtime_manager_file_event(
        "launcher.status.stale_close_recovery_requested",
        {"processingCount": len(processing), "commandIds": [str(command.get("commandId") or "") for command in processing[:8]]},
        suppress_io_errors=True,
    )
    return True


def _observed_workbench() -> dict[str, Any]:
    try:
        observed = observe_workbench(recover_browser_window=False)
    except TypeError as exc:
        if "recover_browser_window" not in str(exc):
            return {}
        try:
            observed = observe_workbench()
        except Exception:
            return {}
    except Exception:
        return {}
    return observed if isinstance(observed, dict) else {}


def _status_observed_workbench(runtime_state: dict[str, Any]) -> dict[str, Any]:
    if (
        _runtime_manager_state_is_fresh(runtime_state)
        and _runtime_state_matches_effective_backend_port(runtime_state)
        and _runtime_state_workbench_is_live(runtime_state)
    ):
        return {}
    if _in_flight_open_should_skip_live_observe(runtime_state):
        return {}
    return _observed_workbench()


def _in_flight_open_should_skip_live_observe(runtime_state: dict[str, Any]) -> bool:
    """Do not run observe_workbench while an open/restart is already in flight.

    Status is polled through a 5s Electron JSON bridge. Live observe plus a
    watchdog daemon start during that window times out the whole snapshot and
    freezes the control page on 正在启动.
    """

    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    desired = str(workbench.get("desiredState") or "").strip().lower()
    phase = str(workbench.get("phase") or "").strip().lower()
    if desired == "open" and phase in _IN_FLIGHT_OPEN_PHASES:
        return True
    return _has_young_processing_open_command()


def _has_young_processing_open_command() -> bool:
    try:
        processing = _recent_command_files(PROCESSING_DIR, limit=20)
    except Exception:
        return False
    recoverable_types = {"open_workbench", "restart_workbench", "hot_restart_workbench"}
    return any(
        str(command.get("type") or "").strip() in recoverable_types
        and not _open_command_is_old_enough_to_recover(command)
        for command in processing
    )


def _open_command_is_old_enough_to_recover(command: dict[str, Any]) -> bool:
    raw = str(command.get("requestedAt") or "").strip()
    if not raw:
        return True
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return age_seconds >= _STATUS_OPEN_RECOVERY_MIN_AGE_SECONDS


def _runtime_state_workbench_is_live(runtime_state: dict[str, Any]) -> bool:
    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    observed = str(workbench.get("observedState") or "").strip().lower()
    return observed in {"open", "partial"}


def _runtime_state_matches_effective_backend_port(runtime_state: dict[str, Any]) -> bool:
    """Keep the status fast path only when its runtime port still matches the active launch contract."""

    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    state_backend_port = _positive_int(workbench.get("backendPort"))
    startup = get_launcher_startup_settings()
    startup_workbench = startup.get("workbench") if isinstance(startup.get("workbench"), dict) else {}
    effective_backend_port = _positive_int(startup_workbench.get("effectiveBackendPort"))
    return bool(state_backend_port and effective_backend_port and state_backend_port == effective_backend_port)


def _runtime_manager_state_is_fresh(runtime_state: dict[str, Any]) -> bool:
    if not bool(runtime_state.get("daemonRunning")):
        return False
    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    if not workbench:
        return False
    updated_at = str(runtime_state.get("updatedAt") or "").strip()
    if not updated_at:
        return False
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0:
        age_seconds = 0
    if age_seconds > _RUNTIME_MANAGER_STATUS_FAST_PATH_MAX_AGE_SECONDS:
        return False
    phase = str(workbench.get("phase") or "").strip()
    desired_state = str(workbench.get("desiredState") or "").strip()
    observed_state = str(workbench.get("observedState") or "").strip()
    return bool(phase and desired_state and observed_state)


def _workbench_payload(*, runtime_state: dict[str, Any], observed_workbench: dict[str, Any]) -> dict[str, Any]:
    state_workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    observed = observed_workbench if isinstance(observed_workbench, dict) else {}
    desktop_window = _desktop_session_workbench_projection()
    if not desktop_window:
        desktop_window = _desktop_session_window_provider_projection()
    if desktop_window:
        observed = {**observed, **desktop_window}
    has_observation = bool(observed)

    def observed_or_state(key: str, default: Any = None) -> Any:
        if has_observation and key in observed:
            return observed.get(key)
        return state_workbench.get(key, default)

    desired_state = str(state_workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(observed_or_state("observedState", "closed") or "closed").strip() or "closed"
    phase = str(state_workbench.get("phase") or "steady").strip() or "steady"
    raw_session_role = str(observed_or_state("sessionRole", "workbench") or "workbench").strip() or "workbench"
    project_window_alive = bool(observed_or_state("browserWindowAlive", False))
    backend_observed = bool(observed_or_state("backendObserved", False))
    backend_healthy = bool(observed_or_state("backendHealthy", False))
    backend_port_listening = bool(observed_or_state("backendPortListening", False))
    last_request_audit = _last_request_audit_payload(state_workbench.get("lastRequestAudit"))
    backend_port_conflict = bool(observed_or_state("backendPortConflict", False))
    backend_alive = bool(
        observed_or_state("backendAlive", False)
        or (backend_healthy and backend_port_listening and not backend_port_conflict)
    )
    browser_managed = bool(observed_or_state("browserManaged", True))
    window_managed = bool(observed_or_state("windowManaged", False))
    window_provider = str(observed_or_state("windowProvider", "") or "").strip()
    external_window_owner = str(observed_or_state("externalWindowOwner", "") or "").strip()
    desktop_session_id = str(observed_or_state("desktopSessionId", "") or "").strip()
    electron_window_expected = bool(
        window_provider == "electron"
        or external_window_owner == "electron"
        or desktop_session_id
    )
    active_close_transaction = (
        lifecycle_intent_store.latest_active_workbench_close_transaction_for_session(desktop_session_id)
        if desktop_session_id
        else {}
    )
    project_backend_present = bool(
        backend_observed
        or backend_alive
        or (backend_healthy and backend_port_listening)
    )
    session_role = (
        "workbench"
        if raw_session_role == "launcher_control_surface" and (project_window_alive or project_backend_present)
        else raw_session_role
    )
    if raw_session_role == "launcher_control_surface":
        if project_window_alive:
            observed_state = "open"
            desired_state = "open"
        elif project_backend_present:
            if observed_state == "closed":
                observed_state = "partial" if browser_managed else "open"
            if desired_state == "closed" and phase not in {"closing", "failed"}:
                desired_state = "open"
        elif desired_state == "open" and phase not in {"opening", "failed"}:
            desired_state = "closed"
    if (
        project_window_alive
        and window_managed
        and electron_window_expected
        and desired_state == "closed"
        and not active_close_transaction
    ):
        # Electron's live workbench window is the current lifecycle truth.
        # A stopped Runtime Manager can leave an older desiredState=closed
        # snapshot behind; do not turn that stale state into a closing overlay.
        desired_state = "open"
    if electron_window_expected and project_backend_present and not project_window_alive and not window_managed:
        observed_state = "partial"
    manager_running = bool(runtime_state.get("daemonRunning"))
    runtime_command = runtime_state.get("command") if isinstance(runtime_state.get("command"), dict) else {}
    active_command_id = str(runtime_command.get("activeCommandId") or "").strip()
    observation_confirms_open_workbench = bool(
        has_observation
        and observed_state == "open"
        and backend_healthy
        and backend_port_listening
        and not backend_port_conflict
    )
    observation_confirms_visible_workbench = bool(
        observation_confirms_open_workbench
        and project_window_alive
        and (browser_managed or window_managed)
    )
    frontend_orphaned = False if observation_confirms_open_workbench else bool(observed_or_state("frontendOrphaned", False))
    lifecycle_consistency = str(
        observed_or_state("lifecycleConsistency", "consistent") or "consistent"
    ).strip() or "consistent"
    if observation_confirms_open_workbench and not electron_window_expected:
        lifecycle_consistency = "consistent"
    if desktop_window and bool(desktop_window.get("windowManaged")) and lifecycle_consistency == "browser_missing":
        # An active Electron workbench window is the managed frontend.  The
        # legacy browser process probe cannot observe it, so its stale
        # browser_missing result must not override desktop-session evidence.
        lifecycle_consistency = "consistent"
    browser_missing = bool(
        lifecycle_consistency == "browser_missing"
        or (electron_window_expected and project_backend_present and not project_window_alive and not window_managed)
        or (
            observed_state == "partial"
            and browser_managed
            and not project_window_alive
            and project_backend_present
        )
    )
    if electron_window_expected and project_backend_present and not project_window_alive and not window_managed:
        lifecycle_consistency = "browser_missing"
    stale_open_state_reconciled = False
    if (
        has_observation
        and not manager_running
        and not active_command_id
        and observed_state == "closed"
        and desired_state == "open"
        and phase != "failed"
    ):
        desired_state = "closed"
        phase = "steady"
        stale_open_state_reconciled = True
    if observed_state == desired_state and phase != "failed":
        phase = "steady"
    elif desired_state == "open" and observed_state == "partial" and browser_missing and phase != "failed":
        phase = "steady"
    elif desired_state == "open" and observed_state != "open" and phase != "failed":
        phase = "opening"
    elif desired_state == "closed" and observed_state != "closed" and phase != "failed":
        phase = "closing"
    failure_message = (
        str(observed.get("failureMessage") or "").strip()
        if observation_confirms_visible_workbench
        else str(state_workbench.get("failureMessage") or "").strip()
    )
    if observation_confirms_visible_workbench and phase == "failed":
        phase = "steady"
    # A non-empty failureMessage must win the status line. Dirty-main / start
    # failures previously left observedState=open + status "running" while the
    # tray showed no error, so users kept staring at a dead Edge window.
    if failure_message and phase != "failed":
        phase = "failed"
    if frontend_orphaned:
        status_line = failure_message or "前端窗口仍在，但后端服务已经离线。"
    elif phase == "failed" or failure_message:
        status_line = failure_message or "工作台生命周期遇到了错误。"
    elif desired_state == "closed" and observed_state != "closed":
        status_line = "正在关闭工作台。"
    elif browser_missing:
        status_line = "工作台窗口已关闭，后端仍在运行。"
    elif desired_state == "open" and observed_state != "open":
        status_line = "正在打开工作台。"
    elif session_role == "launcher_control_surface":
        status_line = "Launcher 控制台正在运行，项目生命周期尚未启动。"
    elif observed_state == "open":
        status_line = "工作台正在运行。"
    else:
        status_line = "工作台已关闭。"

    payload = {
        "desiredState": desired_state,
        "observedState": observed_state,
        "sessionRole": session_role,
        "phase": phase,
        "backendPid": int(observed_or_state("backendPid", 0) or 0),
        "browserWindowPid": int(observed_or_state("browserWindowPid", 0) or 0),
        "backendAlive": backend_alive,
        "backendHealthy": backend_healthy,
        "backendObserved": backend_observed,
        "backendPort": int(observed_or_state("backendPort", 0) or 0),
        "backendPortListening": backend_port_listening,
        "backendPortOwnerPid": int(observed_or_state("backendPortOwnerPid", 0) or 0),
        "backendPortConflict": backend_port_conflict,
        "browserWindowAlive": bool(observed_or_state("browserWindowAlive", False)),
        "browserManaged": browser_managed,
        "backendMissing": bool(observed_or_state("backendMissing", False)),
        "frontendOrphaned": frontend_orphaned,
        "lifecycleConsistency": lifecycle_consistency,
        "url": str(observed_or_state("url", "") or "").strip(),
        "lastReason": str(state_workbench.get("lastReason") or "").strip(),
        "lastSource": str(state_workbench.get("lastSource") or "").strip(),
        "lastTransitionAt": str(state_workbench.get("lastTransitionAt") or "").strip(),
        "lastRequestAudit": last_request_audit,
        "statusLine": status_line,
        "failureMessage": failure_message,
        "staleRuntimeStateReconciled": stale_open_state_reconciled,
        "desktopSessionId": desktop_session_id,
        "desktopSessionRevision": int(observed_or_state("desktopSessionRevision", 0) or 0),
        "desktopSessionLeaseExpiresAt": str(observed_or_state("desktopSessionLeaseExpiresAt", "") or "").strip(),
    }
    if window_provider:
        payload["windowProvider"] = window_provider
    if (has_observation and "windowManaged" in observed) or "windowManaged" in state_workbench:
        payload["windowManaged"] = bool(observed_or_state("windowManaged", False))
    window_id = int(observed_or_state("windowId", 0) or 0)
    if window_id:
        payload["windowId"] = window_id
    renderer_process_id = int(observed_or_state("rendererProcessId", 0) or 0)
    if renderer_process_id:
        payload["rendererProcessId"] = renderer_process_id
    payload.update(window_provider_projection(payload))
    return payload


def _desktop_session_workbench_projection() -> dict[str, Any]:
    projection = desktop_session_store.latest_active_workbench_projection()
    return projection if _desktop_session_projection_owner_is_live(projection) else {}


def _desktop_session_window_provider_projection() -> dict[str, Any]:
    projection = desktop_session_store.latest_active_window_provider_projection(workspace_root=str(PROJECT_ROOT))
    return projection if _desktop_session_projection_owner_is_live(projection) else {}


def _desktop_session_projection_owner_is_live(projection: dict[str, Any]) -> bool:
    if not isinstance(projection, dict) or not projection:
        return False
    session_id = str(projection.get("desktopSessionId") or "").strip()
    match = re.search(r"-(\d+)-[a-z0-9]+$", session_id, re.IGNORECASE)
    return match is None or _is_process_alive(int(match.group(1)))


def _runtime_manager_payload(runtime_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "running": bool(runtime_state.get("daemonRunning")),
        "runtimeState": str(runtime_state.get("runtimeState") or "idle"),
        "managerPid": int(runtime_state.get("managerPid") or 0),
        "stateVersion": int(runtime_state.get("stateVersion") or 0),
    }


def _positive_pid(value: object) -> int:
    try:
        pid = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


_DEFERRED_RESIDUAL_PROCESSES_PAYLOAD: dict[str, Any] = {
    "count": 0,
    "items": [],
    "mode": "deferred_for_status_poll",
}


def _normalize_residual_processes_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"count": 0, "items": []}
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    try:
        reported = int(payload.get("count") or 0)
    except (TypeError, ValueError):
        reported = 0
    normalized = {
        "count": max(reported, len(items)),
        "items": items[:16],
    }
    mode = str(payload.get("mode") or "").strip()
    if mode:
        normalized["mode"] = mode
    return normalized


def _residual_processes_from_runtime_state(runtime_state: dict[str, Any]) -> dict[str, Any] | None:
    cached = runtime_state.get("residualProcesses")
    if not isinstance(cached, dict) or "items" not in cached:
        return None
    return _normalize_residual_processes_payload(cached)


def _should_defer_residual_inventory_for_status(
    *,
    workbench: dict[str, Any],
    runtime_manager: dict[str, Any],
) -> bool:
    desired_state = str(workbench.get("desiredState") or "closed").strip().lower()
    observed_state = str(workbench.get("observedState") or "closed").strip().lower()
    phase = str(workbench.get("phase") or "steady").strip().lower()
    if desired_state == "closed" and observed_state == "closed" and phase in {"steady", ""}:
        return True
    if not bool(runtime_manager.get("running")) and observed_state == "closed":
        return True
    return False


def _should_refresh_residual_inventory_for_status(
    *,
    workbench: dict[str, Any],
) -> bool:
    desired_state = str(workbench.get("desiredState") or "closed").strip().lower()
    observed_state = str(workbench.get("observedState") or "closed").strip().lower()
    phase = str(workbench.get("phase") or "steady").strip().lower()
    if desired_state != observed_state:
        return True
    return phase in {"closing", "failed"}


def _residual_excluded_pids(*, runtime_manager: dict[str, Any], workbench: dict[str, Any]) -> set[int]:
    excluded = {os.getpid()}
    trusted_port_owner = workbench.get("backendPortOwnerPid") if workbench.get("backendPortOwnerTrusted") else 0
    for value in (
        runtime_manager.get("managerPid"),
        workbench.get("backendPid"),
        workbench.get("backendLaunchPid"),
        workbench.get("browserWindowPid"),
        workbench.get("browserLaunchPid"),
        trusted_port_owner,
    ):
        pid = _positive_pid(value)
        if pid:
            excluded.add(pid)
    return excluded


def _residual_processes_payload(
    *,
    runtime_manager: dict[str, Any],
    workbench: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    cached = _residual_processes_from_runtime_state(runtime_state)
    if cached is not None and not _should_refresh_residual_inventory_for_status(workbench=workbench):
        return cached
    if _should_defer_residual_inventory_for_status(workbench=workbench, runtime_manager=runtime_manager):
        return dict(_DEFERRED_RESIDUAL_PROCESSES_PAYLOAD)
    try:
        from core.runtime_manager.process_inventory import residual_process_payload

        payload = residual_process_payload(
            project_root=PROJECT_ROOT,
            exclude_pids=_residual_excluded_pids(runtime_manager=runtime_manager, workbench=workbench),
        )
    except Exception:
        return {"count": 0, "items": []}
    return _normalize_residual_processes_payload(payload)


def _lifecycle_proof(
    *,
    runtime_manager: dict[str, Any],
    workbench: dict[str, Any],
    active_work_runs: list[dict[str, str]],
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verified_at = datetime.now(timezone.utc).isoformat()
    desired_state = str(workbench.get("desiredState") or "closed")
    observed_state = str(workbench.get("observedState") or "closed")
    phase = str(workbench.get("phase") or "steady")
    manager_running = bool(runtime_manager.get("running"))
    backend_alive = bool(workbench.get("backendAlive"))
    browser_managed = bool(workbench.get("browserManaged", True))
    browser_alive = bool(workbench.get("browserWindowAlive"))
    lifecycle_consistency = str(workbench.get("lifecycleConsistency") or "consistent").strip().lower()
    backend_ok = backend_alive and bool(workbench.get("backendHealthy")) and not bool(workbench.get("backendPortConflict"))
    browser_ok = browser_alive or not browser_managed
    active_work_ok = not active_work_runs
    browser_missing = bool(
        lifecycle_consistency == "browser_missing"
        or (observed_state == "partial" and browser_managed and not browser_alive and backend_alive)
    )

    components = [
        _proof_component(
            "runtime_manager",
            label="Runtime Manager",
            ok=manager_running,
            state="running" if manager_running else "missing",
            required_for_open=True,
            required_for_closed=False,
            detail=f"pid={int(runtime_manager.get('managerPid') or 0)}" if manager_running else "Runtime manager is not running.",
            pid=int(runtime_manager.get("managerPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "backend",
            label="Backend",
            ok=backend_ok if desired_state == "open" else not backend_alive or backend_ok,
            state="running" if backend_alive else "missing",
            required_for_open=True,
            required_for_closed=False,
            detail=str(workbench.get("failureMessage") or ""),
            pid=int(workbench.get("backendPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "workbench_window",
            label="Workbench Window",
            ok=browser_ok,
            state="running" if browser_alive else "missing",
            required_for_open=browser_managed,
            required_for_closed=False,
            detail="",
            pid=int(workbench.get("browserWindowPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "active_work_runs",
            label="Active Work",
            ok=active_work_ok,
            state="verified" if active_work_ok else "running",
            required_for_open=False,
            required_for_closed=True,
            detail="" if active_work_ok else f"{len(active_work_runs)} active work item(s) block lifecycle commands.",
            pid=0,
            verified_at=verified_at,
        ),
    ]
    if phase == "failed":
        overall_state = "failed"
    elif active_work_runs and desired_state == "closed" and observed_state == "closed":
        overall_state = "partial"
    elif desired_state == "open" and observed_state == "open" and backend_ok and browser_ok:
        overall_state = "ready"
    elif desired_state == "open" and browser_missing:
        overall_state = "partial"
    elif desired_state == "open" and observed_state != "open":
        overall_state = "starting"
    elif desired_state == "closed" and observed_state != "closed":
        overall_state = "closing"
    elif desired_state == "closed" and observed_state == "closed":
        overall_state = "closed"
    else:
        overall_state = "partial"
    return {
        "overallState": overall_state,
        "overallLabel": overall_state,
        "summary": str(workbench.get("statusLine") or ""),
        "verifiedAt": verified_at,
        "desiredState": desired_state,
        "observedState": observed_state,
        "phase": phase,
        "browserManaged": browser_managed,
        "projectRootMatches": True,
        "components": components,
        "activeWorkRuns": {
            "count": len(active_work_runs),
            "kinds": sorted({item["kind"] for item in active_work_runs if item.get("kind")}),
            "items": active_work_runs[:8],
        },
        "residualProcesses": _residual_processes_payload(
            runtime_manager=runtime_manager,
            workbench=workbench,
            runtime_state=runtime_state,
        ),
    }


def _project_bundle_from_workbench(
    workbench: dict[str, Any],
    *,
    lifecycle_proof: dict[str, Any],
    launcher_state: dict[str, Any],
) -> dict[str, Any]:
    if (
        isinstance(launcher_state, dict)
        and str(launcher_state.get("sessionRole") or "") == "launcher_control_surface"
        and str(workbench.get("sessionRole") or "") == "launcher_control_surface"
    ):
        workbench = dict(workbench)
        workbench["sessionRole"] = "launcher_control_surface"
        workbench["desiredState"] = "closed"
        workbench["observedState"] = "closed"
        workbench["phase"] = "steady"
        workbench["statusLine"] = "Launcher 控制台正在运行，项目生命周期尚未启动。"
        workbench["browserManaged"] = bool(launcher_state.get("browserManaged", False))
        workbench["browserWindowAlive"] = False
        workbench["browserWindowPid"] = 0
        workbench.update(window_provider_projection(workbench))

    window_projection = window_provider_projection(workbench)
    last_request_audit = _last_request_audit_payload(workbench.get("lastRequestAudit"))

    frontend_dist_ready = not bool(workbench.get("frontendOrphaned"))
    backend_component = _component_state(
        "backend",
        ok=bool(workbench.get("backendHealthy")) and not bool(workbench.get("backendPortConflict")),
        state="running" if bool(workbench.get("backendAlive")) else "stopped",
        required_for_running=True,
        pid=int(workbench.get("backendPid") or 0),
        detail=str(workbench.get("failureMessage") or ""),
    )
    frontend_component = _component_state(
        "frontend",
        ok=frontend_dist_ready,
        state="ready" if frontend_dist_ready else "orphaned",
        required_for_running=True,
        pid=0,
        detail="",
    )
    browser_component = _component_state(
        "browser",
        ok=bool(workbench.get("browserWindowAlive")) or not bool(window_projection.get("browserManaged", True)),
        state="running" if bool(workbench.get("browserWindowAlive")) else "stopped",
        required_for_running=bool(window_projection.get("browserManaged", True)),
        pid=int(window_projection.get("browserWindowPid") or 0),
        detail="",
    )
    return {
        "schemaVersion": 1,
        "id": "vibelution-project",
        "mode": "bundled",
        "sessionRole": str(workbench.get("sessionRole") or "workbench"),
        "desiredState": str(workbench.get("desiredState") or "closed"),
        "observedState": str(workbench.get("observedState") or "closed"),
        "phase": str(workbench.get("phase") or "steady"),
        "overallState": str(lifecycle_proof.get("overallState") or ""),
        "lifecycleConsistency": str(workbench.get("lifecycleConsistency") or "consistent"),
        "statusLine": str(workbench.get("statusLine") or ""),
        "url": str(workbench.get("url") or ""),
        "windowProvider": str(window_projection.get("windowProvider") or "none"),
        "windowManaged": bool(window_projection.get("windowManaged")),
        "windowId": int(window_projection.get("windowId") or 0),
        "rendererProcessId": int(window_projection.get("rendererProcessId") or 0),
        "windowProfileDir": str(window_projection.get("windowProfileDir") or ""),
        "desktopSessionId": str(workbench.get("desktopSessionId") or ""),
        "desktopSessionRevision": int(workbench.get("desktopSessionRevision") or 0),
        "desktopSessionLeaseExpiresAt": str(workbench.get("desktopSessionLeaseExpiresAt") or ""),
        "lastReason": str(workbench.get("lastReason") or ""),
        "failureMessage": str(workbench.get("failureMessage") or ""),
        "lastOperation": {
            "reason": str(workbench.get("lastReason") or ""),
            "source": str(workbench.get("lastSource") or ""),
            "transitionAt": str(workbench.get("lastTransitionAt") or ""),
            "requestAudit": last_request_audit,
        },
        "components": [backend_component, frontend_component, browser_component],
        "backend": {
            "pid": int(workbench.get("backendPid") or 0),
            "alive": bool(workbench.get("backendAlive")),
            "healthy": bool(workbench.get("backendHealthy")),
            "port": int(workbench.get("backendPort") or 0),
            "portListening": bool(workbench.get("backendPortListening")),
            "portOwnerPid": int(workbench.get("backendPortOwnerPid") or 0),
            "portConflict": bool(workbench.get("backendPortConflict")),
        },
        "frontend": {
            "mode": "bundled_static_dist",
            "distReady": frontend_dist_ready,
            "orphaned": bool(workbench.get("frontendOrphaned")),
        },
        "browser": {
            "provider": str(window_projection.get("windowProvider") or "none"),
            "managed": bool(window_projection.get("browserManaged")),
            "windowPid": int(window_projection.get("browserWindowPid") or 0),
            "profileDir": str(window_projection.get("browserProfileDir") or ""),
            "alive": bool(workbench.get("browserWindowAlive")),
        },
    }


def _guardian_adapter_from_workbench(*, runtime_manager: dict[str, Any], workbench: dict[str, Any]) -> dict[str, Any]:
    supervisor = _launcher_supervisor_snapshot()
    manager_running = bool(runtime_manager.get("running"))
    manager_pid = int(runtime_manager.get("managerPid") or 0)
    window_projection = window_provider_projection(workbench)
    browser_managed = bool(window_projection.get("browserManaged", True))
    responsibilities = [
        _guardian_responsibility(
            "project_bundle_lifecycle",
            owner="standalone_launcher",
            adapter="runtime_manager",
            status="active",
            detail="Launcher owns the project-bundle lifecycle command facade; execution is delegated to runtime manager commands.",
        ),
        _guardian_responsibility(
            "runtime_manager_daemon",
            owner="runtime_manager",
            adapter="runtime_manager",
            status="running" if manager_running else "offline",
            detail=f"Runtime manager daemon pid={manager_pid}." if manager_running else "Runtime manager daemon is not observed as running.",
        ),
        _guardian_responsibility(
            "desktop_supervisor",
            owner="launcher_adapter",
            adapter="vibelution_launcher",
            status=str(supervisor.get("status") or "unknown"),
            detail=str(supervisor.get("detail") or ""),
            blocking=False,
            impact=str(supervisor.get("impact") or "non_blocking"),
            user_message=str(supervisor.get("userMessage") or ""),
        ),
        _guardian_responsibility(
            "backend_process",
            owner="runtime_manager",
            adapter="runtime_manager",
            status="running" if bool(workbench.get("backendAlive")) else "observed",
            detail="Backend process ownership is inferred from launcher state and port observation.",
        ),
        _guardian_responsibility(
            "browser_window",
            owner="launcher_adapter",
            adapter="vibelution_launcher",
            status="managed" if browser_managed else "external",
            detail="Workbench browser lifecycle remains managed by the launcher adapter until standalone Launcher owns the window controller.",
        ),
        _guardian_responsibility(
            "runtime_scene_logging",
            owner="runtime_manager_events",
            adapter="events_jsonl",
            status="active",
            detail="Standalone Launcher writes audit evidence to runtime-manager events without depending on the Web app service layer.",
        ),
    ]
    return {
        "schemaVersion": 1,
        "mode": "standalone_control_plane",
        "targetMode": "standalone_launcher_guardian",
        "statusLine": "守护职责正在归并到独立 Launcher；当前仍复用 runtime manager 执行生命周期命令。",
        "ownedCount": sum(1 for item in responsibilities if item["owner"] in {"standalone_launcher", "runtime_manager", "runtime_manager_events"}),
        "adapterCount": sum(1 for item in responsibilities if item["owner"] not in {"standalone_launcher", "runtime_manager", "runtime_manager_events"}),
        "supervisor": supervisor,
        "responsibilities": responsibilities,
    }


def _launcher_supervisor_snapshot() -> dict[str, Any]:
    state = _load_launcher_state()
    supervisor_pid = int(state.get("supervisorPid") or 0)
    alive = _is_process_alive(supervisor_pid)
    stdout_path = str(state.get("supervisorStdout") or "").strip()
    stderr_path = str(state.get("supervisorStderr") or "").strip()
    runtime_scene_id = str(state.get("runtimeSceneId") or "").strip()
    runtime_scene_dir = str(state.get("runtimeSceneDir") or "").strip()
    status = "running" if alive else "stopped" if supervisor_pid > 0 else "not_started"
    if not state:
        detail = "Launcher state is unavailable; supervisor health cannot be observed yet."
        user_message = "后台守护检查状态暂不可用；不影响 Launcher 读取当前项目状态。"
    elif alive:
        detail = f"Supervisor process is alive pid={supervisor_pid}."
        user_message = "后台守护检查正在运行。"
    elif supervisor_pid > 0:
        detail = f"Supervisor pid={supervisor_pid} is recorded but no longer alive."
        user_message = "后台守护检查未运行，不影响当前项目使用；需要时可重新接管。"
    else:
        detail = "Supervisor process has not been recorded in launcher state."
        user_message = "后台守护检查尚未记录，不影响当前项目使用。"
    return {
        "pid": supervisor_pid,
        "alive": alive,
        "status": status,
        "blocking": False,
        "impact": "non_blocking",
        "userMessage": user_message,
        "stdoutPath": stdout_path,
        "stderrPath": stderr_path,
        "runtimeSceneId": runtime_scene_id,
        "runtimeSceneDir": runtime_scene_dir,
        "detail": detail,
    }



def _load_launcher_state() -> dict[str, Any]:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _control_plane_evidence() -> dict[str, Any]:
    state = _load_json_file(STATE_PATH)
    try:
        manager_pid = load_pid()
        manager_running = _is_process_alive(manager_pid) and is_runtime_manager_process(manager_pid)
    except Exception:
        manager_pid = 0
        manager_running = False
    if not manager_running:
        manager_pid = 0
        state = dict(state)
        state["runtimeState"] = "idle"
        state["managerPid"] = 0
    pending_commands = _recent_command_files(INBOX_DIR, limit=5)
    processing_commands = _recent_command_files(PROCESSING_DIR, limit=5)
    recent_results = _recent_result_files(RESULTS_DIR, limit=5)
    recent_events = _recent_runtime_manager_events(EVENTS_PATH, limit=8)
    active_command = state.get("command") if isinstance(state.get("command"), dict) else {}
    if _active_command_has_completed_result(active_command, recent_results):
        active_command = {}
    restart_queue = _restart_queue_summary(pending_commands=pending_commands, active_command=active_command)
    return {
        "schemaVersion": 1,
        "state": {
            "stateVersion": int(state.get("stateVersion") or 0),
            "runtimeState": str(state.get("runtimeState") or ""),
            "managerPid": int(manager_pid or state.get("managerPid") or 0),
            "updatedAt": str(state.get("updatedAt") or ""),
            "activeCommand": _command_summary(active_command),
        },
        "queue": {
            "pendingCount": _file_count(INBOX_DIR),
            "processingCount": _file_count(PROCESSING_DIR),
            "pending": pending_commands,
            "processing": processing_commands,
        },
        "results": {"recent": recent_results},
        "events": {"recent": recent_events},
        "recovery": _runtime_manager_recovery_summary(recent_events=recent_events, recent_results=recent_results),
        "restartQueue": restart_queue,
    }


def _active_command_has_completed_result(active_command: dict[str, Any], recent_results: list[dict[str, Any]]) -> bool:
    command_id = str(active_command.get("activeCommandId") or active_command.get("commandId") or "").strip()
    if not command_id:
        return False
    for result in recent_results:
        if str(result.get("commandId") or "").strip() == command_id and bool(result.get("completed")):
            return True
    result_path = RESULTS_DIR / f"{command_id}.json"
    payload = _load_json_file(result_path)
    return str(payload.get("commandId") or command_id).strip() == command_id and bool(payload.get("completed"))


def _append_active_work_run(
    items: list[dict[str, str]],
    seen: set[tuple[str, str]],
    *,
    kind: str,
    payload: dict[str, Any] | None,
    force_current: bool = False,
) -> None:
    if not isinstance(payload, dict):
        return
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return
    item = _active_work_run_item(kind, payload)
    if not item["kind"]:
        return
    if not work_run_store.active_work_payload_blocks_lifecycle(payload):
        return
    if not force_current and work_run_store.snapshot_is_stale(payload):
        return
    key = (item["kind"], item["runId"] or item["sessionId"])
    if key in seen:
        return
    seen.add(key)
    items.append(item)


def _active_work_run_item(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    run_id = str(
        payload.get("runId")
        or payload.get("roundId")
        or payload.get("sessionId")
        or payload.get("id")
        or ""
    ).strip()
    status = str(payload.get("status") or payload.get("currentPhase") or payload.get("phase") or "").strip().lower()
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "").strip()
    return {
        "kind": str(payload.get("runKind") or kind or "").strip(),
        "runId": run_id,
        "status": status,
        "sessionId": session_id,
    }


def _active_work_payload_blocks_lifecycle(payload: dict[str, Any]) -> bool:
    return work_run_store.active_work_payload_blocks_lifecycle(payload)


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_count(directory: Path) -> int:
    try:
        return sum(1 for path in directory.glob("*.json") if path.is_file())
    except OSError:
        return 0


def _recent_command_files(directory: Path, *, limit: int) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    try:
        entries = list(directory.glob("*.json"))
    except OSError:
        return commands
    files: list[tuple[int, Path]] = []
    for path in entries:
        try:
            metadata = path.stat()
        except OSError:
            # A command can be atomically renamed or removed between glob and
            # stat. Ignore that entry instead of failing the whole status
            # snapshot.
            continue
        if not stat_module.S_ISREG(metadata.st_mode):
            continue
        files.append((int(metadata.st_mtime_ns), path))
    files.sort(key=lambda item: item[0], reverse=True)
    for _mtime_ns, path in files[: max(0, limit)]:
        payload = _load_json_file(path)
        if payload:
            commands.append(_command_summary(payload))
    return commands


def _recent_result_files(directory: Path, *, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        entries = list(directory.glob("*.json"))
    except OSError:
        return results
    files: list[tuple[int, Path]] = []
    for path in entries:
        try:
            metadata = path.stat()
        except OSError:
            # A result can be atomically renamed or removed between discovery
            # and stat. Keep the remaining results observable.
            continue
        if not stat_module.S_ISREG(metadata.st_mode):
            continue
        files.append((int(metadata.st_mtime_ns), path))
    files.sort(key=lambda item: item[0], reverse=True)
    for _mtime_ns, path in files[: max(0, limit)]:
        payload = _load_json_file(path)
        if payload:
            summary = _result_summary(payload)
            summary["resultPath"] = path.name
            results.append(summary)
    return results


def _recent_runtime_manager_events(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            raw = handle.read()
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        events.append(
            {
                "type": str(payload.get("type") or ""),
                "at": str(payload.get("at") or ""),
                "commandId": str(event_payload.get("commandId") or ""),
                "commandType": str(event_payload.get("type") or ""),
                "requestedBy": str(event_payload.get("requestedBy") or ""),
                "resultPath": str(event_payload.get("resultPath") or ""),
                "ok": bool(event_payload.get("ok")) if "ok" in event_payload else None,
                "message": _truncate(str(event_payload.get("message") or ""), 180),
            }
        )
        if len(events) >= limit:
            break
    return events


def _runtime_manager_recovery_summary(
    *, recent_events: list[dict[str, Any]], recent_results: list[dict[str, Any]]
) -> dict[str, Any]:
    recovered = next(
        (event for event in recent_events if str(event.get("type") or "") == "command_queue.processing_recovered"),
        None,
    )
    if not recovered:
        return {
            "active": False,
            "commandId": "",
            "commandType": "",
            "recoveredAt": "",
            "resultMessage": "",
            "resultOk": None,
            "statusLine": "",
        }
    command_id = str(recovered.get("commandId") or "")
    matching_result = next((result for result in recent_results if str(result.get("commandId") or "") == command_id), {})
    result_message = str(matching_result.get("message") or "")
    result_ok = bool(matching_result.get("ok")) if matching_result else None
    return {
        "active": True,
        "commandId": command_id,
        "commandType": str(recovered.get("commandType") or ""),
        "recoveredAt": str(recovered.get("at") or ""),
        "resultMessage": result_message,
        "resultOk": result_ok,
        "resultPath": str(matching_result.get("resultPath") or ""),
        "statusLine": _recovery_status_line(command_id=command_id, result_message=result_message, result_ok=result_ok),
    }


def _recovery_status_line(*, command_id: str, result_message: str, result_ok: bool | None) -> str:
    if result_ok is True:
        return f"已恢复并完成未结束的生命周期命令：{result_message or command_id}"
    if result_ok is False:
        return f"已恢复未结束的生命周期命令，但结果需要检查：{result_message or command_id}"
    return f"检测到生命周期管理器恢复了未结束命令：{command_id}"


def _command_summary(command: dict[str, Any]) -> dict[str, Any]:
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    return {
        "commandId": str(command.get("commandId") or command.get("activeCommandId") or ""),
        "type": str(command.get("type") or command.get("activeType") or ""),
        "requestedBy": str(command.get("requestedBy") or ""),
        "requestedAt": str(command.get("requestedAt") or command.get("startedAt") or ""),
        "reason": str(args.get("reason") or ""),
        "source": str(args.get("source") or ""),
        "noBrowser": bool(command.get("noBrowser") if "noBrowser" in command else args.get("noBrowser")),
        "stopManager": bool(command.get("stopManager") if "stopManager" in command else args.get("stopManager")),
        "deferredUntilActiveWorkClear": bool(args.get("deferredUntilActiveWorkClear")),
        "queuedBecauseActiveWork": bool(args.get("queuedBecauseActiveWork")),
        "deferUntil": str(args.get("deferUntil") or ""),
        "activeWorkDeferCount": int(args.get("activeWorkDeferCount") or 0),
        "lastActiveWorkCount": int(args.get("lastActiveWorkCount") or args.get("queuedActiveWorkCount") or 0),
    }


def _restart_queue_summary(
    *, pending_commands: list[dict[str, Any]], active_command: dict[str, Any] | None
) -> dict[str, Any]:
    pending_restarts = [
        command
        for command in pending_commands
        if str(command.get("type") or "") == "restart_workbench"
        and (bool(command.get("deferredUntilActiveWorkClear")) or bool(command.get("queuedBecauseActiveWork")))
    ]
    active_command = active_command if isinstance(active_command, dict) else {}
    active_type = str(active_command.get("activeType") or active_command.get("type") or "")
    active_restart = active_type == "restart_workbench"
    next_command = pending_restarts[0] if pending_restarts else {}
    active_work_count = int(next_command.get("lastActiveWorkCount") or 0) if next_command else 0
    pending_count = len(pending_restarts)
    return {
        "pending": bool(pending_restarts),
        "pendingCount": pending_count,
        "active": active_restart,
        "commandId": str(next_command.get("commandId") or active_command.get("activeCommandId") or ""),
        "deferUntil": str(next_command.get("deferUntil") or ""),
        "activeWorkDeferCount": int(next_command.get("activeWorkDeferCount") or 0) if next_command else 0,
        "lastActiveWorkCount": active_work_count,
        "statusLine": _restart_queue_status_line(
            pending_count=pending_count,
            active_restart=active_restart,
            active_work_count=active_work_count,
        ),
    }


def _restart_queue_status_line(*, pending_count: int, active_restart: bool, active_work_count: int) -> str:
    if active_restart:
        return "正在执行历史重启命令。"
    if pending_count <= 0:
        return ""
    if active_work_count > 0:
        return f"检测到旧版等待重启命令；当前还有 {active_work_count} 个任务，本版不会自动重启，请任务结束后重新提交。"
    return "检测到旧版等待重启命令；本版不会自动重启，请确认状态后重新提交。"


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "commandId": str(result.get("commandId") or ""),
        "ok": bool(result.get("ok")),
        "completed": bool(result.get("completed")),
        "message": _truncate(str(result.get("message") or ""), 220),
        "errorType": str(result.get("errorType") or ""),
        "stateVersion": int(result.get("stateVersion") or 0),
    }


def _proof_component(
    component_id: str,
    *,
    label: str,
    ok: bool,
    state: str,
    required_for_open: bool,
    required_for_closed: bool,
    detail: str,
    pid: int,
    verified_at: str,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "label": label,
        "state": state,
        "ok": bool(ok),
        "requiredForOpen": bool(required_for_open),
        "requiredForClosed": bool(required_for_closed),
        "detail": detail,
        "pid": int(pid or 0),
        "verifiedAt": verified_at,
    }


def _guardian_responsibility(
    responsibility_id: str,
    *,
    owner: str,
    adapter: str,
    status: str,
    detail: str,
    blocking: bool | None = None,
    impact: str = "",
    user_message: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": responsibility_id,
        "owner": owner,
        "adapter": adapter,
        "status": status,
        "detail": detail,
    }
    if blocking is not None:
        payload["blocking"] = bool(blocking)
    if impact:
        payload["impact"] = impact
    if user_message:
        payload["userMessage"] = user_message
    return payload


def _component_state(
    component_id: str,
    *,
    ok: bool,
    state: str,
    required_for_running: bool,
    pid: int,
    detail: str,
) -> dict[str, object]:
    return {
        "id": component_id,
        "ok": bool(ok),
        "state": str(state or "unknown"),
        "requiredForRunning": bool(required_for_running),
        "pid": int(pid or 0),
        "detail": str(detail or ""),
    }


def _record_launcher_event(
    event_code: str,
    *,
    phase: str,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    payload = {
        "phase": phase,
        "message": _truncate(message, 240),
        "outcome": outcome,
        "level": level,
        "fields": fields or {},
    }
    event_at = ""
    try:
        event_at = append_runtime_manager_file_event(event_code, payload, suppress_io_errors=True)
        scene_payload = dict(payload)
        for key, value in (fields or {}).items():
            if key not in scene_payload:
                scene_payload[key] = value
        record_runtime_manager_scene_event(
            event_code,
            scene_payload,
            phase=runtime_manager_event_phase(event_code),
            occurred_at=event_at,
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record launcher scene event: {exc}")
    _append_launcher_control_log_line(
        event_code,
        phase=phase,
        outcome=outcome,
        level=level,
        message=message,
        event_at=event_at,
    )


def _append_launcher_control_log_line(
    event_code: str,
    *,
    phase: str,
    outcome: str,
    level: str,
    message: str,
    event_at: str,
) -> None:
    """追加一行原始控制日志到当前场景包 raw/launcher-control.log（包结构标准成员）。

    场景不可解析时静默跳过（事件化记录仍已生效），任何失败不干扰主流程。
    """
    try:
        scene_dir = _resolve_current_runtime_scene_dir()
        if scene_dir is None:
            return
        _append_scene_log_line(
            Path(scene_dir),
            "raw/launcher-control.log",
            f"[{event_at}] {event_code} phase={phase} outcome={outcome} level={level} {message}",
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to append launcher control log line: {exc}")


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def _audit_value(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _truncate(text.replace("\r", " ").replace("\n", " "), limit)


def _audit_path(value: object, limit: int) -> str:
    text = _audit_value(value, limit)
    if not text:
        return ""
    if "?" in text:
        text = text.split("?", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return _truncate(text, limit)


def _audit_url_path(value: object, limit: int) -> str:
    text = _audit_value(value, limit)
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    return _truncate(parsed.path or "", limit)


def _audit_url_host(value: object, limit: int) -> str:
    text = _audit_value(value, limit)
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    return _truncate(parsed.netloc or "", limit)


def _last_request_audit_payload(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    limits = {
        "operation": 48,
        "trigger": 80,
        "endpoint": 120,
        "method": 16,
        "clientHost": 80,
        "refererPath": 160,
        "originHost": 120,
        "userAgent": 160,
    }
    audit: dict[str, str] = {}
    for key, limit in limits.items():
        if key not in value:
            continue
        text = _audit_value(value.get(key), limit)
        if text:
            audit[key] = text
    return audit
