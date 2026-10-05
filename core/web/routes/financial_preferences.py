"""Typed finance preference projection and explicit user commands."""

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
