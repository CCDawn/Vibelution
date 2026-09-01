"""Exact hypothesis review call budget for one closed review round.

Stage-1 contract (2026-08-31 高ROI优化实施计划 §7 Task 4 / Task 9): with
``n`` screened finalists entering pairwise review, one closed round spends
exactly

    n + n(n-1)/2 + 2

review calls:

- ``n`` individual reflection calls — every finalist is scored independently;
- ``n(n-1)/2`` pairwise calls — every unordered finalist pair is compared once;
- ``2`` closing calls — one Pareto classification plus one MetaReview.

With the frozen finalist limit (``MAX_FINALIST_LIMIT = 3``) this bounds one
formal round at 8 review calls, replacing the unbounded C(n,2) growth of the
legacy 16-candidate path (138 calls at n=16).  The formal G1 gate records the
actual call counts against this budget to prove the exact budget was
respected; the FORMAL revision runner call stays outside the formula (the
contract enumerates reflection / pairwise / Pareto / MetaReview) but is
recorded separately for deadline accounting.

The contract fails closed: a finalist count below 1 or beyond the bounded
review-context cap is rejected, a persisted budget must agree with its own
formula derivation, and reconciling actual counts exposes any deviation from
the exact budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import ContractValidationError

REVIEW_CALL_BUDGET_CONTRACT_VERSION = "review-call-budget-v1"

#: Canonical formula text; every budget mismatch error must carry it so the
#: deviation stays diagnosable without opening this module.
REVIEW_CALL_BUDGET_FORMULA = "n + n(n-1)/2 + 2"

#: Pareto classification + MetaReview, the two closing calls of one round.
CLOSING_REVIEW_CALLS = 2

#: Largest candidate set that can reach review: the bounded review context
#: truncates candidates at the same cap (research_memory_context
#: MAX_REVIEW_CANDIDATES), so a budget beyond it is unreachable.
MAX_BUDGET_FINALIST_COUNT = 16


def validate_finalist_count(finalist_count: Any) -> int:
    """Validate a finalist count the budget formula may be applied to."""

    if isinstance(finalist_count, bool) or not isinstance(finalist_count, int):
        raise ContractValidationError(
            "review call budget finalist count must be an integer, "
            f"got {finalist_count!r}"
        )
    if finalist_count < 1:
        raise ContractValidationError(
            "review call budget finalist count must be at least 1"
        )
    if finalist_count > MAX_BUDGET_FINALIST_COUNT:
        raise ContractValidationError(
            "review call budget finalist count must not exceed "
            f"{MAX_BUDGET_FINALIST_COUNT} (the bounded review context cap)"
        )
    return finalist_count


@dataclass(frozen=True, slots=True)
class ReviewCallBudget:
    """Exact review call budget derived from the finalist count ``n``."""

    finalistCount: int
    individualReviewCalls: int
    pairwiseComparisonCalls: int
    closingReviewCalls: int
    totalReviewCalls: int
    formula: str

    @classmethod
    def for_finalists(cls, finalist_count: int) -> ReviewCallBudget:
        validated = validate_finalist_count(finalist_count)
        pairwise = validated * (validated - 1) // 2
        return cls(
            finalistCount=validated,
            individualReviewCalls=validated,
            pairwiseComparisonCalls=pairwise,
            closingReviewCalls=CLOSING_REVIEW_CALLS,
            totalReviewCalls=validated + pairwise + CLOSING_REVIEW_CALLS,
            formula=REVIEW_CALL_BUDGET_FORMULA,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewCallBudget:
        parsed = cls.for_finalists(payload.get("finalistCount"))
        stored = {
            "individualReviewCalls": payload.get("individualReviewCalls"),
            "pairwiseComparisonCalls": payload.get("pairwiseComparisonCalls"),
            "closingReviewCalls": payload.get("closingReviewCalls"),
            "totalReviewCalls": payload.get("totalReviewCalls"),
            "formula": payload.get("formula"),
        }
        derived = {
            "individualReviewCalls": parsed.individualReviewCalls,
            "pairwiseComparisonCalls": parsed.pairwiseComparisonCalls,
            "closingReviewCalls": parsed.closingReviewCalls,
            "totalReviewCalls": parsed.totalReviewCalls,
            "formula": parsed.formula,
        }
        mismatched = sorted(
            key for key, value in derived.items() if stored.get(key) != value
        )
        if mismatched:
            raise ContractValidationError(
                "persisted review call budget disagrees with its derivation "
                f"({REVIEW_CALL_BUDGET_FORMULA}): mismatched fields "
                + ", ".join(mismatched)
            )
        return parsed

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": REVIEW_CALL_BUDGET_CONTRACT_VERSION,
            "finalistCount": self.finalistCount,
            "individualReviewCalls": self.individualReviewCalls,
            "pairwiseComparisonCalls": self.pairwiseComparisonCalls,
            "closingReviewCalls": self.closingReviewCalls,
            "totalReviewCalls": self.totalReviewCalls,
            "formula": self.formula,
        }

    def describe(self) -> str:
        """Human-readable derivation for diagnostics and error messages."""

        return (
            f"{REVIEW_CALL_BUDGET_FORMULA} with n={self.finalistCount} -> "
            f"{self.individualReviewCalls} individual + "
            f"{self.pairwiseComparisonCalls} pairwise + "
            f"{self.closingReviewCalls} closing = {self.totalReviewCalls} "
            "review calls"
        )


def review_call_budget_for(finalist_count: Any) -> ReviewCallBudget:
    """Exact review call budget for ``finalist_count`` screened finalists."""

    return ReviewCallBudget.for_finalists(finalist_count)


@dataclass(frozen=True, slots=True)
class ReviewCallBudgetReconciliation:
    """Actual review-step counts reconciled against the exact budget."""

    budget: ReviewCallBudget
    actualIndividualReviewCalls: int
    actualPairwiseComparisonCalls: int
    actualParetoCalls: int
    actualMetareviewCalls: int

    @property
    def actualReviewStepCalls(self) -> int:
        return (
            self.actualIndividualReviewCalls
            + self.actualPairwiseComparisonCalls
            + self.actualParetoCalls
            + self.actualMetareviewCalls
        )

    @property
    def within_budget(self) -> bool:
        return self.actualReviewStepCalls <= self.budget.totalReviewCalls

    @property
    def exact(self) -> bool:
        """True when every review step spent exactly its budgeted calls."""

        return (
            self.actualIndividualReviewCalls == self.budget.individualReviewCalls
            and self.actualPairwiseComparisonCalls == self.budget.pairwiseComparisonCalls
            and self.actualParetoCalls == self.budget.closingReviewCalls - 1
            and self.actualMetareviewCalls == 1
        )

    def deviation_detail(self) -> str:
        return (
            f"expected {self.budget.describe()}, actual "
            f"{self.actualIndividualReviewCalls} individual + "
            f"{self.actualPairwiseComparisonCalls} pairwise + "
            f"{self.actualParetoCalls} pareto + {self.actualMetareviewCalls} "
            f"metareview = {self.actualReviewStepCalls} review calls"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "individualReviewCalls": self.actualIndividualReviewCalls,
            "pairwiseComparisonCalls": self.actualPairwiseComparisonCalls,
            "paretoCalls": self.actualParetoCalls,
            "metareviewCalls": self.actualMetareviewCalls,
            "reviewStepCalls": self.actualReviewStepCalls,
            "withinBudget": self.within_budget,
            "matchesFormula": self.exact,
        }


def reconcile_review_call_budget(
    budget: ReviewCallBudget,
    *,
    individual_review_calls: int,
    pairwise_comparison_calls: int,
    pareto_calls: int,
    metareview_calls: int,
) -> ReviewCallBudgetReconciliation:
    """Reconcile actual per-step call counts against the exact budget."""

    counts = {
        "individual_review_calls": individual_review_calls,
        "pairwise_comparison_calls": pairwise_comparison_calls,
        "pareto_calls": pareto_calls,
        "metareview_calls": metareview_calls,
    }
    for name, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractValidationError(
                f"reconciled {name} must be a non-negative integer, got {value!r}"
            )
    return ReviewCallBudgetReconciliation(
        budget=budget,
        actualIndividualReviewCalls=individual_review_calls,
        actualPairwiseComparisonCalls=pairwise_comparison_calls,
        actualParetoCalls=pareto_calls,
        actualMetareviewCalls=metareview_calls,
    )


__all__ = [
    "CLOSING_REVIEW_CALLS",
    "MAX_BUDGET_FINALIST_COUNT",
    "REVIEW_CALL_BUDGET_CONTRACT_VERSION",
    "REVIEW_CALL_BUDGET_FORMULA",
    "ReviewCallBudget",
    "ReviewCallBudgetReconciliation",
    "reconcile_review_call_budget",
    "review_call_budget_for",
    "validate_finalist_count",
]
