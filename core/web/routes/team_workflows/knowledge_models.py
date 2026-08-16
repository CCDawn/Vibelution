"""Public contracts for team workflow knowledge routes.

Ingest/complete payloads still evolve across sync vs background shapes.
Dual-shape endpoints only require identifiers that exist on every
successful shape. Status and coordination views publish their stable
top-level fields. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeIngestionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    workflowKind: str = ""
    scope: str = ""
    status: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    stages: list[dict[str, Any]] = Field(default_factory=list)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    candidateBreakdown: dict[str, Any] = Field(default_factory=dict)
    candidateGraphSummary: dict[str, Any] = Field(default_factory=dict)
    officialBoundary: dict[str, Any] = Field(default_factory=dict)
    knowledgeBases: list[dict[str, Any]] = Field(default_factory=list)
    storage: dict[str, Any] = Field(default_factory=dict)
    activeWorkRun: dict[str, Any] | None = None
    latestWorkRun: dict[str, Any] | None = None
    updatedAt: str = ""


class KnowledgeIngestionPrecheckResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    precheck: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)
    reusedStewardPack: bool = False
    ingestionFingerprint: str = ""


class KnowledgeCollectionExtractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    status: str = ""
    recordCount: int = 0
    candidateCount: int = 0
    pendingRecordCount: int = 0
    importedCount: int = 0
    skippedCount: int = 0
    failedCount: int = 0
    workflow: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class KnowledgeCollectionIngestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    executionMode: str = ""
    accepted: bool = False
    alreadyRunning: bool = False
    activeWorkRun: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    sourceQuality: dict[str, Any] = Field(default_factory=dict)
    candidateGraph: dict[str, Any] | None = None
    precheck: dict[str, Any] | None = None
    sourceReview: dict[str, Any] | None = None
    knowledgeSubmission: dict[str, Any] | None = None
    knowledgeReview: dict[str, Any] | None = None
    knowledgeStewardActivation: dict[str, Any] | None = None
    reusedCandidateGraph: bool = False
    reusedStewardPack: bool = False
    ingestionFingerprint: str = ""
    knowledgeBase: dict[str, Any] | None = None
    statusSnapshot: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    nextActions: list[str] = Field(default_factory=list)
    workflow: dict[str, Any] = Field(default_factory=dict)


class KnowledgeCollectionCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    executionMode: str = ""
    accepted: bool = False
    alreadyRunning: bool = False
    activeWorkRun: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    nextActions: list[str] = Field(default_factory=list)


class CoordinationStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    workflowKind: str = ""
    scope: str = ""
    status: str = ""
    ownerAgentId: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    queues: dict[str, Any] = Field(default_factory=dict)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    communication: dict[str, Any] = Field(default_factory=dict)
    coordinationPolicy: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class CandidateGraphBuildResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidateGraph: dict[str, Any] = Field(default_factory=dict)
    graph: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)
    reusedCandidateGraph: bool = False
    ingestionFingerprint: str = ""


class CandidateSourceExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate: dict[str, Any] = Field(default_factory=dict)
    sourceExtraction: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)


class PaperNoteDraftResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    task: dict[str, Any] = Field(default_factory=dict)
    modelResponse: dict[str, Any] = Field(default_factory=dict)
    sourceCandidate: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)
