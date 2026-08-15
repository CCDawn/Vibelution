"""Public contracts for workspace file tree and preview JSON routes.

Known identity fields stay explicit for OpenAPI. Directory children still
evolve with the preview surface, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FileTreeNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    path: str = ""
    type: str = ""


class FileContentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""
    language: str = ""
    content: str = ""
    truncated: bool = False
