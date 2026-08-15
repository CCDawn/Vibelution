"""Public contracts for config draft provider JSON routes.

Workspace-shaped writes reuse ConfigWorkspaceResponse. Suggestion and
route-preview envelopes still evolve, so only identifiers that exist on
every successful shape are required. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConfigProviderIdSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    suggestedProviderId: str = ""


class ConfigProviderRoutePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providerId: str = ""
