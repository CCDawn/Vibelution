"""Typed HTTP contracts for Agent perception control and runtime projections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PerceptionMode = Literal["off", "manual", "auto"]
PerceptionTrigger = Literal["task", "update", "background"]
PerceptionSource = Literal["personal", "team", "knowledge", "projects"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentPerceptionTriggers(_StrictModel):
    task: bool = False
    update: bool = False
    background: bool = False


class AgentPerceptionPersonalSource(_StrictModel):
    mode: PerceptionMode = "off"
    triggers: AgentPerceptionTriggers = Field(default_factory=AgentPerceptionTriggers)


class AgentPerceptionTeamSource(AgentPerceptionPersonalSource):
    teamIds: list[str] = Field(default_factory=list)


class AgentPerceptionKnowledgeSource(AgentPerceptionPersonalSource):
    scope: Literal["selected", "all_authorized"] = "selected"
    knowledgeBaseIds: list[str] = Field(default_factory=list)
    excludedKnowledgeBaseIds: list[str] = Field(default_factory=list)


class AgentPerceptionBackground(_StrictModel):
    enabled: bool = False
    intervalMinutes: int = 60
    dailyMaxRuns: int = 4
    maxCallsPerRun: int = 8
    maxInputTokensPerRun: int = 16_000
    maxConcurrent: int = 1
    maxResultChars: int = 12_000
    topics: list[str] = Field(default_factory=list)


class AgentPerceptionNotifications(_StrictModel):
    mode: Literal["important", "all", "quiet"] = "important"


class AgentPerceptionSources(_StrictModel):
    personal: AgentPerceptionPersonalSource = Field(default_factory=AgentPerceptionPersonalSource)
    team: AgentPerceptionTeamSource = Field(default_factory=AgentPerceptionTeamSource)
    knowledge: AgentPerceptionKnowledgeSource = Field(default_factory=AgentPerceptionKnowledgeSource)
    projects: AgentPerceptionPersonalSource = Field(default_factory=AgentPerceptionPersonalSource)


class AgentPerceptionPolicy(_StrictModel):
    schemaVersion: Literal[1] = 1
    enabled: bool = False
    sources: AgentPerceptionSources = Field(default_factory=AgentPerceptionSources)
    background: AgentPerceptionBackground = Field(default_factory=AgentPerceptionBackground)
    notifications: AgentPerceptionNotifications = Field(default_factory=AgentPerceptionNotifications)


class AgentPerceptionUpdatePayload(_StrictModel):
    policy: AgentPerceptionPolicy
    expectedAgentUpdatedAt: str = Field(min_length=1, max_length=128)


class AgentPerceptionScope(_StrictModel):
    kind: Literal["selected", "all_authorized", "personal", "project_index"]
    ids: list[str] | None = None
    excludedIds: list[str] | None = None


class AgentPerceptionDecision(_StrictModel):
    enforced: bool
    allowed: bool | None
    reason: str
    source: PerceptionSource
    trigger: PerceptionTrigger
    mode: PerceptionMode | None
    scope: AgentPerceptionScope | None = None


class AgentPerceptionScopeOption(_StrictModel):
    id: str
    label: str
    detail: str = ""


class AgentPerceptionAvailableScopes(_StrictModel):
    teams: list[AgentPerceptionScopeOption] = Field(default_factory=list)
    knowledgeBases: list[AgentPerceptionScopeOption] = Field(default_factory=list)


class AgentPerceptionConfigurationResponse(_StrictModel):
    schemaVersion: Literal[1] = 1
    agentId: str
    agentUpdatedAt: str
    configurationRevision: int = 0
    configured: bool
    policy: AgentPerceptionPolicy
    sourceDecisions: list[AgentPerceptionDecision]
    policyFingerprint: str
    availableScopes: AgentPerceptionAvailableScopes


class AgentPerceptionRunProjection(_StrictModel):
    runId: str
    topicId: str = ""
    status: str
    sessionId: str = ""
    turnId: str = ""
    startedAt: str = ""
    finishedAt: str | None = None
    toolCallsUsed: int = 0
    sources: list[PerceptionSource] = Field(default_factory=list)
    readCount: int = 0
    resultCount: int = 0
    sourceReadCallsUsed: int = 0
    inputTokensUsed: int = 0
    outputCharsUsed: int = 0


class AgentPerceptionDailyBudget(_StrictModel):
    date: str
    used: int
    limit: int
    remaining: int


class AgentPerceptionNotification(_StrictModel):
    notificationId: str
    source: PerceptionSource | None = None
    knowledgeBaseId: str
    knowledgeItemId: str
    revision: str
    contentHash: str
    observedAt: str
    sessionId: str = ""
    turnId: str = ""
    delivered: bool


class AgentPerceptionNotificationsRuntime(_StrictModel):
    unreadCount: int
    totalCount: int
    suppressedCount: int = 0
    items: list[AgentPerceptionNotification] = Field(default_factory=list)


class AgentPerceptionKnowledgeScan(_StrictModel):
    basesScanned: int
    cursorCount: int
    pendingCount: int


class AgentPerceptionActualSource(_StrictModel):
    source: PerceptionSource
    selectedCount: int
    readableCount: int
    mode: PerceptionMode = "off"
    triggers: AgentPerceptionTriggers = Field(default_factory=AgentPerceptionTriggers)
    requiresUserRequest: bool = False


class AgentPerceptionActivity(_StrictModel):
    trigger: PerceptionTrigger
    sources: list[PerceptionSource] = Field(default_factory=list)
    readCount: int
    resultCount: int
    completedAt: str
    sessionId: str = ""
    turnId: str = ""
    runId: str = ""


class AgentPerceptionRuntimeCaps(_StrictModel):
    maxCallsPerRun: int
    maxInputTokensPerRun: int
    maxResultChars: int
    maxConcurrent: int


class AgentPerceptionRuntimeResponse(_StrictModel):
    schemaVersion: Literal[1] = 1
    agentId: str
    enabled: bool
    status: Literal[
        "disabled", "scheduled", "running", "stopping", "completed", "failed", "interrupted", "degraded"
    ]
    nextRunAt: str
    activeRun: AgentPerceptionRunProjection | None = None
    lastRun: AgentPerceptionRunProjection | None = None
    dailyBudget: AgentPerceptionDailyBudget
    notifications: AgentPerceptionNotificationsRuntime
    knowledgeScan: AgentPerceptionKnowledgeScan
    readableSources: list[AgentPerceptionActualSource] = Field(default_factory=list)
    lastActivity: AgentPerceptionActivity | None = None
    caps: AgentPerceptionRuntimeCaps
    cancelAvailable: bool
    updatedAt: str


class AgentPerceptionCancelResponse(_StrictModel):
    agentId: str
    runId: str
    status: str
    sessionId: str = ""
    turnId: str = ""
    stopRequested: bool
    cancelled: bool
    reason: str = ""


class AgentPerceptionCancelPayload(_StrictModel):
    runId: str = Field(default="", max_length=128)
