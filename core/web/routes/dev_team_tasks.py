"""Development-team shared task board routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team.dev_task_board import (
    DevTaskStaleRevision,
    create_dev_task,
    dev_task_changes,
    list_dev_tasks,
    mutate_dev_task,
)
from core.web.services.team_service import TeamNotFoundError, TeamServiceError


class DevTaskView(BaseModel):
    id: str
    revision: int
    subject: str
    description: str = ""
    status: str
    ownerMemberId: str = ""
    ownerName: str = ""
    ownerRole: str = ""
    blockedBy: list[str] = Field(default_factory=list)
    writeScopes: list[str] = Field(default_factory=list)
    reviewNote: str = ""
    ready: bool = False
    writeScopeWarnings: list[str] = Field(default_factory=list)
    workspacePath: str = ""
    workspaceBranch: str = ""
    updatedAt: str = ""


class DevTaskListResponse(BaseModel):
    schemaVersion: int
    teamId: str
    tasks: list[DevTaskView] = Field(default_factory=list)
    updatedAt: str = ""


class DevTaskCreatePayload(BaseModel):
    actorMemberId: str = Field(min_length=1, max_length=96)
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    writeScopes: list[str] = Field(default_factory=list, max_length=8)
    blockedBy: list[str] = Field(default_factory=list, max_length=20)
    ownerMemberId: str = Field(default="", max_length=96)


class DevTaskChangeView(BaseModel):
    path: str
    status: str


class DevTaskChangesResponse(BaseModel):
    available: bool = False
    workspace: bool = False
    truncated: int = 0
    changes: list[DevTaskChangeView] = Field(default_factory=list)


class DevTaskMutatePayload(BaseModel):
    actorMemberId: str = Field(min_length=1, max_length=96)
    action: str = Field(min_length=1, max_length=32)
    expectedRevision: int = Field(ge=1)
    ownerMemberId: str = Field(default="", max_length=96)
    subject: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    writeScopes: list[str] | None = Field(default=None, max_length=8)
    blockedBy: list[str] | None = Field(default=None, max_length=20)
    reviewNote: str = Field(default="", max_length=500)


def register_dev_team_task_routes(router: APIRouter) -> None:
    @router.get(
        "/teams/{team_id}/dev-tasks",
        response_model=DevTaskListResponse,
    )
    def dev_task_list(team_id: str) -> dict:
        try:
            return list_dev_tasks(team_id)
        except TeamNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TeamServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/teams/{team_id}/dev-tasks",
        status_code=status.HTTP_201_CREATED,
        response_model=DevTaskListResponse,
    )
    def dev_task_create(team_id: str, payload: DevTaskCreatePayload) -> dict:
        try:
            return create_dev_task(
                team_id,
                actor_member_id=payload.actorMemberId,
                subject=payload.subject,
                description=payload.description,
                write_scopes=payload.writeScopes,
                blocked_by=payload.blockedBy,
                owner_member_id=payload.ownerMemberId,
            )
        except TeamNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TeamServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get(
        "/teams/{team_id}/dev-tasks/{task_id}/changes",
        response_model=DevTaskChangesResponse,
    )
    def dev_task_change_list(team_id: str, task_id: str) -> dict:
        try:
            return dev_task_changes(team_id, task_id)
        except TeamNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TeamServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/teams/{team_id}/dev-tasks/{task_id}",
        response_model=DevTaskListResponse,
    )
    def dev_task_mutate(team_id: str, task_id: str, payload: DevTaskMutatePayload) -> dict:
        try:
            return mutate_dev_task(
                team_id,
                task_id,
                actor_member_id=payload.actorMemberId,
                action=payload.action,
                expected_revision=payload.expectedRevision,
                owner_member_id=payload.ownerMemberId,
                subject=payload.subject,
                description=payload.description,
                write_scopes=payload.writeScopes,
                blocked_by=payload.blockedBy,
                review_note=payload.reviewNote,
            )
        except DevTaskStaleRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TeamNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TeamServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
