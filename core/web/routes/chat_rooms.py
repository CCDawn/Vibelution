"""Chat room routes for multi-session agent discussion."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from core.web.services.chat_room_service import (
    ChatRoomBusyError,
    ChatRoomNotFoundError,
    ChatRoomValidationError,
    create_chat_room,
    delete_chat_room,
    get_chat_room_detail,
    list_chat_room_modes,
    list_chat_room_purposes,
    list_chat_rooms,
    start_chat_room_round,
    stop_chat_room_round,
    stream_chat_room_events,
    update_chat_room,
)


router = APIRouter(tags=["chat-rooms"])


class ChatRoomCreatePayload(BaseModel):
    title: str = ""
    participantSessionIds: list[str] = Field(default_factory=list)
    agentIds: list[str] = Field(default_factory=list)
    mode: str = ""
    purpose: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class ChatRoomRoundPayload(BaseModel):
    topic: str = ""
    mode: str = ""
    purpose: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class ChatRoomUpdatePayload(BaseModel):
    title: str | None = None
    participantSessionIds: list[str] | None = None
    mode: str | None = None
    purpose: str | None = None
    config: dict[str, Any] | None = None


@router.get("/chat-rooms/modes")
def chat_room_modes() -> list[dict]:
    return list_chat_room_modes()


@router.get("/chat-rooms/purposes")
def chat_room_purposes() -> list[dict]:
    return list_chat_room_purposes()


@router.get("/chat-rooms")
def chat_room_list() -> list[dict]:
    return list_chat_rooms()


@router.post("/chat-rooms", status_code=status.HTTP_201_CREATED)
def chat_room_create(payload: ChatRoomCreatePayload) -> dict:
    try:
        return create_chat_room(
            title=payload.title,
            participant_session_ids=payload.participantSessionIds,
            participant_agent_ids=payload.agentIds,
            mode=payload.mode,
            purpose=payload.purpose,
            config=payload.config,
        )
    except ChatRoomValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chat-rooms/{room_id}")
def chat_room_detail(room_id: str) -> dict:
    detail = get_chat_room_detail(room_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Chat room not found")
    return detail


@router.get("/chat-rooms/{room_id}/events")
def chat_room_events(room_id: str) -> StreamingResponse:
    detail = get_chat_room_detail(room_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Chat room not found")
    return StreamingResponse(
        stream_chat_room_events(room_id, initial_detail=detail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.patch("/chat-rooms/{room_id}")
def chat_room_update(room_id: str, payload: ChatRoomUpdatePayload) -> dict:
    try:
        return update_chat_room(
            room_id,
            title=payload.title,
            participant_session_ids=payload.participantSessionIds,
            mode=payload.mode,
            purpose=payload.purpose,
            config=payload.config,
        )
    except ChatRoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatRoomValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/chat-rooms/{room_id}")
def chat_room_delete(room_id: str) -> dict:
    try:
        return delete_chat_room(room_id)
    except ChatRoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/chat-rooms/{room_id}/rounds", status_code=status.HTTP_202_ACCEPTED)
def chat_room_start_round(room_id: str, payload: ChatRoomRoundPayload) -> dict:
    try:
        return start_chat_room_round(
            room_id,
            payload.topic,
            mode=payload.mode,
            purpose=payload.purpose,
            config=payload.config,
            background=True,
        )
    except ChatRoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatRoomValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/chat-rooms/{room_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def chat_room_stop_round(room_id: str) -> dict:
    try:
        return stop_chat_room_round(room_id)
    except ChatRoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
