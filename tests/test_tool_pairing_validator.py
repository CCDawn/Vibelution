from config import Settings
from core.llm.payload_validator import validate_payload_against_protocol, validate_tool_result_pairing
from core.llm.protocol_resolver import resolve_model_protocol


def _route():
    config = Settings(
        None,
        **{
            "llm.providers.openai_main.kind": "openai_compatible",
            "llm.providers.openai_main.base_url": "https://example.test/v1",
            "llm.profiles.primary.provider_id": "openai_main",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.transport": "chat_completions",
        },
    ).config
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    return resolve_model_protocol(profile, provider)


def test_tool_result_pairing_accepts_complete_chain():
    result = validate_tool_result_pairing(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "read_file_tool", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file content"},
            {"role": "user", "content": "继续"},
        ]
    )

    assert result.ok is True


def test_tool_result_pairing_blocks_orphan_tool_result():
    result = validate_tool_result_pairing(
        [{"role": "tool", "tool_call_id": "missing", "content": "orphan"}]
    )

    assert result.ok is False
    assert result.error_type == "orphan_tool_result"


def test_tool_result_pairing_blocks_missing_result_before_user_message():
    result = validate_tool_result_pairing(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "read_file_tool", "arguments": "{}"}}
                ],
            },
            {"role": "user", "content": "继续"},
        ]
    )

    assert result.ok is False
    assert result.error_type == "missing_tool_result"
    assert result.details["pendingToolCallIds"] == ["call_1"]


def test_payload_protocol_validation_blocks_duplicate_tool_call_id():
    payload = {
        "model": "openai/gpt-4o",
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "dup", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "dup", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "dup", "content": "a result"},
        ],
    }

    result = validate_payload_against_protocol(payload, _route())

    assert result.ok is False
    assert result.error_type == "duplicate_tool_call_id"


def _merged_tool_result_payload() -> dict:
    return {
        "model": "openai/qwen3.6-plus",
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                    {"id": "call_3", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                ],
            },
            {
                "role": "tool",
                "content": [
                    {"type": "text", "text": "result-1", "tool_call_id": "call_1"},
                    {"type": "text", "text": "result-2", "tool_call_id": "call_2"},
                    {
                        "type": "text",
                        "text": "result-3",
                        "tool_call_id": "call_3",
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
            },
            {"role": "user", "content": "继续"},
        ],
    }


def test_tool_result_pairing_accepts_merged_tool_result_blocks():
    result = validate_payload_against_protocol(_merged_tool_result_payload(), _route())

    assert result.ok is True


def test_tool_result_pairing_blocks_merged_block_missing_tool_call_id():
    payload = _merged_tool_result_payload()
    payload["messages"][1]["content"][1] = {"type": "text", "text": "result-2"}

    result = validate_payload_against_protocol(payload, _route())

    assert result.ok is False
    assert result.error_type == "tool_result_missing_id"


def test_tool_result_pairing_blocks_merged_orphan_tool_result_block():
    payload = _merged_tool_result_payload()
    payload["messages"][1]["content"][2]["tool_call_id"] = "unknown_call"

    result = validate_payload_against_protocol(payload, _route())

    assert result.ok is False
    assert result.error_type == "orphan_tool_result"


def test_tool_result_pairing_blocks_merged_duplicate_tool_result_block():
    payload = _merged_tool_result_payload()
    payload["messages"][1]["content"][2]["tool_call_id"] = "call_1"

    result = validate_payload_against_protocol(payload, _route())

    assert result.ok is False
    assert result.error_type == "duplicate_tool_result"


def test_tool_result_pairing_blocks_partial_merged_tool_result():
    payload = _merged_tool_result_payload()
    payload["messages"][1]["content"] = payload["messages"][1]["content"][:2]

    result = validate_payload_against_protocol(payload, _route())

    assert result.ok is False
    assert result.error_type == "missing_tool_result"
    assert result.details["pendingToolCallIds"] == ["call_3"]
