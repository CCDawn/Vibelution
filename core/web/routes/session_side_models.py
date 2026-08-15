"""Public contracts for leftover session side routes.

Child-create returns a large parent/child pair; tool-approvals and review
candidates are still evolving. Only identity fields are required. Extras must
pass through. Routes must use response_model_exclude_unset=True so missing
optional fields stay absent instead of being filled with empty defaults.
"""

from __future__ import annotations

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
