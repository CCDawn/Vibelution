"""Versioned operator contracts; workflow node state remains in the Ledger."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .candidate import Contract, CudaCandidateRef, Digest, Identity, Text
from .model_budget_contracts import OperatorDiscussionBudget


class ArtifactRef(Contract):
    artifactId: Identity
    kind: Identity
    sha256: Digest


MEASUREMENT_PROTOCOL_ARTIFACT_KIND = "operator_measurement_protocol"


class MeasurementProtocolRef(ArtifactRef):
    """Canonical reference to a frozen measurement protocol artifact."""

    kind: Literal["operator_measurement_protocol"] = MEASUREMENT_PROTOCOL_ARTIFACT_KIND
    runId: Identity


class OperatorObjective(Contract):
    schemaVersion: Literal[1] = 1
    operator: Literal["softmax"] = "softmax"
    primaryMetric: Literal["latency_ms"] = "latency_ms"
    preserveSemantics: Literal[True] = True
    allowedChanges: tuple[Literal["parameters", "tiling", "parallel_layout", "fusion", "equivalent_math"], ...] = (
        "parameters", "tiling", "parallel_layout", "fusion", "equivalent_math",
    )
    dtypes: tuple[Literal["float16", "float32"], ...] = ("float16", "float32")


class CampaignBudget(Contract):
    currency: Literal["CNY", "USD"] = "CNY"
    modelCostLimit: float = Field(0, ge=0)
    gpuSecondsLimit: int = Field(0, ge=0, strict=True)
    maxRounds: int = Field(3, ge=1, le=100, strict=True)
    maxTrialsPerRound: int = Field(12, ge=1, le=12, strict=True)
    trialTimeoutSeconds: int = Field(300, ge=1, le=3600, strict=True)
    finalValidationFraction: float = Field(0.2, gt=0, lt=1)
    authorized: bool = False
    discussion: OperatorDiscussionBudget | None = None


class OptimizationHypothesis(Contract):
    schemaVersion: Literal[1] = 1
    hypothesisId: Identity
    revision: int = Field(1, ge=1, strict=True)
    optimizationCampaignId: Identity
    roundId: Identity
    parentCandidateRef: CudaCandidateRef
    observationRefs: tuple[ArtifactRef, ...] = Field(min_length=1, max_length=24)
    proposedChange: Text
    mechanism: Text
    prediction: Text
    counterevidence: Text
    roi: Literal["high", "medium", "low"]
    roiReason: Text
    evidenceGaps: tuple[Text, ...] = Field(default=(), max_length=12)


class OptimizationRound(Contract):
    roundId: Identity
    runId: Identity
    ordinal: int = Field(ge=1, strict=True)
    baselineCandidateRef: CudaCandidateRef
    parentCandidateRef: CudaCandidateRef
    protocolRef: MeasurementProtocolRef
    hypothesisRef: ArtifactRef | None = None
    knowledgeRef: ArtifactRef | None = None
    planRef: ArtifactRef | None = None
    experimentCampaignId: str = ""
    evaluationRef: ArtifactRef | None = None
    feedbackRef: ArtifactRef | None = None


class GpuReservation(Contract):
    reservationId: Identity
    runId: Identity
    protocolHash: Digest
    phase: Literal["tuning", "holdout"]
    reservedSeconds: int = Field(ge=1, strict=True)
    consumedSeconds: float | None = Field(None, ge=0)
    measurementRef: ArtifactRef | None = None
    outcome: Literal["succeeded", "failed", "cancelled", "timed_out"] | None = None

    @model_validator(mode="after")
    def settlement_is_complete(self):
        settled = (self.consumedSeconds is not None, self.measurementRef is not None, self.outcome is not None)
        if any(settled) and not all(settled):
            raise ValueError("A settlement requires actual usage, measurement reference and outcome")
        return self


class OptimizationCampaign(Contract):
    schemaVersion: Literal[1] = 1
    optimizationCampaignId: Identity
    teamId: Identity
    researchProjectId: Identity
    title: Text
    revision: int = Field(1, ge=1, strict=True)
    objective: OperatorObjective
    budget: CampaignBudget
    authorizedBy: str = ""
    gpuReservations: tuple[GpuReservation, ...] = ()
    status: Literal["draft", "running", "paused", "completed", "cancelled", "blocked"] = "draft"
    baselineSetupId: Identity
    baselineRunId: str = ""
    baselineRef: ArtifactRef | None = None
    baselineCandidateRef: CudaCandidateRef | None = None
    bestCandidateRef: CudaCandidateRef | None = None
    rounds: tuple[OptimizationRound, ...] = ()
    activeRunId: str = ""
    createdAt: Text
    updatedAt: Text


class OperatorRunContext(Contract):
    kind: Literal["operator_optimization"] = "operator_optimization"
    optimizationCampaignId: Identity
    researchProjectId: Identity
    objective: OperatorObjective
    baselineSetupId: str = ""
    roundId: str = ""
    baselineCandidateRef: CudaCandidateRef | None = None
    parentCandidateRef: CudaCandidateRef | None = None
    baselineRef: ArtifactRef | None = None
    observationRefs: tuple[ArtifactRef, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def require_one_work_identity(self):
        if bool(self.baselineSetupId) == bool(self.roundId):
            raise ValueError("Exactly one of baselineSetupId and roundId is required")
        if self.roundId and self.parentCandidateRef is None:
            raise ValueError("An optimization round requires its fixed parent candidate")
        if self.baselineCandidateRef is None:
            raise ValueError("An operator run requires its fixed baseline candidate")
        return self
