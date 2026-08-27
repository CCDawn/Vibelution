"""Reviewer-independence and review-disagreement contracts for one review round.

Two canonical data carriers back the joint selection decision (Pareto front +
hard gates + reviewer disagreement; scores never collapse into a total):

- :class:`ReviewerIndependenceRecord` — one reviewer's participation in exactly
  one unique review-step instance (step name + unique step identity), with the
  receipt reference and where the assignment came from.  The fail-closed hard
  gate: the same reviewer must never be counted twice as an independent review
  of the same step instance (same-source pseudo-independence).
- :class:`ReviewDisagreementArtifact` — the disagreement projection over one
  review round: candidate pairs, per-reviewer five-dimension score references
  (references only, never copies of the score bodies), the disagreement axes
  restricted to the five decision dimensions, axis-level direction
  inconsistency counts, and an escalation that is marked only — never executed.

Auxiliary diagnostic dimensions (``replicability``, ``scopeAlignment``) can
never become disagreement axes and never affect the primary decision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_text,
)
from .hypothesis_quality import (
    AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    HYPOTHESIS_SCORE_DIMENSIONS,
)
from .hypothesis_round import COMPARISON_OUTCOMES

REVIEW_INDEPENDENCE_SCHEMA_VERSION = 1
REVIEW_DISAGREEMENT_SCHEMA_VERSION = 1

REVIEW_STEP_NAMES = ("reflection", "pairwise", "pareto", "metareview")
REVIEW_ASSIGNMENT_SOURCES = frozenset({"reviewer_assignments", "executor_role_default"})
REVIEW_EXECUTION_MODES = frozenset({"dev", "formal"})

#: Escalation is a decision-input marker only; it never executes by itself.
ESCALATION_STATUS_FLAGGED_ONLY = "flagged_only"

#: The only axes that may appear as disagreement axes (the decision dimensions).
REVIEW_DISAGREEMENT_DECISION_AXES = HYPOTHESIS_SCORE_DIMENSIONS
#: Diagnostics that must never leak into the disagreement axes.
AUXILIARY_REVIEW_DIAGNOSTIC_AXES = AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS


def review_step_identity(
    review_step: str,
    review_context_id: str,
    identity_parts: Sequence[str] = (),
) -> str:
    """Compose the unique identity of one review-step instance.

    The same reviewer legitimately covers many step instances (for example one
    reflection call per candidate); uniqueness is enforced per step instance,
    not per step name.
    """

    step = str(review_step or "").strip().lower()
    if step not in REVIEW_STEP_NAMES:
        raise ContractValidationError(
            "review step must be one of: " + ", ".join(REVIEW_STEP_NAMES)
        )
    context_id = str(review_context_id or "").strip()
    if not context_id:
        raise ContractValidationError("review step identity requires a review context id")
    parts = [step, context_id, *[str(part or "").strip() for part in identity_parts]]
    if any(not part for part in parts[2:]):
        raise ContractValidationError("review step identity parts must be non-empty")
    return ":".join(parts)


def validate_step_independence(records: Sequence[ReviewerIndependenceRecord]) -> None:
    """Fail closed on same-source pseudo-independence double counting.

    Every step instance may carry exactly one record: counting the same
    reviewer (or any reviewer at all) twice for one step instance would
    fabricate an independent review, so construction of the record set is
    rejected instead of silently deduplicated.
    """

    seen: dict[str, str] = {}
    for record in records:
        prior = seen.get(record.stepIdentity)
        if prior is not None:
            if prior == record.reviewerId:
                raise ContractValidationError(
                    "same-source pseudo-independence: reviewer "
                    f"{record.reviewerId} is double counted for step instance "
                    f"{record.stepIdentity}"
                )
            raise ContractValidationError(
                f"step instance {record.stepIdentity} is claimed by multiple "
                f"reviewers: {prior} and {record.reviewerId}"
            )
        seen[record.stepIdentity] = record.reviewerId


def reviewer_independence_summary(records: Sequence[ReviewerIndependenceRecord]) -> dict[str, Any]:
    """Summarize reviewer independence for one round (data, not a gate).

    ``singleSourcePseudoIndependence`` flags a round whose records all resolve
    to one reviewer; it informs the joint decision but never fails
    construction — the hard gate lives in :func:`validate_step_independence`.
    """

    reviewer_ids = {record.reviewerId for record in records}
    step_ids = {record.stepIdentity for record in records}
    return {
        "recordCount": len(records),
        "uniqueReviewerCount": len(reviewer_ids),
        "uniqueStepCount": len(step_ids),
        "receiptBoundRecordCount": sum(1 for record in records if record.receiptRef),
        "singleSourcePseudoIndependence": len(records) > 1 and len(reviewer_ids) == 1,
    }


@dataclass(frozen=True, slots=True)
class ReviewerIndependenceRecord:
    """One reviewer's participation in one unique review-step instance."""

    recordId: str
    teamId: str
    workflowRunId: str
    reviewRoundId: str
    reviewContextId: str
    reviewStep: str
    stepIdentity: str
    reviewerId: str
    reviewerRole: str
    assignmentSource: str
    receiptRef: str
    executionMode: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewerIndependenceRecord:
        review_step = require_text(payload, "reviewStep").lower()
        if review_step not in REVIEW_STEP_NAMES:
            raise ContractValidationError(
                "reviewStep must be one of: " + ", ".join(REVIEW_STEP_NAMES)
            )
        assignment_source = require_text(payload, "assignmentSource")
        if assignment_source not in REVIEW_ASSIGNMENT_SOURCES:
            raise ContractValidationError(
                "assignmentSource must be one of: "
                + ", ".join(sorted(REVIEW_ASSIGNMENT_SOURCES))
            )
        execution_mode = require_text(payload, "executionMode").lower()
        if execution_mode not in REVIEW_EXECUTION_MODES:
            raise ContractValidationError(
                "executionMode must be one of: " + ", ".join(sorted(REVIEW_EXECUTION_MODES))
            )
        receipt_ref = str(payload.get("receiptRef") or "").strip()
        if execution_mode == "formal" and not receipt_ref:
            raise ContractValidationError(
                "a formal review step requires a provider receipt reference"
            )
        step_identity = require_text(payload, "stepIdentity")
        expected_step = step_identity.split(":", 1)[0]
        if expected_step != review_step:
            raise ContractValidationError(
                "stepIdentity must be scoped by its own reviewStep: "
                f"{step_identity} is not a {review_step} identity"
            )
        return cls(
            recordId=require_text(payload, "recordId"),
            teamId=require_text(payload, "teamId"),
            workflowRunId=require_text(payload, "workflowRunId"),
            reviewRoundId=require_text(payload, "reviewRoundId"),
            reviewContextId=require_text(payload, "reviewContextId"),
            reviewStep=review_step,
            stepIdentity=step_identity,
            reviewerId=require_text(payload, "reviewerId"),
            reviewerRole=require_text(payload, "reviewerRole"),
            assignmentSource=assignment_source,
            receiptRef=receipt_ref,
            executionMode=execution_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordId": self.recordId,
            "teamId": self.teamId,
            "workflowRunId": self.workflowRunId,
            "reviewRoundId": self.reviewRoundId,
            "reviewContextId": self.reviewContextId,
            "reviewStep": self.reviewStep,
            "stepIdentity": self.stepIdentity,
            "reviewerId": self.reviewerId,
            "reviewerRole": self.reviewerRole,
            "assignmentSource": self.assignmentSource,
            "receiptRef": self.receiptRef,
            "executionMode": self.executionMode,
        }

    def is_receipt_bound(self) -> bool:
        return bool(self.receiptRef)


def _validated_axes(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    axes = require_list(payload, key)
    invalid: list[str] = []
    auxiliary: list[str] = []
    for item in axes:
        axis = str(item or "").strip()
        if not axis:
            invalid.append("<empty>")
        elif axis in AUXILIARY_REVIEW_DIAGNOSTIC_AXES:
            auxiliary.append(axis)
        elif axis not in REVIEW_DISAGREEMENT_DECISION_AXES:
            invalid.append(axis)
    if auxiliary:
        raise ContractValidationError(
            "auxiliary diagnostics can never be disagreement axes: "
            + ", ".join(sorted(set(auxiliary)))
        )
    if invalid:
        raise ContractValidationError(
            "disagreement axes are restricted to the five decision dimensions, "
            "unsupported: " + ", ".join(sorted(set(invalid)))
        )
    ordered = [
        axis
        for axis in REVIEW_DISAGREEMENT_DECISION_AXES
        if axis in {str(item or "").strip() for item in axes}
    ]
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class ReviewScoreRef:
    """A pointer to one reviewer's five-dimension score body (no copy)."""

    candidateId: str
    reviewerId: str
    scoreRef: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewScoreRef:
        return cls(
            candidateId=require_text(payload, "candidateId"),
            reviewerId=require_text(payload, "reviewerId"),
            scoreRef=require_text(payload, "scoreRef"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidateId,
            "reviewerId": self.reviewerId,
            "scoreRef": self.scoreRef,
        }


@dataclass(frozen=True, slots=True)
class ReviewPairDisagreement:
    """One debated pair with the axes its outcome direction contradicts."""

    comparisonId: str
    leftCandidateId: str
    rightCandidateId: str
    outcome: str
    inconsistentAxes: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewPairDisagreement:
        outcome = require_text(payload, "outcome").lower()
        if outcome not in COMPARISON_OUTCOMES:
            raise ContractValidationError(
                "comparison outcome must be one of: "
                + ", ".join(sorted(COMPARISON_OUTCOMES))
            )
        left = require_text(payload, "leftCandidateId")
        right = require_text(payload, "rightCandidateId")
        if left == right:
            raise ContractValidationError("a candidate pair cannot compare a candidate to itself")
        return cls(
            comparisonId=require_text(payload, "comparisonId"),
            leftCandidateId=left,
            rightCandidateId=right,
            outcome=outcome,
            inconsistentAxes=_validated_axes(payload, "inconsistentAxes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparisonId": self.comparisonId,
            "leftCandidateId": self.leftCandidateId,
            "rightCandidateId": self.rightCandidateId,
            "outcome": self.outcome,
            "inconsistentAxes": list(self.inconsistentAxes),
        }


@dataclass(frozen=True, slots=True)
class ReviewEscalation:
    """An escalation marker for the joint decision; it never executes itself."""

    required: bool
    reason: str
    status: str = ESCALATION_STATUS_FLAGGED_ONLY

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewEscalation:
        status = require_text(payload, "status")
        if status != ESCALATION_STATUS_FLAGGED_ONLY:
            raise ContractValidationError(
                "review escalation is marked only; status must stay "
                f"{ESCALATION_STATUS_FLAGGED_ONLY}, got {status}"
            )
        return cls(
            required=bool(payload.get("required")),
            reason=str(payload.get("reason") or "").strip(),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ReviewDisagreementArtifact:
    """Reviewer-disagreement projection over one closed review round."""

    reviewRoundId: str
    reviewContextId: str
    candidatePairs: tuple[ReviewPairDisagreement, ...]
    reviewerScoreRefs: tuple[ReviewScoreRef, ...]
    disagreementAxes: tuple[str, ...]
    disagreementMetrics: tuple[dict[str, Any], ...]
    escalation: ReviewEscalation

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewDisagreementArtifact:
        raw_escalation = payload.get("escalation")
        escalation = ReviewEscalation.from_dict(
            raw_escalation if isinstance(raw_escalation, Mapping) else {}
        )
        metrics: list[dict[str, Any]] = []
        for item in require_list(payload, "disagreementMetrics"):
            if not isinstance(item, Mapping):
                raise ContractValidationError("disagreement metrics must be objects")
            axis = require_text(item, "axis")
            if axis in AUXILIARY_REVIEW_DIAGNOSTIC_AXES:
                raise ContractValidationError(
                    "auxiliary diagnostics can never be disagreement axes: " + axis
                )
            if axis not in REVIEW_DISAGREEMENT_DECISION_AXES:
                raise ContractValidationError(
                    "disagreement metrics are restricted to the five decision "
                    f"dimensions, unsupported: {axis}"
                )
            metrics.append(
                {
                    "axis": axis,
                    "directionInconsistencyCount": require_int(
                        item, "directionInconsistencyCount"
                    ),
                }
            )
        artifact = cls(
            reviewRoundId=require_text(payload, "reviewRoundId"),
            reviewContextId=require_text(payload, "reviewContextId"),
            candidatePairs=tuple(
                ReviewPairDisagreement.from_dict(item)
                for item in require_list(payload, "candidatePairs")
            ),
            reviewerScoreRefs=tuple(
                ReviewScoreRef.from_dict(item)
                for item in require_list(payload, "reviewerScoreRefs")
            ),
            disagreementAxes=_validated_axes(payload, "disagreementAxes"),
            disagreementMetrics=tuple(metrics),
            escalation=escalation,
        )
        metric_axes = {str(item["axis"]) for item in artifact.disagreementMetrics}
        missing_metrics = set(artifact.disagreementAxes) - metric_axes
        if missing_metrics:
            raise ContractValidationError(
                "every disagreement axis requires a metric entry: "
                + ", ".join(sorted(missing_metrics))
            )
        zero_metrics = {
            str(item["axis"])
            for item in artifact.disagreementMetrics
            if item["directionInconsistencyCount"] == 0
        }
        leaked = zero_metrics & set(artifact.disagreementAxes)
        if leaked:
            raise ContractValidationError(
                "a disagreement axis must carry a positive inconsistency count: "
                + ", ".join(sorted(leaked))
            )
        if artifact.escalation.required and not artifact.disagreementAxes:
            raise ContractValidationError(
                "escalation requires at least one disagreement axis"
            )
        return artifact

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewRoundId": self.reviewRoundId,
            "reviewContextId": self.reviewContextId,
            "candidatePairs": [item.to_dict() for item in self.candidatePairs],
            "reviewerScoreRefs": [item.to_dict() for item in self.reviewerScoreRefs],
            "disagreementAxes": list(self.disagreementAxes),
            "disagreementMetrics": [dict(item) for item in self.disagreementMetrics],
            "escalation": self.escalation.to_dict(),
        }


def inconsistent_axes_for_pair(
    left_scores: Mapping[str, Any],
    right_scores: Mapping[str, Any],
    outcome: str,
) -> tuple[str, ...]:
    """Return the decision axes whose score direction contradicts the outcome.

    The reflection scores give a per-axis direction between the two
    candidates; a pairwise outcome direction that contradicts an axis
    direction (winner behind on that axis) is a reviewer disagreement on that
    axis.  ``tie`` outcomes never contradict, and only the five decision
    dimensions are ever inspected.
    """

    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome not in COMPARISON_OUTCOMES:
        raise ContractValidationError(
            "comparison outcome must be one of: " + ", ".join(sorted(COMPARISON_OUTCOMES))
        )
    if normalized_outcome == "tie":
        return ()
    winner = "left" if normalized_outcome == "left_wins" else "right"
    inconsistent: list[str] = []
    for axis in REVIEW_DISAGREEMENT_DECISION_AXES:
        left_value = left_scores.get(axis)
        right_value = right_scores.get(axis)
        if not isinstance(left_value, (int, float)) or isinstance(left_value, bool):
            continue
        if not isinstance(right_value, (int, float)) or isinstance(right_value, bool):
            continue
        ahead = "left" if float(left_value) > float(right_value) else (
            "right" if float(right_value) > float(left_value) else "tie"
        )
        if ahead not in ("tie", winner):
            inconsistent.append(axis)
    return tuple(inconsistent)


__all__ = [
    "AUXILIARY_REVIEW_DIAGNOSTIC_AXES",
    "ESCALATION_STATUS_FLAGGED_ONLY",
    "REVIEW_ASSIGNMENT_SOURCES",
    "REVIEW_DISAGREEMENT_DECISION_AXES",
    "REVIEW_DISAGREEMENT_SCHEMA_VERSION",
    "REVIEW_EXECUTION_MODES",
    "REVIEW_INDEPENDENCE_SCHEMA_VERSION",
    "REVIEW_STEP_NAMES",
    "ReviewDisagreementArtifact",
    "ReviewEscalation",
    "ReviewPairDisagreement",
    "ReviewScoreRef",
    "ReviewerIndependenceRecord",
    "inconsistent_axes_for_pair",
    "review_step_identity",
    "reviewer_independence_summary",
    "validate_step_independence",
]
