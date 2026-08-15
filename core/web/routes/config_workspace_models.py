"""Public contracts for config catalog read routes.

Public summary and workspace payloads are large and still evolving.
Only `hash` is required on these envelopes; extras must pass through.
Routes must use response_model_exclude_unset=True so missing optional fields
stay absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PublicConfigSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    hash: str = ""


class ConfigWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    hash: str = ""
