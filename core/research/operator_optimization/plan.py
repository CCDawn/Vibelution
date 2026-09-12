"""Frozen per-round plan that binds protocol and controlled candidates."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .candidate import CudaCandidateRef
from .contracts import ArtifactRef, Contract, Identity, Text
from .measurement import MeasurementProtocolRef

OPTIMIZATION_PLAN_ARTIFACT_KIND = "optimization_plan"


class EvidenceGapCheck(Contract):
    gap: Text
    experimentCheck: Text


class OptimizationPlan(Contract):
    """The immutable execution handoff for one optimization round.

    ``protocolRef`` points to the frozen measurement protocol artifact.  The
    three candidate refs carry the controlled implementation parameters and
    source identity needed to reconstruct a trial after process recovery.
    """

    schemaVersion: Literal[2] = 2
    planId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    hypothesisRef: ArtifactRef
    knowledgeRef: ArtifactRef
    protocolRef: MeasurementProtocolRef
    baselineCandidateRef: CudaCandidateRef
    parentCandidateRef: CudaCandidateRef
    candidateRef: CudaCandidateRef
    objective: Text
    evaluation: Text
    prediction: Text
    counterevidence: Text
    # A package can leave questions to be discriminated by the experiment.
    evidenceAssessment: Text
    gapChecks: tuple[EvidenceGapCheck, ...] = Field(default=(), max_length=12)
    trialCount: int = Field(ge=1, le=12, strict=True)
    trialTimeoutSeconds: int = Field(ge=1, le=3600, strict=True)

__all__ = ["OPTIMIZATION_PLAN_ARTIFACT_KIND", "OptimizationPlan"]
