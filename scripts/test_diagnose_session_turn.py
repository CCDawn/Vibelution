from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
    turn_journal_path,
)


SCRIPT_PATH = Path(__file__).with_name("diagnose_session_turn.py")


def cleanup_session_artifacts(project_root: Path, session_id: str) -> None:
    journal = turn_journal_path(project_root, session_id)
    for path in (journal, journal.with_name("live_output.json")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        journal.parent.rmdir()
    except OSError:
        pass


def load_module():
    spec = importlib.util.spec_from_file_location("diagnose_session_turn", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_build_session_turn_diagnosis_summarizes_journal_live_checkpoint_and_runtime_evidence(tmp_path, request):
    module = load_module()
    unique_token = uuid4().hex
    session_id = f"session-diagnostic-{unique_token}"
    turn_id = f"turn-{unique_token}"
    request.addfinalizer(lambda: cleanup_session_artifacts(tmp_path, session_id))

    append_turn_event(tmp_path, session_id, turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "你好"},
    )
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "你好，我在。"},
    )
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_COMPLETED,
        status="completed",
        payload={"summary": "你好，我在。"},
    )

    checkpoint = turn_journal_path(tmp_path, session_id).with_name("live_output.json")
    checkpoint.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": session_id,
                "turnId": turn_id,
                "stage": "assistant_response",
                "content": "你好，我在。",
                "thought": "",
                "toolCalls": [],
                "feedbackEvents": [],
                "updatedAt": "2026-07-09T00:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scene_events = tmp_path / "logs" / "runtime_scenes" / "20260709T000000Z__probe" / "events"
    scene_events.mkdir(parents=True)
    (scene_events / "conversation.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-09T00:00:01Z",
                "eventCode": "session.assistant_delta.published",
                "fields": {
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "contentChars": 6,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.build_session_turn_diagnosis(tmp_path, session_id, turn_id)

    assert report["sessionId"] == session_id
    assert report["turnId"] == turn_id
    assert report["journal"]["exists"] is True
    assert report["journal"]["eventCount"] == 4
    assert report["journal"]["latestSequence"] == 4
    assert report["journal"]["terminalEvent"]["eventType"] == EVENT_TURN_COMPLETED
    assert report["journal"]["eventTypes"] == [
        EVENT_TURN_STARTED,
        EVENT_USER_MESSAGE,
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TURN_COMPLETED,
    ]
    assert report["liveOutput"]["exists"] is True
    assert report["liveOutput"]["stage"] == "assistant_response"
    assert report["liveOutput"]["contentLength"] == len("你好，我在。")
    assert report["runtimeEvidence"]["matches"][0]["eventCode"] == "session.assistant_delta.published"
    assert "turn_journal.jsonl" in report["paths"]["journal"]


def _write_runtime_events(tmp_path: Path, events: list[dict]) -> None:
    path = tmp_path / "logs" / "runtime_scenes" / "scene-a" / "events" / "agent.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _runtime_event(event_code: str, *, turn_id: str, **fields) -> dict:
    return {
        "ts": "2026-07-27T00:00:00Z",
        "event_code": event_code,
        "level": "info",
        "outcome": "observed",
        "fields": {
            "sessionId": "session-1",
            "turnId": turn_id,
            "invocationId": "invocation-1",
            "routeAttempt": 1,
            "routeId": "route-1",
            **fields,
        },
    }


def test_diagnosis_closes_completed_turn_from_successful_route_evidence(tmp_path):
    module = load_module()
    turn_id = "turn-success"
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_COMPLETED, status="completed")
    _write_runtime_events(
        tmp_path,
        [
            _runtime_event("llm_route_attempt_started", turn_id=turn_id),
            _runtime_event(
                "llm_route_attempt_succeeded",
                turn_id=turn_id,
                durationMs=42,
                streamed=False,
            ),
        ],
    )

    diagnosis = module.build_session_turn_diagnosis(
        tmp_path,
        "session-1",
        turn_id,
    )["diagnosis"]

    assert diagnosis["status"] == "completed"
    assert diagnosis["terminalConsistency"]["consistent"] is True
    assert diagnosis["routeAttempts"][0]["status"] == "succeeded"
    assert diagnosis["nextMinimalAction"] == "no_action_needed"


def test_diagnosis_explains_failed_turn_and_provider_retry_action(tmp_path):
    module = load_module()
    turn_id = "turn-failed"
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_FAILED, status="failed")
    _write_runtime_events(
        tmp_path,
        [
            _runtime_event("llm_route_attempt_started", turn_id=turn_id),
            _runtime_event(
                "llm_route_attempt_exhausted",
                turn_id=turn_id,
                errorCategory="server_error",
            ),
            _runtime_event(
                "llm_turn_terminal",
                turn_id=turn_id,
                errorCategory="server_error",
                reasonCode="no_distinct_fallback",
            ),
        ],
    )

    diagnosis = module.build_session_turn_diagnosis(
        tmp_path,
        "session-1",
        turn_id,
    )["diagnosis"]

    assert diagnosis["status"] == "failed"
    assert diagnosis["failureStage"] == "route"
    assert diagnosis["rootCauseCandidates"][0]["code"] == "server_error"
    assert diagnosis["nextMinimalAction"] == "retry_provider_later"


def test_diagnosis_treats_fallback_route_success_as_completed_turn(tmp_path):
    module = load_module()
    turn_id = "turn-fallback-success"
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_COMPLETED, status="completed")
    _write_runtime_events(
        tmp_path,
        [
            _runtime_event(
                "llm_route_attempt_started",
                turn_id=turn_id,
                invocationId="invocation-primary",
                routeAttempt=1,
                routeId="route-primary",
            ),
            _runtime_event(
                "llm_route_attempt_exhausted",
                turn_id=turn_id,
                invocationId="invocation-primary",
                routeAttempt=1,
                routeId="route-primary",
                errorCategory="server_error",
            ),
            _runtime_event(
                "llm_fallback_selected",
                turn_id=turn_id,
                invocationId="",
                routeAttempt=1,
                routeId="",
                fallbackRouteId="route-fallback",
            ),
            _runtime_event(
                "llm_route_attempt_started",
                turn_id=turn_id,
                invocationId="invocation-fallback",
                routeAttempt=2,
                routeId="route-fallback",
            ),
            _runtime_event(
                "llm_route_attempt_succeeded",
                turn_id=turn_id,
                invocationId="invocation-fallback",
                routeAttempt=2,
                routeId="route-fallback",
                durationMs=57,
            ),
        ],
    )

    diagnosis = module.build_session_turn_diagnosis(
        tmp_path,
        "session-1",
        turn_id,
    )["diagnosis"]

    assert diagnosis["status"] == "completed"
    assert diagnosis["failureStage"] == "none"
    assert diagnosis["terminalConsistency"]["consistent"] is True
    assert [attempt["status"] for attempt in diagnosis["routeAttempts"]] == [
        "failed",
        "succeeded",
    ]
    assert diagnosis["nextMinimalAction"] == "no_action_needed"


def test_diagnosis_uses_latest_exact_turn_evidence_within_match_budget(tmp_path):
    module = load_module()
    turn_id = "turn-target"
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_COMPLETED, status="completed")
    unrelated_events = [
        _runtime_event(
            "llm_route_attempt_started",
            turn_id=f"turn-other-{index}",
            invocationId=f"invocation-other-{index}",
        )
        for index in range(25)
    ]
    _write_runtime_events(
        tmp_path,
        [
            *unrelated_events,
            _runtime_event("llm_route_attempt_started", turn_id=turn_id),
            _runtime_event("llm_route_attempt_succeeded", turn_id=turn_id),
        ],
    )

    report = module.build_session_turn_diagnosis(
        tmp_path,
        "session-1",
        turn_id,
        max_runtime_matches=2,
    )

    assert report["runtimeEvidence"]["matchCount"] == 2
    assert all(
        item["fields"]["turnId"] == turn_id
        for item in report["runtimeEvidence"]["matches"]
    )
    assert report["diagnosis"]["status"] == "completed"
    assert report["diagnosis"]["terminalConsistency"]["consistent"] is True


def test_diagnosis_routes_canonical_incomplete_outcome_to_protocol_adapter(tmp_path):
    module = load_module()
    turn_id = "turn-incomplete"
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-1", turn_id, EVENT_TURN_FAILED, status="failed")
    _write_runtime_events(
        tmp_path,
        [
            _runtime_event("llm_route_attempt_started", turn_id=turn_id),
            _runtime_event(
                "llm_route_attempt_succeeded",
                turn_id=turn_id,
                outcomeKind="incomplete",
            ),
            _runtime_event(
                "llm.turn_outcome.unsuccessful",
                turn_id=turn_id,
                reasonCode="canonical_turn_unsuccessful",
                outcomeKind="incomplete",
            ),
        ],
    )

    diagnosis = module.build_session_turn_diagnosis(
        tmp_path,
        "session-1",
        turn_id,
    )["diagnosis"]

    assert diagnosis["status"] == "failed"
    assert diagnosis["failureStage"] == "outcome_evaluation"
    assert diagnosis["terminalConsistency"]["consistent"] is True
    assert diagnosis["nextMinimalAction"] == "inspect_protocol_adapter"
