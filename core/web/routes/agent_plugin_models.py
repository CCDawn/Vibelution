"""Typed HTTP contracts for trusted Agent plugins."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentPluginBindingResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    pluginId: str
    enabled: bool
    configVersion: int
    bindingRevision: int


class AgentPluginCatalogEntryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    pluginId: str
    displayName: str
    description: str = ""
    version: str
    trustedFirstParty: bool = True
    toolBundleId: str = ""
    promptPackId: str = ""
    toolNames: list[str] = Field(default_factory=list)


class AgentPluginEntryResponse(AgentPluginCatalogEntryResponse):
    binding: AgentPluginBindingResponse | None = None


class AgentPluginListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    plugins: list[AgentPluginEntryResponse] = Field(default_factory=list)


class VirtualHumanCompanionResponse(BaseModel):
    """Desktop companion-lobby projection over Agent Directory + plugin state."""

    model_config = ConfigDict(extra="allow")

    agentId: str
    agentCode: str
    displayName: str
    directSessionId: str
    avatarImageUrl: str = ""
    personaProfile: dict[str, Any] = Field(default_factory=dict)
    status: str
    snapshot: dict[str, Any]


class AgentPluginBindingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    expectedVersion: int = Field(ge=0)
    config: dict[str, Any] = Field(default_factory=dict)
