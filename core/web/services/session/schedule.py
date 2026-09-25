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

import threading
import time
from contextlib import contextmanager
from typing import Any


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _session_scheduler_agent_key(context: dict[str, Any]) -> str:
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    if agent_id:
        return f"agent:{agent_id}"
    session_id = str(context.get("session_id") or "").strip()
    return f"session:{session_id or 'unknown'}"

def _session_scheduler_session_key(context: dict[str, Any]) -> str:
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
    """Reserve the whole Agent for work without an independent Session identity."""

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


@contextmanager
def reserve_session_execution_slot(
    *,
    agent_id: str,
    run_id: str,
    session_id: str,
    owner: str = "external",
    wait_timeout_seconds: float | None = None,
):
    """Reserve one Session for work executed outside the normal turn worker."""

    s = _service()
    with s._SESSION_TURN_SCHEDULER.reserve_session(
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
        submit=s._submit_scheduled_session_turn,
        release=s._release_scheduled_session_turn,
    )

def _submit_scheduled_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    if bool(context.get("_scheduler_deferred_session_admission")):
        from .proactive import (
            admit_session_proactive_turn,
            cancel_proactive_turn_context,
        )

        try:
            admission = admit_session_proactive_turn(context)
        except Exception:
            cancel_proactive_turn_context(context, reason="admission_failed")
            raise
        if admission == "defer":
            # A user turn won the admission race.  Relinquish the provisional
            # scheduler slot, start the user-owned queued context, then append
            # this low-priority proactive turn behind it.
            _release_scheduled_session_turn(context)
            s._schedule_session_turn(context)
            return
        if admission != "admitted":
            _release_scheduled_session_turn(context)
            return
    context["_executor_submitted_at_monotonic"] = s._perf_counter()
    # Register BEFORE handing the context to the executor: an idle worker can
    # pick the item up immediately, and mark_started must always find the
    # pending entry or the watchdog would leak a false-positive registration.
    _executor_watchdog_register(context)
    try:
        s._SESSION_EXECUTOR.submit(_execute_scheduled_session_turn, context)
    except Exception:
        _executor_watchdog_unregister(context)
        if bool(context.get("_scheduler_deferred_session_admission")):
            cancel_proactive_turn_context(context, reason="executor_submit_failed")
        raise
    # Defect-① observability: running is already flagged while this context
    # waits for an executor thread; a saturated pool means it may never start.
    _record_executor_saturation_if_saturated(context)

def _execute_scheduled_session_turn(context: dict[str, Any]) -> None:
    s = _service()
    executor_started_at = s._perf_counter()
    context["_executor_started_at_monotonic"] = executor_started_at
    _executor_watchdog_mark_started(context)
    try:
        s._run_session_turn(context)
    except Exception as exc:
        session_id = str(context.get("session_id") or "").strip()
        turn_id = str(context.get("turn_id") or "").strip()
        try:
            s._record_session_turn_lifecycle_event(
                session_id,
                "worker_unhandled_exception",
                turn_id=turn_id,
                level="error",
                outcome="failed",
                fields={
                    "exceptionType": type(exc).__name__,
                    "errorPreview": s.trim_lines(str(exc), max_lines=2),
                    "agentId": str(context.get("agent_id") or "").strip(),
                    **_scheduler_log_fields(context),
                },
            )
            s._persist_session_turn_failure(session_id, context, exc)
        finally:
            s._set_session_running(session_id, False, turn_id=turn_id)
            s._clear_session_turn_control(session_id, turn_id=turn_id)
            s._publish_session_detail_snapshot(session_id)
    finally:
        _executor_watchdog_mark_finished(context)
        s._release_scheduled_session_turn(context)

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
        s._submit_scheduled_session_turn(next_context)
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
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is not None and s._is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "queued"
            conversation["updated_at"] = now
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
    from . import directory_bridge

    directory_bridge.touch_directory_session_safe(session_id, status="queued", wait=False)
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
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is not None and s._is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "running"
            conversation["updated_at"] = now
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
    from . import directory_bridge

    directory_bridge.touch_directory_session_safe(session_id, status="running", wait=False)
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

# ---------------------------------------------------------------------------
# Worker-start watchdog (defect-① observability).
#
# ``submit_session_message`` flags the session running *before* the turn
# context is handed to the shared thread pool (``_SESSION_EXECUTOR``). When
# every executor thread is occupied by a hung turn, the submitted worker never
# starts, nobody clears running, and the session looks silently dead. The
# watchdog adds diagnostics only: each executor submission is registered, a
# background sweep logs a structured event while a submission waits to start,
# and the in-flight table names the turns currently occupying the pool. It
# never settles turns and never changes ``reconcile_stale_chat_turn_work_runs``
# thresholds or semantics.
# ---------------------------------------------------------------------------

_EXECUTOR_WATCHDOG_LOCK = threading.Lock()
_EXECUTOR_PENDING_WORKER_STARTS: dict[str, dict[str, Any]] = {}
_EXECUTOR_IN_FLIGHT_TURNS: dict[str, dict[str, Any]] = {}
_EXECUTOR_WATCHDOG_THREAD: threading.Thread | None = None
_EXECUTOR_WATCHDOG_TICK_SECONDS = 2.0
_EXECUTOR_WORKER_START_WARN_SECONDS = 10.0
_EXECUTOR_WORKER_START_REPEAT_SECONDS = 30.0
_EXECUTOR_IN_FLIGHT_SNAPSHOT_LIMIT = 8


def _executor_watchdog_turn_key(context: dict[str, Any]) -> str:
    turn_id = str(context.get("turn_id") or context.get("turnId") or "").strip()
    if turn_id:
        return turn_id
    session_id = str(context.get("session_id") or context.get("sessionId") or "").strip()
    return f"session:{session_id or 'unknown'}"


def _executor_saturation_fields() -> dict[str, Any]:
    """Queue depth / worker capacity of the shared chat-turn executor."""

    s = _service()
    fields: dict[str, Any] = {"executorQueuedDepth": -1, "executorMaxWorkers": -1}
    try:
        fields["executorQueuedDepth"] = int(s._SESSION_EXECUTOR._work_queue.qsize())
    except Exception:
        # Diagnostics must never break scheduling; the fake executors used in
        # tests and exotic executor swaps may lack the private queue.
        pass
    try:
        fields["executorMaxWorkers"] = int(s._SESSION_EXECUTOR._max_workers)
    except Exception:
        pass
    return fields


def _executor_in_flight_snapshot_fields() -> dict[str, Any]:
    """Name the turns currently occupying executor threads (oldest first)."""

    s = _service()
    now = s._perf_counter()
    with _EXECUTOR_WATCHDOG_LOCK:
        in_flight_count = len(_EXECUTOR_IN_FLIGHT_TURNS)
        ordered = sorted(
            _EXECUTOR_IN_FLIGHT_TURNS.values(),
            key=lambda entry: float(entry.get("startedAtMonotonic") or 0.0),
        )
        snapshot = [
            {
                "turnId": str(entry.get("turnId") or ""),
                "sessionId": str(entry.get("sessionId") or ""),
                "agentId": str(entry.get("agentId") or ""),
                "runningMs": int(
                    max(0.0, now - float(entry.get("startedAtMonotonic") or now)) * 1000
                ),
            }
            for entry in ordered[:_EXECUTOR_IN_FLIGHT_SNAPSHOT_LIMIT]
        ]
    return {
        "executorInFlightCount": in_flight_count,
        "executorInFlightTurns": snapshot,
    }


def _executor_watchdog_register(context: dict[str, Any]) -> None:
    """Track an executor submission that has not started executing yet."""

    s = _service()
    key = _executor_watchdog_turn_key(context)
    entry = {
        "turnId": key,
        "sessionId": str(context.get("session_id") or context.get("sessionId") or "").strip(),
        "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
        "submittedAtMonotonic": s._perf_counter(),
        "lastWarnedWaitSeconds": 0.0,
        "schedulerFields": _scheduler_log_fields(context),
    }
    with _EXECUTOR_WATCHDOG_LOCK:
        _EXECUTOR_PENDING_WORKER_STARTS[key] = entry
    _ensure_executor_watchdog_thread()


def _executor_watchdog_unregister(context: dict[str, Any]) -> None:
    """Drop a pending registration whose executor submission never landed."""

    key = _executor_watchdog_turn_key(context)
    with _EXECUTOR_WATCHDOG_LOCK:
        _EXECUTOR_PENDING_WORKER_STARTS.pop(key, None)


def _executor_watchdog_mark_started(context: dict[str, Any]) -> None:
    """Move a submission from pending to in-flight; log a late start."""

    s = _service()
    key = _executor_watchdog_turn_key(context)
    started_at = s._perf_counter()
    with _EXECUTOR_WATCHDOG_LOCK:
        entry = _EXECUTOR_PENDING_WORKER_STARTS.pop(key, None)
        _EXECUTOR_IN_FLIGHT_TURNS[key] = {
            "turnId": key,
            "sessionId": str(context.get("session_id") or context.get("sessionId") or "").strip(),
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "startedAtMonotonic": started_at,
        }
    if entry is None:
        return
    waited_seconds = max(0.0, started_at - float(entry.get("submittedAtMonotonic") or started_at))
    if waited_seconds < _EXECUTOR_WORKER_START_WARN_SECONDS:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "worker_started_late",
            "conversation.scheduler.worker_started_late",
            level="warning",
            outcome="running",
            message="Session turn worker started after waiting for a shared executor thread.",
            fields={
                "sessionId": str(entry.get("sessionId") or ""),
                "turnId": key,
                "workerStartWaitMs": int(waited_seconds * 1000),
                **_executor_saturation_fields(),
            },
        )
    except Exception:
        pass


def _executor_watchdog_mark_finished(context: dict[str, Any]) -> None:
    key = _executor_watchdog_turn_key(context)
    with _EXECUTOR_WATCHDOG_LOCK:
        _EXECUTOR_IN_FLIGHT_TURNS.pop(key, None)


def _executor_watchdog_sweep() -> None:
    """Log structured diagnostics for submissions still waiting to start."""

    s = _service()
    now = s._perf_counter()
    due: list[tuple[str, dict[str, Any], float]] = []
    with _EXECUTOR_WATCHDOG_LOCK:
        for key, entry in _EXECUTOR_PENDING_WORKER_STARTS.items():
            waited = max(0.0, now - float(entry.get("submittedAtMonotonic") or now))
            last_warned = float(entry.get("lastWarnedWaitSeconds") or 0.0)
            if (
                waited >= _EXECUTOR_WORKER_START_WARN_SECONDS
                and waited - last_warned >= _EXECUTOR_WORKER_START_REPEAT_SECONDS
            ):
                entry["lastWarnedWaitSeconds"] = waited
                due.append((key, dict(entry), waited))
    for key, entry, waited in due:
        try:
            s.record_runtime_scene_event(
                "conversation",
                "worker_start_watchdog",
                "conversation.scheduler.worker_start_watchdog",
                level="warning",
                outcome="pending",
                message=(
                    "Session turn is flagged running but its worker has not started on the shared "
                    "executor; every thread may be occupied by stuck turns (ghost-running candidate)."
                ),
                fields={
                    "sessionId": str(entry.get("sessionId") or ""),
                    "turnId": key,
                    "activeTurnId": key,
                    "workerStartWaitMs": int(waited * 1000),
                    **_executor_saturation_fields(),
                    **_executor_in_flight_snapshot_fields(),
                    **(entry.get("schedulerFields") if isinstance(entry.get("schedulerFields"), dict) else {}),
                },
            )
        except Exception:
            pass


def _executor_watchdog_loop() -> None:
    while True:
        time.sleep(_EXECUTOR_WATCHDOG_TICK_SECONDS)
        try:
            _executor_watchdog_sweep()
        except Exception:
            continue


def _ensure_executor_watchdog_thread() -> None:
    global _EXECUTOR_WATCHDOG_THREAD
    with _EXECUTOR_WATCHDOG_LOCK:
        if _EXECUTOR_WATCHDOG_THREAD is not None and _EXECUTOR_WATCHDOG_THREAD.is_alive():
            return
        thread = threading.Thread(
            target=_executor_watchdog_loop,
            name="web-chat-turn-start-watchdog",
            daemon=True,
        )
        _EXECUTOR_WATCHDOG_THREAD = thread
    thread.start()


def _reset_executor_watchdog_for_tests() -> None:
    """Clear watchdog registries (test isolation; the daemon sweep is no-op)."""

    with _EXECUTOR_WATCHDOG_LOCK:
        _EXECUTOR_PENDING_WORKER_STARTS.clear()
        _EXECUTOR_IN_FLIGHT_TURNS.clear()


def _record_executor_saturation_if_saturated(context: dict[str, Any]) -> None:
    """Warn once per submission when the executor queue depth reaches capacity."""

    fields = _executor_saturation_fields()
    depth = int(fields.get("executorQueuedDepth") or -1)
    workers = int(fields.get("executorMaxWorkers") or -1)
    if workers <= 0 or depth < workers:
        return
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "executor_saturated",
            "conversation.scheduler.executor_saturated",
            level="warning",
            outcome="queued",
            message=(
                "The shared chat-turn executor has at least as many queued items as workers; "
                "new turns wait for a free thread."
            ),
            fields={
                "sessionId": str(context.get("session_id") or context.get("sessionId") or "").strip(),
                "turnId": str(context.get("turn_id") or context.get("turnId") or "").strip(),
                **fields,
                **_executor_in_flight_snapshot_fields(),
            },
        )
    except Exception:
        pass


def _scheduler_log_fields(context: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "schedulerSessionKey": str(context.get("_scheduler_session_key") or _session_scheduler_session_key(context)).strip(),
        "queueReason": str(context.get("_scheduler_queue_reason") or "").strip(),
        "agentActiveCount": s._coerce_nonnegative_int(context.get("_scheduler_agent_active_count")),
        "agentMaxActive": s._coerce_nonnegative_int(
            context.get("_scheduler_agent_max_active") or s._SESSION_AGENT_MAX_ACTIVE_TURNS
        ),
        **_executor_saturation_fields(),
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
