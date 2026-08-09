"""Crash-safe replay decisions for source-stage Agent session tasks."""

from __future__ import annotations

from typing import Any

MISSING_CANONICAL_SESSION_FAILURE = "project_agent_session_missing"


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _has_accepted_turn(task: dict[str, Any]) -> bool:
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    return bool(turn.get("accepted")) or bool(
        str(turn.get("turnId") or turn.get("startedTurnId") or "").strip()
    )


def _missing_session_task(
    task: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    return {
        **task,
        "status": "failed",
        "failureCode": MISSING_CANONICAL_SESSION_FAILURE,
        "failureMessage": reason,
        "failedAt": now,
        "updatedAt": now,
    }


def prepare_source_collection_stage_task_replay(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Classify an exact replay without duplicating a task or reviving stale state."""
    s = _service()
    current = dict(task)
    task_id = s._trim_text(current.get("taskId"), max_length=160)
    session_id = s._trim_text(current.get("sessionId"), max_length=160)
    status = s._trim_text(current.get("status"), max_length=80).lower()
    failure_code = s._trim_text(current.get("failureCode"), max_length=120)
    has_accepted_turn = _has_accepted_turn(current)
    session_detail = (
        s.session_service.get_session_detail(session_id) if session_id else None
    )

    if not isinstance(session_detail, dict):
        recoverable_pre_submit = not has_accepted_turn and (
            status == "queued"
            or (
                status == "failed"
                and failure_code == MISSING_CANONICAL_SESSION_FAILURE
            )
        )
        if not recoverable_pre_submit:
            raise s.TeamWorkflowOrchestrationError(
                "Stage task references a missing canonical Agent session after submission; "
                f"taskId={task_id}, sessionId={session_id}. Use an explicit new NodeRun attempt."
            )
        reason = (
            "The project Agent session referenced by this pre-submit task no longer exists "
            f"in canonical chat state: {session_id}."
        )
        failed = _missing_session_task(current, reason=reason)
        s._upsert_source_collection_stage_session_task(team_id, run_id, failed)
        s._record_workflow_event(
            "source_collection.stage_session_task_canonical_session_missing",
            team_id,
            fields={
                "runId": run_id,
                "taskId": task_id,
                "sessionId": session_id,
                "failureCode": MISSING_CANONICAL_SESSION_FAILURE,
                "recovery": "formal_retry_same_task",
            },
        )
        return {"action": "formal_retry_same_task", "task": failed}

    if status == "queued" and not has_accepted_turn:
        s._record_workflow_event(
            "source_collection.stage_session_task_pre_submit_replayed",
            team_id,
            fields={
                "runId": run_id,
                "taskId": task_id,
                "sessionId": session_id,
            },
        )
        return {"action": "resume_same_task", "task": current}

    return {"action": "reuse", "task": current}


def mark_source_collection_stage_task_session_missing(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Persist a visible terminal state when the session disappears before submit."""
    s = _service()
    session_id = s._trim_text(task.get("sessionId"), max_length=160)
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    failed = _missing_session_task(
        task,
        reason=(
            "The canonical Agent session disappeared before the task message was accepted: "
            f"{session_id}."
        ),
    )
    s._upsert_source_collection_stage_session_task(team_id, run_id, failed)
    s._record_workflow_event(
        "source_collection.stage_session_task_submit_session_missing",
        team_id,
        fields={
            "runId": run_id,
            "taskId": task_id,
            "sessionId": session_id,
            "failureCode": MISSING_CANONICAL_SESSION_FAILURE,
        },
    )
    return failed
