"""HTTP surface for the Agent-scoped personal affairs domain."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.agent_plugins.personal_affairs.service import (
    PersonalAffairsError,
    PersonalAffairsNotFoundError,
)
from core.web.services.personal_affairs_service import (
    get_personal_affairs_service,
)

router = APIRouter(tags=["personal-affairs"])


def _raise_affairs_error(exc: Exception) -> None:
    from core.web.services.agent_directory_service import AgentUnavailableError

    if isinstance(exc, AgentUnavailableError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PersonalAffairsNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PersonalAffairsError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


class PersonalAffairAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["todo", "schedule", "goal"] = "todo"
    title: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=600)
    dueAt: str = Field(default="", max_length=40)
    sourceTurnId: str = Field(default="", max_length=200)


class PersonalAffairDueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dueAt: str = Field(max_length=40)


@router.get("/agents/{agent_id}/plugins/personal-affairs/affairs")
def personal_affairs_list(
    agent_id: str,
    kind: str = "",
    status: str = "",
) -> dict:
    try:
        return get_personal_affairs_service().list_items(
            agent_id, kind=kind, status=status
        )
    except Exception as exc:
        _raise_affairs_error(exc)
        raise


@router.post("/agents/{agent_id}/plugins/personal-affairs/affairs")
def personal_affairs_add(agent_id: str, payload: PersonalAffairAddRequest) -> dict:
    try:
        item = get_personal_affairs_service().add_item(
            agent_id,
            kind=payload.kind,
            title=payload.title,
            note=payload.note,
            due_at=payload.dueAt,
            source_turn_id=payload.sourceTurnId,
        )
        return {"agentId": str(agent_id).strip(), "item": item}
    except Exception as exc:
        _raise_affairs_error(exc)
        raise


@router.post(
    "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/complete"
)
def personal_affairs_complete(agent_id: str, item_id: str) -> dict:
    try:
        item = get_personal_affairs_service().complete_item(
            agent_id, item_id=item_id
        )
        return {"agentId": str(agent_id).strip(), "item": item}
    except Exception as exc:
        _raise_affairs_error(exc)
        raise


@router.post(
    "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/cancel"
)
def personal_affairs_cancel(agent_id: str, item_id: str) -> dict:
    try:
        item = get_personal_affairs_service().cancel_item(agent_id, item_id=item_id)
        return {"agentId": str(agent_id).strip(), "item": item}
    except Exception as exc:
        _raise_affairs_error(exc)
        raise


@router.post(
    "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/reopen"
)
def personal_affairs_reopen(agent_id: str, item_id: str) -> dict:
    try:
        item = get_personal_affairs_service().reopen_item(agent_id, item_id=item_id)
        return {"agentId": str(agent_id).strip(), "item": item}
    except Exception as exc:
        _raise_affairs_error(exc)
        raise


@router.put(
    "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/due"
)
def personal_affairs_set_due(
    agent_id: str, item_id: str, payload: PersonalAffairDueRequest
) -> dict:
    try:
        item = get_personal_affairs_service().set_due(
            agent_id, item_id=item_id, due_at=payload.dueAt
        )
        return {"agentId": str(agent_id).strip(), "item": item}
    except Exception as exc:
        _raise_affairs_error(exc)
        raise
