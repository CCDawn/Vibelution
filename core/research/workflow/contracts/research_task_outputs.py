"""Strict Pydantic schemas for formal research task outputs."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ._canonical import sha256_hex

RESEARCH_TASK_OUTPUT_SCHEMA_VERSION = 1
ResearchTaskOutputStatus = Literal[
    "completed",
    "needs_more_evidence",
    "needs_revision",
    "blocked",
    "failed",
]

NonEmptyText = Annotated[str, Field(min_length=1)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class _StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HypothesisScoreVector(_StrictOutputModel):
    novelty: Score
    competitionFit: Score
    falsifiability: Score
    evidenceSupport: Score
    feasibility: Score


class HypothesisTaskCandidate(_StrictOutputModel):
    candidateId: NonEmptyText
    claim: NonEmptyText
    mechanism: NonEmptyText
    predictions: list[NonEmptyText]
    falsificationCriteria: list[NonEmptyText]
    evidenceRefs: list[NonEmptyText]
    counterEvidenceRefs: list[NonEmptyText]
    boundaryConditions: list[NonEmptyText]
    scores: HypothesisScoreVector
    derivedFromCandidateIds: list[NonEmptyText]
    status: Literal["draft", "reviewed", "selected", "rejected"]
    reviewRef: str


class EvidenceReasonedTaskOutput(_StrictOutputModel):
    schemaVersion: Literal[RESEARCH_TASK_OUTPUT_SCHEMA_VERSION]
    taskKind: str
    status: ResearchTaskOutputStatus
    reasoning: NonEmptyText
    evidenceRefs: list[NonEmptyText]

    @field_validator("evidenceRefs")
    @classmethod
    def _unique_evidence_refs(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("evidenceRefs values must be unique")
        return values


class HypothesisDesignOutput(EvidenceReasonedTaskOutput):
    taskKind: Literal["hypothesis_design"]
    maxEvolutionRounds: Annotated[int, Field(ge=1)]
    currentEvolutionRound: Annotated[int, Field(ge=1)]
    candidates: list[HypothesisTaskCandidate]

    @model_validator(mode="after")
    def _completed_output_is_complete(self) -> HypothesisDesignOutput:
        if self.currentEvolutionRound > self.maxEvolutionRounds:
            raise ValueError("currentEvolutionRound exceeds maxEvolutionRounds")
        if self.status == "completed" and not self.candidates:
            raise ValueError("completed hypothesis_design requires candidates")
        candidate_ids = [candidate.candidateId for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("hypothesis candidateId values must be unique")
        return self


ProtocolCheck = Literal["pass", "fail"]


class ProtocolReviewChecks(_StrictOutputModel):
    dataset: ProtocolCheck
    baseline: ProtocolCheck
    metric: ProtocolCheck
    seed: ProtocolCheck
    budget: ProtocolCheck
    stopCondition: ProtocolCheck
    smokePlan: ProtocolCheck


class ProtocolReviewFinding(_StrictOutputModel):
    code: NonEmptyText
    severity: Literal["blocking", "warning", "info"]
    summary: NonEmptyText
    evidenceRefs: list[NonEmptyText]


class ProtocolReviewOutput(EvidenceReasonedTaskOutput):
    taskKind: Literal["protocol_review"]
    decision: Literal[
        "approved",
        "changes_requested",
        "needs_more_evidence",
        "blocked",
    ]
    blockingIssueCount: Annotated[int, Field(ge=0)]
    openWaivers: Annotated[int, Field(ge=0)]
    checks: ProtocolReviewChecks
    findings: list[ProtocolReviewFinding]

    @model_validator(mode="after")
    def _approved_output_has_no_open_issues(self) -> ProtocolReviewOutput:
        if self.decision == "approved":
            if self.blockingIssueCount or self.openWaivers:
                raise ValueError(
                    "approved protocol review cannot have blockers or waivers"
                )
            if any(value != "pass" for value in self.checks.model_dump().values()):
                raise ValueError("approved protocol review requires passing checks")
        return self


class EvaluationDimensionScore(_StrictOutputModel):
    dimension: NonEmptyText
    score: Score
    reasoning: NonEmptyText
    evidenceRefs: list[NonEmptyText]


class ResultEvaluationOutput(EvidenceReasonedTaskOutput):
    taskKind: Literal["result_evaluation"]
    resultClassification: Literal[
        "proposal_only",
        "executed_positive",
        "executed_negative",
        "executed_inconclusive",
        "blocked",
        "failed",
    ]
    dimensionScores: list[EvaluationDimensionScore]
    claimCoverage: Score
    evidenceCoverage: Score
    experimentCoverage: Score
    deliverableCoverage: Score
    blockingWarnings: list[NonEmptyText]

    @model_validator(mode="after")
    def _dimension_scores_are_unique(self) -> ResultEvaluationOutput:
        dimensions = [item.dimension for item in self.dimensionScores]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("result evaluation dimensions must be unique")
        return self


ResearchTaskOutput = (
    HypothesisDesignOutput | ProtocolReviewOutput | ResultEvaluationOutput
)

_OUTPUT_MODELS: dict[str, type[EvidenceReasonedTaskOutput]] = {
    "hypothesis_design": HypothesisDesignOutput,
    "protocol_review": ProtocolReviewOutput,
    "result_evaluation": ResultEvaluationOutput,
}
_OUTPUT_ADAPTERS = {
    task_kind: TypeAdapter(model) for task_kind, model in _OUTPUT_MODELS.items()
}


def canonical_research_task_output_schema_bundle() -> dict[str, Any]:
    return {
        "schemaVersion": RESEARCH_TASK_OUTPUT_SCHEMA_VERSION,
        "schemas": {
            task_kind: copy.deepcopy(model.model_json_schema())
            for task_kind, model in _OUTPUT_MODELS.items()
        },
    }


def research_task_output_schema_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_hex(dict(payload))


RESEARCH_TASK_OUTPUT_SCHEMA_SHA256 = research_task_output_schema_sha256(
    canonical_research_task_output_schema_bundle()
)


def parse_research_task_output(
    task_kind: str,
    payload: Mapping[str, Any],
) -> ResearchTaskOutput:
    normalized_kind = str(task_kind or "").strip()
    adapter = _OUTPUT_ADAPTERS.get(normalized_kind)
    if adapter is None:
        raise ValueError(f"unsupported research task output kind: {normalized_kind}")
    payload_kind = str(payload.get("taskKind") or "").strip()
    if payload_kind != normalized_kind:
        raise ValueError(
            f"task output kind {payload_kind or '<empty>'} does not match {normalized_kind}"
        )
    return adapter.validate_python(dict(payload))


__all__ = [
    "RESEARCH_TASK_OUTPUT_SCHEMA_SHA256",
    "RESEARCH_TASK_OUTPUT_SCHEMA_VERSION",
    "EvidenceReasonedTaskOutput",
    "HypothesisDesignOutput",
    "HypothesisScoreVector",
    "HypothesisTaskCandidate",
    "ProtocolReviewChecks",
    "ProtocolReviewFinding",
    "ProtocolReviewOutput",
    "ResearchTaskOutput",
    "ResultEvaluationOutput",
    "canonical_research_task_output_schema_bundle",
    "parse_research_task_output",
    "research_task_output_schema_sha256",
]
