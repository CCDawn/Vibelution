"""Public contracts for project Agent bus JSON routes.

Known timeline identity fields stay explicit for OpenAPI. Delivery and kernel
payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectAgentBusMessagePayload(BaseModel):
    content: str = ""
    targetScope: str = ""
    targetAgentIds: list[str] = Field(default_factory=list)
    interruptMode: str = "none"
    wakeTarget: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectAgentBusRevokePayload(BaseModel):
    reason: str = ""
    stopTargets: bool = True


class ProjectAgentBusListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    events: list[dict[str, Any]] = Field(default_factory=list)
    activeAgentCount: int = 0
    updatedAt: str = ""


class ProjectAgentBusEventResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str = ""
