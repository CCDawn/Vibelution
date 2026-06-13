"""Runtime summary helpers for the web shell."""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import threading
import time

from config.public_config import load_public_config
from config import get_config
from core.infrastructure.mental_model import get_mental_model
from core.mental_model_flags import is_mental_model_enabled
from core.runtime_manager import ensure_daemon_running, submit_command
from core.runtime_manager import work_run_store
from core.runtime_manager.evolution_store import (
    load_active_run_snapshot as load_evolution_active_run_snapshot,
    load_latest_run_snapshot as load_evolution_latest_run_snapshot,
)
from core.runtime_manager.state_store import load_state as load_runtime_manager_state
from core.runtime_manager.work_run_leases import leases_for_snapshot

from .i18n import get_web_language, text_for
from .avatar_image_service import avatar_image_url
from .runtime_manager_control_service import current_runtime_manager_pid
from .session_service import (
    get_active_session_summary,
    list_active_session_work_runs,
    load_chat_turn_work_run_summary,
    request_stop_session_turn,
)
from .runtime_scene_service import record_runtime_scene_event
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_STATE_PATH = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
LAUNCHER_SHUTDOWN_LOG_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "shutdown-request.log"
RUNNING_SESSION_PHASES = {"running", "stopping"}


class RuntimeRestartActiveWorkBlocked(Exception):
    """Raised when a restart would interrupt active work."""

    def __init__(self, message: str, active_work_runs: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.message = message
        self.active_work_runs = active_work_runs


def get_runtime_summary() -> dict:
    """Return a light runtime summary for the global shell."""

    runtime_profile = "safe_local"
    model_ref = "unconfigured"
    model_source = "fallback"
    profile_source = "fallback"
    lang = get_web_language()
    public_config: dict | None = None
    contract = {
        "defaultMode": "chat",
        "defaultRoute": "/chat",
        "intakeMode": "manual_review",
        "modeAvailability": {
            "chat": True,
            "self_evolution": True,
            "supervised_evolution": True,
        },
        "domainAvailability": {
            "chat": True,
            "evolution": True,
            "config": True,
        },
    }
    try:
        public_config = load_public_config()
        contract = get_workbench_contract(public_config)
        runtime_profile = public_config.get("runtime", {}).get("profile", runtime_profile)
        llm_profiles = public_config.get("llm", {}).get("profiles", {})
        primary_profile = llm_profiles.get("primary", {})
        model_ref = primary_profile.get("model_ref") or primary_profile.get("model", model_ref)
        model_source = "public_config_primary"
        profile_source = "public_config_runtime"
    except Exception:
        pass

    active_session = get_active_session_summary() or {}
    model_identity = _safe_active_session_model_identity(active_session)
    if model_identity.get("model"):
        model_ref = str(model_identity.get("model") or "").strip()
        model_source = str(model_identity.get("modelSource") or "").strip() or "active_session_agent"
    if model_identity.get("profile"):
        runtime_profile = str(model_identity.get("profile") or "").strip()
        profile_source = str(model_identity.get("profileSource") or "").strip() or "active_session_agent"
    runtime_state = _load_runtime_state()
    current_phase = str(active_session.get("currentPhase") or "").strip().lower()
    status = _derive_web_status(current_phase, runtime_state)
    session_state = _derive_session_state(lang, active_session, runtime_state)
    active_tools = _active_tools(active_session, runtime_state)
    context_usage = _context_usage(runtime_state)
    context_compression = _context_compression_summary(runtime_state, context_usage)
    runtime_manager = _load_runtime_manager_snapshot()
    work_runs = _work_run_summary()
    workbench = _workbench_payload(lang, runtime_manager)
    lifecycle_proof = _runtime_lifecycle_proof(lang, runtime_manager, workbench, work_runs)
    user_profile = _user_profile_payload(public_config)
    task_summary = (
        active_session.get("taskSummary")
        or text_for(
            lang,
            zh="等待新的任务进入工作台",
            en="Waiting for the next task to enter the workbench",
        )
    )
    session_updated_at = str(
        active_session.get("updatedAt")
        or active_session.get("lastActive")
        or runtime_state.get("updated_at")
        or ""
    ).strip()

    return {
        "status": status,
        "mode": contract["defaultMode"],
        "model": model_ref,
        "profile": runtime_profile,
        "modelSource": model_source,
        "profileSource": profile_source,
        "modelId": str(model_identity.get("modelId") or "").strip(),
        "modelAgentId": str(model_identity.get("agentId") or "").strip(),
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "agentName": "Vibelution",
        "userName": _display_user_name(public_config),
        "userProfile": user_profile,
        "agentStatusLine": _agent_status_line(lang, status, current_phase),
        "sessionTitle": active_session.get("title")
        or text_for(lang, zh="网页工作台 Shell", en="Web workbench shell"),
        "taskSummary": task_summary,
        "currentPhase": current_phase or "idle",
        "sessionState": session_state["state"],
        "sessionStateLine": session_state["line"],
        "sessionNeedsResponse": session_state["needs_response"],
        "sessionToolName": session_state["tool_name"],
        "sessionUpdatedAt": session_updated_at,
        "mentalState": _mental_state_summary(lang, public_config=public_config),
        "contextUsage": context_usage,
        "contextCompression": context_compression,
        "activeTools": active_tools,
        "changedFilesCount": len(active_session.get("changedFiles") or []),
        "recentAction": _recent_action(lang, active_session, runtime_state),
        "runtimeManager": {
            "running": bool(runtime_manager.get("daemonRunning")),
            "runtimeState": str(runtime_manager.get("runtimeState") or "idle"),
            "managerPid": int(runtime_manager.get("managerPid") or 0),
            "stateVersion": int(runtime_manager.get("stateVersion") or 0),
        },
        "workbench": workbench,
        "workRuns": work_runs,
        "lifecycleProof": lifecycle_proof,
    }


def request_runtime_shutdown() -> dict[str, object]:
    """Request the local workbench backend to stop."""

    lang = get_web_language()
    active_work_runs = _restart_guard_active_work_runs()
    _record_shutdown_event(
        "runtime.shutdown.requested",
        message="Runtime shutdown requested from web UI.",
        fields={
            "source": "web_ui",
            "activeWorkCount": len(active_work_runs),
            "activeWorkKinds": _active_work_kinds(active_work_runs),
        },
    )
    if active_work_runs:
        message = _lifecycle_active_work_block_message("shutdown", lang)
        _record_shutdown_event(
            "runtime.shutdown.blocked_active_work",
            message="Runtime shutdown blocked by active work.",
            outcome="blocked",
            level="warning",
            fields={
                "source": "web_ui",
                "activeWorkCount": len(active_work_runs),
                "activeWorkKinds": _active_work_kinds(active_work_runs),
                "activeWorkRuns": active_work_runs[:8],
            },
        )
        raise RuntimeRestartActiveWorkBlocked(message, active_work_runs[:8])
    stopped_chat_room_rounds = _stop_active_chat_room_rounds_before_shutdown()
    stopped_chat_turns = _stop_active_chat_turns_before_shutdown()
    stopped_evolution_runs = _stop_active_evolution_runs_before_shutdown()
    if _can_use_managed_launcher_shutdown():
        try:
            ensure_daemon_running()
            submit_command(
                "close_workbench",
                args={"reason": "web_close_button", "source": "web_ui", "stopManager": False},
                requested_by="web_ui",
            )
            _record_shutdown_event(
                "runtime.shutdown.accepted",
                message="Runtime shutdown queued through runtime manager.",
                outcome="accepted",
                fields=_shutdown_event_fields(
                    mode="runtime_manager",
                    stopped_chat_room_rounds=stopped_chat_room_rounds,
                    stopped_chat_turns=stopped_chat_turns,
                    stopped_evolution_runs=stopped_evolution_runs,
                ),
            )
            return {
                "accepted": True,
                "mode": "runtime_manager",
                "message": text_for(
                    lang,
                    zh="正在关闭项目工作台，Launcher 控制器会保持可再次启动。",
                    en="Closing the project workbench. The Launcher controller will stay available for the next start.",
                ),
                "chatTurns": stopped_chat_turns,
                "chatRoomRounds": stopped_chat_room_rounds,
                "evolutionRuns": stopped_evolution_runs,
            }
        except Exception:
            _spawn_managed_launcher_shutdown()
            _record_shutdown_event(
                "runtime.shutdown.accepted",
                message="Runtime shutdown fell back to managed launcher stop.",
                outcome="accepted",
                fields=_shutdown_event_fields(
                    mode="managed_fallback",
                    stopped_chat_room_rounds=stopped_chat_room_rounds,
                    stopped_chat_turns=stopped_chat_turns,
                    stopped_evolution_runs=stopped_evolution_runs,
                ),
            )
            return {
                "accepted": True,
                "mode": "managed_fallback",
                "message": text_for(
                    lang,
                    zh="正在关闭工作台，窗口会在后端停稳后自动关闭。",
                    en="Closing the workbench. The app window will close after the backend stops.",
                ),
                "chatTurns": stopped_chat_turns,
                "chatRoomRounds": stopped_chat_room_rounds,
                "evolutionRuns": stopped_evolution_runs,
            }

    _schedule_local_backend_exit()
    _record_shutdown_event(
        "runtime.shutdown.accepted",
        message="Runtime shutdown scheduled local backend exit.",
        outcome="accepted",
        fields=_shutdown_event_fields(
            mode="local",
            stopped_chat_room_rounds=stopped_chat_room_rounds,
            stopped_chat_turns=stopped_chat_turns,
            stopped_evolution_runs=stopped_evolution_runs,
        ),
    )
    return {
        "accepted": True,
        "mode": "local",
        "message": text_for(
            lang,
            zh="正在关闭本地后端服务。",
            en="Shutting down the local backend.",
        ),
        "chatTurns": stopped_chat_turns,
        "chatRoomRounds": stopped_chat_room_rounds,
        "evolutionRuns": stopped_evolution_runs,
    }


def request_runtime_restart() -> dict[str, object]:
    """Request a managed workbench restart through the runtime manager."""

    lang = get_web_language()
    active_work_runs = _restart_guard_active_work_runs()
    _record_restart_event(
        "runtime.restart.requested",
        message="Runtime restart requested from web UI.",
        fields={
            "source": "web_ui",
            "activeWorkCount": len(active_work_runs),
            "activeWorkKinds": _active_work_kinds(active_work_runs),
        },
    )
    if active_work_runs:
        _record_restart_event(
            "runtime.restart.blocked_active_work",
            message="Runtime restart blocked by active work.",
            outcome="blocked",
            level="warning",
            fields={
                "source": "web_ui",
                "activeWorkCount": len(active_work_runs),
                "activeWorkKinds": _active_work_kinds(active_work_runs),
                "activeWorkRuns": active_work_runs[:8],
            },
        )
        raise RuntimeRestartActiveWorkBlocked(_lifecycle_active_work_block_message("restart", lang), active_work_runs[:8])
    stopped_chat_room_rounds = _stop_active_chat_room_rounds_before_shutdown()
    stopped_chat_turns = _stop_active_chat_turns_before_shutdown()
    stopped_evolution_runs = _stop_active_evolution_runs_before_shutdown()

    try:
        ensure_daemon_running()
        command = submit_command(
            "restart_workbench",
            args={"reason": "web_restart_button", "source": "web_ui", "noBrowser": False},
            requested_by="web_ui",
        )
    except Exception as exc:
        _record_restart_event(
            "runtime.restart.failed",
            message="Runtime restart could not be queued through runtime manager.",
            outcome="failed",
            level="error",
            fields=_restart_event_fields(
                mode="runtime_manager",
                stopped_chat_room_rounds=stopped_chat_room_rounds,
                stopped_chat_turns=stopped_chat_turns,
                stopped_evolution_runs=stopped_evolution_runs,
                active_work_runs=active_work_runs,
            )
            | {"errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_restart_event(
        "runtime.restart.accepted",
        message="Runtime restart queued through runtime manager.",
        outcome="accepted",
        fields=_restart_event_fields(
            mode="runtime_manager",
            stopped_chat_room_rounds=stopped_chat_room_rounds,
            stopped_chat_turns=stopped_chat_turns,
            stopped_evolution_runs=stopped_evolution_runs,
            active_work_runs=active_work_runs,
        )
        | {"commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager",
        "commandId": command_id,
        "message": text_for(
            lang,
            zh="正在安全重启工作台。运行时管理器会先停稳旧后端，再重新拉起前后端。",
            en="Restarting the workbench safely. The runtime manager will stop the old backend before starting it again.",
        ),
        "chatTurns": stopped_chat_turns,
        "chatRoomRounds": stopped_chat_room_rounds,
        "evolutionRuns": stopped_evolution_runs,
    }


def _record_shutdown_event(
    event_code: str,
    *,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "runtime",
            "shutdown",
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _record_restart_event(
    event_code: str,
    *,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "runtime",
            "restart",
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _record_runtime_summary_event(
    event_code: str,
    *,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "runtime",
            "summary",
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _shutdown_event_fields(
    *,
    mode: str,
    stopped_chat_room_rounds: list[dict[str, object]],
    stopped_chat_turns: list[dict[str, object]],
    stopped_evolution_runs: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "source": "web_ui",
        "mode": mode,
        "chatRoomRoundCount": len(stopped_chat_room_rounds),
        "chatTurnCount": len(stopped_chat_turns),
        "evolutionRunCount": len(stopped_evolution_runs),
        "chatRoomRoundStatuses": _status_counts(stopped_chat_room_rounds),
        "chatTurnStatuses": _status_counts(stopped_chat_turns),
        "evolutionRunStatuses": _status_counts(stopped_evolution_runs),
        "evolutionRunKinds": sorted(
            {
                str(item.get("kind") or "").strip()
                for item in stopped_evolution_runs
                if str(item.get("kind") or "").strip()
            }
        ),
    }


def _restart_event_fields(
    *,
    mode: str,
    stopped_chat_room_rounds: list[dict[str, object]],
    stopped_chat_turns: list[dict[str, object]],
    stopped_evolution_runs: list[dict[str, object]],
    active_work_runs: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    active_work_runs = active_work_runs or []
    return {
        "source": "web_ui",
        "mode": mode,
        "activeWorkCount": len(active_work_runs),
        "activeWorkKinds": _active_work_kinds(active_work_runs),
        "chatRoomRoundCount": len(stopped_chat_room_rounds),
        "chatTurnCount": len(stopped_chat_turns),
        "evolutionRunCount": len(stopped_evolution_runs),
        "chatRoomRoundStatuses": _status_counts(stopped_chat_room_rounds),
        "chatTurnStatuses": _status_counts(stopped_chat_turns),
        "evolutionRunStatuses": _status_counts(stopped_evolution_runs),
        "evolutionRunKinds": sorted(
            {
                str(item.get("kind") or "").strip()
                for item in stopped_evolution_runs
                if str(item.get("kind") or "").strip()
            }
        ),
    }


def _status_counts(items: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown").strip() or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _active_work_kinds(items: list[dict[str, str]]) -> list[str]:
    return sorted({str(item.get("kind") or "").strip() for item in items if str(item.get("kind") or "").strip()})


def _lifecycle_active_work_block_message(action: str, lang: str) -> str:
    if action == "restart":
        return text_for(
            lang,
            zh="有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。",
            en="Vibelution cannot restart while work is active. Wait for it to finish or stop the task first.",
        )
    return text_for(
        lang,
        zh="有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。",
        en="Vibelution cannot stop while work is active. Wait for it to finish or stop the task first.",
    )


def _restart_guard_active_work_runs() -> list[dict[str, str]]:
    """Return active work that should block an unconfirmed destructive restart."""

    try:
        active = _active_work_runs(_work_run_summary())
    except Exception:
        active = []
    if active:
        return active

    try:
        chat_runs = list_active_session_work_runs()
    except Exception:
        return []

    guarded: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for run in chat_runs:
        if not isinstance(run, dict):
            continue
        if not _active_work_payload_blocks_lifecycle(run):
            continue
        item = {
            "kind": "chat_turn",
            "runId": str(run.get("runId") or "").strip(),
            "status": str(run.get("status") or run.get("currentPhase") or "").strip(),
            "sessionId": str(run.get("sessionId") or "").strip(),
        }
        key = (item["kind"], item["runId"] or item["sessionId"])
        if key not in seen:
            seen.add(key)
            guarded.append(item)
    return guarded


def _can_use_managed_launcher_shutdown() -> bool:
    return os.name == "nt" and LAUNCHER_SCRIPT_PATH.exists() and LAUNCHER_STATE_PATH.exists()


def _spawn_managed_launcher_shutdown() -> None:
    LAUNCHER_SHUTDOWN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with LAUNCHER_SHUTDOWN_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] requesting managed shutdown\n")
        log_file.flush()
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(LAUNCHER_SCRIPT_PATH),
                "-Action",
                "stop",
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )


def _schedule_local_backend_exit(delay_seconds: float = 0.35) -> None:
    def _exit_later() -> None:
        time.sleep(max(0.0, float(delay_seconds)))
        os._exit(0)

    thread = threading.Thread(target=_exit_later, name="web-runtime-shutdown", daemon=True)
    thread.start()


def _load_runtime_state() -> dict:
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_runtime_manager_snapshot() -> dict:
    """Return a shell-safe runtime-manager summary without live process inventory."""

    try:
        state = load_runtime_manager_state()
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    payload = json.loads(json.dumps(state)) if state else {}
    manager_pid = current_runtime_manager_pid(PROJECT_ROOT)
    payload["daemonRunning"] = manager_pid > 0
    payload["managerPid"] = manager_pid
    payload["runtimeState"] = "running" if manager_pid > 0 else str(payload.get("runtimeState") or "idle")
    payload["projectRoot"] = str(PROJECT_ROOT)
    payload.setdefault("workbench", {})
    payload.setdefault("runtimeManager", {})
    payload.setdefault("residualProcesses", {"count": 0, "items": [], "mode": "not_scanned_for_summary"})
    return payload


def _local_user_name() -> str:
    for key in ("VIBELUTION_USER_NAME", "USERNAME", "USER", "LOGNAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    try:
        return str(getpass.getuser() or "").strip()
    except Exception:
        return ""


def _user_profile_payload(public_config: dict | None) -> dict[str, object]:
    profile = public_config.get("user_profile", {}) if isinstance(public_config, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    preferences = profile.get("preferences") if isinstance(profile.get("preferences"), list) else []
    return {
        "displayName": str(profile.get("display_name") or "").strip(),
        "bio": str(profile.get("bio") or "").strip(),
        "preferences": [str(item).strip() for item in preferences if str(item).strip()],
        "avatarPreset": str(profile.get("avatar_preset") or "default").strip() or "default",
        "avatarImageUrl": avatar_image_url(profile.get("avatar_image_path")),
    }


def _display_user_name(public_config: dict | None) -> str:
    profile = _user_profile_payload(public_config)
    display_name = str(profile.get("displayName") or "").strip()
    return display_name or _local_user_name()


def _safe_active_session_model_identity(active_session: dict) -> dict[str, str]:
    try:
        return _active_session_model_identity(active_session)
    except Exception as exc:
        _record_runtime_summary_event(
            "runtime.summary.model_identity_failed",
            message="Runtime summary model identity resolution failed; falling back to public config model.",
            outcome="fallback",
            level="warning",
            fields={
                "exceptionType": type(exc).__name__,
                "agentId": str(active_session.get("agentId") or "").strip()
                if isinstance(active_session, dict)
                else "",
            },
        )
        return {}


def _active_session_model_identity(active_session: dict) -> dict[str, str]:
    if not isinstance(active_session, dict):
        return {}
    agent_id = str(active_session.get("agentId") or "").strip()
    if not agent_id:
        return {}
    try:
        from core.llm.agent_runtime import agent_dialogue_model_id
        from .agent_directory_service import get_agent

        agent = get_agent(agent_id, include_archived=True)
    except Exception:
        return {}
    if not isinstance(agent, dict):
        return {}
    model_id = str(agent_dialogue_model_id(agent) or "").strip()
    if not model_id:
        return {}
    try:
        config = get_config()
        entry = config.llm.model_library.get(model_id)
        if not isinstance(entry, dict):
            return {"modelId": model_id, "agentId": agent_id}
        model_name = str(entry.get("model") or entry.get("label") or model_id).strip() or model_id
        provider_id = str(entry.get("provider_id") or "").strip()
    except Exception:
        return {"model": model_id, "modelId": model_id, "agentId": agent_id}
    return {
        "model": model_name,
        "profile": provider_id,
        "modelId": model_id,
        "agentId": agent_id,
        "modelSource": "active_session_agent_dialogue_model",
        "profileSource": "active_session_agent_dialogue_provider",
    }


def _stop_active_chat_turns_before_shutdown() -> list[dict[str, object]]:
    """Persist active chat partials before the backend/launcher is closed."""

    try:
        active_runs = list_active_session_work_runs()
    except Exception as exc:
        return [
            {
                "sessionId": "",
                "runId": "",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        ]

    stopped: list[dict[str, object]] = []
    seen_session_ids: set[str] = set()
    for run in active_runs:
        if not isinstance(run, dict):
            continue
        session_id = str(run.get("sessionId") or "").strip()
        if not session_id or session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        run_id = str(run.get("runId") or "").strip()
        try:
            request_stop_session_turn(session_id)
        except Exception as exc:
            stopped.append(
                {
                    "sessionId": session_id,
                    "runId": run_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        stopped.append(
            {
                "sessionId": session_id,
                "runId": run_id,
                "status": "stopped",
            }
        )
    return stopped


def _stop_active_chat_room_rounds_before_shutdown() -> list[dict[str, object]]:
    """Persist active chat room round stop state before the backend/launcher is closed."""

    reason = text_for(
        get_web_language(),
        zh="工作台关闭前停止活跃群聊轮次。",
        en="Stopped active chat room rounds before workbench shutdown.",
    )
    try:
        from . import chat_room_service

        return list(chat_room_service.force_stop_active_chat_room_rounds_for_shutdown(reason))
    except Exception as exc:
        return [
            {
                "kind": "chat_room_round",
                "roomId": "",
                "runId": "",
                "roundId": "",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        ]


def _stop_active_evolution_runs_before_shutdown() -> list[dict[str, object]]:
    """Release active evolution leases before closing the workbench."""

    stopped: list[dict[str, object]] = []
    reason = text_for(
        get_web_language(),
        zh="工作台关闭前释放活跃进化任务。",
        en="Released active evolution work before workbench shutdown.",
    )

    for kind, stopper in (
        ("self_evolution_run", _force_cancel_self_evolution_for_shutdown),
        ("supervised_evolution_run", _force_cancel_supervised_evolution_for_shutdown),
        ("supervised_worktree_evolution_run", _force_cancel_supervised_worktree_evolution_for_shutdown),
    ):
        try:
            snapshots = stopper(reason)
        except Exception as exc:
            stopped.append(
                {
                    "kind": kind,
                    "runId": "",
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            stopped.append(
                {
                    "kind": kind,
                    "runId": str(snapshot.get("runId") or ""),
                    "status": str(snapshot.get("status") or ""),
                }
            )
    return stopped


def _force_cancel_self_evolution_for_shutdown(reason: str) -> list[dict[str, object]]:
    from . import self_evolution_control_service

    return list(self_evolution_control_service.force_cancel_active_self_evolution_runs_for_shutdown(reason))


def _force_cancel_supervised_evolution_for_shutdown(reason: str) -> list[dict[str, object]]:
    from . import supervised_control_service

    return list(supervised_control_service.force_cancel_active_supervised_runs_for_shutdown(reason))


def _force_cancel_supervised_worktree_evolution_for_shutdown(reason: str) -> list[dict[str, object]]:
    from . import supervised_worktree_evolution_service

    return list(supervised_worktree_evolution_service.force_cancel_active_supervised_worktree_runs_for_shutdown(reason))


def _work_run_summary() -> dict[str, dict[str, dict | None]]:
    chat = load_chat_turn_work_run_summary()
    chat_room = _safe_load_chat_room_work_run_summary()
    source_collection = _safe_load_source_collection_work_run_summary()
    self_active = _safe_load_evolution_work_run("self", active=True)
    self_latest = _safe_load_evolution_work_run("self", active=False)
    supervised_active = _safe_load_evolution_work_run("supervised", active=True)
    supervised_latest = _safe_load_evolution_work_run("supervised", active=False)
    supervised_worktree_active = _safe_load_supervised_worktree_work_run(active=True)
    supervised_worktree_latest = _safe_load_supervised_worktree_work_run(active=False)
    return {
        "active": {
            "chat_turn": chat.get("active"),
            "chat_room_round": chat_room.get("active"),
            "self_evolution_run": self_active,
            "supervised_evolution_run": supervised_active,
            "supervised_worktree_evolution_run": supervised_worktree_active,
            "source_collection_run": source_collection.get("active"),
        },
        "latest": {
            "chat_turn": chat.get("latest"),
            "chat_room_round": chat_room.get("latest"),
            "self_evolution_run": self_latest,
            "supervised_evolution_run": supervised_latest,
            "supervised_worktree_evolution_run": supervised_worktree_latest,
            "source_collection_run": source_collection.get("latest"),
        },
        "activeItems": {
            "chat_turn": [
                item for item in (chat.get("activeItems") or [])
                if isinstance(item, dict)
            ],
            "chat_room_round": [
                item for item in (chat_room.get("activeItems") or [])
                if isinstance(item, dict)
            ],
            "source_collection_run": [
                item for item in (source_collection.get("activeItems") or [])
                if isinstance(item, dict)
            ],
        },
    }


def _safe_load_chat_room_work_run_summary() -> dict[str, dict | None]:
    try:
        from . import chat_room_service

        payload = chat_room_service.load_chat_room_work_run_summary()
    except Exception:
        return {"active": None, "latest": None}
    if not isinstance(payload, dict):
        return {"active": None, "latest": None}
    return {
        "active": payload.get("active") if isinstance(payload.get("active"), dict) else None,
        "latest": payload.get("latest") if isinstance(payload.get("latest"), dict) else None,
    }


def _safe_load_source_collection_work_run_summary() -> dict[str, object]:
    try:
        from . import team_workflow_orchestration_service

        payload = team_workflow_orchestration_service.load_source_collection_work_run_summary()
    except Exception:
        return {"active": None, "latest": None, "activeItems": []}
    if not isinstance(payload, dict):
        return {"active": None, "latest": None, "activeItems": []}
    return {
        "active": payload.get("active") if isinstance(payload.get("active"), dict) else None,
        "latest": payload.get("latest") if isinstance(payload.get("latest"), dict) else None,
        "activeItems": [
            item for item in list(payload.get("activeItems") or [])
            if isinstance(item, dict)
        ],
    }


def _safe_load_evolution_work_run(kind: str, *, active: bool) -> dict | None:
    try:
        payload = (
            load_evolution_active_run_snapshot(kind)
            if active
            else load_evolution_latest_run_snapshot(kind)
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _decorate_evolution_work_run_snapshot(payload, kind=kind)


def _decorate_evolution_work_run_snapshot(payload: dict, *, kind: str) -> dict:
    decorated = dict(payload)
    if kind == "self":
        decorated.setdefault("runKind", "self_evolution_run")
    elif kind == "supervised":
        decorated.setdefault("runKind", "supervised_evolution_run")
    leases = leases_for_snapshot(decorated)
    if leases:
        decorated["leases"] = leases
    return decorated


def _safe_load_supervised_worktree_work_run(*, active: bool) -> dict | None:
    try:
        from . import supervised_worktree_evolution_service

        payload = (
            supervised_worktree_evolution_service.get_active_supervised_worktree_run()
            if active
            else _latest_supervised_worktree_snapshot()
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    decorated = dict(payload)
    leases = leases_for_snapshot(decorated)
    if leases:
        decorated["leases"] = leases
    return decorated


def _latest_supervised_worktree_snapshot() -> dict | None:
    from . import supervised_worktree_evolution_service

    runs = supervised_worktree_evolution_service.list_supervised_worktree_runs(limit=1)
    return runs[0] if runs else None


def _workbench_payload(lang: str, runtime_manager: dict) -> dict[str, object]:
    workbench = runtime_manager.get("workbench") if isinstance(runtime_manager, dict) else {}
    if not isinstance(workbench, dict):
        workbench = {}

    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(workbench.get("observedState") or "closed").strip() or "closed"
    session_role = str(workbench.get("sessionRole") or "workbench").strip() or "workbench"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"
    failure_message = str(workbench.get("failureMessage") or "").strip()
    lifecycle_consistency = str(workbench.get("lifecycleConsistency") or "consistent").strip() or "consistent"
    frontend_orphaned = bool(workbench.get("frontendOrphaned")) or lifecycle_consistency == "orphaned_browser"
    browser_missing = bool(
        lifecycle_consistency == "browser_missing"
        or (
            observed_state == "partial"
            and bool(workbench.get("browserManaged", True))
            and not bool(workbench.get("browserWindowAlive"))
            and bool(workbench.get("backendObserved"))
        )
    )

    if frontend_orphaned:
        status_line = failure_message or text_for(
            lang,
            zh="前端窗口仍在，但后端服务已经离线。",
            en="The frontend window is still open, but the backend service is offline.",
        )
    elif phase == "failed":
        status_line = failure_message or text_for(
            lang,
            zh="工作台生命周期遇到了错误。",
            en="The workbench lifecycle hit an error.",
        )
    elif desired_state == "closed" and observed_state != "closed":
        status_line = text_for(
            lang,
            zh="正在关闭工作台。",
            en="The runtime manager is closing the workbench.",
        )
    elif browser_missing:
        status_line = text_for(
            lang,
            zh="工作台窗口已关闭，后端仍在运行。",
            en="The workbench window is closed, but the backend is still running.",
        )
    elif desired_state == "open" and observed_state != "open":
        status_line = text_for(
            lang,
            zh="正在打开工作台。",
            en="The runtime manager is opening the workbench.",
        )
    elif session_role == "launcher_control_surface":
        status_line = text_for(
            lang,
            zh="Launcher 控制台正在运行，项目生命周期尚未启动。",
            en="The Launcher control surface is running; the project lifecycle has not been started.",
        )
    elif observed_state == "open":
        status_line = text_for(
            lang,
            zh="工作台正在运行。",
            en="The workbench is running.",
        )
    else:
        status_line = text_for(
            lang,
            zh="工作台已关闭。",
            en="The workbench is closed.",
        )

    return {
        "desiredState": desired_state,
        "observedState": observed_state,
        "sessionRole": session_role,
        "phase": phase,
        "backendPid": int(workbench.get("backendPid") or 0),
        "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
        "backendAlive": bool(workbench.get("backendAlive")),
        "backendHealthy": bool(workbench.get("backendHealthy")),
        "backendObserved": bool(workbench.get("backendObserved")),
        "backendPort": int(workbench.get("backendPort") or 0),
        "backendPortListening": bool(workbench.get("backendPortListening")),
        "backendPortOwnerPid": int(workbench.get("backendPortOwnerPid") or 0),
        "backendPortOwnerTrusted": bool(workbench.get("backendPortOwnerTrusted")),
        "backendPortConflict": bool(workbench.get("backendPortConflict")),
        "browserWindowAlive": bool(workbench.get("browserWindowAlive")),
        "browserManaged": bool(workbench.get("browserManaged", True)),
        "backendMissing": bool(workbench.get("backendMissing")),
        "frontendOrphaned": frontend_orphaned,
        "lifecycleConsistency": lifecycle_consistency,
        "url": str(workbench.get("url") or "").strip(),
        "lastReason": str(workbench.get("lastReason") or "").strip(),
        "statusLine": status_line,
        "failureMessage": failure_message,
    }


def _runtime_lifecycle_proof(lang: str, runtime_manager: dict, workbench: dict, work_runs: dict) -> dict[str, object]:
    verified_at = _utc_now_iso()
    desired_state = str(workbench.get("desiredState") or "closed").strip().lower() or "closed"
    observed_state = str(workbench.get("observedState") or "closed").strip().lower() or "closed"
    session_role = str(workbench.get("sessionRole") or "workbench").strip() or "workbench"
    phase = str(workbench.get("phase") or "steady").strip().lower() or "steady"
    failure_message = str(workbench.get("failureMessage") or "").strip()
    manager_running = bool(runtime_manager.get("daemonRunning"))
    manager_pid = int(runtime_manager.get("managerPid") or 0)
    manager_project_root = str(runtime_manager.get("projectRoot") or "").strip()
    project_root_matches = _same_project_root(manager_project_root, str(PROJECT_ROOT))
    runtime_manager_meta = runtime_manager.get("runtimeManager") if isinstance(runtime_manager, dict) else {}
    if not isinstance(runtime_manager_meta, dict):
        runtime_manager_meta = {}
    source_matches = runtime_manager_meta.get("sourceMatches")
    residual_processes = runtime_manager.get("residualProcesses") if isinstance(runtime_manager, dict) else {}
    if not isinstance(residual_processes, dict):
        residual_processes = {}
    residual_items = [item for item in residual_processes.get("items", []) if isinstance(item, dict)]
    residual_count = max(int(residual_processes.get("count") or 0), len(residual_items))
    backend_pid = int(workbench.get("backendPid") or 0)
    backend_port_owner_pid = int(workbench.get("backendPortOwnerPid") or 0)
    backend_port_listening = bool(workbench.get("backendPortListening"))
    backend_port_owner_trusted = bool(workbench.get("backendPortOwnerTrusted"))
    backend_port_conflict = bool(workbench.get("backendPortConflict"))
    backend_alive = bool(workbench.get("backendAlive"))
    backend_healthy = bool(workbench.get("backendHealthy"))
    backend_observed = (
        bool(workbench.get("backendObserved"))
        or (backend_alive and not backend_port_conflict)
        or (backend_healthy and not backend_port_conflict)
        or backend_port_owner_trusted
        or (observed_state in {"open", "partial"} and backend_pid > 0)
    )
    browser_pid = int(workbench.get("browserWindowPid") or 0)
    browser_managed = bool(workbench.get("browserManaged", True))
    browser_window_alive = bool(workbench.get("browserWindowAlive")) or (
        observed_state == "open" and browser_pid > 0
    )
    browser_missing = bool(
        str(workbench.get("lifecycleConsistency") or "").strip().lower() == "browser_missing"
        or (observed_state == "partial" and browser_managed and not browser_window_alive and backend_observed)
    )
    active_work_runs = _active_work_runs(work_runs)
    backend_verified = observed_state in {"open", "partial"} and backend_observed
    backend_closed = desired_state == "closed" and observed_state == "closed" and not backend_observed
    window_verified = observed_state == "open" and (not browser_managed or browser_window_alive)
    window_closed = desired_state == "closed" and observed_state == "closed" and not browser_window_alive
    project_root_state = "verified" if project_root_matches else ("failed" if manager_project_root else "unknown")

    components = [
        {
            "id": "runtime_manager",
            "label": text_for(lang, zh="运行管理器", en="Runtime manager"),
            "state": "verified" if manager_running else "missing",
            "ok": manager_running,
            "requiredForOpen": True,
            "requiredForClosed": False,
            "detail": (
                text_for(lang, zh=f"manager pid {manager_pid}", en=f"manager pid {manager_pid}")
                if manager_running
                else text_for(lang, zh="没有观测到运行管理器进程。", en="No runtime manager process was observed.")
            ),
            "pid": manager_pid,
            "verifiedAt": verified_at,
        },
        {
            "id": "backend",
            "label": text_for(lang, zh="后端服务", en="Backend service"),
            "state": "verified" if backend_verified or backend_closed else ("closing" if desired_state == "closed" else "missing"),
            "ok": backend_verified or backend_closed,
            "requiredForOpen": True,
            "requiredForClosed": True,
            "detail": (
                text_for(lang, zh=f"backend pid {backend_pid}", en=f"backend pid {backend_pid}")
                if backend_verified and backend_pid > 0
                else text_for(lang, zh=f"端口被外部 pid {backend_port_owner_pid} 占用。", en=f"Port is occupied by external pid {backend_port_owner_pid}.")
                if backend_port_conflict and backend_port_owner_pid > 0
                else text_for(lang, zh=f"端口仍被 pid {backend_port_owner_pid} 占用。", en=f"Port is still owned by pid {backend_port_owner_pid}.")
                if not backend_closed and backend_port_owner_pid > 0
                else text_for(lang, zh="后端端口仍在监听。", en="Backend port is still listening.")
                if not backend_closed and backend_port_listening
                else text_for(lang, zh="工作台观测证明后端可达。", en="Workbench observation proves the backend is reachable.")
                if backend_verified
                else text_for(lang, zh="后端已不再被观测为打开。", en="Backend is no longer observed open.")
                if backend_closed
                else text_for(lang, zh="后端未被证明为打开状态。", en="Backend is not proven open.")
            ),
            "pid": backend_pid,
            "verifiedAt": verified_at,
        },
        {
            "id": "workbench_window",
            "label": text_for(lang, zh="工作台窗口", en="Workbench window"),
            "state": "verified" if window_verified or window_closed else ("closing" if desired_state == "closed" else "missing"),
            "ok": window_verified or window_closed,
            "requiredForOpen": True,
            "requiredForClosed": True,
            "detail": text_for(
                lang,
                zh=f"desired={desired_state}, observed={observed_state}, phase={phase}",
                en=f"desired={desired_state}, observed={observed_state}, phase={phase}",
            ),
            "pid": browser_pid,
            "verifiedAt": verified_at,
        },
        {
            "id": "project_root",
            "label": text_for(lang, zh="项目根目录", en="Project root"),
            "state": project_root_state,
            "ok": project_root_matches,
            "requiredForOpen": True,
            "requiredForClosed": False,
            "detail": (
                manager_project_root
                if project_root_matches and manager_project_root
                else text_for(lang, zh="运行管理器未提供项目根目录。", en="Runtime manager did not provide a project root.")
                if not manager_project_root
                else text_for(lang, zh="运行管理器项目根目录与当前仓库不一致。", en="Runtime manager project root does not match this repo.")
            ),
            "pid": 0,
            "verifiedAt": verified_at,
        },
        {
            "id": "active_work_runs",
            "label": text_for(lang, zh="活跃任务", en="Active work runs"),
            "state": "verified" if not active_work_runs else "running",
            "ok": not active_work_runs,
            "requiredForOpen": False,
            "requiredForClosed": True,
            "detail": _active_work_run_detail(lang, active_work_runs),
            "pid": 0,
            "verifiedAt": verified_at,
        },
        {
            "id": "source_freshness",
            "label": text_for(lang, zh="运行器源码", en="Runtime source"),
            "state": "verified" if source_matches is not False else "failed",
            "ok": source_matches is not False,
            "requiredForOpen": False,
            "requiredForClosed": False,
            "detail": (
                text_for(lang, zh="运行器源码签名匹配或未提供签名。", en="Runtime source signature matches or was not provided.")
                if source_matches is not False
                else text_for(lang, zh="运行器源码签名已过期，下一次控制命令需要换代。", en="Runtime source signature is stale; the next control command must replace it.")
            ),
            "pid": 0,
            "verifiedAt": verified_at,
        },
        {
            "id": "residual_processes",
            "label": text_for(lang, zh="残留仓库进程", en="Residual repo processes"),
            "state": "verified" if residual_count == 0 else "running",
            "ok": residual_count == 0,
            "requiredForOpen": False,
            "requiredForClosed": True,
            "detail": _residual_process_detail(lang, residual_items, residual_count),
            "pid": int(residual_items[0].get("pid") or 0) if residual_items else 0,
            "verifiedAt": verified_at,
        },
    ]

    failed = phase == "failed" or bool(failure_message) or any(
        item["state"] == "failed"
        and (
            (desired_state == "open" and bool(item.get("requiredForOpen")))
            or (desired_state == "closed" and bool(item.get("requiredForClosed")))
        )
        for item in components
    )
    if failed:
        overall_state = "failed"
    elif desired_state == "open" and browser_missing:
        overall_state = "partial"
    elif desired_state == "open" and observed_state == "open":
        open_components_ok = manager_running and backend_verified and project_root_matches
        overall_state = "ready" if open_components_ok else "partial"
    elif desired_state == "open" and observed_state != "open":
        overall_state = "starting"
    elif desired_state == "closed" and observed_state != "closed":
        overall_state = "closing"
    elif desired_state == "closed" and observed_state == "closed":
        overall_state = "closed" if not active_work_runs and backend_closed and window_closed and residual_count == 0 else "partial"
    else:
        overall_state = "partial"

    overall_label = _lifecycle_overall_label(lang, overall_state)
    return {
        "overallState": overall_state,
        "overallLabel": overall_label,
        "summary": _lifecycle_summary(
            lang,
            overall_state=overall_state,
            desired_state=desired_state,
            observed_state=observed_state,
            active_count=len(active_work_runs),
            failure_message=failure_message,
        ),
        "verifiedAt": verified_at,
        "desiredState": desired_state,
        "observedState": observed_state,
        "sessionRole": session_role,
        "phase": phase,
        "browserManaged": browser_managed,
        "projectRootMatches": project_root_matches,
        "components": components,
        "activeWorkRuns": {
            "count": len(active_work_runs),
            "kinds": [str(item.get("kind") or "") for item in active_work_runs],
            "items": active_work_runs,
        },
        "residualProcesses": {
            "count": residual_count,
            "items": residual_items,
        },
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _same_project_root(left: str, right: str) -> bool:
    if not left:
        return False
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _active_work_runs(work_runs: dict) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    active_items = work_runs.get("activeItems") if isinstance(work_runs, dict) else {}
    if isinstance(active_items, dict):
        for kind, payloads in active_items.items():
            if not isinstance(payloads, list):
                continue
            for payload in payloads:
                if not isinstance(payload, dict):
                    continue
                item = _active_work_run_item(str(kind or ""), payload)
                key = (item.get("kind") or "", item.get("runId") or "")
                if item and key not in seen:
                    seen.add(key)
                    items.append(item)

    active = work_runs.get("active") if isinstance(work_runs, dict) else {}
    if not isinstance(active, dict):
        return items
    for kind, payload in active.items():
        if not isinstance(payload, dict):
            continue
        item = _active_work_run_item(str(kind or ""), payload)
        key = (item.get("kind") or "", item.get("runId") or "")
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return items


def _active_work_run_item(kind: str, payload: dict) -> dict[str, str]:
    if not _active_work_payload_blocks_lifecycle(payload):
        return {}
    run_id = str(payload.get("runId") or payload.get("sessionId") or "").strip()
    status = str(payload.get("status") or payload.get("currentPhase") or "").strip()
    return {
        "kind": kind,
        "runId": run_id,
        "status": status,
        "sessionId": str(payload.get("sessionId") or "").strip(),
    }


def _active_work_payload_blocks_lifecycle(payload: dict) -> bool:
    return work_run_store.active_work_payload_blocks_lifecycle(payload)


def _active_work_run_detail(lang: str, active_work_runs: list[dict[str, str]]) -> str:
    if not active_work_runs:
        return text_for(lang, zh="没有活跃 work run。", en="No active work runs.")
    kinds = ", ".join(item["kind"] for item in active_work_runs if item.get("kind"))
    return text_for(
        lang,
        zh=f"仍有 {len(active_work_runs)} 个活跃任务：{kinds}",
        en=f"{len(active_work_runs)} active work run(s): {kinds}",
    )


def _residual_process_detail(lang: str, residual_items: list[dict], residual_count: int) -> str:
    if residual_count <= 0:
        return text_for(lang, zh="没有观测到当前仓库的残留 workbench 进程。", en="No repo-local residual workbench processes were observed.")
    examples = []
    for item in residual_items[:3]:
        pid = int(item.get("pid") or 0)
        port = int(item.get("port") or 0)
        kind = str(item.get("kind") or "process")
        examples.append(f"{kind} pid={pid}" + (f" port={port}" if port else ""))
    suffix = "; ".join(examples)
    return text_for(
        lang,
        zh=f"仍有 {residual_count} 个当前仓库残留进程：{suffix}",
        en=f"{residual_count} repo-local residual process(es) remain: {suffix}",
    )


def _lifecycle_overall_label(lang: str, state: str) -> str:
    labels = {
        "ready": text_for(lang, zh="已真正开启", en="Proven open"),
        "starting": text_for(lang, zh="正在开启", en="Starting"),
        "closing": text_for(lang, zh="正在关闭", en="Closing"),
        "closed": text_for(lang, zh="已真正关闭", en="Proven closed"),
        "partial": text_for(lang, zh="部分成立", en="Partial"),
        "failed": text_for(lang, zh="异常", en="Failed"),
    }
    return labels.get(state, state)


def _lifecycle_summary(
    lang: str,
    *,
    overall_state: str,
    desired_state: str,
    observed_state: str,
    active_count: int,
    failure_message: str,
) -> str:
    if overall_state == "ready":
        return text_for(
            lang,
            zh="运行管理器、后端、窗口和项目根目录都已对齐，软件可判定为真正开启。",
            en="Runtime manager, backend, window, and project root all agree; the app is proven open.",
        )
    if overall_state == "closed":
        return text_for(
            lang,
            zh="工作台已观测为关闭，且没有活跃任务或同仓库残留进程，可判定为真正关闭。",
            en="Workbench is observed closed and no work runs or repo-local residual processes remain; the app is proven closed.",
        )
    if overall_state == "starting":
        return text_for(
            lang,
            zh="目标状态是开启，但窗口或后端尚未全部观测到。",
            en="Desired state is open, but the backend or window is not fully observed yet.",
        )
    if overall_state == "closing":
        return text_for(
            lang,
            zh="目标状态是关闭，但仍能观测到后端或窗口，关闭尚未完成。",
            en="Desired state is closed, but backend or window evidence still exists; close is not complete.",
        )
    if overall_state == "failed":
        return failure_message or text_for(
            lang,
            zh="生命周期证明中存在失败组件，需要查看 launcher/runtime-manager 日志。",
            en="A lifecycle proof component failed. Check launcher/runtime-manager logs.",
        )
    if active_count > 0:
        return text_for(
            lang,
            zh=f"工作台状态为 desired={desired_state}, observed={observed_state}，但仍有 {active_count} 个活跃任务。",
            en=f"Workbench is desired={desired_state}, observed={observed_state}, but {active_count} work run(s) remain active.",
        )
    return text_for(
        lang,
        zh=f"工作台状态为 desired={desired_state}, observed={observed_state}，部分证明仍不一致。",
        en=f"Workbench is desired={desired_state}, observed={observed_state}; proof components do not fully agree.",
    )


def _derive_web_status(task_status: object, runtime_state: dict) -> str:
    task = str(task_status or "").strip().lower()
    current_status = str(runtime_state.get("status") or "").strip().upper()
    runtime_status = str(runtime_state.get("runtime_status") or "").strip().upper()

    if task == "blocked":
        return "failed"
    if task in {"needs_input", "waiting"}:
        return "waiting"
    if task in {"done", "ready"}:
        return "success"
    if task in {"running", "stopping"}:
        return "running"
    if task in {"planning", "reading", "editing", "verifying"}:
        return "running"
    if current_status == "ERROR" or runtime_status == "ERROR":
        return "failed"
    if current_status == "SUCCESS":
        return "success"
    if current_status in {"THINKING", "PLANNING", "ACTING", "WORKING"}:
        return "running"
    return "idle"


def _agent_status_line(lang: str, status: str, task_status: object) -> str:
    if status == "failed":
        return text_for(lang, zh="当前轮遇到阻塞", en="current pass is blocked")
    if status == "success":
        return text_for(lang, zh="上一轮已经完成", en="latest pass completed")
    if status == "running":
        return text_for(lang, zh="正在推进当前任务", en="working through the current task")
    return text_for(lang, zh="稳定待命", en="steady and ready")


def _derive_session_state(lang: str, active_session: dict, runtime_state: dict) -> dict[str, str]:
    session_phase = str(active_session.get("currentPhase") or "").strip().lower()
    current_status = str(runtime_state.get("status") or "").strip().upper()
    runtime_status = str(runtime_state.get("runtime_status") or "").strip().upper()
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    turn_output_tokens = max(0, int(runtime_state.get("turn_output_tokens") or 0))

    state = "idle"
    needs_response = session_phase in {"ready", "failed"}
    line = text_for(lang, zh="当前没有活跃会话动作", en="there is no active session activity right now")

    if session_phase == "failed":
        state = "failed"
        needs_response = True
        line = str(active_session.get("taskSummary") or "").strip() or text_for(
            lang,
            zh="当前轮遇到阻塞，需要先处理异常",
            en="the current pass is blocked and needs attention first",
        )
    elif session_phase == "ready":
        state = "ready"
        needs_response = True
        line = text_for(lang, zh="这一轮已经回答完成，可以继续推进", en="the latest reply is complete and ready to continue")
    elif current_status in {"ERROR", "FAILED"} or runtime_status == "ERROR":
        state = "failed"
        needs_response = True
        line = str(active_session.get("taskSummary") or "").strip() or text_for(
            lang,
            zh="当前轮遇到阻塞，需要先处理异常",
            en="the current pass is blocked and needs attention first",
        )
    elif current_status in {"SUCCESS", "DONE"} and session_phase not in RUNNING_SESSION_PHASES:
        state = "ready"
        needs_response = True
        line = text_for(lang, zh="这一轮已经回答完成，可以继续推进", en="the latest reply is complete and ready to continue")
    elif runtime_status == "ACTING":
        state = "tooling"
        line = text_for(
            lang,
            zh=f"正在调用工具 {last_tool_name}" if last_tool_name else "正在调用当前工具",
            en=f"calling tool {last_tool_name}" if last_tool_name else "calling the current tool",
        )
    elif current_status in {"THINKING", "PLANNING"}:
        state = "thinking"
        line = text_for(lang, zh="正在思考这一轮怎么推进", en="thinking through how to advance this pass")
    elif current_status == "WORKING" and runtime_status == "WORKING" and turn_output_tokens > 0 and not last_tool_name:
        state = "answering"
        line = text_for(lang, zh="正在整理并输出回答", en="drafting and sending the current reply")
    elif session_phase in RUNNING_SESSION_PHASES or current_status in {"RUNNING", "WORKING", "ACTING"} or runtime_status == "WORKING":
        state = "running"
        line = _agent_status_line(lang, "running", session_phase)

    return {
        "state": state,
        "line": line,
        "needs_response": needs_response,
        "tool_name": last_tool_name,
    }


def _mental_state_summary(lang: str, public_config: dict | None = None) -> dict[str, object]:
    if not is_mental_model_enabled(public_config):
        return _disabled_mental_state(lang)

    try:
        mental_model = get_mental_model(workspace_root=str(PROJECT_ROOT / "workspace"))
    except TypeError:
        mental_model = get_mental_model()
    except Exception:
        return _empty_mental_state(lang)

    try:
        last_state = mental_model.get_last_state() or {}
    except Exception:
        last_state = {}

    try:
        diagnosis = mental_model.diagnose()
    except Exception:
        diagnosis = None

    mood = str(last_state.get("mood") or "").strip()
    feeling = str(last_state.get("feeling") or "").strip()
    whisper = str(last_state.get("whisper") or "").strip()
    cognitive_state = str(getattr(diagnosis, "state", "") or "").strip().lower()
    confidence = float(getattr(diagnosis, "confidence", 0.0) or 0.0)
    metrics = getattr(diagnosis, "metrics", {}) or {}
    updated_at = str(
        last_state.get("timestamp")
        or getattr(diagnosis, "timestamp", "")
        or ""
    ).strip()

    source = "unavailable"
    if mood or feeling or whisper:
        source = "state"
    elif cognitive_state:
        source = "diagnosis"

    if mood:
        summary = feeling or whisper or text_for(
            lang,
            zh="当前心智层已给出最近一次状态。",
            en="The mental layer has produced a recent state.",
        )
    elif cognitive_state:
        summary = _mental_diagnosis_summary(lang, cognitive_state)
    else:
        summary = text_for(
            lang,
            zh="当前还没有新的心智感知。",
            en="No fresh mental state is available yet.",
        )

    return {
        "mood": mood,
        "feeling": feeling,
        "whisper": whisper,
        "summary": summary,
        "cognitiveState": cognitive_state,
        "confidence": max(0.0, min(confidence, 1.0)),
        "sampleSize": max(0, int(metrics.get("sample_size") or 0)),
        "interventionCount": max(0, int(metrics.get("intervention_count") or 0)),
        "updatedAt": updated_at,
        "source": source,
    }


def _empty_mental_state(lang: str) -> dict[str, object]:
    return {
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": text_for(
            lang,
            zh="当前还没有新的心智感知。",
            en="No fresh mental state is available yet.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": "",
        "source": "unavailable",
    }


def _disabled_mental_state(lang: str) -> dict[str, object]:
    return {
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": text_for(
            lang,
            zh="心智模型已关闭。",
            en="Mental model is disabled.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": "",
        "source": "disabled",
    }


def _mental_diagnosis_summary(lang: str, cognitive_state: str) -> str:
    label = {
        "normal": text_for(lang, zh="稳定", en="stable"),
        "productive": text_for(lang, zh="顺畅", en="productive"),
        "looping": text_for(lang, zh="循环", en="looping"),
        "thrashing": text_for(lang, zh="失稳", en="thrashing"),
        "tunnel_vision": text_for(lang, zh="聚焦过窄", en="tunnel vision"),
        "disoriented": text_for(lang, zh="方向发散", en="disoriented"),
    }.get(cognitive_state, text_for(lang, zh="未判定", en="unclassified"))
    return text_for(
        lang,
        zh=f"当前以规则诊断为主，认知态：{label}。",
        en=f"Showing rule-based diagnosis right now. Cognitive state: {label}.",
    )


def _context_usage(runtime_state: dict) -> dict[str, int]:
    used = max(0, int(runtime_state.get("current_context_tokens") or 0))
    limit = max(0, int(runtime_state.get("context_token_limit") or 0)) or 128000
    return {"used": min(used, limit), "limit": limit}


def _context_compression_summary(runtime_state: dict, context_usage: dict[str, int]) -> dict[str, object]:
    try:
        cfg = get_config().context_compression
    except Exception:
        cfg = None

    persisted = runtime_state.get("context_compression")
    persisted = persisted if isinstance(persisted, dict) else {}
    enabled = bool(getattr(cfg, "enabled", True)) if cfg is not None else bool(persisted.get("enabled", True))
    effective_limit = _positive_int(
        persisted.get("effectiveTokenLimit"),
        context_usage.get("limit"),
        getattr(cfg, "max_token_limit", 0) if cfg is not None else 0,
    )
    context_window = _positive_int(
        persisted.get("contextWindowLimit"),
        runtime_state.get("context_token_limit"),
        effective_limit,
    )
    used = max(0, int(context_usage.get("used") or 0))
    ratio = round(min(1.0, used / effective_limit), 4) if effective_limit > 0 else 0.0
    level = _compression_level_for_ratio(ratio)
    strategy_levels = _compression_strategy_payload(cfg, effective_limit=effective_limit)
    last_compression = persisted.get("lastCompression")
    if not isinstance(last_compression, dict):
        last_compression = {}

    return {
        "enabled": enabled,
        "source": "runtime_state",
        "scope": "runtime_prompt_estimate",
        "tokenBasis": "current_context_tokens",
        "limitBasis": "effective_token_limit",
        "currentTokens": used,
        "effectiveTokenLimit": effective_limit,
        "contextWindowLimit": context_window,
        "usageRatio": ratio,
        "currentLevel": level,
        "compressionCount": max(0, int(persisted.get("compressionCount") or 0)),
        "lastCompression": _last_compression_payload(last_compression),
        "strategy": {
            "levels": strategy_levels,
            "preserveErrors": bool(getattr(getattr(cfg, "preservation", None), "preserve_errors", True)),
            "errorProtectionKeywords": ["error", "exception", "traceback", "failed", "错误", "异常", "失败", "超时", "权限"],
            "summaryStorage": "state_memory",
            "algorithm": "old messages become a runtime summary while recent AI context is kept",
        },
        "updatedAt": str(persisted.get("updatedAt") or runtime_state.get("updated_at") or "").strip(),
    }


def _positive_int(*values: object) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 0


def _compression_level_for_ratio(ratio: float) -> str:
    if ratio >= 0.95:
        return "emergency"
    if ratio >= 0.9:
        return "deep"
    if ratio >= 0.8:
        return "standard"
    if ratio >= 0.6:
        return "light"
    return "normal"


def _compression_strategy_payload(cfg, *, effective_limit: int) -> list[dict[str, object]]:
    levels = getattr(cfg, "levels", None)
    summary_chars = getattr(cfg, "summary_chars", None)
    preservation = getattr(cfg, "preservation", None)
    keep_ai = max(0, int(getattr(preservation, "keep_ai_messages", 5) or 0))
    rows = [
        ("light", float(getattr(levels, "light", 0.6) if levels is not None else 0.6), keep_ai, int(getattr(summary_chars, "light", 500) if summary_chars is not None else 500)),
        ("standard", float(getattr(levels, "standard", 0.8) if levels is not None else 0.8), max(keep_ai - 2, 1), int(getattr(summary_chars, "standard", 1000) if summary_chars is not None else 1000)),
        ("deep", float(getattr(levels, "deep", 0.9) if levels is not None else 0.9), max(keep_ai - 3, 1), int(getattr(summary_chars, "deep", 2000) if summary_chars is not None else 2000)),
        ("emergency", float(getattr(levels, "emergency", 0.95) if levels is not None else 0.95), 1, int(getattr(summary_chars, "emergency", 3000) if summary_chars is not None else 3000)),
    ]
    return [
        {
            "level": level,
            "thresholdRatio": threshold,
            "thresholdTokens": int(threshold * max(0, int(effective_limit or 0))),
            "keepAiMessages": keep,
            "summaryMaxChars": chars,
        }
        for level, threshold, keep, chars in rows
    ]


def _last_compression_payload(payload: dict) -> dict[str, object] | None:
    if not payload:
        return None
    before = max(0, int(payload.get("beforeTokens") or 0))
    after = max(0, int(payload.get("afterTokens") or 0))
    reason = str(payload.get("reason") or "").strip()
    return {
        "level": str(payload.get("level") or "").strip(),
        "reason": reason,
        "triggerSource": _compression_trigger_source_payload(payload.get("triggerSource"), reason),
        "beforeTokens": before,
        "afterTokens": after,
        "savedTokens": max(0, int(payload.get("savedTokens") or max(0, before - after))),
        "iteration": max(0, int(payload.get("iteration") or 0)),
        "summaryWritten": bool(payload.get("summaryWritten")),
        "timestamp": str(payload.get("timestamp") or "").strip(),
    }


def _compression_trigger_source_payload(source: object, reason: str) -> str:
    normalized_source = str(source or "").strip().lower()
    if normalized_source in {"manual", "auto", "provider_limit"}:
        return normalized_source
    normalized_reason = str(reason or "").strip().lower()
    if not normalized_reason or normalized_reason.startswith("level:"):
        return "auto"
    if "context limit" in normalized_reason or "context_length" in normalized_reason or "超出最大上下文" in normalized_reason:
        return "provider_limit"
    return "manual"


def _active_tools(active_session: dict, runtime_state: dict) -> list[str]:
    tools: list[str] = []
    for message in reversed(list(active_session.get("messages") or [])):
        tool_calls = list(message.get("toolCalls") or [])
        if tool_calls:
            for item in tool_calls:
                name = str((item or {}).get("name") or "").strip()
                if name and name not in tools:
                    tools.append(name)
            break
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    if last_tool_name and last_tool_name not in tools:
        tools.append(last_tool_name)
    return tools[:8]


def _recent_action(lang: str, active_session: dict, runtime_state: dict) -> str:
    for value in (active_session.get("taskSummary"),):
        text = str(value or "").strip()
        if text:
            return text
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    if last_tool_name:
        return text_for(
            lang,
            zh=f"最近使用工具：{last_tool_name}",
            en=f"Last tool used: {last_tool_name}",
        )
    return text_for(lang, zh="等待新的运行痕迹", en="Waiting for new runtime activity")
