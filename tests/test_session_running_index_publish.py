"""A session that starts running must reach the rail without opening it.

The settled pass already publishes the terminal index patch; this pins the
start-of-turn patch so a background session stops looking frozen.
"""

from __future__ import annotations

import pytest

from core.web.services import session_service
from core.web.services.session import runtime_glue, session_index_stream

SESSION_ID = "session-live-status"


@pytest.fixture(autouse=True)
def _clean_running_state():
    session_service._RUNNING_SESSION_IDS.discard(SESSION_ID)
    session_service._SESSION_ACTIVE_TURN_IDS.pop(SESSION_ID, None)
    session_service._SESSION_ACTIVE_TURN_LEASES.pop(SESSION_ID, None)
    yield
    session_service._RUNNING_SESSION_IDS.discard(SESSION_ID)
    session_service._SESSION_ACTIVE_TURN_IDS.pop(SESSION_ID, None)
    session_service._SESSION_ACTIVE_TURN_LEASES.pop(SESSION_ID, None)


def _publish_recorder(monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    def fake_publish(session_id, change_type, *, patch=None):
        calls.append((session_id, change_type, dict(patch or {})))
        return 1

    monkeypatch.setattr(
        session_index_stream,
        "publish_session_index_change_safely",
        fake_publish,
    )
    return calls


def test_starting_a_turn_publishes_one_running_patch(monkeypatch):
    calls = _publish_recorder(monkeypatch)
    runtime_glue._set_session_running(SESSION_ID, True, turn_id="turn-1")
    assert len(calls) == 1
    session_id, change_type, patch = calls[0]
    assert (session_id, change_type) == (SESSION_ID, "upsert")
    assert patch["status"] == "running"
    assert patch["currentPhase"] == "running"
    assert patch["updatedAt"]

    # A lease refresh on the same live turn must not republish.
    runtime_glue._set_session_running(SESSION_ID, True, turn_id="turn-1")
    assert len(calls) == 1


def test_settling_a_turn_does_not_publish_a_running_patch(monkeypatch):
    calls = _publish_recorder(monkeypatch)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "notify_parent_session_of_child_return", lambda *_a, **_k: None)
    runtime_glue._set_session_running(SESSION_ID, True, turn_id="turn-1")
    runtime_glue._set_session_running(SESSION_ID, False, turn_id="turn-1")
    assert len(calls) == 1
