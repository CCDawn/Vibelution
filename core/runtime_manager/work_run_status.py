"""Read-only activity and lifecycle protection for heterogeneous WorkRuns.

Snapshots remain owned by their kind's writer. This boundary decodes legacy
status/phase fields without changing Session or AgentRun persistence contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from core.chat.session_activity import (
    ACTIVITY_STATUS_LABELS,
    ACTIVITY_STATUS_LABELS_EN,
    SESSION_ACTIVITY_CONTRACT,
    activity_phase,
    normalize_activity_value,
)


WORK_RUN_ACTIVITY_CONTRACT = {
    "labels": {**ACTIVITY_STATUS_LABELS, "partial": "部分完成", "closed": "已关闭", "routed": "已转交"},
    "labelsEn": {**ACTIVITY_STATUS_LABELS_EN, "partial": "Partially completed", "closed": "Closed", "routed": "Routed"},
    "statusFields": ["status", "currentPhase", "phase", "runtimeStatus"],
    "phases": list(SESSION_ACTIVITY_CONTRACT["phases"]),
    "phaseLabels": dict(SESSION_ACTIVITY_CONTRACT["phaseLabels"]),
    "phaseAliases": dict(SESSION_ACTIVITY_CONTRACT["phaseAliases"]),
    "executions": {
        **SESSION_ACTIVITY_CONTRACT["executions"],
        "pending": "queued", "waiting": "paused",
    },
    "resting": ["ready", "idle"],
    "outcomes": {
        "completed": "completed", "done": "completed", "success": "completed", "succeeded": "completed",
        "failed": "failed", "failed_provider": "failed", "failed_runtime": "failed",
        "failure": "failed", "error": "failed", "stop_failed": "failed",
        "stopped": "stopped", "stopped_by_user": "stopped", "force_stopped": "stopped", "aborted": "stopped",
        "cancelled": "cancelled", "canceled": "cancelled", "superseded": "superseded",
        "needs_continue": "needs_continue", "paused_limit": "paused_limit",
        "partial": "partial", "closed": "closed", "routed": "routed",
    },
    "policy": {"ownedExecutions": ["queued", "running", "stopping", "paused"]},
}


class WorkRunActivity(TypedDict):
    execution: str
    phase: str
    outcome: str
    reason: str
    rawStatus: str
    blocksLifecycle: bool


def resolve_work_run_activity(payload: Mapping[str, Any]) -> WorkRunActivity:
    """Use the first explicit state; only an end receipt overrides protection.

    A phase proves live work, never successful completion. An unknown explicit
    state cannot inherit a terminal verdict from a lower-priority field or an
    old terminalReason. End timestamps prove settlement without inventing its
    outcome, including when a snapshot still contains an active state.
    """
    raw = next((
        value for field in WORK_RUN_ACTIVITY_CONTRACT["statusFields"]
        if (value := normalize_activity_value(payload.get(field)))
    ), "")
    outcome = WORK_RUN_ACTIVITY_CONTRACT["outcomes"].get(raw, "")
    execution = WORK_RUN_ACTIVITY_CONTRACT["executions"].get(raw, "")
    if not execution and activity_phase(raw):
        execution = "running"
    if not execution:
        execution = "settled" if outcome else "idle" if raw in WORK_RUN_ACTIVITY_CONTRACT["resting"] else "unknown"

    ended = any(str(payload.get(field) or "").strip() for field in ("finishedAt", "endedAt"))
    if ended:
        execution = "settled"
    blocking = not (ended or outcome or raw in WORK_RUN_ACTIVITY_CONTRACT["resting"])
    phase = ""
    if blocking and execution != "unknown":
        phase = next((
            decoded for value in (payload.get("currentPhase"), payload.get("phase"), raw)
            if (decoded := activity_phase(value))
        ), "")
    reason = ""
    if outcome:
        reason = next((
            value for field in ("terminalReason", "runtimeStatus")
            if (value := normalize_activity_value(payload.get(field)))
            and WORK_RUN_ACTIVITY_CONTRACT["outcomes"].get(value) == outcome
        ), raw)
    return {
        "execution": execution, "phase": phase, "outcome": outcome,
        "reason": reason, "rawStatus": raw, "blocksLifecycle": blocking,
    }


def work_run_status_blocks_lifecycle(status: Any) -> bool:
    """Compatibility entry for callers that only have a raw status value."""
    return resolve_work_run_activity({"status": status})["blocksLifecycle"]


def work_run_has_execution(payload: Mapping[str, Any]) -> bool:
    """An identified live owner is stricter evidence than a safety blocker."""
    return resolve_work_run_activity(payload)["execution"] in WORK_RUN_ACTIVITY_CONTRACT["policy"]["ownedExecutions"]
