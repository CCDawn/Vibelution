"""Focused tests for session schedule slice."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

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


def _capture_scene_events(monkeypatch):
    events: list[dict] = []

    def capture(component, phase, event_code, **kwargs):
        events.append({"phase": phase, "eventCode": event_code, **kwargs})
        return {}

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture)
    return events


def test_executor_watchdog_logs_pending_start_and_in_flight_turns(monkeypatch) -> None:
    """Defect-① observability: a submission waiting on the shared executor must
    produce a structured watchdog event that names the turns occupying the pool."""
    events = _capture_scene_events(monkeypatch)
    schedule._reset_executor_watchdog_for_tests()
    monkeypatch.setattr(schedule, "_EXECUTOR_WORKER_START_WARN_SECONDS", 0.0)
    monkeypatch.setattr(schedule, "_EXECUTOR_WORKER_START_REPEAT_SECONDS", 0.0)

    hung_context = {
        "session_id": "session-hung",
        "turn_id": "turn-hung",
        "agent_id": "agent-hung",
    }
    pending_context = {
        "session_id": "session-pending",
        "turn_id": "turn-pending",
        "agent_id": "agent-pending",
        "_scheduler_session_key": "session:session-pending",
        "_scheduler_queue_reason": "agent_busy",
    }
    try:
        # Simulate one turn already occupying an executor thread.
        schedule._executor_watchdog_register(hung_context)
        schedule._executor_watchdog_mark_started(hung_context)
        # A second submission is registered but never starts.
        schedule._executor_watchdog_register(pending_context)
        schedule._executor_watchdog_sweep()

        watchdog_events = [event for event in events if event["phase"] == "worker_start_watchdog"]
        assert watchdog_events, "expected a worker-start watchdog event"
        fields = watchdog_events[0]["fields"]
        assert fields["sessionId"] == "session-pending"
        assert fields["turnId"] == "turn-pending"
        assert fields["activeTurnId"] == "turn-pending"
        assert fields["workerStartWaitMs"] >= 0
        assert fields["executorMaxWorkers"] >= -1
        assert fields["executorQueuedDepth"] >= -1
        assert fields["executorInFlightCount"] == 1
        assert fields["executorInFlightTurns"][0]["turnId"] == "turn-hung"
        assert fields["executorInFlightTurns"][0]["sessionId"] == "session-hung"
        assert fields["queueReason"] == "agent_busy"

        # Starting the pending turn clears it and logs a late start (threshold 0).
        events.clear()
        schedule._executor_watchdog_mark_started(pending_context)
        late_events = [event for event in events if event["phase"] == "worker_started_late"]
        assert late_events, "expected a late-start event once the worker begins"
        assert late_events[0]["fields"]["turnId"] == "turn-pending"
        assert late_events[0]["fields"]["workerStartWaitMs"] >= 0

        schedule._executor_watchdog_mark_finished(pending_context)
        schedule._executor_watchdog_mark_finished(hung_context)
        snapshot = schedule._executor_in_flight_snapshot_fields()
        assert snapshot["executorInFlightCount"] == 0
        assert snapshot["executorInFlightTurns"] == []
    finally:
        schedule._reset_executor_watchdog_for_tests()


def test_executor_saturation_event_fires_at_capacity(monkeypatch) -> None:
    events = _capture_scene_events(monkeypatch)

    class SaturatedFakeQueue:
        def qsize(self) -> int:
            return 8

    class SaturatedFakeExecutor:
        _max_workers = 8
        _work_queue = SaturatedFakeQueue()

    class IdleFakeQueue:
        def qsize(self) -> int:
            return 0

    class IdleFakeExecutor:
        _max_workers = 8
        _work_queue = IdleFakeQueue()

    context = {"session_id": "session-sat", "turn_id": "turn-sat", "agent_id": "agent-sat"}

    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SaturatedFakeExecutor())
    schedule._record_executor_saturation_if_saturated(context)
    saturated = [event for event in events if event["phase"] == "executor_saturated"]
    assert saturated, "expected an executor saturation event at capacity"
    assert saturated[0]["eventCode"] == "conversation.scheduler.executor_saturated"
    assert saturated[0]["fields"]["executorQueuedDepth"] == 8
    assert saturated[0]["fields"]["executorMaxWorkers"] == 8
    assert saturated[0]["fields"]["turnId"] == "turn-sat"

    events.clear()
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", IdleFakeExecutor())
    schedule._record_executor_saturation_if_saturated(context)
    assert [event for event in events if event["phase"] == "executor_saturated"] == []


def test_scheduler_log_fields_carry_executor_saturation(monkeypatch) -> None:
    class FakeQueue:
        def qsize(self) -> int:
            return 3

    class FakeExecutor:
        _max_workers = 8
        _work_queue = FakeQueue()

    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", FakeExecutor())
    fields = schedule._scheduler_log_fields({"_scheduler_queue_reason": "agent_busy"})
    assert fields["executorQueuedDepth"] == 3
    assert fields["executorMaxWorkers"] == 8


def test_submit_scheduled_turn_registers_pending_worker_start(monkeypatch) -> None:
    """Registering the pending start must not depend on the executor running it."""
    events = _capture_scene_events(monkeypatch)
    schedule._reset_executor_watchdog_for_tests()
    submitted: list[tuple] = []

    class RecordingFakeExecutor:
        _max_workers = 8
        _work_queue = type("_Q", (), {"qsize": staticmethod(lambda: 0)})()

        def submit(self, fn, context):
            submitted.append((fn, context))

    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", RecordingFakeExecutor())
    context = {"session_id": "session-reg", "turn_id": "turn-reg", "agent_id": "agent-reg"}
    try:
        schedule._submit_scheduled_session_turn(context)
        assert len(submitted) == 1
        with schedule._EXECUTOR_WATCHDOG_LOCK:
            assert "turn-reg" in schedule._EXECUTOR_PENDING_WORKER_STARTS
        assert [event for event in events if event["phase"] == "executor_saturated"] == []

        # The worker-side hook consumes the pending entry even when it starts late.
        schedule._executor_watchdog_mark_started(context)
        with schedule._EXECUTOR_WATCHDOG_LOCK:
            assert "turn-reg" not in schedule._EXECUTOR_PENDING_WORKER_STARTS
            assert "turn-reg" in schedule._EXECUTOR_IN_FLIGHT_TURNS

        # A failed executor submission must not leak a pending registration
        # (the watchdog would otherwise warn about a turn that never existed).
        class ExplodingExecutor(RecordingFakeExecutor):
            def submit(self, fn, context):
                raise RuntimeError("executor down")

        monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", ExplodingExecutor())
        with pytest.raises(RuntimeError, match="executor down"):
            schedule._submit_scheduled_session_turn({"session_id": "s", "turn_id": "turn-down"})
        with schedule._EXECUTOR_WATCHDOG_LOCK:
            assert "turn-down" not in schedule._EXECUTOR_PENDING_WORKER_STARTS
    finally:
        schedule._reset_executor_watchdog_for_tests()
