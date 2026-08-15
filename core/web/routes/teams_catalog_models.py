"""Public contracts for Team catalog read routes.

List, canvas, and AI-search run payloads publish stable envelopes. Detail is
dual-shape (light vs full). Only identifiers that exist on every successful
shape are required there. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
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


class TeamDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""


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
