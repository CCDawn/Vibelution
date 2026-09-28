"""Public contracts for leftover session side routes.

Child-create returns a large parent/child pair; tool-approvals and review
candidates are still evolving. Only identity fields are required. Extras must
pass through. Routes must use response_model_exclude_unset=True so missing
optional fields stay absent instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionChildCreateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    childSessionId: str = ""
    parentSessionId: str = ""
    status: str = ""


class SessionToolApprovalItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestId: str = ""
    sessionId: str = ""


class SessionChatReviewCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidateId: str = ""
    sessionId: str = ""


class SessionMessageCurationPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str = ""


class SessionMessageCurationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str = ""
    messageId: str = ""
    action: str = ""
    status: str = ""
    candidateId: str = ""
    caseId: str = ""
    modelId: str = ""
    datasetName: str = ""
    summary: str = ""


class SessionMessageCurationStateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str = ""
    captureEnabled: bool = False
    items: list[dict[str, Any]] = []
    countsByModel: list[dict[str, Any]] = []
