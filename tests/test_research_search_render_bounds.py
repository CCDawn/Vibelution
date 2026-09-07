"""batch_web_search renders a bounded amount of text into the model context."""

from __future__ import annotations

from tools.research_search_tools import _MAX_BATCH_RENDER_CHARS, _render_batch_result


def test_small_batches_render_every_query_intact() -> None:
    rows = [("q1", "result-1"), ("q2", "result-2")]
    text = _render_batch_result("四视角检索", rows)
    assert "## 1. q1" in text and "## 2. q2" in text
    assert "result-1" in text and "result-2" in text
    assert "[输出截断]" not in text


def test_oversized_batch_is_capped_with_explicit_notice() -> None:
    big = "x" * (_MAX_BATCH_RENDER_CHARS // 2)
    rows = [(f"query-{index}", big) for index in range(6)]
    text = _render_batch_result("四视角检索", rows)
    assert len(text) < _MAX_BATCH_RENDER_CHARS + 400
    assert "[输出截断]" in text
    assert "查询的结果未展示" in text


def test_duplicate_rows_are_deduped() -> None:
    rows = [("q1", "same-result"), ("q1", "same-result"), ("q2", "other")]
    text = _render_batch_result("四视角检索", rows)
    assert text.count("same-result") == 1
    assert "other" in text
