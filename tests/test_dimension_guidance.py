# -*- coding: utf-8 -*-
"""Tests for the dimension-guidance pure computation layer."""

from __future__ import annotations

from core.research.competition.dimension_guidance import (
    GUIDANCE_CAUTION,
    GUIDANCE_EMPHASIZE,
    GUIDANCE_INSUFFICIENT,
    GUIDANCE_NEUTRAL,
    build_dimension_guidance,
)


def _stats(n: int, improved: int, harmed: int, delta: float) -> dict:
    return {
        "critique_count": n,
        "improved_count": improved,
        "harmed_count": harmed,
        "mean_delta": delta,
    }


def test_classification_boundaries() -> None:
    report = build_dimension_guidance(
        {
            "goodDim": _stats(5, 4, 1, 0.12),
            "badDim": _stats(5, 1, 3, -0.02),
            "flatDim": _stats(5, 2, 2, 0.0),
            "tinyDim": _stats(2, 2, 0, 0.5),
        }
    )
    by_name = {item.dimension: item.guidance for item in report.dimensions}
    assert by_name["goodDim"] == GUIDANCE_EMPHASIZE
    assert by_name["badDim"] == GUIDANCE_CAUTION
    assert by_name["flatDim"] == GUIDANCE_NEUTRAL
    assert by_name["tinyDim"] == GUIDANCE_INSUFFICIENT


def test_hint_lists_emphasize_and_caution_in_sorted_order() -> None:
    report = build_dimension_guidance(
        {
            "zeta": _stats(4, 4, 0, 0.2),
            "alpha": _stats(4, 0, 3, -0.1),
        }
    )
    hint = report.guidance_hint
    assert "重点强化 zeta" in hint
    assert "谨慎处理 alpha" in hint
    assert hint.index("重点强化") < hint.index("谨慎处理")


def test_zero_mean_delta_with_harm_is_caution() -> None:
    report = build_dimension_guidance({"dim": _stats(4, 1, 3, 0.0)})
    assert report.dimensions[0].guidance == GUIDANCE_NEUTRAL  # 均值恰 0 不判 caution


def test_negative_delta_without_harm_is_neutral() -> None:
    report = build_dimension_guidance({"dim": _stats(4, 0, 0, -0.05)})
    assert report.dimensions[0].guidance == GUIDANCE_NEUTRAL


def test_min_samples_gate() -> None:
    report = build_dimension_guidance(
        {"dim": _stats(3, 3, 0, 0.5)}, min_samples=3
    )
    assert report.dimensions[0].guidance == GUIDANCE_EMPHASIZE
    report = build_dimension_guidance(
        {"dim": _stats(2, 2, 0, 0.5)}, min_samples=3
    )
    assert report.dimensions[0].guidance == GUIDANCE_INSUFFICIENT


def test_empty_input_and_tolerant_fields() -> None:
    empty = build_dimension_guidance({})
    assert empty.dimensions == ()
    assert "中性" in empty.guidance_hint
    tolerant = build_dimension_guidance(
        {"dim": {"critique_count": "4", "mean_delta": "0.1"}, "": _stats(9, 9, 0, 9.0)}
    )
    assert len(tolerant.dimensions) == 1
    assert tolerant.dimensions[0].sample_count == 4
    assert tolerant.dimensions[0].guidance == GUIDANCE_NEUTRAL  # improved=0


def test_deterministic_ordering_and_asdict() -> None:
    payload = {"b": _stats(4, 4, 0, 0.1), "a": _stats(4, 0, 2, -0.1)}
    first = build_dimension_guidance(payload)
    second = build_dimension_guidance(payload)
    assert first == second
    assert [item.dimension for item in first.dimensions] == ["a", "b"]
    as_dict = first.as_dict()
    assert as_dict["generatedFrom"] == 8
    assert [d["dimension"] for d in as_dict["dimensions"]] == ["a", "b"]
