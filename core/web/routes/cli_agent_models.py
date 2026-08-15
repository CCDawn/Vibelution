"""Public contracts for CLI Agent terminal JSON routes.

Known session identity fields stay explicit for OpenAPI. Event streams stay on
StreamingResponse. Transcript and lifecycle payloads still evolve, so extras
pass through. JSON routes must use response_model_exclude_unset=True.
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
    status: str = ""
