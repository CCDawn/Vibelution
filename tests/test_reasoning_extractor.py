from __future__ import annotations

from core.llm.reasoning_extractor import (
    extract_reasoning_details_text,
    extract_reasoning_text,
    extract_thinking_blocks_text,
)


def _text(value):
    return "" if value is None else str(value)


def test_reasoning_delta_preserves_token_boundary_spaces():
    extracted = extract_reasoning_text(
        {"additional_kwargs": {"reasoning_content_delta": " me"}},
        _text,
        include_content_tags=False,
    )

    assert extracted.text == " me"
    assert extracted.source == "additional_kwargs.reasoning_content_delta"


def test_complete_reasoning_still_trims_outer_whitespace():
    extracted = extract_reasoning_text(
        {"additional_kwargs": {"reasoning_content": " done "}},
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "done"
    assert extracted.source == "additional_kwargs.reasoning_content"


def test_reasoning_details_joins_text_items_in_arrival_order():
    extracted = extract_reasoning_text(
        {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "先看"},
                {"type": "reasoning.text", "text": "日志"},
            ]
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "先看日志"
    assert extracted.source == "reasoning_details"


def test_reasoning_details_uses_summary_when_no_text_items():
    extracted = extract_reasoning_text(
        {
            "reasoning_details": [
                {"type": "reasoning.summary", "summary": "摘要一"},
                {"type": "reasoning.summary", "summary": "摘要二"},
            ]
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "摘要一摘要二"
    assert extracted.source == "reasoning_details"


def test_reasoning_details_skips_encrypted_and_unknown_types():
    extracted = extract_reasoning_text(
        {
            "reasoning_details": [
                {"type": "reasoning.encrypted", "data": "bm9w"},
                {"type": "reasoning.something_new", "text": "未约定"},
                {"type": "reasoning.text", "text": "可见思考"},
            ]
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "可见思考"
    assert extracted.source == "reasoning_details"


def test_reasoning_details_empty_array_falls_back_to_string_keys():
    extracted = extract_reasoning_text(
        {"reasoning_details": [], "reasoning_content": "字符串思考"},
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "字符串思考"
    assert extracted.source == "reasoning_content"


def test_reasoning_details_in_additional_kwargs_beat_top_level_string_keys():
    extracted = extract_reasoning_text(
        {
            "reasoning_content": "顶层字符串",
            "additional_kwargs": {
                "reasoning_details": [{"type": "reasoning.text", "text": "结构化思考"}],
            },
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "结构化思考"
    assert extracted.source == "additional_kwargs.reasoning_details"


def test_reasoning_details_win_over_reasoning_content_in_same_payload():
    extracted = extract_reasoning_text(
        {
            "reasoning_content": "字符串思考",
            "reasoning_details": [{"type": "reasoning.text", "text": "结构化思考"}],
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "结构化思考"
    assert extracted.source == "reasoning_details"


def test_thinking_blocks_fallback_after_string_candidates_miss():
    extracted = extract_reasoning_text(
        {
            "thinking_blocks": [
                {"type": "thinking", "thinking": "块思考", "signature": "sig"},
                {"type": "text", "text": "非思考"},
            ]
        },
        _text,
        include_content_tags=False,
    )

    assert extracted.text == "块思考"
    assert extracted.source == "thinking_blocks"


def test_extract_reasoning_details_text_handles_raw_shapes():
    assert (
        extract_reasoning_details_text(
            [
                {"type": "reasoning.text", "text": "a"},
                {"type": "reasoning.encrypted", "data": "x"},
                {"type": "reasoning.text", "text": "b"},
            ]
        )
        == "ab"
    )
    assert extract_reasoning_details_text({"reasoning_details": [{"type": "reasoning.summary", "summary": "s"}]}) == "s"
    assert extract_reasoning_details_text(None) == ""
    assert extract_reasoning_details_text("not-a-list") == ""
    assert extract_reasoning_details_text([{"type": "reasoning.text", "text": "a"}, "garbage"]) == "a"


def test_extract_thinking_blocks_text_joins_thinking_fields():
    assert (
        extract_thinking_blocks_text(
            [
                {"type": "thinking", "thinking": "x"},
                {"type": "thinking", "thinking": "y"},
                {"type": "redacted_thinking", "data": "z"},
            ]
        )
        == "xy"
    )
    assert extract_thinking_blocks_text(None) == ""
