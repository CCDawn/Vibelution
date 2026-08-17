"""Git status routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.routes.git_models import (
    GitCommitListResponse,
    GitCommitMessageModelPayload,
    GitCommitMessageModelResponse,
    GitCommitMessagePayload,
    GitCommitMessagePromptPayload,
    GitCommitMessagePromptResponse,
    GitCommitMessageResponse,
    GitCommitPayload,
    GitCommitResponse,
    GitFileDiffResponse,
    GitObjectDetailResponse,
    GitStatusResponse,
)
from core.web.services.git_status_service import (
    commit_git_changes,
    generate_git_commit_message,
    get_git_commits,
    get_git_file_diff,
    get_git_object_detail,
    get_git_status,
    update_git_commit_message_model,
    update_git_commit_message_prompt,
)


router = APIRouter(tags=["git"])


@router.get(
    "/git/status",
    response_model=GitStatusResponse,
    response_model_exclude_unset=True,
)
def git_status(limit: int | None = Query(default=80, ge=0, le=500)) -> dict:
    return get_git_status(limit=limit)


@router.get(
    "/git/commits",
    response_model=GitCommitListResponse,
    response_model_exclude_unset=True,
)
def git_commits(limit: int = Query(default=20, ge=1, le=60)) -> dict:
    return get_git_commits(limit=limit)


@router.get(
    "/git/diff",
    response_model=GitFileDiffResponse,
    response_model_exclude_unset=True,
)
def git_diff(path: str = Query(min_length=1)) -> dict:
    try:
        return get_git_file_diff(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/git/object-detail",
    response_model=GitObjectDetailResponse,
    response_model_exclude_unset=True,
)
def git_object_detail(kind: str = Query(min_length=1), ref: str = Query(default=""), path: str = Query(default="")) -> dict:
    try:
        return get_git_object_detail(kind, ref, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/git/commit-message",
    response_model=GitCommitMessageResponse,
    response_model_exclude_unset=True,
)
def git_commit_message(payload: GitCommitMessagePayload) -> dict:
    try:
        return generate_git_commit_message(payload.paths, model_id=payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/git/commit-message/default-model",
    response_model=GitCommitMessageModelResponse,
    response_model_exclude_unset=True,
)
def git_commit_message_default_model(payload: GitCommitMessageModelPayload) -> dict:
    try:
        return update_git_commit_message_model(payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/git/commit-message/prompt",
    response_model=GitCommitMessagePromptResponse,
    response_model_exclude_unset=True,
)
def git_commit_message_prompt(payload: GitCommitMessagePromptPayload) -> dict:
    try:
        return update_git_commit_message_prompt(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/git/commit",
    response_model=GitCommitResponse,
    response_model_exclude_unset=True,
)
def git_commit(payload: GitCommitPayload) -> dict:
    try:
        return commit_git_changes(payload.paths, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
