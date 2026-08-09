"""Bounded hypothesis portfolio contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_score,
    require_text,
)

_SCORE_KEYS = (
    "novelty",
    "competitionFit",
    "falsifiability",
    "evidenceSupport",
    "feasibility",
)


@dataclass(frozen=True, slots=True)
class HypothesisCandidate:
    candidateId: str
    claim: str
    scores: dict[str, float]
    counterEvidenceRefs: tuple[str, ...]
    derivedFromCandidateIds: tuple[str, ...]
    status: str
    reviewRef: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisCandidate:
        raw_scores = require_mapping(payload, "scores")
        missing = [key for key in _SCORE_KEYS if key not in raw_scores]
        if missing:
            raise ContractValidationError(
                f"missing hypothesis scores: {', '.join(missing)}"
            )
        scores = {
            key: require_score(raw_scores[key], f"scores.{key}") for key in _SCORE_KEYS
        }
        return cls(
            candidateId=require_text(payload, "candidateId"),
            claim=require_text(payload, "claim"),
            scores=scores,
            counterEvidenceRefs=tuple(
                str(item) for item in require_list(payload, "counterEvidenceRefs")
            ),
            derivedFromCandidateIds=tuple(
                str(item) for item in require_list(payload, "derivedFromCandidateIds")
            ),
            status=require_text(payload, "status"),
            reviewRef=str(payload.get("reviewRef") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidateId,
            "claim": self.claim,
            "scores": copy.deepcopy(self.scores),
            "counterEvidenceRefs": list(self.counterEvidenceRefs),
            "derivedFromCandidateIds": list(self.derivedFromCandidateIds),
            "status": self.status,
            "reviewRef": self.reviewRef,
        }


@dataclass(frozen=True, slots=True)
class HypothesisPortfolio:
    portfolioId: str
    runId: str
    maxCandidates: int
    maxEvolutionRounds: int
    candidates: tuple[HypothesisCandidate, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisPortfolio:
        candidates = tuple(
            HypothesisCandidate.from_dict(item)
            for item in require_list(payload, "candidates")
        )
        max_candidates = require_int(payload, "maxCandidates", minimum=1)
        if len(candidates) > max_candidates:
            raise ContractValidationError(
                "hypothesis candidate count exceeds maxCandidates"
            )
        if len({item.candidateId for item in candidates}) != len(candidates):
            raise ContractValidationError("candidateId values must be unique")
        return cls(
            portfolioId=require_text(payload, "portfolioId"),
            runId=require_text(payload, "runId"),
            maxCandidates=max_candidates,
            maxEvolutionRounds=require_int(payload, "maxEvolutionRounds", minimum=1),
            candidates=candidates,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolioId": self.portfolioId,
            "runId": self.runId,
            "maxCandidates": self.maxCandidates,
            "maxEvolutionRounds": self.maxEvolutionRounds,
            "candidates": [item.to_dict() for item in self.candidates],
        }
