"""Typed finance preference projection and explicit user commands."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_preferences_service as service

router = APIRouter(tags=["financial-preferences"])


class Preference(BaseModel):
    id: str
    text: str
    createdAt: str


class Preferences(BaseModel):
    agentId: str
    memoryEnabled: bool
    items: list[Preference]
    limit: int


class SavePreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    clientRequestId: str = Field(min_length=36, max_length=36)


class RemovedPreference(BaseModel):
    id: str
    removed: bool


class WorkspaceStock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=24)
    ticker: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=60)
    market: str = Field(min_length=1, max_length=30)


class WorkspaceWatch(WorkspaceStock):
    tags: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=500)


class ResearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["financial", "events", "risk", "comprehensive"]
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"]
    period: str = Field(default="", max_length=100)
    instructions: str = Field(default="", max_length=1000)
    isDefault: bool = False


class ManualPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    stock: WorkspaceStock
    quantity: float = Field(gt=0, le=1e12, allow_inf_nan=False)
    costPrice: float = Field(gt=0, le=1e8, allow_inf_nan=False)
    currency: Literal["CNY", "HKD", "USD"]
    note: str = Field(default="", max_length=500)


class ReviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=500)


class WorkspaceSections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selectedStock: WorkspaceStock | None = None
    watchlist: list[WorkspaceWatch] = Field(default_factory=list, max_length=50)
    profiles: list[ResearchProfile] = Field(default_factory=list, max_length=20)
    manualPositions: list[ManualPosition] = Field(default_factory=list, max_length=50)
    reviewCases: list[ReviewCase] = Field(default_factory=list, max_length=100)


class WorkspaceSettings(WorkspaceSections):
    schemaVersion: Literal[1]
    agentId: str
    revision: int
    updatedAt: str


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=0)
    patch: WorkspaceSections


def _call(callback):
    try:
        return callback()
    except service.FinancialPreferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/financial-preferences/{agent_id}", response_model=Preferences)
def preferences_list(agent_id: str) -> dict:
    return _call(lambda: service.list_preferences(agent_id))


@router.post("/financial-preferences/{agent_id}", response_model=Preference)
def preferences_save(agent_id: str, payload: SavePreference) -> dict:
    return _call(
        lambda: service.save_preference(agent_id, payload.text, payload.clientRequestId)
    )


@router.delete(
    "/financial-preferences/{agent_id}/{preference_id}",
    response_model=RemovedPreference,
)
def preferences_remove(agent_id: str, preference_id: str) -> dict:
    return _call(lambda: service.remove_preference(agent_id, preference_id))


@router.get("/financial-preferences/{agent_id}/workspace", response_model=WorkspaceSettings)
def workspace_settings_get(agent_id: str) -> dict:
    return _call(lambda: service.get_workspace_settings(agent_id))


@router.patch("/financial-preferences/{agent_id}/workspace", response_model=WorkspaceSettings)
def workspace_settings_update(agent_id: str, payload: WorkspaceUpdate) -> dict:
    return _call(lambda: service.update_workspace_settings(agent_id, payload.expectedRevision, payload.patch.model_dump(exclude_unset=True)))
