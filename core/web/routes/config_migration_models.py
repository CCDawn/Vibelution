"""Public contracts for config LLM v2 and provider-merge migration routes.

Preview and apply envelopes still evolve. Only identifiers that exist on
every successful shape are required. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConfigMigrationPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    previewId: str = ""


class ConfigMigrationApplyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    migrationId: str = ""


class ConfigProviderMergePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    previewId: str = ""


class ConfigProviderMergeResultResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    migrationId: str = ""
