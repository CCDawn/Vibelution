"""Frozen Challenge Cup rubric evaluation contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import require_list, require_mapping, require_score, require_text


@dataclass(frozen=True, slots=True)
class CompetitionEvaluationSnapshot:
    evaluationId: str
    runId: str
    rubricVersion: str
    dimensionScores: dict[str, float]
    claimCoverage: float
    evidenceCoverage: float
    experimentCoverage: float
    deliverableCoverage: float
    blockingWarnings: tuple[str, ...]
    reviewerRefs: tuple[str, ...]
    evaluatedAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CompetitionEvaluationSnapshot:
        raw_dimensions = require_mapping(payload, "dimensionScores")
        dimensions = {
            str(key): require_score(value, f"dimensionScores.{key}")
            for key, value in raw_dimensions.items()
        }
        return cls(
            evaluationId=require_text(payload, "evaluationId"),
            runId=require_text(payload, "runId"),
            rubricVersion=require_text(payload, "rubricVersion"),
            dimensionScores=dimensions,
            claimCoverage=require_score(payload.get("claimCoverage"), "claimCoverage"),
            evidenceCoverage=require_score(
                payload.get("evidenceCoverage"), "evidenceCoverage"
            ),
            experimentCoverage=require_score(
                payload.get("experimentCoverage"), "experimentCoverage"
            ),
            deliverableCoverage=require_score(
                payload.get("deliverableCoverage"), "deliverableCoverage"
            ),
            blockingWarnings=tuple(
                str(item) for item in require_list(payload, "blockingWarnings")
            ),
            reviewerRefs=tuple(
                str(item) for item in require_list(payload, "reviewerRefs")
            ),
            evaluatedAt=require_text(payload, "evaluatedAt"),
        )

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockingWarnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluationId": self.evaluationId,
            "runId": self.runId,
            "rubricVersion": self.rubricVersion,
            "dimensionScores": copy.deepcopy(self.dimensionScores),
            "claimCoverage": self.claimCoverage,
            "evidenceCoverage": self.evidenceCoverage,
            "experimentCoverage": self.experimentCoverage,
            "deliverableCoverage": self.deliverableCoverage,
            "blockingWarnings": list(self.blockingWarnings),
            "reviewerRefs": list(self.reviewerRefs),
            "evaluatedAt": self.evaluatedAt,
        }
