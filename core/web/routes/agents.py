"""AgentInstance registry API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services import session_service
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    archive_agent_instance,
    get_agent,
    list_agents,
    update_agent_instance,
)
from core.web.services.supervised_agent_service import ensure_supervised_agent_instances


router = APIRouter(tags=["agents"])


class AgentCreatePayload(BaseModel):
    displayName: str = ""
    templateId: str = ""
    profileId: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdatePayload(BaseModel):
    displayName: str | None = None
    profileId: str | None = None
    toolPolicy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@router.get("/agents")
def agent_list(includeArchived: bool = False) -> list[dict]:
    ensure_supervised_agent_instances()
    return list_agents(include_archived=includeArchived)


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def agent_create(payload: AgentCreatePayload) -> dict:
    try:
        profile_id = payload.profileId or payload.templateId or "primary"
        session = session_service.create_chat_session(
            title=payload.displayName,
            agent_profile_id=profile_id,
            created_by="api_agents",
        )
        agent_id = str(session.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        if not agent:
            raise AgentDirectoryError("Agent was not created for the direct session.")
        if payload.metadata:
            agent = update_agent_instance(agent_id, metadata=payload.metadata)
        return agent
    except session_service.SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str) -> dict:
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/agents/{agent_id}")
def agent_update(agent_id: str, payload: AgentUpdatePayload) -> dict:
    try:
        return update_agent_instance(
            agent_id,
            display_name=payload.displayName,
            profile_id=payload.profileId,
            tool_policy=payload.toolPolicy,
            metadata=payload.metadata,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/agents/{agent_id}")
def agent_archive(agent_id: str) -> dict:
    try:
        return archive_agent_instance(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
