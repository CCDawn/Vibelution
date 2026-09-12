"""Frozen per-round plan that binds protocol and controlled candidates."""
from __future__ import annotations

from typing import Literal

from .candidate import CudaCandidateRef
from .contracts import Contract, Identity, Text
from .measurement import MeasurementProtocolRef

OPTIMIZATION_PLAN_ARTIFACT_KIND = "optimization_plan"


class OptimizationPlan(Contract):
    """The immutable execution handoff for one optimization round.

    ``protocolRef`` points to the frozen measurement protocol artifact.  The
    three candidate refs carry the controlled implementation parameters and
    source identity needed to reconstruct a trial after process recovery.
    """

    schemaVersion: Literal[1] = 1
    planId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    protocolRef: MeasurementProtocolRef
    baselineCandidateRef: CudaCandidateRef
    parentCandidateRef: CudaCandidateRef
    candidateRef: CudaCandidateRef
    objective: Text
    evaluation: Text

__all__ = ["OPTIMIZATION_PLAN_ARTIFACT_KIND", "OptimizationPlan"]
