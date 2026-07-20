"""Session turn schedule adapters (queue / executor handoff).

Claim scope: schedule, queue, release, external slot reservation, and
queued/dequeued UI/work-run side effects. Do not put submit validation or
the full ``_run_session_turn`` worker loop here.

Bodies late-bind ``session_service`` so:
- ``_SESSION_EXECUTOR`` / ``_SESSION_TURN_SCHEDULER`` monkeypatches on the
  facade remain effective (resolved at call time)
- worker/live-output/persist helpers stay on the facade until later slices
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _session_scheduler_agent_key(context: dict[str, Any]) -> str:
    s = _service()
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    if agent_id:
        return f"agent:{agent_id}"
    session_id = str(context.get("session_id") or "").strip()
    return f"session:{session_id or 'unknown'}"

def _session_scheduler_session_key(context: dict[str, Any]) -> str:
    s = _service()
    session_id = str(context.get("session_id") or context.get("sessionId") or "").strip()
    if session_id:
        return f"session:{session_id}"
    turn_id = str(context.get("turn_id") or context.get("turnId") or "").strip()
    return f"turn:{turn_id or 'unknown'}"

def _record_scheduler_event_adapter(
    context: dict[str, Any],
    phase: str,
    outcome: str,
    fields: dict[str, Any] | None,
) -> None:
    s = _service()
    _record_session_scheduler_event(context, phase, outcome=outcome, fields=fields)

@contextmanager
def reserve_agent_execution_slot(
    *,
    agent_id: str,
    run_id: str,
    session_id: str = "",
    owner: str = "external",
    wait_timeout_seconds: float | None = None,
):
    """Reserve the per-agent execution slot for non-session work such as group chat speakers."""

    s = _service()
    with s._SESSION_TURN_SCHEDULER.reserve_external(
        agent_id=agent_id,
        run_id=run_id,
        session_id=session_id,
        owner=owner,
        wait_timeout_seconds=wait_timeout_seconds,
        release=_release_scheduled_session_turn,
    ):
        yield

def _scheduler_context_is_external(context: dict[str, Any]) -> bool:
    s = _service()
    return s._SESSION_TURN_SCHEDULER.is_external(context)

def _cancel_queued_scheduler_context(agent_key: str, turn_id: str) -> bool:
    s = _service()
    return s._SESSION_TURN_SCHEDULER.cancel_queued_context(agent_key, turn_id)

def cancel_agent_execution_reservation(run_id: str) -> bool:
    """Cancel queued external work that is waiting for an agent execution slot."""

    s = _service()
    return s._SESSION_TURN_SCHEDULER.cancel_external_reservation(run_id)

def _schedule_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    s._SESSION_TURN_SCHEDULER.schedule(
        context,
        submit=_submit_scheduled_session_turn,
        release=_release_scheduled_session_turn,
    )

def _submit_scheduled_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    context["_executor_submitted_at_monotonic"] = s._perf_counter()
    s._SESSION_EXECUTOR.submit(_execute_scheduled_session_turn, context)

def _execute_scheduled_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    executor_started_at = s._perf_counter()
    context["_executor_started_at_monotonic"] = executor_started_at
    try:
        s._run_session_turn(context)
    finally:
        _release_scheduled_session_turn(context)

def _release_scheduled_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    try:
        released = s._SESSION_TURN_SCHEDULER.release(context)
        if released is None:
            return

        for dropped in released.dropped_contexts:
            _record_session_scheduler_event(dropped, "dropped_stale", outcome="skipped")

        next_context = released.context
        if next_context is None:
            return
        if released.external:
            _record_session_scheduler_event(next_context, "external_dequeued", outcome="running")
            return

        contexts_to_submit = [next_context, *list(released.additional_contexts or [])]
        for runnable_context in contexts_to_submit:
            _submit_released_session_turn(runnable_context)
    finally:
        _drain_wakeable_agent_inbox_after_session_release(context)

def _drain_wakeable_agent_inbox_after_session_release(context: dict[str, Any]) -> None:
    s = _service()
    session_id = str(context.get("session_id") or context.get("sessionId") or "").strip()
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    if not session_id or not agent_id or s._is_session_running(session_id):
        return

    with s._AGENT_INBOX_WAKE_STATE_LOCK:
        if session_id in s._AGENT_INBOX_IDLE_DRAINING_SESSION_IDS:
            return
        s._AGENT_INBOX_IDLE_DRAINING_SESSION_IDS.add(session_id)

    try:
        agent = s.get_agent(agent_id, include_archived=False)
        if not agent or str(agent.get("directSessionId") or "").strip() != session_id:
            return
        while not s._is_session_running(session_id):
            message = s.next_wakeable_agent_inbox_message_for_agent(agent_id)
            if not message:
                return
            delivery = s.wake_agent_for_inbox_message(message)
            s._record_agent_inbox_idle_drain_event(message, delivery)
            if str(delivery.get("wakeStatus") or "").strip() != "started":
                return
    finally:
        with s._AGENT_INBOX_WAKE_STATE_LOCK:
            s._AGENT_INBOX_IDLE_DRAINING_SESSION_IDS.discard(session_id)

def _submit_released_session_turn(next_context: dict[str, Any]) -> None:
    s = _service()
    try:
        _submit_scheduled_session_turn(next_context)
    except Exception as exc:
        s._record_session_turn_lifecycle_event(
            str(next_context.get("session_id") or "").strip(),
            "scheduler_submit_failed",
            turn_id=str(next_context.get("turn_id") or "").strip(),
            level="error",
            outcome="failed",
            fields={
                "exceptionType": type(exc).__name__,
                "errorPreview": s.trim_lines(str(exc), max_lines=2),
                "agentId": str(next_context.get("agent_id") or "").strip(),
                **_scheduler_log_fields(next_context),
            },
        )
        s._persist_session_turn_failure(str(next_context.get("session_id") or "").strip(), next_context, exc)
        s._set_session_running(
            str(next_context.get("session_id") or "").strip(),
            False,
            turn_id=str(next_context.get("turn_id") or "").strip(),
        )
        s._clear_session_turn_control(
            str(next_context.get("session_id") or "").strip(),
            turn_id=str(next_context.get("turn_id") or "").strip(),
        )
        s._publish_session_detail_snapshot(str(next_context.get("session_id") or "").strip())
        _release_scheduled_session_turn(next_context)

def _cancel_queued_session_turn(session_id: str, turn_id: str) -> bool:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    removed = s._SESSION_TURN_SCHEDULER.cancel_session_turn(normalized_session_id, normalized_turn_id)
    if removed:
        s._record_session_turn_lifecycle_event(
            normalized_session_id,
            "scheduler_cancelled_queued",
            turn_id=normalized_turn_id,
            outcome="cancelled",
            fields={"reason": "stop_requested_before_worker_start"},
        )
    return removed

def _mark_session_turn_queued(context: dict[str, Any], *, queue_position: int) -> None:
    s = _service()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if not session_id or not s._is_session_turn_current(session_id, turn_id):
        return
    context["_scheduler_queued_at_monotonic"] = s._perf_counter()
    now = s._now_timestamp()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is not None and s._is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "queued"
            conversation["updated_at"] = now
            payload["updated_at"] = now
            s.save_chat_state(s.PROJECT_ROOT, payload)
    s._set_session_turn_progress_live_output(session_id, "queued", turn_id=turn_id)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="queued",
        agent_id=str(context.get("agent_id") or "").strip(),
        user_message=str(context.get("raw_user_message") or context.get("user_message") or "").strip(),
        updated_at=now,
    )
    _record_session_scheduler_event(
        context,
        "queued",
        outcome="queued",
        fields={
            "queuePosition": max(1, int(queue_position or 1)),
            **_scheduler_log_fields(context),
        },
    )
    s._publish_session_detail_snapshot(session_id)

def _mark_session_turn_dequeued(context: dict[str, Any]) -> None:
    s = _service()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if not session_id or not s._is_session_turn_current(session_id, turn_id):
        return
    dequeued_at = s._perf_counter()
    context["_scheduler_started_at_monotonic"] = dequeued_at
    now = s._now_timestamp()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is not None and s._is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "running"
            conversation["updated_at"] = now
            payload["updated_at"] = now
            s.save_chat_state(s.PROJECT_ROOT, payload)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="running",
        agent_id=str(context.get("agent_id") or "").strip(),
        user_message=str(context.get("raw_user_message") or context.get("user_message") or "").strip(),
        updated_at=now,
    )
    _record_session_scheduler_event(
        context,
        "dequeued",
        outcome="running",
        fields={
            "queueWaitMs": s._elapsed_ms_between(context.get("_scheduler_queued_at_monotonic"), dequeued_at),
            "scheduledToDequeueMs": s._elapsed_ms_between(context.get("_scheduler_scheduled_at_monotonic"), dequeued_at),
            **_scheduler_log_fields(context),
        },
    )
    s._publish_session_detail_snapshot(session_id)

def _scheduler_log_fields(context: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "schedulerSessionKey": str(context.get("_scheduler_session_key") or _session_scheduler_session_key(context)).strip(),
        "queueReason": str(context.get("_scheduler_queue_reason") or "").strip(),
        "agentActiveCount": s._coerce_nonnegative_int(context.get("_scheduler_agent_active_count")),
        "agentMaxActive": s._coerce_nonnegative_int(
            context.get("_scheduler_agent_max_active") or s._SESSION_AGENT_MAX_ACTIVE_TURNS
        ),
    }

def _record_session_scheduler_event(
    context: dict[str, Any],
    phase: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    agent_key = str(context.get("_scheduler_agent_key") or _session_scheduler_agent_key(context)).strip()
    s._record_session_turn_lifecycle_event(
        session_id,
        f"scheduler_{phase}",
        turn_id=turn_id,
        outcome=outcome,
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "schedulerAgentKey": agent_key,
            **_scheduler_log_fields(context),
            **(fields or {}),
        },
    )
