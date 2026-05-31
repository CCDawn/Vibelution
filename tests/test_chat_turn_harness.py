import pytest

from tests.helpers.chat_turn_harness import FakeTurnRunner, wait_for_condition


def test_wait_for_condition_returns_when_predicate_becomes_true():
    state = {"ready": True}

    wait_for_condition("ready state", timeout_s=0.1, predicate=lambda: state["ready"])


def test_wait_for_condition_raises_readable_timeout():
    with pytest.raises(AssertionError, match="Timed out waiting for never ready"):
        wait_for_condition("never ready", timeout_s=0.01, predicate=lambda: False, interval_s=0.001)


def test_fake_turn_runner_records_submit_release_and_events():
    runner = FakeTurnRunner()
    context = {"session_id": "session-a", "turn_id": "turn-1", "agent_id": "agent-a"}

    runner.submit(context)
    runner.record_event(context, "queued", "waiting", {"position": 1})
    runner.release(context)

    assert runner.submitted == [context]
    assert runner.released == [context]
    assert runner.events == [
        {
            "turn_id": "turn-1",
            "phase": "queued",
            "outcome": "waiting",
            "fields": {"position": 1},
        }
    ]
