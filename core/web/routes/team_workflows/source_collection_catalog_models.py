"""Public contracts for source-collection catalog read routes.

Summary views publish their stable top-level fields. Nested run, card, and
gate payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceCollectionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
    status: str = ""
    run: dict[str, Any] = Field(default_factory=dict)
    runStatus: dict[str, Any] = Field(default_factory=dict)
    searchPlan: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    stageCards: list[dict[str, Any]] = Field(default_factory=list)
    stageCardSummary: dict[str, Any] = Field(default_factory=dict)
    phaseCloseGate: dict[str, Any] = Field(default_factory=dict)
    latestTasks: dict[str, Any] = Field(default_factory=dict)
    stageRound: dict[str, Any] = Field(default_factory=dict)
    activeWorkRun: dict[str, Any] = Field(default_factory=dict)
    storageArtifacts: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""
