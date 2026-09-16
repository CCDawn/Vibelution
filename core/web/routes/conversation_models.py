"""Public contracts for the unified conversation index JSON route.

Known identity fields stay explicit for OpenAPI. Direct-agent and group-room
payloads still diverge, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConversationIndexItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    conversationId: str = ""
    type: str = ""
    title: str = ""
    status: str = ""
    updatedAt: str = ""


class ConversationQueryFilters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    q: str = ""
    agentId: str = ""
    teamId: str = ""
    type: str = ""
    sort: str = "updatedAt_desc"
    limit: int = 100
    cursor: str = ""


class ConversationQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[ConversationIndexItem] = []
    nextCursor: str = ""
    totalEstimate: int = 0
    filters: ConversationQueryFilters = ConversationQueryFilters()
