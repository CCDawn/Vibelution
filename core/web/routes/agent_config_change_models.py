"""Public contracts for agent config-changes, drafts, and model promotion.

These envelopes still evolve. Keep required fields to identifiers that exist
on every successful shape, and let extras pass through. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentConfigChangesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str


class AgentConfigDraftResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    draftId: str


class AgentConfigDraftDiscardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    draftId: str
    status: str = ""


class AgentModelPromotionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    modelRef: str = ""
    agent: dict | None = None
