from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
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
