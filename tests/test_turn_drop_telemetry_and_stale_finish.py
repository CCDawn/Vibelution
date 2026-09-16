"""Non-current persist drop telemetry + skipped_stale worker closeout.

Covers two audit fixes:
- a non-current turn result dropped by ``_persist_session_turn_result`` must
  emit ``turn_result_dropped_not_current`` telemetry (boundary metadata only);
- the ``skipped_stale`` early-return branch must still run
  ``_finish_session_turn_worker`` so worker bookkeeping converges.
"""

from __future__ import annotations

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import session_service
from core.web.services.session import persist
from core.web.services.session import worker


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def test_persist_non_current_turn_records_dropped_not_current_event(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: False)
    events: list[dict] = []

    def recording_event(component, phase, event_code, *, message="", level="info", outcome="observed", fields=None, **_kwargs):
        events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                "message": message,
                "level": level,
                "outcome": outcome,
                "fields": dict(fields or {}),
            }
        )
        return {}

    monkeypatch.setattr(session_service, "record_runtime_scene_event", recording_event)

    persist._persist_session_turn_result(
        "s1",
        {"status": "completed", "summary": "done", "raw_output": "SECRET-RESULT-BODY"},
        turn_id="stale-turn",
    )

    assert len(events) == 1
    event = events[0]
    assert event["component"] == "conversation"
    assert event["phase"] == "turn_result_dropped_not_current"
    assert event["eventCode"] == "conversation.turn_result.dropped_not_current"
    assert event["level"] == "warning"
    assert event["outcome"] == "discarded"
    assert event["fields"]["sessionId"] == "s1"
    assert event["fields"]["turnId"] == "stale-turn"
    assert event["fields"]["resultStatus"] == "completed"
    assert event["fields"]["resultSummaryLength"] == len("done")
    # Boundary metadata only: the result body must never leak into telemetry.
    assert "SECRET-RESULT-BODY" not in str(event)


def test_run_session_turn_impl_skipped_stale_finishes_worker(monkeypatch, tmp_path) -> None:
    """The skipped_stale early return must still close out the worker.

    Mirrors the proactive fence branch: terminal fallback + running-flag
    release run even when the turn is superseded before the main try/finally.
    """

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: False)
    lifecycle: list[tuple] = []

    def recording_lifecycle(sid, phase, *, turn_id="", level="info", outcome="observed", fields=None, **_kwargs):
        lifecycle.append((phase, turn_id, fields))

    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", recording_lifecycle)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda sid: None)
    finished: list[tuple] = []
    monkeypatch.setattr(
        worker,
        "_finish_session_turn_worker",
        lambda sid, tid, control: finished.append((sid, tid, control)),
    )

    worker._run_session_turn_impl(
        {
            "session_id": "session-stale",
            "turn_id": "turn-stale",
        }
    )

    assert any(item[0] == "skipped_stale" and item[1] == "turn-stale" for item in lifecycle)
    assert finished == [("session-stale", "turn-stale", None)]
