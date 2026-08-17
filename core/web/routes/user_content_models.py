"""Public contracts for user markdown-space JSON routes.

Known catalog envelope fields stay explicit for OpenAPI. Page, search, and
import payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MarkdownSpaceImportPreviewPayload(BaseModel):
    sourcePath: str = Field(..., min_length=1, max_length=2000)
    userId: str = Field("default", max_length=160)


class MarkdownSpaceImportPayload(MarkdownSpaceImportPreviewPayload):
    spaceName: str = Field("", max_length=180)
    overwrite: bool = False


class UserContentMarkdownResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    schemaVersion: int = 0
    userId: str = ""
    spaces: list[dict[str, Any]] = Field(default_factory=list)
    space: dict[str, Any] = Field(default_factory=dict)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    page: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    ignoredFiles: list[dict[str, Any]] = Field(default_factory=list)
    query: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    updatedAt: str = ""
