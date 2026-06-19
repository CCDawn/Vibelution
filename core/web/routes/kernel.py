"""Agent Kernel MVP API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.agent_kernel import (
    KernelError,
    KernelNotFoundError,
    KernelValidationError,
    ack_agent_inbox_message,
    get_kernel_event,
    get_kernel_task,
    handle_kernel_event,
    list_agent_inbox,
    list_kernel_tasks,
)


router = APIRouter(tags=["agent-kernel"])


class KernelEventPayload(BaseModel):
    eventId: str = ""
    sender: dict[str, Any] = Field(default_factory=dict)
    senderAgentId: str = ""
    recipients: list[Any] = Field(default_factory=list)
    recipientAgentIds: list[str] = Field(default_factory=list)
    targetAgentIds: list[str] = Field(default_factory=list)
    recipientAgentId: str = ""
    semanticType: str = ""
    semanticPayload: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    idempotencyKey: str = ""
    correlationId: str = ""
    causationId: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class KernelInboxAckPayload(BaseModel):
    consumedBySessionId: str = ""
    consumedByTurnId: str = ""


@router.post("/kernel/events", status_code=status.HTTP_202_ACCEPTED)
def kernel_event_create(payload: KernelEventPayload) -> dict:
    try:
        raw_payload = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return handle_kernel_event(raw_payload)
    except KernelValidationError as exc:
        detail: dict[str, Any] = {"message": str(exc)}
        if exc.event:
            detail["event"] = exc.event
        raise HTTPException(status_code=422, detail=detail) from exc
    except KernelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/kernel/events/{event_id}")
def kernel_event_detail(event_id: str) -> dict:
    try:
        return get_kernel_event(event_id)
    except KernelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/kernel/tasks")
def kernel_task_list(status: str = "", limit: int = Query(default=50, ge=1, le=300)) -> dict:
    return list_kernel_tasks(status=status, limit=limit)


@router.get("/kernel/tasks/{task_id}")
def kernel_task_detail(task_id: str) -> dict:
    try:
        return get_kernel_task(task_id)
    except KernelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/inbox")
def kernel_agent_inbox(agent_id: str, status: str = "pending", limit: int = Query(default=20, ge=1, le=100)) -> dict:
    try:
        return list_agent_inbox(agent_id, status=status, limit=limit)
    except KernelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/inbox/{event_id}/ack")
def kernel_agent_inbox_ack(agent_id: str, event_id: str, payload: KernelInboxAckPayload) -> dict:
    try:
        return ack_agent_inbox_message(
            agent_id,
            event_id,
            consumed_by_session_id=payload.consumedBySessionId,
            consumed_by_turn_id=payload.consumedByTurnId,
        )
    except KernelValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KernelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
