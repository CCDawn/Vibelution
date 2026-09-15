"""Versioned operator contracts; workflow node state remains in the Ledger."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .candidate import Contract, CudaCandidateRef, Digest, Identity, Text
from .model_budget_contracts import OperatorDiscussionBudget, OperatorModelCallBudget


class ArtifactRef(Contract):
    artifactId: Identity
    kind: Identity
    sha256: Digest


STAGE2_SEED_ARTIFACT_KIND = "operator_stage2_seed"


class Stage2SeedRef(ArtifactRef):
    """Reference to the immutable handoff that starts experiment iteration."""

    kind: Literal["operator_stage2_seed"] = STAGE2_SEED_ARTIFACT_KIND
    runId: Identity


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
    knowledge: OperatorModelCallBudget | None = None
    planning: OperatorModelCallBudget | None = None
    decision: OperatorModelCallBudget | None = None


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
    previousRunIds: tuple[Identity, ...] = ()
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
    experimentStage: Literal["foundation_experiment", "experiment_iteration"] = (
        "foundation_experiment"
    )
    stage2SeedRef: Stage2SeedRef | None = None


class OperatorStage2Seed(Contract):
    """Exact, immutable evidence handoff from a completed foundation round."""

    schemaVersion: Literal[1] = 1
    optimizationCampaignId: Identity
    sourceRoundId: Identity
    sourceRunId: Identity
    baselineRunId: Identity
    baselineRef: ArtifactRef
    protocolRef: MeasurementProtocolRef
    hypothesisRef: ArtifactRef | None = None
    hypothesisRunId: str = ""
    hypothesisRoundId: str = ""
    knowledgeRef: ArtifactRef | None = None
    knowledgeRunId: str = ""
    planRef: ArtifactRef | None = None
    planRunId: str = ""
    evaluationRef: ArtifactRef
    feedbackRef: ArtifactRef
    attemptedCandidateRefs: tuple[CudaCandidateRef, ...] = ()

    @model_validator(mode="after")
    def referenced_sources_have_owners(self):
        if (
            self.hypothesisRef is None
            and (self.hypothesisRunId or self.hypothesisRoundId)
        ) or (
            self.hypothesisRef is not None
            and (not self.hypothesisRunId or not self.hypothesisRoundId)
        ):
            raise ValueError("Stage 2 hypothesis reference requires its run and round")
        for ref, owner, label in (
            (self.knowledgeRef, self.knowledgeRunId, "knowledge"),
            (self.planRef, self.planRunId, "plan"),
        ):
            if (ref is None) != (not owner):
                raise ValueError(f"Stage 2 {label} reference requires its owning run")
        return self


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


class ModelBudgetRevision(Contract):
    previousBudget: CampaignBudget
    budget: CampaignBudget
    authorizedBy: Text
    authorizedAt: Text
    campaignVersion: int = Field(ge=1, strict=True)


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
    modelBudgetRevisions: tuple[ModelBudgetRevision, ...] = ()
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
    experimentStage: Literal[
        "baseline", "foundation_experiment", "experiment_iteration"
    ] = "foundation_experiment"
    stage2SeedRef: Stage2SeedRef | None = None

    @model_validator(mode="after")
    def require_one_work_identity(self):
        if bool(self.baselineSetupId) == bool(self.roundId):
            raise ValueError("Exactly one of baselineSetupId and roundId is required")
        if self.roundId and self.parentCandidateRef is None:
            raise ValueError("An optimization round requires its fixed parent candidate")
        if self.baselineCandidateRef is None:
            raise ValueError("An operator run requires its fixed baseline candidate")
        if self.baselineSetupId and self.experimentStage != "baseline":
            raise ValueError("A baseline setup must use the baseline experiment stage")
        if self.roundId and self.experimentStage == "baseline":
            raise ValueError("An optimization round cannot use the baseline experiment stage")
        if (self.experimentStage == "experiment_iteration") != (
            self.stage2SeedRef is not None
        ):
            raise ValueError("Experiment iteration requires exactly one Stage 2 seed")
        return self
