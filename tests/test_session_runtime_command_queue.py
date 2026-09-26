"""Session queue notices: background results and child returns share the user queue.

A rewind advances branchGeneration and drops notices stamped with the old
generation. User follow-ups stay. Contiguous background notices drain as one
turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.session import queued_turns

PARENT_ID = "session-parent"
CHILD_ID = "session-child"


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _session_id: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": PARENT_ID,
            "conversations": [
                {
                    "conversation_id": PARENT_ID,
                    "title": "Parent",
                    "branchGeneration": 0,
                },
                {
                    "conversation_id": CHILD_ID,
                    "title": "查配置",
                    "session_kind": "child",
                    "parent_session_id": PARENT_ID,
                    "task_title": "查配置",
                    "originBranchGeneration": 0,
                },
            ],
        },
    )
    return tmp_path


def _rows(tmp_path, session_id: str = PARENT_ID):
    conversation = load_session_chat_state(tmp_path, session_id)
    return queued_turns.session_queued_turn_rows(conversation)


def test_runtime_notices_share_the_queue_and_background_notices_drain_together(sessions, monkeypatch):
    submitted: list[dict] = []

    def _submit(session_id, content, **kwargs):
        submitted.append({"session_id": session_id, "content": content, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", _submit)
    queued_turns.enqueue_session_queued_turn(
        PARENT_ID,
        content="先看用户这条",
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=False,
        client_submission_id="user-1",
    )
    first = queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="task_notification",
        content="后台任务 A 完成",
        source_id="task-a",
        branch_generation=0,
        task_id="task-a",
        tool_name="cli_agent_run_tool",
    )
    second = queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="task_notification",
        content="后台任务 B 完成",
        source_id="task-b",
        branch_generation=0,
        task_id="task-b",
    )
    assert first["status"] == "queued"
    assert second["kind"] == "task_notification"
    assert [row["kind"] for row in _rows(sessions)] == ["user", "task_notification", "task_notification"]

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[0]["content"] == "先看用户这条"
    assert submitted[0]["message_source"] == "queued_turn"
    assert [row["kind"] for row in _rows(sessions)] == ["task_notification", "task_notification"]

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[1]["message_source"] == "task_notification"
    assert "后台任务 A 完成" in submitted[1]["content"]
    assert "后台任务 B 完成" in submitted[1]["content"]
    assert _rows(sessions) == []


def test_rewind_drops_stale_notices_and_keeps_user_turns(sessions):
    queued_turns.enqueue_session_queued_turn(
        PARENT_ID,
        content="留下这条",
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=False,
        client_submission_id="user-keep",
    )
    queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="task_notification",
        content="旧分支的后台结果",
        source_id="old-task",
        branch_generation=0,
    )
    generation = queued_turns.advance_session_branch_generation(PARENT_ID)
    assert generation == 1
    assert [row["content"] for row in _rows(sessions)] == ["留下这条"]
    dropped = queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="subagent_message",
        content="旧子对话回传",
        source_id="old-child",
        branch_generation=0,
        child_session_id=CHILD_ID,
    )
    assert dropped["dropped"] == "stale_branch"
    assert [row["content"] for row in _rows(sessions)] == ["留下这条"]
    fresh = queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="subagent_message",
        content="新分支的子对话回传",
        source_id="new-child",
        branch_generation=1,
        child_session_id=CHILD_ID,
    )
    assert fresh["status"] == "queued"
    assert [row["kind"] for row in _rows(sessions)] == ["user", "subagent_message"]


def test_child_return_uses_the_generation_captured_at_split(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda _session_id: [
        {"role": "assistant", "content": "配置在 config.toml"},
    ])
    queued = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-1")
    assert queued is not None
    assert queued["kind"] == "subagent_message"
    assert "查配置" in queued["content"]
    assert "config.toml" in queued["content"]
    again = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-1")
    assert again["id"] == queued["id"]
    queued_turns.advance_session_branch_generation(PARENT_ID)
    late = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-2")
    assert late["dropped"] == "stale_branch"
    assert _rows(sessions) == []


def test_cli_result_wake_queues_and_a_later_rewind_drops_it(sessions):
    status = session_service._wake_agent_for_cli_agent_task_result(
        PARENT_ID,
        task_result={"taskId": "cli-1", "status": "completed", "branchGeneration": 0},
        result_content="测试通过",
    )
    assert status == "queued"
    assert _rows(sessions)[0]["kind"] == "task_notification"
    assert "测试通过" in _rows(sessions)[0]["content"]
    queued_turns.advance_session_branch_generation(PARENT_ID)
    late = session_service._wake_agent_for_cli_agent_task_result(
        PARENT_ID,
        task_result={"taskId": "cli-1", "status": "completed", "branchGeneration": 0},
        result_content="测试通过",
    )
    assert late == "stale_branch_dropped"
    assert _rows(sessions) == []
