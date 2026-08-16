"""Boundary tests for ResponseProcessor not covered by agent.py protocol tests."""

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk

from core.orchestration.response_processor import ResponseProcessor


def test_coerce_content_text_handles_none_dict_and_mixed_blocks():
    processor = ResponseProcessor()
    assert processor.coerce_content_text(None) == ""
    assert processor.coerce_content_text({"text": "hello"}) == "hello"
    assert processor.coerce_content_text([{"text": "a"}, "b", None, {"type": "image"}]) == "ab"


def test_coerce_content_text_decodes_bytes_and_mapping_content_key():
    processor = ResponseProcessor()
    assert processor.coerce_content_text(b"hello") == "hello"
    assert processor.coerce_content_text({"content": b"world"}) == "world"
    assert processor.coerce_content_text([{"text": b"a"}, b"b"]) == "ab"


def test_standard_tool_calls_skip_xml_fallback_even_when_invoke_is_present():
    processor = ResponseProcessor()
    preview = processor.preview(
        SimpleNamespace(
            content='visible\n<invoke name="grep_search_tool"><parameter name="query">foo</parameter></invoke>',
            tool_calls=[{"id": "c1", "name": "read_file_tool", "args": {"path": "a.py"}}],
        )
    )
    assert preview.has_tool_calls is True
    assert preview.xml_tool_calls == []


def test_preview_rejects_string_tool_calls_and_parses_json_or_mapping_payloads():
    processor = ResponseProcessor()
    invoke = '<invoke name="grep_search_tool"><parameter name="query">foo</parameter></invoke>'
    split = processor.preview(SimpleNamespace(content=invoke, tool_calls="abc"))
    assert split.has_tool_calls is False
    assert split.tool_calls == []
    assert len(split.xml_tool_calls) == 1
    assert split.xml_tool_calls[0]["name"] == "grep_search_tool"

    json_calls = processor.preview(
        {
            "content": b"visible",
            "toolCalls": json.dumps(
                [{"id": "c1", "name": "read_file_tool", "args": {"path": "a.py"}}]
            ),
        }
    )
    assert json_calls.has_tool_calls is True
    assert json_calls.raw_content == "visible"
    assert json_calls.tool_calls[0]["name"] == "read_file_tool"
    assert json_calls.xml_tool_calls == []

    single = processor.preview(
        SimpleNamespace(
            content="ok",
            tool_calls={"id": "c2", "name": "cli_tool", "args": {"command": "pytest"}},
        )
    )
    assert single.tool_call_count == 1
    assert single.tool_calls[0]["id"] == "c2"


def test_build_ai_message_parses_json_arguments_override_and_keeps_metadata():
    processor = ResponseProcessor()
    response = SimpleNamespace(
        content="done",
        tool_calls=[],
        additional_kwargs={"foo": 1},
        response_metadata={"model": "test-model"},
    )
    processed = processor.process(response)
    message = processed.build_ai_message(
        response,
        tool_calls_override=[
            {
                "id": "call-2",
                "name": "cli_tool",
                "arguments": '{"command": "pytest"}',
            }
        ],
    )
    assert message.tool_calls[0]["id"] == "call-2"
    assert message.tool_calls[0]["name"] == "cli_tool"
    assert message.tool_calls[0]["args"] == {"command": "pytest"}
    assert message.additional_kwargs == {"foo": 1}
    assert message.response_metadata == {"model": "test-model"}
    broken = processed.build_ai_message(
        response,
        tool_calls_override=[{"id": "call-3", "name": "cli_tool", "arguments": "not-json"}],
    )
    assert broken.tool_calls[0]["args"] == {}


def test_build_ai_message_coerces_bytes_ids_function_shape_and_json_override():
    processor = ResponseProcessor()
    response = SimpleNamespace(content="done", tool_calls=[])
    processed = processor.process(response)
    message = processed.build_ai_message(
        response,
        tool_calls_override=[
            {
                "toolCallId": b"call-9",
                "function": {
                    "name": b"cli_tool",
                    "arguments": b'{"command": "pytest"}',
                },
            }
        ],
    )
    assert message.tool_calls[0]["id"] == "call-9"
    assert message.tool_calls[0]["name"] == "cli_tool"
    assert message.tool_calls[0]["args"] == {"command": "pytest"}
    json_override = processed.build_ai_message(
        response,
        tool_calls_override='[{"id":"call-8","name":"cli_tool","args":{"command":"pytest"}}]',
    )
    assert json_override.tool_calls[0]["id"] == "call-8"
    ignored = processed.build_ai_message(response, tool_calls_override="not-a-list")
    assert ignored.tool_calls == []


def test_merge_stream_chunk_compacts_repeated_provider_metadata():
    first = AIMessageChunk(content="你", response_metadata={"provider": "openai"})
    second = AIMessageChunk(content="好", response_metadata={"provider": "openai"})
    merged = ResponseProcessor.merge_stream_chunk(first, second)
    assert merged.content == "你好"
    assert merged.response_metadata["provider"] == "openai"
    assert ResponseProcessor.merge_stream_chunk(None, second) is second
    assert ResponseProcessor.merge_stream_chunk(first, None) is first


def test_extract_active_components_dedupes_and_uppercases():
    components = ResponseProcessor.extract_active_components(
        "<active_components>soul soul SPEC</active_components>"
        "<active_components>spec, CODEBASE_MAP</active_components>"
    )
    assert components == ["SOUL", "SPEC", "CODEBASE_MAP"]
    assert ResponseProcessor.extract_active_components(
        b"<active_components>soul</active_components>"
    ) == ["SOUL"]


def test_preview_unwraps_tool_call_envelopes_and_json_responses():
    processor = ResponseProcessor()
    enveloped = processor.preview(
        SimpleNamespace(
            content="visible",
            tool_calls={
                "toolCalls": [{"id": "c1", "name": "read_file_tool", "args": {"path": "a.py"}}],
            },
        )
    )
    assert enveloped.has_tool_calls is True
    assert enveloped.tool_calls[0]["name"] == "read_file_tool"
    assert enveloped.xml_tool_calls == []

    json_response = processor.preview(
        b'{"content": "visible", "tool_calls": [{"id": "c2", "name": "cli_tool"}]}'
    )
    assert json_response.raw_content == "visible"
    assert json_response.tool_calls[0]["id"] == "c2"
    assert json_response.tool_calls[0]["name"] == "cli_tool"


def test_build_ai_message_parses_json_function_and_metadata_payloads():
    processor = ResponseProcessor()
    response = SimpleNamespace(
        content="done",
        tool_calls=[],
        additional_kwargs='{"foo": 1}',
        response_metadata=b'{"model": "test-model"}',
    )
    processed = processor.process(response)
    message = processed.build_ai_message(
        response,
        tool_calls_override=[
            {
                "id": "call-7",
                "function": '{"name": "cli_tool", "arguments": {"command": "pytest"}}',
            }
        ],
    )
    assert message.tool_calls[0]["id"] == "call-7"
    assert message.tool_calls[0]["name"] == "cli_tool"
    assert message.tool_calls[0]["args"] == {"command": "pytest"}
    assert message.additional_kwargs == {"foo": 1}
    assert message.response_metadata == {"model": "test-model"}


def test_coerce_content_text_parses_json_content_blocks_without_splitting_strings():
    processor = ResponseProcessor()
    assert processor.coerce_content_text(['{"text": "a"}', {"text": "b"}]) == "ab"
    assert processor.coerce_content_text("not-json") == "not-json"
    assert processor.coerce_content_text('{"text": "hello"}') == '{"text": "hello"}'
