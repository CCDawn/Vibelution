"""Public contracts for Team catalog read routes.

List, detail, canvas, and AI-search run payloads still evolve. Detail is
dual-shape (light vs full). Only identifiers that exist on every successful
shape are required. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeamListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0


class TeamDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""


class TeamCanvasResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""


class TeamAiSearchRunListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
