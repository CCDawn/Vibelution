"""Public contracts for claim-level research evidence JSON routes.

Known identity, summary, and boundary envelope fields stay explicit for OpenAPI.
Nested evidence, coverage, and question-tree payloads still evolve, so extras
pass through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimEvidencePayload(BaseModel):
    claimId: str
    candidateId: str
    sourceId: str
    sourceRevision: str
    locator: dict[str, Any]
    quote: str
    evidenceKind: Literal["primary_result", "review_summary", "metadata", "counter_evidence"]
    reasoningRole: Literal["fact", "inference", "analogy", "hypothesis"]
    supportLevel: Literal["supports", "contradicts", "insufficient", "unverified"]
    extractionMethod: Literal["paperqa2", "manual", "model"]
    extractorAgentId: str
    modelRef: str = ""


class ClaimEvidenceReviewPayload(BaseModel):
    decision: Literal["accepted", "rejected"]
    reviewedBy: str
    note: str = ""


class LegacyEvidenceProjectionPayload(BaseModel):
    candidateId: str
    legacyEntries: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class SourceRevisionPayload(BaseModel):
    sourceId: str
    currentSourceRevision: str


class ResearchQuestionTreePayload(BaseModel):
    researchQuestion: str
    createdByAgent: str
    customPerspectives: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class ClaimEvidenceItemResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    team: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    boundaries: dict[str, Any] | None = None


class ClaimEvidenceListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    team: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
    boundaries: dict[str, Any] | None = None


class ClaimEvidenceCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    candidateId: str = ""
    summary: dict[str, Any] | None = None
    evidenceGatePassed: bool = False
    counterEvidencePresent: bool = False
    formalKnowledgeWriteAllowed: bool = False
    boundaries: dict[str, Any] | None = None


class ClaimEvidenceReconcileResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    team: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    boundaries: dict[str, Any] | None = None


class ResearchQuestionTreeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    team: dict[str, Any] | None = None
    questionTree: dict[str, Any] | None = None
    boundaries: dict[str, Any] | None = None


class ResearchQuestionTreeListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    team: dict[str, Any] | None = None
    questionTrees: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
    boundaries: dict[str, Any] | None = None
