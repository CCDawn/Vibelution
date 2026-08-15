"""Public contracts for research workbench JSON routes.

Known identity and summary envelope fields stay explicit for OpenAPI. Nested
session, canvas, prompt, and organization payloads still evolve, so extras
pass through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ThemeDiscoverySessionPayload(BaseModel):
    openGoal: str = Field("", max_length=8000)
    constraints: str = Field("", max_length=8000)
    preferences: str = Field("", max_length=8000)
    candidateCount: int = 5


class ResearchPromptUpdatePayload(BaseModel):
    key: str = Field("", max_length=64)
    content: str = Field("", max_length=50000)


class ResearchAgentTemplateUpdatePayload(BaseModel):
    key: str = Field("", max_length=64)
    label: str = Field("", max_length=120)
    promptFilename: str = Field("", max_length=160)
    templateId: str = Field("", max_length=128)
    profileId: str = Field("", max_length=128)
    llmConfigId: str = Field("", max_length=128)
    enabled: bool | None = None


class ResearchDeepSearchPayload(BaseModel):
    evidenceRequests: list[str] = Field(default_factory=list, max_length=8)


class ResearchFlowCanvasPayload(BaseModel):
    schemaVersion: int = 1
    canvasKind: str = Field("", max_length=80)
    viewport: dict = Field(default_factory=dict)
    nodes: list[dict] = Field(default_factory=list, max_length=80)
    edges: list[dict] = Field(default_factory=list, max_length=160)


class ResearchOrganizationPayload(BaseModel):
    schemaVersion: int = 1
    agents: list[dict] = Field(default_factory=list, max_length=200)
    edges: list[dict] = Field(default_factory=list, max_length=400)
    zones: list[dict] = Field(default_factory=list, max_length=80)
    proposals: list[dict] = Field(default_factory=list, max_length=200)
    auditEvents: list[dict] = Field(default_factory=list, max_length=600)
    messages: list[dict] = Field(default_factory=list, max_length=300)


class ResearchOrgMessagePayload(BaseModel):
    sourceType: str = Field("", max_length=32)
    sourceAgentId: str = Field("", max_length=128)
    sourceSessionId: str = Field("", max_length=128)
    sourceRoomId: str = Field("", max_length=128)
    sourceRoundId: str = Field("", max_length=128)
    targetAgentId: str = Field("", max_length=128)
    targetAgentIds: list[str] = Field(default_factory=list, max_length=80)
    deliveryMode: str = Field("private", max_length=32)
    zoneId: str = Field("", max_length=128)
    messageType: str = Field("notice", max_length=32)
    intent: str = Field("", max_length=128)
    content: str = Field("", max_length=12000)
    summary: str = Field("", max_length=1000)
    threadId: str = Field("", max_length=128)
    wakeTarget: bool = True
    mailboxOnly: bool = False
    humanOverride: bool | None = None
    createdBy: str = Field("", max_length=64)


class ResearchOrgProposalPayload(BaseModel):
    title: str = Field("", max_length=160)
    description: str = Field("", max_length=4000)
    proposedByAgentId: str = Field("", max_length=128)
    recommendedByAgentId: str = Field("", max_length=128)
    riskLevel: str = Field("", max_length=32)
    action: dict | None = None
    actions: list[dict] = Field(default_factory=list, max_length=40)


class ResearchKnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""
    entries: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class ThemeDiscoverySessionListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessions: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class ThemeDiscoverySessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    candidateThemes: list[dict[str, Any]] = Field(default_factory=list)
    searchRuns: list[dict[str, Any]] = Field(default_factory=list)


class ThemeDiscoverySessionDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    deleted: bool = False
    sessionId: str = ""
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class ResearchPromptsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: str = ""
    prompts: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[dict[str, Any]] = Field(default_factory=list)


class ResearchFlowCanvasResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    canvasKind: str = ""
    path: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class ResearchOrganizationGraphResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    agents: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    proposals: list[dict[str, Any]] = Field(default_factory=list)


class ResearchOrgMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    organization: dict[str, Any] | None = None
    message: dict[str, Any] | None = None


class ResearchOrgProposalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    organization: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
