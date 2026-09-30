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


def _register_child_task(store, task_id, *, parent, generation=0, kind="child_session"):
    from core.web.services import runtime_task_registry as runtime_tasks

    return store.register_task(
        runtime_tasks.new_snapshot(
            kind=kind,
            task_id=task_id,
            status="running",
            source_session_id=parent,
            parent_session_id=parent,
            branch_generation=generation,
        )
    )


def test_sealed_child_return_is_dropped_without_waking_parent(sessions, monkeypatch):
    from core.web.services import runtime_task_registry as runtime_tasks

    store = runtime_tasks.store_for(sessions)
    monkeypatch.setattr(runtime_tasks, "default_store", lambda: store)
    _register_child_task(store, CHILD_ID, parent=PARENT_ID)
    store.seal_and_request_stop(
        CHILD_ID,
        reason="parent_turn_cancelled",
        turn_id="turn-stop",
        cascaded_from=PARENT_ID,
    )

    dropped = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-1")

    assert dropped == {
        "id": "",
        "kind": "subagent_message",
        "status": "dropped",
        "dropped": "sealed",
        "sourceId": f"child-return:{CHILD_ID}:turn-1",
        "childSessionId": CHILD_ID,
    }
    assert _rows(sessions) == []
    state = store.load_state(CHILD_ID)
    assert state["lastNotificationDrop"]["dropped"] == "sealed"
    assert state["lastNotificationDrop"]["turnId"] == "turn-1"
    assert state["status"] == "canceled"


def test_unsealed_child_return_still_queues_after_normal_completion(sessions, monkeypatch):
    from core.web.services import runtime_task_registry as runtime_tasks

    store = runtime_tasks.store_for(sessions)
    monkeypatch.setattr(runtime_tasks, "default_store", lambda: store)
    _register_child_task(store, CHILD_ID, parent=PARENT_ID)
    # Normal completion mirrors the return without ever sealing.
    store.mark_task_terminal(CHILD_ID, status="completed", reason="child_session_return")

    queued = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-1")

    assert queued["status"] == "queued"
    assert queued["kind"] == "subagent_message"
    assert [row["kind"] for row in _rows(sessions)] == ["subagent_message"]
    assert store.load_state(CHILD_ID)["notificationSealed"] is False


def test_seal_drops_independently_of_generation_and_stacks_with_fencing(sessions, monkeypatch):
    from core.web.services import runtime_task_registry as runtime_tasks

    store = runtime_tasks.store_for(sessions)
    monkeypatch.setattr(runtime_tasks, "default_store", lambda: store)
    _register_child_task(store, CHILD_ID, parent=PARENT_ID, generation=0)
    store.seal_and_request_stop(CHILD_ID, reason="parent_turn_cancelled", turn_id="turn-stop")

    # Generation still matches: the seal alone drops the return.
    sealed = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-1")
    assert sealed["dropped"] == "sealed"
    assert _rows(sessions) == []

    # A rewind on top of the seal: fencing and seal stack, the sealed channel
    # still reports the drop and nothing reaches the parent queue.
    queued_turns.advance_session_branch_generation(PARENT_ID)
    stacked = queued_turns.notify_parent_session_of_child_return(CHILD_ID, turn_id="turn-2")
    assert stacked["dropped"] == "sealed"
    assert _rows(sessions) == []
