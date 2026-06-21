# -*- coding: utf-8 -*-

from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage

from core.chat.context_assembler import assemble_conversation_context
from core.chat.history_ledger import (
    EVENT_CHECKPOINT,
    build_checkpoint_message,
    build_history_events,
    search_history_events,
)
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_context_compression_checkpoint,
    append_conversation_event,
    load_conversation_events,
)
from core.chat.tool_result_replacement import replace_large_tool_results_for_compression
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


def test_history_ledger_indexes_canonical_role_tool_results():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_read",
                    "type": "function",
                    "function": {"name": "read_file_tool", "arguments": "{\"path\":\"agent.py\"}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_read",
            "content": "完整工具结果：agent.py 已读取",
            "metadata": {"toolName": "read_file_tool", "toolStatus": "done"},
        },
    ]

    events = build_history_events(messages, session_id="session-canonical")
    matches = search_history_events(events, query="完整工具结果", event_type="tool_result")

    assert len(matches) == 1
    assert matches[0].tool_name == "read_file_tool"
    assert matches[0].tool_call_id == "call_read"
    assert matches[0].status == "done"
    assert "agent.py 已读取" in matches[0].content


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
    assert not any(item.get("tool_calls") for item in assembled.history_messages)
    assert not any(item.get("role") == "tool" for item in assembled.history_messages)
    tool_summary = next(item for item in assembled.history_messages if "历史工具结果: cli_tool" in str(item.get("content") or ""))

    assert full_result.strip() in tool_summary["content"]
    assert "terminal-line\n" * 20 in tool_summary["content"]
    assert "Windows detected" not in tool_summary["content"]


def test_context_hash_tracks_canonical_tool_call_identity():
    base_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "read_file_tool", "arguments": "{\"path\":\"agent.py\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "same result"},
    ]
    changed_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "read_file_tool", "arguments": "{\"path\":\"agent.py\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_b", "content": "same result"},
    ]

    base = assemble_conversation_context(base_messages, session_id="session-a", recent_message_limit=4)
    changed = assemble_conversation_context(changed_messages, session_id="session-a", recent_message_limit=4)

    assert base.dynamic_context_hash != changed.dynamic_context_hash


def test_context_assembler_replaces_large_tool_results_only_for_compression():
    large_result = "terminal-line\n" * 700
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_large",
                    "type": "function",
                    "function": {"name": "cli_tool", "arguments": "{\"command\":\"pytest -q\"}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_large",
            "content": large_result,
            "metadata": {"toolName": "cli_tool", "toolStatus": "failed"},
        },
    ]

    normal = assemble_conversation_context(messages, session_id="session-a", recent_message_limit=4)
    normal_tool = next(
        item for item in normal.history_messages if "历史工具结果: cli_tool" in str(item.get("content") or "")
    )
    assert normal_tool["role"] == "assistant"
    assert large_result.strip() in normal_tool["content"]
    assert normal.tool_result_replacement_state["replacements"] == []

    compressed = assemble_conversation_context(
        messages,
        session_id="session-a",
        recent_message_limit=4,
        replace_large_tool_results_for_compression=True,
        tool_result_replacement_char_limit=200,
    )
    compressed_tool = next(
        item for item in compressed.history_messages if "历史工具结果: cli_tool" in str(item.get("content") or "")
    )

    assert large_result not in compressed_tool["content"]
    assert "tool-result-ref:" in compressed_tool["content"]
    assert "原始工具结果仍保存在会话历史" in compressed_tool["content"]
    assert compressed.tool_result_replacement_state["replacements"][0]["toolCallId"] == "call_large"
    assert compressed.tool_result_replacement_state["replacements"][0]["originalChars"] == len(large_result.strip())


def test_tool_result_replacement_handles_langchain_tool_messages():
    tool_message = ToolMessage(content="terminal-line\n" * 80, tool_call_id="call_langchain")

    replaced, state = replace_large_tool_results_for_compression(
        [tool_message],
        char_limit=120,
        session_id="session-langchain",
    )

    assert replaced[0].type == "tool"
    assert replaced[0].tool_call_id == "call_langchain"
    assert "tool-result-ref:session-langchain:call_langchain" in str(replaced[0].content)
    assert state["replacements"][0]["toolCallId"] == "call_langchain"


def test_context_assembler_replays_conversation_ledger_over_message_tail(tmp_path):
    full_result = "ledger-result-line\n" * 80
    append_conversation_event(tmp_path, "session-journal", "turn-a", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续刚才中断的修复"},
    )
    append_conversation_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"name": "cli_tool", "status": "done", "result": full_result}},
    )
    append_conversation_event(
        tmp_path,
        "session-journal",
        "turn-a",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经完成一半实现。"},
    )
    append_conversation_event(
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
        ledger_events=load_conversation_events(tmp_path, "session-journal"),
        recent_message_limit=8,
    )

    contents = [str(item.get("content") or "") for item in assembled.history_messages]
    assert "旧 messages 不应作为事实源" not in contents
    assert "继续刚才中断的修复" in contents
    assert "已经完成一半实现。" in contents
    assert any(TURN_INTERRUPTED_MARKER in content for content in contents)
    assert not any(item.get("tool_calls") for item in assembled.history_messages)
    assert not any(item.get("role") == "tool" for item in assembled.history_messages)
    tool_summary = next(item for item in assembled.history_messages if "历史工具结果: cli_tool" in str(item.get("content") or ""))
    assert full_result.strip() in tool_summary["content"]


def test_context_assembler_with_ledger_source_ignores_legacy_messages_even_when_ledger_empty():
    assembled = assemble_conversation_context(
        [
            {"role": "user", "content": "旧 messages 不允许兜底进入模型"},
            {"role": "assistant", "content": "旧回答也不允许兜底进入模型"},
        ],
        session_id="session-empty-ledger",
        ledger_events=[],
        recent_message_limit=8,
    )

    assert assembled.history_messages == []
    assert assembled.events == []
    assert any(segment.key == "conversation_ledger" for segment in assembled.segments)
    assert all(segment.source != "conversation_history_assembler" for segment in assembled.segments)


def test_context_assembler_excludes_current_turn_ledger_from_history_seed(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-previous",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "上一轮用户输入"},
        source="test",
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-previous",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "上一轮助手输出"},
        source="test",
    )
    append_conversation_event(
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
        ledger_events=load_conversation_events(tmp_path, "session-a"),
    )

    contents = [str(item.get("content") or "") for item in assembled.history_messages]
    assert "上一轮用户输入" in contents
    assert "上一轮助手输出" in contents
    assert "当前轮用户输入" not in contents


def test_context_assembler_replays_ledger_compression_checkpoint_without_current_turn_loss(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧上下文明细"},
    )
    append_context_compression_checkpoint(
        tmp_path,
        "session-compress",
        turn_id="turn-checkpoint",
        current_turn_id="turn-current",
        summary="旧上下文已压缩为 checkpoint。",
        level="standard",
        reason="context_pressure",
        before_tokens=10000,
        after_tokens=4000,
        iteration=3,
        trigger_source="auto",
    )
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-current",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "当前轮部分输出不能作为下一轮历史种子"},
    )

    assembled = assemble_conversation_context(
        [],
        session_id="session-compress",
        current_turn_id="turn-current",
        ledger_events=load_conversation_events(tmp_path, "session-compress"),
    )
    contents = "\n".join(str(item.get("content") or "") for item in assembled.history_messages)

    assert "旧上下文已压缩为 checkpoint" in contents
    assert "旧上下文明细" not in contents
    assert "当前轮部分输出不能作为下一轮历史种子" not in contents
    assert assembled.checkpoint_event_id
    assert any(segment.key == "context_compression_checkpoint" for segment in assembled.segments)


def test_session_conversation_event_append_failure_is_not_silent(monkeypatch):
    def fail_append(*args, **kwargs):
        raise OSError("ledger unavailable")

    recorded: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(session_service, "append_conversation_event", fail_append)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    with pytest.raises(OSError, match="ledger unavailable"):
        session_service._append_session_conversation_event(
            "session-a",
            "turn-a",
            EVENT_USER_MESSAGE,
            payload={"content": "必须写入 ledger"},
        )

    assert recorded
    assert recorded[0][0][2] == "conversation.ledger.append_failed"


def test_session_detail_messages_replay_ledger_before_legacy_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_conversation_event(
        tmp_path,
        "session-visible",
        "turn-ledger",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "ledger 用户事实"},
    )
    append_conversation_event(
        tmp_path,
        "session-visible",
        "turn-ledger",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "ledger 助手事实"},
    )

    messages = session_service._messages_with_live_output(
        "session-visible",
        [
            {"role": "user", "content": "旧 messages 用户内容"},
            {"role": "assistant", "content": "旧 messages 助手内容"},
        ],
    )
    contents = [str(item.get("content") or "") for item in messages]

    assert "ledger 用户事实" in contents
    assert "ledger 助手事实" in contents
    assert "旧 messages 用户内容" not in contents
    assert "旧 messages 助手内容" not in contents


def test_session_detail_without_ledger_does_not_fallback_to_legacy_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    messages = session_service._messages_with_live_output(
        "session-no-ledger",
        [
            {"role": "user", "content": "旧 messages 用户内容"},
            {"role": "assistant", "content": "旧 messages 助手内容"},
        ],
    )

    assert messages == []

def test_session_detail_live_overlay_replaces_open_ledger_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_conversation_event(
        tmp_path,
        "session-visible",
        "turn-live",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "开始执行"},
    )
    append_conversation_event(
        tmp_path,
        "session-visible",
        "turn-live",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "ledger 执行中内容"},
    )
    with session_service._SESSION_LIVE_OUTPUTS_LOCK:
        previous_live_outputs = dict(session_service._SESSION_LIVE_OUTPUTS)
        session_service._SESSION_LIVE_OUTPUTS.clear()
        session_service._SESSION_LIVE_OUTPUTS["session-visible"] = session_service.SessionLiveOutputState(
            session_id="session-visible",
            turn_id="turn-live",
            stage="running",
            content="live 执行中内容",
            updated_at="2026-06-21T00:00:00",
        )
    try:
        messages = session_service._messages_with_live_output("session-visible", [])
    finally:
        with session_service._SESSION_LIVE_OUTPUTS_LOCK:
            session_service._SESSION_LIVE_OUTPUTS.clear()
            session_service._SESSION_LIVE_OUTPUTS.update(previous_live_outputs)

    contents = [str(item.get("content") or "") for item in messages]
    assert "开始执行" in contents
    assert "live 执行中内容" in contents
    assert "ledger 执行中内容" not in contents
    assert len(
        [
            item
            for item in messages
            if item.get("role") == "assistant" and (item.get("metadata") or {}).get("turnId") == "turn-live"
        ]
    ) == 1


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

    assert paused["status"] == "needs_continue"
    assert paused["outcome"] == "progress"
    assert paused["raw_output"] == "已经完成读取，下一步准备修改。"
    assert paused["recommended_next_action"] == "继续当前会话目标并汇总已有工具结果。"
    assert paused["metadata"]["internal_auto_continue_blocked"] is True
    assert "继续完成同一个用户目标" not in str(paused)


def test_auto_continue_pause_result_without_visible_reply_needs_continue():
    result = {
        "status": "completed",
        "outcome": "needs_input",
        "tool_call_count": 3,
        "tool_trace": [{"name": "cli_tool", "status": "done", "summary": "read file"}],
    }

    paused = session_service._build_auto_continue_paused_result(result, None, 2)

    assert paused["status"] == "needs_continue"
    assert paused["outcome"] == "progress"
    assert "没有形成最终回答" in paused["raw_output"]
    assert session_service._is_session_turn_terminal(result) is False
    assert session_service._chat_turn_result_status("completed", result, stop_requested=False) == "needs_continue"


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
        append_conversation_event(
            tmp_path,
            "session-run",
            f"turn-{index}",
            EVENT_USER_MESSAGE,
            status="recorded",
            payload={"content": f"历史用户 {index}"},
        )
        append_conversation_event(
            tmp_path,
            "session-run",
            f"turn-{index}",
            EVENT_ASSISTANT_PARTIAL,
            status="completed",
            payload={"content": f"历史回答 {index}"},
        )
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
    assert "当前请求" not in seeded_contents
    assert len(captured["history"]) <= 8
