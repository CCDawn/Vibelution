from __future__ import annotations

from core.llm.reasoning_extractor import extract_reasoning_text


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
