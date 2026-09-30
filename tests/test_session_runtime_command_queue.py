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


def _enqueue_user_turn(content: str, submission_id: str) -> dict:
    return queued_turns.enqueue_session_queued_turn(
        PARENT_ID,
        content=content,
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=False,
        client_submission_id=submission_id,
    )


def test_send_now_promotes_row_to_head_and_drain_submits_it_first(sessions, monkeypatch):
    session_running = {"value": True}
    monkeypatch.setattr(
        session_service,
        "_is_session_running",
        lambda _session_id: session_running["value"],
    )
    stop_calls: list[dict] = []

    def _stop(session_id, *, expected_turn_id="", fast_ack=False):
        stop_calls.append(
            {"session_id": session_id, "expected_turn_id": expected_turn_id, "fast_ack": fast_ack}
        )
        return {"id": session_id, "currentPhase": "stopping"}

    monkeypatch.setattr(session_service, "request_stop_session_turn", _stop)
    first = _enqueue_user_turn("第一条排队", "user-1")
    second = _enqueue_user_turn("第二条排队", "user-2")
    third = _enqueue_user_turn("第三条排队", "user-3")

    result = queued_turns.send_now_session_queued_turn(
        PARENT_ID,
        third["id"],
        expected_turn_id="turn-running",
    )

    assert stop_calls == [
        {"session_id": PARENT_ID, "expected_turn_id": "turn-running", "fast_ack": True}
    ]
    assert result["stopRequested"] is True
    rows = result["queuedTurns"]
    assert [row["id"] for row in rows] == [third["id"], first["id"], second["id"]]
    assert rows[0]["sendNow"] is True
    assert all("sendNow" not in row for row in rows[1:])
    persisted = _rows(sessions)
    assert persisted[0]["id"] == third["id"]
    assert persisted[0]["sendNow"] is True

    # The stop settled: the drain claims the promoted head row first.
    session_running["value"] = False
    submitted: list[dict] = []

    def _submit(session_id, content, **kwargs):
        submitted.append({"session_id": session_id, "content": content, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", _submit)
    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[0]["content"] == "第三条排队"
    remaining = _rows(sessions)
    assert [row["content"] for row in remaining] == ["第一条排队", "第二条排队"]
    assert all("sendNow" not in row for row in remaining)


def test_send_now_rolls_back_to_original_slot_when_stop_is_rejected(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)

    def _stop(_session_id, *, expected_turn_id="", fast_ack=False):
        raise session_service.SessionBusyError("停止请求对应的轮次已不是当前运行轮次，请刷新后重试。")

    monkeypatch.setattr(session_service, "request_stop_session_turn", _stop)
    first = _enqueue_user_turn("第一条排队", "user-1")
    second = _enqueue_user_turn("第二条排队", "user-2")

    with pytest.raises(session_service.SessionBusyError):
        queued_turns.send_now_session_queued_turn(PARENT_ID, second["id"], expected_turn_id="turn-stale")

    rows = _rows(sessions)
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert all("sendNow" not in row for row in rows)


def test_send_now_is_idempotent_for_an_already_promoted_row(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    stop_calls: list[dict] = []

    def _stop(session_id, *, expected_turn_id="", fast_ack=False):
        stop_calls.append({"session_id": session_id})
        return {"id": session_id, "currentPhase": "stopping"}

    monkeypatch.setattr(session_service, "request_stop_session_turn", _stop)
    only = _enqueue_user_turn("唯一排队", "user-1")

    first_result = queued_turns.send_now_session_queued_turn(PARENT_ID, only["id"])
    second_result = queued_turns.send_now_session_queued_turn(PARENT_ID, only["id"])

    assert first_result["stopRequested"] is True
    assert second_result["stopRequested"] is False
    assert len(stop_calls) == 1
    assert [row["id"] for row in _rows(sessions)] == [only["id"]]
    assert _rows(sessions)[0]["sendNow"] is True


def test_send_now_rejects_runtime_notices(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    stop_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **_kwargs: stop_calls.append({"session_id": session_id}),
    )
    _enqueue_user_turn("用户排队", "user-1")
    notice = queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind="task_notification",
        content="后台任务完成",
        source_id="task-a",
        branch_generation=0,
        task_id="task-a",
    )

    with pytest.raises(session_service.SessionValidationError):
        queued_turns.send_now_session_queued_turn(PARENT_ID, notice["id"])

    assert stop_calls == []
    rows = _rows(sessions)
    assert [row["kind"] for row in rows] == ["user", "task_notification"]
    assert all("sendNow" not in row for row in rows)


def test_send_now_rejects_paused_and_starting_rows(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **_kwargs: {"id": session_id},
    )
    paused = _enqueue_user_turn("暂停条", "user-1")
    queued_turns.update_session_queued_turn(PARENT_ID, paused["id"], status="paused")
    with pytest.raises(session_service.SessionValidationError):
        queued_turns.send_now_session_queued_turn(PARENT_ID, paused["id"])

    # A paused row keeps no send-now pin; pausing a pinned row clears the pin.
    pinned = _enqueue_user_turn("置顶后暂停", "user-2")
    queued_turns.send_now_session_queued_turn(PARENT_ID, pinned["id"])
    assert _rows(sessions)[0]["sendNow"] is True
    queued_turns.update_session_queued_turn(PARENT_ID, pinned["id"], status="paused")
    assert all("sendNow" not in row for row in _rows(sessions))


def _enqueue_notice(kind: str, content: str, source_id: str, branch_generation: int = 0, **kwargs) -> dict:
    return queued_turns.enqueue_session_runtime_notice(
        PARENT_ID,
        kind=kind,
        content=content,
        source_id=source_id,
        branch_generation=branch_generation,
        **kwargs,
    )


def _drain_submitter(monkeypatch) -> list[dict]:
    submitted: list[dict] = []

    def _submit(session_id, content, **kwargs):
        submitted.append({"session_id": session_id, "content": content, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", _submit)
    return submitted


def test_cross_kind_notice_run_merges_into_one_model_turn(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    _enqueue_notice("task_notification", "后台任务 A 完成", "task-a", task_id="task-a")
    _enqueue_notice(
        "subagent_message",
        "子对话返回",
        "child-return:c1:t1",
        child_session_id="session-child-1",
    )
    _enqueue_notice("task_notification", "后台任务 B 完成", "task-b", task_id="task-b")

    assert [row["kind"] for row in _rows(sessions)] == [
        "task_notification",
        "subagent_message",
        "task_notification",
    ]
    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True

    assert len(submitted) == 1
    first = submitted[0]
    assert first["message_source"] == "queued_notice_batch"
    assert first["content"] == "后台任务 A 完成\n\n子对话返回\n\n后台任务 B 完成"
    assert first["message_metadata"]["merged_kinds"] == [
        "task_notification",
        "subagent_message",
    ]
    assert first["message_metadata"]["sourceIds"] == ["task-a", "child-return:c1:t1", "task-b"]
    assert first["message_metadata"]["taskIds"] == ["task-a", "task-b"]
    assert first["message_metadata"]["childSessionIds"] == ["session-child-1"]
    assert _rows(sessions) == []


def test_user_row_cuts_and_keeps_priority_over_later_notices(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    _enqueue_notice("task_notification", "通知 A", "task-a", task_id="task-a")
    _enqueue_user_turn("用户插话", "user-mid")
    _enqueue_notice("task_notification", "通知 B", "task-b", task_id="task-b")

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    # The user row cuts the run: notice A drains alone with the historical
    # single-kind shape, never merged across the user boundary.
    assert len(submitted) == 1
    assert submitted[0]["content"] == "通知 A"
    assert submitted[0]["message_source"] == "task_notification"
    assert submitted[0]["message_metadata"] == {
        "kind": "task_notification",
        "sourceIds": ["task-a"],
        "taskIds": ["task-a"],
    }

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[1]["content"] == "用户插话"
    assert submitted[1]["message_source"] == "queued_turn"

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[2]["content"] == "通知 B"
    assert submitted[2]["message_metadata"]["sourceIds"] == ["task-b"]
    assert _rows(sessions) == []


def test_mixed_run_merges_only_up_to_the_batch_cap(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    for index in range(10):
        kind = "task_notification" if index % 2 == 0 else "subagent_message"
        _enqueue_notice(kind, f"通知 {index}", f"src-{index}")

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert len(submitted) == 1
    merged = submitted[0]
    assert merged["content"].count("\n\n") == queued_turns.MAX_NOTICE_BATCH_PER_TURN - 1
    assert merged["message_metadata"]["sourceIds"] == [f"src-{i}" for i in range(queued_turns.MAX_NOTICE_BATCH_PER_TURN)]
    remaining = _rows(sessions)
    assert len(remaining) == 10 - queued_turns.MAX_NOTICE_BATCH_PER_TURN

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert len(submitted) == 2
    assert submitted[1]["message_metadata"]["sourceIds"] == [
        f"src-{i}" for i in range(queued_turns.MAX_NOTICE_BATCH_PER_TURN, 10)
    ]
    assert _rows(sessions) == []


def test_child_return_run_is_capped_per_turn(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    for index in range(10):
        _enqueue_notice(
            "subagent_message",
            f"子对话 {index} 返回",
            f"child-return:c1:t{index}",
            child_session_id=f"session-child-{index}",
        )

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert len(submitted) == 1
    assert len(submitted[0]["message_metadata"]["childSessionIds"]) == queued_turns.MAX_NOTICE_BATCH_PER_TURN
    remaining = _rows(sessions)
    assert len(remaining) == 10 - queued_turns.MAX_NOTICE_BATCH_PER_TURN
    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert _rows(sessions) == []


def test_pure_task_notification_batch_keeps_historical_shape(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    _enqueue_notice("task_notification", "后台任务 A 完成", "task-a", task_id="task-a")
    _enqueue_notice("task_notification", "后台任务 B 完成", "task-b", task_id="task-b")

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[0]["message_source"] == "task_notification"
    # Conservation: a pure batch must stay byte-identical to the historical
    # drain, so no merged_kinds audit field appears.
    assert submitted[0]["message_metadata"] == {
        "kind": "task_notification",
        "sourceIds": ["task-a", "task-b"],
        "taskIds": ["task-a", "task-b"],
    }
    assert submitted[0]["content"] == "后台任务 A 完成\n\n后台任务 B 完成"


def test_single_child_return_keeps_historical_shape(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    _enqueue_notice(
        "subagent_message",
        "子对话返回",
        "child-return:c1:t1",
        child_session_id="session-child-1",
    )

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    assert submitted[0]["message_source"] == "subagent_message"
    assert submitted[0]["message_metadata"] == {
        "kind": "subagent_message",
        "sourceId": "child-return:c1:t1",
        "childSessionId": "session-child-1",
    }


def test_control_notice_drains_to_journal_without_model_turn(sessions, monkeypatch):
    submitted = _drain_submitter(monkeypatch)
    queued = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="用户在忙时直接启动了后台任务 X",
        source_id="control:start-task-x",
        branch_generation=0,
    )
    assert queued["status"] == "queued"
    assert [row["kind"] for row in _rows(sessions)] == ["control_notice"]

    assert queued_turns.drain_session_queued_turns(PARENT_ID) is True
    # Journal-only: no model turn is submitted and the row is consumed.
    assert submitted == []
    assert _rows(sessions) == []

    events = session_service._load_session_conversation_events_cached(PARENT_ID)
    control_events = [
        event
        for event in events
        if str((event.payload or {}).get("metadata", {}).get("kind") or "") == "control_notice"
    ]
    assert len(control_events) == 1
    event = control_events[0]
    assert event.event_type == session_service.EVENT_USER_MESSAGE
    assert event.visible_in_model is False
    assert event.payload["content"] == "用户在忙时直接启动了后台任务 X"
    assert event.payload["metadata"]["sourceId"] == "control:start-task-x"
    assert event.turn_id == queued["id"]
    # Audit-only visibility: the model-visible projection keeps it out.
    visible = session_service.conversation_visible_messages_from_events(events)
    assert all("后台任务 X" not in str(message.get("content") or "") for message in visible)


def test_control_notice_is_fenced_and_capped_like_runtime_notices(sessions):
    stale = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="旧分支的控制记录",
        source_id="control:old",
        branch_generation=0,
    )
    generation = queued_turns.advance_session_branch_generation(PARENT_ID)
    assert generation == 1
    # A control notice stamped with the pre-rewind generation arrives late:
    # dropped, and the rewind itself pruned nothing (the row was dropped
    # before it could queue).
    assert stale["status"] == "queued"
    assert _rows(sessions) == []
    late = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="rewind 后迟到的控制记录",
        source_id="control:late",
        branch_generation=0,
    )
    assert late["dropped"] == "stale_branch"

    fresh = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="当前分支的控制记录",
        source_id="control:fresh",
        branch_generation=1,
    )
    assert fresh["status"] == "queued"
    generation = queued_turns.advance_session_branch_generation(PARENT_ID)
    assert _rows(sessions) == []

    # The control notice shares the session notice cap with runtime notices.
    for index in range(queued_turns.MAX_RUNTIME_NOTICES_PER_SESSION):
        assert _enqueue_notice(
            "task_notification", f"通知 {index}", f"cap-{index}", branch_generation=generation
        )["status"] == "queued"
    full = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="超限的控制记录",
        source_id="control:overflow",
        branch_generation=generation,
    )
    assert full["dropped"] == "queue_full"
    also_full = _enqueue_notice(
        "task_notification", "超限通知", "cap-overflow", branch_generation=generation
    )
    assert also_full["dropped"] == "queue_full"


def test_control_notice_rejects_edit_and_send_now_but_can_be_withdrawn(sessions, monkeypatch):
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    stop_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **_kwargs: stop_calls.append({"session_id": session_id}),
    )
    control = queued_turns.enqueue_session_control_notice(
        PARENT_ID,
        content="用户决定",
        source_id="control:decision",
        branch_generation=0,
    )
    with pytest.raises(session_service.SessionValidationError):
        queued_turns.update_session_queued_turn(PARENT_ID, control["id"], content="改写")
    with pytest.raises(session_service.SessionValidationError):
        queued_turns.send_now_session_queued_turn(PARENT_ID, control["id"])
    assert stop_calls == []

    remaining = queued_turns.remove_session_queued_turn(PARENT_ID, control["id"])
    assert remaining == []
