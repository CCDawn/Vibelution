"""Public contracts for user markdown-space JSON routes.

Known catalog envelope fields stay explicit for OpenAPI. Page, search, and
import payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

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
    updatedAt: str = ""
