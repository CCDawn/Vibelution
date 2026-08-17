"""Public contracts for team workflow research-ops routes.

Read-only status views publish stable top-level fields. Mechanism/hypothesis/
transfer write payloads still evolve across dual-shape endpoints, so those
routes keep the catch-all write envelope. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchOpsRouteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaperNoteChunkStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    workflowKind: str = ""
    status: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    missingPlanSources: list[dict[str, Any]] = Field(default_factory=list)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    officialBoundary: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class SourceQualityStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    workflowKind: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    status: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    screeningContract: dict[str, Any] = Field(default_factory=dict)
    officialBoundary: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class OfficialModelEvidenceStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    workflowId: str = ""
    workflowKind: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    status: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    providerCounts: dict[str, Any] = Field(default_factory=dict)
    evidenceKindCounts: dict[str, Any] = Field(default_factory=dict)
    recentEvidence: list[dict[str, Any]] = Field(default_factory=list)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    officialBoundary: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
