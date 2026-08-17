"""Public contracts for Team write JSON routes.

Create/update/archive/sync reuse the catalog detail envelope. Canvas writes
reuse the catalog canvas envelope. The remaining write responses publish their
stable top-level fields while allowing additive fields during contract
evolution. Routes use ``response_model_exclude_unset=True`` so absent optional
fields stay absent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamAiSearchRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runId: str = ""
    teamId: str = ""
    title: str = ""
    topic: str = ""
    status: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    sourceScope: dict[str, Any] = Field(default_factory=dict)
    queryPlan: dict[str, Any] = Field(default_factory=dict)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)


class TeamMessageResponse(BaseModel):
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
    createdBy: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    kernel: dict[str, Any] = Field(default_factory=dict)
    deliveries: list[dict[str, Any]] = Field(default_factory=list)
    interruptions: list[dict[str, Any]] = Field(default_factory=list)


class TeamRepairResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    created: bool = False
    memberCount: int = 0
    agentCount: int = 0
    directSessionCount: int = 0
    purgedAgentIds: list[str] = Field(default_factory=list)
    purgeResults: list[dict[str, Any]] = Field(default_factory=list)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    team: dict[str, Any] = Field(default_factory=dict)
