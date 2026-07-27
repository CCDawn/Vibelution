from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.chat.turn_journal as turn_journal
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    append_turn_event,
    load_turn_events,
    model_visible_messages_from_events,
    rewrite_turn_events,
    turn_journal_path,
)


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    return data_home


def test_stopped_assistant_event_projects_explicit_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-stopped",
        session_id="session-stopped",
        turn_id="turn-stopped",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="stopped",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={
            "content": "本轮已按请求停止。",
            "toolCalls": [
                {
                    "id": "call-stopped",
                    "name": "code_symbol_tool",
                    "status": "stopped",
                }
            ],
        },
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is True


def test_completed_assistant_event_does_not_project_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-completed",
        session_id="session-completed",
        turn_id="turn-completed",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="completed",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={"content": "已完成。"},
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is False


def test_concurrent_process_appends_keep_sequences_unique_and_contiguous(tmp_path):
    process_count = 6
    events_per_process = 12
    start_file = tmp_path / "start"
    worker = "\n".join(
        [
            "import os",
            "import time",
            "from pathlib import Path",
            "from core.chat.turn_journal import EVENT_USER_MESSAGE, append_turn_event",
            "start = Path(os.environ['TURN_JOURNAL_START_FILE'])",
            "while not start.exists():",
            "    time.sleep(0.005)",
            "worker_id = os.environ['TURN_JOURNAL_WORKER_ID']",
            f"for index in range({events_per_process}):",
            "    append_turn_event(",
            "        Path(os.environ['TURN_JOURNAL_PROJECT_ROOT']),",
            "        'session-concurrent',",
            "        f'turn-{worker_id}',",
            "        EVENT_USER_MESSAGE,",
            "        payload={'content': f'{worker_id}:{index}'},",
            "    )",
        ]
    )
    processes = []
    for worker_id in range(process_count):
        env = os.environ.copy()
        env.update(
            {
                "TURN_JOURNAL_PROJECT_ROOT": str(tmp_path),
                "TURN_JOURNAL_START_FILE": str(start_file),
                "TURN_JOURNAL_WORKER_ID": str(worker_id),
            }
        )
        processes.append(
            subprocess.Popen(
                [sys.executable, "-c", worker],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

    start_file.touch()
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode:
            failures.append({"returncode": process.returncode, "stdout": stdout, "stderr": stderr})
    assert failures == []

    events = load_turn_events(tmp_path, "session-concurrent")
    expected_count = process_count * events_per_process
    assert len(events) == expected_count
    assert [event.sequence for event in events] == list(range(1, expected_count + 1))
    assert len({event.event_id for event in events}) == expected_count


def test_append_flushes_and_fsyncs_before_return(tmp_path, monkeypatch):
    fsynced_fds: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsynced_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(turn_journal.os, "fsync", record_fsync)

    append_turn_event(
        tmp_path,
        "session-fsync",
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "durable"},
    )

    assert fsynced_fds
    assert load_turn_events(tmp_path, "session-fsync")[0].payload == {"content": "durable"}


def test_rewrite_failure_preserves_original_parseable_journal(tmp_path, monkeypatch):
    append_turn_event(
        tmp_path,
        "session-rewrite",
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "original"},
    )
    path = turn_journal_path(tmp_path, "session-rewrite")
    original_bytes = path.read_bytes()
    replacement = TurnJournalEvent(
        schema_version=2,
        event_id="replacement-000001",
        session_id="session-rewrite",
        turn_id="turn-2",
        sequence=1,
        event_type=EVENT_USER_MESSAGE,
        status="recorded",
        timestamp="2026-07-27T00:00:00Z",
        source="test",
        payload={"content": "replacement"},
    )

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(turn_journal.os, "replace", fail_replace)
    rewrite_turn_events(tmp_path, "session-rewrite", [replacement])

    assert path.read_bytes() == original_bytes
    assert [event.payload for event in load_turn_events(tmp_path, "session-rewrite")] == [
        {"content": "original"}
    ]
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert list(path.parent.glob("turn_journal.jsonl.*.tmp")) == []


def test_loading_missing_journal_has_no_filesystem_side_effect(tmp_path):
    path = turn_journal_path(tmp_path, "session-missing")

    assert load_turn_events(tmp_path, "session-missing") == []
    assert not path.parent.exists()
