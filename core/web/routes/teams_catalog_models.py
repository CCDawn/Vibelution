"""Public contracts for Team catalog read routes.

List, canvas, and AI-search run payloads publish stable envelopes. Team detail
splits light first-paint and full hydration shapes. Write routes return the
full shape. Routes must use response_model_exclude_unset=True so missing
optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teams: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
    storage: dict[str, Any] = Field(default_factory=dict)
    systemTeamBootstrap: dict[str, Any] = Field(default_factory=dict)


class TeamDetailLightResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
    name: str = ""
    description: str = ""
    purpose: str = ""
    status: str = ""
    teamKind: str = ""
    teamCategory: str = ""
    teamSource: str = ""
    teamTemplateId: str = ""
    sourceScopePath: str = ""
    members: list[dict[str, Any]] = Field(default_factory=list)
    memberCount: int = 0
    linkedChatRoomId: str = ""
    linkedChatRoom: dict[str, Any] | None = None
    canvasPath: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    canvas: dict[str, Any] = Field(default_factory=dict)


class TeamDetailFullResponse(TeamDetailLightResponse):
    sourceScope: dict[str, Any] = Field(default_factory=dict)
    conversation: dict[str, Any] = Field(default_factory=dict)


class TeamCanvasResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    canvasKind: str = ""
    teamId: str = ""
    updatedAt: str = ""
    path: str = ""
    viewport: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class TeamAiSearchRunListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runs: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
