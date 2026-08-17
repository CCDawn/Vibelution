"""Public contracts for team workflow experiment routes.

Read-only status and catalog views publish stable top-level fields. Plan,
hypothesis, run, and challenge-program write payloads still evolve across
dual-shape endpoints, so those routes keep the catch-all write envelope.
Routes must use response_model_exclude_unset=True so missing optional fields
stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentRouteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExperimentPlanningStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    latestExperimentRound: dict[str, Any] | None = None
    latestKnowledgeCollectionRound: dict[str, Any] | None = None
    activePlan: dict[str, Any] | None = None
    plans: list[dict[str, Any]] = Field(default_factory=list)
    lifecycleProjection: dict[str, Any] = Field(default_factory=dict)
    challengeProgramProjection: dict[str, Any] = Field(default_factory=dict)
    hypothesisCandidates: list[dict[str, Any]] = Field(default_factory=list)
    readyHypothesisCandidates: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    readiness: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    storagePath: str = ""
    nextActions: list[str] = Field(default_factory=list)
    updatedAt: str = ""


class ExperimentMethodCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    researchModes: list[dict[str, Any]] = Field(default_factory=list)
    experimentPurposes: list[dict[str, Any]] = Field(default_factory=list)
    methods: list[dict[str, Any]] = Field(default_factory=list)
    adapters: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class ChallengeQuestionRunStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    storePath: str = ""


class CandidateStoreListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
    workflowId: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    candidateCount: int = 0
    sourceFamilySummary: dict[str, Any] = Field(default_factory=dict)
    validationSummary: dict[str, Any] = Field(default_factory=dict)
    store: dict[str, Any] = Field(default_factory=dict)


class CandidateStoreValidationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""
