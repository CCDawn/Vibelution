"""Finding prompts require balanced, traceable evidence discovery."""

from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
    stage_writeback_prompt_lines,
)


def test_finding_prompt_requires_counter_search_without_fabrication() -> None:
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "mechanism" in prompt
    assert "independent_baseline" in prompt
    assert "limitation_or_null" in prompt
    assert "falsification" in prompt
    assert "result.searchTrace[]" in prompt
    assert "status=found/no_credible_source" in prompt
    assert "status=needs_review" in prompt
    assert "不得伪造负面资料" in prompt


def test_unknown_stage_has_no_extra_writeback_contract() -> None:
    assert stage_writeback_prompt_lines("unknown") == []
