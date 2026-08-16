"""Boundary tests for ResponseProcessor not covered by agent.py protocol tests."""

from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk

from core.orchestration.response_processor import ResponseProcessor


def test_coerce_content_text_handles_none_dict_and_mixed_blocks():
    processor = ResponseProcessor()
    assert processor.coerce_content_text(None) == ""
    assert processor.coerce_content_text({"text": "hello"}) == "hello"
    assert processor.coerce_content_text([{"text": "a"}, "b", None, {"type": "image"}]) == "ab"


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
