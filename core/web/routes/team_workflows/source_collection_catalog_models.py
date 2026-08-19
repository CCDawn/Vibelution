"""Public contracts for source-collection catalog read routes.

Summary views publish their stable top-level fields. The stage-card and
official-ingestion payloads are bounded read models so unknown storage or
diagnostic fields do not cross the catalog boundary. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceCollectionKnowledgeIngestionIssue(BaseModel):
    """Bounded issue details returned by the formal-knowledge materializer."""

    model_config = ConfigDict(extra="ignore")

    reason: str | None = None
    decision: str | None = None
    confidence: float | None = None
    candidateIds: list[str] | None = None
    errorType: str | None = None


class SourceCollectionMaterializedKnowledgeIngestion(BaseModel):
    """Stable nested contract for source-collection official sync results.

    The materializer may add diagnostic fields over time. Keep those fields
    readable while making the fields used by the catalog and UI explicit.
    """

    model_config = ConfigDict(extra="ignore")

    status: str | None = None
    stewardPackCandidateId: str | None = None
    knowledgeBaseId: str | None = None
    scopedKnowledgeBaseId: str | None = None
    approvedCandidateCount: int | None = None
    approvedCandidateIds: list[str] | None = None
    formalKnowledgeItemCount: int | None = None
    formalKnowledgeItemIds: list[str] | None = None
    writesFormalKnowledge: bool | None = None
    reusedOfficialSync: bool | None = None
    confidence: float | None = None
    sourceReviewStatus: str | None = None
    knowledgeSubmissionStatus: str | None = None
    knowledgeReviewStatus: str | None = None
    createdKnowledgeBaseId: str | None = None
    skippedCount: int | None = None
    failedCount: int | None = None
    skipped: list[SourceCollectionKnowledgeIngestionIssue] | None = None
    failed: list[SourceCollectionKnowledgeIngestionIssue] | None = None


class SourceCollectionStageTaskResponse(BaseModel):
    """Read-model shape for the latest task embedded in a stage card."""

    model_config = ConfigDict(extra="ignore")

    taskId: str | None = None
    stageId: str | None = None
    agentId: str | None = None
    agentRole: str | None = None
    sessionId: str | None = None
    status: str | None = None
    summary: str | None = None
    updatedAt: str | None = None
    resultKeys: list[str] | None = None
    evidenceRefCount: int | None = None
    nextActionCount: int | None = None
    coverageSummary: dict[str, Any] | None = None
    invalidCandidateIds: list[str] | None = None
    invalidRecordIds: list[str] | None = None
    closureSummary: dict[str, Any] | None = None
    taskToolRequired: bool | None = None
    taskChecklist: list[dict[str, Any]] | None = None
    taskToolProgress: dict[str, Any] | None = None
    completionGate: dict[str, Any] | None = None
    materializedSources: dict[str, Any] | None = None
    materializedContentExtraction: dict[str, Any] | None = None
    materializedKnowledgeIngestion: SourceCollectionMaterializedKnowledgeIngestion | None = None


class SourceCollectionStageCardResponse(BaseModel):
    """Read-model shape for one source-collection stage card."""

    model_config = ConfigDict(extra="ignore")

    stageId: str | None = None
    status: str | None = None
    isClosedLoop: bool | None = None
    userStatusLabel: str | None = None
    userSummary: str | None = None
    actionReadiness: dict[str, Any] | None = None
    agentTaskStatus: str | None = None
    artifactStatus: str | None = None
    artifactSummary: str | None = None
    currentCoverageSummary: dict[str, Any] | None = None
    counts: dict[str, Any] | None = None
    latestTask: SourceCollectionStageTaskResponse | None = None
    resultKeys: list[str] | None = None
    nextActions: list[str] | None = None
    blockingReasons: list[str] | None = None


class SourceCollectionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    status: str = ""
    run: dict[str, Any] = Field(default_factory=dict)
    runStatus: dict[str, Any] = Field(default_factory=dict)
    searchPlan: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    stageCards: list[SourceCollectionStageCardResponse] = Field(default_factory=list)
    stageCardSummary: dict[str, Any] = Field(default_factory=dict)
    phaseCloseGate: dict[str, Any] = Field(default_factory=dict)
    latestTasks: dict[str, SourceCollectionStageTaskResponse] = Field(default_factory=dict)
    stageRound: dict[str, Any] = Field(default_factory=dict)
    activeWorkRun: dict[str, Any] = Field(default_factory=dict)
    storageArtifacts: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
