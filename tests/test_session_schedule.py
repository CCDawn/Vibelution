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
