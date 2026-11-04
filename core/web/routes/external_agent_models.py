"""Public contracts for managed external-Agent JSON routes.

Known identity and status envelope fields stay explicit for OpenAPI. Private
lease extras and nested agent/task payloads still evolve, so extras pass
through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StartExternalAgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str = Field(..., min_length=1, max_length=200)
    task: str = Field(..., min_length=1, max_length=64_000)
    permission_profile: str = Field(default="read_only", max_length=40)
    client_request_id: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=160)


class ResolveExternalAgentApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str = Field(..., min_length=1, max_length=40)
    expected_revision: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=500)


class ResolveBoundExternalAgentApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(..., min_length=1, max_length=40)
    expected_revision: str = Field(..., min_length=64, max_length=64)


class CancelExternalAgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(default="", max_length=200)


class ExternalAgentHeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lease_id: str = Field(..., min_length=1, max_length=200)


class RuntimeSourceIdentityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal[1]
    revision: str
    pid: int
    createTime: float
    clean: bool


class ExternalAgentInfoResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    apiProtocolVersion: str = ""
    serverVersion: str = ""
    projectRoot: str = ""
    runtimeSourceRevision: str = ""
    runtimeSourceIdentity: RuntimeSourceIdentityResponse | None = None
    enabled: bool = False


class ExternalAgentConnectionShutdownResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""


class ExternalAgentAgentListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    agents: list[dict[str, Any]] = Field(default_factory=list)


class ExternalAgentTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str = ""
    status: str = ""


class ExternalAgentApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    decision: str = ""


class ExternalAgentApprovalPreviewResponse(BaseModel):
    """ApprovalBinding.preview wire format; keep JSON arguments as lossless text."""

    model_config = ConfigDict(extra="allow")

    taskId: str
    sessionId: str
    agentId: str
    requestId: str
    turnId: str
    callId: str
    toolName: str
    revision: str
    approval: str
    risk: str
    permissionPreset: str
    decisionFingerprint: str
    configRevision: int
    configHash: str
    argumentsJson: str
    executionArgumentsJson: str
