"""Public contracts for Computer Use JSON routes.

Known public session fields stay explicit for OpenAPI. Screenshot bytes stay on
FileResponse. Nested steps still evolve, so extras pass through. JSON routes
must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComputerUseTaskPayload(BaseModel):
    task: str = ""
    targetUrl: str = ""
    allowedDomains: str | list[str] = Field(default_factory=list)
    actions: str | list[Any] | dict[str, Any] = Field(default_factory=list)
    maxSteps: int = 20
    requireConfirmation: bool = True
    mode: str = "browser"
    timeoutSeconds: int = 180


class ComputerUseConfirmPayload(BaseModel):
    confirmation: str = "approved"


class ComputerUseCancelPayload(BaseModel):
    reason: str = "cancelled_by_user"


class ComputerUseSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str = ""
    status: str = ""
    summary: str = ""
    screenshotUrl: str = ""
    needsConfirmation: bool = False
    error: str = ""
    mode: str = ""
    targetUrl: str = ""
    allowedDomains: list[str] = Field(default_factory=list)
    actionCount: int = 0
    requestedActions: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: str = ""
    updatedAt: str = ""
    durationMs: int = 0
