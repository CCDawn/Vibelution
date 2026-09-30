"""Public contracts for session archive/unarchive and the archived listing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionArchiveResponse(BaseModel):
    """Result of a single archive/unarchive command (idempotent)."""

    model_config = ConfigDict(extra="allow")

    sessionId: str
    status: str = ""
    changed: bool = False
    archivedAt: str = ""
    readOnly: bool = False


class SessionArchiveListResponse(BaseModel):
    """Cursor-paginated page of archived session summaries.

    Item shape mirrors ``SessionQueryResponse.items`` (session summaries with
    ``archiveState``) so the frontend can reuse the same row rendering.
    """

    model_config = ConfigDict(extra="allow")

    items: list[dict[str, Any]] = []
    nextCursor: str = ""
    totalEstimate: int = 0
