"""Stage-1 exact review call budget contract tests.

Verifies the frozen budget formula ``n + n(n-1)/2 + 2`` (2026-08-31 高ROI
优化实施计划 §7 Task 4 / Task 9): n individual reflection calls + n(n-1)/2
pairwise calls + 2 closing calls (Pareto + MetaReview).  With the frozen
finalist limit n=3 this is exactly 8 review calls.  Fail-closed parsing,
tamper detection, and per-step reconciliation are covered as well.
"""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import (
    CLOSING_REVIEW_CALLS,
    MAX_BUDGET_FINALIST_COUNT,
    REVIEW_CALL_BUDGET_FORMULA,
    ContractValidationError,
    ReviewCallBudget,
    reconcile_review_call_budget,
    validate_finalist_count,
)


@pytest.mark.parametrize(
    ("finalists", "individual", "pairwise", "total"),
    [
        (1, 1, 0, 3),
        (2, 2, 1, 5),
        (3, 3, 3, 8),
        (4, 4, 6, 12),
        (5, 5, 10, 17),
        (6, 6, 15, 23),
    ],
)
def test_budget_formula_exact_values(finalists, individual, pairwise, total):
    budget = ReviewCallBudget.for_finalists(finalists)

    assert budget.individualReviewCalls == individual
    assert budget.pairwiseComparisonCalls == pairwise
    assert budget.closingReviewCalls == CLOSING_REVIEW_CALLS == 2
    assert budget.totalReviewCalls == individual + pairwise + 2 == total


def test_frozen_finalist_limit_yields_eight_review_calls():
    budget = ReviewCallBudget.for_finalists(3)

    assert budget.totalReviewCalls == 8
    assert budget.describe() == (
        "n + n(n-1)/2 + 2 with n=3 -> 3 individual + 3 pairwise + "
        "2 closing = 8 review calls"
    )


def test_formula_text_is_the_contract_wording():
    assert REVIEW_CALL_BUDGET_FORMULA == "n + n(n-1)/2 + 2"


def test_legacy_sixteen_candidate_path_projects_one_hundred_thirty_eight_calls():
    budget = ReviewCallBudget.for_finalists(16)

    assert budget.totalReviewCalls == 16 + 16 * 15 // 2 + 2 == 138


@pytest.mark.parametrize("finalist_count", [0, -1, 17, True, False, "3", 3.0, None])
def test_finalist_count_validation_fails_closed(finalist_count):
    with pytest.raises(ContractValidationError):
        validate_finalist_count(finalist_count)
    with pytest.raises(ContractValidationError):
        ReviewCallBudget.for_finalists(finalist_count)


def test_exactly_sixteen_finalists_still_parse():
    assert validate_finalist_count(MAX_BUDGET_FINALIST_COUNT) == 16


def test_budget_round_trips_through_dict():
    budget = ReviewCallBudget.for_finalists(3)

    parsed = ReviewCallBudget.from_dict(budget.to_dict())

    assert parsed == budget


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("finalistCount", 4),
        ("individualReviewCalls", 102),
        ("pairwiseComparisonCalls", 102),
        ("closingReviewCalls", 101),
        ("totalReviewCalls", 107),
        ("formula", "n * 3"),
    ],
)
def test_tampered_budget_record_is_rejected(field, tampered):
    payload = ReviewCallBudget.for_finalists(3).to_dict()
    payload[field] = tampered

    with pytest.raises(ContractValidationError, match="disagrees with its derivation"):
        ReviewCallBudget.from_dict(payload)


def test_reconciliation_reports_exact_spending():
    budget = ReviewCallBudget.for_finalists(3)

    reconciliation = reconcile_review_call_budget(
        budget,
        individual_review_calls=3,
        pairwise_comparison_calls=3,
        pareto_calls=1,
        metareview_calls=1,
    )

    assert reconciliation.exact is True
    assert reconciliation.within_budget is True
    assert reconciliation.actualReviewStepCalls == 8
    assert reconciliation.to_dict() == {
        "individualReviewCalls": 3,
        "pairwiseComparisonCalls": 3,
        "paretoCalls": 1,
        "metareviewCalls": 1,
        "reviewStepCalls": 8,
        "withinBudget": True,
        "matchesFormula": True,
    }


def test_reconciliation_detects_overspend_and_underspend():
    budget = ReviewCallBudget.for_finalists(3)

    overspent = reconcile_review_call_budget(
        budget,
        individual_review_calls=4,
        pairwise_comparison_calls=6,
        pareto_calls=1,
        metareview_calls=1,
    )
    assert overspent.within_budget is False
    assert overspent.exact is False

    underspent = reconcile_review_call_budget(
        budget,
        individual_review_calls=3,
        pairwise_comparison_calls=2,
        pareto_calls=1,
        metareview_calls=1,
    )
    assert underspent.within_budget is True
    assert underspent.exact is False
    assert "actual 3 individual + 2 pairwise" in underspent.deviation_detail()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"individual_review_calls": -1, "pairwise_comparison_calls": 0, "pareto_calls": 0, "metareview_calls": 0},
        {"individual_review_calls": 0, "pairwise_comparison_calls": True, "pareto_calls": 0, "metareview_calls": 0},
        {"individual_review_calls": 0, "pairwise_comparison_calls": 0, "pareto_calls": 1.5, "metareview_calls": 0},
    ],
)
def test_reconciliation_rejects_malformed_counts(kwargs):
    budget = ReviewCallBudget.for_finalists(3)

    with pytest.raises(ContractValidationError):
        reconcile_review_call_budget(budget, **kwargs)
