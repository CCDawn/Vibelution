"""Typed personal-assistant entry; native services own identity and execution."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

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
    renderer: Literal["whale", "xiaoluo"]
    profile: Literal["personal_assistant_v1"]


class AssistantResponse(BaseModel):
    assistant: Assistant | None


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(default="个人助理", min_length=1, max_length=80)


class PreferencesPayload(BaseModel):
    """Partial patch; only known flat preference keys are accepted."""

    model_config = ConfigDict(extra="forbid")
    characterId: Literal["dafeiyu", "xiaoluo"] | None = None
    showStatus: StrictBool | None = None
    showTitles: StrictBool | None = None
    showCompletion: StrictBool | None = None
    idleMessage: str | None = Field(default=None, max_length=48)


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    preferences: PreferencesPayload | None = None


class ModelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelId: str = Field(min_length=1, max_length=200)


class Preferences(BaseModel):
    characterId: Literal["dafeiyu", "xiaoluo"]
    showStatus: StrictBool
    showTitles: StrictBool
    showCompletion: StrictBool
    idleMessage: str = Field(max_length=48)


class ModelChoice(BaseModel):
    modelId: str
    label: str
    providerLabel: str
    isDefault: StrictBool
    providerHealthy: StrictBool
    missingApiKey: StrictBool
    availability: str


class ModelSettings(BaseModel):
    currentModelId: str
    choices: list[ModelChoice]


class Settings(BaseModel):
    displayName: str
    preferences: Preferences
    preferencesConfigured: StrictBool
    model: ModelSettings


class SettingsResponse(BaseModel):
    settings: Settings | None


class ModelResponse(BaseModel):
    model: ModelSettings


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
    turnId: str


class Attention(BaseModel):
    id: str
    kind: Literal["approval", "error"]
    title: str
    sessionId: str


class OverviewPagination(BaseModel):
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=100)
    nextOffset: StrictInt | None
    revision: str


class OverviewResponse(BaseModel):
    generatedAt: str
    counts: Counts
    agents: list[AgentSummary]
    sessions: list[SessionSummary]
    attention: list[Attention]
    pagination: OverviewPagination


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
def overview(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> dict:
    return service.get_platform_overview(offset=offset, limit=limit)


@router.get("/personal-assistant/settings", response_model=SettingsResponse)
def get_settings() -> dict:
    try:
        return service.get_personal_assistant_settings()
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/personal-assistant/settings", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdateRequest) -> dict:
    try:
        return service.update_personal_assistant_settings(
            display_name=payload.displayName,
            preferences=payload.preferences.model_dump(exclude_none=True)
            if payload.preferences
            else None,
        )
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/personal-assistant/settings/model", response_model=ModelResponse
)
def update_model(payload: ModelUpdateRequest) -> dict:
    try:
        return service.update_personal_assistant_model(payload.modelId)
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
