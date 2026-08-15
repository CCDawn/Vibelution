"""Public contracts for Agent Center workbench writes.

These envelopes still evolve. Keep required fields to identifiers that exist
on every successful shape, and let extras pass through. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentAvatarUploadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""


class AgentToolGovernanceRequestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestId: str = ""


class AgentInboxConsumeAllResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str = ""


class AgentModeMembershipResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0


class AgentPurgeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str = ""
