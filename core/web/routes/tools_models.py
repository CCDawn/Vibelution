"""Public contracts for tool-registry JSON routes.

Known identity, count, and test envelope fields stay explicit for OpenAPI.
Nested tool items, model selectors, and compatibility payloads still evolve,
so extras pass through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeneratedToolPayload(BaseModel):
    name: str = ""
    description: str = ""
    argsSchema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    responseTemplate: str = ""


class GeneratedToolEnabledPayload(BaseModel):
    enabled: bool


class GeneratedToolBulkEnabledPayload(BaseModel):
    toolIds: list[str] = Field(default_factory=list)
    enabled: bool


class ToolBulkDeletePayload(BaseModel):
    toolIds: list[str] = Field(default_factory=list)


class ToolTestPayload(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    agentScope: str = ""
    agentId: str = ""


class Image2DefaultModelPayload(BaseModel):
    modelRef: str = ""


class ToolRegistryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    counts: dict[str, Any] | None = None
    agentScopes: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)


class ToolWebSearchHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    toolId: str = ""
    available: bool = False


class ToolImage2ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    toolId: str = ""
    defaultModelRef: str = ""
    selectedModel: dict[str, Any] | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)


class ToolGeneratedItemResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    validated: bool = False
    enabled: bool = False
    status: str = ""


class ToolBulkActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str = ""
    successCount: int = 0
    skippedCount: int = 0
    failedCount: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)


class ToolDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    deleted: bool = False
    toolId: str = ""
    summary: str = ""


class ToolTestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    toolId: str = ""
    status: str = ""
    called: bool = False
    callable: bool = False
    message: str = ""
    resultPreview: str = ""
    argsUsed: dict[str, Any] | None = None
    testPolicy: dict[str, Any] | None = None
    agentCompatibility: dict[str, Any] | None = None
    agentScope: dict[str, Any] | None = None
    agent: dict[str, Any] | None = None
    timeout: dict[str, Any] | None = None
