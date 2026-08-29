"""Public contracts for runtime JSON routes.

Known shell and lifecycle envelope fields stay explicit for OpenAPI. Nested
summary, workbench, and freshness payloads still evolve, so extras pass
through. JSON routes must use response_model_exclude_unset=True. SSE stays on
StreamingResponse.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BrowserTelemetryPayload(BaseModel):
    phase: str = Field(default="page", min_length=1)
    eventCode: str = Field(..., min_length=1)
    message: str = ""
    level: str = Field(default="info", min_length=1)
    fields: dict[str, Any] = Field(default_factory=dict)


class RuntimeLifecycleCancelPayload(BaseModel):
    commandId: str = ""
    operation: str = ""
    source: str = "web_ui"


class RuntimeShutdownPayload(BaseModel):
    """Optional shutdown request classification.

    A POST without a body stays the Electron graceful-retire contract
    (workbenchBackendRetire.ts): the backend schedules its own exit. A JSON
    body lets the caller declare window-level close versus operator stop.
    """

    model_config = ConfigDict(extra="ignore")

    source: str = ""
    reason: str = ""
    stopManager: bool = False


class RuntimeSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    mode: str = ""
    model: str = ""
    profile: str = ""
    modelSource: str = ""
    profileSource: str = ""
    modelId: str = ""
    modelAgentId: str = ""
    defaultRoute: str = ""
    intakeMode: str = ""
    modeAvailability: dict[str, Any] = Field(default_factory=dict)
    domainAvailability: dict[str, Any] = Field(default_factory=dict)
    agentName: str = ""
    userName: str = ""
    userProfile: dict[str, Any] = Field(default_factory=dict)
    agentStatusLine: str = ""
    sessionTitle: str = ""
    taskSummary: str = ""
    currentPhase: str = ""
    sessionState: str = ""
    sessionStateLine: str = ""
    sessionNeedsResponse: bool = False
    sessionToolName: str = ""
    sessionUpdatedAt: str = ""
    mentalState: dict[str, Any] = Field(default_factory=dict)
    contextUsage: dict[str, Any] = Field(default_factory=dict)
    cacheUsage: dict[str, Any] = Field(default_factory=dict)
    lastLlmUsage: dict[str, Any] | None = None
    lastContextComposition: dict[str, Any] | None = None
    lastCacheComposition: dict[str, Any] | None = None
    contextCompression: dict[str, Any] = Field(default_factory=dict)
    activeTools: list[Any] = Field(default_factory=list)
    changedFilesCount: int = 0
    recentAction: str = ""
    runtimeManager: dict[str, Any] = Field(default_factory=dict)
    workbench: dict[str, Any] = Field(default_factory=dict)
    workRuns: dict[str, Any] = Field(default_factory=dict)
    lifecycleProof: dict[str, Any] = Field(default_factory=dict)


class RuntimeCodeFreshnessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    verdict: str = ""
    backend: dict[str, Any] = Field(default_factory=dict)
    frontend: dict[str, Any] = Field(default_factory=dict)


class RuntimeLifecycleResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    accepted: bool = False
    mode: str = ""
    commandId: str = ""
    message: str = ""
    chatTurns: list[Any] = Field(default_factory=list)
    chatRoomRounds: list[Any] = Field(default_factory=list)
    evolutionRuns: list[Any] = Field(default_factory=list)


class RuntimeLifecycleCancelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    cancelled: bool = False
    status: str = ""
    commandId: str = ""
    operation: str = ""
    message: str = ""
    stateVersion: int | None = None


class RuntimeBrowserTelemetryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    accepted: bool = False
    reason: str = ""
    runtimeSceneId: str = ""
    recordedAt: str = ""
    indexed: bool = False
