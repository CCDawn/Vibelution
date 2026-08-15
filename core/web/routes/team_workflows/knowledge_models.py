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


class KnowledgeCollectionExtractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runId: str = ""


class KnowledgeCollectionIngestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class KnowledgeCollectionCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


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


class CandidateSourceExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaperNoteDraftResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
