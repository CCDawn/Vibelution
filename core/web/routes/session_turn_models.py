"""Public turn-command contracts for session messages/stop/guidance/attachments/llm-options.

Edit-resubmit/stop/guidance still return a full session document; extras pass
through until the S3 detail contract. Do not strip unknown fields. Turn routes
must use response_model_exclude_unset=True so missing optional fields stay
absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class SessionTurnCommandResponse(BaseModel):
    """Lightweight accept envelope or a full session document.

    POST /messages returns the accept payload when Prefer: respond-async is set,
    and a full session document otherwise. Both shapes must survive.
    """

    model_config = ConfigDict(extra="allow")

    accepted: bool | None = None
    sessionId: str = ""
    id: str = ""
    turnId: str = ""
    clientSubmissionId: str = ""
    status: str = ""
    acceptedAt: str = ""
    queuedTurnId: str = ""
    queuePosition: int = 0


class SessionAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifactId: str
    filename: str = ""
    url: str = ""
    imageUrl: str = ""
    downloadUrl: str = ""
    contentType: str = ""
    sizeBytes: int = 0
    kind: str = ""
    status: str = ""


class SessionLlmOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str
    agentId: str = ""
    configRevision: int = 0
    currentModelId: str = ""
    currentReasoningEffort: str = ""
    contextWindow: int = 0
    maxContextWindow: int = 0
    model: dict[str, Any] | None = None
    choices: list[dict[str, Any]] = []


class SessionModelParametersPayload(BaseModel):
    """CAS update for the model already bound to the session's Agent."""

    model_config = ConfigDict(extra="forbid")

    expectedAgentId: str = Field(min_length=1, max_length=160)
    expectedModelRef: str = Field(min_length=1, max_length=300)
    expectedConfigRevision: StrictInt = Field(ge=0)
    contextWindow: StrictInt = Field(gt=0)
    reasoningEffort: str = Field(max_length=40)


class SessionBudgetParametersResponse(BaseModel):
    """Per-session budget overrides; null fields fall back to default resolution."""

    revision: int = Field(ge=0)
    maxCallsPerTurn: int | None = None


class SessionBudgetParametersPayload(BaseModel):
    """CAS update for per-session budget overrides.

    ``revision`` must match the current revision (409 otherwise). Omitted or
    null fields clear the override back to defaults.
    """

    model_config = ConfigDict(extra="forbid")

    revision: StrictInt = Field(ge=0)
    maxCallsPerTurn: StrictInt | None = None
