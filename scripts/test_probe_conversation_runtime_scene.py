from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

from core.chat.turn_journal import turn_journal_path


SCRIPT_PATH = Path(__file__).with_name("probe_conversation_runtime_scene.py")


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
    spec = importlib.util.spec_from_file_location("probe_conversation_runtime_scene", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_probe_writes_correlated_conversation_evidence_package(tmp_path, request):
    module = load_module()
    unique_token = uuid4().hex
    session_id = f"probe-session-{unique_token}"
    turn_id = f"probe-turn-{unique_token}"
    request.addfinalizer(lambda: cleanup_session_artifacts(tmp_path, session_id))

    report = module.build_conversation_runtime_probe(tmp_path, session_id, turn_id)

    assert report["sessionId"] == session_id
    assert report["turnId"] == turn_id
    assert report["journal"]["terminalEvent"]["eventType"] == "turn_completed"
    assert report["liveOutput"]["stage"] == "assistant_response"

    event_codes = [item["eventCode"] for item in report["runtimeEvidence"]["matches"]]
    assert event_codes == [
        "conversation_probe.message.submitted",
        "session.detail_snapshot.published",
        "conversation_probe.llm.status",
        "conversation_probe.tool.started",
        "conversation_probe.tool.completed",
        "session.assistant_delta.published",
        "conversation_probe.turn.persisted",
        "session.detail_snapshot.published",
    ]
    assert report["probe"]["packagePath"].endswith("probe_conversation_runtime_scene")
    assert report["probe"]["runtimeEventCount"] == 8
