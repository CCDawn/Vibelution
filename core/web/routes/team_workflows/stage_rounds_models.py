"""Public contracts for research stage-round routes.

Start payloads still evolve across create vs continue shapes. Dual-shape
endpoints only require identifiers that exist on every successful shape.
Status views publish their stable top-level fields. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchStageRoundStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    currentStage: str = ""
    phases: list[dict[str, Any]] = Field(default_factory=list)
    activeRounds: list[dict[str, Any]] = Field(default_factory=list)
    latestRound: dict[str, Any] | None = None
    roundCount: int = 0
    storagePath: str = ""
    boundaries: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class ResearchStageRoundStartResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    created: bool = False
