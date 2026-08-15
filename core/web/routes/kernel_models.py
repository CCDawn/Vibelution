"""Public contracts for Agent Kernel JSON routes.

Known identity and loop envelope fields stay explicit for OpenAPI. Nested
event, task, execution, outcome, inbox, and timeline payloads still evolve,
so extras pass through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KernelEventPayload(BaseModel):
    eventId: str = ""
    sender: dict[str, Any] = Field(default_factory=dict)
    senderAgentId: str = ""
    recipients: list[Any] = Field(default_factory=list)
    recipientAgentIds: list[str] = Field(default_factory=list)
    targetAgentIds: list[str] = Field(default_factory=list)
    recipientAgentId: str = ""
    semanticType: str = ""
    semanticPayload: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    idempotencyKey: str = ""
    correlationId: str = ""
    causationId: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    wakeTarget: bool | None = None
    traceOnly: bool | None = None
    deliveryPolicy: dict[str, Any] = Field(default_factory=dict)


class KernelInboxAckPayload(BaseModel):
    consumedBySessionId: str = ""
    consumedByTurnId: str = ""


class KernelAgentMessageAdapterPayload(BaseModel):
    source: str = "manual_api"
    sender: dict[str, Any] = Field(default_factory=dict)
    recipientAgentIds: list[str] = Field(default_factory=list)
    content: str = ""
    correlationId: str = ""
    causationId: str = ""
    wakeTarget: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    sourceId: str = ""
    idempotencyKey: str = ""
    eventId: str = ""


class KernelEventLoopResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    reused: bool = False
    event: dict[str, Any] | None = None
    task: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = Field(default_factory=list)


class KernelEventDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str = ""
    status: str = ""


class KernelTaskListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    tasks: list[dict[str, Any]] = Field(default_factory=list)
    limit: int = 0
    status: str = ""
    updatedAt: str = ""


class KernelTaskTimelineResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str = ""
    task: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    deliveries: list[dict[str, Any]] = Field(default_factory=list)
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    runtimeEvidenceRefs: list[dict[str, Any]] = Field(default_factory=list)
    projectionRefs: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    readModel: dict[str, Any] | None = None


class KernelTaskDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str = ""
    status: str = ""


class KernelInboxResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str = ""
    status: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pendingCount: int = 0
    updatedAt: str = ""


class KernelInboxAckResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    acked: bool = False
    agentId: str = ""
    eventId: str = ""
    message: dict[str, Any] | None = None
