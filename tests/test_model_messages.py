# -*- coding: utf-8 -*-

from __future__ import annotations

from core.chat.model_messages import normalize_model_history_messages, normalize_provider_turn_messages
from core.llm.payload_validator import validate_tool_result_pairing


def test_history_tool_calls_project_to_semantic_messages_not_provider_tool_role():
    messages = normalize_model_history_messages(
        [
            {"role": "user", "content": "你现在能用什么工具"},
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "id": "call_task_list",
                        "name": "task_list_tool",
                        "status": "done",
                        "summary": "已有 3 个任务完成。",
                    }
                ],
            },
        ]
    )

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert not any(message.get("role") == "tool" for message in messages)
    assert "历史工具结果" in messages[1]["content"]
    assert "task_list_tool" in messages[1]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_history_orphan_tool_result_is_demoted_to_semantic_context():
    messages = normalize_model_history_messages(
        [
            {"role": "system", "content": "stable"},
            {
                "role": "tool",
                "tool_call_id": "call_core_context",
                "content": "历史工具调用: get_core_context_tool\n状态: done\n结果:\nA014 程听澜",
            },
            {"role": "assistant", "content": "你好，我是程听澜。"},
            {"role": "user", "content": "你好"},
        ]
    )

    assert [message["role"] for message in messages] == ["system", "assistant", "assistant", "user"]
    assert "历史工具结果" in messages[1]["content"]
    assert "get_core_context_tool" in messages[1]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_preserve_valid_live_tool_pair():
    messages = normalize_provider_turn_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_live",
                        "type": "function",
                        "function": {"name": "grep_search_tool", "arguments": "{\"query\":\"abc\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_live", "content": "匹配 1 处"},
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "tool"]
    assert validate_tool_result_pairing(messages).ok

