from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from core.chat.context_assembler import assemble_conversation_context
from core.chat.conversation_invariant import (
    FORBIDDEN_UI_TOOL_CALLS_ERROR,
    LEDGER_REWRITE_EXCEPTION_OWNERS,
    SILENT_PROVIDER_REPAIR_ERROR,
    canonical_conversation_messages_from_events,
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
    is_system_layer_message,
)
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
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
