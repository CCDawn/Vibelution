from core.ui.chat_state import build_chat_state, load_chat_state, save_chat_state
from core.chat.turn_journal import EVENT_CLI_TASK_RESULT, load_turn_events, model_visible_messages_from_events
from core.web.services import session_service


def test_cli_agent_task_result_event_persists_once_and_enters_history(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_cli_agent_task_result_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda *args, **kwargs: {"signalId": "sig-1"})
    save_chat_state(
        tmp_path,
        build_chat_state(
            [{"role": "user", "content": "让 CLI 分析失败原因", "timestamp": "2026-06-14T10:00:00"}],
            conversation_id="session-1",
            title="CLI 回流",
        ),
    )
    result = {
        "taskId": "cli-task-1",
        "status": "timeout",
        "code": "CLI_AGENT_TASK_TIMEOUT",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "terminalSessionId": "cli-term-1",
        "cwd": str(tmp_path),
        "taskPreview": "运行测试",
        "completionReason": "timeout",
        "timedOut": True,
        "resultSegments": [
            {"kind": "status", "text": "正在运行测试"},
            {"kind": "error", "text": "最后停在读取配置"},
        ],
    }

    first = session_service.append_cli_agent_task_result_event("session-1", task_result=result)
    second = session_service.append_cli_agent_task_result_event("session-1", task_result=result)

    state = load_chat_state(tmp_path)
    journal_events = load_turn_events(tmp_path, "session-1")
    visible = model_visible_messages_from_events(journal_events)
    result_messages = [
        item
        for item in visible
        if (item.get("metadata") or {}).get("kind") == EVENT_CLI_TASK_RESULT
    ]
    assert first is not None
    assert second is not None
    assert "messages" not in state["conversations"][0]
    assert len(result_messages) == 1
    tool_call = result_messages[0]["toolCalls"][0]
    assert "CLI Agent 任务结果回流：MiMo Code" in tool_call["result"]
    assert "状态：超时" in tool_call["result"]
    assert "最后停在读取配置" in tool_call["result"]
    assert [event.event_type for event in journal_events] == [EVENT_CLI_TASK_RESULT]
    assert visible[0]["toolCalls"][0]["name"] == "cli_agent_run_tool"
    assert visible[0]["toolCalls"][0]["status"] == "timeout"


def test_cli_agent_task_result_wake_status_is_returned(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_cli_agent_task_result_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda *args, **kwargs: {"signalId": "sig-1"})
    monkeypatch.setattr(session_service, "_wake_agent_for_cli_agent_task_result", lambda *args, **kwargs: "wake_scheduled")
    save_chat_state(
        tmp_path,
        build_chat_state(
            [{"role": "user", "content": "启动 CLI", "timestamp": "2026-06-14T10:00:00"}],
            conversation_id="session-1",
            title="CLI 唤醒",
        ),
    )

    event = session_service.append_cli_agent_task_result_event(
        "session-1",
        task_result={
            "taskId": "cli-task-2",
            "status": "completed",
            "code": "CLI_AGENT_TASK_COMPLETED",
            "adapterId": "mimo_code",
            "label": "MiMo Code",
            "terminalSessionId": "cli-term-2",
            "stdoutPreview": "已完成",
        },
        wake_agent=True,
        wake_reason="test",
    )

    assert event is not None
    assert event["_cliAgentWakeStatus"] == "wake_scheduled"
