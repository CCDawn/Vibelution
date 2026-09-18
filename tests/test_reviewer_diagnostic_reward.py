# -*- coding: utf-8 -*-
"""Tests for the reviewer diagnostic-reward pure computation layer."""

from __future__ import annotations

import pytest

from core.research.competition.reviewer_diagnostic_reward import (
    DEFAULT_REFLECTION_REVIEWER,
    _wilson_lower_bound,
    build_diagnostic_reward_report,
)
from core.research.workflow.contracts import ContractValidationError


def _row(dimension: str, rating: str, candidate_id: str, reviewer: str = "") -> dict:
    row: dict = {
        "candidateId": candidate_id,
        "dimension": dimension,
        "rating": rating,
        "rationale": "fixture rationale",
        "evidence_refs": [],
    }
    if reviewer:
        row["reviewer"] = reviewer
    return row


def _candidate(candidate_id: str, rows: list[dict]) -> dict:
    return {"candidateId": candidate_id, "dimensionReviews": rows}


def _round(candidates: list[dict], roles: dict | None = None) -> dict:
    return {
        "roundId": "round-fixture",
        "status": "closed",
        "roles": roles or {},
        "candidates": candidates,
    }


def test_improvement_counts_reward_and_rate() -> None:
    rounds = [
        _round([_candidate("c1", [_row("evidence_support", "weak", "c1")])]),
        _round([_candidate("c1", [_row("evidence_support", "adequate", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes[0].delta == 2
    assert report.critique_outcomes[0].reward == 2
    assert report.critique_outcomes[0].improved is True
    assert report.overall is not None
    assert report.overall.improvement_rate == 1.0
    assert report.overall.harm_rate == 0.0
    assert report.overall.mean_reward == 2.0


def test_harm_counts_harm_rate_with_zero_reward() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "adequate", "c1")])]),
        _round([_candidate("c1", [_row("novelty", "weak", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes[0].delta == -2
    assert report.critique_outcomes[0].reward == 0
    assert report.critique_outcomes[0].harmed is True
    assert report.overall is not None
    assert report.overall.harm_rate == 1.0
    assert report.overall.mean_delta == -2.0


def test_unchanged_critique_is_neither_improved_nor_harmed() -> None:
    rounds = [
        _round([_candidate("c1", [_row("falsifiability", "mixed", "c1")])]),
        _round([_candidate("c1", [_row("falsifiability", "mixed", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes[0].delta == 0
    assert report.overall is not None
    assert report.overall.unchanged_count == 1


def test_strong_rating_is_not_a_critique() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "strong", "c1")])]),
        _round([_candidate("c1", [_row("novelty", "weak", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes == ()
    assert report.candidate_transitions == 1
    assert report.overall is None


def test_reviewer_attribution_fallback_chain() -> None:
    rounds = [
        _round(
            [
                _candidate(
                    "c1",
                    [
                        _row("evidence_support", "weak", "c1", reviewer="agent-x"),
                        _row("novelty", "weak", "c1"),
                    ],
                ),
                _candidate("c2", [_row("novelty", "weak", "c2")]),
            ],
            roles={"reflection": "agent-role"},
        ),
        _round(
            [
                _candidate(
                    "c1",
                    [
                        _row("evidence_support", "adequate", "c1"),
                        _row("novelty", "mixed", "c1"),
                    ],
                ),
                _candidate("c2", [_row("novelty", "mixed", "c2")]),
            ]
        ),
    ]
    report = build_diagnostic_reward_report(rounds)
    reviewers = {outcome.reviewer for outcome in report.critique_outcomes}
    assert reviewers == {"agent-x", "agent-role"}
    assert set(report.by_reviewer) == {"agent-x", "agent-role"}


def test_default_attribution_when_no_roles_and_no_row_reviewer() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "weak", "c1")])]),
        _round([_candidate("c1", [_row("novelty", "adequate", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes[0].reviewer == DEFAULT_REFLECTION_REVIEWER


def test_dimension_aggregation() -> None:
    rounds = [
        _round(
            [
                _candidate("c1", [_row("evidence_support", "weak", "c1")]),
                _candidate("c2", [_row("evidence_support", "mixed", "c2")]),
            ]
        ),
        _round(
            [
                _candidate("c1", [_row("evidence_support", "adequate", "c1")]),
                _candidate("c2", [_row("evidence_support", "weak", "c2")]),
            ]
        ),
    ]
    report = build_diagnostic_reward_report(rounds)
    summary = report.by_dimension["evidence_support"]
    assert summary.critique_count == 2
    assert summary.improved_count == 1
    assert summary.harmed_count == 1
    # c1: weak(1) -> adequate(3) = +2; c2: mixed(2) -> weak(1) = -1.
    assert summary.mean_delta == 0.5


def test_candidate_missing_next_round_not_counted() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "weak", "c1")])]),
        _round([_candidate("c2", [_row("novelty", "adequate", "c2")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes == ()
    assert report.candidate_transitions == 0


def test_critiqued_dimension_missing_next_round_skips_outcome() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "weak", "c1")])]),
        _round([_candidate("c1", [_row("falsifiability", "strong", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.critique_outcomes == ()
    assert report.candidate_transitions == 1


def test_three_rounds_pair_consecutive_only() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "insufficient", "c1")])]),
        _round([_candidate("c1", [_row("novelty", "mixed", "c1")])]),
        _round([_candidate("c1", [_row("novelty", "strong", "c1")])]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.candidate_transitions == 2
    assert [outcome.delta for outcome in report.critique_outcomes] == [2, 2]


def test_empty_rounds_returns_empty_report() -> None:
    report = build_diagnostic_reward_report([])
    assert report.rounds_examined == 0
    assert report.critique_outcomes == ()
    assert report.overall is None
    assert report.by_reviewer == {}
    assert report.by_dimension == {}


def test_unknown_rating_fails_closed() -> None:
    rounds = [
        _round([_candidate("c1", [_row("novelty", "excellent", "c1")])]),
    ]
    with pytest.raises(ContractValidationError):
        build_diagnostic_reward_report(rounds)


def test_duplicate_dimension_rows_fail_closed() -> None:
    rounds = [
        _round(
            [
                _candidate(
                    "c1",
                    [
                        _row("novelty", "weak", "c1"),
                        _row("novelty", "mixed", "c1"),
                    ],
                )
            ]
        ),
    ]
    with pytest.raises(ContractValidationError):
        build_diagnostic_reward_report(rounds)


def test_row_bound_to_other_candidate_fails_closed() -> None:
    rounds = [
        _round(
            [
                _candidate(
                    "c1",
                    [
                        {
                            "candidateId": "c2",
                            "dimension": "novelty",
                            "rating": "weak",
                            "rationale": "mismatched",
                            "evidence_refs": [],
                        }
                    ],
                )
            ]
        ),
    ]
    with pytest.raises(ContractValidationError):
        build_diagnostic_reward_report(rounds)


def test_report_is_deterministic() -> None:
    rounds = [
        _round(
            [
                _candidate("c1", [_row("novelty", "weak", "c1", reviewer="a")]),
                _candidate("c2", [_row("novelty", "mixed", "c2", reviewer="b")]),
            ]
        ),
        _round(
            [
                _candidate("c1", [_row("novelty", "adequate", "c1", reviewer="a")]),
                _candidate("c2", [_row("novelty", "weak", "c2", reviewer="b")]),
            ]
        ),
    ]
    first = build_diagnostic_reward_report(rounds)
    second = build_diagnostic_reward_report(rounds)
    assert first == second


def test_wilson_lower_bound_sanity() -> None:
    assert _wilson_lower_bound(0, 0) == 0.0
    assert _wilson_lower_bound(100, 100) > 0.9
    assert _wilson_lower_bound(0, 10) == 0.0
    assert _wilson_lower_bound(1, 1) < 0.5


def _score_round(candidates: list[dict], roles: dict | None = None) -> dict:
    return {
        "roundId": "round-fixture",
        "status": "closed",
        "roles": roles or {},
        "candidates": candidates,
    }


def _score_candidate(candidate_id: str, scores: dict, reviewed_by: str = "") -> dict:
    payload: dict = {"candidateId": candidate_id, "scores": scores}
    if reviewed_by:
        payload["reviewedBy"] = reviewed_by
    return payload


def test_score_lane_improvement_and_harm() -> None:
    rounds = [
        _score_round(
            [
                _score_candidate("c1", {"novelty": 0.3, "feasibility": 0.9}, "agent-a"),
                _score_candidate("c2", {"novelty": 0.5}),
            ]
        ),
        _score_round(
            [
                _score_candidate("c1", {"novelty": 0.8, "feasibility": 0.7}, "agent-a"),
                _score_candidate("c2", {"novelty": 0.5}),
            ]
        ),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.score_candidate_transitions == 2
    # c1 novelty(+0.5)、c1 feasibility(-0.2)、c2 novelty(0.0, 0.5 有改进空间) 共三条批评样本。
    assert len(report.score_outcomes) == 3
    by_dimension = report.score_by_dimension
    assert by_dimension["novelty"].improved_count == 1
    assert by_dimension["feasibility"].harmed_count == 1
    assert report.score_overall is not None
    # (+0.5 - 0.2 + 0.0) / 3 = 0.1
    assert abs(report.score_overall.mean_delta - 0.1) < 1e-9


def test_score_lane_full_score_dimension_not_critique() -> None:
    rounds = [
        _score_round([_score_candidate("c1", {"novelty": 1.0})]),
        _score_round([_score_candidate("c1", {"novelty": 0.4})]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.score_candidate_transitions == 1
    assert report.score_outcomes == ()
    assert report.score_overall is None


def test_score_lane_reviewer_fallback_chain() -> None:
    rounds = [
        _score_round(
            [_score_candidate("c1", {"novelty": 0.3})],
            roles={"reflection": "agent-role"},
        ),
        _score_round([_score_candidate("c1", {"novelty": 0.6})]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert report.score_outcomes[0].reviewer == "agent-role"
    assert set(report.score_by_reviewer) == {"agent-role"}


def test_score_lane_unknown_dimension_fails_closed() -> None:
    rounds = [_score_round([_score_candidate("c1", {"charm": 0.5})])]
    with pytest.raises(ContractValidationError):
        build_diagnostic_reward_report(rounds)


def test_score_lane_missing_next_round_dimension_skips() -> None:
    rounds = [
        _score_round([_score_candidate("c1", {"novelty": 0.3, "feasibility": 0.4})]),
        _score_round([_score_candidate("c1", {"novelty": 0.6})]),
    ]
    report = build_diagnostic_reward_report(rounds)
    assert [o.dimension for o in report.score_outcomes] == ["novelty"]
