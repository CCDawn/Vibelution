"""Public contracts for agent run history, inbox reads, and runtime evidence.

These envelopes still evolve. Keep required fields to identifiers that exist
on every successful shape, and let extras pass through. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentRunHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str


class AgentInboxMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    messageId: str = ""


class AgentRuntimeEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str = ""
