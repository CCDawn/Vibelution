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
from core.infrastructure.mental_model import get_mental_model
from core.mental_model_flags import is_mental_model_enabled
from core.runtime_manager import ensure_daemon_running, load_runtime_snapshot, submit_command
from core.runtime_manager.evolution_store import (
    load_active_run_snapshot as load_evolution_active_run_snapshot,
    load_latest_run_snapshot as load_evolution_latest_run_snapshot,
)
from core.runtime_manager.work_run_leases import leases_for_snapshot

from .i18n import get_web_language, text_for
from .session_service import (
    get_active_session_detail,
    list_active_session_work_runs,
    load_chat_turn_work_run_summary,
    request_stop_session_turn,
)
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_STATE_PATH = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
LAUNCHER_SHUTDOWN_LOG_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "shutdown-request.log"
RUNNING_SESSION_PHASES = {"running", "stopping"}


def get_runtime_summary() -> dict:
    """Return a light runtime summary for the global shell."""

    runtime_profile = "safe_local"
    model_ref = "unconfigured"
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
    except Exception:
        pass

    active_session = get_active_session_detail() or {}
    runtime_state = _load_runtime_state()
    current_phase = str(active_session.get("currentPhase") or "").strip().lower()
    status = _derive_web_status(current_phase, runtime_state)
    session_state = _derive_session_state(lang, active_session, runtime_state)
    active_tools = _active_tools(active_session, runtime_state)
    context_usage = _context_usage(runtime_state)
    runtime_manager = _load_runtime_manager_snapshot()
    work_runs = _work_run_summary()
    workbench = _workbench_payload(lang, runtime_manager)
    lifecycle_proof = _runtime_lifecycle_proof(lang, runtime_manager, workbench, work_runs)
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
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "agentName": "Vibelution",
        "userName": _local_user_name(),
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
    stopped_chat_turns = _stop_active_chat_turns_before_shutdown()
    stopped_evolution_runs = _stop_active_evolution_runs_before_shutdown()
    if _can_use_managed_launcher_shutdown():
        try:
            ensure_daemon_running()
            submit_command(
                "close_workbench",
                args={"reason": "web_close_button", "source": "web_ui", "stopManager": True},
                requested_by="web_ui",
            )
            return {
                "accepted": True,
                "mode": "runtime_manager",
                "message": text_for(
                    lang,
                    zh="正在关闭工作台，窗口会在后端停稳后自动关闭。",
                    en="Closing the workbench. The app window will close after the backend stops.",
                ),
                "chatTurns": stopped_chat_turns,
                "evolutionRuns": stopped_evolution_runs,
            }
        except Exception:
            _spawn_managed_launcher_shutdown()
            return {
                "accepted": True,
                "mode": "managed_fallback",
                "message": text_for(
                    lang,
                    zh="正在关闭工作台，窗口会在后端停稳后自动关闭。",
                    en="Closing the workbench. The app window will close after the backend stops.",
                ),
                "chatTurns": stopped_chat_turns,
                "evolutionRuns": stopped_evolution_runs,
            }

    _schedule_local_backend_exit()
    return {
        "accepted": True,
        "mode": "local",
        "message": text_for(
            lang,
            zh="正在关闭本地后端服务。",
            en="Shutting down the local backend.",
        ),
        "chatTurns": stopped_chat_turns,
        "evolutionRuns": stopped_evolution_runs,
    }


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
    try:
        payload = load_runtime_snapshot()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _local_user_name() -> str:
    for key in ("VIBELUTION_USER_NAME", "USERNAME", "USER", "LOGNAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    try:
        return str(getpass.getuser() or "").strip()
    except Exception:
        return ""


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


def _work_run_summary() -> dict[str, dict[str, dict | None]]:
    chat = load_chat_turn_work_run_summary()
    self_active = _safe_load_evolution_work_run("self", active=True)
    self_latest = _safe_load_evolution_work_run("self", active=False)
    supervised_active = _safe_load_evolution_work_run("supervised", active=True)
    supervised_latest = _safe_load_evolution_work_run("supervised", active=False)
    return {
        "active": {
            "chat_turn": chat.get("active"),
            "self_evolution_run": self_active,
            "supervised_evolution_run": supervised_active,
        },
        "latest": {
            "chat_turn": chat.get("latest"),
            "self_evolution_run": self_latest,
            "supervised_evolution_run": supervised_latest,
        },
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


def _workbench_payload(lang: str, runtime_manager: dict) -> dict[str, object]:
    workbench = runtime_manager.get("workbench") if isinstance(runtime_manager, dict) else {}
    if not isinstance(workbench, dict):
        workbench = {}

    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(workbench.get("observedState") or "closed").strip() or "closed"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"
    failure_message = str(workbench.get("failureMessage") or "").strip()

    if phase == "failed":
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
    elif desired_state == "open" and observed_state != "open":
        status_line = text_for(
            lang,
            zh="正在打开工作台。",
            en="The runtime manager is opening the workbench.",
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
        "url": str(workbench.get("url") or "").strip(),
        "lastReason": str(workbench.get("lastReason") or "").strip(),
        "statusLine": status_line,
        "failureMessage": failure_message,
    }


def _runtime_lifecycle_proof(lang: str, runtime_manager: dict, workbench: dict, work_runs: dict) -> dict[str, object]:
    verified_at = _utc_now_iso()
    desired_state = str(workbench.get("desiredState") or "closed").strip().lower() or "closed"
    observed_state = str(workbench.get("observedState") or "closed").strip().lower() or "closed"
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
        or (observed_state == "open" and backend_pid > 0)
    )
    browser_pid = int(workbench.get("browserWindowPid") or 0)
    browser_managed = bool(workbench.get("browserManaged", True))
    browser_window_alive = bool(workbench.get("browserWindowAlive")) or (
        observed_state == "open" and browser_pid > 0
    )
    active_work_runs = _active_work_runs(work_runs)
    backend_verified = observed_state == "open" and backend_observed
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

    failed = phase == "failed" or bool(failure_message) or any(item["state"] == "failed" for item in components)
    if failed:
        overall_state = "failed"
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
    active = work_runs.get("active") if isinstance(work_runs, dict) else {}
    if not isinstance(active, dict):
        return []
    items: list[dict[str, str]] = []
    for kind, payload in active.items():
        if not isinstance(payload, dict):
            continue
        run_id = str(payload.get("runId") or payload.get("sessionId") or "").strip()
        status = str(payload.get("status") or payload.get("currentPhase") or "").strip()
        items.append(
            {
                "kind": str(kind or ""),
                "runId": run_id,
                "status": status,
            }
        )
    return items


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
