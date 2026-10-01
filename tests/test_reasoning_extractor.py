from __future__ import annotations

from core.llm.reasoning_extractor import (
    ThinkTagStreamParser,
    extract_reasoning_details_text,
    extract_reasoning_text,
    extract_think_tag_reasoning,
    extract_thinking_blocks_text,
    strip_think_tag_reasoning,
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


def test_stream_delta_reasoning_content_preserves_boundary_whitespace():
    # OpenAI-compatible relays (DeepSeek family) stream reasoning in
    # `reasoning_content`; stripping each chunk's boundary whitespace eats
    # the reassembled stream's inter-word spaces (despaced-thinking defect).
    extracted = extract_reasoning_text(
        {"reasoning_content": " wants to find"},
        _text,
        include_content_tags=False,
        is_stream_delta=True,
    )

    assert extracted.text == " wants to find"
    assert extracted.source == "reasoning_content"


def test_stream_delta_preserves_whitespace_for_all_reasoning_field_candidates():
    extracted = extract_reasoning_text(
        {"additional_kwargs": {"reasoning": " me", "thinking": " ", "thought": "now"}},
        _text,
        include_content_tags=False,
        is_stream_delta=True,
    )

    assert extracted.text == " me"
    assert extracted.source == "additional_kwargs.reasoning"


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


# ---------------------------------------------------------------------------
# Mismatched / unclosed think forms: the answer body must never be routed to
# the reasoning channel by a wrong-name close tag or a stray open tag.
# ---------------------------------------------------------------------------


def test_complete_think_block_extraction_is_unchanged():
    assert extract_think_tag_reasoning("<think>想法</think>答案") == "想法"
    assert strip_think_tag_reasoning("<think>想法</think>答案", _text) == "答案"


def test_mismatched_close_routes_only_block_body_to_reasoning():
    content = "<think>secret plan</summary>这是用户应该看到的答案"
    assert extract_think_tag_reasoning(content) == "secret plan"
    assert strip_think_tag_reasoning(content, _text) == "这是用户应该看到的答案"

    extracted = extract_reasoning_text({"content": content}, _text)
    assert extracted.source == "think_tag"
    assert extracted.text == "secret plan"
    assert "答案" not in extracted.text


def test_mismatched_close_with_empty_body_keeps_everything_visible():
    content = "<think></summary>可见答案"
    assert extract_think_tag_reasoning(content) == ""
    assert strip_think_tag_reasoning(content, _text) == "可见答案"


def test_unclosed_think_with_long_front_body_still_recovers_reasoning():
    body = "截断的真实思考内容。" * 30  # > 200 chars, opens at the front
    content = f"<think>{body}"
    assert extract_think_tag_reasoning(content) == body
    assert strip_think_tag_reasoning(content, _text) == ""


def test_unclosed_think_short_body_is_treated_as_prose():
    content = "顺便看看 <think> 这个标签写法"
    assert extract_think_tag_reasoning(content) == ""
    assert strip_think_tag_reasoning(content, _text) == "顺便看看  这个标签写法"


def test_stream_parser_mismatched_close_demotes_remainder_to_visible():
    parser = ThinkTagStreamParser()
    first = parser.feed("<think>secret plan", _text)
    assert first.reasoning_text == "secret plan"
    assert first.visible_text == ""

    second = parser.feed("</summary>这是答案正文", _text)
    assert second.reasoning_text == ""
    assert second.visible_text == "这是答案正文"

    third = parser.feed("，继续可见。", _text)
    assert third.visible_text == "，继续可见。"
    flushed = parser.flush()
    assert flushed.reasoning_text == ""
    assert flushed.visible_text == ""


def test_stream_parser_foreign_close_split_across_chunks():
    parser = ThinkTagStreamParser()
    first = parser.feed("<think>想法</summ", _text)
    assert first.reasoning_text == "想法"
    second = parser.feed("ary>答案", _text)
    assert second.reasoning_text == ""
    assert second.visible_text == "答案"


def test_stream_parser_think_tag_split_across_chunks():
    parser = ThinkTagStreamParser()
    first = parser.feed("<thi", _text)
    assert first.reasoning_text == "" and first.visible_text == ""
    second = parser.feed("nk>思考</think>回答", _text)
    assert second.reasoning_text == "思考"
    assert second.visible_text == "回答"


def test_stream_parser_unclosed_block_flush_demotes_residue_to_visible():
    parser = ThinkTagStreamParser()
    fed = parser.feed("<think>abc", _text)
    assert fed.reasoning_text == "abc"
    # Stream cut mid-tag: the partial-tag residue would previously be emitted
    # as reasoning (or dropped); it now demotes to visible content.
    parser.feed("<thi", _text)
    flushed = parser.flush()
    assert flushed.reasoning_text == ""
    assert flushed.visible_text == "<thi"


def test_stream_parser_normal_think_extraction_regression():
    parser = ThinkTagStreamParser()
    first = parser.feed("<think> 思考过程 </think>", _text)
    assert first.reasoning_text == " 思考过程 "
    assert first.visible_text == ""
    second = parser.feed("最终答案", _text)
    assert second.reasoning_text == ""
    assert second.visible_text == "最终答案"
