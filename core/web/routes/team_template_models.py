"""Public contracts for team template JSON routes.

Known catalog identifiers stay explicit for OpenAPI. Role, canvas, and created
team payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamTemplateInstantiatePayload(BaseModel):
    name: str = Field("", max_length=160)


class TeamTemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    templates: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class TeamTemplateDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    templateId: str = ""
    name: str = ""
    description: str = ""
    purpose: str = ""
    defaultTeamName: str = ""
    safetyLevel: str = ""
    memberIdPrefix: str = ""
    agentMetadata: dict[str, Any] = Field(default_factory=dict)
    chatRoom: dict[str, Any] = Field(default_factory=dict)
    canvas: dict[str, Any] = Field(default_factory=dict)
    roles: list[dict[str, Any]] = Field(default_factory=list)


class TeamTemplateInstantiateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    template: dict[str, Any] = Field(default_factory=dict)
    team: dict[str, Any] = Field(default_factory=dict)
    createdAgents: list[dict[str, Any]] = Field(default_factory=list)
    linkedChatRoom: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
