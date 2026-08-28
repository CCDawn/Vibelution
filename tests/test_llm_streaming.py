# -*- coding: utf-8 -*-
"""Streaming tool-call id hygiene: duplicate and empty ids inside one response."""

from __future__ import annotations

from core.llm.streaming import (
    LiteLLMStreamNormalizer,
    ToolCallAccumulator,
    extract_message_tool_calls,
    parse_tool_arguments,
    parse_tool_arguments_checked,
)


def test_accumulator_renames_duplicate_ids_within_one_response():
    accumulator = ToolCallAccumulator()
    accumulator.add_deltas(
        [
            {"index": 0, "id": "call_same", "function": {"name": "cli_tool", "arguments": "{\"command\":\"first\"}"}},
            {"index": 1, "id": "call_same", "function": {"name": "cli_tool", "arguments": "{\"command\":\"again\"}"}},
        ]
    )

    calls = accumulator.final_calls()

    assert [call.id for call in calls] == ["call_same", "call_same-dup-1"]
    assert [call.name for call in calls] == ["cli_tool", "cli_tool"]
    assert calls[0].arguments == {"command": "first"}
    assert calls[1].arguments == {"command": "again"}
    # The provider payload keeps the renamed id in sync for downstream pairing.
    assert calls[1].provider_payload["id"] == "call_same-dup-1"


def test_accumulator_fills_deterministic_ids_for_empty_ids():
    accumulator = ToolCallAccumulator()
    accumulator.add_deltas(
        [
            {"index": 0, "function": {"name": "tool_a", "arguments": "{}"}},
            {"index": 1, "function": {"name": "tool_b", "arguments": "{}"}},
        ]
    )

    calls = accumulator.final_calls()

    assert [call.id for call in calls] == ["tool_0", "tool_1"]


def test_extract_message_tool_calls_dedupes_duplicate_and_empty_ids():
    calls = extract_message_tool_calls(
        {
            "tool_calls": [
                {"id": "call_same", "type": "function", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "call_same", "type": "function", "function": {"name": "tool_b", "arguments": "{}"}},
                {"id": "", "type": "function", "function": {"name": "tool_c", "arguments": "{}"}},
            ]
        }
    )

    assert [call.id for call in calls] == ["call_same", "call_same-dup-1", "tool_2"]
    assert calls[1].provider_payload["id"] == "call_same-dup-1"


def test_stream_normalizer_emits_deduped_tool_call_final_ids():
    normalizer = LiteLLMStreamNormalizer()
    events = list(
        normalizer.events(
            [
                {"choices": [{"delta": {"content": ""}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "id": "call_same", "function": {"name": "cli_tool", "arguments": ""}}
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 1,
                                        "id": "call_same",
                                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"again\"}"},
                                    }
                                ]
                            }
                        }
                    ]
                },
            ]
        )
    )

    final_events = [event for event in events if event.type == "tool_call_final"]
    assert len(final_events) == 1
    assert [call.id for call in final_events[0].tool_calls] == ["call_same", "call_same-dup-1"]


def test_parse_tool_arguments_truncated_json_reports_unparsable():
    parsed, unparsable = parse_tool_arguments_checked('{"teamId": "research-team", "res')

    assert parsed == {}
    assert unparsable is True
    # Legacy helper keeps returning an empty mapping placeholder.
    assert parse_tool_arguments('{"teamId": "research-team", "res') == {}


def test_parse_tool_arguments_empty_string_is_valid_no_arguments():
    parsed, unparsable = parse_tool_arguments_checked("")

    assert parsed == {}
    assert unparsable is False


def test_parse_tool_arguments_valid_json_object_parses_normally():
    parsed, unparsable = parse_tool_arguments_checked('{"teamId": "research-team"}')

    assert parsed == {"teamId": "research-team"}
    assert unparsable is False


def test_parse_tool_arguments_non_object_json_reports_unparsable():
    for raw in ('["a"]', "123", '"text"'):
        parsed, unparsable = parse_tool_arguments_checked(raw)

        assert parsed == {}
        assert unparsable is True


def test_accumulator_marks_truncated_arguments_and_keeps_raw_text():
    accumulator = ToolCallAccumulator()
    accumulator.add_deltas(
        [
            {"index": 0, "id": "call-1", "function": {"name": "writeback", "arguments": '{"teamId": "research-'}},
            {"index": 0, "function": {"arguments": 'team", "res'}},
        ]
    )

    calls = accumulator.final_calls()

    assert len(calls) == 1
    call = calls[0]
    assert call.id == "call-1"
    assert call.name == "writeback"
    # Empty mapping placeholder only; raw text is preserved for diagnostics.
    assert call.arguments == {}
    assert call.raw_arguments == '{"teamId": "research-team", "res'
    assert call.arguments_unparsable is True
    assert call.provider_payload["function"]["arguments"] == '{"teamId": "research-team", "res'


def test_accumulator_complete_arguments_are_not_marked_unparsable():
    accumulator = ToolCallAccumulator()
    accumulator.add_deltas(
        [
            {"index": 0, "id": "call-ok", "function": {"name": "lookup", "arguments": '{"q": "x"}'}},
            {"index": 1, "id": "call-noargs", "function": {"name": "ping", "arguments": ""}},
        ]
    )

    calls = accumulator.final_calls()

    assert calls[0].arguments == {"q": "x"}
    assert calls[0].arguments_unparsable is False
    assert calls[1].arguments == {}
    assert calls[1].arguments_unparsable is False
