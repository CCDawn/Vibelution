"""Read-only Session activity contract; the Journal and worker remain writers.

Legacy ``currentPhase`` can contain a status. Decode that only at this boundary;
``lastTurnStatus`` and ``terminalReason`` describe an outcome, never live work.
The frontend vocabulary is generated from SESSION_ACTIVITY_CONTRACT.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ACTIVITY_STATUS_LABELS = {
    "queued": "排队中", "running": "进行中", "stopping": "停止中", "paused": "已暂停",
    "completed": "已完成", "failed": "失败", "stopped": "已停止", "cancelled": "已取消",
    "needs_continue": "待继续", "paused_limit": "达到限制，待继续", "superseded": "已替代",
    "idle": "空闲", "settled": "已结束", "unknown": "未知状态",
}
ACTIVITY_STATUS_LABELS_EN = {
    "queued": "Queued", "running": "Running", "stopping": "Stopping", "paused": "Paused",
    "completed": "Completed", "failed": "Failed", "stopped": "Stopped", "cancelled": "Cancelled",
    "needs_continue": "Needs continuation", "paused_limit": "Limit reached, needs continuation", "superseded": "Superseded",
    "idle": "Idle", "settled": "Ended", "unknown": "Unknown state",
}

SESSION_ACTIVITY_CONTRACT = {
    "labels": ACTIVITY_STATUS_LABELS,
    "labelsEn": ACTIVITY_STATUS_LABELS_EN,
    "phases": ["thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"],
    "phaseLabels": {"thinking": "思考中", "tooling": "使用工具", "answering": "回复中", "planning": "规划中", "reading": "读取中", "editing": "编辑中", "verifying": "验证中"},
    "phaseLabelsEn": {"thinking": "Thinking", "tooling": "Using tools", "answering": "Responding", "planning": "Planning", "reading": "Reading", "editing": "Editing", "verifying": "Verifying"},
    "phaseAliases": {"tool": "tooling", "streaming": "answering", "checking": "verifying", "working": "thinking"},
    "executions": {
        "queued": "queued", "running": "running", "active": "running", "started": "running",
        "starting": "running", "in_progress": "running", "resuming": "running",
        "stopping": "stopping", "force_stopping": "stopping", "pausing": "paused", "paused": "paused",
    },
    "resting": ["ready", "idle"],
    "policy": {
        "ownedExecutions": ["queued", "running", "stopping", "paused"],
        "outputExecutions": ["queued", "running"],
        "restingExecutions": ["idle", "settled"],
        "continuableOutcomes": ["stopped", "cancelled", "needs_continue", "paused_limit"],
        "waitingOutcomes": ["needs_continue", "paused_limit"],
        "executionGroups": {"queued": "running", "running": "running", "stopping": "running", "paused": "waiting", "idle": "idle", "settled": "idle", "unknown": "unknown"},
    },
    "outcomes": {
        "completed": "completed", "done": "completed", "success": "completed", "succeeded": "completed",
        "failed": "failed", "failure": "failed", "error": "failed", "failed_runtime": "failed",
        "failed_provider": "failed", "timeout": "failed", "timed_out": "failed", "blocked": "failed",
        "danger": "failed", "crashed": "failed", "unhealthy": "failed",
        "stopped": "stopped", "stopped_by_user": "stopped", "force_stopped": "stopped", "aborted": "stopped", "interrupted": "stopped",
        "cancelled": "cancelled", "canceled": "cancelled", "superseded": "superseded",
        "needs_continue": "needs_continue", "paused_limit": "paused_limit",
    },
}

# Native transport receives canonical success but preserves failure and
# continuation receipts. User stops stay silent; abnormal interruptions notify.
# Derive aliases from their owning Session vocabulary instead of copying a list.
SESSION_NOTIFICATION_CONTRACT = {
    "successTerminalStatuses": ["completed"],
    "continuationTerminalStatuses": SESSION_ACTIVITY_CONTRACT["policy"]["waitingOutcomes"],
    "terminalStatuses": sorted(
        reason for reason, outcome in SESSION_ACTIVITY_CONTRACT["outcomes"].items()
        if outcome in {"failed", "cancelled", "superseded", "needs_continue", "paused_limit"}
        or reason in {"completed", "aborted", "interrupted"}
    ),
}


def normalize_activity_value(value: Any) -> str:
    return str(value or "").strip().lower()


def activity_phase(value: Any) -> str:
    normalized = normalize_activity_value(value)
    if normalized in SESSION_ACTIVITY_CONTRACT["phases"]:
        return normalized
    return SESSION_ACTIVITY_CONTRACT["phaseAliases"].get(normalized, "")


def activity_execution(value: Any) -> str:
    normalized = normalize_activity_value(value)
    return SESSION_ACTIVITY_CONTRACT["executions"].get(normalized, "") or ("running" if activity_phase(value) else "")


def execution_owns_turn(value: Any) -> bool:
    return activity_execution(value) in SESSION_ACTIVITY_CONTRACT["policy"]["ownedExecutions"]


def activity_outcome(value: Any) -> str:
    return SESSION_ACTIVITY_CONTRACT["outcomes"].get(normalize_activity_value(value), "")


def resolve_session_activity(
    session: Mapping[str, Any], *, runtime_running: bool = False, authoritative_runtime: bool = False,
) -> dict[str, str]:
    """Separate execution, phase and result without combining unrelated fields.

    Reconciled backend WorkRuns are authoritative. A frontend runtime hint can
    lag a settled receipt, so it only fills a genuinely missing live status.
    Unknown explicit values stay unknown; they cannot inherit an old success.
    """
    status = normalize_activity_value(session.get("status"))
    legacy_phase = normalize_activity_value(session.get("currentPhase"))
    child = normalize_activity_value(session.get("childStatus")) if session.get("sessionKind") == "child" else ""
    # childStatus is projected from last_turn_status in native child Sessions.
    # It is only a legacy live fallback when the current fields are absent.
    current = [value for value in (status, legacy_phase) if value] or ([child] if child else [])
    phase = next((activity_phase(value) for value in (legacy_phase, status, child if not (status or legacy_phase) else "") if activity_phase(value)), "")
    raw = status or legacy_phase or child
    result = {"execution": "unknown", "phase": "", "outcome": "", "reason": "", "rawStatus": raw}
    execution = next((activity_execution(value) for value in current if activity_execution(value)), "")
    reason = normalize_activity_value(session.get("terminalReason"))
    active_turn_id = str(session.get("activeTurnId") or "").strip()
    # A terminal projection can precede the worker's in-memory owner cleanup.
    # Only the exact Journal terminal identity can retire that stale owner;
    # a live phase or reconciled runtime still takes precedence below.
    settled_owner = bool(
        active_turn_id
        and active_turn_id == str(session.get("lastTurnTerminalTurnId") or "").strip()
        and activity_outcome(reason)
    )
    if execution or (active_turn_id and not settled_owner) or (runtime_running and authoritative_runtime):
        return {**result, "execution": execution or "running", "phase": phase}
    if any(not activity_outcome(value) and value not in SESSION_ACTIVITY_CONTRACT["resting"] for value in current):
        return result
    # Ready/running are historical placeholders in terminalReason, not outcomes.
    if reason and not activity_outcome(reason) and reason not in {"ready", "idle", "running"}:
        return result
    outcome_candidates = (reason, status, legacy_phase, normalize_activity_value(session.get("lastTurnStatus")), child)
    terminal = next((value for value in outcome_candidates if activity_outcome(value)), "")
    if terminal:
        return {**result, "execution": "settled", "outcome": activity_outcome(terminal), "reason": terminal}
    if runtime_running and "ready" not in current:
        return {**result, "execution": "running"}
    if any(value in SESSION_ACTIVITY_CONTRACT["resting"] for value in current):
        return {**result, "execution": "idle"}
    return result


def session_activity_policy(session: Mapping[str, Any]) -> dict[str, bool]:
    """Policies consume decoded execution, never a historical result field.

    Pausing output does not release ownership. Unknown state does not prove
    that deleting/archiving the Session is safe; drafts remain a UI concern.
    """
    state = resolve_session_activity(session)
    execution = state["execution"]
    policy = SESSION_ACTIVITY_CONTRACT["policy"]
    return {
        "executionOwned": execution in policy["ownedExecutions"],
        "outputActive": execution in policy["outputExecutions"],
        "stopping": execution == "stopping",
        "atRest": execution in policy["restingExecutions"],
        "blocksMutation": execution not in policy["restingExecutions"],
    }


def activity_can_continue(value: Any) -> bool:
    return activity_outcome(value) in SESSION_ACTIVITY_CONTRACT["policy"]["continuableOutcomes"]


def session_activity_group(session: Mapping[str, Any], *, needs_approval: bool = False) -> str:
    state = resolve_session_activity(session)
    if needs_approval:
        return "waiting"
    if state["outcome"] == "failed":
        return "failed"
    return SESSION_ACTIVITY_CONTRACT["policy"]["executionGroups"][state["execution"]]
