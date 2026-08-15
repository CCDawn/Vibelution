"""Public catalog contracts for agent list/detail/create/update/archive/reset.

Agent documents and the config-workspace payload are large and still evolving.
Only `agentId` is required on document envelopes; extras must pass through.
Routes must use response_model_exclude_unset=True so missing optional fields
stay absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str


class AgentConfigWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    generatedAt: str = ""


class AgentAvatarOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    modelId: str = ""


class AgentResetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent: dict | None = None
    resetSummary: dict | None = None
