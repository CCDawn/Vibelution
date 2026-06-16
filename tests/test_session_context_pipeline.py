# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.chat.context_assembler import assemble_conversation_context
from core.chat.history_ledger import (
    EVENT_CHECKPOINT,
    build_checkpoint_message,
    build_history_events,
    search_history_events,
)
from core.chat.turn_journal import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_turn_event,
    load_turn_events,
)
from core.ui.chat_state import build_chat_state, save_chat_state
from core.web.services import session_service
from tools import conversation_history_tools
from tools.Key_Tools import create_key_tools


def test_history_ledger_indexes_assistant_tool_results():
    messages = [
        {"role": "user", "content": "运行相关测试"},
        {
            "role": "assistant",
            "content": "",
            "toolCalls": [
                {
                    "toolName": "cli_tool",
                    "toolCallId": "call_test",
                    "status": "failed",
                    "arguments": {"command": "python -m pytest"},
                    "resultPreview": "Windows detected Unix shell fragment.",
                }
            ],
        },
    ]

    events = build_history_events(messages, session_id="session-a")
    matches = search_history_events(events, query="Windows Unix", event_type="tool_result")

    assert len(matches) == 1
    assert matches[0].tool_name == "cli_tool"
    assert matches[0].tool_call_id == "call_test"
    assert "Windows detected" in matches[0].content


def test_context_assembler_keeps_recent_tail_and_omits_old_events():
    messages = []
    for index in range(12):
        messages.append({"role": "user", "content": f"用户消息 {index}"})
        messages.append({"role": "assistant", "content": f"回答 {index}"})

    assembled = assemble_conversation_context(messages, session_id="session-a", recent_message_limit=4)

    assert [item["content"] for item in assembled.history_messages] == ["用户消息 10", "回答 10", "用户消息 11", "回答 11"]
    assert assembled.omitted_event_count > 0
    assert assembled.cacheable_prefix_hash
    assert assembled.dynamic_context_hash


def test_context_assembler_keeps_recent_tool_results_complete_for_model_input():
    huge_output = "terminal-line\n" * 1000
    full_result = f"[EXEC FAILURE | Exit Code: 1]\n{huge_output}"
    messages = [
        {"role": "user", "content": "分析失败"},
        {
            "role": "assistant",
            "content": "",
            "toolCalls": [
                {
                    "toolName": "cli_tool",
                    "toolCallId": "call-heavy",
                    "status": "failed",
                    "arguments": {"command": "pytest -q", "timeout": 120},
                    "result": full_result,
                }
            ],
        },
    ]

    assembled = assemble_conversation_context(messages, session_id="session-a", recent_message_limit=3)
    assistant_message = next(item for item in assembled.history_messages if item.get("tool_calls"))
    tool_message = next(item for item in assembled.history_messages if item.get("role") == "tool")
    tool_call = assistant_message["tool_calls"][0]

    assert tool_call["function"]["name"] == "cli_tool"
    assert json.loads(tool_call["function"]["arguments"]) == {"command": "pytest -q", "timeout": 120}
    assert tool_message["tool_call_id"] == tool_call["id"]
    assert full_result in tool_message["content"]
    assert "terminal-line\n" * 20 in tool_message["content"]
    assert "Windows detected" not in tool_message["content"]


def test_context_assembler_replays_turn_journal_over_message_tail(tmp_path):
    full_result = "journal-result-line\n" * 80
    append_turn_event(tmp_path, "session-journal", "turn-a", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续刚才中断的修复"},
    )
    append_turn_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"name": "cli_tool", "status": "done", "result": full_result}},
    )
    append_turn_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经完成一半实现。"},
    )
    append_turn_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "process_restarted", "marker": TURN_INTERRUPTED_MARKER},
    )

    assembled = assemble_conversation_context(
        [{"role": "user", "content": "旧 messages 不应作为事实源"}],
        session_id="session-journal",
        journal_events=load_turn_events(tmp_path, "session-journal"),
        recent_message_limit=8,
    )

    contents = [str(item.get("content") or "") for item in assembled.history_messages]
    assert "旧 messages 不应作为事实源" not in contents
    assert "继续刚才中断的修复" in contents
    assert "已经完成一半实现。" in contents
    assert any(TURN_INTERRUPTED_MARKER in content for content in contents)
    assistant_tool_message = next(item for item in assembled.history_messages if item.get("tool_calls"))
    tool_result_message = next(item for item in assembled.history_messages if item.get("role") == "tool")
    assert assistant_tool_message["tool_calls"][0]["function"]["name"] == "cli_tool"
    assert full_result in tool_result_message["content"]


def test_context_assembler_excludes_current_turn_journal_from_history_seed(tmp_path):
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-previous",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "上一轮用户输入"},
        source="test",
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-previous",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "上一轮助手输出"},
        source="test",
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-current",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "当前轮用户输入"},
        source="test",
    )

    assembled = assemble_conversation_context(
        [],
        session_id="session-a",
        current_turn_id="turn-current",
        journal_events=load_turn_events(tmp_path, "session-a"),
    )

    contents = [str(item.get("content") or "") for item in assembled.history_messages]
    assert "上一轮用户输入" in contents
    assert "上一轮助手输出" in contents
    assert "当前轮用户输入" not in contents


def test_context_assembler_uses_checkpoint_as_navigation_not_replacing_history():
    messages = [
        {"role": "user", "content": "旧请求"},
        {"role": "assistant", "content": "旧回答"},
        build_checkpoint_message(
            session_id="session-a",
            covered_event_ids=["session-a:0:user_message:old"],
            summary="旧阶段已经完成定位，证据在早期事件里。",
            reason="context_limit",
        ),
        {"role": "user", "content": "最新请求"},
    ]

    events = build_history_events(messages, session_id="session-a")
    checkpoints = [event for event in events if event.event_type == EVENT_CHECKPOINT]
    assembled = assemble_conversation_context(messages, session_id="session-a", recent_message_limit=1)

    assert len(checkpoints) == 1
    assert checkpoints[0].metadata["coveredEventIds"] == ["session-a:0:user_message:old"]
    assert assembled.history_messages[0]["metadata"]["kind"] == "history_checkpoint_seed"
    assert assembled.history_messages[-1]["content"] == "最新请求"
    assert len(events) >= len(messages)


def test_auto_continue_pause_result_preserves_visible_reply_without_internal_prompt():
    result = {
        "status": "completed",
        "outcome": "progress",
        "raw_output": "已经完成读取，下一步准备修改。",
        "tool_call_count": 1,
    }

    paused = session_service._build_auto_continue_paused_result(result, None, 1)

    assert paused["status"] == "completed"
    assert paused["outcome"] == "needs_input"
    assert paused["raw_output"] == "已经完成读取，下一步准备修改。"
    assert paused["metadata"]["internal_auto_continue_blocked"] is True
    assert "继续完成同一个用户目标" not in str(paused)


def test_history_search_tool_uses_current_runtime_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        build_chat_state(
            [
                {"role": "user", "content": "开始修复上下文"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "cli_tool",
                            "status": "done",
                            "resultPreview": "pytest passed for context pipeline",
                        }
                    ],
                },
            ],
            conversation_id="session-tool",
            title="测试会话",
        ),
    )
    monkeypatch.setattr(conversation_history_tools, "PROJECT_ROOT", tmp_path)

    from core.web.services import agent_directory_service

    with agent_directory_service.active_agent_runtime("agent-a", session_id="session-tool"):
        payload = conversation_history_tools.history_search_tool(query="pytest context", event_type="tool_result")

    data = json.loads(payload)
    assert data[0]["toolName"] == "cli_tool"
    assert "pytest passed" in data[0]["content"]


def test_history_tools_are_registered_for_llm_use():
    names = {tool.name for tool in create_key_tools()}

    assert {
        "history_search_tool",
        "history_fetch_tool",
        "history_timeline_tool",
        "history_checkpoint_tool",
    }.issubset(names)


def test_append_history_checkpoint_persists_hidden_checkpoint(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        build_chat_state(
            [{"role": "user", "content": "旧请求"}],
            conversation_id="session-checkpoint",
            title="测试会话",
        ),
    )
    monkeypatch.setattr(conversation_history_tools, "PROJECT_ROOT", tmp_path)

    written = conversation_history_tools.append_history_checkpoint(
        session_id="session-checkpoint",
        summary="旧阶段已经归纳为检查点。",
        reason="context_limit",
    )
    payload = conversation_history_tools.load_chat_state(tmp_path)
    messages = payload["conversations"][0]["messages"]

    assert written is True
    assert messages[-1]["metadata"]["kind"] == EVENT_CHECKPOINT
    assert messages[-1]["content"] == "旧阶段已经归纳为检查点。"
    assert session_service._normalize_messages("session-checkpoint", messages) == [
        {
            "id": "session-checkpoint-message-1",
            "role": "user",
            "content": "旧请求",
            "timestamp": messages[0]["timestamp"],
        }
    ]


def test_run_session_turn_seeds_bounded_assembled_history(tmp_path, monkeypatch):
    messages = []
    for index in range(10):
        messages.append({"role": "user", "content": f"历史用户 {index}"})
        messages.append({"role": "assistant", "content": f"历史回答 {index}"})
    messages.append({"role": "user", "content": "当前请求"})
    save_chat_state(
        tmp_path,
        build_chat_state(messages, conversation_id="session-run", title="测试会话"),
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, list[dict[str, str]]] = {}

    class DummyAgent:
        def seed_chat_history(self, seeded_messages):
            captured["history"] = list(seeded_messages)

        def run_single_turn(self, initial_prompt=None, **_kwargs):
            return {
                "status": "completed",
                "summary": "完成",
                "raw_output": "完成",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "_create_chat_agent_for_session", lambda *_args, **_kwargs: DummyAgent())

    session_service._run_session_turn(
        {
            "session_id": "session-run",
            "user_message": "当前请求",
            "history_messages": messages,
            "mental_model_enabled": False,
            "active_task": None,
        }
    )

    seeded_contents = [str(item.get("content") or "") for item in captured["history"]]
    assert "历史用户 0" not in seeded_contents
    assert "历史回答 9" in seeded_contents
    assert "当前请求" in seeded_contents
    assert len(captured["history"]) <= 8
