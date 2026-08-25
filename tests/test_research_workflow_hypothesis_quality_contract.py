from __future__ import annotations

from copy import deepcopy

import pytest

from core.research.workflow.contracts import (
    AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    HYPOTHESIS_SCORE_DIMENSIONS,
    HYPOTHESIS_SCORE_RUBRIC_SHA256,
    HYPOTHESIS_SCORE_RUBRIC_VERSION,
    HypothesisCandidate,
    HypothesisRoundCandidate,
    canonical_hypothesis_score_rubric,
    hypothesis_score_rubric_sha256,
)
from core.research.workflow.contracts._validation import ContractValidationError


def _five_scores(value: float = 0.7) -> dict[str, float]:
    return {dimension: value for dimension in HYPOTHESIS_SCORE_DIMENSIONS}


def test_five_dimension_rubric_is_complete_versioned_and_hash_bound() -> None:
    rubric = canonical_hypothesis_score_rubric()

    assert HYPOTHESIS_SCORE_DIMENSIONS == (
        "novelty",
        "competitionFit",
        "falsifiability",
        "evidenceSupport",
        "feasibility",
    )
    assert rubric["version"] == HYPOTHESIS_SCORE_RUBRIC_VERSION
    assert tuple(rubric["dimensions"]) == HYPOTHESIS_SCORE_DIMENSIONS
    assert len(rubric["bands"]) == 5
    assert [band["minimum"] for band in rubric["bands"]] == [
        0.0,
        0.2,
        0.4,
        0.6,
        0.8,
    ]
    assert [band["maximum"] for band in rubric["bands"]] == [
        0.2,
        0.4,
        0.6,
        0.8,
        1.0,
    ]
    assert [band["maximumInclusive"] for band in rubric["bands"]] == [
        False,
        False,
        False,
        False,
        True,
    ]
    assert all(
        set(band["descriptions"]) == set(HYPOTHESIS_SCORE_DIMENSIONS)
        for band in rubric["bands"]
    )
    assert hypothesis_score_rubric_sha256(rubric) == HYPOTHESIS_SCORE_RUBRIC_SHA256

    changed = deepcopy(rubric)
    changed["bands"][0]["descriptions"]["novelty"] = "changed"
    assert hypothesis_score_rubric_sha256(changed) != HYPOTHESIS_SCORE_RUBRIC_SHA256


def test_round_legacy_auxiliary_scores_are_diagnostics_not_main_scores() -> None:
    legacy_scores = {
        **_five_scores(),
        "replicability": 0.6,
        "scopeAlignment": 0.8,
    }
    candidate = HypothesisRoundCandidate.from_dict(
        {
            "candidateId": "cand-a",
            "claim": "A testable claim",
            "rationale": "Evidence-linked rationale",
            "differenceFromAlternatives": "Uses a different mechanism",
            "lineageRefs": [],
            "scores": legacy_scores,
            "reviewedBy": "reviewer-a",
            "status": "reviewed",
        }
    )

    assert candidate.scores == _five_scores()
    assert candidate.diagnostics == {
        dimension: legacy_scores[dimension]
        for dimension in AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS
    }
    assert candidate.to_dict()["scores"] == _five_scores()
    assert candidate.to_dict()["diagnostics"] == candidate.diagnostics


def test_portfolio_rejects_unknown_score_dimensions() -> None:
    with pytest.raises(ContractValidationError, match="unsupported hypothesis score"):
        HypothesisCandidate.from_dict(
            {
                "candidateId": "cand-a",
                "claim": "A testable claim",
                "scores": {**_five_scores(), "persuasiveness": 0.9},
                "counterEvidenceRefs": ["evidence://counter-a"],
                "derivedFromCandidateIds": [],
                "status": "draft",
                "reviewRef": "",
            }
        )
