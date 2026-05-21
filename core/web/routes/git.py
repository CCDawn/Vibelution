"""Git status routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.web.services.git_status_service import (
    commit_git_changes,
    generate_git_commit_message,
    get_git_commits,
    get_git_file_diff,
    get_git_status,
)


router = APIRouter(tags=["git"])


class GitCommitMessagePayload(BaseModel):
    paths: list[str] = Field(default_factory=list)
    profile_id: str = Field(default="", alias="profileId")


class GitCommitPayload(BaseModel):
    paths: list[str] = Field(default_factory=list)
    message: str = ""


@router.get("/git/status")
def git_status(limit: int | None = Query(default=80, ge=0, le=500)) -> dict:
    return get_git_status(limit=limit)


@router.get("/git/commits")
def git_commits(limit: int = Query(default=20, ge=1, le=60)) -> dict:
    return get_git_commits(limit=limit)


@router.get("/git/diff")
def git_diff(path: str = Query(min_length=1)) -> dict:
    try:
        return get_git_file_diff(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/git/commit-message")
def git_commit_message(payload: GitCommitMessagePayload) -> dict:
    try:
        return generate_git_commit_message(payload.paths, profile_id=payload.profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/git/commit")
def git_commit(payload: GitCommitPayload) -> dict:
    try:
        return commit_git_changes(payload.paths, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
