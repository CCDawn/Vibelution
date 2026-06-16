"""Background runtime-manager daemon."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.models import PROVIDER_API_KEY_ENV_ALIASES, get_provider_api_key_env
from config.public_config import load_public_config, read_persisted_user_env_var
from core.runtime_manager.evolution_store import build_evolution_summary
from core.web.services import self_evolution_control_service, supervised_control_service

from .command_queue import (
    claim_next_command,
    clear_lifecycle_interrupt,
    complete_command,
    defer_processing_command_for_active_work,
    lifecycle_interrupt_requested,
    recover_processing_queue,
    reject_pending_commands_for_shutdown,
)
from .constants import (
    DAEMON_LOG_BACKUP_COUNT,
    DAEMON_LOG_MAX_BYTES,
    DAEMON_LOCK_PATH,
    DAEMON_LOOP_INTERVAL_SECONDS,
    DAEMON_STDERR_PATH,
    DAEMON_STDOUT_PATH,
    EVENTS_PATH,
    PROJECT_ROOT,
    RESULTS_DIR,
    STATE_PATH,
    ensure_runtime_manager_dirs,
)
from .hot_restart_backup import create_failure_package, create_stable_backup, latest_stable_backup, restore_stable_backup
from .restart_coordinator import claim_next_restart_intent, complete_restart_intent
from .scene_logging import append_runtime_manager_file_event, record_runtime_manager_scene_event, runtime_manager_event_phase
from .state_store import clear_pid, default_state, load_pid, load_state, now_iso, save_pid, save_state
from . import work_run_store
from .process_inventory import (
    list_repo_runtime_processes,
    residual_process_payload,
    terminate_process_descendants,
    terminate_unmanaged_workbench_processes,
    terminate_workbench_processes,
)
from .workbench_controller import (
    LAUNCHER_ACTION_CANCELLED_RETURN_CODE,
    clear_workbench_launcher_state_after_close,
    close_workbench,
    focus_workbench,
    observe_workbench,
    open_workbench,
    persist_workbench_launcher_state_after_open,
    restart_workbench,
)


_WORKBENCH_LIFECYCLE_COMMANDS = {
    "open_workbench",
    "close_workbench",
    "force_close_workbench",
    "restart_workbench",
    "hot_restart_workbench",
    "toggle_workbench",
}
_SOURCE_SIGNATURE_PATHS = (
    Path("core/runtime_manager/cli.py"),
    Path("core/runtime_manager/command_queue.py"),
    Path("core/runtime_manager/constants.py"),
    Path("core/runtime_manager/daemon.py"),
    Path("core/runtime_manager/evolution_store.py"),
    Path("core/runtime_manager/process_inventory.py"),
    Path("core/runtime_manager/restart_coordinator.py"),
    Path("core/runtime_manager/scene_logging.py"),
    Path("core/runtime_manager/state_store.py"),
    Path("core/runtime_manager/workbench_controller.py"),
    Path("core/web/services/self_evolution_control_service.py"),
    Path("core/web/services/supervised_control_service.py"),
    Path("core/evaluation/dataset_adapters.py"),
    Path("core/evaluation/dataset_environment.py"),
    Path("core/evaluation/supervised_evolution.py"),
    Path("core/evaluation/supervised_workbench.py"),
    Path("core/evaluation/dataset_registry.py"),
    Path("core/orchestration/turn_runtime.py"),
    Path("scripts/evolution_harness.py"),
)
_ACTIVE_COMMAND_RESTART_GRACE_SECONDS = 300.0
_OPEN_VERIFICATION_TIMEOUT_SECONDS = 60.0
_OPEN_VERIFICATION_POLL_INTERVAL_SECONDS = 0.4
_CLOSE_VERIFICATION_TIMEOUT_SECONDS = 8.0
_CLOSE_VERIFICATION_POLL_INTERVAL_SECONDS = 0.4
_FAST_CLOSE_PROCESS_TERMINATE_TIMEOUT_SECONDS = 1.0
_DEFERRED_RESTART_ACTIVE_WORK_POLL_SECONDS = 10.0
_RESTART_BUILD_PREFLIGHT_TIMEOUT_SECONDS = 120.0
_ACTIVE_WORK_LIFECYCLE_BLOCKED_MESSAGE = "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"


def _observe_workbench_for_close() -> dict[str, Any]:
    try:
        return observe_workbench(recover_browser_window_for_backend_observed=False)
    except TypeError as exc:
        if "recover_browser_window_for_backend_observed" not in str(exc):
            raise
        return observe_workbench()


def _start_background_thread(*, name: str, target: Any) -> threading.Thread:
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


class RuntimeManagerStaleSourceError(RuntimeError):
    """Raised when the daemon process has stale source for a managed command."""


class ActiveWorkProbeFailed(RuntimeError):
    """Raised when destructive lifecycle commands cannot prove active work is clear."""

    def __init__(self, *, source: str, error_type: str, message: str) -> None:
        super().__init__(message)
        self.source = source
        self.error_type = error_type


def _command_affects_workbench_lifecycle(command_type: str) -> bool:
    return str(command_type or "").strip() in _WORKBENCH_LIFECYCLE_COMMANDS


def _active_work_run_item(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    run_id = str(
        payload.get("runId")
        or payload.get("roundId")
        or payload.get("sessionId")
        or payload.get("id")
        or ""
    ).strip()
    status = str(payload.get("status") or payload.get("currentPhase") or "").strip().lower()
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "").strip()
    return {
        "kind": str(payload.get("runKind") or kind or "").strip(),
        "runId": run_id,
        "status": status,
        "sessionId": session_id,
    }


def _active_work_status_blocks_lifecycle(status: str) -> bool:
    return work_run_store.active_work_status_blocks_lifecycle(status)


def _append_active_work_run(
    items: list[dict[str, str]],
    seen: set[tuple[str, str]],
    *,
    kind: str,
    payload: dict[str, Any] | None,
) -> None:
    if not isinstance(payload, dict):
        return
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return
    item = _active_work_run_item(kind, payload)
    if not item["kind"]:
        return
    if not _active_work_status_blocks_lifecycle(item["status"]):
        return
    key = (item["kind"], item["runId"] or item["sessionId"])
    if key in seen:
        return
    seen.add(key)
    items.append(item)


def _hot_restart_requester_fields(args: dict[str, Any]) -> dict[str, str]:
    hot_restart = args.get("hotRestart") if isinstance(args.get("hotRestart"), dict) else {}
    return {
        "sessionId": str(
            args.get("allowActiveSessionId")
            or hot_restart.get("sessionId")
            or hot_restart.get("session_id")
            or ""
        ).strip(),
        "runId": str(
            args.get("allowActiveRunId")
            or hot_restart.get("runId")
            or hot_restart.get("run_id")
            or ""
        ).strip(),
    }


def _active_work_allowed_for_hot_restart(item: dict[str, str], requester: dict[str, str]) -> bool:
    if str(item.get("kind") or "").strip() != "chat_turn":
        return False
    requester_session_id = str(requester.get("sessionId") or "").strip()
    requester_run_id = str(requester.get("runId") or "").strip()
    item_session_id = str(item.get("sessionId") or "").strip()
    item_run_id = str(item.get("runId") or "").strip()
    if requester_run_id and item_run_id == requester_run_id:
        return True
    return bool(requester_session_id and item_session_id == requester_session_id)


def _filter_active_work_for_lifecycle_command(
    active_work_runs: list[dict[str, str]],
    *,
    command_type: str,
    args: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if command_type != "hot_restart_workbench":
        return active_work_runs, []
    requester = _hot_restart_requester_fields(args)
    blocked: list[dict[str, str]] = []
    allowed: list[dict[str, str]] = []
    for item in active_work_runs:
        if _active_work_allowed_for_hot_restart(item, requester):
            allowed.append(item)
        else:
            blocked.append(item)
    return blocked, allowed


def _runtime_manager_active_work_runs() -> list[dict[str, str]]:
    """Return active project work that must block destructive lifecycle commands."""

    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    try:
        summary = build_evolution_summary()
    except Exception as exc:
        source = "evolution_summary"
        _append_event(
            "workbench.lifecycle.active_work_probe_failed",
            {"source": source, "errorType": type(exc).__name__, "message": str(exc)},
        )
        raise ActiveWorkProbeFailed(source=source, error_type=type(exc).__name__, message=str(exc)) from exc
    if isinstance(summary, dict):
        for kind, payload in (
            ("self_evolution_run", summary.get("self") if isinstance(summary.get("self"), dict) else {}),
            ("supervised_evolution_run", summary.get("supervised") if isinstance(summary.get("supervised"), dict) else {}),
        ):
            active_run_id = str(payload.get("activeRunId") or "").strip()
            if not active_run_id:
                continue
            _append_active_work_run(
                items,
                seen,
                kind=kind,
                payload={"runId": active_run_id, "status": payload.get("activeStatus") or "running"},
            )

    for source_name, kind, loader_name in (
        ("chat_turn", "chat_turn", "list_active_session_work_runs"),
        ("chat_room_round", "chat_room_round", "list_active_chat_room_work_runs"),
    ):
        try:
            if source_name == "chat_turn":
                from core.web.services.session_service import list_active_session_work_runs as loader
            else:
                from core.web.services.chat_room_service import list_active_chat_room_work_runs as loader
            payloads = loader()
        except Exception as exc:
            source = loader_name
            _append_event(
                "workbench.lifecycle.active_work_probe_failed",
                {
                    "source": source,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise ActiveWorkProbeFailed(source=source, error_type=type(exc).__name__, message=str(exc)) from exc
        for payload in payloads if isinstance(payloads, list) else []:
            _append_active_work_run(items, seen, kind=kind, payload=payload)

    try:
        from core.web.services.supervised_worktree_evolution_service import get_active_supervised_worktree_run

        worktree_run = get_active_supervised_worktree_run()
    except Exception as exc:
        source = "get_active_supervised_worktree_run"
        _append_event(
            "workbench.lifecycle.active_work_probe_failed",
            {"source": source, "errorType": type(exc).__name__, "message": str(exc)},
        )
        raise ActiveWorkProbeFailed(source=source, error_type=type(exc).__name__, message=str(exc)) from exc
    _append_active_work_run(
        items,
        seen,
        kind="supervised_worktree_evolution_run",
        payload=worktree_run,
    )
    return items


def _persistent_active_work_run_snapshots() -> list[dict[str, Any]]:
    """Return active work-run snapshots that survive backend process restarts."""

    try:
        from . import work_run_store as work_run_store_module
    except Exception:
        return []

    store = work_run_store_module.WorkRunStore(root=work_run_store_module.WORK_RUNS_DIR)
    active: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind in (
        "chat_turn",
        "chat_room_round",
        "self_evolution_run",
        "supervised_evolution_run",
        "supervised_worktree_evolution_run",
    ):
        try:
            active_run_id = str(store.load_run_index(kind).get("activeRunId") or "").strip()
        except Exception:
            active_run_id = ""
        try:
            payloads = store.list_snapshots(kind)
        except Exception:
            payloads = []
        for payload in payloads if isinstance(payloads, list) else []:
            if not isinstance(payload, dict):
                continue
            if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
                continue
            item = _active_work_run_item(kind, payload)
            if not item["kind"] or not _active_work_status_blocks_lifecycle(item["status"]):
                continue
            if not work_run_store_module.snapshot_is_current_or_fresh(payload, active_run_id=active_run_id):
                continue
            key = (item["kind"], item["runId"] or item["sessionId"])
            if key in seen:
                continue
            seen.add(key)
            active.append(payload)
    return active


def _mark_persistent_active_work_runs_force_stopped(reason: str) -> list[dict[str, Any]]:
    """Mark persisted active work runs as force-stopped for post-shutdown observability."""

    try:
        from . import work_run_store as work_run_store_module
    except Exception as exc:
        return [
            {
                "kind": "",
                "runId": "",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        ]

    store = work_run_store_module.WorkRunStore(root=work_run_store_module.WORK_RUNS_DIR)
    stopped_at = now_iso()
    stopped: list[dict[str, Any]] = []
    for snapshot in _persistent_active_work_run_snapshots():
        kind = str(snapshot.get("runKind") or snapshot.get("kind") or "").strip()
        run_id = str(snapshot.get("runId") or snapshot.get("roundId") or snapshot.get("sessionId") or "").strip()
        if not kind or not run_id:
            continue
        next_snapshot = dict(snapshot)
        next_snapshot.update(
            {
                "runId": run_id,
                "runKind": kind,
                "status": "stopped_by_user" if kind == "chat_turn" else "stopped",
                "currentPhase": "stopped_by_user" if kind == "chat_turn" else "stopped",
                "runtimeStatus": "force_stopped",
                "forceStoppedAt": stopped_at,
                "forceStopReason": str(reason or "").strip(),
                "finishedAt": str(next_snapshot.get("finishedAt") or stopped_at),
                "updatedAt": stopped_at,
            }
        )
        try:
            store.persist_snapshot(kind, next_snapshot, active_run_id="")
        except Exception as exc:
            stopped.append(
                {
                    "kind": kind,
                    "runId": run_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        stopped.append(
            {
                "kind": kind,
                "runId": run_id,
                "status": str(next_snapshot.get("status") or ""),
            }
        )
    return stopped


def _runtime_manager_source_signature() -> str:
    digest = hashlib.sha256()
    for relative_path in _SOURCE_SIGNATURE_PATHS:
        path = PROJECT_ROOT / relative_path
        digest.update(str(relative_path).replace("\\", "/").encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


_PROCESS_SOURCE_SIGNATURE = _runtime_manager_source_signature()


def _process_source_signature() -> str:
    return _PROCESS_SOURCE_SIGNATURE


def _disk_source_signature() -> str:
    return _runtime_manager_source_signature()


def _state_source_signature(state: dict[str, Any]) -> str:
    payload = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    return str(payload.get("sourceSignature") or "").strip()


def _source_freshness_payload() -> dict[str, Any]:
    process_signature = _process_source_signature()
    disk_signature = _disk_source_signature()
    return {
        "processSourceSignature": process_signature,
        "diskSourceSignature": disk_signature,
        "sourceFresh": process_signature == disk_signature,
        "signaturePathsCount": len(_SOURCE_SIGNATURE_PATHS),
    }


def _require_fresh_source_for_supervised_run() -> dict[str, Any]:
    freshness = _source_freshness_payload()
    if bool(freshness.get("sourceFresh")):
        record_runtime_manager_scene_event(
            "supervised_run.preflight.source_fresh",
            freshness,
            phase="supervised_preflight",
        )
        return freshness
    record_runtime_manager_scene_event(
        "supervised_run.preflight.stale_runtime_manager_source",
        freshness,
        phase="supervised_preflight",
    )
    raise RuntimeManagerStaleSourceError("运行管理器源码已过期，请重启后再开始监督进化。")


def _configured_llm_key_env_names(public_config: dict[str, Any]) -> set[str]:
    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    model_library = llm.get("model_library") if isinstance(llm.get("model_library"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    env_names: set[str] = set()

    for item in model_library.values():
        if isinstance(item, dict):
            env_name = str(item.get("api_key_env") or "").strip()
            if env_name:
                env_names.add(env_name)

    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        provider_env = str(provider.get("api_key_env") or "").strip()
        if provider_env:
            env_names.add(provider_env)
        provider_kind = str(provider.get("kind") or "").strip().lower()
        canonical_env = get_provider_api_key_env(provider_kind)
        if canonical_env:
            env_names.add(canonical_env)
        for alias in PROVIDER_API_KEY_ENV_ALIASES.get(provider_kind, []):
            alias_env = str(alias or "").strip()
            if alias_env:
                env_names.add(alias_env)

    return env_names


def _sync_llm_key_env_from_persisted_user_env(*, command_type: str) -> dict[str, Any]:
    """Refresh long-lived Runtime Manager env from saved user-level LLM keys."""

    try:
        public_config = load_public_config()
    except Exception as exc:
        payload = {
            "commandType": command_type,
            "ok": False,
            "errorType": type(exc).__name__,
            "message": str(exc),
        }
        record_runtime_manager_scene_event(
            "supervised_run.preflight.llm_key_env_sync_failed",
            payload,
            phase="supervised_preflight",
        )
        return payload

    env_names = sorted(_configured_llm_key_env_names(public_config))
    synced: list[str] = []
    already_present = 0
    missing: list[str] = []
    for env_name in env_names:
        if os.environ.get(env_name):
            already_present += 1
            continue
        persisted_value = read_persisted_user_env_var(env_name)
        if persisted_value:
            os.environ[env_name] = persisted_value
            synced.append(env_name)
        else:
            missing.append(env_name)

    payload = {
        "commandType": command_type,
        "ok": True,
        "envCount": len(env_names),
        "alreadyPresentCount": already_present,
        "syncedCount": len(synced),
        "syncedEnvNames": synced[:20],
        "missingCount": len(missing),
        "missingEnvNames": missing[:20],
    }
    record_runtime_manager_scene_event(
        "supervised_run.preflight.llm_key_env_synced",
        payload,
        phase="supervised_preflight",
    )
    return payload


def _active_command_is_recent(state: dict[str, Any]) -> bool:
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    if not str(command.get("activeCommandId") or "").strip():
        return False
    started_at = str(command.get("startedAt") or "").strip()
    if not started_at:
        return False
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return age_seconds < _ACTIVE_COMMAND_RESTART_GRACE_SECONDS


def _parse_command_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_ms_between(start: Any, end: Any) -> float | None:
    started = _parse_command_datetime(start)
    ended = _parse_command_datetime(end)
    if started is None or ended is None:
        return None
    return round(max(0.0, (ended - started).total_seconds() * 1000.0), 1)


def _elapsed_monotonic_ms(started_at: float) -> float:
    return round(max(0.0, (time.monotonic() - started_at) * 1000.0), 1)


def _command_runtime_timing_fields(
    payload: dict[str, Any],
    *,
    started_at: str,
    run_ms: float,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "startedAt": started_at,
        "runMs": round(max(0.0, run_ms), 1),
    }
    requested_at = str(payload.get("requestedAt") or "").strip()
    if requested_at:
        fields["requestedAt"] = requested_at
        queued_ms = _elapsed_ms_between(requested_at, started_at)
        if queued_ms is not None:
            fields["queuedMs"] = queued_ms
    claimed_at = str(payload.get("claimedAt") or "").strip()
    if claimed_at:
        fields["claimedAt"] = claimed_at
    return fields


def _command_result_is_completed(command_id: str) -> bool:
    normalized = str(command_id or "").strip()
    if not normalized:
        return False
    result_path = RESULTS_DIR / f"{normalized}.json"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(isinstance(payload, dict) and payload.get("completed"))


def _terminate_daemon_process(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            clear_pid(pid)
            return
        time.sleep(0.1)
    if hasattr(signal, "SIGKILL"):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    clear_pid(pid)


def _read_daemon_lock_pid() -> int:
    try:
        return int(DAEMON_LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _claim_daemon_ownership(pid: int) -> bool:
    current_pid = int(pid or 0)
    try:
        DAEMON_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    existing_pid = load_pid()
    if existing_pid and existing_pid != current_pid and _is_process_alive(existing_pid):
        _append_event(
            "daemon.start_blocked_existing_owner",
            {"pid": current_pid, "ownerPid": existing_pid, "source": "pid_file"},
        )
        return False

    for _attempt in range(2):
        try:
            fd = os.open(str(DAEMON_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner_pid = _read_daemon_lock_pid()
            if owner_pid == current_pid:
                save_pid(current_pid)
                return True
            if owner_pid and _is_process_alive(owner_pid):
                _append_event(
                    "daemon.start_blocked_existing_owner",
                    {"pid": current_pid, "ownerPid": owner_pid, "source": "lock_file"},
                )
                return False
            try:
                DAEMON_LOCK_PATH.unlink(missing_ok=True)
            except OSError:
                _append_event(
                    "daemon.start_blocked_existing_owner",
                    {"pid": current_pid, "ownerPid": owner_pid, "source": "stale_lock_unlink_failed"},
                )
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(current_pid))
        save_pid(current_pid)
        return True

    _append_event(
        "daemon.start_blocked_existing_owner",
        {"pid": current_pid, "ownerPid": _read_daemon_lock_pid(), "source": "lock_retry_exhausted"},
    )
    return False


def _release_daemon_ownership(pid: int) -> None:
    current_pid = int(pid or 0)
    if _read_daemon_lock_pid() != current_pid:
        return
    try:
        DAEMON_LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _exit_current_process(exit_code: int = 0) -> None:
    os._exit(int(exit_code))


def _workbench_failure_should_stick(state: dict[str, Any], *, desired_state: str, observed_state: str) -> bool:
    if observed_state == desired_state:
        return False
    raw_last_error = state.get("lastError")
    if isinstance(raw_last_error, dict):
        last_error = raw_last_error
        if not any(str(last_error.get(key) or "").strip() for key in ("scope", "message", "at")):
            return False
    else:
        last_error = {}
    scope = str(last_error.get("scope") or "").strip()
    return not scope or _command_affects_workbench_lifecycle(scope)


def _workbench_has_orphaned_browser(observation: dict[str, Any]) -> bool:
    consistency = str(observation.get("lifecycleConsistency") or "").strip().lower()
    if consistency == "orphaned_browser" or bool(observation.get("frontendOrphaned")):
        return True
    return bool(
        observation.get("browserManaged", True)
        and observation.get("browserWindowAlive")
        and not observation.get("backendObserved")
        and not observation.get("backendPortListening")
        and int(observation.get("backendPortOwnerPid") or 0) <= 0
    )


def _workbench_has_missing_managed_browser(observation: dict[str, Any]) -> bool:
    consistency = str(observation.get("lifecycleConsistency") or "").strip().lower()
    if consistency == "browser_missing":
        return True
    return bool(
        observation.get("browserManaged", True)
        and not observation.get("browserWindowAlive")
        and observation.get("backendObserved")
        and str(observation.get("observedState") or "closed") == "partial"
    )


def _workbench_consistency_fields(observation: dict[str, Any]) -> dict[str, Any]:
    consistency = str(observation.get("lifecycleConsistency") or "").strip() or "consistent"
    return {
        "backendMissing": bool(observation.get("backendMissing")) or (
            str(observation.get("observedState") or "closed") == "open"
            and not bool(observation.get("backendObserved"))
        ),
        "frontendOrphaned": _workbench_has_orphaned_browser(observation),
        "browserMissing": _workbench_has_missing_managed_browser(observation),
        "lifecycleConsistency": consistency,
    }


def _workbench_orphaned_browser_failure_message(observation: dict[str, Any]) -> str:
    return (
        "Workbench frontend window is still open, but no backend service is reachable. "
        f"browserWindowPid={int(observation.get('browserWindowPid') or 0)} "
        f"backendPid={int(observation.get('backendPid') or 0)} "
        f"backendPort={int(observation.get('backendPort') or 0)}"
    )


def _orphaned_browser_event_payload(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "observedState": str(observation.get("observedState") or "closed"),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "sessionId": str(observation.get("sessionId") or "").strip(),
    }


def _snapshot_should_persist_reconciliation(original_state: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    if not isinstance(original_state, dict):
        return True
    scalar_keys = ("runtimeState", "managerPid", "daemonRunning")
    if any(original_state.get(key) != snapshot.get(key) for key in scalar_keys):
        return True
    original_workbench = original_state.get("workbench") if isinstance(original_state.get("workbench"), dict) else {}
    snapshot_workbench = snapshot.get("workbench") if isinstance(snapshot.get("workbench"), dict) else {}
    workbench_keys = (
        "desiredState",
        "observedState",
        "phase",
        "backendPid",
        "browserLaunchPid",
        "browserWindowPid",
        "backendAlive",
        "backendHealthy",
        "backendObserved",
        "backendPortListening",
        "backendPortOwnerPid",
        "backendPortOwnerKind",
        "backendPortOwnerResidual",
        "backendPortOwnerTrusted",
        "backendPortConflict",
        "browserWindowAlive",
        "browserWindowRecoverySource",
        "backendMissing",
        "frontendOrphaned",
        "lifecycleConsistency",
        "statusLine",
        "failureMessage",
    )
    return any(original_workbench.get(key) != snapshot_workbench.get(key) for key in workbench_keys)


def _open_request_already_satisfied(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if not _open_request_ready(observation, no_browser=no_browser):
        return False
    return bool(observation.get("launcherStatePresent"))


def _open_should_probe_before_launch(workbench: dict[str, Any], *, no_browser: bool) -> bool:
    if str(workbench.get("phase") or "").strip() == "failed":
        return True
    observed_state = str(workbench.get("observedState") or "closed").strip()
    desired_state = str(workbench.get("desiredState") or "closed").strip()
    if observed_state in {"open", "partial"} or desired_state == "open":
        return True
    if bool(workbench.get("backendPortOwnerResidual")) or bool(workbench.get("frontendOrphaned")):
        return True
    return False


def _open_backend_ready(observation: dict[str, Any], *, launcher_confirmed: bool = False) -> bool:
    if bool(observation.get("backendPortConflict")):
        return False
    health_ready = (
        bool(observation.get("backendHealthy"))
        and bool(observation.get("backendObserved"))
    )
    if health_ready:
        return True
    if not launcher_confirmed:
        return False
    return (
        bool(observation.get("backendObserved"))
        and bool(observation.get("backendPortListening"))
        and bool(observation.get("backendPortOwnerTrusted"))
    )


def _open_backend_ready_source(observation: dict[str, Any], *, launcher_confirmed: bool = False) -> str:
    if bool(observation.get("backendPortConflict")):
        return "port_conflict"
    if bool(observation.get("backendHealthy")) and bool(observation.get("backendObserved")):
        return "health_probe"
    if _open_backend_ready(observation, launcher_confirmed=launcher_confirmed):
        return "launcher_confirmed_port"
    return "not_ready"


def _open_request_ready(observation: dict[str, Any], *, no_browser: bool, launcher_confirmed: bool = False) -> bool:
    if str(observation.get("observedState") or "closed") != "open":
        return False
    if not _open_backend_ready(observation, launcher_confirmed=launcher_confirmed):
        return False
    if no_browser:
        return True
    if not bool(observation.get("browserManaged")):
        return False
    return bool(observation.get("browserWindowAlive"))


def _restart_should_preserve_visible_browser(observation: dict[str, Any]) -> bool:
    if str(observation.get("observedState") or "closed") != "open":
        return False
    if not bool(observation.get("browserManaged")):
        return False
    if not bool(observation.get("browserWindowAlive")):
        return False
    return int(observation.get("browserWindowPid") or 0) > 0


def _restart_should_preflight_frontend_build(observation: dict[str, Any], *, args: dict[str, Any]) -> bool:
    if bool(args.get("skipFrontendBuildPreflight")):
        return False
    return (
        str(observation.get("observedState") or "closed") == "open"
        and bool(observation.get("backendAlive"))
        and bool(observation.get("browserWindowAlive"))
    )


def _open_verification_failure_message(observation: dict[str, Any], *, no_browser: bool) -> str:
    backend_ready = _open_backend_ready(observation, launcher_confirmed=True)
    browser_ready = bool(no_browser) or (
        bool(observation.get("browserManaged")) and bool(observation.get("browserWindowAlive"))
    )
    parts = [
        "Workbench launcher exited successfully, but the workbench is not ready.",
        f"observedState={str(observation.get('observedState') or 'closed')}",
        f"backendHealthy={bool(observation.get('backendHealthy'))}",
        f"backendObserved={bool(observation.get('backendObserved'))}",
        f"backendPortListening={bool(observation.get('backendPortListening'))}",
        f"backendPortOwnerPid={int(observation.get('backendPortOwnerPid') or 0)}",
        f"backendPortOwnerKind={str(observation.get('backendPortOwnerKind') or '')}",
        f"backendPortOwnerResidual={bool(observation.get('backendPortOwnerResidual'))}",
        f"backendPortConflict={bool(observation.get('backendPortConflict'))}",
        f"browserManaged={bool(observation.get('browserManaged', True))}",
        f"browserWindowAlive={bool(observation.get('browserWindowAlive'))}",
        f"noBrowser={bool(no_browser)}",
        f"backendReady={backend_ready}",
        f"backendReadySource={_open_backend_ready_source(observation, launcher_confirmed=True)}",
        f"browserReady={browser_ready}",
    ]
    return " ".join(parts)


def _open_verification_event_payload(
    observation: dict[str, Any],
    *,
    no_browser: bool,
    message: str = "",
    command_id: str = "",
    launcher_result: Any = None,
) -> dict[str, Any]:
    payload = {
        "message": message,
        "commandId": str(command_id or ""),
        "noBrowser": bool(no_browser),
        "observedState": str(observation.get("observedState") or "closed"),
        "launcherStatePresent": bool(observation.get("launcherStatePresent")),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "backendReady": _open_backend_ready(observation, launcher_confirmed=True),
        "backendReadySource": _open_backend_ready_source(observation, launcher_confirmed=True),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
        "backendPortConflict": bool(observation.get("backendPortConflict")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "url": str(observation.get("url") or ""),
        "healthUrl": str(observation.get("healthUrl") or ""),
    }
    port_owner_kind = str(observation.get("backendPortOwnerKind") or "")
    lifecycle_consistency = str(observation.get("lifecycleConsistency") or "consistent")
    if port_owner_kind:
        payload["backendPortOwnerKind"] = port_owner_kind
    if bool(observation.get("backendPortOwnerResidual")):
        payload["backendPortOwnerResidual"] = True
    if lifecycle_consistency != "consistent":
        payload["lifecycleConsistency"] = lifecycle_consistency
    if not message:
        payload.pop("message", None)
    if not command_id:
        payload.pop("commandId", None)
    if launcher_result is not None:
        payload["launcher"] = {
            "returnCode": int(getattr(launcher_result, "returncode", 0) or 0),
            "stdout": str(getattr(launcher_result, "stdout", "") or "").strip()[-1200:],
            "stderr": str(getattr(launcher_result, "stderr", "") or "").strip()[-1200:],
        }
    return payload


def _open_verification_should_retry_stale_session(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if _open_request_ready(observation, no_browser=no_browser, launcher_confirmed=True):
        return False
    if not bool(observation.get("launcherStatePresent")):
        return False
    if str(observation.get("observedState") or "closed") not in {"open", "partial"}:
        return False
    if bool(observation.get("backendPortConflict")):
        return False

    backend_ready = _open_backend_ready(observation, launcher_confirmed=True)
    browser_ready = bool(no_browser) or (
        bool(observation.get("browserManaged")) and bool(observation.get("browserWindowAlive"))
    )
    return not backend_ready or not browser_ready


def _open_verification_should_restart_missing_browser(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if no_browser:
        return False
    if _open_request_ready(observation, no_browser=no_browser, launcher_confirmed=True):
        return False
    if bool(observation.get("backendPortConflict")):
        return False
    return _workbench_has_missing_managed_browser(observation)


def _wait_for_open_verification(
    *,
    no_browser: bool,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[bool, dict[str, Any], int]:
    deadline = time.monotonic() + _OPEN_VERIFICATION_TIMEOUT_SECONDS
    attempts = 0
    latest: dict[str, Any] = {}
    while True:
        if cancel_check is not None and cancel_check():
            return False, latest, attempts
        attempts += 1
        latest = observe_workbench()
        if _open_request_ready(latest, no_browser=no_browser, launcher_confirmed=True):
            return True, latest, attempts
        if cancel_check is not None and cancel_check():
            return False, latest, attempts
        if time.monotonic() >= deadline:
            return False, latest, attempts
        time.sleep(_OPEN_VERIFICATION_POLL_INTERVAL_SECONDS)


def _active_lifecycle_interrupt(command_id: str) -> dict[str, Any]:
    interrupt = lifecycle_interrupt_requested(command_id)
    return interrupt if isinstance(interrupt, dict) else {}


def _lifecycle_interrupt_cancel_check(command_id: str) -> Callable[[], bool]:
    def check() -> bool:
        return bool(_active_lifecycle_interrupt(command_id))

    return check


def _lifecycle_interrupt_error_type(interrupt: dict[str, Any]) -> str:
    close_type = str(interrupt.get("closeCommandType") or "")
    return "SupersededByForceCloseWorkbench" if close_type == "force_close_workbench" else "SupersededByCloseWorkbench"


def _lifecycle_interrupt_result_data(
    *,
    interrupt: dict[str, Any],
    stage: str,
    launcher_result: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "interruptedByClose": True,
        "interruptStage": stage,
        "supersededByCommandId": str(interrupt.get("closeCommandId") or ""),
        "supersededByCommandType": str(interrupt.get("closeCommandType") or ""),
        "interruptOperation": str(interrupt.get("operation") or ""),
    }
    if launcher_result is not None:
        payload["launcher"] = {
            "returnCode": int(getattr(launcher_result, "returncode", 0) or 0),
            "stdout": str(getattr(launcher_result, "stdout", "") or "").strip()[-800:],
            "stderr": str(getattr(launcher_result, "stderr", "") or "").strip()[-800:],
        }
    return payload


def _open_already_satisfied_event_payload(
    observation: dict[str, Any], *, command_id: str, no_browser: bool
) -> dict[str, Any]:
    return {
        "commandId": str(command_id or ""),
        "noBrowser": bool(no_browser),
        "focusRequested": not bool(no_browser),
        "observedState": str(observation.get("observedState") or "closed"),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "sessionId": str(observation.get("sessionId") or ""),
        "url": str(observation.get("url") or ""),
    }


def _close_request_already_satisfied(observation: dict[str, Any]) -> bool:
    if str(observation.get("observedState") or "closed") != "closed":
        return False
    live_backend_evidence = (
        bool(observation.get("backendAlive"))
        or bool(observation.get("backendHealthy"))
        or bool(observation.get("backendObserved"))
        or bool(observation.get("backendPortListening"))
        or int(observation.get("backendPortOwnerPid") or 0) > 0
    )
    live_browser_evidence = bool(observation.get("browserWindowAlive"))
    return not live_backend_evidence and not live_browser_evidence


def _backend_port_is_closed_for_fast_close(port: int) -> bool:
    if int(port or 0) <= 0:
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        return probe.connect_ex(("127.0.0.1", int(port))) != 0
    finally:
        probe.close()


def _cleanup_result_confirms_workbench_closed(cleanup_result: dict[str, Any], initial_observation: dict[str, Any]) -> bool:
    if not bool(cleanup_result.get("supported", True)):
        return False
    remaining = cleanup_result.get("remaining")
    if not isinstance(remaining, list) or remaining:
        return False
    requested = cleanup_result.get("requested")
    terminated = cleanup_result.get("terminated")
    if not isinstance(requested, list) or not isinstance(terminated, list):
        return False
    if not requested and (
        bool(initial_observation.get("backendAlive"))
        or bool(initial_observation.get("backendPortListening"))
        or bool(initial_observation.get("browserWindowAlive"))
    ):
        return False
    return _backend_port_is_closed_for_fast_close(int(initial_observation.get("backendPort") or 0))


def _closed_observation_from_cleanup_result(
    initial_observation: dict[str, Any],
    cleanup_result: dict[str, Any],
) -> dict[str, Any]:
    observation = dict(initial_observation)
    observation.update(
        {
            "backendPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerKind": "",
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "observedState": "closed",
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "closeVerificationSource": "cleanup_result",
        }
    )
    if not bool(cleanup_result.get("preserveBrowserWindowPid", False)):
        observation["browserWindowRecoveredPid"] = 0
        observation["browserWindowRecoverySource"] = ""
    return observation


def _closed_observation_has_residual_evidence(observation: dict[str, Any]) -> bool:
    if str(observation.get("observedState") or "closed") != "closed":
        return False
    return bool(observation.get("backendPortOwnerResidual")) or str(observation.get("lifecycleConsistency") or "") in {
        "residual_backend",
        "orphaned_browser",
    }


def _clear_launcher_state_after_verified_close(
    observation: dict[str, Any],
    *,
    command_id: str,
    cleanup_result: dict[str, Any],
    event_type: str,
) -> dict[str, Any]:
    try:
        state_cleanup = clear_workbench_launcher_state_after_close()
    except Exception as exc:
        state_cleanup = {
            "ok": False,
            "errorType": type(exc).__name__,
            "message": str(exc),
        }
    _append_event(
        event_type,
        _close_verification_event_payload(
            observation,
            command_id=command_id,
            cleanup_result=cleanup_result,
        )
        | {"stateCleanup": state_cleanup},
    )
    return state_cleanup


def _close_verification_failure_message(observation: dict[str, Any]) -> str:
    parts = [
        "Workbench launcher exited successfully, but the workbench is not fully stopped.",
        f"observedState={str(observation.get('observedState') or 'closed')}",
        f"backendAlive={bool(observation.get('backendAlive'))}",
        f"backendHealthy={bool(observation.get('backendHealthy'))}",
        f"backendObserved={bool(observation.get('backendObserved'))}",
        f"backendPortListening={bool(observation.get('backendPortListening'))}",
        f"backendPortOwnerPid={int(observation.get('backendPortOwnerPid') or 0)}",
        f"backendPortOwnerKind={str(observation.get('backendPortOwnerKind') or '')}",
        f"backendPortOwnerResidual={bool(observation.get('backendPortOwnerResidual'))}",
        f"backendPortConflict={bool(observation.get('backendPortConflict'))}",
        f"browserWindowAlive={bool(observation.get('browserWindowAlive'))}",
        f"browserWindowPid={int(observation.get('browserWindowPid') or 0)}",
    ]
    return " ".join(parts)


def _close_verification_event_payload(
    observation: dict[str, Any],
    *,
    command_id: str = "",
    message: str = "",
    cleanup_result: dict[str, Any] | None = None,
    launcher_result: Any = None,
) -> dict[str, Any]:
    payload = {
        "message": message,
        "commandId": str(command_id or ""),
        "observedState": str(observation.get("observedState") or "closed"),
        "launcherStatePresent": bool(observation.get("launcherStatePresent")),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendLaunchPid": int(observation.get("backendLaunchPid") or 0),
        "backendAlive": bool(observation.get("backendAlive")),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
        "backendPortConflict": bool(observation.get("backendPortConflict")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "url": str(observation.get("url") or ""),
        "healthUrl": str(observation.get("healthUrl") or ""),
        "residualCleanup": cleanup_result if isinstance(cleanup_result, dict) else {},
    }
    port_owner_kind = str(observation.get("backendPortOwnerKind") or "")
    lifecycle_consistency = str(observation.get("lifecycleConsistency") or "consistent")
    if port_owner_kind:
        payload["backendPortOwnerKind"] = port_owner_kind
    if bool(observation.get("backendPortOwnerResidual")):
        payload["backendPortOwnerResidual"] = True
    if lifecycle_consistency != "consistent":
        payload["lifecycleConsistency"] = lifecycle_consistency
    if launcher_result is not None:
        payload["launcher"] = {
            "returnCode": int(getattr(launcher_result, "returncode", 0) or 0),
            "stdout": str(getattr(launcher_result, "stdout", "") or "").strip()[-800:],
            "stderr": str(getattr(launcher_result, "stderr", "") or "").strip()[-800:],
        }
    if not message:
        payload.pop("message", None)
    if not command_id:
        payload.pop("commandId", None)
    return payload


def _wait_for_close_verification() -> tuple[bool, dict[str, Any], int]:
    deadline = time.monotonic() + _CLOSE_VERIFICATION_TIMEOUT_SECONDS
    attempts = 0
    latest: dict[str, Any] = {}
    while True:
        attempts += 1
        latest = observe_workbench()
        if _close_request_already_satisfied(latest):
            return True, latest, attempts
        if time.monotonic() >= deadline:
            return False, latest, attempts
        time.sleep(_CLOSE_VERIFICATION_POLL_INTERVAL_SECONDS)


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _is_process_alive_windows(int(pid))
        except OSError:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def is_daemon_running() -> bool:
    return _is_process_alive(load_pid())


def _append_event(event_type: str, payload: dict[str, Any]) -> None:
    event_at = append_runtime_manager_file_event(
        event_type,
        payload,
        events_path=EVENTS_PATH,
        ensure_dirs=ensure_runtime_manager_dirs,
    )
    record_runtime_manager_scene_event(
        event_type,
        payload,
        phase=runtime_manager_event_phase(event_type),
        occurred_at=event_at,
    )


def _claim_workbench_reopen_intent() -> dict[str, Any] | None:
    intent = claim_next_restart_intent(target="workbench")
    if not intent:
        return None
    payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
    if str(payload.get("action") or "") != "reopen_after_close":
        complete_restart_intent(str(intent.get("intentId") or ""), status="failed", message="Unsupported workbench restart intent action.")
        return None
    return intent


def _workbench_reopen_intent_event_payload(intent: dict[str, Any], *, command_id: str) -> dict[str, Any]:
    payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
    return {
        "commandId": command_id,
        "intentId": str(intent.get("intentId") or ""),
        "target": str(intent.get("target") or ""),
        "reason": str(intent.get("reason") or ""),
        "requestedBy": str(intent.get("requestedBy") or ""),
        "sourceCommandId": str(intent.get("sourceCommandId") or ""),
        "noBrowser": bool(payload.get("noBrowser")),
    }


def _creation_flag_names() -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    return ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW")


def _creation_flags() -> int:
    flags = 0
    for name in _creation_flag_names():
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _rotated_log_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def _rotate_daemon_log_file(
    path: Path,
    *,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> dict[str, Any]:
    effective_max_bytes = DAEMON_LOG_MAX_BYTES if max_bytes is None else max_bytes
    effective_backup_count = DAEMON_LOG_BACKUP_COUNT if backup_count is None else backup_count
    payload: dict[str, Any] = {
        "path": str(path),
        "maxBytes": int(effective_max_bytes),
        "backupCount": int(effective_backup_count),
        "sizeBytes": 0,
        "rotated": False,
        "backupPath": "",
        "action": "none",
        "errorType": "",
        "errorMessage": "",
    }
    try:
        if int(effective_max_bytes) <= 0 or not path.exists():
            return payload
        size_bytes = int(path.stat().st_size)
        payload["sizeBytes"] = size_bytes
        if size_bytes <= int(effective_max_bytes):
            return payload
        path.parent.mkdir(parents=True, exist_ok=True)
        if int(effective_backup_count) <= 0:
            path.write_text("", encoding="utf-8")
            payload.update({"rotated": True, "action": "truncated"})
            return payload
        for index in range(int(effective_backup_count), 0, -1):
            source = _rotated_log_path(path, index)
            if index == int(effective_backup_count):
                if source.exists():
                    source.unlink()
                continue
            target = _rotated_log_path(path, index + 1)
            if source.exists():
                source.replace(target)
        backup_path = _rotated_log_path(path, 1)
        path.replace(backup_path)
        path.touch()
        payload.update({"rotated": True, "backupPath": str(backup_path), "action": "rotated"})
    except Exception as exc:  # pragma: no cover - platform-specific filesystem race
        payload.update({"errorType": type(exc).__name__, "errorMessage": str(exc)})
    return payload


def _rotate_daemon_logs_before_launch() -> None:
    for result in (
        _rotate_daemon_log_file(DAEMON_STDOUT_PATH),
        _rotate_daemon_log_file(DAEMON_STDERR_PATH),
    ):
        if result.get("rotated") or result.get("errorType"):
            event_type = "daemon.log_rotation.failed" if result.get("errorType") else "daemon.log_rotation.completed"
            _append_event(event_type, result)


def _select_daemon_python_runtime(python_executable: str) -> dict[str, Any]:
    """Select the Python runtime used for the long-lived daemon process."""

    raw = str(python_executable or "").strip()
    creation_flag_names = list(_creation_flag_names()) if os.name == "nt" else []
    result = {
        "pythonExecutable": raw,
        "sourcePythonExecutable": raw,
        "noConsolePythonExecutable": "",
        "consoleWindowSuppressed": bool(creation_flag_names),
        "consoleSuppressionMode": "creation_flags" if creation_flag_names else "native",
        "consoleFallbackReason": "empty_python_executable",
        "pythonLaunchPolicy": "pythonw_no_console_background_service",
        "creationFlagNames": creation_flag_names,
    }
    if not raw:
        result["consoleWindowSuppressed"] = False
        result["consoleSuppressionMode"] = "none"
        result["pythonLaunchPolicy"] = "missing_python_executable"
        return result
    candidate = Path(raw)
    if os.name != "nt":
        result["consoleFallbackReason"] = "non_windows"
        result["pythonLaunchPolicy"] = "source_python_native_process"
        return result
    if candidate.name.lower() == "pythonw.exe":
        result["pythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["noConsolePythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["consoleFallbackReason"] = "" if candidate.exists() else "pythonw_executable_missing"
        return result
    sibling = candidate.with_name("pythonw.exe")
    if sibling.exists():
        resolved_sibling = str(sibling.resolve())
        result["pythonExecutable"] = resolved_sibling
        result["noConsolePythonExecutable"] = resolved_sibling
        result["consoleFallbackReason"] = ""
        return result
    if candidate.name.lower() == "python.exe":
        result["pythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["consoleFallbackReason"] = "pythonw_missing" if candidate.exists() else "python_executable_missing"
        result["pythonLaunchPolicy"] = "source_python_hidden_creation_flags_fallback"
        return result
    sibling = candidate.with_name("python.exe")
    if sibling.exists():
        result["pythonExecutable"] = str(sibling.resolve())
        result["consoleFallbackReason"] = "pythonw_missing"
        result["pythonLaunchPolicy"] = "sibling_python_exe_hidden_creation_flags_fallback"
        return result
    if candidate.exists():
        result["pythonExecutable"] = str(candidate.resolve())
        result["consoleFallbackReason"] = "pythonw_missing"
        result["pythonLaunchPolicy"] = "source_python_hidden_creation_flags_fallback"
        return result
    result["consoleFallbackReason"] = "python_executable_missing"
    result["pythonLaunchPolicy"] = "missing_python_executable"
    return result


def ensure_daemon_running(*, python_executable: str | None = None) -> bool:
    current_pid = load_pid()
    if _is_process_alive(current_pid):
        state = load_state()
        current_signature = _process_source_signature()
        if _state_source_signature(state) == current_signature or _active_command_is_recent(state):
            return False
        _append_event(
            "daemon.restart_requested",
            {"pid": current_pid, "reason": "runtime_manager_source_changed"},
        )
        _terminate_daemon_process(current_pid)

    ensure_runtime_manager_dirs()
    _rotate_daemon_logs_before_launch()
    python_runtime = _select_daemon_python_runtime(python_executable or sys.executable)
    python_cmd = str(python_runtime["pythonExecutable"])
    with DAEMON_STDOUT_PATH.open("a", encoding="utf-8") as stdout_handle, DAEMON_STDERR_PATH.open(
        "a", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            [python_cmd, "-m", "core.runtime_manager.cli", "daemon"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=_creation_flags(),
            close_fds=True,
        )
    _append_event(
        "daemon.start_requested",
        {
            "launchPid": int(getattr(process, "pid", 0) or 0),
            "pythonExecutable": python_cmd,
            "sourcePythonExecutable": str(python_runtime["sourcePythonExecutable"]),
            "noConsolePythonExecutable": str(python_runtime["noConsolePythonExecutable"]),
            "consoleWindowSuppressed": bool(python_runtime["consoleWindowSuppressed"]),
            "consoleSuppressionMode": str(python_runtime["consoleSuppressionMode"]),
            "consoleFallbackReason": str(python_runtime["consoleFallbackReason"]),
            "pythonLaunchPolicy": str(python_runtime["pythonLaunchPolicy"]),
            "creationFlagNames": list(python_runtime["creationFlagNames"]),
        },
    )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if is_daemon_running():
            return True
        time.sleep(0.2)
    raise RuntimeError("Runtime manager daemon failed to start.")


def load_runtime_snapshot() -> dict[str, Any]:
    loaded_state = load_state()
    state = json.loads(json.dumps(loaded_state)) if isinstance(loaded_state, dict) else loaded_state
    observation = observe_workbench()
    manager_running = is_daemon_running()
    manager_pid = load_pid() if manager_running else 0
    residual_processes = residual_process_payload(
        project_root=PROJECT_ROOT,
        exclude_pids=_snapshot_residual_excluded_pids(observation, manager_pid),
    )

    if not state:
        state = default_state()

    workbench = state.setdefault("workbench", {})
    active_command = str((state.get("command") or {}).get("activeCommandId") or "").strip()
    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"
    consistency_fields = _workbench_consistency_fields(observation)
    orphaned_browser = bool(consistency_fields["frontendOrphaned"])
    browser_missing = bool(consistency_fields["browserMissing"])

    if phase == "failed" and not _workbench_failure_should_stick(state, desired_state=desired_state, observed_state=observed_state):
        phase = "steady"
        workbench["failureMessage"] = ""
    if orphaned_browser and phase not in {"opening", "closing", "failed"}:
        desired_state = "closed"
        phase = "closing"
        workbench["failureMessage"] = _workbench_orphaned_browser_failure_message(observation)

    if (not manager_running or not active_command) and phase != "failed":
        if observed_state in {"open", "partial"} and desired_state != "open":
            desired_state = "open"
            phase = "steady"
        elif observed_state == "partial" and desired_state == "open":
            phase = "steady"
        elif observed_state == "closed" and desired_state != "closed":
            desired_state = "closed"
            phase = "steady"
    if observed_state == "closed" and not manager_running and not active_command:
        phase = "steady"
        workbench["failureMessage"] = ""
        state["lastError"] = {"scope": "", "message": "", "at": ""}

    if observed_state == desired_state and phase != "failed":
        phase = "steady"
        workbench["failureMessage"] = ""
    elif desired_state == "open" and observed_state == "partial" and browser_missing and phase != "failed":
        phase = "steady"
        workbench["failureMessage"] = ""
    elif desired_state == "closed" and observed_state != "closed" and phase != "failed":
        phase = "closing"
    elif desired_state == "open" and observed_state != "open" and phase != "failed":
        phase = "opening"

    workbench.update(
        {
            "desiredState": desired_state,
            "observedState": observed_state,
            "backendPid": int(observation.get("backendPid") or 0),
            "browserLaunchPid": int(observation.get("browserLaunchPid") or 0)
            if bool(observation.get("browserWindowAlive"))
            else 0,
            "browserWindowPid": int(observation.get("browserWindowPid") or 0)
            if bool(observation.get("browserWindowAlive"))
            else 0,
            "backendAlive": bool(observation.get("backendAlive")),
            "backendHealthy": bool(observation.get("backendHealthy")),
            "backendObserved": bool(observation.get("backendObserved")),
            "backendPort": int(observation.get("backendPort") or 0),
            "backendPortListening": bool(observation.get("backendPortListening")),
            "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
            "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
            "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
            "backendPortOwnerResidual": bool(observation.get("backendPortOwnerResidual")),
            "backendPortConflict": bool(observation.get("backendPortConflict")),
            "browserWindowAlive": bool(observation.get("browserWindowAlive")),
            "browserWindowRecoverySource": str(observation.get("browserWindowRecoverySource") or ""),
            "browserManaged": bool(observation.get("browserManaged", True)),
            "backendMissing": bool(consistency_fields["backendMissing"]),
            "frontendOrphaned": bool(consistency_fields["frontendOrphaned"]),
            "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
            "sessionId": str(observation.get("sessionId") or "").strip(),
            "url": str(observation.get("url") or workbench.get("url") or "").strip(),
            "phase": phase,
            "statusLine": _build_workbench_status_line(
                desired_state=desired_state,
                observed_state=observed_state,
                phase=phase,
                backend_pid=int(observation.get("backendPid") or 0),
                browser_pid=int(observation.get("browserWindowPid") or 0),
                lifecycle_consistency=str(consistency_fields["lifecycleConsistency"]),
            ),
        }
    )
    previous_runtime_state = str(state.get("runtimeState") or "").strip().lower()
    state["runtimeState"] = "stopping" if manager_running and previous_runtime_state == "stopping" else "running" if manager_running else "idle"
    state["managerPid"] = manager_pid
    state["daemonRunning"] = manager_running
    state["projectRoot"] = str(PROJECT_ROOT)
    state["statePath"] = str(STATE_PATH)
    state["evolution"] = build_evolution_summary()
    state["residualProcesses"] = residual_processes
    runtime_manager = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    state["runtimeManager"] = {
        "sourceSignature": str(runtime_manager.get("sourceSignature") or "").strip(),
        "currentSourceSignature": _process_source_signature(),
        "sourceMatches": _state_source_signature(state) == _process_source_signature(),
    }
    if _snapshot_should_persist_reconciliation(loaded_state, state):
        state = save_state(state)
        _append_event(
            "runtime.snapshot.reconciled",
            {
                "managerRunning": bool(manager_running),
                "managerPid": int(manager_pid or 0),
                "desiredState": str(workbench.get("desiredState") or "closed"),
                "observedState": str(workbench.get("observedState") or "closed"),
                "backendPid": int(workbench.get("backendPid") or 0),
                "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
                "lifecycleConsistency": str(workbench.get("lifecycleConsistency") or "consistent"),
            },
        )
    return state


def _snapshot_residual_excluded_pids(
    observation: dict[str, Any],
    manager_pid: int = 0,
    *,
    include_workbench: bool = True,
) -> set[int]:
    excluded = {os.getpid(), int(manager_pid or 0)}
    if not include_workbench:
        return {pid for pid in excluded if pid > 0}
    for key in ("backendPid", "backendLaunchPid", "browserLaunchPid", "browserWindowPid"):
        try:
            value = int(observation.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            excluded.add(value)
    try:
        port_owner_pid = int(observation.get("backendPortOwnerPid") or 0)
    except (TypeError, ValueError):
        port_owner_pid = 0
    if port_owner_pid > 0 and bool(observation.get("backendPortOwnerTrusted")):
        excluded.add(port_owner_pid)
    return _expand_excluded_workbench_ancestors(excluded)


def _expand_excluded_workbench_ancestors(excluded: set[int]) -> set[int]:
    try:
        processes = list_repo_runtime_processes(project_root=PROJECT_ROOT)
    except Exception:
        return excluded

    by_pid = {int(item.pid): item for item in processes}
    expanded = set(excluded)
    changed = True
    while changed:
        changed = False
        for pid in list(expanded):
            item = by_pid.get(int(pid))
            if item is None:
                continue
            parent_pid = int(getattr(item, "parent_pid", 0) or 0)
            parent = by_pid.get(parent_pid)
            if parent is None or str(getattr(parent, "kind", "") or "") != "unmanaged_workbench":
                continue
            if parent_pid not in expanded:
                expanded.add(parent_pid)
                changed = True
    return expanded


def _build_workbench_status_line(
    *,
    desired_state: str,
    observed_state: str,
    phase: str,
    backend_pid: int,
    browser_pid: int,
    lifecycle_consistency: str = "consistent",
) -> str:
    if phase == "failed":
        if lifecycle_consistency == "orphaned_browser":
            return "Workbench frontend is orphaned: browser window is open but backend is stopped."
        return "Workbench hit a lifecycle error."
    if phase == "force_stopping":
        return "Runtime manager is force-closing the workbench."
    if desired_state == "closed" and observed_state != "closed":
        return "Runtime manager is closing the workbench."
    if lifecycle_consistency == "browser_missing":
        return f"Workbench window is closed; backend is still running (backend PID={backend_pid or '-'}, window PID={browser_pid or '-'})"
    if desired_state == "open" and observed_state != "open":
        return "Runtime manager is opening the workbench."
    if observed_state == "open":
        return f"Workbench is open (backend PID={backend_pid or '-'}, window PID={browser_pid or '-'})"
    return "Workbench is closed."


def _launcher_error_detail(result: Any, fallback: str) -> str:
    if not result:
        return fallback
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    return_code = int(getattr(result, "returncode", 0) or 0)
    parts: list[str] = []
    if stderr:
        parts.append(stderr)
    if stdout:
        stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        progress_lines = [line for line in stdout_lines if line.startswith("[Vibelution]")]
        diagnostic_lines = [line for line in stdout_lines if not line.startswith("[Vibelution]")]
        if diagnostic_lines:
            parts.append("\n".join(diagnostic_lines))
        elif progress_lines:
            parts.append(f"Launcher progress before exit: {progress_lines[-1]}")
    if return_code:
        parts.append(f"Launcher exit code: {return_code}")
    detail = "\n".join(part for part in parts if part)
    return detail or fallback


def _frontend_build_preflight_commands() -> list[tuple[str, list[str]]]:
    web_dir = PROJECT_ROOT / "web"
    node_command = shutil.which("node.exe" if os.name == "nt" else "node")
    if not node_command:
        node_command = "node.exe" if os.name == "nt" else "node"
    return [
        ("tsc -b", [node_command, str(web_dir / "node_modules" / "typescript" / "bin" / "tsc"), "-b"]),
        ("vite build", [node_command, str(web_dir / "node_modules" / "vite" / "bin" / "vite.js"), "build"]),
    ]


def _npm_cli_script_for_node(node_command: str) -> str:
    npm_command = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    candidates: list[Path] = []
    if npm_command:
        npm_path = Path(npm_command)
        candidates.extend([npm_path.parent, npm_path.parent.parent])
    if node_command:
        node_path = Path(node_command)
        candidates.extend([node_path.parent, node_path.parent.parent])
    for root in candidates:
        candidate = root / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if candidate.is_file():
            return str(candidate)
    return "npm.cmd" if os.name == "nt" else "npm"


def _frontend_dependency_restore_command() -> tuple[str, list[str]]:
    node_command = shutil.which("node.exe" if os.name == "nt" else "node")
    if not node_command:
        node_command = "node.exe" if os.name == "nt" else "node"
    npm_cli_script = _npm_cli_script_for_node(node_command)
    if npm_cli_script.endswith("npm-cli.js"):
        return "node npm-cli.js install", [node_command, npm_cli_script, "install"]
    return "npm install", [npm_cli_script, "install"]


def _frontend_build_preflight_missing_dependency_entries(commands: list[tuple[str, list[str]]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for label, command in commands:
        if len(command) < 2:
            continue
        entrypoint = Path(str(command[1]))
        if not entrypoint.is_file():
            missing.append({"step": label, "path": str(entrypoint)})
    return missing


def _restore_frontend_dependencies_for_restart(command_id: str, missing_entries: list[dict[str, str]]) -> dict[str, Any]:
    label, command = _frontend_dependency_restore_command()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT / "web"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_RESTART_BUILD_PREFLIGHT_TIMEOUT_SECONDS,
            creationflags=_creation_flags(),
            startupinfo=_hidden_startup_info(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        payload = {
            "commandId": command_id,
            "ok": False,
            "step": label,
            "errorType": type(exc).__name__,
            "message": str(exc),
            "missingEntries": missing_entries,
        }
        _append_event("workbench.restart.frontend_dependency_restore_failed", payload)
        raise RuntimeError(
            f"Restart preflight failed before closing the workbench during {label}: {type(exc).__name__}: {exc}"
        ) from exc
    payload = {
        "commandId": command_id,
        "ok": result.returncode == 0,
        "returnCode": int(result.returncode),
        "step": label,
        "missingEntries": missing_entries,
        "stdoutTail": str(result.stdout or "")[-1000:],
        "stderrTail": str(result.stderr or "")[-1000:],
    }
    if result.returncode != 0:
        _append_event("workbench.restart.frontend_dependency_restore_failed", payload)
        raise RuntimeError(
            "Restart preflight failed before closing the workbench.\n"
            + _launcher_error_detail(result, "Frontend dependencies are missing and automatic restore failed.")
        )
    _append_event("workbench.restart.frontend_dependency_restore_succeeded", payload)
    return payload


def _latest_mtime(paths: list[Path]) -> float:
    latest = 0.0
    for path in paths:
        try:
            if not path.exists():
                continue
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        latest = max(latest, child.stat().st_mtime)
            elif path.is_file():
                latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _frontend_build_current() -> tuple[bool, str, dict[str, Any]]:
    web_dir = PROJECT_ROOT / "web"
    dist_index = web_dir / "dist" / "index.html"
    if not dist_index.is_file():
        return False, "web/dist is missing", {"distIndex": str(dist_index), "distMtime": 0.0, "inputMtime": 0.0}

    input_paths = [
        web_dir / "src",
        web_dir / "public",
        web_dir / "package.json",
        web_dir / "package-lock.json",
        web_dir / "tsconfig.json",
        web_dir / "tsconfig.app.json",
        web_dir / "tsconfig.node.json",
        web_dir / "vite.config.ts",
        web_dir / "vite.config.js",
    ]
    try:
        dist_mtime = dist_index.stat().st_mtime
    except OSError:
        return False, "web/dist/index.html is unreadable", {"distIndex": str(dist_index), "distMtime": 0.0, "inputMtime": 0.0}
    input_mtime = _latest_mtime(input_paths)
    if input_mtime > dist_mtime:
        return (
            False,
            "frontend sources changed",
            {"distIndex": str(dist_index), "distMtime": dist_mtime, "inputMtime": input_mtime},
        )
    return True, "frontend build is current", {"distIndex": str(dist_index), "distMtime": dist_mtime, "inputMtime": input_mtime}


def _preflight_frontend_build_for_restart(command_id: str) -> dict[str, Any]:
    started_at = now_iso()
    current, reason, freshness = _frontend_build_current()
    if current:
        payload = {
            "commandId": command_id,
            "ok": True,
            "skipped": True,
            "reason": reason,
            "startedAt": started_at,
            "completedSteps": [],
            "freshness": freshness,
        }
        _append_event("workbench.restart.build_preflight_skipped_current", payload)
        return payload

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    completed_steps: list[str] = []
    commands = _frontend_build_preflight_commands()
    missing_entries = _frontend_build_preflight_missing_dependency_entries(commands)
    if missing_entries:
        _append_event(
            "workbench.restart.frontend_dependencies_missing",
            {
                "commandId": command_id,
                "ok": False,
                "missingEntries": missing_entries,
                "reason": "frontend build tool entrypoints are missing",
            },
        )
        restore_payload = _restore_frontend_dependencies_for_restart(command_id, missing_entries)
        completed_steps.append(str(restore_payload.get("step") or "npm install"))
        commands = _frontend_build_preflight_commands()
        missing_after_restore = _frontend_build_preflight_missing_dependency_entries(commands)
        if missing_after_restore:
            payload = {
                "commandId": command_id,
                "ok": False,
                "startedAt": started_at,
                "step": "frontend dependency restore verification",
                "completedSteps": completed_steps,
                "missingEntries": missing_after_restore,
            }
            _append_event("workbench.restart.build_preflight_failed", payload)
            raise RuntimeError(
                "Restart preflight failed before closing the workbench. "
                "Frontend dependencies are still missing after automatic restore: "
                + ", ".join(entry["path"] for entry in missing_after_restore)
            )
    for label, command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT / "web"),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=_RESTART_BUILD_PREFLIGHT_TIMEOUT_SECONDS,
                creationflags=_creation_flags(),
                startupinfo=_hidden_startup_info(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            payload = {
                "commandId": command_id,
                "ok": False,
                "startedAt": started_at,
                "step": label,
                "errorType": type(exc).__name__,
                "message": str(exc),
            }
            _append_event("workbench.restart.build_preflight_failed", payload)
            raise RuntimeError(
                f"Restart preflight failed before closing the workbench during {label}: {type(exc).__name__}: {exc}"
            ) from exc
        stdout = str(result.stdout or "")
        stderr = str(result.stderr or "")
        if stdout:
            stdout_parts.append(stdout)
        if stderr:
            stderr_parts.append(stderr)
        completed_steps.append(label)
        if result.returncode != 0:
            payload = {
                "commandId": command_id,
                "ok": False,
                "returnCode": int(result.returncode),
                "startedAt": started_at,
                "step": label,
                "completedSteps": completed_steps,
                "stdoutTail": "\n".join(stdout_parts)[-1000:],
                "stderrTail": "\n".join(stderr_parts)[-1000:],
            }
            _append_event("workbench.restart.build_preflight_failed", payload)
            raise RuntimeError(
                "Restart preflight failed before closing the workbench.\n"
                + _launcher_error_detail(result, f"Frontend build preflight failed during {label}.")
            )
    payload = {
        "commandId": command_id,
        "ok": True,
        "returnCode": 0,
        "startedAt": started_at,
        "completedSteps": completed_steps,
        "stdoutTail": "\n".join(stdout_parts)[-1000:],
        "stderrTail": "\n".join(stderr_parts)[-1000:],
    }
    _append_event("workbench.restart.build_preflight_succeeded", payload)
    return payload


def _close_active_evolution_runs_for_shutdown() -> list[dict[str, Any]]:
    reason = "Runtime manager is closing the workbench."
    closed: list[dict[str, Any]] = []
    for kind, closer in (
        ("self_evolution_run", self_evolution_control_service.force_cancel_active_self_evolution_runs_for_shutdown),
        ("supervised_evolution_run", supervised_control_service.force_cancel_active_supervised_runs_for_shutdown),
    ):
        try:
            snapshots = closer(reason)
        except Exception as exc:
            closed.append(
                {
                    "kind": kind,
                    "runId": "",
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for snapshot in list(snapshots or []):
            if not isinstance(snapshot, dict):
                continue
            closed.append(
                {
                    "kind": kind,
                    "runId": str(snapshot.get("runId") or ""),
                    "status": str(snapshot.get("status") or ""),
                }
            )
    return closed


def _prepare_daemon_shutdown() -> dict[str, Any]:
    closed_runs = _close_active_evolution_runs_for_shutdown()
    descendants = terminate_process_descendants(os.getpid(), exclude_pids={os.getpid()}, timeout_seconds=5.0)
    rejected_commands = reject_pending_commands_for_shutdown(shutdown_state=load_state())
    if int(rejected_commands.get("count") or 0) > 0:
        _append_event(
            "daemon.shutdown.rejected_pending_commands",
            {
                "count": int(rejected_commands.get("count") or 0),
                "commands": [
                    {
                        "commandId": str(item.get("commandId") or ""),
                        "type": str(item.get("type") or ""),
                        "status": str(item.get("status") or ""),
                    }
                    for item in list(rejected_commands.get("items") or [])
                    if isinstance(item, dict)
                ],
            },
        )
    return {
        "closedEvolutionRuns": closed_runs,
        "descendantCleanup": descendants,
        "rejectedPendingCommands": rejected_commands,
    }


def _finalize_daemon_stopped_state(*, manager_pid: int) -> None:
    state = load_state()
    if not isinstance(state, dict):
        state = default_state()
    workbench = state.setdefault("workbench", {})
    workbench.update(
        {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerKind": "",
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "failureMessage": "",
            "statusLine": "Workbench is closed.",
        }
    )
    state.setdefault("command", {}).update(
        {
            "activeCommandId": "",
            "activeType": "",
            "requestedBy": "",
            "startedAt": "",
            "stopManager": False,
        }
    )
    state["runtimeState"] = "idle"
    state["managerPid"] = 0
    state["daemonRunning"] = False
    state["lastStoppedAt"] = now_iso()
    state["lastStoppedManagerPid"] = int(manager_pid)
    save_state(state)


def _mark_daemon_not_running_after_exit(*, manager_pid: int) -> None:
    state = load_state()
    if not isinstance(state, dict):
        state = default_state()
    if int(state.get("managerPid") or 0) not in {0, int(manager_pid)}:
        return
    state["runtimeState"] = "idle"
    state["managerPid"] = 0
    state["daemonRunning"] = False
    state["lastStoppedAt"] = now_iso()
    state["lastStoppedManagerPid"] = int(manager_pid)
    save_state(state)


class RuntimeManagerDaemon:
    def __init__(self) -> None:
        self._pid = os.getpid()
        self._owns_daemon_lock = False

    def run_forever(self) -> None:
        ensure_runtime_manager_dirs()
        if not _claim_daemon_ownership(self._pid):
            return
        self._owns_daemon_lock = True

        state = load_state()
        if not isinstance(state, dict):
            state = default_state()
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["startedAt"] = now_iso()
        state = self._reconcile_observation(state)
        save_state(state)
        recover_processing_queue()

        try:
            while True:
                command = claim_next_command()
                if command is not None:
                    path, payload = command
                    result = self._handle_command(payload)
                    if bool(result.get("deferCommandUntilActiveWorkClear")):
                        defer_processing_command_for_active_work(
                            path,
                            payload,
                            active_work_runs=list(result.get("activeWorkRuns") or []),
                            delay_seconds=_DEFERRED_RESTART_ACTIVE_WORK_POLL_SECONDS,
                        )
                        self._clear_active_command()
                        time.sleep(DAEMON_LOOP_INTERVAL_SECONDS)
                        continue
                    if bool(result.get("stopDaemon")):
                        shutdown_cleanup = _prepare_daemon_shutdown()
                        if shutdown_cleanup.get("closedEvolutionRuns"):
                            result["closedEvolutionRuns"] = shutdown_cleanup["closedEvolutionRuns"]
                        result["descendantCleanup"] = shutdown_cleanup.get("descendantCleanup")
                        result["rejectedPendingCommands"] = shutdown_cleanup.get("rejectedPendingCommands")
                        state = load_state()
                        if isinstance(state, dict):
                            state["runtimeState"] = "stopping"
                            state["managerPid"] = self._pid
                            state["daemonRunning"] = True
                            save_state(state)
                        _append_event("daemon.stopped", {"commandId": str(result.get("commandId") or "")})
                    complete_command(path, result)
                    if bool(result.get("runDeferredWorkbenchOpen")):
                        self._run_deferred_workbench_open(result)
                    if bool(result.get("stopDaemon")):
                        _finalize_daemon_stopped_state(manager_pid=self._pid)
                        clear_pid(self._pid)
                        _exit_current_process(0)
                        return
                    continue

                self._process_self_evolution_restart_intent()
                state = self._reconcile_observation(load_state())
                save_state(state)
                time.sleep(DAEMON_LOOP_INTERVAL_SECONDS)
        finally:
            clear_pid(self._pid)
            if self._owns_daemon_lock:
                _release_daemon_ownership(self._pid)
            _mark_daemon_not_running_after_exit(manager_pid=self._pid)

    def _handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = str(payload.get("commandId") or "").strip()
        command_type = str(payload.get("type") or "").strip()
        requested_by = str(payload.get("requestedBy") or "unknown").strip() or "unknown"
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        command_started_at = now_iso()
        command_started_monotonic = time.monotonic()

        def with_timing(result: dict[str, Any]) -> dict[str, Any]:
            run_ms = (time.monotonic() - command_started_monotonic) * 1000.0
            result.update(
                _command_runtime_timing_fields(
                    payload,
                    started_at=command_started_at,
                    run_ms=run_ms,
                )
            )
            return result

        state = load_state()
        command_state = state.setdefault("command", {})
        command_state.update(
            {
                "activeCommandId": command_id,
                "activeType": command_type,
                "requestedBy": requested_by,
                "startedAt": command_started_at,
                "stopManager": command_type == "close_workbench" and bool(args.get("stopManager")),
                "noBrowser": command_type in {"open_workbench", "restart_workbench"} and bool(args.get("noBrowser")),
            }
        )
        if command_type == "open_workbench":
            state["runtimeState"] = "running"
            state["managerPid"] = self._pid
            state["daemonRunning"] = True
            state = save_state(state)
            _append_event(
                "command.active_marked_fast_path",
                {
                    "commandId": command_id,
                    "type": command_type,
                    "reason": "open_workbench_avoids_prelaunch_reconcile",
                },
            )
        else:
            state = self._reconcile_observation(state)
            state = save_state(state)

        handler = getattr(self, f"_handle_{command_type}", None)
        if handler is None:
            result = self._finish_command(
                command_id,
                ok=False,
                message=f"Unsupported runtime-manager command: {command_type}",
                error_scope="command",
                failure_message=f"Unsupported command: {command_type}",
            )
            result = with_timing(result)
            _append_event(
                "command.failed",
                {
                    "commandId": command_id,
                    "type": command_type,
                    "message": result["message"],
                    "requestedAt": result.get("requestedAt", ""),
                    "claimedAt": result.get("claimedAt", ""),
                    "startedAt": result.get("startedAt", ""),
                    "queuedMs": result.get("queuedMs"),
                    "runMs": result.get("runMs"),
                },
            )
            return result

        try:
            result = handler(command_id=command_id, args=args)
            result = with_timing(result)
            if bool(result.get("deferCommandUntilActiveWorkClear")):
                event_payload = {
                    "commandId": command_id,
                    "type": command_type,
                    "reason": "active_work",
                    "requestedAt": result.get("requestedAt", ""),
                    "claimedAt": result.get("claimedAt", ""),
                    "startedAt": result.get("startedAt", ""),
                    "queuedMs": result.get("queuedMs"),
                    "runMs": result.get("runMs"),
                }
                if isinstance(result.get("lifecycleTimingsMs"), dict):
                    event_payload["lifecycleTimingsMs"] = result["lifecycleTimingsMs"]
                _append_event("command.deferred", event_payload)
            else:
                event_payload = {
                    "commandId": command_id,
                    "type": command_type,
                    "ok": result["ok"],
                    "requestedAt": result.get("requestedAt", ""),
                    "claimedAt": result.get("claimedAt", ""),
                    "startedAt": result.get("startedAt", ""),
                    "queuedMs": result.get("queuedMs"),
                    "runMs": result.get("runMs"),
                }
                if isinstance(result.get("lifecycleTimingsMs"), dict):
                    event_payload["lifecycleTimingsMs"] = result["lifecycleTimingsMs"]
                if bool(result.get("interruptedByClose")):
                    event_payload["interruptedByClose"] = True
                    event_payload["interruptStage"] = str(result.get("interruptStage") or "")
                    event_payload["supersededByCommandId"] = str(result.get("supersededByCommandId") or "")
                _append_event("command.completed", event_payload)
            return result
        except Exception as exc:
            result = self._finish_command(
                command_id,
                ok=False,
                message=str(exc),
                error_scope=command_type or "command",
                failure_message=str(exc),
                error_type=type(exc).__name__,
            )
            result = with_timing(result)
            _append_event(
                "command.failed",
                {
                    "commandId": command_id,
                    "type": command_type,
                    "message": str(exc),
                    "requestedAt": result.get("requestedAt", ""),
                    "claimedAt": result.get("claimedAt", ""),
                    "startedAt": result.get("startedAt", ""),
                    "queuedMs": result.get("queuedMs"),
                    "runMs": result.get("runMs"),
                },
            )
        return result

    def _clear_active_command(self) -> None:
        state = load_state()
        if not isinstance(state, dict):
            state = default_state()
        state.setdefault("command", {}).update(
            {
                "activeCommandId": "",
                "activeType": "",
                "requestedBy": "",
                "startedAt": "",
                "stopManager": False,
                "noBrowser": False,
            }
        )
        state["lastError"] = {"scope": "", "message": "", "at": ""}
        save_state(state)

    def _finish_command(
        self,
        command_id: str,
        *,
        ok: bool,
        message: str,
        error_scope: str = "",
        failure_message: str = "",
        error_type: str = "",
        result_data: dict[str, Any] | None = None,
        reconcile: bool = True,
        reconcile_observation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = load_state()
        state.setdefault("command", {}).update(
            {
                "activeCommandId": "",
                "activeType": "",
                "requestedBy": "",
                "startedAt": "",
                "stopManager": False,
                "noBrowser": False,
            }
        )
        if ok and isinstance(result_data, dict) and bool(result_data.get("stopDaemon")):
            state["runtimeState"] = "stopping"
            state["managerPid"] = self._pid
            state["daemonRunning"] = True
        if ok:
            state["lastError"] = {"scope": "", "message": "", "at": ""}
        else:
            state["lastError"] = {"scope": error_scope, "message": message, "at": now_iso()}
            if _command_affects_workbench_lifecycle(error_scope):
                state.setdefault("workbench", {})["phase"] = "failed"
                state["workbench"]["failureMessage"] = failure_message or message
        if reconcile:
            state = self._reconcile_observation(state, observation=reconcile_observation)
        state = save_state(state)
        result = {
            "commandId": command_id,
            "accepted": True,
            "completed": True,
            "ok": ok,
            "message": message,
            "stateVersion": int(state.get("stateVersion") or 0),
        }
        if error_type:
            result["errorType"] = error_type
        if isinstance(result_data, dict):
            result.update(result_data)
        return result

    def _finish_successful_open_command(
        self,
        command_id: str,
        *,
        message: str,
        verification: dict[str, Any],
        stable_backup: dict[str, Any],
        lifecycle_timings_ms: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        workbench.update(
            {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "failureMessage": "",
                "sessionId": str(verification.get("sessionId") or "").strip(),
                "sessionRole": str(verification.get("sessionRole") or "workbench").strip() or "workbench",
                "backendPid": int(verification.get("backendPid") or 0),
                "browserLaunchPid": int(verification.get("browserLaunchPid") or 0),
                "browserWindowPid": int(verification.get("browserWindowPid") or 0),
                "backendAlive": bool(verification.get("backendAlive")),
                "backendHealthy": bool(verification.get("backendHealthy")),
                "backendObserved": bool(verification.get("backendObserved")),
                "backendPort": int(verification.get("backendPort") or 0),
                "backendPortListening": bool(verification.get("backendPortListening")),
                "backendPortOwnerPid": int(verification.get("backendPortOwnerPid") or 0),
                "backendPortOwnerKind": str(verification.get("backendPortOwnerKind") or ""),
                "backendPortOwnerTrusted": bool(verification.get("backendPortOwnerTrusted")),
                "backendPortOwnerResidual": bool(verification.get("backendPortOwnerResidual")),
                "backendPortConflict": bool(verification.get("backendPortConflict")),
                "browserWindowAlive": bool(verification.get("browserWindowAlive")),
                "browserWindowRecoverySource": str(verification.get("browserWindowRecoverySource") or ""),
                "browserManaged": bool(verification.get("browserManaged", True)),
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": str(verification.get("lifecycleConsistency") or "consistent"),
                "url": str(verification.get("url") or workbench.get("url") or "").strip(),
                "statusLine": _build_workbench_status_line(
                    desired_state="open",
                    observed_state="open",
                    phase="steady",
                    backend_pid=int(verification.get("backendPid") or 0),
                    browser_pid=int(verification.get("browserWindowPid") or 0),
                    lifecycle_consistency=str(verification.get("lifecycleConsistency") or "consistent"),
                ),
            }
        )
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        launcher_state_sync = persist_workbench_launcher_state_after_open(
            verification,
            last_reason=str(workbench.get("lastReason") or "explicit_open"),
            last_source=str(workbench.get("lastSource") or "runtime_manager"),
        )
        save_state(state)
        return self._finish_command(
            command_id,
            ok=True,
            message=message,
            result_data={
                "stableBackup": stable_backup,
                "lifecycleTimingsMs": lifecycle_timings_ms or {},
                "launcherStateSync": launcher_state_sync,
            },
            reconcile=False,
        )

    def _finish_interrupted_lifecycle_command(
        self,
        command_id: str,
        *,
        command_type: str,
        interrupt: dict[str, Any],
        stage: str,
        launcher_result: Any = None,
        extra_result_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        short_type = command_type.removesuffix("_workbench")
        error_type = _lifecycle_interrupt_error_type(interrupt)
        result_data = _lifecycle_interrupt_result_data(
            interrupt=interrupt,
            stage=stage,
            launcher_result=launcher_result,
        )
        if isinstance(extra_result_data, dict):
            result_data.update(extra_result_data)
        clear_lifecycle_interrupt(command_id)
        _append_event(
            f"workbench.{short_type}.interrupted_by_close",
            {
                "commandId": command_id,
                "stage": stage,
                "errorType": error_type,
                **result_data,
            },
        )
        return self._finish_command(
            command_id,
            ok=False,
            message=f"{command_type} was superseded by a close request.",
            error_scope="command_superseded",
            error_type=error_type,
            result_data=result_data,
        )

    def _block_lifecycle_command_if_active_work(
        self,
        *,
        command_id: str,
        command_type: str,
        args: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            active_work_runs = _runtime_manager_active_work_runs()
        except ActiveWorkProbeFailed as exc:
            event_verb = {
                "close_workbench": "close",
                "restart_workbench": "restart",
                "hot_restart_workbench": "hot_restart",
                "toggle_workbench": "toggle",
            }.get(command_type, "lifecycle")
            _append_event(
                f"workbench.{event_verb}.blocked_active_work_probe_failed",
                {
                    "commandId": command_id,
                    "commandType": command_type,
                    "reason": str(args.get("reason") or "").strip(),
                    "source": str(args.get("source") or "").strip(),
                    "probeSource": exc.source,
                    "errorType": exc.error_type,
                    "message": str(exc),
                },
            )
            return self._finish_command(
                command_id,
                ok=False,
                message=_ACTIVE_WORK_LIFECYCLE_BLOCKED_MESSAGE,
                error_scope="active_work",
                failure_message="",
                error_type="ActiveWorkProbeFailed",
                result_data={
                    "activeWorkRuns": {
                        "count": 0,
                        "items": [],
                        "allowedItems": [],
                        "probeFailed": True,
                        "probeSource": exc.source,
                        "probeErrorType": exc.error_type,
                    }
                },
            )
        blocked_active_work_runs, allowed_active_work_runs = _filter_active_work_for_lifecycle_command(
            active_work_runs,
            command_type=command_type,
            args=args,
        )
        if not blocked_active_work_runs:
            if allowed_active_work_runs:
                event_verb = {
                    "hot_restart_workbench": "hot_restart",
                }.get(command_type, "lifecycle")
                _append_event(
                    f"workbench.{event_verb}.allowed_requester_active_work",
                    {
                        "commandId": command_id,
                        "commandType": command_type,
                        "reason": str(args.get("reason") or "").strip(),
                        "source": str(args.get("source") or "").strip(),
                        "allowedActiveWorkCount": len(allowed_active_work_runs),
                        "allowedActiveWorkRuns": allowed_active_work_runs[:8],
                    },
                )
            return None

        event_verb = {
            "close_workbench": "close",
            "restart_workbench": "restart",
            "hot_restart_workbench": "hot_restart",
            "toggle_workbench": "toggle",
        }.get(command_type, "lifecycle")
        event_payload = {
            "commandId": command_id,
            "commandType": command_type,
            "reason": str(args.get("reason") or "").strip(),
            "source": str(args.get("source") or "").strip(),
            "activeWorkCount": len(blocked_active_work_runs),
            "activeWorkRuns": blocked_active_work_runs[:8],
        }
        if allowed_active_work_runs:
            event_payload["allowedActiveWorkRuns"] = allowed_active_work_runs[:8]
        if bool(args.get("deferredUntilActiveWorkClear")):
            _append_event(f"workbench.{event_verb}.deferred_active_work_wait", event_payload)
            return {
                "commandId": command_id,
                "accepted": True,
                "completed": False,
                "ok": False,
                "message": _ACTIVE_WORK_LIFECYCLE_BLOCKED_MESSAGE,
                "deferCommandUntilActiveWorkClear": True,
                "activeWorkRuns": blocked_active_work_runs,
                "allowedActiveWorkRuns": allowed_active_work_runs,
            }
        _append_event(f"workbench.{event_verb}.blocked_active_work", event_payload)
        return self._finish_command(
            command_id,
            ok=False,
            message=_ACTIVE_WORK_LIFECYCLE_BLOCKED_MESSAGE,
            error_scope="active_work",
            failure_message="",
            error_type="ActiveWorkBlocked",
            result_data={
                "activeWorkRuns": {
                    "count": len(blocked_active_work_runs),
                    "items": blocked_active_work_runs,
                    "allowedItems": allowed_active_work_runs,
                }
            },
        )

    def _reconcile_observation(self, state: dict[str, Any], *, observation: dict[str, Any] | None = None) -> dict[str, Any]:
        observation = observation if isinstance(observation, dict) else observe_workbench()
        residual_processes = residual_process_payload(
            project_root=PROJECT_ROOT,
            exclude_pids=_snapshot_residual_excluded_pids(observation, self._pid),
        )
        workbench = state.setdefault("workbench", {})
        desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
        observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
        session_role = str(observation.get("sessionRole") or "workbench").strip() or "workbench"
        phase = str(workbench.get("phase") or "steady").strip() or "steady"
        command_state = state.setdefault("command", {})
        active_command = str(command_state.get("activeCommandId") or "").strip()
        if active_command and _command_result_is_completed(active_command):
            _append_event(
                "command.active_completed_cleared",
                {
                    "commandId": active_command,
                    "activeType": str(command_state.get("activeType") or ""),
                    "requestedBy": str(command_state.get("requestedBy") or ""),
                },
            )
            command_state.update(
                {
                    "activeCommandId": "",
                    "activeType": "",
                    "requestedBy": "",
                    "startedAt": "",
                    "stopManager": False,
                    "noBrowser": False,
                }
            )
            active_command = ""
        previous_frontend_orphaned = bool(workbench.get("frontendOrphaned"))
        consistency_fields = _workbench_consistency_fields(observation)
        orphaned_browser = bool(consistency_fields["frontendOrphaned"])
        browser_missing = bool(consistency_fields["browserMissing"])

        if phase == "failed" and not _workbench_failure_should_stick(
            state,
            desired_state=desired_state,
            observed_state=observed_state,
        ):
            phase = "steady"
            workbench["failureMessage"] = ""
        if orphaned_browser and phase not in {"opening", "closing", "failed"}:
            desired_state = "closed"
            phase = "closing"
            workbench["failureMessage"] = _workbench_orphaned_browser_failure_message(observation)
            payload = _orphaned_browser_event_payload(observation)
            if not previous_frontend_orphaned:
                _append_event(
                    "workbench.consistency.orphaned_browser_detected",
                    payload,
                )
            _append_event("workbench.consistency.orphaned_browser_cleanup_requested", payload)
            result = close_workbench()
            cleanup_payload = payload | {
                "returnCode": int(result.returncode),
                "stdout": str(getattr(result, "stdout", "") or "").strip()[-400:],
                "stderr": str(getattr(result, "stderr", "") or "").strip()[-400:],
            }
            if result.returncode == 0:
                _append_event("workbench.consistency.orphaned_browser_cleanup_succeeded", cleanup_payload)
                observation = observe_workbench()
                observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
                consistency_fields = _workbench_consistency_fields(observation)
                orphaned_browser = bool(consistency_fields["frontendOrphaned"])
                browser_missing = bool(consistency_fields["browserMissing"])
                if not orphaned_browser and observed_state == "closed":
                    phase = "steady"
                    workbench["failureMessage"] = ""
            else:
                phase = "failed"
                _append_event("workbench.consistency.orphaned_browser_cleanup_failed", cleanup_payload)

        if (
            not active_command
            and desired_state == "closed"
            and phase not in {"opening", "closing", "failed"}
            and int(residual_processes.get("count") or 0) > 0
        ):
            cleanup_payload = {
                "desiredState": desired_state,
                "observedState": observed_state,
                "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
                "residualProcesses": residual_processes,
            }
            _append_event("workbench.consistency.closed_residual_cleanup_requested", cleanup_payload)
            cleanup_result = self._cleanup_residual_workbench_processes()
            cleanup_payload = cleanup_payload | {"cleanup": cleanup_result}
            if isinstance(cleanup_result, dict) and not cleanup_result.get("remaining"):
                _append_event("workbench.consistency.closed_residual_cleanup_succeeded", cleanup_payload)
            else:
                _append_event("workbench.consistency.closed_residual_cleanup_incomplete", cleanup_payload)
            observation = observe_workbench()
            observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
            consistency_fields = _workbench_consistency_fields(observation)
            browser_missing = bool(consistency_fields["browserMissing"])
            residual_processes = residual_process_payload(
                project_root=PROJECT_ROOT,
                exclude_pids=_snapshot_residual_excluded_pids(observation, self._pid),
            )

        if not active_command and phase != "failed":
            if observed_state in {"open", "partial"} and desired_state != "open":
                desired_state = "open"
                phase = "steady"
                workbench["lastReason"] = "external_open"
            elif observed_state == "partial" and desired_state == "open":
                phase = "steady"
            elif observed_state == "closed" and desired_state != "closed":
                desired_state = "closed"
                if phase != "failed":
                    phase = "steady"
                if not workbench.get("lastReason"):
                    workbench["lastReason"] = "external_close"
            elif observed_state == desired_state and phase != "failed":
                phase = "steady"

        if desired_state == "closed" and observed_state != "closed" and phase not in {"failed", "force_stopping"}:
            phase = "closing"
        elif desired_state == "open" and observed_state == "partial" and browser_missing and phase != "failed":
            phase = "steady"
        elif desired_state == "open" and observed_state != "open" and phase != "failed":
            phase = "opening"

        workbench.update(
            {
                "desiredState": desired_state,
                "observedState": observed_state,
                "phase": phase,
                "sessionId": str(observation.get("sessionId") or "").strip(),
                "sessionRole": session_role,
                "backendPid": int(observation.get("backendPid") or 0),
                "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
                "browserWindowPid": int(observation.get("browserWindowPid") or 0),
                "backendAlive": bool(observation.get("backendAlive")),
                "backendHealthy": bool(observation.get("backendHealthy")),
                "backendObserved": bool(observation.get("backendObserved")),
                "backendPort": int(observation.get("backendPort") or 0),
                "backendPortListening": bool(observation.get("backendPortListening")),
                "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
                "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
                "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
                "backendPortOwnerResidual": bool(observation.get("backendPortOwnerResidual")),
                "backendPortConflict": bool(observation.get("backendPortConflict")),
                "browserWindowAlive": bool(observation.get("browserWindowAlive")),
                "browserWindowRecoverySource": str(observation.get("browserWindowRecoverySource") or ""),
                "browserManaged": bool(observation.get("browserManaged", True)),
                "backendMissing": bool(consistency_fields["backendMissing"]),
                "frontendOrphaned": bool(consistency_fields["frontendOrphaned"]),
                "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
                "url": str(observation.get("url") or workbench.get("url") or "").strip(),
                "statusLine": _build_workbench_status_line(
                    desired_state=desired_state,
                    observed_state=observed_state,
                    phase=phase,
                    backend_pid=int(observation.get("backendPid") or 0),
                    browser_pid=int(observation.get("browserWindowPid") or 0),
                    lifecycle_consistency=str(consistency_fields["lifecycleConsistency"]),
                ),
            }
        )
        previous_runtime_state = str(state.get("runtimeState") or "").strip().lower()
        state["runtimeState"] = "stopping" if previous_runtime_state == "stopping" else "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["evolution"] = build_evolution_summary()
        state["residualProcesses"] = residual_processes
        return state

    def _process_self_evolution_restart_intent(self) -> None:
        intent = claim_next_restart_intent(target="self_evolution_run")
        if not intent:
            return
        intent_id = str(intent.get("intentId") or "").strip()
        try:
            result = self_evolution_control_service._LOCAL_FULFILL_SELF_EVOLUTION_RESTART(intent)
            snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
            complete_restart_intent(
                intent_id,
                status="completed",
                message=str(result.get("message") or "Self-evolution restart queued."),
            )
            _append_event(
                "self_evolution.restarted_from_intent",
                {
                    "intentId": intent_id,
                    "runId": str(snapshot.get("runId") or result.get("runId") or ""),
                    "status": str(snapshot.get("status") or ""),
                    "reason": str(intent.get("reason") or ""),
                },
            )
        except Exception as exc:
            if intent_id:
                complete_restart_intent(intent_id, status="failed", message=f"{type(exc).__name__}: {exc}")
            _append_event(
                "self_evolution.restart_intent_failed",
                {
                    "intentId": intent_id,
                    "reason": str(intent.get("reason") or ""),
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                },
            )

    def _create_stable_backup_after_successful_open(self, *, command_id: str, reason: str) -> dict[str, Any]:
        try:
            backup = create_stable_backup(reason=reason, command_id=command_id)
        except Exception as exc:
            backup = {"errorType": type(exc).__name__, "message": str(exc)}
            _append_event(
                "workbench.stable_backup.failed",
                {
                    "commandId": command_id,
                    "reason": reason,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                },
            )
            return backup
        _append_event(
            "workbench.stable_backup.created",
            {
                "commandId": command_id,
                "reason": reason,
                "backupId": str(backup.get("backupId") or ""),
                "fileCount": int(backup.get("fileCount") or 0),
                "prunedBackupIds": backup.get("prunedBackupIds") if isinstance(backup.get("prunedBackupIds"), list) else [],
            },
        )
        return backup

    def _queue_stable_backup_after_successful_open(self, *, command_id: str, reason: str) -> dict[str, Any]:
        _append_event(
            "workbench.stable_backup.queued",
            {
                "commandId": command_id,
                "reason": reason,
                "mode": "background",
            },
        )

        def run_backup() -> None:
            self._create_stable_backup_after_successful_open(command_id=command_id, reason=reason)

        _start_background_thread(
            name=f"vibelution-stable-backup-{command_id or 'open'}",
            target=run_backup,
        )
        return {
            "status": "queued",
            "mode": "background",
            "reason": reason,
        }

    def _handle_open_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        no_browser = bool(args.get("noBrowser"))
        should_probe_before_launch = _open_should_probe_before_launch(workbench, no_browser=no_browser)
        observation = observe_workbench() if should_probe_before_launch else {}
        if observation and _open_request_already_satisfied(observation, no_browser=no_browser) and str(workbench.get("phase") or "") != "failed":
            workbench["desiredState"] = "open"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state))
            _append_event(
                "workbench.open.already_satisfied",
                _open_already_satisfied_event_payload(observation, command_id=command_id, no_browser=no_browser),
            )
            if not no_browser:
                result = focus_workbench()
                if result.returncode != 0:
                    _append_event(
                        "workbench.open.focus_failed",
                        {
                            "commandId": command_id,
                            "returnCode": int(result.returncode),
                            "detail": _launcher_error_detail(result, "Focusing the workbench failed."),
                        },
                    )
                    raise RuntimeError(_launcher_error_detail(result, "Focusing the workbench failed."))
                _append_event(
                    "workbench.open.focus_requested",
                    {
                        "commandId": command_id,
                        "returnCode": int(result.returncode),
                        "stdout": str(getattr(result, "stdout", "") or "").strip()[-400:],
                        "stderr": str(getattr(result, "stderr", "") or "").strip()[-400:],
                    },
                )
            else:
                _append_event(
                    "workbench.open.focus_skipped",
                    {"commandId": command_id, "reason": "no_browser"},
                )
            persist_workbench_launcher_state_after_open(
                observation,
                last_reason=str(workbench.get("lastReason") or args.get("reason") or "already_open"),
                last_source=str(workbench.get("lastSource") or args.get("source") or "runtime_manager"),
            )
            return self._finish_command(command_id, ok=True, message="Workbench is already open.")

        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_open"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        save_state(state)
        _append_event(
            "workbench.open.fast_path_started",
            {
                "commandId": command_id,
                "noBrowser": no_browser,
                "prelaunchProbeSkipped": not should_probe_before_launch,
                "initialObservedState": str(observation.get("observedState") or "closed"),
                "initialLifecycleConsistency": str(observation.get("lifecycleConsistency") or "consistent"),
            },
        )
        lifecycle_timings_ms: dict[str, Any] = {}
        if bool(observation.get("backendPortOwnerResidual")):
            cleanup_started = time.monotonic()
            cleanup_result = self._cleanup_residual_workbench_processes()
            lifecycle_timings_ms["residual_cleanup_ms"] = _elapsed_monotonic_ms(cleanup_started)
            _append_event(
                "workbench.open.residual_cleanup",
                {
                    "commandId": command_id,
                    "backendPort": int(observation.get("backendPort") or 0),
                    "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
                    "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
                    "cleanup": cleanup_result,
                },
            )
        cancel_check = _lifecycle_interrupt_cancel_check(command_id)
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt:
            return self._finish_interrupted_lifecycle_command(
                command_id,
                command_type="open_workbench",
                interrupt=interrupt,
                stage="before_launcher_start",
                extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
            )
        launcher_started = time.monotonic()
        result = open_workbench(no_browser=no_browser, cancel_check=cancel_check)
        lifecycle_timings_ms["launcher_action_ms"] = _elapsed_monotonic_ms(launcher_started)
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt or int(result.returncode or 0) == LAUNCHER_ACTION_CANCELLED_RETURN_CODE:
            return self._finish_interrupted_lifecycle_command(
                command_id,
                command_type="open_workbench",
                interrupt=interrupt,
                stage="launcher_action",
                launcher_result=result,
                extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
            )
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Opening the workbench failed."))
        verification_started = time.monotonic()
        ready, verification, verification_attempts = _wait_for_open_verification(no_browser=no_browser, cancel_check=cancel_check)
        lifecycle_timings_ms["open_verification_ms"] = _elapsed_monotonic_ms(verification_started)
        lifecycle_timings_ms["open_verification_attempts"] = verification_attempts
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt:
            return self._finish_interrupted_lifecycle_command(
                command_id,
                command_type="open_workbench",
                interrupt=interrupt,
                stage="open_verification",
                launcher_result=result,
                extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
            )
        if not ready:
            if _open_verification_should_restart_missing_browser(verification, no_browser=no_browser):
                _append_event(
                    "workbench.open.browser_missing_restart",
                    _open_verification_event_payload(
                        verification,
                        no_browser=no_browser,
                        message="Open verification found a managed backend without its browser window; restarting once to rebuild the session.",
                        command_id=command_id,
                        launcher_result=result,
                    )
                    | {"attempts": verification_attempts},
                )
                browser_restart_started = time.monotonic()
                restart_result = restart_workbench(no_browser=no_browser, cancel_check=cancel_check)
                lifecycle_timings_ms["browser_missing_restart_ms"] = _elapsed_monotonic_ms(browser_restart_started)
                interrupt = _active_lifecycle_interrupt(command_id)
                if interrupt or int(restart_result.returncode or 0) == LAUNCHER_ACTION_CANCELLED_RETURN_CODE:
                    return self._finish_interrupted_lifecycle_command(
                        command_id,
                        command_type="open_workbench",
                        interrupt=interrupt,
                        stage="browser_missing_restart",
                        launcher_result=restart_result,
                        extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
                    )
                if restart_result.returncode != 0:
                    raise RuntimeError(_launcher_error_detail(restart_result, "Opening the workbench failed."))
                restart_verification_started = time.monotonic()
                ready, verification, restart_attempts = _wait_for_open_verification(no_browser=no_browser, cancel_check=cancel_check)
                lifecycle_timings_ms["browser_missing_verification_ms"] = _elapsed_monotonic_ms(restart_verification_started)
                lifecycle_timings_ms["browser_missing_verification_attempts"] = restart_attempts
                verification_attempts += restart_attempts
                lifecycle_timings_ms["open_verification_attempts"] = verification_attempts
                result = restart_result
                interrupt = _active_lifecycle_interrupt(command_id)
                if interrupt:
                    return self._finish_interrupted_lifecycle_command(
                        command_id,
                        command_type="open_workbench",
                        interrupt=interrupt,
                        stage="browser_missing_verification",
                        launcher_result=restart_result,
                        extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
                    )
                if ready:
                    _append_event(
                        "workbench.open.verification_succeeded",
                        _open_verification_event_payload(
                            verification,
                            no_browser=no_browser,
                            command_id=command_id,
                            launcher_result=restart_result,
                        )
                        | {"attempts": verification_attempts, "retry": "browser_missing_restart"},
                    )
                    stable_backup = self._queue_stable_backup_after_successful_open(
                        command_id=command_id,
                        reason="launcher_open_browser_missing_restart_success",
                    )
                    return self._finish_successful_open_command(
                        command_id,
                        message="Workbench opened.",
                        verification=verification,
                        stable_backup=stable_backup,
                        lifecycle_timings_ms=lifecycle_timings_ms,
                    )
            if _open_verification_should_retry_stale_session(verification, no_browser=no_browser):
                _append_event(
                    "workbench.open.stale_session_retry",
                    _open_verification_event_payload(
                        verification,
                        no_browser=no_browser,
                        message="Open verification found an incomplete stale session; retrying launcher cleanup once.",
                        command_id=command_id,
                        launcher_result=result,
                    )
                    | {"attempts": verification_attempts},
                )
                retry_launcher_started = time.monotonic()
                retry_result = open_workbench(no_browser=no_browser, cancel_check=cancel_check)
                lifecycle_timings_ms["launcher_retry_ms"] = _elapsed_monotonic_ms(retry_launcher_started)
                interrupt = _active_lifecycle_interrupt(command_id)
                if interrupt or int(retry_result.returncode or 0) == LAUNCHER_ACTION_CANCELLED_RETURN_CODE:
                    return self._finish_interrupted_lifecycle_command(
                        command_id,
                        command_type="open_workbench",
                        interrupt=interrupt,
                        stage="launcher_retry",
                        launcher_result=retry_result,
                        extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
                    )
                if retry_result.returncode != 0:
                    raise RuntimeError(_launcher_error_detail(retry_result, "Opening the workbench failed."))
                retry_verification_started = time.monotonic()
                ready, verification, retry_attempts = _wait_for_open_verification(no_browser=no_browser, cancel_check=cancel_check)
                lifecycle_timings_ms["retry_verification_ms"] = _elapsed_monotonic_ms(retry_verification_started)
                lifecycle_timings_ms["retry_verification_attempts"] = retry_attempts
                verification_attempts += retry_attempts
                lifecycle_timings_ms["open_verification_attempts"] = verification_attempts
                result = retry_result
                interrupt = _active_lifecycle_interrupt(command_id)
                if interrupt:
                    return self._finish_interrupted_lifecycle_command(
                        command_id,
                        command_type="open_workbench",
                        interrupt=interrupt,
                        stage="retry_verification",
                        launcher_result=retry_result,
                        extra_result_data={"lifecycleTimingsMs": lifecycle_timings_ms},
                    )
                if ready:
                    _append_event(
                        "workbench.open.verification_succeeded",
                        _open_verification_event_payload(
                            verification,
                            no_browser=no_browser,
                            command_id=command_id,
                            launcher_result=retry_result,
                        )
                        | {"attempts": verification_attempts, "retry": "stale_session_cleanup"},
                    )
                    stable_backup = self._queue_stable_backup_after_successful_open(
                        command_id=command_id,
                        reason="launcher_open_retry_success",
                    )
                    return self._finish_successful_open_command(
                        command_id,
                        message="Workbench opened.",
                        verification=verification,
                        stable_backup=stable_backup,
                        lifecycle_timings_ms=lifecycle_timings_ms,
                    )
            message = _open_verification_failure_message(verification, no_browser=no_browser)
            _append_event(
                "workbench.open.verification_failed",
                _open_verification_event_payload(
                    verification,
                    no_browser=no_browser,
                    message=message,
                    command_id=command_id,
                    launcher_result=result,
                )
                | {"attempts": verification_attempts},
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.open.verification_succeeded",
            _open_verification_event_payload(
                verification,
                no_browser=no_browser,
                command_id=command_id,
            )
            | {"attempts": verification_attempts},
        )
        stable_backup = self._queue_stable_backup_after_successful_open(
            command_id=command_id,
            reason="launcher_open_success",
        )
        return self._finish_successful_open_command(
            command_id,
            message="Workbench opened.",
            verification=verification,
            stable_backup=stable_backup,
            lifecycle_timings_ms=lifecycle_timings_ms,
        )

    def _try_fast_close_workbench(
        self,
        *,
        command_id: str,
        initial_observation: dict[str, Any],
    ) -> dict[str, Any]:
        timings_ms: dict[str, Any] = {}
        started_at = time.monotonic()
        _append_event(
            "workbench.close.fast_path_requested",
            _close_verification_event_payload(initial_observation, command_id=command_id)
            | {
                "closeStrategy": "runtime_manager_fast_path",
            },
        )
        try:
            cleanup_started = time.monotonic()
            cleanup_result = self._force_cleanup_workbench_processes(initial_observation)
            timings_ms["fast_cleanup_ms"] = _elapsed_monotonic_ms(cleanup_started)
        except Exception as exc:
            timings_ms["fast_close_path_ms"] = _elapsed_monotonic_ms(started_at)
            payload = _close_verification_event_payload(initial_observation, command_id=command_id) | {
                "closeStrategy": "runtime_manager_fast_path",
                "fallbackReason": "cleanup_exception",
                "errorType": type(exc).__name__,
                "message": str(exc),
                "timingsMs": timings_ms,
            }
            _append_event("workbench.close.fast_path_fallback", payload)
            return {
                "ok": False,
                "fallbackReason": "cleanup_exception",
                "cleanupResult": {},
                "verification": initial_observation,
                "verificationAttempts": 0,
                "timingsMs": timings_ms,
                "errorType": type(exc).__name__,
                "message": str(exc),
            }

        if not bool(cleanup_result.get("supported", True)):
            timings_ms["fast_close_path_ms"] = _elapsed_monotonic_ms(started_at)
            _append_event(
                "workbench.close.fast_path_fallback",
                _close_verification_event_payload(
                    initial_observation,
                    command_id=command_id,
                    cleanup_result=cleanup_result,
                )
                | {
                    "closeStrategy": "runtime_manager_fast_path",
                    "fallbackReason": "process_inventory_unavailable",
                    "timingsMs": timings_ms,
                },
            )
            return {
                "ok": False,
                "fallbackReason": "process_inventory_unavailable",
                "cleanupResult": cleanup_result,
                "verification": initial_observation,
                "verificationAttempts": 0,
                "timingsMs": timings_ms,
            }

        verification_source = "observe_workbench"
        verification_started = time.monotonic()
        if _cleanup_result_confirms_workbench_closed(cleanup_result, initial_observation):
            verification = _closed_observation_from_cleanup_result(initial_observation, cleanup_result)
            closed = True
            verification_attempts = 0
            verification_source = "cleanup_result"
        else:
            closed, verification, verification_attempts = _wait_for_close_verification()
        timings_ms["close_verification_ms"] = _elapsed_monotonic_ms(verification_started)
        timings_ms["close_verification_attempts"] = verification_attempts
        if not closed:
            timings_ms["fast_close_path_ms"] = _elapsed_monotonic_ms(started_at)
            _append_event(
                "workbench.close.fast_path_fallback",
                _close_verification_event_payload(
                    verification,
                    command_id=command_id,
                    cleanup_result=cleanup_result,
                )
                | {
                    "closeStrategy": "runtime_manager_fast_path",
                    "fallbackReason": "verification_failed",
                    "attempts": verification_attempts,
                    "verificationSource": verification_source,
                    "timingsMs": timings_ms,
                },
            )
            return {
                "ok": False,
                "fallbackReason": "verification_failed",
                "cleanupResult": cleanup_result,
                "verification": verification,
                "verificationAttempts": verification_attempts,
                "timingsMs": timings_ms,
            }

        state_cleanup_started = time.monotonic()
        try:
            state_cleanup = clear_workbench_launcher_state_after_close()
        except Exception as exc:
            state_cleanup = {
                "ok": False,
                "errorType": type(exc).__name__,
                "message": str(exc),
            }
            _append_event(
                "workbench.close.fast_path_state_cleanup_failed",
                _close_verification_event_payload(
                    verification,
                    command_id=command_id,
                    cleanup_result=cleanup_result,
                )
                | {
                    "closeStrategy": "runtime_manager_fast_path",
                    "stateCleanup": state_cleanup,
                },
            )
        timings_ms["launcher_state_cleanup_ms"] = _elapsed_monotonic_ms(state_cleanup_started)
        timings_ms["fast_close_path_ms"] = _elapsed_monotonic_ms(started_at)
        _append_event(
            "workbench.close.fast_path_succeeded",
            _close_verification_event_payload(
                verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
            )
            | {
                "closeStrategy": "runtime_manager_fast_path",
                "attempts": verification_attempts,
                "verificationSource": verification_source,
                "stateCleanup": state_cleanup,
                "timingsMs": timings_ms,
            },
        )
        return {
            "ok": True,
            "fallbackReason": "",
            "cleanupResult": cleanup_result,
            "verification": verification,
            "verificationAttempts": verification_attempts,
            "verificationSource": verification_source,
            "timingsMs": timings_ms,
            "stateCleanup": state_cleanup,
        }

    def _close_workbench_with_fast_path(
        self,
        *,
        command_id: str,
        initial_observation: dict[str, Any],
        launcher_failure_message: str,
    ) -> dict[str, Any]:
        lifecycle_timings_ms: dict[str, Any] = {}
        fast_close = self._try_fast_close_workbench(
            command_id=command_id,
            initial_observation=initial_observation,
        )
        lifecycle_timings_ms.update(fast_close.get("timingsMs") if isinstance(fast_close.get("timingsMs"), dict) else {})
        if bool(fast_close.get("ok")):
            return {
                "closeStrategy": "runtime_manager_fast_path",
                "cleanupResult": fast_close.get("cleanupResult") if isinstance(fast_close.get("cleanupResult"), dict) else {},
                "verification": fast_close.get("verification") if isinstance(fast_close.get("verification"), dict) else {},
                "verificationAttempts": int(fast_close.get("verificationAttempts") or 0),
                "launcherResult": None,
                "lifecycleTimingsMs": lifecycle_timings_ms,
                "fastClose": fast_close,
                "stateCleanup": fast_close.get("stateCleanup") if isinstance(fast_close.get("stateCleanup"), dict) else {},
            }

        fallback_reason = str(fast_close.get("fallbackReason") or "fast_path_failed")
        launcher_started = time.monotonic()
        result = close_workbench()
        lifecycle_timings_ms["launcher_action_ms"] = _elapsed_monotonic_ms(launcher_started)
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, launcher_failure_message))
        cleanup_started = time.monotonic()
        cleanup_result = self._cleanup_residual_workbench_processes()
        lifecycle_timings_ms["residual_cleanup_ms"] = _elapsed_monotonic_ms(cleanup_started)
        verification_started = time.monotonic()
        closed, verification, verification_attempts = _wait_for_close_verification()
        lifecycle_timings_ms["close_verification_ms"] = _elapsed_monotonic_ms(verification_started)
        lifecycle_timings_ms["close_verification_attempts"] = verification_attempts
        return {
            "closeStrategy": "launcher_internal_stop",
            "fallbackReason": fallback_reason,
            "cleanupResult": cleanup_result,
            "verification": verification,
            "verificationAttempts": verification_attempts,
            "launcherResult": result,
            "lifecycleTimingsMs": lifecycle_timings_ms,
            "fastClose": fast_close,
            "closed": closed,
        }

    def _handle_close_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        blocked = self._block_lifecycle_command_if_active_work(
            command_id=command_id,
            command_type="close_workbench",
            args=args,
        )
        if blocked is not None:
            return blocked

        state = load_state()
        workbench = state.setdefault("workbench", {})
        observation = _observe_workbench_for_close()
        if _close_request_already_satisfied(observation) and str(workbench.get("phase") or "") != "failed":
            closed_runs = _close_active_evolution_runs_for_shutdown()
            workbench["desiredState"] = "closed"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state, observation=observation))
            cleanup_result = {"supported": True, "requested": [], "terminated": [], "remaining": [], "skipped": "already_closed_no_residual"}
            if bool(args.get("stopManager")) or _closed_observation_has_residual_evidence(observation):
                cleanup_result = self._cleanup_residual_workbench_processes()
            launcher_state_cleanup = _clear_launcher_state_after_verified_close(
                observation,
                command_id=command_id,
                cleanup_result=cleanup_result,
                event_type="workbench.close.already_satisfied_state_cleanup",
            )
            reopen_intent = _claim_workbench_reopen_intent() if bool(args.get("stopManager")) else None
            if bool(args.get("stopManager")):
                if reopen_intent:
                    _append_event(
                        "workbench.reopen_after_close.claimed",
                        _workbench_reopen_intent_event_payload(reopen_intent, command_id=command_id),
                    )
                else:
                    _append_event("daemon.stop_requested", {"commandId": command_id, "reason": "close_workbench"})
            return self._finish_command(
                command_id,
                ok=True,
                message="Workbench is already closed.",
                result_data={
                    "residualCleanup": cleanup_result,
                    "closedEvolutionRuns": closed_runs,
                    "stopDaemon": bool(args.get("stopManager")) and not bool(reopen_intent),
                    "runDeferredWorkbenchOpen": bool(reopen_intent),
                    "restartIntent": reopen_intent or {},
                    "launcherStateCleanup": launcher_state_cleanup,
                },
                reconcile_observation=observation,
            )

        closed_runs = _close_active_evolution_runs_for_shutdown()
        workbench.update(
            {
                "desiredState": "closed",
                "phase": "closing",
                "lastReason": str(args.get("reason") or "explicit_close"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state, observation=observation))
        close_outcome = self._close_workbench_with_fast_path(
            command_id=command_id,
            initial_observation=observation,
            launcher_failure_message="Closing the workbench failed.",
        )
        cleanup_result = close_outcome["cleanupResult"]
        verification = close_outcome["verification"]
        verification_attempts = int(close_outcome["verificationAttempts"])
        lifecycle_timings_ms = close_outcome["lifecycleTimingsMs"]
        launcher_result = close_outcome.get("launcherResult")
        close_strategy = str(close_outcome.get("closeStrategy") or "")
        closed = bool(close_outcome.get("closed", True))
        if not closed:
            message = _close_verification_failure_message(verification)
            _append_event(
                "workbench.close.verification_failed",
                _close_verification_event_payload(
                    verification,
                    command_id=command_id,
                    message=message,
                    cleanup_result=cleanup_result,
                    launcher_result=launcher_result,
                )
                | {
                    "attempts": verification_attempts,
                    "closeStrategy": close_strategy,
                    "fastClose": close_outcome.get("fastClose") if isinstance(close_outcome.get("fastClose"), dict) else {},
                },
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.close.verification_succeeded",
            _close_verification_event_payload(
                verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
                launcher_result=launcher_result,
            )
            | {
                "attempts": verification_attempts,
                "closeStrategy": close_strategy,
                "fastClose": close_outcome.get("fastClose") if isinstance(close_outcome.get("fastClose"), dict) else {},
            },
        )
        launcher_state_cleanup = close_outcome.get("stateCleanup") if isinstance(close_outcome.get("stateCleanup"), dict) else {}
        if not launcher_state_cleanup:
            launcher_state_cleanup = _clear_launcher_state_after_verified_close(
                verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
                event_type="workbench.close.launcher_state_cleanup",
            )
        reopen_intent = _claim_workbench_reopen_intent() if bool(args.get("stopManager")) else None
        final_result = self._finish_command(
            command_id,
            ok=True,
            message="Workbench closed.",
            result_data={
                "residualCleanup": cleanup_result,
                "closedEvolutionRuns": closed_runs,
                "stopDaemon": bool(args.get("stopManager")) and not bool(reopen_intent),
                "runDeferredWorkbenchOpen": bool(reopen_intent),
                "restartIntent": reopen_intent or {},
                "lifecycleTimingsMs": lifecycle_timings_ms,
                "closeStrategy": close_strategy,
                "launcherStateCleanup": launcher_state_cleanup,
            },
            reconcile_observation=verification,
        )
        if bool(args.get("stopManager")):
            if reopen_intent:
                _append_event(
                    "workbench.reopen_after_close.claimed",
                    _workbench_reopen_intent_event_payload(reopen_intent, command_id=command_id),
                )
            else:
                _append_event("daemon.stop_requested", {"commandId": command_id, "reason": "close_workbench"})
        return final_result

    def _handle_force_close_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        reason = str(args.get("reason") or "explicit_force_close").strip() or "explicit_force_close"
        source = str(args.get("source") or "").strip()
        state = load_state()
        workbench = state.setdefault("workbench", {})
        initial_observation = _observe_workbench_for_close()
        already_satisfied = _close_request_already_satisfied(initial_observation) and not _closed_observation_has_residual_evidence(
            initial_observation
        )
        active_work_runs = _persistent_active_work_run_snapshots()
        closed_runs = _close_active_evolution_runs_for_shutdown()
        force_stopped_runs = _mark_persistent_active_work_runs_force_stopped(reason)

        workbench.update(
            {
                "desiredState": "closed",
                "phase": "steady" if already_satisfied else "force_stopping",
                "lastReason": reason,
                "lastSource": source,
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state, observation=initial_observation))
        _append_event(
            "workbench.force_close.requested",
            _close_verification_event_payload(
                initial_observation,
                command_id=command_id,
                message="Force close requested for the managed workbench.",
            )
            | {
                "reason": reason,
                "source": source,
                "alreadySatisfied": already_satisfied,
                "activeWorkCount": len(active_work_runs),
                "activeWorkRuns": [
                    {
                        "kind": str(item.get("runKind") or item.get("kind") or ""),
                        "runId": str(item.get("runId") or item.get("roundId") or item.get("sessionId") or ""),
                        "status": str(item.get("status") or item.get("currentPhase") or ""),
                        "sessionId": str(item.get("sessionId") or ""),
                    }
                    for item in active_work_runs[:8]
                    if isinstance(item, dict)
                ],
            },
        )
        if already_satisfied:
            cleanup_result = {
                "supported": True,
                "requested": [],
                "terminated": [],
                "remaining": [],
                "skipped": "already_closed_no_residual",
            }
            launcher_state_cleanup = _clear_launcher_state_after_verified_close(
                initial_observation,
                command_id=command_id,
                cleanup_result=cleanup_result,
                event_type="workbench.force_close.already_satisfied_state_cleanup",
            )
            _append_event(
                "workbench.force_close.already_satisfied",
                _close_verification_event_payload(
                    initial_observation,
                    command_id=command_id,
                    message="Force close skipped process cleanup because the workbench was already closed.",
                    cleanup_result=cleanup_result,
                )
                | {"attempts": 0},
            )
            return self._finish_command(
                command_id,
                ok=True,
                message="Workbench is already closed.",
                result_data={
                    "residualCleanup": cleanup_result,
                    "closedEvolutionRuns": closed_runs,
                    "forceStoppedWorkRuns": force_stopped_runs,
                    "alreadySatisfied": True,
                    "launcherStateCleanup": launcher_state_cleanup,
                },
                reconcile_observation=initial_observation,
            )

        cleanup_result = self._force_cleanup_workbench_processes(initial_observation)
        closed, verification, verification_attempts = _wait_for_close_verification()
        if not closed:
            cleanup_retry_result = self._force_cleanup_workbench_processes(verification)
            closed, verification, retry_attempts = _wait_for_close_verification()
            verification_attempts += retry_attempts
            cleanup_result = {
                "first": cleanup_result,
                "retry": cleanup_retry_result,
            }

        if not closed:
            message = _close_verification_failure_message(verification)
            _append_event(
                "workbench.force_close.verification_failed",
                _close_verification_event_payload(
                    verification,
                    command_id=command_id,
                    message=message,
                    cleanup_result=cleanup_result,
                )
                | {"attempts": verification_attempts},
            )
            return self._finish_command(
                command_id,
                ok=False,
                message=message,
                error_scope="force_close_workbench",
                failure_message=message,
                error_type="ForceCloseVerificationFailed",
                result_data={
                    "residualCleanup": cleanup_result,
                    "closedEvolutionRuns": closed_runs,
                    "forceStoppedWorkRuns": force_stopped_runs,
                },
            )

        _append_event(
            "workbench.force_close.verification_succeeded",
            _close_verification_event_payload(
                verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
            )
            | {"attempts": verification_attempts},
        )
        state = load_state()
        workbench = state.setdefault("workbench", {})
        workbench.update(
            {
                "desiredState": "closed",
                "phase": "steady",
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state, observation=verification))
        launcher_state_cleanup = _clear_launcher_state_after_verified_close(
            verification,
            command_id=command_id,
            cleanup_result=cleanup_result,
            event_type="workbench.force_close.launcher_state_cleanup",
        )
        return self._finish_command(
            command_id,
            ok=True,
            message="Workbench force closed.",
            result_data={
                "residualCleanup": cleanup_result,
                "closedEvolutionRuns": closed_runs,
                "forceStoppedWorkRuns": force_stopped_runs,
                "launcherStateCleanup": launcher_state_cleanup,
            },
            reconcile_observation=verification,
        )

    def _run_deferred_workbench_open(self, result: dict[str, Any]) -> None:
        intent = result.get("restartIntent") if isinstance(result.get("restartIntent"), dict) else {}
        intent_id = str(intent.get("intentId") or "").strip()
        payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
        command_id = str(intent.get("sourceCommandId") or intent_id or "deferred-open").strip()
        try:
            _append_event(
                "workbench.reopen_after_close.started",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id),
            )
            open_result = self._handle_open_workbench(
                command_id=command_id,
                args={
                    "reason": "reopen_after_close",
                    "noBrowser": bool(payload.get("noBrowser")),
                    "source": "restart_coordinator",
                },
            )
            if intent_id:
                complete_restart_intent(intent_id, status="completed", message=str(open_result.get("message") or "Workbench reopened."))
            _append_event(
                "workbench.reopen_after_close.completed",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id)
                | {"ok": bool(open_result.get("ok")), "message": str(open_result.get("message") or "")},
            )
        except Exception as exc:
            if intent_id:
                complete_restart_intent(intent_id, status="failed", message=f"{type(exc).__name__}: {exc}")
            _append_event(
                "workbench.reopen_after_close.failed",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id)
                | {"errorType": type(exc).__name__, "message": str(exc)},
            )

    def _cleanup_residual_workbench_processes(self) -> dict[str, Any]:
        return terminate_unmanaged_workbench_processes(
            project_root=PROJECT_ROOT,
            exclude_pids=_snapshot_residual_excluded_pids(observe_workbench(), self._pid, include_workbench=False),
        )

    def _force_cleanup_workbench_processes(self, observation: dict[str, Any] | None = None) -> dict[str, Any]:
        observed = observation if isinstance(observation, dict) else observe_workbench()
        return terminate_workbench_processes(
            project_root=PROJECT_ROOT,
            browser_profile_dir=str(observed.get("browserProfileDir") or ""),
            exclude_pids={os.getpid(), self._pid},
            timeout_seconds=_FAST_CLOSE_PROCESS_TERMINATE_TIMEOUT_SECONDS,
            verify_remaining_with_inventory=False,
        )

    def _perform_restart_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        requested_no_browser = bool(args.get("noBrowser"))
        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_restart"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        state = save_state(self._reconcile_observation(state))
        workbench = state.setdefault("workbench", {})
        effective_no_browser = requested_no_browser
        build_preflight: dict[str, Any] = {}
        lifecycle_timings_ms: dict[str, Any] = {}
        if _restart_should_preflight_frontend_build(workbench, args=args):
            build_preflight_started = time.monotonic()
            build_preflight = _preflight_frontend_build_for_restart(command_id)
            lifecycle_timings_ms["build_preflight_ms"] = _elapsed_monotonic_ms(build_preflight_started)
        if requested_no_browser and _restart_should_preserve_visible_browser(workbench):
            effective_no_browser = False
            _append_event(
                "workbench.restart.no_browser_overridden",
                {
                    "commandId": command_id,
                    "requestedNoBrowser": True,
                    "effectiveNoBrowser": False,
                    "reason": "preserve_existing_managed_browser_window",
                    "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
                    "browserManaged": bool(workbench.get("browserManaged")),
                    "browserWindowAlive": bool(workbench.get("browserWindowAlive")),
                    "requestedReason": str(args.get("reason") or ""),
                    "requestedSource": str(args.get("source") or ""),
                },
            )
        close_outcome = self._close_workbench_with_fast_path(
            command_id=command_id,
            initial_observation=observe_workbench(),
            launcher_failure_message="Closing the workbench for restart failed.",
        )
        lifecycle_timings_ms.update(
            close_outcome.get("lifecycleTimingsMs") if isinstance(close_outcome.get("lifecycleTimingsMs"), dict) else {}
        )
        cleanup_result = close_outcome["cleanupResult"]
        close_verification = close_outcome["verification"]
        close_attempts = int(close_outcome["verificationAttempts"])
        close_result = close_outcome.get("launcherResult")
        close_strategy = str(close_outcome.get("closeStrategy") or "")
        closed = bool(close_outcome.get("closed", True))
        if not closed:
            message = _close_verification_failure_message(close_verification)
            _append_event(
                "workbench.restart.close_verification_failed",
                _close_verification_event_payload(
                    close_verification,
                    command_id=command_id,
                    message=message,
                    cleanup_result=cleanup_result,
                    launcher_result=close_result,
                )
                | {
                    "attempts": close_attempts,
                    "closeStrategy": close_strategy,
                    "fastClose": close_outcome.get("fastClose") if isinstance(close_outcome.get("fastClose"), dict) else {},
                },
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.restart.close_verification_succeeded",
            _close_verification_event_payload(
                close_verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
                launcher_result=close_result,
            )
            | {
                "attempts": close_attempts,
                "closeStrategy": close_strategy,
                "fastClose": close_outcome.get("fastClose") if isinstance(close_outcome.get("fastClose"), dict) else {},
            },
        )
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt:
            return {
                "residualCleanup": cleanup_result,
                "requestedNoBrowser": requested_no_browser,
                "effectiveNoBrowser": effective_no_browser,
                "buildPreflight": build_preflight,
                "lifecycleTimingsMs": lifecycle_timings_ms,
                "closeStrategy": close_strategy,
                "interruptedByClose": True,
                "interrupt": interrupt,
                "interruptStage": "after_close_before_open",
            }

        state = load_state()
        workbench = state.setdefault("workbench", {})
        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_restart"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        cancel_check = _lifecycle_interrupt_cancel_check(command_id)
        open_launcher_started = time.monotonic()
        open_result = open_workbench(no_browser=effective_no_browser, cancel_check=cancel_check)
        lifecycle_timings_ms["open_launcher_action_ms"] = _elapsed_monotonic_ms(open_launcher_started)
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt or int(open_result.returncode or 0) == LAUNCHER_ACTION_CANCELLED_RETURN_CODE:
            return {
                "residualCleanup": cleanup_result,
                "requestedNoBrowser": requested_no_browser,
                "effectiveNoBrowser": effective_no_browser,
                "buildPreflight": build_preflight,
                "lifecycleTimingsMs": lifecycle_timings_ms,
                "closeStrategy": close_strategy,
                "interruptedByClose": True,
                "interrupt": interrupt,
                "interruptStage": "restart_open_launcher",
                "launcherResult": open_result,
            }
        if open_result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(open_result, "Opening the workbench for restart failed."))
        open_verification_started = time.monotonic()
        ready, open_verification, open_attempts = _wait_for_open_verification(no_browser=effective_no_browser, cancel_check=cancel_check)
        lifecycle_timings_ms["open_verification_ms"] = _elapsed_monotonic_ms(open_verification_started)
        lifecycle_timings_ms["open_verification_attempts"] = open_attempts
        interrupt = _active_lifecycle_interrupt(command_id)
        if interrupt:
            return {
                "residualCleanup": cleanup_result,
                "requestedNoBrowser": requested_no_browser,
                "effectiveNoBrowser": effective_no_browser,
                "buildPreflight": build_preflight,
                "lifecycleTimingsMs": lifecycle_timings_ms,
                "closeStrategy": close_strategy,
                "interruptedByClose": True,
                "interrupt": interrupt,
                "interruptStage": "restart_open_verification",
                "launcherResult": open_result,
            }
        if not ready:
            message = _open_verification_failure_message(open_verification, no_browser=effective_no_browser)
            _append_event(
                "workbench.restart.open_verification_failed",
                _open_verification_event_payload(
                    open_verification,
                    no_browser=effective_no_browser,
                    message=message,
                    command_id=command_id,
                    launcher_result=open_result,
                )
                | {"attempts": open_attempts},
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.restart.open_verification_succeeded",
            _open_verification_event_payload(
                open_verification,
                no_browser=effective_no_browser,
                command_id=command_id,
                launcher_result=open_result,
            )
            | {"attempts": open_attempts},
        )
        launcher_state_sync = persist_workbench_launcher_state_after_open(
            open_verification,
            last_reason=str(args.get("reason") or "explicit_restart"),
            last_source=str(args.get("source") or "runtime_manager"),
        )
        return {
            "residualCleanup": cleanup_result,
            "requestedNoBrowser": requested_no_browser,
            "effectiveNoBrowser": effective_no_browser,
            "buildPreflight": build_preflight,
            "lifecycleTimingsMs": lifecycle_timings_ms,
            "closeStrategy": close_strategy,
            "launcherStateSync": launcher_state_sync,
        }

    def _handle_restart_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if not bool(args.get("skipActiveWorkGuard")):
            blocked = self._block_lifecycle_command_if_active_work(
                command_id=command_id,
                command_type="restart_workbench",
                args=args,
            )
            if blocked is not None:
                return blocked

        result_data = self._perform_restart_workbench(command_id=command_id, args=args)
        if bool(result_data.get("interruptedByClose")):
            interrupt = result_data.pop("interrupt") if isinstance(result_data.get("interrupt"), dict) else {}
            stage = str(result_data.pop("interruptStage", "") or "restart")
            launcher_result = result_data.pop("launcherResult", None)
            return self._finish_interrupted_lifecycle_command(
                command_id,
                command_type="restart_workbench",
                interrupt=interrupt,
                stage=stage,
                launcher_result=launcher_result,
                extra_result_data=result_data,
            )
        return self._finish_command(
            command_id,
            ok=True,
            message="Workbench restarted.",
            result_data=result_data,
        )

    def _wake_hot_restart_session(
        self,
        *,
        session_id: str,
        message: str,
        command_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        delivery = {
            "wakeRequested": bool(session_id),
            "wakeStatus": "skipped",
            "targetSessionId": str(session_id or "").strip(),
            "turnId": "",
            "reason": "",
        }
        if not session_id:
            delivery["reason"] = "missing_session_id"
            return delivery
        try:
            from core.web.services import session_service

            if session_service._is_session_running(session_id):
                try:
                    session_service.request_stop_session_turn(session_id)
                except Exception:
                    pass

            detail = session_service.submit_session_message(
                session_id,
                message,
                turn_mode="hot_restart_resume",
                write_intent=False,
                message_metadata={
                    "kind": "hot_restart_resume",
                    "commandId": command_id,
                    **(metadata or {}),
                },
                message_source="hot_restart_resume",
                include_started_turn_id=True,
            )
        except Exception as exc:
            delivery["wakeStatus"] = "failed"
            delivery["reason"] = f"{type(exc).__name__}: {exc}"
            _append_event(
                "workbench.hot_restart.session_wake_failed",
                {
                    "commandId": command_id,
                    "sessionId": session_id,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                },
            )
            return delivery
        delivery["wakeStatus"] = "delivered"
        delivery["turnId"] = str((detail or {}).get("startedTurnId") or "")
        _append_event(
            "workbench.hot_restart.session_wake_delivered",
            {
                "commandId": command_id,
                "sessionId": session_id,
                "turnId": delivery["turnId"],
            },
        )
        return delivery

    def _handle_hot_restart_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        hot_restart = args.get("hotRestart") if isinstance(args.get("hotRestart"), dict) else {}
        requester = _hot_restart_requester_fields(args)
        session_id = requester["sessionId"]
        run_id = requester["runId"]
        reason = str(args.get("reason") or hot_restart.get("reason") or "agent_hot_restart").strip() or "agent_hot_restart"
        if not session_id:
            return self._finish_command(
                command_id,
                ok=False,
                message="Hot restart requires sessionId.",
                error_scope="hot_restart_workbench",
                failure_message="Hot restart requires sessionId.",
                error_type="HotRestartSessionRequired",
            )

        blocked = self._block_lifecycle_command_if_active_work(
            command_id=command_id,
            command_type="hot_restart_workbench",
            args=args,
        )
        if blocked is not None:
            return blocked

        backup = latest_stable_backup()
        if not backup:
            try:
                backup = create_stable_backup(reason="pre_hot_restart_seed", command_id=command_id)
            except Exception as exc:
                return self._finish_command(
                    command_id,
                    ok=False,
                    message=f"Hot restart could not create a rollback backup: {exc}",
                    error_scope="hot_restart_workbench",
                    failure_message=str(exc),
                    error_type=type(exc).__name__,
                )

        try:
            restart_data = self._perform_restart_workbench(
                command_id=command_id,
                args={
                    **args,
                    "reason": reason,
                    "source": "agent_hot_restart",
                    "noBrowser": bool(args.get("noBrowser")),
                    "skipActiveWorkGuard": True,
                },
            )
            restart_result = {"ok": True, "message": "Workbench restarted.", **restart_data}
        except Exception as exc:
            restart_result = {
                "ok": False,
                "message": str(exc),
                "errorType": type(exc).__name__,
            }
        if bool(restart_result.get("ok")):
            try:
                stable_backup = create_stable_backup(reason="hot_restart_success", command_id=command_id)
            except Exception as exc:
                stable_backup = {"errorType": type(exc).__name__, "message": str(exc)}
                _append_event(
                    "workbench.hot_restart.stable_backup_failed",
                    {"commandId": command_id, "errorType": type(exc).__name__, "message": str(exc)},
                )
            delivery = self._wake_hot_restart_session(
                session_id=session_id,
                command_id=command_id,
                message=str(
                    hot_restart.get("resumeMessage")
                    or "热重启已完成。请继续完成当前任务的验证、记忆同步和收口。"
                ),
                metadata={
                    "hotRestartStatus": "completed",
                    "stableBackupId": str((stable_backup or {}).get("backupId") or ""),
                    "runId": run_id,
                },
            )
            if delivery.get("wakeStatus") == "delivered":
                return self._finish_command(
                    command_id,
                    ok=True,
                    message="Hot restart completed and the requester session was awakened.",
                    result_data={
                        "hotRestart": {
                            "status": "completed",
                            "sessionId": session_id,
                            "runId": run_id,
                            "stableBackup": stable_backup,
                            "delivery": delivery,
                            "restartResult": restart_result,
                        }
                    },
                )
            failure = create_failure_package(
                reason=reason,
                command_id=command_id,
                session_id=session_id,
                run_id=run_id,
                failure_stage="session_wake",
                error_type="HotRestartWakeFailed",
                error_message=str(delivery.get("reason") or "session wake failed"),
                runtime_result=restart_result,
            )
            return self._rollback_after_hot_restart_failure(
                command_id=command_id,
                args=args,
                session_id=session_id,
                run_id=run_id,
                reason=reason,
                backup=backup,
                failure=failure,
                error_type="HotRestartWakeFailed",
                error_message=str(delivery.get("reason") or "session wake failed"),
            )

        failure = create_failure_package(
            reason=reason,
            command_id=command_id,
            session_id=session_id,
            run_id=run_id,
            failure_stage="restart",
            error_type=str(restart_result.get("errorType") or "HotRestartFailed"),
            error_message=str(restart_result.get("message") or "hot restart failed"),
            runtime_result=restart_result,
        )
        return self._rollback_after_hot_restart_failure(
            command_id=command_id,
            args=args,
            session_id=session_id,
            run_id=run_id,
            reason=reason,
            backup=backup,
            failure=failure,
            error_type=str(restart_result.get("errorType") or "HotRestartFailed"),
            error_message=str(restart_result.get("message") or "hot restart failed"),
        )

    def _rollback_after_hot_restart_failure(
        self,
        *,
        command_id: str,
        args: dict[str, Any],
        session_id: str,
        run_id: str,
        reason: str,
        backup: dict[str, Any],
        failure: dict[str, Any],
        error_type: str,
        error_message: str,
    ) -> dict[str, Any]:
        try:
            rollback = restore_stable_backup(backup)
            _append_event(
                "workbench.hot_restart.rollback_restored",
                {
                    "commandId": command_id,
                    "backupId": rollback.get("backupId"),
                    "failurePackageId": failure.get("packageId"),
                },
            )
        except Exception as exc:
            rollback = {"status": "failed", "errorType": type(exc).__name__, "message": str(exc)}
            return self._finish_command(
                command_id,
                ok=False,
                message=f"Hot restart failed and rollback failed: {exc}",
                error_scope="hot_restart_workbench",
                failure_message=str(exc),
                error_type=type(exc).__name__,
                result_data={
                    "hotRestart": {
                        "status": "rollback_failed",
                        "sessionId": session_id,
                        "runId": run_id,
                        "failurePackage": failure,
                        "rollback": rollback,
                    }
                },
            )

        try:
            recovery_data = self._perform_restart_workbench(
                command_id=command_id,
                args={
                    **args,
                    "reason": f"rollback_after_hot_restart_failure: {reason}",
                    "source": "agent_hot_restart_rollback",
                    "noBrowser": bool(args.get("noBrowser")),
                    "skipActiveWorkGuard": True,
                },
            )
            recovery_result = {"ok": True, "message": "Workbench restarted after rollback.", **recovery_data}
        except Exception as exc:
            recovery_result = {"ok": False, "message": str(exc), "errorType": type(exc).__name__}
        delivery = self._wake_hot_restart_session(
            session_id=session_id,
            command_id=command_id,
            message=(
                "热重启失败，已回滚。失败现场已保存，请根据最新日志和失败现场包分析问题。\n"
                f"- failurePackageId: {failure.get('packageId')}\n"
                f"- failureStage: {failure.get('failureStage')}\n"
                f"- error: {error_type}: {error_message}"
            ),
            metadata={
                "hotRestartStatus": "rolled_back",
                "failurePackageId": str(failure.get("packageId") or ""),
                "restoredBackupId": str(rollback.get("backupId") or ""),
                "runId": run_id,
            },
        )
        return self._finish_command(
            command_id,
            ok=False,
            message="Hot restart failed; rollback was applied.",
            error_scope="hot_restart_workbench",
            failure_message=str(error_message or "hot restart failed"),
            error_type=str(error_type or "HotRestartFailed"),
            result_data={
                "hotRestart": {
                    "status": "rolled_back",
                    "sessionId": session_id,
                    "runId": run_id,
                    "rollback": rollback,
                    "failurePackage": failure,
                    "recoveryRestart": recovery_result,
                    "delivery": delivery,
                }
            },
        )

    def _handle_toggle_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        observed_state = str(state.setdefault("workbench", {}).get("observedState") or "closed").strip() or "closed"
        if observed_state == "open":
            blocked = self._block_lifecycle_command_if_active_work(
                command_id=command_id,
                command_type="toggle_workbench",
                args=args,
            )
            if blocked is not None:
                return blocked
            return self._handle_close_workbench(command_id=command_id, args=args)
        return self._handle_open_workbench(command_id=command_id, args=args)

    def _handle_start_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = self_evolution_control_service._LOCAL_START_SELF_EVOLUTION_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run started.",
            result_data={"runId": str(snapshot.get("runId") or ""), "snapshot": snapshot},
        )

    def _handle_pause_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_RESUME_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_restart_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        reason = str(args.get("reason") or payload.get("reason") or "self_evolution_restart").strip() or "self_evolution_restart"
        intent = self_evolution_control_service._LOCAL_REQUEST_SELF_EVOLUTION_RESTART(run_id=run_id, reason=reason)
        snapshot = intent.get("snapshot") if isinstance(intent.get("snapshot"), dict) else {}
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution restart requested.",
            result_data={
                "runId": str(snapshot.get("runId") or run_id),
                "snapshot": snapshot,
                "restartIntent": {key: value for key, value in intent.items() if key != "snapshot"},
            },
        )

    def _handle_start_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        freshness = _require_fresh_source_for_supervised_run()
        llm_key_env_sync = _sync_llm_key_env_from_persisted_user_env(command_type="start_supervised_run")
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = supervised_control_service._LOCAL_START_SUPERVISED_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run started.",
            result_data={
                "runId": str(snapshot.get("runId") or ""),
                "snapshot": snapshot,
                "sourceFreshness": freshness,
                "llmKeyEnvSync": llm_key_env_sync,
            },
        )

    def _handle_retry_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        freshness = _require_fresh_source_for_supervised_run()
        llm_key_env_sync = _sync_llm_key_env_from_persisted_user_env(command_type="retry_supervised_run")
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_RETRY_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run retry started.",
            result_data={
                "runId": str(snapshot.get("runId") or ""),
                "snapshot": snapshot,
                "sourceFreshness": freshness,
                "llmKeyEnvSync": llm_key_env_sync,
            },
        )

    def _handle_pause_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_RESUME_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_STOP_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_delete_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        result = supervised_control_service._LOCAL_DELETE_SUPERVISED_RUN_SNAPSHOT(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run record deleted.",
            result_data={"runId": run_id, "deleteResult": result},
        )


def run_daemon() -> None:
    RuntimeManagerDaemon().run_forever()
