from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.chat.turn_journal as turn_journal
from core.chat.conversation_invariant import check_conversation_payload_invariant
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_BRANCH_REBASE,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    append_turn_event,
    fold_active_events,
    latest_open_turn_id,
    latest_turn_sequence,
    load_latest_turn_events_for_preview,
    load_turn_events,
    model_messages_from_events,
    model_visible_messages_from_events,
    rewrite_turn_events,
    session_turn_items_from_events,
    turn_journal_path,
)
from tests.helpers.managed_processes import managed_processes


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


def test_completed_turn_usage_enriches_canonical_assistant_message():
    assistant_event = TurnJournalEvent(
        schema_version=1,
        event_id="event-assistant-canonical",
        session_id="session-usage",
        turn_id="turn-usage",
        sequence=1,
        event_type=EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        timestamp="2026-08-01T00:00:00",
        source="test",
        payload={
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "text": "CACHE-PROBE-B-OK",
            "invocationId": "invocation-usage",
            "itemId": "item-usage",
            "revision": 1,
        },
    )
    terminal_event = TurnJournalEvent(
        schema_version=1,
        event_id="event-turn-completed",
        session_id="session-usage",
        turn_id="turn-usage",
        sequence=2,
        event_type=EVENT_TURN_COMPLETED,
        status="completed",
        timestamp="2026-08-01T00:00:01",
        source="test",
        payload={
            "llmUsage": {
                "source": "provider_usage",
                "inputTokens": 15418,
                "outputTokens": 9,
                "totalTokens": 15427,
                "cachedInputTokens": 15360,
                "cacheReadInputTokens": 15360,
                "uncachedInputTokens": 58,
                "cacheHitRate": 15360 / 15418,
            }
        },
    )

    messages = model_visible_messages_from_events([assistant_event, terminal_event])

    assert len(messages) == 1
    assert messages[0]["content"] == "CACHE-PROBE-B-OK"
    assert messages[0]["metadata"]["llmUsage"]["source"] == "provider_usage"
    assert messages[0]["metadata"]["llmUsage"]["cachedInputTokens"] == 15360


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
    with managed_processes() as processes:
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
                failures.append(
                    {"returncode": process.returncode, "stdout": stdout, "stderr": stderr}
                )
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


def test_post_terminal_write_raises_dedicated_error_and_reports_settled_turn(tmp_path):
    append_turn_event(tmp_path, "session-settled", "turn-1", EVENT_USER_MESSAGE, payload={"content": "hi"})
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-1") is False

    append_turn_event(
        tmp_path,
        "session-settled",
        "turn-1",
        turn_journal.EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "detail_loaded_after_restart"},
    )

    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-1") is True
    with pytest.raises(turn_journal.TurnJournalPostTerminalWriteError) as excinfo:
        append_turn_event(
            tmp_path,
            "session-settled",
            "turn-1",
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "reasoning", "text": "late"},
        )
    assert isinstance(excinfo.value, ValueError)
    assert "after terminal event" in str(excinfo.value)


def test_turn_has_terminal_event_ignores_unknown_and_empty_turns(tmp_path):
    append_turn_event(tmp_path, "session-settled", "turn-1", EVENT_USER_MESSAGE, payload={"content": "hi"})

    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "") is False
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-other") is False
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-missing", "turn-1") is False


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


def test_rewrite_preserves_monotonic_sequence_watermark(tmp_path):
    events = [
        append_turn_event(
            tmp_path,
            "session-watermark",
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(5)
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    path = turn_journal_path(tmp_path, "session-watermark")

    rewrite_turn_events(tmp_path, "session-watermark", events[:2])

    # The rewrite dropped sequences 3..5; cursors already published must stay valid.
    assert latest_turn_sequence(tmp_path, "session-watermark") == 5
    turn_journal._forget_sequence(path)
    assert latest_turn_sequence(tmp_path, "session-watermark") == 5

    next_event = append_turn_event(
        tmp_path,
        "session-watermark",
        "turn-2",
        EVENT_USER_MESSAGE,
        payload={"content": "edited"},
    )
    assert next_event.sequence == 6
    assert [event.sequence for event in load_turn_events(tmp_path, "session-watermark")] == [1, 2, 6]


def test_empty_rewrite_keeps_sequence_watermark(tmp_path):
    events = [
        append_turn_event(
            tmp_path,
            "session-watermark-empty",
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(3)
    ]
    assert events[-1].sequence == 3

    rewrite_turn_events(tmp_path, "session-watermark-empty", [])

    assert latest_turn_sequence(tmp_path, "session-watermark-empty") == 3
    next_event = append_turn_event(
        tmp_path,
        "session-watermark-empty",
        "turn-2",
        EVENT_USER_MESSAGE,
        payload={"content": "after-unlink"},
    )
    assert next_event.sequence == 4


def test_loading_missing_journal_has_no_filesystem_side_effect(tmp_path):
    path = turn_journal_path(tmp_path, "session-missing")

    assert load_turn_events(tmp_path, "session-missing") == []
    assert not path.parent.exists()


def _incident_shape_event(sequence: int, event_type: str, payload: dict, **kwargs) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=1,
        event_id=f"event-empty-{sequence}",
        session_id="session-empty-tool-result",
        turn_id="turn-empty-tool-result",
        sequence=sequence,
        event_type=event_type,
        status="completed",
        timestamp="2026-09-10T08:16:00Z",
        source="test",
        payload=payload,
        **kwargs,
    )


def test_empty_tool_result_with_call_id_keeps_placeholder_and_closes_provider_chain():
    """Regression: session-20260910-170320-944065 empty glob_tool result.

    An EVENT_TOOL_RESULT whose body is empty must still close the assistant
    tool_call at replay; dropping it degraded the chain into
    historical_unresolved_tool_call and the fail-closed send invariant
    permanently rejected every later send for the session.
    """

    events = [
        _incident_shape_event(1, EVENT_USER_MESSAGE, {"content": "帮我找一下文件"}),
        _incident_shape_event(
            2,
            EVENT_ASSISTANT_MESSAGE,
            {
                "content": "",
                "toolCalls": [
                    {
                        "id": "call_01_incident",
                        "name": "glob_tool",
                        "arguments": {"pattern": "**/*.md"},
                    }
                ],
            },
        ),
        _incident_shape_event(
            3,
            EVENT_TOOL_RESULT,
            {
                "toolCall": {
                    "id": "call_01_incident",
                    "name": "glob_tool",
                    "status": "done",
                    "result": [],
                }
            },
            tool_call_id="call_01_incident",
            correlation_id="call_01_incident",
        ),
        _incident_shape_event(4, EVENT_ASSISTANT_MESSAGE, {"content": "没有找到匹配文件。"}),
        _incident_shape_event(5, EVENT_TURN_COMPLETED, {}),
    ]

    model_messages = model_messages_from_events(events)

    assistant_calls = [
        call["id"]
        for message in model_messages
        for call in message.get("tool_calls") or []
        if isinstance(call, dict)
    ]
    assert assistant_calls == ["call_01_incident"]
    tool_messages = [message for message in model_messages if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_01_incident"]
    assert tool_messages[0]["content"] == "（空结果）工具已执行但未返回可见输出。"
    kinds = [str((message.get("metadata") or {}).get("kind") or "") for message in model_messages]
    assert "historical_unresolved_tool_call" not in kinds

    result = check_conversation_payload_invariant(list(model_messages))
    assert result.ok, f"{result.error_type}: {result.message}"


def test_empty_unlinked_tool_result_event_is_still_dropped():
    events = [
        _incident_shape_event(1, EVENT_USER_MESSAGE, {"content": "普通问题"}),
        _incident_shape_event(2, EVENT_TOOL_RESULT, {"result": []}),
        _incident_shape_event(3, EVENT_ASSISTANT_MESSAGE, {"content": "已处理。"}),
        _incident_shape_event(4, EVENT_TURN_COMPLETED, {}),
    ]

    messages = model_visible_messages_from_events(events)

    contents = [str(message.get("content") or "") for message in messages]
    assert "帮我" not in "".join(contents)
    assert "（空结果）工具已执行但未返回可见输出。" not in contents
    assert "已处理。" in contents
    assert [str(message.get("role") or "") for message in messages] == ["user", "assistant"]


def _branch_event(
    event_id: str,
    turn_id: str,
    sequence: int,
    event_type: str,
    *,
    payload: dict | None = None,
    parent_event_id: str = "",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=2,
        event_id=event_id,
        session_id="session-branch",
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status="recorded",
        timestamp=f"2026-09-12T00:00:{sequence:02d}",
        source="test",
        payload=dict(payload or {}),
        parent_event_id=parent_event_id,
    )


def _rebase_event(
    sequence: int,
    from_event_id: str,
    *,
    operation: str = "edit",
    event_id: str = "event-rebase",
) -> TurnJournalEvent:
    return _branch_event(
        event_id,
        "turn-new",
        sequence,
        EVENT_BRANCH_REBASE,
        payload={
            "operation": operation,
            "branchId": "branch-1",
            "fromEventId": from_event_id,
            "replacedTurnIds": [],
        },
        parent_event_id=from_event_id,
    )


def _fold_fixture() -> list[TurnJournalEvent]:
    return [
        _branch_event("event-u1", "turn-1", 1, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _branch_event("event-a1", "turn-1", 2, EVENT_ASSISTANT_MESSAGE, payload={"content": "原始回答"}),
        _branch_event("event-u2", "turn-2", 3, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _branch_event("event-a2", "turn-2", 4, EVENT_ASSISTANT_MESSAGE, payload={"content": "后续回答"}),
    ]


def test_unknown_event_type_stays_readable_and_invisible_to_replay(tmp_path):
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "问题"}
    )
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", "future_schema_event", status="recorded", payload={"future": True}
    )
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", EVENT_ASSISTANT_MESSAGE, status="completed", payload={"content": "回答"}
    )

    events = load_turn_events(tmp_path, "session-unknown")

    assert [event.event_type for event in events] == [
        EVENT_USER_MESSAGE,
        "future_schema_event",
        EVENT_ASSISTANT_MESSAGE,
    ]
    visible = model_visible_messages_from_events(events)
    assert [str(message.get("content") or "") for message in visible] == ["问题", "回答"]
    model_messages = model_messages_from_events(events)
    assert [str(message.get("content") or "") for message in model_messages] == ["问题", "回答"]


def test_unknown_event_type_marks_preview_unsafe_for_canonical_fallback(tmp_path):
    append_turn_event(
        tmp_path, "session-preview", "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "问题"}
    )
    append_turn_event(
        tmp_path, "session-preview", "turn-1", "future_schema_event", status="recorded", payload={}
    )
    append_turn_event(
        tmp_path, "session-preview", "turn-1", EVENT_ASSISTANT_MESSAGE, status="completed", payload={"content": "回答"}
    )

    events, _reached_start, safe = load_latest_turn_events_for_preview(tmp_path, "session-preview")

    assert safe is False
    assert not any(event.event_type == "future_schema_event" for event in events)


def test_fold_active_events_is_identity_without_rebase():
    events = _fold_fixture()

    assert fold_active_events(events) == events


def test_fold_active_events_cuts_superseded_segment_after_fork_point():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2b"]


def test_fold_active_events_supports_nested_rebase():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-u1", event_id="event-rebase-2"),
        _branch_event("event-u1c", "turn-4", 9, EVENT_USER_MESSAGE, payload={"content": "重开"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-u1c"]


def test_fold_active_events_empty_fork_point_clears_history():
    events = [
        *_fold_fixture(),
        _rebase_event(5, ""),
        _branch_event("event-u1b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "从零开始"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1b"]


def test_fold_active_events_keeps_path_when_fork_point_is_missing():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-missing"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [event.event_id for event in _fold_fixture()]


def test_fold_active_events_head_select_restores_superseded_branch():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-a2", operation="head_select", event_id="event-rebase-2"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_fold_active_events_head_select_then_new_message_continues_from_target():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-a2", operation="head_select", event_id="event-rebase-2"),
        _branch_event("event-u3", "turn-4", 9, EVENT_USER_MESSAGE, payload={"content": "沿旧分支继续"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [
        "event-u1",
        "event-a1",
        "event-u2",
        "event-a2",
        "event-u3",
    ]


def test_fold_active_events_head_select_to_active_tip_is_idempotent():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a2", operation="head_select", event_id="event-rebase-1"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_fold_active_events_head_select_to_unknown_event_keeps_current_path():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-missing", operation="head_select", event_id="event-rebase-1"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [event.event_id for event in _fold_fixture()]


def test_fold_active_events_ignores_unknown_rebase_operation():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", operation="future_operation"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_turn_items_follow_the_active_branch():
    events = [
        _branch_event("event-u1", "turn-1", 1, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _branch_event("event-a1", "turn-1", 2, EVENT_ASSISTANT_MESSAGE, payload={"content": "原始回答"}),
        _branch_event("event-ts2", "turn-2", 3, "turn_started", payload={}),
        _branch_event("event-u2", "turn-2", 4, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _branch_event(
            "event-item2",
            "turn-2",
            5,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "assistant_message", "text": "后续回答", "itemId": "item-2", "revision": 1},
        ),
        _rebase_event(6, "event-a1", event_id="event-rebase"),
        _branch_event("event-ts3", "turn-3", 7, "turn_started", payload={}),
        _branch_event("event-u3", "turn-3", 8, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event(
            "event-item3",
            "turn-3",
            9,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "assistant_message", "text": "新回答", "itemId": "item-3", "revision": 1},
        ),
    ]

    items = session_turn_items_from_events(events)

    assert [item["text"] for item in items] == ["新回答"]


def test_latest_open_turn_id_ignores_superseded_open_turn():
    events = [
        _branch_event("event-ts1", "turn-1", 1, "turn_started", payload={}),
        _branch_event("event-u1", "turn-1", 2, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _rebase_event(3, "", event_id="event-rebase"),
    ]

    assert latest_open_turn_id(events) == ""
