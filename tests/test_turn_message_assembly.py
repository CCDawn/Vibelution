from langchain_core.messages import AIMessage, SystemMessage

from agent import SelfEvolvingAgent
from core.infrastructure.llm_utils import (
    build_cacheable_system_prefix_message,
    build_dynamic_system_context_message,
    extend_system_message_cacheable_prefix,
    is_dynamic_system_context_message,
)
from core.infrastructure.runtime_input import build_chat_user_message
from core.orchestration.turn_message_assembly import (
    assemble_prepared_turn_messages,
    insert_pending_volatile_context_messages,
    normalize_seeded_tool_calls,
    refresh_system_prefix_on_messages,
    sanitize_seeded_chat_content,
)
from core.orchestration.turn_outcome import TurnOutcomeController


def test_normalize_seeded_tool_calls_accepts_alias_shapes():
    normalized = normalize_seeded_tool_calls(
        [
            {"id": "call-1", "name": "read_file_tool", "args": {"path": "a.py"}},
            {
                "toolCallId": "call-2",
                "toolName": "cli_tool",
                "arguments": '{"command": "pytest"}',
            },
            {
                "tool_call_id": "call-3",
                "function": {"name": "write_file_tool", "arguments": {"path": "b.py"}},
            },
            {"name": "missing-id"},
            "skip-me",
        ]
    )

    assert normalized == [
        {"id": "call-1", "name": "read_file_tool", "args": {"path": "a.py"}},
        {"id": "call-2", "name": "cli_tool", "args": {"command": "pytest"}},
        {"id": "call-3", "name": "write_file_tool", "args": {"path": "b.py"}},
    ]


def test_sanitize_seeded_chat_content_strips_internal_protocol_from_assistant_only():
    user_text = "请继续 spawn_agent_tool"
    assert sanitize_seeded_chat_content("user", user_text) == user_text
    assert sanitize_seeded_chat_content("assistant", "Tool failed: spawn_agent_tool") == ""
    assert sanitize_seeded_chat_content("assistant", "内部 _internal_delegate 痕迹") == ""
    assert (
        sanitize_seeded_chat_content(
            "assistant",
            "[工具策略提示] `write_file_tool` 不在该 Agent 的可见工具策略中。请改用别的工具。",
        )
        == "[工具策略提示] 历史中有一次未授权工具调用已被省略。请改用别的工具。"
    )
    assert sanitize_seeded_chat_content("assistant", "正常历史结论") == "正常历史结论"


def test_agent_wrappers_share_normalize_and_sanitize_path():
    raw = [{"id": "call-1", "name": "read_file_tool", "args": {"path": "a.py"}}]
    assert SelfEvolvingAgent._normalize_seeded_tool_calls(raw) == normalize_seeded_tool_calls(raw)
    assert SelfEvolvingAgent._sanitize_seeded_chat_content(
        "assistant",
        "Tool failed: spawn_agent_tool",
    ) == sanitize_seeded_chat_content("assistant", "Tool failed: spawn_agent_tool")


def test_insert_pending_volatile_places_blocks_before_current_user():
    messages = [
        {"role": "system", "content": "system"},
        build_chat_user_message("第一句"),
        AIMessage(content="第一轮回复"),
        build_chat_user_message("第二句"),
    ]

    updated, inserted = insert_pending_volatile_context_messages(
        messages,
        ["## Slash Skill Context\nCommand: /brt"],
    )

    assert inserted == ["## Slash Skill Context\nCommand: /brt"]
    assert updated is not messages
    assert updated[1:3] == messages[1:3]
    assert isinstance(updated[3], SystemMessage)
    assert updated[3].content.startswith("## Slash Skill Context")
    assert updated[-1] == messages[-1]


def test_insert_pending_volatile_skips_blank_blocks_without_mutating_order():
    messages = [SystemMessage(content="system"), build_chat_user_message("现在")]
    updated, inserted = insert_pending_volatile_context_messages(messages, ["  ", ""])
    assert inserted == []
    assert updated == messages or list(updated) == list(messages)


def test_assemble_prepared_turn_messages_keeps_system_history_volatile_user_order():
    history = [
        SystemMessage(content="old system"),
        build_chat_user_message("第一句"),
        AIMessage(content="第一轮回复"),
    ]
    split_prompt = ("new static system", "<<<SYSTEM_PROMPT_SPLIT>>>", "new dynamic system")

    assembled = assemble_prepared_turn_messages(
        system_prompt=split_prompt,
        user_prompt="第二句",
        effective_goal="第二句",
        active_turn_messages=history,
        active_turn_goal="__chat_session__",
        build_system_message=build_cacheable_system_prefix_message,
        build_external_request_message=build_chat_user_message,
        allow_append_user_message=True,
        static_context_blocks=["## Agent Static Context\nstable"],
        runtime_context_blocks=["## Agent Runtime Context\nvolatile"],
        dynamic_system_context_message=build_dynamic_system_context_message(split_prompt),
    )

    assert assembled.resumed is True
    assert assembled.static_context_inserted is True
    assert assembled.cacheable_prefix_merged is True
    assert assembled.dynamic_system_context_inserted is True
    assert assembled.pending_runtime_context_blocks == ("## Agent Runtime Context\nvolatile",)
    assert assembled.messages[0]["content"][0]["text"].endswith("## Agent Static Context\nstable")
    assert assembled.messages[1:3] == history[1:]
    assert assembled.messages[-1]["role"] == "user"
    assert "第二句" in assembled.messages[-1]["content"]
    volatile = assembled.messages[3:-1]
    assert any(is_dynamic_system_context_message(item) for item in volatile)
    assert any(
        isinstance(item, SystemMessage) and str(item.content or "").startswith("## Agent Runtime Context")
        for item in volatile
    )


def test_assemble_falls_back_to_static_insert_when_prefix_cannot_merge():
    assembled = assemble_prepared_turn_messages(
        system_prompt="plain system",
        user_prompt="现在",
        effective_goal="现在",
        active_turn_messages=None,
        active_turn_goal="",
        build_system_message=lambda sp: SystemMessage(content=str(sp)),
        build_external_request_message=build_chat_user_message,
        allow_append_user_message=False,
        static_context_blocks=["## Agent Static Context\nstable"],
        runtime_context_blocks=[],
        dynamic_system_context_message=None,
    )

    assert assembled.resumed is False
    assert assembled.cacheable_prefix_merged is False
    assert assembled.static_context_inserted is True
    assert isinstance(assembled.messages[0], SystemMessage)
    assert assembled.messages[0].content == "plain system"
    assert isinstance(assembled.messages[1], SystemMessage)
    assert assembled.messages[1].content == "## Agent Static Context\nstable"
    assert assembled.messages[-1]["role"] == "user"


def test_refresh_system_prefix_replaces_dynamic_suffix_and_remerges_static():
    split_prompt = ("new static system", "<<<SYSTEM_PROMPT_SPLIT>>>", "new dynamic system")
    stale_dynamic = SystemMessage(content="## Dynamic System Context\nstale")
    messages = [
        SystemMessage(content="old system"),
        build_chat_user_message("第一句"),
        stale_dynamic,
        build_chat_user_message("第二句"),
    ]

    refreshed = refresh_system_prefix_on_messages(
        messages=messages,
        system_prompt=split_prompt,
        static_context_blocks=["## Agent Static Context\nstable"],
        build_cacheable_prefix_fn=build_cacheable_system_prefix_message,
        is_dynamic_system_context_fn=is_dynamic_system_context_message,
        build_dynamic_system_context_fn=build_dynamic_system_context_message,
        extend_cacheable_prefix_fn=extend_system_message_cacheable_prefix,
        insert_volatile_fn=TurnOutcomeController.insert_volatile_context_before_current_user,
    )

    assert refreshed[0]["content"][0]["text"].endswith("## Agent Static Context\nstable")
    assert refreshed[1] == messages[1]
    assert all(item is not stale_dynamic for item in refreshed)
    assert any(is_dynamic_system_context_message(item) for item in refreshed[2:-1])
    assert refreshed[-1] == messages[-1]
