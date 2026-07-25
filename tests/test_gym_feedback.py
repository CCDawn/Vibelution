#!/usr/bin/env python3
"""Deterministic feedback derivation contracts for supervised evolution."""

import pytest

from core.gym import (
    Attempt,
    OptimizationContractError,
    Score,
    Trace,
    build_reflective_feedback,
)


def _attempt(
    *,
    attempt_id: str,
    trace_id: str,
    success: bool,
    validation=None,
    tool_errors: int = 0,
    regression_risk: float = 0.0,
    safety_risk: float = 0.0,
    dataset_splits=None,
) -> Attempt:
    return Attempt(
        attempt_id=attempt_id,
        case_id="case:feedback",
        agent_version="vibelution-agent@test",
        trace_id=trace_id,
        score=Score(
            success=success,
            validation=validation or {},
            tool_errors=tool_errors,
            regression_risk=regression_risk,
            safety_risk=safety_risk,
        ),
        dataset_splits=dataset_splits or ["train"],
    )


def test_feedback_is_deterministic_and_keeps_only_bounded_trace_evidence():
    failed = _attempt(
        attempt_id="attempt:failed",
        trace_id="trace:failed",
        success=False,
        validation={"failed": 1},
        tool_errors=2,
    )
    passed = _attempt(attempt_id="attempt:passed", trace_id="trace:passed", success=True)
    traces = [
        Trace(
            trace_id="trace:failed",
            case_id="case:feedback",
            events=[{"type": "generic_case_result", "user_prompt": "must not escape"}],
            artifacts={"artifact_ref": "traces/failed.json"},
        ),
        Trace(
            trace_id="trace:passed",
            case_id="case:feedback",
            artifacts={"artifact_ref": "traces/passed.json"},
        ),
    ]

    left = build_reflective_feedback(
        episode_id="episode:feedback",
        attempts=[failed, passed],
        traces=traces,
    )
    right = build_reflective_feedback(
        episode_id="episode:feedback",
        attempts=[passed, failed],
        traces=list(reversed(traces)),
    )

    assert left.to_dict() == right.to_dict()
    assert left.trace_refs == ["traces/failed.json", "traces/passed.json"]
    assert left.failure_taxonomy == ["tool_error", "validation_failure"]
    assert left.target_components == ["agent_tool_policy", "validation_contract"]
    assert left.successful_patterns == ["validated_success"]
    assert "must not escape" not in str(left.to_dict())


def test_environment_failure_is_classified_without_agent_mutation_lesson():
    attempt = _attempt(
        attempt_id="attempt:environment",
        trace_id="trace:environment",
        success=False,
        validation={"environment_unavailable": True},
    )
    trace = Trace(
        trace_id="trace:environment",
        case_id="case:feedback",
        events=[{"type": "harness_result", "status": "environment_unavailable"}],
        artifacts={"artifact_ref": "traces/environment.json"},
    )

    feedback = build_reflective_feedback(
        episode_id="episode:feedback",
        attempts=[attempt],
        traces=[trace],
    )

    assert feedback.failure_taxonomy == ["environment_unavailable"]
    assert feedback.actionable_lessons == []
    assert feedback.target_components == []
    assert feedback.confidence == 0.7


def test_feedback_rejects_holdout_evidence_and_missing_traces():
    holdout = _attempt(
        attempt_id="attempt:holdout",
        trace_id="trace:holdout",
        success=True,
        dataset_splits=["holdout"],
    )

    with pytest.raises(OptimizationContractError, match="holdout"):
        build_reflective_feedback(
            episode_id="episode:feedback",
            attempts=[holdout],
            traces=[Trace(trace_id="trace:holdout", case_id="case:feedback")],
        )

    with pytest.raises(OptimizationContractError, match="missing trace"):
        build_reflective_feedback(
            episode_id="episode:feedback",
            attempts=[_attempt(attempt_id="attempt:missing", trace_id="trace:missing", success=True)],
            traces=[],
        )
