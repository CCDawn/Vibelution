"""Public contracts for config catalog read routes.

Public summary and workspace payloads are large and still evolving.
Only `hash` is required on these envelopes; extras must pass through.
Routes must use response_model_exclude_unset=True so missing optional fields
stay absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConfigBootstrapResponse(BaseModel):
    """Required shell initialization fields; diagnostics are fetched separately."""

    model_config = ConfigDict(extra="forbid")

    hash: str
    language: Literal["zh", "en"]
    runtimeProfile: str
    defaultMode: str
    defaultRoute: str
    intakeMode: str
    modeAvailability: dict[str, bool]
    domainAvailability: dict[str, bool]
    modelLibraryCount: int
    modelLabels: dict[str, str]
    modelImageInputSupport: dict[str, bool | None]
    themeBackgroundImagePath: str
    themeBackgroundImageUrl: str
    themeBackgroundReadability: Literal["soft", "standard", "strong"]


class PublicConfigSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    hash: str = ""


class ConfigWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    hash: str = ""
