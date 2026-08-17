"""Public contracts for CLI Agent terminal JSON routes.

Known session identity and live-state fields stay explicit for OpenAPI.
Event streams stay on StreamingResponse. Transcript and lifecycle payloads
still evolve, so extras pass through. JSON routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CliAgentTerminalEnsurePayload(BaseModel):
    agentType: str = ""
    task: str = ""
    cwd: str = ""
    mode: str = "readonly"
    intent: str = "task"
    model: str = ""
    agent: str = ""
    sourceSessionId: str = ""
    sourceMessageId: str = ""
    sourceRunId: str = ""
    cliSessionId: str = ""
    rows: int = Field(default=28, ge=4, le=120)
    cols: int = Field(default=100, ge=20, le=240)
    sendInitialTask: bool = False


class CliAgentTerminalInputPayload(BaseModel):
    data: str = ""


class CliAgentTerminalResizePayload(BaseModel):
    rows: int = Field(default=28, ge=4, le=120)
    cols: int = Field(default=100, ge=20, le=240)


class CliAgentTerminalSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    terminalSessionId: str = ""
    adapterId: str = ""
    agentType: str = ""
    label: str = ""
    sourceSessionId: str = ""
    sourceMessageId: str = ""
    sourceRunId: str = ""
    linkedSourceMessageIds: list[str] = Field(default_factory=list)
    linkedSourceRunIds: list[str] = Field(default_factory=list)
    cliRunId: str = ""
    lockKey: str = ""
    cwd: str = ""
    mode: str = ""
    taskHash: str = ""
    taskPreview: str = ""
    cliSessionId: str = ""
    cliSessionIdSource: str = ""
    sessionDiscoveryStatus: str = ""
    commandPreview: list[str] = Field(default_factory=list)
    resumed: bool = False
    status: str = ""
    alive: bool = False
    transport: str = ""
    rows: int = 0
    cols: int = 0
    transcriptPath: str = ""
    transcriptTail: str = ""
    transcriptTailReplayable: bool = False
    transcriptTailRenderReason: str = ""
    screenText: str = ""
    screenReplay: str = ""
    screenQuality: str = ""
    screenRows: int = 0
    screenCols: int = 0
    screenParserVersion: str = ""
    processStartedAt: str = ""
    processStartedAtMs: int = 0
    userClosed: bool = False
    closedAt: str = ""
    closedTerminalSessionIds: list[str] = Field(default_factory=list)
    closeReason: str = ""
    supersededByTerminalSessionId: str = ""
    semanticStatus: str = ""
    interactionState: str = ""
    canInput: bool = False
    canResume: bool = False
    canStart: bool = False
    resumeAction: str = ""
    displayMode: str = ""
    stateReason: str = ""
    tuiState: str = ""
    createdAt: str = ""
    updatedAt: str = ""
