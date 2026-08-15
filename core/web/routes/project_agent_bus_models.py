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
    messageType: str = ""
    targetScope: str = ""
    targetAgentIds: list[str] = Field(default_factory=list)
    targetAgentCodes: list[str] = Field(default_factory=list)
    targetAgentNames: list[str] = Field(default_factory=list)
    mentionedTokens: list[str] = Field(default_factory=list)
    unresolvedMentions: list[str] = Field(default_factory=list)
    content: str = ""
    summary: str = ""
    status: str = ""
    revokedAt: str = ""
    revokedBy: str = ""
    revokeReason: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    kernel: dict[str, Any] = Field(default_factory=dict)
    deliveries: list[dict[str, Any]] = Field(default_factory=list)
    interruptions: list[dict[str, Any]] = Field(default_factory=list)
    revocations: list[dict[str, Any]] = Field(default_factory=list)
