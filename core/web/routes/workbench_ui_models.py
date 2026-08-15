"""Public contracts for Workbench UI preference JSON routes.

Known preference envelope fields stay explicit for OpenAPI. Shell chrome and
pane maps still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaneLayoutPatch(BaseModel):
    layoutId: str = Field(min_length=1)
    widths: dict[str, float] = Field(default_factory=dict)


class WorkbenchUiPreferencesPayload(BaseModel):
    paneLayouts: dict[str, dict[str, float]] | None = None
    paneLayout: PaneLayoutPatch | None = None
    shell: dict[str, Any] | None = None


class WorkbenchUiPreferencesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    paneLayouts: dict[str, dict[str, int]] = Field(default_factory=dict)
    shell: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str | None = None


class WorkbenchUiPreferencesSaveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    preferences: WorkbenchUiPreferencesResponse = Field(
        default_factory=WorkbenchUiPreferencesResponse
    )
