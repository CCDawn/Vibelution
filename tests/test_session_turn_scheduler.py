import threading

from core.web.services.session_turn_scheduler import SessionTurnScheduler
from tests.helpers.chat_turn_harness import FakeTurnRunner, wait_for_condition


def _agent_key(context):
    agent_id = str(context.get("agent_id") or "").strip()
    return f"agent:{agent_id or 'missing'}"


def _session_key(context):
    session_id = str(context.get("session_id") or "").strip()
    return f"session:{session_id or 'missing'}"


def _scheduler(
    *,
    running=None,
    current=None,
    events=None,
    queued=None,
    dequeued=None,
    event_hook=None,
    max_active_per_agent=4,
):
    event_log = events if events is not None else []
    queued_log = queued if queued is not None else []
    dequeued_log = dequeued if dequeued is not None else []
    tick = {"value": 0.0}

    def now():
        tick["value"] += 1.0
        return tick["value"]

    def record_event(context, phase, outcome, fields):
        event = {
            "turn_id": context.get("turn_id"),
            "phase": phase,
            "outcome": outcome,
            "fields": fields or {},
        }
        event_log.append(event)
        if event_hook:
            event_hook(event)

    return SessionTurnScheduler(
        agent_key_for_context=_agent_key,
        session_key_for_context=_session_key,
        max_active_per_agent=max_active_per_agent,
        now=now,
        record_event=record_event,
        mark_queued=lambda context, position: queued_log.append((context.get("turn_id"), position)),
        mark_dequeued=lambda context: dequeued_log.append(context.get("turn_id")),
        is_session_running=lambda session_id: (running or {}).get(session_id, True),
        is_session_turn_current=lambda session_id, turn_id: (current or {}).get((session_id, turn_id), True),
    )


def test_session_turn_scheduler_serializes_turns_per_session():
    queued = []
    dequeued = []
    submitted = []
    scheduler = _scheduler(queued=queued, dequeued=dequeued)
    active = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}
    waiting = {"session_id": "session-a", "turn_id": "turn-2", "agent_id": "agent-a"}

    scheduler.schedule(active, submit=submitted.append, release=lambda context: None)
    scheduler.schedule(waiting, submit=submitted.append, release=lambda context: None)
    released = scheduler.release(active)

    assert [item["turn_id"] for item in submitted] == ["turn-1"]
    assert queued == [("turn-2", 1)]
    assert released is not None
    assert released.context["turn_id"] == "turn-2"
    assert released.external is False
    assert dequeued == ["turn-2"]


def test_session_turn_scheduler_runs_same_agent_different_sessions_concurrently():
    submitted = []
    scheduler = _scheduler()
    first = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}
    second = {"session_id": "session-b", "turn_id": "turn-2", "agent_id": "agent-a"}

    scheduler.schedule(first, submit=submitted.append, release=lambda context: None)
    scheduler.schedule(second, submit=submitted.append, release=lambda context: None)

    assert [item["turn_id"] for item in submitted] == ["turn-1", "turn-2"]


def test_session_turn_scheduler_queues_same_agent_when_agent_limit_is_reached():
    queued = []
    dequeued = []
    submitted = []
    scheduler = _scheduler(queued=queued, dequeued=dequeued, max_active_per_agent=1)
    active = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}
    waiting = {"session_id": "session-b", "turn_id": "turn-2", "agent_id": "agent-a"}

    scheduler.schedule(active, submit=submitted.append, release=lambda context: None)
    scheduler.schedule(waiting, submit=submitted.append, release=lambda context: None)
    released = scheduler.release(active)

    assert [item["turn_id"] for item in submitted] == ["turn-1"]
    assert queued == [("turn-2", 1)]
    assert released is not None
    assert released.context["turn_id"] == "turn-2"
    assert released.context["_scheduler_queue_reason"] == ""
    assert released.external is False
    assert dequeued == ["turn-2"]


def test_session_turn_scheduler_dequeues_multiple_chat_turns_after_external_finishes():
    queued = []
    dequeued = []
    external_contexts = []
    scheduler = _scheduler(queued=queued, dequeued=dequeued, max_active_per_agent=2)
    waiting_chat = {"session_id": "session-b", "turn_id": "turn-2", "agent_id": "agent-a"}
    later_chat = {"session_id": "session-c", "turn_id": "turn-3", "agent_id": "agent-a"}

    with scheduler.reserve_external(
        agent_id="agent-a",
        run_id="round-1",
        session_id="session-room",
        owner="chat_room_round",
        wait_timeout_seconds=0.1,
        release=external_contexts.append,
    ):
        scheduler.schedule(waiting_chat, submit=lambda context: None, release=lambda context: None)
        scheduler.schedule(later_chat, submit=lambda context: None, release=lambda context: None)

    assert queued == [("turn-2", 1), ("turn-3", 2)]
    assert len(external_contexts) == 1
    released = scheduler.release(external_contexts[0])

    assert released is not None
    assert released.external is False
    assert released.context["turn_id"] == "turn-2"
    assert [item["turn_id"] for item in released.additional_contexts] == ["turn-3"]
    assert dequeued == ["turn-2", "turn-3"]


def test_session_turn_scheduler_reports_dropped_stale_turns_even_without_next_turn():
    queued = []
    scheduler = _scheduler(
        running={"session-a": True},
        current={("session-a", "turn-2"): False},
        queued=queued,
    )
    active = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}
    stale = {"session_id": "session-a", "turn_id": "turn-2", "agent_id": "agent-a"}

    scheduler.schedule(active, submit=lambda context: None, release=lambda context: None)
    scheduler.schedule(stale, submit=lambda context: None, release=lambda context: None)
    released = scheduler.release(active)

    assert queued == [("turn-2", 1)]
    assert released is not None
    assert released.context is None
    assert [item["turn_id"] for item in released.dropped_contexts] == ["turn-2"]


def test_session_turn_scheduler_releases_external_reservation_after_active_turn():
    runner = FakeTurnRunner()
    external_queued = threading.Event()
    scheduler = _scheduler(
        events=runner.events,
        event_hook=lambda event: external_queued.set() if event["phase"] == "external_queued" else None,
    )
    active = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}
    scheduler.schedule(active, submit=runner.submit, release=runner.release)
    entered = threading.Event()

    def wait_for_slot():
        with scheduler.reserve_external(
            agent_id="agent-a",
            run_id="round-1",
            session_id="session-room",
            owner="chat_room_round",
            wait_timeout_seconds=2.0,
            release=lambda context: None,
        ):
            entered.set()

    worker = threading.Thread(target=wait_for_slot)
    worker.start()
    wait_for_condition("external reservation queued", timeout_s=2.0, predicate=external_queued.is_set)
    assert not entered.is_set()

    released = scheduler.release(active)
    assert released is not None
    assert released.external is True
    wait_for_condition("external reservation entered", timeout_s=2.0, predicate=entered.is_set)
    worker.join(timeout=2.0)

    phases = [item["phase"] for item in runner.events]
    assert "external_queued" in phases
    assert "external_dequeued" not in phases
