"""Public catalog contracts for session list/query/bootstrap/select/update/delete.

Create/select/update still return a full session document; extras pass through
until the S3 detail contract. Do not strip unknown fields. Catalog routes must
use response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionCatalogItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    status: str = ""
    taskSummary: str = ""
    lastActive: str = ""
    updatedAt: str = ""
    currentPhase: str = ""


class SessionActiveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    activeSessionId: str = ""


class SessionQueryFilters(BaseModel):
    model_config = ConfigDict(extra="allow")

    q: str = ""
    agentId: str = ""
    sessionKind: str = ""
    state: str = ""
    sort: str = ""
    limit: int = 50
    cursor: str = ""


class SessionQueryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[SessionCatalogItem] = Field(default_factory=list)
    nextCursor: str = ""
    totalEstimate: int | None = None
    filters: SessionQueryFilters = Field(default_factory=SessionQueryFilters)


class ChatWorkbenchBootstrapResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    activeSessionId: str = ""
    sessionPage: SessionQueryResponse
    agents: list[dict[str, Any]] = Field(default_factory=list)
    conversations: list[dict[str, Any]] = Field(default_factory=list)


class SessionDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    deleted: bool
    deletedSessionId: str = ""
    nextActiveSessionId: str = ""


class SessionBulkDeletePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionIds: list[str] = Field(default_factory=list)


class SessionBulkDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    requestedSessionIds: list[str] = Field(default_factory=list)
    success: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    failed: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    nextActiveSessionId: str = ""
    durationMs: float | None = None
