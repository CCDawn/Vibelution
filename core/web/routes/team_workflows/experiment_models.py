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
    competitionProgramProjection: dict[str, Any] = Field(default_factory=dict)
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


class SubmissionReadinessAction(BaseModel):
    kind: str = ""
    target: str = ""
    label: str = ""


class SubmissionReadinessArtifact(BaseModel):
    key: str = ""
    label: str = ""
    required: bool = False
    status: str = ""
    detail: str = ""
    blocker: str = ""
    primaryAction: SubmissionReadinessAction = Field(default_factory=SubmissionReadinessAction)


class ChallengeSubmissionReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    readyCount: int = 0
    requiredCount: int = 0
    blockerCount: int = 0
    artifacts: list[SubmissionReadinessArtifact] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    programSummary: dict[str, Any] = Field(default_factory=dict)


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


class ThemeContractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    programId: str = ""
    themeId: str = ""
    themeName: str = ""
    campaignId: str = ""
    status: str = ""
    isolationPolicy: dict[str, Any] = Field(default_factory=dict)
    activatedAt: str = ""
    activatedBy: str = ""
    activationRef: str = ""


class ResearchCampaignActivationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    programId: str = ""
    themeId: str = ""
    campaignId: str = ""
    status: str = ""
    activatedBy: str = ""
    activatedAt: str = ""
    activationRef: str = ""
    scopeHash: str = ""
    activationHash: str = ""


class ResearchScopeEnvelopeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    program: str = ""
    theme: str = ""
    campaign: str = ""
    question: str = ""
    branch: str = ""
    workflow: str = ""
    agentId: str = ""
    mode: str = ""
    scopeHash: str = ""
    artifactLocator: str = ""
    ledgerRoot: str = ""
    cacheKey: str = ""


class PrivateMemoryMigrationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    targetScopeHash: str = ""
    candidateCount: int = 0
    rejectedCount: int = 0
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


class PlatformFlowReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    programId: str = ""
    themeId: str = ""
    campaignId: str = ""
    themeActivated: bool = False
    mode: str = ""
    devContractTestsAllowed: bool = False
    realCampaignAllowed: bool = False
    formalArtifactReadWriteAllowed: bool = False
    blockers: list[str] = Field(default_factory=list)
    scopeHash: str = ""
    privateMemoryMigration: list[dict[str, Any]] = Field(default_factory=list)
    generatedAt: str = ""
