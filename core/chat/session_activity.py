"""Read-only Session activity contract; the Journal and worker remain writers.

Legacy ``currentPhase`` can contain a status. Decode that only at this boundary;
``lastTurnStatus`` and ``terminalReason`` describe an outcome, never live work.
The frontend vocabulary is generated from SESSION_ACTIVITY_CONTRACT.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SESSION_ACTIVITY_CONTRACT = {
    "phases": ["thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"],
    "phaseLabels": {"thinking": "思考中", "tooling": "使用工具", "answering": "回复中", "planning": "规划中", "reading": "读取中", "editing": "编辑中", "verifying": "验证中"},
    "phaseAliases": {"tool": "tooling", "streaming": "answering", "checking": "verifying", "working": "thinking"},
    "executions": {
        "queued": "queued", "running": "running", "active": "running", "started": "running",
        "starting": "running", "in_progress": "running", "resuming": "running",
        "stopping": "stopping", "force_stopping": "stopping", "pausing": "paused", "paused": "paused",
    },
    "resting": ["ready", "idle"],
    "outcomes": {
        "completed": "completed", "done": "completed", "success": "completed", "succeeded": "completed",
        "failed": "failed", "failure": "failed", "error": "failed", "failed_runtime": "failed",
        "failed_provider": "failed", "timeout": "failed", "timed_out": "failed", "blocked": "failed",
        "danger": "failed", "crashed": "failed", "unhealthy": "failed",
        "stopped": "stopped", "stopped_by_user": "stopped", "force_stopped": "stopped", "aborted": "stopped",
        "cancelled": "cancelled", "canceled": "cancelled", "superseded": "superseded",
        "needs_continue": "needs_continue", "paused_limit": "paused_limit",
    },
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
    if raw and not (activity_outcome(raw) or raw in SESSION_ACTIVITY_CONTRACT["resting"]):
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
