"""Typed personal-assistant dispatch tracking entry (read-only aggregation)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import (
    personal_assistant_dispatches_service as dispatches_service,
)
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentStateConflictError,
)
from core.web.services.personal_assistant_dispatches_service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PersonalAssistantDispatchesError,
    PersonalAssistantMissingError,
)

router = APIRouter(tags=["personal-assistant"])

ReportedTaskStatus = Literal["running", "blocked", "completed", "failed"]
DispatchTaskStatus = Literal[
    "awaiting_result", "running", "blocked", "awaiting_confirmation", "completed", "failed", "cancelled"
]


class DispatchReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messageId: str = ""
    sourceAgentId: str = ""
    sourceAgentName: str = ""
    summary: str = ""
    status: str = Field(default="pending", description="pending | consumed | revoked")
    receivedAt: str = ""
    taskStatus: ReportedTaskStatus | None = None
    evidenceRefs: list[str] = Field(default_factory=list)


class DispatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messageId: str = ""
    threadId: str | None = None
    targetAgentId: str = ""
    targetAgentName: str = ""
    targetSessionId: str = ""
    sourceSessionId: str = ""
    summary: str = ""
    deliveryStatus: str = Field(default="pending", description="pending | consumed | revoked")
    taskStatus: DispatchTaskStatus = "awaiting_result"
    sentAt: str = ""
    receipts: list[DispatchReceipt] = []


class DispatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistantAgentId: str = ""
    dispatches: list[DispatchRecord] = []
    unmatchedReceipts: list[DispatchReceipt] = []
    generatedAt: str = ""


@router.get("/personal-assistant/dispatches", response_model=DispatchesResponse)
def personal_assistant_dispatches(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict:
    try:
        return dispatches_service.list_personal_assistant_dispatches(limit=limit)
    except PersonalAssistantMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PersonalAssistantDispatchesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
