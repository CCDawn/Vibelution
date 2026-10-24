"""AgentRun lifecycle vocabulary, distinct from Session readiness and activity."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.chat.session_activity import ACTIVITY_STATUS_LABELS, ACTIVITY_STATUS_LABELS_EN, activity_phase, normalize_activity_value

RUN_STATUS_LABELS = {key: label for key, label in ACTIVITY_STATUS_LABELS.items() if key != "settled"}
RUN_STATUS_LABELS_EN = {key: label for key, label in ACTIVITY_STATUS_LABELS_EN.items() if key != "settled"}
RUN_STATUS_ALIASES = {
    "done": "completed", "success": "completed", "succeeded": "completed",
    "failed_provider": "failed", "failed_runtime": "failed", "failure": "failed", "error": "failed",
    "timeout": "failed", "timed_out": "failed", "blocked": "failed", "stop_failed": "failed",
    "stopped_by_user": "stopped", "force_stopped": "stopped", "aborted": "stopped",
    "canceled": "cancelled", "pending": "queued", "waiting": "paused", "ready": "idle",
    "active": "running", "started": "running", "starting": "running", "in_progress": "running",
    "resuming": "running", "pausing": "paused", "force_stopping": "stopping",
}
RUN_ACTIVE_STATUSES = frozenset({"queued", "running", "stopping", "paused"})
RUN_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped", "cancelled", "needs_continue", "paused_limit", "superseded"})
RUN_REASON_LABELS = {
    "failed_provider": "模型服务失败", "failed_runtime": "运行失败", "error": "运行错误",
    "timeout": "执行超时", "timed_out": "执行超时", "blocked": "已阻塞", "stop_failed": "停止失败",
    "stopped_by_user": "用户停止", "force_stopped": "强制停止", "aborted": "执行中断",
}
RUN_REASON_LABELS_EN = {
    "failed_provider": "Model service failed", "failed_runtime": "Execution failed", "error": "Runtime error",
    "timeout": "Execution timed out", "timed_out": "Execution timed out", "blocked": "Blocked", "stop_failed": "Stop failed",
    "stopped_by_user": "Stopped by user", "force_stopped": "Force stopped", "aborted": "Aborted",
}


def normalize_run_status(value: Any) -> str:
    normalized = normalize_activity_value(value)
    if normalized in RUN_STATUS_LABELS:
        return normalized
    if normalized in RUN_STATUS_ALIASES:
        return RUN_STATUS_ALIASES[normalized]
    return "running" if activity_phase(normalized) else "unknown"


def run_activity_fields(status: str, result: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, str]:
    raw = normalize_activity_value(status or result.get("status") or previous.get("rawStatus") or previous.get("status"))
    normalized = normalize_run_status(raw)
    result_raw = normalize_activity_value(result.get("status") or result.get("currentPhase"))
    if result_raw and normalize_run_status(result_raw) == normalized:
        raw = result_raw
    # Keep the provider/user/force cause separate from the normalized lifecycle.
    reason = normalize_activity_value(result.get("terminalReason"))
    if reason and normalize_run_status(reason) != normalized:
        reason = ""
    if normalized in RUN_TERMINAL_STATUSES:
        previous_reason = normalize_activity_value(previous.get("terminalReason"))
        if normalize_run_status(previous_reason) != normalized:
            previous_reason = ""
        reason = reason or (previous_reason if previous.get("status") == normalized else "") or raw
    else:
        reason = ""
    phase = ""
    if normalized in RUN_ACTIVE_STATUSES:
        phase = next((activity_phase(value) for value in (
            result.get("currentPhase"), result.get("phase"), raw, previous.get("currentPhase"),
        ) if activity_phase(value)), "")
    return {"status": normalized, "currentPhase": phase, "terminalReason": reason, "rawStatus": raw}


def public_run_activity(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Decode canonical public fields without rewriting historical snapshots."""
    status = normalize_activity_value(snapshot.get("status"))
    if not status:
        status = normalize_activity_value(snapshot.get("currentPhase"))
    fields = run_activity_fields(status, snapshot, {})
    # A previously normalized unknown value must retain its original diagnostic.
    diagnostic = normalize_activity_value(snapshot.get("rawStatus"))
    if diagnostic and normalize_run_status(diagnostic) == fields["status"]:
        fields["rawStatus"] = diagnostic
    if (
        fields["status"] == "stopped" and snapshot.get("runtimeStatus") == "force_stopped"
        and normalize_run_status(snapshot.get("terminalReason")) != "stopped"
    ):
        fields["terminalReason"] = "force_stopped"
    return {
        "status": fields["status"], "currentPhase": fields["currentPhase"],
        "terminalReason": fields["terminalReason"], "rawStatus": fields["rawStatus"],
    }
