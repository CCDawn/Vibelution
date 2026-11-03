"""Read-only lifecycle source selection shared by Launcher and runtime summary."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .slot_identity import normalize_slot_key


STATUS_SNAPSHOT_MAX_AGE_SECONDS = 15.0


def project_root_matches(value: object, project_root: Path | str) -> bool:
    root = str(value or "").strip()
    if not root:
        return True  # Older snapshots predate the explicit project-root field.
    try:
        return normalize_slot_key(root) == normalize_slot_key(project_root)
    except (OSError, ValueError):
        return False


def status_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def runtime_manager_snapshot_is_fresh(
    state: dict[str, Any], *, project_root: Path | str,
    max_age_seconds: float = STATUS_SNAPSHOT_MAX_AGE_SECONDS,
) -> bool:
    if not project_root_matches(state.get("projectRoot"), project_root) or not state.get("daemonRunning"):
        return False
    workbench = state.get("workbench") if isinstance(state.get("workbench"), dict) else {}
    updated_at = status_timestamp(state.get("updatedAt"))
    if not workbench or updated_at is None:
        return False
    if (datetime.now(timezone.utc) - updated_at).total_seconds() > max_age_seconds:
        return False
    return all(str(workbench.get(key) or "").strip() for key in ("phase", "desiredState", "observedState"))


def has_current_lifecycle_command(
    state: dict[str, Any], *, project_root: Path | str,
    max_age_seconds: float = STATUS_SNAPSHOT_MAX_AGE_SECONDS,
) -> bool:
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    return bool(
        command.get("activeCommandId") and command.get("activeType") in {
            "open_workbench", "restart_workbench", "hot_restart_workbench",
            "close_workbench", "force_close_workbench", "toggle_workbench",
        }
        and runtime_manager_snapshot_is_fresh(state, project_root=project_root, max_age_seconds=max_age_seconds)
    )


def runtime_state_for_status(
    runtime_state: dict[str, Any], launcher_state: dict[str, Any], *, project_root: Path | str,
) -> dict[str, Any]:
    """Select lifecycle facts without modifying either input or its disk history.

    A live, fresh daemon still owns an admitted in-flight command. Otherwise the newer,
    project-matching Electron snapshot owns intent/error; it does not prove
    process health. Callers retain their existing liveness observations.
    """
    same_project = project_root_matches(runtime_state.get("projectRoot"), project_root)
    if has_current_lifecycle_command(runtime_state, project_root=project_root):
        return runtime_state
    workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    last_error = runtime_state.get("lastError") if isinstance(runtime_state.get("lastError"), dict) else {}
    # updatedAt is an observation heartbeat, not the age of the lifecycle intent.
    # load_state also stamps defaults at read time without any persisted source.
    has_origin = bool(runtime_state.get("projectRoot") or runtime_state.get("stateVersion") or workbench.get("lastSource"))
    runtime_at = status_timestamp(workbench.get("lastTransitionAt")) if has_origin else None
    if workbench.get("phase") == "failed":
        failure_at = status_timestamp(last_error.get("at")) or status_timestamp(runtime_state.get("updatedAt"))
        if failure_at is not None:
            runtime_at = max(runtime_at, failure_at) if runtime_at is not None else failure_at
    launcher_at = status_timestamp(launcher_state.get("updatedAt"))
    launcher_current = bool(
        launcher_state.get("lastSource") == "electron_main"
        and project_root_matches(launcher_state.get("runtimeProjectRoot") or launcher_state.get("projectRoot"), project_root)
        and launcher_at is not None
        and all(str(launcher_state.get(key) or "").strip() for key in ("phase", "desiredState", "observedState"))
    )
    launcher_supersedes = bool(launcher_current and (not same_project or runtime_at is None or launcher_at > runtime_at))
    if same_project and not launcher_supersedes:
        return runtime_state
    error_at = status_timestamp(last_error.get("at"))
    current_error = last_error if same_project and error_at is not None and launcher_at is not None and error_at > launcher_at else {}
    projected = {
        **runtime_state, "projectRoot": str(project_root),
        "workbench": dict(launcher_state) if launcher_current else {}, "command": {}, "lastError": current_error,
    }
    if not same_project:
        projected.update(daemonRunning=False, managerPid=0, runtimeState="idle")
    return projected
