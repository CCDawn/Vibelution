"""Multi-round hypothesis review contract with fail-closed completeness checks.

A ``HypothesisRound`` is the closed-loop artifact that turns two or more
substantially different hypothesis candidates into a decision.  It carries:

- at least two distinct candidates, each scored independently across seven
  fixed review dimensions by a reviewer agent;
- pairwise comparisons covering every unordered candidate pair;
- a Pareto analysis that classifies every candidate as front or dominated;
- a MetaReview with one recommendation and an acceptance flag;
- the full scope identity (six formal fields + owning agent + mode), the
  lineage of prior rounds/candidates it was derived from, and the meeting
  refs (meeting round, digest, decision) that closed it.

Parsing fails closed: a round missing any required field, dimension, pair
comparison, Pareto classification, MetaReview, or meeting ref cannot be
accepted as complete.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_score,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, scope_hash_for

SCORE_DIMENSIONS = (
    "novelty",
    "competitionFit",
    "falsifiability",
    "evidenceSupport",
    "feasibility",
    "replicability",
    "scopeAlignment",
)

MIN_CANDIDATES = 2
ROUND_STATUSES = {"open", "reviewed", "closed"}
COMPARISON_OUTCOMES = {"left_wins", "right_wins", "tie"}
LINEAGE_KINDS = {"round", "candidate", "baseline"}
MEETING_REF_KINDS = {"meeting_round", "meeting_digest", "decision_record"}


def _scope_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    identity = {field: require_text(payload, field) for field in REQUIRED_SCOPE_FIELDS}
    identity["agentId"] = require_text(payload, "agentId")
    identity["mode"] = require_text(payload, "mode").lower()
    return identity


def _validated_scope_hash(payload: Mapping[str, Any], identity: Mapping[str, str]) -> str:
    supplied = require_text(payload, "scopeHash").lower()
    expected = scope_hash_for(
        **{field: identity[field] for field in REQUIRED_SCOPE_FIELDS},
        agent_id=identity["agentId"],
        mode=identity["mode"],
    )
    if supplied != expected:
        raise ContractValidationError("scopeHash does not match the round scope identity")
    return supplied


def _candidate_id_set(candidates: tuple["HypothesisRoundCandidate", ...]) -> set[str]:
    return {item.candidateId for item in candidates}


@dataclass(frozen=True, slots=True)
class HypothesisRoundCandidate:
    """One scored candidate in a review round across seven fixed dimensions."""

    candidateId: str
    claim: str
    rationale: str
    differenceFromAlternatives: str
    lineageRefs: tuple[str, ...]
    scores: dict[str, float]
    reviewedBy: str
    status: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisRoundCandidate:
        raw_scores = payload.get("scores")
        if not isinstance(raw_scores, Mapping):
            raise ContractValidationError("candidate scores must be an object")
        missing = [key for key in SCORE_DIMENSIONS if key not in raw_scores]
        if missing:
            raise ContractValidationError(
                "missing candidate review dimensions: " + ", ".join(missing)
            )
        scores = {
            key: require_score(raw_scores[key], f"scores.{key}")
            for key in SCORE_DIMENSIONS
        }
        return cls(
            candidateId=require_text(payload, "candidateId"),
            claim=require_text(payload, "claim"),
            rationale=str(payload.get("rationale") or "").strip(),
            differenceFromAlternatives=require_text(
                payload, "differenceFromAlternatives"
            ),
            lineageRefs=tuple(
                str(item) for item in require_list(payload, "lineageRefs")
            ),
            scores=scores,
            reviewedBy=require_text(payload, "reviewedBy"),
            status=require_text(payload, "status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidateId,
            "claim": self.claim,
            "rationale": self.rationale,
            "differenceFromAlternatives": self.differenceFromAlternatives,
            "lineageRefs": list(self.lineageRefs),
            "scores": dict(self.scores),
            "reviewedBy": self.reviewedBy,
            "status": self.status,
        }

    def is_substantially_different(self, other: "HypothesisRoundCandidate") -> bool:
        """Two candidates are substantially different when their claims diverge.

        A duplicate claim or identical difference statement is not a real
        alternative and must not count toward the minimum candidate count.
        """
        normalized_self = " ".join(self.claim.lower().split())
        normalized_other = " ".join(other.claim.lower().split())
        if normalized_self == normalized_other:
            return False
        difference_self = " ".join(self.differenceFromAlternatives.lower().split())
        difference_other = " ".join(other.differenceFromAlternatives.lower().split())
        if difference_self and difference_self == difference_other:
            return False
        return True


@dataclass(frozen=True, slots=True)
class HypothesisPairwiseComparison:
    """One independent pairwise comparison between two candidates."""

    comparisonId: str
    leftCandidateId: str
    rightCandidateId: str
    reviewerAgentId: str
    outcome: str
    justification: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisPairwiseComparison:
        outcome = require_text(payload, "outcome").lower()
        if outcome not in COMPARISON_OUTCOMES:
            raise ContractValidationError(
                "comparison outcome must be one of: "
                + ", ".join(sorted(COMPARISON_OUTCOMES))
            )
        return cls(
            comparisonId=require_text(payload, "comparisonId"),
            leftCandidateId=require_text(payload, "leftCandidateId"),
            rightCandidateId=require_text(payload, "rightCandidateId"),
            reviewerAgentId=require_text(payload, "reviewerAgentId"),
            outcome=outcome,
            justification=require_text(payload, "justification"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparisonId": self.comparisonId,
            "leftCandidateId": self.leftCandidateId,
            "rightCandidateId": self.rightCandidateId,
            "reviewerAgentId": self.reviewerAgentId,
            "outcome": self.outcome,
            "justification": self.justification,
        }


@dataclass(frozen=True, slots=True)
class HypothesisParetoAnalysis:
    """Pareto classification of every candidate into front or dominated."""

    paretoFrontCandidateIds: tuple[str, ...]
    dominatedCandidateIds: tuple[str, ...]
    analystAgentId: str
    notes: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisParetoAnalysis:
        return cls(
            paretoFrontCandidateIds=tuple(
                str(item) for item in require_list(payload, "paretoFrontCandidateIds")
            ),
            dominatedCandidateIds=tuple(
                str(item) for item in require_list(payload, "dominatedCandidateIds")
            ),
            analystAgentId=str(payload.get("analystAgentId") or "").strip(),
            notes=str(payload.get("notes") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paretoFrontCandidateIds": list(self.paretoFrontCandidateIds),
            "dominatedCandidateIds": list(self.dominatedCandidateIds),
            "analystAgentId": self.analystAgentId,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class HypothesisMetaReview:
    """Final agent review that recommends one candidate and accepts/withholds it."""

    metaReviewId: str
    reviewerAgentId: str
    recommendationCandidateId: str
    rationale: str
    riskNotes: str
    accepted: bool

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisMetaReview:
        return cls(
            metaReviewId=str(payload.get("metaReviewId") or "").strip(),
            reviewerAgentId=str(payload.get("reviewerAgentId") or "").strip(),
            recommendationCandidateId=str(
                payload.get("recommendationCandidateId") or ""
            ).strip(),
            rationale=str(payload.get("rationale") or "").strip(),
            riskNotes=str(payload.get("riskNotes") or "").strip(),
            accepted=bool(payload.get("accepted")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metaReviewId": self.metaReviewId,
            "reviewerAgentId": self.reviewerAgentId,
            "recommendationCandidateId": self.recommendationCandidateId,
            "rationale": self.rationale,
            "riskNotes": self.riskNotes,
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class HypothesisLineageRef:
    """A provenance pointer to the round/candidate/baseline this round derives from."""

    kind: str
    id: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisLineageRef:
        kind = require_text(payload, "kind").lower()
        if kind not in LINEAGE_KINDS:
            raise ContractValidationError(
                "lineage kind must be one of: " + ", ".join(sorted(LINEAGE_KINDS))
            )
        return cls(kind=kind, id=require_text(payload, "id"))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True, slots=True)
class HypothesisMeetingRef:
    """A provenance pointer to the meeting artifacts that closed this round."""

    kind: str
    id: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisMeetingRef:
        kind = require_text(payload, "kind").lower()
        if kind not in MEETING_REF_KINDS:
            raise ContractValidationError(
                "meeting ref kind must be one of: "
                + ", ".join(sorted(MEETING_REF_KINDS))
            )
        return cls(kind=kind, id=require_text(payload, "id"))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True, slots=True)
class HypothesisRound:
    """Complete, hash-bound hypothesis review round artifact."""

    roundId: str
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    status: str
    candidates: tuple[HypothesisRoundCandidate, ...]
    pairwiseComparisons: tuple[HypothesisPairwiseComparison, ...]
    pareto: HypothesisParetoAnalysis
    metaReview: HypothesisMetaReview
    lineage: tuple[HypothesisLineageRef, ...]
    meetingRefs: tuple[HypothesisMeetingRef, ...]
    createdAt: str
    closedAt: str
    closedBy: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisRound:
        identity = _scope_identity(payload)
        status = require_text(payload, "status").lower()
        if status not in ROUND_STATUSES:
            raise ContractValidationError(
                "round status must be one of: " + ", ".join(sorted(ROUND_STATUSES))
            )
        raw_candidates = [
            HypothesisRoundCandidate.from_dict(item)
            for item in require_list(payload, "candidates")
        ]
        if len(raw_candidates) < MIN_CANDIDATES:
            raise ContractValidationError(
                "a hypothesis round requires at least two candidates"
            )
        if len({item.candidateId for item in raw_candidates}) != len(raw_candidates):
            raise ContractValidationError("candidateId values must be unique")
        if not any(
            left.is_substantially_different(right)
            for index, left in enumerate(raw_candidates)
            for right in raw_candidates[index + 1 :]
        ):
            raise ContractValidationError(
                "a hypothesis round requires at least two substantially different candidates"
            )
        pairwise = tuple(
            HypothesisPairwiseComparison.from_dict(item)
            for item in require_list(payload, "pairwiseComparisons")
        )
        pareto = HypothesisParetoAnalysis.from_dict(
            payload.get("pareto") if isinstance(payload.get("pareto"), Mapping) else {}
        )
        raw_meta = payload.get("metaReview")
        meta_review = (
            HypothesisMetaReview.from_dict(raw_meta)
            if isinstance(raw_meta, Mapping)
            else HypothesisMetaReview.from_dict({})
        )
        lineage = tuple(
            HypothesisLineageRef.from_dict(item)
            for item in require_list(payload, "lineage")
        )
        meeting_refs = tuple(
            HypothesisMeetingRef.from_dict(item)
            for item in require_list(payload, "meetingRefs")
        )
        candidate_ids = _candidate_id_set(raw_candidates)
        for comparison in pairwise:
            if comparison.leftCandidateId not in candidate_ids:
                raise ContractValidationError(
                    f"comparison references unknown candidate {comparison.leftCandidateId}"
                )
            if comparison.rightCandidateId not in candidate_ids:
                raise ContractValidationError(
                    f"comparison references unknown candidate {comparison.rightCandidateId}"
                )
            if comparison.leftCandidateId == comparison.rightCandidateId:
                raise ContractValidationError(
                    "a pairwise comparison cannot compare a candidate to itself"
                )
        front_ids = set(pareto.paretoFrontCandidateIds)
        dominated_ids = set(pareto.dominatedCandidateIds)
        if front_ids & dominated_ids:
            raise ContractValidationError(
                "a candidate cannot be both on the Pareto front and dominated"
            )
        unknown = (front_ids | dominated_ids) - candidate_ids
        if unknown:
            raise ContractValidationError(
                "Pareto analysis references unknown candidates: "
                + ", ".join(sorted(unknown))
            )
        if meta_review.recommendationCandidateId and meta_review.recommendationCandidateId not in candidate_ids:
            raise ContractValidationError(
                "metaReview recommendation references an unknown candidate"
            )
        return cls(
            roundId=require_text(payload, "roundId"),
            **identity,
            scopeHash=_validated_scope_hash(payload, identity),
            status=status,
            candidates=tuple(raw_candidates),
            pairwiseComparisons=pairwise,
            pareto=pareto,
            metaReview=meta_review,
            lineage=lineage,
            meetingRefs=meeting_refs,
            createdAt=require_text(payload, "createdAt"),
            closedAt=str(payload.get("closedAt") or "").strip(),
            closedBy=str(payload.get("closedBy") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "roundId": self.roundId,
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "status": self.status,
            "candidates": [item.to_dict() for item in self.candidates],
            "pairwiseComparisons": [item.to_dict() for item in self.pairwiseComparisons],
            "pareto": self.pareto.to_dict(),
            "metaReview": self.metaReview.to_dict(),
            "lineage": [item.to_dict() for item in self.lineage],
            "meetingRefs": [item.to_dict() for item in self.meetingRefs],
            "createdAt": self.createdAt,
            "closedAt": self.closedAt,
            "closedBy": self.closedBy,
        }

    def candidate_pairs(self) -> list[tuple[str, str]]:
        ids = [item.candidateId for item in self.candidates]
        pairs: list[tuple[str, str]] = []
        for index, left in enumerate(ids):
            for right in ids[index + 1 :]:
                pairs.append((left, right))
        return pairs

    def _pair_covered(self, left: str, right: str) -> bool:
        for comparison in self.pairwiseComparisons:
            a = comparison.leftCandidateId
            b = comparison.rightCandidateId
            if {a, b} == {left, right}:
                return True
        return False

    def validate_complete(self) -> None:
        """Enforce full closure semantics for a reviewed/closed round.

        Raises :class:`ContractValidationError` when any required item is
        missing: pair coverage, Pareto coverage, MetaReview, or meeting refs.
        """
        if self.status not in {"reviewed", "closed"}:
            raise ContractValidationError(
                "a complete round must be reviewed or closed"
            )
        if not self.closedAt or not self.closedBy:
            raise ContractValidationError(
                "a closed round requires closedAt and closedBy"
            )
        if len(self.candidates) < MIN_CANDIDATES:
            raise ContractValidationError(
                "a hypothesis round requires at least two candidates"
            )
        for pair in self.candidate_pairs():
            if not self._pair_covered(*pair):
                raise ContractValidationError(
                    f"missing pairwise comparison between {pair[0]} and {pair[1]}"
                )
        if not self.pareto.paretoFrontCandidateIds:
            raise ContractValidationError("a closed round requires a non-empty Pareto front")
        candidate_ids = _candidate_id_set(self.candidates)
        classified = set(self.pareto.paretoFrontCandidateIds) | set(
            self.pareto.dominatedCandidateIds
        )
        missing_classification = candidate_ids - classified
        if missing_classification:
            raise ContractValidationError(
                "Pareto analysis must classify every candidate: "
                + ", ".join(sorted(missing_classification))
            )
        if not self.pareto.analystAgentId:
            raise ContractValidationError("Pareto analysis requires an analystAgentId")
        if not self.metaReview.reviewerAgentId:
            raise ContractValidationError("a closed round requires a MetaReview reviewer")
        if not self.metaReview.recommendationCandidateId:
            raise ContractValidationError(
                "a closed round requires a MetaReview recommendation"
            )
        digest_refs = [ref for ref in self.meetingRefs if ref.kind == "meeting_digest"]
        decision_refs = [
            ref for ref in self.meetingRefs if ref.kind == "decision_record"
        ]
        if not digest_refs or not decision_refs:
            raise ContractValidationError(
                "a closed round requires meeting digest and decision refs"
            )
