"""Typed personal-assistant entry; native services own identity and execution."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from core.web.services import personal_assistant_service as service
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentStateConflictError,
)

router = APIRouter(tags=["personal-assistant"])


class Assistant(BaseModel):
    agentId: str
    displayName: str
    directSessionId: str
    status: Literal["active"]
    setupStatus: Literal["ready", "session_missing", "setup_required"]
    renderer: Literal["whale"]
    profile: Literal["personal_assistant_v1"]


class AssistantResponse(BaseModel):
    assistant: Assistant | None


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(default="个人助理", min_length=1, max_length=80)


class Counts(BaseModel):
    agents: StrictInt = Field(ge=0)
    sessions: StrictInt = Field(ge=0)
    running: StrictInt = Field(ge=0)
    waiting: StrictInt = Field(ge=0)
    failed: StrictInt = Field(ge=0)


class AgentSummary(BaseModel):
    id: str
    displayName: str
    status: str


class SessionSummary(BaseModel):
    id: str
    agentId: str
    title: str
    status: str
    currentPhase: str


class Attention(BaseModel):
    id: str
    kind: Literal["approval", "error"]
    title: str
    sessionId: str


class OverviewResponse(BaseModel):
    generatedAt: str
    counts: Counts
    agents: list[AgentSummary]
    sessions: list[SessionSummary]
    attention: list[Attention]


@router.get("/personal-assistant", response_model=AssistantResponse)
def get_assistant() -> dict:
    try:
        return service.get_personal_assistant()
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/personal-assistant", response_model=AssistantResponse)
def create_assistant(payload: CreateRequest) -> dict:
    try:
        return service.create_personal_assistant(payload.displayName)
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/personal-assistant/overview", response_model=OverviewResponse)
def overview() -> dict:
    return service.get_platform_overview()
