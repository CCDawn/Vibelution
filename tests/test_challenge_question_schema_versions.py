from __future__ import annotations

import json

import pytest

from core.web.services.team_workflow import challenge_question_runs


V2_GROUPS = {
    "identity",
    "classification",
    "scope",
    "run",
    "problem_understanding",
    "evidence",
    "hypotheses",
    "dimension_reviews",
    "selection",
    "research_plan",
    "feedback_iterations",
    "result_classification",
    "competition_result_view",
    "collaboration_refs",
    "review",
    "submission",
    "audit",
}


def test_tracked_question_schemas_are_versioned_and_v2_has_all_frozen_groups() -> None:
    schema_v1 = json.loads(challenge_question_runs._schema_path(1).read_text(encoding="utf-8"))
    schema_v2 = json.loads(challenge_question_runs._schema_path(2).read_text(encoding="utf-8"))

    assert schema_v1["properties"]["schema_version"]["const"] == 1
    assert schema_v2["properties"]["schema_version"]["const"] == 2
    assert V2_GROUPS <= set(schema_v2["required"])
    assert "挑战杯" not in str(challenge_question_runs._schema_path(1))
    assert "挑战杯" not in str(challenge_question_runs._catalog_path())


def test_question_schema_dispatch_rejects_unknown_versions_and_v1_new_writes() -> None:
    issues = challenge_question_runs._schema_issues({"schema_version": 3})
    assert issues == [{"path": "schema_version", "message": "Unsupported challenge question schema version: 3."}]

    with pytest.raises(ValueError, match="read-only"):
        challenge_question_runs._require_writable_schema({"schema_version": 1})
    challenge_question_runs._require_writable_schema({"schema_version": 2})
