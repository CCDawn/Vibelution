"""Focused tests for session schedule slice."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from core.web.services import session_service
from core.web.services.session import schedule


def test_facade_reexports_schedule_entrypoints() -> None:
    assert session_service._schedule_session_turn is schedule._schedule_session_turn
    assert session_service._submit_scheduled_session_turn is schedule._submit_scheduled_session_turn
    assert session_service.reserve_agent_execution_slot is schedule.reserve_agent_execution_slot
    assert session_service.cancel_agent_execution_reservation is schedule.cancel_agent_execution_reservation


def test_scheduler_keys_are_stable() -> None:
    assert schedule._session_scheduler_agent_key({"agent_id": "ag-1"}) == "agent:ag-1"
    assert schedule._session_scheduler_session_key({"session_id": "s-9"}) == "session:s-9"
    assert schedule._scheduler_log_fields(
        {
            "_scheduler_session_key": "session:s-9",
            "_scheduler_queue_reason": "agent_busy",
            "_scheduler_agent_active_count": 2,
            "_scheduler_agent_max_active": 4,
        }
    )["queueReason"] == "agent_busy"


def test_schedule_uses_facade_executor_monkeypatch(monkeypatch) -> None:
    """Executor must be resolved at call time from the facade for conftest isolation."""

    ran: list[str] = []

    def fake_run(context: dict) -> None:
        ran.append(str(context.get("turn_id") or ""))

    monkeypatch.setattr(session_service, "_run_session_turn", fake_run)
    isolated = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sched-test")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", isolated)

    session_id = "sched-test-session"
    turn_id = "sched-test-turn"
    session_service._set_session_running(session_id, True, turn_id=turn_id)
    try:
        session_service._schedule_session_turn(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "agent_id": "sched-agent",
            }
        )
        # drain isolated executor
        isolated.shutdown(wait=True)
        assert ran == [turn_id]
    finally:
        session_service._set_session_running(session_id, False, turn_id=turn_id)
        if hasattr(session_service, "_SESSION_TURN_SCHEDULER"):
            session_service._SESSION_TURN_SCHEDULER.clear()


def test_execute_scheduled_turn_terminalizes_unhandled_prepare_failure(monkeypatch) -> None:
    context = {
        "session_id": "session-prepare-failure",
        "turn_id": "turn-prepare-failure",
        "agent_id": "agent-prepare-failure",
    }
    lifecycle_events: list[tuple[str, str, dict]] = []
    persisted_failures: list[tuple[str, str, str]] = []
    running_updates: list[tuple[str, bool, str]] = []
    cleared_controls: list[tuple[str, str]] = []
    published_sessions: list[str] = []
    released_turns: list[str] = []

    def fail_during_prepare(_context: dict) -> None:
        raise AttributeError("missing extracted dependency")

    monkeypatch.setattr(session_service, "_run_session_turn", fail_during_prepare)
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append((session_id, phase, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_failure",
        lambda session_id, failure_context, exc: persisted_failures.append(
            (session_id, str(failure_context.get("turn_id") or ""), f"{type(exc).__name__}: {exc}")
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda session_id, running, *, turn_id="": running_updates.append((session_id, running, turn_id)),
    )
    monkeypatch.setattr(
        session_service,
        "_clear_session_turn_control",
        lambda session_id, *, turn_id="": cleared_controls.append((session_id, turn_id)),
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id: published_sessions.append(session_id),
    )
    monkeypatch.setattr(
        session_service,
        "_release_scheduled_session_turn",
        lambda released_context: released_turns.append(str(released_context.get("turn_id") or "")),
    )

    schedule._execute_scheduled_session_turn(context)

    assert lifecycle_events[0][0:2] == ("session-prepare-failure", "worker_unhandled_exception")
    assert lifecycle_events[0][2]["outcome"] == "failed"
    assert lifecycle_events[0][2]["fields"]["exceptionType"] == "AttributeError"
    assert persisted_failures == [
        ("session-prepare-failure", "turn-prepare-failure", "AttributeError: missing extracted dependency")
    ]
    assert running_updates == [("session-prepare-failure", False, "turn-prepare-failure")]
    assert cleared_controls == [("session-prepare-failure", "turn-prepare-failure")]
    assert published_sessions == ["session-prepare-failure"]
    assert released_turns == ["turn-prepare-failure"]
