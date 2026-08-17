"""Public contracts for remaining agent support JSON routes.

These envelopes still evolve. Keep required fields to identifiers that exist
on every successful shape, and let extras pass through. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentProjectMemoryUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    proposalId: str = ""


class AgentToolPolicyConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str = ""


class AgentToolPolicyConfigurationListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class AgentMessageCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str = ""


class AgentChatRoomMembershipResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class PromptTemplateWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    promptTemplateId: str = ""
