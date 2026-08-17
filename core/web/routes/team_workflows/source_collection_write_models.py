"""Public contracts for source-collection write routes.

Search execute payloads still evolve across sync vs background shapes.
Dual-shape endpoints only require identifiers that exist on every
successful shape. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceCollectionRunStartResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run: dict[str, Any] = Field(default_factory=dict)
    searchPlan: dict[str, Any] = Field(default_factory=dict)
    storageArtifacts: dict[str, str] = Field(default_factory=dict)
    researchProjectId: str = ""
    experimentName: str = ""
    assignments: list[dict[str, Any]] = Field(default_factory=list)
    assignmentCount: int = 0
    promptCachePolicy: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)
    nextActions: list[str] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionAgentSessionContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    stageId: str = ""
    agentId: str = ""
    agentRole: str = ""
    sessionId: str = ""
    researchProjectId: str = ""
    experimentName: str = ""
    sessionTitle: str = ""
    sessionAttempt: int = 0
    sessionCreated: bool = False
    retryOfSessionId: str = ""
    chatRoute: str = ""
    contextKey: str = ""
    created: bool = False
    alreadyPresent: bool = False
    message: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionStageSessionTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    stageId: str = ""
    agentId: str = ""
    agentRole: str = ""
    sessionId: str = ""
    researchProjectId: str = ""
    experimentName: str = ""
    sessionTitle: str = ""
    sessionAttempt: int = 0
    sessionCreated: bool = False
    retryOfSessionId: str = ""
    chatRoute: str = ""
    taskId: str = ""
    idempotencyKey: str = ""
    created: bool = False
    alreadyPresent: bool = False
    task: dict[str, Any] = Field(default_factory=dict)
    turn: dict[str, Any] = Field(default_factory=dict)
    writebackContract: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionCandidateSourceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionSourceCandidateImportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    created: bool = False
    candidate: dict[str, Any] = Field(default_factory=dict)
    dataRecordRef: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionSearchExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    status: str = ""
    provider: str = ""
    executedQueryCount: int = 0
    skippedQueryCount: int = 0
    failedQueryCount: int = 0
    resultCount: int = 0
    recordCount: int = 0
    outputCount: int = 0
    importedCount: int = 0
    run: dict[str, Any] = Field(default_factory=dict)
    runStatus: dict[str, Any] = Field(default_factory=dict)
    storageArtifacts: dict[str, str] = Field(default_factory=dict)
    assignments: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    nextActions: list[str] = Field(default_factory=list)


class SourceCollectionStorageOpenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    target: str = ""
    path: str = ""
    openedPath: str = ""
    targetExists: bool = False
    storageArtifacts: dict[str, str] = Field(default_factory=dict)


class SourceCollectionStageWritebackResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    taskId: str = ""
    stageId: str = ""
    agentId: str = ""
    agentRole: str = ""
    task: dict[str, Any] = Field(default_factory=dict)
    writeback: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
