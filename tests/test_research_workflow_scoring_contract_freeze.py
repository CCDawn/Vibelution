"""Challenge-cup scoring contract freeze tests (ruling 2026-08-28, item 9).

Freezes the authoritative hypothesis scoring contract as exactly five
decision dimensions (novelty, competitionFit, falsifiability,
evidenceSupport, feasibility) plus exactly two auxiliary diagnostics
(replicability, scopeAlignment):

- the dimension id sets are closed: adding or removing one id turns red;
- the Pareto/dominance and pairwise-debate ranking paths consume only the
  five decision dimensions — auxiliary diagnostics can never move the
  primary ranking, they stay a separate diagnostics channel;
- no review artifact exposes an unexplained single total score (ruling
  item 4: scores are never collapsed into one weighted aggregate; the
  canonical rubric carries no dimension weights either).

This is the test-side freeze of ruling item 9 (= plan step R0.2) and does
not restate the rubric hash/version binding already covered by
``test_research_workflow_hypothesis_quality_contract.py``.

Authoritative surfaces under test:
- ``core/research/workflow/contracts/hypothesis_quality.py`` (5+2 rubric)
- ``core/web/services/team_workflow/hypothesis_review_executor.py``
  (reflection / pairwise / Pareto ranking consumption)
"""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import (
    AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    HYPOTHESIS_SCORE_DIMENSIONS,
    SCORE_DIMENSIONS,
    HypothesisRoundCandidate,
    canonical_hypothesis_score_rubric,
)
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.hypothesis_quality import (
    normalize_hypothesis_scores,
)
from core.web.services.team_workflow import hypothesis_review_executor

FROZEN_DECISION_DIMENSIONS = frozenset(
    {
        "novelty",
        "competitionFit",
        "falsifiability",
        "evidenceSupport",
        "feasibility",
    }
)
FROZEN_AUXILIARY_DIAGNOSTICS = frozenset(
    {
        "replicability",
        "scopeAlignment",
    }
)

# Names a "seven dimensions collapsed into one aggregate" regression would
# plausibly reintroduce on a review artifact.  The contract ships none of
# them; if one ever appears, ranking has drifted back to a single total.
_TOTAL_SCORE_KEY_DENYLIST = frozenset(
    {
        "totalScore",
        "total_score",
        "overall",
        "overallScore",
        "overall_score",
        "weightedScore",
        "weighted_score",
        "averageScore",
        "average_score",
        "aggregateScore",
        "aggregate_score",
        "recommendationScore",
        "recommendation_score",
    }
)


def _five_scores(value: float) -> dict[str, float]:
    return {dimension: value for dimension in HYPOTHESIS_SCORE_DIMENSIONS}


def _two_candidates_context() -> dict:
    return {
        "contextId": "ctx-scoring-freeze",
        "candidates": [
            {
                "candidateId": "cand-a",
                "claim": "候选 cand-a 的核心机制陈述：以不同归纳偏置提升样本效率",
                "differenceFromAlternatives": "cand-a 采用区别于 cand-b 的机制路径",
            },
            {
                "candidateId": "cand-b",
                "claim": "候选 cand-b 的核心机制陈述：以稀疏先验压缩假设空间",
                "differenceFromAlternatives": "cand-b 采用区别于 cand-a 的机制路径",
            },
        ],
    }


def _dominance_reflection_runner(diagnostics_by_candidate):
    """cand-a strictly dominates cand-b on the five decision dimensions."""

    def reflection(candidate, context):
        candidate_id = str(candidate["candidateId"])
        return {
            "claim": str(candidate["claim"]),
            "rationale": "五维独立评分依据",
            "differenceFromAlternatives": str(candidate["differenceFromAlternatives"]),
            "scores": _five_scores(0.9 if candidate_id == "cand-a" else 0.4),
            "diagnostics": dict(diagnostics_by_candidate[candidate_id]),
        }

    return reflection


def test_decision_dimensions_are_exactly_the_frozen_five() -> None:
    assert set(HYPOTHESIS_SCORE_DIMENSIONS) == FROZEN_DECISION_DIMENSIONS
    assert len(HYPOTHESIS_SCORE_DIMENSIONS) == len(set(HYPOTHESIS_SCORE_DIMENSIONS)) == 5

    # The ranking layer imports the alias; it must be the same frozen ids,
    # not a parallel set that can drift back toward the legacy dimensions.
    assert SCORE_DIMENSIONS == HYPOTHESIS_SCORE_DIMENSIONS
    assert set(SCORE_DIMENSIONS) == FROZEN_DECISION_DIMENSIONS

    rubric = canonical_hypothesis_score_rubric()
    assert set(rubric["dimensions"]) == FROZEN_DECISION_DIMENSIONS
    assert len(rubric["dimensions"]) == 5


def test_auxiliary_diagnostics_are_exactly_the_frozen_two() -> None:
    assert set(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS) == FROZEN_AUXILIARY_DIAGNOSTICS
    assert (
        len(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS)
        == len(set(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS))
        == 2
    )
    # Diagnostics are disjoint from the decision set: an id can never be
    # both a ranking input and a diagnostic.
    assert not FROZEN_AUXILIARY_DIAGNOSTICS & FROZEN_DECISION_DIMENSIONS

    rubric = canonical_hypothesis_score_rubric()
    assert set(rubric["auxiliaryDiagnostics"]) == FROZEN_AUXILIARY_DIAGNOSTICS
    assert len(rubric["auxiliaryDiagnostics"]) == 2
    # The full rubric reviews 5 + 2 ids and nothing else.
    assert (
        set(rubric["dimensions"]) | set(rubric["auxiliaryDiagnostics"])
        == FROZEN_DECISION_DIMENSIONS | FROZEN_AUXILIARY_DIAGNOSTICS
    )
    assert len(set(rubric["dimensions"]) | set(rubric["auxiliaryDiagnostics"])) == 7


def test_any_seventh_score_dimension_fails_closed() -> None:
    # A "seven equally weighted dimensions" regression must be refused at
    # the normalization gate, for a legacy dimension id and a brand-new id.
    for intruder in ("noveltyGap", "persuasiveness"):
        with pytest.raises(ContractValidationError, match="unsupported hypothesis score"):
            normalize_hypothesis_scores({**_five_scores(0.7), intruder: 0.5})

    with pytest.raises(ContractValidationError, match="unsupported hypothesis diagnostic"):
        normalize_hypothesis_scores(
            _five_scores(0.7),
            raw_diagnostics={"novelty": 0.5},
        )


def test_auxiliary_diagnostics_are_carried_outside_the_decision_scores() -> None:
    scores, diagnostics = normalize_hypothesis_scores(
        _five_scores(0.7),
        raw_diagnostics={"replicability": 0.6, "scopeAlignment": 0.8},
    )
    assert set(scores) == FROZEN_DECISION_DIMENSIONS
    assert set(diagnostics) == FROZEN_AUXILIARY_DIAGNOSTICS

    candidate = HypothesisRoundCandidate.from_dict(
        {
            "candidateId": "cand-a",
            "claim": "A testable claim",
            "differenceFromAlternatives": "A distinct mechanism",
            "lineageRefs": [],
            "scores": _five_scores(0.7),
            "diagnostics": {"replicability": 0.6, "scopeAlignment": 0.8},
            "reviewedBy": "reviewer-a",
            "status": "reviewed",
        }
    )
    assert set(candidate.scores) == FROZEN_DECISION_DIMENSIONS
    assert set(candidate.diagnostics) == FROZEN_AUXILIARY_DIAGNOSTICS
    persisted = candidate.to_dict()
    assert set(persisted["scores"]) == FROZEN_DECISION_DIMENSIONS
    assert set(persisted["diagnostics"]) == FROZEN_AUXILIARY_DIAGNOSTICS


def test_pareto_dominance_uses_only_the_five_decision_dimensions() -> None:
    # Direct call on the DEV fixture ranking helper on purpose: it is the
    # one in-repo dominance implementation and the shape every FORMAL
    # pareto runner payload is validated against.  cand-a wins all five
    # decision dimensions; cand-b wins both diagnostics.  If a regression
    # ever let the dominance loop consult diagnostics, cand-a would no
    # longer dominate cand-b and the front would change.
    scores = {
        "cand-a": {**_five_scores(0.9), "replicability": 0.0, "scopeAlignment": 0.0},
        "cand-b": {**_five_scores(0.4), "replicability": 1.0, "scopeAlignment": 1.0},
    }

    front, dominated = hypothesis_review_executor._fixture_pareto(scores)

    assert front == ["cand-a"]
    assert dominated == ["cand-b"]

    # Same inputs restricted to the closed five-dimension set must produce
    # the identical classification: extra diagnostic keys are inert.
    five_dim_only = {key: {d: v[d] for d in HYPOTHESIS_SCORE_DIMENSIONS} for key, v in scores.items()}
    assert hypothesis_review_executor._fixture_pareto(five_dim_only) == (front, dominated)


def test_pairwise_debate_counts_only_the_five_decision_dimensions() -> None:
    # cand-a leads on 3 of 5 decision dimensions, cand-b leads on the other
    # 2 plus both diagnostics.  A seven-dimension vote would flip the debate
    # to right_wins; the frozen contract must keep left_wins.
    left = {
        **{dimension: 0.9 for dimension in ("novelty", "competitionFit", "falsifiability")},
        "evidenceSupport": 0.4,
        "feasibility": 0.4,
        "replicability": 0.0,
        "scopeAlignment": 0.0,
    }
    right = {
        **{dimension: 0.9 for dimension in ("evidenceSupport", "feasibility")},
        "novelty": 0.4,
        "competitionFit": 0.4,
        "falsifiability": 0.4,
        "replicability": 1.0,
        "scopeAlignment": 1.0,
    }

    with_diagnostics, justification = hypothesis_review_executor._fixture_debate_outcome(
        {"candidateId": "cand-a", "scores": left},
        {"candidateId": "cand-b", "scores": right},
    )
    five_dim_left = {d: left[d] for d in HYPOTHESIS_SCORE_DIMENSIONS}
    five_dim_right = {d: right[d] for d in HYPOTHESIS_SCORE_DIMENSIONS}
    without_diagnostics, _ = hypothesis_review_executor._fixture_debate_outcome(
        {"candidateId": "cand-a", "scores": five_dim_left},
        {"candidateId": "cand-b", "scores": five_dim_right},
    )

    assert with_diagnostics == "left_wins"
    assert without_diagnostics == with_diagnostics
    assert "cand-a" in justification and "cand-b" in justification


def test_flipping_diagnostics_never_moves_the_primary_ranking() -> None:
    diagnostics_low_for_a = {
        "cand-a": {"replicability": 0.0, "scopeAlignment": 0.0},
        "cand-b": {"replicability": 1.0, "scopeAlignment": 1.0},
    }
    diagnostics_flipped = {
        "cand-a": {"replicability": 1.0, "scopeAlignment": 1.0},
        "cand-b": {"replicability": 0.0, "scopeAlignment": 0.0},
    }

    runs = [
        hypothesis_review_executor.execute_hypothesis_review(
            _two_candidates_context(),
            round_id="hround-scoring-freeze",
            reflection_runner=_dominance_reflection_runner(diagnostics),
            reviewer_assignments={"metareview": "coordinator"},
            position_seed="freeze-seed-1",
        )
        for diagnostics in (diagnostics_low_for_a, diagnostics_flipped)
    ]

    baseline, flipped = runs
    for run, diagnostics in zip(runs, (diagnostics_low_for_a, diagnostics_flipped)):
        for item in run["candidates"]:
            # Scores stay the closed five-dimension set; diagnostics stay on
            # their own channel and never leak into ``scores``.
            assert set(item["scores"]) == FROZEN_DECISION_DIMENSIONS
            assert set(item["diagnostics"]) == FROZEN_AUXILIARY_DIAGNOSTICS
            assert item["diagnostics"] == diagnostics[item["candidateId"]]

    # Identical five-dimension inputs: the entire ranking outcome — Pareto
    # classification, pairwise outcomes, and the MetaReview recommendation —
    # is byte-identical no matter how the diagnostics are flipped.
    assert flipped["pareto"] == baseline["pareto"]
    assert flipped["pairwiseComparisons"] == baseline["pairwiseComparisons"]
    assert flipped["metaReview"] == baseline["metaReview"]
    assert baseline["pareto"]["paretoFrontCandidateIds"] == ["cand-a"]
    assert baseline["pareto"]["dominatedCandidateIds"] == ["cand-b"]


def test_review_artifacts_expose_no_unexplained_total_score() -> None:
    # Ruling item 4: scores are never collapsed into a single weighted
    # aggregate; selection rides on Pareto front + hard gates + pairwise
    # disagreement.  The implementation ships no such field — this
    # assertion is the regression tripwire that keeps it that way.
    result = hypothesis_review_executor.execute_hypothesis_review(
        _two_candidates_context(),
        round_id="hround-scoring-freeze-total",
        reflection_runner=_dominance_reflection_runner(
            {
                "cand-a": {"replicability": 0.5, "scopeAlignment": 0.5},
                "cand-b": {"replicability": 0.5, "scopeAlignment": 0.5},
            }
        ),
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="freeze-seed-2",
    )

    top_level_keys = set(result)
    assert not top_level_keys & _TOTAL_SCORE_KEY_DENYLIST
    for item in result["candidates"]:
        assert not set(item) & _TOTAL_SCORE_KEY_DENYLIST
        assert set(item["scores"]) == FROZEN_DECISION_DIMENSIONS
    for key in ("pareto", "metaReview"):
        assert not set(result[key]) & _TOTAL_SCORE_KEY_DENYLIST
    for comparison in result["pairwiseComparisons"]:
        assert not set(comparison) & _TOTAL_SCORE_KEY_DENYLIST

    candidate = HypothesisRoundCandidate.from_dict(
        {
            "candidateId": "cand-a",
            "claim": "A testable claim",
            "differenceFromAlternatives": "A distinct mechanism",
            "lineageRefs": [],
            "scores": _five_scores(0.7),
            "reviewedBy": "reviewer-a",
            "status": "reviewed",
        }
    )
    assert not set(candidate.to_dict()) & _TOTAL_SCORE_KEY_DENYLIST

    # The canonical rubric defines bands and descriptions only — a
    # "seven dimensions with weights" comeback would need a weights key.
    rubric = canonical_hypothesis_score_rubric()
    assert set(rubric) == {"version", "dimensions", "auxiliaryDiagnostics", "bands"}
    assert all("weights" not in band for band in rubric["bands"])
