# -*- coding: utf-8 -*-

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from core.chat.model_messages import (
    HISTORY_TOOL_RESULT_CHAR_LIMIT,
    normalize_model_history_messages,
    normalize_provider_turn_messages,
)
from core.llm.payload_validator import validate_tool_result_pairing


def test_history_tool_calls_keep_provider_tool_chain():
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

    assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
    assert messages[1].get("tool_calls")
    assert messages[1]["tool_calls"][0]["id"] == "call_task_list"
    assert messages[2]["tool_call_id"] == "call_task_list"
    assert "已有 3 个任务完成。" in messages[2]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_history_orphan_tool_result_is_repaired_without_prose_splice():
    messages = normalize_model_history_messages(
        [
            {"role": "system", "content": "stable"},
            {
                "role": "tool",
                "tool_call_id": "call_core_context",
                "content": "A014 程听澜",
            },
            {"role": "assistant", "content": "你好，我是程听澜。"},
            {"role": "user", "content": "你好"},
        ]
    )

    roles = [message["role"] for message in messages]
    assert "system" in roles
    assert "user" in roles
    # Orphan tool results are repaired into a valid pairing or dropped safely.
    assert validate_tool_result_pairing(messages).ok
    assert any("程听澜" in str(message.get("content") or "") for message in messages)


def test_history_tool_result_keeps_provider_pairing():
    messages = normalize_model_history_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_cli",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"pytest\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_cli", "content": "All checks passed."},
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "tool"]
    assert messages[0]["tool_calls"][0]["id"] == "call_cli"
    assert messages[1]["tool_call_id"] == "call_cli"
    assert messages[1]["content"] == "All checks passed."
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_demote_partial_live_tool_chain_without_orphan_result():
    messages = normalize_provider_turn_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_ok",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"echo ok\"}"},
                    },
                    {
                        "id": "call_timeout",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"bash -c find .\"}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_ok", "content": "ok"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "assistant", "user"]
    assert "tool_calls" not in messages[0]
    assert "历史工具调用未返回结果: cli_tool" in messages[0]["content"]
    assert "历史工具结果" in messages[1]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_complete_explicitly_interrupted_parallel_chain_with_aborted_result():
    messages = normalize_provider_turn_messages(
        [
            {
                "role": "assistant",
                "content": "先完成可返回的检查。",
                "metadata": {"interrupted": True},
                "tool_calls": [
                    {
                        "id": "call_done",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"echo ok\"}"},
                    },
                    {
                        "id": "call_stopped",
                        "type": "function",
                        "function": {"name": "read_file_tool", "arguments": "{\"file_path\":\"large.log\"}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_done", "content": "ok"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "tool", "tool", "user"]
    assert messages[1]["tool_call_id"] == "call_done"
    assert messages[2]["tool_call_id"] == "call_stopped"
    assert messages[2]["content"] == "aborted"
    assert messages[2]["metadata"]["kind"] == "interrupted_tool_result"
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_complete_stopped_embedded_tool_call_with_aborted_result():
    messages = normalize_provider_turn_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "metadata": {"interrupted": True},
                "toolCalls": [
                    {
                        "id": "call_stopped",
                        "name": "code_symbol_tool",
                        "status": "stopped",
                        "arguments": {"query": "Agent"},
                    }
                ],
            }
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "tool"]
    assert messages[1]["tool_call_id"] == "call_stopped"
    assert messages[1]["content"] == "aborted"
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


def test_provider_turn_messages_demote_orphan_langchain_tool_result():
    messages = normalize_provider_turn_messages(
        [ToolMessage(content="orphan result", tool_call_id="call_orphan")]
    )

    assert [message["role"] for message in messages] == ["assistant"]
    assert "历史工具结果: unknown_tool" in messages[0]["content"]
    assert "orphan result" in messages[0]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_demote_partial_parallel_langchain_tool_chain():
    assistant = AIMessage(
        content="",
        additional_kwargs={"responsesReplayItems": [{"type": "reasoning", "id": "reasoning_partial"}]},
        tool_calls=[
            {"id": "call_ok", "name": "cli_tool", "args": {"command": "echo ok"}},
            {"id": "call_missing", "name": "read_file_tool", "args": {"file_path": "missing.txt"}},
        ],
    )
    messages = normalize_provider_turn_messages(
        [assistant, ToolMessage(content="ok", tool_call_id="call_ok")]
    )

    assert [message["role"] for message in messages] == ["assistant", "assistant"]
    assert all(isinstance(message, dict) for message in messages)
    assert "历史工具调用未返回结果: cli_tool" in messages[0]["content"]
    assert "历史工具调用未返回结果: read_file_tool" in messages[0]["content"]
    assert "历史工具结果: cli_tool" in messages[1]["content"]
    assert validate_tool_result_pairing(messages).ok


def test_provider_turn_messages_preserve_complete_langchain_pair_and_replay_metadata():
    replay_items = [{"type": "reasoning", "id": "reasoning_complete", "encrypted_content": "opaque"}]
    assistant = AIMessage(
        content="",
        additional_kwargs={"responsesReplayItems": replay_items},
        response_metadata={"response_id": "resp_complete"},
        tool_calls=[
            {"id": "call_complete", "name": "lookup_tool", "args": {"query": "moon"}},
        ],
    )
    tool = ToolMessage(
        content="The moon is Earth's natural satellite.",
        tool_call_id="call_complete",
        additional_kwargs={"replayMarker": "complete"},
    )

    messages = normalize_provider_turn_messages([assistant, tool])

    assert messages[0] is assistant
    assert messages[1] is tool
    assert assistant.additional_kwargs["responsesReplayItems"] is replay_items
    assert assistant.response_metadata["response_id"] == "resp_complete"
    assert tool.additional_kwargs["replayMarker"] == "complete"


def test_provider_turn_messages_preserve_structured_user_content_blocks():
    content = [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    messages = normalize_provider_turn_messages([{"role": "user", "content": content}])

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == content
    assert isinstance(messages[0]["content"], list)


def test_history_tool_result_bodies_are_not_prose_truncated():
    bulky = "X" * (HISTORY_TOOL_RESULT_CHAR_LIMIT * 3)
    messages = normalize_model_history_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bulky",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": bulky,
                "tool_call_id": "call_bulky",
                "metadata": {"toolName": "cli_tool"},
            },
        ]
    )

    assert [message["role"] for message in messages] == ["assistant", "tool"]
    assert messages[1]["content"] == bulky
    assert "历史工具结果已截断" not in messages[1]["content"]
    assert validate_tool_result_pairing(messages).ok


def _duplicate_id_chain():
    return [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_same",
                    "type": "function",
                    "function": {"name": "cli_tool", "arguments": "{\"command\":\"first\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_same", "content": "first result"},
        {"role": "user", "content": "继续"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_same",
                    "type": "function",
                    "function": {"name": "cli_tool", "arguments": "{\"command\":\"again\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_same", "content": "second result"},
    ]


def test_duplicate_tool_call_ids_are_renumbered_with_paired_results():
    import copy

    raw_chain = _duplicate_id_chain()
    snapshot = copy.deepcopy(raw_chain)
    messages = normalize_provider_turn_messages(raw_chain)

    # Copy-on-write: the persisted/journal-shaped input keeps its original ids.
    assert raw_chain == snapshot
    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "user", "assistant", "tool"]
    first_call_id = messages[1]["tool_calls"][0]["id"]
    second_call_id = messages[4]["tool_calls"][0]["id"]
    assert first_call_id == "call_same"
    assert second_call_id == "call_same-dedup-1"
    assert messages[2]["tool_call_id"] == first_call_id
    assert messages[5]["tool_call_id"] == second_call_id
    assert messages[2]["content"] == "first result"
    assert messages[5]["content"] == "second result"
    # Deterministic: the same input always renames to the same ids.
    assert normalize_provider_turn_messages(_duplicate_id_chain()) == messages
    # The strict pairing gate now passes on the repaired projection.
    assert validate_tool_result_pairing(messages).ok


def test_duplicate_tool_call_id_renormalization_is_idempotent():
    once = normalize_provider_turn_messages(_duplicate_id_chain())
    twice = normalize_provider_turn_messages(once)

    assert twice == once
    ids = [
        call["id"]
        for message in twice
        for call in message.get("tool_calls") or []
    ]
    assert ids == ["call_same", "call_same-dedup-1"]
    assert validate_tool_result_pairing(twice).ok


def test_duplicate_tool_call_id_renumbering_keeps_parallel_pairing_and_interrupted_metadata():
    messages = normalize_provider_turn_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "one"},
            {
                "role": "assistant",
                "content": "",
                "metadata": {"interruptedToolCallIds": ["call_a"]},
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{}"},
                    },
                    {
                        "id": "call_b",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "two"},
            {"role": "tool", "tool_call_id": "call_b", "content": "three"},
        ]
    )

    renamed_call = messages[2]["tool_calls"][0]["id"]
    assert renamed_call == "call_a-dedup-1"
    assert messages[2]["tool_calls"][1]["id"] == "call_b"
    assert messages[3]["tool_call_id"] == renamed_call
    assert messages[4]["tool_call_id"] == "call_b"
    assert messages[2]["metadata"]["interruptedToolCallIds"] == [renamed_call]
    assert validate_tool_result_pairing(messages).ok


def test_payload_validator_terminal_gate_still_rejects_unnormalized_duplicates():
    raw_chain = _duplicate_id_chain()[1:]  # drop the leading user message

    result = validate_tool_result_pairing(raw_chain)

    assert not result.ok
    assert result.error_type == "duplicate_tool_call_id"
    assert result.details["toolCallId"] == "call_same"
