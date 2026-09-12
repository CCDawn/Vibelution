"""Round-scoped evidence requests and accepted knowledge snapshots."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contracts import ArtifactRef, Contract, Identity, Text


class OperatorKnowledgeRequest(Contract):
    schemaVersion: Literal[1] = 1
    teamId: Identity
    researchProjectId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    runId: Identity
    hypothesisRef: ArtifactRef
    evidenceGaps: tuple[Text, ...] = Field(max_length=12)
    observationRefs: tuple[ArtifactRef, ...] = Field(min_length=1, max_length=24)
    managedSourceRootIds: tuple[Identity, ...] = Field(default=(), max_length=32)
    sourcePolicyVersion: Identity
    # This is a frozen server policy, never a model-provided instruction.
    sourcePolicy: dict
    reuseRequirements: dict


class AcceptedOperatorPackage(Contract):
    invocationId: Identity
    canonicalRef: Text
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class OperatorKnowledgeSnapshot(Contract):
    schemaVersion: Literal[1] = 1
    optimizationCampaignId: Identity
    roundId: Identity
    runId: Identity
    requestRef: ArtifactRef
    hypothesisRef: ArtifactRef
    mode: Literal["existing_observations", "accepted_packages"]
    observationRefs: tuple[ArtifactRef, ...] = Field(min_length=1, max_length=24)
    packages: tuple[AcceptedOperatorPackage, ...] = Field(default=(), max_length=24)
    # Collection/acceptance does not establish the hypothesis scientifically.
    evidenceGaps: tuple[Text, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def sources_match_mode(self):
        if self.mode == "existing_observations" and (
            self.packages or self.evidenceGaps
        ):
            raise ValueError(
                "Existing observations require no declared collection gaps"
            )
        if self.mode == "accepted_packages" and not self.packages:
            raise ValueError("Accepted package mode requires a verified package")
        return self
