"""Public contracts for research-loop JSON routes.

Known envelope fields stay explicit for OpenAPI. Loop, evidence, proposal, and
status payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchLoopCreatePayload(BaseModel):
    templateId: str = Field("algorithm_model_experiment", max_length=96)
    title: str = Field("", max_length=240)
    researchQuestion: str = Field("", max_length=2000)
    stageRoundId: str = Field("", max_length=128)
    planId: str = Field("", max_length=128)
    targetRef: str = Field("", max_length=500)
    candidateIds: list[str] = Field(default_factory=list, max_length=24)
    inputRefs: list[str] = Field(default_factory=list, max_length=80)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    datasetRefs: list[str] = Field(default_factory=list, max_length=24)
    environmentRefs: list[str] = Field(default_factory=list, max_length=24)
    constraints: str = Field("", max_length=4000)
    createdByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopEvidencePayload(BaseModel):
    evidenceType: str = Field("", max_length=96)
    status: str = Field("needs_review", max_length=64)
    summary: str = Field("", max_length=4000)
    metricName: str = Field("", max_length=500)
    metricValue: str = Field("", max_length=240)
    baselineMetricValue: str = Field("", max_length=240)
    delta: str = Field("", max_length=240)
    artifactRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    datasetRefs: list[str] = Field(default_factory=list, max_length=24)
    environmentRefs: list[str] = Field(default_factory=list, max_length=24)
    logRefs: list[str] = Field(default_factory=list, max_length=24)
    commandPreview: str = Field("", max_length=2000)
    recordedByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopDecisionPayload(BaseModel):
    decision: str = Field("", max_length=96)
    rationale: str = Field("", max_length=4000)
    nextTemplateId: str = Field("", max_length=96)
    nextActions: list[str] = Field(default_factory=list, max_length=24)
    allowedVariableChanges: list[str] = Field(default_factory=list, max_length=24)
    frozenControls: list[str] = Field(default_factory=list, max_length=24)
    decidedByAgent: str = Field("", max_length=160)
    createNextDesignDraft: bool = False
    idempotencyKey: str = Field("", max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopIterationDesignPayload(BaseModel):
    createdByAgent: str = Field("", max_length=160)


class ResearchLoopTemplatesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    defaultTemplateId: str = ""
    templates: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    storeKind: str = ""
    teamId: str = ""
    team: dict[str, Any] = Field(default_factory=dict)
    activeLoopId: str = ""
    activeLoop: dict[str, Any] | None = None
    loops: list[dict[str, Any]] = Field(default_factory=list)
    historicalEmptyLoops: list[dict[str, Any]] = Field(default_factory=list)
    pendingDesignProposals: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    templates: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""
    nextActions: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    researchProjectId: str = ""


class ResearchLoopCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    loop: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence: dict[str, Any] = Field(default_factory=dict)
    loop: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    idempotency: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision: dict[str, Any] = Field(default_factory=dict)
    iterationProposal: dict[str, Any] | None = None
    nextDesignDraft: dict[str, Any] | None = None
    loop: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    idempotentReplay: bool = False
