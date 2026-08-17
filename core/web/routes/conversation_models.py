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
