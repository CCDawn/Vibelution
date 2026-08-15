"""Public turn-command contracts for session messages/stop/guidance/attachments/llm-options.

Edit-resubmit/stop/guidance still return a full session document; extras pass
through until the S3 detail contract. Do not strip unknown fields. Turn routes
must use response_model_exclude_unset=True so missing optional fields stay
absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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
    currentModelId: str = ""
    currentReasoningEffort: str = ""
    model: dict[str, Any] | None = None
