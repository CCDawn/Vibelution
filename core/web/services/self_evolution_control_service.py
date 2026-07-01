"""Bounded self-evolution run control for the web workbench."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.evaluation import DEFAULT_SELF_EVOLUTION_GOAL, build_self_evolution_run_prompt
from core.evaluation.self_evolution_experience_repository import (
    record_terminal_self_evolution_experience,
)
from core.evaluation.self_evolution_reflection import (
    record_bounded_self_evolution_reflection,
)
from core.infrastructure import developer_sandbox, git_process
from core.launcher import service as launcher_service
from core.infrastructure.agent_session import get_session_state
from core.orchestration.context_engine import build_agent_context, record_agent_turn_result
from core.orchestration.turn_runner import AgentSingleTurnRequest, run_agent_single_turn
from core.orchestration.turn_runtime import AgentTurnRuntimeRequest
from core.runtime_manager.command_queue import submit_command, wait_for_result
from core.runtime_manager.evolution_store import (
    load_active_run_snapshot as load_manager_active_run_snapshot,
    load_latest_run_snapshot as load_manager_latest_run_snapshot,
    load_run_snapshot as load_manager_run_snapshot,
    persist_run_snapshot as persist_manager_run_snapshot,
)
from core.runtime_manager.restart_coordinator import create_restart_intent
from core.runtime_manager.work_run_leases import (
    EVOLUTION_TRANSACTION_LEASE,
    MEMORY_WRITE_LEASE,
    WORKTREE_WRITE_LEASE,
    WorkRunLeaseRequest,
    check_lease_conflicts,
)

from .i18n import get_web_language, text_for
from . import agent_directory_service, agent_mode_binding_service, session_service
from .runtime_manager_control_service import runtime_manager_live_control_enabled
from .runtime_scene_service import record_runtime_scene_event
from .session_service import (
    SessionBusyError,
    SessionNotFoundError,
    active_session_has_write_leases,
    get_active_session_detail,
    create_supervised_agent_session,
    get_session_detail,
    get_session_turn_completion_snapshot,
    has_running_sessions,
    list_active_session_work_runs,
    request_stop_session_turn,
    submit_session_message,
)
from .supervised_control_service import get_active_supervised_run
from .supervised_worktree_evolution_service import (
    get_active_supervised_worktree_run,
    start_supervised_worktree_run,
)
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_STATE_PATH = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "ui_runtime_state.json")
ROLLBACK_ROOT = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "web_self_evolution")
_RUN_STATE_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-self-evolution")
_RUN_STATES: dict[str, dict[str, Any]] = {}
_RUN_INTERNALS: dict[str, dict[str, Any]] = {}
_ACTIVE_RUN_ID: str | None = None
_RUN_STREAM_HEARTBEAT_SECONDS = 15.0
_RUN_STREAM_POLL_SECONDS = 2.0
_RUN_STREAM_QUEUE_SIZE = 8
_RUN_SUBSCRIBERS_LOCK = threading.Lock()
_RUN_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_RUN_EXECUTING_STATUSES = {"queued", "running", "stopping"}
_RUN_LOCKED_STATUSES = {"queued", "running", "stopping", "paused"}
_RUN_FINAL_STATUSES = {"done", "failed", "cancelled"}
_OBSERVATION_OPERATOR_TERMINAL_STATUSES = {"terminated", "cancelled", "stopped"}
_OBSERVATION_RUN_STATE_LOCK = threading.RLock()
_OBSERVATION_RUNS: dict[str, dict[str, Any]] = {}
_ACTIVE_OBSERVATION_RUN_ID: str = ""
_MANAGER_CONTROL_KEY = "runtimeManagerControl"
SELF_OBSERVATION_MIN_DURATION_SECONDS = 30
SELF_OBSERVATION_MAX_DURATION_SECONDS = 3600
_SELF_OBSERVATION_FORBIDDEN_REQUEST_FIELDS = (
    "allowedTools",
    "tools",
    "toolRequests",
    "requestedTools",
    "dynamicTools",
    "temporaryAuthorization",
    "temporaryToolAuthorization",
    "toolPolicy",
    "permissions",
    "writeLeases",
    "readScopes",
    "writeScopes",
    "mutationAccess",
)
SELF_EVOLUTION_AGENT_ROLES: tuple[dict[str, str], ...] = (
    {
        "role": "executor",
        "label": "自进化执行 Agent",
        "profileId": "primary",
        "promptTemplateId": "prompt-self-executor",
    },
    {
        "role": "reviewer",
        "label": "自进化评审 Agent",
        "profileId": "primary",
        "promptTemplateId": "prompt-self-reviewer",
    },
    {
        "role": "summarizer",
        "label": "自进化总结 Agent",
        "profileId": "primary",
        "promptTemplateId": "prompt-self-summarizer",
    },
)
_SELF_EVOLUTION_RISKY_WRITE_TEXT_MARKERS = (
    "修改",
    "修复",
    "实现",
    "新增",
    "删除",
    "重构",
    "提交",
    "继续修",
    "继续做",
    "动手",
)
_SELF_EVOLUTION_RISKY_WRITE_TOKEN_MARKERS = (
    "apply",
    "edit",
    "modify",
    "fix",
    "implement",
    "refactor",
    "commit",
    "delete",
    "patch",
    "merge",
    "install",
)
_SELF_EVOLUTION_RISKY_WRITE_MODES = {
    "coding",
    "code",
    "edit",
    "write",
    "worktree_write",
    "risky_write",
    "mutation",
    "mutating",
    "agent",
}
_SELF_EVOLUTION_RISKY_RISK_PROFILES = {
    "medium",
    "high",
    "write",
    "worktree_write",
    "risky_write",
    "mutation",
    "mutating",
}


class SelfEvolutionRunBusyError(RuntimeError):
    """Raised when a self-evolution run is already active."""


class SelfEvolutionRunValidationError(ValueError):
    """Raised when an incoming self-evolution action is invalid."""


class SelfEvolutionRunNotFoundError(LookupError):
    """Raised when a requested self-evolution run cannot be found."""


def _lifecycle_string(value: Any) -> str:
    return str(value or "").strip()


def _lifecycle_nested_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for nested_key in ("id", "taskId", "path", "root"):
            nested = _lifecycle_string(value.get(nested_key))
            if nested:
                return nested
    return ""


def _trusted_lifecycle_task_id(snapshot: dict[str, Any], fallback: str) -> str:
    for key in ("sourceTaskId", "taskId", "currentTaskId"):
        value = _lifecycle_nested_string(snapshot, key)
        if value:
            return value
    for key in ("task", "activeTask"):
        value = _lifecycle_nested_string(snapshot, key)
        if value:
            return value
    return fallback


def _trusted_lifecycle_worktree(snapshot: dict[str, Any]) -> str:
    for key in ("sourceWorktree", "worktree", "worktreeRoot", "workspaceRoot", "projectRoot"):
        value = _lifecycle_nested_string(snapshot, key)
        if value:
            return value
    artifacts = snapshot.get("artifacts") if isinstance(snapshot.get("artifacts"), dict) else {}
    for key in ("sourceWorktree", "worktree", "worktreeRoot", "workspaceRoot", "projectRoot"):
        value = _lifecycle_nested_string(artifacts, key)
        if value:
            return value
    return str(PROJECT_ROOT)


def _record_lifecycle_intent_decision(
    *,
    action: str,
    run_id: str,
    reason: str,
    decision: str,
    outcome: str,
    snapshot: dict[str, Any] | None = None,
    detail: str = "",
) -> None:
    rollback = snapshot.get("rollback") if isinstance(snapshot, dict) and isinstance(snapshot.get("rollback"), dict) else {}
    fields = {
        "action": action,
        "reason": reason[:200],
        "decision": decision,
        "detail": detail[:240],
        "status": _lifecycle_string((snapshot or {}).get("status")) if isinstance(snapshot, dict) else "",
        "rollbackStatus": _lifecycle_string(rollback.get("status")),
    }
    _record_self_scene_event(
        "lifecycle_intent",
        f"self_evolution_run.lifecycle_intent.{decision}",
        run_id=run_id,
        message=f"Self-evolution lifecycle intent {decision}.",
        level="error" if outcome == "failed" else "info",
        outcome=outcome,
        fields=fields,
        lifecycle=True,
    )


def _require_lifecycle_run_snapshot(action: str, run_id: str, reason: str) -> dict[str, Any]:
    normalized = _lifecycle_string(run_id)
    if not normalized:
        _record_lifecycle_intent_decision(
            action=action,
            run_id="",
            reason=reason,
            decision="rejected",
            outcome="failed",
            detail="missing_run_id",
        )
        raise SelfEvolutionRunValidationError(
            text_for(get_web_language(), zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )
    snapshot = get_self_evolution_run_snapshot(normalized)
    if snapshot is None:
        _record_lifecycle_intent_decision(
            action=action,
            run_id=normalized,
            reason=reason,
            decision="rejected",
            outcome="failed",
            detail="run_not_found",
        )
        raise SelfEvolutionRunNotFoundError(
            text_for(get_web_language(), zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )
    return snapshot


def _validate_lifecycle_action_state(action: str, snapshot: dict[str, Any], reason: str) -> None:
    run_id = _lifecycle_string(snapshot.get("runId"))
    status = _lifecycle_string(snapshot.get("status")).lower()
    rollback = snapshot.get("rollback") if isinstance(snapshot.get("rollback"), dict) else {}
    rollback_status = _lifecycle_string(rollback.get("status")).lower()
    if action == "restart_after_apply":
        if status != "done" or rollback_status != "available":
            _record_lifecycle_intent_decision(
                action=action,
                run_id=run_id,
                reason=reason,
                decision="rejected",
                outcome="failed",
                snapshot=snapshot,
                detail="apply_or_rollback_not_ready",
            )
            raise SelfEvolutionRunValidationError(
                text_for(
                    get_web_language(),
                    zh="只有已完成且具备可用回滚清单的自进化记录才能请求应用后重启。",
                    en="restart_after_apply requires a completed self-evolution run with an available rollback manifest.",
                )
            )
        return
    if action == "resume_self_evolution":
        if status != "paused":
            _record_lifecycle_intent_decision(
                action=action,
                run_id=run_id,
                reason=reason,
                decision="rejected",
                outcome="failed",
                snapshot=snapshot,
                detail="run_not_paused",
            )
            raise SelfEvolutionRunValidationError(
                text_for(
                    get_web_language(),
                    zh="只有已暂停的自进化记录才能请求继续。",
                    en="resume_self_evolution requires a paused self-evolution run.",
                )
            )


def _runtime_manager_live_control_enabled() -> bool:
    return runtime_manager_live_control_enabled(PROJECT_ROOT)


def _ensure_runtime_manager_daemon() -> None:
    from core.runtime_manager.daemon import ensure_daemon_running

    ensure_daemon_running()


def request_lifecycle_intent(*, action: str, reason: str, run_id: str, task_id: str, worktree: str) -> dict[str, Any]:
    normalized_action = _lifecycle_string(action)
    normalized_reason = _lifecycle_string(reason)
    snapshot = _require_lifecycle_run_snapshot(normalized_action, run_id, normalized_reason)
    _validate_lifecycle_action_state(normalized_action, snapshot, normalized_reason)
    trusted_run_id = _lifecycle_string(snapshot.get("runId")) or _lifecycle_string(run_id)
    trusted_task_id = _trusted_lifecycle_task_id(snapshot, _lifecycle_string(task_id))
    trusted_worktree = _trusted_lifecycle_worktree(snapshot)
    _record_lifecycle_intent_decision(
        action=normalized_action,
        run_id=trusted_run_id,
        reason=normalized_reason,
        decision="validated",
        outcome="succeeded",
        snapshot=snapshot,
    )
    result = launcher_service.submit_lifecycle_intent(
        {
            "action": normalized_action,
            "reason": normalized_reason,
            "idempotencyKey": f"{trusted_run_id}:{normalized_action}",
        },
        actor_context={
            "actorType": "self_evolution_agent",
            "actorId": "self-evolution",
            "sourceRunId": trusted_run_id,
            "sourceTaskId": trusted_task_id,
            "sourceWorktree": trusted_worktree,
        },
    )
    result = {
        **result,
        "sourceRunId": trusted_run_id,
        "sourceTaskId": trusted_task_id,
        "sourceWorktree": trusted_worktree,
    }
    _record_lifecycle_intent_decision(
        action=normalized_action,
        run_id=trusted_run_id,
        reason=normalized_reason,
        decision=str(result.get("status") or "submitted"),
        outcome="failed" if str(result.get("status") or "") == "rejected" else "succeeded",
        snapshot=snapshot,
        detail=str(result.get("intentId") or ""),
    )
    return result


def _map_runtime_manager_error(message: str, error_type: str) -> Exception:
    normalized = str(error_type or "").strip()
    if normalized == "SelfEvolutionRunBusyError":
        return SelfEvolutionRunBusyError(message)
    if normalized == "SelfEvolutionRunNotFoundError":
        return SelfEvolutionRunNotFoundError(message)
    return SelfEvolutionRunValidationError(message)


def _payload_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "no", "off", "none", "null"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _payload_bool(payload: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if _payload_truthy(payload.get(key)):
            return True
    return False


def _payload_normalized_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip().lower()
        if value:
            return value.replace("-", "_")
    return ""


def _text_has_risky_write_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    compact = "".join(lowered.split())
    if any(marker in compact for marker in _SELF_EVOLUTION_RISKY_WRITE_TEXT_MARKERS):
        return True
    for marker in _SELF_EVOLUTION_RISKY_WRITE_TOKEN_MARKERS:
        if re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", lowered):
            return True
    return False


def _self_evolution_worktree_isolation_reason(payload: dict[str, Any], goal: str) -> str:
    data = payload if isinstance(payload, dict) else {}
    if _payload_bool(data, "writeIntent", "requiresWorktreeIsolation"):
        return "explicit_write_intent"

    mode = _payload_normalized_value(data, "mode", "turnMode", "intent", "toolMode", "tool_calling_mode")
    if mode in _SELF_EVOLUTION_RISKY_WRITE_MODES:
        return f"mode:{mode}"

    risk_profile = _payload_normalized_value(data, "riskProfile", "risk_level", "riskLevel")
    if risk_profile in _SELF_EVOLUTION_RISKY_RISK_PROFILES:
        return f"risk:{risk_profile}"

    if _text_has_risky_write_marker(goal):
        return "goal_write_marker"
    return ""


def _raise_if_self_evolution_requires_worktree_isolation(payload: dict[str, Any], goal: str, *, lang: str) -> None:
    reason = _self_evolution_worktree_isolation_reason(payload, goal)
    if not reason:
        return
    _record_self_scene_event(
        "control",
        "self_evolution_run.start.blocked_requires_worktree",
        run_id="",
        message="Self-evolution start blocked because risky writes require worktree isolation.",
        level="warning",
        outcome="blocked",
        fields={
            "reason": reason,
            "goalPreview": str(goal or "")[:160],
            "candidateOnlyEntryPoint": True,
            "requiresWorktreeIsolation": True,
        },
        lifecycle=True,
    )
    raise SelfEvolutionRunValidationError(
        text_for(
            lang,
            zh=(
                "这条 self-evolution 目标看起来需要 risky write。主工作树里的 self-evolution "
                "只允许只读观察、经验/反思记录和候选生成；请改用 worktree isolation / supervised worktree "
                "进化路径，并在合并前回到监督线 review。"
            ),
            en=(
                "This self-evolution goal appears to require risky writes. Main-worktree self evolution "
                "is limited to read-only observation, experience/reflection records, and candidate generation; "
                "use a worktree-isolated / supervised worktree path and review before merge."
            ),
        )
    )


def start_self_evolution_worktree_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Route every self-evolution goal through a reviewed candidate worktree."""

    lang = get_web_language()
    contract = get_workbench_contract()
    availability = contract.get("modeAvailability") if isinstance(contract.get("modeAvailability"), dict) else {}
    if not bool(availability.get("self_evolution")) or not bool(availability.get("supervised_evolution")):
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="需要同时启用 self_evolution 和 supervised_evolution，才能把 risky write 转入监督工作树。",
                en="Both self_evolution and supervised_evolution must be enabled before delegating risky writes to a supervised worktree.",
            )
        )

    data = payload if isinstance(payload, dict) else {}
    goal = str(data.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    reason = _self_evolution_worktree_isolation_reason(data, goal) or "self_evolution_worktree_default"

    delegated_payload = {
        "sourceKind": str(data.get("sourceKind") or "bundle").strip() or "bundle",
        "datasetName": str(data.get("datasetName") or "").strip(),
        "datasetLimit": data.get("datasetLimit"),
        "bundleName": str(data.get("bundleName") or "").strip(),
        "keepWorktree": True,
        "mode": str(data.get("mode") or "manual").strip() or "manual",
        "executionMode": str(data.get("executionMode") or "simulation").strip() or "simulation",
        "confirmRealLlmCost": bool(data.get("confirmRealLlmCost")),
        "requestSource": "api:evolution.self.worktree-runs",
        "uiRoute": str(data.get("uiRoute") or "/evolution?track=self").strip() or "/evolution?track=self",
        "initiator": "self_evolution_risky_write",
        "clientAction": "start_self_evolution_worktree_run",
        "selfEvolutionGoal": goal,
        "selfEvolutionRiskReason": reason,
        "requiresSupervisedReview": True,
        "reviewReason": "Self-evolution candidate must return to human review before merge.",
    }
    snapshot = start_supervised_worktree_run(delegated_payload)
    _record_self_scene_event(
        "control",
        "self_evolution_run.worktree_delegated",
        run_id=str(snapshot.get("runId") or ""),
        message="Risky self-evolution write delegated to supervised worktree run.",
        outcome="succeeded",
        fields={
            "riskReason": reason,
            "goalPreview": goal[:160],
            "supervisedWorktreeRunId": str(snapshot.get("runId") or ""),
            "requiresSupervisedReview": True,
        },
        lifecycle=True,
    )
    return snapshot
def _record_self_scene_event(
    phase: str,
    event_code: str,
    *,
    run_id: str = "",
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    event_fields: dict[str, Any] = {"runId": str(run_id or "").strip()}
    if fields:
        event_fields.update(fields)
    try:
        record_runtime_scene_event(
            "self_evolution_run",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            child_log_path=_self_child_log_path(run_id) if child_log_payload is not None else "",
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _self_child_log_path(run_id: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(run_id or "").strip()
    ).strip("._-")
    return f"agent/self_evolution_runs/{normalized or 'run'}.jsonl"


def ensure_self_evolution_agent_instances() -> list[dict[str, Any]]:
    """Ensure self-evolution fixed roles are persistent AgentInstances."""

    project_root = Path(PROJECT_ROOT).resolve()
    previous_session_root = session_service.PROJECT_ROOT
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
    ensured: list[dict[str, Any]] = []
    try:
        for role in SELF_EVOLUTION_AGENT_ROLES:
            agent = _ensure_self_evolution_role(role)
            if agent:
                ensured.append(agent)
        _sync_self_evolution_mode_binding(ensured, preserve_existing_slots=True)
        return ensured
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root


def self_evolution_agent_bindings() -> dict[str, dict[str, Any]]:
    raw_slots = _raw_self_evolution_mode_slots()
    for role in [item["role"] for item in SELF_EVOLUTION_AGENT_ROLES]:
        raw_agent_id = str(raw_slots.get(role) or "").strip()
        if raw_agent_id and not agent_directory_service.get_agent(raw_agent_id, include_archived=False):
            _record_self_evolution_binding_failure(role, agent_id=raw_agent_id, reason="missing_or_archived_slot_agent")
            raise SelfEvolutionRunValidationError(
                f"Self-evolution role slot points to an archived or missing Agent: {role} ({raw_agent_id})"
            )
    ensure_self_evolution_agent_instances()
    payload = agent_mode_binding_service.get_mode_bindings_payload()
    mode = (payload.get("modes") or {}).get("self_evolution")
    slots = mode.get("slots") if isinstance(mode, dict) else {}
    bindings: dict[str, dict[str, Any]] = {}
    for role in [item["role"] for item in SELF_EVOLUTION_AGENT_ROLES]:
        stale_warning = _self_evolution_slot_warning(payload, role)
        if stale_warning:
            agent_id = str(stale_warning.get("agentId") or "").strip()
            _record_self_evolution_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SelfEvolutionRunValidationError(
                f"Self-evolution role slot points to an archived or missing Agent: {role} ({agent_id or 'unknown'})"
            )
        agent_id = str((slots or {}).get(role) or "").strip()
        if not agent_id:
            _record_self_evolution_binding_failure(role, agent_id="", reason="missing_slot_agent")
            raise SelfEvolutionRunValidationError(f"Self-evolution role slot is not configured: {role}")
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            _record_self_evolution_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SelfEvolutionRunValidationError(f"Self-evolution role slot points to an archived or missing Agent: {role}")
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        llm_bindings = agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings"))
        dialogue_model_id = agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings})
        bindings[role] = {
            "agentId": str(agent.get("agentId") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "profileId": str(agent.get("profileId") or "").strip(),
            "llmBindings": llm_bindings,
            "dialogueModelId": dialogue_model_id,
            "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "workspacePath": str(agent.get("workspacePath") or "").strip(),
            "role": role,
            "roleLabel": str(metadata.get("selfEvolutionRoleLabel") or role).strip(),
        }
    return bindings


def _raw_self_evolution_mode_slots() -> dict[str, str]:
    path = agent_mode_binding_service.mode_binding_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    for item in payload.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("mode") or "").strip() != "self_evolution":
            continue
        slots = item.get("slots") if isinstance(item.get("slots"), dict) else {}
        return {str(key): str(value or "").strip() for key, value in slots.items()}
    return {}


def _self_evolution_slot_warning(mode_payload: dict[str, Any], role: str) -> dict[str, str] | None:
    expected_field = f"slots.{role}"
    for warning in mode_payload.get("repairWarnings") or []:
        if not isinstance(warning, dict):
            continue
        if str(warning.get("mode") or "").strip() != "self_evolution":
            continue
        if str(warning.get("field") or "").strip() == expected_field:
            return {str(key): str(value or "") for key, value in warning.items()}
    return None


def _record_self_evolution_binding_failure(role: str, *, agent_id: str, reason: str) -> None:
    try:
        record_runtime_scene_event(
            "agent_runtime",
            "self_evolution",
            "agent_runtime.resolve_failed",
            message="Self-evolution role Agent resolution failed",
            level="error",
            outcome="failed",
            fields={
                "mode": "self_evolution",
                "slot": str(role or "").strip(),
                "roleKey": str(role or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": "ModeBinding.slots",
                "reason": str(reason or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _ensure_self_evolution_role(role: dict[str, str]) -> dict[str, Any] | None:
    role_key = str(role.get("role") or "").strip()
    label = str(role.get("label") or role_key).strip() or role_key
    profile_id = str(role.get("profileId") or "primary").strip() or "primary"
    prompt_template_id = str(role.get("promptTemplateId") or "").strip()
    seed_llm_bindings = session_service.llm_bindings_for_profile_id(profile_id)
    existing = _find_agent_by_self_evolution_role(role_key)
    if _self_evolution_role_slot_excluded(role_key):
        _record_self_evolution_agent_sync_skipped(
            role_key,
            agent_id=str((existing or {}).get("agentId") or "").strip(),
            reason="mode_binding_slot_excluded",
        )
        return None
    if not existing:
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=seed_llm_bindings,
            created_by="self_evolution",
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise RuntimeError(f"Self-evolution agent was not created for role: {role_key}")
    if str(existing.get("status") or "active").strip() == "archived":
        _record_self_evolution_agent_sync_skipped(
            role_key,
            agent_id=str(existing.get("agentId") or "").strip(),
            reason="agent_archived",
        )
        return None
    existing_llm_bindings = agent_directory_service.normalize_agent_llm_bindings(existing.get("llmBindings"))
    existing_dialogue_model_id = agent_directory_service.agent_dialogue_model_id({"llmBindings": existing_llm_bindings})
    desired_llm_bindings = existing_llm_bindings if existing_dialogue_model_id else seed_llm_bindings
    metadata = dict(existing.get("metadata") or {})
    expected_metadata = {
        "agentMode": "self_evolution",
        "configSurface": "model_config",
        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN,
        "fixedRole": True,
        "showInSessionIndex": False,
        "selfEvolutionRole": role_key,
        "selfEvolutionRoleLabel": label,
        "directSessionVisibility": "active_session",
        "functionalDisplayName": label,
    }
    if (
        str((metadata or {}).get("functionalDisplayName") or "").strip() != label
        or str(existing.get("primaryMode") or "").strip() != "self_evolution"
        or str(existing.get("roleKey") or "").strip() != role_key
        or not existing_dialogue_model_id
        or str(existing.get("promptTemplateId") or "").strip() != prompt_template_id
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
    ):
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            display_name=label,
            llm_bindings=desired_llm_bindings,
            primary_mode="self_evolution",
            role_key=role_key,
            prompt_template_id=prompt_template_id,
            metadata=expected_metadata,
            status="active",
            preserve_generated_display_name=True,
        )
    return existing


def _self_evolution_role_slot_excluded(role: str) -> bool:
    normalized = str(role or "").strip()
    if not normalized:
        return False
    try:
        payload = agent_mode_binding_service.get_mode_bindings_payload()
        mode = (payload.get("modes") or {}).get("self_evolution") or {}
        excluded_slots = {str(item or "").strip() for item in list(mode.get("excludedSlots") or [])}
        return normalized in excluded_slots
    except Exception:
        return False


def _record_self_evolution_agent_sync_skipped(role: str, *, agent_id: str, reason: str) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            "self_evolution.agent_instance.sync_skipped",
            message="Self-evolution fixed role Agent sync skipped",
            level="info",
            outcome="skipped",
            fields={
                "selfEvolutionRole": str(role or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "reason": str(reason or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _find_agent_by_self_evolution_role(role: str) -> dict[str, Any] | None:
    normalized = str(role or "").strip()
    if not normalized:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("selfEvolutionRole") or "").strip() == normalized:
            return agent
        if str(agent.get("primaryMode") or "").strip() == "self_evolution" and str(agent.get("roleKey") or "").strip() == normalized:
            return agent
    return None


def _sync_self_evolution_mode_binding(agents: list[dict[str, Any]], *, preserve_existing_slots: bool = False) -> None:
    active_agents = [
        agent
        for agent in agents
        if str(agent.get("agentId") or "").strip()
        and str(agent.get("status") or "active").strip() != "archived"
    ]
    active_agent_ids = [str(agent.get("agentId") or "").strip() for agent in active_agents]
    slots: dict[str, str] = {}
    if preserve_existing_slots:
        try:
            payload = agent_mode_binding_service.get_mode_bindings_payload()
            existing = ((payload.get("modes") or {}).get("self_evolution") or {}).get("slots")
            if isinstance(existing, dict):
                slots.update({str(key): str(value or "").strip() for key, value in existing.items()})
        except Exception:
            slots = {}
    for agent in active_agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("selfEvolutionRole") or agent.get("roleKey") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if role and agent_id and not slots.get(role):
            slots[role] = agent_id
    if not active_agent_ids:
        return
    agent_mode_binding_service.update_mode_binding(
        "self_evolution",
        default_agent_id=active_agent_ids[0],
        available_agent_ids=active_agent_ids,
        slots=slots,
    )


def _compact_agent_bindings(bindings: dict[str, Any]) -> dict[str, dict[str, str]]:
    compact: dict[str, dict[str, str]] = {}
    for role, binding in (bindings or {}).items():
        if not isinstance(binding, dict):
            continue
        compact[str(role)] = {
            "agentId": str(binding.get("agentId") or "").strip(),
            "profileId": str(binding.get("profileId") or "").strip(),
            "dialogueModelId": str(binding.get("dialogueModelId") or "").strip(),
            "promptTemplateId": str(binding.get("promptTemplateId") or "").strip(),
        }
    return compact


def _self_role_binding(bindings: dict[str, Any], role: str) -> dict[str, Any]:
    binding = bindings.get(role) if isinstance(bindings, dict) else {}
    return dict(binding or {}) if isinstance(binding, dict) else {}


def _self_evolution_agent_config(binding: dict[str, Any]) -> Any | None:
    agent_id = str((binding or {}).get("agentId") or "").strip()
    if not agent_id:
        return None
    try:
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            return None
        return session_service._session_agent_config_for_llm_slot(agent, "dialogue")
    except Exception:
        return None


def _optional_scene_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _self_snapshot_event_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    return {
        "status": str(payload.get("status") or "").strip(),
        "phase": str(payload.get("phase") or "").strip(),
        "runtimeStatus": str(payload.get("runtimeStatus") or "").strip(),
        "toolCallCount": _optional_scene_int(payload.get("toolCallCount")),
        "lastToolName": str(payload.get("lastToolName") or "").strip(),
        "controlAction": str(payload.get("controlAction") or "").strip(),
        "stopReason": str(payload.get("stopReason") or "").strip(),
        "error": str(payload.get("error") or "").strip(),
        "updatedAt": str(payload.get("updatedAt") or "").strip(),
        "finishedAt": str(payload.get("finishedAt") or "").strip(),
        "rollbackStatus": str(rollback.get("status") or "").strip(),
        "rollbackManifestPath": str(rollback.get("manifestPath") or "").strip(),
    }


def get_active_self_evolution_run() -> dict[str, Any] | None:
    """Return the current bounded self-evolution snapshot when it is still active or paused."""

    with _RUN_STATE_LOCK:
        payload = _current_active_run_locked()
        if payload is None:
            return None
        if str(payload.get("status") or "").strip().lower() not in _RUN_LOCKED_STATUSES:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def get_latest_self_evolution_run() -> dict[str, Any] | None:
    """Return the latest known bounded self-evolution run snapshot."""

    with _RUN_STATE_LOCK:
        payload = _latest_run_locked()
        if payload is None:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def get_self_evolution_run_snapshot(run_id: str) -> dict[str, Any] | None:
    """Return any known self-evolution run snapshot by id."""

    normalized = str(run_id or "").strip()
    if not normalized:
        return None
    with _RUN_STATE_LOCK:
        payload = _RUN_STATES.get(normalized)
        if payload is None:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def stream_self_evolution_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    """Yield SSE snapshots for one self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    snapshot = initial_snapshot or get_self_evolution_run_snapshot(normalized)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_RUN_STREAM_QUEUE_SIZE)
    _register_run_subscriber(normalized, subscriber)
    last_signature = _snapshot_signature(snapshot)
    last_keepalive = time.monotonic()
    try:
        terminal = _is_terminal_run_snapshot(snapshot)
        yield _encode_sse_event(
            "self_evolution_run",
            {
                "type": "self_evolution_run",
                "runId": normalized,
                "snapshot": snapshot,
                "terminal": terminal,
            },
        )
        if terminal:
            return

        while True:
            try:
                event = subscriber.get(timeout=_RUN_STREAM_POLL_SECONDS)
            except queue.Empty:
                latest = get_self_evolution_run_snapshot(normalized)
                if latest is not None:
                    signature = _snapshot_signature(latest)
                    if signature != last_signature:
                        last_signature = signature
                        terminal = _is_terminal_run_snapshot(latest)
                        yield _encode_sse_event(
                            "self_evolution_run",
                            {
                                "type": "self_evolution_run",
                                "runId": normalized,
                                "snapshot": latest,
                                "terminal": terminal,
                            },
                        )
                        last_keepalive = time.monotonic()
                        if terminal:
                            break
                        continue
                if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
                    yield ": keep-alive\n\n"
                    last_keepalive = time.monotonic()
                continue

            snapshot_payload = event.get("snapshot") if isinstance(event.get("snapshot"), dict) else None
            if snapshot_payload is not None:
                last_signature = _snapshot_signature(snapshot_payload)
            yield _encode_sse_event(str(event.get("type") or "self_evolution_run"), event)
            last_keepalive = time.monotonic()
            if bool(event.get("terminal")):
                break
    finally:
        _unregister_run_subscriber(normalized, subscriber)


def has_active_self_evolution_run() -> bool:
    """Report whether a bounded web self-evolution run is active or paused."""

    with _RUN_STATE_LOCK:
        payload = _current_active_run_locked()
        if payload is None:
            return False
        return str(payload.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES


def start_self_evolution_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start one bounded self-evolution pass from the web workbench."""

    global _ACTIVE_RUN_ID
    lang = get_web_language()
    contract = get_workbench_contract()
    if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="配置里没有启用 self_evolution，当前不能从网页启动这一轮。",
                en="The current config does not enable self_evolution, so the web surface cannot launch this pass.",
            )
        )

    goal = str(payload.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    _raise_if_self_evolution_requires_worktree_isolation(payload, goal, lang=lang)
    if active_session_has_write_leases():
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前有写入型网页会话还在运行，请等这一轮结束后再启动自进化。",
                en="A write-capable web chat turn is still running. Wait for it to finish before launching self evolution.",
            )
        )
    _raise_if_self_lease_conflict(lang=lang)

    active_supervised = get_active_supervised_run()
    if _supervised_run_blocks_self_evolution(active_supervised):
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前已有监督任务在运行，请等监督任务结束后再启动自进化。",
                en="A supervised run is already active. Wait for it to finish before launching self evolution.",
            )
        )
    active_supervised_worktree = get_active_supervised_worktree_run()
    if _supervised_run_blocks_self_evolution(active_supervised_worktree):
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前已有监督工作树进化在运行，请等这一轮结束后再启动自进化。",
                en="A supervised worktree evolution run is already active. Wait for it to finish before launching self evolution.",
            )
        )

    with _RUN_STATE_LOCK:
        active_id = _ACTIVE_RUN_ID
        if active_id and _RUN_STATES.get(active_id):
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已经有一轮网页自进化在运行或暂停中，请先继续或终止这一轮。",
                    en="A web self-evolution pass is already active or paused. Resume or terminate it before starting another one.",
            )
        )

    agent_bindings = self_evolution_agent_bindings()
    run_id = f"web-self-{uuid4().hex[:12]}"
    started_at = _now_timestamp()
    preflight = _capture_preflight_state(run_id)
    state = {
        "runId": run_id,
        "runKind": "self_evolution_run",
        "leases": [EVOLUTION_TRANSACTION_LEASE, WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE],
        "goal": goal,
        "status": "queued",
        "phase": "queued",
        "startedAt": started_at,
        "updatedAt": started_at,
        "finishedAt": "",
        "latestMessage": text_for(
            lang,
            zh="已加入网页自进化队列，准备开始这一轮。",
            en="The self-evolution pass is queued and preparing to start.",
        ),
        "currentGoal": goal,
        "lastToolName": "",
        "runtimeStatus": "idle",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [
            _build_run_message(
                run_id=run_id,
                role="user",
                content=goal,
                timestamp=started_at,
            )
        ],
        "agentBindings": agent_bindings,
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": _initial_rollback_state(lang, base_rev=str(preflight.get("baseRev") or "")),
        "artifacts": {
            "runDir": str(preflight.get("runDir") or ""),
            "backupDir": str(preflight.get("backupDir") or ""),
            "manifestPath": str(preflight.get("manifestPath") or ""),
            "baseRev": str(preflight.get("baseRev") or ""),
        },
        _MANAGER_CONTROL_KEY: _build_manager_control_payload(),
    }
    context = {
        "runId": run_id,
        "goal": goal,
        "startedAt": started_at,
        "preflight": preflight,
        "agentBindings": agent_bindings,
    }

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is not None and str(active.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES:
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已有自进化任务在运行或暂停中，请先继续或终止这一轮。",
                    en="A self-evolution pass is already active or paused. Resume or terminate it before starting another one.",
                )
            )
        _RUN_STATES[run_id] = state
        _RUN_INTERNALS[run_id] = {
            "preflight": preflight,
            "carryover": {},
        }
        _ACTIVE_RUN_ID = run_id
    _publish_run_snapshot(run_id, record_scene_state=True)

    try:
        _RUN_EXECUTOR.submit(_run_self_evolution_turn, context)
    except Exception as exc:
        _mark_run_failed(
            run_id,
            text_for(
                lang,
                zh=f"无法启动自进化：{type(exc).__name__}: {exc}",
                en=f"Failed to start self evolution: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_self_evolution_run_snapshot(run_id) or state


def request_pause_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Request a graceful pause for one active self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )

    now = _now_timestamp()
    immediate_snapshot: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            raise SelfEvolutionRunNotFoundError(
                text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
            )
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_FINAL_STATUSES or status == "paused":
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status == "stopping":
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status == "queued":
            current.update(
                {
                    "status": "paused",
                    "phase": "paused",
                    "updatedAt": now,
                    "runtimeStatus": "idle",
                    "latestMessage": text_for(
                        lang,
                        zh="这轮网页自进化已在启动前暂停，可随时继续。",
                        en="This web self-evolution pass was paused before it started and can be resumed any time.",
                    ),
                    "summary": text_for(
                        lang,
                        zh="用户在启动前请求暂停这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to pause before start.",
                    ),
                    "stopReason": text_for(
                        lang,
                        zh="用户请求暂停这一轮。",
                        en="The operator requested this pass to pause.",
                    ),
                    "controlAction": "",
                    "controlRequestedAt": "",
                }
            )
            _append_run_message_locked(
                current,
                role="assistant",
                content=current["latestMessage"],
                timestamp=now,
            )
            immediate_snapshot = _decorate_runtime_snapshot(_clone_payload(current))
        else:
            current.update(
                {
                    "status": "stopping",
                    "phase": "stopping",
                    "updatedAt": now,
                    "runtimeStatus": "pausing",
                    "latestMessage": text_for(
                        lang,
                        zh="已请求暂停这一轮，等待当前安全点收口。",
                        en="A pause was requested. Waiting for the current safe point to pause this pass.",
                    ),
                    "stopReason": text_for(
                        lang,
                        zh="用户请求暂停这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to pause.",
                    ),
                    "controlAction": "pause",
                    "controlRequestedAt": now,
                }
            )
    if immediate_snapshot is not None:
        _publish_run_snapshot(normalized, terminal=True, record_scene_state=True)
        return immediate_snapshot

    _publish_run_snapshot(normalized, record_scene_state=True)
    get_session_state().note_scope_completion(
        text_for(
            lang,
            zh="网页控制台请求暂停当前自进化，请在当前安全点收口并保留可继续上下文。",
            en="The web control requested a pause. Close the current safe point and preserve resumable context for this self-evolution pass.",
        )
    )
    return get_self_evolution_run_snapshot(normalized) or {}


def resume_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Resume one paused self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )
    if active_session_has_write_leases():
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前有写入型网页会话还在运行，请等这一轮结束后再继续自进化。",
                en="A write-capable web chat turn is still running. Wait for it to finish before resuming self evolution.",
            )
        )
    _raise_if_self_lease_conflict(lang=lang)
    active_supervised = get_active_supervised_run()
    if _supervised_run_blocks_self_evolution(active_supervised):
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前已有监督任务在运行，请等监督任务结束后再继续自进化。",
                en="A supervised run is already active. Wait for it to finish before resuming self evolution.",
            )
        )

    now = _now_timestamp()
    state_snapshot: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            raise SelfEvolutionRunNotFoundError(
                text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
            )
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_EXECUTING_STATUSES:
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status != "paused":
            raise SelfEvolutionRunValidationError(
                text_for(
                    lang,
                    zh="只有已暂停的自进化任务才能继续。",
                    en="Only a paused self-evolution pass can be resumed.",
                )
            )
        current.update(
            {
                "status": "queued",
                "phase": "queued",
                "updatedAt": now,
                "runtimeStatus": "idle",
                "latestMessage": text_for(
                    lang,
                    zh="这一轮网页自进化已恢复排队，准备继续。",
                    en="This web self-evolution pass is queued to resume.",
                ),
                "summary": "",
                "error": "",
                "cancelRequested": False,
                "cancelRequestedAt": "",
                "stopReason": "",
                "controlAction": "",
                "controlRequestedAt": "",
                "resumeCount": max(0, int(current.get("resumeCount") or 0)) + 1,
                _MANAGER_CONTROL_KEY: _build_manager_control_payload(),
            }
        )
        _append_run_message_locked(
            current,
            role="user",
            content=_build_resume_user_message(str(current.get("goal") or "")),
            timestamp=now,
        )
        state_snapshot = _clone_payload(current)

    assert state_snapshot is not None
    _publish_run_snapshot(normalized, record_scene_state=True)
    try:
        _RUN_EXECUTOR.submit(
            _run_self_evolution_turn,
            {
                "runId": normalized,
                "goal": str(state_snapshot.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL),
            },
        )
    except Exception as exc:
        _mark_run_failed(
            normalized,
            text_for(
                lang,
                zh=f"无法继续自进化：{type(exc).__name__}: {exc}",
                en=f"Failed to resume self evolution: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_self_evolution_run_snapshot(normalized) or state_snapshot


def request_stop_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Request termination for one active or paused self-evolution run."""

    global _ACTIVE_RUN_ID
    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )

    now = _now_timestamp()
    finalize_snapshot: dict[str, Any] | None = None
    publish_terminal = False
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            stored = load_manager_run_snapshot("self", normalized)
            stored_status = str((stored or {}).get("status") or "").strip().lower()
            if stored is None or stored_status not in _RUN_LOCKED_STATUSES:
                raise SelfEvolutionRunNotFoundError(
                    text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
                )
            finalize_snapshot = _build_cancelled_file_self_run_snapshot(
                stored,
                latest_message=text_for(
                    lang,
                    zh="这轮网页自进化已终止，可以重新开始新的一轮。",
                    en="This web self-evolution pass has been terminated, and a new pass can be started now.",
                ),
                summary=text_for(
                    lang,
                    zh="用户请求终止这一轮网页自进化。",
                    en="The operator requested this bounded self-evolution pass to terminate.",
                ),
                stop_reason=text_for(
                    lang,
                    zh="用户请求终止这一轮。",
                    en="The operator requested this pass to terminate.",
                ),
            )
            return _decorate_runtime_snapshot(_clone_payload(finalize_snapshot))
        status = str(current.get("status") or "").strip().lower()
        if current is not None and status in _RUN_FINAL_STATUSES:
            return _decorate_runtime_snapshot(_clone_payload(current))
        if current is not None and status in {"queued", "paused"}:
            current.update(
                {
                    "status": "cancelled",
                    "phase": "cancelled",
                    "updatedAt": now,
                    "finishedAt": now,
                    "runtimeStatus": "idle",
                    "latestMessage": text_for(
                        lang,
                        zh="这轮网页自进化已终止，可以重新开始新的一轮。",
                        en="This web self-evolution pass has been terminated, and a new pass can be started now.",
                    ),
                    "summary": text_for(
                        lang,
                        zh="用户请求终止这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to terminate.",
                    ),
                    "cancelRequested": True,
                    "cancelRequestedAt": now,
                    "stopReason": text_for(
                        lang,
                        zh="用户请求终止这一轮。",
                        en="The operator requested this pass to terminate.",
                    ),
                    "controlAction": "",
                    "controlRequestedAt": "",
                }
            )
            _append_run_message_locked(
                current,
                role="assistant",
                content=current["latestMessage"],
                timestamp=now,
            )
            if _ACTIVE_RUN_ID == normalized:
                _ACTIVE_RUN_ID = None
            finalize_snapshot = _clone_payload(current)
            publish_terminal = True
        elif current is not None:
            current.update(
                {
                    "status": "stopping",
                    "phase": "stopping",
                    "updatedAt": now,
                    "runtimeStatus": "stopping",
                    "latestMessage": text_for(
                        lang,
                        zh="已请求这一轮尽快收口，等待当前安全点结束。",
                        en="A termination was requested. Waiting for the current safe point to close this pass.",
                    ),
                    "cancelRequested": True,
                    "cancelRequestedAt": now,
                    "stopReason": text_for(
                        lang,
                        zh="用户请求终止这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to terminate.",
                    ),
                    "controlAction": "terminate",
                    "controlRequestedAt": now,
                }
            )
    if finalize_snapshot is not None:
        manifest = _finalize_terminal_run_snapshot(normalized)
        if manifest is not None:
            _merge_run_state(normalized, {"rollback": manifest})
        if publish_terminal:
            _publish_run_snapshot(
                normalized,
                terminal=True,
                record_scene_state=True,
                scene_clear_active=True,
            )
        return get_self_evolution_run_snapshot(normalized) or finalize_snapshot

    _publish_run_snapshot(normalized, record_scene_state=True)
    get_session_state().note_scope_completion(
        text_for(
            lang,
            zh="网页控制台请求终止当前自进化，请在当前安全点收口并停止继续扩散。",
            en="The web control requested termination. Close the current safe point and stop expanding this self-evolution pass.",
        )
    )
    return get_self_evolution_run_snapshot(normalized) or {}


def rollback_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Safely roll one finished self-evolution run back to its pre-run file state."""

    lang = get_web_language()
    state = _require_terminal_run(run_id)
    manifest = _load_rollback_manifest(state)
    rollback = manifest.get("display") if isinstance(manifest.get("display"), dict) else {}
    touched_files = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    if not touched_files:
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="这一轮没有可安全回滚的文件差异。",
                en="This run does not have any safe file diff to roll back.",
            )
        )
    rollback_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    if not rollback_entries:
        rollback_entries = touched_files
    if any(
        str(item.get("path") or "").strip() and not str(item.get("restoreSource") or "").strip()
        for item in rollback_entries
    ):
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="这轮记录缺少完整的回滚清单，当前不能自动一键回滚，请交给会话 agent 继续处理。",
                en="This run is missing a complete rollback manifest, so automatic rollback is unavailable. Hand it off to the session agent instead.",
            )
        )

    conflicts = _detect_rollback_conflicts(state, entries=rollback_entries)
    if conflicts:
        _merge_run_state(
            state["runId"],
            {
                "rollback": _build_rollback_state(
                    lang=lang,
                    status="blocked",
                    reason=text_for(
                        lang,
                        zh="这些文件在进化后又被改过了，不能自动一键回滚。",
                        en="These files changed again after the self-evolution pass, so automatic rollback is blocked.",
                    ),
                    base_rev=str(rollback.get("baseRev") or ""),
                    touched_files=touched_files,
                    conflict_files=conflicts,
                    rolled_back_at=str(rollback.get("rolledBackAt") or ""),
                )
            }
        )
        return get_self_evolution_run_snapshot(state["runId"]) or {}

    _apply_rollback_entries(state, rollback_entries)
    updated = _build_rollback_state(
        lang=lang,
        status="rolled_back",
        reason=text_for(
            lang,
            zh="已把这轮网页自进化恢复到进化前的文件状态。",
            en="This bounded self-evolution pass has been restored to its pre-run file state.",
        ),
        base_rev=str(rollback.get("baseRev") or ""),
        touched_files=touched_files,
        conflict_files=[],
        rolled_back_at=_now_timestamp(),
    )
    _merge_run_state(
        state["runId"],
        {
            "updatedAt": _now_timestamp(),
            "latestMessage": updated["reason"],
            "rollback": updated,
        }
    )
    return get_self_evolution_run_snapshot(state["runId"]) or {}


def handoff_self_evolution_run_to_session(run_id: str) -> dict[str, Any]:
    """Send or prepare a rollback handoff for the active coding session."""

    lang = get_web_language()
    state = _require_run_snapshot(run_id)
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    content = _build_session_handoff_message(state)
    active_session = get_active_session_detail()
    session_id = str((active_session or {}).get("id") or "").strip()
    if not session_id:
        return {
            "status": "ready",
            "message": text_for(
                lang,
                zh="当前没有可直接提交的会话，已为会话 agent 准备好 handoff 内容。",
                en="No active session is ready to receive this automatically. The handoff content is prepared for the session agent.",
            ),
            "sessionId": "",
            "content": content,
            "run": get_self_evolution_run_snapshot(state["runId"]),
        }

    try:
        submit_session_message(session_id, content)
    except (SessionBusyError, SessionNotFoundError):
        return {
            "status": "ready",
            "message": text_for(
                lang,
                zh="当前会话正忙，已准备好 handoff 内容，切到会话页后可继续交给 agent。",
                en="The current session is busy. The handoff content is ready to continue with the session agent on the chat page.",
            ),
            "sessionId": session_id,
            "content": content,
            "run": get_self_evolution_run_snapshot(state["runId"]),
        }

    summary = text_for(
        lang,
        zh="已把这次回滚处理请求直接交给当前会话 agent。",
        en="This rollback handoff was sent directly to the current session agent.",
    )
    _merge_run_state(state["runId"], {"updatedAt": _now_timestamp(), "latestMessage": summary})
    return {
        "status": "submitted",
        "message": summary,
        "sessionId": session_id,
        "content": content,
        "run": get_self_evolution_run_snapshot(state["runId"]),
    }


def _run_self_evolution_turn(context: dict[str, Any]) -> None:
    lang = get_web_language()
    run_id = str(context.get("runId") or "").strip()
    goal = str(context.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    initial = get_self_evolution_run_snapshot(run_id) or {}
    agent_bindings = dict(context.get("agentBindings") or initial.get("agentBindings") or {})
    initial_status = str(initial.get("status") or "").strip().lower()
    if initial_status in {"cancelled", "paused"}:
        return
    internal = _get_run_internal(run_id)
    preflight = internal.get("preflight") if isinstance(internal.get("preflight"), dict) else {}
    carryover = internal.get("carryover") if isinstance(internal.get("carryover"), dict) else {}
    total_tool_call_count = max(0, int(initial.get("toolCallCount") or 0))

    _merge_run_state(
        run_id,
        {
            "status": "running",
            "phase": "running",
            "updatedAt": _now_timestamp(),
            "runtimeStatus": "running",
            "controlAction": "",
            "controlRequestedAt": "",
            "latestMessage": text_for(
                lang,
                zh="正在执行这一轮网页自进化，现场证据和事务列表会继续刷新。",
                en="The bounded self-evolution pass is running. Evidence and transaction panels will keep refreshing.",
            ),
            "turnCount": max(0, int(initial.get("turnCount") or 0)) + 1,
        },
    )
    _record_self_scene_event(
        "turn",
        "self_evolution_run.turn.started",
        run_id=run_id,
        message="Self-evolution turn started.",
        outcome="observed",
        fields={
            "goalPreview": goal[:320],
            "hadCarryover": bool(carryover),
            "previousToolCallCount": total_tool_call_count,
            "turnCount": max(0, int(initial.get("turnCount") or 0)) + 1,
            "agentBindings": _compact_agent_bindings(agent_bindings),
        },
        child_log_payload={
            "goalPreview": goal[:320],
            "hadCarryover": bool(carryover),
            "previousToolCallCount": total_tool_call_count,
            "turnCount": max(0, int(initial.get("turnCount") or 0)) + 1,
            "agentBindings": _compact_agent_bindings(agent_bindings),
        },
        lifecycle=True,
    )
    live_refresh_stop = threading.Event()
    live_refresh_thread = threading.Thread(
        target=_self_live_refresh_loop,
        args=(run_id, live_refresh_stop),
        daemon=True,
        name=f"self-evolution-live-{run_id[:8]}",
    )
    live_refresh_thread.start()
    result: dict[str, Any] = {}
    result_status = ""
    summary = ""
    tool_call_count = 0
    try:
        executor_binding = _self_role_binding(agent_bindings, "executor")
        executor_context = build_agent_context(
            str(executor_binding.get("agentId") or ""),
            session_id=str(executor_binding.get("directSessionId") or ""),
            run_id=run_id,
        )
        runtime_context = agent_directory_service.active_agent_runtime(
            str(executor_binding.get("agentId") or ""),
            session_id=str(executor_binding.get("directSessionId") or ""),
            turn_id=run_id,
        )
        prompt = goal if carryover else _build_web_run_prompt(goal)
        turn_runtime_request = AgentTurnRuntimeRequest(
            mode="self_evolution",
            run_kind="self_evolution",
            run_id=run_id,
            session_id=str(executor_binding.get("directSessionId") or ""),
            agent_id=str(executor_binding.get("agentId") or ""),
            llm_slot="dialogue",
            model_id=str(executor_binding.get("dialogueModelId") or ""),
            cache_scope="executor",
            workspace_path=str(executor_binding.get("workspacePath") or ""),
        )
        with runtime_context:
            turn_result = run_agent_single_turn(
                AgentSingleTurnRequest(
                    mode="self_evolution",
                    workspace_path=str(executor_binding.get("workspacePath") or "") or None,
                    config=_self_evolution_agent_config(executor_binding),
                    initial_prompt=prompt,
                    carryover=carryover if isinstance(carryover, dict) else None,
                    runtime_context=executor_context.context_block,
                    static_runtime_context=executor_context.static_context_block,
                    dynamic_runtime_context=executor_context.dynamic_context_block,
                    interrupt_checker=lambda: _current_run_control_reason(run_id),
                    runtime=turn_runtime_request,
                )
            )
        result = turn_result.result
        if executor_context.agent_id:
            record_agent_turn_result(
                executor_context.agent_id,
                executor_context.session_id,
                result if isinstance(result, dict) else {},
                run_id=run_id,
            )
        result_status = str(result.get("status") or "").strip().lower()
        summary = str(result.get("summary") or "").strip()
        tool_call_count = max(0, int(result.get("tool_call_count") or 0))
        total_tool_call_count += tool_call_count
        carryover_payload: dict[str, Any] = turn_result.carryover if isinstance(turn_result.carryover, dict) else {}
        run_snapshot = get_self_evolution_run_snapshot(run_id) or {}
        control_action = str(run_snapshot.get("controlAction") or "").strip().lower()
        cancel_requested = bool(run_snapshot.get("cancelRequested"))
        assistant_message = _build_result_message(
            result=result,
            fallback=summary
            or text_for(
                lang,
                zh="这一轮网页自进化已结束。",
                en="This bounded self-evolution pass is complete.",
            ),
        )
        transcript_tool_calls = _tool_calls_from_result(result)
        last_tool_name = _last_tool_name_from_result(result)
        turn_runtime_metadata = dict(turn_result.runtime.metadata) if turn_result.runtime is not None else {}
        _record_self_scene_event(
            "turn",
            "self_evolution_run.turn.completed",
            run_id=run_id,
            message=f"Self-evolution turn completed: {result_status or 'unknown'}",
            level="error" if result_status == "failed" else "info",
            outcome="failed" if result_status == "failed" else "succeeded",
            fields={
                "resultStatus": result_status,
                "toolCallCount": tool_call_count,
                "totalToolCallCount": total_tool_call_count,
                "lastToolName": last_tool_name,
                "summaryPreview": (assistant_message or summary)[:320],
                "turnRuntime": turn_runtime_metadata,
            },
            child_log_payload={
                "resultStatus": result_status,
                "toolCallCount": tool_call_count,
                "totalToolCallCount": total_tool_call_count,
                "lastToolName": last_tool_name,
                "summaryPreview": (assistant_message or summary)[:800],
                "turnRuntime": turn_runtime_metadata,
                "toolCalls": transcript_tool_calls,
            },
            lifecycle=True,
        )
        if result_status == "failed":
            error = str(result.get("error") or summary or "").strip()
            if control_action == "pause":
                _mark_run_paused(
                    run_id,
                    summary=assistant_message or error,
                    tool_call_count=total_tool_call_count,
                    reason=text_for(
                        lang,
                        zh="这一轮已按网页请求暂停，可从当前上下文继续。",
                        en="This pass paused at the web request and can resume from the current context.",
                    ),
                    carryover=carryover_payload,
                    tool_calls=transcript_tool_calls,
                    last_tool_name=last_tool_name,
                )
                return
            if cancel_requested or control_action == "terminate":
                _mark_run_cancelled(
                    run_id,
                    summary=assistant_message or error,
                    tool_call_count=total_tool_call_count,
                    reason=text_for(
                        lang,
                        zh="已请求终止这一轮，运行在失败前收口。",
                        en="A stop was requested and this pass closed before finishing cleanly.",
                    ),
                    tool_calls=transcript_tool_calls,
                    last_tool_name=last_tool_name,
                )
                return
            _mark_run_failed(
                run_id,
                error
                or text_for(
                    lang,
                        zh="这一轮网页自进化执行失败，请检查日志。",
                        en="This web self-evolution pass failed. Check the logs for details.",
                    ),
                tool_call_count=total_tool_call_count,
                summary=assistant_message or summary,
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        if control_action == "pause":
            _mark_run_paused(
                run_id,
                summary=assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已暂停，可继续当前上下文。",
                    en="This bounded self-evolution pass is paused and can resume from the current context.",
                ),
                tool_call_count=total_tool_call_count,
                reason=text_for(
                    lang,
                    zh="这一轮已按网页请求暂停。",
                    en="This pass was paused by the web request.",
                ),
                carryover=carryover_payload,
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        if cancel_requested or control_action == "terminate" or result_status == "stopped":
            _mark_run_cancelled(
                run_id,
                summary=assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已按请求终止。",
                    en="This bounded self-evolution pass stopped as requested.",
                ),
                tool_call_count=total_tool_call_count,
                reason=text_for(
                    lang,
                    zh="这一轮已按网页请求收口。",
                    en="This pass was closed by the web stop request.",
                ),
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        finished_at = _now_timestamp()
        _merge_run_state(
            run_id,
            {
                "status": "done",
                "phase": result_status or "completed",
                "updatedAt": finished_at,
                "finishedAt": finished_at,
                "runtimeStatus": "idle",
                "latestMessage": assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已结束。",
                    en="This bounded self-evolution pass is complete.",
                ),
                "summary": assistant_message or summary,
                "toolCallCount": total_tool_call_count,
                "lastToolName": last_tool_name,
                "error": "",
                "controlAction": "",
                "controlRequestedAt": "",
                "messages": _append_run_message(
                    list(initial.get("messages") or []),
                    _build_run_message(
                        run_id=run_id,
                        role="assistant",
                        content=assistant_message
                        or text_for(
                            lang,
                            zh="这一轮网页自进化已结束。",
                            en="This bounded self-evolution pass is complete.",
                        ),
                        timestamp=finished_at,
                        tool_calls=transcript_tool_calls,
                    ),
                ),
            },
            clear_active=True,
        )
    except SystemExit as exc:
        _mark_run_cancelled(
            run_id,
            summary=text_for(
                lang,
                zh="这一轮网页自进化请求了进程级动作，当前按已结束记录。",
                en="This bounded self-evolution pass requested a process-level action and has been recorded as finished.",
            ),
            tool_call_count=total_tool_call_count,
            reason=str(exc) if str(exc).strip() else "",
        )
    except Exception as exc:
        _mark_run_failed(
            run_id,
            f"{type(exc).__name__}: {exc}",
            tool_call_count=total_tool_call_count,
            summary=summary,
        )
    finally:
        live_refresh_stop.set()
        live_refresh_thread.join(timeout=1.0)
        _persist_self_snapshot(run_id)
        state = get_self_evolution_run_snapshot(run_id) or {}
        if str(state.get("status") or "").strip().lower() in _RUN_FINAL_STATUSES:
            manifest = _finalize_rollback_manifest(run_id, preflight)
            if manifest is not None:
                _merge_run_state(run_id, {"rollback": manifest})
                state = get_self_evolution_run_snapshot(run_id) or state
            _record_terminal_self_evolution_experience(run_id, state, manifest)
            _clear_run_internal(run_id)


def _self_live_refresh_loop(run_id: str, stop_event: threading.Event) -> None:
    while not stop_event.wait(0.75):
        snapshot = _persist_self_snapshot(run_id)
        if snapshot is None:
            return
        status = str(snapshot.get("status") or "").strip().lower()
        if status in _RUN_FINAL_STATUSES | {"paused"}:
            return


def _build_web_run_prompt(goal: str) -> str:
    base = build_self_evolution_run_prompt(goal=goal, project_root=PROJECT_ROOT)
    return (
        f"{base}\n\n"
        "网页工作台约束:\n"
        "1. 这是一轮有界自进化，只完成当前这一轮，不要继续进入无限自主循环。\n"
        "2. 如果共享现场风险很高，可以先总结风险并停止，不必为了修改而强行修改。\n"
        "3. 不要等待额外人工交互；直接完成这一轮并给出可见结论。"
    )


def _normalize_observation_duration(value: Any) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        duration = 300
    return max(SELF_OBSERVATION_MIN_DURATION_SECONDS, min(SELF_OBSERVATION_MAX_DURATION_SECONDS, duration))


def _self_observation_tool_policy() -> dict[str, Any]:
    return {
        "policyId": "self-observation-no-tools",
        "allowedTools": [],
        "preferredTools": [],
        "blockedTools": [],
        "readScopes": [],
        "writeScopes": [],
        "mutationAccess": "none",
    }


def build_self_observation_prompt(goal: str, duration_seconds: int) -> str:
    normalized_goal = str(goal or "").strip() or DEFAULT_SELF_EVOLUTION_GOAL
    normalized_duration = _normalize_observation_duration(duration_seconds)
    return (
        "你是 Vibelution 的自进化观察 Agent，处在无工具观察沙盒中。\n"
        f"观察目标：{normalized_goal}\n"
        f"运行时长上限：{normalized_duration} 秒。\n\n"
        "硬性规则：\n"
        "1. 你没有任何工具。\n"
        "2. 你不能声称已经读取、搜索、运行、验证、修改、提交、合并或调用外部能力。\n"
        "3. 你不能请求工具授权，因为本模式本阶段不支持工具申请。\n"
        "4. 你只能理解目标、提出假设、分解可能路径、识别风险、描述未来需要的证据。\n"
        "5. 需要证据时必须写入“无法验证”，不能编造结果。\n\n"
        "每段输出使用以下结构：\n"
        "当前理解：\n"
        "可观察推理：\n"
        "关键假设：\n"
        "无法验证：\n"
        "如果未来允许工具，需要的证据：\n"
        "下一段观察重点：\n"
    )


def detect_self_observation_boundary_violation(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""
    file_read_markers = ("已经读取", "读取了项目", "read the file", "read files", "opened the file")
    command_markers = ("运行了", "执行了命令", "ran pytest", "ran npm", "executed the command", "i ran")
    mutation_markers = ("修改了", "写入了", "提交了", "合并了", "modified the file", "committed", "merged")
    search_markers = ("搜索了", "查到了网页", "searched the web", "web search")
    if any(marker in normalized for marker in file_read_markers):
        return "claimed_file_read"
    if any(marker in normalized for marker in command_markers):
        return "claimed_command_execution"
    if any(marker in normalized for marker in mutation_markers):
        return "claimed_mutation"
    if any(marker in normalized for marker in search_markers):
        return "claimed_search"
    return ""


def _build_self_observation_snapshot(
    *,
    run_id: str,
    goal: str,
    duration_seconds: int,
    status: str,
    latest_message: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "runId": run_id,
        "runKind": "self_observation_run",
        "selfMode": "observation",
        "status": status,
        "phase": status,
        "runtimeStatus": status,
        "goal": goal,
        "durationSeconds": duration_seconds,
        "allowedTools": [],
        "toolPolicy": _self_observation_tool_policy(),
        "writeLeases": [],
        "worktreeCreated": False,
        "conversationSessionId": "",
        "startedAt": started_at,
        "updatedAt": started_at,
        "finishedAt": "",
        "latestMessage": latest_message,
        "messages": [],
        "report": "",
        "boundaryViolation": "",
        "actionStates": {
            "terminate": {"enabled": status in {"queued", "running"}, "label": "终止观察", "reason": ""},
        },
    }


def get_active_self_observation_run() -> dict[str, Any] | None:
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(_ACTIVE_OBSERVATION_RUN_ID)
        if not snapshot:
            return None
        if str(snapshot.get("status") or "").lower() in {"queued", "running"}:
            return dict(snapshot)
        return None


def get_self_observation_run_snapshot(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        return dict(snapshot) if snapshot else None


def force_cancel_active_self_observation_runs_for_shutdown(reason: str = "") -> list[dict[str, Any]]:
    global _ACTIVE_OBSERVATION_RUN_ID
    closed: list[dict[str, Any]] = []
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        for snapshot in _OBSERVATION_RUNS.values():
            if str(snapshot.get("status") or "").lower() in {"queued", "running"}:
                snapshot["status"] = "terminated"
                snapshot["phase"] = "terminated"
                snapshot["runtimeStatus"] = "terminated"
                snapshot["finishedAt"] = now
                snapshot["updatedAt"] = now
                snapshot["latestMessage"] = reason or "Observation run terminated."
                terminate_state = snapshot.get("actionStates") if isinstance(snapshot.get("actionStates"), dict) else {}
                if isinstance(terminate_state.get("terminate"), dict):
                    terminate_state["terminate"]["enabled"] = False
                closed.append(dict(snapshot))
        _ACTIVE_OBSERVATION_RUN_ID = ""
    return closed


def _self_observation_has_operator_terminal_state(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    for key in ("status", "phase", "runtimeStatus"):
        value = str(snapshot.get(key) or "").strip().lower()
        if value in _OBSERVATION_OPERATOR_TERMINAL_STATUSES:
            return True
    return False


def _set_self_observation_terminal_state(
    run_id: str,
    *,
    status: str,
    latest_message: str,
    report: str,
    boundary_violation: str = "",
    conversation_session_id: str = "",
    messages: list[str] | None = None,
) -> dict[str, Any] | None:
    global _ACTIVE_OBSERVATION_RUN_ID
    timestamp = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(str(run_id or "").strip())
        if not snapshot:
            return None
        if _self_observation_has_operator_terminal_state(snapshot):
            if _ACTIVE_OBSERVATION_RUN_ID == snapshot.get("runId"):
                _ACTIVE_OBSERVATION_RUN_ID = ""
            return dict(snapshot)
        snapshot["status"] = status
        snapshot["phase"] = status
        snapshot["runtimeStatus"] = status
        snapshot["latestMessage"] = str(latest_message or "").strip()
        snapshot["report"] = str(report or "").strip()
        snapshot["boundaryViolation"] = str(boundary_violation or "").strip()
        if conversation_session_id:
            snapshot["conversationSessionId"] = str(conversation_session_id or "").strip()
        if messages is not None:
            snapshot["messages"] = [str(item) for item in list(messages or []) if str(item or "").strip()]
        snapshot["updatedAt"] = timestamp
        snapshot["finishedAt"] = timestamp
        action_states = snapshot.get("actionStates")
        if not isinstance(action_states, dict):
            action_states = {}
            snapshot["actionStates"] = action_states
        terminate_state = action_states.get("terminate")
        if not isinstance(terminate_state, dict):
            terminate_state = {"label": "终止观察", "reason": ""}
            action_states["terminate"] = terminate_state
        terminate_state["enabled"] = False
        if _ACTIVE_OBSERVATION_RUN_ID == snapshot.get("runId"):
            _ACTIVE_OBSERVATION_RUN_ID = ""
        return dict(snapshot)


def _self_observation_operator_terminated(run_id: str) -> bool:
    snapshot = get_self_observation_run_snapshot(run_id)
    return _self_observation_has_operator_terminal_state(snapshot)


def _self_observation_assistant_messages(detail: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for item in list((detail or {}).get("messages") or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role != "assistant" or not content:
            continue
        messages.append(content)
    return messages


def _self_observation_completion_status(completion_snapshot: dict[str, Any], detail: dict[str, Any]) -> str:
    return str(
        completion_snapshot.get("terminalStatus")
        or completion_snapshot.get("lastTurnStatus")
        or detail.get("lastTurnStatus")
        or ""
    ).strip().lower()


def _run_observation_session(*, run_id: str, prompt: str, duration_seconds: int) -> dict[str, Any]:
    bindings = self_evolution_agent_bindings()
    executor_binding = bindings.get("executor") if isinstance(bindings, dict) else {}
    agent_id = str((executor_binding or {}).get("agentId") or "").strip()
    if not agent_id:
        raise SelfEvolutionRunValidationError("Missing self observation executor agent binding.")

    tool_policy = _self_observation_tool_policy()
    session = create_supervised_agent_session(
        agent_id=agent_id,
        title=f"自进化观察 {run_id[:8]}",
        metadata={
            "role": "executor",
            "mode": "self_observation",
            "runKind": "self_observation_run",
            "runId": run_id,
            "toolPolicy": tool_policy,
        },
    )
    session_id = str(session.get("id") or session.get("sessionId") or "").strip()
    if not session_id:
        raise SelfEvolutionRunValidationError("Observation session creation did not return a session id.")
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(run_id)
        if isinstance(snapshot, dict):
            snapshot["conversationSessionId"] = session_id
            snapshot["updatedAt"] = _now_timestamp()

    accepted = submit_session_message(
        session_id,
        prompt,
        mental_model_enabled=False,
        message_metadata={
            "runKind": "self_observation_run",
            "runId": run_id,
            "mode": "self_observation",
            "toolPolicy": tool_policy,
        },
        message_source="self_observation",
        include_started_turn_id=True,
        lightweight_response=True,
    )
    turn_id = str(accepted.get("turnId") or accepted.get("startedTurnId") or "").strip()
    deadline = time.monotonic() + max(5, int(duration_seconds or 0))
    stop_requested = False
    latest_detail: dict[str, Any] = {}
    latest_completion_snapshot: dict[str, Any] = {}
    while True:
        latest_detail = get_session_detail(session_id) or {}
        latest_completion_snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
        if bool(latest_completion_snapshot.get("terminal")):
            break
        last_status = _self_observation_completion_status(latest_completion_snapshot, latest_detail)
        if last_status and last_status not in {"queued", "running"}:
            break
        if _self_observation_operator_terminated(run_id) and not stop_requested:
            stop_requested = True
            try:
                request_stop_session_turn(session_id)
            except Exception:
                pass
        if time.monotonic() >= deadline:
            try:
                request_stop_session_turn(session_id)
            except Exception:
                pass
            raise TimeoutError("Observation session timed out.")
        time.sleep(0.5)

    latest_detail = get_session_detail(session_id) or latest_detail
    latest_completion_snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
    assistant_messages = _self_observation_assistant_messages(latest_detail)
    assistant_text = str(latest_completion_snapshot.get("assistantText") or "").strip()
    if assistant_text and (not assistant_messages or assistant_messages[-1] != assistant_text):
        assistant_messages.append(assistant_text)
    report = assistant_text or (assistant_messages[-1] if assistant_messages else "")
    if not report:
        turn_error = latest_detail.get("lastTurnError") if isinstance(latest_detail.get("lastTurnError"), dict) else {}
        error_text = str(turn_error.get("message") or _self_observation_completion_status(latest_completion_snapshot, latest_detail) or "").strip()
        report = (
            "当前理解：\n"
            "- observation conversation 已结束，但未返回可见 assistant 输出。\n\n"
            "无法验证：\n"
            f"- {error_text or '未获得会话结果。'}"
        )
    return {
        "conversationSessionId": session_id,
        "messages": assistant_messages,
        "report": report,
    }


def _run_self_observation_turn(context: dict[str, Any]) -> None:
    global _ACTIVE_OBSERVATION_RUN_ID
    run_id = str((context or {}).get("runId") or "").strip()
    goal = str((context or {}).get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    duration_seconds = _normalize_observation_duration((context or {}).get("durationSeconds"))
    if not run_id:
        return None
    started_at = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(run_id)
        if not snapshot:
            return None
        if _self_observation_has_operator_terminal_state(snapshot):
            if _ACTIVE_OBSERVATION_RUN_ID == snapshot.get("runId"):
                _ACTIVE_OBSERVATION_RUN_ID = ""
            return None
        snapshot["status"] = "running"
        snapshot["phase"] = "running"
        snapshot["runtimeStatus"] = "running"
        snapshot["updatedAt"] = started_at
        snapshot["latestMessage"] = text_for(
            get_web_language(),
            zh="自主观察正在生成最小观察报告。",
            en="Observation run is generating a minimal report.",
        )
        terminate_state = snapshot.get("actionStates")
        if isinstance(terminate_state, dict) and isinstance(terminate_state.get("terminate"), dict):
            terminate_state["terminate"]["enabled"] = True
    try:
        result = _run_observation_session(
            run_id=run_id,
            prompt=build_self_observation_prompt(goal, duration_seconds),
            duration_seconds=duration_seconds,
        )
        conversation_session_id = str(result.get("conversationSessionId") or "").strip()
        messages = [str(item) for item in list(result.get("messages") or []) if str(item or "").strip()]
        report = str(result.get("report") or "").strip()
        violation = ""
        for item in [*messages, report]:
            violation = detect_self_observation_boundary_violation(item)
            if violation:
                break
        status = "failed" if violation else "done"
        latest_message = messages[-1] if messages else report
        if violation:
            latest_message = text_for(
                get_web_language(),
                zh="自主观察检测到边界违规并已终止。",
                en="Observation run detected a boundary violation and stopped.",
            )
        _set_self_observation_terminal_state(
            run_id,
            status=status,
            latest_message=latest_message,
            report=report,
            boundary_violation=violation,
            conversation_session_id=conversation_session_id,
            messages=messages,
        )
    except Exception as exc:
        _set_self_observation_terminal_state(
            run_id,
            status="failed",
            latest_message=text_for(
                get_web_language(),
                zh="自主观察启动失败。",
                en="Observation run failed to start.",
            ),
            report=text_for(
                get_web_language(),
                zh=f"当前理解：\n- observation run 在最小生命周期阶段失败。\n\n无法验证：\n- {exc}",
                en=f"Current understanding:\n- observation run failed during the minimal lifecycle stage.\n\nCannot verify:\n- {exc}",
            ),
        )
    return None


def start_self_observation_run(payload: dict[str, Any]) -> dict[str, Any]:
    global _ACTIVE_OBSERVATION_RUN_ID
    lang = get_web_language()
    contract = get_workbench_contract()
    if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="配置里没有启用 self_evolution，当前不能启动自主观察。", en="self_evolution is disabled.")
        )
    data = payload if isinstance(payload, dict) else {}
    rejected_fields = [field for field in _SELF_OBSERVATION_FORBIDDEN_REQUEST_FIELDS if field in data]
    if rejected_fields:
        field_list = ", ".join(rejected_fields)
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh=f"observation mode has zero tools，且不支持工具授权或策略覆盖字段：{field_list}",
                en=f"Observation mode has zero tools and does not support tool authorization or policy override fields: {field_list}",
            )
        )
    goal = str(data.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    duration_seconds = _normalize_observation_duration(data.get("durationSeconds"))
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        active = get_active_self_observation_run()
        if active is not None:
            raise SelfEvolutionRunBusyError(
                text_for(lang, zh="当前已有自主观察正在运行，请先终止或等待结束。", en="An observation run is already active.")
            )
        run_id = f"self-observe-{uuid4().hex[:12]}"
        snapshot = _build_self_observation_snapshot(
            run_id=run_id,
            goal=goal,
            duration_seconds=duration_seconds,
            status="queued",
            latest_message=text_for(lang, zh="自主观察已排队，等待无工具会话启动。", en="Observation run queued."),
            started_at=now,
        )
        _OBSERVATION_RUNS[run_id] = snapshot
        _ACTIVE_OBSERVATION_RUN_ID = run_id
    _RUN_EXECUTOR.submit(_run_self_observation_turn, {"runId": run_id, "goal": goal, "durationSeconds": duration_seconds})
    return get_self_observation_run_snapshot(run_id) or snapshot


def execute_self_observation_action(run_id: str, action: str) -> dict[str, Any]:
    global _ACTIVE_OBSERVATION_RUN_ID
    normalized_run_id = str(run_id or "").strip()
    normalized_action = str(action or "").strip().lower()
    if not normalized_run_id:
        raise SelfEvolutionRunValidationError("Missing self observation run id.")
    if normalized_action not in {"terminate", "stop", "cancel"}:
        raise SelfEvolutionRunValidationError("Unsupported self observation action.")

    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized_run_id)
        if snapshot is None:
            raise SelfEvolutionRunNotFoundError("Self observation run not found.")
        if str(snapshot.get("status") or "").lower() not in {"queued", "running"}:
            raise SelfEvolutionRunBusyError("Self observation run is not active.")
        snapshot["status"] = "terminated"
        snapshot["phase"] = "terminated"
        snapshot["runtimeStatus"] = "terminated"
        snapshot["updatedAt"] = now
        snapshot["finishedAt"] = now
        snapshot["latestMessage"] = text_for(
            get_web_language(),
            zh="自主观察已由用户终止。",
            en="Observation run terminated by user.",
        )
        snapshot["report"] = snapshot.get("report") or text_for(
            get_web_language(),
            zh="观察被用户终止，未生成完整结束报告。",
            en="Observation run was terminated by user before a final report was generated.",
        )
        action_states = snapshot.get("actionStates")
        if not isinstance(action_states, dict):
            action_states = {}
            snapshot["actionStates"] = action_states
        action_states["terminate"] = {
            "enabled": False,
            "label": "已终止",
            "reason": "operator_terminated",
        }
        if _ACTIVE_OBSERVATION_RUN_ID == normalized_run_id:
            _ACTIVE_OBSERVATION_RUN_ID = ""
        updated = dict(snapshot)
    conversation_session_id = str(updated.get("conversationSessionId") or "").strip()
    if conversation_session_id:
        try:
            request_stop_session_turn(conversation_session_id)
        except Exception:
            pass
    return updated


def stream_self_observation_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    normalized_run_id = str(run_id or "").strip()
    if initial_snapshot:
        yield _encode_sse_event("self_observation_run", initial_snapshot)
    while normalized_run_id:
        snapshot = get_self_observation_run_snapshot(normalized_run_id)
        if snapshot is None:
            return
        if not initial_snapshot:
            yield _encode_sse_event("self_observation_run", snapshot)
        initial_snapshot = None
        if str(snapshot.get("status") or "").lower() not in {"queued", "running"}:
            return
        time.sleep(1.0)


def _mark_run_paused(
    run_id: str,
    *,
    summary: str,
    tool_call_count: int = 0,
    reason: str = "",
    carryover: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    paused_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    if carryover:
        _set_run_internal_value(run_id, "carryover", carryover)
    _merge_run_state(
        run_id,
        {
            "status": "paused",
            "phase": "paused",
            "updatedAt": paused_at,
            "runtimeStatus": "idle",
            "latestMessage": str(summary or "").strip(),
            "summary": str(summary or "").strip(),
            "toolCallCount": max(0, int(tool_call_count or 0)),
            "stopReason": str(reason or "").strip(),
            "lastToolName": str(last_tool_name or "").strip(),
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": _append_run_message(
                list(snapshot.get("messages") or []),
                _build_run_message(
                    run_id=run_id,
                    role="assistant",
                    content=str(summary or "").strip(),
                    timestamp=paused_at,
                    tool_calls=tool_calls,
                ),
            ),
            "error": "",
        },
    )


def _mark_run_failed(
    run_id: str,
    message: str,
    *,
    tool_call_count: int | None = None,
    summary: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    finished_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    visible_summary = str(summary or message or "").strip()
    payload: dict[str, Any] = {
        "status": "failed",
        "phase": "failed",
        "updatedAt": finished_at,
        "finishedAt": finished_at,
        "runtimeStatus": "failed",
        "latestMessage": str(message or "").strip(),
        "summary": visible_summary,
        "error": str(message or "").strip(),
        "lastToolName": str(last_tool_name or "").strip(),
        "controlAction": "",
        "controlRequestedAt": "",
    }
    if tool_call_count is not None:
        payload["toolCallCount"] = max(0, int(tool_call_count))
    if visible_summary:
        payload["messages"] = _append_run_message(
            list(snapshot.get("messages") or []),
            _build_run_message(
                run_id=run_id,
                role="assistant",
                content=visible_summary,
                timestamp=finished_at,
                tool_calls=tool_calls,
            ),
        )
    _merge_run_state(run_id, payload, clear_active=True)
    _record_self_scene_event(
        "state",
        "self_evolution_run.failed",
        run_id=run_id,
        message=str(message or "Self-evolution run failed."),
        level="error",
        outcome="failed",
        fields={
            **_self_snapshot_event_fields({**snapshot, **payload}),
            "summary": visible_summary,
        },
        lifecycle=True,
    )


def _mark_run_cancelled(
    run_id: str,
    *,
    summary: str,
    tool_call_count: int = 0,
    reason: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    finished_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    _merge_run_state(
        run_id,
        {
            "status": "cancelled",
            "phase": "cancelled",
            "updatedAt": finished_at,
            "finishedAt": finished_at,
            "runtimeStatus": "idle",
            "latestMessage": summary,
            "summary": summary,
            "toolCallCount": max(0, int(tool_call_count or 0)),
            "cancelRequested": True,
            "cancelRequestedAt": finished_at,
            "stopReason": str(reason or "").strip(),
            "error": "",
            "lastToolName": str(last_tool_name or "").strip(),
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": _append_run_message(
                list(snapshot.get("messages") or []),
                _build_run_message(
                    run_id=run_id,
                    role="assistant",
                    content=str(summary or "").strip(),
                    timestamp=finished_at,
                    tool_calls=tool_calls,
                ),
            ),
        },
        clear_active=True,
    )


def _merge_run_state(run_id: str, payload: dict[str, Any], *, clear_active: bool = False) -> None:
    global _ACTIVE_RUN_ID
    normalized = str(run_id or "").strip()
    if not normalized:
        return
    terminal = False
    file_only_snapshot: dict[str, Any] | None = None
    active_run_id = ""
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            stored = load_manager_run_snapshot("self", normalized)
            if stored is not None:
                stored.update(payload)
                if clear_active:
                    active_run_id = ""
                else:
                    index_active = load_manager_active_run_snapshot("self")
                    if str((index_active or {}).get("runId") or "").strip() == normalized:
                        active_run_id = normalized
                file_only_snapshot = stored
                terminal = _is_terminal_run_snapshot(stored)
        else:
            current.update(payload)
            terminal = _is_terminal_run_snapshot(current)
            if clear_active and _ACTIVE_RUN_ID == normalized:
                _ACTIVE_RUN_ID = None
            active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    if file_only_snapshot is not None:
        persist_manager_run_snapshot("self", file_only_snapshot, active_run_id=active_run_id)
        _record_self_state_change_scene_event(normalized, file_only_snapshot, payload, clear_active=clear_active)
        return
    _publish_run_snapshot(normalized, terminal=terminal)
    latest = get_self_evolution_run_snapshot(normalized) or {}
    _record_self_state_change_scene_event(normalized, latest, payload, clear_active=clear_active)


def _record_self_state_change_scene_event(
    run_id: str,
    snapshot: dict[str, Any],
    payload: dict[str, Any],
    *,
    clear_active: bool,
) -> None:
    status = str(snapshot.get("status") or payload.get("status") or "").strip().lower()
    phase = str(snapshot.get("phase") or payload.get("phase") or status or "state").strip().lower()
    if not status and not phase:
        return
    level = "error" if status == "failed" or str(snapshot.get("runtimeStatus") or "").strip().lower() == "failed" else "info"
    outcome = "failed" if level == "error" else "succeeded" if status in {"done", "cancelled", "paused"} else "observed"
    fields = {
        **_self_snapshot_event_fields(snapshot),
        "clearActive": bool(clear_active),
        "turnCount": _optional_scene_int(snapshot.get("turnCount")),
        "resumeCount": _optional_scene_int(snapshot.get("resumeCount")),
        "summaryPreview": str(snapshot.get("summary") or snapshot.get("latestMessage") or "")[:320],
    }
    _record_self_scene_event(
        "state",
        "self_evolution_run.state.changed",
        run_id=run_id,
        message=f"Self-evolution state changed: {status or phase}",
        level=level,
        outcome=outcome,
        fields=fields,
        child_log_payload=fields,
        lifecycle=status in _RUN_FINAL_STATUSES | {"running", "queued", "paused", "stopping"},
    )


def _raise_if_self_lease_conflict(*, lang: str) -> None:
    active_runs = list_active_session_work_runs()
    supervised_active = _load_active_work_run_snapshot("supervised")
    if supervised_active is not None:
        active_runs.append(supervised_active)
    supervised_worktree_active = get_active_supervised_worktree_run()
    if supervised_worktree_active is not None:
        active_runs.append(supervised_worktree_active)
    decision = check_lease_conflicts(
        WorkRunLeaseRequest(
            run_kind="self_evolution_run",
            leases=[EVOLUTION_TRANSACTION_LEASE, WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE],
        ),
        active_runs,
    )
    if not decision.allowed:
        raise SelfEvolutionRunBusyError(_localize_lease_conflict(decision.reason, lang=lang))


def _supervised_run_blocks_self_evolution(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    status = str(snapshot.get("status") or "").strip().lower()
    return status in _RUN_LOCKED_STATUSES


def _load_active_work_run_snapshot(kind: str) -> dict[str, Any] | None:
    try:
        snapshot = load_manager_active_run_snapshot(kind)
    except Exception:
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _localize_lease_conflict(reason: str, *, lang: str) -> str:
    fallback = str(reason or "").strip()
    return text_for(
        lang,
        zh=f"当前资源正在被另一条运行占用，请等待它收束后再启动自进化。{fallback}",
        en=f"Another active run holds a conflicting resource lease. Wait for it to finish before starting self evolution. {fallback}",
    ).strip()


def _get_run_internal(run_id: str) -> dict[str, Any]:
    normalized = str(run_id or "").strip()
    if not normalized:
        return {}
    with _RUN_STATE_LOCK:
        payload = _RUN_INTERNALS.get(normalized) or {}
        return payload if isinstance(payload, dict) else {}


def _set_run_internal_value(run_id: str, key: str, value: Any) -> None:
    normalized = str(run_id or "").strip()
    if not normalized or not key:
        return
    with _RUN_STATE_LOCK:
        bucket = _RUN_INTERNALS.setdefault(normalized, {})
        if isinstance(bucket, dict):
            bucket[key] = value


def _clear_run_internal(run_id: str) -> None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return
    with _RUN_STATE_LOCK:
        _RUN_INTERNALS.pop(normalized, None)


def _finalize_terminal_run_snapshot(run_id: str) -> dict[str, Any] | None:
    internal = _get_run_internal(run_id)
    preflight = internal.get("preflight") if isinstance(internal.get("preflight"), dict) else {}
    manifest = _finalize_rollback_manifest(run_id, preflight)
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    _record_terminal_self_evolution_experience(run_id, snapshot, manifest)
    _clear_run_internal(run_id)
    return manifest


def _record_terminal_self_evolution_experience(
    run_id: str,
    snapshot: dict[str, Any],
    rollback: dict[str, Any] | None,
) -> None:
    if not isinstance(snapshot, dict):
        return
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _RUN_FINAL_STATUSES:
        return
    try:
        result = record_terminal_self_evolution_experience(
            snapshot,
            rollback=rollback,
            project_root=PROJECT_ROOT,
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        _record_self_scene_event(
            "experience",
            "self_evolution_run.experience_record_failed",
            run_id=run_id,
            message=f"Failed to record self-evolution terminal experience: {type(exc).__name__}",
            level="warning",
            outcome="failed",
            fields={
                "errorType": type(exc).__name__,
                "status": status,
            },
            lifecycle=True,
        )
        return

    record = result.record if hasattr(result, "record") else {}
    _record_self_scene_event(
        "experience",
        "self_evolution_run.experience_recorded",
        run_id=run_id,
        message="Self-evolution terminal experience recorded.",
        outcome="succeeded",
        fields={
            "experienceId": str(record.get("experience_id") or ""),
            "experienceKind": str(record.get("kind") or ""),
            "created": bool(getattr(result, "created", False)),
            "dedupeKey": str(record.get("dedupe_key") or ""),
            "status": status,
        },
        lifecycle=True,
    )
    _record_terminal_self_evolution_reflection(run_id, record)


def _record_terminal_self_evolution_reflection(run_id: str, experience: dict[str, Any]) -> None:
    if not isinstance(experience, dict):
        return
    try:
        result = record_bounded_self_evolution_reflection(
            experience,
            project_root=PROJECT_ROOT,
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        _record_self_scene_event(
            "reflection",
            "self_evolution_run.reflection_record_failed",
            run_id=run_id,
            message=f"Failed to record self-evolution bounded reflection: {type(exc).__name__}",
            level="warning",
            outcome="failed",
            fields={
                "errorType": type(exc).__name__,
                "experienceId": str(experience.get("experience_id") or ""),
            },
            lifecycle=True,
        )
        return

    record = result.record if hasattr(result, "record") else {}
    _record_self_scene_event(
        "reflection",
        "self_evolution_run.reflection_recorded",
        run_id=run_id,
        message="Self-evolution bounded reflection recorded.",
        outcome="succeeded",
        fields={
            "experienceId": str(experience.get("experience_id") or ""),
            "reflectionId": str(record.get("reflection_id") or ""),
            "created": bool(getattr(result, "created", False)),
            "dedupeKey": str(record.get("dedupe_key") or ""),
        },
        lifecycle=True,
    )


def _current_run_control_reason(run_id: str) -> str:
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    if str(snapshot.get("status") or "").strip().lower() != "stopping":
        return ""
    action = str(snapshot.get("controlAction") or "").strip().lower()
    if action not in {"pause", "terminate"}:
        return ""
    return str(snapshot.get("stopReason") or "").strip()


def _build_resume_user_message(goal: str) -> str:
    normalized_goal = str(goal or "").strip() or DEFAULT_SELF_EVOLUTION_GOAL
    return text_for(
        get_web_language(),
        zh=f"继续这一轮自进化\n目标：{normalized_goal}",
        en=f"Resume this self-evolution pass\nGoal: {normalized_goal}",
    )


def _build_run_message(
    *,
    run_id: str,
    role: str,
    content: str,
    timestamp: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stamp = str(timestamp or _now_timestamp()).strip()
    payload: dict[str, Any] = {
        "id": f"{run_id}-message-{stamp}-{role}-{uuid4().hex[:8]}",
        "role": str(role or "").strip().lower(),
        "content": str(content or "").strip(),
        "timestamp": stamp,
    }
    normalized_tool_calls = [dict(item) for item in list(tool_calls or []) if isinstance(item, dict)]
    if normalized_tool_calls:
        payload["toolCalls"] = normalized_tool_calls
    return payload


def _append_run_message(messages: list[dict[str, Any]], message: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(message, dict) or not str(message.get("content") or "").strip():
        return list(messages or [])
    return [*list(messages or []), message]


def _append_run_message_locked(
    current: dict[str, Any],
    *,
    role: str,
    content: str,
    timestamp: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> None:
    current["messages"] = _append_run_message(
        list(current.get("messages") or []),
        _build_run_message(
            run_id=str(current.get("runId") or "web-self"),
            role=role,
            content=content,
            timestamp=timestamp,
            tool_calls=tool_calls,
        ),
    )


def _tool_calls_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    seen: set[str] = set()
    calls: list[dict[str, Any]] = []
    for raw in list(result.get("tool_trace") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        calls.append({"name": name, "status": "done"})
    return calls[:6]


def _last_tool_name_from_result(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    for raw in reversed(list(result.get("tool_trace") or [])):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name:
            return name
    return ""


def _build_result_message(result: dict[str, Any], fallback: str = "") -> str:
    if not isinstance(result, dict):
        return str(fallback or "").strip()
    for key in ("raw_output", "summary", "error", "message"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    return str(fallback or "").strip()


def _build_manager_control_payload() -> dict[str, Any]:
    return {
        "ownerPid": os.getpid(),
        "kind": "self",
        "claimedAt": _now_timestamp(),
    }


def _current_runtime_manager_owner_pid() -> int:
    try:
        from core.runtime_manager.state_store import load_pid

        return int(load_pid() or 0)
    except Exception:
        return 0


def _manager_control_is_current(payload: dict[str, Any]) -> bool:
    control = payload.get(_MANAGER_CONTROL_KEY) if isinstance(payload.get(_MANAGER_CONTROL_KEY), dict) else {}
    try:
        owner_pid = int(control.get("ownerPid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    return owner_pid > 0 and owner_pid == _current_runtime_manager_owner_pid()


def _current_active_run_locked() -> dict[str, Any] | None:
    if not _ACTIVE_RUN_ID:
        return None
    return _RUN_STATES.get(_ACTIVE_RUN_ID)


def _latest_run_locked() -> dict[str, Any] | None:
    if _ACTIVE_RUN_ID and _RUN_STATES.get(_ACTIVE_RUN_ID):
        return _RUN_STATES[_ACTIVE_RUN_ID]
    if not _RUN_STATES:
        return None
    return max(
        _RUN_STATES.values(),
        key=lambda item: (
            str(item.get("updatedAt") or ""),
            str(item.get("startedAt") or ""),
            str(item.get("runId") or ""),
        ),
    )


def _snapshot_from_memory_locked(run_id: str, *, decorate: bool = True) -> dict[str, Any] | None:
    current = _RUN_STATES.get(run_id)
    if current is None:
        return None
    snapshot = _clone_payload(current)
    if decorate:
        return _decorate_runtime_snapshot(snapshot)
    return snapshot


def request_self_evolution_restart(run_id: str = "", *, reason: str = "self_evolution_restart") -> dict[str, Any]:
    """Ask the runtime-manager supervisor to restart a self-evolution run."""

    normalized_run_id = str(run_id or "").strip()
    if _runtime_manager_live_control_enabled():
        return _submit_self_runtime_manager_command(
            "restart_self_evolution_run",
            run_id=normalized_run_id,
            payload={"reason": reason},
        )
    return _LOCAL_REQUEST_SELF_EVOLUTION_RESTART(run_id=normalized_run_id, reason=reason)


def _LOCAL_REQUEST_SELF_EVOLUTION_RESTART(*, run_id: str = "", reason: str = "self_evolution_restart") -> dict[str, Any]:
    normalized_run_id = str(run_id or "").strip()
    snapshot = get_self_evolution_run_snapshot(normalized_run_id) if normalized_run_id else get_active_self_evolution_run()
    if not isinstance(snapshot, dict) or not str(snapshot.get("runId") or "").strip():
        snapshot = get_latest_self_evolution_run() or {}
    resolved_run_id = str(snapshot.get("runId") or normalized_run_id or "").strip()
    intent = create_restart_intent(
        "self_evolution_run",
        reason=reason,
        requested_by="self_evolution",
        source_command_id=resolved_run_id,
        payload={
            "runId": resolved_run_id,
            "action": "restart_self_evolution_run",
            "status": str(snapshot.get("status") or ""),
            "phase": str(snapshot.get("phase") or ""),
        },
    )
    updated_at = _now_timestamp()
    if resolved_run_id:
        _merge_run_state(
            resolved_run_id,
            {
                "updatedAt": updated_at,
                "runtimeStatus": "restart_requested",
                "latestMessage": text_for(
                    get_web_language(),
                    zh="已登记自进化重启意图，将由 runtime manager 在安全点接管。",
                    en="A self-evolution restart intent was registered for the runtime manager to coordinate at a safe point.",
                ),
                "restartIntent": {
                    "intentId": str(intent.get("intentId") or ""),
                    "status": str(intent.get("status") or ""),
                    "reason": str(intent.get("reason") or ""),
                    "createdAt": str(intent.get("createdAt") or ""),
                },
            },
        )
        snapshot = get_self_evolution_run_snapshot(resolved_run_id) or snapshot
    _record_self_scene_event(
        "restart",
        "self_evolution_run.restart_intent_created",
        run_id=resolved_run_id,
        message="Self-evolution restart intent registered.",
        outcome="succeeded",
        fields={
            "intentId": str(intent.get("intentId") or ""),
            "reason": str(intent.get("reason") or ""),
            "status": str((snapshot or {}).get("status") or ""),
        },
        lifecycle=True,
    )
    return {**intent, "snapshot": snapshot or {"runId": resolved_run_id}}


def _LOCAL_FULFILL_SELF_EVOLUTION_RESTART(intent: dict[str, Any]) -> dict[str, Any]:
    payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
    run_id = str(payload.get("runId") or intent.get("sourceCommandId") or "").strip()
    reason = str(intent.get("reason") or "self_evolution_restart").strip() or "self_evolution_restart"
    if not run_id:
        raise SelfEvolutionRunValidationError("Self-evolution restart intent is missing runId.")
    snapshot = _requeue_self_evolution_run_for_restart(run_id, reason=reason)
    return {
        "runId": str(snapshot.get("runId") or run_id),
        "snapshot": snapshot,
        "message": "Self-evolution restart queued.",
    }


def _requeue_self_evolution_run_for_restart(run_id: str, *, reason: str) -> dict[str, Any]:
    lang = get_web_language()
    normalized = str(run_id or "").strip()
    now = _now_timestamp()
    state_snapshot: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            stored = load_manager_run_snapshot("self", normalized)
            if stored is None:
                raise SelfEvolutionRunNotFoundError(
                    text_for(lang, zh="未找到要重启的自进化记录。", en="Self-evolution run not found for restart.")
                )
            _RUN_STATES[normalized] = _clone_payload(stored)
            current = _RUN_STATES[normalized]
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_EXECUTING_STATUSES:
            return _decorate_runtime_snapshot(_clone_payload(current))
        current.update(
            {
                "status": "queued",
                "phase": "queued",
                "updatedAt": now,
                "finishedAt": "",
                "runtimeStatus": "idle",
                "latestMessage": text_for(
                    lang,
                    zh="Runtime manager 已接管自进化重启，正在重新排队这一轮。",
                    en="Runtime manager accepted the self-evolution restart and queued this pass again.",
                ),
                "summary": "",
                "error": "",
                "cancelRequested": False,
                "cancelRequestedAt": "",
                "stopReason": str(reason or "").strip(),
                "controlAction": "",
                "controlRequestedAt": "",
                "resumeCount": max(0, int(current.get("resumeCount") or 0)) + 1,
                _MANAGER_CONTROL_KEY: _build_manager_control_payload(),
            }
        )
        _append_run_message_locked(
            current,
            role="user",
            content=text_for(
                lang,
                zh=f"Runtime manager 重新启动这一轮自进化\n原因：{reason or 'self_evolution_restart'}",
                en=f"Runtime manager restarted this self-evolution pass\nReason: {reason or 'self_evolution_restart'}",
            ),
            timestamp=now,
        )
        _RUN_INTERNALS.setdefault(normalized, {}).setdefault("carryover", {})
        global _ACTIVE_RUN_ID
        _ACTIVE_RUN_ID = normalized
        state_snapshot = _clone_payload(current)

    assert state_snapshot is not None
    _publish_run_snapshot(normalized, record_scene_state=True)
    _record_self_scene_event(
        "restart",
        "self_evolution_run.restart_queued",
        run_id=normalized,
        message="Self-evolution run queued from restart intent.",
        outcome="succeeded",
        fields={
            "reason": str(reason or ""),
            **_self_snapshot_event_fields(state_snapshot),
        },
        lifecycle=True,
    )
    try:
        _RUN_EXECUTOR.submit(
            _run_self_evolution_turn,
            {
                "runId": normalized,
                "goal": str(state_snapshot.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL),
            },
        )
    except Exception as exc:
        _mark_run_failed(
            normalized,
            text_for(
                lang,
                zh=f"无法重启自进化：{type(exc).__name__}: {exc}",
                en=f"Failed to restart self evolution: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_self_evolution_run_snapshot(normalized) or state_snapshot


def _persist_self_snapshot(run_id: str, *, decorate: bool = True) -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        snapshot = _snapshot_from_memory_locked(run_id, decorate=decorate)
        active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    if snapshot is None:
        return None
    return persist_manager_run_snapshot("self", snapshot, active_run_id=active_run_id)


def _publish_run_snapshot(
    run_id: str,
    *,
    terminal: bool = False,
    record_scene_state: bool = False,
    scene_clear_active: bool = False,
) -> None:
    snapshot = _persist_self_snapshot(run_id)
    if snapshot is None:
        return
    if record_scene_state:
        _record_self_state_change_scene_event(run_id, snapshot, {}, clear_active=scene_clear_active)
    event = {
        "type": "self_evolution_run",
        "runId": run_id,
        "snapshot": snapshot,
        "terminal": terminal or _is_terminal_run_snapshot(snapshot),
    }
    with _RUN_SUBSCRIBERS_LOCK:
        subscribers = list(_RUN_SUBSCRIBERS.get(run_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _register_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.setdefault(run_id, set())
        bucket.add(subscriber)


def _unregister_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.get(run_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _RUN_SUBSCRIBERS.pop(run_id, None)


def _is_terminal_run_snapshot(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    return status in _RUN_FINAL_STATUSES | {"paused"}


def _snapshot_signature(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _decorate_self_snapshot_fields(payload: dict[str, Any]) -> dict[str, Any]:
    lang = get_web_language()
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    rollback_status = str(rollback.get("status") or "unavailable").strip().lower() or "unavailable"
    phase = str(payload.get("phase") or payload.get("status") or "idle").strip().lower() or "idle"
    status = str(payload.get("status") or "idle").strip().lower() or "idle"
    payload["runSemantics"] = {
        "runStatus": status,
        "runStatusLabel": _self_status_label(status, lang=lang),
        "phase": phase,
        "phaseLabel": _self_status_label(phase, lang=lang),
        "rollbackState": rollback_status,
        "rollbackStateLabel": _rollback_state_label(rollback_status, lang=lang),
        "rollbackSummary": str(rollback.get("reason") or "").strip(),
    }
    payload["actionStates"] = _self_action_states(payload, lang=lang)
    return payload


def _self_action_states(payload: dict[str, Any], *, lang: str) -> dict[str, dict[str, Any]]:
    status = str(payload.get("status") or "").strip().lower()
    runtime_status = str(payload.get("runtimeStatus") or "").strip().lower()
    control_action = str(payload.get("controlAction") or "").strip().lower()
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    rollback_status = str(rollback.get("status") or "").strip().lower()
    is_final = status in _RUN_FINAL_STATUSES

    def enabled_state() -> dict[str, Any]:
        return {"enabled": True, "reason": ""}

    def disabled_state(reason: str) -> dict[str, Any]:
        return {"enabled": False, "reason": reason}

    if status in {"queued", "running"} and control_action != "pause" and status != "stopping":
        pause_state = enabled_state()
    elif status == "paused":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经暂停，可以直接继续。", en="This pass is already paused and can be resumed directly.")
        )
    elif is_final:
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，不能再暂停。", en="This pass is already finished and cannot be paused.")
        )
    elif status == "stopping" or control_action == "pause" or runtime_status == "pausing":
        pause_state = disabled_state(
            text_for(lang, zh="暂停请求已经发出，等待当前安全点收口。", en="Pause has already been requested. Wait for the current safe point to close.")
        )
    else:
        pause_state = disabled_state(
            text_for(lang, zh="当前状态不能再发起暂停。", en="The current state cannot accept another pause request.")
        )

    if status == "paused":
        resume_state = enabled_state()
    elif is_final:
        resume_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，不能再继续。", en="This pass is already finished and cannot be resumed.")
        )
    else:
        resume_state = disabled_state(
            text_for(lang, zh="只有已暂停的这一轮才能继续。", en="Only a paused pass can be resumed.")
        )

    if status in {"queued", "running", "paused"}:
        terminate_state = enabled_state()
    elif is_final:
        terminate_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，无需再次终止。", en="This pass is already finished and does not need to be terminated again.")
        )
    else:
        terminate_state = disabled_state(
            text_for(lang, zh="当前正在收束这一轮，请等它结束。", en="This pass is already closing down. Wait for it to finish.")
        )

    if status in _RUN_LOCKED_STATUSES:
        rollback_state = disabled_state(
            text_for(lang, zh="要等这一轮先收口，才会生成可执行回滚。", en="Wait for this pass to close before automatic rollback becomes available.")
        )
    elif rollback_status == "available":
        rollback_state = enabled_state()
    elif rollback_status == "blocked":
        rollback_state = disabled_state(
            str(rollback.get("reason") or "")
            or text_for(lang, zh="这轮回滚已被后续改动污染，需要转交处理。", en="Later edits contaminated this rollback and it now needs handoff handling.")
        )
    elif rollback_status == "rolled_back":
        rollback_state = disabled_state(
            text_for(lang, zh="这轮改动已经回滚完成。", en="This pass has already been rolled back.")
        )
    else:
        rollback_state = disabled_state(
            str(rollback.get("reason") or "")
            or text_for(lang, zh="当前还没有可执行的回滚清单。", en="There is no runnable rollback manifest yet.")
        )

    if rollback_status == "blocked":
        handoff_state = enabled_state()
    else:
        handoff_state = disabled_state(
            text_for(
                lang,
                zh="只有出现回滚冲突时，才需要把这轮交接给会话 agent。",
                en="Rollback handoff is only needed when this pass is blocked by a rollback conflict.",
            )
        )

    return {
        "pause": pause_state,
        "resume": resume_state,
        "terminate": terminate_state,
        "rollback": rollback_state,
        "handoff": handoff_state,
    }


def _self_status_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "idle"
    mapping = {
        "idle": text_for(lang, zh="空闲", en="Idle"),
        "queued": text_for(lang, zh="已排队", en="Queued"),
        "running": text_for(lang, zh="进行中", en="Running"),
        "reading": text_for(lang, zh="读现场", en="Reading"),
        "thinking": text_for(lang, zh="想下一步", en="Thinking"),
        "tooling": text_for(lang, zh="调用工具", en="Using tools"),
        "editing": text_for(lang, zh="改实现", en="Editing"),
        "verifying": text_for(lang, zh="做验证", en="Verifying"),
        "answering": text_for(lang, zh="收结论", en="Wrapping up"),
        "paused": text_for(lang, zh="已暂停", en="Paused"),
        "stopping": text_for(lang, zh="等待收口", en="Stopping"),
        "done": text_for(lang, zh="已完成", en="Done"),
        "failed": text_for(lang, zh="已失败", en="Failed"),
        "cancelled": text_for(lang, zh="已终止", en="Cancelled"),
        "blocked": text_for(lang, zh="受阻", en="Blocked"),
        "available": text_for(lang, zh="可执行", en="Available"),
        "unavailable": text_for(lang, zh="暂不可用", en="Unavailable"),
    }
    return mapping.get(normalized, normalized)


def _rollback_state_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "unavailable"
    mapping = {
        "available": text_for(lang, zh="可安全回滚", en="Safe rollback ready"),
        "blocked": text_for(lang, zh="回滚冲突待处理", en="Rollback blocked by conflict"),
        "rolled_back": text_for(lang, zh="已完成回滚", en="Rolled back"),
        "unavailable": text_for(lang, zh="暂不可回滚", en="Rollback unavailable"),
    }
    return mapping.get(normalized, normalized)


def _decorate_runtime_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _load_runtime_state()
    status = str(payload.get("status") or "").strip().lower()
    if status in _RUN_FINAL_STATUSES | {"paused"}:
        return _decorate_self_snapshot_fields(payload)
    attention = get_session_state().get_attention_snapshot()

    current_goal = str((runtime or {}).get("current_goal") or "").strip()
    last_tool_name = str((runtime or {}).get("last_tool_name") or "").strip()
    runtime_status = str((runtime or {}).get("runtime_status") or (runtime or {}).get("status") or "").strip().lower()
    updated_at = str((runtime or {}).get("updated_at") or "").strip()
    reading_task = str(attention.get("reading_task") or "").strip()
    reading_hint = str(attention.get("reading_recommendation") or "").strip()
    reading_sufficiency = str(attention.get("reading_sufficiency") or "").strip()
    convergence_state = str(attention.get("convergence_state") or "").strip().lower()
    next_tool_intent = str(attention.get("next_tool_intent") or "").strip()
    stop_reason = str(attention.get("stop_reason") or "").strip()

    if current_goal:
        payload["currentGoal"] = current_goal
    if last_tool_name:
        payload["lastToolName"] = last_tool_name
    if runtime_status:
        payload["runtimeStatus"] = runtime_status
    if updated_at:
        payload["updatedAt"] = updated_at

    derived_phase = _derive_self_live_phase(
        status=status,
        runtime_status=runtime_status,
        reading_task=reading_task,
        last_tool_name=last_tool_name,
        convergence_state=convergence_state,
    )
    if derived_phase:
        payload["phase"] = derived_phase

    current_task = _derive_self_current_task(
        phase=derived_phase or str(payload.get("phase") or "").strip().lower(),
        latest_message=str(payload.get("latestMessage") or "").strip(),
        reading_task=reading_task,
        reading_hint=reading_hint,
        next_tool_intent=next_tool_intent,
        last_tool_name=last_tool_name,
        stop_reason=stop_reason,
    )
    if current_task:
        payload["currentTask"] = current_task
    if reading_task:
        payload["readingTask"] = reading_task
    if reading_hint:
        payload["readingHint"] = reading_hint
    if reading_sufficiency:
        payload["readingSufficiency"] = reading_sufficiency
    if convergence_state:
        payload["convergenceState"] = convergence_state
    if next_tool_intent:
        payload["nextToolIntent"] = next_tool_intent
    if stop_reason and not str(payload.get("stopReason") or "").strip():
        payload["stopReason"] = stop_reason
    return _decorate_self_snapshot_fields(payload)


def _finalize_orphaned_manager_self_run(snapshot: dict[str, Any]) -> dict[str, Any]:
    lang = get_web_language()
    return _build_cancelled_file_self_run_snapshot(
        snapshot,
        latest_message=text_for(
            lang,
            zh="这轮网页自进化已失去活动索引，系统已自动收口，可以重新开始新的一轮。",
            en="This web self-evolution pass lost its active index and was closed automatically. A new pass can be started now.",
        ),
        summary=text_for(
            lang,
            zh="系统检测到历史自进化快照仍处于锁定状态，但运行管理器已没有对应 active run。",
            en="The system found a historical self-evolution snapshot still in a locked state, but the runtime manager no longer has a matching active run.",
        ),
        stop_reason=text_for(
            lang,
            zh="清理孤儿自进化运行快照。",
            en="Cleaned up an orphaned self-evolution run snapshot.",
        ),
    )


def force_cancel_active_self_evolution_runs_for_shutdown(reason: str = "") -> list[dict[str, Any]]:
    """Force-close active self-evolution snapshots before the workbench exits."""

    lang = get_web_language()
    run_ids: list[str] = []
    with _RUN_STATE_LOCK:
        if _ACTIVE_RUN_ID:
            run_ids.append(_ACTIVE_RUN_ID)
    try:
        active_snapshot = load_manager_active_run_snapshot("self")
    except Exception:
        active_snapshot = None
    active_run_id = str((active_snapshot or {}).get("runId") or "").strip()
    if active_run_id and active_run_id not in run_ids:
        run_ids.append(active_run_id)

    closed: list[dict[str, Any]] = []
    for run_id in run_ids:
        snapshot = _force_cancel_self_run_for_shutdown(run_id, lang=lang, reason=reason)
        if snapshot is not None:
            closed.append(snapshot)
    return closed


def _force_cancel_self_run_for_shutdown(run_id: str, *, lang: str, reason: str = "") -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return None

    latest_message = text_for(
        lang,
        zh="工作台正在关闭，系统已收口这轮自进化，可以重新开始新的一轮。",
        en="The workbench is shutting down, so this self-evolution pass was closed and a new pass can be started later.",
    )
    summary = str(reason or "").strip() or text_for(
        lang,
        zh="工作台关闭时终止活跃自进化运行。",
        en="Closed the active self-evolution run during workbench shutdown.",
    )
    stop_reason = text_for(
        lang,
        zh="工作台关闭时收口活跃自进化运行。",
        en="Closed the active self-evolution run during workbench shutdown.",
    )

    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is not None:
            status = str(current.get("status") or "").strip().lower()
            if status not in _RUN_LOCKED_STATUSES:
                return _decorate_runtime_snapshot(_clone_payload(current))
            now = _now_timestamp()
            current.update(
                {
                    "status": "cancelled",
                    "phase": "cancelled",
                    "updatedAt": now,
                    "finishedAt": now,
                    "runtimeStatus": "idle",
                    "latestMessage": latest_message,
                    "summary": summary,
                    "cancelRequested": True,
                    "cancelRequestedAt": str(current.get("cancelRequestedAt") or now),
                    "stopReason": stop_reason,
                    "controlAction": "",
                    "controlRequestedAt": "",
                    _MANAGER_CONTROL_KEY: {
                        "ownerPid": "",
                        "kind": "self",
                        "clearedAt": now,
                        "reason": "shutdown",
                    },
                }
            )
            _append_run_message_locked(
                current,
                role="assistant",
                content=latest_message,
                timestamp=now,
            )
    if current is not None:
        _merge_run_state(normalized, {}, clear_active=True)
        return get_self_evolution_run_snapshot(normalized)

    stored = load_manager_run_snapshot("self", normalized)
    if stored is None:
        return None
    status = str(stored.get("status") or "").strip().lower()
    if status not in _RUN_LOCKED_STATUSES:
        return _decorate_runtime_snapshot(_clone_payload(stored))
    payload = _build_cancelled_file_self_run_snapshot(
        stored,
        latest_message=latest_message,
        summary=summary,
        stop_reason=stop_reason,
    )
    payload[_MANAGER_CONTROL_KEY] = {
        "ownerPid": "",
        "kind": "self",
        "clearedAt": str(payload.get("updatedAt") or _now_timestamp()),
        "reason": "shutdown",
    }
    return persist_manager_run_snapshot("self", payload, active_run_id="")


def _build_cancelled_file_self_run_snapshot(
    snapshot: dict[str, Any],
    *,
    latest_message: str,
    summary: str,
    stop_reason: str,
) -> dict[str, Any]:
    now = _now_timestamp()
    payload = _clone_payload(snapshot)
    payload.update(
        {
            "status": "cancelled",
            "phase": "cancelled",
            "updatedAt": now,
            "finishedAt": now,
            "runtimeStatus": "idle",
            "latestMessage": latest_message,
            "summary": summary,
            "cancelRequested": True,
            "cancelRequestedAt": now,
            "stopReason": stop_reason,
            "controlAction": "",
            "controlRequestedAt": "",
            _MANAGER_CONTROL_KEY: {
                "ownerPid": "",
                "kind": "self",
                "clearedAt": now,
                "reason": "orphaned",
            },
        }
    )
    _append_run_message_locked(
        payload,
        role="assistant",
        content=str(payload.get("latestMessage") or ""),
        timestamp=now,
    )
    return persist_manager_run_snapshot("self", payload, active_run_id="")


def _normalize_manager_latest_self_run(snapshot: dict[str, Any]) -> dict[str, Any]:
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _RUN_LOCKED_STATUSES:
        return snapshot
    active = load_manager_active_run_snapshot("self")
    active_run_id = str((active or {}).get("runId") or "").strip()
    snapshot_run_id = str(snapshot.get("runId") or "").strip()
    if active_run_id and active_run_id == snapshot_run_id and _manager_control_is_current(snapshot):
        return snapshot
    return _finalize_orphaned_manager_self_run(snapshot)


def _derive_self_live_phase(
    *,
    status: str,
    runtime_status: str,
    reading_task: str,
    last_tool_name: str,
    convergence_state: str,
) -> str:
    if status in {"queued", "stopping", "paused"}:
        return status
    if reading_task:
        return "reading"
    if runtime_status in {"thinking", "planning"}:
        return "thinking"
    if runtime_status in {"reading"}:
        return "reading"
    if runtime_status in {"editing", "patching", "writing"}:
        return "editing"
    if runtime_status in {"verifying", "testing", "validating"}:
        return "verifying"
    if runtime_status in {"answering", "responding"}:
        return "answering"
    if last_tool_name or runtime_status in {"tooling", "calling_tools", "calling-tools"}:
        return "tooling"
    if convergence_state in {"converged", "ready_to_answer"}:
        return "answering"
    return "running"


def _derive_self_current_task(
    *,
    phase: str,
    latest_message: str,
    reading_task: str,
    reading_hint: str,
    next_tool_intent: str,
    last_tool_name: str,
    stop_reason: str,
) -> str:
    if phase == "stopping":
        return stop_reason or latest_message or "Stopping current self-evolution pass."
    if phase == "reading":
        return reading_task or reading_hint or latest_message
    if phase == "tooling":
        return next_tool_intent or (f"tool:{last_tool_name}" if last_tool_name else latest_message)
    if phase == "verifying":
        return next_tool_intent or latest_message or "Verifying the latest changes."
    if phase == "editing":
        return next_tool_intent or latest_message or "Editing the current implementation."
    if phase == "thinking":
        return next_tool_intent or reading_hint or latest_message or "Thinking through the next step."
    if phase == "answering":
        return next_tool_intent or latest_message or "Preparing the current conclusion."
    return next_tool_intent or latest_message or reading_hint or reading_task


def _capture_preflight_state(run_id: str) -> dict[str, Any]:
    run_dir = _rollback_root() / run_id
    backup_dir = run_dir / "backups"
    manifest_path = run_dir / "rollback_manifest.json"
    backup_dir.mkdir(parents=True, exist_ok=True)
    base_rev = _git_head_rev()
    dirty_entries: dict[str, dict[str, Any]] = {}
    for path, status in _git_status_entries().items():
        abs_path = (PROJECT_ROOT / path).resolve()
        exists_before = abs_path.exists() and abs_path.is_file()
        backup_path = ""
        pre_hash = ""
        backup_error = ""
        if exists_before:
            try:
                pre_hash = _hash_file(abs_path)
                backup_path = _backup_file(abs_path, backup_dir)
            except OSError as exc:
                backup_error = str(exc)
        dirty_entries[path] = {
            "path": path,
            "status": status,
            "trackedBefore": status != "??",
            "existsBefore": exists_before,
            "preHash": pre_hash,
            "backupPath": backup_path,
            "backupError": backup_error,
        }
    preflight = {
        "runDir": str(run_dir),
        "backupDir": str(backup_dir),
        "manifestPath": str(manifest_path),
        "baseRev": base_rev,
        "dirtyEntries": dirty_entries,
    }
    backup_error_count = sum(
        1
        for item in dirty_entries.values()
        if isinstance(item, dict) and str(item.get("backupError") or "").strip()
    )
    _record_self_scene_event(
        "preflight",
        "self_evolution_run.preflight.captured",
        run_id=run_id,
        message="Self-evolution preflight state captured.",
        outcome="succeeded",
        fields={
            "baseRev": base_rev,
            "dirtyEntryCount": len(dirty_entries),
            "backupErrorCount": backup_error_count,
            "runDir": str(run_dir),
            "manifestPath": str(manifest_path),
        },
        lifecycle=True,
    )
    return preflight


def _finalize_rollback_manifest(run_id: str, preflight: dict[str, Any]) -> dict[str, Any] | None:
    lang = get_web_language()
    if not isinstance(preflight, dict):
        return None
    dirty_entries = preflight.get("dirtyEntries") if isinstance(preflight.get("dirtyEntries"), dict) else {}
    post_status = _git_status_entries()
    base_rev = str(preflight.get("baseRev") or "")
    touched_files: list[dict[str, Any]] = []
    candidate_paths = set(dirty_entries.keys()) | set(post_status.keys())
    for path in sorted(candidate_paths):
        pre_entry = dirty_entries.get(path) if isinstance(dirty_entries.get(path), dict) else None
        post_state = post_status.get(path, "")
        abs_path = (PROJECT_ROOT / path).resolve()
        current_exists = abs_path.exists() and abs_path.is_file()
        current_hash = _hash_file(abs_path) if current_exists else ""
        if pre_entry is None:
            if not post_state:
                continue
            existed_before = _path_exists_in_git_revision(path, base_rev)
            tracked_before = existed_before
            restore_source = "git" if existed_before else "delete"
            touched_files.append(
                {
                    "path": path,
                    "changeType": (
                        "created"
                        if not existed_before and current_exists
                        else "deleted"
                        if existed_before and not current_exists
                        else "modified"
                    ),
                    "trackedBefore": tracked_before,
                    "existedBefore": existed_before,
                    "preHash": "",
                    "postHash": current_hash,
                    "postExists": current_exists,
                    "backupPath": "",
                    "restoreSource": restore_source,
                    "statusAfter": post_state,
                    "conflict": False,
                    "conflictReason": "",
                }
            )
            continue

        existed_before = bool(pre_entry.get("existsBefore"))
        pre_hash = str(pre_entry.get("preHash") or "")
        changed = existed_before != current_exists
        if not changed and existed_before:
            changed = pre_hash != current_hash
        if not changed:
            continue
        if not existed_before:
            change_type = "created" if current_exists else "unchanged"
            restore_source = "delete"
        elif not current_exists:
            change_type = "deleted"
            restore_source = "backup" if str(pre_entry.get("backupPath") or "") else "delete"
        else:
            change_type = "modified"
            restore_source = "backup" if str(pre_entry.get("backupPath") or "") else "delete"
        touched_files.append(
            {
                "path": path,
                "changeType": change_type,
                "trackedBefore": bool(pre_entry.get("trackedBefore")),
                "existedBefore": existed_before,
                "preHash": pre_hash,
                "postHash": current_hash,
                "postExists": current_exists,
                "backupPath": str(pre_entry.get("backupPath") or ""),
                "restoreSource": restore_source,
                "statusAfter": post_state,
                "conflict": False,
                "conflictReason": "",
            }
        )

    rollback_state = _build_rollback_state(
        lang=lang,
        status="available" if touched_files else "unavailable",
        reason=(
            text_for(
                lang,
                zh="可以把这轮网页自进化回滚到启动前的文件状态。",
                en="This web self-evolution pass can be rolled back to its pre-run file state.",
            )
            if touched_files
            else text_for(
                lang,
                zh="这一轮没有留下需要回滚的文件差异。",
                en="This run did not leave any file diff that needs rollback.",
            )
        ),
        base_rev=base_rev,
        touched_files=touched_files,
        conflict_files=[],
        rolled_back_at="",
    )
    manifest_payload = {
        "version": 1,
        "runId": run_id,
        "generatedAt": _now_timestamp(),
        "baseRev": base_rev,
        "display": rollback_state,
        "entries": touched_files,
    }
    manifest_path = Path(str(preflight.get("manifestPath") or "")).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rollback_state


def _build_rollback_state(
    *,
    lang: str,
    status: str,
    reason: str,
    base_rev: str,
    touched_files: list[dict[str, Any]],
    conflict_files: list[dict[str, Any]],
    rolled_back_at: str,
) -> dict[str, Any]:
    enriched_touched = []
    conflict_map = {str(item.get("path") or ""): item for item in conflict_files}
    for item in touched_files:
        conflict = conflict_map.get(str(item.get("path") or ""))
        enriched_touched.append(
            {
                "path": str(item.get("path") or ""),
                "changeType": str(item.get("changeType") or "modified"),
                "trackedBefore": bool(item.get("trackedBefore")),
                "existedBefore": bool(item.get("existedBefore")),
                "statusAfter": str(item.get("statusAfter") or ""),
                "preHash": str(item.get("preHash") or ""),
                "postHash": str(item.get("postHash") or ""),
                "postExists": bool(item.get("postExists")),
                "conflict": bool(conflict),
                "conflictReason": str((conflict or {}).get("reason") or ""),
            }
        )
    return {
        "status": status,
        "reason": reason,
        "baseRev": base_rev,
        "rolledBackAt": rolled_back_at,
        "entryCount": len(enriched_touched),
        "touchedFiles": enriched_touched,
        "conflictFiles": [
            {
                "path": str(item.get("path") or ""),
                "reason": str(item.get("reason") or ""),
                "currentHash": str(item.get("currentHash") or ""),
                "expectedHash": str(item.get("expectedHash") or ""),
            }
            for item in conflict_files
        ],
        "blockedHint": (
            text_for(
                lang,
                zh="如果这些文件已经被后续改动污染，请把这次回滚交给会话 agent 继续处理。",
                en="If later edits contaminated these files, hand this rollback off to the session agent instead.",
            )
            if status == "blocked"
            else ""
        ),
    }


def _initial_rollback_state(lang: str, *, base_rev: str) -> dict[str, Any]:
    return _build_rollback_state(
        lang=lang,
        status="unavailable",
        reason=text_for(
            lang,
            zh="这一轮还没结束，暂时不能生成安全回滚清单。",
            en="This pass has not finished yet, so a safe rollback manifest is not available.",
        ),
        base_rev=base_rev,
        touched_files=[],
        conflict_files=[],
        rolled_back_at="",
    )


def _detect_rollback_conflicts(
    state: dict[str, Any],
    *,
    entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rollback_entries = entries
    if rollback_entries is None:
        manifest = _load_rollback_manifest(state)
        rollback_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    if not rollback_entries:
        rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
        rollback_entries = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    conflicts: list[dict[str, Any]] = []
    for item in rollback_entries:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        abs_path = (PROJECT_ROOT / path).resolve()
        current_exists = abs_path.exists() and abs_path.is_file()
        current_hash = _hash_file(abs_path) if current_exists else ""
        expected_exists = bool(item.get("postExists"))
        expected_hash = str(item.get("postHash") or "")
        if current_exists != expected_exists or current_hash != expected_hash:
            conflicts.append(
                {
                    "path": path,
                    "reason": text_for(
                        get_web_language(),
                        zh="这个文件在进化后又被修改过了。",
                        en="This file changed again after the self-evolution pass.",
                    ),
                    "currentHash": current_hash,
                    "expectedHash": expected_hash,
                }
            )
    return conflicts


def _apply_rollback_entries(state: dict[str, Any], touched_files: list[dict[str, Any]]) -> None:
    base_rev = str(((state.get("rollback") or {}) if isinstance(state.get("rollback"), dict) else {}).get("baseRev") or "")
    for item in touched_files:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        abs_path = (PROJECT_ROOT / path).resolve()
        restore_source = str(item.get("restoreSource") or "").strip().lower()
        existed_before = bool(item.get("existedBefore"))
        backup_path = str(item.get("backupPath") or "").strip()
        if restore_source == "git" and existed_before and base_rev:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["restore", "--source", base_rev, "--worktree", "--", path])
            continue
        if restore_source == "backup" and backup_path:
            backup_file = Path(backup_path).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup_file, abs_path)
            continue
        if abs_path.exists():
            abs_path.unlink()


def _build_session_handoff_message(state: dict[str, Any]) -> str:
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    conflicts = rollback.get("conflictFiles") if isinstance(rollback.get("conflictFiles"), list) else []
    touched = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    lines = [
        "请接手一条网页自进化回滚请求。",
        "",
        f"- run_id: {state.get('runId') or '--'}",
        f"- goal: {state.get('goal') or '--'}",
        f"- status: {state.get('status') or '--'}",
        f"- rollback_status: {rollback.get('status') or '--'}",
        f"- rollback_reason: {rollback.get('reason') or '--'}",
        f"- started_at: {state.get('startedAt') or '--'}",
        f"- finished_at: {state.get('finishedAt') or '--'}",
        "",
        "请先判断这些文件是否还能安全恢复到进化前状态；如果不能安全恢复，就给出最小人工处理建议。",
        "不要覆盖不确定来源的后续改动。",
        "",
        "touched_files:",
    ]
    if touched:
        lines.extend(
            f"- {item.get('path') or '--'} | change={item.get('changeType') or '--'} | conflict={bool(item.get('conflict'))}"
            for item in touched
        )
    else:
        lines.append("- --")
    lines.append("")
    lines.append("conflicts:")
    if conflicts:
        lines.extend(f"- {item.get('path') or '--'} | {item.get('reason') or '--'}" for item in conflicts)
    else:
        lines.append("- --")
    return "\n".join(lines).strip()


def _load_rollback_manifest(state: dict[str, Any]) -> dict[str, Any]:
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    manifest_path = Path(str(artifacts.get("manifestPath") or "")).resolve() if artifacts.get("manifestPath") else None
    payload: dict[str, Any] = {}
    if manifest_path is not None:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            payload = raw
    display = payload.get("display") if isinstance(payload.get("display"), dict) else (
        payload if "status" in payload else rollback
    )
    if not isinstance(display, dict):
        display = rollback
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return {
        "display": display if isinstance(display, dict) else {},
        "entries": entries,
        "baseRev": str(payload.get("baseRev") or display.get("baseRev") or rollback.get("baseRev") or ""),
    }


def _require_run_snapshot(run_id: str) -> dict[str, Any]:
    lang = get_web_language()
    snapshot = get_self_evolution_run_snapshot(run_id)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )
    return snapshot


def _require_terminal_run(run_id: str) -> dict[str, Any]:
    lang = get_web_language()
    state = _require_run_snapshot(run_id)
    if str(state.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES:
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前这轮还在运行，先等它收口后再回滚。",
                en="This pass is still running. Wait for it to close before rollback.",
            )
        )
    return state


def _git_status_entries() -> dict[str, str]:
    output = _run_git(["-c", "status.renames=false", "status", "--porcelain=v1", "--untracked-files=all"], capture_text=True)
    entries: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:].strip().replace("\\", "/")
        if path:
            entries[path] = status
    return entries


def _git_head_rev() -> str:
    return _run_git(["rev-parse", "HEAD"], capture_text=True).strip()


def _path_exists_in_git_revision(path: str, revision: str) -> bool:
    normalized_path = str(path or "").strip().replace("\\", "/")
    normalized_revision = str(revision or "").strip()
    if not normalized_path or not normalized_revision:
        return False
    completed = git_process.run_git(
        ["-C", str(PROJECT_ROOT), "cat-file", "-e", f"{normalized_revision}:{normalized_path}"],
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _run_git(args: list[str], *, capture_text: bool = False) -> str:
    completed = git_process.run_git(
        ["-C", str(PROJECT_ROOT), *args],
        check=True,
        capture_output=True,
        text=capture_text,
    )
    if capture_text:
        return completed.stdout
    return ""


def _backup_file(abs_path: Path, backup_dir: Path) -> str:
    relative = abs_path.resolve().relative_to(PROJECT_ROOT)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(abs_path, target)
    return str(target)


def _hash_file(abs_path: Path) -> str:
    digest = hashlib.sha256()
    with abs_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _load_runtime_state() -> dict[str, Any]:
    try:
        payload = json.loads(_runtime_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_state_path() -> Path:
    return developer_sandbox.route_workspace_path(
        PROJECT_ROOT,
        "runtime",
        "ui_runtime_state.json",
        intent="state",
        seed=True,
    )


def _rollback_root() -> Path:
    return developer_sandbox.route_workspace_path(
        PROJECT_ROOT,
        "self_evolution",
        "web_self_evolution",
        intent="state",
        seed=True,
    )


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


_LOCAL_GET_ACTIVE_SELF_EVOLUTION_RUN = get_active_self_evolution_run
_LOCAL_GET_LATEST_SELF_EVOLUTION_RUN = get_latest_self_evolution_run
_LOCAL_GET_SELF_EVOLUTION_RUN_SNAPSHOT = get_self_evolution_run_snapshot
_LOCAL_STREAM_SELF_EVOLUTION_RUN_EVENTS = stream_self_evolution_run_events
_LOCAL_HAS_ACTIVE_SELF_EVOLUTION_RUN = has_active_self_evolution_run
_LOCAL_START_SELF_EVOLUTION_RUN = start_self_evolution_run
_LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN = request_pause_self_evolution_run
_LOCAL_RESUME_SELF_EVOLUTION_RUN = resume_self_evolution_run
_LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN = request_stop_self_evolution_run


def _stream_manager_self_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    snapshot = initial_snapshot or load_manager_run_snapshot("self", normalized)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    last_signature = _snapshot_signature(snapshot)
    last_keepalive = time.monotonic()
    terminal = _is_terminal_run_snapshot(snapshot)
    yield _encode_sse_event(
        "self_evolution_run",
        {
            "type": "self_evolution_run",
            "runId": normalized,
            "snapshot": snapshot,
            "terminal": terminal,
        },
    )
    if terminal:
        return

    while True:
        latest = load_manager_run_snapshot("self", normalized)
        if latest is not None:
            signature = _snapshot_signature(latest)
            if signature != last_signature:
                last_signature = signature
                terminal = _is_terminal_run_snapshot(latest)
                yield _encode_sse_event(
                    "self_evolution_run",
                    {
                        "type": "self_evolution_run",
                        "runId": normalized,
                        "snapshot": latest,
                        "terminal": terminal,
                    },
                )
                last_keepalive = time.monotonic()
                if terminal:
                    break
        if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_keepalive = time.monotonic()
        time.sleep(_RUN_STREAM_POLL_SECONDS)


def _submit_self_runtime_manager_command(command_type: str, *, run_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_runtime_manager_daemon()
    args: dict[str, Any] = {}
    if run_id:
        args["runId"] = run_id
    if payload is not None:
        args["payload"] = payload
        if command_type == "restart_self_evolution_run" and str(payload.get("reason") or "").strip():
            args["reason"] = str(payload.get("reason") or "").strip()
    command = submit_command(command_type, args=args, requested_by="web_ui")
    result = wait_for_result(command["commandId"])
    if not bool(result.get("ok")):
        _record_self_scene_event(
            "runtime_manager",
            f"self_evolution_run.manager.{command_type}.failed",
            run_id=run_id,
            message=str(result.get("message") or "Runtime manager command failed."),
            level="error",
            outcome="failed",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                "errorType": str(result.get("errorType") or ""),
            },
            lifecycle=True,
        )
        raise _map_runtime_manager_error(
            str(result.get("message") or "Runtime manager command failed."),
            str(result.get("errorType") or ""),
        )
    if command_type == "restart_self_evolution_run":
        snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
        target_run_id = str(result.get("runId") or snapshot.get("runId") or run_id or "").strip()
        loaded = load_manager_run_snapshot("self", target_run_id) if target_run_id else None
        effective_snapshot = loaded if loaded is not None else snapshot
        _record_self_scene_event(
            "runtime_manager",
            f"self_evolution_run.manager.{command_type}.succeeded",
            run_id=target_run_id,
            message="Self-evolution restart intent accepted by runtime manager.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                "intentId": str((result.get("restartIntent") or {}).get("intentId") or ""),
                **(_self_snapshot_event_fields(effective_snapshot) if isinstance(effective_snapshot, dict) else {}),
            },
            lifecycle=True,
        )
        return {
            "runId": target_run_id,
            "snapshot": effective_snapshot if isinstance(effective_snapshot, dict) else {},
            "restartIntent": result.get("restartIntent") if isinstance(result.get("restartIntent"), dict) else {},
        }
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    if snapshot is not None and str(snapshot.get("runId") or run_id or "").strip():
        _record_self_scene_event(
            "runtime_manager",
            f"self_evolution_run.manager.{command_type}.succeeded",
            run_id=str(snapshot.get("runId") or run_id),
            message="Self-evolution runtime-manager command succeeded.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                **_self_snapshot_event_fields(snapshot),
            },
            lifecycle=True,
        )
        return snapshot
    target_run_id = str(result.get("runId") or run_id or "").strip()
    loaded = load_manager_run_snapshot("self", target_run_id) if target_run_id else None
    if loaded is not None:
        _record_self_scene_event(
            "runtime_manager",
            f"self_evolution_run.manager.{command_type}.succeeded",
            run_id=target_run_id,
            message="Self-evolution runtime-manager command loaded snapshot.",
            outcome="succeeded",
            fields={
                "commandType": command_type,
                "commandId": str(command.get("commandId") or ""),
                **_self_snapshot_event_fields(loaded),
            },
            lifecycle=True,
        )
        return loaded
    missing_snapshot_message = "Runtime manager command completed without a self-evolution snapshot."
    _record_self_scene_event(
        "runtime_manager",
        f"self_evolution_run.manager.{command_type}.failed",
        run_id=target_run_id,
        message=missing_snapshot_message,
        level="error",
        outcome="failed",
        fields={
            "commandType": command_type,
            "commandId": str(command.get("commandId") or ""),
            "errorType": "MissingRuntimeManagerSnapshot",
        },
        lifecycle=True,
    )
    raise SelfEvolutionRunValidationError(missing_snapshot_message)


def get_active_self_evolution_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("self")
        if snapshot is None:
            return None
        status = str(snapshot.get("status") or "").strip().lower()
        if status not in _RUN_LOCKED_STATUSES:
            return None
        if not _manager_control_is_current(snapshot):
            _finalize_orphaned_manager_self_run(snapshot)
            return None
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_ACTIVE_SELF_EVOLUTION_RUN()


def get_latest_self_evolution_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_latest_run_snapshot("self")
        if snapshot is None:
            return None
        snapshot = _normalize_manager_latest_self_run(snapshot)
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_LATEST_SELF_EVOLUTION_RUN()


def get_self_evolution_run_snapshot(run_id: str) -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_run_snapshot("self", run_id)
        if snapshot is None:
            return None
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_SELF_EVOLUTION_RUN_SNAPSHOT(run_id)


def stream_self_evolution_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    if _runtime_manager_live_control_enabled():
        return _stream_manager_self_events(run_id, initial_snapshot=initial_snapshot)
    return _LOCAL_STREAM_SELF_EVOLUTION_RUN_EVENTS(run_id, initial_snapshot=initial_snapshot)


def has_active_self_evolution_run() -> bool:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("self")
        if snapshot is None:
            return False
        status = str(snapshot.get("status") or "").strip().lower()
        if status not in _RUN_LOCKED_STATUSES:
            return False
        if not _manager_control_is_current(snapshot):
            _finalize_orphaned_manager_self_run(snapshot)
            return False
        return True
    return _LOCAL_HAS_ACTIVE_SELF_EVOLUTION_RUN()


def start_self_evolution_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        lang = get_web_language()
        contract = get_workbench_contract()
        if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
            raise SelfEvolutionRunValidationError(
                text_for(
                    lang,
                    zh="配置里没有启用 self_evolution，当前不能从网页启动这一轮。",
                    en="The current config does not enable self_evolution, so the web surface cannot launch this pass.",
                )
            )
        goal = str(payload.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
        _raise_if_self_evolution_requires_worktree_isolation(payload, goal, lang=lang)
        if active_session_has_write_leases():
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前有写入型网页会话还在运行，请等这一轮结束后再启动自进化。",
                    en="A write-capable web chat turn is still running. Wait for it to finish before launching self evolution.",
                )
            )
        _raise_if_self_lease_conflict(lang=lang)
        active_supervised = get_active_supervised_run()
        if active_supervised is not None and str(active_supervised.get("status") or "").strip().lower() in {"queued", "running", "paused", "stopping"}:
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已有监督任务在运行，请等监督任务结束后再启动自进化。",
                    en="A supervised run is already active. Wait for it to finish before launching self evolution.",
                )
            )
        return _submit_self_runtime_manager_command("start_self_evolution_run", payload=payload)
    snapshot = _LOCAL_START_SELF_EVOLUTION_RUN(payload)
    _record_self_scene_event(
        "control",
        "self_evolution_run.started",
        run_id=str(snapshot.get("runId") or ""),
        message="Self-evolution run started from web UI.",
        outcome="succeeded",
        fields=_self_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def request_pause_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_self_runtime_manager_command("pause_self_evolution_run", run_id=run_id)
    snapshot = _LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN(run_id)
    _record_self_scene_event(
        "control",
        "self_evolution_run.pause_requested",
        run_id=run_id,
        message="Self-evolution run pause requested.",
        outcome="succeeded",
        fields=_self_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def resume_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        if active_session_has_write_leases():
            raise SelfEvolutionRunBusyError(
                text_for(
                    get_web_language(),
                    zh="当前有写入型网页会话还在运行，请等这一轮结束后再继续自进化。",
                    en="A write-capable web chat turn is still running. Wait for it to finish before resuming self evolution.",
                )
        )
        _raise_if_self_lease_conflict(lang=get_web_language())
        return _submit_self_runtime_manager_command("resume_self_evolution_run", run_id=run_id)
    snapshot = _LOCAL_RESUME_SELF_EVOLUTION_RUN(run_id)
    _record_self_scene_event(
        "control",
        "self_evolution_run.resumed",
        run_id=run_id,
        message="Self-evolution run resumed.",
        outcome="succeeded",
        fields=_self_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot


def request_stop_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_self_runtime_manager_command("stop_self_evolution_run", run_id=run_id)
    snapshot = _LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN(run_id)
    _record_self_scene_event(
        "control",
        "self_evolution_run.stop_requested",
        run_id=run_id,
        message="Self-evolution run stop requested.",
        outcome="succeeded",
        fields=_self_snapshot_event_fields(snapshot),
        lifecycle=True,
    )
    return snapshot
