"""Public contracts for log preview and runtime-scene JSON routes.

Known identity and preview envelope fields stay explicit for OpenAPI. Nested
tree, diagnostics, and scene package payloads still evolve, so extras pass
through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LogClearPayload(BaseModel):
    root: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)


class LogDeletePayload(BaseModel):
    root: str = Field(..., min_length=1)
    paths: list[str] = Field(default_factory=list)


class RuntimeSceneDeletePayload(BaseModel):
    sceneIds: list[str] = Field(default_factory=list)


class LogRootItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    path: str = ""
    exists: bool = False
    summary: dict[str, Any] | None = None


class LogTreeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class LogContentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    rootId: str = ""
    rootPath: str = ""
    relativePath: str = ""
    path: str = ""
    language: str = ""
    content: str = ""
    truncated: bool = False
    diagnostics: dict[str, Any] | None = None


class LogDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    rootId: str = ""
    rootPath: str = ""
    deletedPaths: list[str] = Field(default_factory=list)
    missingPaths: list[str] = Field(default_factory=list)
    deletedCount: int = 0


class RuntimeSceneListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    runtimeSceneId: str = ""
    directoryName: str = ""
    displayName: str = ""
    packageIndex: dict[str, Any] | None = None
    status: str = ""
    eventCount: int = 0
    rawLogCount: int = 0
    eventLogCount: int = 0
    warningCount: int = 0
    errorCount: int = 0


class RuntimeSceneDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runtimeSceneId: str = ""
    directoryName: str = ""
    displayName: str = ""
    packageIndex: dict[str, Any] | None = None
    status: str = ""
    frontend: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    lifecycle: list[dict[str, Any]] = Field(default_factory=list)
    rawFiles: list[dict[str, Any]] = Field(default_factory=list)
    eventLogs: list[dict[str, Any]] = Field(default_factory=list)
    packageSummary: dict[str, Any] | None = None


class RuntimeSceneDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestedCount: int = 0
    deletedCount: int = 0
    missingCount: int = 0
    deletedSceneIds: list[str] = Field(default_factory=list)
    missingSceneIds: list[str] = Field(default_factory=list)
    summary: str = ""
