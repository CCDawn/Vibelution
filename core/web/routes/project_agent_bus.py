"""Project Agent bus API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.web.routes.project_agent_bus_models import (
    ProjectAgentBusEventResponse,
    ProjectAgentBusListResponse,
    ProjectAgentBusMessagePayload,
    ProjectAgentBusRevokePayload,
)
from core.web.services.project_agent_bus_service import (
    ProjectAgentBusError,
    list_project_agent_bus_events,
    revoke_project_agent_bus_message,
    send_project_agent_bus_message,
)


router = APIRouter(tags=["project-agent-bus"])


@router.get(
    "/project-agent-bus",
    response_model=ProjectAgentBusListResponse,
    response_model_exclude_unset=True,
)
def project_agent_bus_list(limit: int = 80) -> dict:
    return list_project_agent_bus_events(limit=limit)


@router.post(
    "/project-agent-bus/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectAgentBusEventResponse,
    response_model_exclude_unset=True,
)
def project_agent_bus_message_create(payload: ProjectAgentBusMessagePayload) -> dict:
    try:
        return send_project_agent_bus_message(
            content=payload.content,
            target_scope=payload.targetScope,
            target_agent_ids=payload.targetAgentIds,
            interrupt_mode=payload.interruptMode,
            wake_target=payload.wakeTarget,
            created_by="user",
            metadata=payload.metadata,
        )
    except ProjectAgentBusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/project-agent-bus/messages/{event_id}/revoke",
    response_model=ProjectAgentBusEventResponse,
    response_model_exclude_unset=True,
)
def project_agent_bus_message_revoke(event_id: str, payload: ProjectAgentBusRevokePayload) -> dict:
    try:
        return revoke_project_agent_bus_message(
            event_id,
            revoked_by="user",
            reason=payload.reason,
            stop_targets=payload.stopTargets,
        )
    except ProjectAgentBusError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
