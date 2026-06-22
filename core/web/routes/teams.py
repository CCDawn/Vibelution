"""Team registry API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_service import (
    TeamNotFoundError,
    TeamServiceError,
    archive_team,
    create_team,
    ensure_challenge_cup_research_team_agents,
    get_team,
    get_team_canvas,
    list_ai_search_source_scope_runs,
    list_teams_compact,
    request_system_team_bootstrap,
    save_team_canvas,
    send_team_message,
    start_ai_search_source_scope_run,
    sync_team_chat_room,
    update_team,
)


router = APIRouter(tags=["teams"])


class TeamMemberPayload(BaseModel):
    memberId: str = ""
    agentId: str = ""
    role: str = ""
    purpose: str = ""


class TeamCreatePayload(BaseModel):
    name: str = Field("", max_length=160)
    description: str = Field("", max_length=4000)
    purpose: str = Field("", max_length=1000)
    members: list[TeamMemberPayload] = Field(default_factory=list, max_length=120)


class TeamUpdatePayload(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    purpose: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=32)
    members: list[TeamMemberPayload] | None = Field(default=None, max_length=120)


class TeamCanvasPayload(BaseModel):
    schemaVersion: int = 1
    canvasKind: str = Field("", max_length=80)
    teamId: str = Field("", max_length=128)
    viewport: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=120)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=240)


class TeamMessagePayload(BaseModel):
    content: str = Field("", max_length=12000)
    interruptMode: str = Field("none", max_length=32)
    wakeTarget: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AiSearchRunStartPayload(BaseModel):
    topic: str = Field("", max_length=240)
    sourceLimit: int = Field(8, ge=1, le=12)
    maxResultsPerQuery: int = Field(3, ge=1, le=10)
    includeSignals: bool = False


@router.get("/teams")
def team_list(includeArchived: bool = False) -> dict:
    payload = list_teams_compact(include_archived=includeArchived)
    payload["systemTeamBootstrap"] = request_system_team_bootstrap(reason="team_list")
    return payload


@router.post("/teams", status_code=status.HTTP_201_CREATED)
def team_create(payload: TeamCreatePayload) -> dict:
    try:
        return create_team(
            name=payload.name,
            description=payload.description,
            purpose=payload.purpose,
            members=[item.model_dump() for item in payload.members],
        )
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}")
def team_detail(team_id: str) -> dict:
    try:
        return get_team(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/teams/{team_id}")
def team_update(team_id: str, payload: TeamUpdatePayload) -> dict:
    try:
        members = None if payload.members is None else [item.model_dump() for item in payload.members]
        return update_team(
            team_id,
            name=payload.name,
            description=payload.description,
            purpose=payload.purpose,
            status=payload.status,
            members=members,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/teams/{team_id}")
def team_delete(team_id: str) -> dict:
    try:
        return archive_team(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/canvas")
def team_canvas(team_id: str) -> dict:
    try:
        return get_team_canvas(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/teams/{team_id}/canvas")
def team_canvas_update(team_id: str, payload: TeamCanvasPayload) -> dict:
    try:
        return save_team_canvas(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/ai-search-runs")
def team_ai_search_run_list(team_id: str, limit: int = 6) -> dict:
    try:
        return list_ai_search_source_scope_runs(team_id, limit=limit)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/ai-search-runs", status_code=status.HTTP_201_CREATED)
def team_ai_search_run_start(team_id: str, payload: AiSearchRunStartPayload) -> dict:
    try:
        return start_ai_search_source_scope_run(
            team_id,
            topic=payload.topic,
            source_limit=payload.sourceLimit,
            max_results_per_query=payload.maxResultsPerQuery,
            include_signals=payload.includeSignals,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/messages", status_code=status.HTTP_201_CREATED)
def team_message_create(team_id: str, payload: TeamMessagePayload) -> dict:
    try:
        return send_team_message(
            team_id,
            content=payload.content,
            interrupt_mode=payload.interruptMode,
            wake_target=payload.wakeTarget,
            created_by="user",
            metadata=payload.metadata,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/chat-room/sync")
def team_chat_room_sync(team_id: str) -> dict:
    try:
        return sync_team_chat_room(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/challenge-cup-agents/repair")
def team_challenge_cup_agents_repair(team_id: str) -> dict:
    if team_id != "research-team":
        raise HTTPException(status_code=404, detail="Challenge Cup research Team not found.")
    try:
        return ensure_challenge_cup_research_team_agents(purge_stale=True)
    except TeamServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
