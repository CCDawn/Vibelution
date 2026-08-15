from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from core.chat.context_assembler import assemble_conversation_context
from core.chat.conversation_invariant import (
    FORBIDDEN_UI_TOOL_CALLS_ERROR,
    LEDGER_REWRITE_EXCEPTION_OWNERS,
    SILENT_PROVIDER_REPAIR_ERROR,
    canonical_conversation_messages_from_events,
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
    is_system_layer_message,
    live_conversation_messages_from_events,
)
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_RESULT,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.orchestration.turn_message_assembly import replay_current_turn_messages
from core.llm.client import LLMClient
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    return data_home


def _client_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", True)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    kwargs.setdefault("llm.providers.default.kind", "openai_compatible")
    kwargs.setdefault("llm.providers.default.api_key", "test-key")
    kwargs.setdefault("llm.providers.default.base_url", "https://example.test/v1")
    kwargs.setdefault("llm.profiles.primary.provider_id", "default")
    kwargs.setdefault("llm.profiles.primary.model", "gpt-4o")
    return isolated_settings_config(**kwargs)


def test_rewrite_exceptions_are_named_owners():
    joined = " ".join(LEDGER_REWRITE_EXCEPTION_OWNERS)
    assert "truncate_session_ledger_before_message" in joined
    assert "chat_room_service" in joined


def test_assembled_history_fingerprint_matches_ledger_reconstruction(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-invariant",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "说明会话日志不变量"},
    )
    append_conversation_event(
        tmp_path,
        "session-invariant",
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "对话层只能从 journal 重建"},
    )
    append_conversation_event(
        tmp_path,
        "session-invariant",
        "turn-2",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "下一轮请求"},
    )
    events = load_conversation_events(tmp_path, "session-invariant")
    assembled = assemble_conversation_context(
        [],
        session_id="session-invariant",
        current_turn_id="turn-2",
        recent_message_limit=None,
        ledger_events=events,
    )
    canonical = canonical_conversation_messages_from_events(events, current_turn_id="turn-2")

    assert conversation_layer_fingerprint(assembled.history_messages) == conversation_layer_fingerprint(canonical)
    assert [item["content"] for item in canonical] == [
        "说明会话日志不变量",
        "对话层只能从 journal 重建",
    ]


def test_status_bar_is_system_layer_and_excluded_from_fingerprint():
    conversation = [
        {"role": "user", "content": "继续"},
        {"role": "assistant", "content": "好的"},
    ]
    with_status_bar = [
        *conversation,
        {"role": "system", "content": "## Turn Status Bar\niteration: 2"},
    ]
    assert is_system_layer_message(with_status_bar[-1]) is True
    assert conversation_layer_fingerprint(conversation) == conversation_layer_fingerprint(with_status_bar)


def test_invariant_rejects_ui_tool_calls_field():
    result = check_conversation_payload_invariant(
        [
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [{"name": "read_file_tool"}],
            }
        ]
    )
    assert result.ok is False
    assert result.error_type == FORBIDDEN_UI_TOOL_CALLS_ERROR
    assert result.details["forbiddenField"] == "toolCalls"


def test_llm_client_blocks_silent_orphan_tool_repair():
    client = LLMClient(config=_client_config(), backend=lambda payload: payload)
    with pytest.raises(LLMError) as exc_info:
        client._build_payload(
            [
                {
                    "role": "tool",
                    "tool_call_id": "call_orphan",
                    "content": "orphan result must not become model prose",
                },
                {"role": "user", "content": "继续"},
            ]
        )

    assert exc_info.value.category == "payload_protocol_error"
    assert exc_info.value.details["payloadValidationErrorType"] == SILENT_PROVIDER_REPAIR_ERROR
    assert exc_info.value.details["payloadValidationResult"] == "blocked_before_provider"


def test_llm_client_accepts_complete_tool_pair_with_matching_fingerprint():
    from core.chat.model_messages import ProviderMessageChain

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_ok",
                    "type": "function",
                    "function": {"name": "lookup_tool", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "content": "ok"},
        {"role": "user", "content": "继续"},
    ]
    chain = ProviderMessageChain.from_messages(messages)
    assert chain.repaired is False
    client = LLMClient(config=_client_config(), backend=lambda payload: payload)
    payload = client._build_payload(
        messages,
        metadata={
            "ledgerConversationFingerprint": conversation_layer_fingerprint(
                chain.to_provider_payload()
            )
        },
    )

    assert [message["role"] for message in payload["messages"]] == ["assistant", "tool", "user"]
    assert payload["messages"][1]["tool_call_id"] == "call_ok"


def test_llm_client_still_rejects_ui_tool_calls_before_provider():
    client = LLMClient(config=_client_config(), backend=lambda payload: payload)
    with pytest.raises(LLMError) as exc_info:
        client._build_payload(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "toolCalls": [{"name": "history_search_tool", "toolCallId": "call_history"}],
                },
                {"role": "user", "content": "继续"},
            ]
        )

    assert exc_info.value.category == "payload_protocol_error"
    assert exc_info.value.details["forbiddenField"] == "toolCalls"


def _append_current_turn_tool_journal(tmp_path, *, session_id: str, turn_id: str, result: str) -> None:
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "请读取文件"},
    )
    append_conversation_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TOOL_RESULT,
        status="done",
        payload={
            "toolCall": {
                "id": "call_live",
                "name": "read_file_tool",
                "status": "done",
                "result": result,
            }
        },
        tool_call_id="call_live",
    )


def test_live_reconstruction_includes_current_turn_tool_pair(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "历史请求"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "历史回复"},
    )
    _append_current_turn_tool_journal(
        tmp_path,
        session_id="session-live",
        turn_id="turn-2",
        result="journal-tool-result",
    )
    events = load_conversation_events(tmp_path, "session-live")
    historical = canonical_conversation_messages_from_events(events, current_turn_id="turn-2")
    live = live_conversation_messages_from_events(events, turn_id="turn-2")

    assert [item["content"] for item in historical] == ["历史请求", "历史回复"]
    assert [item["role"] for item in live] == ["user", "assistant", "tool"]
    assert live[0]["content"] == "请读取文件"
    assert live[2]["tool_call_id"] == "call_live"
    assert "journal-tool-result" in live[2]["content"]


def test_replay_replaces_in_memory_tool_chain_from_journal_and_keeps_system_prefix(tmp_path):
    _append_current_turn_tool_journal(
        tmp_path,
        session_id="session-replay",
        turn_id="turn-live",
        result="journal-tool-result",
    )
    events = load_conversation_events(tmp_path, "session-replay")
    live = live_conversation_messages_from_events(events, turn_id="turn-live")
    messages = [
        SystemMessage(content="cacheable system prefix"),
        {"role": "user", "content": "## Chat User Message\n请读取文件"},
        AIMessage(
            content="",
            tool_calls=[{"id": "call_live", "name": "read_file_tool", "args": {}}],
        ),
        ToolMessage(content="memory-only-result", tool_call_id="call_live"),
        {"role": "system", "content": "## Turn Status Bar\niteration: 2"},
    ]

    replayed = replay_current_turn_messages(messages, events, turn_id="turn-live")
    continuation = conversation_layer_messages_from_last_assistant(replayed)

    assert str(replayed[0].content) == "cacheable system prefix"
    assert replayed[1]["content"] == "## Chat User Message\n请读取文件"
    assert all("Turn Status Bar" not in _message_content(item) for item in replayed)
    assert conversation_layer_fingerprint(continuation) == conversation_layer_fingerprint(live[1:])
    assert "memory-only-result" not in "\n".join(_message_content(item) for item in replayed)
    assert any("journal-tool-result" in _message_content(item) for item in replayed)
    assert check_conversation_payload_invariant(replayed).ok is True


def test_replay_is_noop_when_current_turn_has_only_user(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-seed",
        "turn-live",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "请读取文件"},
    )
    events = load_conversation_events(tmp_path, "session-seed")
    original = [
        SystemMessage(content="prefix"),
        {"role": "user", "content": "## Chat User Message\n请读取文件"},
    ]
    replayed = replay_current_turn_messages(original, events, turn_id="turn-live")
    assert replayed == original


def conversation_layer_messages_from_last_assistant(messages):
    from core.chat.conversation_invariant import conversation_layer_messages

    layer = conversation_layer_messages(messages)
    start = 0
    for index, item in enumerate(layer):
        role = item.get("role") if isinstance(item, dict) else getattr(item, "type", "")
        if str(role or "").strip().lower() in {"assistant", "ai"}:
            start = index
            break
    return layer[start:]


def _message_content(message) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    return str(content or "")
