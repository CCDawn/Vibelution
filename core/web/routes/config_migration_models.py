"""Public contracts for config LLM v2 and provider-merge migration routes.

Known wire fields stay explicit for OpenAPI and typed clients. Forward-compatible
extras still pass through, and routes use ``response_model_exclude_unset=True``
so optional apply-only fields are not injected into rollback responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConfigMigrationProviderPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providerId: str = ""
    label: str = ""
    serviceClass: str = ""
    vendor: str = ""
    driver: str = ""
    baseUrl: str = ""
    credentialState: str = ""
    modelRefs: list[str] = Field(default_factory=list)


class ConfigMigrationReferenceImpactResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    liveReferenceCount: int = 0
    historicalReferenceCount: int = 0


class ConfigMigrationPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    previewId: str = ""
    baseHash: str = ""
    status: str = ""
    providers: list[ConfigMigrationProviderPreviewResponse] = Field(default_factory=list)
    modelRefMap: dict[str, str] = Field(default_factory=dict)
    referenceImpact: ConfigMigrationReferenceImpactResponse = Field(
        default_factory=ConfigMigrationReferenceImpactResponse
    )
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class ConfigMigrationApplyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    migrationId: str = ""
    status: str = ""
    hash: str = ""
    modelAliasUsage: dict[str, Any] = Field(default_factory=dict)
    updatedReferenceCount: int | None = None


class ConfigProviderMergePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    previewId: str = ""
    status: str = ""
    baseHash: str = ""
    canonicalProviderId: str = ""
    duplicateProviderIds: list[str] = Field(default_factory=list)
    modelRefMap: dict[str, str] = Field(default_factory=dict)
    modelsToAdd: list[dict[str, Any]] = Field(default_factory=list)
    liveReferences: list[dict[str, Any]] = Field(default_factory=list)
    historicalReferences: list[dict[str, Any]] = Field(default_factory=list)
    liveReferenceCount: int = 0
    historicalReferenceCount: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    requiredProbeModelRef: str = ""


class ConfigProviderMergeResultResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    migrationId: str = ""
    status: str = ""
    hash: str = ""
    updatedReferenceCount: int | None = None
