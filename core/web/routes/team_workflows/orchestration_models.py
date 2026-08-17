"""Public contracts for team workflow orchestration routes.

Workflow payloads still evolve. Dual-shape endpoints only require
identifiers that exist on every successful shape. Known orchestration
envelope fields stay explicit for OpenAPI. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamWorkflowOrchestrationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    workflowId: str = ""
    teamId: str = ""
    workflowKind: str = ""
    status: str = ""
    ownerAgentId: str = ""
    stateMachine: dict[str, Any] = Field(default_factory=dict)
    routingPolicy: dict[str, Any] = Field(default_factory=dict)
    transferPolicy: dict[str, Any] = Field(default_factory=dict)
    activeWorkflowItems: list[dict[str, Any]] = Field(default_factory=list)
    candidateStore: dict[str, Any] = Field(default_factory=dict)
    transferRecordsPath: str = ""
    storagePath: str = ""
    createdAt: str = ""
    updatedAt: str = ""
