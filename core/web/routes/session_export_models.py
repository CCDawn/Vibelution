"""Public contracts for POST /sessions/{id}/export-html.

Local self-contained HTML export (intentional deviation from ZCode's cloud
share): the route returns one `{filename, html, skippedTurnIds}` document that
the client saves through a Blob download. `html` carries the full document so
no second fetch is needed; `skippedTurnIds` reports requested-but-unknown turn
ids instead of failing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionExportHtmlPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    """Selected turn ids; empty/missing keeps every turn."""
    turnIds: list[str] = Field(default_factory=list)
    """Embed image attachments as base64 data URIs; file attachments stay name+size rows."""
    includeAttachments: bool = True


class SessionExportHtmlResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filename: str = ""
    html: str = ""
    skippedTurnIds: list[str] = Field(default_factory=list)
